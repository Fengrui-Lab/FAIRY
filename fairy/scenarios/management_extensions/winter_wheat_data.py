#!/usr/bin/env python3
"""Acquire actual reference inputs explicitly. Scenario execution itself is offline."""

from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from fairy.scenarios.management_extensions.engines.winter_wheat_inputs import (
    Season,
    WeatherDay,
    WeatherSeries,
    WHEAT_URL,
    UPSTREAM_COMMIT,
    ZENODO_DOI,
    ZENODO_FILES,
    number,
)


def download(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "FAIRY-winter-wheat-inputs/0.1"})
    with urlopen(request, timeout=90) as response:
        data = response.read(60_000_001)
    if len(data) > 60_000_000 or not data:
        raise ValueError("Download empty or exceeds 60 MB safety limit")
    return data


def record(path: Path, root: Path) -> dict:
    return {
        "path": str(path.relative_to(root)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def power_rows(payload: dict) -> list[WeatherDay]:
    parameters = payload["properties"]["parameter"]
    metadata = payload["parameters"]
    aliases = {
        "T2M_MIN": ("tmin_c", {"C", "Celsius", "degC"}),
        "T2M_MAX": ("tmax_c", {"C", "Celsius", "degC"}),
        "T2M": ("tmean_c", {"C", "Celsius", "degC"}),
        "PRECTOTCORR": ("rain_mm", {"mm/day", "mm"}),
        "WS2M": ("wind_2m_m_s", {"m/s"}),
        "RH2M": ("rh_pct", {"%"}),
    }
    radiation_units = metadata["ALLSKY_SFC_SW_DWN"]["units"].replace(" ", "")
    factors = {
        "MJ/m^2/day": 1,
        "MJ/m2/day": 1,
        "kW-hr/m^2/day": 3.6,
        "kW-hr/m2/day": 3.6,
        "kWh/m2/day": 3.6,
    }
    if radiation_units not in factors:
        raise ValueError(
            f"Unrecognized POWER radiation unit {radiation_units}; no guessing"
        )
    for code, (_, units) in aliases.items():
        if metadata[code]["units"] not in units:
            raise ValueError(
                f"Unrecognized POWER unit for {code}: {metadata[code]['units']}"
            )
    keys = set(parameters["T2M"])
    for code in (*aliases, "ALLSKY_SFC_SW_DWN"):
        if set(parameters[code]) != keys:
            raise ValueError(f"POWER dates differ for {code}")
    fill = payload.get("header", {}).get("fill_value", -999)
    result = []
    for key in sorted(keys):
        if len(key) != 8 or not key.isdigit():
            raise ValueError(f"Unexpected POWER date key: {key}")
        values = {}
        for code, (field, _) in aliases.items():
            value = number(parameters[code][key], code)
            if value == fill:
                raise ValueError(f"Missing POWER observation at {key}:{code}")
            values[field] = value
        rad = number(parameters["ALLSKY_SFC_SW_DWN"][key], "radiation")
        if rad == fill:
            raise ValueError(f"Missing POWER radiation at {key}")
        values["radiation_mj_m2"] = rad * factors[radiation_units]
        result.append(
            WeatherDay(date(int(key[:4]), int(key[4:6]), int(key[6:])), **values)
        )
    return result


def fetch(args):
    root = Path(args.output).resolve()
    if (root / "manifest.json").exists():
        raise FileExistsError(
            "Input bundle already exists; choose a new directory to preserve provenance"
        )
    root.mkdir(parents=True, exist_ok=True)
    season = Season(
        date(2019, 10, 1), date(2019, 10, 5), date(2019, 10, 25), date(2020, 7, 15)
    )
    raw_crop = download(WHEAT_URL)
    import yaml
    from fairy.scenarios.management_extensions.engines.winter_wheat_inputs import (
        validate_wheat_parameters,
    )

    cultivar = "Winter_wheat_104"
    raw_params = yaml.safe_load(raw_crop)["CropParameters"]["Varieties"][cultivar]
    validate_wheat_parameters(
        {k: v[0] for k, v in raw_params.items() if k != "Metadata"}
    )
    crop_path = root / "wheat.yaml"
    crop_path.write_bytes(raw_crop)
    params = {
        "parameters": "T2M_MIN,T2M_MAX,T2M,PRECTOTCORR,ALLSKY_SFC_SW_DWN,WS2M,RH2M",
        "community": "AG",
        "longitude": 114.5,
        "latitude": 38.05,
        "start": season.start.strftime("%Y%m%d"),
        "end": (season.deadline + timedelta(days=1)).strftime("%Y%m%d"),
        "format": "JSON",
        "time-standard": "LST",
    }
    url = "https://power.larc.nasa.gov/api/temporal/daily/point?" + urlencode(params)
    raw_weather = download(url)
    (root / "power_raw.json").write_bytes(raw_weather)
    payload = json.loads(raw_weather)
    rows = power_rows(payload)
    WeatherSeries(rows).require(season.start, season.deadline + timedelta(days=1))
    weather_path = root / "weather.csv"
    with weather_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(WeatherDay.__dataclass_fields__)
        )
        writer.writeheader()
        writer.writerows(r.as_dict() for r in rows)
    manifest = {
        "schema": "fairy.winter_wheat.inputs.v1",
        "season": season.as_dict(),
        "parameter_status": "uncalibrated_reference",
        "crop": {
            **record(crop_path, root),
            "cultivar": cultivar,
            "source": WHEAT_URL,
            "commit": UPSTREAM_COMMIT,
            "region": "European reference; NOT a Chinese calibrated cultivar",
        },
        "weather": {
            **record(weather_path, root),
            "source": url,
            "product": "NASA POWER daily grid",
            "time_standard": "LST",
            "calendar_note": "LST dates used as daily model dates; not hourly China civil-time data",
        },
        "raw_weather": record(root / "power_raw.json", root),
        "site": {
            "latitude": 38.05,
            "longitude": 114.5,
            "elevation_m": 80,
            "identity": "illustrative Shijiazhuang-area grid; not matched to a Zenodo station",
        },
        "native_soil_parameters": {
            "SMW": 0.12,
            "SMFCF": 0.30,
            "SM0": 0.45,
            "CRAIRC": 0.06,
            "SOPE": 10.0,
            "KSUB": 1.0,
            "K0": 10.0,
            "RDMSOL": 120.0,
        },
        "native_site_parameters": {
            "WAV": 20.0,
            "NAVAILI": 40.0,
            "CO2": 410.0,
            "NSOILBASE": 40.0,
            "NSOILBASE_FR": 0.01,
            "SMLIM": 0.30,
            "NOTINF": 0.0,
            "SSI": 0.0,
            "SSMAX": 0.0,
            "IFUNRN": 0,
        },
        "soil_status": "generic engineering assumptions; NOT measured at a Chinese validation station",
        "management": {
            "irrigation_efficiency": 0.85,
            "nitrogen_recovery_fraction": 0.70,
        },
        "observations": {
            "doi": ZENODO_DOI,
            "status": "not imported or calibrated",
            "license_note": "consult original record and data-use terms; no license invented",
        },
        "notes": [
            "Weather and crop YAML are actual downloads; soil/prices/calendar are benchmark assumptions.",
            "This bundle does not reproduce the Zenodo author's training or validation experiment.",
            "Never compare a single grid simulation to a county yield without a justified spatial aggregation.",
        ],
    }
    if args.with_observations:
        obs = root / "observations"
        obs.mkdir(exist_ok=True)
        files = []
        for filename, expected_md5 in ZENODO_FILES.items():
            address = (
                "https://zenodo.org/records/14785961/files/"
                + quote(filename)
                + "?download=1"
            )
            data = download(address)
            if hashlib.md5(data).hexdigest() != expected_md5:
                raise ValueError(f"Zenodo checksum mismatch: {filename}")
            target = obs / filename
            target.write_bytes(data)
            files.append(
                {**record(target, root), "md5": expected_md5, "source": address}
            )
        manifest["observations"]["files"] = files
        manifest["observations"]["status"] = (
            "archives_downloaded_not_mapped_not_calibrated"
        )
    # Commit manifest last. Partial downloads cannot masquerade as a complete bundle.
    temp = root / ".manifest.json.tmp"
    temp.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temp, root / "manifest.json")
    print(
        json.dumps(
            {
                "bundle": str(root),
                "status": manifest["parameter_status"],
                "weather_days": len(rows),
            },
            ensure_ascii=False,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    fetch_parser = subs.add_parser("fetch")
    fetch_parser.add_argument(
        "--output",
        default=str(Path(__file__).parent / "data/winter_wheat_ncp_2019_2020"),
    )
    fetch_parser.add_argument("--with-observations", action="store_true")
    inspect_parser = subs.add_parser("inspect-observations")
    inspect_parser.add_argument("--directory", required=True)
    inspect_parser.add_argument("--output", required=True)
    normalize_parser = subs.add_parser("normalize-observations")
    normalize_parser.add_argument("--directory", required=True)
    normalize_parser.add_argument("--mapping", required=True)
    normalize_parser.add_argument("--output", required=True)
    summaries_parser = subs.add_parser("import-summaries")
    summaries_parser.add_argument("--directory", required=True)
    summaries_parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "fetch":
        fetch(args)
    else:
        from fairy.scenarios.management_extensions.evaluation.winter_wheat_observations import (
            inspect_archives,
            normalize,
            import_published_summaries,
        )

        if args.command == "inspect-observations":
            result = inspect_archives(args.directory)
        elif args.command == "import-summaries":
            result = import_published_summaries(args.directory)
        else:
            result = normalize(args.directory, args.mapping)
        output = Path(args.output)
        if output.exists():
            raise FileExistsError(f"Refusing to overwrite {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {output}")


if __name__ == "__main__":
    main()
