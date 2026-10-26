from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from fairy.apps.farm_world import FarmWorldApp, WeatherApp
from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
from fairy.physics import (
    HarvestAction,
    ManagementAction,
    ManagementActionType,
    PlantingConfig,
    SeedType,
    SoilWeatherInput,
    SoybeanStage,
)


SOWING_DAY = date(2026, 5, 1)
RIDGE_AREA_M2 = 174.2


@pytest.fixture
def wofost_api():
    """Real engine checks are optional when the WOFOST extra is not installed."""
    pytest.importorskip("pcse")
    from fairy.physics.wofost_backend import WofostBackend, WofostConfig

    return WofostBackend, WofostConfig


def _planted_physics(seed_type: SeedType = SeedType.STANDARD) -> FarmPhysicsState:
    physics = FarmPhysicsState(num_ridges=1)
    physics.phenology.plant_ridges(
        [0], PlantingConfig(planting_date=SOWING_DAY, seed_type=seed_type)
    )
    physics.management.states[0].planted = True
    physics.management.states[0].stand_fraction = 1.0
    return physics


def _weather(day: date, *, rain_mm: float = 0.0) -> SoilWeatherInput:
    return SoilWeatherInput(
        day=day,
        air_temp_mean_c=22.0,
        air_temp_min_c=16.0,
        air_temp_max_c=28.0,
        rain_mm=rain_mm,
        solar_rad_mj_m2=20.0,
        wind_ms=2.0,
    )


def _advance(backend, physics, day: date, *, actions=None, density=40.0, rain=0.0):
    backend.advance_day(
        physics=physics,
        day=day,
        weather=_weather(day, rain_mm=rain),
        actions_by_ridge=actions or {},
        density_by_ridge={0: density},
        ridge_area_m2=RIDGE_AREA_M2,
        humidity_pct=55.0,
    )


def _timestamp(day: date) -> float:
    return datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp()


def _one_ridge_farm() -> FarmWorldApp:
    farm = FarmWorldApp()
    farm.num_ridges = 1
    farm._ridges = farm._ridges[:1]
    farm._weather_app = WeatherApp()
    farm.configure_crop_backend("wofost")
    physics = farm.physics
    physics.phenology.plant_ridges(
        [0], PlantingConfig(planting_date=SOWING_DAY, seed_type=SeedType.STANDARD)
    )
    physics.management.states[0].planted = True
    physics.management.states[0].stand_fraction = 1.0
    ridge = farm._ridges[0]
    ridge.planted = True
    ridge.seed_type = SeedType.STANDARD.value
    ridge.seeds_planted = round(40.0 * RIDGE_AREA_M2)
    ridge.days_since_planted = 0
    return farm


def _pin_weather(farm: FarmWorldApp, day: date, *, rain: float = 0.0) -> None:
    farm._weather_app.set_weather(
        date=day.isoformat(),
        temp_c=22.0,
        humidity_pct=55.0,
        wind_speed_ms=2.0,
        rainfall_mm=rain,
        solar_radiation=20.0 / 0.0864,
    )


def test_existing_farm_defaults_to_legacy_backend() -> None:
    farm = FarmWorldApp()
    assert not farm.physics_active
    assert farm.physics.crop_backend_name == "legacy"
    assert farm.physics.crop_backend is None
    assert not farm.physics.yield_recovery.params.biological_yield_is_dry_matter
    assert not farm.physics_active
    with pytest.raises(ValueError):
        farm.configure_crop_backend("unknown")
    assert farm.physics.crop_backend_name == "legacy"


