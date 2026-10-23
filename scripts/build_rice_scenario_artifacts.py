"""Author reviewed rice event plans and full checkpoints, outside scenario setup.

The policy uses real public tools. Published plans then run through the same
build_events_flow/EventRegisterer/Engine path as farm_world_fullseason_v2.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fairy.apps.paddy.world import PaddyWorldApp
from fairy.apps.paddy.operations import PaddyOpsApp
from fairy.apps.paddy.observations import PaddyObservationApp
from fairy.apps.paddy.machinery import PaddyMachineryApp
from fairy.apps.paddy.infrastructure import PaddyInfrastructureApp
from fairy.apps.paddy.drone import PaddyDroneApp
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.rice import farm_checkpoint_state as artifacts
from fairy.scenarios.rice.farm_checkpoint_state import (
    ARTIFACT_ROOT, ARTIFACT_SCHEMA, MANIFEST_NAME,
    checkpoint_relative_path, plan_relative_path,
)
from fairy.scenarios.rice.rice_scenario_catalog import SPECS, configuration
from fairy.scenarios.rice.rice_scenario_helpers import populate_rice_apps
from rice_reference_policy import ToolRecorder, run_reference


def write_artifact(root, relative_path, payload, manifest, *, compact=False):
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    options = {"separators": (",", ":")} if compact else {"indent": 2}
    data = (json.dumps(payload, ensure_ascii=False, allow_nan=False, **options) + "\n").encode("utf-8")
    path.write_bytes(data)
    manifest["files"][relative_path.as_posix()] = hashlib.sha256(data).hexdigest()


def author_scenario(spec, checkpoints):
    scenario = get_scenario_class(spec.scenario_id)()
    scenario._building_baseline = True  # authoring must not depend on external outcome baselines
    field, weather = configuration(spec.variant)
    world = PaddyWorldApp(field=field, weather=weather)
    if spec.checkpoint_label:
        world.load_state(checkpoints[spec.variant][spec.checkpoint_label])
    # Do not call setup: generation is the sole place a policy creates new plans.
    populate_rice_apps(scenario, world)
    engine = Engine(None, scenario)
    recorder = ToolRecorder(world, scenario.get_typed_app(PaddyOpsApp), scenario.get_typed_app(SystemApp),
                            world._weather_app, scenario.get_typed_app(PaddyObservationApp),
                            scenario.get_typed_app(PaddyMachineryApp), scenario.get_typed_app(PaddyInfrastructureApp),
                            scenario.get_typed_app(PaddyDroneApp))
    if spec.level == "L3":
        recorder.save("initial_before_field_prep")
    scenario.workflow = run_reference(recorder, spec.task)
    validation = engine.evaluate()
    if not validation.success:
        raise RuntimeError(f"Rice authoring failed for {spec.scenario_id}: {validation.to_dict()}")
    provenance = world.crop_backend_provenance()
    plan = {
        "schema_version": ARTIFACT_SCHEMA,
        "scenario_id": spec.scenario_id, "task": spec.task, "variant": spec.variant,
        "source_l3_scenario_id": spec.source_l3_scenario_id,
        "source_checkpoint_label": spec.source_checkpoint_label,
        "initial_checkpoint_sha256": scenario._initial_state["sha256"],
        "config_fingerprint": provenance["config_fingerprint"],
        "pcse_version": provenance["pcse_version"],
        "expected_final_state_sha256": world.get_state()["sha256"],
        "checkpoint_steps": recorder.checkpoint_steps if spec.level == "L3" else {},
        "steps": [{"tool_name": step.tool_name, "tool_args": step.tool_args,
                   "duration_seconds": step.time_after - step.time_before}
                  for step in recorder.workflow.dag.values()],
    }
    return plan, recorder.checkpoints


def verify_event_plans(staging, specs):
    """Exercise the actual registered scenarios before publishing new data.

This offline tool runs in one process. Scope the artifact root to the staging
tree so neither verification nor failure can consume/overwrite published data.
"""
    previous_root = artifacts.ARTIFACT_ROOT
    artifacts.ARTIFACT_ROOT = staging
    try:
        for spec in specs:
            cls = get_scenario_class(spec.scenario_id)
            scenario = cls()
            scenario._building_baseline = True
            engine = Engine(None, scenario)
            workflow = engine.run_scenario_oracle(run_oracle=True)
            expected = artifacts.load_oracle_plan(spec.scenario_id)["expected_final_state_sha256"]
            state = scenario.get_typed_app(PaddyWorldApp).get_state()
            if state["sha256"] != expected or not engine.evaluate().success:
                raise RuntimeError(f"Captured rice events diverged from authoring: {spec.scenario_id}")
            replay_scenario = cls()
            replay_scenario._building_baseline = True
            replay = Engine(None, replay_scenario)
            replay.replay_workflow(workflow)
            if replay_scenario.get_typed_app(PaddyWorldApp).get_state() != state or not replay.evaluate().success:
                raise RuntimeError(f"Rice artifact replay failed: {spec.scenario_id}")
            print(f"{spec.scenario_id}: captured events and independent replay verified", flush=True)
    finally:
        artifacts.ARTIFACT_ROOT = previous_root


def build_artifacts(output_dir):
    output_dir = Path(output_dir).resolve()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": ARTIFACT_SCHEMA,
                "generator": "scripts/build_rice_scenario_artifacts.py", "files": {}}
    checkpoints = {}
    specs = sorted(SPECS.values(), key=lambda s: (s.level != "L3", s.scenario_id))
    # Finish all authoring/acceptance before publishing; manifest is replaced last.
    with tempfile.TemporaryDirectory(prefix="rice-artifacts-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        for spec in specs:
            plan, states = author_scenario(spec, checkpoints)
            manifest["pcse_version"] = plan["pcse_version"]
            if spec.level == "L3":
                checkpoints[spec.variant] = states
                for label, state in sorted(states.items()):
                    write_artifact(staging, checkpoint_relative_path(spec.variant, label), state, manifest, compact=True)
            write_artifact(staging, plan_relative_path(spec.scenario_id), plan, manifest)
            print(f"{spec.scenario_id}: {len(plan['steps'])} tool events, acceptance passed", flush=True)
        manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        (staging / MANIFEST_NAME).write_text(manifest_text, encoding="utf-8")
        verify_event_plans(staging, specs)
        output_dir.mkdir(parents=True, exist_ok=True)
        for name in manifest["files"]:
            destination = output_dir / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(staging / name, destination)
        manifest_path = output_dir / MANIFEST_NAME
        temporary_manifest = output_dir / f".{MANIFEST_NAME}.tmp"
        temporary_manifest.write_text(manifest_text, encoding="utf-8")
        temporary_manifest.replace(manifest_path)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ARTIFACT_ROOT,
                        help="Artifact root, with the same layout as fairy/scenarios/rice")
    args = parser.parse_args()
    manifest = build_artifacts(args.output_dir)
    print(f"Published {len(manifest['files'])} checked artifacts to {args.output_dir}")


if __name__ == "__main__":
    main()
