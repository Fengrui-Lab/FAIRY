"""Rain-event totals must survive the daily query path used by the farm."""

from copy import deepcopy
from dataclasses import asdict
from datetime import date, timedelta
from decimal import Decimal
import json

import pytest

from fairy.apps.farm_world.physics_orchestrator import (
    _build_generated_forecast,
    _generate_weather_day,
)
from fairy.physics.weather_engine import (
    MonthlyClimate,
    WeatherEvent,
    WeatherGenerator,
    WeatherGeneratorConfig,
)
from fairy.scenarios.farm_world_fullseason_v2.farm_checkpoint_state import (
    _export_weather_generator,
    _restore_weather_generator,
)


START = date(2026, 6, 1)


def generator(*, seed=17, background_rain=0):
    return WeatherGenerator(
        WeatherGeneratorConfig(monthly={
            month: MonthlyClimate(20, background_rain, .5, 20)
            for month in range(1, 13)
        }),
        seed=seed,
    )


def event(*, total=72, days=6, start=START):
    return WeatherEvent("rain_event", start, days, total_rain_mm=total)


def as_cents(value):
    return int(Decimal(str(value)) * 100)


@pytest.mark.parametrize("total,days", [
    (0, 6), (.01, 17), (.03, 40), (13.37, 7), (72, 6), (84.321, 5),
])
def test_complete_rain_event_preserves_total_to_one_hundredth_mm(total, days):
    trace = generator().generate(START, START + timedelta(days=days - 1),
                                 [event(total=total, days=days)])
    assert all(day.rain_mm >= 0 for day in trace)
    assert sum(as_cents(day.rain_mm) for day in trace) == as_cents(round(total, 2))


def test_daily_and_partial_queries_select_the_complete_event_allocation():
    expected = generator().generate(START, START + timedelta(days=5), [event()])
    # Different background RNG histories and query orders cannot repartition
    # the rain event. A paired control isolates event rain from background rain.
    for order in [range(6), reversed(range(6))]:
        queried = generator(background_rain=90)
        queried.generate(START - timedelta(days=11), START - timedelta(days=2))
        for offset in order:
            day = START + timedelta(days=offset)
            control = deepcopy(queried)
            rainy = queried.generate(day, day, [event()])[0]
            background = control.generate(day, day)[0]
            assert round(rainy.rain_mm - background.rain_mm, 2) == expected[offset].rain_mm
            assert queried.rng.bit_generator.state == control.rng.bit_generator.state
    partial = generator().generate(START + timedelta(days=2),
                                    START + timedelta(days=4), [event()])
    assert [day.rain_mm for day in partial] == [day.rain_mm for day in expected[2:5]]


def test_forecast_repeated_read_and_checkpoint_do_not_repeat_total_rain():
    storm = event(total=72, days=12)
    expected = generator().generate(START, START + timedelta(days=11), [storm])
    queried = generator()
    forecast = _build_generated_forecast(queried, START, [storm], days=7)
    first = _generate_weather_day(queried, START, [storm])
    assert _generate_weather_day(queried, START, [storm]) == first
    saved = json.loads(json.dumps(_export_weather_generator(queried), allow_nan=False))
    restored = generator(seed=999)
    _restore_weather_generator(restored, saved)
    rain = [first.rain_mm]
    for offset in range(1, 12):
        day = START + timedelta(days=offset)
        actual = _generate_weather_day(restored, day, [storm])
        assert _generate_weather_day(restored, day, [storm]) == actual
        assert actual.rain_mm == expected[offset].rain_mm
        assert _generate_weather_day(queried, day, [storm]) == actual
        rain.append(actual.rain_mm)
    assert [row["rainfall_mm"] for row in forecast] == [day.rain_mm for day in expected[1:8]]
    assert sum(as_cents(value) for value in rain) == 7200


def test_overlapping_rain_events_add_their_own_conserved_totals():
    storms = [event(total=13.37), event(total=7.01, days=3, start=START + timedelta(days=2))]
    gen = generator()
    trace = [_generate_weather_day(gen, START + timedelta(days=i), storms) for i in range(6)]
    assert sum(as_cents(day.rain_mm) for day in trace) == 2038


@pytest.mark.parametrize("total", [0, 13.37, 72.005])
def test_one_day_event_retains_existing_rounded_amount(total):
    value = generator().generate(START, START, [event(total=total, days=1)])[0]
    assert value.rain_mm == round(total, 2)


