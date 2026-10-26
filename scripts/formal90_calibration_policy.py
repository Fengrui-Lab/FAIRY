"""Public-observation timing policy for the formal 90 WOFOST Oracles.

This module changes planning, not crop physics. Native DVS and resource truth
are captured by an audit-only path and never select a management action.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime
from math import ceil, floor, isfinite
from pathlib import Path
import re

from scripts.compile_wofost_observed_oracle import (
    ObservedCompiler, TZ, clean, save, stage_rank,
)


MANAGEMENT_METHODS = {
    "apply_fertigation", "apply_fertilizer", "irrigate", "irrigate_range",
    "irrigate_ridge", "apply_fungicide", "spray_pesticide", "apply_herbicide",
    "apply_pesticide", "apply_pesticide_manual", "mechanical_weed_control",
    "replant_seeds", "incorporate_residue",
}
WATER_N_METHODS = {
    "apply_fertigation", "apply_fertilizer", "irrigate", "irrigate_range",
    "irrigate_ridge",
}
STAGE_WAIT = re.compile(r"o_wait_(emergence|r1|r5|harvest)_advance_day_\d+")
CALENDAR_WAIT = re.compile(r".*_advance_day_\d+$")


def source_timestamp(value):
    """Interpret a source-plan date in the scene's explicit China calendar."""
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return parsed.timestamp()


def target_range(args, num_ridges=64):
    start = int(args.get("start_ridge", args.get("start", args.get("ridge_id", 0))))
    default_end = (start + int(args.get("ridge_count", 1)) - 1
                   if "ridge_id" in args else num_ridges - 1)
    end = int(args.get("end_ridge", args.get("end", default_end)))
    return start, end


def declared_phase(label):
    """Read a source label, never a private native development variable."""
    for phase in ("r5", "r1", "emergence", "harvest"):
        if re.search(r"(?:^|_)" + phase + r"(?:_|$)", label):
            return phase
    return None


