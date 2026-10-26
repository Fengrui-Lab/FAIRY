"""Run and independently replay rice seasons, with audit artifacts and no LLM."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fairy.apps.paddy.models import default_soil
from fairy.apps.paddy.world import PaddyWorldApp
from fairy.controllers.engine import Engine
from fairy.physics.rice_backend import RiceWofostBackend
from fairy.physics.simulation_unit import SimulationUnit
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.rice.rice_scenario_catalog import VARIANTS
from fairy.scenarios.rice.farm_checkpoint_state import checkpoint_labels, load_checkpoint, load_oracle_plan
from fairy.scenarios.rice.evaluation import build_baseline, compare_outcome


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def sensitivity():
    """One-factor sensitivity around the declared completion, not calibration."""
    weather = dict(tmin_c=23., tmax_c=31., humidity_pct=75., rain_mm=0., radiation_mj_m2=18., wind_ms=2.)
    results = []
    for overrides in ({}, {"AMAX_REF": 32.}, {"AMAX_REF": 48.}, {"KN": .3}, {"KN": .5}):
        backend = RiceWofostBackend(SimulationUnit("sensitivity", "paddy_plot", 1000.),
                                   "2026-01-01", default_soil(), weather, parameter_overrides=overrides)
        backend.apply("transplant", day="2026-01-01")
        backend.apply("puddle", sope_cm_day=1., ksub_cm_day=.2)
        for _ in range(220):
            if backend.water.states.SS < 2:
                backend.apply("water", amount_mm=40.)
            backend.apply("day", day=backend.model.day.isoformat(), weather=weather)
            if backend.maturity:
                break
        if not backend.maturity:
            raise RuntimeError("Rice sensitivity did not mature")
        results.append({"overrides": overrides, "crop": backend.crop_values,
                        "water": backend.water.audit(), "provenance": backend.provenance})
    return {"purpose": "engineering sensitivity, not field calibration", "weather": weather, "runs": results}


def run_variant(variant, output):
    scenario_id = f"scenario_rice_l3_{variant}"
    cls = get_scenario_class(scenario_id)
    reference = Engine(None, cls())
    workflow = reference.run_scenario_oracle(run_oracle=True)
    replay = Engine(None, cls())
    replay.replay_workflow(workflow)
    validation = replay.evaluate()
    expected = reference.scenario.get_typed_app(PaddyWorldApp).get_state()
    world = replay.scenario.get_typed_app(PaddyWorldApp)
    actual = world.get_state()
    if expected != actual or not validation.success:
        raise RuntimeError(f"Rice {variant} reference/replay or task validation failed")
    if actual["sha256"] != load_oracle_plan(scenario_id)["expected_final_state_sha256"]:
        raise RuntimeError(f"Rice {variant} no longer matches its reviewed reference state; rebuild scenario artifacts")
    directory = output / variant
    baseline = build_baseline(scenario_id)
    outcome = world.outcome_summary()
    report = {"scenario_id": scenario_id, "validation": validation.to_dict(),
              "exact_replay": True, "workflow_steps": len(workflow),
              "outcome": outcome, "comparison": compare_outcome(replay.scenario, baseline)}
    write_json(directory / "report.json", report)
    write_json(directory / "baseline.json", baseline)
    workflow.save_workflow(str(directory / "workflow.json"))
    write_json(directory / "initial_checkpoint.json", replay.scenario._initial_state)
    write_json(directory / "final_checkpoint.json", actual)
    for label in checkpoint_labels(variant):
        write_json(directory / "checkpoints" / f"{label}.json", load_checkpoint(variant, label))
    write_json(directory / "operations.json", world.actions)
    (directory / "daily.jsonl").write_text("".join(json.dumps(r) + "\n" for r in world.daily_records))
    return {"variant": variant, "success": validation.success, "exact_replay": True,
            "biological_dry_kg": outcome["biological_dry_kg"],
            "stored_kg_at_14pct": outcome["stored_kg_at_14pct"],
            "withdrawn_m3": world.channel("supply").withdrawn_m3,
            "harvest_timestamps": {a["plot_id"]: a["timestamp"] for a in world.actions if a["action"] == "harvest"},
            "resources_used": outcome["resources_used"],
            "max_nitrogen_balance_residual_kg_ha": max(abs(r["nitrogen"]["balance_residual_n_kg_ha"]) for r in world.daily_records),
            "max_water_balance_residual_mm": max(abs(r["water"]["balance_residual_mm"]) for r in world.daily_records)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=("all", *VARIANTS), default="all")
    parser.add_argument("--output-dir", type=Path, default=Path("validation_runs/rice"))
    parser.add_argument("--sensitivity", action="store_true")
    args = parser.parse_args()
    variants = VARIANTS if args.variant == "all" else (args.variant,)
    results = [run_variant(variant, args.output_dir) for variant in variants]
    write_json(args.output_dir / "summary.json", results)
    if args.sensitivity:
        write_json(args.output_dir / "sensitivity.json", sensitivity())
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
