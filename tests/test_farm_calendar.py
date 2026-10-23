"""The scene calendar, model dates and tools must agree at date boundaries."""
from datetime import date, datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from fairy.agents.agent.base_agent import BaseAgent
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.physics_orchestrator import _dates_between
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class


SHANGHAI = ZoneInfo("Asia/Shanghai")
SCENES = (
    "scenario_two_farm_full_season_hn84_normal",
    "scenario_three_farm_full_season_hn84_normal",
)


def local_timestamp(day: int, hour: int, minute: int = 0) -> float:
    return datetime(2026, 5, day, hour, minute, tzinfo=SHANGHAI).timestamp()


def static_environment(monkeypatch, start: float) -> FarmEnvironment:
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: 0.0)
    weather = WeatherApp()
    weather.set_weather(
        date="2026-05-05", temp_c=16.0, humidity_pct=55.0,
        wind_speed_ms=1.0, rainfall_mm=0.0, solar_radiation=250.0,
        forecast=[{
            "date": "2026-05-06", "temp_c": 18.0, "humidity_pct": 50.0,
            "wind_speed_ms": 1.0, "rainfall_mm": 0.0, "solar_radiation": 250.0,
        }],
    )
    farms = []
    for farm_id in ("farm_a", "farm_b"):
        world = FarmWorldApp(farm_id=farm_id)
        world.configure_physics_profile("calendar_static_weather")
        farms.append(FarmContext(farm_id, world, weather))
    return FarmEnvironment(
        farms, weather, start_time=start, timezone_name="Asia/Shanghai"
    )


def test_local_midnight_advances_one_day_even_without_crossing_utc_date(monkeypatch):
    env = static_environment(monkeypatch, local_timestamp(5, 23, 50))
    result = env.advance_time(20 * 60)
    assert all(item["day_ticks_run"] == 1 for item in result.values())
    assert {farm.world._sim_date for farm in env.farms.values()} == {"2026-05-06"}
    assert env.weather.get_current_weather_snapshot()["date"] == "2026-05-06"


def test_utc_midnight_does_not_advance_the_local_day(monkeypatch):
    env = static_environment(monkeypatch, local_timestamp(5, 7, 50))
    result = env.advance_time(20 * 60)
    assert all(item["day_ticks_run"] == 0 for item in result.values())
    assert {farm.world._sim_date for farm in env.farms.values()} == {"2026-05-05"}
    assert env.weather.get_current_weather_snapshot()["date"] == "2026-05-05"


def test_date_arithmetic_keeps_utc_as_legacy_default():
    start, end = local_timestamp(5, 7, 50), local_timestamp(5, 8, 10)
    assert _dates_between(start, end) == [date(2026, 5, 5)]
    assert _dates_between(start, end, simulation_timezone=SHANGHAI) == []
    assert FarmWorldApp().simulation_timezone is timezone.utc


def test_standalone_sowing_window_keeps_its_existing_beijing_calendar(monkeypatch):
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: 0.0)
    farm = FarmWorldApp()
    farm.time_manager.reset(local_timestamp(5, 7))
    farm.configure_planting_windows([{
        "start": 0, "end": 0, "earliest_date": "2026-05-05",
    }])
    assert farm.check_planting_window([0], "HEINONG84") is None
    farm.time_manager.reset(local_timestamp(4, 23))
    assert "today=2026-05-04" in farm.check_planting_window([0], "HEINONG84")


