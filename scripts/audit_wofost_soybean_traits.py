#!/usr/bin/env python3
"""Run controlled native WOFOST contrasts; these are model checks, not field validation."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
from fairy.physics import ManagementAction, ManagementActionType, PlantingConfig, SeedType, SoilWeatherInput
from fairy.physics.wofost_backend import WofostBackend, WofostConfig
from fairy.physics.wofost_profiles import REFERENCE_CULTIVAR_PROFILES


SOWING = date(2026, 5, 1)
AREA_M2 = 268.0 * 1.1


def run_reference(seed: str, forcing: str) -> tuple[dict, list[dict]]:
    physics = FarmPhysicsState(num_ridges=1)
    physics.phenology.plant_ridges([0], PlantingConfig(planting_date=SOWING, seed_type=SeedType(seed)))
    physics.management.states[0].planted = True
    physics.management.states[0].stand_fraction = 1.0
    physics.soil.states[0].root_vwc = 0.30
    backend = WofostBackend(WofostConfig(
        cultivar_profiles=REFERENCE_CULTIVAR_PROFILES,
        require_explicit_cultivar_parameters=True,
        external_biotic_coupling=False,
        soil_overrides={"RDMSOL": 45.0, "SMW": 0.12, "SMFCF": 0.30, "SM0": 0.45},
    ))
    rows = []
    for offset in range(160):
        day = SOWING + timedelta(days=offset)
        cold = forcing == "cold" and 15 <= offset < 35
        drought = forcing in ("drought", "drought_rescue") and 35 <= offset < 65
        actions = {}
        if forcing == "drought_rescue" and offset in (42, 49, 56):
            actions = {0: [ManagementAction(ManagementActionType.IRRIGATION, amount=15.0)]}
        backend.advance_day(
            physics=physics, day=day,
            weather=SoilWeatherInput(
                day=day, air_temp_mean_c=12.0 if cold else 22.0,
                air_temp_min_c=4.0 if cold else 16.0,
                air_temp_max_c=20.0 if cold else 28.0,
                rain_mm=0.0 if drought else 6.0,
                solar_rad_mj_m2=18.0, wind_ms=2.0,
            ),
            actions_by_ridge=actions, density_by_ridge={0: 30.0},
            ridge_area_m2=AREA_M2, humidity_pct=55.0,
        )
        native = backend._runs[0]
        record = native.pcse
        rows.append({
            "seed_type": seed, "forcing": forcing, "day": day.isoformat(),
            "offset": offset, "DVS": record.get("DVS"), "TAGP": record.get("TAGP"),
            "TWSO": record.get("TWSO"), "LAI": record.get("LAI"), "SM": record.get("SM"),
            "RFTRA": record.get("RFTRA"), "TRA": record.get("TRA"),
        })
    run = backend._runs[0]
    final = run.maturity_snapshot or run.pcse
    summary = {"seed_type": seed, "forcing": forcing,
               "final_native_TWSO_kg_ha": final.get("TWSO"),
               "final_native_TAGP_kg_ha": final.get("TAGP"),
               "native_DOM": str(final.get("DOM")),
               "native_model": "Wofost81_NWLP_CWB_CNB",
               "profile_id": REFERENCE_CULTIVAR_PROFILES[seed],
               "profile_sha256": run.specification["cultivar_profile"]["sha256"],
               "irrigation_mm": run.cumulative_irrigation_mm}
    return summary, rows


def audit() -> dict:
    summaries, daily = [], []
    for seed in REFERENCE_CULTIVAR_PROFILES:
        forcings = ("normal", "cold") if seed in ("SUINONG42", "KENDOU40") else (
            "normal", "drought", "drought_rescue")
        for forcing in forcings:
            summary, rows = run_reference(seed, forcing)
            summaries.append(summary)
            daily.extend(rows)
    indexed = {(row["seed_type"], row["forcing"]): row for row in summaries}
    # Warm, watered controls must have exactly equal native output despite different labels.
    baseline = indexed["SUINONG42", "normal"]["final_native_TWSO_kg_ha"]
    assert baseline > 0
    for seed in REFERENCE_CULTIVAR_PROFILES:
        assert indexed[seed, "normal"]["final_native_TWSO_kg_ha"] == baseline
    assert indexed["SUINONG42", "cold"]["final_native_TWSO_kg_ha"] > indexed["KENDOU40", "cold"]["final_native_TWSO_kg_ha"]
    assert indexed["HEINONG44", "drought"]["final_native_TWSO_kg_ha"] > indexed["HEINONG65", "drought"]["final_native_TWSO_kg_ha"]
    for seed in ("HEINONG44", "HEINONG65"):
        assert indexed[seed, "drought"]["final_native_TWSO_kg_ha"] < baseline
        assert indexed[seed, "drought_rescue"]["final_native_TWSO_kg_ha"] > indexed[seed, "drought"]["final_native_TWSO_kg_ha"]
    return {"validation_status": "controlled_model_check_not_field_validation",
            "sowing_day": SOWING.isoformat(), "days": 160,
            "controls": {"density_plants_m2": 30, "normal_rain_mm_day": 6,
                         "drought_days_after_sowing": [35, 64],
                         "cold_days_after_sowing": [15, 34],
                         "cold_daily_temperature_c": {"min": 4, "mean": 12, "max": 20},
                         "rescue_irrigation_mm": [[42, 15], [49, 15], [56, 15]],
                         "soil_overrides": {"RDMSOL": 45, "SMW": 0.12, "SMFCF": 0.30, "SM0": 0.45}},
            "runs": summaries, "daily": daily,
            "interpretation": "Only declared native response parameters differ; no forced maturity, harvest or output yield scaling. Cold forcing is a nighttime-chilling benchmark, not a reproduction of the 4C chamber experiment. Drought ordering need not imply universal field superiority."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = audit()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = result.pop("daily")
    with (args.output_dir / "daily.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (args.output_dir / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
