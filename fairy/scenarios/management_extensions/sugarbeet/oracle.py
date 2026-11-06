"""Finite-policy search harness using ONLY published scenario tools for decisions.

No model state, maturity flag, soil setting or crop yield is modified by a policy.
Evaluation can inspect engine truth, but the controller sees public observations.
A completed finite grid is not a proof of globally optimal agronomic management.
"""

from __future__ import annotations
from fairy.scenarios.management_extensions.oracle_time import oracle_time_arguments
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from itertools import product
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo
from .contracts import digest, select_candidates


class PolicyInfeasible(Exception):
    """Policy cannot finish within the declared operations/physical constraints."""


@dataclass(frozen=True)
class Policy:
    beet_n_kg_ha: float = 140.0
    wheat_n_kg_ha: float = 180.0
    sm_trigger: float = 0.22
    irrigation_mm: float = 30.0
    beet_sowing_offset_days: int = 0
    beet_harvest_offset_days: int = 14
    review_interval_days: int = 3

    @property
    def candidate_id(self):
        return digest(asdict(self))[:16]


def policy_grid(rotation=False):
    wheat_rates = (150.0, 210.0) if rotation else (180.0,)
    return [
        Policy(n, wn, sm, 30.0, sowing, harvest, 3)
        for n, wn, sm, sowing, harvest in product(
            (100.0, 140.0, 180.0), wheat_rates, (0.20, 0.24), (0, 7), (0, 21)
        )
    ]


