#!/usr/bin/env python3
"""Constrain regional reference phenology without using Oracle yield or risk dates.

Only one common scale of TSUM1 and TSUM2 is screened. Their 5:11 ratio is
inherited from the existing HN84 reference, because aggregate emergence-to-
maturity durations cannot identify the two phases independently. NASA POWER
weather is a forcing proxy, not a cultivar/site/year field observation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
from fairy.physics import PlantingConfig, SeedType, SoilWeatherInput
from fairy.physics.wofost_backend import WofostBackend, WofostConfig


TARGETS = {
    "HEINONG84": 121.0,
    "HEINONG58": 118.0,
    "HEINONG60": 119.0,
    "HEIHE50": 110.0,
    "HEIHE43": 115.0,
    "HEIKE71": 108.0,
}


def run(scale: float, year: int, *, seed: str = "HEINONG84", native_profile: str | None = None) -> dict:
    weather_path = ROOT / f"fairy/physics/data/wofost/weather/harbin_{year}_nasa_power.json"
    weather = json.loads(weather_path.read_text())["properties"]["parameter"]
    start = date(year, 5, 5)
    physics = FarmPhysicsState(num_ridges=1)
    physics.phenology.plant_ridges([0], PlantingConfig(
        planting_date=start, seed_type=SeedType(seed)))
    physics.management.states[0].planted = True
    physics.management.states[0].stand_fraction = 1.0
    physics.soil.states[0].root_vwc = 0.30
    options = WofostConfig(
        cultivar_profile=native_profile or "heilongjiang_heinong84_complete_v1",
        require_explicit_cultivar_parameters=True,
        external_biotic_coupling=False,
        parameter_overrides={} if native_profile else {"HEINONG84": {
            "TSUM1": round(500.0 * scale, 6),
            "TSUM2": round(1100.0 * scale, 6),
        }},
    )
    backend = WofostBackend(options)
    for offset in range(180):
        day = start + timedelta(days=offset)
        key = day.strftime("%Y%m%d")
        if key not in weather["T2M"]:
            break
        backend.advance_day(
            physics=physics, day=day,
            weather=SoilWeatherInput(
                day=day,
                air_temp_mean_c=weather["T2M"][key],
                air_temp_min_c=weather["T2M_MIN"][key],
                air_temp_max_c=weather["T2M_MAX"][key],
                rain_mm=weather["PRECTOTCORR"][key],
                solar_rad_mj_m2=weather["ALLSKY_SFC_SW_DWN"][key],
                wind_ms=weather["WS2M"][key],
            ),
            density_by_ridge={0: 23.0}, ridge_area_m2=294.8,
            humidity_pct=weather["RH2M"][key],
        )
        native = backend._runs[0]
        if native.maturity_snapshot is not None:
            final = native.maturity_snapshot
            doe, doa, dom = (final.get(k) for k in ("DOE", "DOA", "DOM"))
            result = {
                "scale": scale, "forcing_year": year,
                "TSUM1": round(500.0 * scale, 6),
                "TSUM2": round(1100.0 * scale, 6),
                "native_DOE": str(doe), "native_DOA": str(doa),
                "native_DOM": str(dom),
                "DOE_to_DOM_days": (dom - doe).days,
                "DOE_to_DOA_days": (doa - doe).days,
                "DOA_to_DOM_days": (dom - doa).days,
                "weather_sha256": hashlib.sha256(weather_path.read_bytes()).hexdigest(),
            }
            if native_profile:
                result.pop("scale")
                result.update({"seed_type": seed, "profile_id": native_profile,
                    "runtime_thermal_override": False,
                    "profile_sha256": native.specification["cultivar_profile"]["sha256"],
                    "native_variety_name": native.specification["variety"],
                    "TSUM1": native.specification["crop_parameters"]["TSUM1"],
                    "TSUM2": native.specification["crop_parameters"]["TSUM2"]})
            return result
    return {"scale": scale, "forcing_year": year, "DOE_to_DOM_days": None}


def audit() -> dict:
    candidates = [run(round(i / 200.0, 3), 2017) for i in range(160, 211)]
    selected = {}
    for seed, target in TARGETS.items():
        eligible = [r for r in candidates if r["DOE_to_DOM_days"] is not None]
        chosen = min(eligible, key=lambda r: (
            abs(r["DOE_to_DOM_days"] - target), abs(r["scale"] - 1.0), r["scale"]))
        # Existing HN84 stays byte-for-byte fixed; its published interval is
        # 119–123 days. The 121 day middle is only an explicit screen reference.
        if seed == "HEINONG84":
            chosen = next(r for r in eligible if r["scale"] == 1.0)
        selected[seed] = {
            "target_aggregate_duration_days": target,
            "selection": chosen,
            "unfitted_forcing_year_diagnostics": [run(chosen["scale"], y) for y in (2018, 2019)],
        }
    return {
        "schema_version": 1,
        "purpose": "public_aggregate_reference_constraint_not_field_calibration",
        "selection_uses_yield": False,
        "selection_uses_scenario_oracle_or_risk_window": False,
        "independently_identified_parameters": ["common_TSUM_scale"],
        "fixed_ratio_TSUM1_to_TSUM2": [5, 11],
        "source_profile": "heilongjiang_heinong84_complete_v1",
        "source_profile_sha256": hashlib.sha256((ROOT / "fairy/physics/data/wofost/profiles/heilongjiang_heinong84_complete_v1.json").read_bytes()).hexdigest(),
        "model": "PCSE Wofost81_NWLP_CWB_CNB",
        "sowing_month_day": "05-05",
        "location": {"latitude_deg": 45.7, "longitude_deg": 126.6},
        "screen_forcing_year": 2017,
        "unfitted_diagnostic_years": [2018, 2019],
        "field_validation": False,
        "limitations": [
            "Official aggregate durations are weak regional evidence, not observed calendar stages at Harbin in 2017.",
            "Native DOM is used as an explicitly approximate endpoint for the published emergence-to-maturity descriptions.",
            "The fixed 5:11 phase ratio is an engineering transfer; flowering timing is not independently fitted.",
            "NASA POWER is gridded weather, not a field station or a cultivar experiment.",
            "Neither yield nor a benchmark's favorable harvest/drought window enters selection.",
            "No native drought, cold, density or pathogen-specific response is identified by this phenology screen.",
        ],
        "candidates": candidates,
        "selected": selected,
    }


def verify_published() -> dict:
    """Use actual seed-scoped published profiles without candidate overrides."""
    config = json.loads((ROOT / "configs/wofost/formal90_cultivar_mapping_v1.json").read_text())
    cases = []
    for seed, profile in config["cultivar_profiles"].items():
        for year in (2017, 2018, 2019):
            record = run(1.0, year, seed=seed, native_profile=profile)
            assert record["DOE_to_DOM_days"] is not None
            record["target_aggregate_duration_days"] = TARGETS[seed]
            record["used_for_selection"] = year == 2017
            record["field_validation"] = False
            cases.append(record)
    training = [r for r in cases if r["forcing_year"] == 2017]
    return {"schema_version": 1, "field_validation": False,
        "passed": all(abs(r["DOE_to_DOM_days"] - r["target_aggregate_duration_days"]) <= 1 for r in training),
        "actual_profile_identity_and_seed_used": True,
        "native_thermal_overrides_used": False,
        "cross_year_results_are_diagnostics_not_fixed_duration_targets": True,
        "cases": cases}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-published", action="store_true")
    arguments = parser.parse_args()
    result = verify_published() if arguments.verify_published else audit()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result if arguments.verify_published else {
        seed: row["selection"] for seed, row in result["selected"].items()}, ensure_ascii=False))
