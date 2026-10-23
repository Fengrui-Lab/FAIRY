from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
from fairy.scenarios.scenario import Scenario
from fairy.time_manager import TimeManager


START = datetime(2026, 4, 25, 7, tzinfo=timezone.utc).timestamp()


@pytest.fixture
def two_farms(monkeypatch):
    # Keep assertions about clock ownership independent of wall-clock runtime.
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: START)
    clock = TimeManager()
    clock.reset(START)
    weather = WeatherApp()
    weather.set_weather(
        date="2026-04-25", temp_c=15.0, humidity_pct=55.0,
        wind_speed_ms=1.0, rainfall_mm=0.0, solar_radiation=350.0,
        avg_soil_vwc=0.23,
        forecast=[
            {"date": "2026-04-26", "temp_c": 19.0, "rainfall_mm": 4.0},
            {"date": "2026-04-27", "temp_c": 24.0, "rainfall_mm": 0.0},
            {"date": "2026-04-28", "temp_c": 21.0, "rainfall_mm": 1.0},
        ],
    )
    farms = []
    for farm_id, vwc in (("farm_a", 0.17), ("farm_b", 0.34)):
        world = FarmWorldApp(farm_id=farm_id, name=f"{farm_id}_World")
        for ridge in world._ridges:
            ridge.soil_vwc = vwc
            ridge.soil_temp_c = 15.0
        world.configure_physics_profile("two_farm_static_weather")
        farms.append(FarmContext(farm_id, world, weather))
    return FarmEnvironment(farms, weather, clock)


def test_two_physical_farms_use_one_forecast_day_and_keep_soil_independent(two_farms):
    env = two_farms
    env.advance_time(86400)
    assert env.time_manager.offset == 86400
    assert env.weather.get_current_weather_snapshot()["date"] == "2026-04-26"
    assert env.weather.get_forecast()["forecast"][0]["date"] == "2026-04-27"
    assert env.weather._avg_soil_vwc == 0.23
    a, b = env.get_farm("farm_a").world, env.get_farm("farm_b").world
    assert a._sim_date == b._sim_date == "2026-04-26"
    assert a.physics.last_physics_sim_time == b.physics.last_physics_sim_time == START + 86400
    assert a.physics.soil.states[0].top_vwc < b.physics.soil.states[0].top_vwc
    assert env.weather_inputs(date(2026, 4, 26), True)["soil"].rain_mm == 4.0
    assert env.weather_inputs(date(2026, 4, 26), True)["soil"].air_temp_mean_c == 19.0
    # A second read cannot consume the second forecast day or repeat a tick.
    before = b.physics.soil.states[0].top_vwc
    a.get_farm_overview()
    assert b.physics.soil.states[0].top_vwc == before
    assert env.weather.get_current_weather_snapshot()["date"] == "2026-04-26"


def test_multi_day_jump_uses_each_days_forcing_once(two_farms):
    env = two_farms
    result = env.advance_time(2 * 86400)
    assert result["farm_a"]["day_ticks_run"] == 2
    assert result["farm_b"]["day_ticks_run"] == 2
    assert env.weather.get_current_weather_snapshot()["date"] == "2026-04-27"
    assert env.weather_inputs(date(2026, 4, 26), True)["soil"].air_temp_mean_c == 19.0
    assert env.weather_inputs(date(2026, 4, 27), True)["soil"].air_temp_mean_c == 24.0
    assert len(env.weather.get_forecast()["forecast"]) == 1


def test_scenario_can_install_todays_weather_without_station_advancing_twice(two_farms):
    env = two_farms
    env.sync()
    env.weather.set_weather(
        date="2026-04-26", temp_c=20.0, humidity_pct=55.0,
        wind_speed_ms=1.0, rainfall_mm=6.0, solar_radiation=350.0,
    )
    env.advance_time(86400)
    assert env.weather.get_current_weather_snapshot()["date"] == "2026-04-26"
    assert env.weather_inputs(date(2026, 4, 26), True)["soil"].rain_mm == 6.0


