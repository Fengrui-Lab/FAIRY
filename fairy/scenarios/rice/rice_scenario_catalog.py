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
    "refuel": "before_refuel",
    "repair_bund": "before_bund_repair",
    "puddle": "before_puddle",
    "transplant": "before_transplant",
    "irrigate": "before_irrigate",
    "drain": "before_drain",
    "harvest": "before_harvest",
    "irrigation_management": "management_start",
    "harvest_storage": "before_harvest",
    "observe_water": "before_water_observation",
    "dry": "before_dry",
    "store": "before_store",
    "fertilize": "before_topdress",
    "scout": "before_treat",
    "crop_protection": "before_treat",
    "gap_fill": "after_transplant",
    "nutrition_management": "management_start",
    "harvest_batches": "before_harvest",
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
    "establishment": "完成两个田格的泡田、耙田整平、基肥、浅水调整和成品苗插秧。",
    "irrigation_management": "根据观测完成本窗口至少 10 天的水分管理，避免胁迫并遵守共享水额。",
    "harvest_storage": "从新版来源季的收获窗口开始，复核成熟、天气、水分与通行性，完成两个田格收割、卸粮、干燥至 14% 和入库。",
    "puddle": "完成 p1 耙田整平，泡田前置条件和机具已经具备。",
    "transplant": "检查并装载成品秧苗，完成 p1 标准密度插秧。",
    "irrigate": "根据水位和根区观测，为 p1 完成 20 毫米到田灌水。",
    "drain": "把 p1 的田面水调整至约 20 毫米，为基肥和插秧准备浅水条件。",
    "harvest": "复核成熟、水分、天气和通行性，收割 p1。",
    "observe_water": "读取 p1 的田面水和根区水分传感器，保留带时间戳的观测。",
    "refuel": "为拖拉机补充 59 升燃油，使当前 1 升余油补至 60 升满箱。",
    "dry": "测量接粮区目标粮批含水率，干燥至 14%，保留在接粮区。",
    "store": "将已干燥至 14% 的目标粮批安全入库。",
    "fertilize": "检查 p1 生育阶段，装载尿素，完成 300 千克/公顷的一轮追肥。",
    "scout": "落地检查 p1 的虫、病、草害，保留分项观测；本任务只诊断。",
    "gap_fill": "检查 p1 缺苗，使用剩余成品秧苗补苗，等待两天后复查成活。",
    "nutrition_management": "根据观测完成本窗口至少 25 天的水肥管理，在分蘖期为两个田格各完成一轮 300 千克/公顷尿素追肥。",
    "crop_protection": "落地确诊两个田格的虫、病、草害，按对象、天气和水层处理并复查。",
    "repair_bund": "根据 p1 田埂巡检修复渗漏，并复查修复结果。",
    "infrastructure_recovery": "巡查田埂和渠道，疏通堵塞并修复渗漏，复查恢复情况。",
    "harvest_batches": "在 600 千克粮箱和每日 2000 千克湿谷干燥能力下，分批完成两个田格收割、卸粮、干燥至 14% 和入库；避免湿谷长时间排队。",
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
    from fairy.scenarios.rice.l3_defaults import detailed_briefing, split_briefing
    return RiceScenarioSpec(
        scenario_id=f"scenario_rice_{level.lower()}_{suffix}",
        level=level,
        task=task,
        variant=variant,
        checkpoint_label=CHECKPOINTS.get(task),
        briefing_text=goal if level == "L3" else split_briefing(f"scenario_rice_{level.lower()}_{suffix}", False),
        detailed_briefing_text=(detailed_briefing(f"scenario_rice_l3_{suffix}")
                                if level == "L3" else split_briefing(f"scenario_rice_{level.lower()}_{suffix}")),
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
