"""Configuration and task specifications for the registered rice scenarios."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from fairy.apps.paddy.models import PaddyField


@dataclass(frozen=True)
class RiceScenarioSpec:
    scenario_id: str
    level: Literal["L1", "L2", "L3"]
    task: str
    variant: str
    checkpoint_label: str | None
    briefing_text: str
    detailed_briefing_text: str

    @property
    def source_l3_scenario_id(self) -> str:
        return f"scenario_rice_l3_{self.variant}"

    @property
    def source_checkpoint_label(self) -> str:
        return self.checkpoint_label or "initial_before_field_prep"

    @property
    def source_slug(self) -> str:
        return f"rice_{self.variant}"


VARIANTS = (
    "normal", "water_limit", "late_rain", "nitrogen_limit", "biotic",
    "infrastructure", "equipment_limit", "poor_stand",
)

CHECKPOINTS = {
    "puddle": "before_puddle",
    "transplant": "before_transplant",
    "irrigate": "before_irrigate",
    "drain": "before_drain",
    "harvest": "before_harvest",
    "irrigation_management": "management_start",
    "harvest_storage": "before_drain",
    "observe_water": "after_transplant",
    "dry": "before_dry",
    "store": "before_store",
    "fertilize": "before_topdress",
    "scout": "before_treat",
    "crop_protection": "before_treat",
    "gap_fill": "after_transplant",
    "nutrition_management": "management_start",
    "harvest_batches": "before_drain",
}

TASK_VARIANTS = {
    "scout": "biotic",
    "crop_protection": "biotic",
    "gap_fill": "poor_stand",
    "repair_bund": "infrastructure",
    "infrastructure_recovery": "infrastructure",
    "harvest_batches": "equipment_limit",
    "refuel": "equipment_limit",
}


def configuration(variant: str) -> tuple[dict[str, Any], dict[str, Any]]:
    field = PaddyField().to_dict()
    weather: dict[str, Any] = {"rain_mm": 1.}
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


_TASK_GOALS = {
    "season": "完成两个田格从泡田整地、成品苗插秧、灌排管理到收获干燥入库的单季种植。",
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
    "harvest_batches": "在小粮箱和有限干燥能力下，分批完成两个田格的收割、卸粮、干燥和入库。",
}

_TOOL_BRIEFING = (
    " PaddyWorldApp提供台账，PaddyObservationApp提供现场观测；"
    "PaddyMachineryApp管理油箱和农具，PaddyOpsApp执行农事，PaddyInfrastructureApp维护水利，"
    "PaddyDroneApp航拍，WeatherApp查看天气，SystemApp推进时间。成品苗已入库，不需要育秧。"
    "每个田格的分批插秧须在同一UTC日完成。阶段是管理代理标签，不是大豆阶段。"
)


def _spec(level: Literal["L1", "L2", "L3"], task: str, variant: str = "normal") -> RiceScenarioSpec:
    suffix = variant if level == "L3" else task
    goal = _TASK_GOALS[task]
    return RiceScenarioSpec(
        scenario_id=f"scenario_rice_{level.lower()}_{suffix}",
        level=level,
        task=task,
        variant=variant,
        checkpoint_label=CHECKPOINTS.get(task),
        briefing_text=goal,
        detailed_briefing_text=goal + _TOOL_BRIEFING,
    )


SPECS: dict[str, RiceScenarioSpec] = {
    spec.scenario_id: spec for spec in (
        _spec("L1", "irrigate"),
        _spec("L1", "drain"),
        _spec("L1", "puddle"),
        _spec("L1", "transplant"),
        _spec("L1", "harvest"),
        _spec("L1", "observe_water"),
        _spec("L1", "refuel", "equipment_limit"),
        _spec("L1", "dry"),
        _spec("L1", "store"),
        _spec("L1", "fertilize"),
        _spec("L1", "scout", "biotic"),
        _spec("L1", "repair_bund", "infrastructure"),
        _spec("L1", "gap_fill", "poor_stand"),
        _spec("L2", "establishment"),
        _spec("L2", "irrigation_management"),
        _spec("L2", "harvest_storage"),
        _spec("L2", "nutrition_management"),
        _spec("L2", "crop_protection", "biotic"),
        _spec("L2", "infrastructure_recovery", "infrastructure"),
        _spec("L2", "harvest_batches", "equipment_limit"),
        _spec("L3", "season", "normal"),
        _spec("L3", "season", "water_limit"),
        _spec("L3", "season", "late_rain"),
        _spec("L3", "season", "nitrogen_limit"),
        _spec("L3", "season", "biotic"),
        _spec("L3", "season", "infrastructure"),
        _spec("L3", "season", "equipment_limit"),
        _spec("L3", "season", "poor_stand"),
    )
}


def get_spec(scenario_id: str) -> RiceScenarioSpec:
    return SPECS[scenario_id]
