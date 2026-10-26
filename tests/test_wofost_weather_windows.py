"""Explicit operational weather windows preserve all undeclared forcing."""
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, timedelta
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from fairy.apps.farm_world import FarmWorldApp, WeatherApp
from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs, _generate_weather_day
from fairy.physics.weather_engine import MonthlyClimate, WeatherGenerator, WeatherGeneratorConfig
from fairy.scenarios.wofost_events import (
    DroughtEvent, PressureEvent, WeatherWindowEvent, apply_scenario_events_for_day,
    install_scenario_events, scenario_events_snapshot,
)


DAY = date(2026, 6, 1)
START = datetime(2026, 6, 1, 7, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()


def farm(farm_id="east"):
    value = FarmWorldApp(name="Farm_" + farm_id, farm_id=farm_id, num_ridges=4)
    value.simulation_timezone = ZoneInfo("Asia/Shanghai")
    value._sim_date = DAY.isoformat()
    value.physics.engines_active = True
    value.physics.weather_generator = WeatherGenerator(WeatherGeneratorConfig(monthly={
        month: MonthlyClimate(20, 40, .4, 20) for month in range(1, 13)}), seed=9)
    for offset in range(9):
        value.physics.weather_generator.set_day_override(DAY + timedelta(days=offset),
            air_temp_mean_c=21., rain_mm=12.+offset, wind_ms=2.37+offset/100,
            solar_rad_mj_m2=18.+offset/10, air_temp_min_c=15., air_temp_max_c=27.,
            relative_humidity_pct=70.+offset, weather_tags=["original_pinned_reference"])
    return value


def scene(*farms):
    return SimpleNamespace(apps=list(farms), start_time=START)


def window(event_id="closed", **updates):
    return WeatherWindowEvent(event_id, "east", DAY, DAY + timedelta(days=2), **updates)


@pytest.mark.parametrize("updates", [{"rain_mm": 8.}, {"wind_ms": 7.}, {"rain_mm": 0., "wind_ms": 2.}])
def test_window_only_changes_declared_fields_and_target_farm_with_exclusive_stop(updates):
    east, west = farm(), farm("west")
    original = deepcopy(east.physics.weather_generator._day_overrides)
    install_scenario_events(scene(east, west), [window(**updates)])
    for day, before in original.items():
        actual = asdict(_generate_weather_day(east.physics.weather_generator, day))
        expected = asdict(before)
        if DAY <= day < DAY + timedelta(days=2):
            expected.update(updates)
            expected["is_raining"] = expected["rain_mm"] > .1
            expected["weather_tags"].append("scenario_weather_window:closed")
        assert actual == expected
        assert _generate_weather_day(west.physics.weather_generator, day) == before


def test_per_day_amount_is_not_split_as_a_whole_interval_rain_total():
    value = farm()
    install_scenario_events(scene(value), [window(rain_mm=8.)])
    assert sum(_generate_weather_day(value.physics.weather_generator, DAY+timedelta(days=i)).rain_mm
               for i in range(2)) == 16.
    assert _generate_weather_day(value.physics.weather_generator, DAY+timedelta(days=2)).rain_mm == 14.


def test_before_after_ledger_and_plan_are_explicit_json_and_idempotent():
    value = farm()
    declaration = window(rain_mm=0., wind_ms=2.)
    install_scenario_events(scene(value), [declaration])
    first = scenario_events_snapshot(value)
    assert first["events"][0]["type"] == "weather_window"
    assert first["events"][0]["start"] == "2026-06-01"
    assert first["events"][0]["end"] == "2026-06-03"
    assert first["weather_changes"][0] == {
        "event_id": "closed", "day": "2026-06-01", "type": "weather_window",
        "before": {"rain_mm": 12., "wind_ms": 2.37}, "after": {"rain_mm": 0., "wind_ms": 2.},
    }
    pins = deepcopy(value.physics.weather_generator._day_overrides)
    install_scenario_events(scene(value), [declaration])
    assert scenario_events_snapshot(value) == first
    assert value.physics.weather_generator._day_overrides == pins
    assert json.loads(json.dumps(first, allow_nan=False)) == first
    # A weather declaration is not a pressure event and does not alter biotics.
    pressure = deepcopy(value.physics.biotic.get_state())
    assert apply_scenario_events_for_day(value, DAY) == []
    assert value.physics.biotic.get_state() == pressure


@pytest.mark.parametrize("reverse", [False, True])
def test_overlapping_disjoint_fields_compose_without_reverting_earlier_edits(reverse):
    value = farm()
    declarations = [window("rain", rain_mm=0.), window("wind", wind_ms=8.)]
    install_scenario_events(scene(value), declarations[::-1] if reverse else declarations)
    actual = _generate_weather_day(value.physics.weather_generator, DAY)
    assert (actual.rain_mm, actual.wind_ms, actual.relative_humidity_pct) == (0., 8., 70.)
    assert len(scenario_events_snapshot(value)["weather_changes"]) == 4


def test_wind_window_can_overlap_old_drought_while_old_drought_ledger_is_unchanged():
    value = farm()
    declarations = [window("wind", wind_ms=7.), DroughtEvent("dry", "east", DAY, DAY+timedelta(days=2), .25)]
    install_scenario_events(scene(value), declarations)
    assert _generate_weather_day(value.physics.weather_generator, DAY).rain_mm == 3.
    assert _generate_weather_day(value.physics.weather_generator, DAY).wind_ms == 7.
    dry = [row for row in scenario_events_snapshot(value)["weather_changes"] if row["event_id"] == "dry"]
    assert dry[0] == {"event_id": "dry", "day": "2026-06-01", "baseline_rain_mm": 12., "rain_mm": 3.}


@pytest.mark.parametrize("other", [
    lambda: window("second_rain", rain_mm=0.),
    lambda: DroughtEvent("dry", "east", DAY, DAY+timedelta(days=1)),
])
def test_same_day_same_field_conflicts_fail_before_mutating_any_pin(other):
    value = farm()
    before = deepcopy(value.physics.weather_generator._day_overrides)
    with pytest.raises(ValueError, match="same day/field"):
        install_scenario_events(scene(value), [window(rain_mm=8.), other()])
    assert value.physics.weather_generator._day_overrides == before
    assert scenario_events_snapshot(value) == {}


@pytest.mark.parametrize("updates", [
    {}, {"rain_mm": -1.}, {"wind_ms": -1.}, {"rain_mm": float("nan")},
    {"wind_ms": float("inf")}, {"rain_mm": True}, {"wind_ms": "7"},
])
def test_invalid_window_values_are_explicit_errors(updates):
    with pytest.raises(ValueError, match="WeatherWindowEvent"):
        window(**updates)


def test_unpinned_day_on_later_farm_cannot_partially_install_the_first_farm():
    east, west = farm(), farm("west")
    before = deepcopy(east.physics.weather_generator._day_overrides)
    invalid = WeatherWindowEvent("missing_pin", "west", DAY+timedelta(days=9), DAY+timedelta(days=10), wind_ms=7.)
    with pytest.raises(ValueError, match="explicit pinned"):
        install_scenario_events(scene(east, west), [window(rain_mm=8.), invalid])
    assert east.physics.weather_generator._day_overrides == before
    assert scenario_events_snapshot(east) == scenario_events_snapshot(west) == {}


def test_current_station_cached_generation_and_forecast_share_the_declared_open_window():
    value, station = farm(), WeatherApp()
    value.attach_weather_app(station)
    _build_weather_inputs(station, DAY, physics=value.physics, advance_weather=False)
    assert station.get_current_weather()["rainfall_mm"] == 12.
    install_scenario_events(scene(value), [window(rain_mm=0., wind_ms=2.)])
    current = station.get_current_weather()
    assert (current["rainfall_mm"], current["wind_speed_ms"], current["temp_c"], current["humidity_pct"]) == (0., 2., 21., 70.)
    forecast = {row["date"]: row for row in station.get_forecast()["forecast"]}
    assert forecast["2026-06-02"]["rainfall_mm"] == 0.
    assert forecast["2026-06-02"]["wind_speed_ms"] == 2.
    assert forecast["2026-06-03"]["rainfall_mm"] == 14.
    assert _generate_weather_day(value.physics.weather_generator, DAY).wind_ms == 2.


def test_full_checkpoint_restore_keeps_future_windows_and_does_not_append_a_second_ledger():
    from fairy.scenarios.farm_world_fullseason_v2.farm_checkpoint_state import (
        export_farm_checkpoint_state, restore_farm_checkpoint_state,
    )
    from fairy.time_manager import SimulationTimeManager

    value = farm()
    clock = SimulationTimeManager(); clock.reset(START)
    value.register_time_manager(clock)
    declaration = WeatherWindowEvent("future", "east", DAY+timedelta(days=2), DAY+timedelta(days=4), rain_mm=0., wind_ms=2.)
    install_scenario_events(scene(value), [declaration])
    value.advance_physics_time(START)
    payload = json.loads(json.dumps(export_farm_checkpoint_state(farm_world=value, weather_app=None,
        scenario_id="window_codec", checkpoint_label="before_window"), allow_nan=False))
    restored = farm()
    restored_clock = SimulationTimeManager(); restored_clock.reset(START)
    restored.register_time_manager(restored_clock)
    restore_farm_checkpoint_state(farm_world=restored, weather_app=None, checkpoint_state=payload)
    before = scenario_events_snapshot(restored)
    install_scenario_events(scene(restored), [declaration])
    assert scenario_events_snapshot(restored) == before == scenario_events_snapshot(value)
    for offset in range(5):
        day = DAY + timedelta(days=offset)
        assert _generate_weather_day(restored.physics.weather_generator, day) == _generate_weather_day(value.physics.weather_generator, day)


def test_static_formal_flow_and_fresh_replay_use_the_same_declared_window_and_calendar():
    from fairy.apps.system import SystemApp
    from fairy.controllers.engine import Engine
    from fairy.scenarios.scenario import Scenario
    from fairy.types import EventRegisterer

    class WindowScenario(Scenario):
        start_time = START
        duration = 10 * 86400

        def init_and_populate_apps(self):
            self.world, self.station, self.system = farm(), WeatherApp(), SystemApp()
            self.world.attach_weather_app(self.station)
            self.apps = [self.world, self.station, self.system]

        def build_events_flow(self):
            install_scenario_events(self, [
                WeatherWindowEvent("closed", "east", DAY, DAY+timedelta(days=2), rain_mm=8., wind_ms=7.),
                WeatherWindowEvent("open", "east", DAY+timedelta(days=2), DAY+timedelta(days=4), rain_mm=0., wind_ms=2.),
            ])
            with EventRegisterer.capture_mode() as events:
                self.system.advance_time(days=2).oracle().with_id("wait_open")
                self.station.get_current_weather().oracle().with_id("observe_open")
            self.events = events

    first = WindowScenario()
    engine = Engine(None, first)
    workflow = engine.build_oracle_workflow(run_oracle=True)
    assert workflow.dag["observe_open"].content["rainfall_mm"] == 0.
    assert workflow.dag["observe_open"].content["wind_speed_ms"] == 2.
    second = WindowScenario()
    fresh = Engine(None, second)
    replay = fresh.replay_workflow(workflow)
    assert replay.dag["observe_open"].content == workflow.dag["observe_open"].content
    assert engine.time_manager.time() == fresh.time_manager.time()
    assert scenario_events_snapshot(second.world) == scenario_events_snapshot(first.world)
