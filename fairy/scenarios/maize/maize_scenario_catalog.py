"""Fixed, synthetic reference conditions for the three maize L3 tasks.

The European Grain_maize_201 parameters are not a calibrated Harbin cultivar.
Physical conditions stay fixed while reference management is tested within each task.
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
    # Core reference policies only; None preserves the historical schedule.
    irrigation_schedule: tuple[tuple[int, float], ...] | None = None
    topdress_schedule: tuple[tuple[int, float], ...] | None = None
    harvest_window_day: int = 100
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
        topdress_kg=600.0,
        irrigation_schedule=((20, 50.0), (60, 50.0), (70, 50.0), (80, 50.0)),
        harvest_window_day=98, harvest_day=99,
    ),
    "water_limit": MaizeScenarioSpec(
        "water_limit", "低降雨和限额供水条件下管理玉米，完成收获与安全入库。",
        precipitation_factor=0.25, irrigation_quota_mm=150.0,
        topdress_kg=0.0, irrigation_days=(38, 58, 78), irrigation_mm=50.0,
        harvest_day=100,
    ),
    "nitrogen_limit": MaizeScenarioSpec(
        "nitrogen_limit", "低土壤供氮和限量肥料条件下管理玉米，完成收获与安全入库。",
        initial_available_n_kg_ha=5.0, base_soil_n_kg_ha=15.0,
        fertilizer_stock_kg=360.0, fertilizer_quota_kg=360.0,
        topdress_kg=160.0, topdress_schedule=((15, 80.0), (30, 80.0)),
        irrigation_schedule=((20, 50.0), (60, 50.0), (70, 50.0), (80, 50.0)),
        harvest_window_day=98, harvest_day=99,
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
        "harvest_window_start": ("after", f"o_day_{SPECS['normal'].harvest_window_day:03d}_crop"),
        "before_harvest_refuel": ("before", "o_refuel_before_harvest"),
        "before_first_harvest": ("before", "o_maize_harvest_0_3"),
        "before_first_unload": ("before", "o_maize_unload_after_3"),
        "before_drying": ("before", "o_maize_dry_grain"),
        "before_storage": ("before", "o_maize_store_grain"),
    },
    "water_limit": {"before_first_irrigation": ("before", "o_day_038_irrigate")},
    "nitrogen_limit": {"before_first_topdress": ("before", "o_day_015_topdress")},
}


def build_reference_events(scenario, spec):
    """Capture the tested management plan; construction never simulates growth.

    Keep this core-maize policy with its catalog: source_fingerprint hashes this
    file, and changing a plan invalidates its real L1/L2 checkpoints. Challenge
    scenarios keep their separately reviewed policies and source fingerprints.
    """
    from fairy.apps.agent_user_interface import AgentUserInterface
    from fairy.apps.farm_world import FarmWorldApp, FieldOpsApp, SensorApp, TractorApp, WeatherApp
    from fairy.scenarios.farm_world_fullseason_v2.harbin_l3_scenario_helpers import (
        collect_event_graph, harvest_range,
    )
    from fairy.scenarios.maize.maize_scenario_helpers import build_maize_establishment
    from fairy.types import EventRegisterer
    from fairy.apps.system import SystemApp

    system = scenario.get_typed_app(SystemApp)
    aui = scenario.get_typed_app(AgentUserInterface)
    farm = scenario.get_typed_app(FarmWorldApp)
    tractor = scenario.get_typed_app(TractorApp)
    weather = scenario.get_typed_app(WeatherApp)
    sensor = scenario.get_typed_app(SensorApp)
    field_ops = scenario.get_typed_app(FieldOpsApp)
    water = dict(spec.irrigation_schedule) if spec.irrigation_schedule is not None else {
        day: spec.irrigation_mm for day in spec.irrigation_days
    }
    fertilizer = dict(spec.topdress_schedule) if spec.topdress_schedule is not None else {
        day: spec.topdress_kg / 2.0 for day in (25, 50)
    }
    with EventRegisterer.capture_mode():
        briefing = aui.send_message_to_agent(content=scenario.scenario_input).with_id("briefing")
        prev = briefing
        prev = weather.get_current_weather().oracle().with_id("o_preparation_weather").depends_on(prev)
        prev = farm.get_inventory().oracle().with_id("o_initial_inventory").depends_on(prev)
        prev = sensor.read_soil_sensors().oracle().with_id("o_seedbed_soil").depends_on(prev)
        prev = build_maize_establishment(scenario, prev)
        previous_day = 0
        for day in sorted({15, 25, 40, 50, 70, spec.harvest_window_day, spec.harvest_day,
                           *water, *fertilizer}):
            days = day - previous_day
            # One public wait per window; physics still settles each crossed day.
            prev = system.advance_time(days=days).oracle().with_id(
                f"o_wait_to_day_{day:03d}"
            ).depends_on(prev, delay_seconds=1)
            previous_day = day
            prev = weather.get_forecast(days=7).oracle().with_id(f"o_day_{day:03d}_forecast").depends_on(prev)
            prev = sensor.read_soil_sensors().oracle().with_id(f"o_day_{day:03d}_soil").depends_on(prev)
            prev = farm.get_farm_overview().oracle().with_id(f"o_day_{day:03d}_crop").depends_on(prev)
            if fertilizer.get(day, 0) > 0:
                prev = farm.apply_fertigation(
                    start_ridge=0, end_ridge=63,
                    nutrient_amount=fertilizer[day] / (30.0 * 64), water_mm=0.0,
                ).oracle().with_id(f"o_day_{day:03d}_topdress").depends_on(prev)
            if water.get(day, 0) > 0:
                prev = field_ops.irrigate(0, 63, water[day] / 5.0).oracle().with_id(
                    f"o_day_{day:03d}_irrigate"
                ).depends_on(prev)
        prev = tractor.refuel(100.0).oracle().with_id("o_refuel_before_harvest").depends_on(prev)
        prev = harvest_range(tractor, farm, prev, start_ridge=0, end_ridge=63,
                             id_prefix="o_maize", drying_target_moisture_pct=14.0)
        prev = farm.get_inventory().oracle().with_id("o_final_inventory").depends_on(prev)
        aui.send_message_to_user(
            content="玉米全季参考操作结束；结合全田收获覆盖、水分和库存台账核实安全入库结果。"
        ).oracle().with_id("o_report").depends_on(prev)
        scenario.events = collect_event_graph(briefing)


def configure_reference_briefing(scenario, spec):
    """Expose the reviewed management guidance only for detailed briefings."""
    if type(scenario.detailed_briefing) is not bool:
        raise ValueError("detailed_briefing must be a JSON boolean: false or true")
    if not scenario.detailed_briefing:
        return
    water = spec.irrigation_schedule if spec.irrigation_schedule is not None else tuple(
        (day, spec.irrigation_mm) for day in spec.irrigation_days
    )
    fertilizer = spec.topdress_schedule if spec.topdress_schedule is not None else tuple(
        (day, spec.topdress_kg / 2.0) for day in (25, 50) if spec.topdress_kg > 0
    )
    water_text = "、".join(f"第{day}日{amount:g}毫米" for day, amount in water)
    fertilizer_text = (
        "参考追肥安排为" + "、".join(f"第{day}日{amount:g}公斤" for day, amount in fertilizer)
        + f"，加上200公斤基肥，全季共{200 + sum(amount for _, amount in fertilizer):g}公斤肥料产品。"
        if fertilizer else
        "参考方案不额外追肥，全季仅使用200公斤基肥；缺水时不要用追加肥料代替有效供水。"
    )
    scenario.scenario_input += (
        "\n\n详细管理参考：在原资源上限内，争取较高的安全入库产量。以下是管理窗口参考，"
        "不是无条件执行指令；每次作业都应核对实际天气、土壤、作物和设备状态。\n"
        "1. 建植：先复查天气、墒情、种子、肥料、燃油和设备。按顺序完成整平、"
        "200公斤基肥和0.75米起垄，再以MAIZE_201、播深4厘米、株距20厘米播完0–63垄。"
        "每次最多4垄，全田预计用种85760粒；播种后持续检查出苗和全田覆盖。\n"
        f"2. 营养管理：{fertilizer_text}肥料产品重量不等于纯氮量。"
        "追肥前检查营养与剩余库存，追肥后核对实际投入并观察响应；单独追肥不额外添加灌溉水。\n"
        f"3. 水分管理：参考灌溉安排为{water_text}，全季参考用水"
        f"{sum(amount for _, amount in water):g}毫米，上限{spec.irrigation_quota_mm:g}毫米。"
        "灌溉前检查土壤和近期预报，为后续关键生长阶段保留水量；土壤已经过湿时不要继续灌溉，"
        "根据实际生育和水分状况调整，并在处理后复查。\n"
        "4. 等待与复查：没有立即需要执行的作业时，可一次等待到下一个检查窗口，"
        "不需要每天重复发送等待命令；出现异常或接近收获门槛时缩短复查间隔。"
        "这里的日期编号对应建植后的管理窗口，作业本身也耗时，应以实际模拟日期和作物状态为准。\n"
        f"5. 收获：约第{spec.harvest_window_day}日复查成熟、籽粒水分、天气和田间条件，"
        f"参考第{spec.harvest_day}日收获。只有实际达到成熟、籽粒水分不高于25%且天气和通行条件允许时才操作；"
        "不满足时等待并复查。检查燃油，每次最多收获4垄，及时卸粮，核对全部64垄覆盖和粮箱容量。\n"
        "6. 干燥、入库与报告：卸粮后检查水分及处理容量，需要时实际干燥至14%或更低再入库。"
        "核对粮箱、接粮区和仓库的转移记录，报告真实入库产量、全田完成情况、水肥及燃油使用，"
        "不能把计划产量或口头完成声明当作已入库粮食。"
    )
