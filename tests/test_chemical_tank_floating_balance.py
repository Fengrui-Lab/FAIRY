"""Bulk loaded working fluid survives floating subtraction, without free doses."""
from copy import deepcopy
from datetime import date, datetime, timezone

import pytest

from fairy.apps.farm_world import FarmWorldApp, TractorApp, WeatherApp
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.time_manager import SimulationTimeManager


DAY = date(2026, 5, 10)
CHEMICALS = [
    ("load_fungicide", "apply_fungicide", "fungicide_tank_l", "fungicide", "disease_pressure", 3.8, .45),
    ("refill_pesticide_tank", "spray_pesticide", "pesticide_tank_l", "insecticide", "insect_pressure", 8., .65),
    ("refill_pesticide_tank", "apply_herbicide", "pesticide_tank_l", "herbicide", "weed_pressure", 8., .55),
]


def rig(shared):
    clock = SimulationTimeManager()
    clock.reset(datetime(2026, 5, 10, 12, tzinfo=timezone.utc).timestamp())
    weather = WeatherApp()
    weather.register_time_manager(clock)
    weather.set_weather(str(DAY), 22., 55., 2., 0., 20. / .0864)
    world = FarmWorldApp(num_ridges=24)
    world.register_time_manager(clock)
    if shared:
        warehouse = WarehouseApp(stock=WarehouseStock(
            seed_stock={"STANDARD": 1_000_000}, pesticide_liters=1000., fertilizer_kg=1000., fuel_liters=100.))
        environment = FarmEnvironment([FarmContext("a", world, weather),
            FarmContext("b", FarmWorldApp(num_ridges=24), weather)], weather, clock, warehouse=warehouse)
        tractor = SharedTractorApp(environment)
    else:
        environment = None
        world._inventory.pesticide_liters = 1000.
        tractor = TractorApp(world, weather)
        tractor.register_time_manager(clock)
    world.configure_physics_profile("chemical_tank_floating_balance")
    world.advance_physics_time()
    return world, tractor, clock, environment


def stock(world, environment):
    return environment.warehouse.stock.pesticide_liters if environment else world._inventory.pesticide_liters


def apply(tractor, shared, method, start, end, dose):
    return getattr(tractor, method)(*(("a", start, end, dose) if shared else (start, end, dose)))


def snapshot(world, tractor, clock, environment):
    return deepcopy((stock(world, environment), tractor.get_state(), clock.time(),
        world.get_state(), world.physics.biotic.states, world.physics.management.states,
        world.physics.action_log, world.physics.last_physics_sim_time))


@pytest.mark.parametrize("shared", [False, True], ids=["single", "shared"])
@pytest.mark.parametrize("chemical", CHEMICALS, ids=[row[1] for row in CHEMICALS])
@pytest.mark.parametrize("total", [91.2, 24 * 3.8], ids=["decimal_total", "dose_product_total"])
def test_one_bulk_load_supplies_all_three_passes_without_dose_or_budget_distortion(shared, chemical, total):
    loader, method, tank, residual, pressure, reference, knockdown = chemical
    world, tractor, clock, environment = rig(shared)
    world.configure_management_regime(active_ingredient_cap_kg=.0912,
        max_insecticide_applications=1, max_fungicide_applications=1)
    for state in world.physics.biotic.states.values():
        setattr(state, pressure, .8)
    warehouse_before = stock(world, environment)
    assert getattr(tractor, loader)(total)["status"] == "ok"
    assert stock(world, environment) == warehouse_before - total
    before = clock.time()
    receipts = [apply(tractor, shared, method, start, end, 3.8)
                for start, end in [(0, 9), (10, 19), (20, 23)]]
    assert all(result.get("status") == "ok" for result in receipts), receipts
    used_key = {"apply_fungicide": "fungicide_used_liters", "spray_pesticide": "pesticide_used_liters",
                "apply_herbicide": "herbicide_used_liters"}[method]
    assert [result[used_key] for result in receipts] == [38., 38., 4*3.8]
    # A mathematically equal dose product can have a negative last-bit tail;
    # clamp that tail only. Do not round away a positive tiny stock remainder.
    expected = max(0., (total - 38. - 38.) - 4*3.8)
    assert tractor.get_status()[tank] == expected
    if total == 24*3.8:
        assert tractor.get_status()[tank] == 0.
    assert clock.time() > before
    assert stock(world, environment) == warehouse_before - total  # One warehouse transfer only.
    assert world._management_regime.active_ingredient_used_kg == .0912
    efficacy = min(1., 3.8/reference)
    for state in world.physics.biotic.states.values():
        assert getattr(state, residual + "_residual_strength") == pytest.approx(efficacy)
        assert getattr(state, pressure) == pytest.approx(.8 * (1-knockdown*efficacy))


@pytest.mark.parametrize("shared", [False, True], ids=["single", "shared"])
@pytest.mark.parametrize("chemical", CHEMICALS, ids=[row[1] for row in CHEMICALS])
@pytest.mark.parametrize("available,dose", [(0., 1e-12), (0., 1e-300),
                                          (1e-12, 2e-12), (3.8*(1-1e-10), 3.8)],
                         ids=["zero_stock_micro", "zero_stock_near_underflow", "real_tiny_shortage", "real_relative_shortage"])
def test_real_shortage_rejects_without_free_effect_time_or_resource_use(shared, chemical, available, dose):
    loader, method, tank, _, pressure, _, _ = chemical
    world, tractor, clock, environment = rig(shared)
    if available:
        assert getattr(tractor, loader)(available)["status"] == "ok"
    for state in world.physics.biotic.states.values():
        setattr(state, pressure, .8)
    before = snapshot(world, tractor, clock, environment)
    result = apply(tractor, shared, method, 0, 0, dose)
    assert "Insufficient" in result.get("error", ""), result
    assert tractor.get_status()[tank] == available
    assert snapshot(world, tractor, clock, environment) == before
