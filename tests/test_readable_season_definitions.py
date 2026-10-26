"""Declared scene inputs must reach tools, agent briefings and final validation."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from fairy.controllers.engine import Engine
from fairy.scenarios.farm_world_diverse.full_season import (
    ScenarioMultiCropFullSeasonMixed,
    ScenarioMultiFarmFullSeason,
)


@pytest.mark.parametrize("window_days", [2, 10])
def test_declared_planting_window_reaches_tool_boundary_checks(window_days):
    class CustomWindowScenario(ScenarioMultiCropFullSeasonMixed):
        farm_plans = tuple(
            replace(plan, planting_window_days=window_days)
            for plan in ScenarioMultiCropFullSeasonMixed.farm_plans
        )

    scenario = CustomWindowScenario()
    scenario.setup()
    engine = Engine(None, scenario)
    farm = scenario.fleet.get("maize").farm
    plan = next(plan for plan in scenario.farm_plans if plan.farm_id == "maize")
    start = datetime.fromtimestamp(scenario.start_time, timezone.utc)

    def check_day(season_day):
        engine.time_manager.reset(start_time=(start + timedelta(days=season_day)).timestamp())
        return farm.check_planting_window([0], farm.crop_profile.seed_type)

    assert "not open" in check_day(plan.planting_start_day - 1)
    assert check_day(plan.planting_start_day) is None
    assert check_day(plan.planting_start_day + window_days - 1) is None
    assert "closed" in check_day(plan.planting_start_day + window_days)


def test_mixed_scene_areas_match_real_farms_and_agent_briefing():
    scenario = ScenarioMultiCropFullSeasonMixed()
    scenario.setup()
    Engine(None, scenario)

    for farm_id, expected_area in (("soy", 660), ("maize", 735), ("rice", 900)):
        site = scenario.fleet.get(farm_id)
        plan = next(plan for plan in scenario.farm_plans if plan.farm_id == farm_id)
        assert site.farm.get_farm_overview()["field_area_m2"] == pytest.approx(expected_area)
        assert plan.layout.area_m2 == pytest.approx(expected_area)
        assert f"Simulated planted area {expected_area:g} m²" in scenario.scenario_input
    assert sum(plan.layout.area_m2 for plan in scenario.farm_plans) == pytest.approx(2295)


def test_validator_uses_declared_planting_window_instead_of_fixed_six_days():
    scenario = ScenarioMultiFarmFullSeason()
    engine = Engine(None, scenario)
    engine.run_scenario_oracle(run_oracle=True)
    original = scenario.farm_plans
    assert engine.evaluate().success

    # South actually sowed on day 7. Its new day-0 through day-7 window must
    # accept that history, exposing any fixed "+5" rule in final validation.
    scenario.farm_plans = (
        original[0],
        replace(original[1], planting_start_day=0, planting_window_days=8),
    )
    expanded = engine.evaluate()
    assert expanded.success, expanded.message

    # Closing that same window on day 6 rejects the unchanged day-7 sowing.
    scenario.farm_plans = (
        original[0],
        replace(original[1], planting_start_day=0, planting_window_days=7),
    )
    restricted = engine.evaluate()
    assert not restricted.success
    assert "planting fell outside" in restricted.message
