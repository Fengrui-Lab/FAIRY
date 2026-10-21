#!/usr/bin/env python3
"""Cache and validate unaltered NASA POWER weather for Harbin soybean scenarios.

Source is gridded meteorology, not field-station observations. Existing validated
files are reused without changing their download timestamps or raw bytes.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNITS = {
    "ALLSKY_SFC_SW_DWN": "MJ/m^2/day", "T2M_MIN": "C", "T2M_MAX": "C",
    "T2M": "C", "RH2M": "%", "WS2M": "m/s", "PRECTOTCORR": "mm/day",
}


def validate(raw: bytes, year: int) -> dict:
    document = json.loads(raw)
    parameters = document["properties"]["parameter"]
    expected = [(date(year, 5, 1) + timedelta(days=i)).strftime("%Y%m%d") for i in range(184)]
    for name, unit in UNITS.items():
        if document["parameters"][name]["units"] != unit:
            raise ValueError(f"Unit mismatch: {name}")
        if sorted(parameters[name]) != expected:
            raise ValueError(f"Nonconsecutive/incomplete weather: {name}")
        if not all(math.isfinite(float(v)) and float(v) != document["header"]["fill_value"] for v in parameters[name].values()):
            raise ValueError(f"Missing weather: {name}")
    for key in expected:
        if not parameters["T2M_MIN"][key] <= parameters["T2M"][key] <= parameters["T2M_MAX"][key]:
            raise ValueError(f"Temperature order: {key}")
        if not (0 <= parameters["RH2M"][key] <= 100 and parameters["WS2M"][key] >= 0
                and parameters["PRECTOTCORR"][key] >= 0 and parameters["ALLSKY_SFC_SW_DWN"][key] >= 0):
            raise ValueError(f"Physical range: {key}")
    return document


def aggregate(parameters: dict, keys: list[str]) -> dict:
    return {
        "days": len(keys),
        "rain_mm": round(sum(parameters["PRECTOTCORR"][k] for k in keys), 2),
        "mean_temp_c": round(sum(parameters["T2M"][k] for k in keys) / len(keys), 2),
        "solar_mj_m2": round(sum(parameters["ALLSKY_SFC_SW_DWN"][k] for k in keys), 2),
        "mean_rh_pct": round(sum(parameters["RH2M"][k] for k in keys) / len(keys), 2),
        "gdd_base7_c_day": round(sum(max(0, parameters["T2M"][k] - 7) for k in keys), 2),
        "gdd_base8_c_day": round(sum(max(0, parameters["T2M"][k] - 8) for k in keys), 2),
        "positive_rain_days": sum(parameters["PRECTOTCORR"][k] > 0 for k in keys),
        "rain_ge1mm_days": sum(parameters["PRECTOTCORR"][k] >= 1 for k in keys),
    }


def fetch(year: int, output: Path) -> tuple[dict, dict]:
    path = output / f"fairy_nasa_power_harbin_{year}0501_{year}1031.json"
    query = urllib.parse.urlencode({
        "parameters": ",".join(UNITS), "community": "AG", "latitude": 45.7, "longitude": 126.6,
        "start": f"{year}0501", "end": f"{year}1031", "format": "JSON", "time-standard": "LST",
    })
    url = "https://power.larc.nasa.gov/api/temporal/daily/point?" + query
    provenance_path = path.with_suffix(".provenance.json")
    source = ROOT / "validation_runs/wofost_reference_diagnostics_20261020/weather/fairy_nasa_power_harbin_20170501_20171031.json"
    provenance = {}
    if path.exists():
        raw = path.read_bytes()
        if provenance_path.exists():
            provenance = json.loads(provenance_path.read_text())
    elif year == 2017 and source.exists():
        raw = source.read_bytes()
        provenance = {
            "copied_from": str(source), "copied_at_utc": datetime.now(timezone.utc).isoformat(),
            "original_download_provenance": json.loads(source.with_suffix(".provenance.json").read_text()),
        }
    else:
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "FAIRY-reproducible-crop-validation/1.0"})
                with urllib.request.urlopen(request, timeout=50) as response:
                    raw = response.read()
                    provenance = {"status": response.status, "retrieved_at_utc": datetime.now(timezone.utc).isoformat()}
                break
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(3 * (attempt + 1))
    document = validate(raw, year)
    path.write_bytes(raw)
    provenance.update({
        "path": str(path.resolve()), "url": url, "sha256": hashlib.sha256(raw).hexdigest(),
        "header": document["header"], "parameters": document["parameters"], "geometry": document["geometry"],
        "quality_checks": {"dates_consecutive": True, "days": 184, "all_requested_units_match": True,
                           "missing_values": 0, "temperature_order_valid": True, "physical_ranges_valid": True},
        "interpretation": "NASA POWER gridded reanalysis and satellite-derived solar radiation; not field station observations. Raw bytes retained exactly as downloaded.",
    })
    provenance_path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n")
    p = document["properties"]["parameter"]
    days = sorted(p["T2M"])
    total = aggregate(p, days)
    total.update({
        "year": year, "path": str(path), "sha256": provenance["sha256"],
        "min_tmin_c": min(p["T2M_MIN"].values()), "max_tmax_c": max(p["T2M_MAX"].values()),
        "sowing_window": {k: {n: p[n][k] for n in ("T2M", "T2M_MIN", "PRECTOTCORR")}
                          for k in days if f"{year}0501" <= k <= f"{year}0510"},
    })
    detail = {
        "year": year, "may10_to_sep20": aggregate(p, [k for k in days if f"{year}0510" <= k <= f"{year}0920"]),
        "monthly": {f"{month:02d}": aggregate(p, [k for k in days if k[4:6] == f"{month:02d}"])
                    for month in range(5, 11)},
        "first_autumn_tmin_below_zero": next((k for k in days if k >= f"{year}0801" and p["T2M_MIN"][k] < 0), None),
        "sep_dry_days": [k for k in days if k[4:6] == "09" and p["PRECTOTCORR"][k] == 0],
    }
    return total, detail


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, nargs="+", default=[2017, 2018, 2019])
    parser.add_argument("--output-dir", type=Path, default=ROOT / "validation_runs/wofost_complete_20261021/weather")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda year: fetch(year, args.output_dir), args.years))
    (args.output_dir / "climate_summary.json").write_text(json.dumps([r[0] for r in results], indent=2) + "\n")
    (args.output_dir / "climate_detail.json").write_text(json.dumps([r[1] for r in results], indent=2) + "\n")
    for total, _ in results:
        print(json.dumps({key: value for key, value in total.items() if key != "sowing_window"}))


if __name__ == "__main__":
    main()
