"""Offline authoring through public tools. Private state is used only for evidence.

The policies are engineering references, not optimizers. Scenario execution uses
their frozen public-tool plans, never this authoring module.
"""
from __future__ import annotations

import math
from fairy.apps.system import SystemApp
from fairy.scenarios.workflow import Workflow, WorkflowStep
from fairy.scenarios.crop_challenges.runtime import measurements


class Recorder:
    def __init__(self, scenario, engine):
        self.scenario, self.engine = scenario, engine
        self.apps = {a.name: a for a in scenario.apps}
        self.system = scenario.get_typed_app(SystemApp)
        self.workflow = Workflow()
        self.checkpoints, self.boundaries, self.endpoints = {}, {}, {}

    def now(self):
        return self.engine.time_manager.time()

    def call(self, app, method, **kwargs):
        if isinstance(app, str):
            app = self.apps[app]
        before = self.now()
        result = getattr(app, method)(**kwargs)
        if isinstance(result, dict) and (result.get("error") or result.get("warning")):
            raise RuntimeError(f"{app.name}.{method} {kwargs}: {result}")
        reading = method.startswith(("get_", "read_", "inspect_", "measure_"))
        self.workflow.add_node(WorkflowStep(tool_name=f"{app.name}__{method}", tool_args=kwargs,
            content=result, op_type="READ" if reading else "WRITE", time_before=before, time_after=self.now()))
        return result

    def save(self, label):
        if label not in self.checkpoints:
            self.checkpoints[label] = self.scenario.export_checkpoint(label)
            self.boundaries[label] = len(self.workflow)

    def endpoint(self, label):
        if label not in self.endpoints:
            self.endpoints[label] = {"step": len(self.workflow), "measurements": measurements(self.scenario),
                                     "state": self.scenario.export_checkpoint("endpoint")}

    def wait_until(self, day):
        target = self.scenario._source_start + day * 86400
        if self.now() < target:
            self.call(self.system, "advance_time", seconds=target - self.now())

    def maize_observe(self):
        forecast = self.call("WeatherApp", "get_forecast", days=7)
        roots = self.call("SensorApp", "read_root_zone_sensors")["root_zone_sensors"]
        ridges = self.call("FarmWorldApp", "get_ridge_range_state", start=0, end=63)["ridges"]
        inventory = self.call("FarmWorldApp", "get_inventory")
        return forecast, roots, ridges, inventory


def maize_establish(r):
    r.call("WeatherApp", "get_current_weather")
    r.call("SensorApp", "read_soil_sensors")
    r.call("TractorApp", "attach_implement", implement="grader")
    r.call("TractorApp", "level")
    r.call("TractorApp", "detach_implement")
    r.call("TractorApp", "load_fertilizer", kg=200.)
    r.call("TractorApp", "base_fertilize", total_kg=200.)
    r.call("TractorApp", "attach_implement", implement="furrower")
    r.call("TractorApp", "form_ridges", ridge_width_m=.75)
    r.call("TractorApp", "detach_implement")
    groups = [(0, 21, 0), (22, 43, 8), (44, 63, 16)] if r.scenario.definition.name == "staggered_water_priority" else [(0, 63, 0)]
    for first, last, day in groups:
        r.wait_until(day)
        # Wait for an actual permissible sowing window. The group stays bare
        # soil until its first successful sowing; never replant existing ridges.
        for _ in range(12):
            weather = r.call("WeatherApp", "get_current_weather")
            soil = r.call("SensorApp", "read_soil_sensors")["soil_sensors"]
            if weather["rainfall_mm"] == 0 and max(p["vwc"] for p in soil if p["ridge_end"] >= first and p["ridge_start"] <= last) < .38:
                if min(p["vwc"] for p in soil if p["ridge_end"] >= first and p["ridge_start"] <= last) < .21:
                    r.call("FieldOpsApp", "irrigate", start=first, end=last, hours=4.)
                    r.call(r.system, "advance_time", days=1)
                    continue
                break
            r.call(r.system, "advance_time", days=1)
        r.call("TractorApp", "load_seeds", seed_type="MAIZE_201", count=(last-first+1)*1340)
        for start in range(first, last+1, 4):
            r.call("TractorApp", "plant_seeds", start_ridge=start, end_ridge=min(start+3, last), depth_cm=4., seed_spacing_cm=20.)
        r.call("FarmWorldApp", "commit_daily_physics")


