"""Fixed, synthetic reference conditions for the three maize L3 tasks.

The European Grain_maize_201 parameters are not a calibrated Harbin cultivar.
Only weather and resource limits differ between these reproducible test cases.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MaizeScenarioSpec:
    variant: str
    description: str
    precipitation_factor: float = 1.0
    initial_available_n_kg_ha: float = 50.0
    base_soil_n_kg_ha: float = 50.0
    fertilizer_stock_kg: float = 800.0
    fertilizer_quota_kg: float = 800.0
    irrigation_quota_mm: float = 300.0
    topdress_kg: float = 240.0
    irrigation_days: tuple[int, ...] = ()
    irrigation_mm: float = 30.0
    harvest_day: int = 145
    start_date: str = "2026-05-05"
    weather_seed: int = 101

    @property
    def scenario_id(self) -> str:
        return f"scenario_maize_l3_{self.variant}"

    def backend_options(self) -> dict:
        return {
            "crop_name": "maize",
            "variety_name": "Grain_maize_201",
            "reference_density_plants_m2": 1.0 / (0.75 * 0.20),
            "initial_available_n_kg_ha": self.initial_available_n_kg_ha,
            "base_soil_n_kg_ha": self.base_soil_n_kg_ha,
            "soil_n_mineralization_fraction": 0.002,
            "external_biotic_coupling": False,
        }


SPECS = {
    "normal": MaizeScenarioSpec(
        "normal", "正常资源条件下完成玉米全季种植、收获和安全入库。",
        harvest_day=101,
    ),
    "water_limit": MaizeScenarioSpec(
        "water_limit", "低降雨和限额供水条件下管理玉米，完成收获与安全入库。",
        precipitation_factor=0.25, irrigation_quota_mm=150.0,
        irrigation_days=(25, 40, 55, 70, 85),
    ),
    "nitrogen_limit": MaizeScenarioSpec(
        "nitrogen_limit", "低土壤供氮和限量肥料条件下管理玉米，完成收获与安全入库。",
        initial_available_n_kg_ha=5.0, base_soil_n_kg_ha=15.0,
        fertilizer_stock_kg=360.0, fertilizer_quota_kg=360.0,
        topdress_kg=160.0,
    ),
}


def get_spec(variant: str) -> MaizeScenarioSpec:
    return SPECS[variant]


@dataclass(frozen=True)
class MaizeTaskSpec:
    level: str
    task: str
    variant: str
    checkpoint_label: str
    briefing: str
    target_ridges: tuple[int, int] = (0, 63)
    window_days: int = 0
    water_budget_mm: float = 0.0
    fertilizer_budget_kg: float = 0.0

    @property
    def scenario_id(self) -> str:
        return f"scenario_maize_{self.level.lower()}_{self.task}"

    @property
    def source_l3_scenario_id(self) -> str:
        return SPECS[self.variant].scenario_id


# Labels refer to real boundaries in the source Python Oracle, never fabricated
# crop states. Identical L1/L2 starts deliberately share one checkpoint.
TASKS = [
    MaizeTaskSpec("L1", "level", "normal", "initial_before_field_prep",
                  "检查作业条件，挂接整平机完成全田整平，然后卸下农具。"),
    MaizeTaskSpec("L1", "base_fertilize", "normal", "before_base_fertilizer",
                  "田块已整平。装载并均匀施用200公斤基肥。", fertilizer_budget_kg=200),
    MaizeTaskSpec("L1", "form_ridges", "normal", "before_form_ridges",
                  "基肥已施用。挂接起垄机，以0.75米垄宽完成全田起垄，然后卸下农具。"),
    MaizeTaskSpec("L1", "plant", "normal", "after_seed_loading",
                  "整地和装种已完成。复核种子及设备，只为0–3垄播种：MAIZE_201、播深4厘米、株距20厘米，每垄一行。",
                  target_ridges=(0, 3)),
    MaizeTaskSpec("L1", "refuel", "normal", "before_harvest_refuel",
                  "为后续收获准备燃油。从库存将油箱补满至100升，并复查油箱及仓库的实际转移量。"),
    MaizeTaskSpec("L1", "harvest", "normal", "before_first_harvest",
                  "田块已进入可收获窗口。复核成熟、天气和籽粒水分，只收获0–3垄，粮食保留在收割机粮箱。",
                  target_ridges=(0, 3)),
    MaizeTaskSpec("L1", "unload", "normal", "before_first_unload",
                  "0–3垄已收获。将粮箱内该批粮食全部卸至接粮区，复查转移数量，暂不烘干或入库。",
                  target_ridges=(0, 3)),
    MaizeTaskSpec("L1", "dry", "normal", "before_drying",
                  "全田湿粮已卸至接粮区。检查粮食水分及容量，烘干至14%，复查后仍保留在接粮区。"),
    MaizeTaskSpec("L1", "store", "normal", "before_storage",
                  "全田粮食已完成干燥。复核水分不超过14%及仓储容量，将接粮区粮食全部入库。"),
    MaizeTaskSpec("L1", "irrigate", "water_limit", "before_first_irrigation",
                  "复核土壤和剩余配额，为全田完成一次30毫米灌溉，等待作用兑现后复查。",
                  water_budget_mm=30),
    MaizeTaskSpec("L1", "fertilize", "nitrogen_limit", "before_first_topdress",
                  "复核作物及库存，为全田均匀追施80公斤肥料产品，不添加载液灌水，复查投入记录。",
                  fertilizer_budget_kg=80),
    MaizeTaskSpec("L2", "establishment", "normal", "initial_before_field_prep",
                  "从裸地开始完成玉米建植：观测作业条件，整平、施基肥200公斤、起0.75米垄、全田播种。"
                  "使用MAIZE_201，播深4厘米、株距20厘米，每垄一行；播种后观察15天并复查全田出苗。",
                  window_days=15, fertilizer_budget_kg=200),
    MaizeTaskSpec("L2", "irrigation_management", "water_limit", "before_first_irrigation",
                  "接下来15天管理全田水分，结合天气、土壤和作物观测决定灌溉，操作后持续观察并复查。"
                  "本窗口最多使用30毫米全田等效水量，保留后续季节配额，不追加肥料。",
                  window_days=15, water_budget_mm=30),
    MaizeTaskSpec("L2", "nutrition_management", "nitrogen_limit", "before_first_topdress",
                  "接下来25天管理全田营养，结合田间观测和施肥记录决定追肥，操作后持续观察并复查。"
                  "本窗口最多使用80公斤肥料产品，保留后续季节用肥，不追加灌溉。",
                  window_days=25, fertilizer_budget_kg=80),
    MaizeTaskSpec("L2", "harvest_storage", "normal", "harvest_window_start",
                  "玉米已经生理成熟。观测天气、土壤和籽粒水分，自行判断收获窗口；水分超过25%时等待并复查。"
                  "确认条件后完成全田收获、卸粮、烘干至14%及安全入库，复查库存。"),
]
TASK_SPECS = {task.scenario_id: task for task in TASKS}

# Real source-event boundaries used only by the offline artifact exporter.
CHECKPOINT_EVENTS = {
    "normal": {
        "initial_before_field_prep": ("before", "o_preparation_weather"),
        "before_base_fertilizer": ("before", "o_load_base_fertilizer"),
        "before_form_ridges": ("before", "o_attach_furrower"),
        "after_seed_loading": ("after", "o_maize_load_seed_before_0_3"),
        "harvest_window_start": ("after", "o_day_100_crop"),
        "before_harvest_refuel": ("before", "o_refuel_before_harvest"),
        "before_first_harvest": ("before", "o_maize_harvest_0_3"),
        "before_first_unload": ("before", "o_maize_unload_after_3"),
        "before_drying": ("before", "o_maize_dry_grain"),
        "before_storage": ("before", "o_maize_store_grain"),
    },
    "water_limit": {"before_first_irrigation": ("before", "o_day_025_irrigate")},
    "nitrogen_limit": {"before_first_topdress": ("before", "o_day_025_topdress")},
}
