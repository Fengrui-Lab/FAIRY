"""Old checkpoint migration and complete crop snapshots keep regional weather."""
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.system import SystemApp
from fairy.physics.weather_engine import WeatherEvent
from fairy.scenarios.farm_world_fullseason_v2.farm_checkpoint_state import (
    export_farm_checkpoint_state, restore_farm_checkpoint_state,
)
from fairy.scenarios.farm_world_fullseason_v2.l2_l1_splits.hb_coldspring_planting_window_heihe50.scenario_l2_heihe50_harvest_drydown_store import (
    ScenarioL2HBColdspringHeihe50HarvestDrydownStore,
)
from fairy.time_manager import SimulationTimeManager


CHECKPOINT = (Path(__file__).resolve().parents[1] / "fairy/scenarios/farm_world_fullseason_v2/l2_l1_splits/"
              "hb_coldspring_planting_window_heihe50/checkpoints/o_wait_harvest_day_020.json")


def test_legacy_heihe50_checkpoint_keeps_rng_and_generates_weather_after_forecast_end():
    checkpoint = json.loads(CHECKPOINT.read_text())
    scene = ScenarioL2HBColdspringHeihe50HarvestDrydownStore()
    scene.setup()
    clock = SimulationTimeManager()
    clock.reset(scene.start_time)
    for app in scene.apps:
        app.register_time_manager(clock)
    world, weather = scene.get_typed_app(FarmWorldApp), scene.get_typed_app(WeatherApp)
    system = scene.get_typed_app(SystemApp)
    generator = world.physics.weather_generator
    assert generator is not None and world.physics.profile is not None
    assert generator.rng.bit_generator.state == checkpoint["physics_state"]["weather_generator"]["rng_state"]
    initial_rng = deepcopy(generator.rng.bit_generator.state)
    observed = {}
    for offset in range(1, 17):
        assert system.advance_time(days=1)["status"] == "ok"
        observed[offset] = weather.get_current_weather()
        assert len(weather.get_forecast(days=7)["forecast"]) == 7
    # Golden values from this historical checkpoint's original continuation.
    # The broken migration instead repeated 27.96 C / 16.42 mm after day 7.
    assert observed[10] == {
        "date": "2026-08-31", "temp_c": 21.73, "humidity_pct": 55.0,
        "wind_speed_ms": 4.62, "rainfall_mm": 0.0, "solar_radiation": 237.3,
    }
    assert observed[16] == {
        "date": "2026-09-06", "temp_c": 16.31, "humidity_pct": 55.0,
        "wind_speed_ms": 5.75, "rainfall_mm": 0.0, "solar_radiation": 225.5,
    }
    assert generator.rng.bit_generator.state != initial_rng


def new_physical_farm(crop_id, start_time):
    world = FarmWorldApp(farm_id="field", crop_id=crop_id)
    weather = WeatherApp()
    weather.set_weather(date="2026-05-15", temp_c=17.0, humidity_pct=55.0,
                        wind_speed_ms=2.0, rainfall_mm=0.0, solar_radiation=250.0)
    environment = FarmEnvironment([FarmContext("field", world, weather)], weather,
                                  start_time=start_time, timezone_name="Asia/Shanghai")
    return world, weather, environment


@pytest.mark.parametrize("crop_id", ["soybean", "maize"])
def test_full_checkpoint_preserves_custom_weather_profile_and_exact_continuation(crop_id):
    start = datetime(2026, 5, 15, 7, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
    original, weather, environment = new_physical_farm(crop_id, start)
    original.configure_physics_profile("harbin_baseline_2026_seed_101")
    original.physics.profile = deepcopy(original.physics.profile)
    # This event is beyond the saved forecast cache, so continued generation
    # must use the saved scenario profile rather than the registered template.
    original.physics.profile.weather_events.append(WeatherEvent(
        event_type="wind_event", start_date=date(2026, 5, 25), duration_days=4,
        wind_ms=9.75, label="checkpoint_local_wind_marker",
    ))
    environment.advance_time(86400)
    saved_time = environment.time_manager.time()
    checkpoint = json.loads(json.dumps(export_farm_checkpoint_state(
        farm_world=original, weather_app=weather, scenario_id="continuation-test",
        checkpoint_label="custom-regional-weather",
    ), allow_nan=False))
    assert checkpoint["schema_version"] == 2
    assert "physics_state" not in checkpoint  # no competing soybean-only copy
    restored, restored_weather, restored_environment = new_physical_farm(crop_id, saved_time)
    with patch.object(restored, "configure_physics_profile", side_effect=AssertionError("must use the saved complete bundle")):
        restore_farm_checkpoint_state(farm_world=restored, weather_app=restored_weather,
                                      checkpoint_state=checkpoint, target_sim_time=saved_time)
    assert restored.get_state() == original.get_state()
    for _ in range(16):
        environment.advance_time(86400)
        restored_environment.advance_time(86400)
        assert weather.get_current_weather() == restored_weather.get_current_weather()
        assert original.get_state() == restored.get_state()
    assert restored.physics.weather_generator.rng.bit_generator.state == original.physics.weather_generator.rng.bit_generator.state
    event_day = restored.physics.weather_generator._day_cache[date(2026, 5, 25)]
    assert event_day.wind_ms == 9.75
    assert "checkpoint_local_wind_marker" in event_day.weather_tags