@pytest.mark.parametrize("scene_id", SCENES)
def test_initial_system_world_engine_and_agent_share_one_local_date(monkeypatch, scene_id):
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: 0.0)
    scenario = get_scenario_class(scene_id)()
    scenario.setup()
    agent = BaseAgent("calendar", SimpleNamespace(provider="openai"))
    engine = Engine(agent, scenario)
    snapshot = scenario.system.get_current_time()
    expected = "2026-05-05 07:00:00+08:00"
    assert snapshot["current_datetime"] == expected
    assert snapshot["timezone"] == "Asia/Shanghai"
    assert snapshot["utc_offset"] == "+0800"
    assert engine._format_timestamp(scenario.start_time) == agent.env_time_str() == expected
    for farm in scenario.farm_environment.farms.values():
        # First access must preserve the scene date rather than move it to May 4.
        assert farm.world.get_state()["sim_date"] == "2026-05-05"
        assert farm.world.physics.last_physics_sim_time == scenario.start_time
    assert scenario.weather.get_current_weather_snapshot()["date"] == "2026-05-05"
    advanced = scenario.system.advance_time(hours=1)
    assert advanced["current_datetime"] == "2026-05-05 08:00:00+08:00"
    assert all(farm.world._sim_date == "2026-05-05"
               for farm in scenario.farm_environment.farms.values())


def test_seeded_planting_history_uses_the_scene_day(monkeypatch):
    env = static_environment(monkeypatch, local_timestamp(5, 7))
    ridge = env.get_farm("farm_a").world._ridges[0]
    ridge.planted = True
    ridge.days_since_planted = 2
    env.sync()
    phenology = env.get_farm("farm_a").world.physics.phenology.states[0]
    assert phenology.planting_date == date(2026, 5, 3)


def test_sowing_windows_planting_records_and_observations_use_local_day(monkeypatch):
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: 0.0)
    scenario = get_scenario_class(SCENES[0])()
    scenario.setup()
    Engine(None, scenario)
    farm = scenario.farm_a
    farm.configure_planting_windows([{
        "start": 0, "end": 0, "earliest_date": "2026-05-05",
    }])
    assert farm.check_planting_window([0], "HEINONG84") is None
    # The test starts from completed preparation to isolate the sowing calendar.
    farm.completed_prep_ops[:] = ["level", "base_fertilize", "form_ridges"]
    assert scenario.tractor.load_seeds("farm_a", "HEINONG84", 10_000)["status"] == "ok"
    assert scenario.tractor.plant_seeds("farm_a", 0, 0, 4.0, 7.9)["status"] == "ok"
    assert farm.physics.phenology.states[0].planting_date == date(2026, 5, 5)
    # Hold flight eligibility constant; this assertion concerns observation dates.
    scenario.weather.set_weather(
        date="2026-05-05", temp_c=16.0, humidity_pct=55.0,
        wind_speed_ms=1.0, rainfall_mm=0.0, solar_radiation=250.0,
    )
    observation_days = []
    model = farm.physics.observation_model
    for method_name in (
        "observe_uav_multispectral", "observe_uav_thermal", "observe_ground_inspection"
    ):
        original = getattr(model, method_name)

        def record_day(*args, _original=original, **kwargs):
            observation_days.append(kwargs["day"])
            return _original(*args, **kwargs)

        monkeypatch.setattr(model, method_name, record_day)
    assert scenario.mavic.fly_survey("farm_a", 0, 0)["status"] == "ok"
    assert scenario.robot.inspect_crop_health("farm_a", 0, 0)["status"] == "ok"
    assert len(observation_days) == 3
    assert set(observation_days) == {date(2026, 5, 5)}


def test_weather_forecast_promotes_on_local_midnight():
    weather = WeatherApp()
    weather.simulation_timezone = SHANGHAI
    weather.set_weather(
        date="2026-05-05", temp_c=16.0, humidity_pct=55.0,
        wind_speed_ms=1.0, rainfall_mm=0.0, solar_radiation=250.0,
        forecast=[{
            "date": "2026-05-06", "temp_c": 18.0, "humidity_pct": 50.0,
            "wind_speed_ms": 1.0, "rainfall_mm": 0.0, "solar_radiation": 250.0,
        }],
    )
    assert weather.advance_to_timestamp(local_timestamp(6, 0, 1))["status"] == "advanced"
    assert weather.get_current_weather_snapshot()["date"] == "2026-05-06"
