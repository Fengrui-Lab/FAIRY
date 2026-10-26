"""A full-season event graph is executable and its construction has no actions."""
from copy import deepcopy
import importlib

import pytest

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.controllers.engine import Engine
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.workflow import Workflow, WorkflowStep
from fairy.scenarios.workflow_validation import workflow_from_oracle_events
from fairy.types import CapturedEvent, EventRegisterer


SCENARIO_IDS = (
    "scenario_multi_farm_full_season",
    "scenario_multi_farm_full_season_drought_priority",
    "scenario_multi_farm_full_season_staggered_windows",
    "scenario_multi_farm_full_season_weather_risk",
    "scenario_multi_crop_full_season_maize",
    "scenario_multi_crop_full_season_rice",
    "scenario_multi_crop_full_season_mixed",
    "scenario_multi_crop_full_season_staggered",
)
PACKAGE = "fairy.scenarios.farm_world_diverse"
MIXED_SCENARIO = "scenario_multi_crop_full_season_mixed"


def _scene(scenario_id, **kwargs):
    module = importlib.import_module(f"{PACKAGE}.{scenario_id}")
    scene_class, = {
        value for value in vars(module).values()
        if isinstance(value, type) and value is not Scenario
        and issubclass(value, Scenario) and value.__module__ == module.__name__
    }
    return scene_class(**kwargs)


def _state(scenario):
    """Include the inventories, machine logs and simulated offsets, not wall time."""
    return deepcopy({
        "apps": {app.name: app.get_state() for app in scenario.apps},
        "clocks": {
            app.name: (app.time_manager.start_time, app.time_manager.real_start_time,
                       app.time_manager.offset)
            for app in scenario.apps
        },
        "domain": {
            site.spec.farm_id: {app.name: app.get_state() for app in site.private_apps}
            for site in scenario.fleet.sites
        },
        "assets": {
            asset_id: asset.snapshot() for asset_id, asset in scenario.fleet.runtime.assets.items()
        },
        "physics": {
            site.spec.farm_id: (site.farm.physics.action_log,
                               site.farm.physics.last_physics_sim_time)
            for site in scenario.fleet.sites
        },
        "messages": scenario.get_typed_app(AgentUserInterface).messages,
    })


def _event_signature(events):
    return deepcopy([
        (event.event_id, event.app.name, event.function.__name__, event.args, event.kwargs,
         event.is_oracle, tuple(dep.event_id for dep in event.dependencies), event.delay_seconds)
        for event in events
    ])


def _assert_complete_local_graph(scenario):
    assert scenario.event_flow_error is None
    events = scenario.events
    assert events and all(isinstance(event, CapturedEvent) for event in events)
    event_ids = [event.event_id for event in events]
    assert all(event_ids) and len(event_ids) == len(set(event_ids))
    local_apps = {id(app): app for app in scenario.apps}
    nodes = {id(event): event for event in events}
    visited, visiting = set(), set()

    def visit(event):
        assert id(event) in nodes, "Dependencies must belong to this scenario instance"
        if id(event) in visited:
            return
        assert id(event) not in visiting, "Event dependencies must be acyclic"
        visiting.add(id(event))
        for dependency in event.dependencies:
            visit(dependency)
        visiting.remove(id(event))
        visited.add(id(event))

    for event in events:
        assert id(event.app) in local_apps, "Events must execute on the original local apps"
        assert event.function.__name__ in {tool.name for tool in event.app.get_tools()}
        visit(event)
    assert any(event.is_oracle for event in events)
    assert any(event.app.name == "SystemApp" and event.function.__name__ == "advance_time"
               for event in events)
    for site in scenario.fleet.sites:
        local_methods = [event.function.__name__ for event in events
                         if event.kwargs.get("farm_id") == site.spec.farm_id and event.is_oracle]
        assert {"level", "base_fertilize", "form_ridges", "plant_seeds",
                "harvest", "unload_grain", "store_grain"} <= set(local_methods)
        assert sum(method.startswith(("get_", "read_", "inspect_"))
                   for method in local_methods) >= 3
        plant_events = [event for event in events if event.app.name == "Tractor"
                        and event.function.__name__ == "plant_seeds"
                        and event.kwargs.get("farm_id") == site.spec.farm_id]
        assert plant_events and all(event.kwargs["asset_id"] == "tractor_shared" for event in plant_events)


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_build_is_complete_idempotent_and_does_not_execute_or_leak(scenario_id, monkeypatch):
    scenario = _scene(scenario_id)
    # Bypass setup's automatic event build so there is a genuine before snapshot.
    scenario.init_and_populate_apps()
    engine = Engine(None, scenario)
    before = _state(scenario)
    sentinel = [object()]
    monkeypatch.setattr(EventRegisterer, "last_events", sentinel)
    capture_stack = list(EventRegisterer._stack)
    scenario.build_events_flow()

    _assert_complete_local_graph(scenario)
    signature = _event_signature(scenario.events)
    assert _state(scenario) == before
    assert EventRegisterer.last_events is sentinel
    assert EventRegisterer._stack == capture_stack
    assert engine._agent_briefing_from_events() == scenario.scenario_input

    other_id = SCENARIO_IDS[(SCENARIO_IDS.index(scenario_id) + 1) % len(SCENARIO_IDS)]
    other = _scene(other_id)
    other.setup()
    other_events = other.events
    other_signature = _event_signature(other_events)
    other_state = _state(other)
    assert other.events is not scenario.events

    scenario.setup()
    scenario.build_events_flow()
    scenario.setup()
    assert _event_signature(scenario.events) == signature
    assert _state(scenario) == before
    assert other.events is other_events
    assert _event_signature(other.events) == other_signature
    assert _state(other) == other_state
    assert EventRegisterer.last_events is sentinel
    assert EventRegisterer._stack == capture_stack
    _assert_complete_local_graph(scenario)
    _assert_complete_local_graph(other)


