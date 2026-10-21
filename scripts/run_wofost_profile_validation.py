"""Discover observed harvest readiness, then validate its static replay.

The source scenario and all original tools/arguments/order are retained. A first
world runs the unchanged prefix and calls registered state/time tools until all
64 ridges report R8, grain is dry enough, and weather/soil observations permit
harvesting. Those observed calls become an explicit workflow. A second,
fresh world replays that ordinary workflow through the existing strict L3 audit.
The source fixed-calendar result remains a separate artifact and may fail.
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from fairy.apps.farm_world import FarmWorldApp
from fairy.apps.farm_world.weather_app import _MAX_VWC_TRAFFIC
from fairy.controllers import engine as engine_module
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.workflow import Workflow, WorkflowStep
from run_wofost_l3_comparison import ReplayAudit, _safe, _tool_errors, _workflow_hash, _write_json, run_case


DEFAULT_SCENARIOS = (
    "scenario_full_season_hb_base_hn84_std_normal",
    "scenario_full_season_hb_dryr5r6_hn84_water_limit",
)


def _copy_step(step: WorkflowStep, **changes):
    values = {
        "name": step.name, "content": copy.deepcopy(step.content),
        "op_type": step.op_type, "tool_name": step.tool_name,
        "tool_args": copy.deepcopy(step.tool_args),
        "depends_on": list(step.depends_on), "time": step.time,
    }
    values.update(changes)
    return WorkflowStep(**values)


def discover_workflow(scenario_id: str, source: Workflow, config: dict,
                      output_dir: Path, *, maturity_only: bool = False) -> tuple[Workflow, dict]:
    original_items = list(source.dag.items())
    first_harvest = next(i for i, (_, step) in enumerate(original_items)
                         if step.tool_name == "TractorApp__harvest")
    prefix = Workflow()
    for _, step in original_items[:first_harvest]:
        prefix.add_node(_copy_step(step))
    scenario = get_scenario_class(scenario_id)(crop_backend="wofost", crop_backend_options=config)
    engine = Engine(agent=None, scenario=scenario)
    scenario.setup()
    engine._register_scenario_apps()
    farm = scenario.get_typed_app(FarmWorldApp)
    if farm.physics.weather_generator is None:
        raise RuntimeError("Adaptive discovery requires the scenario's existing daily weather generator")
    audit = ReplayAudit(engine, prefix, output_dir)
    inserted = []
    observations = []
    deadline = engine.start_time + float(scenario.duration)
    previous_name = original_items[first_harvest - 1][0]

    with audit.instrument():
        replayed_prefix = engine.replay_workflow(prefix)
        _, _, tools = engine_module.build_toolset(list(scenario.apps or []))

        def execute_inserted(name: str, tool_name: str, arguments: dict):
            nonlocal previous_name
            step = WorkflowStep(name=name, tool_name=tool_name,
                                tool_args=arguments, depends_on=[previous_name])
            audit._source_tools.append((name, step))
            content = tools[tool_name](**arguments)
            if _tool_errors(content):
                raise RuntimeError(f"Discovery tool {name} failed: {content}")
            inserted.append(step)
            replayed_prefix.add_node(_copy_step(step, content=content,
                                                time=engine._env_time_str()))
            previous_name = name
            return content

        poll = 0
        while True:
            observed = execute_inserted(f"v_maturity_observe_{poll:03d}",
                                        "FarmWorldApp__get_ridge_range_state",
                                        {"start": 0, "end": 63})
            ridges = observed.get("ridges", [])
            all_r8 = (len(ridges) == 64 and
                      {r.get("ridge_id") for r in ridges} == set(range(64)) and
                      all(r.get("growth_stage") == "R8" for r in ridges))
            weather = execute_inserted(f"v_weather_observe_{poll:03d}",
                                       "WeatherApp__get_current_weather", {})
            soil = execute_inserted(f"v_soil_observe_{poll:03d}",
                                    "SensorApp__read_soil_sensors", {})
            soil_sensors = soil.get("soil_sensors", [])
            # Readiness uses real agent observations. The harvest tool then
            # independently checks exact field-average soil water and all
            # operational gates on the second-world replay.
            moisture_ok = len(ridges) == 64 and all(
                r.get("grain_moisture_pct", 100) <= 18.0 for r in ridges)
            dry_weather = weather.get("rainfall_mm", 1) == 0
            observed_trafficable = bool(soil_sensors) and all(
                s.get("vwc", 1) <= _MAX_VWC_TRAFFIC for s in soil_sensors)
            harvest_ready = all_r8 and moisture_ok and dry_weather and observed_trafficable
            observations.append({"poll": poll, "sim_timestamp": engine.time_manager.time(),
                                 "all_64_observed_r8": all_r8,
                                 "all_grain_at_most_18_percent": moisture_ok,
                                 "rain_free": dry_weather,
                                 "observed_soil_trafficable": observed_trafficable,
                                 "observed_harvest_ready": harvest_ready,
                                 "ridge_observation": observed,
                                 "weather_observation": weather,
                                 "soil_observation": soil})
            if (all_r8 if maturity_only else harvest_ready):
                break
            if engine.time_manager.time() + 86400 > deadline:
                raise RuntimeError("No observed harvest readiness within the original scenario duration")
            execute_inserted(f"v_maturity_wait_{poll:03d}",
                             "SystemApp__advance_time", {"days": 1})
            poll += 1

    augmented = Workflow()
    for index, (_, step) in enumerate(original_items):
        if index == first_harvest:
            for extra in inserted:
                augmented.add_node(_copy_step(extra))
            augmented.add_node(_copy_step(step, depends_on=list(step.depends_on) + [inserted[-1].name]))
        else:
            augmented.add_node(_copy_step(step))
    output_dir.mkdir(parents=True, exist_ok=True)
    replayed_prefix.save_workflow(str(output_dir / "discovery_replay.json"))
    augmented.save_workflow(str(output_dir / "augmented_workflow.json"))
    _write_json(output_dir / "planning_observations.json", observations)
    _write_json(output_dir / "discovery_errors.json", {
        "tool_errors": [r for r in audit.calls if r["status"] != "ok"],
        "storage_warnings": audit.storage_warnings})
    if audit.daily_rows:
        with (output_dir / "daily.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(audit.daily_rows[0]))
            writer.writeheader()
            writer.writerows(audit.daily_rows)
    details = {
        "policy": "Observed maturity/readiness polling then static fresh replay; no forced states, weather replacement, maturity extrapolation, or core/scenario edits.",
        "maturity_only": maturity_only,
        "source_scenario_id": scenario_id,
        "source_tool_contract_sha256": _workflow_hash(source),
        "augmented_tool_contract_sha256": _workflow_hash(augmented),
        "original_tool_calls": sum(bool(s.tool_name) for _, s in original_items),
        "inserted_tool_calls": len(inserted),
        "inserted_wait_days": poll,
        "all_64_observed_r8": observations[-1]["all_64_observed_r8"],
        "observed_harvest_ready": observations[-1]["observed_harvest_ready"],
        "readiness_condition": "64 observed R8; every ridge grain moisture <=18%; current rain=0; every observed soil sensor VWC <=0.40; native harvest tool independently enforces all existing gates.",
        "final_discovery_timestamp": engine.time_manager.time(),
        "original_scenario_deadline": deadline,
        "existing_weather_generator": type(farm.physics.weather_generator).__name__,
        "discovery_original_prefix_calls": first_harvest,
        "original_calls_preserved_in_order": [
            (name, step.tool_name, step.tool_args) for name, step in augmented.dag.items()
            if name in source.dag] == [
            (name, step.tool_name, step.tool_args) for name, step in original_items],
        "scope_limit": "Earlier management timing is unchanged; this validates harvest adaptation only. Literature parameter transfer is not field calibration.",
    }
    _write_json(output_dir / "planning_summary.json", details)
    return augmented, details


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wofost-config", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True,
                        help="Directory containing each scenario's original canonical_workflow.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--scenario", action="append")
    parser.add_argument("--maturity-only", action="store_true",
                        help="Stop at observed R8, allowing existing wet-grain or weather gates to reject harvest")
    args = parser.parse_args()
    config = json.loads(args.wofost_config.read_text())
    if not isinstance(config, dict):
        parser.error("--wofost-config must contain an object")
    results = []
    for sid in args.scenario or DEFAULT_SCENARIOS:
        source_path = args.source_root / sid / "canonical_workflow.json"
        source = Workflow.load_workflow(str(source_path))
        case_dir = args.output_dir / sid
        augmented, plan = discover_workflow(sid, source, config, case_dir / "discovery",
                                            maturity_only=args.maturity_only)
        summary = run_case(sid, "wofost", augmented, output_dir=case_dir / "wofost",
                           backend_options=config)
        summary["adaptive_harvest"] = {**plan, "source_workflow": str(source_path.resolve()),
                                      "discovery_directory": str((case_dir / "discovery").resolve())}
        summary["strict_checks"]["all_original_calls_preserved_in_order"] = plan["original_calls_preserved_in_order"]
        summary["strict_checks"]["inserted_waits_discovered_from_observed_r8"] = plan["all_64_observed_r8"]
        if not args.maturity_only:
            summary["strict_checks"]["observed_harvest_readiness_before_harvest"] = plan["observed_harvest_ready"]
        summary["strict_success"] = all(summary["strict_checks"].values())
        _write_json(case_dir / "wofost" / "summary.json", summary)
        results.append(summary)
        print(json.dumps({"scenario_id": sid, "strict_success": summary["strict_success"],
                          "inserted_wait_days": plan["inserted_wait_days"],
                          "metrics": summary["metrics"], "counts": summary["counts"]},
                         ensure_ascii=False), flush=True)
    _write_json(args.output_dir / "adaptive_validation_summary.json", {
        "runs": results, "all_strict_success": all(r["strict_success"] for r in results),
        "scope": "Harvest timing adaptation; fixed-calendar results are retained separately."})
    return 0 if all(r["strict_success"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
