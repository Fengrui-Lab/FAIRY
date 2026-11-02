from datetime import date, timedelta
import json
import pytest
from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
from fairy.physics import PlantingConfig, SeedType, SoilWeatherInput
from fairy.scenarios.management_extensions.v2.l4.backend import ContinuousSeasonBackend

START = date(2026, 5, 5)


def weather(day):
    # Deliberately synthetic warm climate, including winter; mechanism test,
    # not a claim of regional crop suitability or a production scenario.
    return SoilWeatherInput(
        day=day,
        air_temp_mean_c=22,
        air_temp_min_c=16,
        air_temp_max_c=28,
        rain_mm=5 if day.day % 5 == 0 else 0,
        solar_rad_mj_m2=20,
        wind_ms=2,
    )


def plant(p, day):
    p.phenology.plant_ridges(
        [0], PlantingConfig(planting_date=day, seed_type=SeedType.MAIZE_201)
    )
    p.management.states[0].planted = True
    p.management.states[0].stand_fraction = 1


def advance(b, p, day):
    b.advance_day(p, day, weather(day), density_by_ridge={0: 20 / 3}, ridge_area_m2=201)


def test_two_native_seasons_preserve_soil_and_replay():
    p = FarmPhysicsState(num_ridges=1, crop_type="maize")
    b = ContinuousSeasonBackend(
        {
            "crop_name": "maize",
            "variety_name": "Grain_maize_201",
            "reference_density_plants_m2": 20 / 3,
            "initial_available_n_kg_ha": 50,
        }
    )
    plant(p, START)
    for n in range(180):
        advance(b, p, START + timedelta(days=n))
    assert b._runs[0].maturity_snapshot is not None
    p.phenology.states[0].planted = False
    model = b._runs[0].model
    soil = model.soil
    end_first = b._soil_pools(model)
    for n in range(180, 365):
        advance(b, p, START + timedelta(days=n))
    pre_second = b._soil_pools(model)
    assert pre_second != end_first
    second = START + timedelta(days=365)
    b.authorize_next_season(p, [0], second)
    plant(p, second)
    for n in range(365, 510):
        advance(b, p, START + timedelta(days=n))
    assert b._runs[0].model is model and model.soil is soil
    assert len(b.season_history) == 1
    assert b.season_history[0]["soil_before"] == b.season_history[0]["soil_after"]
    assert b._runs[0].maturity_snapshot is not None
    saved = json.loads(json.dumps(b.export_state()))
    clone = ContinuousSeasonBackend.from_state(saved)
    assert clone._soil_pools(clone._runs[0].model) == b._soil_pools(model)
    assert clone._runs[0].pcse == b._runs[0].pcse
    assert clone.export_state() == saved


def test_live_crop_cannot_be_replaced():
    p = FarmPhysicsState(num_ridges=1, crop_type="maize")
    b = ContinuousSeasonBackend(
        {"crop_name": "maize", "variety_name": "Grain_maize_201"}
    )
    plant(p, START)
    advance(b, p, START)
    with pytest.raises(ValueError, match="harvested"):
        b.authorize_next_season(p, [0], START + timedelta(days=1))


def test_complete_farm_checkpoint_preserves_continuous_backend():
    from fairy.scenarios.management_extensions.v2.l4.runtime import ContinuousFarm

    world = ContinuousFarm(num_ridges=1, crop_type="maize", ridge_width_m=0.75)
    world.configure_crop_backend(
        "wofost", crop_name="maize", variety_name="Grain_maize_201"
    )
    p = world.physics
    b = ContinuousSeasonBackend(
        {"crop_name": "maize", "variety_name": "Grain_maize_201"}
    )
    p.crop_backend = b
    b.bind_physics(p)
    plant(p, START)
    for n in range(180):
        advance(b, p, START + timedelta(days=n))
    p.phenology.states[0].planted = False
    for n in range(180, 365):
        advance(b, p, START + timedelta(days=n))
    b.authorize_next_season(p, [0], START + timedelta(days=365))
    plant(p, START + timedelta(days=365))
    for n in range(365, 380):
        advance(b, p, START + timedelta(days=n))
    saved = json.loads(json.dumps(world.get_state()))
    clone = ContinuousFarm(num_ridges=1, crop_type="maize", ridge_width_m=0.75)
    clone.load_state(saved)
    assert isinstance(clone.physics.crop_backend, ContinuousSeasonBackend)
    assert clone.physics.crop_backend.export_state() == b.export_state()
    tomorrow = START + timedelta(days=380)
    advance(b, p, tomorrow)
    advance(clone.physics.crop_backend, clone.physics, tomorrow)
    assert clone.physics.crop_backend.snapshot() == b.snapshot()


