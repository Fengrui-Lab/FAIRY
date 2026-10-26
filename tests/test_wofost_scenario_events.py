"""Formal disturbances share the ordinary physics path and checkpoint ledger."""
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from fairy.apps.farm_world import FarmWorldApp, WeatherApp
from fairy.physics.weather_engine import WeatherGenerator, WeatherGeneratorConfig, MonthlyClimate
from fairy.scenarios.wofost_events import (
    DroughtEvent, PressureEvent, apply_scenario_events_for_day,
    install_scenario_events, scenario_events_snapshot,
)


START = datetime(2026, 6, 1, 7, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()


def farm(farm_id="east"):
    value = FarmWorldApp(name="Farm_" + farm_id, farm_id=farm_id, num_ridges=4)
    value.simulation_timezone = ZoneInfo("Asia/Shanghai")
    value._sim_date = "2026-06-01"
    value.physics.engines_active = True
    value.physics.weather_generator = WeatherGenerator(WeatherGeneratorConfig(monthly={
        month: MonthlyClimate(20, 40, .4, 20) for month in range(1, 13)}), seed=11)
    for day in range(1, 8):
        value.physics.weather_generator.set_day_override(date(2026, 6, day), 21, 12, 2, 18,
            air_temp_min_c=15, air_temp_max_c=27, relative_humidity_pct=70)
    return value


def scene(*farms):
    return SimpleNamespace(apps=list(farms), start_time=START)


def pressure(**kwargs):
    return PressureEvent("disease", "east", 1, 2, date(2026, 6, 2), date(2026, 6, 4),
                         "disease", .4, **kwargs)


def test_drought_only_changes_pinned_rain_and_target_farm_with_exclusive_stop():
    east, west = farm(), farm("west")
    before = {day: asdict(value) for day, value in east.physics.weather_generator._day_overrides.items()}
    install_scenario_events(scene(east, west), [DroughtEvent("dry", "east", date(2026, 6, 2), date(2026, 6, 4), .25)])
    for day, old in before.items():
        actual = asdict(east.physics.weather_generator.generate(day, day)[0])
        assert actual["rain_mm"] == (3 if day.day in {2, 3} else 12)
        for key in old.keys() - {"rain_mm", "is_raining", "weather_tags"}:
            assert actual[key] == old[key]
        assert west.physics.weather_generator.generate(day, day)[0].rain_mm == 12


def test_install_refreshes_public_startup_weather_and_forecast_after_drought_pins_change():
    from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs

    value, station = farm(), WeatherApp()
    value.attach_weather_app(station)
    _build_weather_inputs(station, date(2026, 6, 1), physics=value.physics, advance_weather=False)
    assert station.get_current_weather()["rainfall_mm"] == 12
    assert station.get_forecast()["forecast"][0]["rainfall_mm"] == 12
    install_scenario_events(scene(value), [DroughtEvent("initial_dry", "east", date(2026, 6, 1), date(2026, 6, 4))])
    assert station.get_current_weather()["rainfall_mm"] == 0
    forecast = {row["date"]: row for row in station.get_forecast()["forecast"]}
    assert forecast["2026-06-02"]["rainfall_mm"] == 0
    assert forecast["2026-06-03"]["rainfall_mm"] == 0
    assert forecast["2026-06-04"]["rainfall_mm"] == 12


def test_once_add_is_local_idempotent_and_does_not_clear_at_stop():
    east, west = farm(), farm("west")
    baseline = east.physics.biotic.states[1].disease_pressure
    install_scenario_events(scene(east, west), [pressure()])
    assert apply_scenario_events_for_day(east, date(2026, 6, 1)) == []
    assert len(apply_scenario_events_for_day(east, date(2026, 6, 2))) == 1
    expected = baseline + .4
    assert east.physics.biotic.states[1].disease_pressure == pytest.approx(expected)
    assert east.physics.biotic.states[0].disease_pressure == baseline
    assert west.physics.biotic.states[1].disease_pressure == baseline
    assert apply_scenario_events_for_day(east, date(2026, 6, 2)) == []
    assert apply_scenario_events_for_day(east, date(2026, 6, 3)) == []
    assert apply_scenario_events_for_day(east, date(2026, 6, 4)) == []
    assert east.physics.biotic.states[1].disease_pressure == pytest.approx(expected)


def test_daily_set_warns_that_it_reimposes_pressure_but_stopping_does_not_clear_it():
    value = farm()
    install_scenario_events(scene(value), [pressure(mode="set", repeat="daily")])
    assert "overwrite management" in scenario_events_snapshot(value)["warnings"][0]
    apply_scenario_events_for_day(value, date(2026, 6, 2))
    value.physics.biotic.set_pressure([1, 2], disease_pressure=.1)
    apply_scenario_events_for_day(value, date(2026, 6, 3))
    assert value.physics.biotic.states[1].disease_pressure == .4
    apply_scenario_events_for_day(value, date(2026, 6, 4))
    assert value.physics.biotic.states[1].disease_pressure == .4


def test_reinstall_and_json_restored_ledger_do_not_reapply_an_increment():
    original = farm()
    declaration = pressure(repeat="daily")
    install_scenario_events(scene(original), [declaration])
    apply_scenario_events_for_day(original, date(2026, 6, 2))
    after = original.physics.biotic.states[1].disease_pressure
    saved = json.loads(json.dumps(scenario_events_snapshot(original), allow_nan=False))
    restored = farm()
    restored.physics.scenario_metadata = {"wofost_scenario_events": saved}
    restored.physics.biotic.set_pressure([1, 2], disease_pressure=after)
    install_scenario_events(scene(restored), [declaration])
    assert apply_scenario_events_for_day(restored, date(2026, 6, 2)) == []
    assert restored.physics.biotic.states[1].disease_pressure == after
    apply_scenario_events_for_day(restored, date(2026, 6, 3))
    assert restored.physics.biotic.states[1].disease_pressure == pytest.approx(min(1, after + .4))


def test_initial_day_once_event_survives_normal_physics_initialization():
    value = farm()
    declaration = PressureEvent("initial", "east", 0, 0, date(2026, 6, 1), date(2026, 6, 2), "insect", .7, mode="set")
    install_scenario_events(scene(value), [declaration])
    value.advance_physics_time(START)
    assert value.physics.biotic.states[0].insect_pressure == .7
    assert scenario_events_snapshot(value)["applied_pressure_days"] == {"initial": ["2026-06-01"]}


def test_event_checkpoint_cannot_inject_into_another_farm():
    east, west = farm(), farm("west")
    install_scenario_events(scene(east), [pressure()])
    west.physics.scenario_metadata = {"wofost_scenario_events": scenario_events_snapshot(east)}
    before = deepcopy(west.physics.biotic.get_state())
    with pytest.raises(ValueError, match="does not belong"):
        apply_scenario_events_for_day(west, date(2026, 6, 2))
    assert west.physics.biotic.get_state() == before


@pytest.mark.parametrize("bad", ["unknown_farm", "range", "unfixed_rain", "overlap", "duplicate_id"])
def test_invalid_plans_reject_before_mutating_any_farm(bad):
    value = farm();generator = value.physics.weather_generator
    declarations = [pressure()]
    if bad == "unknown_farm": declarations = [PressureEvent("x", "missing", 0, 0, date(2026, 6, 2), date(2026, 6, 3), "weed", .2)]
    if bad == "range": declarations = [PressureEvent("x", "east", 0, 9, date(2026, 6, 2), date(2026, 6, 3), "weed", .2)]
    if bad == "unfixed_rain": declarations = [DroughtEvent("dry", "east", date(2026, 6, 8), date(2026, 6, 9))]
    if bad == "overlap": declarations = [DroughtEvent("a", "east", date(2026, 6, 2), date(2026, 6, 4)), DroughtEvent("b", "east", date(2026, 6, 3), date(2026, 6, 5))]
    if bad == "duplicate_id": declarations = [pressure(), pressure()]
    before = deepcopy(generator._day_overrides)
    with pytest.raises(ValueError): install_scenario_events(scene(value), declarations)
    assert generator._day_overrides == before
    assert scenario_events_snapshot(value) == {}


def test_no_events_do_not_mutate_historical_scene_or_physics_metadata():
    value = farm()
    before = deepcopy(getattr(value.physics, "scenario_metadata", {}))
    biotic_before = deepcopy(value.physics.biotic.get_state())
    assert install_scenario_events(scene(value), []) == {}
    assert apply_scenario_events_for_day(value, date(2026, 6, 2)) == []
    assert getattr(value.physics, "scenario_metadata", {}) == before
    assert value.physics.biotic.get_state() == biotic_before


def test_pressure_is_visible_to_native_backend_before_its_daily_growth_call():
    value = farm()
    install_scenario_events(scene(value), [pressure(mode="set")])
    seen = []
    value.physics.crop_backend = SimpleNamespace(advance_day=lambda **kwargs:
        seen.append((kwargs["day"], kwargs["physics"].biotic.states[1].disease_pressure)))
    value.sync_initial_physics_state(START)
    value.advance_physics_time(START + 86400)
    assert seen == [(date(2026, 6, 2), .4)]


def test_full_checkpoint_codec_preserves_event_ledger_and_future_drought_forcing():
    from fairy.scenarios.farm_world_fullseason_v2.farm_checkpoint_state import (
        export_farm_checkpoint_state, restore_farm_checkpoint_state,
    )
    from fairy.apps.farm_world.physics_orchestrator import _generate_weather_day
    from fairy.time_manager import SimulationTimeManager

    value = farm()
    clock = SimulationTimeManager();clock.reset(START)
    value.register_time_manager(clock)
    declarations = [pressure(repeat="daily"), DroughtEvent("dry", "east", date(2026, 6, 3), date(2026, 6, 5))]
    install_scenario_events(scene(value), declarations)
    value.advance_physics_time(START)
    clock.add_offset(86400);value.advance_physics_time(clock.time())
    payload = json.loads(json.dumps(export_farm_checkpoint_state(farm_world=value, weather_app=None,
        scenario_id="event_codec", checkpoint_label="after_first_injection"), allow_nan=False))
    restored = farm()
    restored_clock = SimulationTimeManager();restored_clock.reset(clock.time())
    restored.register_time_manager(restored_clock)
    restore_farm_checkpoint_state(farm_world=restored, weather_app=None, checkpoint_state=payload)
    install_scenario_events(scene(restored), declarations)
    assert scenario_events_snapshot(restored) == scenario_events_snapshot(value)
    assert apply_scenario_events_for_day(restored, date(2026, 6, 2)) == []
    assert _generate_weather_day(restored.physics.weather_generator, date(2026, 6, 3)).rain_mm == 0
    clock.add_offset(86400);value.advance_physics_time(clock.time())
    restored_clock.add_offset(86400);restored.advance_physics_time(restored_clock.time())
    assert scenario_events_snapshot(restored) == scenario_events_snapshot(value)
    assert restored.physics.biotic.get_state() == value.physics.biotic.get_state()


def test_formal_build_flow_long_jump_and_fresh_replay_share_daily_hook():
    from fairy.apps.system import SystemApp
    from fairy.controllers.engine import Engine
    from fairy.scenarios.scenario import Scenario
    from fairy.types import EventRegisterer

    class DeclaredScenario(Scenario):
        start_time = START
        duration = 10 * 86400

        def init_and_populate_apps(self):
            self.world = farm()
            self.station = WeatherApp()
            self.world.attach_weather_app(self.station)
            self.system = SystemApp()
            self.apps = [self.world, self.station, self.system]

        def build_events_flow(self):
            install_scenario_events(self, [pressure(repeat="daily")])
            with EventRegisterer.capture_mode() as events:
                self.system.advance_time(days=4).oracle().with_id("long_jump")
            self.events = events

    first = DeclaredScenario()
    engine = Engine(agent=None, scenario=first)
    workflow = engine.build_oracle_workflow(run_oracle=True)
    state = scenario_events_snapshot(first.world)
    assert state["applied_pressure_days"]["disease"] == ["2026-06-02", "2026-06-03"]
    assert [r["day"] for r in state["pressure_journal"]] == ["2026-06-02", "2026-06-03"]
    second = DeclaredScenario()
    fresh = Engine(agent=None, scenario=second)
    replay = fresh.replay_workflow(workflow)
    assert scenario_events_snapshot(second.world) == state
    assert second.world.physics.biotic.get_state() == first.world.physics.biotic.get_state()
    assert replay.dag["long_jump"].content == workflow.dag["long_jump"].content
