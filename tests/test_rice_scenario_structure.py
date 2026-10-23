"""Registered rice tasks use independent classes and side-effect-free event graphs."""
from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from fairy.apps.paddy.world import PaddyWorldApp
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class, list_scenarios
from fairy.scenarios.rice import farm_checkpoint_state as artifacts
from fairy.scenarios.rice.farm_checkpoint_state import load_checkpoint, load_oracle_plan
from fairy.scenarios.rice.rice_scenario_catalog import SPECS, configuration, get_spec
from fairy.scenarios.scenario import Scenario
from fairy.types import CapturedEvent


L1_TASKS = (
    "irrigate", "drain", "puddle", "transplant", "harvest", "observe_water",
    "refuel", "dry", "store", "fertilize", "scout", "repair_bund", "gap_fill",
)
L2_TASKS = (
    "establishment", "irrigation_management", "harvest_storage",
    "nutrition_management", "crop_protection", "infrastructure_recovery", "harvest_batches",
)
L3_VARIANTS = (
    "normal", "water_limit", "late_rain", "nitrogen_limit", "biotic",
    "infrastructure", "equipment_limit", "poor_stand",
)
SCENARIO_IDS = (
    tuple(f"scenario_rice_l1_{task}" for task in L1_TASKS)
    + tuple(f"scenario_rice_l2_{task}" for task in L2_TASKS)
    + tuple(f"scenario_rice_l3_{variant}" for variant in L3_VARIANTS)
)
EXPECTED_CHECKPOINTS = {
    "irrigate": "before_irrigate", "drain": "before_drain",
    "puddle": "before_puddle", "transplant": "before_transplant",
    "harvest": "before_harvest", "observe_water": "after_transplant",
    "dry": "before_dry", "store": "before_store", "fertilize": "before_topdress",
    "scout": "before_treat", "gap_fill": "after_transplant",
    "irrigation_management": "management_start", "harvest_storage": "before_drain",
    "nutrition_management": "management_start", "crop_protection": "before_treat",
    "harvest_batches": "before_drain",
}
EXPECTED_VARIANTS = {
    "scout": "biotic", "crop_protection": "biotic", "gap_fill": "poor_stand",
    "repair_bund": "infrastructure", "infrastructure_recovery": "infrastructure",
    "harvest_batches": "equipment_limit", "refuel": "equipment_limit",
}


def test_registry_preserves_28_ids_with_independent_declared_classes():
    registered = {sid for sid in list_scenarios() if sid.startswith("scenario_rice_")}
    assert registered == set(SCENARIO_IDS) == set(SPECS)
    classes = [get_scenario_class(sid) for sid in SCENARIO_IDS]
    assert len(set(classes)) == len({cls.__module__ for cls in classes}) == 28

    for sid, cls in zip(SCENARIO_IDS, classes):
        source = Path(inspect.getfile(cls))
        declarations = [node.name for node in ast.parse(source.read_text()).body
                        if isinstance(node, ast.ClassDef)]
        assert declarations == [cls.__name__]
        assert cls.__name__.startswith("Scenario")
        assert "init_and_populate_apps" in cls.__dict__
        assert "build_events_flow" in cls.__dict__
        assert cls.oracle_solution is Scenario.oracle_solution
        if "_l3_" in sid:
            assert source.name == f"scenario_full_season_rice_{get_spec(sid).variant}.py"
        else:
            assert source.name == f"{sid}.py"
            assert source.parent.name == f"rice_{get_spec(sid).variant}"
            assert source.parent.parent.name == "l2_l1_splits"


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_registered_metadata_preserves_levels_and_source_checkpoints(scenario_id):
    scenario = get_scenario_class(scenario_id)()
    spec = get_spec(scenario_id)
    _, _, level, suffix = scenario_id.split("_", 3)
    task = "season" if level == "l3" else suffix
    variant = suffix if level == "l3" else EXPECTED_VARIANTS.get(task, "normal")
    checkpoint = EXPECTED_CHECKPOINTS.get(task)
    assert scenario.scenario_id == spec.scenario_id == scenario_id
    assert scenario.level == spec.level == level.upper()
    assert scenario.task == spec.task == task
    assert scenario.variant == spec.variant == variant
    assert spec.checkpoint_label == checkpoint
    assert scenario.source_l3_scenario_id == f"scenario_rice_l3_{variant}"
    assert scenario.source_slug == f"rice_{variant}"
    assert scenario.source_checkpoint_label == (checkpoint or "initial_before_field_prep")


