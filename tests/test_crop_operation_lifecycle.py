"""Public operation sequences that the fixed full-season oracle did not cover."""
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from fairy.apps.farm_world.equipment import DEFAULT_TRACTOR_IMPLEMENTS, TractorEquipment
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.models import InventoryState
from fairy.apps.farm_world.tractor_app import TractorApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.controllers.engine import Engine
from fairy.scenarios.maize.scenario_single_farm_maize_full_season import ScenarioSingleFarmMaizeFullSeason


def call(app, method, **arguments):
    return next(tool for tool in app.get_tools() if tool.name == method)(**arguments)


@pytest.fixture(params=['soybean', 'maize'])
def planted(request):
    world = FarmWorldApp(crop_id=request.param)
    seed_type = world.crop_definition.seed_types[0]
    world._inventory = InventoryState({seed_type: 100000}, 0, 500, 300, 0)
    for ridge in world._ridges:
        ridge.soil_vwc, ridge.soil_temp_c = 0.24, 18.0
    weather = WeatherApp()
    weather.set_weather(date='2026-05-15', temp_c=20.0, humidity_pct=50.0,
                        wind_speed_ms=1.0, rainfall_mm=0.0, solar_radiation=350.0)
    start = datetime(2026, 5, 15, 7, tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
    env = FarmEnvironment([FarmContext('field', world, weather)], weather, start_time=start)
    equipment = TractorEquipment(
        implements=(*DEFAULT_TRACTOR_IMPLEMENTS, 'maize_planter', 'maize_header'),
        ridging_implement='furrower',
    )
    tractor = TractorApp(world, weather, equipment=equipment)
    tractor.register_time_manager(env.time_manager)
    env.sync()
    operations = [
        ('attach_implement', {'implement': 'grader'}), ('level', {}),
        ('detach_implement', {}), ('load_fertilizer', {'kg': 200}), ('base_fertilize', {}),
        ('attach_implement', {'implement': 'furrower'}),
        ('form_ridges', {'ridge_width_m': world.ridge_width_m}), ('detach_implement', {}),
        ('attach_implement', {'implement': world.crop_definition.planting_rules.required_implement or 'furrower'}),
        ('load_seeds', {'seed_type': seed_type, 'count': 50000}),
        ('plant_seeds', {'start_ridge': 0, 'end_ridge': 3, 'depth_cm': 4, 'seed_spacing_cm': 25}),
    ]
    for method, arguments in operations:
        result = call(tractor, method, **arguments)
        assert 'error' not in result, (method, result)
    return env, world, tractor


def snapshot(env, world, tractor):
    return deepcopy((env.time_manager.time(), world.get_state(), tractor.get_state()))


def test_ridging_a_living_crop_is_rejected_without_any_effect(planted):
    env, world, tractor = planted
    before = snapshot(env, world, tractor)
    result = call(tractor, 'form_ridges', ridge_width_m=world.ridge_width_m)
    assert 'crop is planted' in result['error']
    assert snapshot(env, world, tractor) == before
    # An ordinary clock advance must preserve the same living crop and seed metadata.
    env.advance_time(3600)
    ridge = world.get_ridge_state(0)
    assert ridge['planted'] and ridge['seeds_planted'] == before[1]['ridges'][0]['seeds_planted']


def test_repeated_and_partly_occupied_planting_is_rejected_before_charging(planted):
    env, world, tractor = planted
    for start, end in ((0, 3), (3, 6)):
        before = snapshot(env, world, tractor)
        result = call(tractor, 'plant_seeds', start_ridge=start, end_ridge=end, depth_cm=4, seed_spacing_cm=25)
        assert 'error' in result
        assert snapshot(env, world, tractor) == before


def test_invalid_snapshot_is_rejected_before_any_world_replacement(planted):
    env, world, tractor = planted
    before = snapshot(env, world, tractor)
    broken = deepcopy(before[1])
    broken['ridges'][0]['seeds_planted'] = 999
    broken['inventory'].pop('seed_stock')
    with pytest.raises(KeyError):
        world.load_state(broken)
    assert snapshot(env, world, tractor) == before


def test_replant_keeps_establishment_feedback_in_response_and_saved_log(planted):
    _, _, tractor = planted
    result = call(tractor, 'replant_seeds', start_ridge=0, end_ridge=3,
                  depth_cm=4, spacing_cm=25, full_replant=True)
    assert result.get('status') == 'ok', result
    assert result['stand_fraction_before'] == dict.fromkeys(range(4), 1.0)
    assert result['stand_fraction_after'] == dict.fromkeys(range(4), 1.0)
    operation = tractor.get_state()['operation_log'][-1]
    assert operation['stand_fraction_before'] == result['stand_fraction_before']
    assert operation['stand_fraction_after'] == result['stand_fraction_after']
    assert operation['phenology_reset_ridge_ids'] == result['phenology_reset_ridges']
    assert operation['seed_spacing_cm'] == 25


def test_public_state_and_emergence_inspection_agree_after_real_maize_harvest():
    scene = ScenarioSingleFarmMaizeFullSeason()
    scene.setup()
    engine = Engine(None, scene)
    engine.run_scenario_oracle(run_oracle=True)
    assert scene.validate().success
    for ridge_id in range(scene.farm_world.num_ridges):
        state = scene.farm_world.get_ridge_state(ridge_id)
        assert state['harvested'] and not state['planted'] and state['stand_fraction'] == 0
    result = call(scene.robot, 'inspect_emergence', start_ridge=0, end_ridge=0)
    assert result['status'] == 'ok'
    assert result['observations'][0]['stand_fraction'] == 0
