#!/usr/bin/env python3
"""Independently recompute complete-season checks from saved rows and app calls.

This does not import the runner, trust its success flag, or modify model output.
Crop plausibility and cultivar calibration still require independent observations.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path


def number(row: dict, key: str, default=None):
    value = row.get(key)
    return default if value in (None, "") else float(value)


def audit(case: Path) -> dict:
    summary = json.loads((case / "summary.json").read_text())
    resolved = json.loads((case / "resolved_parameters.json").read_text())
    ridges = json.loads((case / "final_ridges.json").read_text())
    operations = [json.loads(line) for line in (case / "operations.jsonl").read_text().splitlines() if line.strip()]
    with (case / "daily_by_ridge.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    by_day, by_ridge = defaultdict(list), defaultdict(list)
    for row in rows:
        by_day[row["forcing_day"]].append(row)
        by_ridge[int(row["ridge_id"])].append(row)
    issues = []

    def check(ok: bool, name: str, details=None):
        if not ok:
            issues.append({"check": name, "details": details})

    check(set(ridges) == {str(i) for i in range(64)}, "all_64_final_ridges")
    check(set(by_ridge) == set(range(64)), "all_64_daily_ridges")
    days = sorted(by_day)
    check(bool(days), "daily_rows_exist")
    for index, day in enumerate(days):
        check(sorted(int(r["ridge_id"]) for r in by_day[day]) == list(range(64)), "one_record_per_ridge_per_day", day)
        if index:
            check(date.fromisoformat(day) == date.fromisoformat(days[index - 1]) + timedelta(days=1), "consecutive_daily_forcing", day)
    residuals, post_maturity_changes, dvs_reversals = [], [], []
    maximum_native_bio_disagreement = 0.0
    for rid, group in by_ridge.items():
        previous_dvs, frozen_bio = None, None
        for row in group:
            dvs = number(row, "DVS")
            if dvs is None:
                continue
            if previous_dvs is not None and dvs < previous_dvs - 1e-8:
                dvs_reversals.append([rid, row["forcing_day"]])
            previous_dvs = dvs
            check(0 <= number(row, "SM") <= resolved["reduced_soil_parameters"]["saturation_vwc"] + 1e-8,
                  "soil_range", [rid, row["forcing_day"]])
            for key in ("RFTRA", "RFRGRL"):
                value = number(row, key)
                check(value is None or 0 <= value <= 1 + 1e-8, "stress_range", [rid, key, row["forcing_day"]])
            biological = number(row, "biological_yield_g_dm_m2")
            native_storage = number(row, "TWSO_kg_dm_ha")
            maximum_native_bio_disagreement = max(maximum_native_bio_disagreement, abs(biological - native_storage / 10))
            if frozen_bio is not None and abs(biological - frozen_bio) > 1e-7:
                post_maturity_changes.append([rid, row["forcing_day"], biological - frozen_bio])
            if row["r8_reached"] == "True" and frozen_bio is None:
                frozen_bio = biological
            outgoing = sum(number(row, key, 0) for key in ("evaporation_mm", "surface_evaporation_mm", "transpiration_mm", "runoff_mm", "bottom_drainage_mm"))
            delta = number(row, "storage_end_mm") - number(row, "storage_start_mm")
            residuals.append(number(row, "rain_mm") + number(row, "effective_irrigation_mm", 0) - outgoing - delta)
    check(not dvs_reversals, "dvs_monotonic", dvs_reversals[:5])
    check(not post_maturity_changes, "biological_mass_frozen_after_maturity", post_maturity_changes[:5])
    check(maximum_native_bio_disagreement < 1e-7, "native_storage_equals_recovery_biological_pool", maximum_native_bio_disagreement)
    check(bool(residuals) and max(map(abs, residuals)) < 1e-7, "recomputed_daily_water_balance", max(map(abs, residuals), default=None))

    area = summary["area_m2"] / 64
    reconstructed_market = biological_total = 0.0
    for rid, final in ridges.items():
        phen, state = final["phenology"], final["recovery"]
        check(bool(phen["planting_date"]), "planted", rid)
        check(state["r8_reached"] and state["harvested"], "mature_harvested", rid)
        check(not state["drying_required"] and state["grain_moisture_frac"] <= 0.135, "safe_final_moisture", rid)
        dry = state["biological_yield_g_m2"]
        expected = dry * (1 - state["field_loss_fraction"]) * (1 - state["machine_loss_fraction"]) / .87
        check(abs(expected - state["recovered_yield_g_m2_at_market_moisture"]) < 1e-7, "single_standard_moisture_conversion", rid)
        reconstructed_market += expected * area / 1000
        biological_total += dry * area / 1000
    check(abs(biological_total - summary["biological_yield_kg_dry_total"]) < 1e-7, "biological_total_recomputed")
    harvested = unloaded = stored = applied_product = applied_irrigation = 0.0
    stored_ids, harvested_ids = [], []
    mass_before_drying = None
    tool_errors = []
    for operation in operations:
        name, result = operation["tool"].split(".")[-1], operation["result"]
        if isinstance(result, dict) and result.get("error"):
            tool_errors.append({"tool": operation["tool"], "error": result["error"]})
        if name == "base_fertilize" or name == "apply_fertilizer":
            applied_product += result["fertilizer_used_kg"]
        elif name == "irrigate":
            arguments = operation["arguments"]
            applied_irrigation += arguments["hours"] * 5 * (arguments["end"] - arguments["start"] + 1) / 64
        elif name == "harvest":
            harvested += result["grain_kg_added"]
            harvested_ids.extend(result["harvested_ridges"])
        elif name == "unload_grain":
            unloaded += result["grain_kg_unloaded"]
            mass_before_drying = unloaded - stored
        elif name == "dry_grain":
            check(abs(result["trailer_grain_kg"] - mass_before_drying) < .01, "drying_does_not_double_convert_standard_mass")
        elif name == "store_grain":
            stored += result["moved_kg"]
            stored_ids.extend(result["batch_ridge_ids"])
            check(not result.get("warning"), "all_storage_batches_safe")
    check(not tool_errors, "no_tool_errors", tool_errors)
    check(abs(applied_product - summary["fertilizer_product_kg_total"]) < 1e-7,
          "actual_tool_fertilizer_product_matches_recipe", applied_product)
    check(abs(applied_irrigation - summary["irrigation_gross_mm"]) < 1e-7,
          "actual_tool_irrigation_matches_ledger", applied_irrigation)
    check(sorted(stored_ids) == list(range(64)), "all_64_stored_exactly_once")
    check(sorted(harvested_ids) == list(range(64)), "all_64_harvested_exactly_once")
    check(abs(harvested - reconstructed_market) <= .10, "native_recovery_matches_tool_mass", harvested - reconstructed_market)
    check(abs(harvested - unloaded) < .01 and abs(unloaded - stored) < .01, "harvest_unload_store_mass_continuity")
    check(abs(stored - summary["warehouse_kg_at_13pct"]) < .01, "warehouse_matches_actual_store_calls")

    native = summary["final_native_snapshot"]["ridges"]
    irrigation_efficiency = resolved["backend_config"]["irrigation_efficiency"]
    n_fraction = resolved["backend_config"]["fertilizer_n_fraction"]
    check(abs(sum(state["cumulative_fertilizer_kg"] for state in native.values()) - applied_product) < 1e-7,
          "actual_tool_fertilizer_product_reaches_native_exactly_once")
    for rid, state in native.items():
        group = [row for row in by_ridge[int(rid)] if number(row, "DVS") is not None]
        check(abs(sum(number(row, "n_applied_kg_ha", 0) for row in group) - state["cumulative_n_kg_ha"]) < 1e-8,
              "daily_nitrogen_ledger_matches_cumulative_native_input", rid)
        check(abs(sum(number(row, "irrigation_gross_mm", 0) for row in group) - state["cumulative_irrigation_mm"]) < 1e-8,
              "daily_gross_irrigation_matches_cumulative_native_input", rid)
        for parameter_group in ("crop_parameters", "soil_parameters"):
            check(state["specification"][parameter_group] == resolved["native_inputs_ridge0"][parameter_group],
                  "all_64_native_parameters_identical", [rid, parameter_group])
        check(abs(state["cumulative_irrigation_mm"] - summary["irrigation_gross_mm"]) < 1e-8, "gross_water_reaches_each_ridge", rid)
        check(abs(state["pcse"]["TOTIRR"] * 10 - state["cumulative_irrigation_mm"] * irrigation_efficiency) < 1e-8,
              "effective_irrigation_native_accounting", rid)
        expected_n = state["cumulative_fertilizer_kg"] * n_fraction * 10000 / area
        check(abs(state["cumulative_n_kg_ha"] - expected_n) < 1e-8, "nitrogen_units_per_ridge", rid)
    weather_path = Path(summary["weather_source"]["path"])
    source_hash = hashlib.sha256(weather_path.read_bytes()).hexdigest()
    check(source_hash == summary["weather_source"]["sha256"], "raw_weather_sha256")
    weather = json.loads(weather_path.read_text())["properties"]["parameter"]
    multiplier = summary["weather_source"].get("weather_transform", {}).get("rain_multiplier", 1)
    first_autumn_freeze = next((key for key in sorted(weather["T2M_MIN"]) if key[4:] >= "0801" and weather["T2M_MIN"][key] < 0), None)
    freeze_date = date.fromisoformat(f"{first_autumn_freeze[:4]}-{first_autumn_freeze[4:6]}-{first_autumn_freeze[6:]}") if first_autumn_freeze else None
    mature_before_freeze = freeze_date is None or all(date.fromisoformat(day) < freeze_date for day in summary["maturity_dates"])
    check(mature_before_freeze, "natural_maturity_precedes_first_autumn_air_tmin_below_zero")
    native_vap_errors = []
    for day, group in by_day.items():
        row, key = group[0], day.replace("-", "")
        for column, parameter, factor in (("rain_mm", "PRECTOTCORR", multiplier), ("tmean_c", "T2M", 1), ("tmin_c", "T2M_MIN", 1),
                                          ("tmax_c", "T2M_MAX", 1), ("radiation_mj_m2", "ALLSKY_SFC_SW_DWN", 1),
                                          ("wind_ms", "WS2M", 1), ("source_rh_pct", "RH2M", 1)):
            check(abs(number(row, column) - weather[parameter][key] * factor) < 1e-9, "source_weather_preserved", [day, column])
        for actual_row in group:
            if number(actual_row, "DVS") is not None:
                check(abs(number(actual_row, "used_rh_pct") - weather["RH2M"][key]) < 1e-9,
                      "source_humidity_reaches_native_journal", [day, actual_row["ridge_id"]])
                expected_vap = max(.06, 6.108 * math.exp(17.27 * weather["T2M"][key] / (weather["T2M"][key] + 237.3)) * weather["RH2M"][key] / 100)
                native_vap_errors.append(abs(number(actual_row, "native_vap_hpa") - expected_vap))
    check(bool(native_vap_errors) and max(native_vap_errors) < 1e-9,
          "raw_source_temperature_humidity_to_native_vap", max(native_vap_errors, default=None))
    return {
        "path": str(case.resolve()), "passed": not issues, "issues": issues,
        "daily_rows": len(rows), "daily_forcing_days": len(days), "ridges": len(ridges),
        "max_recomputed_water_residual_mm": max(map(abs, residuals), default=None),
        "max_native_vap_error_hpa": max(native_vap_errors, default=None),
        "reconstructed_market_mass_kg_13pct": reconstructed_market, "warehouse_kg_13pct": stored,
        "warehouse_kg_mu_13pct": stored / (summary["area_m2"] / (2000 / 3)),
        "case": summary["case"], "area_m2": summary["area_m2"],
        "sowing_dates": summary["sowing_dates"], "emergence_dates": summary["emergence_dates"],
        "maturity_dates": summary["maturity_dates"], "harvest_dates": summary["harvest_dates"],
        "gross_irrigation_mm": summary["irrigation_gross_mm"],
        "fertilizer_product_kg_total": summary["fertilizer_product_kg_total"],
        "actual_applied_product_kg_from_tools": applied_product,
        "actual_gross_irrigation_mm_from_tools": applied_irrigation,
        "first_autumn_air_tmin_below_zero": freeze_date.isoformat() if freeze_date else None,
        "mature_before_first_autumn_air_tmin_below_zero": mature_before_freeze,
        "air_frost_note": "NASA 2m air Tmin<0 is a screening proxy; canopy frost damage is not explicitly modeled by this audit.",
        "weather_sha256": source_hash, "rain_multiplier": multiplier,
        "native_biological_pool_max_abs_error_g_m2": maximum_native_bio_disagreement,
        "parameter_fingerprint": hashlib.sha256(json.dumps({
            "backend_config": resolved["backend_config"], "soil_parameters": resolved["native_inputs_ridge0"]["soil_parameters"],
            "crop_parameters": resolved["native_inputs_ridge0"]["crop_parameters"],
            "reduced_soil_parameters": resolved["reduced_soil_parameters"]}, sort_keys=True).encode()).hexdigest(),
        "interpretation": "Independent software, saved-ledger and water/mass audit; does not establish cultivar validation or field yield accuracy.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = [audit(case) for case in args.cases]
    identical = len({r["parameter_fingerprint"] for r in results}) == 1
    groups = defaultdict(list)
    for result in results:
        groups[str(Path(result["path"]).parent)].append(result)
    comparisons = []
    for directory, group in groups.items():
        same_environment = len({json.dumps({key: r[key] for key in (
            "parameter_fingerprint", "area_m2", "sowing_dates", "weather_sha256", "rain_multiplier",
            "fertilizer_product_kg_total")}, sort_keys=True) for r in group}) == 1
        comparisons.append({"directory": directory, "same_environment_and_parameters": same_environment,
                            "cases": [{key: r[key] for key in ("case", "warehouse_kg_mu_13pct", "gross_irrigation_mm",
                                                              "maturity_dates", "harvest_dates")} for r in group]})
    report = {"passed": all(result["passed"] for result in results) and identical and all(c["same_environment_and_parameters"] for c in comparisons), "cases": results,
              "all_case_native_parameters_identical": identical, "paired_case_comparisons": comparisons}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
