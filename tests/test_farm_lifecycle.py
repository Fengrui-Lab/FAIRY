"""A scene owns its clock before reads; reset cannot retain physical truth."""
from datetime import datetime, timezone

import pytest

from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.time_manager import TimeManager


@pytest.fixture
def fixed_wall_time(monkeypatch):
    wall = datetime(2026, 10, 23, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: wall)


def full_scene(count):
    scene = get_scenario_class(f"scenario_{count}_farm_full_season_hn84_normal")()
    scene.setup()
    return scene


@pytest.mark.parametrize("count", ["two", "three"])
def test_state_read_before_engine_uses_scene_clock_and_engine_keeps_progress(count, fixed_wall_time):
    scene = full_scene(count)
    clock = scene.farm_environment.time_manager
    assert all(app.time_manager is clock for app in scene.apps)
    assert scene.system.get_current_time()["current_datetime"] == "2026-05-05 07:00:00+08:00"
    snapshot = scene.farm_a.get_state()
    assert snapshot["sim_date"] == "2026-05-05"
    assert scene.farm_a.physics.last_physics_sim_time == scene.start_time
    scene.farm_environment.advance_time(3600)
    engine = Engine(None, scene)
    assert engine.time_manager is clock
    assert engine.time_manager.offset == 3600
    result = scene.farm_environment.advance_time(86400)
    for farm_id, context in scene.farm_environment.farms.items():
        assert result[farm_id]["day_ticks_run"] == 1
        assert context.world._sim_date == "2026-05-06"
        assert context.world.physics.last_physics_sim_time == scene.start_time + 90000


def test_environment_rejects_implicit_wall_clock_and_ambiguous_clock():
    weather = WeatherApp()
    farm = FarmContext("farm_a", FarmWorldApp(), weather)
    with pytest.raises(ValueError, match="start_time or an explicit clock"):
        FarmEnvironment([farm], weather)
    with pytest.raises(ValueError, match="not both"):
        FarmEnvironment([farm], weather, TimeManager(), start_time=0)
    assert farm.world.farm_environment is None


def test_rebinding_an_earlier_clock_is_rejected_before_any_binding_changes(fixed_wall_time):
    scene = full_scene("two")
    environment = scene.farm_environment
    environment.advance_time(86400)
    original_clock = environment.time_manager
    earlier = TimeManager()
    earlier.reset(scene.start_time)
    with pytest.raises(ValueError, match="earlier than initialized farm physics"):
        environment.register_time_manager(earlier)
    assert environment.time_manager is original_clock
    assert all(context.world.time_manager is original_clock for context in environment.farms.values())


def test_failed_environment_creation_does_not_leave_half_bound_farms(fixed_wall_time):
    weather = WeatherApp()
    world = FarmWorldApp()
    world.configure_physics_profile("lifecycle_static_weather")
    world.advance_physics_time()
    farm = FarmContext("farm_a", world, weather)
    original_id = world.farm_id
    original_clock = world.time_manager
    original_weather_clock = weather.time_manager
    earlier = datetime(2026, 5, 5, tzinfo=timezone.utc).timestamp()

    with pytest.raises(ValueError, match="earlier than initialized farm physics"):
        FarmEnvironment([farm], weather, start_time=earlier, timezone_name="Asia/Shanghai")
    assert farm.environment is None
    assert world.farm_environment is None
    assert world.farm_id == original_id
    assert world.time_manager is original_clock
    assert weather.time_manager is original_weather_clock
    assert weather.simulation_timezone is timezone.utc

    environment = FarmEnvironment([farm], weather, time_manager=original_clock)
    assert farm.environment is environment
    assert world.farm_environment is environment


def test_engine_rejects_environment_with_a_different_scene_origin(fixed_wall_time):
    scene = full_scene("two")
    original_clock = scene.farm_environment.time_manager
    scene.start_time += 86400
    with pytest.raises(ValueError, match="start_time must match"):
        Engine(None, scene)
    assert scene.farm_environment.time_manager is original_clock


def test_backward_sync_is_rejected_before_changing_any_farm_date(fixed_wall_time):
    scene = full_scene("two")
    environment = scene.farm_environment
    environment.advance_time(86400)
    before = {
        farm_id: (context.world._sim_date, context.world.physics.last_physics_sim_time)
        for farm_id, context in environment.farms.items()
    }
    with pytest.raises(ValueError, match="backwards"):
        environment.sync(scene.start_time)
    assert {
        farm_id: (context.world._sim_date, context.world.physics.last_physics_sim_time)
        for farm_id, context in environment.farms.items()
    } == before


def test_reset_discards_engines_and_queues_without_resetting_other_farms(fixed_wall_time):
    scene = full_scene("two")
    environment = scene.farm_environment
    environment.sync()
    world = scene.farm_a
    old_physics = world.physics
    old_physics.soil.states[0].top_vwc = 0.123
    old_physics.soil.states[0].root_vwc = 0.123
    old_physics.management.states[0].planted = True
    old_physics.phenology.states[0].planted = True
    old_physics.pending_management_actions_by_ridge[0] = [object()]
    old_physics.pending_treatments_by_ridge[0] = [object()]
    old_physics.pending_harvest_actions_by_ridge[0] = object()
    neighbor_physics = scene.farm_b.physics
    neighbor_soil = neighbor_physics.soil.states[0].top_vwc

    world.reset()
    assert world._physics is None
    assert not world.physics_active
    assert world.farm_id == "farm_a"
    assert world.farm_environment is environment
    assert world.time_manager is environment.time_manager
    assert world.simulation_timezone is environment.simulation_timezone
    assert world._sim_date == "2026-05-05"
    assert world._ridges[0].soil_vwc == 0.22
    assert not any(ridge.planted for ridge in world._ridges)
    assert world.completed_prep_ops == []

    environment.advance_time(1)
    reading = scene.sensor_a.read_soil_sensor("S1")
    assert 0.21 <= reading["vwc"] <= 0.23
    assert world._ridges[0].soil_vwc == 0.22
    assert scene.farm_b.physics is neighbor_physics
    assert neighbor_physics.soil.states[0].top_vwc == neighbor_soil

    fresh = world.physics
    assert fresh is not old_physics
    assert fresh.last_physics_sim_time is None
    assert fresh.profile_name is None
    assert not fresh.management.states[0].planted
    assert not fresh.phenology.states[0].planted
    assert not fresh.pending_management_actions_by_ridge
    assert not fresh.pending_treatments_by_ridge
    assert not fresh.pending_harvest_actions_by_ridge
