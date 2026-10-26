"""Rain-event totals must survive the daily query path used by the farm."""

from copy import deepcopy
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
    with pytest.raises(ValueError, match="requires total_rain_mm"):
        generator().generate(START, START, [event(total=None)])
