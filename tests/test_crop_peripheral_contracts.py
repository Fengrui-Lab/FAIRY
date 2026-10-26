"""Field geometry, visible crop state, and sensor capabilities govern devices."""
from copy import deepcopy
from datetime import datetime
import json
from zoneinfo import ZoneInfo

import pytest

from fairy.apps.farm_world.drone_app import DroneApp
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.field_ops_app import FieldOpsApp
from fairy.apps.farm_world.robot_app import RobotApp
from fairy.apps.farm_world.sensor_app import SensorApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.apps.farm_world.weather_app import WeatherApp


def call(app, name, **arguments):
    return next(tool for tool in app.get_tools() if tool.name == name)(**arguments)


def field(crop_id):
    world, weather = FarmWorldApp(crop_id=crop_id, field_length_m=200.0), WeatherApp()
    for ridge in world._ridges:
        ridge.soil_vwc, ridge.soil_temp_c = 0.24, 18.0
    weather.set_weather(date="2026-05-15", temp_c=20.0, humidity_pct=50.0,
                        wind_speed_ms=1.0, rainfall_mm=0.0,
                        solar_radiation=350.0, avg_soil_vwc=0.24)
    world.configure_physics_profile("peripheral_static_weather")
    start = datetime(2026, 5, 15, 12, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
    environment = FarmEnvironment([FarmContext("field", world, weather)], weather,
                                  start_time=start, timezone_name="Asia/Shanghai")
    environment.sync()
    return environment, world, weather


@pytest.mark.parametrize("crop_id", ["soybean", "maize"])
def test_ground_range_never_claims_unobserved_ridges(crop_id):
    environment, world, weather = field(crop_id)
    robot = RobotApp(world, weather)
    robot.register_time_manager(environment.time_manager)
    original = world.physics.observation_model.observe_ground_inspection
    actual_products, actual_batches = [], []

    def observe(**arguments):
        actual_batches.append(arguments["ridge_ids"])
        assert len(arguments["ridge_ids"]) <= world.physics.observation_model.params.ground_inspection_max_ridges
        products = original(**arguments)
        actual_products.extend(products[0].values)
        return products

    world.physics.observation_model.observe_ground_inspection = observe
    start = environment.time_manager.time()
    result = call(robot, "inspect_emergence", start_ridge=0, end_ridge=9)
    assert result["status"] == "partial"
    assert actual_batches == [[0, 1, 2, 3], [4, 5, 6, 7]]
    assert result["covered_ridges"] == actual_products == list(range(8))
    assert result["uncovered_ridges"] == [8, 9]
    assert list(result["observations"]) == actual_products
    assert result["battery_remaining_pct"] == 60.0
    assert environment.time_manager.time() - start == 8 * (int(200.0 * 2 / 0.8) + 30)


@pytest.mark.parametrize("crop_id", ["soybean", "maize"])
def test_emergence_reports_zero_for_harvested_historical_stand(crop_id):
    environment, world, weather = field(crop_id)
    physics = world.physics
    # Keep historical establishment while marking the crop as harvested. The
    # public observation must use current crop projection, not the old seed log.
    for rid in range(4):
        physics.phenology.states[rid].planted = True
        physics.phenology.states[rid].emerged = True
        physics.management.states[rid].planted = True
        physics.management.states[rid].stand_fraction = 0.95
        physics.yield_recovery.states[rid].harvested = True
    robot = RobotApp(world, weather)
    robot.register_time_manager(environment.time_manager)
    result = call(robot, "inspect_emergence", start_ridge=0, end_ridge=3)
    assert result["status"] == "ok"
    assert {item["stand_fraction"] for item in result["observations"].values()} == {0.0}


@pytest.mark.parametrize("crop_id", ["soybean", "maize"])
def test_drone_flight_time_uses_field_geometry_for_every_crop(crop_id):
    environment, world, weather = field(crop_id)
    drone = DroneApp(world, weather, speed_ms=5.0, effective_ridges_per_pass=2)
    drone.register_time_manager(environment.time_manager)
    start = environment.time_manager.time()
    result = call(drone, "fly_survey", start_ridge=0, end_ridge=4)
    assert result["surveyed_ridges"] == [0, 1, 2, 3, 4]
    assert environment.time_manager.time() - start == 30 + 3 * int(200.0 / 5.0)


@pytest.mark.parametrize("crop_id", ["soybean", "maize"])
def test_sensor_json_round_trip_continues_same_random_samples(crop_id):
    sensor = SensorApp(FarmWorldApp(crop_id=crop_id))
    sensor.set_seed(123)
    call(sensor, "read_soil_sensors")
    saved = json.loads(json.dumps(sensor.get_state()))
    expected = [call(sensor, "read_soil_sensors"), call(sensor, "read_canopy_sensors")]
    restored = SensorApp(FarmWorldApp(crop_id=crop_id))
    restored.load_state(saved)
    actual = [call(restored, "read_soil_sensors"), call(restored, "read_canopy_sensors")]
    assert actual == expected


def test_legacy_sensor_snapshot_without_crop_or_rng_still_loads_soybean():
    sensor = SensorApp(FarmWorldApp())
    saved = deepcopy(sensor.get_state())
    saved.pop("crop_id")
    saved.pop("random_state")
    saved["soil_sensors"][0]["vwc"] = 0.123
    sensor.set_seed(321)
    random_before = sensor.rng.getstate()
    sensor.load_state(saved)
    assert sensor._soil_sensors[0]["vwc"] == 0.123
    assert sensor.rng.getstate() == random_before


def test_mixed_fields_share_explicit_environment_clock_and_warehouse():
    weather = WeatherApp()
    soybean, maize = FarmWorldApp(), FarmWorldApp(crop_id="maize")
    warehouse = WarehouseApp(WarehouseStock(
        seed_stock={"STANDARD": 100000, "MAIZE_EARLY_2026": 100000},
        pesticide_liters=10.0, fertilizer_kg=100.0, fuel_liters=100.0,
    ))
    environment = FarmEnvironment([
        FarmContext("soy", soybean, weather), FarmContext("corn", maize, weather),
    ], weather, warehouse=warehouse, start_time=0.0)
    # The single-farm wrapper creates a fresh context; the world's explicit
    # binding must still charge the one common environment for either crop.
    for world in (soybean, maize):
        context = FarmContext("wrapper", world, weather)
        before = environment.time_manager.time()
        context.advance_time(5)
        assert environment.time_manager.time() == before + 5
    assert warehouse.environment is environment
    assert all(world.farm_environment is environment for world in (soybean, maize))


def test_legacy_field_ops_rejects_nonfinite_irrigation_before_time_or_stock():
    environment, world, weather = field("soybean")
    ops = FieldOpsApp(world, weather)
    ops.register_time_manager(environment.time_manager)
    assert ops.require_explicit_tool_docs is False
    before_time = environment.time_manager.time()
    before_stock = deepcopy(world._inventory)
    result = call(ops, "irrigate", start_ridge=0, end_ridge=0, hours=float("nan"))
    assert "error" in result
    assert environment.time_manager.time() == before_time
    assert world._inventory == before_stock


@pytest.mark.parametrize("crop_id", ["soybean", "maize"])
def test_harvested_canopy_history_is_not_reported_as_living_crop(crop_id):
    environment, world, weather = field(crop_id)
    physics = world.physics
    # Preserve old high NDVI in the physical history deliberately: observers
    # must consult the current crop projection rather than canopy.initialized.
    for rid in range(world.num_ridges):
        physics.phenology.states[rid].planted = True
        physics.phenology.states[rid].emerged = True
        physics.management.states[rid].planted = True
        physics.management.states[rid].stand_fraction = 1.0
        physics.yield_recovery.states[rid].harvested = True
        canopy = physics.canopy.states[rid]
        canopy.initialized, canopy.ndvi_proxy = True, 0.8
        canopy.lai, canopy.canopy_cover = 4.0, 0.9
    sensor = SensorApp(world)
    sensor.register_time_manager(environment.time_manager)
    readings = call(sensor, "read_canopy_sensors")["canopy_sensors"]
    assert {reading["ndvi_proxy"] for reading in readings} == {-1.0}
    drone = DroneApp(world, weather)
    drone.register_time_manager(environment.time_manager)
    output = call(drone, "fly_survey", start_ridge=0, end_ridge=3)
    assert output["status"] == "ok"
    assert {item["ndvi"] for item in output["observations"]} == {-1.0}


@pytest.mark.parametrize("crop_id", ["soybean", "maize"])
def test_single_ridge_diagnostics_follow_explicit_capability(crop_id, monkeypatch):
    from types import SimpleNamespace
    from fairy.crops.runtime import CropObservationTraits

    environment, world, weather = field(crop_id)
    world.physics.biotic.states[0].insect_pressure = 0.8
    world.physics.biotic.states[0].disease_pressure = 0.8
    robot = RobotApp(world, weather)
    robot.register_time_manager(environment.time_manager)
    world.physics.crop.observation_traits = CropObservationTraits(
        unstressed_root_vwc=0.2, diagnosed_pest_type="configured_pest",
        diagnosed_disease_type="configured_disease",
    )
    diagnosed = call(robot, "inspect_ridge", ridge_id=0)["result"]
    assert diagnosed["pest_type"] == "configured_pest"
    assert diagnosed["disease_type"] == "configured_disease"

    # Removing identity capability on the same crop switches to actual generic
    # observation products, including a forced false negative.
    world.physics.crop.observation_traits = CropObservationTraits(unstressed_root_vwc=0.2)
    products = [SimpleNamespace(values={0: {"pest_present": False, "confidence": 0.123}}),
                SimpleNamespace(values={0: {"disease_present": False, "confidence": 0.234}})]
    monkeypatch.setattr(world.physics.observation_model, "observe_ground_inspection",
                        lambda **kwargs: products)
    generic = call(robot, "inspect_ridge", ridge_id=0)["result"]
    assert generic["pest_detected"] is generic["disease_detected"] is False
    assert generic["pest_type"] is generic["disease_type"] is None
    assert generic["pest_confidence"] == 0.123