class PublicController:
    def __init__(self, scene):
        self.apps = {app.name: app for app in scene.apps}
        self.allowed = {
            name: {t.name for t in app.get_tools()} for name, app in self.apps.items()
        }
        self.trace = []
        self.zone = ZoneInfo(scene.timezone_name)
        self.counter = 0

    def call(
        self,
        app,
        tool,
        *,
        reason="Apply declared policy using public observations",
        allow_error=False,
        **args,
    ):
        if tool not in self.allowed[app]:
            raise RuntimeError(f"Nonpublic tool: {app}.{tool}")
        value = getattr(self.apps[app], tool)(**args)
        failed = isinstance(value, dict) and "error" in value
        self.trace.append(
            dict(
                app=app, tool=tool, arguments=args, reason=reason, expected_error=failed
            )
        )
        if failed and not allow_error:
            raise PolicyInfeasible(f"{app}.{tool}: {value['error']}")
        return value

    def now(self):
        value = self.call("SystemApp", "get_current_time")
        return datetime.fromtimestamp(value["current_timestamp"], self.zone)

    def until(self, day, hour=7):
        target = datetime.combine(day, time(hour), self.zone)
        seconds = (target - self.now()).total_seconds()
        if seconds > 0:
            self.call(
                "SystemApp",
                "advance_time",
                **oracle_time_arguments(seconds),
                reason="Advance native crop AND fallow soil through elapsed time",
            )

    def tomorrow(self):
        self.until(self.now().date() + timedelta(days=1))

    def work_morning(self):
        if self.now().hour >= 17:
            self.tomorrow()

    def machine(self, implement=None):
        s = self.call("Tractor", "get_status")
        if implement is not None and s["attached_implement"] != implement:
            if s["attached_implement"] is not None:
                self.call("Tractor", "detach_implement")
            self.call("Tractor", "attach_implement", implement=implement)
        if s["fuel_tank_l"] < 20:
            stock = self.call("Warehouse", "get_inventory")
            amount = min(100 - s["fuel_tank_l"], stock["fuel_liters"])
            if amount <= 0:
                raise PolicyInfeasible("No fuel remaining")
            self.call("Tractor", "refuel", liters=amount)

    def observe(self):
        field = self.call("ArableField", "get_field_info")
        observations = self.call(
            "ArableField",
            "inspect_blocks",
            start_block=0,
            end_block=len(field["blocks"]) - 1,
        )
        return field, observations["blocks"]

    def sow_cycle(self, info, policy):
        c = info["cycle"]
        day = date.fromisoformat(c["sowing_open"])
        if c["crop"] == "sugarbeet":
            day += timedelta(days=policy.beet_sowing_offset_days)
        self.until(day)
        close = date.fromisoformat(c["sowing_close"])
        for _ in range(40):
            info, blocks = self.observe()
            if self.now().date() > close:
                raise PolicyInfeasible("Sowing window expired")
            if "level" not in info["completed_preparation"]:
                self.machine("grader")
                outcome = self.call("Tractor", "prepare_field", allow_error=True)
                if "error" in outcome:
                    self.tomorrow()
                    continue
            self.machine("seeder")
            ids = [b["block_id"] for b in blocks if not b["planted"]]
            if not ids:
                return self.now().date()
            for i in ids:
                self.work_morning()
                self.machine("seeder")
                s = self.call("Tractor", "get_status")
                need = info["seeds_per_block"] - s["seed_hopper"]
                if need > 0:
                    self.call(
                        "Tractor", "load_seeds", seed_type=info["seed_type"], count=need
                    )
                outcome = self.call(
                    "Tractor",
                    "sow",
                    start_block=i,
                    end_block=i,
                    depth_cm=c["sowing_depth_cm"],
                    allow_error=True,
                )
                if "error" in outcome:
                    break
            else:
                return self.now().date()
            self.tomorrow()
        raise PolicyInfeasible("No feasible sowing after bounded retries")

    def nitrogen(self, dose, info):
        """Dose is pure N/ha; existing tool takes urea product kg per block."""
        self.work_morning()
        self.machine()
        stock = self.call("Warehouse", "get_inventory")
        machine = self.call("Tractor", "get_status")
        need = dose * info["area_ha"] / info["fertilizer_n_fraction"]
        if need > stock["fertilizer_kg"] + machine["fertilizer_spreader_kg"] + 1e-6:
            raise PolicyInfeasible("Policy exceeds remaining fertilizer stock")
        load = max(0, need - machine["fertilizer_spreader_kg"])
        if load:
            self.call("Tractor", "load_fertilizer", kg=load)
        product_per_block = need / len(info["blocks"])
        # A failure is explicitly infeasible rather than silently dropping a dose.
        for start in range(0, len(info["blocks"]), 8):
            self.machine()
            self.call(
                "Tractor",
                "fertilize",
                start_block=start,
                end_block=min(start + 7, len(info["blocks"]) - 1),
                kg_per_block=product_per_block,
            )

    def manage_until_harvest(self, info, sowed, policy):
        c = info["cycle"]
        beet = c["crop"] == "sugarbeet"
        closing = date.fromisoformat(c["harvest_close"])
        nclose = date.fromisoformat(c["nitrogen_close"])
        target = date.fromisoformat(c["harvest_open"])
        if beet:
            target += timedelta(days=policy.beet_harvest_offset_days)
            delivery = self.call("RootDelivery", "get_delivery_info")
            target = max(target, date.fromisoformat(delivery["delivery_open"]))
        stock = self.call("Warehouse", "get_inventory")
        nmax = stock["fertilizer_kg"] * info["fertilizer_n_fraction"] / info["area_ha"]
        target_n = min(
            policy.beet_n_kg_ha if beet else policy.wheat_n_kg_ha,
            c["maximum_n_kg_ha"],
            nmax,
        )
        if beet:
            dates = [sowed, sowed + timedelta(days=30), sowed + timedelta(days=60)]
        else:
            dates = [sowed, date(closing.year, 3, 10), date(closing.year, 4, 5)]
        schedule = list(zip(dates, (0.4, 0.3, 0.3)))
        applied = set()
        while self.now().date() <= closing:
            info, blocks = self.observe()
            today = self.now().date()
            ready = (
                all(b["maturity_date"] for b in blocks) if not beet else today >= target
            )
            if ready and today >= target:
                return
            if info["weather_today"]["rain_mm"] == 0:
                for j, (day, portion) in enumerate(schedule):
                    if j not in applied and today >= day:
                        if today > nclose:
                            raise PolicyInfeasible(
                                "Required N installment missed the no-late-N cutoff"
                            )
                        self.nitrogen(target_n * portion, info)
                        applied.add(j)
            # Do not irrigate frozen conditions, mature wheat, or beet near target harvest.
            stop = target - timedelta(days=c["irrigation_withholding_days"])
            may_water = (not beet or today < stop) and info["weather_today"][
                "air_temperature_proxy_c"
            ] >= 5
            alive = all(
                b["planted"] and b["stage"] not in {"MATURE", "BARE"} for b in blocks
            )
            if (
                may_water
                and alive
                and min(float(b["SM"]) for b in blocks) < policy.sm_trigger
            ):
                account = self.call("OperatingAccounts", "get_accounts")
                amount = min(
                    policy.irrigation_mm,
                    account["shared_water_remaining_m3"] / (info["area_ha"] * 10),
                )
                if amount >= 1:
                    self.call(
                        "Irrigation",
                        "irrigate",
                        start_block=0,
                        end_block=len(blocks) - 1,
                        depth_mm=amount,
                        allow_error=True,
                    )
            nxt = min(today + timedelta(days=policy.review_interval_days), closing)
            if nxt <= today:
                raise PolicyInfeasible("Crop not ready by last harvest date")
            self.until(nxt)
        raise PolicyInfeasible("Harvest deadline expired")

    def harvest_wheat(self, info):
        closing = date.fromisoformat(info["cycle"]["harvest_close"])
        for i in range(len(info["blocks"])):
            while True:
                self.work_morning()
                self.machine("harvester")
                if self.now().date() > closing:
                    raise PolicyInfeasible("Wheat harvest missed deadline")
                result = self.call(
                    "Tractor",
                    "harvest_blocks",
                    start_block=i,
                    end_block=i,
                    allow_error=True,
                )
                if "error" in result:
                    self.tomorrow()
                    continue
                batch = f"{info['cycle']['cycle_id']}:grain:{i}"
                self.call("Tractor", "unload_grain", batch_id=batch)
                self.call(
                    "Warehouse",
                    "dry_grain",
                    batch_id=batch,
                    target_moisture_pct=info["storage_moisture_pct"],
                )
                self.call("Warehouse", "store_grain", batch_id=batch)
                break
        self.call("Tractor", "return_supplies")

    def harvest_beet(self, info):
        closing = date.fromisoformat(info["cycle"]["harvest_close"])
        for i in range(len(info["blocks"])):
            # Harvest one block and clear its truck batch before lifting another.
            while True:
                self.work_morning()
                self.machine("beet_harvester")
                if self.now().date() > closing:
                    raise PolicyInfeasible("Root harvest deadline missed")
                d = self.call("RootDelivery", "get_delivery_info")
                current = self.now().date().isoformat()
                used = d["batch_state"]["daily_gross"].get(current, 0)
                _, blocks = self.observe()
                dry = (
                    float(blocks[i]["TWSO"] or 0) * info["blocks"][i]["area_m2"] / 10000
                )
                net = (
                    dry
                    * d["contract"]["machine_recovery"]
                    / d["contract"]["dry_matter_fraction"]
                )
                gross = net / (1 - d["contract"]["tare_fraction_gross"])
                if gross > d["contract"]["delivery_daily_gross_kg"]:
                    raise PolicyInfeasible(
                        "One management block exceeds daily factory receiving capacity"
                    )
                if used + gross > d["contract"]["delivery_daily_gross_kg"]:
                    self.tomorrow()
                    continue
                lifted = self.call(
                    "Tractor",
                    "harvest_roots",
                    start_block=i,
                    end_block=i,
                    operation_id=f"lift:{info['cycle']['cycle_id']}:{i}",
                    allow_error=True,
                )
                if "error" in lifted:
                    self.tomorrow()
                    continue
                batch_id = lifted["batch_ids"][0]
                break
            while True:
                d = self.call("RootDelivery", "get_delivery_info")
                b = next(
                    b for b in d["batch_state"]["batches"] if b["batch_id"] == batch_id
                )
                left = b["recovered_net_kg"] - b["delivered_net_kg"]
                if left < 1e-7:
                    break
                load = min(
                    left,
                    d["contract"]["truck_gross_capacity_kg"]
                    * (1 - d["contract"]["tare_fraction_gross"]),
                )
                self.counter += 1
                self.call(
                    "RootDelivery",
                    "deliver_roots",
                    batch_id=batch_id,
                    net_kg=load,
                    operation_id=f"trip:{info['cycle']['cycle_id']}:{self.counter}",
                )
        self.call("Tractor", "return_supplies")

    def run(self, policy):
        initial = self.call("ArableField", "get_field_info")
        for index, c in enumerate(initial["cycles"]):
            if index:
                self.until(date.fromisoformat(c["prepare_open"]))
                self.call(
                    "ArableField",
                    "begin_next_cycle",
                    reason="Same field: preserve native water/N and shared stores",
                )
            info = self.call("ArableField", "get_field_info")
            sowed = self.sow_cycle(info, policy)
            self.manage_until_harvest(info, sowed, policy)
            if c["crop"] == "winter_wheat":
                self.harvest_wheat(info)
            else:
                self.harvest_beet(info)
        return self.trace


