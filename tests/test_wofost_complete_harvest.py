"""Wet-harvest equipment must retain crop, weather and safe-storage gates."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from fairy.apps.farm_world import FarmWorldApp, WeatherApp
from fairy.apps.farm_world.farm_world_app import DEFAULT_RIDGE_WIDTH_M, FIELD_LENGTH_M
from fairy.apps.farm_world.tractor_app import TractorApp
from fairy.physics import SoybeanStage
from fairy.time_manager import TimeManager


DAY = date(2017, 9, 14)


def _equipment(*, moisture=24.0, native_mass=False):
    """One mature fixture; only the existing yield/recovery machinery is real."""
    farm = FarmWorldApp()
    farm.num_ridges = 1
    farm._ridges = farm._ridges[:1]
    weather = WeatherApp()
    weather.set_weather(date=DAY.isoformat(), temp_c=18.0, humidity_pct=65.0,
                        wind_speed_ms=2.0, rainfall_mm=0.0,
                        solar_radiation=20.0 / 0.0864)
    tractor = TractorApp(farm, weather)
    clock = TimeManager()
    clock.reset(datetime(2017, 9, 14, 8, tzinfo=timezone.utc).timestamp())
    for app in (farm, weather, tractor):
        app.register_time_manager(clock)
    ridge = farm._ridges[0]
    ridge.planted = True
    ridge.growth_stage = "R8_FULL_MATURITY"
    ridge.grain_moisture_pct = moisture
    ridge.soil_vwc = 0.25
    if native_mass:
        physics = farm.physics
        physics.engines_active = True
        physics.yield_recovery.params.biological_yield_is_dry_matter = True
        phenology = physics.phenology.states[0]
        phenology.planted = True
        phenology.stage = SoybeanStage.R8
        phenology.maturity_date = DAY
        canopy = physics.canopy.states[0]
        canopy.yield_potential_g_m2 = 300.0
        canopy.aboveground_biomass_g_m2 = 650.0
        recovery = physics.yield_recovery.states[0]
        recovery.r8_reached = True
        recovery.maturity_date = DAY
        recovery.grain_moisture_frac = moisture / 100.0
        recovery.biological_yield_g_m2 = 300.0
        recovery.field_loss_fraction = 0.02
    return farm, weather, tractor


@pytest.mark.parametrize("limit,moisture,allowed", [
    (None, 18.0, True), (None, 18.01, False),
    (25.0, 24.99, True), (25.0, 25.0, True), (25.0, 25.01, False),
])
def test_equipment_moisture_boundary(limit, moisture, allowed):
    _, _, tractor = _equipment(moisture=moisture)
    if limit is not None:
        tractor.configure_harvest(max_grain_moisture_pct=limit)
    result = tractor.harvest(0, 0)
    assert ("error" not in result) is allowed
    if not allowed:
        assert "moisture too high" in result["error"]


@pytest.mark.parametrize("bad", [14.9, 25.01, float("nan"), float("inf"), -float("inf")])
def test_invalid_harvest_equipment_capability_is_rejected(bad):
    _, _, tractor = _equipment()
    with pytest.raises(ValueError, match=r"\[15, 25\]"):
        tractor.configure_harvest(max_grain_moisture_pct=bad)
    assert tractor.get_status()["harvest_moisture_limit_pct"] == 18.0


def test_equipment_capability_checkpoint_legacy_load_and_reset():
    _, _, tractor = _equipment()
    tractor.configure_harvest(max_grain_moisture_pct=25.0)
    checkpoint = tractor.get_state()
    tractor.reset()
    assert tractor.get_status()["harvest_moisture_limit_pct"] == 18.0
    tractor.load_state(checkpoint)
    assert tractor.get_status()["harvest_moisture_limit_pct"] == 25.0
    # A checkpoint written before this feature must retain its old capability.
    old_checkpoint = {k: v for k, v in checkpoint.items() if k != "harvest_moisture_limit_pct"}
    tractor.load_state(old_checkpoint)
    assert tractor.get_status()["harvest_moisture_limit_pct"] == 18.0
    tractor.configure_harvest(max_grain_moisture_pct=25.0)
    assert "configure_harvest" not in {tool.name for tool in tractor.get_tools()}


@pytest.mark.parametrize("barrier,expected", [
    ("immature", "not mature"), ("rain", "rainy"), ("soil", "Soil too wet"),
])
def test_wet_harvest_capability_preserves_other_operating_gates(barrier, expected):
    farm, weather, tractor = _equipment()
    tractor.configure_harvest(max_grain_moisture_pct=25.0)
    if barrier == "immature":
        farm._ridges[0].growth_stage = "R6_FULL_SEED"
    elif barrier == "rain":
        weather.set_weather(date=DAY.isoformat(), temp_c=18.0, humidity_pct=65.0,
                            wind_speed_ms=2.0, rainfall_mm=0.01, solar_radiation=20.0 / 0.0864)
    else:
        farm._ridges[0].soil_vwc = 0.401
    assert expected in tractor.harvest(0, 0)["error"]
    assert tractor.get_status()["grain_bin_kg"] == 0.0
    assert farm._ridges[0].planted


def test_native_dry_mass_wet_harvest_then_dry_and_store_converts_once():
    farm, _, tractor = _equipment(native_mass=True)
    tractor.configure_harvest(max_grain_moisture_pct=25.0)
    farm.configure_postharvest_market(max_storage_moisture_pct=13.5,
                                     drying_capacity_kg_per_day=1000.0,
                                     storage_capacity_kg=1000.0)
    harvested = tractor.harvest(0, 0)
    assert "error" not in harvested
    state = farm.physics.yield_recovery.states[0]
    assert "wet_harvest_machine_loss" in state.tags
    assert state.drying_required
    expected_dry_g_m2 = state.biological_yield_g_m2 * (1 - state.field_loss_fraction) * (1 - state.machine_loss_fraction)
    expected_standard_kg = expected_dry_g_m2 / 0.87 * FIELD_LENGTH_M * DEFAULT_RIDGE_WIDTH_M / 1000
    assert harvested["grain_kg_added"] == pytest.approx(expected_standard_kg, abs=0.01)
    assert "error" not in tractor.unload_grain()
    mass_before = farm._inventory.harvest_grain_kg
    dried = farm.dry_grain(target_moisture_pct=13.0)
    assert "error" not in dried
    assert not state.drying_required
    assert state.grain_moisture_frac == 0.13
    assert farm._inventory.harvest_grain_kg == mass_before
    stored = farm.store_grain()
    assert "warning" not in stored
    assert stored["moved_kg"] == mass_before
    assert farm._inventory.warehouse_grain_kg == mass_before
    assert farm._inventory.harvest_grain_kg == 0
    assert tractor.get_state()["grain_bin_kg"] == 0


def test_wet_harvest_without_drying_still_warns_at_storage():
    farm, _, tractor = _equipment(native_mass=True)
    tractor.configure_harvest(max_grain_moisture_pct=25.0)
    assert "error" not in tractor.harvest(0, 0)
    assert "error" not in tractor.unload_grain()
    assert "without drying" in farm.store_grain()["warning"]
