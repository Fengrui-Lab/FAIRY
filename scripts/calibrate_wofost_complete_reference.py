#!/usr/bin/env python3
"""Offline native WOFOST81 reference screening, never a field validation.

Only phenology's two thermal sums are screened initially. All temperatures use
one explicitly retained native 7 C response. Public cultivar duration and yield
are multi-site aggregate plausibility constraints, not 2017 observations.
"""
from __future__ import annotations

import argparse
import copy
import csv
from dataclasses import replace
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
from fairy.physics import PlantingConfig, SeedType
from fairy.physics.wofost_backend import WofostBackend, WofostConfig
from scripts.check_wofost_real_weather_parity import load_weather, serializable

OUTPUTS = ["DVS", "TSUM", "LAI", "TAGP", "TWSO", "TWLV", "TWST", "TWRT", "RD", "SM", "NAVAIL", "NfixTotal", "NuptakeTotal", "RFTRA", "RFRGRL", "TRA", "EVS", "DOE", "DOA", "DOM"]
SOURCE = {
    "cultivar": "https://www.haas.cn/cgcyc/info/1231/2141.htm",
    "regional_parameters": "https://essd.copernicus.org/articles/18/2413/2026/",
    "base": "https://github.com/ajwdewit/WOFOST_crop_parameters/blob/1ca91d7dbb5aaf6b41462162de03a8254812d3a5/soybean.yaml",
}


