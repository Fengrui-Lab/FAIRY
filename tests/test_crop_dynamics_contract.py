"""Crop lifecycle, pure preflight and versioned native-state contracts."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from fairy.apps.farm_world.crop_dynamics import create_crop_dynamics
from fairy.apps.farm_world.crop_snapshot import restore_physics, snapshot_physics
from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
from fairy.apps.farm_world.models import RidgeState
from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs, _run_daily_tick
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.crops.catalog import MAIZE
from fairy.crops.maize import MaizeCropModel, MaizeStage
from fairy.crops.rules import ScalarRange
from fairy.crops.runtime import PlantingEvent
from fairy.physics import HarvestAction
from fairy.physics.phenology_engine import SoybeanStage


START = date(2026, 5, 5)


def planting(seed="MAIZE_EARLY_2026", *, ridges=(0, 1), replace_existing=False):
    return PlantingEvent(ridges, START, seed, 4.5,
                         {rid: 1.0 for rid in ridges},
                         {rid: 6.5 for rid in ridges},
                         replace_existing=replace_existing)


def test_preflight_rejects_late_invalid_ridge_without_planting_early_ridge():
    crop = create_crop_dynamics("maize", 2)
    event = replace(planting(), density_by_ridge={0: 6.5, 1: float("nan")})
    before = deepcopy(crop.get_state())
    with pytest.raises(ValueError):
        crop.validate_planting(event)
    assert crop.get_state() == before
    with pytest.raises(ValueError):
        crop.plant(event)
    assert crop.get_state() == before


def test_pure_model_uses_the_injected_planting_rules():
    rules = replace(MAIZE.planting_rules, depth_cm=ScalarRange(4.0, 4.2))
    model = MaizeCropModel(2, planting_rules=rules)
    with pytest.raises(ValueError, match="planting depth"):
        model.validate_planting(planting())
    model.validate_planting(replace(planting(), depth_cm=4.1))
    assert not any(state.planted for state in model.phenology.states.values())


@pytest.mark.parametrize("species,seed", [("soybean", "HEINONG84"), ("maize", "MAIZE_EARLY_2026")])
def test_harvested_projection_has_no_current_living_stand(species, seed):
    # Minimal native-state fixture isolates current-vs-historical semantics;
    # full-season public tools are covered by the scenario integration tests.
    crop = create_crop_dynamics(species, 2)
    crop.plant(planting(seed))
    crop.phenology.states[0].emerged = True
    crop.yield_recovery.states[0].harvested = True
    management = SimpleNamespace(stand_fraction=0.82)
    status = crop.project(0, management)
    assert status.harvested and not status.current_planted and not status.emerged
    assert status.current_stand == 0.0
    assert management.stand_fraction == 0.82  # historical establishment


def test_native_maize_harvest_projection_keeps_historical_establishment():
    crop = create_crop_dynamics("maize", 2)
    crop.plant(planting())
    phen, grain = crop.phenology.states[0], crop.yield_recovery.states[0]
    phen.emerged, phen.stage = True, MaizeStage.R6_MATURITY
    grain.r6_reached, grain.grain_moisture_frac = True, 0.20
    grain.biological_yield_g_m2 = 800.0
    crop.settle_harvest(None, START + timedelta(days=140), {}, {0: HarvestAction()})
    status = crop.project(0, SimpleNamespace(stand_fraction=0.93))
    assert status.stage == "BARE" and status.current_stand == 0
    assert crop.yield_recovery.states[0].recovered_yield_g_m2_at_market_moisture > 0


def test_maize_public_yield_fraction_uses_dry_matter_basis():
    crop = create_crop_dynamics("maize", 2)
    crop.plant(planting())
    canopy = crop.canopy.states[0]
    canopy.initialized = True
    canopy.yield_potential_g_m2 = crop.model.params.max_biological_yield_g_m2
    status = crop.project(0, SimpleNamespace(stand_fraction=1.0))
    assert status.yield_potential == 1.0
    assert crop.max_recoverable_yield_g_m2 == pytest.approx(
        canopy.yield_potential_g_m2 / (1 - crop.model.params.market_moisture_frac))


def test_soybean_new_season_starts_with_new_crop_canopy_and_yield():
    crop = create_crop_dynamics("soybean", 2)
    crop.plant(planting("HEINONG84"))
    old = crop.phenology.states[0]
    old.stage, old.emerged = SoybeanStage.R8, True
    old.maturity_date = START + timedelta(days=140)
    crop.canopy.states[0].initialized = True
    crop.canopy.states[0].aboveground_biomass_g_m2 = 500.0
    crop.yield_recovery.states[0].harvested = True
    crop.yield_recovery.states[0].biological_yield_g_m2 = 250.0
    crop.yield_recovery.states[0].harvest_date = START + timedelta(days=150)
    neighbor = deepcopy(crop.get_state()["phenology"]["states"]["1"])
    event = replace(planting("HEINONG84", ridges=(0,)), planting_date=date(2027, 5, 5))
    crop.validate_planting(event)
    assert crop.yield_recovery.states[0].harvested  # preflight stays pure
    crop.plant(event)
    status = crop.project(0, SimpleNamespace(stand_fraction=1.0))
    assert status.current_planted and not status.harvested and not status.emerged
    assert crop.phenology.states[0].planting_date == date(2027, 5, 5)
    assert crop.phenology.states[0].maturity_date is None
    assert not crop.canopy.states[0].initialized
    assert crop.canopy.states[0].aboveground_biomass_g_m2 == 0.0
    assert crop.yield_recovery.states[0].biological_yield_g_m2 == 0.0
    assert crop.get_state()["phenology"]["states"]["1"] == neighbor


@pytest.mark.parametrize("species,seed", [("soybean", "HEINONG84"), ("maize", "MAIZE_EARLY_2026")])
def test_soil_tick_uses_no_living_cover_after_harvest_and_preserves_canopy_history(species, seed):
    physics = FarmPhysicsState(num_ridges=1, crop_id=species)
    physics.crop.plant(planting(seed, ridges=(0,)))
    phen, canopy, grain = (component.states[0] for component in (
        physics.phenology, physics.canopy, physics.yield_recovery))
    phen.emerged = True
    phen.stage = SoybeanStage.R8 if species == "soybean" else MaizeStage.R6_MATURITY
    canopy.initialized, canopy.canopy_cover = True, 0.8
    canopy.aboveground_biomass_g_m2 = 500.0
    grain.harvested = True
    canopy_history = deepcopy(canopy)
    weather_app = WeatherApp()
    weather_app.set_weather(date="2026-09-25", temp_c=20.0, humidity_pct=55.0,
                            wind_speed_ms=2.0, rainfall_mm=0.0, solar_radiation=250.0)
    day = date(2026, 9, 25)
    weather = _build_weather_inputs(weather_app, day, physics=physics)
    world = SimpleNamespace(physics=physics, _ridges=[RidgeState.default(0)], ridge_width_m=1.1)
    with patch.object(physics.soil, "update_day", wraps=physics.soil.update_day) as soil_tick:
        _run_daily_tick(world, physics, weather_app, day, weather)
    assert soil_tick.call_count == 1
    assert soil_tick.call_args.kwargs["canopy_cover_by_ridge"] == {0: 0.0}
    assert physics.canopy.states[0] == canopy_history
    assert not physics.crop.project(0, physics.management.states[0]).current_planted


def test_replant_plan_is_pure_and_full_replant_resets_only_target_crop():
    crop = create_crop_dynamics("maize", 2)
    crop.plant(planting())
    management = {rid: SimpleNamespace(planted=True, stand_fraction=0.6) for rid in (0, 1)}
    crop.phenology.states[0].emerged = True
    crop.canopy.states[0].initialized = True
    crop.canopy.states[0].aboveground_biomass_g_m2 = 50.0
    event = replace(planting(ridges=(0,)), planting_date=START + timedelta(days=20))
    before = deepcopy(crop.get_state())
    with pytest.raises(ValueError, match="gap-filling"):
        crop.prepare_replant(event, management, full_replant=False)
    assert crop.get_state() == before
    plan = crop.prepare_replant(event, management, full_replant=True)
    assert crop.get_state() == before
    crop.apply_replant(plan, management)
    assert not crop.phenology.states[0].emerged
    assert crop.canopy.states[0].aboveground_biomass_g_m2 == 0
    assert crop.phenology.states[1].planting_date == START
    assert management[0].stand_fraction == 1.0
    assert management[1].stand_fraction == 0.6


def test_soybean_gap_fill_preserves_established_crop_and_uses_original_recovery():
    crop = create_crop_dynamics("soybean", 2)
    crop.plant(planting("HEINONG84"))
    crop.phenology.states[0].stage = SoybeanStage.R1
    crop.phenology.states[0].emerged = True
    crop.canopy.states[0].initialized = True
    crop.canopy.states[0].aboveground_biomass_g_m2 = 90.0
    management = {0: SimpleNamespace(planted=True, stand_fraction=0.4,
                                    planting_quality=0.4, tags=[])}
    event = replace(planting("HEINONG84", ridges=(0,)), planting_date=START + timedelta(days=20))
    plan = crop.prepare_replant(event, management, full_replant=False)
    assert not plan.fresh_ridge_ids
    assert plan.stand_after[0] == pytest.approx(0.76)
    crop.apply_replant(plan, management)
    assert crop.phenology.states[0].stage == SoybeanStage.R1
    assert crop.canopy.states[0].aboveground_biomass_g_m2 == 90.0
    assert management[0].stand_fraction == pytest.approx(0.76)


@pytest.mark.parametrize("species,seed", [("soybean", "HEINONG84"), ("maize", "MAIZE_EARLY_2026")])
def test_complete_native_crop_snapshot_json_restores_exactly(species, seed):
    physics = FarmPhysicsState(num_ridges=2, crop_id=species)
    physics.crop.plant(planting(seed))
    if species == "soybean":
        physics.crop.apply_seed_growth_overrides(physics, {seed: {"rue_g_mj_apar": 3.14}})
    snapshot = json.loads(json.dumps(snapshot_physics(physics), allow_nan=False))
    restored = restore_physics(snapshot, 2, crop_id=species)
    assert snapshot_physics(restored) == snapshot
    assert restored.phenology is restored.crop.phenology
    assert restored.phenology is not physics.phenology
    assert restored.crop.project(0, restored.management.states[0]) == physics.crop.project(0, physics.management.states[0])
