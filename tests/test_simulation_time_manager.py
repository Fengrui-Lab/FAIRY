"""Live farm simulation and replay must not depend on model or host speed."""
from datetime import datetime, timezone

import pytest

from fairy.scenarios.registry import get_scenario_class
from fairy.time_manager import SimulationTimeManager, TimeManager


def test_simulation_clock_uses_explicit_durations_while_legacy_keeps_wall_time(monkeypatch):
    wall = [1000.0]
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: wall[0])
    simulation = SimulationTimeManager()
    legacy = TimeManager()
    simulation.reset(500.0)
    legacy.reset(500.0)
    wall[0] += 3600.0
    assert simulation.time() == 500.0
    assert legacy.time() == 4100.0
    simulation.add_offset(60)
    assert simulation.time() == 560.0
    simulation.reset(700.0)
    assert simulation.time() == 700.0
    assert simulation.offset == 0


@pytest.mark.parametrize("count", ["two", "three"])
def test_model_wait_cannot_change_farm_date_but_explicit_wait_advances_all_farms(monkeypatch, count):
    wall = [0.0]
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: wall[0])
    scene = get_scenario_class(f"scenario_{count}_farm_full_season_hn84_normal")()
    scene.setup()
    environment = scene.farm_environment
    assert isinstance(environment.time_manager, SimulationTimeManager)
    environment.sync()
    wall[0] += 86400.0
    assert environment.time_manager.time() == scene.start_time
    assert scene.system.get_current_time()["current_datetime"] == "2026-05-05 07:00:00+08:00"
    assert {farm.world._sim_date for farm in environment.farms.values()} == {"2026-05-05"}

    result = scene.system.advance_time(days=1)
    assert result["current_datetime"] == "2026-05-06 07:00:00+08:00"
    assert all(farm.world.physics.last_physics_sim_time == scene.start_time + 86400
               for farm in environment.farms.values())
    assert {farm.world._sim_date for farm in environment.farms.values()} == {"2026-05-06"}


def test_explicitly_provided_legacy_clock_remains_caller_owned(monkeypatch):
    from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
    from fairy.apps.farm_world.farm_world_app import FarmWorldApp
    from fairy.apps.farm_world.weather_app import WeatherApp

    wall = [0.0]
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: wall[0])
    clock = TimeManager()
    start = datetime(2026, 5, 5, tzinfo=timezone.utc).timestamp()
    clock.reset(start)
    weather = WeatherApp()
    environment = FarmEnvironment([FarmContext("farm_a", FarmWorldApp(), weather)], weather, clock)
    wall[0] += 60
    assert environment.time_manager is clock
    assert environment.time_manager.time() == start + 60
