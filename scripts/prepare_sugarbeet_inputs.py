#!/usr/bin/env python3
"""Fetch pinned official parameters and real daily forcing; never synthesize weather.

The site is REQUIRED, because a reference cultivar does not establish suitability.
A two-crop calendar means wheat in years Y-2/Y-1, fallow, then beet in year Y.
All soil, quality, price and timing defaults remain explicit engineering assumptions.
"""

from __future__ import annotations
import argparse
import csv
from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import urllib.parse
import urllib.request

COMMIT = "1ca91d7dbb5aaf6b41462162de03a8254812d3a5"
BASE = f"https://raw.githubusercontent.com/ajwdewit/WOFOST_crop_parameters/{COMMIT}"
POWER = "https://power.larc.nasa.gov/api/temporal/daily/point"
FIELDS = [
    "day",
    "tmin_c",
    "tmax_c",
    "tmean_c",
    "rain_mm",
    "radiation_mj_m2",
    "wind_2m_m_s",
    "rh_pct",
]
PARAMETERS = {
    "T2M_MIN": "tmin_c",
    "T2M_MAX": "tmax_c",
    "T2M": "tmean_c",
    "PRECTOTCORR": "rain_mm",
    "ALLSKY_SFC_SW_DWN": "radiation_mj_m2",
    "WS2M": "wind_2m_m_s",
    "RH2M": "rh_pct",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fetch(url, path):
    path = Path(path)
    request = urllib.request.Request(
        url, headers={"User-Agent": "FAIRY-sugarbeet-reproducible-inputs/1.0"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    tmp = path.with_name(path.name + ".partial")
    tmp.write_bytes(data)
    tmp.replace(path)
    return {"path": path.name, "sha256": sha(path), "url": url}


def radiation_factor(unit):
    u = unit.lower().replace(" ", "").replace("²", "^2")
    if u in {"mj/m^2/day", "mj/m2/day", "mj/m^2/d"}:
        return 1.0
    if u in {"kw-hr/m^2/day", "kwh/m^2/day", "kwhr/m^2/day", "kwh/m2/day"}:
        return 3.6
    raise ValueError(
        f"Unrecognized POWER radiation units {unit!r}; do not guess the conversion"
    )


def power_weather(root, start, end, latitude, longitude):
    raw = root / "source_weather"
    raw.mkdir(exist_ok=True)
    rows = []
    records = []
    for year in range(start.year, end.year + 1):
        a = max(start, date(year, 1, 1))
        b = min(end, date(year, 12, 31))
        url = (
            POWER
            + "?"
            + urllib.parse.urlencode(
                dict(
                    parameters=",".join(PARAMETERS),
                    community="AG",
                    latitude=latitude,
                    longitude=longitude,
                    start=a.strftime("%Y%m%d"),
                    end=b.strftime("%Y%m%d"),
                    format="JSON",
                    **{"time-standard": "LST"},
                )
            )
        )
        dest = raw / f"POWER_{year}.json"
        record = fetch(url, dest)
        record["path"] = str(dest.relative_to(root))
        records.append(record)
        data = json.loads(dest.read_bytes())
        parameters = data["properties"]["parameter"]
        units = data["parameters"]
        factor = radiation_factor(units["ALLSKY_SFC_SW_DWN"]["units"])
        fill = float(data.get("header", {}).get("fill_value", -999))
        day = a
        while day <= b:
            row = {"day": day.isoformat()}
            for key, field in PARAMETERS.items():
                value = float(parameters[key][day.strftime("%Y%m%d")])
                if not math.isfinite(value) or value == fill:
                    raise ValueError(
                        f"POWER missing/invalid {key} at {day}; no interpolation fallback"
                    )
                row[field] = value * factor if key == "ALLSKY_SFC_SW_DWN" else value
            rows.append(row)
            day += timedelta(days=1)
    with (root / "weather.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return records


def cycle_data(year, rotation):
    beet = dict(
        cycle_id=f"beet_{year}",
        crop="sugarbeet",
        cultivar="Sugarbeet_601",
        prepare_open=f"{year}-03-20",
        sowing_open=f"{year}-04-01",
        sowing_close=f"{year}-04-20",
        harvest_open=f"{year}-09-25",
        harvest_close=f"{year}-10-31",
        nitrogen_close=f"{year}-07-15",
        maximum_n_kg_ha=180.0,
        sowing_depth_cm=2.5,
        seed_count_ha=100000,
        irrigation_withholding_days=20,
        minimum_dry_yield_kg_ha=1000.0,
    )
    if not rotation:
        return [beet]
    wheat = dict(
        cycle_id=f"wheat_{year - 1}",
        crop="winter_wheat",
        cultivar="Winter_wheat_104",
        prepare_open=f"{year - 2}-10-01",
        sowing_open=f"{year - 2}-10-05",
        sowing_close=f"{year - 2}-10-25",
        harvest_open=f"{year - 1}-06-01",
        harvest_close=f"{year - 1}-07-31",
        nitrogen_close=f"{year - 1}-05-01",
        maximum_n_kg_ha=240.0,
        sowing_depth_cm=3.0,
        seed_count_ha=4000000,
        irrigation_withholding_days=0,
        minimum_dry_yield_kg_ha=2000.0,
    )
    return [wheat, beet]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--rotation", action="store_true")
    p.add_argument(
        "--year",
        type=int,
        default=2021,
        help="Beet harvest year; rotation starts in autumn year-2",
    )
    p.add_argument("--latitude", type=float, required=True)
    p.add_argument("--longitude", type=float, required=True)
    p.add_argument("--elevation", type=float, required=True)
    p.add_argument("--weather-csv", type=Path)
    p.add_argument("--beet-yaml", type=Path)
    p.add_argument("--wheat-yaml", type=Path)
    args = p.parse_args(argv)
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / "manifest.json").exists():
        p.error(
            "Output already has a manifest; use a new directory to preserve reproducibility"
        )
    if (
        not -89 <= args.latitude <= 89
        or not -180 <= args.longitude <= 180
        or not -400 <= args.elevation <= 5000
    ):
        p.error("Invalid site coordinates/elevation")
    cycles = cycle_data(args.year, args.rotation)
    start = date.fromisoformat(cycles[0]["prepare_open"])
    deadline = date(args.year, 11, 5)
    crops = {}
    for c in cycles:
        kind = "wheat" if c["crop"] == "winter_wheat" else "sugarbeet"
        dest = root / (kind + ".yaml")
        source = args.wheat_yaml if kind == "wheat" else args.beet_yaml
        if source:
            shutil.copyfile(source, dest)
            entry = {
                "path": dest.name,
                "sha256": sha(dest),
                "origin": "user_supplied_file",
            }
        else:
            entry = fetch(BASE + "/" + kind + ".yaml", dest)
            entry["upstream_commit"] = COMMIT
        entry["parameter_overrides"] = {}
        crops[c["cycle_id"]] = entry
    if args.weather_csv:
        shutil.copyfile(args.weather_csv, root / "weather.csv")
        source_weather = [
            {
                "origin": "user_supplied_exact_daily_csv",
                "source_name": args.weather_csv.name,
            }
        ]
    else:
        source_weather = power_weather(
            root, start, deadline + timedelta(days=1), args.latitude, args.longitude
        )
    manifest = dict(
        schema="fairy.sugarbeet.rotation.inputs.v1",
        start=start.isoformat(),
        deadline=deadline.isoformat(),
        timezone="Asia/Shanghai",
        cycles=cycles,
        crops=crops,
        site={
            "latitude": args.latitude,
            "longitude": args.longitude,
            "elevation_m": args.elevation,
        },
        site_agronomy_status="unverified_transfer_experiment_not_a_local_production_recommendation",
        parameter_status="uncalibrated_reference",
        residue_policy="no_unmodelled_residue_n_credit",
        weather={"path": "weather.csv", "sha256": sha(root / "weather.csv")},
        source_weather=source_weather,
        native_soil_parameters=dict(
            SMW=0.12,
            SMFCF=0.30,
            SM0=0.45,
            CRAIRC=0.06,
            SOPE=10.0,
            KSUB=1.0,
            K0=10.0,
            RDMSOL=120.0,
        ),
        native_site_parameters=dict(
            WAV=20.0,
            NAVAILI=40.0,
            CO2=410.0,
            NSOILBASE=40.0,
            NSOILBASE_FR=0.01,
            SMLIM=0.30,
            NOTINF=0.0,
            SSI=0.0,
            SSMAX=0.0,
            IFUNRN=0,
        ),
        management=dict(irrigation_efficiency=0.85, nitrogen_recovery_fraction=0.70),
        assumptions=[
            "Soil, N stock, rates, density and dates are engineering assumptions, not measured data",
            "Minimum yield floors are task acceptance thresholds, not calibrated targets",
            "European official cultivars have not been calibrated for this site",
            "POWER daily LST is not a local civil-time station measurement",
            "Historical forecast is an explicit perfect-information reference",
            "No frost survival, bolting, pest, salinity, P/K or residue organic N process is claimed",
        ],
        source_urls=[
            BASE + "/sugarbeet.yaml",
            "https://www.agri.cn/zx/nyyw/202408/t20240827_8665579.htm",
            "https://nmj.tongliao.gov.cn/xwzx/jftx/202604/t20260403_1041668.html",
        ],
    )
    dest = root / "manifest.json"
    dest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        from fairy.scenarios.management_extensions.engines.sugarbeet_inputs import (
            SugarBeetInputs,
        )
        import yaml

        SugarBeetInputs(root).load_parameters(yaml)
    except Exception:
        dest.rename(root / "manifest.INVALID.json")
        raise
    print(
        f"Verified input contracts: {root}; calibration status remains uncalibrated_reference"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"Input build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