def test_reset_keeps_selected_native_backend_and_discards_previous_crop(wofost_api) -> None:
    farm = _one_ridge_farm()
    original = farm.physics.crop_backend
    _advance(original, farm.physics, SOWING_DAY, rain=2.0)
    assert original.export_state()["runs"]

    farm.reset()

    fresh = farm.physics.crop_backend
    assert fresh is not original
    assert fresh.config == original.config
    assert farm.physics.crop_backend_name == "wofost"
    assert farm.physics.yield_recovery.params.biological_yield_is_dry_matter
    assert fresh.last_day is None
    assert fresh.export_state()["runs"] == {}
    assert fresh.export_state()["pending"] == {}
    assert not farm.physics.phenology.states[0].planted
    assert original.export_state()["runs"]  # Prior native objects were not reset in place.


def test_missing_pcse_has_actionable_error_without_legacy_fallback() -> None:
    program = """
import builtins
from fairy.apps.farm_world import FarmWorldApp

original_import = builtins.__import__
def without_pcse(name, *args, **kwargs):
    if name == 'pcse' or name.startswith('pcse.'):
        raise ModuleNotFoundError('PCSE intentionally unavailable')
    return original_import(name, *args, **kwargs)
builtins.__import__ = without_pcse
farm = FarmWorldApp()
assert farm.physics.crop_backend_name == 'legacy'
try:
    farm.configure_crop_backend('wofost')
except RuntimeError as error:
    assert 'pip install' in str(error) and 'wofost' in str(error)
else:
    raise AssertionError('An unavailable WOFOST engine must not silently fall back')
assert farm.physics.crop_backend_name == 'legacy'
assert farm.physics.crop_backend is None
"""
    result = subprocess.run(
        [sys.executable, "-c", program], text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_pcse_grows_from_sowing_to_maturity(wofost_api) -> None:
    backend_type, config_type = wofost_api
    backend = backend_type(config_type())
    physics = _planted_physics()

    _advance(backend, physics, SOWING_DAY)
    assert not physics.phenology.states[0].emerged
    assert physics.phenology.states[0].stage == SoybeanStage.PLANTED_PRE_EMERGENCE
    assert physics.canopy.states[0].yield_potential_g_m2 == 0.0

    stages = []
    for offset in range(1, 161):
        day = SOWING_DAY + timedelta(days=offset)
        _advance(backend, physics, day, rain=10.0 if offset % 3 == 0 else 0.0)
        stages.append(physics.phenology.states[0].stage)
        if physics.phenology.states[0].maturity_date is not None:
            break

    phenology = physics.phenology.states[0]
    canopy = physics.canopy.states[0]
    assert phenology.emerged
    assert SOWING_DAY < phenology.emergence_date < phenology.maturity_date
    assert SoybeanStage.R1 in stages
    assert phenology.stage == SoybeanStage.R8
    assert canopy.aboveground_biomass_g_m2 > 0.0
    assert 0.0 < canopy.yield_potential_g_m2 < canopy.aboveground_biomass_g_m2


def test_real_pcse_irrigation_changes_root_zone_water(wofost_api) -> None:
    backend_type, config_type = wofost_api
    dry_backend = backend_type(config_type())
    wet_backend = backend_type(config_type())
    dry_physics = _planted_physics()
    wet_physics = _planted_physics()
    for offset in range(26):
        day = SOWING_DAY + timedelta(days=offset)
        _advance(dry_backend, dry_physics, day)
        _advance(wet_backend, wet_physics, day)

    day = SOWING_DAY + timedelta(days=26)
    _advance(dry_backend, dry_physics, day)
    _advance(
        wet_backend,
        wet_physics,
        day,
        actions={
            0: [
                ManagementAction(
                    ManagementActionType.IRRIGATION,
                    amount=25.0,
                    metadata={"water_mm": 25.0},
                )
            ]
        },
    )

    assert (
        wet_physics.soil.states[0].root_vwc
        > dry_physics.soil.states[0].root_vwc
    )


def test_deepcopy_replays_independently_and_deterministically(wofost_api) -> None:
    backend_type, config_type = wofost_api
    backend = backend_type(config_type())
    physics = _planted_physics()
    for offset in range(18):
        _advance(backend, physics, SOWING_DAY + timedelta(days=offset), rain=2.0)
    clone_backend = copy.deepcopy(backend)
    clone_physics = copy.deepcopy(physics)
    before = copy.deepcopy(backend.snapshot())
    day = SOWING_DAY + timedelta(days=18)
    actions = {
        0: [ManagementAction(ManagementActionType.IRRIGATION, amount=12.0)]
    }

    _advance(clone_backend, clone_physics, day, actions=actions)

    assert backend.snapshot() == before
    assert vars(physics.phenology.states[0]) != vars(clone_physics.phenology.states[0])

    _advance(backend, physics, day, actions=actions)

    assert backend.snapshot() == clone_backend.snapshot()
    assert vars(physics.soil.states[0]) == vars(clone_physics.soil.states[0])
    assert vars(physics.canopy.states[0]) == vars(clone_physics.canopy.states[0])

    restored_backend = backend_type.from_state(backend.export_state())
    restored_physics = copy.deepcopy(physics)
    next_day = day + timedelta(days=1)
    _advance(restored_backend, restored_physics, next_day, rain=3.0)
    _advance(backend, physics, next_day, rain=3.0)
    assert restored_backend.snapshot() == backend.snapshot()
    assert vars(restored_physics.canopy.states[0]) == vars(physics.canopy.states[0])


def test_fertilizer_uses_physical_mass_and_fertigation_water_metadata(wofost_api) -> None:
    backend_type, config_type = wofost_api
    backend = backend_type(config_type(fertilizer_n_fraction=0.46))
    physics = _planted_physics()
    control_backend = backend_type(config_type(fertilizer_n_fraction=0.46))
    control_physics = _planted_physics()
    actions = {
        0: [
            # Tractor fertilizer amount is a normalized relative value.
            ManagementAction(
                ManagementActionType.FERTIGATION,
                amount=0.1,
                metadata={"kg_per_ridge": 3.0, "method": "broadcast"},
            ),
            # FarmWorld fertigation amount is the carrier water depth.
            ManagementAction(
                ManagementActionType.FERTIGATION,
                amount=5.0,
                metadata={"fertilizer_kg_per_ridge": 2.0, "water_mm": 5.0},
            ),
        ]
    }

    _advance(backend, physics, SOWING_DAY, actions=actions)
    _advance(control_backend, control_physics, SOWING_DAY)

    ridge = backend.snapshot()["ridges"]["0"]
    assert ridge["cumulative_irrigation_mm"] == pytest.approx(5.0)
    assert ridge["cumulative_fertilizer_kg"] == pytest.approx(5.0)
    assert ridge["cumulative_n_kg_ha"] == pytest.approx(
        5.0 * 0.46 * 10000.0 / RIDGE_AREA_M2
    )
    assert ridge["pcse"]["TOTIRR"] == pytest.approx(0.5 * 0.92)
    assert (
        ridge["pcse"]["NAVAIL"]
        > control_backend.snapshot()["ridges"]["0"]["pcse"]["NAVAIL"]
    )


def test_preplant_base_fertilizer_enters_native_n_pool_once(wofost_api) -> None:
    backend_type, config_type = wofost_api
    backend = backend_type(config_type())
    control_backend = backend_type(config_type())
    physics = FarmPhysicsState(num_ridges=1)
    control_physics = FarmPhysicsState(num_ridges=1)
    preplant_day = SOWING_DAY - timedelta(days=1)
    _advance(
        backend,
        physics,
        preplant_day,
        actions={0: [ManagementAction(
            ManagementActionType.BASE_FERTILIZER,
            amount=1.0,
            metadata={"kg_per_ridge": 30.0},
        )]},
    )
    _advance(control_backend, control_physics, preplant_day)
    # A checkpoint before crop creation must retain the physical fertilizer.
    backend = backend_type.from_state(json.loads(json.dumps(backend.export_state())))
    for candidate in (physics, control_physics):
        candidate.phenology.plant_ridges(
            [0], PlantingConfig(planting_date=SOWING_DAY, seed_type=SeedType.STANDARD)
        )
        candidate.management.states[0].planted = True
        candidate.management.states[0].stand_fraction = 1.0

    expected_n = 30.0 * 0.46 * 10000.0 / RIDGE_AREA_M2
    for offset in range(2):
        day = SOWING_DAY + timedelta(days=offset)
        _advance(backend, physics, day)
        _advance(control_backend, control_physics, day)
        ridge = backend.snapshot()["ridges"]["0"]
        control = control_backend.snapshot()["ridges"]["0"]
        assert ridge["cumulative_fertilizer_kg"] == pytest.approx(30.0)
        assert ridge["cumulative_n_kg_ha"] == pytest.approx(expected_n)
        assert ridge["pcse"]["NAVAIL"] - control["pcse"]["NAVAIL"] == pytest.approx(
            expected_n * 0.7
        )


def test_native_n_limitation_changes_biomass_and_seed_yield(wofost_api) -> None:
    backend_type, config_type = wofost_api
    # Suppress soybean fixation to isolate fertilizer N under ample water.
    config = config_type(
        initial_available_n_kg_ha=1.0,
        base_soil_n_kg_ha=0.0,
        soil_n_mineralization_fraction=0.0,
        parameter_overrides={"*": {"NFIX_FR": 0.0}},
    )
    fertilized_backend = backend_type(config)
    poor_backend = backend_type(config)
    fertilized_physics = _planted_physics()
    poor_physics = _planted_physics()
    fertilizer = {0: [ManagementAction(
        ManagementActionType.BASE_FERTILIZER,
        amount=1.0,
        metadata={"kg_per_ridge": 10.0},
    )]}
    for offset in range(161):
        day = SOWING_DAY + timedelta(days=offset)
        for backend, physics, actions in (
            (fertilized_backend, fertilized_physics, fertilizer if offset == 0 else {}),
            (poor_backend, poor_physics, {}),
        ):
            if physics.phenology.states[0].maturity_date is None:
                _advance(backend, physics, day, actions=actions, rain=6.0)
        if all(
            physics.phenology.states[0].maturity_date is not None
            for physics in (fertilized_physics, poor_physics)
        ):
            break

    assert fertilized_physics.phenology.states[0].maturity_date is not None
    assert poor_physics.phenology.states[0].maturity_date is not None
    assert (
        fertilized_physics.canopy.states[0].aboveground_biomass_g_m2
        > poor_physics.canopy.states[0].aboveground_biomass_g_m2
    )
    assert (
        fertilized_physics.canopy.states[0].yield_potential_g_m2
        > poor_physics.canopy.states[0].yield_potential_g_m2
    )
    assert (
        fertilized_backend.snapshot()["ridges"]["0"]["pcse"]["NuptakeTotal"]
        > poor_backend.snapshot()["ridges"]["0"]["pcse"]["NuptakeTotal"]
    )


def test_subdaily_queued_irrigation_applies_once_on_daily_tick(wofost_api) -> None:
    # Both schedules deliver the same water before the same daily growth tick.
    immediate_farm = _one_ridge_farm()
    daily_farm = _one_ridge_farm()
    for farm in (immediate_farm, daily_farm):
        _pin_weather(farm, SOWING_DAY)
        assert farm.advance_physics_time(_timestamp(SOWING_DAY))["day_ticks_run"] == 0
        farm.physics.queue_management_action(
            0, ManagementAction(ManagementActionType.IRRIGATION, amount=18.0)
        )

    immediate_farm.advance_physics_time(_timestamp(SOWING_DAY) + 3600.0)
    next_day = SOWING_DAY + timedelta(days=1)
    for farm in (immediate_farm, daily_farm):
        _pin_weather(farm, next_day)
        assert farm.advance_physics_time(_timestamp(next_day))["day_ticks_run"] == 1

    expected = daily_farm.physics.crop_backend.snapshot()
    actual = immediate_farm.physics.crop_backend.snapshot()
    assert actual == expected
    assert actual["ridges"]["0"]["cumulative_irrigation_mm"] == pytest.approx(18.0)
    assert immediate_farm.advance_physics_time(_timestamp(next_day))["status"] == "noop"
    assert immediate_farm.physics.crop_backend.snapshot() == actual

    for farm in (immediate_farm, daily_farm):
        following_day = next_day + timedelta(days=1)
        _pin_weather(farm, following_day)
        farm.advance_physics_time(_timestamp(following_day))
    assert immediate_farm.physics.crop_backend.snapshot() == daily_farm.physics.crop_backend.snapshot()
    assert (
        immediate_farm.physics.crop_backend.snapshot()["ridges"]["0"]["cumulative_irrigation_mm"]
        == pytest.approx(18.0)
    )


def test_density_changes_initial_crop_canopy(wofost_api) -> None:
    backend_type, config_type = wofost_api
    sparse_backend = backend_type(config_type())
    dense_backend = backend_type(config_type())
    sparse_physics = _planted_physics()
    dense_physics = _planted_physics()
    for offset in range(16):
        day = SOWING_DAY + timedelta(days=offset)
        _advance(sparse_backend, sparse_physics, day, density=10.0, rain=3.0)
        _advance(dense_backend, dense_physics, day, density=40.0, rain=3.0)

    assert sparse_physics.phenology.states[0].emerged
    assert dense_physics.phenology.states[0].emerged
    assert (
        dense_physics.canopy.states[0].lai
        > sparse_physics.canopy.states[0].lai
    )


def test_explicit_zero_stand_does_not_become_a_full_native_crop(wofost_api) -> None:
    backend_type, config_type = wofost_api
    failed = FarmPhysicsState(num_ridges=2)
    failed.phenology.plant_ridges(
        [0, 1], PlantingConfig(planting_date=SOWING_DAY, seed_type=SeedType.STANDARD))
    for state in failed.management.states.values():
        state.planted, state.stand_fraction = True, 1.0
    failed.management.states[1].stand_fraction = 0.0
    backend = backend_type(config_type())
    with pytest.raises(ValueError, match="failed stand.*positive biomass"):
        _advance(backend, failed, SOWING_DAY)
    assert not backend.has_started
    assert failed.management.states[1].stand_fraction == 0


@pytest.mark.parametrize("stand", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_stand_is_rejected_before_native_model_creation(wofost_api, stand) -> None:
    backend_type, config_type = wofost_api
    physics = _planted_physics()
    physics.management.states[0].stand_fraction = stand
    backend = backend_type(config_type())
    with pytest.raises(ValueError, match="initial_stand_fraction"):
        _advance(backend, physics, SOWING_DAY)
    assert not backend.has_started


def test_explicit_cultivar_map_changes_native_maturity(wofost_api) -> None:
    backend_type, config_type = wofost_api
    early_backend = backend_type(config_type(variety_name="Soybean_901"))
    later_backend = backend_type(
        config_type(cultivar_map={SeedType.HEINONG84.value: "Soybean_902"})
    )
    early_physics = _planted_physics()
    later_physics = _planted_physics(SeedType.HEINONG84)
    first_flowering = {}
    for offset in range(161):
        day = SOWING_DAY + timedelta(days=offset)
        for name, backend, physics in (
            ("early", early_backend, early_physics),
            ("later", later_backend, later_physics),
        ):
            if physics.phenology.states[0].maturity_date is None:
                _advance(backend, physics, day, rain=3.0)
                if physics.phenology.states[0].stage == SoybeanStage.R1:
                    first_flowering.setdefault(name, day)
        if all(
            physics.phenology.states[0].maturity_date is not None
            for physics in (early_physics, later_physics)
        ):
            break

    # These published varieties share TSUM1=350, while TSUM2 is 850 vs 950.
    assert first_flowering["early"] == first_flowering["later"]
    assert (
        early_physics.phenology.states[0].maturity_date
        < later_physics.phenology.states[0].maturity_date
    )


def test_existing_biotic_pressure_affects_native_growth(wofost_api) -> None:
    backend_type, config_type = wofost_api
    healthy_backend = backend_type(config_type())
    damaged_backend = backend_type(config_type())
    healthy_physics = _planted_physics()
    damaged_physics = _planted_physics()
    damaged_physics.biotic.states[0].disease_pressure = 0.9
    for offset in range(51):
        day = SOWING_DAY + timedelta(days=offset)
        _advance(healthy_backend, healthy_physics, day, rain=3.0)
        _advance(damaged_backend, damaged_physics, day, rain=3.0)

    assert (
        healthy_physics.canopy.states[0].aboveground_biomass_g_m2
        > damaged_physics.canopy.states[0].aboveground_biomass_g_m2
        > 0.0
    )


def test_mature_crop_retains_delayed_harvest_losses_and_recovery(wofost_api) -> None:
    farm = _one_ridge_farm()
    _pin_weather(farm, SOWING_DAY)
    farm.advance_physics_time(_timestamp(SOWING_DAY))
    for offset in range(1, 161):
        day = SOWING_DAY + timedelta(days=offset)
        _pin_weather(farm, day, rain=10.0 if offset % 3 == 0 else 0.0)
        farm.advance_physics_time(_timestamp(day))
        if farm.physics.yield_recovery.states[0].r8_reached:
            break

    state = farm.physics.yield_recovery.states[0]
    assert state.r8_reached
    biological_yield = state.biological_yield_g_m2
    first_field_loss = state.field_loss_fraction
    assert biological_yield > 0.0
    assert not state.harvested
    assert state.recovered_yield_g_m2_at_market_moisture == 0.0
    maturity_day = day

    for offset in range(1, 22):
        day = maturity_day + timedelta(days=offset)
        _pin_weather(farm, day)
        farm.advance_physics_time(_timestamp(day))

    assert state.biological_yield_g_m2 == biological_yield
    assert state.field_loss_fraction > first_field_loss
    assert not state.harvested
    assert state.recovered_yield_g_m2_at_market_moisture == 0.0

    farm.physics.queue_harvest(0, HarvestAction())
    day += timedelta(days=1)
    _pin_weather(farm, day)
    farm.advance_physics_time(_timestamp(day))
    assert state.harvested
    assert farm.physics.yield_recovery.params.biological_yield_is_dry_matter
    assert state.recovered_yield_g_m2_at_market_moisture > 0.0
    assert state.recovered_yield_g_m2_at_market_moisture < biological_yield / 0.87
    assert state.recovered_yield_g_m2_at_market_moisture * 0.87 == pytest.approx(
        biological_yield * (1.0 - state.field_loss_fraction) * (1.0 - state.machine_loss_fraction)
    )


@pytest.mark.parametrize("drain_subdaily", [False, True])
@pytest.mark.parametrize("custom_soil", [False, True])
def test_full_farm_checkpoint_preserves_pending_irrigation(
    wofost_api, drain_subdaily, custom_soil
) -> None:
    from fairy.scenarios.farm_world_fullseason_v2.farm_checkpoint_state import (
        export_farm_checkpoint_state,
        restore_farm_checkpoint_state,
    )

    farm = _one_ridge_farm()
    if custom_soil:
        farm.physics.soil.params = replace(
            farm.physics.soil.params,
            root_depth_m=0.5,
            wilting_point_vwc=0.12,
            field_capacity_vwc=0.32,
            saturation_vwc=0.46,
        )
    _pin_weather(farm, SOWING_DAY)
    farm.advance_physics_time(_timestamp(SOWING_DAY))
    next_day = SOWING_DAY + timedelta(days=1)
    _pin_weather(farm, next_day)
    farm.advance_physics_time(_timestamp(next_day))
    farm.physics.queue_management_action(
        0, ManagementAction(ManagementActionType.IRRIGATION, amount=18.0)
    )
    if drain_subdaily:
        farm.advance_physics_time(_timestamp(next_day) + 3600.0)

    checkpoint = json.loads(json.dumps(export_farm_checkpoint_state(
        farm_world=farm,
        weather_app=farm._weather_app,
        scenario_id="wofost_checkpoint_test",
        checkpoint_label="irrigation_before_daily_tick",
    )))
    restored = FarmWorldApp()
    restored.num_ridges = 1
    restored._ridges = restored._ridges[:1]
    restored._weather_app = WeatherApp()
    restore_farm_checkpoint_state(
        farm_world=restored,
        weather_app=restored._weather_app,
        checkpoint_state=checkpoint,
    )

    assert restored.physics.crop_backend_name == "wofost"
    assert restored.physics.soil.params == farm.physics.soil.params
    assert restored.physics.yield_recovery.params.biological_yield_is_dry_matter
    assert restored.physics.crop_backend.snapshot() == farm.physics.crop_backend.snapshot()
    following_day = next_day + timedelta(days=1)
    for candidate in (farm, restored):
        _pin_weather(candidate, following_day)
        candidate.advance_physics_time(_timestamp(following_day))
    assert restored.physics.crop_backend.snapshot() == farm.physics.crop_backend.snapshot()
    assert vars(restored.physics.canopy.states[0]) == vars(farm.physics.canopy.states[0])
    assert vars(restored.physics.soil.states[0]) == vars(farm.physics.soil.states[0])
    assert (
        restored.physics.crop_backend.snapshot()["ridges"]["0"]["cumulative_irrigation_mm"]
        == pytest.approx(18.0)
    )


def test_midseason_backend_change_requires_a_native_checkpoint(wofost_api) -> None:
    farm = _one_ridge_farm()
    _pin_weather(farm, SOWING_DAY)
    farm.advance_physics_time(_timestamp(SOWING_DAY))
    day = SOWING_DAY + timedelta(days=1)
    _pin_weather(farm, day)
    farm.advance_physics_time(_timestamp(day))
    original = farm.physics.crop_backend.snapshot()

    with pytest.raises(ValueError, match="before planting|checkpoint"):
        farm.configure_crop_backend("legacy")
    with pytest.raises(ValueError, match="before planting|checkpoint"):
        farm.configure_crop_backend("wofost", variety_name="Soybean_902")
    assert farm.physics.crop_backend.snapshot() == original


def test_scenario_and_cli_accept_wofost_configuration(wofost_api, tmp_path: Path) -> None:
    from fairy.scenarios.farm_world_physics.scenario_field_prep_physics_action_tick import (
        ScenarioFarmWorldFieldPrepPhysicsActionTick,
    )

    config = {"variety_name": "Soybean_902", "fertilizer_n_fraction": 0.2}
    scenario = ScenarioFarmWorldFieldPrepPhysicsActionTick(
        crop_backend="wofost", crop_backend_options=config
    )
    scenario.setup()
    assert scenario.get_typed_app(FarmWorldApp).physics.crop_backend.config.variety_name == "Soybean_902"

    config_path = tmp_path / "wofost_config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    scenario_id = "scenario_farm_world_field_prep_physics_action_tick"
    output_dir = tmp_path / "runs"
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run(
        [sys.executable, "-m", "fairy.cli", "--scenario", scenario_id,
         "--build-oracle", "--wofost-config", str(config_path),
         "--output-dir", str(output_dir)],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((output_dir / f"{scenario_id}.run_report.json").read_text())
    provenance = report["crop_backend_provenance"]
    assert provenance["backend"] == "wofost"
    assert provenance["config"]["variety_name"] == "Soybean_902"
    assert provenance["config"]["fertilizer_n_fraction"] == 0.2
