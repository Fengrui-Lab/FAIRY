"""Offline authoring policy for scripts/build_rice_scenario_artifacts.py.

Registered scenarios never import this module: they execute captured event graphs
from the reviewed plans and checkpoints produced by the generator.
"""
from __future__ import annotations

import math
from fairy.scenarios.workflow import Workflow, WorkflowStep


class ToolRecorder:
    def __init__(self, world, ops, system, weather, observation, machinery, infrastructure, drone):
        self.world, self.ops, self.system, self.weather = world, ops, system, weather
        self.observation, self.machinery, self.infrastructure, self.drone = observation, machinery, infrastructure, drone
        self.workflow = Workflow()
        self.checkpoints = {}
        self.checkpoint_steps = {}

    def call(self, app, method, **kwargs):
        before = self.world.sim_time
        value = getattr(app, method)(**kwargs)
        if isinstance(value, dict) and value.get("error"):
            raise RuntimeError(value["error"])
        self.workflow.add_node(WorkflowStep(tool_name=f"{app.name}__{method}", tool_args=kwargs,
            content=value, time_before=before, time_after=self.world.sim_time))
        return value

    def observe(self):
        return self.call(self.world, "get_farm_overview")["plots"]

    def water(self, pid):
        return self.call(self.observation, "read_water_sensors", plot_id=pid)

    def save(self, label):
        if label not in self.checkpoints:
            self.checkpoints[label] = self.world.get_state()
            self.checkpoint_steps[label] = len(self.workflow)

    def machine(self, mid, required_fuel=0., implement=None):
        m = self.call(self.machinery, "get_machine_status", machine_id=mid)["machines"][0]
        if m["fuel_liters"] + 1e-8 < required_fuel:
            self.call(self.machinery, "refuel", machine_id=mid,
                      liters=m["tank_capacity_liters"] - m["fuel_liters"])
        if implement and m["implement"] != implement:
            if m["implement"]:
                self.call(self.machinery, "detach_implement", machine_id=mid)
            self.call(self.machinery, "attach_implement", machine_id=mid, implement=implement)
        return m

    def canal(self, pid, amount, drain=False):
        inv = self.call(self.world, "get_inventory")
        channel = next(c for c in inv["channels"] if c["channel_id"] == ("drain" if drain else "supply"))
        area = next(p["area_m2"] for p in self.observe() if p["plot_id"] == pid)
        volume = area * amount / 1000 / (1 if drain else channel["efficiency"])
        duration = math.ceil(volume / (channel["flow_m3_hour"] * (1 - channel["blockage_fraction"])) * 3600)
        within_day = self.world.sim_time % 86400
        if (channel["open_hour"], channel["close_hour"]) != (0, 24):
            if within_day < channel["open_hour"] * 3600:
                self.call(self.system, "advance_time", seconds=math.ceil(channel["open_hour"] * 3600 - within_day))
            elif within_day + duration > channel["close_hour"] * 3600:
                self.call(self.system, "advance_time", seconds=math.ceil(86400 - within_day + channel["open_hour"] * 3600))
        return self.call(self.ops, "drain" if drain else "irrigate", plot_id=pid, water_mm=amount)


def maintain_infrastructure(r):
    for p in r.observe():
        report = r.call(r.infrastructure, "inspect_infrastructure", plot_id=p["plot_id"])
        for c in report["channels"]:
            if c["blockage_fraction"] > 0:
                r.call(r.infrastructure, "clear_channel", channel_id=c["channel_id"])
        if report["bund_leak_mm_day_estimate"] > 0:
            r.call(r.infrastructure, "repair_bund", plot_id=p["plot_id"])


