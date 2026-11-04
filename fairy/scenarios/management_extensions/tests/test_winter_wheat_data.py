"""Offline native input checks; no workbook import or observation evaluation."""

from datetime import date
import pytest
from fairy.scenarios.management_extensions.engines.winter_wheat_inputs import (
    WeatherSeries,
    validate_wheat_parameters,
    verified_file,
)
from fairy.scenarios.management_extensions.engines.winter_wheat_wofost import (
    InputBundle,
    WinterWheatBackend,
)
from fairy.scenarios.management_extensions.winter_wheat_oracles import DEFAULT_INPUTS


def test_pinned_local_inputs_cover_winter_and_leap_day():
    b = InputBundle(DEFAULT_INPUTS)
    assert len(b.weather.rows) == 290
    assert date(2020, 2, 29) in b.weather.rows
    assert "observations" not in b.manifest
    assert not (DEFAULT_INPUTS / "observations").exists()
    for key in ("crop", "weather"):
        assert verified_file(DEFAULT_INPUTS, b.manifest[key]).exists()
    rows = [r for d, r in b.weather.rows.items() if d != date(2020, 2, 29)]
    with pytest.raises(ValueError, match="Missing daily weather"):
        WeatherSeries(rows).require(date(2020, 2, 28), date(2020, 3, 1))


def test_real_official_wheat_parameters_keep_vernalization_and_photoperiod():
    b = WinterWheatBackend(InputBundle(DEFAULT_INPUTS))
    assert (
        b.parameters["IDSL"] == 2 and b.parameters["VERNSAT"] > b.parameters["VERNBASE"]
    )
    assert b.bundle.cultivar == "Winter_wheat_104"
    bad = dict(b.parameters)
    bad["IDSL"] = 0
    with pytest.raises(ValueError):
        validate_wheat_parameters(bad)


def test_late_harvest_weather_preserves_the_original_daily_inputs():
    legacy = InputBundle(DEFAULT_INPUTS)
    extended = InputBundle(DEFAULT_INPUTS, late_harvest=True)
    assert legacy.season.deadline == date(2020, 7, 15)
    assert extended.season.deadline == date(2020, 8, 30)
    assert extended.weather[date(2020, 8, 31)].day == date(2020, 8, 31)
    assert len(extended.weather.rows) == 336
    assert all(extended.weather[day] == row for day, row in legacy.weather.rows.items())
    assert extended.identity != legacy.identity
    assert verified_file(
        DEFAULT_INPUTS, extended.manifest["late_harvest"]["raw_weather"]
    )


def test_default_wheat_can_advance_and_evaluate_on_august_30():
    from fairy.scenarios.registry import get_scenario_class

    scene = get_scenario_class("scenario_l3_winter_wheat_full_season")()
    scene.setup()
    assert (
        scene.accounts.get_accounts()["operation_deadline"]
        == "2020-08-30T23:59:59+08:00"
    )
    assert scene.farm.get_field_info()["season"]["deadline"] == "2020-08-30"

    days = (date(2020, 8, 30) - scene.input_bundle.season.start).days
    assert scene.system.advance_time(days=days)["status"] == "ok"
    assert scene.farm.simulation_date() == date(2020, 8, 30)
    assert scene.weather.get_current_weather()["date"] == "2020-08-30"
    result = scene.validate()
    assert not result.success
    assert result.metadata["stored_grain_kg"] == 0
    assert "oracle_comparison" in result.metadata
