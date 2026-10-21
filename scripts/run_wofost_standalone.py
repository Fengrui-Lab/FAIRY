#!/usr/bin/env python3
"""Run native PCSE WOFOST 7.2 without importing the FAIRY world or adapter.

The JSON config supplies ``crop_parameters`` (or ``crop_parameter_file``,
relative to the config), ``soil_parameters``, ``site_parameters``,
``location`` (latitude, longitude, elevation), ``sowing_date`` (ISO date),
and ``reference_et`` (angsta, angstb, optionally et_model="PM"). Optional
``max_duration`` defaults to 200 days; ``year`` must match sowing_date.
Optional ``model`` accepts only Wofost72_WLP_CWB or its PCSE 5.5 name
Wofost72_WLP_FD; the installed version determines which native alias is used.

Weather CSV columns are DAY, IRRAD, TMIN, TMAX, VAP, WIND, RAIN, in native
PCSE units: ISO date, J/m2/day, degrees C, degrees C, hPa, m/s, cm/day.
DAY may instead be called DATE. Daily reference evaporation is calculated
by PCSE itself. No weather is interpolated, extended, or downloaded.

Example::

    python scripts/run_wofost_standalone.py --config config.json \
        --weather observed_weather.csv --output-dir validation_runs/native

Native PCSE summary dates are preserved, including the model's own maturity
date convention. TWSO is storage-organ dry matter in kg/ha, not harvested
market-moisture yield. This runner does not apply harvest/storage losses.
The 13% yield conversion is omitted when native maturity was not reached.
PCSE 5.5 calls this model Wofost72_WLP_FD; PCSE 6 calls it
Wofost72_WLP_CWB. The actual class and native crop/soil components are saved.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
from typing import Any


WEATHER_UNITS = {
    "IRRAD": "J/m2/day", "TMIN": "C", "TMAX": "C", "VAP": "hPa",
    "WIND": "m/s", "RAIN": "cm/day",
}
OUTPUT_VARIABLES = [
    "DVS", "LAI", "TAGP", "TWSO", "TWLV", "TWST", "TWRT", "TRA", "RD",
    "SM", "WWLOW", "RFTRA", "W", "EVS", "EVW",
]
SUMMARY_VARIABLES = [
    "DVS", "LAIMAX", "TAGP", "TWSO", "TWLV", "TWST", "TWRT", "CTRAT",
    "RD", "DOS", "DOE", "DOA", "DOM", "DOH", "DOV", "CEVST",
]


def _iso_date(value: Any, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be an ISO date (YYYY-MM-DD): {value!r}") from error


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a finite number") from error
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def _json_default(value: Any) -> str:
    if isinstance(value, (date, Path)):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, default=_json_default,
                   allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_config(path: str | Path) -> dict[str, Any]:
    """Resolve fully explicit native parameters and validate experiment metadata."""
    path = Path(path).resolve()
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Config must contain a JSON object")
    config.setdefault("model", "Wofost72_WLP_CWB")
    if not isinstance(config["model"], str) or config["model"] not in {"Wofost72_WLP_CWB", "Wofost72_WLP_FD"}:
        raise ValueError("model must be Wofost72_WLP_CWB or its native PCSE 5.5 alias Wofost72_WLP_FD")
    if ("crop_parameters" in config) == ("crop_parameter_file" in config):
        raise ValueError("Supply exactly one of crop_parameters or crop_parameter_file")
    if "crop_parameter_file" in config:
        crop_path = (path.parent / config["crop_parameter_file"]).resolve()
        config["crop_parameters"] = json.loads(crop_path.read_text(encoding="utf-8"))
        config["resolved_crop_parameter_file"] = str(crop_path)
    for name in ("crop_parameters", "soil_parameters", "site_parameters", "location", "reference_et"):
        if not isinstance(config.get(name), dict) or not config[name]:
            raise ValueError(f"{name} must be a non-empty JSON object")
    if "AMAXTB" not in config["crop_parameters"]:
        raise ValueError("WOFOST 7.2 requires AMAXTB; WOFOST 8.1 AMAX_REF is not a substitute")
    config["sowing_date"] = _iso_date(config.get("sowing_date"), "sowing_date")
    if "year" in config and config["year"] != config["sowing_date"].year:
        raise ValueError("year must match sowing_date")
    max_duration = config.get("max_duration", 200)
    if isinstance(max_duration, bool) or not isinstance(max_duration, int) or max_duration <= 0:
        raise ValueError("max_duration must be a positive integer")
    config["max_duration"] = max_duration
    for key in ("latitude", "longitude", "elevation"):
        config["location"][key] = _number(config["location"].get(key), f"location.{key}")
    if not -90 <= config["location"]["latitude"] <= 90:
        raise ValueError("location.latitude must lie between -90 and 90")
    if not -180 <= config["location"]["longitude"] <= 180:
        raise ValueError("location.longitude must lie between -180 and 180")
    for key in ("angsta", "angstb"):
        config["reference_et"][key] = _number(config["reference_et"].get(key), f"reference_et.{key}")
    config["reference_et"].setdefault("et_model", "PM")
    if config["reference_et"]["et_model"] not in {"PM", "P"}:
        raise ValueError("reference_et.et_model must be PM or P")
    if "weather_units" in config and config["weather_units"] != WEATHER_UNITS:
        raise ValueError(f"weather_units must match native PCSE units: {WEATHER_UNITS}")
    config["weather_units"] = dict(WEATHER_UNITS)
    config["source_config"] = str(path)
    return config


def read_weather(path: str | Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate all input values and contiguous coverage of the requested season."""
    rows: dict[date, dict[str, Any]] = {}
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        columns = set(reader.fieldnames or [])
        date_column = "DAY" if "DAY" in columns else "DATE"
        required = {date_column, *WEATHER_UNITS}
        if missing := required - columns:
            raise ValueError(f"Weather CSV is missing columns: {', '.join(sorted(missing))}")
        for line, raw in enumerate(reader, start=2):
            day = _iso_date(raw[date_column], f"Weather line {line} {date_column}")
            if day in rows:
                raise ValueError(f"Weather CSV contains duplicate date: {day}")
            row = {name: _number(raw[name], f"Weather line {line} {name}") for name in WEATHER_UNITS}
            if row["TMAX"] < row["TMIN"]:
                raise ValueError(f"Weather {day}: TMAX is below TMIN")
            for name in ("IRRAD", "RAIN", "WIND"):
                if row[name] < 0:
                    raise ValueError(f"Weather {day}: {name} must be non-negative")
            if row["VAP"] <= 0:
                raise ValueError(f"Weather {day}: VAP must be positive")
            rows[day] = {"DAY": day, **row}
    first = config["sowing_date"]
    final = first + timedelta(days=config["max_duration"])
    needed = [first + timedelta(days=offset) for offset in range((final - first).days + 1)]
    if missing_days := [day for day in needed if day not in rows]:
        raise ValueError(
            f"Weather must cover {first} through {final} without gaps; "
            f"first missing date: {missing_days[0]} ({len(missing_days)} missing)"
        )
    return [rows[day] for day in needed]


