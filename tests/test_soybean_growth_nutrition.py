"""Non-WOFOST crops retain zero-growth nutrient accounting across integration.

Growth, fertilization, background depletion and checkpoint continuity remain
real; compatibility growth never introduces an additional nutrient debit.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime
import json
from zoneinfo import ZoneInfo

import pytest

from fairy.apps.farm_world.crop_snapshot import snapshot_physics
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.crops.runtime import PlantingEvent
from fairy.physics import HarvestAction
from fairy.physics.phenology_engine import SoybeanStage


START_DAY = date(2026, 6, 1)
START = datetime(2026, 6, 1, 7, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
GROWTH_FIELDS = (
    "last_growth_uptake_day",
    "daily_growth_biomass_g_m2",
    "daily_growth_uptake_index",
    "cumulative_growth_uptake_index",
)


def farm_pair(stage="V3", other_stage="bare"):
    """Small living patches in two normal 64-ridge fields, with static weather."""
    weather = WeatherApp()
    weather.set_weather(
        date=START_DAY.isoformat(),
        temp_c=24.0,
        humidity_pct=55.0,
        wind_speed_ms=1.0,
        rainfall_mm=0.0,
        solar_radiation=300.0,
    )
    worlds = []
    for farm_id, crop_stage in (("farm_a", stage), ("farm_b", other_stage)):
        world = FarmWorldApp(farm_id=farm_id, name=farm_id)
        for ridge in world._ridges:
            ridge.planted = crop_stage != "bare" and ridge.ridge_id < 2
            ridge.harvested = False
            ridge.growth_stage = crop_stage if ridge.planted else "bare"
            ridge.days_since_planted = 30 if ridge.planted else 0
            ridge.seed_type = "HEINONG84"
            ridge.seeds_planted = 6700 if ridge.planted else 0
            ridge.seed_spacing_cm = 8.0 if ridge.planted else 0.0
            ridge.stand_fraction = 1.0
            ridge.nutrient_index = 0.8
            ridge.soil_vwc, ridge.soil_temp_c = 0.27, 20.0
            ridge.pest_pressure_base = ridge.disease_pressure_base = 0.0
        world.configure_physics_profile("growth_uptake_static_weather")
        worlds.append(world)
    warehouse = WarehouseApp(
        stock=WarehouseStock(
            seed_stock={"HEINONG84": 100000},
            fertilizer_kg=500.0,
            pesticide_liters=20.0,
            fuel_liters=100.0,
        )
    )
    env = FarmEnvironment(
        [FarmContext(world.farm_id, world, weather) for world in worlds],
        weather,
        warehouse=warehouse,
        start_time=START,
        timezone_name="Asia/Shanghai",
    )
    env.sync()
    return env, *worlds


def planting(world, ridges=(0,)):
    return PlantingEvent(
        ridge_ids=ridges,
        planting_date=world.simulation_date(),
        seed_type="HEINONG84",
        depth_cm=4.0,
        stand_fraction_by_ridge={rid: 1.0 for rid in ridges},
        density_by_ridge={rid: 23.0 for rid in ridges},
    )


def call(app, method, **arguments):
    return next(tool for tool in app.get_tools() if tool.name == method)(**arguments)


def restore_pair(env, a, b, *, drop_growth_fields=False):
    snapshots = json.loads(json.dumps([world.get_state() for world in (a, b)], allow_nan=False))
    if drop_growth_fields:
        for snapshot in snapshots:
            for state in snapshot["physics_state"]["management"]["states"].values():
                for field in GROWTH_FIELDS:
                    state.pop(field)
    restored_env, restored_a, restored_b = farm_pair()
    restored_env.time_manager.set_offset(env.time_manager.time() - START)
    for world, snapshot in zip((restored_a, restored_b), snapshots):
        world.load_state(snapshot)
    return restored_env, restored_a, restored_b


def test_legacy_vegetative_growth_does_not_consume_nutrient_proxy():
    env, world, other = farm_pair()
    before_biomass = world.physics.canopy.states[0].aboveground_biomass_g_m2
    before_index = world.physics.management.states[0].nutrient_index
    env.advance_time(86400)
    state = world.physics.management.states[0]
    grown = world.physics.canopy.states[0].aboveground_biomass_g_m2 - before_biomass
    parameters = world.physics.management.params
    assert grown > 0
    assert world.physics.phenology.states[0].stage in {
        SoybeanStage.V3,
        SoybeanStage.V4_PLUS,
    }
    assert state.last_growth_uptake_day == world.simulation_date() == date(2026, 6, 2)
    assert state.daily_growth_biomass_g_m2 == 0
    assert state.daily_growth_uptake_index == 0
    assert state.cumulative_growth_uptake_index == pytest.approx(state.daily_growth_uptake_index)
    assert state.nutrient_index == pytest.approx(
        before_index - parameters.daily_nutrient_decay - state.daily_growth_uptake_index
    )
    assert state.nutrient_stress == pytest.approx(
        world.physics.management._nutrient_stress_from_index(state.nutrient_index)
    )
    assert call(world, "get_ridge_state", ridge_id=0)["nutrient_index"] == round(state.nutrient_index, 3)
    # Same wall clock and weather cannot transfer one field's crop uptake to another.
    assert other.simulation_date() == world.simulation_date()
    assert other.physics.management.states[0].daily_growth_uptake_index == 0
    assert other.physics.management.states[0].cumulative_growth_uptake_index == 0


@pytest.mark.parametrize("configuration", [
    {"crop_type": "soybean"}, {"crop_type": "maize"}, {"crop_type": "rice"},
    {"crop_id": "maize"},
])
def test_non_wofost_crop_adapters_always_supply_zero_growth(configuration):
    world = FarmWorldApp(**configuration)
    world.configure_physics_profile("legacy_growth_contract")
    assert world.physics.crop_backend is None
    for canopy in world.physics.canopy.states.values():
        canopy.daily_biomass_g_m2 = 25.0
    assert all(value.daily_biomass_g_m2 == 0.0
               for value in world.physics.crop.management_inputs(world.physics).values())


def test_multi_day_jump_and_daily_steps_preserve_background_only_nutrient_use():
    jumped_env, jumped, _ = farm_pair()
    stepped_env, stepped, _ = farm_pair()
    initial_biomass = jumped.physics.canopy.states[0].aboveground_biomass_g_m2
    jumped_env.advance_time(3 * 86400)
    for _ in range(3):
        stepped_env.advance_time(86400)
    assert snapshot_physics(jumped.physics) == snapshot_physics(stepped.physics)
    total_growth = jumped.physics.canopy.states[0].aboveground_biomass_g_m2 - initial_biomass
    management = jumped.physics.management.states[0]
    assert total_growth > 0
    assert management.cumulative_growth_uptake_index == 0
    assert management.last_growth_uptake_day == date(2026, 6, 4)


def test_same_day_reads_and_fertilizer_commit_do_not_charge_growth_again():
    env, world, other = farm_pair()
    env.advance_time(86400)
    before = deepcopy(world.physics.management.states[0])
    other_before = deepcopy(other.physics.management.states)
    clock = env.time_manager.time()
    for _ in range(2):
        call(world, "get_ridge_state", ridge_id=0)
        call(world, "get_ridge_range_state", start=0, end=3)
        env.sync()
    result = call(world, "apply_fertigation", start_ridge=0, end_ridge=0, nutrient_amount=0.2, water_mm=0.0)
    assert result["status"] == "ok"
    after = world.physics.management.states[0]
    assert env.time_manager.time() == clock
    for field in GROWTH_FIELDS:
        assert getattr(after, field) == getattr(before, field)
    assert after.nutrient_index == pytest.approx(
        before.nutrient_index + 0.2 * world.physics.management.params.fertigation_gain
    )
    assert other.physics.management.states == other_before


@pytest.mark.parametrize("phase", ["bare", "preemergence", "R8", "harvested"])
def test_non_growing_states_have_no_growth_uptake(phase):
    env, world, _ = farm_pair(stage="R8" if phase in {"R8", "harvested"} else "bare")
    if phase == "preemergence":
        world.physics.crop.plant(planting(world))
    elif phase == "harvested":
        grain = world.physics.yield_recovery.states[0]
        grain.r8_reached, grain.grain_moisture_frac = True, 0.13
        grain.biological_yield_g_m2 = 300.0
        before = deepcopy(world.physics.management.states[0])
        world.physics.queue_harvest(0, HarvestAction())
        env.sync()  # Harvest drydown does not introduce a crop-growth nutrient debit.
        assert world.physics.yield_recovery.states[0].harvested
        assert world.physics.management.states[0] == before
    before_index = world.physics.management.states[0].nutrient_index
    env.advance_time(86400)
    state = world.physics.management.states[0]
    assert state.daily_growth_biomass_g_m2 == 0
    assert state.daily_growth_uptake_index == 0
    assert state.cumulative_growth_uptake_index == 0
    assert state.nutrient_index == pytest.approx(before_index - world.physics.management.params.daily_nutrient_decay)


def test_emergence_seed_reserves_are_not_counted_as_new_daily_growth():
    env, world, _ = farm_pair(stage="bare")
    world.physics.crop.plant(planting(world))
    for _ in range(30):
        env.advance_time(86400)
        if world.physics.phenology.states[0].emerged:
            break
    else:
        pytest.fail("The warm, moist seedbed did not produce emergence")
    canopy = world.physics.canopy.states[0]
    management = world.physics.management.states[0]
    seed_reserve = world.physics.canopy.params.initial_biomass_g_m2_at_emergence
    assert canopy.aboveground_biomass_g_m2 >= seed_reserve
    assert management.daily_growth_biomass_g_m2 == 0
    assert management.cumulative_growth_uptake_index == 0


def test_json_snapshot_preserves_daily_cursor_and_continues_without_double_consumption():
    env, world, other = farm_pair()
    env.advance_time(86400)
    restored_env, restored, _ = restore_pair(env, world, other)
    before = deepcopy(restored.physics.management.states[0])
    assert isinstance(before.last_growth_uptake_day, date)
    assert snapshot_physics(restored.physics) == snapshot_physics(world.physics)
    restored_env.sync()
    call(restored, "get_ridge_state", ridge_id=0)
    assert restored.physics.management.states[0] == before
    env.advance_time(86400)
    restored_env.advance_time(86400)
    assert snapshot_physics(restored.physics) == snapshot_physics(world.physics)


def test_old_snapshot_without_growth_accounting_fields_does_not_recharge_history():
    env, world, other = farm_pair()
    env.advance_time(2 * 86400)
    restored_env, restored, _ = restore_pair(env, world, other, drop_growth_fields=True)
    state = restored.physics.management.states[0]
    old_index = state.nutrient_index
    old_biomass = restored.physics.canopy.states[0].aboveground_biomass_g_m2
    restored_env.sync()
    assert state.nutrient_index == old_index
    assert state.cumulative_growth_uptake_index == 0
    restored_env.advance_time(86400)
    grown = restored.physics.canopy.states[0].aboveground_biomass_g_m2 - old_biomass
    assert grown > 0
    assert state.cumulative_growth_uptake_index == 0
    assert state.nutrient_index == pytest.approx(
        old_index - restored.physics.management.params.daily_nutrient_decay - state.daily_growth_uptake_index
    )


def test_full_replant_does_not_consume_old_canopy_growth_again():
    env, world, _ = farm_pair()
    env.advance_time(86400)
    cumulative = world.physics.management.states[0].cumulative_growth_uptake_index
    neighbor_cumulative = world.physics.management.states[1].cumulative_growth_uptake_index
    event = replace(planting(world), replace_existing=True)
    plan = world.physics.crop.prepare_replant(event, world.physics.management.states, full_replant=True)
    world.physics.crop.apply_replant(plan, world.physics.management.states)
    assert world.physics.canopy.states[0].aboveground_biomass_g_m2 == 0
    env.sync()
    assert world.physics.management.states[0].cumulative_growth_uptake_index == cumulative
    env.advance_time(86400)
    state = world.physics.management.states[0]
    assert state.daily_growth_biomass_g_m2 == state.daily_growth_uptake_index == 0
    assert state.cumulative_growth_uptake_index == cumulative
    assert world.physics.management.states[1].cumulative_growth_uptake_index == neighbor_cumulative


def test_world_reset_discards_previous_growth_accounting():
    env, world, _ = farm_pair()
    env.advance_time(86400)
    assert world.physics.canopy.states[0].aboveground_biomass_g_m2 > 0
    assert world.physics.management.states[0].cumulative_growth_uptake_index == 0
    world.reset()
    world.configure_physics_profile("growth_uptake_static_weather")
    env.sync()
    state = world.physics.management.states[0]
    assert state.last_growth_uptake_day is None
    assert state.daily_growth_biomass_g_m2 == state.daily_growth_uptake_index == 0
    assert state.cumulative_growth_uptake_index == 0
