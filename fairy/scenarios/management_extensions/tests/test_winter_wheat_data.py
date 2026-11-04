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
