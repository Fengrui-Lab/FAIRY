"""Compile a legal native Oracle using only registered public observations.

The original plan is preserved separately. Discovery logs every attempted call;
its successful public calls become a static workflow which is replayed from a
fresh scene. Doses are preserved and marked for management review: operational
completion does not establish agronomic necessity or yield optimality.
"""

from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
import sys
import traceback
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
UUID_FIELDS = {"op_id", "mission_id", "inspection_id", "action_id"}


def clean(value):
    if is_dataclass(value):
        return clean(asdict(value))
    if isinstance(value, dict):
        return {
            str(k): "<ID>" if k in UUID_FIELDS else clean(v) for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, set):
        return sorted(clean(v) for v in value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )


def digest(value):
    return hashlib.sha256(json.dumps(clean(value), sort_keys=True).encode()).hexdigest()


def stage_rank(value):
    text = str(value).upper()
    for prefix, rank in [
        ("R8", 8),
        ("R7", 7),
        ("R6", 6),
        ("R5", 5),
        ("R4", 4),
        ("R3", 3),
        ("R2", 2),
        ("R1", 1),
    ]:
        if text.startswith(prefix):
            return rank
    if text.startswith("V"):
        return 0
    return -1


class ObservedCompiler:
    def __init__(self, sid, config, output, imports):
        self.sid, self.config, self.output, self.i = sid, config, output, imports
        self.scenario, self.engine = self.fresh()
        self.worlds = [
            app
            for app in self.scenario.apps
            if isinstance(app, imports["FarmWorldApp"])
        ]
        self.farm = self.worlds[0]
        self.sensors = {
            world.name: next(
                (
                    app
                    for app in self.scenario.apps
                    if isinstance(app, imports["SensorApp"])
                    and getattr(app, "_farm_world_app", None) is world
                ),
                None,
            )
            for world in self.worlds
        }
        self.weather = self.scenario.get_typed_app(imports["WeatherApp"])
        self.system = self.scenario.get_typed_app(imports["SystemApp"])
        _, _, self.tools = imports["build_toolset"](list(self.scenario.apps))
        self.workflow = imports["Workflow"]()
        self.trace = []
        self.changes = []
        self.review_notes = []
        self.counter = 0
        self.deadline = self.engine.start_time + float(self.scenario.duration)
        self.last = None

    def fresh(self):
        scenario = self.i["get_scenario_class"](self.sid)(
            crop_backend="wofost", crop_backend_options=self.config
        )
        scenario.setup()
        engine = self.i["Engine"](agent=None, scenario=scenario)
        engine._register_scenario_apps()
        return scenario, engine

    def call(self, label, tool, args, *, op="READ", guard=False):
        self.counter += 1
        name = f"v{self.counter:05d}_{label}"
        before = self.engine.time_manager.time()
        try:
            result = self.tools[tool](**args)
        except Exception as exc:
            self.trace.append(
                {
                    "name": name,
                    "source_label": label,
                    "tool_name": tool,
                    "tool_args": deepcopy(args),
                    "time_before": before,
                    "time_after": self.engine.time_manager.time(),
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
            raise
        after = self.engine.time_manager.time()
        entry = {
            "name": name,
            "source_label": label,
            "tool_name": tool,
            "tool_args": deepcopy(args),
            "time_before": before,
            "time_after": after,
            "content": clean(result),
        }
        self.trace.append(entry)
        error = isinstance(result, dict) and (
            result.get("error")
            or result.get("status") in {"error", "failed", "partial"}
        )
        if error:
            if guard and before == after:
                entry["discovery_only_rejected_guard"] = True
                return result
            raise RuntimeError(f"{tool}: {result}")
        step = self.i["WorkflowStep"](
            name=name,
            tool_name=tool,
            tool_args=deepcopy(args),
            content=result,
            op_type=op,
            depends_on=[self.last] if self.last else [],
            time_before=before,
            time_after=after,
        )
        self.workflow.add_node(step)
        self.last = name
        return result

    def wait(self, label, seconds=86400):
        if self.engine.time_manager.time() + seconds > self.deadline:
            raise RuntimeError(
                "No observed readiness within the original scenario duration"
            )
        return self.call(
            label, self.system.name + "__advance_time", {"seconds": int(seconds)}
        )

    def ridges(self, label, start=0, end=63):
        response = self.call(
            label,
            self.farm.name + "__get_ridge_range_state",
            {"start": start, "end": end},
        )
        rows = response.get("ridges", [])
        if {r["ridge_id"] for r in rows} != set(range(start, end + 1)):
            raise RuntimeError("Incomplete public ridge state response")
        return rows

    def current_weather(self, label):
        return self.call(label, self.weather.name + "__get_current_weather", {})

    def phase_wait(self, label, phase):
        target = {"emergence": 0, "r1": 1, "r5": 5, "harvest": 8}[phase]
        for poll in range(181):
            rows = self.ridges(label + f"_stage_{poll}")
            if all(stage_rank(r["growth_stage"]) >= target for r in rows):
                return
            self.wait(label + f"_stage_wait_{poll}")
        raise RuntimeError("Stage polling cap exceeded")

    def battery(self, prefix, required, label):
        status = self.call(label + "_battery", prefix + "__check_status", {})
        if status.get("charging") or float(status.get("battery_pct", 0)) < required:
            self.call(label + "_charge", prefix + "__charge", {}, op="WRITE")
            self.wait(label + "_charge_wait", 3600)

    def gate(self, method, args, label, prefix):
        start = int(args.get("start_ridge", args.get("start", 0)))
        end = int(args.get("end_ridge", args.get("end", 63)))
        for poll in range(181):
            weather = self.current_weather(label + f"_weather_{poll}")
            ok = True
            if method in {
                "fly_survey",
                "harvest",
                "apply_fungicide",
                "spray_pesticide",
                "apply_herbicide",
            }:
                ok = float(weather.get("rainfall_mm", 1)) == 0
            if method == "fly_survey":
                ok = ok and float(weather.get("wind_speed_ms", 99)) < 10
                time = self.call(
                    label + f"_clock_{poll}",
                    self.system.name + "__get_current_time",
                    {},
                )
                hour = datetime.fromtimestamp(time["current_timestamp"], TZ).hour
                if prefix.startswith("Mavic") and not 7 <= hour < 17:
                    self.wait(label + f"_daylight_wait_{poll}", 3600)
                    continue
            if method in {"apply_fungicide", "spray_pesticide", "apply_herbicide"}:
                ok = ok and float(weather.get("wind_speed_ms", 99)) < 6
            if method in {
                "plant_seeds",
                "harvest",
                "level",
                "base_fertilize",
                "form_ridges",
                "apply_fertilizer",
                "apply_fungicide",
                "spray_pesticide",
                "apply_herbicide",
                "mechanical_weed_control",
            }:
                rows = self.ridges(label + f"_field_{poll}", start, end)
                sensor = self.sensors.get(self.farm.name)
                if sensor is None:
                    raise RuntimeError(
                        "No public fixed soil sensor for the target farm"
                    )
                soil = self.call(
                    label + f"_soil_{poll}", sensor.name + "__read_soil_sensors", {}
                )
                probes = [
                    probe
                    for probe in soil.get("soil_sensors", [])
                    if probe.get("ridge_end", probe.get("ridge_id", -1)) >= start
                    and probe.get("ridge_start", probe.get("ridge_id", 64)) <= end
                ]
                if not probes or any(
                    probe.get("vwc") is None or probe.get("temp_c") is None
                    for probe in probes
                ):
                    raise RuntimeError(
                        "Public soil observations are unavailable; no hidden-state fallback"
                    )
                ok = ok and all(float(probe["vwc"]) <= 0.35 for probe in probes)
                if method == "plant_seeds":
                    ok = ok and all(
                        float(probe["temp_c"]) >= 10 and float(probe["vwc"]) >= 0.20
                        for probe in probes
                    )
                if method == "harvest":
                    ok = ok and all(
                        stage_rank(r["growth_stage"]) >= 8
                        and float(r.get("grain_moisture_pct", 100)) <= 17.5
                        for r in rows
                    )
            if ok:
                return
            self.wait(label + f"_readiness_wait_{poll}")
        raise RuntimeError("Public operation gate polling cap exceeded")

    def snapshot(self, scenario, engine):
        # Verification only. This data is never passed to a policy decision.
        worlds = [
            app for app in scenario.apps if isinstance(app, self.i["FarmWorldApp"])
        ]
        return {
            "clock": engine.time_manager.time(),
            "farms": {
                farm.name: {
                    "world": farm.get_state(),
                    "engines": {
                        name: getattr(farm.physics, name).states
                        for name in (
                            "soil",
                            "phenology",
                            "canopy",
                            "management",
                            "biotic",
                            "yield_recovery",
                        )
                    },
                    "native_backend": (
                        farm.physics.crop_backend.snapshot()
                        if farm.physics.crop_backend is not None
                        else None
                    ),
                }
                for farm in worlds
            },
            "apps": {app.name: app.get_state() for app in scenario.apps},
        }

    def compile(self, source):
        items = list(source.dag.items())
        index = 0
        phase_positions = {
            phase: [
                i
                for i, (name, _) in enumerate(items)
                if re.fullmatch(r"o_wait_" + phase + r"_advance_day_\d+", name)
            ]
            for phase in ("emergence", "r1", "r5", "harvest")
        }
        safe_phases = {
            phase
            for phase, positions in phase_positions.items()
            if positions and positions == list(range(positions[0], positions[-1] + 1))
        }
        for phase, positions in phase_positions.items():
            if positions and phase not in safe_phases:
                self.review_notes.append(
                    f"{phase}: original daily waits retained because source hooks interleave them"
                )
        seed_types = {
            step.tool_args["seed_type"]
            for _, step in items
            if step.tool_name
            and step.tool_name.endswith("__load_seeds")
            and step.tool_args.get("seed_type")
        }
        module = sys.modules[type(self.scenario).__module__]
        spec = getattr(module, "SPEC", None)
        if len(seed_types) > 1 or (spec is not None and len(spec.planting_zones) > 1):
            safe_phases.clear()
            self.review_notes.append(
                "Mixed cultivars or staggered planting: original phase calendar retained; per-zone management timing needs review"
            )
        while index < len(items):
            name, step = items[index]
            tool = step.tool_name
            if not tool:
                index += 1
                continue
            args = dict(step.tool_args or {})
            prefix, method = tool.rsplit("__", 1)
            if "farm_id" in args:
                candidates = [
                    world for world in self.worlds if world.farm_id == args["farm_id"]
                ]
                if len(candidates) != 1:
                    raise RuntimeError("Unresolved explicit farm target")
                self.farm = candidates[0]
            else:
                candidates = [
                    world
                    for world in self.worlds
                    if prefix == world.name or prefix.startswith(world.name + "_")
                ]
                if len(candidates) == 1:
                    self.farm = candidates[0]
            if method == "load_seeds" and len(seed_types) > 1:
                # Obtain geometry from the public interface, then load only the
                # explicit planned planting segment before the next seed load.
                overview = self.call(
                    name + "_public_geometry",
                    self.farm.name + "__get_farm_overview",
                    {},
                )
                geometry = overview.get("crop_profile", {})
                if "field_length_m" not in overview or "rows_per_ridge" not in geometry:
                    raise RuntimeError(
                        "Public planting geometry is missing; cannot size a mixed-cultivar seed load"
                    )
                demand = 0
                for _, future in items[index + 1 :]:
                    if future.tool_name == prefix + "__load_seeds":
                        break
                    if future.tool_name == prefix + "__plant_seeds":
                        planting = future.tool_args
                        per_ridge = int(
                            round(
                                float(overview["field_length_m"])
                                * int(geometry["rows_per_ridge"])
                                * 100
                                / float(planting["seed_spacing_cm"])
                            )
                        )
                        demand += (
                            int(planting["end_ridge"])
                            - int(planting["start_ridge"])
                            + 1
                        ) * per_ridge
                status = self.call(
                    name + "_public_seed_payload", prefix + "__get_status", {}
                )
                hopper = int(status.get("seed_hopper", 0))
                if hopper and status.get("seed_type") != args["seed_type"]:
                    return_tool = prefix + "__return_supplies"
                    if return_tool not in self.tools:
                        raise RuntimeError(
                            "Mixed-cultivar seed switch requires an empty hopper; no registered seed-return tool is available"
                        )
                    self.call(
                        name + "_return_before_cultivar_switch",
                        return_tool,
                        {},
                        op="WRITE",
                    )
                    hopper = 0
                if demand > 0:
                    revised = max(0, min(int(args["count"]), demand - hopper))
                    if revised != args["count"]:
                        self.changes.append(
                            {
                                "kind": "mixed_cultivar_load_sized_to_public_geometry_and_explicit_plan",
                                "source_step": name,
                                "original_count": args["count"],
                                "revised_count": revised,
                                "planned_seed_demand": demand,
                            }
                        )
                        args["count"] = revised
                    if revised == 0:
                        index += 1
                        continue
            # Only replace plain contiguous daily wait groups; keep hook events.
            match = re.fullmatch(
                r"o_wait_(emergence|r1|r5|harvest)_advance_day_\d+", name
            )
            if match and match.group(1) in safe_phases:
                phase = match.group(1)
                end = index
                while end + 1 < len(items) and re.fullmatch(
                    r"o_wait_" + phase + r"_advance_day_\d+", items[end + 1][0]
                ):
                    end += 1
                self.phase_wait(name, phase)
                self.changes.append(
                    {
                        "kind": "public_stage_wait_replaces_fixed_daily_group",
                        "source_steps": [items[k][0] for k in range(index, end + 1)],
                        "phase": phase,
                    }
                )
                index = end + 1
                continue
            if (
                method.startswith("inspect_")
                and "start_ridge" in args
                and "end_ridge" in args
            ):
                for first in range(args["start_ridge"], args["end_ridge"] + 1, 4):
                    last = min(first + 3, args["end_ridge"])
                    sub = {**args, "start_ridge": first, "end_ridge": last}
                    self.battery(prefix, 40, name + f"_{first}_{last}")
                    result = self.call(name + f"_{first}_{last}", tool, sub)
                    if set(result.get("covered_ridges", [])) != set(
                        range(first, last + 1)
                    ):
                        raise RuntimeError(
                            "Ground tool did not cover its explicit four-ridge request"
                        )
                    for ridge_id, observation in result.get("observations", {}).items():
                        confidence = [
                            float(value)
                            for key, value in observation.items()
                            if key.endswith("_confidence") or key == "confidence"
                        ]
                        if confidence and max(confidence) <= 0:
                            raise RuntimeError(
                                f"Ground observation for ridge {ridge_id} has no positive confidence"
                            )
                self.changes.append(
                    {
                        "kind": "ground_requests_split_to_actual_four_ridge_evidence",
                        "source_step": name,
                        "original_arguments": args,
                    }
                )
                index += 1
                continue
            if method == "fly_survey":
                self.battery(prefix, 90, name)
            if method in {
                "fly_survey",
                "harvest",
                "plant_seeds",
                "level",
                "base_fertilize",
                "form_ridges",
                "apply_fertilizer",
                "apply_fungicide",
                "spray_pesticide",
                "apply_herbicide",
                "mechanical_weed_control",
            }:
                self.gate(method, args, name, prefix)
            if method in {
                "harvest",
                "plant_seeds",
                "level",
                "base_fertilize",
                "form_ridges",
                "apply_fertilizer",
                "apply_fungicide",
                "spray_pesticide",
                "apply_herbicide",
                "mechanical_weed_control",
            }:
                status = self.call(name + "_fuel_status", prefix + "__get_status", {})
                if float(status.get("fuel_tank_l", 100)) < 20:
                    self.call(
                        name + "_refuel",
                        prefix + "__refuel",
                        {"liters": 100.0},
                        op="WRITE",
                    )
            if method == "store_grain":
                dry_args = {"target_moisture_pct": 13.0}
                if "batch_id" in args:
                    dry_args["batch_id"] = args["batch_id"]
                self.call(
                    name + "_dry_to_safe_storage",
                    prefix + "__dry_grain",
                    dry_args,
                    op="WRITE",
                )
            result = self.call(
                name, tool, args, op=getattr(step, "op_type", "READ") or "READ"
            )
            index += 1
        self.workflow.save_workflow(str(self.output / "observed_workflow.json"))
        discovery_hash = digest(self.snapshot(self.scenario, self.engine))
        fresh, replay_engine = self.fresh()
        replayed = replay_engine.replay_workflow(self.workflow)
        replayed.save_workflow(str(self.output / "fresh_replay.json"))
        replay_hash = digest(self.snapshot(fresh, replay_engine))
        replay_errors = []
        trace_differences = []
        for index, (name, step) in enumerate(replayed.dag.items()):
            response = step.content
            if isinstance(response, dict) and (
                response.get("error")
                or response.get("status") in {"error", "failed", "partial"}
            ):
                replay_errors.append({"step": name, "content": clean(response)})
            actual = {
                key: clean(getattr(step, key))
                for key in (
                    "tool_name",
                    "tool_args",
                    "content",
                    "time_before",
                    "time_after",
                )
            }
            expected = (
                {key: self.trace[index].get(key) for key in actual}
                if index < len(self.trace)
                else None
            )
            if actual != expected:
                trace_differences.append(
                    {"step": name, "actual": actual, "expected": expected}
                )
        if len(replayed) != len(self.trace):
            trace_differences.append(
                {"step_count": {"replay": len(replayed), "discovery": len(self.trace)}}
            )
        save(self.output / "fresh_replay_errors.json", replay_errors)
        save(self.output / "fresh_replay_trace_differences.json", trace_differences)
        worlds = [app for app in fresh.apps if isinstance(app, self.i["FarmWorldApp"])]
        harvested = {
            world.farm_id
            or world.name: sum(
                s.harvested for s in world.physics.yield_recovery.states.values()
            )
            for world in worlds
        }
        warehouse = getattr(getattr(fresh, "farm_environment", None), "warehouse", None)
        stored = (
            warehouse.get_inventory()["warehouse_grain_kg"]
            if warehouse is not None
            else sum(world._inventory.warehouse_grain_kg for world in worlds)
        )
        complete = all(
            sum(
                state.harvested
                for state in world.physics.yield_recovery.states.values()
            )
            == world.num_ridges
            for world in worlds
        )
        safely_stored = {world.farm_id or world.name: set() for world in worlds}
        storage_warnings = []
        if warehouse is not None:
            for batch in warehouse.grain_batches.values():
                if (
                    batch.status == "stored"
                    and batch.moisture_pct is not None
                    and batch.moisture_pct <= warehouse._storage_limit(batch) + 1e-9
                ):
                    safely_stored[batch.origin_farm_id].update(batch.ridge_ids)
            storage_complete = all(
                safely_stored[world.farm_id or world.name]
                == set(range(world.num_ridges))
                for world in worlds
            ) and all(
                batch.status == "stored" for batch in warehouse.grain_batches.values()
            )
        else:
            for record in self.trace:
                receipt = record.get("content")
                if record["tool_name"].endswith("__store_grain") and isinstance(
                    receipt, dict
                ):
                    if receipt.get("warning"):
                        storage_warnings.append(receipt["warning"])
                    elif float(receipt.get("moved_kg", 0)) > 0:
                        safely_stored[worlds[0].farm_id or worlds[0].name].update(
                            receipt.get("batch_ridge_ids", [])
                        )
            storage_complete = (
                all(
                    safely_stored[world.farm_id or world.name]
                    == set(range(world.num_ridges))
                    and world._inventory.harvest_grain_kg <= 0.01
                    for world in worlds
                )
                and not storage_warnings
            )
        bin_empty = all(
            float(getattr(app, "_grain_bin_kg", 0)) <= 0.01 for app in fresh.apps
        )
        return {
            "replay_exact_physical_state": discovery_hash == replay_hash,
            "discovery_state_hash": discovery_hash,
            "replay_state_hash": replay_hash,
            "harvested_ridges": harvested,
            "warehouse_grain_kg": stored,
            "replay_exact_tool_trace_and_time": not trace_differences,
            "replay_error_count": len(replay_errors),
            "safely_stored_ridges": {
                key: len(value) for key, value in safely_stored.items()
            },
            "safe_storage_complete": storage_complete,
            "combine_bins_empty": bin_empty,
            "initial_state_adjustments": getattr(
                self.scenario, "initial_state_adjustments", []
            ),
            "compiled_steps": len(self.workflow),
            "management_review_notes": self.review_notes,
            "management_doses": "preserved from source; requires agronomic necessity/rate review",
            "completion": (
                "feasible_operational_reference"
                if complete
                and storage_complete
                and bin_empty
                and not replay_errors
                and not trace_differences
                and discovery_hash == replay_hash
                else "incomplete"
            ),
        }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--source-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    p.add_argument("--scenario", required=True)
    p.add_argument("--wofost-config", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    root = args.source_root.resolve()
    sys.path.insert(0, str(root))
    from fairy.controllers.engine import Engine
    from fairy.scenarios.registry import get_scenario_class
    from fairy.scenarios.workflow import Workflow, WorkflowStep
    from fairy.agents.agent.toolset_builder import build_toolset
    from fairy.apps.farm_world import FarmWorldApp, WeatherApp, SensorApp
    from fairy.apps.system import SystemApp

    imports = locals()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    config = json.loads(args.wofost_config.read_text())
    compiler = None
    before = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "fairy").rglob("*.py"))
    }
    save(out / "source_before.json", before)
    try:
        original_engine = Engine(
            agent=None, scenario=get_scenario_class(args.scenario)()
        )
        source = original_engine.build_oracle_workflow(run_oracle=False)
        source.save_workflow(str(out / "original_workflow.json"))
        save(
            out / "provenance.json",
            {
                "scenario_id": args.scenario,
                "source_root": str(root),
                "raw_workflow_sha256": digest(source.to_dict()),
                "wofost_config": config,
                "policy_input": "Registered public tool responses only; raw physical/native states are verification only",
                "compiler_sha256": hashlib.sha256(
                    Path(__file__).read_bytes()
                ).hexdigest(),
            },
        )
        compiler = ObservedCompiler(args.scenario, config, out, imports)
        provenance = json.loads((out / "provenance.json").read_text())
        provenance["initial_state_adjustments"] = getattr(
            compiler.scenario, "initial_state_adjustments", []
        )
        save(out / "provenance.json", provenance)
        result = compiler.compile(source)
    except Exception as exc:
        message = str(exc)
        blocked = any(
            term in message
            for term in (
                "requires explicit cultivar",
                "rotations/replanting",
                "new native season",
                "parameter 'NOTINF'",
            )
        )
        result = {
            "completion": (
                "model_unsupported" if blocked else "requires_management_review"
            ),
            "exception_type": type(exc).__name__,
            "message": message,
            "traceback": traceback.format_exc(),
        }
    if compiler is not None:
        save(out / "discovery_trace.json", compiler.trace)
        save(out / "changes.json", compiler.changes)
        compiler.workflow.save_workflow(str(out / "partial_workflow.json"))
    after = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "fairy").rglob("*.py"))
    }
    save(out / "source_after.json", after)
    result["source_changed_during_run"] = [
        key
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key)
    ]
    if result["source_changed_during_run"]:
        result["completion_before_source_check"] = result["completion"]
        result["completion"] = "provisional_source_changed"
    save(out / "summary.json", {"scenario_id": args.scenario, **result})
    print(
        json.dumps(
            {
                "scenario_id": args.scenario,
                **{k: v for k, v in result.items() if k != "traceback"},
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
