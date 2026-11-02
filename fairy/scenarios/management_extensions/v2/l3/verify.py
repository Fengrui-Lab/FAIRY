"""Independent static-plan execution and JSON replay, with accounting comparison."""

import argparse
from copy import deepcopy
import json
from pathlib import Path

from fairy.controllers.engine import Engine
from fairy.scenarios.workflow import Workflow
from .scenario import ScenarioJointCropOperatingMargin


def stable(value):
    if isinstance(value, dict):
        return {
            name: stable(v)
            for name, v in value.items()
            if name not in {"action_id", "op_id"}
        }
    if isinstance(value, (tuple, list)):
        return [stable(v) for v in value]
    if isinstance(value, float):
        return round(value, 9)
    return value


def snapshot(scene):
    return stable(
        {
            "farms": [farm.get_state() for farm in scene.farms],
            "warehouse": scene.warehouse.get_state(),
            "tractor": scene.tractor.get_state(),
            "irrigation": {
                name: controller.get_state()
                for name, controller in scene.irrigation.items()
            },
            "clock": scene.farm_environment.time_manager.time(),
            "accounts": scene.accounts.compute_accounts(),
        }
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    scene = ScenarioJointCropOperatingMargin()
    scene.setup()
    engine = Engine(None, scene)
    before = deepcopy(snapshot(scene))
    plan = engine.build_oracle_workflow(run_oracle=False)
    assert before == snapshot(scene), "Oracle capture must not execute tools"
    path = args.output / "oracle_workflow.json"
    plan.save_workflow(str(path))
    engine.run_scenario_oracle(run_oracle=True)
    direct = snapshot(scene)
    result = scene.validate()
    assert result.success, result.message
    replay = ScenarioJointCropOperatingMargin()
    replay.setup()
    fresh = Engine(None, replay)
    replayed_workflow = fresh.replay_workflow(Workflow.load_workflow(str(path)))
    replayed_workflow.save_workflow(str(args.output / "replayed_workflow.json"))
    replay_result = replay.validate()
    assert replay_result.success, replay_result.message
    assert direct == snapshot(replay), "Fresh replay state differs"
    reference = json.loads(Path(__file__).with_name("reference.json").read_text())
    assert (
        abs(
            result.metadata["net_operating_margin"]
            - reference["selected"]["net_operating_margin"]
        )
        < 1e-7
    )
    report = {
        "success": True,
        "capture_pure": True,
        "fresh_replay_exact": True,
        "workflow_steps": len(plan),
        "evaluation": result.metadata,
        "replay_evaluation": replay_result.metadata,
    }
    (args.output / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
