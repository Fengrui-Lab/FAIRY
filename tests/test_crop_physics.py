"""Behavioral coverage for crop-specific reduced physics adapters."""
from datetime import date, datetime, timedelta, timezone

import pytest

from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.physics_orchestrator import (
    _crop_water_stress,
    _ridge_planting_density_plants_m2,
    advance_physics_time,
)
from fairy.physics import PhenologySoilInput, PhenologyWeatherInput, PlantingConfig, SeedType
from fairy.physics.crop_physiology import public_crop_stage
from fairy.physics.phenology_engine import SoybeanStage
from fairy.physics.yield_recovery_engine import (
    GrowthStage, HarvestAction, YieldGrowthInput, YieldPhenologyInput, YieldWeatherInput,
)


@pytest.mark.parametrize("crop,stage,day", [
    ("maize", "R3", 85), ("rice", "heading", 75),
])
def test_midseason_seed_and_next_tick_keep_crop_native_stages(crop, stage, day):
    farm = FarmWorldApp(crop_type=crop, num_ridges=3, field_length_m=90, ridge_width_m=1)
    ridge = farm._ridges[0]
    ridge.planted = True
    ridge.seed_type = farm.crop_profile.seed_type
    ridge.growth_stage = stage
    ridge.days_since_planted = day
    ridge.soil_vwc = 0.30
    ridge.soil_temp_c = 24.0
    farm.physics.engines_active = True
    now = datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp()
    advance_physics_time(farm, now)
    assert ridge.growth_stage == stage
    assert farm.physics.canopy.states[0].initialized
    advance_physics_time(farm, now + 86400)
    assert ridge.growth_stage in {candidate for _, candidate in farm.crop_profile.stage_thresholds}
    assert ridge.growth_stage == stage


@pytest.mark.parametrize("crop", ["maize", "rice"])
def test_warm_irrigated_crop_reaches_own_maturity_under_thermal_time(crop):
    physics = FarmPhysicsState(num_ridges=1, crop_type=crop)
    profile = physics.crop_profile
    start = date(2026, 5, 1)
    physics.phenology.plant_ridges([0], PlantingConfig(
        planting_date=start, seed_type=SeedType(profile.seed_type),
        seed_depth_cm=profile.planting_depth_cm,
    ))
    seen = set()
    for offset in range(180):
        physics.phenology.update_day(
            weather=PhenologyWeatherInput(start + timedelta(days=offset), 20, 30, 25),
            soil_by_ridge={0: PhenologySoilInput(25, 0.30, 1.0)},
        )
        state = physics.phenology.states[0]
        seen.add(public_crop_stage(profile, state, physics.phenology.seed_type_params))
    assert state.stage == SoybeanStage.R8
    assert public_crop_stage(profile, state, physics.phenology.seed_type_params) == profile.mature_stage
    assert {s for _, s in profile.stage_thresholds}.issubset(seen)
    assert state.last_photoperiod_multiplier == 1.0


def test_crop_density_uses_local_geometry_and_rice_has_higher_water_demand():
    maize = FarmWorldApp(crop_type="maize", num_ridges=2, field_length_m=100, ridge_width_m=0.8)
    maize._ridges[0].seeds_planted = 600
    assert _ridge_planting_density_plants_m2(maize, 0) == 7.5
    maize._ridges[1].seed_spacing_cm = 20
    assert _ridge_planting_density_plants_m2(maize, 1) == pytest.approx(6.25)
    rice = FarmPhysicsState(crop_type="rice", num_ridges=2)
    assert _crop_water_stress(rice, 0.20) < _crop_water_stress(maize.physics, 0.20)
    assert all(0 <= rid < 2 for rid in rice.soil_sensor_ridges)
    assert "non-flooded" in " ".join(rice.snapshot()["model_assumptions"])


@pytest.mark.parametrize("crop,moisture", [("maize", 0.22), ("rice", 0.21)])
def test_crop_harvest_ready_uses_native_moisture_and_drying_basis(crop, moisture):
    physics = FarmPhysicsState(crop_type=crop, num_ridges=1)
    yld = physics.yield_recovery.states[0]
    yld.r8_reached = True
    yld.maturity_date = date(2026, 9, 1)
    yld.grain_moisture_frac = moisture
    yld.biological_yield_g_m2 = 750
    inputs = dict(
        weather=YieldWeatherInput(date(2026, 9, 2), 20, 0, 15, 1),
        phenology_by_ridge={0: YieldPhenologyInput(GrowthStage.R8, yld.maturity_date)},
        growth_by_ridge={0: YieldGrowthInput(750, 1500)},
    )
    result = physics.yield_recovery.update_day(**inputs)[0]
    assert result.harvest_ready
    result = physics.yield_recovery.update_day(
        **inputs, harvest_actions_by_ridge={0: HarvestAction(pass_completed=True)}
    )[0]
    assert result.harvested and result.drying_required
    assert result.recovered_yield_kg_ha_at_market_moisture > 0
    assert (result.recovered_yield_bu_ac_at_market_moisture is None) == (crop == "rice")


def test_mature_snapshot_keeps_crop_grain_moisture_and_recent_maturity():
    farm = FarmWorldApp(crop_type="maize", num_ridges=1)
    ridge = farm._ridges[0]
    ridge.planted, ridge.seed_type = True, "MAIZE_STANDARD"
    ridge.growth_stage, ridge.days_since_planted = "R6", 125
    ridge.grain_moisture_pct = 22.0
    farm.physics.engines_active = True
    now = datetime(2026, 9, 10, tzinfo=timezone.utc).timestamp()
    advance_physics_time(farm, now)
    assert ridge.growth_stage == "R6" and ridge.grain_moisture_pct == 22
    yld = farm.physics.yield_recovery.states[0]
    assert yld.maturity_date == date(2026, 9, 10)
    assert yld.biological_yield_g_m2 == 1000


def test_wofost_selection_uses_native_maize_and_rejects_the_legacy_seed_identity():
    farm = FarmWorldApp(crop_type="maize", num_ridges=1)
    pytest.importorskip("pcse")
    farm.configure_crop_backend("wofost")
    assert farm.physics.crop_backend.config.crop_name == "maize"
    assert farm.physics.crop_backend.config.variety_name == "Grain_maize_201"
    assert farm.validate_seed_for_crop("MAIZE_STANDARD") is not None
    assert farm.validate_seed_for_crop("MAIZE_201") is None
