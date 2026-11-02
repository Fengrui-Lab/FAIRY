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
