"""Pinned real forcing and honest import of the published summary workbooks."""

import json
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from fairy.scenarios.management_extensions.engines.winter_wheat_inputs import (
    WeatherSeries,
)
from fairy.scenarios.management_extensions.engines.winter_wheat_wofost import (
    InputBundle,
)
from fairy.scenarios.management_extensions.evaluation.winter_wheat_observations import (
    import_published_summaries,
    compare,
)
from fairy.scenarios.management_extensions.winter_wheat_data import power_rows

INPUTS = Path(__file__).resolve().parents[1] / "data/winter_wheat_ncp_2019_2020"


def test_actual_forcing_has_all_winter_and_leap_days_and_correct_radiation_units():
    bundle = InputBundle(INPUTS)
    payload = json.loads((INPUTS / "power_raw.json").read_text())
    rows = power_rows(payload)
    assert len(rows) == 290
    assert date(2020, 2, 29) in bundle.weather.rows
    assert {row.day: row.as_dict() for row in rows} == {
        day: row.as_dict() for day, row in bundle.weather.rows.items()
    }
    missing = [r for r in rows if r.day != date(2020, 2, 29)]
    with pytest.raises(ValueError, match="Missing daily weather"):
        WeatherSeries(missing).require(date(2020, 2, 28), date(2020, 3, 1))


def test_real_summary_headers_are_imported_without_inventing_years_or_dates():
    result = import_published_summaries(INPUTS / "observations")
    assert Counter(r["split"] for r in result["records"]) == {
        "calibration": 75,
        "validation": 75,
        "overall": 37,
    }
    counties = [r for r in result["records"] if r["entity_type"] == "county"]
    assert len(counties) == 150 and all(r["harvest_year"] is None for r in counties)
    phenology = [r for r in counties if r["metric"].endswith("_day_statistic")]
    assert len(phenology) == 100
    assert any(not r["value_days"].is_integer() for r in phenology)
    assert all(r["calendar_date"] is None for r in phenology)
    assert all(r["native_comparable"] is False for r in result["records"])
    assert not any(
        r.get("source_column", "").startswith("WOFOST") for r in result["records"]
    )
    assert result == json.loads(
        (INPUTS / "observations/published_summaries.json").read_text()
    )


def test_published_county_summaries_cannot_generate_fake_field_validation_accuracy():
    obs = import_published_summaries(INPUTS / "observations")
    predictions = {
        "schema": "fairy.winter_wheat.predictions.v1",
        "records": [],
        "input_fingerprint": "example",
        "spatial_matching_evidence": "No annual county mapping supplied",
    }
    with pytest.raises(ValueError, match="No scientifically comparable"):
        compare(obs, predictions)
    with pytest.raises(ValueError, match="not an independent"):
        compare(obs, predictions, split="overall")