def make_weather_provider(rows: list[dict[str, Any]], config: dict[str, Any]) -> Any:
    """Use PCSE's own meteorology and ET calculations, with no FAIRY code."""
    from pcse.base import WeatherDataContainer, WeatherDataProvider
    from pcse.util import reference_ET

    location = config["location"]
    provider = WeatherDataProvider()
    provider.latitude = location["latitude"]
    provider.longitude = location["longitude"]
    provider.elevation = location["elevation"]
    provider.angstA = config["reference_et"]["angsta"]
    provider.angstB = config["reference_et"]["angstb"]
    provider.ETmodel = config["reference_et"]["et_model"]
    provider.description = ["Explicit local weather CSV; standalone native PCSE diagnostic"]
    for row in rows:
        evaporation_mm = reference_ET(
            DAY=row["DAY"], LAT=provider.latitude, ELEV=provider.elevation,
            TMIN=row["TMIN"], TMAX=row["TMAX"], IRRAD=row["IRRAD"],
            VAP=row["VAP"], WIND=row["WIND"], ANGSTA=provider.angstA,
            ANGSTB=provider.angstB, ETMODEL=provider.ETmodel,
        )
        container = WeatherDataContainer(
            LAT=provider.latitude, LON=provider.longitude, ELEV=provider.elevation,
            **row, E0=evaporation_mm[0] / 10.0, ES0=evaporation_mm[1] / 10.0,
            ET0=evaporation_mm[2] / 10.0,
        )
        provider._store_WeatherDataContainer(container, row["DAY"])
    return provider


