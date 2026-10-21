"""Run an external, frozen WOFOST cultivar/soil/management scenario end to end.

Example: env -u USER python scripts/run_wofost_complete_season.py --config
configs/wofost/complete_harbin_heinong84_v1.json --weather NASA_POWER.json
--output-dir validation_runs/complete_harbin --cases managed,rainfed

Uses actual app tools for every operation, including harvest/dry/store. Daily
CSV records post-integration model truth; tool observations are separately logged.
Success means integration and accounting passed, not field validation of a cultivar.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from dataclasses import asdict, replace
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
from fairy.scenarios.farm_world_fullseason_v2.wofost_complete_scenario import WofostCompleteScenario
from fairy.scenarios.fos.provenance import crop_backend_provenance
from scripts.check_wofost_real_weather_parity import load_weather

N_RIDGES = 64  # Installed six-zone sensor geometry is defined for 64 ridges.


def stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def validate_configuration(config):
    """Reject malformed executable inputs before any tool mutates the farm."""
    def finite_tree(value, location="config"):
        if isinstance(value, dict):
            for key, child in value.items():
                finite_tree(child, location+"."+key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                finite_tree(child, f"{location}[{index}]")
        elif isinstance(value, (float, int)) and not isinstance(value, bool) and not math.isfinite(value):
            raise ValueError(f"Nonfinite numeric input at {location}")
    finite_tree(config)
    start, end = date.fromisoformat(config["start_date"]), date.fromisoformat(config["deadline"])
    sow_start, sow_end = (date.fromisoformat(config["sowing_window"][key]) for key in ("start", "end"))
    if not start <= sow_start <= sow_end <= end:
        raise ValueError("Require start_date <= sowing window start <= sowing window end <= deadline")
    field, initial, backend = config["field"], config["initial_soil"], config["crop_backend_options"]
    if field["ridges"] != 64:
        raise ValueError("Complete scenario requires64 ridges for installed sensor-zone geometry")
    if not 0 < field["ridge_width_m"] <= 3 or not 1 <= field["seed_spacing_cm"] <= 100:
        raise ValueError("Require ridge width in(0,3]m and seed spacing in[1,100]cm")
    if not 3 <= field["sowing_depth_cm"] <= 5:
        raise ValueError("Actual planter requires sowing depth3–5cm")
    if field["seed_type"] not in ("STANDARD", "HEINONG84", "EARLY_COLD"):
        raise ValueError("Unsupported seed label for complete scenario")
    if field.get("assumed_establishment_fraction", 1.0) != 1.0:
        raise ValueError("Complete reference currently requires explicitly assumed100% establishment")
    if not 0 < initial["root_depth_m"] <= 3 or not 0 < initial["vwc"] < 1:
        raise ValueError("Invalid initial soil water content or profile depth")
    if "RDMSOL" in backend.get("soil_overrides", {}) and abs(backend["soil_overrides"]["RDMSOL"]-100*initial["root_depth_m"])>1e-8:
        raise ValueError("Native RDMSOL and declared soil depth must agree")
    fertilizer, policy = config["fertilizer"], config["management"]
    if fertilizer["total_product_kg_ha"]*FIELD_LENGTH_M*field["ridge_width_m"]*64/10000 < 200:
        raise ValueError("Declared fertilizer recipe cannot cover fixed200kg basal tool")
    for name in ("n_fraction", "n_recovery"):
        if not 0 <= fertilizer[name] <= 1:
            raise ValueError(f"Fertilizer {name} must be in[0,1]")
        native_key = "fertilizer_"+name
        if abs(backend[native_key]-fertilizer[name])>1e-12:
            raise ValueError("Fertilizer ledger and native N conversion must agree")
    if policy["irrigation_mm_per_event"] <= 0 or policy["irrigation_season_max_mm"] < 0 or policy["minimum_gap_days"] < 0:
        raise ValueError("Invalid irrigation event, quota or gap")
    if not 15 <= policy["harvest_moisture_max_pct"] <= 25:
        raise ValueError("Complete reference harvest moisture cap must be15–25%")



def run_case(output, forcing, metadata, config, case):
    output.mkdir(parents=True, exist_ok=True)
    field_config, fertilizer, policy = config["field"], config["fertilizer"], config["management"]
    start_day, sow_target = date.fromisoformat(config["start_date"]), date.fromisoformat(config["sowing_window"]["start"])
    sow_end, deadline = date.fromisoformat(config["sowing_window"]["end"]), date.fromisoformat(config["deadline"])
    width, spacing, seed_type = field_config["ridge_width_m"], field_config["seed_spacing_cm"], field_config["seed_type"]
    area = FIELD_LENGTH_M * width * N_RIDGES
    target_product = fertilizer["total_product_kg_ha"] * area / 10000.0
    n_fraction = fertilizer["n_fraction"]
    seed = int(config.get("random_seed", 1729))
    irrigation_limit = policy["irrigation_season_max_mm"] if case == "managed" else policy.get("high_quota_max_mm", 1000.0)
    supplemental_irrigation = case != "rainfed"
    random.seed(seed)
    scenario = WofostCompleteScenario(complete_config=config, scenario_id=config["scenario_id"]+"_"+case, crop_backend="wofost",
                               crop_backend_options=config["crop_backend_options"],
                               start_time=datetime.combine(start_day, time(8), timezone.utc).timestamp())
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
        app.rng.seed(seed)
    physics = farm.physics
    by_day = {w.day: (w, rh) for w, rh in forcing}
    for w, rh in forcing:
        physics.set_weather_day_override(w.day, air_temp_mean_c=w.air_temp_mean_c,
            air_temp_min_c=w.air_temp_min_c, air_temp_max_c=w.air_temp_max_c,
            rain_mm=w.rain_mm, wind_ms=w.wind_ms, solar_rad_mj_m2=w.solar_rad_mj_m2,
            relative_humidity_pct=rh)
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
        w, rh = by_day[day]
        weather.set_weather(date=day.isoformat(), temp_c=w.air_temp_mean_c,
            humidity_pct=rh, rainfall_mm=w.rain_mm, wind_speed_ms=w.wind_ms,
            solar_radiation=w.solar_rad_mj_m2 / 0.0864, avg_soil_vwc=config["initial_soil"]["vwc"], forecast=[])

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
            used_humidity = run.journal[-1]["humidity_pct"] if run and run.journal else None
            native_vap = float(run.provider(day).VAP) if run else None
            source_vap = max(.06, 6.108*math.exp(17.27*w.air_temp_mean_c/(w.air_temp_mean_c+237.3))*rh/100)
            rows.append({
                "forcing_day": day.isoformat(), "observed_at_utc": stamp(engine.time_manager.time()),
                "ridge_id": rid, "stage": phen.stage.value, "emerged": phen.emerged,
                "emergence_date": str(phen.emergence_date or ""), "maturity_date": str(phen.maturity_date or ""),
                "harvest_date": str(y.harvest_date or ""), "r8_reached": y.r8_reached, "harvested": y.harvested,
                "rain_mm": w.rain_mm, "tmean_c": w.air_temp_mean_c, "tmin_c": w.air_temp_min_c,
                "tmax_c": w.air_temp_max_c, "radiation_mj_m2": w.solar_rad_mj_m2,
                "wind_ms": w.wind_ms, "used_rh_pct": used_humidity, "source_rh_pct": rh,
                "native_vap_hpa": native_vap, "source_expected_vap_hpa": source_vap,
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
    irrigation_total, last_irrigation, topdressed, stress_days = 0, None, False, 0
    decisions = []
    weed_counts = {i: 0 for i in range(6)}
    last_treatment = {}
    try:
        set_current(start_day)
        call(tractor.attach_implement, implement="grader")
        call(tractor.level)
        call(tractor.detach_implement)
        call(tractor.load_fertilizer, kg=min(500.0, math.ceil(target_product*100)/100))
        call(tractor.base_fertilize)
        call(tractor.attach_implement, implement="furrower")
        call(tractor.form_ridges, ridge_width_m=width)
        call(tractor.detach_implement)
        # The fixed 200kg base tool is part of, rather than added to, the recipe.
        remaining_product = target_product - 200.0
        if remaining_product < -1e-9:
            raise ValueError("Requested whole-field fertilizer must cover the fixed 200kg base operation")
        if remaining_product > 1e-9:
            for first, last in split_pass(0, 63, 10):
                ensure_fuel()
                required = (last-first+1) * remaining_product/64
                if tractor._fertilizer_spreader_kg + .005 < required:
                    # Product inventories round to0.01kg per pass. Refill only
                    # the tiny rounding deficit, rather than another full pass.
                    deficit = math.ceil((required-tractor._fertilizer_spreader_kg)*100)/100+.01
                    call(tractor.load_fertilizer, kg=min(500-tractor._fertilizer_spreader_kg, deficit))
                call(tractor.apply_fertilizer, start_ridge=first, end_ridge=last, kg_per_ridge=remaining_product/64)
        planted = False
        while True:
            today = datetime.fromtimestamp(engine.time_manager.time(), timezone.utc).date()
            if today > deadline:
                raise RuntimeError("Season deadline reached before safe storage")
            set_current(today)
            readings = call(sensor.read_soil_sensors)["soil_sensors"]
            call(farm.get_ridge_range_state, start=0, end=63)
            if not planted and today > sow_end:
                raise RuntimeError("No safe sowing opportunity inside the declared sowing window")
            if not planted and today >= sow_target:
                if min(s["temp_c"] for s in readings) > 10 and all(.20 <= s["vwc"] <= .35 for s in readings):
                    count = plants_per_ridge_from_spacing(spacing)
                    for start, end in split_pass(0, 63, 4):
                        ensure_fuel()
                        needed = count * (end-start+1)
                        if tractor._seed_hopper < needed:
                            call(tractor.load_seeds, seed_type=seed_type, count=300000-tractor._seed_hopper)
                        call(tractor.plant_seeds, start_ridge=start, end_ridge=end, depth_cm=field_config["sowing_depth_cm"], seed_spacing_cm=spacing)
                    planted = True
            mature = planted and all(y.r8_reached for y in physics.yield_recovery.states.values())
            if planted and not mature and today >= sow_target + timedelta(days=7):
                mean_sensor = sum(s["vwc"] for s in readings) / len(readings)
                p = backend._runs.get(0)
                native = p.pcse if p else {}
                rftra, dvs = float(native.get("RFTRA", 1)), float(native.get("DVS", 0))
                critical_stage = policy.get("irrigation_dvs_min", 1.0) <= dvs < policy.get("irrigation_dvs_max", 1.9)
                stress_days = stress_days+1 if rftra < policy.get("irrigation_trigger_rftra", .9) else 0
                rain_next3 = sum(by_day[today+timedelta(days=i)][0].rain_mm for i in range(3) if today+timedelta(days=i) in by_day)
                dry_window = by_day[today][0].rain_mm < policy.get("rain_today_max_mm", 1.0) and rain_next3 < policy.get("next3day_rain_max_mm", 10.0)
                gap_ok = last_irrigation is None or (today-last_irrigation).days >= policy["minimum_gap_days"]
                trigger = critical_stage and stress_days >= policy.get("stress_consecutive_days", 2)
                decisions.append({"date": today.isoformat(), "case": case, "DVS": dvs, "RFTRA_previous_day": rftra,
                                  "stress_consecutive_days": stress_days, "sensor_mean_vwc": mean_sensor,
                                  "retrospective_next3day_rain_mm": rain_next3, "irrigation_trigger": trigger,
                                  "quota_remaining_mm": max(0, irrigation_limit-irrigation_total)})
                if supplemental_irrigation and trigger and dry_window and gap_ok and irrigation_total < irrigation_limit:
                    # All zones must be eligible: the real tool rejects a wet ridge.
                    if max(s.root_vwc for s in physics.soil.states.values()) < .30:
                        amount = min(policy["irrigation_mm_per_event"], irrigation_limit-irrigation_total)
                        call(field.irrigate, start=0, end=63, hours=amount/5)
                        irrigation_total += amount
                        last_irrigation = today
                if policy.get("topdress_enabled", policy.get("automatic_topdress", False)) and p and not topdressed and float(p.pcse.get("RFRGRL", 1)) < .9 and float(p.pcse.get("NAVAIL") or 0) < 10:
                    for start, end in split_pass(0, 63, 10):
                        ensure_fuel()
                        call(tractor.apply_fertilizer, start_ridge=start, end_ridge=end, kg_per_ridge=1.0)
                    topdressed = True
                das = (today-sow_target).days
                if das % 7 == 0 and policy.get("weekly_scouting", True):
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
            grain_ready = mature and all((y.grain_moisture_frac or 1)*100 <= policy["harvest_moisture_max_pct"] for y in physics.yield_recovery.states.values())
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
    mu = area / (2000/3)
    recovery = physics.yield_recovery.states
    native_rows = [r for r in rows if r["DVS"] is not None]
    residuals = [abs(r["water_balance_residual_mm"]) for r in native_rows]
    biological = sum(y.biological_yield_g_m2 for y in recovery.values()) * (area/N_RIDGES) / 1000
    recovered = sum(y.recovered_yield_g_m2_at_market_moisture for y in recovery.values()) * (area/N_RIDGES) / 1000
    harvest_kg = sum(c["result"].get("grain_kg_added",0) for c in calls if c["tool"].endswith(".harvest"))
    product_applied = sum(c["result"].get("fertilizer_used_kg",0) for c in calls if c["tool"].endswith((".apply_fertilizer", ".base_fertilize")))
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
                                          and abs(run.pcse["TOTIRR"]*10-irrigation_total*backend.config.irrigation_efficiency)<1e-8 for run in backend._runs.values()),
        "fertilizer_reaches_native": all(abs(run.cumulative_fertilizer_kg-(target_product/64+(1 if topdressed else 0)))<1e-9
                                           and abs(run.cumulative_n_kg_ha-run.cumulative_fertilizer_kg*n_fraction*10000/(area/64))<1e-8 for run in backend._runs.values()),
        "soil_bounds": all(0<=r["SM"]<=physics.soil.params.saturation_vwc+1e-8 for r in native_rows),
        "stress_bounds": all(0<=float(r["RFTRA"] or 0)<=1+1e-8 and 0<=float(r["RFRGRL"] or 0)<=1+1e-8 for r in native_rows),
        "all_source_humidity_preserved": bool(native_rows) and all(r["used_rh_pct"] is not None and abs(r["used_rh_pct"]-r["source_rh_pct"])<1e-9 for r in native_rows),
        "native_vapor_matches_source": bool(native_rows) and all(abs(r["native_vap_hpa"]-r["source_expected_vap_hpa"])<1e-9 for r in native_rows),
        "fertilizer_recipe_tool_mass": abs(product_applied-(target_product+(64 if topdressed else 0)))<1e-8,
        "fertilizer_inventory_balance": abs(farm._inventory.fertilizer_kg+tractor._fertilizer_spreader_kg+product_applied-1000.0)<.05,
        "seed_inventory_balance": farm._inventory.seed_stock[seed_type]+tractor._seed_hopper+sum(
            plants_per_ridge_from_spacing(spacing) for phen in physics.phenology.states.values() if phen.planting_date is not None)==600000,
        "standard_moisture_conversion_once": all(not y.harvested or abs(y.recovered_yield_g_m2_at_market_moisture-
             y.biological_yield_g_m2*(1-y.field_loss_fraction)*(1-y.machine_loss_fraction)/.87)<1e-7 for y in recovery.values()),
        "dvs_monotonic": all(all(b["DVS"]+1e-8>=a["DVS"] for a,b in zip(group,group[1:]))
                             for rid in range(64) for group in [[r for r in native_rows if r["ridge_id"]==rid]]),
    }
    summary = {
        "success": all(checks.values()), "checks": checks, "error": error,
        "case": case, "scenario_id": config["scenario_id"], "area_m2": area, "area_mu": mu,
        "density_plants_m2": plants_per_ridge_from_spacing(spacing)/(area/N_RIDGES),
        "seed_spacing_cm": spacing, "seed_type": seed_type,
        "native_variety": backend._runs[0].specification["variety"] if 0 in backend._runs else backend.config.variety_name,
        "cultivar_profile": backend.config.cultivar_profile,
        "sowing_dates": sorted({str(p.planting_date) for p in physics.phenology.states.values()}),
        "emergence_dates": sorted({str(p.emergence_date) for p in physics.phenology.states.values()}),
        "maturity_dates": sorted({str(p.maturity_date) for p in physics.phenology.states.values()}),
        "harvest_dates": sorted({str(y.harvest_date) for y in recovery.values()}),
        "end_time_utc": stamp(engine.time_manager.time()), "daily_forcing_days": len({r["forcing_day"] for r in rows}),
        "biological_yield_kg_dry_total": biological, "biological_yield_kg_dry_per_mu": biological/mu,
        "recovered_yield_kg_at_13pct_total": recovered, "recovered_yield_kg_at_13pct_per_mu": recovered/mu,
        "harvest_tool_kg": harvest_kg, "warehouse_kg_at_13pct": warehouse,
        "irrigation_gross_mm": irrigation_total, "topdress_applied": topdressed,
        "fertilizer_product_kg_total": target_product+(64 if topdressed else 0),
        "fertilizer_product_kg_from_tool_log": product_applied,
        "unused_fertilizer_kg_warehouse": farm._inventory.fertilizer_kg,
        "unused_fertilizer_kg_spreader": tractor._fertilizer_spreader_kg,
        "fertilizer_n_kg_ha": (target_product+(64 if topdressed else 0))*n_fraction/(area/10000),
        "fertilizer_effective_n_kg_ha": (target_product+(64 if topdressed else 0))*n_fraction*fertilizer["n_recovery"]/(area/10000),
        "fertilizer_recipe_ledger": fertilizer.get("products", []),
        "fertilizer_note": "All products are a homogeneous accounting mixture. Only N mass and recovery reach WOFOST8.1; P/K and fertilizer-specific chemistry/placement have no native feedback.",
        "weed_control_counts_by_zone": weed_counts,
        "bottom_drainage_mm_ridge0": sum(r["bottom_drainage_mm"] for r in native_rows if r["ridge_id"]==0),
        "rain_mm_during_native_ridge0": sum(r["rain_mm"] for r in native_rows if r["ridge_id"]==0),
        "max_water_balance_residual_mm": max(residuals,default=None), "storage_warnings": warnings,
        "final_native_snapshot": backend.snapshot(),
        "yield_recovery": {str(k):vars(v) for k,v in recovery.items()},
        "provenance": crop_backend_provenance(physics), "weather_source": metadata,
        "limitations": config.get("limitations", []) + [
            "Homogeneous assumed soil; no field soil measurements",
            "NASA POWER gridded weather, including real relative humidity; not station observations",
            "Retrospective known same-day and next3day weather; not a forecast skill test",
            "Density only scales TDWI; P/K and fertilizer chemistry not modeled",
            "100% establishment is an explicit scenario assumption, not measured stand",
            "WOFOST crop/soil plus FAIRY empirical biotic, stand, grain drying and recovery models",
            "Dryer capacity gate is batch standard-moisture mass; energy, wet grain throughput and continuous hourly drying are not modeled"],
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
    names = {
        "forcing_day":"日期_当天完成日步", "stages":"生育期", "DVS":"发育指数DVS", "LAI":"叶面积指数LAI",
        "TWSO_kg_dm_ha":"籽粒干重_kg每公顷", "TAGP_kg_dm_ha":"地上生物量干重_kg每公顷",
        "root_depth_cm":"根深_cm_成熟后为作物终值", "SM":"根区体积含水率_作物结束后为表层代理", "NAVAIL_kg_n_ha":"有效土壤氮_kgN每公顷",
        "RFTRA":"水分限制系数", "RFRGRL":"氮限制系数", "rain_mm":"降雨_mm", "tmean_c":"平均气温_摄氏度",
        "used_rh_pct":"相对湿度_百分比", "effective_irrigation_mm":"有效灌水_mm",
        "evaporation_mm":"土壤蒸发_mm", "transpiration_mm":"作物蒸腾_mm", "runoff_mm":"径流_mm",
        "bottom_drainage_mm":"底部排水_mm", "grain_moisture_pct":"籽粒含水率_百分比",
        "biological_yield_g_dm_m2":"籽粒干物质_g每平方米", "field_loss_fraction":"累计田间损失比例",
        "storage_end_mm":"日末土壤总储水_mm", "water_balance_residual_mm":"水量平衡误差_mm",
    }
    write_csv(output/"每日状态.csv", [{names[k]: row.get(k) for k in names} for row in averages])
    write_csv(output/"management_decisions.csv", decisions)
    (output/"data_dictionary.json").write_text(json.dumps({
        "forcing_day": "Weather forcing date d; post-integration truth for completed day d, read at shared clock d+1. The final harvesting operations are in operations.jsonl and final_ridges.json.",
        "used_rh_pct": "Actual humidity passed into native WOFOST, read from each run's weather journal. None before native sowing; source_rh_pct comes independently from source NASA file.",
        "SM": "Native rooted-zone water content while crop is alive; after PCSE deletes crop at maturity, its soil module reports the upper soil compartment. Use storage_end_mm for full-profile water accounting.",
        "root_depth_cm": "Native RD for living crop; last crop RD is retained after maturity. It does not describe a continuing root-growth process after crop deletion.",
        "TWSO_kg_dm_ha": "Native storage-organ dry matter, not field-moisture grain mass. Final stored inventory is at declared13pct market moisture after field and machine losses.",
        "recovered_yield_g_m2_at_13pct": "Dry-matter mass converted once to13pct standard moisture. Dryer is a batch moisture/safety operation; it does not reconvert this already-standardized inventory mass.",
        "RFTRA": "Actual/potential transpiration ratio from native model. Management reads this model diagnostic as an oracle; the soil sensor alone does not expose it.",
        "irrigation_rule": "RFTRA<declared threshold for consecutive days, critical DVS range, dry present/next3day weather, minimum gap, seasonal quota. Next3day weather is retrospective perfect knowledge.",
    },ensure_ascii=False,indent=2))
    (output/"resolved_parameters.json").write_text(json.dumps({
        "backend_config": asdict(backend.config), "reduced_soil_parameters": asdict(physics.soil.params),
        "native_inputs_ridge0": backend._runs[0].specification if 0 in backend._runs else None,
        "all_native_specifications_identical": len({json.dumps(r.specification,sort_keys=True,default=str) for r in backend._runs.values()})==1,
        "configuration":config, "weather":metadata}, ensure_ascii=False,indent=2,default=str))
    (output/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str))
    print(json.dumps({k:v for k,v in summary.items() if k not in ("final_native_snapshot","yield_recovery","provenance","weather_source")},ensure_ascii=False),flush=True)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,default=ROOT/"configs/wofost/complete_harbin_heinong84_v1.json")
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--weather",type=Path,default=None,help="NASA POWER JSON; defaults to config-relative weather_file")
    parser.add_argument("--cases",default="managed,rainfed",help="Comma separated managed,rainfed,high_quota")
    parser.add_argument("--year",type=int,help="Relocate all configured calendar dates into a different weather year")
    parser.add_argument("--rain-multiplier",type=float,default=1.0,help="Explicit synthetic rainfall sensitivity; never represented as observed weather")
    args=parser.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    config=json.loads(args.config.read_text())
    original_year=date.fromisoformat(config["start_date"]).year
    if args.year:
        for key in ("start_date", "deadline"):
            config[key]=date.fromisoformat(config[key]).replace(year=args.year).isoformat()
        for key in ("start", "end"):
            config["sowing_window"][key]=date.fromisoformat(config["sowing_window"][key]).replace(year=args.year).isoformat()
    validate_configuration(config)
    if not math.isfinite(args.rain_multiplier) or args.rain_multiplier < 0:
        raise ValueError("Rain multiplier must be nonnegative")
    weather_path=args.weather
    if weather_path is None:
        weather_name=config.get("weather_file")
        if not weather_name:
            raise ValueError("Supply --weather or a config-relative weather_file")
        if args.year:
            weather_name=weather_name.replace(str(original_year),str(args.year))
        weather_name=weather_name.format(year=args.year or original_year)
        weather_path=(args.config.resolve().parent/weather_name).resolve()
    forcing,metadata=load_weather(weather_path,date.fromisoformat(config["start_date"]))
    if date.fromisoformat(config["deadline"]) > forcing[-1][0].day:
        raise ValueError("Weather must cover every day through the configured deadline")
    if args.rain_multiplier != 1.0:
        forcing=[(replace(w,rain_mm=w.rain_mm*args.rain_multiplier),rh) for w,rh in forcing]
    metadata["weather_transform"]={"rain_multiplier":args.rain_multiplier,"status":"unmodified_source" if args.rain_multiplier==1 else "synthetic_rainfall_sensitivity"}
    selected=args.cases.split(",")
    if not selected or len(selected)!=len(set(selected)) or not set(selected)<={"managed","rainfed","high_quota"}:
        raise ValueError("Cases must be unique choices of managed,rainfed,high_quota")
    frozen={"config":config,"config_source":str(args.config.resolve()),"weather":metadata,"cases":selected}
    (args.output_dir/"frozen_configuration.json").write_text(json.dumps(frozen,ensure_ascii=False,indent=2,default=str))
    cases={name:run_case(args.output_dir/name,forcing,metadata,config,name) for name in selected}
    (args.output_dir/"comparison.json").write_text(json.dumps({name:{k:v for k,v in s.items() if k not in ("final_native_snapshot","yield_recovery","provenance","weather_source")} for name,s in cases.items()},ensure_ascii=False,indent=2,default=str))
    return 0 if all(s["success"] for s in cases.values()) else 1

if __name__=="__main__":
    raise SystemExit(main())