def test_runtime_package_does_not_import_offline_reference_policy():
    import fairy.scenarios.rice as rice

    package = Path(rice.__file__).parent
    assert not (package / "scenarios.py").exists()
    assert not (package / "reference.py").exists()
    for source in package.rglob("*.py"):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.ImportFrom):
                imports = [node.module or ""]
            elif isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            else:
                continue
            assert not any("rice_reference_policy" in name for name in imports), source


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_setup_and_event_capture_preserve_checkpoint_and_connect_dependencies(scenario_id, monkeypatch):
    pytest.importorskip("pcse")

    def reject_execution(*args, **kwargs):
        pytest.fail("Building a rice scenario must not execute physical jobs or captured events")

    monkeypatch.setattr(PaddyWorldApp, "run_job", reject_execution)
    monkeypatch.setattr(CapturedEvent, "execute", reject_execution)
    scenario = get_scenario_class(scenario_id)()
    spec = get_spec(scenario_id)
    scenario.setup()
    world = scenario.get_typed_app(PaddyWorldApp)
    if spec.checkpoint_label:
        expected = load_checkpoint(spec.variant, spec.checkpoint_label)
    else:
        field, weather = configuration(spec.variant)
        expected = PaddyWorldApp(field=field, weather=weather).get_state()
    assert world.get_state() == expected
    assert scenario._initial_state == expected
    assert scenario._initial_action_count == len(expected["actions"])
    assert scenario.start_time == expected["sim_time"]

    engine = Engine(None, scenario)
    before = world.get_state()
    clock = (engine.time_manager.start_time, engine.time_manager.offset)
    scenario.build_events_flow()
    assert world.get_state() == before
    events = scenario.events
    event_ids = [event.event_id for event in events]
    assert events and all(event_ids) and len(event_ids) == len(set(event_ids))
    assert all(isinstance(event, CapturedEvent) for event in events)
    assert any(event.is_oracle for event in events)
    roots = [event for event in events if not event.dependencies]
    assert len(roots) == 1
    seen = set()
    for event in events:
        assert all(id(dependency) in seen for dependency in event.dependencies)
        seen.add(id(event))

    workflow = engine.build_oracle_workflow(run_oracle=False)
    assert world.get_state() == before
    assert (engine.time_manager.start_time, engine.time_manager.offset) == clock
    assert set(workflow.dag) == set(event_ids)
    seen_names = set()
    for name, step in workflow.dag.items():
        assert set(step.depends_on) <= seen_names
        assert step.content is None
        seen_names.add(name)


def artifact_target(kind):
    if kind == "checkpoint":
        args = ("normal", "before_irrigate")
        return artifacts.load_checkpoint, args, artifacts.checkpoint_relative_path(*args)
    args = ("scenario_rice_l1_irrigate",)
    return artifacts.load_oracle_plan, args, artifacts.plan_relative_path(*args)


@pytest.mark.parametrize("kind", ["checkpoint", "plan"])
@pytest.mark.parametrize("missing", ["manifest", "payload"])
def test_missing_artifacts_fail_with_actionable_rebuild_command(kind, missing, tmp_path, monkeypatch):
    loader, args, relative_path = artifact_target(kind)
    monkeypatch.setattr(artifacts, "ARTIFACT_ROOT", tmp_path)
    if missing == "manifest":
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True)
        path.write_text("{}")
    else:
        (tmp_path / artifacts.MANIFEST_NAME).write_text(json.dumps({
            "schema_version": artifacts.ARTIFACT_SCHEMA, "files": {},
        }))
    with pytest.raises(FileNotFoundError, match="Missing rice scenario artifact") as error:
        loader(*args)
    assert artifacts.REBUILD_COMMAND in str(error.value)


@pytest.mark.parametrize("kind", ["checkpoint", "plan"])
def test_artifact_checksum_rejects_modified_payload(kind, tmp_path, monkeypatch):
    loader, args, relative_path = artifact_target(kind)
    monkeypatch.setattr(artifacts, "ARTIFACT_ROOT", tmp_path)
    payload = {"artifact_kind": kind, "version": 1}
    data = json.dumps(payload).encode("utf-8")
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    (tmp_path / artifacts.MANIFEST_NAME).write_text(json.dumps({
        "schema_version": artifacts.ARTIFACT_SCHEMA,
        "files": {relative_path.as_posix(): hashlib.sha256(data).hexdigest()},
    }))
    assert loader(*args) == payload
    path.write_text(json.dumps({**payload, "version": 2}))
    with pytest.raises(ValueError, match="checksum mismatch") as error:
        loader(*args)
    assert artifacts.REBUILD_COMMAND in str(error.value)


@pytest.mark.parametrize("field", ["config_fingerprint", "initial_checkpoint_sha256"])
def test_mismatched_plan_rejects_capture_without_mutating_world_or_events(field, monkeypatch):
    pytest.importorskip("pcse")
    from fairy.scenarios.rice import rice_scenario_helpers as helpers

    sid = "scenario_rice_l1_irrigate"
    scenario = get_scenario_class(sid)()
    scenario.setup()
    world = scenario.get_typed_app(PaddyWorldApp)
    before = world.get_state()
    events_before = scenario.events
    plan = copy.deepcopy(load_oracle_plan(sid))
    plan[field] = "wrong"
    monkeypatch.setattr(helpers, "load_oracle_plan", lambda scenario_id: plan)

    with pytest.raises(ValueError, match="configuration/checkpoint mismatch"):
        scenario.build_events_flow()
    assert world.get_state() == before
    assert scenario.events is events_before


@pytest.mark.parametrize("detailed,brief", [(True, False), ("true", "false")])
def test_briefing_modes_keep_the_goal_and_change_the_provided_context(detailed, brief):
    cls = get_scenario_class("scenario_rice_l1_irrigate")
    full, short = cls(detailed_briefing=detailed), cls(detailed_briefing=brief)
    assert full.detailed_briefing is True and short.detailed_briefing is False
    assert short.scenario_input.strip()
    assert short.scenario_input in full.scenario_input
    assert full.scenario_input != short.scenario_input
    assert "PaddyOpsApp" in full.scenario_input
    assert full.spec == short.spec


@pytest.mark.parametrize("mode", ["skill", "none", "", None, 1])
def test_unsupported_briefing_modes_are_rejected(mode):
    cls = get_scenario_class("scenario_rice_l1_irrigate")
    with pytest.raises(ValueError, match="detailed_briefing supports true/false"):
        cls(detailed_briefing=mode)
