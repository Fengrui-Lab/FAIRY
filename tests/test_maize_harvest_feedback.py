import copy
import json

import pytest

from fairy.apps.farm_world import FarmWorldApp, WeatherApp
from fairy.apps.farm_world.tractor_app import TractorApp
from fairy.apps.farm_world.maize_harvest_feedback import maturity_feedback
from fairy.agents.jev.snapshot import _short


@pytest.mark.parametrize('crop', ['maize', 'soybean', 'rice'])
@pytest.mark.parametrize('rain', [0, 5])
def test_feedback_is_maize_only_and_rejection_is_read_only(crop, rain):
    farm = FarmWorldApp(num_ridges=1, crop_type=crop)
    weather = WeatherApp()
    weather.set_weather(date='2026-05-05', temp_c=20, humidity_pct=50,
                        wind_speed_ms=1, rainfall_mm=rain, solar_radiation=240)
    tractor = TractorApp(farm, weather)
    ridge = farm.get_ridge(0)
    ridge.planted = True
    ridge.days_since_planted = 2
    before = copy.deepcopy([a.get_state() for a in (farm, weather, tractor)])
    result = tractor.harvest(0, 0)
    assert 'error' in result
    assert [a.get_state() for a in (farm, weather, tractor)] == before
    if crop != 'maize':
        assert set(result) == {'error'}
    else:
        assert 'guidance' in result
        assert _short(result) == json.dumps(result, ensure_ascii=False)
        if rain:
            assert 'WeatherApp__get_forecast(days=7)' in result['guidance']
        else:
            assert result['estimated_days_to_reference_maturity_range'] == [123, 123]


@pytest.mark.parametrize('age', [None, -1, float('nan'), 125, 140])
def test_unknown_or_overdue_does_not_claim_ready(age):
    farm = FarmWorldApp(num_ridges=1, crop_type='maize')
    farm.get_ridge(0).days_since_planted = age
    result = maturity_feedback(farm, [0])
    assert result['estimated_days_to_reference_maturity_range'] is None
    assert 'uncertain' in result['guidance']


def test_different_planting_ages_are_kept_in_range():
    farm = FarmWorldApp(num_ridges=2, crop_type='maize')
    farm.get_ridge(0).days_since_planted = 25
    farm.get_ridge(1).days_since_planted = 15
    assert maturity_feedback(farm, [0, 1])['estimated_days_to_reference_maturity_range'] == [100, 110]


def test_forecast_jev_menu_has_integer_day_options():
    from fairy.agents.jev.menu import build_tool_menus
    # Use the same initialized tool map builder as the existing adaptation tests.
    from test_jev_new_tools import setup, SCENES
    scenario, agent = setup(SCENES[0])
    menus = build_tool_menus(agent.tools_map, task_text='Inspect forecast', num_ridges=64)
    forecast = next(m for name, m in menus.items() if name.endswith('__get_forecast'))
    days = next(a for a in forecast.args if a.name == 'days')
    assert set(days.options.values()) == set(range(1, 8))
    assert all(type(v) is int for v in days.options.values())
