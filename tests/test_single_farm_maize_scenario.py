"""Real public-tool maize season, exported reference replay, and crop boundaries."""
from copy import deepcopy

import pytest

from fairy.agents.agent.toolset_builder import build_toolset
from fairy.controllers.engine import Engine
from fairy.physics.profiles import get_profile
from fairy.scenarios.maize.scenario_single_farm_maize_full_season import (
    CULTIVAR_ID, SCENARIO_ID, WEATHER_PROFILE, ScenarioSingleFarmMaizeFullSeason,
)
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.workflow import Workflow
from fairy.time_manager import SimulationTimeManager


def scene():
    scenario = ScenarioSingleFarmMaizeFullSeason()
    scenario.setup()
    return scenario, Engine(None, scenario)


def state(scenario):
    scenario.farm_environment.sync()
    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()
                    if key not in {"action_id", "op_id", "mission_id", "inspection_id"}}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value
    return deepcopy(clean({
        "time": scenario.farm_environment.time_manager.time(),
        "world": scenario.farm_world.get_state(),
        "phenology": scenario.farm_world.physics.phenology.states,
        "soil": scenario.farm_world.physics.soil.states,
        "yield": scenario.farm_world.physics.yield_recovery.states,
    }))


def test_maize_scene_has_one_farm_real_geometry_and_single_farm_tools():
    scenario, engine = scene()
    assert get_scenario_class(SCENARIO_ID) is ScenarioSingleFarmMaizeFullSeason
    assert set(scenario.farm_environment.farms) == {"maize_field"}
    assert isinstance(engine.time_manager, SimulationTimeManager)
    assert all(app.time_manager is engine.time_manager for app in scenario.apps)
    assert str(scenario.farm_environment.simulation_timezone) == "Asia/Shanghai"
    farm = scenario.farm_world
    assert farm.crop_id == "maize"
    assert farm.cultivar_id == CULTIVAR_ID
    assert farm.field_geometry.planted_area_m2 == pytest.approx(11148.8)
    assert farm.rows_per_ridge == 1
    assert farm.plants_per_ridge_from_spacing(25.0) == 1072
    assert not any(ridge.planted for ridge in farm._ridges)
    _, schemas, _ = build_toolset(scenario.apps)
    functions = {entry["function"]["name"]: entry["function"] for entry in schemas}
    assert "FarmWorldApp__get_crop_capabilities" in functions
    for name in ("TractorApp__plant_seeds", "TractorApp__harvest", "Mavic3M__fly_survey",
                 "FieldOpsApp__irrigate", "Robot0__inspect_crop_health"):
        assert "farm_id" not in functions[name]["parameters"]["properties"]
    assert functions["TractorApp__load_seeds"]["parameters"]["properties"]["seed_type"]["enum"] == [CULTIVAR_ID]


def test_scene_profile_is_local_and_workflow_export_does_not_execute_actions():
    registered = get_profile(WEATHER_PROFILE)
    original = deepcopy(registered)
    scenario, engine = scene()
    assert scenario.farm_world.physics.profile is not registered
    before = state(scenario)
    workflow = engine.run_scenario_oracle(False)
    assert state(scenario) == before
    assert get_profile(WEATHER_PROFILE) == original
    assert len(workflow) == len(scenario.events) - 1
    for event, step in zip(scenario.events[1:], workflow.dag.values()):
        assert event.event_id == step.name
        assert f"{event.app.name}__{event.function.__name__}" == step.tool_name
        assert event.kwargs == step.tool_args
        assert not event.args
    assert {step.tool_args["implement"] for step in workflow.dag.values()
            if step.tool_name == "TractorApp__attach_implement"} >= {"maize_planter", "maize_header"}
    assert "harvest_maturity" in workflow.dag


@pytest.fixture(scope="module")
def completed_season():
    scenario, engine = scene()
    engine.run_scenario_oracle(True)
    return scenario, engine