def test_short_season_setup_survives_unfinished_reference_but_cannot_export_an_oracle():
    source = _scene(MIXED_SCENARIO, season_length_days=90)
    engine = Engine(None, source)
    source.setup()
    engine._register_scenario_apps()
    assert source.event_flow_error and "unfinished" in source.event_flow_error.lower()
    assert any(event.function.__name__ == "plant_seeds" for event in source.events)
    assert engine._agent_briefing_from_events() == source.scenario_input
    assert engine.time_manager.offset == 0
    for site in source.fleet.sites:
        assert all(not ridge.planted and not ridge.harvested and not ridge.seeds_planted
                   for ridge in site.farm._ridges)
        assert site.farm.get_inventory() == source._initial_inventories[site.spec.farm_id]
        assert not site.tractor.get_state()["operation_log"]
        assert not site.farm.physics.action_log
    before_export = _state(source)
    with pytest.raises(RuntimeError, match="(?i)unfinished|incomplete"):
        source.oracle_solution(run_oracle=False)
    assert not source.workflow.dag
    assert _state(source) == before_export


def _assert_season_success(scenario, engine):
    result = engine.evaluate()
    assert result.success, result.message
    assert result.metadata["elapsed_days"] > 30
    assert len(result.metadata["farms"]) == 3
    for plan in scenario.farm_plans:
        details = result.metadata["farms"][plan.farm_id]
        assert details["emerged"] == details["matured"] == details["harvested"] == plan.num_ridges
        assert details["warehouse_grain_kg"] > 0
        assert details["warehouse_grain_kg"] == pytest.approx(details["recovered_grain_kg"], abs=.1)


@pytest.mark.parametrize("mode", ["captured_plan", "captured_execution", "exported_plan"])
def test_mixed_event_interfaces_reach_real_full_season_storage(mode):
    source = _scene(MIXED_SCENARIO)
    engine = Engine(None, source)
    source.setup()
    engine._register_scenario_apps()
    before = _state(source)

    if mode == "captured_execution":
        # Custom oracle_solution bypasses this path, so exercise the event runner directly.
        engine._run_captured_oracle_events(run_oracle=True)
        assert source.workflow.dag
        assert all(step.time_before is not None and step.time_after >= step.time_before
                   for step in source.workflow.dag.values())
        _assert_season_success(source, engine)
        return
    if mode == "captured_plan":
        engine._run_captured_oracle_events(run_oracle=False)
        workflow = source.workflow
    else:
        workflow = Workflow()
        for step in workflow_from_oracle_events(source).values():
            workflow.add_node(WorkflowStep(**step))
    assert workflow.dag
    assert _state(source) == before
    for site in source.fleet.sites:
        local_steps = [step for step in workflow.dag.values()
                       if (step.tool_args or {}).get("farm_id") == site.spec.farm_id]
        assert any(step.tool_name == "Tractor__plant_seeds" and
                   step.tool_args["asset_id"] == "tractor_shared" for step in local_steps)
        assert any(step.tool_name == "Farm__store_grain" for step in local_steps)

    replay = _scene(MIXED_SCENARIO)
    replay_engine = Engine(None, replay)
    replay_engine.replay_workflow(deepcopy(workflow), manifest=source.events_manifest)
    _assert_season_success(replay, replay_engine)
    assert _state(source) == before