@pytest.mark.parametrize("total", [-.01, float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("query_offset", [0, 20])
def test_invalid_rain_amount_is_rejected_even_outside_query_window(total, query_offset):
    day = START + timedelta(days=query_offset)
    with pytest.raises(ValueError, match="finite and nonnegative"):
        generator().generate(day, day, [event(total=total)])


def test_missing_total_is_rejected():
    with pytest.raises(ValueError, match="requires rain_mm or total_rain_mm"):
        generator().generate(START, START, [event(total=None)])


def test_rain_mm_preserves_main_window_allocation_and_random_stream():
    def legacy_generator():
        return WeatherGenerator(WeatherGeneratorConfig(monthly={
            6: MonthlyClimate(20, 0, 0, 20),
        }), seed=17)

    storm = WeatherEvent("rain_event", START, 3, rain_mm=30)
    daily = legacy_generator()
    assert [daily.generate(START + timedelta(days=i), START + timedelta(days=i),
                           [storm])[0].rain_mm for i in range(3)] == [30, 30, 30]
    window = legacy_generator()
    # Captured from main before the field migration, including the next RNG
    # value. Keeping only the rain sum would miss changes to later weather.
    assert [day.rain_mm for day in window.generate(
        START, START + timedelta(days=2), [storm]
    )] == [4.31, 14.49, 11.2]
    assert window.rng.random() == 0.4619579095338642


def test_amount_fields_are_exclusive_and_historical_positional_slot_is_preserved():
    storm = WeatherEvent("rain_event", START, 3, 30)
    assert storm.rain_mm == 30 and storm.total_rain_mm is None
    with pytest.raises(ValueError, match="only one"):
        WeatherEvent("rain_event", START, 3, rain_mm=30, total_rain_mm=30)


def test_historical_event_snapshot_restores_legacy_semantics():
    restored = WeatherEvent.from_state({
        "event_type": "rain_event", "start_date": START.isoformat(),
        "duration_days": 3, "total_rain_mm": 30,
    })
    assert restored.rain_mm == 30 and restored.total_rain_mm is None
    assert generator().generate(START, START, [restored])[0].rain_mm == 30


@pytest.mark.parametrize("storm", [
    WeatherEvent("rain_event", START, 3, rain_mm=30),
    WeatherEvent("rain_event", START, 3, total_rain_mm=30),
])
def test_current_event_snapshot_roundtrip_preserves_selected_amount_field(storm):
    saved = json.loads(json.dumps(asdict(storm), default=str))
    restored = WeatherEvent.from_state(saved)
    assert restored == storm
    assert generator().generate(START, START, [restored]) == generator().generate(
        START, START, [storm]
    )


@pytest.mark.parametrize("scene_id", [
    "scenario_two_farm_full_season_hn84_normal",
    "scenario_three_farm_full_season_hn84_normal",
])
def test_new_shared_scenes_use_total_profile_without_changing_old_single_farm(scene_id):
    from fairy.physics.profiles import get_profile
    from fairy.scenarios.registry import get_scenario_class

    legacy = get_profile("harbin_hb_base_hn84_std_normal_seed_1101")
    before = deepcopy(legacy)
    scenario = get_scenario_class(scene_id)()
    scenario.setup()
    for context in scenario.farm_environment.farms.values():
        profile = context.world.physics.profile
        assert profile is not legacy
        assert profile.name == "harbin_hb_base_hn84_std_normal_total_rain_seed_1101"
        assert [e.rain_mm for e in profile.weather_events] == [None, None]
        assert [e.total_rain_mm for e in profile.weather_events] == [42, 30]

    assert get_profile(legacy.name) == before
    assert [e.rain_mm for e in legacy.weather_events] == [42, 30]
    assert [e.total_rain_mm for e in legacy.weather_events] == [None, None]
    for profile, expected_cents in [(legacy, 18600), (profile, 7200)]:
        queried = WeatherGenerator(profile.to_weather_generator_config(), seed=profile.rng_seed)
        control = deepcopy(queried)
        injected = 0
        for offset in range(18):
            day = date(2026, 8, 2) + timedelta(days=offset)
            actual = queried.generate(day, day, profile.weather_events)[0]
            background = control.generate(day, day)[0]
            injected += round(100 * (actual.rain_mm - background.rain_mm))
        assert injected == expected_cents


@pytest.mark.parametrize("codec", ["crop_snapshot", "historical_embedded_profile"])
@pytest.mark.parametrize("encoding", ["historical", "rain_mm", "total_rain_mm"])
def test_checkpoint_codecs_preserve_rain_amount_semantics(codec, encoding):
    from fairy.apps.farm_world import FarmWorldApp
    from fairy.apps.farm_world.crop_snapshot import restore_physics, snapshot_physics
    from fairy.scenarios.farm_world_fullseason_v2.farm_checkpoint_state import (
        _restore_embedded_weather,
    )

    source = FarmWorldApp(num_ridges=1)
    source.configure_physics_profile("harbin_hb_base_hn84_std_normal_seed_1101")
    source.physics.profile = deepcopy(source.physics.profile)
    field = "total_rain_mm" if encoding == "total_rain_mm" else "rain_mm"
    source.physics.profile.weather_events = [WeatherEvent("rain_event", START, 3, **{field: 30})]
    snapshot = json.loads(json.dumps(snapshot_physics(source.physics)))
    if encoding == "historical":
        saved_event = snapshot["profile"]["weather_events"][0]
        saved_event["total_rain_mm"] = saved_event.pop("rain_mm")
    if codec == "crop_snapshot":
        restored = restore_physics(snapshot, num_ridges=1)
    else:
        restored = deepcopy(source.physics)
        _restore_embedded_weather(restored, {"physics_profile": snapshot["profile"]})
    storm = restored.profile.weather_events[0]
    assert storm.rain_mm == (None if field == "total_rain_mm" else 30)
    assert storm.total_rain_mm == (30 if field == "total_rain_mm" else None)
    rain = [generator().generate(START + timedelta(days=i), START + timedelta(days=i),
                                 [storm])[0].rain_mm for i in range(3)]
    assert round(sum(rain), 2) == (30 if field == "total_rain_mm" else 90)
