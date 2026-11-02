"""Independently execute the literal Oracle and replay its saved workflow."""

import argparse
from copy import deepcopy
import json
import hashlib
from pathlib import Path

from fairy.apps.farm_world import FarmWorldApp, TractorApp, WeatherApp, SensorApp
from fairy.controllers.engine import Engine
from fairy.scenarios.workflow import Workflow
from .scene import TwoYearMaizeScenario


def stable(value):
    if isinstance(value, dict):
        return {
            key: stable(item)
            for key, item in value.items()
            if key not in {"action_id", "op_id"}
        }
    if isinstance(value, (list, tuple)):
        return [stable(item) for item in value]
    if isinstance(value, float):
        return round(value, 9)
    return value


def snapshot(scene):
    return stable(
        {
            "farm": scene.get_typed_app(FarmWorldApp).get_state(),
            "tractor": scene.get_typed_app(TractorApp).get_state(),
            "cycle": scene.cycle.get_state(),
            "weather": scene.get_typed_app(WeatherApp).get_state(),
            "sensors": scene.get_typed_app(SensorApp).get_state(),
            "clock": scene.get_typed_app(FarmWorldApp).time_manager.time(),
        }
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    scene = TwoYearMaizeScenario()
    scene.setup()
    engine = Engine(None, scene)
    before = deepcopy(snapshot(scene))
    workflow = engine.build_oracle_workflow(run_oracle=False)
    assert snapshot(scene) == before, "Oracle capture must not execute tools"
    workflow_path = args.output / "oracle_workflow.json"
    workflow.save_workflow(str(workflow_path))
    engine.run_scenario_oracle(run_oracle=True)
    evaluation = scene.validate()
    assert evaluation.success, evaluation.message
    assert abs(evaluation.metadata["yield_loss_pct"]) < 1e-9, evaluation.metadata
    direct = snapshot(scene)
    replay = TwoYearMaizeScenario()
    replay.setup()
    fresh = Engine(None, replay)
    replayed = fresh.replay_workflow(Workflow.load_workflow(str(workflow_path)))
    replayed.save_workflow(str(args.output / "replayed_workflow.json"))
    replay_evaluation = replay.validate()
    assert replay_evaluation.success, replay_evaluation.message
    assert snapshot(replay) == direct, "Fresh replay differs from direct execution"
    backend = scene.get_typed_app(FarmWorldApp).physics.crop_backend
    soil_audit = {
        "first_close_ridge_0": scene.cycle.closed[0]["native_soil_pools"]["0"],
        "second_start_ridge_0": backend.season_history[0]["soil_before"],
        "final_ridge_0": backend._soil_pools(backend._runs[0].model),
        "second_start_count": len(backend.season_history),
        "all_transitions_conserve_pools": all(
            row["soil_before"] == row["soil_after"] for row in backend.season_history
        ),
    }
    assert soil_audit["first_close_ridge_0"] != soil_audit["second_start_ridge_0"], (
        "Fallow soil must evolve"
    )
    report = {
        "soil_audit": soil_audit,
        "input_fingerprint": scene.input_fingerprint,
        "success": True,
        "capture_pure": True,
        "fresh_replay_exact": True,
        "comparison_normalization": {
            "ignored_keys": ["action_id", "op_id"],
            "float_decimal_places": 9,
        },
        "workflow_steps": len(workflow),
        "evaluation": evaluation.to_dict(),
        "replay_evaluation": replay_evaluation.to_dict(),
    }
    (args.output / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    source_directory = Path(__file__).parent
    repository = source_directory.parents[4]
    framework_paths = (
        "fairy/physics/wofost_backend.py",
        "fairy/physics/weather_engine.py",
        "fairy/apps/farm_world/physics_orchestrator.py",
        "fairy/apps/farm_world/tractor_operations.py",
        "fairy/controllers/engine.py",
    )
    source_manifest = {
        "framework_sources": {
            relative: hashlib.sha256((repository / relative).read_bytes()).hexdigest()
            for relative in framework_paths
        },
        "input_fingerprint": scene.input_fingerprint,
        "source_files": {
            str(path.relative_to(source_directory)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(source_directory.rglob("*"))
            if path.is_file() and path.suffix in {".py", ".json", ".md"}
        },
        "verification_sha256": hashlib.sha256(
            (args.output / "verification.json").read_bytes()
        ).hexdigest(),
        "workflow_sha256": hashlib.sha256(workflow_path.read_bytes()).hexdigest(),
    }
    (args.output / "source_manifest.json").write_text(
        json.dumps(source_manifest, ensure_ascii=False, indent=2)
    )
    print(
        json.dumps(
            {
                "success": True,
                "steps": len(workflow),
                "total_stored_grain_kg": evaluation.metadata["total_stored_grain_kg"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
