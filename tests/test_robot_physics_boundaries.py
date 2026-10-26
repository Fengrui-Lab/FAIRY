"""Battery admission and declared coverage agree with the observation device."""
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.robot_app import RobotApp
from fairy.apps.farm_world.shared_robot_app import SharedRobotApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.time_manager import SimulationTimeManager


@pytest.mark.parametrize("shared", [False, True])
def test_robot_refuses_single_ridge_below_actual_twenty_percent(shared):
    world, weather, clock = FarmWorldApp(), WeatherApp(), SimulationTimeManager()
    clock.reset(datetime(2026, 5, 12, tzinfo=timezone.utc).timestamp())
    if shared:
        env = FarmEnvironment([FarmContext("a", world, weather)], weather, clock,
                              warehouse=WarehouseApp(stock=WarehouseStock(seed_stock={}, pesticide_liters=0, fertilizer_kg=0, fuel_liters=0)))
        robot = SharedRobotApp(env)
        inspect = lambda: robot.inspect_ridge("a", 0)
    else:
        robot = RobotApp(world, weather)
        for app in (world, weather, robot):
            app.register_time_manager(clock)
        inspect = lambda: robot.inspect_ridge(0)
    robot._battery_pct = 15
    before = clock.time()
    assert "error" in inspect()
    assert robot._battery_pct == 15
    assert clock.time() == before


@pytest.mark.parametrize("shared", [False, True])
def test_robot_covers_visited_ridges_through_sensor_sized_batches(shared):
    world, weather, clock = FarmWorldApp(), WeatherApp(), SimulationTimeManager()
    clock.reset(datetime(2026, 5, 12, tzinfo=timezone.utc).timestamp())
    weather.set_weather("2026-05-12", 22, 55, 2, 0, 240)
    world.physics.engines_active = True
    observe = Mock(wraps=world.physics.observation_model.observe_ground_inspection)
    world.physics.observation_model.observe_ground_inspection = observe
    if shared:
        env = FarmEnvironment([FarmContext("a", world, weather)], weather, clock,
                              warehouse=WarehouseApp(stock=WarehouseStock(seed_stock={}, pesticide_liters=0, fertilizer_kg=0, fuel_liters=0)))
        robot = SharedRobotApp(env)
        result = robot.inspect_crop_health("a", 0, 7)
    else:
        robot = RobotApp(world, weather)
        for app in (world, weather, robot):
            app.register_time_manager(clock)
        result = robot.inspect_crop_health(0, 7)
    assert result["status"] == "ok"
    assert result["covered_ridges"] == list(range(8))
    assert result["uncovered_ridges"] == []
    assert set(result["observations"]) == set(range(8))
    assert [call.kwargs["ridge_ids"] for call in observe.call_args_list] == [list(range(4)), list(range(4, 8))]
    assert robot._battery_pct == 60
