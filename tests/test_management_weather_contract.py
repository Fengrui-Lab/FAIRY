from datetime import date, timedelta

from fairy.apps.farm_world import FarmWorldApp, WeatherApp
from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs
from fairy.scenarios.management_extensions.L4.scenario_two_year_maize_soil_carryover import (
    TwoYearMaizeScenario,
)


def test_every_calendar_day_forecast_current_and_physics_agree():
    scene = TwoYearMaizeScenario()
    scene.setup()
    farm = scene.get_typed_app(FarmWorldApp)
    weather = scene.get_typed_app(WeatherApp)
    forecast_by_day = {}
    winter_temperatures = []
    for offset in range(550):
        day = date(2026, 5, 5) + timedelta(days=offset)
        inputs = _build_weather_inputs(weather, day, physics=farm.physics)
        current = weather.get_current_weather_snapshot()
        assert current["date"] == day.isoformat()
        assert inputs["soil"].day == day
        assert current["rainfall_mm"] == inputs["soil"].rain_mm
        assert current["temp_c"] == inputs["soil"].air_temp_mean_c
        if day.isoformat() in forecast_by_day:
            forecast = forecast_by_day[day.isoformat()]
            assert forecast["rainfall_mm"] == current["rainfall_mm"]
            assert forecast["temp_c"] == current["temp_c"]
        forecast_by_day.update(
            {row["date"]: row for row in weather.get_forecast()["forecast"]}
        )
        if day.month in (12, 1, 2):
            winter_temperatures.append(current["temp_c"])
    assert min(winter_temperatures) < 0
