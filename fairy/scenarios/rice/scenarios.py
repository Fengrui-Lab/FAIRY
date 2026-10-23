"""Registered, native-WOFOST rice tasks and complete-history checkpoint splits."""
from __future__ import annotations

import copy
import json
import os
from functools import lru_cache
from pathlib import Path

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.paddy.models import PaddyField
from fairy.apps.paddy.world import PaddyWorldApp
from fairy.apps.paddy.operations import PaddyOpsApp
from fairy.apps.paddy.observations import PaddyObservationApp
from fairy.apps.paddy.machinery import PaddyMachineryApp
from fairy.apps.paddy.infrastructure import PaddyInfrastructureApp
from fairy.apps.paddy.drone import PaddyDroneApp
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.registry import register_scenario
from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.scenarios.rice.reference import ToolRecorder, run_reference

CHECKPOINTS = {"puddle": "before_puddle", "transplant": "before_transplant",
               "irrigate": "before_irrigate", "drain": "before_drain",
               "harvest": "before_harvest", "irrigation_management": "management_start",
               "harvest_storage": "before_drain", "observe_water": "after_transplant",
               "dry": "before_dry", "store": "before_store", "fertilize": "before_topdress",
               "scout": "before_treat", "crop_protection": "before_treat",
               "gap_fill": "after_transplant", "nutrition_management": "management_start",
               "harvest_batches": "before_drain"}

VARIANTS = ("normal", "water_limit", "late_rain", "nitrogen_limit", "biotic",
            "infrastructure", "equipment_limit", "poor_stand")
TASK_VARIANTS = {"scout": "biotic", "crop_protection": "biotic", "gap_fill": "poor_stand",
                 "repair_bund": "infrastructure", "infrastructure_recovery": "infrastructure",
                 "harvest_batches": "equipment_limit", "refuel": "equipment_limit"}


def configuration(variant):
    field = PaddyField().to_dict()
    weather = {"rain_mm": 1.}
    if variant == "water_limit":
        field["channels"][0]["quota_m3"] = 1100.
        weather["rain_mm"] = 0.
    elif variant == "late_rain":
        weather["overrides"] = {f"2026-04-{day:02d}": {"rain_mm": 25.} for day in range(1, 5)}
    elif variant == "nitrogen_limit":
        field["fertilizer_kg"] = 55.
        for p in field["plots"]:
            p["soil"].update(NAVAILI=12., NSOILBASE=20.)
    elif variant == "biotic":
        for p in field["plots"]:
            p.update(pests=.3, disease=.3, weeds=.3)
    elif variant == "infrastructure":
        field["plots"][0]["bund_leak_mm_day"] = 8.
        field["channels"][0].update(blockage_fraction=.6, open_hour=6, close_hour=20)
        field["forecast_error_mm"] = 3.
    elif variant == "equipment_limit":
        for m in field["machines"]:
            m["fuel_liters"] = 1.
        field["machines"][1]["seedling_capacity"] = 75000
        field["machines"][2]["grain_capacity_wet_kg"] = 600.
        field["drying_capacity_wet_kg_day"] = 2000.
    elif variant == "poor_stand":
        field["plots"][0]["stand_fraction"] = .75
    elif variant != "normal":
        raise ValueError(f"Unknown rice variant {variant}")
    return field, weather


@lru_cache(maxsize=8)
def reference_checkpoints(variant):
    # The reference runs through real tools in a separate world, never by
    # assigning DVS/LAI or bypassing tool preconditions.
    scenario = RiceScenario(task="season", variant=variant)
    scenario.setup()
    Engine(None, scenario)
    recorder = scenario.recorder()
    run_reference(recorder)
    return recorder.checkpoints


