"""Shared mobile devices must preserve one device state and target one farm."""
from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fairy.apps.farm_world.drone_app import DroneApp
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.robot_app import RobotApp
from fairy.apps.farm_world.shared_drone_app import SharedDroneApp
from fairy.apps.farm_world.shared_robot_app import SharedRobotApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.time_manager import TimeManager
from fairy.types import EventRegisterer


@pytest.fixture
def environment(monkeypatch):
    now = datetime(2026, 5, 12, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: now)
    clock = TimeManager()
    clock.reset(now)
    weather = WeatherApp()
    weather.set_weather("2026-05-12", 20, 50, 2, 0, 200)
    farm_a, farm_b = FarmWorldApp(name="FarmA"), FarmWorldApp(name="FarmB")
    return FarmEnvironment(
        [FarmContext("farm_a", farm_a, weather), FarmContext("farm_b", farm_b, weather)],
        weather,
        time_manager=clock,
        warehouse=WarehouseApp(stock=WarehouseStock(
            seed_stock={"STANDARD": 2_000_000}, pesticide_liters=4000.0,
            fertilizer_kg=4000.0, fuel_liters=2000.0,
        )),
    )


def test_drone_uses_target_observations_and_one_battery(environment):
    a = environment.get_farm("farm_a").world
    b = environment.get_farm("farm_b").world
    a.get_ridge(0).planted = True
    a.get_ridge(0).growth_stage = "V4"
    drone = SharedDroneApp(environment, name="Mavic3M")
    before_b = b.get_ridge(0).ndvi

    first = drone.fly_survey("farm_a", 0, 0)
    assert first["farm_id"] == "farm_a"
    assert first["observations"][0]["ndvi"] > 0
    assert a.get_ridge(0).ndvi == first["observations"][0]["ndvi"]
    assert b.get_ridge(0).ndvi == before_b
    assert first["battery_remaining_pct"] == 99

    second = drone.fly_survey("farm_b", 0, 0)
    assert second["observations"][0]["ndvi"] == -1
    assert second["battery_remaining_pct"] == 98
    assert [item["farm_id"] for item in drone.get_state()["mission_log"]] == [
        "farm_a", "farm_b"
    ]
    assert a.time_manager is b.time_manager is drone.time_manager


def test_drone_missing_farm_or_invalid_range_spends_no_battery_or_time(environment):
    drone = SharedDroneApp(environment)
    initial = environment.time_manager.time()
    assert "farm_id" in drone.fly_survey("unknown", 0, 0)["error"]
    assert "error" in drone.fly_survey("farm_a", 0, 1000)
    assert drone.check_status()["battery_pct"] == 100
    assert environment.time_manager.time() == initial
    assert drone.get_state()["mission_log"] == []


def test_drone_partial_reports_actual_ridges_and_preserves_cross_farm_battery(environment):
    drone = SharedDroneApp(environment, effective_ridges_per_pass=2)
    drone.load_state({"battery_pct": 23})
    first = drone.fly_survey("farm_a", 0, 3)
    assert first["status"] == "partial"
    assert first["surveyed_ridges"] == [0, 1]
    assert first["battery_remaining_pct"] == 21
    second = drone.fly_survey("farm_b", 0, 1)
    assert second["status"] == "partial"
    assert second["surveyed_ridges"] == []
    assert second["battery_remaining_pct"] == 21
    assert "Ridges not surveyed" in second["warning"]


@pytest.mark.parametrize("device_type,minutes", [(SharedDroneApp, 30), (SharedRobotApp, 60)])
def test_shared_charging_uses_common_time_without_farm_parameter(environment, device_type, minutes):
    device = device_type(environment)
    device.load_state({"battery_pct": 40})
    start = environment.time_manager.time()
    assert device.charge()["status"] == "charging_started"
    assert environment.time_manager.time() == start
    environment.advance_time(minutes * 30)
    assert device.check_status()["battery_pct"] == 70
    environment.advance_time(minutes * 30)
    assert device.check_status()["battery_pct"] == 100
    assert device.check_status()["charging"] is False