def execute_candidate(factory, policy, controller_type=PublicController):
    scene = factory()
    scene.setup()
    controller = controller_type(scene)
    result = dict(
        candidate_id=policy.candidate_id,
        policy=asdict(policy),
        input_fingerprint=scene.input_fingerprint(),
        feasible=False,
        execution_status="completed",
    )
    try:
        controller.run(policy)
        evaluation = scene.validate()
        result.update(evaluation.metadata)
        result["feasible"] = bool(evaluation.success)
        result["validation_message"] = evaluation.message
    except PolicyInfeasible as exc:
        result["validation_message"] = str(exc)
    except Exception as exc:
        # Model/API errors are NOT evidence that a candidate is agronomically infeasible.
        result.update(
            execution_status="runtime_error", error=f"{type(exc).__name__}: {exc}"
        )
    result["workflow"] = controller.trace
    return result


def replay_workflow(factory, workflow, selected):
    scene = factory()
    scene.setup()
    controller = PublicController(scene)
    for step in workflow:
        response = controller.call(
            step["app"],
            step["tool"],
            **step["arguments"],
            allow_error=True,
            reason=step["reason"],
        )
        failed = isinstance(response, dict) and "error" in response
        if failed != step.get("expected_error", False):
            raise RuntimeError("Fresh replay changed a public-tool success/failure")
    evaluation = scene.validate()
    if not evaluation.success:
        raise RuntimeError(f"Fresh replay failed: {evaluation.message}")
    for key in (
        "root_yield",
        "wheat_yield",
        "net_operating_margin",
        "water_m3",
        "pure_n_applied_kg",
    ):
        if not math.isclose(
            evaluation.metadata[key], selected[key], rel_tol=1e-10, abs_tol=1e-7
        ):
            raise RuntimeError(f"Fresh replay changed objective or resources: {key}")
    return evaluation.metadata