def maize_reference(r):
    maize_establish(r)
    name = r.scenario.definition.name
    for day in (24, 32, 40, 50, 60, 70, 80):
        r.wait_until(day)
        if day == 24 and name != "rainy_harvest_window":
            r.save("diagnosis")
        forecast, roots, ridges, inv = r.maize_observe()
        regime = inv["management_regime"]
        if day in (24, 40) and name in {"zonal_nitrogen_recovery", "compound_water_n_limit"}:
            low = [z for z in roots if z["soil_nitrogen"].get("available_n_kg_ha") is not None
                   and z["soil_nitrogen"]["available_n_kg_ha"] < 12.]
            for z in low:
                count = z["ridge_end"] - z["ridge_start"] + 1
                kg = min(count * 3., inv["fertilizer_kg"])
                if kg <= 0:
                    continue
                r.save("targeted_fertilization")
                r.call("FarmWorldApp", "apply_fertigation", start_ridge=z["ridge_start"], end_ridge=z["ridge_end"],
                       nutrient_amount=kg / (30. * count), water_mm=0.)
                r.call("FarmWorldApp", "get_inventory")
                r.endpoint("targeted_fertilization")
                inv = r.call("FarmWorldApp", "get_inventory")
        if name not in {"zonal_nitrogen_recovery", "rainy_harvest_window"}:
            imminent = sum(row.get("rainfall_mm", row.get("rain_mm", 0.)) for row in forecast.get("forecast", [])[:3])
            if name != "rain_aware_irrigation" or imminent < 20:
                # Rank observable deficits; equal input units are area weighted.
                for z in sorted(roots, key=lambda row: row["root_vwc"]):
                    if z["root_vwc"] >= .25:
                        continue
                    inv = r.call("FarmWorldApp", "get_inventory")
                    regime = inv["management_regime"]
                    remaining = regime["irrigation_quota_mm_total"] - regime["irrigation_used_mm_total"]
                    count = z["ridge_end"] - z["ridge_start"] + 1
                    mm = min(30., remaining * 64 / count)
                    if mm < 5:
                        continue
                    r.save("targeted_irrigation")
                    r.call("FieldOpsApp", "irrigate", start=z["ridge_start"], end=z["ridge_end"], hours=mm/5.)
                    r.call(r.system, "advance_time", days=1)
                    r.maize_observe()
                    r.endpoint("targeted_irrigation")
        if day == 60 and name != "rainy_harvest_window":
            r.maize_observe()
            r.endpoint("diagnosis")
    r.wait_until(100)
    if name == "rainy_harvest_window":
        r.save("diagnosis")
    for _ in range(80):
        weather = r.call("WeatherApp", "get_current_weather")
        _, roots, ridges, _ = r.maize_observe()
        remaining = [p for p in ridges if not p["harvested"]]
        if not remaining:
            break
        if weather["rainfall_mm"] == 0:
            for start in range(0, 64, 4):
                group = ridges[start:start+4]
                if all(p["harvested"] for p in group):
                    continue
                if not all(p["growth_stage"] == "MATURE" and p["grain_moisture_pct"] <= 25. for p in group):
                    continue
                if any(z["root_vwc"] >= .38 for z in roots if z["ridge_end"] >= start and z["ridge_start"] <= start+3):
                    continue
                status = r.call("TractorApp", "get_status")
                if status["fuel_tank_l"] < 20:
                    r.call("TractorApp", "refuel", liters=100. - status["fuel_tank_l"])
                r.call("TractorApp", "harvest", start_ridge=start, end_ridge=min(start+3, 63))
                r.call("TractorApp", "unload_grain")
                r.call("FarmWorldApp", "dry_grain", target_moisture_pct=14.)
                r.call("FarmWorldApp", "store_grain")
        r.call(r.system, "advance_time", days=1)
    r.maize_observe()
    if name == "rainy_harvest_window":
        r.endpoint("diagnosis")


class RiceRecorder(Recorder):
    """Public-tool helper interface shared with the existing rice authoring policy."""
    def __init__(self, scenario, engine):
        super().__init__(scenario, engine)
        self.world = self.apps["PaddyWorldApp"]
        for attr, name in (("ops", "PaddyOpsApp"), ("observation", "PaddyObservationApp"),
                           ("machinery", "PaddyMachineryApp"), ("infrastructure", "PaddyInfrastructureApp"),
                           ("drone", "PaddyDroneApp"), ("weather", "WeatherApp")):
            setattr(self, attr, self.apps[name])

    # Existing helpers only obtain management inputs through public calls.
    from scripts.rice_reference_policy import ToolRecorder as _Base
    observe = _Base.observe
    water = _Base.water
    machine = _Base.machine
    canal = _Base.canal


