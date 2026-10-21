"""Measure the existing density bridge; do not fit or add a density response.

One homogeneous ridge per case, fixed crop/soil/weather/fertilizer and sowing.
Density enters through the same _specification method used by the farm. Native
water/N feedback stays active. Results are biological grain at 13% moisture,
before FAIRY biotic or harvest losses, and do not establish an optimal density.
"""
from __future__ import annotations

import argparse
import copy
import csv
from dataclasses import replace
from datetime import date
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
from fairy.apps.farm_world.farm_world_app import FIELD_LENGTH_M
from fairy.physics import PlantingConfig, SeedType
from fairy.physics.wofost_backend import WofostBackend
from scripts.check_wofost_real_weather_parity import load_weather, serializable


def run_case(config, weather_path, sow, density, rain_multiplier):
    from pcse.base import ParameterProvider, WeatherDataProvider
    from pcse.models import Wofost81_NWLP_CWB_CNB

    options = copy.deepcopy(config["crop_backend_options"])
    options["external_biotic_coupling"] = False
    backend = WofostBackend(options)
    physics = FarmPhysicsState(num_ridges=1)
    soil = options["soil_overrides"]
    physics.soil.params = replace(physics.soil.params,
        root_depth_m=config["initial_soil"]["root_depth_m"],
        wilting_point_vwc=soil["SMW"], field_capacity_vwc=soil["SMFCF"],
        saturation_vwc=soil["SM0"])
    physics.soil.states[0].root_vwc = config["initial_soil"]["vwc"]
    physics.phenology.plant_ridges([0], PlantingConfig(planting_date=sow,
        seed_type=SeedType(config["field"]["seed_type"])))
    physics.management.states[0].stand_fraction = 1.0
    spec = backend._specification(physics, 0, sow, density)
    forcing, weather_meta = load_weather(weather_path, sow)
    provider = WeatherDataProvider()
    for weather, rh in forcing:
        weather = replace(weather, rain_mm=weather.rain_mm * rain_multiplier)
        provider._store_WeatherDataContainer(
            backend._weather_container(weather.day, vars(weather), rh), weather.day)
    management = [{sow: {"CropCalendar": {
        "crop_name": "soybean", "variety_name": spec["variety"],
        "crop_start_date": sow, "crop_start_type": "sowing", "crop_end_date": None,
        "crop_end_type": "maturity", "max_duration": 180},
        "TimedEvents": [{"event_signal": "apply_n", "name": "Fixed basal N",
            "comment": "50 kg N/ha in every case; no irrigation",
            "events_table": [{sow: {"N_amount": 50.0,
                "N_recovery": options.get("fertilizer_n_recovery", .7)}}]}],
        "StateEvents": None}}]
    variables = ["DVS", "LAI", "TWSO", "TAGP", "SM", "RFTRA", "RFRGRL", "WTRAT",
                 "NuptakeTotal", "NfixTotal", "DOE", "DOM"]
    model = Wofost81_NWLP_CWB_CNB(ParameterProvider(
        cropdata=copy.deepcopy(spec["crop_parameters"]),
        soildata=copy.deepcopy(spec["soil_parameters"]),
        sitedata=copy.deepcopy(spec["site_parameters"])), provider, management,
        output_vars=variables, summary_vars=variables)
    while model.day < forcing[-2][0].day and not model.flag_terminate:
        model.run(days=1)
    daily = model.get_output()
    summary = model.get_summary_output()[-1]
    if not summary.get("DOM"):
        raise RuntimeError("A density case did not mature within the fixed weather window")
    active = [row for row in daily if row.get("DVS") is not None and 0 <= row["DVS"] < 2]
    area_mu = config["field"]["ridges"] * config["field"]["ridge_width_m"] * FIELD_LENGTH_M / (2000 / 3)
    yield_mu = summary["TWSO"] / .87 / 15
    result = {"density_plants_m2": density, "rain_multiplier": rain_multiplier,
        "initial_TDWI_kg_dm_ha": spec["crop_parameters"]["TDWI"],
        "maturity_date": summary["DOM"], "peak_LAI": max(row.get("LAI") or 0 for row in daily),
        "grain_kg_dm_ha": summary["TWSO"],
        "grain_kg_mu_13pct_before_losses": yield_mu,
        "field_grain_kg_13pct_before_losses": yield_mu * area_mu,
        "field_area_mu": area_mu,
        "water_stress_days_RFTRA_lt_09": sum((row.get("RFTRA") or 0) < .9 for row in active),
        "crop_transpiration_mm": (summary.get("WTRAT") or 0) * 10,
        "crop_N_uptake_kg_ha": summary.get("NuptakeTotal"),
        "crop_N_fixation_kg_ha": summary.get("NfixTotal"),
        "weather_sha256": weather_meta["sha256"]}
    return result, spec, daily


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/wofost/complete_harbin_heinong84_v1.json")
    parser.add_argument("--weather", type=Path, default=ROOT / "fairy/physics/data/wofost/weather/harbin_2017_nasa_power.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows, specs = [], []
    for multiplier in (1.0, .25):
        for density in (10., 16., 20., 21., 22., 23., 25., 30., 40.):
            result, spec, daily = run_case(config, args.weather, date(2017, 5, 5), density, multiplier)
            rows.append(serializable(result)); specs.append(spec)
            stem = f"rain{multiplier:g}_density{density:g}"
            (args.output_dir / f"{stem}_inputs.json").write_text(json.dumps(serializable(spec), ensure_ascii=False, indent=2))
            with (args.output_dir / f"{stem}_daily.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(daily[0]))
                writer.writeheader(); writer.writerows(daily)
    reference = copy.deepcopy(specs[0]["crop_parameters"])
    reference.pop("TDWI")
    for spec in specs:
        crop = copy.deepcopy(spec["crop_parameters"]); crop.pop("TDWI")
        assert crop == reference
        assert spec["soil_parameters"] == specs[0]["soil_parameters"]
        assert spec["site_parameters"] == specs[0]["site_parameters"]
    baselines = {row["rain_multiplier"]: row["grain_kg_mu_13pct_before_losses"]
                 for row in rows if row["density_plants_m2"] == 23.0}
    for row in rows:
        row["yield_change_pct_vs_23_same_rain"] = (
            row["grain_kg_mu_13pct_before_losses"] / baselines[row["rain_multiplier"]] - 1) * 100
    report = {"purpose": "Diagnostic of current density implementation, not a calibrated density-yield curve",
        "only_density_entry": "TDWI = profile TDWI * density / reference density * initial stand",
        "controls": {"sowing_date": "2017-05-05", "initial_stand_fraction": 1,
            "basal_N_kg_ha": 50, "irrigation_mm": 0, "biotic_coupling": False,
            "other_crop_soil_site_parameters_identical": True,
            "config_path": str(args.config.resolve()),
            "config_sha256": hashlib.sha256(args.config.read_bytes()).hexdigest(),
            "dry_weather_note": "Rainfall multiplied by .25; other weather unchanged; synthetic stress test"},
        "yield_basis": "Native biological grain at 13% water, before FAIRY biotic and harvest losses; not warehouse yield",
        "results": rows}
    (args.output_dir / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
