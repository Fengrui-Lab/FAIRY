from __future__ import annotations

from copy import deepcopy

import pytest

from fairy.apps.farm_world import FarmWorldApp, SensorApp
from fairy.controllers.engine import Engine
from fairy.scenarios.farm_world_diverse.scenarios import SCENARIO_IDS
from fairy.scenarios.registry import get_scenario_class, list_scenarios
from fairy.scenarios.workflow import Workflow


def reference(scenario_id):
    scenario = get_scenario_class(scenario_id)()
    engine = Engine(None, scenario)
    return scenario, engine, engine.run_scenario_oracle(run_oracle=False)


def _omit_steps(workflow, predicate):
    """Keep a valid DAG so the negative case reaches the business validator."""
    original_count = len(workflow)
    workflow.dag = {key: step for key, step in workflow.dag.items() if not predicate(step)}
    assert len(workflow) < original_count, "The requested omission must remove actual calls"
    for step in workflow.dag.values():
        step.depends_on = [name for name in step.depends_on if name in workflow.dag]


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_diverse_oracle_fresh_replay_and_do_nothing(scenario_id):
    assert scenario_id in list_scenarios()
    source, _, workflow = reference(scenario_id)
    assert all(step.content.get("oracle_reason") for step in workflow.dag.values())
    assert not any(r.harvested for site in source.fleet.sites for r in site.farm._ridges)
    scenario = get_scenario_class(scenario_id)()
    engine = Engine(None, scenario)
    engine.replay_workflow(workflow)
    result = engine.evaluate()
    assert result.success, result.message
    assert len(result.metadata["farms"]) == len(scenario.orders)
    untouched = get_scenario_class(scenario_id)()
    untouched.setup()
    noop = Engine(None, untouched)
    assert not noop.evaluate(Workflow()).success


@pytest.mark.parametrize("scenario_id, method", [
    (SCENARIO_IDS[0], "plant_seeds"),
    (SCENARIO_IDS[1], "irrigate"),
    (SCENARIO_IDS[2], "dry_grain"),
    (SCENARIO_IDS[4], "plant_seeds"),
    (SCENARIO_IDS[5], "plant_seeds"),
    (SCENARIO_IDS[7], "store_grain"),
])
def test_omitted_required_action_is_rejected(scenario_id, method):
    _, _, workflow = reference(scenario_id)
    _omit_steps(workflow, lambda step: str(step.tool_name).endswith("__"+method))
    scenario = get_scenario_class(scenario_id)()
    engine = Engine(None, scenario)
    engine.replay_workflow(workflow)
    assert not engine.evaluate().success


def test_real_agent_tool_op_type_cannot_bypass_same_farm_preflight():
    _, _, workflow = reference(SCENARIO_IDS[0])
    _omit_steps(workflow, lambda step: step.tool_name == "Weather__get_current_weather"
                and (step.tool_args or {}).get("farm_id") == "north")
    for step in workflow.dag.values():
        step.op_type = "TOOL"
    scenario = get_scenario_class(SCENARIO_IDS[0])()
    engine = Engine(None, scenario)
    engine.replay_workflow(workflow)
    result = engine.evaluate()
    assert not result.success
    assert "NorthWeather__get_current_weather" in result.message


def test_rain_at_one_farm_blocks_only_its_own_harvest():
    scenario, engine, _ = reference(SCENARIO_IDS[3])
    dry, rainy = scenario.fleet.get("dry"), scenario.fleet.get("rainy")
    before = deepcopy(rainy.farm.get_state())
    assert "error" in rainy.tractor.harvest(0, 3)
    assert rainy.farm.get_state() == before
    assert "error" not in dry.tractor.harvest(0, 3)
    assert not any(r.harvested for r in rainy.farm._ridges)


@pytest.mark.parametrize("count", [1, 3, 5, 7, 65, 97])
def test_sensor_geometry_covers_every_configured_ridge_once(count):
    farm = FarmWorldApp(num_ridges=count)
    sensor = SensorApp(farm)
    readings = sensor.read_soil_sensors()["soil_sensors"]
    covered = [ridge for reading in readings
               for ridge in range(reading["ridge_start"], reading["ridge_end"]+1)]
    assert covered == list(range(count))
    assert all(0 <= s["ridge_id"] < count for s in readings)


def test_sensor_geometry_refreshes_after_loading_a_different_layout():
    farm = FarmWorldApp()
    sensor = SensorApp(farm)
    farm.load_state(FarmWorldApp(num_ridges=3).get_state())
    readings = sensor.read_soil_sensors()["soil_sensors"]
    assert [s["ridge_id"] for s in readings] == [0, 1, 2]