def test_robot_targets_local_diagnostics_and_keeps_one_battery(environment):
    a = environment.get_farm("farm_a").world
    b = environment.get_farm("farm_b").world
    a.get_ridge(0).pest_pressure_base = 0.8
    b.get_ridge(0).pest_pressure_base = 0
    robot = SharedRobotApp(environment, name="Robot0")
    first = robot.inspect_ridge("farm_a", 0)
    second = robot.inspect_ridge("farm_b", 0)
    assert first["result"]["pest_detected"] is True
    assert second["result"]["pest_detected"] is False
    assert first["battery_remaining_pct"] == 80
    assert second["battery_remaining_pct"] == 60
    assert [item["farm_id"] for item in robot.get_state()["inspection_log"]] == [
        "farm_a", "farm_b"
    ]


@pytest.mark.parametrize("method", ["inspect_pests", "inspect_crop_health", "inspect_emergence"])
def test_robot_range_partial_and_legacy_unknown_weeds(environment, method):
    robot = SharedRobotApp(environment)
    response = getattr(robot, method)("farm_a", 0, 9)
    assert response["farm_id"] == "farm_a"
    assert response["status"] == "partial"
    assert response["covered_ridges"] == list(range(8))
    assert response["uncovered_ridges"] == [8, 9]
    assert response["battery_remaining_pct"] == 60
    assert response["observations"][0]["weed_pressure_band"] == "unknown"
    assert response["observations"][0]["weed_present"] is None


def test_robot_unknown_farm_and_bad_local_ridge_do_not_consume_battery(environment):
    robot = SharedRobotApp(environment)
    start = environment.time_manager.time()
    assert "farm_id" in robot.inspect_pests("other", 0, 2)["error"]
    assert "error" in robot.inspect_ridge("farm_a", 1000)
    assert "error" in robot.inspect_pests("farm_b", 3, 1)
    assert robot.check_status()["battery_pct"] == 100
    assert environment.time_manager.time() == start
    assert robot.get_state()["inspection_log"] == []


@pytest.mark.parametrize("device_type,method,args", [
    (SharedDroneApp, "fly_survey", ("farm_b", 0, 1)),
    (SharedRobotApp, "inspect_pests", ("farm_b", 0, 1)),
])
def test_mobile_capture_preserves_explicit_target_without_early_effects(
    environment, device_type, method, args
):
    device = device_type(environment)
    with EventRegisterer.capture_mode() as events:
        getattr(device, method)(*args)
    assert len(events) == 1
    assert events[0].args == args
    assert device.check_status()["battery_pct"] == 100
    assert events[0].execute()["farm_id"] == "farm_b"
    assert device.check_status()["battery_pct"] < 100


@pytest.mark.parametrize("device_type,methods", [
    (SharedDroneApp, ["fly_survey"]),
    (SharedRobotApp, ["inspect_ridge", "inspect_pests", "inspect_crop_health", "inspect_emergence"]),
])
def test_mobile_source_signature_matches_provider_schema(environment, device_type, methods):
    device = device_type(environment)
    schemas = {tool.name: tool.to_open_ai()["function"] for tool in device.get_tools()}
    source_path = Path(inspect.getfile(device_type))
    cls = next(
        node for node in ast.parse(source_path.read_text()).body
        if isinstance(node, ast.ClassDef)
    )
    definitions = {node.name: node for node in cls.body if isinstance(node, ast.FunctionDef)}
    for method in methods:
        parameters = schemas[method]["parameters"]
        source_args = [arg.arg for arg in definitions[method].args.args if arg.arg != "self"]
        assert list(parameters["properties"]) == source_args
        assert "farm_id" in source_args
        assert parameters["properties"]["farm_id"]["enum"] == ["farm_a", "farm_b"]
        assert set(parameters["required"]) == set(source_args)
        assert all(param["description"] for param in parameters["properties"].values())
        assert parameters["additionalProperties"] is False
    assert schemas["check_status"]["parameters"]["properties"] == {}
    assert schemas["charge"]["parameters"]["properties"] == {}


