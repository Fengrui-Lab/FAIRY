from datetime import date

import pytest

from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
from fairy.apps.farm_world.physics_orchestrator import _generate_weather_day
from fairy.physics.weather_engine import (
    WeatherEvent,
    WeatherGenerator,
    default_harbin_soybean_config,
)
from fairy.scenarios.farm_world_fullseason_v2.farm_checkpoint_state import (
    _export_weather_generator,
    _restore_weather_generator,
)


def test_exact_override_survives_events_repeated_generation_and_cache() -> None:
    generator = WeatherGenerator(default_harbin_soybean_config(), seed=17)
    day = date(2017, 5, 10)
    previous = _generate_weather_day(generator, day)
    tags = ["historical_record"]
    generator.set_day_override(
        day, air_temp_mean_c=14.321, air_temp_min_c=7.123,
        air_temp_max_c=21.987, rain_mm=0.0, wind_ms=2.123,
        solar_rad_mj_m2=18.456, weather_tags=tags,
    )
    tags.append("caller_mutation")
    events = [WeatherEvent("rain_event", day, 1, total_rain_mm=80.0)]
    first = generator.generate(day, day, events)[0]
    second = generator.generate(day, day, events)[0]
    assert first == second
    assert first.air_temp_mean_c == 14.321
    assert first.air_temp_min_c == 7.123
    assert first.air_temp_max_c == 21.987
    assert first.rain_mm == 0.0 and not first.is_raining
    assert first.wind_ms == 2.123
    assert first.solar_rad_mj_m2 == 18.456
    assert first.weather_tags == ["historical_record"]
    first.weather_tags.append("result_mutation")
    assert generator.generate(day, day)[0].weather_tags == ["historical_record"]
    assert _generate_weather_day(generator, day) == second
    assert _generate_weather_day(generator, day) != previous


def test_farm_override_defaults_and_future_checkpoint_weather() -> None:
    physics = FarmPhysicsState(num_ridges=1)
    # October is deliberately absent from the default generator's climatology.
    day = date(2017, 10, 1)
    physics.set_weather_day_override(
        day, air_temp_mean_c=8.0, rain_mm=12.345,
        wind_ms=1.5, solar_rad_mj_m2=9.123,
    )
    generator = physics.weather_generator
    assert generator is not None
    pinned = generator.generate(day, day)[0]
    assert pinned.air_temp_min_c == 3.0
    assert pinned.air_temp_max_c == 13.0
    assert pinned.rain_mm == 12.345 and pinned.is_raining
    restored = WeatherGenerator(default_harbin_soybean_config(), seed=42)
    _restore_weather_generator(restored, _export_weather_generator(generator))
    assert _generate_weather_day(restored, day) == pinned
    with pytest.raises(ValueError, match="Tmin"):
        generator.set_day_override(
            day, air_temp_mean_c=8, air_temp_min_c=12,
            rain_mm=0, wind_ms=1, solar_rad_mj_m2=9,
        )


def test_observed_humidity_reaches_current_weather_forecast_and_checkpoint() -> None:
    from datetime import timedelta
    from fairy.apps.farm_world.weather_app import WeatherApp
    from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs

    physics = FarmPhysicsState(num_ridges=1)
    day = date(2017, 5, 10)
    for offset in range(8):
        physics.set_weather_day_override(
            day + timedelta(days=offset), air_temp_mean_c=20.0, rain_mm=0.0,
            wind_ms=2.0, solar_rad_mj_m2=20.0, relative_humidity_pct=73.25 + offset,
        )
    weather = WeatherApp()
    forcing = _build_weather_inputs(weather, day, physics)
    current = weather.get_current_weather_snapshot()
    assert current["humidity_pct"] == 73.2  # Agent display rounds, native forcing must not.
    assert forcing["humidity_pct"] == 73.25
    assert weather.get_forecast()["forecast"][0]["humidity_pct"] == 74.25
    restored = WeatherGenerator(default_harbin_soybean_config(), seed=42)
    _restore_weather_generator(restored, _export_weather_generator(physics.weather_generator))
    assert _generate_weather_day(restored, day).relative_humidity_pct == 73.25
    with pytest.raises(ValueError, match="humidity"):
        physics.set_weather_day_override(
            day, air_temp_mean_c=20.0, rain_mm=0.0, wind_ms=2.0,
            solar_rad_mj_m2=20.0, relative_humidity_pct=101.0,
        )