def fertilize(r, p, dose):
    pid = p["plot_id"]
    water = r.water(pid)
    if water["surface_water_mm"] > 40:
        r.canal(pid, water["surface_water_mm"] - 20, drain=True)
    machine = r.machine("tractor", p["area_m2"] * .001, "spreader")
    inv = r.call(r.world, "get_inventory")
    total = inv["fertilizer"]["stock_kg"] + machine["fertilizer_kg"]
    dose = min(dose, total / p["area_m2"] * 10000)
    if dose < 1:
        return
    need = dose * p["area_m2"] / 10000
    if machine["fertilizer_kg"] + 1e-8 < need:
        r.call(r.ops, "load_fertilizer", kg=need - machine["fertilizer_kg"])
    r.call(r.ops, "apply_fertilizer", plot_id=pid, kg_per_ha=dose)


def establish(r):
    r.call(r.weather, "get_current_weather")
    r.call(r.world, "get_inventory")
    maintain_infrastructure(r)
    for p in r.observe():
        pid = p["plot_id"]
        if p["puddled"]:
            continue
        water = r.water(pid)
        if water["surface_water_mm"] < 80:
            r.canal(pid, 100. - water["surface_water_mm"])
        for _ in range(6):
            water = r.water(pid)
            if water["preparation_wet_hours"] >= 24:
                break
            if water["surface_water_mm"] < 30:
                r.canal(pid, 60.)
            r.call(r.ops, "soak", plot_id=pid, hours=24)
        else:
            raise RuntimeError("Reference could not complete soaking")
        r.machine("tractor", p["area_m2"] * .004, "puddler")
        if pid == "p1":
            r.save("before_puddle")
        r.call(r.ops, "puddle_and_level", plot_id=pid)
    for p in r.observe():
        water = r.water(p["plot_id"])
        if water["surface_water_mm"] > 20:
            r.canal(p["plot_id"], water["surface_water_mm"] - 20, drain=True)
        fertilize(r, p, 120.)
    r.save("before_transplant")
    for p in r.observe():
        if not p["planted"]:
            transplant_plot(r, p)
    r.save("after_transplant")
    for p in r.observe():
        report = r.call(r.observation, "inspect_establishment", plot_id=p["plot_id"])
        if report["stand_fraction_estimate"] < .99:
            fill_gaps(r, p, report)


def transplant_plot(r, p):
    capacity = r.machine("transplanter", p["area_m2"] * .002)["seedling_capacity"]
    remaining = p["area_m2"] - p["transplanted_area_m2"]
    # Keep each hydraulic plot in one native start day, including all loading jobs.
    total_seconds = remaining / 2000 * 3600 + math.ceil(remaining * 75 / capacity) * 600
    if r.world.sim_time % 86400 + total_seconds >= 86400:
        r.call(r.system, "advance_time", seconds=math.ceil(86400 - r.world.sim_time % 86400))
    while remaining > 1e-8:
        area = min(remaining, capacity / 75)
        needed = math.ceil(area * 75)
        inv = r.call(r.world, "get_inventory")["seedlings"]
        if inv["loaded"] < needed:
            r.call(r.ops, "load_seedlings", batch_id=inv["batch_id"], quantity=needed - inv["loaded"])
        r.call(r.ops, "transplant", plot_id=p["plot_id"], batch_id=inv["batch_id"], area_m2=area)
        remaining -= area


def fill_gaps(r, p, report=None):
    report = report or r.call(r.observation, "inspect_establishment", plot_id=p["plot_id"])
    missing = math.floor((1 - report["stand_fraction_estimate"]) * p["area_m2"] * 75 + 1e-7)
    inv = r.call(r.world, "get_inventory")["seedlings"]
    count = min(missing, inv["quantity"] + inv["loaded"])
    if count <= 0:
        return
    water = r.water(p["plot_id"])
    if water["surface_water_mm"] > 25:
        r.canal(p["plot_id"], water["surface_water_mm"] - 20, drain=True)
    if water["root_vwc"] < .4:
        r.canal(p["plot_id"], 20.)
        r.call(r.system, "advance_time", days=1)
    if inv["loaded"] < count:
        r.call(r.ops, "load_seedlings", batch_id=inv["batch_id"], quantity=count-inv["loaded"])
    r.machine("transplanter", p["area_m2"] * .001)
    r.call(r.ops, "replant_seedlings", plot_id=p["plot_id"], quantity=count)