def test_generated_weather_is_published_once_for_each_shared_day(two_farms, monkeypatch):
    env = two_farms
    for farm in env.farms.values():
        farm.world.configure_physics_profile("harbin_cold_spring_seed_202")
    published = []
    real_set_weather = env.weather.set_weather

    def record_weather(**kwargs):
        published.append(kwargs["date"])
        return real_set_weather(**kwargs)

    monkeypatch.setattr(env.weather, "set_weather", record_weather)
    env.advance_time(2 * 86400)
    assert published == ["2026-04-26", "2026-04-27"]
    a, b = (farm.world for farm in env.farms.values())
    assert a.physics.last_physics_sim_time == b.physics.last_physics_sim_time
    assert env.weather._avg_soil_vwc == 0.23


def test_direct_farm_daily_commit_advances_both_fields(two_farms):
    env = two_farms
    a, b = env.get_farm("farm_a").world, env.get_farm("farm_b").world
    result = a.commit_daily_physics()
    assert result["status"] == "ok"
    assert env.time_manager.offset == 86400
    assert a.physics.last_physics_sim_time == b.physics.last_physics_sim_time == START + 86400


def test_engine_system_and_notification_wait_advance_all_farms(two_farms):
    env = two_farms
    system = SystemApp()
    scenario = Scenario(start_time=START, apps=[
        *(farm.world for farm in env.farms.values()), env.weather, system,
    ])
    scenario.farm_environment = env
    scenario.shared_equipment = []
    engine = Engine(None, scenario)
    assert system.farm_environment is env
    assert all(farm.world.time_manager is engine.time_manager for farm in env.farms.values())
    system.advance_time(days=1)
    system.wait_for_notification(timeout=86400)
    assert engine.time_manager.offset == 2 * 86400
    assert env.weather.get_current_weather_snapshot()["date"] == "2026-04-27"
    assert all(
        farm.world.physics.last_physics_sim_time == START + 2 * 86400
        for farm in env.farms.values()
    )
    summary = engine.outcome_summary()
    assert set(summary["farms"]) == {"farm_a", "farm_b"}
    assert summary["shared_equipment"] == {}


def test_notification_wait_stops_at_event_and_synchronizes_before_event(two_farms):
    env = two_farms
    observed = []
    event = SimpleNamespace(
        time_start=START + 86400,
        triggered=False,
        start=lambda now: observed.append(now),
        step=lambda: "day changed",
    )
    system = SystemApp()
    scenario = Scenario(start_time=START, apps=[system], dynamic_events=[event])
    scenario.farm_environment = env
    Engine(None, scenario)
    system.wait_for_notification(timeout=2 * 86400)
    assert event.triggered
    assert observed == [START + 86400]
    assert all(farm.world._sim_date == "2026-04-26" for farm in env.farms.values())


def test_field_preparation_state_has_farm_ownership_and_roundtrips(two_farms):
    a, b = (farm.world for farm in two_farms.farms.values())
    a.completed_prep_ops.append("level_field")
    saved = a.get_state()
    assert b.completed_prep_ops == []
    a.completed_prep_ops.clear()
    a.load_state(saved)
    assert a.completed_prep_ops == ["level_field"]
    with pytest.raises(ValueError, match="another farm"):
        b.load_state(saved)


def test_context_legacy_clock_does_not_advance_world_clock(monkeypatch):
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: START)
    world, weather = FarmWorldApp(), WeatherApp()
    device_clock = TimeManager()
    context = FarmContext("legacy", world, weather, legacy_clock=device_clock)
    context.advance_time(120)
    assert device_clock.offset == 120
    assert world.time_manager.offset == 0
    assert world._physics is None


def test_environment_rejects_duplicate_world_and_invalid_time(two_farms):
    env = two_farms
    with pytest.raises(ValueError, match="non-negative"):
        env.advance_time(-1)
    with pytest.raises(ValueError, match="Unknown farm_id"):
        env.get_farm("missing")
    assert env.time_manager.offset == 0
