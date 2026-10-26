"""Exact-dose bulk topdressing works across64 ridges without free fertilizer."""
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, timezone

import pytest

from fairy.apps.farm_world import FarmWorldApp, TractorApp, WeatherApp
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.time_manager import SimulationTimeManager


def rig(shared):
    clock = SimulationTimeManager()
    clock.reset(datetime(2026, 5, 10, 12, tzinfo=timezone.utc).timestamp())
    weather = WeatherApp()
    weather.register_time_manager(clock)
    weather.set_weather('2026-05-10', 22., 55., 2., 0., 20./.0864)
    world = FarmWorldApp(num_ridges=64)
    world.register_time_manager(clock)
    if shared:
        warehouse = WarehouseApp(stock=WarehouseStock(seed_stock={'STANDARD': 1_000_000},
            pesticide_liters=1000., fertilizer_kg=1000., fuel_liters=100.))
        environment = FarmEnvironment([FarmContext('a', world, weather),
            FarmContext('b', FarmWorldApp(), weather)], weather, clock, warehouse=warehouse)
        tractor = SharedTractorApp(environment)
    else:
        environment = None
        world._inventory.fertilizer_kg = 1000.
        tractor = TractorApp(world, weather)
        tractor.register_time_manager(clock)
    world.configure_physics_profile('fertilizer_spreader_floating_balance')
    world.advance_physics_time()
    return world, tractor, clock, environment


def stock(world, environment):
    return environment.warehouse.stock.fertilizer_kg if environment else world._inventory.fertilizer_kg


def apply(tractor, shared, start, end, dose):
    return tractor.apply_fertilizer(*(('a', start, end, dose) if shared else (start, end, dose)))


def snapshot(world, tractor, clock, environment):
    return deepcopy((stock(world, environment), tractor.get_state(), clock.time(), world.get_state(),
        world.physics.biotic.states, world.physics.management.states, world.physics.soil.states,
        world.physics.action_log, world.physics.last_physics_sim_time))


@pytest.mark.parametrize('shared', [False, True], ids=['single', 'shared'])
def test_one_76_8kg_load_topdresses_all64_ridges_at_true_1_2kg_per_ridge(shared):
    world, tractor, clock, environment = rig(shared)
    world.configure_management_regime(fertilizer_quota_kg=76.8)
    before = stock(world, environment)
    assert tractor.load_fertilizer(76.8)['status'] == 'ok'
    assert stock(world, environment) == before-76.8
    start_time, start_fuel = clock.time(), tractor.get_status()['fuel_tank_l']
    receipts = [apply(tractor, shared, start, min(start+9, 63), 1.2) for start in range(0, 64, 10)]
    assert all(result.get('status') == 'ok' for result in receipts), receipts
    assert [row['fertilizer_used_kg'] for row in receipts] == [12.]*6 + [4.8]
    assert Counter(rid for row in receipts for rid in row['fertilized_ridges']) == Counter(range(64))
    assert tractor.get_status()['fertilizer_spreader_kg'] == 0.
    assert stock(world, environment) == before-76.8  # No second warehouse deduction.
    assert world._management_regime.fertilizer_used_kg == 76.8
    assert clock.time() > start_time
    assert tractor.get_status()['fuel_tank_l'] == start_fuel-14.
    physical = [action for action in world.physics.action_log if action.action_type == 'fertigation']
    assert len(physical) == 7
    assert all(action.parameters['kg_per_ridge'] == 1.2 for action in physical)
    assert Counter(rid for action in physical for rid in action.ridge_ids) == Counter(range(64))


@pytest.mark.parametrize('shared', [False, True], ids=['single', 'shared'])
@pytest.mark.parametrize('available,dose', [(0., 1e-12), (0., 1e-300),
                                          (1e-12, 2e-12), (1.2*(1-1e-10), 1.2)],
                         ids=['zero_stock_micro', 'zero_stock_near_underflow', 'real_tiny_shortage', 'real_relative_shortage'])
def test_real_shortage_cannot_create_time_fuel_or_nutrient_effects(shared, available, dose):
    world, tractor, clock, environment = rig(shared)
    if available:
        assert tractor.load_fertilizer(available)['status'] == 'ok'
    before = snapshot(world, tractor, clock, environment)
    response = apply(tractor, shared, 0, 0, dose)
    assert 'Insufficient fertilizer' in response.get('error', ''), response
    assert tractor.get_status()['fertilizer_spreader_kg'] == available
    assert snapshot(world, tractor, clock, environment) == before