def protect_crop(r, p):
    report = r.call(r.observation, "inspect_pests", plot_id=p["plot_id"])
    weather = r.call(r.weather, "get_current_weather")
    if weather["rainfall_mm"] <= 5 and weather["wind_speed_ms"] <= 6:
        for severity, tool in (("insect_severity", "apply_pesticide"), ("disease_severity", "apply_fungicide")):
            if report[severity] >= .25:
                r.machine("tractor", p["area_m2"] * .001, "sprayer")
                r.call(r.ops, tool, plot_id=p["plot_id"])
    if report["weed_cover_fraction"] >= .25:
        water = r.water(p["plot_id"])
        if water["surface_water_mm"] > 25:
            r.canal(p["plot_id"], water["surface_water_mm"] - 20, drain=True)
        r.call(r.ops, "control_weeds", plot_id=p["plot_id"])


def harvest_plot(r, p):
    r.machine("combine", p["area_m2"] * .003)
    remaining = p["area_m2"] - p["harvested_area_m2"]
    while remaining > 1e-8:
        water = r.water(p["plot_id"])
        weather = r.call(r.weather, "get_current_weather")
        moisture = r.call(r.observation, "measure_grain_moisture", plot_id=p["plot_id"])["moisture_pct"]
        if water["surface_water_mm"] > .1 or water["root_vwc"] > .42 or weather["rainfall_mm"] > 5 or not 14 <= moisture <= 28:
            return
        # Conservative physical work batch, independent of hidden native yield.
        capacity = r.call(r.machinery, "get_machine_status", machine_id="combine")["machines"][0]["grain_capacity_wet_kg"]
        area = min(remaining, capacity / 1.5)
        harvested = r.call(r.ops, "harvest", plot_id=p["plot_id"], area_m2=area)
        r.call(r.ops, "unload_grain", plot_id=p["plot_id"])
        if p["plot_id"] == "p1":
            r.save("before_dry")
        r.call(r.observation, "measure_grain_moisture", batch_id=harvested["batch_id"])
        r.call(r.ops, "dry_grain", batch_id=harvested["batch_id"])
        if p["plot_id"] == "p1":
            r.save("before_store")
        r.call(r.ops, "store_grain", batch_id=harvested["batch_id"])
        remaining -= area


def manage(r, *, days=None, fertilizing=True, protecting=True):
    start = r.world.sim_time
    entries = r.call(r.world, "get_operation_log")["operations"]
    feed_counts = {p["plot_id"]: sum(a["action"] == "apply_fertilizer" and a.get("plot_id") == p["plot_id"] for a in entries)
                   for p in r.observe()}
    for iteration in range(220):
        plots = r.observe()
        if days is not None and r.world.sim_time - start >= days * 86400:
            return
        if all(p["harvested"] and p["stored_dry_kg"] > 0 for p in plots):
            return
        forecast = r.call(r.weather, "get_forecast", days=3)["forecast"]
        for p in plots:
            pid = p["plot_id"]
            if not p["planted"] or p["harvested"]:
                continue
            crop = r.call(r.observation, "inspect_crop", plot_id=pid)
            water = r.water(pid)
            stage = crop["stage"]
            if pid == "p1" and stage in {"late_tillering_proxy", "panicle_development_proxy", "grain_filling"}:
                r.save("management_start")
                r.save("before_topdress")
            count = feed_counts[pid]
            if fertilizing and ((count < 2 and stage == "late_tillering_proxy") or
                                (count < 3 and stage == "panicle_development_proxy")):
                fertilize(r, p, 150.)
                feed_counts[pid] += 1
            if protecting and iteration % 7 == 0 and not crop["maturity_observed"]:
                if pid == "p1":
                    r.save("before_treat")
                protect_crop(r, p)
            if stage not in {"late_grain_filling", "mature"} and water["surface_water_mm"] < 15:
                if pid == "p1":
                    r.save("before_irrigate")
                inv = r.call(r.world, "get_inventory")
                channel = next(c for c in inv["channels"] if c["channel_id"] == "supply")
                area = sum(x["area_m2"] for x in plots if x["planted"] and not x["harvested"])
                affordable = max(0., channel["quota_m3"] - channel["withdrawn_m3"]) * channel["efficiency"] * 1000 / area
                if affordable >= 1 and forecast[0]["rain_mm"] < 20:
                    r.canal(pid, min(40., affordable))
            if stage in {"late_grain_filling", "mature"} and water["surface_water_mm"] > .1:
                if pid == "p1":
                    r.save("before_drain")
                r.canal(pid, water["surface_water_mm"], drain=True)
            if days is None and crop["maturity_observed"]:
                water = r.water(pid)
                moisture = r.call(r.observation, "measure_grain_moisture", plot_id=pid)["moisture_pct"]
                today = r.call(r.weather, "get_current_weather")
                if water["surface_water_mm"] <= .1 and water["root_vwc"] <= .42 and 14 <= moisture <= 28 and today["rainfall_mm"] <= 5:
                    if pid == "p1":
                        r.save("before_harvest")
                    harvest_plot(r, p)
        r.call(r.system, "advance_time", days=1)
    raise RuntimeError("Rice reference exceeded its season cap")


