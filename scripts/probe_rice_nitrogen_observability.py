#!/usr/bin/env python3
"""Isolated 2×2 native-adapter experiment; not a scenario Oracle or field trial.

Compare low/high initial N under dry/wet conditions. Machinery and resource
ledgers are deliberately outside this physiological proxy experiment. It does
not change any scenario, cultivar parameter, or acceptance threshold.
"""
import json
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fairy.apps.paddy.models import PaddyField
from fairy.apps.paddy.observations import crop_report
from fairy.apps.paddy.world import PaddyWorldApp


def probe():
    results = {}
    for water in ("dry", "wet"):
        for nitrogen in ("low", "high"):
            field = PaddyField().to_dict()
            field["plots"][0]["soil"].update(
                initial_vwc=.16 if water == "dry" else .45,
                NAVAILI=1. if nitrogen == "low" else 60.,
                NSOILBASE=2. if nitrogen == "low" else 80.)
            world = PaddyWorldApp(field=field, weather={"rain_mm": 0.})
            plot, backend = world.plot("p1"), world.backends["p1"]
            backend.apply("puddle", sope_cm_day=1., ksub_cm_day=.2)
            backend.apply("transplant", day=backend.model.day.isoformat())
            plot.planted = True
            rows = []
            for _ in range(7):
                if water == "wet" and backend.water.ledger()["surface_water_mm"] < 20:
                    backend.apply("water", amount_mm=40.)
                backend.apply("day", day=backend.model.day.isoformat(), weather=world.weather_for(backend.model.day))
                rows.append(crop_report(world, plot))
            results[f"{water}_{nitrogen}_n"] = rows
    separated = [low["nitrogen_signal_date"] for low, high in
                 zip(results["wet_low_n"], results["wet_high_n"])
                 if low["nitrogen_stress_signal"] == "elevated" and high["nitrogen_stress_signal"] == "low"]
    days = [date.fromisoformat(day) for day in separated]
    three_consecutive = any((days[i+2]-days[i]).days == 2 for i in range(len(days)-2))
    return {"experiment": "isolated 2x2 WOFOST81 juvenile-N proxy; fixed IR72 structural-transfer parameters",
            "days": 7, "required_separation_days": 3,
            "separated_wet_n_dates": separated,
            "three_day_n_observability_gate": three_consecutive,
            "groups": results}


if __name__ == "__main__":
    print(json.dumps(probe(), ensure_ascii=False, indent=2, allow_nan=False))