def rice_reference(r):
    from scripts.rice_reference_policy import fertilize, transplant_plot, protect_crop, harvest_plot
    name = r.scenario.definition.name
    r.call(r.weather, "get_current_weather")
    if name == "infrastructure_water_priority":
        r.save("diagnosis")
    # Inspect before restoring flow; the water-window challenge is calibrated
    # against repair-first and irrigation-first rather than prescribing a path.
    for p in r.observe():
        report = r.call(r.infrastructure, "inspect_infrastructure", plot_id=p["plot_id"])
        for channel in report["channels"]:
            if channel["blockage_fraction"] > 0:
                r.save("channel_clearance")
                r.call(r.infrastructure, "clear_channel", channel_id=channel["channel_id"])
                r.call(r.infrastructure, "inspect_infrastructure", plot_id=p["plot_id"])
                r.endpoint("channel_clearance")
        if report["bund_leak_mm_day_estimate"] > 0:
            if name == "infrastructure_water_priority":
                other = "p2" if p["plot_id"] == "p1" else "p1"
                emergency = r.water(other)
                if emergency["root_vwc"] < .28:
                    r.canal(other, 20.)
            r.call(r.infrastructure, "repair_bund", plot_id=p["plot_id"])
    for p in r.observe():
        pid = p["plot_id"]
        water = r.water(pid)
        if water["surface_water_mm"] < 80:
            r.canal(pid, 100 - water["surface_water_mm"])
        for _ in range(8):
            water = r.water(pid)
            if water["preparation_wet_hours"] >= 24:
                break
            if water["surface_water_mm"] < 30:
                r.canal(pid, 60.)
            r.call(r.ops, "soak", plot_id=pid, hours=24)
        r.machine("tractor", p["area_m2"] * .004, "puddler")
        r.call(r.ops, "puddle_and_level", plot_id=pid)
    for p in r.observe():
        water = r.water(p["plot_id"])
        if water["surface_water_mm"] > 20:
            r.canal(p["plot_id"], water["surface_water_mm"] - 20, drain=True)
        if name != "zonal_water_n_allocation":
            fertilize(r, p, 120.)
        transplant_plot(r, p)
    if name not in {"infrastructure_water_priority", "rainy_harvest_capacity"}:
        r.save("diagnosis")
    feed_counts = {p["plot_id"]: 0 for p in r.observe()}
    for iteration in range(160):
        plots = r.observe()
        if all(p["harvested"] for p in plots):
            break
        forecast = r.call(r.weather, "get_forecast", days=3)["forecast"]
        for p in plots:
            pid = p["plot_id"]
            if p["harvested"]:
                continue
            crop = r.call(r.observation, "inspect_crop", plot_id=pid)
            water = r.water(pid)
            stage = crop["stage"]
            if name == "zonal_water_n_allocation":
                need_n = crop["nitrogen_stress_signal"] == "elevated" and feed_counts[pid] < 1
            else:
                need_n = ((feed_counts[pid] == 0 and stage == "late_tillering_proxy") or
                          (feed_counts[pid] == 1 and stage == "panicle_development_proxy"))
            if need_n:
                fertilize(r, p, 150.)
                feed_counts[pid] += 1
            if name == "zonal_crop_protection" and iteration % 7 == 0 and not crop["maturity_observed"]:
                if pid == "p1":
                    r.save("targeted_protection")
                protect_crop(r, p)
                r.call(r.observation, "inspect_pests", plot_id=pid)
                if pid == "p1":
                    r.endpoint("targeted_protection")
            if stage not in {"late_grain_filling", "mature"} and water["surface_water_mm"] < 10:
                inv = r.call(r.world, "get_inventory")
                channel = next(c for c in inv["channels"] if c["channel_id"] == "supply")
                affordable = max(0., channel["quota_m3"]-channel["withdrawn_m3"]) * channel["efficiency"] * 1000 / sum(x["area_m2"] for x in plots)
                if affordable >= 2 and forecast[0]["rain_mm"] < 20:
                    r.canal(pid, min(30., affordable))
            if stage in {"late_grain_filling", "mature"}:
                if name == "rainy_harvest_capacity":
                    r.save("diagnosis")
                water = r.water(pid)
                if water["surface_water_mm"] > .1:
                    r.canal(pid, water["surface_water_mm"], drain=True)
            if crop["maturity_observed"]:
                harvest_plot(r, p)
        if iteration == 25 and name != "rainy_harvest_capacity":
            r.call(r.world, "get_farm_overview")
            r.endpoint("diagnosis")
        r.call(r.system, "advance_time", days=1)
    r.call(r.world, "get_farm_overview")
    if name == "rainy_harvest_capacity":
        r.endpoint("diagnosis")
