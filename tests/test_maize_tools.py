"""Single-farm maize tools enforce crop rules before spending time/resources."""
from copy import deepcopy
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.equipment import TractorEquipment, DEFAULT_TRACTOR_IMPLEMENTS
from fairy.apps.farm_world.models import InventoryState
from fairy.apps.farm_world.irrigation_app import IrrigationApp
from fairy.apps.farm_world.tractor_app import TractorApp
from fairy.apps.farm_world.weather_app import WeatherApp


def call(app, name, **arguments):
    return next(tool for tool in app.get_tools() if tool.name == name)(**arguments)


@pytest.fixture
def maize():
    world = FarmWorldApp(crop_id="maize", field_length_m=200.0)
    world._inventory = InventoryState(
        seed_stock={"MAIZE_EARLY_2026": 150000}, pesticide_liters=0.0,
        fertilizer_kg=1000.0, fuel_liters=300.0, harvest_grain_kg=0.0,
    )
    weather = WeatherApp()
    weather.set_weather(date="2026-05-15", temp_c=20.0, humidity_pct=50.0,
                        wind_speed_ms=1.0, rainfall_mm=0.0,
                        solar_radiation=350.0, avg_soil_vwc=0.24)
    for ridge in world._ridges:
        ridge.soil_vwc = 0.24
        ridge.soil_temp_c = 18.0
    world.configure_physics_profile("maize_tool_static_weather")
    start = datetime(2026, 5, 15, 7, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
    environment = FarmEnvironment([FarmContext("maize", world, weather)], weather,
                                  start_time=start, timezone_name="Asia/Shanghai")
    tractor = TractorApp(world, weather, equipment=TractorEquipment(
        implements=(*DEFAULT_TRACTOR_IMPLEMENTS, "maize_planter", "maize_header"),
        ridging_implement="furrower",
    ))
    tractor.register_time_manager(environment.time_manager)
    environment.sync()
    assert call(tractor, "attach_implement", implement="grader")["status"] == "ok"
    assert call(tractor, "level")["status"] == "ok"
    assert call(tractor, "detach_implement")["status"] == "ok"
    assert call(tractor, "load_fertilizer", kg=200.0)["status"] == "ok"
    assert call(tractor, "base_fertilize")["status"] == "ok"
    assert call(tractor, "attach_implement", implement="furrower")["status"] == "ok"
    assert call(tractor, "form_ridges", ridge_width_m=0.65)["status"] == "ok"
    assert call(tractor, "detach_implement")["status"] == "ok"
    assert call(tractor, "load_seeds", seed_type="MAIZE_EARLY_2026", count=10000)["status"] == "ok"
    return environment, world, tractor


def test_maize_seed_and_implement_catalog_matches_real_tools(maize):
    _, world, tractor = maize
    tools = {tool.name: tool for tool in tractor.get_tools()}
    seed = next(arg for arg in tools["load_seeds"].args if arg.name == "seed_type")
    assert seed.choices == world.crop_capabilities()["allowed_seed_types"]
    assert "STANDARD" not in tools["load_seeds"].function_description
    assert "3–6 cm" in tools["plant_seeds"].function_description
    assert "R6_MATURITY" in tools["harvest"].function_description
    assert "30%" in tools["harvest"].function_description
    assert "maize_header" in tools["harvest"].function_description
    before = tractor.get_state()
    assert "error" in tractor.load_seeds("STANDARD", 100)
    assert tractor.get_state() == before
    assert "error" in call(tractor, "load_seeds", seed_type="STANDARD", count=100)
    soy = TractorApp(FarmWorldApp(), WeatherApp())
    assert "maize_planter" not in soy.get_status()["available_implements"]
    assert "error" in soy.load_seeds("MAIZE_EARLY_2026", 100)


def test_maize_planting_uses_one_row_actual_length_and_one_clock(maize):
    environment, world, tractor = maize
    before = tractor.get_state()
    now = environment.time_manager.time()
    missing = call(tractor, "plant_seeds", start_ridge=0, end_ridge=3,
                   depth_cm=6.0, seed_spacing_cm=20.0)
    assert "maize_planter" in missing["error"]
    assert tractor.get_state() == before
    assert environment.time_manager.time() == now
    assert call(tractor, "attach_implement", implement="maize_planter")["status"] == "ok"
    result = call(tractor, "plant_seeds", start_ridge=0, end_ridge=3,
                  depth_cm=6.0, seed_spacing_cm=20.0)
    assert result["status"] == "ok"
    assert result["seeds_per_ridge"] == 1000  # 200m × one row / 0.20m
    assert result["seeds_used"] == 4000
    assert tractor.get_status()["seed_hopper"] == 6000
    assert environment.time_manager.time() - now == int(200 / (5000 / 3600)) + 30
    assert all(world.physics.phenology.states[rid].seed_type == "MAIZE_EARLY_2026"
               for rid in range(4))
    assert all(not world.physics.phenology.states[rid].planted for rid in range(4, 64))
    assert all(world.get_ridge(rid).seeds_planted == 1000 for rid in range(4))
    assert all(world.physics.management.states[rid].planted for rid in range(4))
    assert all(world.physics.management.states[rid].stand_fraction > 0.5 for rid in range(4))
    assert all(world.physics.canopy.states[rid].stand_fraction == 1.0 for rid in range(4))


@pytest.mark.parametrize("arguments", [
    {"depth_cm": 2.9, "seed_spacing_cm": 20.0},
    {"depth_cm": 6.1, "seed_spacing_cm": 20.0},
    {"depth_cm": float("nan"), "seed_spacing_cm": 20.0},
    {"depth_cm": 5.0, "seed_spacing_cm": 0.0},
    {"depth_cm": 5.0, "seed_spacing_cm": 0.1},
    {"depth_cm": 5.0, "seed_spacing_cm": 1e12},
])
def test_invalid_maize_planting_is_rejected_before_effects(maize, arguments):
    environment, world, tractor = maize
    call(tractor, "attach_implement", implement="maize_planter")
    before, now = tractor.get_state(), environment.time_manager.time()
    assert "error" in call(tractor, "plant_seeds", start_ridge=0, end_ridge=0, **arguments)
    assert tractor.get_state() == before
    assert environment.time_manager.time() == now
    assert not world.physics.phenology.states[0].planted


def test_maize_replant_rejects_established_gapfill_before_spending_and_full_reset_works(maize):
    environment, world, tractor = maize
    call(tractor, "attach_implement", implement="maize_planter")
    assert call(tractor, "plant_seeds", start_ridge=0, end_ridge=0,
                depth_cm=4.5, seed_spacing_cm=20.0)["status"] == "ok"
    # Reach real emergence through the daily physics path.
    environment.advance_time(10 * 86400)
    assert world.physics.phenology.states[0].emerged
    irrigation = IrrigationApp(world, environment.weather)
    irrigation.register_time_manager(environment.time_manager)
    assert call(irrigation, "irrigate", start=0, end=0, hours=2.0)["status"] == "irrigation_started"
    planting_date = world.physics.phenology.states[0].planting_date
    before, now = tractor.get_state(), environment.time_manager.time()
    result = call(tractor, "replant_seeds", start_ridge=0, end_ridge=0,
                  depth_cm=5.0, spacing_cm=20.0)
    assert "gap-filling" in result["error"]
    assert tractor.get_state() == before
    assert environment.time_manager.time() == now
    assert world.physics.phenology.states[0].planting_date == planting_date
    result = call(tractor, "replant_seeds", start_ridge=0, end_ridge=0,
                  depth_cm=5.0, spacing_cm=20.0, full_replant=True)
    assert result["status"] == "ok"
    assert result["phenology_reset_ridges"] == [0]
    assert world.physics.phenology.states[0].planting_date > planting_date
    assert not world.physics.phenology.states[0].emerged


def test_maize_harvest_accepts_native_maturity_and_30pct_gate_with_actual_area(maize):
    environment, world, tractor = maize
    call(tractor, "attach_implement", implement="maize_planter")
    assert call(tractor, "plant_seeds", start_ridge=0, end_ridge=3,
                depth_cm=4.5, seed_spacing_cm=20.0)["status"] == "ok"
    # Constant warm, rainy forcing is a controlled model test, not a climate claim.
    environment.weather.set_weather(
        date=world.simulation_date().isoformat(), temp_c=25.0, humidity_pct=50.0,
        wind_speed_ms=1.0, rainfall_mm=3.0, solar_radiation=350.0, avg_soil_vwc=0.24,
    )
    environment.advance_time(120 * 86400)
    assert world.get_ridge_state(0)["growth_stage"] == "R6_MATURITY"
    moisture = world.get_ridge_state(0)["grain_moisture_pct"]
    assert 18.0 < moisture <= 30.0
    environment.weather.set_weather(
        date=world.simulation_date().isoformat(), temp_c=25.0, humidity_pct=50.0,
        wind_speed_ms=1.0, rainfall_mm=0.0, solar_radiation=350.0, avg_soil_vwc=0.24,
    )
    assert "maize_header" in call(tractor, "harvest", start_ridge=0, end_ridge=3)["error"]
    call(tractor, "detach_implement")
    call(tractor, "attach_implement", implement="maize_header")
    # A synthetic nearly-full bin must reject against the model's conservative
    # bound before consuming fuel or time; clear it to exercise real settlement.
    tractor._grain_bin_kg = 1900.0
    before, now = tractor.get_state(), environment.time_manager.time()
    assert "overflow" in call(tractor, "harvest", start_ridge=0, end_ridge=3)["error"]
    assert tractor.get_state() == before
    assert environment.time_manager.time() == now
    tractor._grain_bin_kg = 0.0
    result = call(tractor, "harvest", start_ridge=0, end_ridge=3)
    assert result["status"] == "ok"
    expected = sum(world.physics.yield_recovery.states[rid].recovered_yield_g_m2_at_market_moisture
                   * 200.0 * 0.65 / 1000.0 for rid in range(4))
    assert result["grain_kg_added"] == pytest.approx(round(expected, 2))
    assert environment.time_manager.time() - now == int(200 / (4000 / 3600)) + 30
    assert all(world.get_ridge_state(rid)["harvested"] for rid in range(4))
    assert not world.physics.yield_recovery.states[4].harvested


def test_tractor_snapshots_cannot_move_between_crop_types(maize):
    _, _, tractor = maize
    soybean = TractorApp(FarmWorldApp(), WeatherApp())
    maize_state, soy_state = deepcopy(tractor.get_state()), deepcopy(soybean.get_state())
    with pytest.raises(ValueError, match="snapshot crop"):
        tractor.load_state(soy_state)
    with pytest.raises(ValueError, match="snapshot crop"):
        soybean.load_state(maize_state)
    assert tractor.get_state() == maize_state

    assert soybean.get_state() == soy_state
    corrupted = deepcopy(maize_state)
    corrupted["seed_type"] = "STANDARD"
    with pytest.raises(ValueError, match="incompatible"):
        tractor.load_state(corrupted)
    assert tractor.get_state() == maize_state


def test_maize_harvest_crossing_rainy_midnight_returns_failure_without_queuing_harvest(maize):
    environment, world, tractor = maize
    call(tractor, "attach_implement", implement="maize_planter")
    assert call(tractor, "plant_seeds", start_ridge=0, end_ridge=0,
                depth_cm=4.5, seed_spacing_cm=20.0)["status"] == "ok"
    environment.weather.set_weather(
        date=world.simulation_date().isoformat(), temp_c=25.0, humidity_pct=50.0,
        wind_speed_ms=1.0, rainfall_mm=3.0, solar_radiation=350.0, avg_soil_vwc=0.24,
    )
    environment.advance_time(120 * 86400)
    day = world.simulation_date()
    late = datetime.combine(day, time(23, 59, 30), environment.simulation_timezone).timestamp()
    environment.advance_time(late - environment.time_manager.time())
    # Install a real next-day forecast: start is dry and harvestable, while the
    # daily storm rewets maize during the operation across Beijing midnight.
    environment.weather.set_weather(
        date=day.isoformat(), temp_c=25.0, humidity_pct=50.0, wind_speed_ms=1.0,
        rainfall_mm=0.0, solar_radiation=350.0, avg_soil_vwc=0.24,
        forecast=[{"date": (day + timedelta(days=1)).isoformat(), "temp_c": 10.0,
                   "rainfall_mm": 100.0, "wind_speed_ms": 1.0, "solar_radiation": 50.0}],
    )
    assert world.get_ridge_state(0)["grain_moisture_pct"] <= 30.0
    call(tractor, "detach_implement")
    call(tractor, "attach_implement", implement="maize_header")
    before = tractor.get_status()
    start = environment.time_manager.time()
    result = call(tractor, "harvest", start_ridge=0, end_ridge=0)
    assert result["status"] == "failed"
    assert "during the pass" in result["error"]
    assert result["grain_kg_added"] == 0.0 and result["harvested_ridges"] == []
    assert result["grain_moisture_pct_by_ridge"][0] > 30.0
    assert tractor.get_status()["fuel_tank_l"] == before["fuel_tank_l"] - 2.0
    assert environment.time_manager.time() - start == result["duration_s"]
    assert world.get_ridge_state(0)["planted"]
    assert not world.physics.yield_recovery.states[0].harvested
    assert not world.physics.pending_harvest_actions_by_ridge
    assert not world._pending_bin_grain_ridge_ids
    assert tractor.get_status()["grain_bin_kg"] == before["grain_bin_kg"]
