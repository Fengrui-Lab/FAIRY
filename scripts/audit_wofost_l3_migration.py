"""Inventory the formal L3 pool without executing any farming tool or daily tick.

This is a migration readiness audit, not a WOFOST replay or a success claim.
The original oracle graph is captured with run_oracle=False so its declared
seed plan, fixed waiting calls and replanting operations can be inspected.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib
import inspect
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from fairy.apps.farm_world import FarmWorldApp
from fairy.controllers.engine import Engine
from fairy.physics.wofost_backend import WofostBackend
from fairy.scenarios.registry import get_scenario_class, list_scenarios


def _relative(path: str | Path) -> str:
    return str(Path(path).resolve().relative_to(REPO_ROOT))


def _seconds(arguments: dict) -> float:
    return sum(float(arguments.get(key, 0) or 0) * multiplier for key, multiplier in (
        ("days", 86400), ("hours", 3600), ("minutes", 60), ("seconds", 1)
    ))


def inspect_scenario(scenario_id: str) -> dict:
    cls = get_scenario_class(scenario_id)
    module = importlib.import_module(cls.__module__)
    spec = getattr(module, "SPEC", None)
    scenario = cls(crop_backend="legacy", crop_backend_options={})
    workflow = Engine(agent=None, scenario=scenario).build_oracle_workflow(run_oracle=False)
    farm = scenario.get_typed_app(FarmWorldApp)
    calls = [{"step": name, "tool": step.tool_name, "arguments": step.tool_args}
             for name, step in workflow.dag.items() if step.tool_name]
    seeds = sorted({call["arguments"]["seed_type"] for call in calls
                    if call["tool"].endswith("__load_seeds")})
    waits = [{**call, "duration_days": _seconds(call["arguments"]) / 86400}
             for call in calls if call["tool"].endswith("__advance_time")]
    replant_calls = [call for call in calls if call["tool"].endswith("__replant_seeds")]
    planted = sum(bool(farm.get_ridge(i).planted) for i in range(farm.num_ridges))
    emerged = sum(bool(state.emerged) for state in farm.physics.phenology.states.values())
    flags = ["fixed_oracle_calendar_requires_native_stage_and_harvest_review",
             "same_backend_oracle_baseline_required"]
    if replant_calls:
        flags.append("current_native_adapter_rejects_second_planting")
    if any(seed != "HEINONG84" for seed in seeds):
        flags.append("named_native_cultivar_parameters_needed_beyond_complete_heinong84")
    if len(seeds) > 1:
        flags.append("multiple_native_cultivar_profiles_needed_in_one_season")
    if "micronutrient" in scenario_id or "potassium" in scenario_id:
        flags.append("non_nitrogen_nutrient_stress_not_native_to_current_nwlp_model")
    if "rhizobia" in scenario_id:
        flags.append("nodulation_failure_proxy_needs_native_nfix_mapping")
    if any(word in scenario_id for word in ("density", "dense_canopy")):
        flags.append("density_currently_scales_initial_tdwi_only")
    if any(word in scenario_id for word in ("cold", "crusting", "establishment", "stand", "skip_rows")):
        flags.append("legacy_cold_wet_stand_loss_not_equivalent_in_native_branch")
    if spec and (spec.prior_histories or spec.custom_histories):
        flags.append("prior_history_effects_need_native_parameter_or_retained_coupling_review")
    if spec and spec.hydraulic_modifiers:
        flags.append("legacy_drainage_rates_not_direct_native_cwb_parameters")
    if spec and spec.seed_growth_overrides:
        flags.append("legacy_seed_growth_overrides_do_not_override_native_crop_parameters")
    ranges = {
        "declared_soil_vwc": [min(farm.get_ridge(i).soil_vwc for i in range(farm.num_ridges)),
                              max(farm.get_ridge(i).soil_vwc for i in range(farm.num_ridges))],
        "physics_root_vwc_before_first_tick": [min(s.root_vwc for s in farm.physics.soil.states.values()),
                                               max(s.root_vwc for s in farm.physics.soil.states.values())],
        "nutrient_index": [min(farm.get_ridge(i).nutrient_index for i in range(farm.num_ridges)),
                           max(farm.get_ridge(i).nutrient_index for i in range(farm.num_ridges))],
    }
    return {
        "scenario_id": scenario_id,
        "source_path": _relative(inspect.getsourcefile(cls)),
        "source_line": inspect.getsourcelines(cls)[1],
        "structure": "catalog_spec_wrapper" if spec else "standalone",
        "initial_backend": farm.physics.crop_backend_name,
        "initial_ridge_count": farm.num_ridges,
        "initial_planted_count": planted,
        "initial_emerged_count": emerged,
        "initial_stage_counts": dict(Counter(str(farm.get_ridge(i).growth_stage)
                                             for i in range(farm.num_ridges))),
        "native_start_group": "pre_sowing" if planted == 0 else
                              "growing_requires_native_history_or_checkpoint",
        "cultivars": seeds,
        "multiple_cultivars": len(seeds) > 1,
        "has_replanting": bool(replant_calls),
        "replant_tool_calls": replant_calls,
        "declared_spec_waits_days": dict(spec.waits) if spec else None,
        "declared_spec_waits_total_days": sum(spec.waits.values()) if spec else None,
        "declared_planting_zones": [vars(zone) for zone in spec.planting_zones] if spec else None,
        "explicit_advance_time_total_days": sum(wait["duration_days"] for wait in waits),
        "explicit_advance_time_calls": waits,
        "captured_oracle_tool_call_count": len(calls),
        "initial_state_ranges": ranges,
        "migration_review_flags": flags,
        "native_replay_status": "not_run_by_this_audit",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path,
                        default=REPO_ROOT / "scripts/fullseason/formal_90_scenario_ids.txt")
    parser.add_argument("--output", type=Path,
                        default=REPO_ROOT / "validation_runs/wofost_l3_migration_20261021/inventory.json")
    args = parser.parse_args()
    ids = [line.strip() for line in args.manifest.read_text().splitlines()
           if line.strip() and not line.lstrip().startswith("#")]
    if len(ids) != len(set(ids)):
        raise ValueError("Scenario manifest contains duplicate IDs")
    rows = [inspect_scenario(scenario_id) for scenario_id in ids]
    counts = {
        "formal_scenarios": len(rows),
        "catalog_spec_wrappers": sum(row["structure"] == "catalog_spec_wrapper" for row in rows),
        "standalone_scenarios": sum(row["structure"] == "standalone" for row in rows),
        "pre_sowing": sum(row["initial_planted_count"] == 0 for row in rows),
        "growing_initial_state": sum(row["initial_planted_count"] > 0 for row in rows),
        "multiple_cultivars": sum(row["multiple_cultivars"] for row in rows),
        "heinong84_only": sum(row["cultivars"] == ["HEINONG84"] for row in rows),
        "replanting": sum(row["has_replanting"] for row in rows),
        "cultivar_scenario_counts": dict(Counter(seed for row in rows for seed in row["cultivars"])),
        "migration_review_flag_counts": dict(Counter(flag for row in rows
                                                     for flag in row["migration_review_flags"])),
    }
    registered = list_scenarios()
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest": _relative(args.manifest),
        "method": "Original scenario setup plus Engine.build_oracle_workflow(run_oracle=False); inspect initial state and captured tool arguments only.",
        "farming_tool_calls_executed": False,
        "daily_physics_ticks_executed": False,
        "native_replays_executed": False,
        "migration_success_claimed": False,
        "review_flags_note": "Flags combine captured tool evidence, structured ScenarioSpec fields and scenario-name screening; they are review prompts, not an exhaustive proof of mechanism coverage.",
        "scope_note": "Current formal 90 L3 pool; legacy registered full-season scenarios are listed separately, not silently included.",
        "counts": counts,
        "replant_scenario_ids": [row["scenario_id"] for row in rows if row["has_replanting"]],
        "outside_formal_pool_registered_fullseason_ids": [
            scenario_id for scenario_id in registered if scenario_id not in ids and
            ("full_season" in scenario_id or "fullseason" in scenario_id)],
        "code_references": {
            "fixed_waits": "fairy/scenarios/farm_world_fullseason_v2/harbin_l3_batch_scenario.py:495",
            "native_replant_guard": f"fairy/physics/wofost_backend.py:{inspect.getsourcelines(WofostBackend.queue_actions)[1]}",
            "native_specification": f"fairy/physics/wofost_backend.py:{inspect.getsourcelines(WofostBackend._specification)[1]}",
        },
        "scenarios": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "counts": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
