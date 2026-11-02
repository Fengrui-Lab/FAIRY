"""Offline public-tool search; no runtime optimizer or hidden crop-state policy."""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, date, time, timedelta
import json
from pathlib import Path
from fairy.controllers.engine import Engine
from fairy.apps.farm_world import (
    FarmWorldApp,
    TractorApp,
    WeatherApp,
    FieldOpsApp,
    SensorApp,
)
from fairy.apps.system import SystemApp
from .scene import TwoYearMaizeScenario


def run_candidate(first_fertilizer=600.0, first_water=200.0):
    scene = TwoYearMaizeScenario(calibrating=True)
    scene.setup()
    engine = Engine(None, scene)
    engine.build_oracle_workflow(False)
    farm = scene.get_typed_app(FarmWorldApp)
    tractor = scene.get_typed_app(TractorApp)
    weather = scene.get_typed_app(WeatherApp)
    sensor = scene.get_typed_app(SensorApp)
    ops = scene.get_typed_app(FieldOpsApp)
    system = scene.get_typed_app(SystemApp)
    trace = []

    def call(app, method, **args):
        before = engine.time_manager.time()
        result = getattr(app, method)(**args)
        trace.append(
            {
                "app": app.name,
                "method": method,
                "args": args,
                "time_before": before,
                "time_after": engine.time_manager.time(),
                "result": result,
            }
        )
        if isinstance(result, dict) and (
            "error" in result or result.get("status") in ("failed", "partial")
        ):
            raise ValueError(f"{app.name}.{method}: {result}")
        return result

    def until(day):
        target = datetime.combine(day, time(7), farm.simulation_timezone).timestamp()
        if target > engine.time_manager.time():
            call(system, "advance_time", seconds=target - engine.time_manager.time())

    try:
        for year, fertilizer, water in [
            (2026, first_fertilizer, first_water),
            (2027, 1200 - first_fertilizer, 400 - first_water),
        ]:
            sow = date(year, 5, 5)
            until(sow)
            if year == 2027:
                call(scene.cycle, "open_next_season", year=year)
            call(weather, "get_current_weather")
            inventory = call(farm, "get_inventory")
            if year == 2027:
                water = min(
                    300.0,
                    400.0 - inventory["management_regime"]["irrigation_used_mm_total"],
                )
            call(tractor, "attach_implement", implement="grader")
            call(tractor, "level")
            call(tractor, "detach_implement")
            call(tractor, "load_fertilizer", kg=200.0)
            call(tractor, "base_fertilize", total_kg=200.0)
            call(tractor, "attach_implement", implement="furrower")
            call(tractor, "form_ridges", ridge_width_m=0.75)
            call(tractor, "detach_implement")
            call(tractor, "load_seeds", seed_type="MAIZE_201", count=85760)
            for start in range(0, 64, 4):
                call(
                    tractor,
                    "plant_seeds",
                    start_ridge=start,
                    end_ridge=start + 3,
                    depth_cm=4.0,
                    seed_spacing_cm=20.0,
                )
            call(farm, "commit_daily_physics")
            for day in sorted({15, 30, 20, 60, 70, 80}):
                until(sow + timedelta(days=day))
                call(weather, "get_forecast", days=7)
                call(farm, "get_farm_overview")
                if day in (15, 30) and fertilizer > 200:
                    call(
                        farm,
                        "apply_fertigation",
                        start_ridge=0,
                        end_ridge=63,
                        nutrient_amount=(fertilizer - 200) / 2 / (30 * 64),
                        water_mm=0.0,
                    )
                if day in (20, 60, 70, 80) and water:
                    observation = call(sensor, "read_soil_sensors")
                    readings = observation["soil_sensors"]
                    if readings and all(probe["vwc"] < 0.28 for probe in readings):
                        call(ops, "irrigate", start=0, end=63, hours=water / 4 / 5)
            # Public maturity and weather observations determine harvest readiness.
            for day in range(99, 171):
                until(sow + timedelta(days=day))
                state = call(farm, "get_ridge_range_state", start=0, end=63)
                conditions = call(weather, "get_current_weather")
                rows = state.get("ridges", []) if isinstance(state, dict) else state
                if (
                    rows
                    and all(
                        r.get("growth_stage") in ("MATURE", "R8")
                        and r.get("grain_moisture_pct", 100) <= 25
                        for r in rows
                    )
                    and conditions.get("rainfall_mm", 0) == 0
                ):
                    break
            call(tractor, "refuel", liters=100.0)
            for start in range(0, 64, 4):
                call(tractor, "harvest", start_ridge=start, end_ridge=start + 3)
                call(tractor, "unload_grain")
            call(farm, "dry_grain", target_moisture_pct=14.0)
            call(farm, "store_grain")
            call(scene.cycle, "close_season", year=year)
        validation = scene.validate()
        if not validation.success:
            raise ValueError(f"Final scenario validation failed: {validation.message}")
        return {
            "feasible": True,
            "input_fingerprint": scene.input_fingerprint,
            "input_signature": scene.input_signature,
            "first_fertilizer": first_fertilizer,
            "first_water": first_water,
            "stored_grain_kg": sum(r["stored_grain_kg"] for r in scene.cycle.closed),
            "seasons": scene.cycle.closed,
            "trace": trace,
            "validation": validation.success,
            "soil_audit": {
                "first_close_ridge_0": scene.cycle.closed[0]["native_soil_pools"]["0"],
                "second_start_ridge_0": farm.physics.crop_backend.season_history[0][
                    "soil_before"
                ],
                "final_ridge_0": farm.physics.crop_backend._soil_pools(
                    farm.physics.crop_backend._runs[0].model
                ),
                "second_start_count": len(farm.physics.crop_backend.season_history),
                "all_transitions_conserve_pools": all(
                    row["soil_before"] == row["soil_after"]
                    for row in farm.physics.crop_backend.season_history
                ),
            },
        }
    except Exception as exc:
        return {
            "feasible": False,
            "input_fingerprint": scene.input_fingerprint,
            "input_signature": scene.input_signature,
            "first_fertilizer": first_fertilizer,
            "first_water": first_water,
            "error": repr(exc),
            "trace": trace,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    grid = (
        [(600.0, 200.0)]
        if args.smoke
        else [
            (fertilizer, water)
            for fertilizer in (400.0, 600.0, 800.0)
            for water in (100.0, 200.0, 300.0)
        ]
    )
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs = {pool.submit(run_candidate, *candidate): candidate for candidate in grid}
        for future in as_completed(jobs):
            result = future.result()
            fertilizer, water = jobs[future]
            (args.output / f"f{fertilizer:g}_w{water:g}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2, default=str)
            )
            rows.append({key: value for key, value in result.items() if key != "trace"})
            print(
                fertilizer,
                water,
                result["feasible"],
                result.get("stored_grain_kg"),
                result.get("error"),
                flush=True,
            )
    (args.output / "summary.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2, default=str)
    )


if __name__ == "__main__":
    main()
