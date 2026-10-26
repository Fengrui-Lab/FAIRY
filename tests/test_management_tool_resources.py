"""Real tool boundaries conserve small stocks and reject invalid native work."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json

import pytest

from fairy.apps.farm_world import FarmWorldApp, TractorApp, WeatherApp
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.field_ops_app import FieldOpsApp
from fairy.apps.farm_world.manual_ops_app import ManualOpsApp
from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.physics import PlantingConfig, SeedType
from fairy.time_manager import SimulationTimeManager


DAY = date(2026, 5, 10)


def scene(shared=False):
    clock = SimulationTimeManager()
    clock.reset(datetime(2026, 5, 10, 12, tzinfo=timezone.utc).timestamp())
    weather = WeatherApp()
    weather.register_time_manager(clock)
    weather.set_weather(DAY.isoformat(), 22, 55, 2, 0, 20 / 0.0864)
    world = FarmWorldApp()
    world.register_time_manager(clock)
    if shared:
        warehouse = WarehouseApp(stock=WarehouseStock(
            seed_stock={"STANDARD": 1_000_000}, pesticide_liters=10.0,
            fertilizer_kg=1000.0, fuel_liters=100.0,
        ))
        environment = FarmEnvironment(
            [FarmContext("a", world, weather),
             FarmContext("b", FarmWorldApp(), weather)],
            weather, clock, warehouse=warehouse,
        )
        tractor = SharedTractorApp(environment)
        manual = ManualOpsApp(environment)
    else:
        environment = None
        world._inventory.pesticide_liters = 10.0
        tractor = TractorApp(world, weather)
        manual = FieldOpsApp(world, weather)
        for app in (tractor, manual):
            app.register_time_manager(clock)
    world.configure_physics_profile("management_tool_resources")
    world.advance_physics_time()
    return world, weather, tractor, manual, clock, environment


def stock(world, environment):
    return (environment.warehouse.stock.pesticide_liters if environment
            else world._inventory.pesticide_liters)


def spray(tractor, shared, method, dose):
    args = ("a", 0, 0, dose) if shared else (0, 0, dose)
    return getattr(tractor, method)(*args)


@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("loader,method,tank", [
    ("load_fungicide", "apply_fungicide", "fungicide_tank_l"),
    ("refill_pesticide_tank", "spray_pesticide", "pesticide_tank_l"),
    ("refill_pesticide_tank", "apply_herbicide", "pesticide_tank_l"),
])
def test_small_chemical_transfer_application_and_snapshot_conserve_stock(shared, loader, method, tank):
    world, _, tractor, _, _, environment = scene(shared)
    before = stock(world, environment)
    dose = 0.001
    assert getattr(tractor, loader)(dose)["status"] == "ok"
    assert stock(world, environment) == pytest.approx(before - dose, abs=1e-12)
    assert tractor.get_status()[tank] == dose
    state = json.loads(json.dumps(tractor.get_state()))
    tractor.load_state(state)
    assert tractor.get_state()[tank] == dose
    result = spray(tractor, shared, method, dose)
    assert result["status"] == "ok", result
    assert tractor.get_state()[tank] == 0
    assert stock(world, environment) == pytest.approx(before - dose, abs=1e-12)
    biotic = world.physics.biotic.states[0]
    pressure, reference = {
        "apply_fungicide": ("fungicide", 3.8),
        "spray_pesticide": ("insecticide", 8.0),
        "apply_herbicide": ("herbicide", 8.0),
    }[method]
    assert getattr(biotic, f"{pressure}_residual_strength") == pytest.approx(dose / reference)


@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("dose", [0.0, -0.1, float("nan"), float("inf")])
def test_invalid_dose_does_not_spend_stock_time_or_change_crop(shared, dose):
    world, _, tractor, _, clock, environment = scene(shared)
    assert tractor.load_fungicide(3.8)["status"] == "ok"
    world.advance_physics_time()
    before = (stock(world, environment), deepcopy(tractor.get_state()),
              clock.time(), deepcopy(world.physics.biotic.states[0]))
    result = spray(tractor, shared, "apply_fungicide", dose)
    assert "error" in result
    assert (stock(world, environment), tractor.get_state(), clock.time(),
            world.physics.biotic.states[0]) == before


@pytest.mark.parametrize("shared", [False, True])
def test_manual_half_dose_uses_its_explicit_three_liter_reference(shared):
    world, _, _, manual, _, environment = scene(shared)
    world.advance_physics_time()
    world.physics.biotic.states[0].insect_pressure = 0.8
    before = stock(world, environment)
    result = (manual.apply_pesticide_manual("a", 0, 0, 1.5) if shared
              else manual.apply_pesticide_manual(0, 1.5))
    assert result["status"] == "ok", result
    assert stock(world, environment) == before - 1.5
    state = world.physics.biotic.states[0]
    assert state.insecticide_residual_strength == 0.5
    assert state.insect_pressure == pytest.approx(0.8 * (1 - 0.65 * 0.5))


@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("full_replant", [False, True])
def test_native_replant_rejects_before_machine_resources_time_or_crop_change(shared, full_replant):
    pytest.importorskip("pcse")
    world, _, tractor, _, clock, environment = scene(shared)
    world.configure_crop_backend("wofost")
    physics = world.physics
    physics.phenology.plant_ridges(
        [0], PlantingConfig(planting_date=DAY, seed_type=SeedType.STANDARD))
    physics.management.states[0].planted = True
    physics.management.states[0].stand_fraction = 1.0
    world.get_ridge(0).planted = True
    world.get_ridge(0).seed_type = "STANDARD"
    world.get_ridge(0).seeds_planted = 6000
    clock.add_offset(86400)
    world._weather_app.set_weather("2026-05-11", 22, 55, 2, 0, 20 / 0.0864)
    world.advance_physics_time()
    assert world.physics.crop_backend.has_started
    assert tractor.load_seeds("STANDARD", 10000)["status"] == "ok"
    before = (deepcopy(tractor.get_state()), clock.time(),
              deepcopy(world.physics.crop_backend.export_state()),
              deepcopy(world.get_ridge(0)))
    args = ("a", 0, 0, 4.0, 5.0, full_replant) if shared else (0, 0, 4.0, 5.0, full_replant)
    result = tractor.replant_seeds(*args)
    assert "new native season" in result["error"]
    assert (tractor.get_state(), clock.time(), world.physics.crop_backend.export_state(),
            world.get_ridge(0)) == before


def test_legacy_stock_snapshot_preserves_a_sub_centiliter_withdrawal():
    world, _, _, _, _, _ = scene()
    assert world.consume_pesticide(0.001)
    state = json.loads(json.dumps(world.get_state()))
    assert state["inventory"]["pesticide_liters"] == 9.999
    world.load_state(state)
    assert world._inventory.pesticide_liters == 9.999


def test_native_harvest_uses_target_area_and_rejects_real_mass_above_bin_capacity():
    pytest.importorskip("pcse")
    clock, weather = SimulationTimeManager(), WeatherApp()
    sowing = date(2026, 5, 1)
    clock.reset(datetime(2026, 5, 1, 12, tzinfo=timezone.utc).timestamp())
    small = FarmWorldApp(num_ridges=1, field_length_m=100, ridge_width_m=1.1)
    large = FarmWorldApp(num_ridges=1, field_length_m=10000, ridge_width_m=1.1)
    warehouse = WarehouseApp(stock=WarehouseStock(
        seed_stock={"STANDARD": 1_000_000}, pesticide_liters=100,
        fertilizer_kg=1000, fuel_liters=1000))
    environment = FarmEnvironment(
        [FarmContext("small", small, weather), FarmContext("large", large, weather)],
        weather, clock, warehouse=warehouse)
    tractor = SharedTractorApp(environment)
    for world in (small, large):
        world.configure_crop_backend("wofost", initial_available_n_kg_ha=200,
                                     soil_overrides={"SMFCF": 0.30})
        world.physics.phenology.plant_ridges(
            [0], PlantingConfig(planting_date=sowing, seed_type=SeedType.STANDARD))
        world.physics.management.states[0].planted = True
        world.physics.management.states[0].stand_fraction = 1
        ridge = world.get_ridge(0)
        ridge.planted, ridge.seed_type, ridge.soil_vwc = True, "STANDARD", 0.30
        ridge.seeds_planted = round(40 * world.ridge_area_m2)
    mature = False
    for offset in range(150):
        day = sowing + timedelta(days=offset)
        clock.reset(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())
        weather.set_weather(str(day), 22, 55, 2, 0 if mature else 5, 20 / 0.0864)
        environment.sync()
        mature = all(w.get_ridge(0).growth_stage == "R8" for w in (small, large))
        if mature and all(w.get_ridge(0).grain_moisture_pct <= 18 for w in (small, large)):
            break
    assert mature
    # Per-area native TWSO is identical; geometry determines physical bin kg.
    assert small.physics.yield_recovery.states[0].biological_yield_g_m2 == pytest.approx(
        large.physics.yield_recovery.states[0].biological_yield_g_m2)
    assert large.physics.yield_recovery.states[0].biological_yield_g_m2 * large.ridge_area_m2 / 1000 > 2000
    before = deepcopy(tractor.get_state()), clock.time(), large.get_ridge(0).planted
    rejected = tractor.harvest("large", 0, 0)
    assert "overflow" in rejected["error"]
    assert (tractor.get_state(), clock.time(), large.get_ridge(0).planted) == before
    fuel_before, time_before = tractor.get_status()["fuel_tank_l"], clock.time()
    harvested = tractor.harvest("small", 0, 0)
    assert harvested["status"] == "ok", harvested
    recovered = small.physics.yield_recovery.states[0].recovered_yield_g_m2_at_market_moisture
    assert harvested["grain_kg_added"] == round(recovered * small.ridge_area_m2 / 1000, 2)
    assert tractor.get_status()["fuel_tank_l"] == pytest.approx(fuel_before - 2 * 100 / 268)
    assert clock.time() - time_before == 120

