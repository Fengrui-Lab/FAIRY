"""Declared finite management policies using the same public telemetry as agents."""

from dataclasses import dataclass
from datetime import date, timedelta
from itertools import product

from .oracle import Policy, PolicyInfeasible, PublicController


@dataclass(frozen=True)
class YieldPolicy(Policy):
    beet_n_kg_ha: float = 180.0
    beet_harvest_offset_days: int = 21
    water_trigger_fraction: float = 0.65
    zone_water_share: float = 0.5
    response_delay_days: int = 0
    wheat_irrigation_cap_mm: float = 300.0


def yield_policy_grid(variant):
    if variant == "seedling_rescue":
        return [YieldPolicy(response_delay_days=delay, water_trigger_fraction=trigger, irrigation_mm=depth)
                for delay, trigger, depth in product((0, 7, 14), (0.45, 0.65), (20.0, 30.0))]
    if variant == "soil_water_priority":
        return [YieldPolicy(zone_water_share=share, water_trigger_fraction=trigger, irrigation_mm=depth)
                for share, trigger, depth in product((0.25, 0.5, 0.6, 0.65, 0.7, 0.75, 0.85, 0.9, 0.95, 1.0), (0.45, 0.65), (20.0, 30.0))]
    if variant == "shared_resources":
        return [YieldPolicy(wheat_n_kg_ha=wn, beet_n_kg_ha=300 - wn, wheat_irrigation_cap_mm=water)
                for wn, water in product((120.0, 150.0, 180.0, 210.0), (210.0, 240.0, 270.0, 300.0))]
    raise ValueError(f"No yield-management grid: {variant}")


class YieldController(PublicController):
    def run(self, policy):
        initial = self.call("ArableField", "get_field_info")
        self.water_stock_m3 = self.call("OperatingAccounts", "get_accounts")["shared_water_remaining_m3"]
        self.takeover_day = self.now().date()
        self.zoned = len({b["soil_water_reference"]["field_capacity_vwc"] for b in initial["blocks"]}) > 1
        for index, cycle in enumerate(initial["cycles"]):
            if index:
                self.until(date.fromisoformat(cycle["prepare_open"]))
                self.call("ArableField", "begin_next_cycle")
            info, blocks = self.observe()
            if all(b["planted"] for b in blocks):
                sowed = max(date.fromisoformat(b["sowing_date"]) for b in blocks)
            else:
                sowed = self.sow_cycle(info, policy)
            self.manage_until_harvest(info, sowed, policy)
            if cycle["crop"] == "winter_wheat":
                self.harvest_wheat(info)
            else:
                self.harvest_beet(info)
        return self.trace

    def manage_until_harvest(self, info, sowed, policy):
        cycle = info["cycle"]
        beet = cycle["crop"] == "sugarbeet"
        closing = date.fromisoformat(cycle["harvest_close"])
        nclose = date.fromisoformat(cycle["nitrogen_close"])
        target = date.fromisoformat(cycle["harvest_open"])
        if beet:
            target += timedelta(days=policy.beet_harvest_offset_days)
        dates = [sowed, sowed + timedelta(days=30), sowed + timedelta(days=60)] if beet else [
            sowed, date(closing.year, 3, 10), date(closing.year, 4, 5)]
        _, blocks = self.observe()
        n_so_far = sum(b["applied_n_kg_ha"] for b in blocks) / len(blocks)
        stock = self.call("Warehouse", "get_inventory")
        target_n = min(policy.beet_n_kg_ha if beet else policy.wheat_n_kg_ha,
                       cycle["maximum_n_kg_ha"],
                       n_so_far + stock["fertilizer_kg"] * info["fertilizer_n_fraction"] / info["area_ha"])
        while self.now().date() <= closing:
            info, blocks = self.observe()
            today = self.now().date()
            ready = today >= target and (beet or all(b["maturity_date"] for b in blocks))
            if ready:
                return
            due = target_n * sum(portion for day, portion in zip(dates, (0.4, 0.3, 0.3)) if day <= today)
            current_n = sum(b["applied_n_kg_ha"] for b in blocks) / len(blocks)
            if due > current_n + 1e-6 and info["weather_today"]["rain_mm"] == 0:
                if today > nclose:
                    raise PolicyInfeasible("Required N missed the no-late-N cutoff")
                self.nitrogen(due - current_n, info)
                info, blocks = self.observe()
            stop = target - timedelta(days=cycle["irrigation_withholding_days"])
            may_water = (not beet or today < stop) and info["weather_today"]["air_temperature_proxy_c"] >= 5
            may_water &= today >= self.takeover_day + timedelta(days=policy.response_delay_days)
            groups = [(0, len(blocks) - 1, 1.0)]
            if self.zoned:
                middle = len(blocks) // 2
                groups = [(0, middle - 1, policy.zone_water_share), (middle, len(blocks) - 1, 1 - policy.zone_water_share)]
                groups.sort(key=lambda group: min(b["relative_available_water"] for b in blocks[group[0]:group[1] + 1]))
            for start, end, share in groups:
                zone = blocks[start:end + 1]
                alive = all(b["planted"] and b["stage"] not in {"MATURE", "BARE"} for b in zone)
                if not may_water or not alive or min(b["relative_available_water"] for b in zone) >= policy.water_trigger_fraction:
                    continue
                area = sum(info["blocks"][i]["area_m2"] for i in range(start, end + 1)) / 10000
                used = sum(b["irrigation_mm_this_cycle"] for b in zone) / len(zone)
                account = self.call("OperatingAccounts", "get_accounts")
                amount = min(policy.irrigation_mm, account["shared_water_remaining_m3"] / (area * 10))
                if self.zoned:
                    amount = min(amount, self.water_stock_m3 * share / (area * 10) - used)
                if not beet:
                    amount = min(amount, policy.wheat_irrigation_cap_mm - used)
                if amount >= 1:
                    self.call("Irrigation", "irrigate", start_block=start, end_block=end,
                              depth_mm=amount, allow_error=True)
            nxt = min(today + timedelta(days=policy.review_interval_days), closing)
            if nxt <= today:
                raise PolicyInfeasible("Crop not ready by last harvest date")
            self.until(nxt)
        raise PolicyInfeasible("Harvest deadline expired")