def run_reference(r, task="season"):
    if task == "season":
        establish(r)
        manage(r)
    elif task == "establishment":
        establish(r)
    elif task in {"irrigation_management", "nutrition_management"}:
        manage(r, days=10 if task == "irrigation_management" else 25)
    elif task in {"harvest_storage", "harvest_batches"}:
        manage(r)
    elif task == "irrigate":
        r.canal("p1", 30.)
    elif task == "drain":
        r.canal("p1", 20., drain=True)
    elif task == "puddle":
        p = next(p for p in r.observe() if p["plot_id"] == "p1")
        r.machine("tractor", p["area_m2"]*.004, "puddler")
        r.call(r.ops, "puddle_and_level", plot_id="p1")
    elif task == "transplant":
        transplant_plot(r, next(p for p in r.observe() if p["plot_id"] == "p1"))
    elif task == "harvest":
        p = next(p for p in r.observe() if p["plot_id"] == "p1")
        r.machine("combine", p["area_m2"]*.003)
        r.call(r.ops, "harvest", plot_id="p1")
    elif task == "observe_water":
        r.water("p1")
    elif task == "refuel":
        r.call(r.machinery, "refuel", machine_id="tractor", liters=10.)
    elif task in {"dry", "store"}:
        batches = r.call(r.world, "get_inventory")["grain_batches"]
        batch = next(b for b in batches if b["location"] == "reception")
        r.call(r.observation, "measure_grain_moisture", batch_id=batch["batch_id"])
        r.call(r.ops, "dry_grain" if task == "dry" else "store_grain", batch_id=batch["batch_id"])
    elif task == "fertilize":
        fertilize(r, next(p for p in r.observe() if p["plot_id"] == "p1"), 150.)
    elif task in {"scout", "crop_protection"}:
        r.call(r.drone, "fly_survey", plot_ids=["p1", "p2"])
        for p in r.observe():
            if task == "scout":
                r.call(r.observation, "inspect_pests", plot_id=p["plot_id"])
            else:
                protect_crop(r, p)
    elif task in {"repair_bund", "infrastructure_recovery"}:
        if task == "repair_bund":
            r.call(r.infrastructure, "inspect_infrastructure", plot_id="p1")
            r.call(r.infrastructure, "repair_bund", plot_id="p1")
        else:
            maintain_infrastructure(r)
    elif task == "gap_fill":
        fill_gaps(r, next(p for p in r.observe() if p["plot_id"] == "p1"))
        r.call(r.system, "advance_time", days=2)
        r.call(r.observation, "inspect_establishment", plot_id="p1")
    else:
        raise ValueError(f"Unknown rice task: {task}")
    r.call(r.world, "get_farm_overview")
    return r.workflow
