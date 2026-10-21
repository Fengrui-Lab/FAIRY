"""Retrospective full-field FAIRY/WOFOST acceptance run with real app tools.

Not a calibrated cultivar trial. Configuration is frozen before either run.
Daily CSV is post-integration truth; observations/actions are logged separately.
Run with PCSE 6.0.x, e.g. env -u USER python scripts/run_wofost_managed_season.py.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fairy.apps.farm_world import FarmWorldApp, WeatherApp, SensorApp, RobotApp
from fairy.apps.farm_world import physics_orchestrator
from fairy.apps.farm_world.field_ops_app import FieldOpsApp
from fairy.apps.farm_world.tractor_app import TractorApp, split_pass
from fairy.apps.farm_world.farm_world_app import FIELD_LENGTH_M, plants_per_ridge_from_spacing
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.fos.provenance import crop_backend_provenance
from scripts.check_wofost_real_weather_parity import load_weather

START = date(2017, 5, 8)
SOW = date(2017, 5, 10)
END = date(2017, 10, 25)
N_RIDGES = 64
WIDTH = 1.1
SPACING = 7.9
CONFIG = {
    "variety_name": "Soybean_901", "co2_ppm": 400.0,
    "fertilizer_n_fraction": 0.18, "fertilizer_n_recovery": 0.7,
    "soil_overrides": {"RDMSOL": 120.0},
}
POLICY = {
    "irrigation_trigger_sensor_vwc": 0.22, "irrigation_mm_per_event": 20.0,
    "irrigation_season_max_mm": 120.0, "minimum_gap_days": 5,
    "irrigation_rain_today_max_mm": 1.0,
    "topdress_rule": "Only if native RFRGRL <0.9 and NAVAIL <10 kg N/ha; once, 1 kg product/ridge",
    "biotic_rule": "Weekly sentinel confirmation >=0.6 confidence; affected zones only on sprayable days, at least14 days apart and DVS<1.8; simulator mixture dose5L/ridge",
    "weed_rule": "Weekly 6-zone sentinel inspection; mechanical control of detected zones before DVS 1.0, at most twice/zone",
    "harvest_rule": "All ridges R8; grain <=18%; actual day rain=0; trafficable soil <=0.35; then dry to13 and store",
}


def stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class ManagedScenario(Scenario):
    def init_and_populate_apps(self):
        farm, weather = FarmWorldApp(), WeatherApp()
        farm.set_season_phase("full_season")
        farm.ridge_width_m = WIDTH
        for ridge in farm._ridges:
            ridge.soil_vwc, ridge.soil_temp_c = 0.28, 12.0
            ridge.pest_pressure_base = ridge.pest_pressure = 0.0
            ridge.disease_pressure_base = ridge.disease_pressure = 0.0
        farm._inventory.seed_stock["STANDARD"] = 600000
        farm._inventory.fertilizer_kg = 1000.0
        farm._inventory.fuel_liters = 1200.0
        farm._inventory.pesticide_liters = 2500.0
        self.apps = [farm, weather, SensorApp(farm), RobotApp(farm, weather, name="Robot0"),
                     TractorApp(farm, weather), FieldOpsApp(farm, weather), SystemApp()]
        physics = farm.physics
        physics.soil.params = replace(physics.soil.params, root_depth_m=1.2)


def run_case(output, forcing, metadata, supplemental_irrigation):
    output.mkdir(parents=True, exist_ok=True)
    random.seed(1729)
    scenario = ManagedScenario(scenario_id="managed_wofost_2017", crop_backend="wofost",
                               crop_backend_options=CONFIG,
                               start_time=datetime.combine(START, time(8), timezone.utc).timestamp())
    scenario.initialize()
    engine = Engine(agent=None, scenario=scenario)
    farm = scenario.get_typed_app(FarmWorldApp)
    weather = scenario.get_typed_app(WeatherApp)
    sensor = scenario.get_typed_app(SensorApp)
    tractor = scenario.get_typed_app(TractorApp)
    robot = scenario.get_typed_app(RobotApp, "Robot0")
    field = scenario.get_typed_app(FieldOpsApp)
    system = scenario.get_typed_app(SystemApp)
    for app in scenario.apps:
        app.rng.seed(1729)
    physics = farm.physics
    by_day = {w.day: (w, rh) for w, rh in forcing}
    for w, rh in forcing:
        physics.set_weather_day_override(w.day, air_temp_mean_c=w.air_temp_mean_c,
            air_temp_min_c=w.air_temp_min_c, air_temp_max_c=w.air_temp_max_c,
            rain_mm=w.rain_mm, wind_ms=w.wind_ms, solar_rad_mj_m2=w.solar_rad_mj_m2)
    calls, rows, flux, stored, warnings = [], [], {}, set(), []
    operation_file = (output / "operations.jsonl").open("w", encoding="utf-8")

    def call(tool, **kwargs):
        before = engine.time_manager.time()
        result = tool(**kwargs)
        record = {"tool": tool.__qualname__, "arguments": kwargs,
                  "start_time_utc": stamp(before), "end_time_utc": stamp(engine.time_manager.time()),
                  "result": result}
        calls.append(record)
        operation_file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        operation_file.flush()
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(f"{tool.__qualname__}: {result['error']}")
        if tool.__name__ == "store_grain":
            stored.update(result.get("batch_ridge_ids", []))
            if result.get("warning"):
                warnings.append(result["warning"])
        return result

    def set_current(day):
        w, _ = by_day[day]
        weather.set_weather(date=day.isoformat(), temp_c=w.air_temp_mean_c,
            humidity_pct=55.0, rainfall_mm=w.rain_mm, wind_speed_ms=w.wind_ms,
            solar_radiation=w.solar_rad_mj_m2 / 0.0864, avg_soil_vwc=0.28, forecast=[])

    def ensure_fuel():
        fuel = call(tractor.get_status)["fuel_tank_l"]
        if fuel < 15.0:
            call(tractor.refuel, liters=100.0 - fuel)

    def instrument_native(run, entry):
        def storage():
            return sum(float(run.model.get_variable(key) or 0.0) for key in ("W", "WLOW", "SS")) * 10
        before = storage()
        cumulative_keys = ("TOTIRR", "EVST", "EVWT", "WTRAT", "TSR", "LOSST")
        before_cumulative = {key: float(run.model.get_variable(key) or 0) for key in cumulative_keys}
        original_native(run, entry)
        delta = {key: (float(run.model.get_variable(key) or 0)-before_cumulative[key])*10
                 for key in cumulative_keys}
        outgoing = sum(delta[key] for key in ("EVST", "EVWT", "WTRAT", "TSR", "LOSST"))
        change = storage() - before
        flux[(entry["day"], id(run))] = {
            "storage_start_mm": before, "storage_end_mm": storage(),
            "effective_irrigation_mm": delta["TOTIRR"],
            "evaporation_mm": delta["EVST"], "surface_evaporation_mm": delta["EVWT"],
            "transpiration_mm": delta["WTRAT"], "runoff_mm": delta["TSR"], "bottom_drainage_mm": delta["LOSST"],
            "water_balance_residual_mm": entry["weather"]["rain_mm"] + delta["TOTIRR"] - outgoing - change,
        }

    backend = physics.crop_backend
    original_native = backend._advance_native
    backend._advance_native = instrument_native
    original_tick = physics_orchestrator._run_daily_tick

    def recorded_tick(tick_farm, tick_physics, tick_weather, day):
        result = original_tick(tick_farm, tick_physics, tick_weather, day)
        if tick_farm is not farm:
            return result
        w, rh = by_day[day]
        for rid, phen in physics.phenology.states.items():
            run = backend._runs.get(rid)
            p = run.pcse if run else {}
            s, c, y = physics.soil.states[rid], physics.canopy.states[rid], physics.yield_recovery.states[rid]
            native_in = run.last_native_inputs if run else {}
            rows.append({
                "forcing_day": day.isoformat(), "observed_at_utc": stamp(engine.time_manager.time()),
                "ridge_id": rid, "stage": phen.stage.value, "emerged": phen.emerged,
                "emergence_date": str(phen.emergence_date or ""), "maturity_date": str(phen.maturity_date or ""),
                "harvest_date": str(y.harvest_date or ""), "r8_reached": y.r8_reached, "harvested": y.harvested,
                "rain_mm": w.rain_mm, "tmean_c": w.air_temp_mean_c, "tmin_c": w.air_temp_min_c,
                "tmax_c": w.air_temp_max_c, "radiation_mj_m2": w.solar_rad_mj_m2,
                "wind_ms": w.wind_ms, "used_rh_pct": 55, "source_rh_pct": rh,
                "DVS": p.get("DVS"), "LAI": p.get("LAI"), "TAGP_kg_dm_ha": p.get("TAGP"),
                "TWSO_kg_dm_ha": p.get("TWSO"), "root_depth_cm": p.get("RD"),
                "SM": p.get("SM"), "sensor_proxy_top_vwc": s.top_vwc, "soil_temperature_c": s.top_temp_c,
                "NAVAIL_kg_n_ha": p.get("NAVAIL"), "RFTRA": p.get("RFTRA"), "RFRGRL": p.get("RFRGRL"),
                "irrigation_gross_mm": native_in.get("irrigation_mm", 0),
                "n_applied_kg_ha": native_in.get("n_kg_ha", 0) + native_in.get("preplant_n_kg_ha", 0),
                "evaporation_mm": float(p.get("EVS") or 0) * 10,
                "transpiration_mm": float(p.get("TRA") or 0) * 10,
                "runoff_mm": float(p.get("DTSR") or 0) * 10,
                "bottom_drainage_mm": float(p.get("LOSS") or 0) * 10,
                "grain_moisture_pct": (y.grain_moisture_frac or 0) * 100,
                "biological_yield_g_dm_m2": y.biological_yield_g_m2,
                "field_loss_fraction": y.field_loss_fraction, "machine_loss_fraction": y.machine_loss_fraction,
                "external_growth_factor": native_in.get("external_growth_factor"),
                "weed_pressure": physics.biotic.states[rid].weed_pressure,
                "insect_pressure": physics.biotic.states[rid].insect_pressure,
                "disease_pressure": physics.biotic.states[rid].disease_pressure,
                "recovered_yield_g_m2_at_13pct": y.recovered_yield_g_m2_at_market_moisture,
                **flux.get((day.isoformat(), id(run)), {
                    "storage_start_mm": None, "storage_end_mm": None, "effective_irrigation_mm": 0, "surface_evaporation_mm": 0,
                    "water_balance_residual_mm": None}),
            })
        return result

    physics_orchestrator._run_daily_tick = recorded_tick
    error = None
    irrigation_total, last_irrigation, topdressed = 0, None, False
    weed_counts = {i: 0 for i in range(6)}
    last_treatment = {}
    try:
        set_current(START)
        call(tractor.attach_implement, implement="grader")
        call(tractor.level)
        call(tractor.detach_implement)
        call(tractor.load_fertilizer, kg=300.0)
        call(tractor.base_fertilize)
        call(tractor.attach_implement, implement="furrower")
        call(tractor.form_ridges, ridge_width_m=WIDTH)
        call(tractor.detach_implement)
        planted = False
        while True:
            today = datetime.fromtimestamp(engine.time_manager.time(), timezone.utc).date()
            if today > END:
                raise RuntimeError("Season deadline reached before safe storage")
            set_current(today)
            readings = call(sensor.read_soil_sensors)["soil_sensors"]
            call(farm.get_ridge_range_state, start=0, end=63)
            if not planted and today >= SOW:
                if min(s["temp_c"] for s in readings) > 10 and all(.20 <= s["vwc"] <= .35 for s in readings):
                    count = plants_per_ridge_from_spacing(SPACING)
                    for start, end in split_pass(0, 63, 4):
                        ensure_fuel()
                        needed = count * (end-start+1)
                        if tractor._seed_hopper < needed:
                            call(tractor.load_seeds, seed_type="STANDARD", count=300000-tractor._seed_hopper)
                        call(tractor.plant_seeds, start_ridge=start, end_ridge=end, depth_cm=4.0, seed_spacing_cm=SPACING)
                    planted = True
            mature = planted and all(y.r8_reached for y in physics.yield_recovery.states.values())
            if planted and not mature and today >= SOW + timedelta(days=7):
                mean_sensor = sum(s["vwc"] for s in readings) / len(readings)
                dry_window = by_day[today][0].rain_mm < POLICY["irrigation_rain_today_max_mm"]
                gap_ok = last_irrigation is None or (today-last_irrigation).days >= POLICY["minimum_gap_days"]
                if supplemental_irrigation and mean_sensor < .22 and dry_window and gap_ok and irrigation_total < 120:
                    # All zones must be eligible: the real tool rejects a wet ridge.
                    if max(s.root_vwc for s in physics.soil.states.values()) < .30:
                        call(field.irrigate, start=0, end=63, hours=4.0)
                        irrigation_total += 20
                        last_irrigation = today
                p = backend._runs.get(0)
                if p and not topdressed and float(p.pcse.get("RFRGRL") or 1) < .9 and float(p.pcse.get("NAVAIL") or 0) < 10:
                    for start, end in split_pass(0, 63, 10):
                        ensure_fuel()
                        call(tractor.apply_fertilizer, start_ridge=start, end_ridge=end, kg_per_ridge=1.0)
                    topdressed = True
                das = (today-SOW).days
                if das % 7 == 0:
                    # Six sentinels cover each installed sensor zone (2 ridges each).
                    if robot._charging:
                        call(robot.check_status)
                    for zone, first in enumerate((0,11,22,33,44,54)):
                        if robot._battery_pct < 25:
                            break
                        observation = call(robot.inspect_crop_health, start_ridge=first, end_ridge=first+1)
                        detected = any(item["weed_present"] and item["weed_confidence"] >= .6
                                       for item in observation["observations"].values())
                        if detected and weed_counts[zone] < 2 and float(p.pcse.get("DVS") or 0) < 1 and weather.rainfall_mm == 0:
                            last = (10,21,32,43,53,63)[zone]
                            for start,end in split_pass(first,last,10):
                                ensure_fuel()
                                call(tractor.mechanical_weed_control, start_ridge=start,end_ridge=end)
                            weed_counts[zone] += 1
                        if weather.is_sprayable and max(s.top_vwc for s in physics.soil.states.values()) <= .35 and float(p.pcse.get("DVS") or 0) < 1.8:
                            for kind in ("pest", "disease"):
                                confirmed = any(item[f"{kind}_present"] and item[f"{kind}_confidence"] >= .6
                                                for item in observation["observations"].values())
                                key = (zone, kind)
                                if confirmed and (key not in last_treatment or (today-last_treatment[key]).days >= 14):
                                    last = (10,21,32,43,53,63)[zone]
                                    volume = (last-first+1)*5.0
                                    if kind == "pest":
                                        call(tractor.refill_pesticide_tank, liters=volume)
                                        spray = tractor.spray_pesticide
                                    else:
                                        call(tractor.load_fungicide, liters=volume)
                                        spray = tractor.apply_fungicide
                                    for start,end in split_pass(first,last,10):
                                        ensure_fuel()
                                        call(spray, start_ridge=start, end_ridge=end, liters_per_ridge=5.0)
                                    last_treatment[key] = today
                    call(robot.charge)
            mature = planted and all(y.r8_reached for y in physics.yield_recovery.states.values())
            grain_ready = mature and all((y.grain_moisture_frac or 1) <= .18 for y in physics.yield_recovery.states.values())
            if grain_ready and weather.rainfall_mm == 0 and max(s.top_vwc for s in physics.soil.states.values()) <= .35:
                call(tractor.attach_implement, implement="harvester")
                for start,end in split_pass(0,63,4):
                    ensure_fuel()
                    call(tractor.harvest, start_ridge=start, end_ridge=end)
                    call(tractor.unload_grain)
                call(farm.dry_grain, target_moisture_pct=13.0)
                call(farm.store_grain)
                break
            next_morning = datetime.combine(today+timedelta(days=1), time(8), timezone.utc).timestamp()
            if engine.time_manager.time() >= next_morning:
                raise RuntimeError("Management overran next daily decision; do not silently skip dates")
            call(system.advance_time, seconds=math.ceil(next_morning-engine.time_manager.time()))
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        physics_orchestrator._run_daily_tick = original_tick
        backend._advance_native = original_native
        operation_file.close()
    area = FIELD_LENGTH_M * WIDTH * N_RIDGES
    mu = area / (2000/3)
    recovery = physics.yield_recovery.states
    native_rows = [r for r in rows if r["DVS"] is not None]
    residuals = [abs(r["water_balance_residual_mm"]) for r in native_rows]
    biological = sum(y.biological_yield_g_m2 for y in recovery.values()) * (area/N_RIDGES) / 1000
    recovered = sum(y.recovered_yield_g_m2_at_market_moisture for y in recovery.values()) * (area/N_RIDGES) / 1000
    harvest_kg = sum(c["result"].get("grain_kg_added",0) for c in calls if c["tool"].endswith(".harvest"))
    warehouse = farm._inventory.warehouse_grain_kg
    checks = {
        "no_exception": error is None, "native_ridges_64": len(backend._runs)==64,
        "all_planted": all(p.planting_date is not None for p in physics.phenology.states.values()),
        "all_mature": all(y.r8_reached for y in recovery.values()),
        "all_harvested": all(y.harvested for y in recovery.values()),
        "all_safely_stored": stored == set(range(64)) and not warnings,
        "grain_bin_empty": tractor._grain_bin_kg == 0,
        "trailer_empty": farm._inventory.harvest_grain_kg == 0,
        "mass_accounting": abs(harvest_kg-recovered)<.1 and abs(warehouse-recovered)<.5,
        "native_water_balance": bool(residuals) and max(residuals)<1e-7,
        "irrigation_reaches_native": all(abs(run.cumulative_irrigation_mm-irrigation_total)<1e-9
                                          and abs(run.pcse["TOTIRR"]*10-irrigation_total*.92)<1e-8 for run in backend._runs.values()),
        "fertilizer_reaches_native": all(abs(run.cumulative_fertilizer_kg-(200/64+(1 if topdressed else 0)))<1e-9
                                           and abs(run.cumulative_n_kg_ha-run.cumulative_fertilizer_kg*.18*10000/(area/64))<1e-8 for run in backend._runs.values()),
        "soil_bounds": all(0<=r["SM"]<=.48+1e-8 for r in native_rows),
        "stress_bounds": all(0<=float(r["RFTRA"] or 0)<=1+1e-8 and 0<=float(r["RFRGRL"] or 0)<=1+1e-8 for r in native_rows),
    }
    summary = {
        "success": all(checks.values()), "checks": checks, "error": error,
        "case": "managed" if supplemental_irrigation else "rainfed", "area_m2": area, "area_mu": mu,
        "density_plants_m2": plants_per_ridge_from_spacing(SPACING)/(area/N_RIDGES),
        "seed_spacing_cm": SPACING, "seed_type": "STANDARD", "native_variety": "Soybean_901",
        "sowing_dates": sorted({str(p.planting_date) for p in physics.phenology.states.values()}),
        "emergence_dates": sorted({str(p.emergence_date) for p in physics.phenology.states.values()}),
        "maturity_dates": sorted({str(p.maturity_date) for p in physics.phenology.states.values()}),
        "harvest_dates": sorted({str(y.harvest_date) for y in recovery.values()}),
        "end_time_utc": stamp(engine.time_manager.time()), "daily_forcing_days": len({r["forcing_day"] for r in rows}),
        "biological_yield_kg_dry_total": biological, "biological_yield_kg_dry_per_mu": biological/mu,
        "recovered_yield_kg_at_13pct_total": recovered, "recovered_yield_kg_at_13pct_per_mu": recovered/mu,
        "harvest_tool_kg": harvest_kg, "warehouse_kg_at_13pct": warehouse,
        "irrigation_gross_mm": irrigation_total, "topdress_applied": topdressed,
        "weed_control_counts_by_zone": weed_counts,
        "bottom_drainage_mm_ridge0": sum(r["bottom_drainage_mm"] for r in native_rows if r["ridge_id"]==0),
        "rain_mm_during_native_ridge0": sum(r["rain_mm"] for r in native_rows if r["ridge_id"]==0),
        "max_water_balance_residual_mm": max(residuals,default=None), "storage_warnings": warnings,
        "final_native_snapshot": backend.snapshot(),
        "yield_recovery": {str(k):vars(v) for k,v in recovery.items()},
        "provenance": crop_backend_provenance(physics), "weather_source": metadata,
        "limitations": ["Uncalibrated native Soybean_901; not a named Heilongjiang cultivar",
            "120cm homogeneous assumed soil; no field measurements", "Source daily mean/min/max/rain/radiation/wind retained; RH fixed55% by current generator bridge",
            "Retrospective known same-day weather; not a forecast skill test", "Density only scales TDWI; P/K and fertilizer chemistry not modeled",
            "WOFOST crop/soil plus FAIRY empirical biotic, stand, grain drying and recovery models"],
    }
    (output/"final_ridges.json").write_text(json.dumps({
        str(rid): {"phenology": vars(physics.phenology.states[rid]), "recovery": vars(y)}
        for rid,y in recovery.items()},ensure_ascii=False,indent=2,default=str))
    write_csv(output/"daily_by_ridge.csv", rows)
    averages = []
    text_columns = {"forcing_day", "observed_at_utc", "ridge_id", "stage", "emergence_date", "maturity_date", "harvest_date"}
    numeric = [key for key in rows[0] if key not in text_columns
               and any(isinstance(r[key], (int, float)) for r in rows)] if rows else []
    for day in sorted({r["forcing_day"] for r in rows}):
        group = [r for r in rows if r["forcing_day"]==day]
        record = {"forcing_day":day, "stages":"|".join(sorted({r["stage"] for r in group}))}
        for key in numeric:
            values = [r[key] for r in group if isinstance(r[key],(int,float))]
            record[key] = sum(values)/len(values) if values else None
        averages.append(record)
    write_csv(output/"daily_field_mean.csv",averages)
    (output/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str))
    print(json.dumps({k:v for k,v in summary.items() if k not in ("final_native_snapshot","yield_recovery","provenance","weather_source")},ensure_ascii=False),flush=True)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",type=Path,default=ROOT/"validation_runs/wofost_managed_season_20261021")
    parser.add_argument("--weather",type=Path,default=ROOT/"fairy/physics/data/wofost/weather/harbin_2017_nasa_power.json")
    args=parser.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    forcing,metadata=load_weather(args.weather,START)
    frozen={"config":CONFIG,"policy":POLICY,"start":START,"sow_target":SOW,"deadline":END,
            "ridges":64,"ridge_width_m":WIDTH,"seed_spacing_cm":SPACING,
            "soil": "Homogeneous assumed loam: WP .14, FC .36, SAT .48, RDMSOL120cm; initialSM .28 and soilT12C",
            "fertilizer":"200kg basal product,18% N,70% N recovery; P/K not simulated", "weather":metadata}
    (args.output_dir/"frozen_configuration.json").write_text(json.dumps(frozen,ensure_ascii=False,indent=2,default=str))
    cases={name:run_case(args.output_dir/name,forcing,metadata,irrigation) for name,irrigation in (("managed",True),("rainfed",False))}
    (args.output_dir/"comparison.json").write_text(json.dumps({name:{k:v for k,v in s.items() if k not in ("final_native_snapshot","yield_recovery","provenance","weather_source")} for name,s in cases.items()},ensure_ascii=False,indent=2,default=str))
    return 0 if all(s["success"] for s in cases.values()) else 1

if __name__=="__main__":
    raise SystemExit(main())