class RiceScenario(Scenario):
    task = "season"
    variant = "normal"
    crop_name = "rice"
    crop_backend = "wofost"

    def __init__(self, *, task=None, variant=None, **kwargs):
        self.task = task or type(self).task
        self.variant = variant or type(self).variant
        self._constructor_kwargs = copy.deepcopy(kwargs)
        requested_backend = kwargs.pop("crop_backend", "wofost")
        if requested_backend != "wofost":
            raise ValueError("Rice scenarios require WOFOST; legacy is not substituted")
        if kwargs.get("start_time", 1767225600.) != 1767225600.:
            raise ValueError("Rice scenarios use the fixed 2026-01-01 season; later starts come from checkpoints")
        kwargs.setdefault("start_time", 1767225600.)  # 2026-01-01 UTC
        kwargs["crop_backend"] = "wofost"
        kwargs.setdefault("scenario_input", self.briefing())
        super().__init__(**kwargs)
        self.source_l3_scenario_id = f"scenario_rice_l3_{self.variant}"
        self.source_checkpoint_label = CHECKPOINTS.get(self.task, "initial_before_field_prep")

    def briefing(self):
        goals = {"season": "完成两个田格从泡田整地、成品苗插秧、灌排管理到收获干燥入库的单季种植。",
                 "establishment": "完成两个田格的泡田、耙田整平、浅水调整和成品苗插秧。",
                 "irrigation_management": "根据观测完成接下来10天的灌排管理，避免水分胁迫并遵守共享配额。",
                 "harvest_storage": "完成收前排水、成熟监测、收割、卸粮和干燥入库。",
                 "puddle": "完成p1田格的耙田整平，泡田前置条件已具备。",
                 "transplant": "复核p1田格、装载成品秧苗并完成标准密度插秧。",
                 "irrigate": "为p1田格完成30毫米到田灌水，并复查水量和资源。",
                 "drain": "从p1田格排出至多20毫米田面水，并复查实际排水量。",
                 "harvest": "复核条件后收割p1田格，当前已进入可收获窗口。",
                 "observe_water": "读取p1水位及土壤水分传感器，并保留带时间戳的观测。",
                 "refuel": "检查拖拉机油箱，从仓库补充10升燃油。",
                 "dry": "测量接粮区粮批含水率，将其干燥至14%，保留在接粮区。",
                 "store": "复测已干燥粮批的含水率，将其入库。",
                 "fertilize": "根据p1田间观测，装载尿素并完成150千克/公顷追肥。",
                 "scout": "无人机巡查两个田格，落地检查病虫草害，保留观测。",
                 "gap_fill": "检查p1缺苗，使用剩余成品秧苗补苗，等待两天后复查成活。",
                 "nutrition_management": "根据观测完成接下来25天的水肥管理，包括适时追肥。",
                 "crop_protection": "无人机巡查并确认两个田格的病虫草害，采取处理使三类危害均下降。",
                 "repair_bund": "巡检p1田埂，使用维修材料修复渗漏。",
                 "infrastructure_recovery": "巡查田埂和渠道，修复渗漏并疏通堵塞渠道。",
                 "harvest_batches": "在小粮箱和有限干燥能力下，分批完成两个田格的收割、卸粮、干燥和入库。"}
        return (goals[self.task] + " PaddyWorldApp提供台账，PaddyObservationApp提供现场观测；"
                "PaddyMachineryApp管理油箱和农具，PaddyOpsApp执行农事，PaddyInfrastructureApp维护水利，"
                "PaddyDroneApp航拍，WeatherApp查看天气，SystemApp推进时间。成品苗已入库，不需要育秧。"
                "每个田格的分批插秧须在同一UTC日完成。阶段是管理代理标签，不是大豆阶段。")

    def init_and_populate_apps(self):
        if self.crop_backend_options:
            raise ValueError("Rice has a versioned fixed model profile; soybean config overrides are not applicable")
        field, weather = configuration(self.variant)
        world = PaddyWorldApp(field=field, weather=weather)
        if self.task in CHECKPOINTS:
            world.load_state(copy.deepcopy(reference_checkpoints(self.variant)[CHECKPOINTS[self.task]]))
        self.start_time = world.sim_time
        self._initial_state = world.get_state()
        self._initial_action_count = len(world.actions)
        self.apps = [world, PaddyOpsApp(world), PaddyObservationApp(world), PaddyMachineryApp(world),
                     PaddyInfrastructureApp(world), PaddyDroneApp(world), world._weather_app,
                     SystemApp(), AgentUserInterface()]

    def recorder(self):
        world = self.get_typed_app(PaddyWorldApp)
        return ToolRecorder(world, self.get_typed_app(PaddyOpsApp), self.get_typed_app(SystemApp), world._weather_app,
                            self.get_typed_app(PaddyObservationApp), self.get_typed_app(PaddyMachineryApp),
                            self.get_typed_app(PaddyInfrastructureApp), self.get_typed_app(PaddyDroneApp))

    def oracle_solution(self, run_oracle=False):
        if run_oracle:
            recorder = self.recorder()
        else:
            clone = RiceScenario(task=self.task, variant=self.variant, **self._constructor_kwargs)
            clone.setup()
            Engine(None, clone)
            recorder = clone.recorder()
        self.workflow = run_reference(recorder, self.task)
        self._reference_checkpoints = recorder.checkpoints

    def validate(self, env):
        world = self.get_typed_app(PaddyWorldApp)
        world.advance_physics_time()
        actions = world.actions[self._initial_action_count:]
        plots = world.field.plots
        p1 = world.plot("p1")
        if self.task in {"season", "harvest_storage", "harvest_batches"}:
            goal = _all_harvested_grain_stored(world)
            if self.task == "harvest_batches":
                goal = goal and sum(a["action"] == "harvest" for a in actions) > len(plots)
        elif self.task == "establishment":
            goal = all(p.planted and p.puddled and p.levelled for p in plots)
        elif self.task == "irrigation_management":
            records = world.daily_records[len(self._initial_state["daily_records"]):]
            stress_ok = all(r["rates"].get("RFTRA", 1.) is None or
                            r["rates"].get("RFTRA", 1.) >= .8 for r in records)
            goal = (world.sim_time - self._initial_state["sim_time"] >= 10 * 86400 and
                    any(a["action"] == "irrigate" for a in actions) and stress_ok)
        elif self.task == "irrigate":
            goal = abs(sum(a["water_mm"] for a in actions if a["action"] == "irrigate" and a["plot_id"] == "p1") - 30) < 1e-6
        elif self.task == "drain":
            goal = any(a["action"] == "drain" and a["plot_id"] == "p1" and a["actual_mm"] > 0 for a in actions)
        elif self.task in {"puddle", "transplant", "harvest"}:
            goal = {"puddle": p1.puddled and p1.levelled, "transplant": p1.planted, "harvest": p1.harvested}[self.task]
        elif self.task == "observe_water":
            goal = any(k == "water:p1" and v["timestamp"] >= self.start_time for k, v in world.observations.items())
        elif self.task == "refuel":
            goal = abs(sum(a.get("liters", 0) for a in actions
                           if a["action"] == "refuel" and a["machine_id"] == "tractor") - 10.) < 1e-8
        elif self.task in {"dry", "store"}:
            original = next(b for b in self._initial_state["field"]["grain_batches"] if b["location"] == "reception")
            batch = world.batch(original["batch_id"])
            goal = batch.moisture_pct <= 14 and batch.location == ("reception" if self.task == "dry" else "stored")
        elif self.task in {"fertilize", "nutrition_management"}:
            applied = {p.plot_id: sum(a["product_kg"] for a in actions
                       if a["action"] == "apply_fertilizer" and a["plot_id"] == p.plot_id) for p in plots}
            if self.task == "fertilize":
                goal = abs(applied["p1"] - p1.unit.mass_kg(150.)) < 1e-6
            else:
                goal = (all(applied[p.plot_id] >= p.unit.mass_kg(150.) - 1e-6 for p in plots)
                        and world.sim_time - self.start_time >= 25 * 86400)
        elif self.task in {"scout", "crop_protection"}:
            goal = all(f"pests:{p.plot_id}" in world.observations for p in plots)
            goal = goal and any(a["action"] == "fly_survey" for a in actions)
            if self.task == "crop_protection":
                goal = goal and all(all(getattr(p, key) < old[key] for key in ("pests", "disease", "weeds"))
                                    for p, old in zip(plots, self._initial_state["field"]["plots"]))
        elif self.task in {"repair_bund", "infrastructure_recovery"}:
            goal = p1.bund_leak_mm_day == 0 and any(a["action"] == "repair_bund" for a in actions)
            if self.task == "infrastructure_recovery":
                goal = goal and all(c.blockage_fraction == 0 for c in world.field.channels)
        elif self.task == "gap_fill":
            goal = p1.stand_fraction >= .99 and p1.pending_stand_recovery == 0
        else:
            raise ValueError(f"Unknown task: {self.task}")
        errors = [s for s in env.workflow.dag.values()
                  if s.op_type == "TOOL_ERROR" or
                  (isinstance(s.content, dict) and s.content.get("error"))]
        audit = audit_world(world)
        metadata = {"goal_met": goal, "tool_errors": len(errors), "audit": audit,
                    "source_l3_scenario_id": self.source_l3_scenario_id,
                    "source_checkpoint_label": self.source_checkpoint_label,
                    "initial_checkpoint_sha256": self._initial_state["sha256"]}
        baseline_dir = os.environ.get("FOS_ORACLE_BASELINE_DIR")
        if baseline_dir and not getattr(self, "_building_baseline", False):
            from fairy.scenarios.rice.evaluation import compare_outcome
            path = Path(baseline_dir) / f"{self.scenario_id}.json"
            metadata["rice_outcome"] = compare_outcome(self, json.loads(path.read_text()))
        return ScenarioValidationResult(success=bool(goal and not errors and audit["success"]),
            message="Rice task, water/nitrogen balances and resource accounting evaluated",
            metadata=metadata)


