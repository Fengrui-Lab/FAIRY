"""Agent-visible nutrition follows committed physics for each farm and ridge."""
from copy import deepcopy

import pytest

from fairy.scenarios.registry import get_scenario_class


SCENE = "scenario_two_farm_full_season_hn84_disease_water"


@pytest.fixture
def scene():
    scenario = get_scenario_class(SCENE)()
    scenario.setup()
    scenario.farm_environment.sync()
    return scenario


def call(world, name, **arguments):
    """Use the same AppTool entry point exposed to the Agent."""
    tool = next(tool for tool in world.get_tools() if tool.name == name)
    return tool(**arguments)


@pytest.mark.parametrize("farm_id", ["farm_a", "farm_b"])
@pytest.mark.parametrize("amount", [0.24, 2.0])
def test_fertigation_updates_both_public_nutrition_reads_and_only_target_ridges(scene, farm_id, amount):
    target = scene.farm_environment.farms[farm_id].world
    other = scene.farm_b if target is scene.farm_a else scene.farm_a
    initial = call(target, "get_ridge_state", ridge_id=0)["nutrient_index"]
    assert initial == pytest.approx(0.76)
    other_before = deepcopy(other.physics.management.states)
    neighbor_before = target.physics.management.states[2].nutrient_index

    result = call(target, "apply_fertigation", start_ridge=0, end_ridge=1,
                  nutrient_amount=amount, water_mm=0.0)
    assert result["status"] == "ok"
    expected = {rid: round(target.physics.management.states[rid].nutrient_index, 3)
                for rid in range(3)}
    assert expected[0] > initial
    single = call(target, "get_ridge_state", ridge_id=0)
    multiple = call(target, "get_ridge_range_state", start=0, end=2)["ridges"]
    assert single["nutrient_index"] == expected[0]
    assert {ridge["ridge_id"]: ridge["nutrient_index"] for ridge in multiple} == expected
    assert other.physics.management.states == other_before
    assert call(other, "get_ridge_state", ridge_id=0)["nutrient_index"] == initial
    assert target.physics.management.states[2].nutrient_index == neighbor_before
    assert target.physics.management.states[2].cumulative_fertigation_amount == 0


@pytest.mark.parametrize("farm_id", ["farm_a", "farm_b"])
def test_daily_nutrient_consumption_updates_public_reads_without_read_side_effects(scene, farm_id):
    world = scene.farm_environment.farms[farm_id].world
    result = call(world, "apply_fertigation", start_ridge=0, end_ridge=0,
                  nutrient_amount=0.24, water_mm=0.0)
    assert result["status"] == "ok"
    after_fertigation = world.physics.management.states[0].nutrient_index
    scene.farm_environment.advance_time(86400)
    after_day = world.physics.management.states[0].nutrient_index
    assert after_day < after_fertigation
    management_before_reads = deepcopy(world.physics.management.states)
    time_before_reads = scene.farm_environment.time_manager.time()

    for _ in range(2):
        single = call(world, "get_ridge_state", ridge_id=0)
        multiple = call(world, "get_ridge_range_state", start=0, end=1)["ridges"]
        assert single["nutrient_index"] == round(after_day, 3)
        assert multiple[0]["nutrient_index"] == round(after_day, 3)

    assert world.physics.management.states == management_before_reads
    assert scene.farm_environment.time_manager.time() == time_before_reads