def settled_first_season_fixture():
    """Real native fallow clock plus settled accounting for lifecycle edge tests."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from fairy.apps.farm_world import TractorApp, WeatherApp
    from fairy.scenarios.management_extensions.v2.l4.runtime import (
        ContinuousFarm,
        SeasonCycle,
    )
    from fairy.time_manager import SimulationTimeManager

    world = ContinuousFarm(num_ridges=1, crop_type="maize", ridge_width_m=0.75)
    world.simulation_timezone = ZoneInfo("Asia/Shanghai")
    backend = ContinuousSeasonBackend(
        {"crop_name": "maize", "variety_name": "Grain_maize_201"}
    )
    world.physics.crop_backend = backend
    backend.bind_physics(world.physics)
    plant(world.physics, START)
    for offset in range(180):
        advance(backend, world.physics, START + timedelta(days=offset))
    world.physics.phenology.states[0].planted = False
    for offset in range(180, 365):
        advance(backend, world.physics, START + timedelta(days=offset))
    world._ridges[0].harvested = True
    world._inventory.warehouse_grain_kg = 1000.0
    world._inventory.fertilizer_kg = 1200.0
    world.configure_management_regime(
        fertilizer_quota_kg=800.0, irrigation_quota_mm_total=300.0
    )
    # Account debits isolate the budget edge; native water/N continuity is
    # independently exercised above and by the full public-tool Oracle replay.
    assert world.consume_fertilizer(200.0)
    world.record_irrigation_use(50.0)
    tractor = TractorApp(world, WeatherApp())
    cycle = SeasonCycle(world, tractor)
    cycle.closed = [
        {
            "year": 2026,
            "stored_grain_kg": 1000.0,
            "fertilizer_used_kg_cumulative": 200.0,
            "irrigation_used_mm_cumulative": 50.0,
        }
    ]
    clock = SimulationTimeManager()
    clock.reset(datetime(2027, 5, 5, 7, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())
    for app in (world, tractor, cycle):
        app.register_time_manager(clock)
    return world, tractor, cycle


@pytest.mark.parametrize(
    "winter_fertilizer,winter_water", [(0.0, 0.0), (150.0, 50.0), (600.0, 250.0)]
)
def test_fallow_inputs_do_not_create_new_second_season_allowance(
    winter_fertilizer, winter_water
):
    world, tractor, cycle = settled_first_season_fixture()
    if winter_fertilizer:
        assert world.consume_fertilizer(winter_fertilizer)
    if winter_water:
        world.record_irrigation_use(winter_water)
    inventory = world._inventory.to_dict()
    cycle.open_next_season(2027)
    regime = world._management_regime
    assert regime.fertilizer_quota_kg == 1000.0
    assert regime.irrigation_quota_mm_total == 350.0
    fertilizer_remaining = 800.0 - winter_fertilizer
    water_remaining = 300.0 - winter_water
    assert world.check_fertilizer_use(fertilizer_remaining) is None
    assert world.check_fertilizer_use(fertilizer_remaining + 0.001) is not None
    assert world.check_irrigation_quota(water_remaining) is None
    assert world.check_irrigation_quota(water_remaining + 0.001) is not None
    assert world._inventory.to_dict() == inventory


def test_unused_same_crop_seed_and_fertilizer_payloads_survive_opening():
    world, tractor, cycle = settled_first_season_fixture()
    world._inventory.seed_stock = {"MAIZE_201": 900}
    tractor.seed_type = "MAIZE_201"
    tractor._seed_hopper = 100
    assert world.withdraw_fertilizer(50.0)
    tractor._fertilizer_spreader_kg = 50.0
    inventory = world._inventory.to_dict()
    fuel = tractor._fuel_tank_l
    tractor._grain_bin_kg = 1.0
    with pytest.raises(ValueError, match="Unload harvested grain"):
        cycle.open_next_season(2027)
    tractor._grain_bin_kg = 0.0
    cycle.open_next_season(2027)
    assert tractor.seed_type == "MAIZE_201"
    assert tractor._seed_hopper == 100
    assert tractor._fertilizer_spreader_kg == 50.0
    assert tractor._fuel_tank_l == fuel
    assert world._inventory.to_dict() == inventory
    assert world._inventory.seed_stock["MAIZE_201"] + tractor._seed_hopper == 1000
    assert (
        world._inventory.fertilizer_kg
        + tractor._fertilizer_spreader_kg
        + world._management_regime.fertilizer_used_kg
        == 1200.0
    )
