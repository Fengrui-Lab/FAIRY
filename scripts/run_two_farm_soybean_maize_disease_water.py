"""Run the mixed-crop reference without an Agent, network calls or file cleanup.

From this checkout, with its Python dependencies available:
    python -B scripts/run_two_farm_soybean_maize_disease_water.py \
        --output-dir /tmp/fairy-soybean-maize-disease-water

The output directory must be absent or empty. Existing outputs are never removed.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
from statistics import mean
import sys

# Prefer the checkout containing this script over another editable installation.
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from fairy.controllers.engine import Engine
from fairy.scenarios.two_farm.scenario_two_farm_soybean_maize_disease_water import (
    SCENARIO_ID, ScenarioTwoFarmSoybeanMaizeDiseaseWater,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    output = args.output_dir.expanduser().resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error("Choose an absent or empty output directory; existing files are preserved.")

    source = ScenarioTwoFarmSoybeanMaizeDiseaseWater(seed=args.seed)
    source.setup()
    plan = Engine(None, source).run_scenario_oracle(False)
    scene = ScenarioTwoFarmSoybeanMaizeDiseaseWater(seed=args.seed)
    scene.setup()
    engine = Engine(None, scene)
    checkpoints = []
    record = engine._record_run_log
    checkpoint_names = {
        "silking_soybean_field_health", "disease_confirm_32", "disease_treat_20",
        "disease_treat_30", "disease_followup_28", "disease_followup_32",
        "grain_fill_maize_field_soil", "drought_irrigate", "drought_crop_recheck",
        "drought_second_soil", "drought_second_irrigate", "drought_second_crop_recheck",
    }

    def capture(**event):
        record(**event)
        if event["step_name"] not in checkpoint_names:
            return
        # Passive backing-state reads: no extra sensor tool, RNG or clock change.
        truth = {}
        for farm in (scene.soybean, scene.maize):
            def region(ridges):
                return {
                    "ridge_ids": list(ridges),
                    "root_vwc_mean": mean(farm.physics.soil.states[r].root_vwc for r in ridges),
                    "surface_vwc_mean": mean(farm.physics.soil.states[r].top_vwc for r in ridges),
                    "disease_pressure_mean": mean(farm.physics.biotic.states[r].disease_pressure for r in ridges),
                    "growth_stages": sorted({farm._ridges[r].growth_stage for r in ridges}),
                }
            truth[farm.farm_id] = {
                "plot_label": scene.plot_labels[farm.farm_id],
                "crop_id": farm.crop_id,
                "target": region(tuple(range(20, 40))),
                "other_ridges": region(tuple(range(20)) + tuple(range(40, 64))),
            }
        checkpoints.append({
            "step": event["step_name"], "tool": event["tool_name"],
            "time": datetime.fromtimestamp(event["sim_time_after"], scene.farm_environment.simulation_timezone).isoformat(),
            "observation_or_tool_result": event["content"],
            "simulation_truth": truth,
        })

    engine._record_run_log = capture
    executed = engine.replay_workflow(plan)
    validation = engine.evaluate()
    summary = {
        "scenario_id": SCENARIO_ID, "seed": args.seed, "crop_backend": "legacy",
        "planned_steps": len(plan), "executed_steps": len(executed),
        "distinct_tools_used": len({s.tool_name for s in executed.dag.values()}),
        "start_time": datetime.fromtimestamp(scene.start_time, scene.farm_environment.simulation_timezone).isoformat(),
        "end_time": datetime.fromtimestamp(engine.time_manager.time(), scene.farm_environment.simulation_timezone).isoformat(),
        "validation": validation.to_dict(),
        "checkpoint_semantics": "Observations and passive simulation truth are separate. Disease pressure is an index, not diseased-leaf percentage.",
    }
    output.mkdir(parents=True, exist_ok=True)
    for filename, data in (
        ("oracle-plan.json", plan.to_dict()), ("executed-workflow.json", executed.to_dict()),
        ("run-summary.json", summary), ("intervention-checkpoints.json", checkpoints),
    ):
        with (output / filename).open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    manifest = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(output.iterdir()) if path.is_file()}
    with (output / "file-manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2)
    print(json.dumps(summary, indent=2))
    print(f"Results: {output}")
    return 0 if validation.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
