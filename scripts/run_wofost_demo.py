"""Run a synthetic sowing-to-harvest FAIRY/WOFOST season without an LLM.

The field starts prepared and unplanted. All subsequent crop operations use
the real app tools, and SystemApp advances the shared Engine clock. Weather
is deliberately synthetic; this is an integration demonstration, not a
calibrated agronomic trial or management recommendation.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from fairy.apps.farm_world import FarmWorldApp, WeatherApp
from fairy.apps.farm_world.field_ops_app import FieldOpsApp
from fairy.apps.farm_world.farm_world_app import FIELD_LENGTH_M
from fairy.apps.farm_world.tractor_app import TractorApp
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
from fairy.scenarios.fos.provenance import crop_backend_provenance
from fairy.scenarios.scenario import Scenario


SOWING_DATE = date(2026, 5, 1)


class WofostDemoScenario(Scenario):
    """Small bare field; preparation is part of the initial scenario state."""

    def init_and_populate_apps(self, *, ridges: int = 1, max_days: int = 220) -> None:
        farm = FarmWorldApp()
        # Set field size before the lazy physics container is constructed.
        farm.num_ridges = ridges
        farm._ridges = farm._ridges[:ridges]
        for ridge in farm._ridges:
            ridge.soil_vwc = 0.26
            ridge.soil_temp_c = 18.0
            ridge.pest_pressure_base = ridge.pest_pressure = 0.0
            ridge.disease_pressure_base = ridge.disease_pressure = 0.0
        weather = WeatherApp()
        weather.set_weather(
            date=SOWING_DATE.isoformat(), temp_c=22.0, humidity_pct=55.0,
            wind_speed_ms=2.0, rainfall_mm=0.0,
            solar_radiation=20.0 / 0.0864, avg_soil_vwc=0.26,
            forecast=[{
                "date": (SOWING_DATE + timedelta(days=offset)).isoformat(),
                "temp_c": 22.0, "humidity_pct": 55.0, "wind_speed_ms": 2.0,
                "rainfall_mm": 0.0, "solar_radiation": 20.0 / 0.0864,
            } for offset in range(1, max_days + 10)],
        )
        tractor = TractorApp(farm, weather)
        tractor.load_state({
            "completed_prep_ops": ["level", "base_fertilize", "form_ridges"],
        })
        self.apps = [farm, weather, tractor, FieldOpsApp(farm, weather), SystemApp()]


def run_demo(*, output_dir: Path, ridges: int, max_days: int,
             backend_options: dict[str, Any]) -> dict[str, Any]:
    scenario = WofostDemoScenario(
        scenario_id="wofost_integration_demo",
        start_time=datetime.combine(SOWING_DATE, time(8), timezone.utc).timestamp(),
        crop_backend="wofost", crop_backend_options=backend_options,
    )
    scenario.initialize(ridges=ridges, max_days=max_days)
    engine = Engine(agent=None, scenario=scenario)
    farm = scenario.get_typed_app(FarmWorldApp)
    tractor = scenario.get_typed_app(TractorApp)
    field_ops = scenario.get_typed_app(FieldOpsApp)
    system = scenario.get_typed_app(SystemApp)
    physics = farm.physics

    calls: list[dict[str, Any]] = []

    def call(tool, **kwargs):
        result = tool(**kwargs)
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(f"{tool.__qualname__} failed: {result['error']}")
        calls.append({
            "tool": tool.__qualname__, "arguments": kwargs,
            "sim_time": engine.time_manager.time(), "result": result,
        })
        return result

    call(tractor.load_seeds, seed_type="STANDARD", count=15000 * ridges)
    call(tractor.load_fertilizer, kg=2.0 * ridges)
    call(tractor.plant_seeds, start_ridge=0, end_ridge=ridges - 1,
         depth_cm=4.0, seed_spacing_cm=4.5)

    rows: list[dict[str, Any]] = []
    fertilizer_applied = False
    scheduled_irrigation_applied = False
    harvest_result = None
    advances = 0

    def record_daily() -> None:
        snapshot = physics.crop_backend.snapshot()
        for ridge_id in range(ridges):
            native = snapshot["ridges"].get(str(ridge_id), {})
            pcse = native.get("pcse", {})
            phen = physics.phenology.states[ridge_id]
            recovery = physics.yield_recovery.states[ridge_id]
            rows.append({
                "date": datetime.fromtimestamp(engine.time_manager.time(), timezone.utc).date().isoformat(),
                "forcing_day": native.get("last_day"), "ridge_id": ridge_id,
                "DVS": pcse.get("DVS"), "LAI_m2_m2": pcse.get("LAI"),
                "TAGP_kg_dm_ha": pcse.get("TAGP"), "TWSO_kg_dm_ha": pcse.get("TWSO"),
                "SM_m3_m3": pcse.get("SM"), "NAVAIL_kg_n_ha": pcse.get("NAVAIL"),
                "native_TSUM": pcse.get("TSUM"), "fairy_stage": phen.stage.value,
                "biological_yield_g_dm_m2": recovery.biological_yield_g_m2,
                "grain_moisture_fraction": recovery.grain_moisture_frac,
                "recovered_yield_g_m2_at_market_moisture": recovery.recovered_yield_g_m2_at_market_moisture,
                "harvested": recovery.harvested,
                "cumulative_irrigation_mm": native.get("cumulative_irrigation_mm", 0.0),
                "cumulative_fertilizer_kg": native.get("cumulative_fertilizer_kg", 0.0),
            })

    for _ in range(max_days):
        today = datetime.fromtimestamp(engine.time_manager.time(), timezone.utc).date()
        day_after_sowing = (today - SOWING_DATE).days
        mature = all(state.r8_reached for state in physics.yield_recovery.states.values())
        if not mature:
            average_root_vwc = sum(s.root_vwc for s in physics.soil.states.values()) / ridges
            due = day_after_sowing >= 20 and not scheduled_irrigation_applied
            if due or (day_after_sowing >= 7 and average_root_vwc < 0.22):
                call(field_ops.irrigate, start=0, end=ridges - 1, hours=2.0)
                scheduled_irrigation_applied = scheduled_irrigation_applied or due
            if day_after_sowing >= 30 and not fertilizer_applied:
                call(tractor.apply_fertilizer, start_ridge=0, end_ridge=ridges - 1,
                     kg_per_ridge=2.0)
                fertilizer_applied = True
        ready = mature and all(
            state.grain_moisture_frac is not None and state.grain_moisture_frac <= 0.15
            for state in physics.yield_recovery.states.values()
        )
        if ready:
            harvest_result = call(tractor.harvest, start_ridge=0, end_ridge=ridges - 1)
            call(tractor.unload_grain)
            record_daily()
            break
        # Keep the next reading at 08:00 UTC despite hours spent on operations.
        now = engine.time_manager.time()
        next_reading = datetime.combine(today + timedelta(days=1), time(8), timezone.utc).timestamp()
        call(system.advance_time, seconds=max(1, math.ceil(next_reading - now)))
        advances += 1
        record_daily()

    area_m2 = FIELD_LENGTH_M * farm.ridge_width_m
    backend_snapshot = physics.crop_backend.snapshot()
    recovery = physics.yield_recovery.states
    summary = {
        "success": harvest_result is not None and all(s.harvested for s in recovery.values()),
        "scenario_id": scenario.scenario_id,
        "description": "Synthetic tool-driven sowing-to-harvest integration demo; no LLM and no field calibration.",
        "ridges": ridges, "ridge_area_m2": area_m2, "sowing_date": SOWING_DATE.isoformat(),
        "end_date": datetime.fromtimestamp(engine.time_manager.time(), timezone.utc).date().isoformat(),
        "daily_time_advances": advances,
        "biological_yield_kg_dm_total": sum(s.biological_yield_g_m2 for s in recovery.values()) * area_m2 / 1000,
        "recovered_yield_kg_at_market_moisture_total": sum(
            s.recovered_yield_g_m2_at_market_moisture for s in recovery.values()
        ) * area_m2 / 1000,
        "market_moisture_fraction": physics.yield_recovery.params.market_moisture_frac,
        "fertilizer_applied": fertilizer_applied,
        "scheduled_irrigation_applied": scheduled_irrigation_applied,
        "crop_backend_provenance": crop_backend_provenance(physics),
        "native_backend": backend_snapshot,
        "yield_recovery": {str(rid): vars(state) for rid, state in recovery.items()},
        "operation_calls": [item for item in calls if item["tool"] != "SystemApp.advance_time"],
        "artifacts": {"daily_csv": str(output_dir / "daily.csv"), "summary_json": str(output_dir / "summary.json")},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "daily.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    if not summary["success"]:
        raise RuntimeError(f"Crop was not harvested within {max_days} daily advances; inspect {output_dir / 'summary.json'}")
    if not fertilizer_applied or not scheduled_irrigation_applied:
        raise RuntimeError("Demo ended before the scheduled fertilizer and irrigation operations")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ridges", type=int, choices=(1, 4), default=1)
    parser.add_argument("--max-days", type=int, default=220)
    parser.add_argument("--wofost-config", type=Path, help="Optional JSON object of WofostConfig settings")
    parser.add_argument("--output-dir", type=Path,
                        default=REPO_ROOT / "validation_runs/wofost_integration_demo")
    args = parser.parse_args()
    if args.max_days < 1:
        parser.error("--max-days must be positive")
    options = {}
    if args.wofost_config is not None:
        options = json.loads(args.wofost_config.expanduser().read_text(encoding="utf-8"))
        if not isinstance(options, dict):
            parser.error("--wofost-config must contain a JSON object")
    summary = run_demo(output_dir=args.output_dir.expanduser().resolve(), ridges=args.ridges,
                       max_days=args.max_days, backend_options=options)
    print(json.dumps({key: summary[key] for key in (
        "success", "ridges", "sowing_date", "end_date", "biological_yield_kg_dm_total",
        "recovered_yield_kg_at_market_moisture_total", "artifacts",
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
