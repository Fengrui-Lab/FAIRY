"""Actions are immediate; daily aging is charged only by calendar ticks."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pytest

from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.physics_orchestrator import advance_physics_time
from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.physics.biotic_pressure_engine import (
    BioticCropInput, BioticPressureEngine, BioticPressureState, BioticWeatherInput,
    GrowthStage as BioticStage, TreatmentApplication, TreatmentType,
)
from fairy.physics.management_effect_engine import (
    ManagementAction, ManagementActionType, ManagementEffectEngine,
    ManagementWeatherInput,
)
from fairy.physics.yield_recovery_engine import (
    GrowthStage as YieldStage, HarvestAction, YieldGrowthInput,
    YieldPhenologyInput, YieldRecoveryEngine, YieldRecoveryState,
    YieldWeatherInput,
)
from fairy.time_manager import TimeManager


DAY = date(2026, 9, 15)
START = datetime(2026, 9, 15, 7, tzinfo=timezone.utc).timestamp()


def test_management_same_day_new_actions_do_not_age_existing_effects():
    engine = ManagementEffectEngine(num_ridges=4)
    weather = ManagementWeatherInput(day=DAY)
    engine.update_day(weather)
    engine.update_day(weather, {0: [ManagementAction(ManagementActionType.INSECTICIDE),
                                  ManagementAction(ManagementActionType.IRRIGATION, amount=5)]})
    before = deepcopy(engine.states[0])
    for ridge_id in (1, 2, 3):
        engine.update_day(weather, {ridge_id: [ManagementAction(ManagementActionType.INSECTICIDE)]})
    state = engine.states[0]
    assert state.insecticide_residual_days_left == before.insecticide_residual_days_left == 10
    assert state.days_since_irrigation == before.days_since_irrigation == 0
    assert state.nutrient_index == before.nutrient_index
    assert state.cumulative_pesticide_applications == 1
    assert all(engine.states[rid].insecticide_residual_days_left == 10 for rid in range(4))
    engine.update_day(ManagementWeatherInput(day=DAY + timedelta(days=1)))
    assert state.insecticide_residual_days_left == 9
    assert state.days_since_irrigation == 1


def test_biotic_same_day_new_treatments_do_not_repeat_growth_or_exposure():
    engine = BioticPressureEngine(num_ridges=4, initial_insect_pressure=0.6)
    weather = BioticWeatherInput(day=DAY, air_temp_mean_c=27, rain_mm=0)
    crops = {rid: BioticCropInput(stage=BioticStage.R3) for rid in range(4)}
    engine.update_day(weather, crops)
    engine.update_day(weather, crops, treatments_by_ridge={
        0: [TreatmentApplication(TreatmentType.INSECTICIDE)]})
    before = deepcopy(engine.states[0])
    for ridge_id in (1, 2, 3):
        engine.update_day(weather, crops, treatments_by_ridge={
            ridge_id: [TreatmentApplication(TreatmentType.INSECTICIDE)]})
    assert engine.states[0].insecticide_residual_days_left == 10
    assert engine.states[0].insect_pressure == before.insect_pressure
    assert engine.states[0].cumulative_insect_pressure == before.cumulative_insect_pressure
    assert all(engine.states[rid].insect_pressure < 0.3 for rid in range(4))
    engine.update_day(BioticWeatherInput(DAY + timedelta(days=1), 27, 0), crops)
    assert engine.states[0].insecticide_residual_days_left == 9
    assert engine.states[0].cumulative_insect_pressure > before.cumulative_insect_pressure


def test_subdaily_effects_do_not_mark_a_daily_tick_complete():
    management = ManagementEffectEngine(num_ridges=1)
    biotic = BioticPressureEngine(num_ridges=1, initial_insect_pressure=0.6)
    management.update_day(ManagementWeatherInput(DAY), {
        0: [ManagementAction(ManagementActionType.INSECTICIDE)]}, advance_daily=False)
    biotic.update_day(BioticWeatherInput(DAY, 27, 0), {
        0: BioticCropInput(stage=BioticStage.R3)}, treatments_by_ridge={
        0: [TreatmentApplication(TreatmentType.INSECTICIDE)]}, advance_daily=False)
    assert management.states[0].last_nutrient_decay_day is None
    assert biotic.states[0].last_daily_update_day is None
    assert biotic.states[0].cumulative_insect_pressure == 0
    tomorrow = DAY + timedelta(days=1)
    management.update_day(ManagementWeatherInput(tomorrow))
    biotic.update_day(BioticWeatherInput(tomorrow, 27, 0), {
        0: BioticCropInput(stage=BioticStage.R3)})
    assert management.states[0].insecticide_residual_days_left == 9
    assert biotic.states[0].insecticide_residual_days_left == 9
    assert biotic.states[0].cumulative_insect_pressure > 0


def yield_inputs():
    weather = YieldWeatherInput(DAY, 20, 0, 20, 2)
    phenology = {rid: YieldPhenologyInput(YieldStage.R8, DAY) for rid in range(2)}
    growth = {rid: YieldGrowthInput(400) for rid in range(2)}
    return weather, phenology, growth


def test_yield_daily_update_is_idempotent_and_harvest_does_not_dry_again():
    engine = YieldRecoveryEngine(num_ridges=2)
    weather, phenology, growth = yield_inputs()
    engine.update_day(weather, phenology, growth)
    before = deepcopy(engine.states)
    engine.update_day(weather, phenology, growth)
    assert engine.states[0].grain_moisture_frac == before[0].grain_moisture_frac
    non_target = deepcopy(engine.states[1])
    results = engine.settle_harvest(weather, phenology, growth, {0: HarvestAction()})
    assert [result.ridge_id for result in results] == [0]
    assert engine.states[0].harvested
    assert engine.states[0].grain_moisture_frac == before[0].grain_moisture_frac
    assert engine.states[0].field_loss_fraction == before[0].field_loss_fraction
    assert engine.states[1] == non_target


def test_new_date_cursors_roundtrip_and_old_state_dictionaries_remain_valid():
    for state_class in (BioticPressureState, YieldRecoveryState):
        legacy = vars(state_class(ridge_id=0)).copy()
        legacy.pop("last_daily_update_day")
        assert state_class(**legacy).last_daily_update_day is None
        state = state_class(**legacy, last_daily_update_day=DAY)
        assert state_class(**vars(state)) == state


def make_field(monkeypatch, warehouse=None):
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: START)
    clock = TimeManager()
    clock.reset(START)
    world, weather = FarmWorldApp(), WeatherApp()
    weather.set_weather(date=DAY.isoformat(), temp_c=20, humidity_pct=50,
                        wind_speed_ms=1, rainfall_mm=0, solar_radiation=350,
                        avg_soil_vwc=0.23)
    world.configure_physics_profile("idempotence_static_weather")
    environment = FarmEnvironment([FarmContext("farm_a", world, weather)], weather, clock,
                                  warehouse=warehouse)
    environment.sync()
    return environment, world


@pytest.fixture
def field(monkeypatch):
    return make_field(monkeypatch)


@pytest.fixture
def shared_field(monkeypatch):
    return make_field(monkeypatch, WarehouseApp(stock=WarehouseStock(
        seed_stock={"STANDARD": 100_000}, pesticide_liters=100.0,
        fertilizer_kg=500.0, fuel_liters=200.0,
    )))


def test_equal_timestamp_commits_irrigation_once_without_daily_evolution(field):
    env, world = field
    physics = world.physics
    before = physics.soil.states[0].top_vwc
    physics.queue_management_action(0, ManagementAction(ManagementActionType.IRRIGATION, amount=5))
    result = env.sync()["farm_a"]
    assert result["day_ticks_run"] == 0
    assert physics.soil.states[0].top_vwc > before
    assert physics.management.states[0].cumulative_irrigation_mm == 5
    assert physics.management.states[0].days_since_irrigation == 0
    assert physics.management.states[0].last_nutrient_decay_day is None
    once = physics.soil.states[0].top_vwc
    assert env.sync()["farm_a"]["status"] == "noop"
    assert physics.soil.states[0].top_vwc == once
    env.advance_time(86400)
    assert physics.management.states[0].days_since_irrigation == 1


def test_sequential_23_minute_treatments_preserve_first_ridge_effect(field):
    env, world = field
    physics = world.physics
    before = None
    for ridge_id in range(4):
        physics.queue_management_action(ridge_id, ManagementAction(ManagementActionType.INSECTICIDE))
        physics.queue_treatment(ridge_id, TreatmentApplication(TreatmentType.INSECTICIDE))
        env.sync()
        if ridge_id == 0:
            before = deepcopy(physics.biotic.states[0])
        if ridge_id < 3:
            env.advance_time(23 * 60 / 3)
    assert env.time_manager.offset == 23 * 60
    assert physics.management.states[0].insecticide_residual_days_left == 10
    assert physics.biotic.states[0].insecticide_residual_days_left == 10
    assert physics.biotic.states[0].insect_pressure == before.insect_pressure
    assert physics.biotic.states[0].cumulative_insect_pressure == 0


def test_backwards_time_rejects_without_consuming_pending_actions(field):
    _, world = field
    physics = world.physics
    physics.queue_management_action(0, ManagementAction(ManagementActionType.INSECTICIDE))
    with pytest.raises(ValueError, match="backwards"):
        advance_physics_time(world, START - 1)
    assert 0 in physics.pending_management_actions_by_ridge
    assert physics.last_physics_sim_time == START


def test_harvest_tool_settles_current_moisture_and_preserves_non_target(shared_field):
    env, world = shared_field
    physics = world.physics
    from fairy.physics import SoybeanStage
    for rid in (0, 1):
        ridge = world._ridges[rid]
        ridge.planted = True
        ridge.seed_type = "STANDARD"
        ridge.growth_stage = "R8_FULL_MATURITY"
        ridge.grain_moisture_pct = 15
        phen = physics.phenology.states[rid]
        phen.planted = True
        phen.stage = SoybeanStage.R8
        phen.maturity_date = DAY
        state = physics.yield_recovery.states[rid]
        state.r8_reached = True
        state.maturity_date = DAY
        state.biological_yield_g_m2 = 400
        state.grain_moisture_frac = 0.15
    non_target = deepcopy(physics.yield_recovery.states[1])
    tractor = SharedTractorApp(env)
    result = tractor.harvest("farm_a", 0, 0)
    assert result["status"] == "ok"
    assert physics.yield_recovery.states[0].grain_moisture_frac == 0.15
    assert tractor.get_state()["grain_moistures_pct"] == [15]
    assert physics.yield_recovery.states[1] == non_target
    assert physics.yield_recovery.states[0].harvested
    assert not physics.pending_harvest_actions_by_ridge
