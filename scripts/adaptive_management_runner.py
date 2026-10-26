"""Discover and replay seasonal management from registered observations.

The scene owns crop parameters, disturbances and finite resources. Pure policy
modules propose actions; this compiler owns real tools, elapsed time and receipts.
It never passes private PCSE state to a decision. Frozen weather makes comparisons
between policies reproducible despite different observation schedules.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import json
from math import ceil, isfinite
from pathlib import Path
import re
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.adaptive_weather_forcing import FrozenWeatherCompiler
from scripts.adaptive_irrigation_policy import decide_irrigation
from scripts.adaptive_crop_management_policy import decide_crop_management
from scripts.adaptive_replant_policy import decide_replant_candidate
from scripts.compile_wofost_observed_oracle import ObservedCompiler, TZ, clean, digest, save, stage_rank
from scripts.formal90_calibration_policy import source_timestamp, STAGE_WAIT, CALENDAR_WAIT


GROWTH_MANAGEMENT = {
    "irrigate", "irrigate_range", "irrigate_ridge", "apply_fertigation",
    "apply_fertilizer", "apply_fungicide", "spray_pesticide",
    "apply_herbicide", "apply_pesticide", "apply_pesticide_manual",
    "mechanical_weed_control",
}


def without_fixed_growth_management(source, Workflow):
    """Remove prescriptions before the old compiler can gate or load for them.

    Keep establishment, explicit replant objectives, observation, harvest and
    storage. Base fertilizer remains the scenario's establishment treatment.
    """
    result, removed, planted, last = Workflow(), [], False, None
    items = list(source.dag.items())
    for index, (label, original) in enumerate(items):
        method = (original.tool_name or "").rsplit("__", 1)[-1]
        if method == "plant_seeds":
            planted = True
        remove = method in GROWTH_MANAGEMENT
        remove |= method in {"load_fungicide", "load_pesticide", "refill_pesticide_tank"}
        if planted and method == "load_fertilizer":
            # Staggered sowing may still need establishment fertilizer for an
            # unplanted block. Keep a load if its next consumer is base dressing.
            consumer = next(((s.tool_name or "").rsplit("__", 1)[-1]
                for _, s in items[index + 1:]
                if (s.tool_name or "").rsplit("__", 1)[-1] in
                {"load_fertilizer", "base_fertilize", "apply_fertilizer"}), None)
            remove |= consumer != "base_fertilize"
        if remove:
            removed.append({"label": label, "tool": original.tool_name,
                            "arguments": deepcopy(original.tool_args)})
            continue
        step = deepcopy(original)
        step.depends_on = [last] if last else []
        result.add_node(step)
        last = step.name
    return result, removed


class AdaptiveManagementCompiler(FrozenWeatherCompiler):
    def __init__(self, *args, irrigation_parameters=None, crop_parameters=None,
                 manage_crop=True, scout_interval_days=3, **kwargs):
        self.irrigation_parameters = irrigation_parameters
        self.crop_parameters = {"root_zone_adequate_vwc": .25, **(crop_parameters or {})}
        self.manage_crop = manage_crop
        self.scout_interval_days = scout_interval_days
        self.policy_history = []
        self.crop_history = []
        self.decisions = []
        self._in_management_review = False
        self._last_review_day = None
        self._last_scout_timestamp = None
        self._previous_crop_observation = None
        self._prefer_manual_pesticide = False
        super().__init__(*args, **kwargs)
        if len(self.worlds) != 1:
            raise ValueError("This formal90 runner requires one explicit farm; shared-farm routing needs its own execution adapter")

    def _tool(self, method):
        matches = [name for name in self.tools if name.endswith("__" + method)]
        if len(matches) > 1:
            raise RuntimeError(f"Ambiguous registered capability: {method}: {matches}")
        return matches[0] if matches else None

    def _read(self, label, method, args=None):
        tool = self._tool(method)
        return self.call(label, tool, args or {}) if tool else None

    def advance_until(self, label, target_epoch, manage=True):
        """Reach an absolute deadline; management work consumes the same clock.

        No callbacks run inside a tool: water/resource registration must finish
        before any new decision. Nested charging/effect waits cannot recurse.
        """
        if target_epoch > self.deadline:
            raise RuntimeError("Adaptive wait exceeds original scenario duration")
        result = None
        while self.engine.time_manager.time() < target_epoch:
            if manage and not self._in_management_review:
                self.review_management(label)
            now = self.engine.time_manager.time()
            if now > self.deadline:
                raise RuntimeError("Management work exceeded original scenario duration")
            remaining = target_epoch - now
            if remaining <= 0:
                break
            # A daily checkpoint at 07:00 China time; when an operation crosses
            # it, the next review uses its real completion time, never the past.
            current = datetime.fromtimestamp(now, TZ)
            boundary = current.replace(hour=7, minute=0, second=0, microsecond=0).timestamp()
            if boundary <= now:
                boundary += 86400
            seconds = max(1, int(ceil(min(remaining, boundary - now))))
            if now + seconds > self.deadline:
                raise RuntimeError("Integer-second wait cannot fit the remaining scenario duration")
            result = ObservedCompiler.call(self, label + "_observed_wait",
                                          self.system.name + "__advance_time",
                                          {"seconds": seconds})
        if manage and not self._in_management_review:
            self.review_management(label)
        return result

    def wait(self, label, seconds=86400):
        return self.advance_until(label, self.engine.time_manager.time() + seconds,
                                  manage=not self._in_management_review)

    def battery(self, prefix, required, label):
        """Reserve a prepared device until its caller can start the operation.

        Charging is a resource-preparation wait, not an idle growth interval:
        running a second scouting mission in it can consume the just-charged
        battery. Check the real status again after charging and defer management
        review until the caller finishes using that device.
        """
        for attempt in range(8):
            status = self.call(label + f"_battery_{attempt}", prefix + "__check_status", {})
            if not status.get("charging") and float(status.get("battery_pct", 0)) >= required:
                return
            self.call(label + f"_charge_{attempt}", prefix + "__charge", {}, op="WRITE")
            self.advance_until(label + f"_charge_wait_{attempt}",
                               self.engine.time_manager.time() + 3600, manage=False)
        raise RuntimeError("Registered battery did not reach the required operation reserve")

    def _calendar_wait(self, label, tool, args, op, guard):
        target = source_timestamp(getattr(self._source_steps[label], "time", None))
        if target is None:
            target = self.engine.time_manager.time() + self._wait_seconds(args)
        return self.advance_until(label, target, manage=not self._in_management_review)

    @staticmethod
    def _wait_seconds(args):
        return sum(float(args.get(unit, 0)) * scale for unit, scale in
                   (("days", 86400), ("hours", 3600), ("minutes", 60), ("seconds", 1)))

    def call(self, label, tool, args, *, op="READ", guard=False):
        if tool.endswith("__advance_time") and (label not in self._source_steps or
                not (STAGE_WAIT.fullmatch(label) or CALENDAR_WAIT.fullmatch(label))):
            return self.wait(label, self._wait_seconds(args))
        before = self.engine.time_manager.time()
        if tool.endswith("__plant_seeds"):
            result = self._plant_with_guard_retry(label, tool, args, op)
        elif tool.endswith("__replant_seeds"):
            result = self._condition_replant_request(label, tool, args, op=op, guard=guard)
        else:
            result = super().call(label, tool, args, op=op, guard=guard)
        after = self.engine.time_manager.time()
        if after > self.deadline:
            raise RuntimeError("Registered operation exceeded original scenario duration")
        if (not self._in_management_review and after > before
                and datetime.fromtimestamp(before, TZ).date() != datetime.fromtimestamp(after, TZ).date()):
            self.review_management(label + "_after_operation")
        return result

    def _condition_replant_request(self, label, tool, args, *, op, guard):
        """Retain adequate observed stand; unresolved candidates keep the API boundary."""
        start, end = int(args["start_ridge"]), int(args["end_ridge"])
        observed = self._read(label + "_fresh_public_stand", "get_ridge_range_state",
                              {"start": start, "end": end})
        requirement = {"source_label": label, "tool_name": tool, "arguments": deepcopy(args)}
        decision = decide_replant_candidate(observed, start=start, end=end,
                                             threshold=.70, source_requirement=requirement)
        # Link only existing registered ground responses; no native/private
        # snapshot is consulted and no extra noisy inspection is invented.
        links = {}
        for record in reversed(self.trace):
            if (record.get("tool_name") or "").rsplit("__", 1)[-1] not in {"inspect_emergence", "inspect_crop_health"}:
                continue
            content = record.get("content") or {}
            content = content.get("data", content)
            for rid in content.get("covered_ridges", []):
                row = content.get("observations", {}).get(str(rid), content.get("observations", {}).get(rid))
                if start <= rid <= end and rid not in links and isinstance(row, dict):
                    links[rid] = {"trace_step": record.get("name"), "source_label": record.get("source_label"),
                                  "time_after": record.get("time_after"), "ridge_id": rid,
                                  "public_stand_fraction": row.get("stand_fraction")}
            if len(links) == end - start + 1:
                break
        self.decisions.append({"kind": "replant_conditioning", "observations": clean(observed),
                               "decision": clean(decision), "existing_public_ground_links": list(links.values())})
        if decision["skip_fixed_replant"]:
            self.changes.append({"kind": "conditional_replant_retains_existing_stand",
                                 "source_step": label, "source_requirement": requirement,
                                 "decision": clean(decision), "economic_benefit_established": False})
            # A real registered read replaces the obsolete fixed prescription
            # in the replay workflow. No replant tool is called or reported done.
            return self._read(label + "_retain_existing_stand", "get_current_time")
        return super().call(label, tool, args, op=op, guard=guard)

    def _seedbed_not_before(self, args):
        """A successful overlapping irrigation needs a full day to be observed."""
        start, end = int(args["start_ridge"]), int(args["end_ridge"])
        return max((float(row.get("finished_at", row["started_at"])) + 86400
            for row in self.policy_history
            if row.get("response", {}).get("status") == "irrigation_started"
            and int(row["tool_args"]["start"]) <= end
            and int(row["tool_args"]["end"]) >= start), default=0.)

    def gate(self, method, args, label, prefix):
        """Use coarse probes for preparation, then the planter for its exact target.

        A probe can include untreated neighbours outside a four-ridge pass.
        Requiring its whole support area to become suitable can repeatedly
        water an already prepared target. The registered planter is authoritative
        and its verified zero-effect refusals drive subsequent retries.
        """
        if method != "plant_seeds":
            return super().gate(method, args, label, prefix)
        self._ensure_target_phase(label, method, args)
        start, end = int(args["start_ridge"]), int(args["end_ridge"])
        sensor = self.sensors.get(self.farm.name)
        if sensor is None:
            raise RuntimeError("No public fixed soil sensor for the planting target")
        weather = self.current_weather(label + "_weather")
        self.ridges(label + "_field", start, end)
        soil = self.call(label + "_soil", sensor.name + "__read_soil_sensors", {})
        probes = [p for p in soil.get("soil_sensors", [])
            if p.get("ridge_end", p.get("ridge_id", -1)) >= start
            and p.get("ridge_start", p.get("ridge_id", self.farm.num_ridges)) <= end]
        if not probes or any(p.get("vwc") is None or p.get("temp_c") is None for p in probes):
            raise RuntimeError("Public planting soil observations unavailable; no hidden-state fallback")
        waters, temperatures = [float(p["vwc"]) for p in probes], [float(p["temp_c"]) for p in probes]
        if not all(isfinite(v) for v in waters + temperatures) or not all(0 <= v <= 1 for v in waters):
            raise RuntimeError("Public planting soil observations must be finite, with VWC in 0..1")
        dry, wet, cold = min(waters) < .20, max(waters) > .35, min(temperatures) < 10
        record = {"kind": "public_seedbed_readiness", "source_step": label,
            "target": {"start": start, "end": end}, "clock": self.engine.time_manager.time(),
            "public_probes": clean(probes), "public_weather": clean(weather),
            "dry": dry, "wet": wet, "cold": cold,
            "readiness_authority": "Registered planter checks its actual target; coarse overlapping probes are not an exact-ridge veto",
            "basis": "Existing soybean bounds VWC 0.20–0.35 and temperature >= 10 C; one bounded preparation pulse may precede the authoritative attempt"}
        self.decisions.append(record)
        if (dry and not wet and not cold and not getattr(self, "_plant_guard_active", False)
                and self._seedbed_not_before(args) <= self.engine.time_manager.time()):
            reserved = self._in_management_review
            self._in_management_review = True
            try:
                record["preparation_water_applied"] = self._seedbed_water(label, args)
            finally:
                self._in_management_review = reserved
        # Even a coarse wet/cold reading may describe neighbours. A refusal
        # from the actual target is handled below with a real managed wait.

    @staticmethod
    def _planting_soil_rejection(message):
        values = re.match(r"^Soil VWC (\d+(?:\.\d+)?) must be within (\d+(?:\.\d+)?)[–-](\d+(?:\.\d+)?) for ", message)
        if values:
            water, minimum, maximum = map(float, values.groups())
            if not all(isfinite(v) for v in (water, minimum, maximum)):
                return None
            return "dry" if water < minimum else "wet" if water > maximum else "rounded_boundary"
        if message.startswith("Soil temperature ") and ("must exceed" in message or "too low" in message):
            return "cold"
        return None

    def _seedbed_water(self, source_label, args):
        """Try a declared 4 mm engineering pulse, not an inferred water deficit."""
        label = f"adaptive_seedbed_{self.counter + 1}"
        irrigation = self._tool("irrigate")
        record = {"kind": "seedbed_preparation", "source_step": source_label,
                  "label": label, "pulse_mm": 4.,
                  "basis": "Bounded engineering pulse after public soil readings or the registered planter reported dry soil; not a calculated root-zone deficit"}
        self.decisions.append(record)
        if irrigation is None:
            record["fallback"] = "No registered irrigation tool; wait for natural soil change"
            return False
        limits = self._read(label + "_limits", "get_management_status"
                            if self._tool("get_management_status") else "get_inventory")
        limits = limits.get("data", limits)
        regime = limits.get("management_regime", limits)
        start, end = int(args["start_ridge"]), int(args["end_ridge"])
        required = 4. * (end-start+1) / self.farm.num_ridges
        quota, used = regime.get("irrigation_quota_mm_total"), regime.get("irrigation_used_mm_total")
        record.update(public_limits=clean(limits), field_equivalent_mm=required)
        if used is None or (quota is not None and float(used)+required > float(quota)+1e-9):
            record["fallback"] = "Insufficient or unavailable public water quota; no water applied"
            return False
        # The existing registered system delivers 5 mm/h plus 5 min setup and
        # publishes a 2 h effect confirmation. Do not start a pulse that cannot
        # even reach that confirmation within the original scene deadline.
        if self.engine.time_manager.time() + 300 + 2880 + 7200 > self.deadline:
            record["fallback"] = "Insufficient time for pulse and effect confirmation"
            return False
        started = self.engine.time_manager.time()
        arguments = {"start": start, "end": end, "hours": .8}
        receipt = self._execute_guarded(label, irrigation, arguments)
        record["receipt"] = clean(receipt)
        if receipt.get("status") != "irrigation_started":
            record["fallback"] = "Registered irrigation did not apply water; wait and reobserve"
            return False
        self.policy_history.append({"started_at": started,
            "finished_at": self.engine.time_manager.time(), "tool_args": arguments,
            "response": clean(receipt), "purpose": "seedbed_guard_repair",
            "source_step": source_label})
        ready = receipt.get("effect_ready_at")
        if ready is None or not isfinite(float(ready)) or float(ready) <= self.engine.time_manager.time():
            raise RuntimeError("Registered seedbed irrigation lacks a future effect confirmation time")
        self.advance_until(label + "_effect_confirmation", float(ready), manage=False)
        # Keep the actual post-delivery public readings as evidence; the next
        # attempt also re-runs the ordinary public planting gate.
        self._read(label + "_confirmed_surface", "read_soil_sensors")
        self._read(label + "_confirmed_root", "read_root_zone_sensors")
        return True

    def _plant_with_guard_retry(self, label, tool, args, op):
        prefix = tool.rsplit("__", 1)[0]
        was_reviewing = self._in_management_review
        prior_guard_active = getattr(self, "_plant_guard_active", False)
        self._plant_guard_active = True
        self._in_management_review = True

        def natural_wait(wait_label, target):
            if target <= self.engine.time_manager.time():
                raise RuntimeError("Planting soil did not become ready within original scenario duration")
            # Long soil/readiness waits still manage already established crops.
            # Only the short resource/action/effect-confirmation window reserves
            # the tractor and freshly prepared target from unrelated work.
            self._in_management_review = was_reviewing
            try:
                self.advance_until(wait_label, target, manage=not was_reviewing)
            finally:
                self._in_management_review = True

        try:
            for attempt in range(181):
                if attempt:
                    self._in_management_review = was_reviewing
                    try:
                        self.gate("plant_seeds", args, label + f"_retry_gate_{attempt}", prefix)
                    finally:
                        self._in_management_review = True
                # Transfers/refuelling are legitimate preparation, completed
                # before the rejected planter's zero-mutation signature.
                self._ensure_seed_payload(label + f"_payload_{attempt}", tool, args)
                status = self.call(label + f"_plant_fuel_{attempt}", prefix + "__get_status", {})
                if float(status.get("fuel_tank_l", 0)) < 20:
                    self.call(label + f"_plant_refuel_{attempt}", prefix + "__refuel",
                              {"liters": 100.}, op="WRITE")
                before = self._harvest_guard_signature(label + f"_plant_guard_before_{attempt}", prefix, args)
                index = len(self.trace)
                result = ObservedCompiler.call(self, label + f"_plant_attempt_{attempt}",
                                               tool, args, op=op, guard=True)
                if not isinstance(result, dict) or not result.get("error"):
                    return result
                message = str(result["error"])
                reason = self._planting_soil_rejection(message)
                window = re.match(r"^Planting window not open .*earliest_date=(\d{4}-\d{2}-\d{2}), today=\d{4}-\d{2}-\d{2}$", message)
                if window is not None:
                    reason = "window_not_open"
                if reason is None:
                    raise RuntimeError(f"{tool}: {result}")
                rejected = self.trace[index]
                after = self._harvest_guard_signature(label + f"_plant_guard_after_{attempt}", prefix, args)
                if before != after or rejected["time_before"] != rejected["time_after"]:
                    raise RuntimeError("Rejected planter changed public state; cannot discard or retry")
                del self.trace[index]
                self.rejected_guards.append({"source_step": label, "attempt": attempt,
                    "rejection": rejected, "public_before": before, "public_after": after,
                    "zero_mutation_verified": True, "soil_rejection": reason})
                save(self.output / "discovery_rejected_guards.json", self.rejected_guards)
                self.changes.append({"kind": "zero_mutation_planting_guard_replanned",
                                     "source_step": label, "reason": message, "attempt": attempt})
                if reason == "window_not_open":
                    opens = datetime.fromisoformat(window.group(1)).replace(tzinfo=TZ).timestamp()
                    natural_wait(label + f"_public_window_wait_{attempt}", opens)
                    continue
                if reason == "dry":
                    recent_ready = self._seedbed_not_before(args)
                    if recent_ready > self.engine.time_manager.time():
                        self.changes.append({"kind": "seedbed_wait_for_prior_daily_water_commit",
                            "source_step": label, "not_before": recent_ready,
                            "basis": "An overlapping successful irrigation needs at least 24 h before a second seedbed pulse; effect_ready is not a promise of higher soil moisture"})
                        natural_wait(label + f"_prior_water_commit_wait_{attempt}",
                                     min(self.deadline, recent_ready))
                        continue
                    if self._seedbed_water(label, args):
                        continue
                now = self.engine.time_manager.time()
                target = min(self.deadline, now+86400)
                if target <= now:
                    raise RuntimeError("Planting soil did not become ready within original scenario duration")
                natural_wait(label + f"_soil_wait_{attempt}", target)
            raise RuntimeError("Public planting guard retry cap exceeded")
        finally:
            self._in_management_review = was_reviewing
            self._plant_guard_active = prior_guard_active

    def _observe_water(self, label):
        clock = self._read(label + "_clock", "get_current_time")
        overview = self._read(label + "_overview", "get_farm_overview")
        rows = self._read(label + "_ridges", "get_ridge_range_state",
                          {"start": 0, "end": int(overview["num_ridges"]) - 1})
        observation = {"clock": clock, "overview": overview, "ridges": rows,
                       "management": self._read(label + "_limits", "get_management_status"
                           if self._tool("get_management_status") else "get_inventory"),
                       "forecast": self._read(label + "_forecast", "get_forecast", {"days": 7}),
                       "root_zone": self._read(label + "_root", "read_root_zone_sensors"),
                       "surface": self._read(label + "_surface", "read_soil_sensors"),
                       "capabilities": {"application_mm_per_hour": 5.,
                           "root_zone_registered": self._tool("read_root_zone_sensors") is not None}}
        sampled = self._read(label + "_sample_time", "get_current_time")
        observation["observed_at"] = {"root_zone": sampled, "surface": sampled}
        return observation

    def _guard_signature(self, label):
        # Public deterministic reads only; noisy sensors would change on read.
        return {"clock": self._read(label + "_clock", "get_current_time"),
                "inventory": self._read(label + "_inventory", "get_inventory"),
                "device": self._read(label + "_device", "get_status"),
                "ridges": self._read(label + "_ridges", "get_ridge_range_state",
                    {"start": 0, "end": self.farm.num_ridges - 1})}

    def _execute_guarded(self, label, tool, args):
        """Keep guard rejection as evidence, but never pretend it applied input."""
        before = self._guard_signature(label + "_before")
        result = self.call(label, tool, args, op="WRITE", guard=True)
        if isinstance(result, dict) and result.get("error"):
            index = next(i for i in range(len(self.trace) - 1, -1, -1)
                         if self.trace[i].get("discovery_only_rejected_guard"))
            entry = self.trace[index]
            after = self._guard_signature(label + "_after")
            if before != after or entry["time_before"] != entry["time_after"]:
                raise RuntimeError("Rejected adaptive action mutated public state")
            del self.trace[index]
            self.rejected_guards.append({"rejection": entry, "public_before": before,
                                         "public_after": after, "zero_mutation_verified": True})
        return result

    def review_management(self, label):
        if self._in_management_review:
            return
        now = self.engine.time_manager.time()
        day = datetime.fromtimestamp(now, TZ).date().isoformat()
        if day == self._last_review_day:
            return
        self._last_review_day = day
        self._in_management_review = True
        try:
            prefix = "adaptive_" + day.replace("-", "")
            obs = self._observe_water(prefix)
            rows = obs["ridges"]["ridges"]
            if not any(r.get("planted") and not r.get("harvested") for r in rows):
                return
            # Each recommendation reads the actual updated quota and fresh probes.
            for attempt in range(3):
                decision = decide_irrigation(obs, history=self.policy_history,
                                             parameters=self.irrigation_parameters)
                self.decisions.append({"kind": "irrigation", "observations": clean(obs),
                                       "decision": clean(decision)})
                if decision["action"] != "irrigate":
                    break
                tool = self._tool("irrigate")
                if tool is None:
                    self.decisions[-1]["execution_block"] = "No registered irrigation tool"
                    break
                args = {**decision["target"], "hours": float(decision["hours"])}
                started = self.engine.time_manager.time()
                receipt = self._execute_guarded(prefix + f"_water_{attempt}", tool, args)
                self.policy_history.append({"started_at": started,
                    "finished_at": self.engine.time_manager.time(), "tool_args": args,
                    "response": clean(receipt)})
                if receipt.get("status") != "irrigation_started":
                    break
                obs = self._observe_water(prefix + f"_after_water_{attempt}")
            active_crop = any(r.get("planted") and not r.get("harvested")
                              and 0 <= stage_rank(r.get("growth_stage")) <= 6
                              for r in obs["ridges"]["ridges"])
            if self.manage_crop and active_crop and (self._last_scout_timestamp is None or
                self.engine.time_manager.time() - self._last_scout_timestamp >= self.scout_interval_days * 86400):
                self._review_crop(prefix, obs)
        finally:
            self._last_review_day = datetime.fromtimestamp(self.engine.time_manager.time(), TZ).date().isoformat()
            self._in_management_review = False
            # Persist the growing evidence once at completion/failure; rewriting
            # the entire seasonal record each day makes a 90-case run quadratic.
            save(self.output / "adaptive_progress.json", {
                "simulation_timestamp": self.engine.time_manager.time(),
                "review_date": self._last_review_day,
                "decision_count": len(self.decisions),
                "water_receipts": len(self.policy_history),
                "crop_receipts": len(self.crop_history)})

    def _review_crop(self, label, water):
        tool = self._tool("inspect_crop_health")
        if tool is None:
            self.decisions.append({"kind": "crop", "unsupported": "No registered ground diagnosis"})
            return
        # This optional crop-health patrol must not inspect unplanted blocks
        # while an establishment operation is waiting to use its field window.
        # Only public, currently planted and nonmature crop rows are eligible.
        eligible = sorted({row["ridge_id"] for row in water["ridges"]["ridges"]
            if row.get("planted") and not row.get("harvested")
            and type(row.get("ridge_id")) is int
            and 0 <= row["ridge_id"] < self.farm.num_ridges
            and 0 <= stage_rank(row.get("growth_stage")) <= 6})
        ranges = []
        for ridge_id in eligible:
            if ranges and ridge_id == ranges[-1][1] + 1 and ridge_id-ranges[-1][0] < 4:
                ranges[-1][1] = ridge_id
            else:
                ranges.append([ridge_id, ridge_id])
        if not ranges:
            self.decisions.append({"kind": "crop_scout_skipped",
                "reason": "No public planted, unharvested VE-to-R6 target",
                "clock": self.engine.time_manager.time()})
            return
        observations = {}
        prefix = tool.rsplit("__", 1)[0]
        for start, end in ranges:
            # Retain the established conservative reserve: four ridges consume
            # 20%, but the robot may return early to preserve its landing reserve.
            self.battery(prefix, 40, label + f"_scout_energy_{start}")
            receipt = self.call(label + f"_scout_{start}", tool,
                                {"start_ridge": start, "end_ridge": end})
            if set(receipt.get("covered_ridges", [])) != set(range(start, end + 1)):
                raise RuntimeError("Adaptive ground inspection did not cover its request")
            sampled_day = (self.engine.time_manager.time() - self.engine.start_time) / 86400
            observations.update({rid: {**value, "observed_day": sampled_day}
                                 for rid, value in receipt.get("observations", {}).items()})
        self._last_scout_timestamp = self.engine.time_manager.time()
        # Scouting takes real time. Refresh water, stages, stocks and weather now.
        water = self._observe_water(label + "_after_scout")
        inventory = self._read(label + "_stock", "get_inventory")
        observation = {"now_day": (self.engine.time_manager.time() - self.engine.start_time) / 86400,
                       "date": water["overview"]["sim_date"],
                       "farm_id": water["overview"]["farm_id"],
                       "num_ridges": water["overview"]["num_ridges"],
                       "ridges": water["ridges"]["ridges"],
                       "ground_observations": observations,
                       "root_zone": water["root_zone"], "soil_sensors": water["surface"],
                       "weather": self._read(label + "_weather", "get_current_weather"),
                       "forecast": water["forecast"],
                       "management_regime": inventory.get("management_regime", {}),
                       "inventory": inventory,
                       "equipment_status": self._read(label + "_tractor", "get_status"),
                       "capabilities": {
                           "manual_pesticide_registered": self._tool("apply_pesticide_manual") is not None,
                           "prefer_manual_pesticide": getattr(self, "_prefer_manual_pesticide", False)},
                       "previous_observations": ([self._previous_crop_observation]
                                                 if self._previous_crop_observation else [])}
        attempted = set()
        for index in range(self.farm.num_ridges * 4):
            # A previous pass can cross midnight, use the last permitted
            # application day, or move the crop out of its treatment window.
            # Re-decide after each actual action using current public resources.
            if index:
                water = self._observe_water(label + f"_treatment_refresh_{index}")
                inventory = self._read(label + f"_stock_{index}", "get_inventory")
                observation.update(
                    now_day=(self.engine.time_manager.time() - self.engine.start_time) / 86400,
                    date=water["overview"]["sim_date"], ridges=water["ridges"]["ridges"],
                    root_zone=water["root_zone"], soil_sensors=water["surface"],
                    weather=self._read(label + f"_weather_{index}", "get_current_weather"),
                    forecast=water["forecast"], inventory=inventory,
                    management_regime=inventory.get("management_regime", {}),
                    equipment_status=self._read(label + f"_tractor_{index}", "get_status"))
            decision = decide_crop_management(observation, self.crop_history, self.crop_parameters)
            self.decisions.append({"kind": "crop", "observations": clean(observation),
                                   "decision": clean(decision)})
            proposal = next((p for p in decision.get("proposals", [])
                            if (p["operation"], p["start"], p["end"]) not in attempted), None)
            if proposal is None:
                break
            attempted.add((proposal["operation"], proposal["start"], proposal["end"]))
            self._execute_crop(label + f"_treatment_{index}", proposal)
        self._previous_crop_observation = {"now_day": observation["now_day"],
                                          "ridges": observation["ridges"]}

    def _execute_crop(self, label, proposal):
        method = proposal["operation"]
        tool = self._tool(method)
        if tool is None:
            self.decisions.append({"kind": "unsupported_proposal", "proposal": proposal})
            return
        args = {"start_ridge": int(proposal["start"]), "end_ridge": int(proposal["end"])}
        dose = proposal.get("dose")
        if method == "apply_fertigation":
            args.update(dose if isinstance(dose, dict) else {"nutrient_amount": float(dose), "water_mm": 0.})
        elif method == "apply_pesticide_manual":
            amount = float(dose.get("liters_per_ridge") if isinstance(dose, dict) else dose)
            args = {"ridge_id": int(proposal["start"]),
                    "ridge_count": int(proposal["end"]) - int(proposal["start"]) + 1,
                    "liters_per_ridge": amount, "advance_time": True}
        elif method in {"apply_fungicide", "spray_pesticide", "apply_herbicide"}:
            amount = float(dose.get("liters_per_ridge") if isinstance(dose, dict) else dose)
            args["liters_per_ridge"] = amount
            status = self._read(label + "_payload", "get_status")
            tank = "fungicide_tank_l" if method == "apply_fungicide" else "pesticide_tank_l"
            needed = amount * (args["end_ridge"] - args["start_ridge"] + 1) - float(status[tank])
            if needed > 1e-8:
                load = "load_fungicide" if method == "apply_fungicide" else "refill_pesticide_tank"
                receipt = self._execute_guarded(label + "_load", self._tool(load), {"liters": needed})
                if receipt.get("error"):
                    return
        if method not in {"apply_fertigation", "apply_pesticide_manual"}:
            status = self._read(label + "_fuel", "get_status")
            if float(status["fuel_tank_l"]) < 20:
                receipt = self._execute_guarded(label + "_refuel", self._tool("refuel"), {"liters": 100.})
                if receipt.get("error"):
                    return
        receipt = self._execute_guarded(label, tool, args)
        if not receipt.get("error") and receipt.get("status") not in {"failed", "partial"}:
            self.crop_history.append({"day": (self.engine.time_manager.time() - self.engine.start_time) / 86400,
                "operation": method, "start": int(proposal["start"]), "end": int(proposal["end"]),
                "dose": dose, "response": clean(receipt)})

    def compile(self, source):
        # Preserve the source's explicit handheld work method while allowing
        # its dates, targets and dose decisions to follow current observations.
        self._prefer_manual_pesticide = any((s.tool_name or "").endswith("__apply_pesticide_manual")
                                            for s in source.dag.values())
        filtered, removed = without_fixed_growth_management(source, self.i["Workflow"])
        save(self.output / "replaced_fixed_prescriptions.json", removed)
        filtered.save_workflow(str(self.output / "establishment_and_harvest_workflow.json"))
        try:
            result = super().compile(filtered)
        finally:
            save(self.output / "adaptive_decisions.json", self.decisions)
            save(self.output / "adaptive_irrigation_receipts.json", self.policy_history)
            save(self.output / "adaptive_crop_receipts.json", self.crop_history)
        result.update({"management_doses": "state-dependent registered-tool decisions",
                       "policy_input": "Registered public observations plus the declared source establishment/harvest plan and manual-method preference; private native states are verification only",
                       "global_optimum_proven": False,
                       "adaptive_water_actions": len([r for r in self.policy_history if r["response"].get("status") == "irrigation_started"]),
                       "adaptive_crop_actions": len(self.crop_history)})
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=["adaptive", "control"], default="adaptive")
    parser.add_argument("--forcing", type=Path)
    parser.add_argument("--water-parameters", type=Path)
    parser.add_argument("--water-only", action="store_true")
    args = parser.parse_args()
    from scripts.calibrate_formal90_oracles import imports, fingerprint, metrics
    i = imports()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    config = json.loads((ROOT / "configs/wofost/formal90_cultivar_mapping_v1.json").read_text())
    reviews = json.loads((ROOT / "configs/oracles/formal90_review_v1.json").read_text())
    review = deepcopy(next(r for r in reviews["rows"] if r["scenario_id"] == args.scenario))
    adaptations = json.loads((ROOT / "configs/oracles/formal90_runtime_adaptations_v1.json").read_text())
    adaptation = next((r for r in adaptations["rows"] if r["scenario_id"] == args.scenario), {})
    config.update(deepcopy(adaptation.get("config_overrides", {})))
    review["seed_replacements"] = deepcopy(adaptation.get("seed_replacements", {}))
    source = i["Engine"](agent=None, scenario=i["get_scenario_class"](args.scenario)()).build_oracle_workflow(run_oracle=False)
    source.save_workflow(str(out / "original_workflow.json"))
    forcing = json.loads(args.forcing.read_text()) if args.forcing else None
    params = json.loads(args.water_parameters.read_text()) if args.water_parameters else None
    compiler = None
    source_hashes = fingerprint()
    for path in sorted((ROOT / "scripts").glob("adaptive_*.py")):
        import hashlib
        source_hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    save(out / "provenance.json", {"scenario_id": args.scenario, "mode": args.mode,
        "config": config, "review": review, "source_sha256": source_hashes,
        "water_parameters": params, "crop_management_enabled": not args.water_only,
        "source_workflow_sha256": digest(source.to_dict())})
    result = {"scenario_id": args.scenario, "mode": args.mode}
    try:
        kwargs = {"review": review, "forcing_manifest": forcing}
        cls = FrozenWeatherCompiler
        if args.mode == "adaptive":
            cls = AdaptiveManagementCompiler
            kwargs.update(irrigation_parameters=params, manage_crop=not args.water_only)
        compiler = cls(args.scenario, config, out, i, **kwargs)
        result.update(compiler.compile(source))
        snapshot = compiler.snapshot(compiler.scenario, compiler.engine)
        save(out / "final_state.json", snapshot)
        result["metrics"] = metrics(clean(snapshot), compiler.workflow)
    except Exception as exc:
        result.update(completion="blocked", exception_type=type(exc).__name__,
                      message=str(exc), traceback=traceback.format_exc())
    finally:
        if compiler is not None:
            result.setdefault("model_blocks", compiler.model_blocks)
            result.setdefault("semantic_model_gaps", review.get("semantic_model_gaps", []))
            result["semantic_model_gaps_scope"] = "Inherited source-review annotations; these may be historical and are not a statement of current runtime failures. See completion, message and model_blocks for actual execution."
            if isinstance(compiler, AdaptiveManagementCompiler):
                result.setdefault("adaptive_water_actions", sum(r["response"].get("status") == "irrigation_started"
                                                                  for r in compiler.policy_history))
                result.setdefault("adaptive_crop_actions", len(compiler.crop_history))
            save(out / "discovery_trace.json", compiler.trace)
            save(out / "weather_forcing.json", compiler.forcing_manifest)
            compiler.workflow.save_workflow(str(out / "partial_workflow.json"))
        save(out / "summary.json", result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