def search(
    factory, output, *, rotation=False, objective="root_yield", max_candidates=None,
    policies=None, controller_type=PublicController,
):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    policies = list(policies) if policies is not None else policy_grid(rotation)
    declared = [p.candidate_id for p in policies]
    rows = []
    for i, policy in enumerate(policies):
        if max_candidates is not None and i >= max_candidates:
            break
        print(f"candidate {i + 1}/{len(policies)}: {policy.candidate_id}", flush=True)
        result = execute_candidate(factory, policy, controller_type)
        (output / (policy.candidate_id + ".json")).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        rows.append({k: v for k, v in result.items() if k != "workflow"})
        # One runtime incompatibility is a release blocker, not a reason to waste a full grid.
        if result["execution_status"] == "runtime_error":
            break
    summary = select_candidates(rows, declared, objective)
    summary.update(
        declared_policies=[asdict(p) for p in policies],
        information_regime="public_model_telemetry_and_historical_weather",
        objective_definition="rotation_yield = beet net roots, then wheat grain, then margin; wheat floor is mandatory",
        empirical_field_validation=False,
    )
    (output / "search_report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if summary.get("best") is None:
        return summary
    chosen = summary["best"]
    full = json.loads(
        (output / (chosen["candidate_id"] + ".json")).read_text(encoding="utf-8")
    )
    # Candidate logs keep every observation and refusal. The fixed reference
    # only needs state-changing calls and clock advances, then a fresh replay.
    read_tools = {
        "get_current_time",
        "get_status",
        "get_inventory",
        "get_field_info",
        "inspect_blocks",
        "get_delivery_info",
        "get_accounts",
    }
    workflow = [
        step
        for step in full["workflow"]
        if not step["expected_error"] and step["tool"] not in read_tools
    ]
    replay = replay_workflow(factory, workflow, chosen)
    probe = factory()  # Constructor does not run or change data.
    reference = dict(
        schema="fairy.sugarbeet.oracle.v1",
        scenario_id=probe.scenario_id,
        input_fingerprint=chosen["input_fingerprint"],
        fresh_replay_verified=True,
        search_scope=summary["status"],
        global_optimum_proven=False,
        objective=objective,
        selected=chosen,
        replay_metrics=replay,
        workflow=workflow,
    )
    # Partial searches get a clearly named baseline, never an optimum certificate.
    filename = (
        "oracle_reference.json" if summary["complete"] else "best_tested_reference.json"
    )
    (output / filename).write_text(
        json.dumps(reference, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary
