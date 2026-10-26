#!/usr/bin/env python3
"""Rebuild real maize checkpoints and matched-management acceptance references.

Run with the project's WOFOST environment. No remote models or Oracle JSON
plans are used. Output is deterministic across processes and contains only
world snapshots, provenance and validation evidence.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import random
import sys
from dataclasses import replace
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fairy.apps.farm_world import FarmWorldApp
from fairy.controllers.engine import Engine
from fairy.scenarios.maize.farm_checkpoint_state import (
    ROOT, SCHEMA, checkpoint_path, export_maize_checkpoint, json_bytes,
    load_checkpoint, source_fingerprint,
)
from fairy.scenarios.maize.maize_scenario_catalog import SPECS, CHECKPOINT_EVENTS
from fairy.scenarios.maize import farm_checkpoint_state as artifact_store
from fairy.scenarios.maize.maize_scenario_catalog import TASK_SPECS
from fairy.scenarios.maize.validation import task_state
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.workflow import Workflow
from fairy.types import CapturedEvent


def make_engine(sid):
    scenario = get_scenario_class(sid)()
    scenario.setup()
    engine = Engine(None, scenario)
    engine.time_manager.real_time_passed = lambda: 0.0
    return scenario, engine


def export_source(variant, output_root):
    scenario, engine = make_engine(SPECS[variant].scenario_id)
    boundaries = CHECKPOINT_EVENTS[variant]
    files, captured = {}, set()
    original = CapturedEvent.execute

    def capture(position, event):
        for label, boundary in boundaries.items():
            if boundary == (position, event.event_id):
                payload = export_maize_checkpoint(scenario, label)
                data = json_bytes(payload)
                path = checkpoint_path(variant, label)
                (output_root / path).parent.mkdir(parents=True, exist_ok=True)
                (output_root / path).write_bytes(data + b"\n")
                files[path.as_posix()] = hashlib.sha256(data + b"\n").hexdigest()
                captured.add(label)

    def execute(event):
        capture("before", event)
        result = original(event)
        capture("after", event)
        return result

    # IDs in operation logs are bookkeeping only. Stable UUIDs make the offline
    # payload reproducible without changing the runtime or public tool code.
    rng = random.Random(f"maize-artifacts:{variant}:v1")
    with patch.object(CapturedEvent, "execute", execute), patch("uuid.uuid4", lambda: uuid.UUID(int=rng.getrandbits(128))):
        workflow = engine.run_scenario_oracle()
    result = engine.evaluate(workflow)
    if not result.success:
        raise RuntimeError(f"Source {variant} failed: {result.message}")
    if captured != set(boundaries):
        raise RuntimeError(f"Missing source boundaries: {set(boundaries) - captured}")
    return files, {"source_fingerprint": source_fingerprint(variant),
                   "workflow_steps": len(workflow), "validation": result.success,
                   "warehouse_grain_kg_at_14pct": result.metadata["warehouse_grain_kg_at_14pct"]}


def management_reference(task, output_root):
    from fairy.scenarios.maize.l2_l1_splits import _maize_split_common as common
    # Allows reproducibility checks in a temporary output directory.
    with patch.object(common, "load_checkpoint", lambda variant, label: load_checkpoint(variant, label, root=output_root)):
        managed, engine = make_engine(f"scenario_maize_l2_{task}")
        workflow = engine.run_scenario_oracle()
        control_workflow = Workflow()
        omitted = "FieldOpsApp__irrigate" if task == "irrigation_management" else "FarmWorldApp__apply_fertigation"
        for step in workflow.dag.values():
            if step.tool_name == omitted:
                if task == "irrigation_management":
                    seconds = round(step.content["total_duration_minutes"] * 60)
                    step = replace(step, tool_name="SystemApp__advance_time", tool_args={"seconds": seconds})
                else:
                    step = replace(step, tool_name="FarmWorldApp__get_inventory", tool_args={})
            control_workflow.add_node(step)
        control, other_engine = make_engine(f"scenario_maize_l2_{task}")
        other_engine.replay_workflow(control_workflow)
    managed_state, control_state = task_state(managed), task_state(control)
    native = managed.get_typed_app(FarmWorldApp).physics.crop_backend
    other = control.get_typed_app(FarmWorldApp).physics.crop_backend
    unchanged = "fertilizer_kg" if task == "irrigation_management" else "irrigation_mm"
    for rid, run in native._runs.items():
        comparison = other._runs[rid]
        if [(row["day"], row["weather"], row["inputs"][unchanged]) for row in run.journal] != [
            (row["day"], row["weather"], row["inputs"][unchanged]) for row in comparison.journal
        ]:
            raise RuntimeError("Management control changed weather or non-ablated inputs")
    metric, direction = ("stress_days", "lower") if task == "irrigation_management" else ("n_uptake", "higher")
    m, c = managed_state[metric], control_state[metric]
    if (direction == "lower" and not m < c) or (direction == "higher" and not m > c):
        raise RuntimeError(f"No measurable {task} response")
    return {"metric": metric, "direction": direction, "managed": m, "control": c,
            "threshold": (m + c) / 2, "equal_weather_and_other_inputs": True,
            "endpoint_sim_time": managed_state["time"],
            "native_last_day": managed_state["native_last_day"],
            "source_fingerprint": source_fingerprint(managed.spec.variant),
            "initial_checkpoint_sha256": managed._checkpoint["sha256"],
            "comparison": {key: {"managed": managed_state[key], "control": control_state[key]}
                           for key in ("rftra", "stress_days", "n_uptake", "biomass")}}


def build_artifacts(output_root=ROOT):
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": SCHEMA, "files": {}, "sources": {}, "management_thresholds": {}}
    for variant in SPECS:
        files, source = export_source(variant, output_root)
        manifest["files"].update(files)
        manifest["sources"][variant] = source
        print(f"{variant}: {len(files)} real checkpoints, source validation passed", flush=True)
    path = output_root / "scenario_artifacts.json"
    path.write_bytes(json_bytes(manifest) + b"\n")
    for task in ("irrigation_management", "nutrition_management"):
        manifest["management_thresholds"][task] = management_reference(task, output_root)
        print(f"{task}: matched control verified", flush=True)
    path.write_bytes(json_bytes(manifest) + b"\n")
    return manifest


def _verification_state(scenario):
    from fairy.apps.farm_world import TractorApp
    from fairy.scenarios.maize.farm_checkpoint_state import TRACTOR_FIELDS
    farm = scenario.get_typed_app(FarmWorldApp)
    tractor = scenario.get_typed_app(TractorApp)

    def bookkeeping_free(value):
        if isinstance(value, dict):
            return {key: bookkeeping_free(item) for key, item in value.items()
                    if key not in {"op_id", "action_id"}}
        if isinstance(value, (list, tuple)):
            return [bookkeeping_free(item) for item in value]
        return value

    # Random bookkeeping IDs identify a particular operation invocation. All
    # physical state, timestamps, queues, observation streams and native model
    # journals remain part of this independent replay comparison.
    return bookkeeping_free({
        "farm": farm.get_state(),
        "native": farm.physics.crop_backend.export_state(),
        "tractor": {key: getattr(tractor, key) for key in TRACTOR_FIELDS},
        "rng": {app.name: app.rng.getstate() for app in scenario.apps
                if app.name not in {"AgentUserInterface", "SystemApp"}},
        "observation_rng": farm.physics.observation_model.rng.getstate(),
    })


def verify_artifacts(output_root):
    """Run all split goals and independent replays against staging data."""
    results = {}
    with patch.object(artifact_store, "ARTIFACT_ROOT", Path(output_root)):
        for sid in TASK_SPECS:
            scenario, engine = make_engine(sid)
            workflow = engine.run_scenario_oracle()
            validation = engine.evaluate(workflow)
            if not validation.success:
                raise RuntimeError(f"Staged maize task failed: {sid}: {validation.to_dict()}")
            expected = _verification_state(scenario)
            replay, other_engine = make_engine(sid)
            other_engine.replay_workflow(workflow)
            replay_validation = other_engine.evaluate()
            if not replay_validation.success or _verification_state(replay) != expected:
                raise RuntimeError(f"Staged maize task replay diverged: {sid}")
            results[sid] = {"validation": True, "replay_validation": True,
                            "workflow_steps": len(workflow),
                            "physical_state_sha256": hashlib.sha256(json_bytes(expected)).hexdigest()}
            print(f"{sid}: task and independent replay verified", flush=True)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT)
    parser.add_argument("--verify-only", action="store_true",
                        help="Verify existing output-root artifacts without regenerating them")
    args = parser.parse_args()
    if not args.verify_only:
        build_artifacts(args.output_root)
    verify_artifacts(args.output_root)