def test_single_farm_wrapper_uses_its_world_bound_environment_clock(environment):
    farm = environment.get_farm("farm_a")
    for context in environment.farms.values():
        context.world.configure_physics_profile("bound_wrapper_clock_test")
    environment.sync()
    # A legacy-shaped wrapper does not acquire an independent scene clock when
    # its target world already belongs to an explicitly configured environment.
    drone = DroneApp(farm.world, farm.weather)
    robot = RobotApp(farm.world, farm.weather)
    clock = TimeManager()
    drone.register_time_manager(clock)
    robot.register_time_manager(clock)
    assert list(inspect.signature(drone.fly_survey).parameters) == ["start_ridge", "end_ridge"]
    assert list(inspect.signature(robot.inspect_ridge).parameters) == ["ridge_id"]
    before = clock.offset
    environment_before = environment.time_manager.time()
    assert drone.fly_survey(0, 0)["status"] == "ok"
    assert robot.inspect_ridge(0)["status"] == "ok"
    assert clock.offset == before
    assert environment.time_manager.time() > environment_before
    assert all(context.world.physics.last_physics_sim_time == environment.time_manager.time()
               for context in environment.farms.values())


def test_true_legacy_single_farm_wrapper_keeps_its_registered_clock():
    world, weather = FarmWorldApp(), WeatherApp()
    weather.set_weather("2026-05-12", 20, 50, 2, 0, 200)
    drone, robot = DroneApp(world, weather), RobotApp(world, weather)
    clock = TimeManager()
    for app in (world, weather, drone, robot):
        app.register_time_manager(clock)
    before = clock.offset
    assert world.farm_environment is None
    assert list(inspect.signature(drone.fly_survey).parameters) == ["start_ridge", "end_ridge"]
    assert list(inspect.signature(robot.inspect_ridge).parameters) == ["ridge_id"]
    assert drone.fly_survey(0, 0)["status"] == "ok"
    assert robot.inspect_ridge(0)["status"] == "ok"
    assert clock.offset > before


def test_physics_mobile_observation_reads_selected_engine_and_ticks_both_farms(
    environment, monkeypatch
):
    a = environment.get_farm("farm_a").world
    b = environment.get_farm("farm_b").world
    a.get_ridge(0).pest_pressure_base = 0.9
    b.get_ridge(0).pest_pressure_base = 0.0
    for world in (a, b):
        world.configure_physics_profile("two_farm_mobile_test")
    environment.sync()
    expected_pressures = [
        a.physics.biotic.states[0].insect_pressure,
        b.physics.biotic.states[0].insect_pressure,
    ]
    assert expected_pressures[0] > expected_pressures[1]
    calls = []

    # Observe calls while retaining the actual noisy observation implementation.
    for farm_id, world in (("farm_a", a), ("farm_b", b)):
        model = world.physics.observation_model
        original = model.observe_ground_inspection

        def observe(
            *, day, truth_by_ridge, ridge_ids, asset_id,
            _farm_id=farm_id, _original=original
        ):
            calls.append((_farm_id, truth_by_ridge[0].insect_pressure, asset_id))
            return _original(
                day=day, truth_by_ridge=truth_by_ridge,
                ridge_ids=ridge_ids, asset_id=asset_id
            )

        monkeypatch.setattr(model, "observe_ground_inspection", observe)

    robot = SharedRobotApp(environment, name="Robot0")
    first = robot.inspect_pests("farm_a", 0, 0)
    second = robot.inspect_pests("farm_b", 0, 0)
    assert [item[0] for item in calls] == ["farm_a", "farm_b"]
    assert [item[1] for item in calls] == expected_pressures
    assert all(item[2] == "Robot0" for item in calls)
    assert first["farm_id"] == "farm_a"
    assert second["farm_id"] == "farm_b"
    assert second["battery_remaining_pct"] == 90
    assert a.physics.last_physics_sim_time == b.physics.last_physics_sim_time
    assert a.physics.last_physics_sim_time == environment.time_manager.time()

    drone = SharedDroneApp(environment, name="Mavic3M")
    assert drone.fly_survey("farm_a", 0, 0)["status"] == "ok"
    assert drone.fly_survey("farm_b", 0, 0)["status"] == "ok"
    assert drone.check_status()["battery_pct"] == 98
    assert a.physics.last_physics_sim_time == b.physics.last_physics_sim_time