class CalibrationCompiler(ObservedCompiler):
    """Keep the registered-tool replay contract while correcting source time.

    API: ``CalibrationCompiler(sid, config, output, imports, review=None)`` then
    ``compile(source_workflow)``. The result extends ObservedCompiler's summary.
    Every saved policy decision uses public tool results. Audit records may
    contain native state but are not read by the decision functions.
    """

    def __init__(self, sid, config, output, imports, review=None):
        self.review = review or {}
        self._fresh_count = 0
        self._source_steps = {}
        self._source_phases = {}
        self._source_stage_wait_done = set()
        self._phase_checked = {}
        self.management_audit = []
        self.timing_audit = []
        self.model_blocks = []
        self.rejected_guards = []
        self._observed_survey_cost = {}
        Path(output).mkdir(parents=True, exist_ok=True)
        super().__init__(sid, config, Path(output), imports)

    def fresh(self):
        replacements = self.review.get("seed_replacements", {})
        if replacements:
            scenario = self.i["get_scenario_class"](self.sid)(
                crop_backend="wofost", crop_backend_options=self.config)
            original_init = scenario.init_and_populate_apps

            def initialize_with_explicit_seed_choice(*args, **kwargs):
                original_init(*args, **kwargs)
                # Scenario.setup calls this hook before selecting a native
                # backend and before building events or registering tools.
                self._apply_seed_replacements(scenario, replacements)

            scenario.init_and_populate_apps = initialize_with_explicit_seed_choice
            scenario.setup()
            engine = self.i["Engine"](agent=None, scenario=scenario)
            engine._register_scenario_apps()
        else:
            scenario, engine = super().fresh()
        self._fresh_count += 1
        if self._fresh_count == 1:
            # Save before the discovery tools mutate anything. The snapshot is
            # serialized immediately, so mutable engine-state references cannot
            # later change the on-disk initial state.
            save(self.output / "initial_snapshot.json", super().snapshot(scenario, engine))
        return scenario, engine

    def _apply_seed_replacements(self, scenario, replacements):
        """An explicit pre-sowing seed choice, with conserved seed inventory.

        This does not relabel a parameter profile or alter native coefficients.
        The new seed identity must have its own strictly scoped native profile.
        """
        from fairy.apps.farm_world.models import SeedType
        from fairy.apps.farm_world.crop_profiles import seed_crop_type

        for old, new in replacements.items():
            SeedType(old)
            SeedType(new)
            if seed_crop_type(old) != seed_crop_type(new):
                raise ValueError("A seed adaptation must preserve the scenario crop species")
        note = "Explicit pre-sowing cultivar adaptation: " + ", ".join(f"{old} -> {new}" for old, new in sorted(replacements.items())) + ". Original scenario/cultivar identity remains the control; this run evaluates the declared new cultivar, not calibration of the old cultivar."
        stocks = []
        worlds = [a for a in scenario.apps if isinstance(a, self.i["FarmWorldApp"])]
        for world in worlds:
            stocks.append(world._inventory.seed_stock)
            for ridge in world._ridges:
                if ridge.seed_type in replacements:
                    if ridge.planted:
                        raise ValueError("Cultivar adaptation cannot relabel an already planted ridge")
                    ridge.seed_type = replacements[ridge.seed_type]
            physics = world.physics
            for component in (physics.phenology, physics.canopy):
                for state in component.states.values():
                    seed = getattr(state, "seed_type", None)
                    value = getattr(seed, "value", seed)
                    if value in replacements:
                        if getattr(state, "planted", False) or getattr(state, "initialized", False):
                            raise ValueError("Cultivar adaptation cannot relabel a started physical crop")
                        state.seed_type = type(seed)(replacements[value]) if hasattr(seed, "value") else replacements[value]
            metadata = getattr(physics, "scenario_metadata", {})
            if metadata.get("seed_type") in replacements:
                metadata["seed_type"] = replacements[metadata["seed_type"]]
            metadata["cultivar_adaptation"] = note
            metadata["cultivar"] = str(metadata.get("cultivar", "")) + " | " + note
            physics.scenario_metadata = metadata
            for window in world._planting_windows:
                if window.get("seed_type") in replacements:
                    window["seed_type"] = replacements[window["seed_type"]]
        for app in scenario.apps:
            stock = getattr(getattr(app, "stock", None), "seed_stock", None)
            if stock is not None:
                stocks.append(stock)
            seed = getattr(app, "seed_type", None)
            if seed in replacements:
                app.seed_type = replacements[seed]
        changes, seen = [], set()
        for stock in stocks:
            if id(stock) in seen:
                continue
            seen.add(id(stock))
            before = dict(stock)
            # Simultaneous renaming avoids order-dependent chain mappings.
            after = {}
            for seed, count in before.items():
                target = replacements.get(seed, seed)
                after[target] = after.get(target, 0) + count
            assert sum(before.values()) == sum(after.values())
            stock.clear()
            stock.update(after)
            changes.append({"before": before, "after": after, "total_seed_count_preserved": True})
        record = {"kind": "explicit_pre_sowing_cultivar_choice", "seed_replacements": dict(replacements), "seed_inventories": changes, "note": note, "evidence": self.review.get("runtime_adaptation", self.review.get("seed_replacement_basis"))}
        scenario.initial_state_adjustments = list(getattr(scenario, "initial_state_adjustments", [])) + [record]
        scenario.additional_system_prompt = (scenario.additional_system_prompt or "") + "\n" + note

    def snapshot(self, scenario, engine):
        value = super().snapshot(scenario, engine)
        role = "discovery" if scenario is getattr(self, "scenario", None) else "replay"
        save(self.output / f"{role}_final_snapshot.json", value)
        return value

    def snapshot_unrecorded(self, scenario, engine):
        """Capture an independent trial without replacing reference evidence."""
        return super().snapshot(scenario, engine)

    def phase_wait(self, label, phase):
        """Open a scouting window when a planted zone reaches the phase.

        A mixed/late field must not hold an early field's scouting window until
        every plant is in that phase. Actual management and harvest still gate
        their explicit target range separately.
        """
        target = {"emergence": 0, "r1": 1, "r5": 5, "harvest": 8}[phase]
        for poll in range(181):
            rows = self.ridges(label + f"_stage_{poll}")
            planted = [r for r in rows if r.get("planted", stage_rank(r.get("growth_stage")) >= 0)]
            if any(stage_rank(r.get("growth_stage")) >= target for r in planted):
                self.timing_audit.append({"kind": "public_phase_scout_window", "source_label": label, "phase": phase, "clock": self.engine.time_manager.time(), "criterion": "at least one planted target zone has reached phase; actions gate their own range", "observed_stage_counts": dict(Counter(r.get("growth_stage") for r in rows))})
                return
            self.wait(label + f"_stage_wait_{poll}")
        raise RuntimeError(f"Public {phase} phase polling cap exceeded")

    def _management_phase(self, label, method):
        if method not in WATER_N_METHODS:
            return None
        phase = declared_phase(label) or self._source_phases.get(label)
        return phase if phase in {"r1", "r5"} else None

    def _ensure_target_phase(self, label, method, args):
        phase = self._management_phase(label, method)
        if phase is None:
            return
        start, end = target_range(args, self.farm.num_ridges)
        key = (label, self.farm.name, start, end, phase)
        if self._phase_checked.get(key) == self.engine.time_manager.time():
            return
        minimum, latest = (1, 3) if phase == "r1" else (5, 6)
        for poll in range(181):
            rows = self.ridges(label + f"_target_phase_{poll}", start, end)
            ranks = [stage_rank(r.get("growth_stage")) for r in rows]
            # Reaching a minimum does not require the whole field or all rows
            # to have the SAME stage. Only the actual operation range is read.
            if ranks and min(ranks) >= minimum:
                late = max(ranks) > latest
                record = {"kind": "target_range_stage_gate", "source_label": label, "farm_id": self.farm.farm_id, "ridge_range": [start, end], "declared_phase": phase, "clock": self.engine.time_manager.time(), "observed_stage_counts": dict(Counter(r.get("growth_stage") for r in rows)), "outside_declared_latest_stage": late, "decision_input": "public get_ridge_range_state only"}
                self.timing_audit.append(record)
                self.changes.append(record)
                if late:
                    self.review_notes.append(f"{label}: target range is already beyond {'R3' if phase == 'r1' else 'R6'}; original {phase} management window was missed, not repaired by waiting")
                self._phase_checked[key] = self.engine.time_manager.time()
                return
            self.wait(label + f"_target_phase_wait_{poll}")
        raise RuntimeError(f"Target {start}-{end} never reached public {phase} phase within scenario")

    def gate(self, method, args, label, prefix):
        self._ensure_target_phase(label, method, args)
        if method == "harvest":
            return self._harvest_gate(args, label, prefix)
        return super().gate(method, args, label, prefix)

    def _harvest_gate(self, args, label, prefix):
        """Use the actual public combine capability, not a fixed17.5% gate."""
        start, end = target_range(args, self.farm.num_ridges)
        sensor = self.sensors.get(self.farm.name)
        if sensor is None:
            raise RuntimeError("No public soil sensor for harvest readiness")
        for poll in range(181):
            weather = self.current_weather(label + f"_weather_{poll}")
            status = self.call(label + f"_harvest_capability_{poll}", prefix + "__get_status", {})
            limit = status.get("harvest_moisture_limit_pct")
            if limit is None or not isfinite(float(limit)):
                raise RuntimeError("Combine public harvest moisture capability is unavailable")
            rows = self.ridges(label + f"_field_{poll}", start, end)
            soil = self.call(label + f"_soil_{poll}", sensor.name + "__read_soil_sensors", {})
            probes = [p for p in soil.get("soil_sensors", []) if p.get("ridge_end", p.get("ridge_id", -1)) >= start and p.get("ridge_start", p.get("ridge_id", 64)) <= end]
            if not probes or any(p.get("vwc") is None for p in probes):
                raise RuntimeError("Public harvest soil observations unavailable")
            # Probe support areas are coarse and can overlap a dry operation
            # range. They cannot prove every target ridge/whole-field average
            # is too wet. The registered combine's zero-mutation guard is the
            # authoritative trafficability check; retain probes as evidence.
            ready = (float(weather.get("rainfall_mm", 1)) == 0
                     and all(stage_rank(r.get("growth_stage")) >= 8
                             and float(r.get("grain_moisture_pct", 100)) <= float(limit)
                             for r in rows))
            if ready:
                self.timing_audit.append({"kind": "public_combine_harvest_gate", "source_label": label, "ridge_range": [start, end], "clock": self.engine.time_manager.time(), "harvest_moisture_limit_pct": float(limit), "observed_moisture_range_pct": [min(float(r["grain_moisture_pct"]) for r in rows), max(float(r["grain_moisture_pct"]) for r in rows)], "coarse_soil_vwc_range": [min(float(p["vwc"]) for p in probes), max(float(p["vwc"]) for p in probes)], "trafficability_authority": "registered combine preflight; coarse overlapping probes are observations, not exact-ridge vetoes"})
                return
            self.wait(label + f"_readiness_wait_{poll}")
        raise RuntimeError("Public harvest readiness polling cap exceeded")

    def _survey_complete_range(self, label, tool, args, op):
        """Split coverage using observed battery consumption and a stated reserve.

        Old check_status does not publish per-ridge cost or its true return
        threshold. Learn cost from successful public mission receipts, starting
        with one pass; reserve30% is a conservative planning choice, not a claim
        that30% is the hardware's hidden threshold.
        """
        prefix = tool.rsplit("__", 1)[0]
        start, end = target_range(args, self.farm.num_ridges)
        first, covered, missions = start, [], []
        while first <= end:
            status = self.call(label + f"_coverage_{first}_battery", prefix + "__check_status", {})
            width = max(1, int(status.get("effective_ridges_per_pass", 1)))
            battery = float(status.get("battery_pct", 0))
            rate = self._observed_survey_cost.get(prefix)
            published_rate = status.get("battery_pct_per_ridge")
            if published_rate is not None and isfinite(float(published_rate)) and float(published_rate) > 0:
                rate = max(float(published_rate), rate or 0)
            reserve = max(30., float(status.get("min_battery_pct", 0)))
            remaining = end - first + 1
            capacity = floor((battery - reserve) / rate + 1e-8) if rate else min(width, remaining)
            needs_charge = status.get("charging") or (rate is None and battery < 90) or capacity < min(width, remaining)
            if needs_charge:
                self.call(label + f"_coverage_{first}_charge", prefix + "__charge", {}, op="WRITE")
                self.wait(label + f"_coverage_{first}_charge_wait", 3600)
                continue
            count = min(remaining, capacity)
            if count > width and count < remaining:
                count = max(width, count // width * width)
            if count <= 0:
                raise RuntimeError("Public battery observations cannot support even one survey ridge")
            last = first + count - 1
            sub = {**args, "start_ridge": first, "end_ridge": last}
            mission_label = label + f"_coverage_{first}_{last}"
            self.gate("fly_survey", sub, mission_label, prefix)
            # Weather waits do not drain a landed drone. Refresh public battery
            # after gating nevertheless, so the observed consumption is exact.
            launch = self.call(mission_label + "_launch_battery", prefix + "__check_status", {})
            result = super().call(mission_label, tool, sub, op=op)
            actual = result.get("surveyed_ridges", [])
            if set(actual) != set(range(first, last + 1)) or result.get("status") != "ok":
                raise RuntimeError("Survey mission did not cover its explicit energy-budgeted range")
            used = float(launch["battery_pct"]) - float(result["battery_remaining_pct"])
            if used <= 0:
                raise RuntimeError("Public survey receipt does not establish positive battery consumption")
            measured = used / count
            self._observed_survey_cost[prefix] = max(measured, rate or 0)
            covered.extend(actual)
            missions.append({"ridge_range": [first, last], "battery_before_pct": launch["battery_pct"], "battery_after_pct": result["battery_remaining_pct"], "observed_cost_pct_per_ridge": measured, "planner_reserve_pct": reserve})
            first = last + 1
        self.changes.append({"kind": "survey_split_by_observed_energy_and_verified_coverage", "source_step": label, "original_arguments": deepcopy(args), "missions": missions, "surveyed_ridges": covered})
        return {"status": "ok", "surveyed_ridges": covered, "mission_count": len(missions)}

    def _harvest_guard_signature(self, label, prefix, args):
        """Public evidence that a rejected attempt consumed no management state."""
        start, end = target_range(args, self.farm.num_ridges)
        clock = self.call(label + "_clock", self.system.name + "__get_current_time", {})
        status = self.call(label + "_device", prefix + "__get_status", {})
        inventory = self.call(label + "_inventory", self.farm.name + "__get_inventory", {})
        rows = self.ridges(label + "_ridges", start, end)
        return clean({"clock": clock, "device": status, "inventory": inventory, "ridges": rows})

    def _harvest_with_safe_guard_retry(self, label, tool, args, op):
        prefix = tool.rsplit("__", 1)[0]
        for attempt in range(181):
            self.gate("harvest", args, label + f"_final_gate_{attempt}", prefix)
            before = self._harvest_guard_signature(label + f"_guard_before_{attempt}", prefix, args)
            trace_index = len(self.trace)
            result = super().call(label + f"_attempt_{attempt}", tool, args, op=op, guard=True)
            if not isinstance(result, dict) or not result.get("error"):
                return result
            failed = self.trace[trace_index]
            message = str(result.get("error", ""))
            retryable = message == "Cannot harvest in rainy conditions" or message.startswith("Soil too wet for harvest")
            if not retryable or failed["time_before"] != failed["time_after"]:
                raise RuntimeError(f"{tool}: {result}")
            after = self._harvest_guard_signature(label + f"_guard_after_{attempt}", prefix, args)
            if before != after:
                raise RuntimeError("Rejected harvest changed public management state; cannot discard/retry it")
            # Preserve the real rejected discovery receipt separately. It is
            # not a committed action and consumed no state/time; the canonical
            # executable plan contains its surrounding real reads and wait.
            del self.trace[trace_index]
            self.rejected_guards.append({"source_step": label, "attempt": attempt, "rejection": failed, "public_before": before, "public_after": after, "zero_mutation_verified": True})
            save(self.output / "discovery_rejected_guards.json", self.rejected_guards)
            self.changes.append({"kind": "zero_mutation_harvest_guard_replanned", "source_step": label, "reason": message, "attempt": attempt})
            # Rounded public rainfall can read0.00 while the tool still rejects
            # a trace of rain. Its rejection is new public evidence; wait for a
            # different date rather than retrying indefinitely at that instant.
            self.wait(label + f"_weather_guard_wait_{attempt}")
        raise RuntimeError("Harvest weather guard retry cap exceeded")

    def _calendar_wait(self, label, tool, args, op, guard):
        source = self._source_steps[label]
        target = source_timestamp(getattr(source, "time", None))
        if target is None:
            self.review_notes.append(f"{label}: source has no absolute timestamp; source relative wait preserved")
            return super().call(label, tool, args, op=op, guard=guard)
        before = self.engine.time_manager.time()
        remaining = max(0, int(ceil(target - before)))
        record = {"kind": "source_calendar_wait_not_cumulative", "source_step": label, "original_arguments": deepcopy(args), "source_target_timestamp": target, "source_target_china_time": datetime.fromtimestamp(target, TZ).isoformat(), "actual_before": before, "revised_wait_seconds": remaining, "already_past_source_calendar": remaining == 0}
        self.changes.append(record)
        self.timing_audit.append(record)
        if remaining:
            if before + remaining > self.deadline:
                raise RuntimeError("Source calendar wait exceeds original scenario duration")
            return super().call(label, tool, {"seconds": remaining}, op=op, guard=guard)
        return super().call(label + "_calendar_already_reached", self.system.name + "__get_current_time", {}, op="READ")

    def _ensure_seed_payload(self, label, tool, args):
        """Transfer existing warehouse seed only when public payload is short."""
        prefix = tool.rsplit("__", 1)[0]
        status = self.call(label + "_plant_seed_payload", prefix + "__get_status", {})
        overview = self.call(label + "_plant_public_geometry", self.farm.name + "__get_farm_overview", {})
        profile = overview.get("crop_profile", {})
        length, rows = overview.get("field_length_m"), profile.get("rows_per_ridge")
        if length is None or rows is None:
            raise RuntimeError("Public geometry is missing for seed-demand validation")
        start, end = target_range(args, self.farm.num_ridges)
        spacing = float(args.get("seed_spacing_cm", args.get("spacing_cm", 0)))
        if spacing <= 0:
            return  # Let the registered tool reject its own invalid parameter.
        required = int(round(float(length) * int(rows) * 100 / spacing)) * (end - start + 1)
        loaded = int(status.get("seed_hopper", 0))
        if loaded >= required:
            return
        seed = status.get("seed_type")
        if not seed:
            raise RuntimeError("No public seed variety loaded before planting")
        amount = required - loaded
        result = self.call(label + "_supplement_existing_seed", prefix + "__load_seeds", {"seed_type": seed, "count": amount}, op="WRITE")
        self.changes.append({"kind": "seed_payload_supplement_from_existing_inventory", "source_step": label, "seed_type": seed, "required_seeds": required, "loaded_before": loaded, "requested_transfer": amount, "receipt": clean(result), "inventory_created": False})

    def _private_management_audit(self, label, tool, args):
        """Verification-only collection, deliberately isolated from all gates."""
        start, end = target_range(args, self.farm.num_ridges)
        physics = self.farm.physics
        backend = physics.crop_backend
        runs = getattr(backend, "_runs", {}) if backend is not None else {}
        native = {str(rid): {name: getattr(runs.get(rid), "pcse", {}).get(name) for name in ("DVS", "TWSO", "TAGP", "SM", "NAVAIL")} for rid in range(start, end + 1)}
        method = tool.rsplit("__", 1)[1]
        count = end - start + 1
        dose = {"target_ridges": count}
        if method == "apply_fertigation":
            kg = float(args["nutrient_amount"]) * 30 * count
            fraction = getattr(getattr(backend, "config", None), "fertilizer_n_fraction", None)
            dose.update(product_kg=kg, nitrogen_kg=kg * fraction if fraction is not None else None, carrier_water_mm_per_target_ridge=args.get("water_mm", 0))
        elif method in {"irrigate", "irrigate_range", "irrigate_ridge"}:
            duration = args.get("hours", args.get("duration_hours"))
            dose.update(duration_hours_per_ridge=duration, estimated_water_mm_per_target_ridge=float(duration) * 5 if duration is not None else None)
        elif "liters_per_ridge" in args:
            dose.update(working_fluid_l_per_ridge=args["liters_per_ridge"], total_working_fluid_l=float(args["liters_per_ridge"]) * count)
        prefix = tool.rsplit("__", 1)[0]
        app = next((a for a in self.scenario.apps if a.name == prefix), None)
        device = {name: getattr(app, name) for name in ("_fuel_tank_l", "_pesticide_tank_l", "_fungicide_tank_l", "_fertilizer_spreader_kg", "_seed_hopper") if app is not None and hasattr(app, name)}
        return {"source_label": label, "tool_name": tool, "arguments": deepcopy(args), "farm_id": self.farm.farm_id, "ridge_range": [start, end], "clock": self.engine.time_manager.time(), "stage_counts": dict(Counter(physics.phenology.states[rid].stage.value for rid in range(start, end + 1))), "native_audit_only": native, "actual_API_dose": dose, "device_loads": device, "farm_inventory": self.farm._inventory.to_dict(), "not_a_policy_input": True}

    def call(self, label, tool, args, *, op="READ", guard=False):
        method = tool.rsplit("__", 1)[-1]
        if method == "apply_pesticide_manual" and args.get("advance_time") is False:
            args = {**args, "advance_time": True}
            self.changes.append({"kind": "manual_spray_requires_real_operator_time", "source_step": label, "original_advance_time": False, "revised_advance_time": True, "reason": "Each real backpack pass must consume registered operator time; source passes had no aggregate time charge, so zero-duration application is not retained."})
        if method == "advance_time" and label in self._source_steps:
            match = STAGE_WAIT.fullmatch(label)
            if match:
                phase = match.group(1)
                key = (self.farm.name, phase)
                if key not in self._source_stage_wait_done:
                    self.phase_wait(label, phase)
                    self._source_stage_wait_done.add(key)
                    self.changes.append({"kind": "mixed_or_interleaved_phase_wait_uses_public_stage", "source_step": label, "phase": phase})
                return super().call(label + "_phase_already_observed", self.system.name + "__get_current_time", {}, op="READ")
            if CALENDAR_WAIT.fullmatch(label):
                return self._calendar_wait(label, tool, args, op, guard)
        if method == "fly_survey":
            return self._survey_complete_range(label, tool, args, op)
        if method == "harvest":
            return self._harvest_with_safe_guard_retry(label, tool, args, op)
        if method == "plant_seeds":
            self._ensure_seed_payload(label, tool, args)
        if method not in MANAGEMENT_METHODS:
            return super().call(label, tool, args, op=op, guard=guard)
        self._ensure_target_phase(label, method, args)
        record = {"before": self._private_management_audit(label, tool, args)}
        try:
            result = super().call(label, tool, args, op=op, guard=guard)
            record["receipt"] = clean(result)
            return result
        except Exception as exc:
            record["exception_type"] = type(exc).__name__
            record["message"] = str(exc)
            if method == "replant_seeds":
                block = {"source_label": label, "tool_name": tool, "arguments": deepcopy(args), "status": "native_replant_lifecycle_unsupported", "message": str(exc), "original_objective_preserved": True}
                self.model_blocks.append(block)
                save(self.output / "calibration_block.json", block)
            raise
        finally:
            record["after"] = self._private_management_audit(label, tool, args)
            self.management_audit.append(record)
            save(self.output / "management_actions_audit.json", self.management_audit)

    def compile(self, source):
        replacements = self.review.get("seed_replacements", {})
        if replacements:
            mapped = self.i["Workflow"]()
            note = "本次显式播前品种适应选择：" + ", ".join(f"{old}→{new}" for old, new in sorted(replacements.items())) + "。原场景品种保留为控制证据，本次使用实际新种子及其独立参数档案；不宣称原品种校准成功。"
            for label, original in source.dag.items():
                step = deepcopy(original)
                args = step.tool_args or {}
                if (step.tool_name or "").endswith("__load_seeds") and args.get("seed_type") in replacements:
                    old = args["seed_type"]
                    args["seed_type"] = replacements[old]
                    self.changes.append({"kind": "explicit_cultivar_load_choice", "source_step": label, "original_seed": old, "actual_seed": replacements[old]})
                if (step.tool_name or "").endswith("__send_message_to_agent") and isinstance(args.get("content"), str):
                    args["content"] += "\n\n" + note
                step.tool_args = args
                mapped.add_node(step)
            source = mapped
            source.save_workflow(str(self.output / "mapped_source_workflow.json"))
        self._source_steps = dict(source.dag)
        phase = None
        for label in self._source_steps:
            explicit = declared_phase(label)
            if explicit:
                phase = explicit
            self._source_phases[label] = phase
        try:
            result = super().compile(source)
            result.update({"timing_policy": "source absolute calendar plus public target-range phase gates", "management_audit_count": len(self.management_audit), "model_blocks": self.model_blocks, "semantic_model_gaps": self.review.get("semantic_model_gaps", []), "management_doses": "source rates retained for parent driver paired dose/omission comparisons; actual API mass and water recorded"})
            return result
        finally:
            self.snapshot(self.scenario, self.engine)
            save(self.output / "timing_policy_audit.json", self.timing_audit)
            save(self.output / "management_actions_audit.json", self.management_audit)
            save(self.output / "discovery_rejected_guards.json", self.rejected_guards)
            save(self.output / "calibration_policy_review.json", {"scenario_id": self.sid, "review": self.review, "notes": self.review_notes, "changes": self.changes, "model_blocks": self.model_blocks})