def _all_harvested_grain_stored(world):
    """Complete storage means every recovered grain batch reached the warehouse.

    Resource conservation also holds when grain remains in the combine or
    reception area, so a successful balance audit alone cannot establish this
    task goal. Check the physical batches as well as each plot's derived totals.
    """
    tolerance = 1e-7
    batches = world.field.grain_batches
    if not all(b.location == "stored" and 0 <= b.moisture_pct <= 14 for b in batches):
        return False
    return all(
        p.harvested and p.stored_dry_kg > 0 and p.storage_moisture_pct == 14
        and abs(p.loaded_grain_dry_kg) <= tolerance
        and abs(p.unloaded_grain_dry_kg) <= tolerance
        and abs(p.stored_dry_kg - p.harvested_dry_kg) <= tolerance
        and abs(sum(b.dry_kg for b in batches if b.plot_id == p.plot_id)
                - p.harvested_dry_kg) <= tolerance
        for p in world.field.plots
    )


def audit_world(world):
    failures = []
    for p in world.field.plots:
        b = world.backends[p.plot_id]
        if abs(b.water.audit()["balance_residual_mm"]) > 1e-6:
            failures.append(f"{p.plot_id}: water ledger")
        accounted = p.loaded_grain_dry_kg + p.unloaded_grain_dry_kg + p.stored_dry_kg
        if abs(accounted - p.harvested_dry_kg) > 1e-7:
            failures.append(f"{p.plot_id}: grain accounting")
        if p.harvested:
            bio = p.unit.mass_kg(float(b.crop_values.get("TWSO") or 0))
            if abs(bio - p.harvested_dry_kg - p.harvest_loss_dry_kg - p.field_loss_dry_kg) > 1e-7:
                failures.append(f"{p.plot_id}: harvest accounting")
        if abs(b.nitrogen.audit()["balance_residual_n_kg_ha"]) > 1e-6:
            failures.append(f"{p.plot_id}: nitrogen ledger")
    batch = world.field.seedlings
    original = world.initial_field["seedlings"]
    if batch.quantity + batch.loaded + sum(p.seedlings_planted for p in world.field.plots) != original["quantity"] + original["loaded"]:
        failures.append("seedling accounting")
    supply = world.channel("supply")
    if supply.withdrawn_m3 > supply.quota_m3 + 1e-7:
        failures.append("water quota")
    delivered = sum(p.unit.volume_m3(world.backends[p.plot_id].water.ledger()["irrigation_mm"]) for p in world.field.plots)
    if abs(delivered - supply.delivered_m3) > 1e-6 or abs(supply.withdrawn_m3 * supply.efficiency - delivered) > 1e-6:
        failures.append("canal delivery accounting")
    drained = sum(p.unit.volume_m3(world.backends[p.plot_id].water.ledger()["drainage_mm"]) for p in world.field.plots)
    if abs(drained - world.channel("drain").discharged_m3) > 1e-6:
        failures.append("canal drainage accounting")
    if sum(p.stored_dry_kg / .86 for p in world.field.plots) > world.field.storage_capacity_kg + 1e-7:
        failures.append("grain storage capacity")
    if world.field.fuel_liters < 0:
        failures.append("negative fuel")
    f, initial = world.field, world.initial_field
    fuel = f.fuel_liters + sum(m.fuel_liters for m in f.machines) + f.fuel_used_liters
    if abs(fuel - initial["fuel_liters"] - sum(m["fuel_liters"] for m in initial["machines"])) > 1e-6:
        failures.append("fuel accounting")
    fertilizer = f.fertilizer_kg + sum(m.fertilizer_kg for m in f.machines) + f.fertilizer_applied_kg
    if abs(fertilizer - initial["fertilizer_kg"] - sum(m["fertilizer_kg"] for m in initial["machines"])) > 1e-6:
        failures.append("fertilizer accounting")
    applied_n = sum(p.unit.mass_kg(world.backends[p.plot_id].nitrogen.audit()["applied_n_kg_ha"]) for p in f.plots)
    if abs(applied_n - f.fertilizer_applied_kg * .46) > 1e-6:
        failures.append("fertilizer nitrogen accounting")
    for stock, used in (("electricity_kwh", "energy_used_kwh"), ("repair_material_kg", "repair_used_kg")):
        if abs(getattr(f, stock) + getattr(f, used) - initial[stock] - initial[used]) > 1e-6:
            failures.append(f"{stock} accounting")
    for key, used in f.chemicals_used.items():
        if abs(getattr(f, key) + used - initial[key] - initial["chemicals_used"][key]) > 1e-6:
            failures.append(f"{key} accounting")
    for p in f.plots:
        if abs(sum(b.dry_kg for b in f.grain_batches if b.plot_id == p.plot_id) - p.harvested_dry_kg) > 1e-6:
            failures.append(f"{p.plot_id}: batch accounting")
    if sum(b.wet_kg for b in f.grain_batches if b.location == "combine") > world.machine("combine").grain_capacity_wet_kg + 1e-6:
        failures.append("combine capacity")
    if not 0 <= f.drone_battery_pct <= 100:
        failures.append("drone battery bounds")
    return {"success": not failures, "failures": failures}


for _level, _task in [("l1", t) for t in ("irrigate", "drain", "puddle", "transplant", "harvest",
        "observe_water", "refuel", "dry", "store", "fertilize", "scout", "repair_bund", "gap_fill")] + [
        ("l2", t) for t in ("establishment", "irrigation_management", "harvest_storage",
                            "nutrition_management", "crop_protection", "infrastructure_recovery", "harvest_batches")]:
    _id = f"scenario_rice_{_level}_{_task}"
    globals()[f"Rice_{_level}_{_task}"] = register_scenario(_id)(type(
        f"Rice_{_level}_{_task}", (RiceScenario,), {"task": _task,
            "variant": TASK_VARIANTS.get(_task, "normal"), "__module__": __name__}))
for _variant in VARIANTS:
    _id = f"scenario_rice_l3_{_variant}"
    globals()[f"Rice_l3_{_variant}"] = register_scenario(_id)(type(
        f"Rice_l3_{_variant}", (RiceScenario,), {"variant": _variant, "__module__": __name__}))
