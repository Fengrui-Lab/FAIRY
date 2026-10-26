"""Audit fixed public-weather inputs without executing or calibrating WOFOST."""
from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import yaml


BUNDLE = (
    Path(__file__).resolve().parents[1]
    / "fairy/physics/data/wofost/research/official_soybean_nasa2019_v1"
)
MANIFEST = json.loads((BUNDLE / "manifest.json").read_text())
ROWS = MANIFEST["rows"]
EXPECTED = {
    "lille": ("Soybean_901", 50.63, 3.06, "2019-04-28"),
    "clermont_ferrand": ("Soybean_902", 45.78, 3.08, "2019-04-28"),
    "valladolid": ("Soybean_903", 41.65, -4.72, "2019-04-30"),
    "bologna": ("Soybean_905", 44.49, 11.34, "2019-04-30"),
}
FIELD_UNITS = {
    "T2M_MIN": ("tmin_c", "C"),
    "T2M_MAX": ("tmax_c", "C"),
    "RH2M": ("relative_humidity_pct", "%"),
    "WS2M": ("wind_2m_m_s", "m/s"),
    "PRECTOTCORR": ("rain_mm", "mm/day"),
    "ALLSKY_SFC_SW_DWN": ("shortwave_mj_m2_day", "MJ/m^2/day"),
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _data(row: dict) -> tuple[dict, dict]:
    return (
        json.loads((BUNDLE / row["source_path"]).read_bytes()),
        json.loads((BUNDLE / row["weather_path"]).read_bytes()),
    )


def test_bundle_states_model_reference_and_preserves_official_crop_identity() -> None:
    assert MANIFEST["reference_kind"] == (
        "reproducible_official_model_reference_not_field_trial_replication"
    )
    assert {row["id"] for row in ROWS} == set(EXPECTED)
    assert len(ROWS) == len(EXPECTED)
    assert MANIFEST["soil_and_initial_nitrogen"]["field_observed"] is False
    crop_path = BUNDLE / MANIFEST["crop_source"]["path"]
    assert _sha(crop_path.read_bytes()) == MANIFEST["crop_source"]["sha256"]
    varieties = yaml.safe_load(crop_path.read_bytes())["CropParameters"]["Varieties"]
    for row in ROWS:
        variety, latitude, longitude, sowing = EXPECTED[row["id"]]
        assert row["variety"] == variety
        assert row["location"]["latitude"] == latitude
        assert row["location"]["longitude"] == longitude
        assert row["sowing_date"] == sowing
        assert row["parameter_overrides"] == {}
        assert row["observed_yield"] is None
        assert row["field_validation_available"] is False
        native = {k: v[0] for k, v in varieties[variety].items() if k != "Metadata"}
        content = json.dumps(
            native, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode()
        assert len(native) == row["native_parameter_count"] == 78
        assert _sha(content) == row["native_parameters_sha256"]


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["id"])
def test_fixed_weather_matches_preserved_source_bytes_and_request(row: dict) -> None:
    original = (BUNDLE / row["source_path"]).read_bytes()
    normalized = (BUNDLE / row["weather_path"]).read_bytes()
    assert len(original) == row["source_bytes"]
    assert _sha(original) == row["source_sha256"]
    assert _sha(normalized) == row["weather_sha256"]
    url = urlparse(row["source_url"])
    query = parse_qs(url.query)
    assert url.scheme == "https"
    assert url.netloc == "power.larc.nasa.gov"
    assert url.path == "/api/temporal/daily/point"
    assert set(query["parameters"][0].split(",")) == set(FIELD_UNITS)
    assert query["community"] == ["AG"]
    assert query["start"] == ["20190301"]
    assert query["end"] == ["20191130"]
    assert float(query["latitude"][0]) == row["location"]["latitude"]
    assert float(query["longitude"][0]) == row["location"]["longitude"]


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["id"])
def test_daily_weather_has_complete_date_coverage_and_original_lst_labels(row: dict) -> None:
    raw, weather = _data(row)
    start, end = date(2019, 3, 1), date(2019, 11, 30)
    expected = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    assert len(expected) == len(weather["daily"]) == row["row_count"] == 275
    assert [day["date"] for day in weather["daily"]] == [d.isoformat() for d in expected]
    assert weather["time_standard"] == raw["header"]["time_standard"] == "LST"
    assert weather["start_date"] == start.isoformat()
    assert weather["end_date"] == end.isoformat()
    assert raw["header"]["start"] == "20190301"
    assert raw["header"]["end"] == "20191130"
    assert raw["geometry"]["coordinates"] == [
        row["location"]["longitude"], row["location"]["latitude"],
        row["location"]["elevation_m"],
    ]
    assert (date.fromisoformat(row["sowing_date"]) - start).days >= 14
    for name in FIELD_UNITS:
        assert set(raw["properties"]["parameter"][name]) == {
            day.strftime("%Y%m%d") for day in expected
        }


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["id"])
def test_each_value_and_unit_is_preserved_without_filling_or_weather_scaling(row: dict) -> None:
    raw, weather = _data(row)
    for source, (target, unit) in FIELD_UNITS.items():
        assert raw["parameters"][source]["units"] == unit
        assert row["source_units"][source] == unit
        assert weather["units"][target] == unit
        assert MANIFEST["weather_normalization"]["multipliers"][source] == 1
        for day in weather["daily"]:
            key = date.fromisoformat(day["date"]).strftime("%Y%m%d")
            original = raw["properties"]["parameter"][source][key]
            assert math.isfinite(original)
            assert original != raw["header"]["fill_value"]
            assert day[target] == original
    for day in weather["daily"]:
        assert day["tmin_c"] <= day["tmax_c"]
        assert 0 <= day["relative_humidity_pct"] <= 100
        assert min(day["rain_mm"], day["wind_2m_m_s"], day["shortwave_mj_m2_day"]) >= 0