def make_management(config: dict[str, Any]) -> list[dict[date, Any]]:
    """Create one rainfed sowing-to-maturity crop; no scheduled interventions."""
    start = config["sowing_date"]
    return [{start: {
        "CropCalendar": {
            "crop_name": config.get("crop_name", "soybean"),
            "variety_name": config.get("variety_name", "explicit-research-parameters"),
            "crop_start_date": start, "crop_start_type": "sowing",
            "crop_end_date": None, "crop_end_type": "maturity",
            "max_duration": config["max_duration"],
        },
        "TimedEvents": None, "StateEvents": None,
    }}]


def run(config_path: str | Path, weather_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Run one native season and write complete inputs, daily results, and summary."""
    config_path, weather_path = Path(config_path).resolve(), Path(weather_path).resolve()
    config = load_config(config_path)
    rows = read_weather(weather_path, config)
    try:
        import pcse
        from pcse.base import ParameterProvider
        import pcse.models
    except ImportError as error:
        raise RuntimeError("Native PCSE is required; install the project's wofost extra") from error

    provider = make_weather_provider(rows, config)
    management = make_management(config)
    parameters = ParameterProvider(
        cropdata=config["crop_parameters"], soildata=config["soil_parameters"],
        sitedata=config["site_parameters"],
    )
    if hasattr(pcse.models, "Wofost72_WLP_CWB"):
        model = pcse.models.Wofost72_WLP_CWB(
            parameters, provider, management,
            output_vars=OUTPUT_VARIABLES, summary_vars=SUMMARY_VARIABLES,
        )
        expected_crop = ("pcse.crop.wofost72", "Wofost72")
    elif hasattr(pcse.models, "Wofost72_WLP_FD"):
        model = pcse.models.Wofost72_WLP_FD(parameters, provider, management)
        # PCSE 5.5 lacks output-list constructor arguments. These affect only
        # saved diagnostics and are changed before the first daily output.
        model.mconf.OUTPUT_VARS = list(OUTPUT_VARIABLES)
        model.mconf.SUMMARY_OUTPUT_VARS = list(SUMMARY_VARIABLES)
        expected_crop = ("pcse.crop.wofost7", "Wofost")
    else:
        raise RuntimeError("Installed PCSE has neither native Wofost72_WLP_CWB nor Wofost72_WLP_FD")
    actual_soil = (model.mconf.SOIL.__module__, model.mconf.SOIL.__name__)
    actual_crop = (model.mconf.CROP.__module__, model.mconf.CROP.__name__)
    if actual_soil != ("pcse.soil.classic_waterbalance", "WaterbalanceFD") or actual_crop != expected_crop:
        raise RuntimeError(f"Unexpected native 7.2 crop/soil components: {actual_crop}, {actual_soil}")
    native_configuration = {
        "requested_model": "WOFOST 7.2 water-limited, classic free-drainage water balance",
        "configured_model_alias": config["model"],
        "actual_model_class": type(model).__name__,
        "crop_component": ".".join(actual_crop), "soil_component": ".".join(actual_soil),
        "configuration_file": str(Path(pcse.__file__).resolve().parent / "conf" / model.config),
    }
    native_configuration["configuration_sha256"] = _sha256(Path(native_configuration["configuration_file"]))
    model.run_till_terminate()
    daily = model.get_output()
    native_summaries = model.get_summary_output()
    if len(native_summaries) != 1:
        raise RuntimeError(f"Expected one native crop summary, received {len(native_summaries)}")
    crop_summary = native_summaries[0]
    dry_yield = crop_summary.get("TWSO")
    mature = crop_summary.get("DOM") is not None
    emerged = crop_summary.get("DOE")
    maturity_date = crop_summary.get("DOM")
    growing = [row for row in daily if row.get("DVS") is not None and row["DVS"] >= 0]
    stresses = [row["RFTRA"] for row in growing if row.get("RFTRA") is not None]
    summary = {
        "model": type(model).__name__, "pcse_version": pcse.__version__,
        "native_configuration": native_configuration,
        "sowing_date": config["sowing_date"], "simulation_end_date": model.day,
        "matured": mature, "native_crop_summary": crop_summary,
        "emergence_to_maturity_days": (maturity_date - emerged).days if mature and emerged else None,
        "storage_organ_dry_matter_kg_ha": dry_yield,
        "dry_matter_kg_mu": dry_yield / 15.0 if dry_yield is not None else None,
        "equivalent_13pct_moisture_kg_mu_before_losses": dry_yield / 0.87 / 15.0 if mature and dry_yield is not None else None,
        "peak_lai": max((row["LAI"] for row in daily if row.get("LAI") is not None), default=None),
        "mean_growing_season_rftra": sum(stresses) / len(stresses) if stresses else None,
        "water_stress_days_rftra_below_0_95": sum(value < 0.95 for value in stresses),
        "severe_water_stress_days_rftra_below_0_5": sum(value < 0.5 for value in stresses),
        "max_root_depth_cm": max((row["RD"] for row in daily if row.get("RD") is not None), default=None),
        "daily_row_count": len(daily), "weather_first_date": rows[0]["DAY"],
        "weather_last_date": rows[-1]["DAY"],
        "interpretation": {
            "calendar": "Dates, including DOE/DOA/DOM, are unmodified native PCSE summary dates.",
            "yield": "TWSO is the measured final storage-organ dry matter, kg/ha; if DOM is null, this is immature biomass, not mature yield. The 13% conversion is reported only after native maturity and before all harvest losses.",
            "scope": "Rainfed native 7.2 water-limited diagnostic; no nitrogen limitation, FAIRY soil mapping, actions, harvest or storage.",
            "validation": "A completed run is not evidence of local cultivar calibration or reproduction of a published study.",
        },
    }
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "summary.json", summary)
    _write_json(output_dir / "resolved_inputs.json", config)
    _write_json(output_dir / "agromanagement.json", [
        {str(day): payload for day, payload in campaign.items()} for campaign in management
    ])
    with (output_dir / "daily.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["day", *OUTPUT_VARIABLES])
        writer.writeheader()
        writer.writerows(daily)
    with (output_dir / "weather_with_et.csv").open("w", newline="", encoding="utf-8") as stream:
        names = ["DAY", *WEATHER_UNITS, "E0", "ES0", "ET0"]
        writer = csv.DictWriter(stream, fieldnames=names)
        writer.writeheader()
        for row in rows:
            native = provider(row["DAY"])
            writer.writerow({name: getattr(native, name) for name in names})
    source_files = {"config": config_path, "weather": weather_path, "runner": Path(__file__).resolve()}
    if crop_file := config.get("resolved_crop_parameter_file"):
        source_files["crop_parameters"] = Path(crop_file)
    _write_json(output_dir / "provenance.json", {
        "model": type(model).__name__, "pcse_version": pcse.__version__,
        "native_configuration": native_configuration,
        "python_version": platform.python_version(),
        "input_files": {name: {"path": str(path), "sha256": _sha256(path)}
                        for name, path in source_files.items()},
        "resolved_inputs_sha256": _sha256(output_dir / "resolved_inputs.json"),
        "config_provenance": config.get("provenance", {}),
        "weather_units": WEATHER_UNITS, "evaporation_output_units": "cm/day",
    })
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--weather", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        summary = run(args.config, args.weather, args.output_dir)
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(2, f"Standalone WOFOST error: {error}\n")
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=_json_default, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