def test_actual_maize_oracle_completes_and_preserves_resource_accounting(completed_season):
    scenario, engine = completed_season
    result = engine.evaluate()
    assert result.success, result.message
    assert result.metadata["harvested_ridges"] == 64
    assert result.metadata["seed_use"] == 68608
    assert result.metadata["water_used_mm"] == pytest.approx(40.0)
    farm = scenario.farm_world
    assert farm._inventory.seed_stock == {CULTIVAR_ID: 150000 - 68608}
    assert farm._inventory.fertilizer_kg == pytest.approx(1200 - 200 - 64 * 6)
    assert farm._inventory.warehouse_grain_kg > 0
    assert farm._inventory.harvest_grain_kg == 0
    assert scenario.tractor._grain_bin_kg == 0
    assert all(ridge.harvested for ridge in farm._ridges)
    assert all(state.seed_type == CULTIVAR_ID for state in farm.physics.phenology.states.values())
    assert all(state.stage.value == "R6_MATURITY" for state in farm.physics.phenology.states.values())
    assert all(state.grain_moisture_frac <= 0.14 for state in farm.physics.yield_recovery.states.values())
    steps = scenario.workflow.dag
    mature = steps["harvest_maturity"].content["ridges"]
    assert {ridge["ridge_id"] for ridge in mature} == set(range(64))
    assert all(ridge["growth_stage"] == "R6_MATURITY" and ridge["grain_moisture_pct"] <= 30 for ridge in mature)
    assert steps["harvest_0_3"].time_before >= steps["harvest_maturity"].time_after
    assert all(step.time_before <= step.time_after for step in steps.values())
    assert all(not step.error_stage and "error" not in step.content and step.content.get("status") != "partial"
               for step in steps.values())
    missions = scenario.mavic.get_state()["mission_log"]
    assert {rid for mission in missions for rid in mission["surveyed_ridges"]} == set(range(64))
    emergence = [entry for entry in scenario.robot.get_state()["inspection_log"] if entry.get("modality") == "emergence"]
    assert {rid for entry in emergence for rid in entry["covered_ridges"]} == set(range(4))


def test_saved_complete_reference_replays_to_same_truth_and_clock(tmp_path, completed_season):
    original, _ = completed_season
    empty, exporter = scene()
    reference = exporter.run_scenario_oracle(False)
    path = tmp_path / "maize_oracle.json"
    reference.save_workflow(str(path))
    fresh, replay = scene()
    replay.replay_workflow(Workflow.load_workflow(str(path)))
    result = replay.evaluate()
    assert result.success, result.message
    assert state(fresh) == state(original)
    assert empty.farm_world._inventory.warehouse_grain_kg == 0
    assert not any(ridge.planted for ridge in empty.farm_world._ridges)


def test_build_events_flow_executes_the_same_complete_season(completed_season):
    original, _ = completed_season
    fresh, engine = scene()
    engine._run_captured_oracle_events(True)
    result = engine.evaluate()
    assert result.success, result.message
    assert state(fresh) == state(original)
    # Captured execution also delivers the task briefing before the same 136
    # operational actions; that message has zero duration and no farm effect.
    assert len(fresh.workflow) == len(original.workflow) + 1
    assert [(step.tool_name, step.tool_args, step.time_before, step.time_after)
            for name, step in fresh.workflow.dag.items() if name != "briefing"] == [
                (step.tool_name, step.tool_args, step.time_before, step.time_after)
                for step in original.workflow.dag.values()]


@pytest.mark.parametrize("omission", ["harvest", "store_grain"])
def test_missing_harvest_or_storage_cannot_pass(omission):
    scenario, engine = scene()
    actions = scenario._reference_actions()
    # Keep the actual reference until the omitted final phase. Dropping harvest
    # necessarily drops unload/drying/storage, rather than intentionally causing
    # meaningless empty-bin errors before checking the validator.
    if omission == "harvest":
        actions = actions[:next(i for i, item in enumerate(actions) if item[2] == "harvest")]
    else:
        actions = [item for item in actions if item[2] != omission]
    scenario._reference_actions = lambda: actions
    engine.run_scenario_oracle(True)
    result = engine.evaluate()
    assert not result.success
    assert "harvest coverage" in result.message if omission == "harvest" else "grain missing" in result.message
