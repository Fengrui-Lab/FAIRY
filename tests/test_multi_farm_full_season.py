"""A season means all local crops grow; initial/final snapshots cannot stand in."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache

import pytest

from fairy.controllers.engine import Engine
from fairy.scenarios.farm_world_diverse.full_season import (
    FULL_SEASON_SCENARIO_IDS, FullSeasonMultiFarmScenario,
)
from fairy.scenarios.registry import get_scenario_class, list_scenarios
from fairy.scenarios.workflow import Workflow
from fairy.tool_execution import ToolExecutionError


@lru_cache(maxsize=None)
def _cached_reference(scenario_id):
    source = get_scenario_class(scenario_id)()
    engine = Engine(None, source)
    workflow = engine.run_scenario_oracle(run_oracle=False)
    return deepcopy(workflow)


def _reference(scenario_id):
    return deepcopy(_cached_reference(scenario_id))


def _omit_steps(workflow, predicate):
    """Remove a responsibility without leaving structurally invalid dependencies."""
    original_count = len(workflow)
    workflow.dag = {key: step for key, step in workflow.dag.items() if not predicate(step)}
    assert len(workflow) < original_count, "The requested omission must remove actual calls"
    for step in workflow.dag.values():
        step.depends_on = [name for name in step.depends_on if name in workflow.dag]


def _replay(scenario_id, workflow=None, *, allow_operation_rejection=False):
    scenario = get_scenario_class(scenario_id)()
    engine = Engine(None, scenario)
    try:
        engine.replay_workflow(deepcopy(_reference(scenario_id) if workflow is None else workflow))
    except ToolExecutionError as error:
        # A deliberately incomplete policy may now stop at the shared runtime's
        # domain guard. Still validate the actual partial attempt; never swallow
        # schema/manifest mismatches or internal execution errors as test success.
        assert allow_operation_rejection, error
        assert error.code == "OPERATION_REJECTED", error
    return scenario, engine, engine.evaluate()


@pytest.mark.parametrize("scenario_id", FULL_SEASON_SCENARIO_IDS)
def test_full_season_registered_starts_blank_and_replays_to_local_storage(scenario_id):
    assert scenario_id in list_scenarios()
    source = get_scenario_class(scenario_id)()
    engine = Engine(None, source)
    workflow = engine.run_scenario_oracle(run_oracle=False)
    for site in source.fleet.sites:
        assert not site.tractor._completed_prep_ops
        assert not site.tractor._operation_log
        assert not site.farm.physics.action_log
        assert all(not ridge.planted and not ridge.harvested and not ridge.seeds_planted
                   for ridge in site.farm._ridges)
        assert all(not state.emerged and state.maturity_date is None
                   for state in site.farm.physics.phenology.states.values())
        assert not site.farm._inventory.warehouse_grain_kg
    assert all(step.content.get("oracle_reason") for step in workflow.dag.values())
    scenario, engine, result = _replay(scenario_id, workflow)
    assert result.success, result.message
    assert len(result.metadata["farms"]) == len(scenario.farm_plans) >= 2
    assert result.metadata["elapsed_days"] > 30
    for plan in scenario.farm_plans:
        details = result.metadata["farms"][plan.farm_id]
        assert details["emerged"] == details["matured"] == details["harvested"] == plan.num_ridges
        assert details["recovered_grain_kg"] > 0
        assert details["warehouse_grain_kg"] == pytest.approx(details["recovered_grain_kg"], abs=0.1)
        assert details["in_season_care_actions"] > 0
        assert len(details["soil_observation_dates"]) >= 3
        assert all(details["observed_checkpoint_dates"].values())
    # Shared time also reached every farm whose harvest occurred earlier.
    assert all(site.farm.physics.last_physics_sim_time == pytest.approx(engine.time_manager.time())
               for site in scenario.fleet.sites)


def test_empty_and_harvest_only_workflows_cannot_complete_a_season():
    scenario = get_scenario_class(FULL_SEASON_SCENARIO_IDS[0])()
    scenario.setup()
    assert not Engine(None, scenario).evaluate(Workflow()).success
    workflow = _reference(FULL_SEASON_SCENARIO_IDS[0])
    _omit_steps(workflow, lambda step: not str(step.tool_name).endswith(
        ("__harvest", "__unload_grain", "__dry_grain", "__store_grain")))
    result = _replay(FULL_SEASON_SCENARIO_IDS[0], workflow, allow_operation_rejection=True)[2]
    assert not result.success
    assert "missing tool-based planting" in result.message


@pytest.mark.parametrize("scenario_id", [FULL_SEASON_SCENARIO_IDS[0], FULL_SEASON_SCENARIO_IDS[6]])
def test_directly_executed_oracle_has_real_checkpoint_times(scenario_id):
    scenario = get_scenario_class(scenario_id)()
    engine = Engine(None, scenario)
    workflow = engine.run_scenario_oracle(run_oracle=True)
    assert all(step.time_before is not None and step.time_after >= step.time_before
               for step in workflow.dag.values())
    result = engine.evaluate()
    assert result.success, result.message


@pytest.mark.parametrize("omission", ["one_farm", "field_prep", "care", "growth_time", "local_observations", "drying", "storage"])
def test_omitted_whole_season_responsibilities_are_rejected(omission):
    scenario_id = FULL_SEASON_SCENARIO_IDS[0]
    workflow = _reference(scenario_id)
    if omission == "one_farm":
        omit = lambda step: (step.tool_args or {}).get("farm_id") == "south"
    elif omission == "field_prep":
        omit = lambda step: str(step.tool_name).endswith(("__level", "__base_fertilize", "__form_ridges"))
    elif omission == "care":
        omit = lambda step: str(step.tool_name).endswith(("__irrigate", "__apply_fertigation", "__apply_fungicide", "__spray_pesticide", "__mechanical_weed_control"))
    elif omission == "growth_time":
        omit = lambda step: str(step.tool_name).endswith("__advance_time")
    elif omission == "local_observations":
        omit = lambda step: (step.tool_args or {}).get("farm_id") == "south" and str(step.tool_name).endswith(("__get_farm_overview", "__get_ridge_range_state", "__get_ridge_state", "__get_current_weather", "__read_soil_sensors"))
    elif omission == "drying":
        omit = lambda step: str(step.tool_name).endswith("__dry_grain")
    else:
        omit = lambda step: str(step.tool_name).endswith("__store_grain")
    _omit_steps(workflow, omit)
    result = _replay(scenario_id, workflow, allow_operation_rejection=True)[2]
    assert not result.success
    expected_failure = {
        "one_farm": "south: farm was never managed",
        "field_prep": "field preparation was not actually performed",
        "care": "missing in-season care after emergence",
        "growth_time": "missing elapsed physics growth",
        "local_observations": "missing observed",
        "drying": "grain was stored without verified safe batch moisture",
        "storage": "local warehouse mass",
    }
    assert expected_failure[omission] in result.message


def test_agent_tool_labels_do_not_bypass_local_evidence_checks():
    scenario_id = FULL_SEASON_SCENARIO_IDS[0]
    workflow = _reference(scenario_id)
    _omit_steps(workflow, lambda step: step.tool_name == "Weather__get_current_weather"
                and (step.tool_args or {}).get("farm_id") == "south")
    for step in workflow.dag.values():
        step.op_type = "TOOL"
    result = _replay(scenario_id, workflow)[2]
    assert not result.success
    assert "SouthWeather__get_current_weather" in result.message or "same-farm get_current_weather" in result.message


def test_warehouse_transfer_between_farms_fails_per_farm_mass_balance():
    scenario, engine, result = _replay(FULL_SEASON_SCENARIO_IDS[0])
    assert result.success, result.message
    north, south = scenario.fleet.sites
    north.farm._inventory.warehouse_grain_kg += 1
    south.farm._inventory.warehouse_grain_kg -= 1
    result = engine.evaluate()
    assert not result.success
    assert "local warehouse mass" in result.message


def test_final_yield_and_maturity_without_observed_growth_cannot_pass():
    scenario, engine, result = _replay(FULL_SEASON_SCENARIO_IDS[0])
    assert result.success, result.message
    # Final state remains correct; deleting the entire season's crop evidence
    # must still fail, so a lucky harvest-only script is not a season manager.
    _omit_steps(scenario.workflow, lambda step: str(step.tool_name).endswith(
        ("__get_farm_overview", "__get_ridge_range_state", "__get_ridge_state")))
    result = engine.evaluate()
    assert not result.success
    assert "checkpoint" in result.message


def test_four_sparse_visits_cannot_replace_active_season_monitoring():
    scenario, engine, result = _replay(FULL_SEASON_SCENARIO_IDS[0])
    assert result.success, result.message
    soil_tools = {"Sensor__read_soil_sensors", "Sensor__read_root_zone_sensors"}
    def local_soil(step):
        return step.tool_name in soil_tools and (step.tool_args or {}).get("farm_id") == "south"
    soil_dates = sorted({step.time[:10] for step in scenario.workflow.dag.values()
                         if local_soil(step)})
    assert len(soil_dates) > 4
    keep_dates = {soil_dates[index] for index in (0, len(soil_dates)//3,
                                                 2*len(soil_dates)//3, len(soil_dates)-1)}
    _omit_steps(scenario.workflow, lambda step: local_soil(step) and step.time[:10] not in keep_dates)
    # All actual management, four growth-phase records and final grain remain
    # correct; the omitted farm visits are independently consequential.
    result = engine.evaluate()
    assert not result.success
    assert "monitoring gap" in result.message


def test_custom_fleet_requires_multiple_farms_and_valid_timeline():
    with pytest.raises(ValueError, match="at least two"):
        FullSeasonMultiFarmScenario(farm_configs=[{"farm_id": "only", "prefix": "Only", "num_ridges": 3, "length_m": 100}])
    with pytest.raises(ValueError, match="at least 60 days"):
        FullSeasonMultiFarmScenario(farm_configs=[
            {"farm_id": "a", "prefix": "A", "num_ridges": 3, "length_m": 100},
            {"farm_id": "b", "prefix": "B", "num_ridges": 5, "length_m": 120, "plant_day": 150}])
