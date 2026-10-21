"""Input contracts and a native rainfed response, without the FAIRY adapter."""
from __future__ import annotations

import ast
import copy
import csv
from datetime import date, timedelta
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_wofost_standalone.py"
SPEC = importlib.util.spec_from_file_location("standalone_wofost", SCRIPT)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def _config(tmp_path: Path, **changes):
    config = {
        "crop_parameters": {"AMAXTB": [0, 29, 2, 0]},
        "soil_parameters": {"SMW": 0.11},
        "site_parameters": {"WAV": 10},
        "location": {"latitude": 47.43, "longitude": 126.8, "elevation": 240},
        "reference_et": {"angsta": 0.25, "angstb": 0.5},
        "sowing_date": "2020-05-10", "year": 2020, "max_duration": 2,
        **changes,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _weather(tmp_path: Path, days=3, rain=0.6, omit=(), name="weather.csv"):
    path = tmp_path / name
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["DAY", *runner.WEATHER_UNITS])
        writer.writeheader()
        for index in range(days):
            if index in omit:
                continue
            writer.writerow({
                "DAY": date(2020, 5, 10) + timedelta(days=index),
                "IRRAD": 18_000_000 + index % 5 * 400_000,
                "TMIN": 13 + index % 7, "TMAX": 25 + index % 5,
                "VAP": 13.0, "WIND": 2.0, "RAIN": rain,
            })
    return path