def write_json(path, value):
    path.write_text(json.dumps(serializable(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def make_inputs(overrides, sow):
    config = WofostConfig(
        co2_ppm=400, reference_density_plants_m2=23,
        parameter_overrides={"HEINONG84": overrides},
        soil_overrides={"RDMSOL": 120}, external_biotic_coupling=False,
        fertilizer_n_recovery=.7, max_duration_days=180,
    )
    backend = WofostBackend(config)
    physics = FarmPhysicsState(num_ridges=1)
    physics.soil.params = replace(physics.soil.params, root_depth_m=1.2)
    physics.soil.states[0].root_vwc = .28
    physics.phenology.plant_ridges([0], PlantingConfig(planting_date=sow, seed_type=SeedType.HEINONG84))
    physics.management.states[0].stand_fraction = 1
    spec = backend._specification(physics, 0, sow, 23)
    return backend, spec


def run_native(overrides, weather_path, sow, *, return_daily=False):
    from pcse.base import ParameterProvider, WeatherDataProvider
    from pcse.models import Wofost81_NWLP_CWB_CNB

    forcing, meta = load_weather(weather_path, sow)
    backend, spec = make_inputs(overrides, sow)
    provider = WeatherDataProvider()
    for w, rh in forcing:
        provider._store_WeatherDataContainer(backend._weather_container(w.day, vars(w), rh), w.day)
    management = [{sow: {"CropCalendar": {
        "crop_name": "soybean", "variety_name": "HEINONG84_engineering_reference",
        "crop_start_date": sow, "crop_start_type": "sowing", "crop_end_date": None,
        "crop_end_type": "maturity", "max_duration": 180,
    }, "TimedEvents": [{"event_signal":"apply_n", "name":"Basal nitrogen",
                         "comment":"50 kg N/ha, recovery 0.7, applied before first rate calculation",
                         "events_table":[{sow:{"N_amount":50.0,"N_recovery":.7}}]}],
        "StateEvents": None}}]
    model = Wofost81_NWLP_CWB_CNB(
        ParameterProvider(cropdata=copy.deepcopy(spec["crop_parameters"]),
                          soildata=copy.deepcopy(spec["soil_parameters"]),
                          sitedata=copy.deepcopy(spec["site_parameters"])),
        provider, management, output_vars=OUTPUTS, summary_vars=OUTPUTS)
    while model.day < forcing[-2][0].day and not model.flag_terminate:
        model.run(days=1)
    daily = model.get_output()
    summary = model.get_summary_output()[-1] if model.get_summary_output() else {}
    doe, doa, dom = (summary.get(k) for k in ("DOE", "DOA", "DOM"))
    peak = max((row.get("LAI") or 0 for row in daily), default=0)
    dry = summary.get("TWSO") if dom else None
    active = [row for row in daily if row.get("DVS") is not None and 0 <= row["DVS"] < 2]
    result = {
        "weather_year": sow.year, "sowing_date": sow, "emergence_date": doe,
        "anthesis_date": doa, "maturity_date": dom,
        "emergence_to_maturity_days": (dom-doe).days if dom and doe else None,
        "emergence_to_anthesis_days": (doa-doe).days if doa and doe else None,
        "anthesis_to_maturity_days": (dom-doa).days if dom and doa else None,
        "peak_lai": peak, "peak_lai_date": next((row["day"] for row in daily if row.get("LAI")==peak), None),
        "mature_grain_dry_kg_ha": dry,
        "mature_grain_kg_mu_13pct_before_harvest_losses": dry / .87 / 15 if dry is not None else None,
        "mature_tagp_dry_kg_ha": summary.get("TAGP"),
        "minimum_active_rftra": min((row["RFTRA"] for row in active if row.get("RFTRA") is not None), default=None),
        "mean_active_rftra": sum(row["RFTRA"] for row in active if row.get("RFTRA") is not None) / len(active),
        "minimum_active_n_growth_factor": min((row["RFRGRL"] for row in active if row.get("RFRGRL") is not None), default=None),
        "active_water_stressed_days_rftra_lt_09": sum(row.get("RFTRA",1) < .9 for row in active),
        "nitrogen_fixation_kg_ha": summary.get("NfixTotal"),
        "density_plants_m2": 23, "reference_density_plants_m2": 23,
        "effective_initial_TDWI_kg_ha": spec["crop_parameters"]["TDWI"],
        "applied_n_kg_ha": 50, "n_recovery": .7,
        "weather_sha256": meta["sha256"],
    }
    return result, spec, daily if return_daily else None


def phenology_score(result):
    days = result["emergence_to_maturity_days"]
    if days is None:
        return 1e6
    # Literature yield is reported, never used in the phenology objective.
    return abs(days-121) + .05 * abs((result["emergence_to_anthesis_days"] or 40)-40)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--weather", type=Path, default=ROOT/"fairy/physics/data/wofost/weather/harbin_2017_nasa_power.json")
    ap.add_argument("--extra-weather", type=Path, action="append", default=[])
    ap.add_argument("--sowing-month-day", default="05-05")
    ap.add_argument("--output-dir", type=Path, default=ROOT/"validation_runs/wofost_complete_20261021/parameterization")
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    year = int(next(iter(json.loads(args.weather.read_text())["properties"]["parameter"]["T2M"]))) // 10000
    sow = date.fromisoformat(f"{year}-{args.sowing_month_day}")
    frozen = {
        "status": "public_evidence_constrained_engineering_reference_not_field_calibrated",
        "sources": SOURCE,
        "fixed_assumptions": "Native 8.1 soybean physiology; TDWI120 at reference23plants/m2; actual NASA RH; 120cm homogeneous soil(.14,.36,.48), initialSM.28, NOTINF.15, SOPE/KSUB3.5cm/day; CO2=400; appliedN50 recovery.7; rainfed; no external biotic loss.",
        "public_weak_constraints": {"emergence_to_maturity_days": [119,123], "official_yield_kg_mu_unknown_moisture": [192.72,209.0133333333]},
        "selection": "Only duration and phase-balance score; no yield multiplication, maturity forcing or yield objective.",
        "screen": {"total_thermal_time": [1560,1580,1600,1620,1640], "TSUM1": [500,540,580]},
        "temperature_response": [0,0,7,0,30,23,45,38],
        "changed_for_emergence": {"TBASEM":8,"TEFFMX":22,"TSUMEM":70},
        "canopy_scope": "Native SLATB, SPAN23 and RGRLAI.01 retained first; broad LAI3–5 plausibility bracket is not a cultivar observation.",
    }
    write_json(args.output_dir/"frozen_screen.json", frozen)
    common = {"TBASEM":8.0, "TEFFMX":22.0, "TSUMEM":70.0,
              "IDSL":0, "DTSMTB":[0.,0.,7.,0.,30.,23.,45.,38.], "TDWI":120.0}
    candidates = []
    for total in frozen["screen"]["total_thermal_time"]:
        for first in frozen["screen"]["TSUM1"]:
            overrides = dict(common, TSUM1=float(first), TSUM2=float(total-first))
            result, _, _ = run_native(overrides, args.weather, sow)
            result.update(TSUM1=first, TSUM2=total-first, total_thermal_time=total,
                          phenology_score=phenology_score(result))
            candidates.append(result)
            print(json.dumps(serializable(result)), flush=True)
    candidates.sort(key=lambda r:r["phenology_score"])
    best = candidates[0]
    selected = dict(common, TSUM1=float(best["TSUM1"]), TSUM2=float(best["TSUM2"]))
    result, spec, daily = run_native(selected, args.weather, sow, return_daily=True)
    write_json(args.output_dir/"screen_results.json", candidates)
    write_json(args.output_dir/"selected_overrides.json", selected)
    write_json(args.output_dir/"complete_native_crop_parameters.json", spec["crop_parameters"])
    write_json(args.output_dir/"selected_resolved_inputs.json", spec)
    # Every retained value remains inspectable, including upstream units and
    # descriptions; this prevents an opaque two-number cultivar definition.
    catalogue = {}
    pinned = WofostBackend()._varieties["Soybean_901"]
    for key, value in spec["crop_parameters"].items():
        upstream = pinned[key]
        catalogue[key] = {
            "value": value, "description": upstream[1], "units": upstream[2],
            "origin": "reference_screen" if key in {"TSUM1", "TSUM2"} else
                      "Xu2026_A1_regional_prior" if key == "TBASEM" else "pinned_native_soybean",
            "changed_from_pinned_native": value != upstream[0],
        }
    write_json(args.output_dir/"complete_parameter_catalogue.json", catalogue)
    write_json(args.output_dir/"selected_reference_metadata.json", {
        "identity": "Heinong84_public_evidence_engineering_reference_v1",
        "status": "engineering_reference_not_field_validated",
        "selection_year": year, "cross_years": [2018,2019],
        "sources": SOURCE, "parameter_count":len(catalogue),
        "changed_native_parameter_names":[k for k,v in catalogue.items() if v["changed_from_pinned_native"]],
        "selection": "15 fixed thermal-time candidates; minimize |VE–R8 days−121| plus 0.05*|VE–anthesis days−40|. Yield is excluded from score. 40 days is an explicitly assumed phase-balance preference, not a measured Heinong84 date.",
        "important_definitions": {
            "TSUM1_and_TSUM2": "effective temperature sums under the same pinned native DTSMTB (approximately max(0,Tmean−7C)); not Chinese active sum above10C",
            "TDWI": "120kg total initial dry matter/ha at23plants/m2; reference-density assumption explicit, not an observed local density response",
            "LAI": "3–5 considered a broad canopy plausibility bracket only; native canopy values retained without fitting",
            "yield": "Native mature TWSO dry matter / .87 /15 = kg/mu at13% water before external biotic, stand, harvest, storage losses",
        },
        "limitations": [
            "Public 119–123days and193–209kg/mu are aggregate cultivar references, not year-specific station observations.",
            "All assimilation, nitrogen fixation, leaf area, senescence, partitioning and conversion parameters remain native Soybean901 priors; local response accuracy is unestablished.",
            "High native yield is an output, not a calibrated target. No yield multiplier or forced maturity is used.",
            "2018/2019 are fixed-parameter weather extrapolation checks, not independent field validation.",
            "No soybean-specific short-day response, oxygen stress, pests/disease, establishment or harvest losses in the native-only screening.",
            "Soil is assumed homogeneous120cm loam, not measured Harbin soil.",
        ],
    })
    write_json(args.output_dir/"selected_2017_summary.json", result)
    write_json(args.output_dir/"selected_2017_daily.json", daily)
    with (args.output_dir/"selected_2017_daily.csv").open("w", newline="") as f:
        writer=csv.DictWriter(f, fieldnames=daily[0]); writer.writeheader(); writer.writerows(daily)
    verification = []
    for extra in args.extra_weather:
        doc=json.loads(extra.read_text()); yr=int(next(iter(doc["properties"]["parameter"]["T2M"])))//10000
        result, _, daily=run_native(selected, extra, date.fromisoformat(f"{yr}-{args.sowing_month_day}"), return_daily=True)
        verification.append(result)
        write_json(args.output_dir/f"locked_{yr}_summary.json", result)
        write_json(args.output_dir/f"locked_{yr}_daily.json", daily)
    write_json(args.output_dir/"locked_cross_year_checks.json", verification)
    ablations = []
    for label, parameters in (
        ("native_901_TDWI120_at_reference23", {}),
        ("native_901_legacy_TDWI69_at_density23_over40", {"TDWI":120*23/40}),
        ("selected_phenology_legacy_TDWI69", dict(selected, TDWI=120*23/40)),
    ):
        result, _, _ = run_native(parameters,args.weather,sow)
        result["case"] = label
        ablations.append(result)
    write_json(args.output_dir/"controlled_ablations_2017.json", ablations)
    print("SELECTED",json.dumps(serializable({"overrides":selected,"result":best})),flush=True)


if __name__ == "__main__":
    main()
