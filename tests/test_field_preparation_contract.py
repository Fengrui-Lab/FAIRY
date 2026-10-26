"""Field-specific sowing prerequisites preserve real work and legacy defaults."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from fairy.apps.farm_world import FarmWorldApp, TractorApp, WeatherApp
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.scenarios.wofost_farm import FarmDefinition, WofostFarmScenario
from fairy.time_manager import SimulationTimeManager


LEGACY = ('level', 'base_fertilize', 'form_ridges')
NO_BASE = ('level', 'form_ridges')


def make_scene(shared=False, required=NO_BASE):
    clock = SimulationTimeManager()
    clock.reset(datetime(2026, 5, 10, 7, tzinfo=timezone.utc).timestamp())
    weather = WeatherApp()
    weather.register_time_manager(clock)
    weather.set_weather('2026-05-10', 22, 55, 2, 0, 350)
    a = FarmWorldApp(farm_id='a', num_ridges=4, required_field_preparation_ops=required)
    a.register_time_manager(clock)
    for ridge in a._ridges:
        ridge.soil_temp_c, ridge.soil_vwc = 12., .24
    if shared:
        b = FarmWorldApp(farm_id='b', num_ridges=4)
        warehouse = WarehouseApp(stock=WarehouseStock(seed_stock={'STANDARD': 1_000_000},
            pesticide_liters=100., fertilizer_kg=100., fuel_liters=100.))
        environment = FarmEnvironment([FarmContext('a', a, weather), FarmContext('b', b, weather)],
            weather, clock, warehouse=warehouse)
        tractor = SharedTractorApp(environment)
    else:
        b = environment = None
        tractor = TractorApp(a, weather)
        tractor.register_time_manager(clock)
    return a, b, tractor, clock, environment


def call(tractor, shared, method, *args):
    if method in ('level', 'base_fertilize', 'form_ridges', 'plant_seeds') and shared:
        return getattr(tractor, method)('a', *args)
    return getattr(tractor, method)(*args)


def prepare_without_fertilizer(tractor, shared, *, with_base=False):
    assert call(tractor, shared, 'attach_implement', 'grader')['status'] == 'ok'
    assert call(tractor, shared, 'level')['status'] == 'ok'
    assert call(tractor, shared, 'detach_implement')['status'] == 'ok'
    if with_base:
        assert call(tractor, shared, 'load_fertilizer', 20.)['status'] == 'ok'
        assert call(tractor, shared, 'base_fertilize')['status'] == 'ok'
    assert call(tractor, shared, 'attach_implement', 'furrower')['status'] == 'ok'
    assert call(tractor, shared, 'form_ridges', 1.1)['status'] == 'ok'
    assert call(tractor, shared, 'detach_implement')['status'] == 'ok'
    assert call(tractor, shared, 'load_seeds', 'STANDARD', 60000)['status'] == 'ok'


@pytest.mark.parametrize('shared', [False, True])
def test_explicit_no_base_contract_sows_after_only_real_required_work(shared):
    a, _, tractor, _, _ = make_scene(shared)
    prepare_without_fertilizer(tractor, shared)
    result = call(tractor, shared, 'plant_seeds', 0, 3, 4., 5.)
    assert result['status'] == 'ok', result
    assert all(a.get_ridge(r).planted for r in range(4))
    assert a.completed_prep_ops == ['level', 'form_ridges']
    assert a._management_regime.fertilizer_used_kg == 0.
    assert a.get_farm_overview()['required_field_preparation_ops'] == list(NO_BASE)
    assert a.get_farm_overview()['completed_field_preparation_ops'] == ['level', 'form_ridges']


@pytest.mark.parametrize('shared', [False, True])
def test_legacy_default_still_requires_actual_base_fertilization(shared):
    a, _, tractor, clock, _ = make_scene(shared, required=LEGACY)
    prepare_without_fertilizer(tractor, shared)
    before = deepcopy((tractor.get_state(), a.get_state(), clock.time()))
    result = call(tractor, shared, 'plant_seeds', 0, 3, 4., 5.)
    assert 'base_fertilize' in result['error']
    assert (tractor.get_state(), a.get_state(), clock.time()) == before
    assert a.required_field_preparation_ops == LEGACY


def test_shared_tractor_uses_selected_farms_contract_and_work():
    a, b, tractor, clock, _ = make_scene(True)
    prepare_without_fertilizer(tractor, True)
    assert call(tractor, True, 'plant_seeds', 0, 3, 4., 5.)['status'] == 'ok'
    assert b.required_field_preparation_ops == LEGACY and b.completed_prep_ops == []
    before = deepcopy((tractor.get_state(), b.get_state(), clock.time()))
    result = tractor.plant_seeds('b', 0, 3, 4., 5.)
    assert 'base_fertilize' in result['error']
    assert (tractor.get_state(), b.get_state(), clock.time()) == before


@pytest.mark.parametrize('shared', [False, True])
def test_legacy_complete_real_preparation_still_sows(shared):
    a, _, tractor, _, _ = make_scene(shared, required=LEGACY)
    prepare_without_fertilizer(tractor, shared, with_base=True)
    result = call(tractor, shared, 'plant_seeds', 0, 3, 4., 5.)
    assert result['status'] == 'ok', result
    assert a.completed_prep_ops == list(LEGACY)
    assert a._management_regime.fertilizer_used_kg == 12.5


@pytest.mark.parametrize('operations', [(), ('level',), ('form_ridges',),
    ('form_ridges', 'level'), ('level', 'level', 'form_ridges'),
    ('level', 'unknown', 'form_ridges'), 'level,form_ridges', None])
def test_invalid_contract_is_rejected_before_world_is_used(operations):
    with pytest.raises(ValueError, match='required_field_preparation_ops'):
        FarmWorldApp(required_field_preparation_ops=operations)


@pytest.mark.parametrize('shared', [False, True])
def test_snapshot_restores_requirement_and_real_completion_separately(shared):
    a, _, tractor, _, _ = make_scene(shared)
    prepare_without_fertilizer(tractor, shared)
    saved = deepcopy(a.get_state())
    a.reset()
    assert a.required_field_preparation_ops == NO_BASE
    assert a.completed_prep_ops == []
    a.load_state(saved)
    assert a.required_field_preparation_ops == NO_BASE
    assert a.completed_prep_ops == ['level', 'form_ridges']


def test_older_snapshot_without_contract_uses_legacy_requirement():
    world = FarmWorldApp()
    saved = world.get_state()
    saved.pop('required_field_preparation_ops')
    restored = FarmWorldApp(required_field_preparation_ops=NO_BASE)
    restored.load_state(saved)
    assert restored.required_field_preparation_ops == LEGACY


def test_shared_snapshot_cannot_silently_replace_configured_requirement():
    a, _, _, _, _ = make_scene(True)
    saved = deepcopy(a.get_state())
    saved['required_field_preparation_ops'] = list(LEGACY)
    before = deepcopy(a.get_state())
    with pytest.raises(ValueError, match='configuration'):
        a.load_state(saved)
    assert a.get_state() == before


def test_wofost_world_declaration_passes_contract_without_completed_work():
    world = FarmDefinition(reference_id='lille', seed_type='SOYBEAN_901',
        timezone_name='Europe/Paris', sowing_date=date(2019, 4, 28),
        end_date=date(2019, 11, 15), base_fertilizer_kg=0.,
        required_field_preparation_ops=NO_BASE)
    class Declared(WofostFarmScenario):
        WORLD = world
        def build_events_flow(self):
            self.events = []
            return []
    scenario = Declared()
    scenario.setup()
    farm = scenario.get_typed_app(FarmWorldApp)
    assert farm.required_field_preparation_ops == NO_BASE
    assert farm.completed_prep_ops == []
    assert farm._management_regime.fertilizer_used_kg == 0.
    assert replace(world).required_field_preparation_ops == NO_BASE


def test_shared_runtime_capabilities_publish_actual_requirement():
    from types import SimpleNamespace
    from fairy.apps.farm_world.runtime import FarmRuntime
    farm = FarmWorldApp(required_field_preparation_ops=NO_BASE)
    result = FarmRuntime.capabilities(None, SimpleNamespace(farm=farm, farm_id='a', asset=None))
    assert result['planting']['required_field_preparation_ops'] == list(NO_BASE)


def test_full_native_checkpoint_preserves_declared_and_real_preparation():
    from fairy.controllers.engine import Engine
    from fairy.scenarios.farm_world_fullseason_v2.farm_checkpoint_state import (
        export_farm_checkpoint_state, restore_farm_checkpoint_state,
    )
    world = FarmDefinition(reference_id='lille', seed_type='SOYBEAN_901',
        timezone_name='Europe/Paris', sowing_date=date(2019, 4, 28),
        end_date=date(2019, 11, 15), num_ridges=4, base_fertilizer_kg=0.,
        required_field_preparation_ops=NO_BASE)
    class Declared(WofostFarmScenario):
        WORLD = world
        def build_events_flow(self):
            self.events = []
            return []
    scenario = Declared()
    scenario.setup()
    engine = Engine(None, scenario)
    farm = scenario.get_typed_app(FarmWorldApp)
    tractor = scenario.get_typed_app(TractorApp)
    assert tractor.attach_implement('grader')['status'] == 'ok'
    assert tractor.level()['status'] == 'ok'
    saved = export_farm_checkpoint_state(farm_world=farm,
        weather_app=scenario.get_typed_app(WeatherApp),
        scenario_id='preparation_test', checkpoint_label='after_real_level')
    restored = FarmWorldApp(num_ridges=4)
    restored.register_time_manager(engine.time_manager)
    restore_farm_checkpoint_state(farm_world=restored, weather_app=None, checkpoint_state=saved)
    assert restored.required_field_preparation_ops == NO_BASE
    assert restored.completed_prep_ops == ['level']
    assert restored.physics.crop_backend_name == 'wofost'
