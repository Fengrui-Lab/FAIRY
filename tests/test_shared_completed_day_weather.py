"""The shared station shows today while native biology settles yesterday."""
from copy import deepcopy
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from fairy.apps.farm_world import physics_orchestrator
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.physics.weather_engine import WeatherGenerator, default_harbin_soybean_config


FIRST = date(2019, 5, 1)
ZONE = ZoneInfo("Europe/Paris")


def environment(*, native=True):
    if native:
        pytest.importorskip("pcse")
    weather = WeatherApp()
    weather.set_weather(FIRST.isoformat(), 20, 55, 2, 0, 20 / .0864)
    soy = FarmWorldApp(farm_id="soy", num_ridges=4)
    corn = FarmWorldApp(farm_id="corn", num_ridges=4, crop_type="maize", ridge_width_m=.75)
    start = datetime.combine(FIRST, datetime.min.time(), tzinfo=ZONE).replace(hour=7).timestamp()
    env = FarmEnvironment(
        [FarmContext(world.farm_id, world, weather) for world in (soy, corn)],
        weather, start_time=start, timezone_name=ZONE.key,
        warehouse=WarehouseApp(stock=WarehouseStock({}, 0, 0, 0)),
    )
    for world in (soy, corn):
        if native:
            world.configure_crop_backend("wofost", crop_name=world.crop_type)
        world.physics.engines_active = True
        world.physics.scenario_metadata = {"daily_settlement": "completed_calendar_day"}
        generator = WeatherGenerator(default_harbin_soybean_config(), seed=0)
        for offset in range(12):
            generator.set_day_override(
                FIRST + timedelta(days=offset), air_temp_mean_c=20 + offset,
                air_temp_min_c=15 + offset, air_temp_max_c=25 + offset,
                rain_mm=0 if offset == 0 else 12, wind_ms=2,
                solar_rad_mj_m2=20, relative_humidity_pct=55,
            )
        world.physics.weather_generator = generator
    return env, weather, (soy, corn)


def test_initial_native_sync_refreshes_today_before_any_crop_has_been_sown():
    env, weather, worlds = environment()
    weather.set_weather("2019-04-30", 5, 80, 9, 50, 100)
    results = env.sync()
    assert all(result["status"] == "initialized" and result["day_ticks_run"] == 0
               for result in results.values())
    assert weather.get_current_weather_snapshot()["date"] == FIRST.isoformat()
    assert weather.get_current_weather_snapshot()["rainfall_mm"] == 0
    assert all(world.physics.crop_backend.export_state()["runs"] == {} for world in worlds)
    assert env._daily_weather == {}


def test_shared_native_station_updates_to_today_without_an_extra_biological_day(monkeypatch):
    env, weather, worlds = environment()
    days = []
    advance = physics_orchestrator._run_daily_tick

    def record(world, physics, weather_app, day, inputs=None):
        days.append((world.farm_id, day))
        return advance(world, physics, weather_app, day, inputs)

    monkeypatch.setattr(physics_orchestrator, "_run_daily_tick", record)
    results = env.advance_time(86400)
    assert all(result["day_ticks_run"] == 1 for result in results.values())
    assert days == [(world.farm_id, FIRST) for world in worlds]
    current = weather.get_current_weather_snapshot()
    assert current["date"] == (FIRST + timedelta(days=1)).isoformat()
    assert current["temp_c"] == 21
    assert current["rainfall_mm"] == 12
    assert set(env._daily_weather) == {FIRST}
    assert all(world.physics.last_physics_sim_time == env.time_manager.time() for world in worlds)
    before = deepcopy([world.get_state() for world in worlds])
    for _ in range(2):
        assert all(result["status"] == "noop" for result in env.sync().values())
    assert [world.get_state() for world in worlds] == before
    assert days == [(world.farm_id, FIRST) for world in worlds]
    assert weather.get_current_weather_snapshot() == current


def test_current_day_weather_cache_does_not_bypass_the_public_station_refresh():
    env, weather, _ = environment()
    cached = env.weather_inputs(FIRST, True)
    weather.set_weather("2019-04-30", 5, 80, 9, 50, 100)
    env.sync()
    assert env._daily_weather[FIRST] is cached
    assert weather.get_current_weather_snapshot()["date"] == FIRST.isoformat()
    assert weather.get_current_weather_snapshot()["temp_c"] == 20
    assert weather.get_current_weather_snapshot()["rainfall_mm"] == 0


def test_legacy_completed_day_worlds_retain_their_existing_weather_behavior():
    env, weather, _ = environment(native=False)
    env.advance_time(86400)
    # Only native WOFOST opted-in worlds acquire the new public projection.
    assert weather.get_current_weather_snapshot()["date"] == FIRST.isoformat()
