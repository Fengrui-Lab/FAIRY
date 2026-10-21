#!/usr/bin/env python3
"""Compare the FAIRY daily bridge with unmodified PCSE on identical real forcing.

This is a numerical adapter diagnostic, not a local cultivar calibration. Both
members of each pair receive the exact same native parameters and NASA POWER
weather containers. Across pairs, only soil_overrides.RDMSOL is changed.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import platform
import sys
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
from fairy.physics import PlantingConfig, SeedType, SoilWeatherInput
from fairy.physics.wofost_backend import WofostBackend, WofostConfig


VARIABLES = ("DVS", "LAI", "TAGP", "TWSO", "SM", "NAVAIL", "DOM")
REQUIRED_UNITS = {
    "ALLSKY_SFC_SW_DWN": "MJ/m^2/day",
    "T2M_MIN": "C",
    "T2M_MAX": "C",
    "T2M": "C",
    "RH2M": "%",
    "WS2M": "m/s",
    "PRECTOTCORR": "mm/day",
}


def serializable(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): serializable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [serializable(item) for item in value]
    return value


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(serializable(value), ensure_ascii=False, indent=2) + "\n")


def load_weather(path: Path, sowing: date) -> tuple[list[tuple[SoilWeatherInput, float]], dict[str, Any]]:
    raw = path.read_bytes()
    document = json.loads(raw)
    parameters = document["properties"]["parameter"]
    for name, unit in REQUIRED_UNITS.items():
        actual = document["parameters"][name]["units"]
        if actual != unit:
            raise ValueError(f"NASA unit mismatch for {name}: {actual!r}, expected {unit!r}")
    days = sorted(parameters["T2M"])
    if not days:
        raise ValueError("Empty weather record")
    start = date.fromisoformat(f"{days[0][:4]}-{days[0][4:6]}-{days[0][6:]}")
    expected = [(start + timedelta(days=i)).strftime("%Y%m%d") for i in range(len(days))]
    if days != expected or any(sorted(parameters[name]) != days for name in REQUIRED_UNITS):
        raise ValueError("Weather variables must cover identical consecutive dates")
    forcing = []
    fill = float(document["header"]["fill_value"])
    for key in days:
        values = {name: float(parameters[name][key]) for name in REQUIRED_UNITS}
        if any(not math.isfinite(value) or value == fill for value in values.values()):
            raise ValueError(f"Missing/non-finite NASA weather at {key}")
        day = datetime.strptime(key, "%Y%m%d").date()
        if day < sowing:
            continue
        forcing.append((SoilWeatherInput(
            day=day,
            air_temp_mean_c=values["T2M"],
            air_temp_min_c=values["T2M_MIN"],
            air_temp_max_c=values["T2M_MAX"],
            rain_mm=values["PRECTOTCORR"],
            solar_rad_mj_m2=values["ALLSKY_SFC_SW_DWN"],
            wind_ms=values["WS2M"],
        ), values["RH2M"]))
    if len(forcing) < 2 or forcing[0][0].day != sowing:
        raise ValueError("Weather must include sowing day and at least the following day")
    lon, lat, elevation = document["geometry"]["coordinates"]
    metadata = {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "header": document["header"],
        "units": document["parameters"],
        "longitude_deg": lon, "latitude_deg": lat, "elevation_m": elevation,
        "available_days": len(days), "used_forcing_start": forcing[0][0].day,
        "available_end": forcing[-1][0].day,
        "interpretation": "NASA POWER gridded reanalysis and satellite-derived radiation; not station observations",
        "conversion": "AG radiation MJ/m2/day to J/m2/day; rain mm/day to cm/day. Same adapter RH/mean-temperature VAP and reference_ET conversion in both models.",
    }
    companion = path.with_suffix(".provenance.json")
    if companion.is_file():
        metadata["download_provenance"] = json.loads(companion.read_text())
    return forcing, metadata


def run_pair(depth_cm: float, base_config: dict[str, Any], forcing: list[tuple[SoilWeatherInput, float]],
             output: Path, tolerance: float) -> dict[str, Any]:
    import pcse
    from pcse.base import ParameterProvider, WeatherDataProvider
    from pcse.models import Wofost81_NWLP_CWB_CNB

    output.mkdir(parents=True, exist_ok=True)
    start = forcing[0][0].day
    config_values = copy.deepcopy(base_config)
    config_values.setdefault("soil_overrides", {})["RDMSOL"] = depth_cm
    config = WofostConfig(**config_values)
    physics = FarmPhysicsState(num_ridges=1)
    physics.phenology.plant_ridges(
        [0], PlantingConfig(planting_date=start, seed_type=SeedType.HEINONG84)
    )
    physics.management.states[0].stand_fraction = 1.0
    backend = WofostBackend(config)

    def advance(weather: SoilWeatherInput, humidity: float) -> None:
        backend.advance_day(
            physics=physics, day=weather.day, weather=weather,
            actions_by_ridge={}, density_by_ridge={0: 40.0},
            ridge_area_m2=174.2, humidity_pct=humidity,
        )

    advance(*forcing[0])
    specification = backend._runs[0].specification
    provider = WeatherDataProvider()
    for weather, humidity in forcing:
        provider._store_WeatherDataContainer(
            backend._weather_container(weather.day, vars(weather), humidity), weather.day
        )
    management = [
        {start: {
            "CropCalendar": {
                "crop_name": "soybean", "variety_name": specification["variety"],
                "crop_start_date": start, "crop_start_type": "sowing",
                "crop_end_date": None, "crop_end_type": "maturity",
                "max_duration": config.max_duration_days,
            }, "TimedEvents": None, "StateEvents": None,
        }},
        {start + timedelta(days=config.max_duration_days + 3660): None},
    ]
    native = Wofost81_NWLP_CWB_CNB(
        ParameterProvider(
            cropdata=copy.deepcopy(specification["crop_parameters"]),
            soildata=copy.deepcopy(specification["soil_parameters"]),
            sitedata=copy.deepcopy(specification["site_parameters"]),
        ), provider, management,
        output_vars=list(VARIABLES), summary_vars=list(VARIABLES),
    )

    maxima = {name: 0.0 for name in VARIABLES if name != "DOM"}
    maxima_dates: dict[str, str | None] = {name: None for name in maxima}
    failures = []
    rows = []
    maturity_boundary = None
    native_final = None
    for index, (weather, humidity) in enumerate(forcing[:-1]):
        if index:
            advance(weather, humidity)
        native.run(days=1)
        run = backend._runs[0]
        expected_boundary = weather.day + timedelta(days=1)
        clock_ok = run.model.day == native.day == expected_boundary
        if not clock_ok:
            failures.append({"day": str(weather.day), "variable": "clock"})
        summaries = native.get_summary_output()
        crop_final = summaries[-1] if native.crop is None and summaries else None
        row: dict[str, Any] = {
            "forcing_day": weather.day.isoformat(),
            "native_boundary_day": native.day.isoformat(),
            "adapter_boundary_day": run.model.day.isoformat(),
            "expected_boundary_day": expected_boundary.isoformat(),
            "clock_matches": clock_ok,
        }
        for name in VARIABLES:
            expected = (crop_final[name] if crop_final is not None and name not in {"SM", "NAVAIL"}
                        else native.get_variable(name))
            actual = run.pcse[name]
            row[f"native_{name}"] = serializable(expected)
            row[f"adapter_{name}"] = serializable(actual)
            if name == "DOM" or actual is None or expected is None:
                equal = actual == expected
                if not equal:
                    failures.append({"day": str(weather.day), "variable": name,
                                     "actual": actual, "expected": expected})
            else:
                error = abs(float(actual) - float(expected))
                row[f"abs_error_{name}"] = error
                if error > maxima[name]:
                    maxima[name], maxima_dates[name] = error, weather.day.isoformat()
                if error > tolerance:
                    failures.append({"day": str(weather.day), "variable": name,
                                     "absolute_error": error, "actual": actual, "expected": expected})
        rows.append(row)
        if crop_final is not None and maturity_boundary is None:
            maturity_boundary = native.day
            native_final = dict(crop_final)
        if maturity_boundary is not None and native.day >= maturity_boundary + timedelta(days=7):
            break

    with (output / "daily_parity.csv").open("w", newline="") as stream:
        fields = list(dict.fromkeys(key for row in rows for key in row))
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    if native_final is None:
        native_final = {name: native.get_variable(name) for name in VARIABLES}
    crop_yield = native_final.get("TWSO")
    summary = {
        "passed": not failures,
        "comparison": "FAIRY deferred-rate adapter vs unmodified native Wofost81_NWLP_CWB_CNB",
        "pcse_version": pcse.__version__, "soil_depth_cm": depth_cm,
        "tolerance_absolute": tolerance, "compared_variables": VARIABLES,
        "compared_boundaries": len(rows), "first_forcing_day": rows[0]["forcing_day"],
        "last_forcing_day": rows[-1]["forcing_day"],
        "clock_convention": "Both states at native day d+1 after integrating actual forcing day d; the adapter has not evaluated d+1 rates yet",
        "max_absolute_errors": maxima, "max_error_forcing_day": maxima_dates,
        "date_mismatches": sum(item["variable"] == "DOM" for item in failures),
        "clock_mismatches": sum(item["variable"] == "clock" for item in failures),
        "failure_count": len(failures), "failures": failures,
        "matured": native_final.get("DOM") is not None,
        "native_DOM": native_final.get("DOM"),
        "native_crop_deletion_boundary": maturity_boundary,
        "fairy_compatibility_maturity_date": physics.phenology.states[0].maturity_date,
        "native_final": native_final,
        "native_storage_organ_dry_kg_ha": crop_yield,
        "native_mature_yield_dry_kg_ha": crop_yield if native_final.get("DOM") is not None else None,
        "native_mature_yield_dry_kg_mu": float(crop_yield) / 15 if crop_yield is not None and native_final.get("DOM") is not None else None,
        "yield_basis": "Native TWSO dry matter before any harvest loss; not FAIRY market-moisture recovered yield. End-of-coverage storage biomass is not a mature yield when DOM is null.",
        "management": "No fertilizer, irrigation, harvest or external biotic stress; planting stand 1.0, density/reference density both 40 plants/m2 (neutral TDWI scaling)",
        "limitations": [
            "Numerical parity does not establish physical correctness of soil mapping, weather conversion, cultivar parameters or crop model.",
            "Both sides intentionally share the adapter's RH/T2M vapour-pressure approximation and fixed Angstrom coefficients.",
            "Depth pairs change only soil_overrides.RDMSOL; mapped initial available water WAV consequently changes at fixed initial root VWC.",
            "No forced maturity or yield multiplier. End criterion is seven days after native crop deletion, otherwise weather coverage end.",
        ],
        "config": asdict(config),
    }
    write_json(output / "native_specification.json", specification)
    write_json(output / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weather-json", type=Path, required=True)
    parser.add_argument("--wofost-config", type=Path)
    parser.add_argument("--sowing-date", type=date.fromisoformat, default=date(2017, 5, 10))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=1e-10)
    args = parser.parse_args()
    forcing, metadata = load_weather(args.weather_json, args.sowing_date)
    config = json.loads(args.wofost_config.read_text()) if args.wofost_config else {}
    config.update({
        "external_biotic_coupling": False, "reference_density_plants_m2": 40.0,
        "latitude_deg": metadata["latitude_deg"], "longitude_deg": metadata["longitude_deg"],
        # Keep max-duration crop deletion outside the available forcing window.
        # An immature candidate is reported as such when real weather ends.
        "elevation_m": metadata["elevation_m"], "max_duration_days": 366,
    })
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summaries = [run_pair(depth, config, forcing, args.output_dir / f"depth_{depth}cm", args.tolerance)
                 for depth in (40, 120)]
    summary = {
        "passed": all(result["passed"] for result in summaries),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "command_arguments": sys.argv[1:], "weather": metadata,
        "config_file": str(args.wofost_config.resolve()) if args.wofost_config else None,
        "config_file_sha256": hashlib.sha256(args.wofost_config.read_bytes()).hexdigest() if args.wofost_config else None,
        "purpose": "Isolate adapter numerical state/rate-clock effects on identical actual historical forcing; independent of the separate WOFOST 7.2 literature-prior exercise",
        "pairs": summaries,
    }
    write_json(args.output_dir / "parity_summary.json", summary)
    print(json.dumps(serializable({"passed": summary["passed"], "output": str(args.output_dir.resolve()),
          "pairs": [{key: result[key] for key in ("soil_depth_cm", "compared_boundaries", "matured", "native_DOM", "native_storage_organ_dry_kg_ha", "native_mature_yield_dry_kg_ha", "max_absolute_errors", "failure_count")} for result in summaries]}), indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
