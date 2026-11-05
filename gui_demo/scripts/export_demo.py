"""Export an audited, passive replay for the two-crop GUI demo.

Run with PYTHONDONTWRITEBYTECODE=1 and PYTHONHASHSEED=0. This script uses
the Python API directly, never the CLI cleanup paths. The output directory
must be absent or empty. Existing files are never replaced or removed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import mean
import sys
import time


SCENARIO_ID = "scenario_two_farm_soybean_maize_disease_water"
SCHEMA_VERSION = "fairy-gui-demo/1"
IGNORED_RANDOM_IDS = {"action_id", "op_id", "mission_id", "inspection_id"}
TARGET_RIDGES = set(range(20, 40))
DEVICE_FIELDS = (
    "name", "seed_type", "equipment", "_fuel_tank_l", "_pesticide_tank_l",
    "_fungicide_tank_l", "_fertilizer_spreader_kg", "_seed_hopper",
    "_grain_bin_kg", "_attached_implement", "source_farm_id",
    "grain_origin_farm_id", "_grain_cultivar_ids", "_grain_ridge_ids",
    "_grain_moistures_pct", "_operation_log", "_battery_pct", "_charging",
    "_charge_started_at", "_charge_complete_at", "_charge_start_battery_pct",
    "_mission_log", "_inspection_log", "speed_ms", "effective_ridges_per_pass",
    "takeoff_overhead_s", "min_battery_pct", "battery_pct_per_ridge",
)
METHOD_TITLES = {
    "get_farm_overview": "Review farm plot", "get_management_status": "Review management",
    "get_ridge_state": "Review ridge", "get_ridge_range_state": "Review crop stage",
    "get_crop_capabilities": "Review crop requirements", "get_current_weather": "Check weather",
    "get_forecast": "Check rainfall forecast", "read_soil_sensors": "Read soil sensors",
    "read_soil_sensor": "Read soil sensor", "read_canopy_sensors": "Read canopy sensors",
    "read_canopy_sensor": "Read canopy sensor", "fly_survey": "Survey crop canopy",
    "inspect_crop_health": "Inspect crop health", "inspect_pests": "Inspect pests",
    "inspect_emergence": "Inspect emergence", "inspect_ridge": "Inspect ridge",
    "get_status": "Check tractor", "check_status": "Check device", "get_inventory": "Check inventory",
    "get_grain_batches": "Review grain batches", "get_irrigation_log": "Review irrigation",
    "get_current_time": "Check simulation time", "advance_time": "Advance shared time",
    "wait_for_notification": "Wait for notification", "charge": "Charge shared device",
    "refuel": "Refuel tractor", "load_seeds": "Load crop seeds", "load_fertilizer": "Load fertilizer",
    "load_fungicide": "Load fungicide", "load_pesticide": "Load pesticide",
    "refill_pesticide_tank": "Refill pesticide tank", "return_supplies": "Return unused supplies",
    "attach_implement": "Attach implement", "detach_implement": "Detach implement",
    "level": "Level soil", "base_fertilize": "Apply base fertilizer", "form_ridges": "Form ridges",
    "plant_seeds": "Sow crop", "replant_seeds": "Replant crop", "apply_fertilizer": "Apply fertilizer",
    "apply_fertigation": "Apply fertigation", "apply_fungicide": "Treat soybean disease",
    "apply_pesticide": "Apply pesticide", "spray_pesticide": "Spray pesticide",
    "apply_herbicide": "Apply herbicide", "mechanical_weed_control": "Control weeds",
    "incorporate_residue": "Incorporate crop residue", "irrigate": "Irrigate target ridges",
    "harvest": "Harvest crop", "unload_grain": "Unload traced grain batch",
    "dry_grain": "Dry grain batch", "store_grain": "Store grain batch",
    "send_message_to_user": "Report completion", "send_message_to_agent": "Deliver task briefing",
    "commit_daily_physics": "Advance shared crop day",
}


def plain(value):
    """Encode stored values without invoking app state getters."""
    if isinstance(value, Enum):
        return plain(value.value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Captured state contains a non-finite value")
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [plain(item) for item in sorted(value, key=str)]
    if type(value).__module__.startswith("numpy"):
        return plain(value.tolist())
    raise TypeError(f"Unsupported stored value: {type(value).__name__}")


def json_text(value, pretty=False):
    return json.dumps(plain(value), ensure_ascii=False, sort_keys=True, allow_nan=False,
                      indent=2 if pretty else None,
                      separators=None if pretty else (",", ":"))


def selected(obj, names):
    return {key: plain(vars(obj)[key]) for key in names if key in vars(obj)}


def rng_state(scene):
    result = {app.name: plain(app.rng.getstate()) for app in scene.apps if hasattr(app, "rng")}
    for farm in (scene.soybean, scene.maize):
        for label in ("observation_model", "weather_generator"):
            obj = vars(farm._physics).get(label)
            generator = vars(obj).get("rng") if obj is not None else None
            if generator is not None:
                if hasattr(generator, "getstate"):
                    result[f"{farm.farm_id}:{label}"] = plain(generator.getstate())
                elif hasattr(generator, "bit_generator"):
                    result[f"{farm.farm_id}:{label}"] = plain(generator.bit_generator.state)
    return result


def audit_snapshot(scene, clock):
    """Read raw world, physics, resource, device and random state passively."""
    farms = {}
    for farm in (scene.soybean, scene.maize):
        data = selected(farm, (
            "farm_id", "name", "crop_type", "crop_id", "cultivar_id", "num_ridges",
            "field_length_m", "ridge_width_m", "rows_per_ridge", "_ridges",
            "_management_regime", "_sim_date", "_season_phase", "_field_preparation_ops",
            "_planting_windows", "_pending_irrigation", "_field_geometry_cache",
        ))
        physics = vars(farm).get("_physics")
        if physics is not None:
            state = selected(physics, (
                "engines_active", "last_physics_sim_time", "crop_backend_name",
                "action_log", "pending_management_actions_by_ridge",
                "pending_treatments_by_ridge", "pending_harvest_actions_by_ridge",
                "profile", "scenario_metadata",
            ))
            state["engines"] = {
                name: selected(vars(physics)[name], ("states", "params", "hydraulic_modifiers"))
                for name in ("soil", "phenology", "canopy", "biotic", "management", "yield_recovery")
            }
            state["observation"] = selected(physics.observation_model, ("assets", "_product_counter", "params"))
            generator = vars(physics).get("weather_generator")
            if generator is not None:
                state["weather_generator"] = selected(generator, ("config", "_day_cache", "_day_overrides"))
            data["physics"] = state
        farms[farm.farm_id] = data
    timestamp = clock.time()
    return {
        "timestamp": timestamp,
        "datetime": datetime.fromtimestamp(timestamp, scene.farm_environment.simulation_timezone).isoformat(),
        "farms": farms,
        "devices": {app.name: selected(app, DEVICE_FIELDS) for app in scene.shared_equipment},
        "warehouse": selected(scene.warehouse, (
            "name", "stock", "grain_batches", "_drying_usage_by_date", "storage_capacity_kg",
            "drying_capacity_kg_per_day", "max_storage_moisture_pct",
        )),
        "weather": selected(scene.weather, ("_weather", "_avg_soil_vwc")),
        "fixed_facilities": {
            app.name: selected(app, ("name", "bound_farm_id", "_sensor_zones", "_soil_sensors",
                                    "_canopy_sensors", "_irrigation_log"))
            for app in (scene.soybean_sensor, scene.maize_sensor, scene.soybean_irrigation, scene.maize_irrigation)
        },
        "random_state": rng_state(scene),
    }


def compact_frame(audit, index):
    farms = {}
    for farm_id, stored in audit["farms"].items():
        physics = stored.get("physics") or {}
        initialized = physics.get("last_physics_sim_time") is not None
        engines = physics.get("engines", {})
        ridges = []
        for original in stored["_ridges"]:
            rid = str(original["ridge_id"])
            soil = engines.get("soil", {}).get("states", {}).get(rid, {}) if initialized else {}
            biotic = engines.get("biotic", {}).get("states", {}).get(rid, {}) if initialized else {}
            management = engines.get("management", {}).get("states", {}).get(rid, {}) if initialized else {}
            ridges.append({
                "ridge_id": original["ridge_id"], "planted": original["planted"],
                "harvested": original["harvested"], "growth_stage": original["growth_stage"],
                "soil_vwc": soil.get("top_vwc", original["soil_vwc"]),
                "root_vwc": soil.get("root_vwc", original["soil_vwc"]),
                "disease_pressure": biotic.get("disease_pressure", original["disease_pressure"]),
                "pest_pressure": biotic.get("insect_pressure", original["pest_pressure"]),
                "nutrient_index": management.get("nutrient_index", original["nutrient_index"]),
                "grain_moisture_pct": original["grain_moisture_pct"],
                "stand_fraction": management.get("stand_fraction", original["stand_fraction"]),
            })
        def stats(rows):
            return {key: mean(row[key] for row in rows)
                    for key in ("soil_vwc", "root_vwc", "disease_pressure", "pest_pressure", "nutrient_index")}
        farms[farm_id] = {
            "ridges": ridges, "management": stored["_management_regime"],
            "physics_initialized": initialized,
            "stats": {"all": stats(ridges), "target": stats([r for r in ridges if r["ridge_id"] in TARGET_RIDGES]),
                      "other": stats([r for r in ridges if r["ridge_id"] not in TARGET_RIDGES]),
                      "planted_ridges": sum(r["planted"] for r in ridges),
                      "harvested_ridges": sum(r["harvested"] for r in ridges)},
        }
    # Full growing logs remain in the gzip audit. Compact device values are stored raw attributes.
    devices = {name: {key: value for key, value in state.items()
                      if key not in {"_operation_log", "_mission_log", "_inspection_log"}}
               for name, state in audit["devices"].items()}
    return {"index": index, "timestamp": audit["timestamp"], "datetime": audit["datetime"],
            "farms": farms, "devices": devices, "warehouse": audit["warehouse"],
            "weather": audit["weather"], "fixed_facilities": audit["fixed_facilities"]}


def category_of(tool):
    method = tool.split("__", 1)[-1]
    if method in {"advance_time", "wait_for_notification", "commit_daily_physics"}:
        return "wait"
    if method.startswith("send_message"):
        return "report"
    if method.startswith("inspect_"):
        return "diagnose"
    if method.startswith(("get_", "read_", "check_")) or method == "fly_survey":
        return "observe"
    if method.startswith(("load_", "refill_", "attach_", "detach_")) or method in {
        "charge", "refuel", "return_supplies", "unload_grain", "dry_grain", "store_grain",
    }:
        return "resource"
    return "act"


def scope_of(tool, arguments, result, scene, fixed_targets):
    app = tool.split("__", 1)[0]
    farm_ids = [scene.soybean.farm_id, scene.maize.farm_id]
    shared = app in {item.name for item in scene.shared_equipment} | {scene.warehouse.name}
    global_actor = app in {scene.system.name, scene.weather.name, scene.aui.name}
    actor_scope = "shared" if shared else "global" if global_actor else "fixed"
    batch = result.get("batch", {}) if isinstance(result, dict) else {}
    target = (arguments.get("farm_id") or fixed_targets.get(app)
              or (result.get("farm_id") if isinstance(result, dict) else None)
              or (batch.get("origin_farm_id") if isinstance(batch, dict) else None))
    if target not in farm_ids and arguments.get("batch_id"):
        existing = vars(scene.warehouse)["grain_batches"].get(arguments["batch_id"])
        target = vars(existing).get("origin_farm_id") if existing is not None else None
    return {"kind": "farm_plot" if target in farm_ids else "global" if global_actor else "shared",
            "farm_ids": [target] if target in farm_ids else farm_ids,
            "world_farm_ids": farm_ids, "actor_app": app, "actor_scope": actor_scope}


def normalized(value):
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items() if key not in IGNORED_RANDOM_IDS}
    if isinstance(value, list):
        return [normalized(item) for item in value]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Destination data directory; must be absent or empty.")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if os.environ.get("PYTHONHASHSEED") != "0":
        parser.error("Launch with PYTHONHASHSEED=0 for reproducible reference comparisons.")
    sys.dont_write_bytecode = True
    repo, output = args.repo.expanduser().resolve(), args.output_dir.expanduser().resolve()
    if not (repo / "fairy/scenarios/two_farm" / f"{SCENARIO_ID}.py").is_file():
        parser.error("--repo must point to the FAIRY checkout containing the selected scenario.")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error("Output must be absent or empty; existing files are preserved.")
    sys.path.insert(0, str(repo))
    import fairy
    if not Path(fairy.__file__).resolve().is_relative_to(repo):
        raise RuntimeError("Imported FAIRY does not belong to --repo")
    from fairy.controllers.engine import Engine
    from fairy.agents.agent.toolset_builder import build_toolset
    from fairy.controllers.agent_builder import FARM_AGENT_HIDDEN_TOOL_NAMES
    from fairy.scenarios.two_farm.scenario_two_farm_soybean_maize_disease_water import (
        ScenarioTwoFarmSoybeanMaizeDiseaseWater,
    )

    def fresh():
        scene = ScenarioTwoFarmSoybeanMaizeDiseaseWater(seed=args.seed)
        scene.setup()
        return scene, Engine(None, scene)

    def write_json(name, value, pretty=False):
        with (output / name).open("x", encoding="utf-8") as stream:
            stream.write(json_text(value, pretty=pretty) + "\n")

    started = time.perf_counter()
    source, exporter = fresh()
    initial_source = audit_snapshot(source, exporter.time_manager)
    plan = exporter.run_scenario_oracle(False)
    assert audit_snapshot(source, exporter.time_manager) == initial_source, "Plan export changed initial state"
    assert len(plan) == 374, f"Reference changed: expected 374 events, received {len(plan)}"
    scene, engine = fresh()
    _, runtime_schemas, runtime_tools = build_toolset(list(scene.apps))
    _, agent_schemas, agent_tools = build_toolset(list(scene.apps), excluded_tool_names=FARM_AGENT_HIDDEN_TOOL_NAMES)
    fixed_targets = {}
    for farm, sensor, irrigation in ((scene.soybean, scene.soybean_sensor, scene.soybean_irrigation),
                                    (scene.maize, scene.maize_sensor, scene.maize_irrigation)):
        fixed_targets.update({app.name: farm.farm_id for app in (farm, sensor, irrigation)})
    initial = audit_snapshot(scene, engine.time_manager)
    records, frames = [], [compact_frame(initial, 0)]
    output.mkdir(parents=True, exist_ok=True)
    original_record = engine._record_run_log
    last_audit = initial
    with (output / "audit-snapshots.jsonl.gz").open("xb") as raw_stream:
        with gzip.GzipFile(fileobj=raw_stream, mode="wb", mtime=0) as snapshot_stream:
            snapshot_stream.write((json_text({"index": 0, "after_step_id": None, **initial}) + "\n").encode())

            def capture(**event):
                nonlocal last_audit
                original_record(**event)
                index = len(records) + 1
                before_rng = rng_state(scene)
                audit = audit_snapshot(scene, engine.time_manager)
                assert before_rng == rng_state(scene), "Passive capture changed a random stream"
                assert audit["timestamp"] == event["sim_time_after"], "Passive capture changed the clock"
                tool, arguments, result = event["tool_name"], plain(event["tool_args"] or {}), plain(event["content"])
                tz = scene.farm_environment.simulation_timezone
                records.append({
                    "sequence": index, "step_id": event["step_name"], "tool_name": tool,
                    "arguments": arguments, "result": result, "status": event["status"],
                    "error": event.get("error"), "time_before": event["sim_time_before"],
                    "time_after": event["sim_time_after"],
                    "datetime_before": datetime.fromtimestamp(event["sim_time_before"], tz).isoformat(),
                    "datetime_after": datetime.fromtimestamp(event["sim_time_after"], tz).isoformat(),
                    "scope": scope_of(tool, arguments, result, scene, fixed_targets),
                    "category": category_of(tool),
                    "title": METHOD_TITLES.get(tool.split("__", 1)[-1], tool.split("__", 1)[-1].replace("_", " ").capitalize()),
                    "snapshot_before": index - 1, "snapshot_after": index,
                })
                frames.append(compact_frame(audit, index))
                snapshot_stream.write((json_text({"index": index, "after_step_id": event["step_name"], **audit}) + "\n").encode())
                last_audit = audit
                if index % 50 == 0:
                    print(f"Captured {index}/{len(plan)} events", flush=True)

            engine._record_run_log = capture
            executed = engine.replay_workflow(plan)
    validation = engine.evaluate().to_dict()
    assert validation["success"], validation
    assert all(record["status"] == "ok" for record in records)
    assert len(records) == len(plan) == 374 and len(frames) == 375
    assert audit_snapshot(scene, engine.time_manager) == last_audit, "Validation changed state"

    print("Verifying against an uninstrumented replay...", flush=True)
    control_scene, control = fresh()
    control_workflow = control.replay_workflow(plan)
    assert normalized(plain(executed.to_dict())) == normalized(plain(control_workflow.to_dict())), "Capture changed tool results or timing"
    assert normalized(last_audit) == normalized(audit_snapshot(control_scene, control.time_manager)), "Capture changed the final state"
    assert control.evaluate().success

    counts = Counter(record["tool_name"] for record in records)
    examples = {}
    for record in records:
        examples.setdefault(record["tool_name"], record["result"])
    catalog = {"scenario_id": SCENARIO_ID, "runtime_count": len(runtime_schemas),
               "agent_exposed_count": len(agent_schemas), "used_count": len(counts),
               "runtime_only_names": sorted(set(runtime_tools) - set(agent_tools)),
               "tools": [{"name": schema["function"]["name"],
                          "app": schema["function"]["name"].split("__", 1)[0],
                          "exposed": schema["function"]["name"] in agent_tools,
                          "schema": schema, "use_count": counts[schema["function"]["name"]],
                          "category": category_of(schema["function"]["name"]), "output_schema": None,
                          "output_example": examples.get(schema["function"]["name"])}
                         for schema in runtime_schemas]}
    step_index = {record["step_id"]: record["sequence"] for record in records}
    milestones = {key: step_index[name] for key, name in {
        "disease_before": "disease_confirm_32", "disease_after": "disease_treat_30",
        "disease_followup": "disease_followup_32", "water_before": "drought_thermal",
        "water_after": "drought_irrigate", "water_followup": "drought_crop_recheck",
    }.items()}
    milestones["final"] = len(records)
    farms = [{"id": farm.farm_id, "label": scene.plot_labels[farm.farm_id],
              "crop_id": farm.crop_id, "cultivar_id": farm.cultivar_id,
              "num_ridges": farm.num_ridges, "field_length_m": farm.field_length_m,
              "ridge_width_m": farm.ridge_width_m, "rows_per_ridge": farm.rows_per_ridge,
              "area_m2": farm.field_geometry.planted_area_m2}
             for farm in (scene.soybean, scene.maize)]
    checks = {"all_calls_ok": True, "event_count_matches_reference": True,
              "plan_export_preserves_initial_state": True, "capture_preserves_rng_and_clock": True,
              "tool_results_and_timing_match_uninstrumented_run": True,
              "final_state_matches_uninstrumented_run": True, "validation_preserves_state": True,
              "no_llm_calls": True}
    availability = {
        "available": ["Original tool inputs/results", "Per-ridge simulation truth", "Observed soil and canopy values",
                      "Ridge-level drone NDVI and canopy temperature", "Ground detection confidence and coverage",
                      "Shared device and inventory state", "Crop-specific grain-batch provenance"],
        "not_produced": ["RGB or aerial photographs", "Thermal raster images", "Image bounding boxes or masks",
                         "Raw spectral bands", "Georeferenced plot polygons or GPS tracks", "Measured pesticide residue concentration",
                         "LLM or Jev reasoning for this Oracle replay"],
        "notes": ["Frames contain simulation truth; observations remain in event results.",
                  "Disease pressure is a model index, not a percentage of diseased leaves.",
                  "Both drone apps return NDVI and canopy temperature, not image assets.",
                  "Device attributes are stored values; charging getters are not called during capture.",
                  "Input schemas are official AppTool schemas; formal output schemas are not declared.",
                  "Before physics initialization, compact values use configured initial ridge fields."]}
    source_path = repo / "fairy/scenarios/two_farm" / f"{SCENARIO_ID}.py"
    manifest = {
        "schema_version": SCHEMA_VERSION, "scenario_id": SCENARIO_ID, "seed": args.seed,
        "farms": farms, "event_count": len(records), "frame_count": len(frames),
        "validation": validation, "milestones": milestones, "checks": checks,
        "start_datetime": frames[0]["datetime"], "end_datetime": frames[-1]["datetime"],
        "runtime_tool_count": len(runtime_schemas), "agent_exposed_tool_count": len(agent_schemas),
        "executed_tool_count": len(counts), "timezone": str(scene.farm_environment.simulation_timezone),
        "crop_backend": "legacy", "run_kind": "executed_oracle_reference", "availability": availability,
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "capture_policy": "Initial plus every post-tool global state, read from stored fields without observation calls.",
        "ignored_random_identifier_fields": sorted(IGNORED_RANDOM_IDS),
    }
    for filename, value in (("manifest.json", manifest), ("events.json", records), ("frames.json", frames),
                            ("tool-catalog.json", catalog), ("oracle-plan.json", plan.to_dict()),
                            ("executed-workflow.json", executed.to_dict()), ("availability.json", availability)):
        write_json(filename, value)
    write_json("checks.json", {**checks, "wall_seconds": round(time.perf_counter() - started, 3)}, pretty=True)
    write_json("file-manifest.json", {
        path.name: {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted(output.iterdir()) if path.is_file()
    }, pretty=True)
    print(json_text({"output_dir": str(output), "event_count": len(records), "frame_count": len(frames),
                     "runtime_tools": len(runtime_schemas), "agent_exposed_tools": len(agent_schemas),
                     "used_tools": len(counts), "milestones": milestones, "checks": checks}, pretty=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