def test_standalone_never_imports_fairy():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(alias.name.split(".")[0] == "fairy" for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "fairy"


@pytest.mark.parametrize("changes,match", [
    ({"year": 2021}, "year must match"),
    ({"max_duration": 2.5}, "positive integer"),
    ({"max_duration": True}, "positive integer"),
    ({"reference_et": {"angsta": 0.25}}, "angstb"),
    ({"weather_units": {"RAIN": "mm/day"}}, "native PCSE units"),
    ({"crop_parameters": {"AMAX_REF": 29}}, "requires AMAXTB"),
    ({"model": "Wofost81_NWLP_CWB_CNB"}, "model must be Wofost72"),
])
def test_rejects_ambiguous_experiment_inputs(tmp_path, changes, match):
    with pytest.raises(ValueError, match=match):
        runner.load_config(_config(tmp_path, **changes))


def test_external_crop_file_is_relative_to_config(tmp_path):
    crop_path = tmp_path / "crop.json"
    crop_path.write_text('{"AMAXTB": [0, 29, 2, 0]}', encoding="utf-8")
    path = _config(tmp_path)
    raw = json.loads(path.read_text())
    del raw["crop_parameters"]
    raw["crop_parameter_file"] = "crop.json"
    path.write_text(json.dumps(raw))
    config = runner.load_config(path)
    assert config["crop_parameters"]["AMAXTB"] == [0, 29, 2, 0]
    assert config["resolved_crop_parameter_file"] == str(crop_path)


@pytest.mark.parametrize("model", ["Wofost72_WLP_CWB", "Wofost72_WLP_FD"])
def test_accepts_only_documented_native_72_model_aliases(tmp_path, model):
    assert runner.load_config(_config(tmp_path, model=model))["model"] == model


def test_weather_gap_is_rejected_before_starting_model(tmp_path):
    config = runner.load_config(_config(tmp_path))
    with pytest.raises(ValueError, match="first missing date: 2020-05-11"):
        runner.read_weather(_weather(tmp_path, omit=(1,)), config)


def test_duplicate_weather_date_is_rejected(tmp_path):
    config = runner.load_config(_config(tmp_path))
    path = _weather(tmp_path)
    lines = path.read_text().splitlines()
    path.write_text("\n".join([*lines, lines[1]]) + "\n")
    with pytest.raises(ValueError, match="duplicate date"):
        runner.read_weather(path, config)


def test_weather_nan_is_rejected(tmp_path):
    config = runner.load_config(_config(tmp_path))
    path = _weather(tmp_path)
    path.write_text(path.read_text().replace("18000000", "nan", 1))
    with pytest.raises(ValueError, match="IRRAD must be a finite number"):
        runner.read_weather(path, config)


def test_native_evaporation_is_converted_from_mm_to_cm_once(tmp_path):
    pytest.importorskip("pcse")
    from pcse.util import reference_ET

    config = runner.load_config(_config(tmp_path))
    rows = runner.read_weather(_weather(tmp_path), config)
    provider = runner.make_weather_provider(rows, config)
    row = rows[0]
    expected = reference_ET(
        DAY=row["DAY"], LAT=47.43, ELEV=240, TMIN=row["TMIN"], TMAX=row["TMAX"],
        IRRAD=row["IRRAD"], VAP=row["VAP"], WIND=row["WIND"], ANGSTA=0.25, ANGSTB=0.5,
    )
    weather = provider(row["DAY"])
    assert [weather.E0, weather.ES0, weather.ET0] == pytest.approx([x / 10 for x in expected])
    assert weather.RAIN == 0.6  # Native input is already centimetres.
    assert weather.IRRAD == 18_000_000


def test_native_rainfall_response_and_reproducible_artifacts(tmp_path):
    """Synthetic forcing checks plumbing and water stress, not local calibration."""
    pytest.importorskip("pcse")
    research_config = ROOT / "configs" / "wofost" / "standalone_xu2026_hailun.json"
    config = copy.deepcopy(runner.load_config(research_config))
    config.pop("crop_parameter_file", None)
    config.pop("resolved_crop_parameter_file", None)
    config.update(sowing_date="2020-05-10", year=2020, max_duration=200)
    config["site_parameters"]["WAV"] = 5.0
    path = tmp_path / "native.json"
    path.write_text(json.dumps(config, default=str))
    wet_weather = _weather(tmp_path, days=201, rain=0.6, name="wet.csv")
    dry_weather = _weather(tmp_path, days=201, rain=0, name="dry.csv")
    wet_dir, dry_dir = tmp_path / "wet", tmp_path / "dry"
    wet = runner.run(path, wet_weather, wet_dir)
    dry = runner.run(path, dry_weather, dry_dir)
    assert wet["model"] in {"Wofost72_WLP_CWB", "Wofost72_WLP_FD"}
    assert wet["native_configuration"]["soil_component"] == "pcse.soil.classic_waterbalance.WaterbalanceFD"
    assert wet["matured"] is True
    assert wet["storage_organ_dry_matter_kg_ha"] > dry["storage_organ_dry_matter_kg_ha"]
    assert wet["mean_growing_season_rftra"] > dry["mean_growing_season_rftra"]
    assert wet["equivalent_13pct_moisture_kg_mu_before_losses"] == pytest.approx(
        wet["storage_organ_dry_matter_kg_ha"] / 0.87 / 15
    )
    provenance = json.loads((wet_dir / "provenance.json").read_text())
    assert provenance["input_files"]["weather"]["sha256"] == runner._sha256(wet_weather)
    assert provenance["resolved_inputs_sha256"] == runner._sha256(wet_dir / "resolved_inputs.json")
    daily = list(csv.DictReader((wet_dir / "daily.csv").open()))
    assert len(daily) == wet["daily_row_count"]
    assert {"LAI", "RFTRA", "RD", "SM", "TWSO"}.issubset(daily[0])
    assert json.loads((wet_dir / "summary.json").read_text())["native_crop_summary"]["DOM"]


def test_max_duration_biomass_is_not_reported_as_mature_market_yield(tmp_path):
    """A real native cutoff keeps measured biomass but cannot imply mature yield."""
    pytest.importorskip("pcse")
    research_config = ROOT / "configs" / "wofost" / "standalone_xu2026_hailun.json"
    config = copy.deepcopy(runner.load_config(research_config))
    config.pop("crop_parameter_file", None)
    config.pop("resolved_crop_parameter_file", None)
    config.update(sowing_date="2020-05-10", year=2020, max_duration=20)
    path = tmp_path / "cutoff.json"
    path.write_text(json.dumps(config, default=str))
    weather = _weather(tmp_path, days=21)
    summary = runner.run(path, weather, tmp_path / "cutoff")
    assert summary["matured"] is False
    assert summary["native_crop_summary"]["DOM"] is None
    assert summary["storage_organ_dry_matter_kg_ha"] is not None
    assert summary["storage_organ_dry_matter_kg_ha"] >= 0
    assert summary["dry_matter_kg_mu"] is not None
    assert summary["equivalent_13pct_moisture_kg_mu_before_losses"] is None
    assert "immature biomass" in summary["interpretation"]["yield"]
