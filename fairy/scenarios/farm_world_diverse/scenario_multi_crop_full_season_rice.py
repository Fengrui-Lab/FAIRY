"""两场旱直播水稻全季管理：各场独立建立与管理水肥。

场景 ID：scenario_multi_crop_full_season_rice
本文件包含此场景的完整实现，按以下顺序阅读：
1. 本地配置类型、单位与输入校验；
2. ScenarioMultiCropFullSeasonRice：本场景参数、农场创建、初态和逐日天气；
3. build_events_flow：任务通知和完整全季工具事件 DAG；
4. oracle_solution 与本地 _SeasonManager：事件导出和动态参考管理；
5. validate：完整过程与逐场收储验收，辅助函数也在本文件中。

所有场景配置、初始化、Oracle 和验收均在本文件，没有导入其他场景实现。
日期和事件从第 0 天计算，起止日均包含；VWC 为体积含水率（0~1）。
面积 = 垄数 × 垄长 × 每垄占地宽度，不含设施用地；现有尺寸为小型测试田块，
没有生产规模依据。底层设备工具、仿真时钟与作物物理使用 FAIRY 平台。
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
import math
from numbers import Real
import re
from typing import Any, ClassVar, Mapping

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world.crop_profiles import get_crop_profile
from fairy.apps.farm_world.multi_farm import AssetSpec, FarmFleet, FarmSite
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import register_scenario
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.scenarios.workflow import Workflow, WorkflowStep
from fairy.tool_utils import OperationType
from fairy.types import EventRegisterer


# 1. 本文件的配置类型、单位与输入校验

def _integer(name: str, value: Any, *, minimum: int, maximum: int | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        bounds = f"[{minimum}, {maximum}]" if maximum is not None else f">= {minimum}"
        raise ValueError(f"{name} must be {bounds}")


def _number(
    name: str, value: Any, *, minimum: float | None = None,
    maximum: float | None = None, strictly_positive: bool = False,
) -> None:
    try:
        finite = isinstance(value, Real) and math.isfinite(value)
    except OverflowError:
        finite = False
    if isinstance(value, bool) or not finite:
        raise ValueError(f"{name} must be a finite number")
    if strictly_positive and value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}")


def _day_window(name: str, value: tuple[int, int] | None) -> None:
    if value is None:
        return
    if not isinstance(value, tuple) or len(value) != 2:
        raise ValueError(f"{name} must be a (start_day, end_day) tuple")
    _integer(f"{name}.start_day", value[0], minimum=0)
    _integer(f"{name}.end_day", value[1], minimum=0)
    if value[0] > value[1]:
        raise ValueError(f"{name} must be an inclusive nonnegative day range")


@dataclass(frozen=True, kw_only=True)
class FieldLayout:
    """一个农场当前模拟的连续耕作地块，所有长度单位为米。

    每垄宽度在本模型中包含该垄占用的横向间距；地块宽 = 垄数 × 垄宽，
    耕作面积 = 地块宽 × 垄长，不包括道路、沟渠、仓库等设施用地。
    小垄数是测试地块的取值，不是农场面积或农业生产标准。
    """

    ridge_count: int
    ridge_length_m: float
    ridge_width_m: float

    def __post_init__(self) -> None:
        _integer("ridge_count", self.ridge_count, minimum=1)
        _number("ridge_length_m", self.ridge_length_m, strictly_positive=True)
        _number("ridge_width_m", self.ridge_width_m, strictly_positive=True)
        _number("field_width_m", self.field_width_m, strictly_positive=True)
        _number("area_m2", self.area_m2, strictly_positive=True)

    @property
    def field_width_m(self) -> float:
        """整个耕作地块的宽度，米。"""
        return self.ridge_count * self.ridge_width_m

    @property
    def area_m2(self) -> float:
        """耕作面积，平方米。"""
        return self.field_width_m * self.ridge_length_m

    @property
    def area_ha(self) -> float:
        """耕作面积，公顷；1 公顷 = 10000 平方米。"""
        return self.area_m2 / 10000

    @property
    def area_mu(self) -> float:
        """耕作面积，市亩；1 平方米 = 0.0015 亩。"""
        return self.area_m2 * 0.0015


@dataclass(frozen=True, kw_only=True)
class SoilInitialState:
    """第 0 天每垄的土壤和潜在病虫压力；VWC 与指数均为比例。"""

    topsoil_vwc: float = 0.26
    soil_temperature_c: float = 20.0
    nutrient_index: float = 0.68
    pest_pressure: float = 0.01
    disease_pressure: float = 0.01

    def __post_init__(self) -> None:
        _number("topsoil_vwc", self.topsoil_vwc, minimum=0, maximum=1)
        _number("soil_temperature_c", self.soil_temperature_c)
        _number("nutrient_index", self.nutrient_index, strictly_positive=True, maximum=1)
        _number("pest_pressure", self.pest_pressure, minimum=0, maximum=1)
        _number("disease_pressure", self.disease_pressure, minimum=0, maximum=1)


@dataclass(frozen=True, kw_only=True)
class WeatherSchedule:
    """当地确定性天气；所有 day 均从整个场景的第 0 天计。

    drought_days 和 harvest_rain_days 的起止日均包含。正常雨量会被每隔
    workable_every_n_days 天的无雨日、计划开始播种日前后的无雨日、干旱事件和
    late_dry_from_day 之后的干燥天气覆盖；收获降雨事件优先级最高。
    """

    mean_temperature_c: float = 26.0
    normal_daily_rain_mm: float = 2.0
    drought_days: tuple[int, int] | None = None
    harvest_rain_days: tuple[int, int] | None = None
    workable_every_n_days: int = 7
    late_dry_from_day: int = 130
    wind_speed_m_s: float = 2.0
    solar_radiation_mj_m2_day: float = 15.0
    daily_temperature_range_c: float = 8.0
    dry_relative_humidity_pct: float = 65.0
    rainy_relative_humidity_pct: float = 85.0
    rainy_humidity_threshold_mm: float = 8.0
    harvest_rain_mm: float = 10.0
    latitude_deg: float = 32.0
    sowing_dry_margin_days: int = 1
    forcing_buffer_days: int = 8
    initial_station_rain_mm: float = 0.0

    def __post_init__(self) -> None:
        _number("mean_temperature_c", self.mean_temperature_c)
        _number("normal_daily_rain_mm", self.normal_daily_rain_mm, minimum=0)
        _day_window("drought_days", self.drought_days)
        _day_window("harvest_rain_days", self.harvest_rain_days)
        _integer("workable_every_n_days", self.workable_every_n_days, minimum=1)
        _integer("late_dry_from_day", self.late_dry_from_day, minimum=0)
        _number("wind_speed_m_s", self.wind_speed_m_s, minimum=0)
        _number("solar_radiation_mj_m2_day", self.solar_radiation_mj_m2_day, minimum=0)
        _number("daily_temperature_range_c", self.daily_temperature_range_c, minimum=0)
        _number("dry_relative_humidity_pct", self.dry_relative_humidity_pct, minimum=0, maximum=100)
        _number("rainy_relative_humidity_pct", self.rainy_relative_humidity_pct, minimum=0, maximum=100)
        _number("rainy_humidity_threshold_mm", self.rainy_humidity_threshold_mm, minimum=0)
        _number("harvest_rain_mm", self.harvest_rain_mm, minimum=0)
        _number("latitude_deg", self.latitude_deg, minimum=-90, maximum=90)
        _integer("sowing_dry_margin_days", self.sowing_dry_margin_days, minimum=0)
        _integer("forcing_buffer_days", self.forcing_buffer_days, minimum=0)
        _number("initial_station_rain_mm", self.initial_station_rain_mm, minimum=0)


@dataclass(frozen=True, kw_only=True)
class FarmResources:
    """本场独立额度与收储能力；灌溉 mm 是全场等效水深。"""

    irrigation_budget_mm: float = 300.0
    fertilizer_budget_kg: float = 500.0
    drying_capacity_kg_per_day: float = 20000.0
    storage_capacity_kg: float = 100000.0

    def __post_init__(self) -> None:
        for item in fields(self):
            _number(item.name, getattr(self, item.name), minimum=0)


@dataclass(frozen=True, kw_only=True)
class SeasonSettings:
    """所有农场共享的日历、期限和巡检频率；日期为 ISO 日期。"""

    start_date: str = "2026-05-01"
    start_hour_utc: int = 7
    max_days: int = 180
    monitor_interval_days: int = 7

    def __post_init__(self) -> None:
        if not isinstance(self.start_date, str):
            raise ValueError("start_date must be an ISO date string (YYYY-MM-DD)")
        try:
            parsed_date = date.fromisoformat(self.start_date)
        except ValueError as error:
            raise ValueError("start_date must be an ISO date string (YYYY-MM-DD)") from error
        if parsed_date.isoformat() != self.start_date:
            raise ValueError("start_date must be an ISO date string (YYYY-MM-DD)")
        _integer("start_hour_utc", self.start_hour_utc, minimum=0, maximum=23)
        _integer("max_days", self.max_days, minimum=90, maximum=365)
        _integer("monitor_interval_days", self.monitor_interval_days, minimum=1, maximum=14)


@dataclass(frozen=True, kw_only=True)
class SeasonFarmPlan:
    """一个农场全季的输入，不包含管理动作和最终状态。

    farm_id 是公开工具的目标标识，tool_prefix 仅保留显示名和旧内部句柄兼容。
    crop_type 是作物类型，layout 明确耕作面积；库存、天气数据和额度按场配置。
    设备由本场景单独声明为资产，可以服务多个农场，不属于农场布局。
    planting_start_day 从公共第 0 天计，planting_window_days 是窗口天数，
    例如开始日 7、天数 6 表示第 7 至 12 天，包含首尾。
    """

    farm_id: str
    tool_prefix: str
    crop_type: str
    layout: FieldLayout
    planting_start_day: int = 0
    planting_window_days: int = 6
    initial_soil: SoilInitialState = field(default_factory=SoilInitialState)
    weather: WeatherSchedule = field(default_factory=WeatherSchedule)
    resources: FarmResources = field(default_factory=FarmResources)

    def __post_init__(self) -> None:
        for name in ("farm_id", "tool_prefix"):
            value = getattr(self, name)
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value):
                raise ValueError(f"{name} must start with a letter and contain letters, numbers or underscores")
        get_crop_profile(self.crop_type)
        for name, expected_type in (
            ("layout", FieldLayout), ("initial_soil", SoilInitialState),
            ("weather", WeatherSchedule), ("resources", FarmResources),
        ):
            if not isinstance(getattr(self, name), expected_type):
                raise ValueError(f"{name} must be a {expected_type.__name__}")
        _integer("planting_start_day", self.planting_start_day, minimum=0)
        _integer("planting_window_days", self.planting_window_days, minimum=1)

    # 只读别名供旧 Oracle / 验收器使用；新场景声明请使用上面的具名字段。
    @property
    def prefix(self) -> str:
        return self.tool_prefix

    @property
    def num_ridges(self) -> int:
        return self.layout.ridge_count

    @property
    def length_m(self) -> float:
        return self.layout.ridge_length_m

    @property
    def width_m(self) -> float:
        return self.layout.ridge_width_m

    @property
    def crop(self) -> str:
        return self.crop_type

    @property
    def plant_day(self) -> int:
        return self.planting_start_day

    @property
    def drought_window(self) -> tuple[int, int] | None:
        return self.weather.drought_days

    @property
    def harvest_rain_window(self) -> tuple[int, int] | None:
        return self.weather.harvest_rain_days

    @property
    def irrigation_quota_mm(self) -> float:
        return self.resources.irrigation_budget_mm

    @property
    def fertilizer_quota_kg(self) -> float:
        return self.resources.fertilizer_budget_kg

    @property
    def mean_temp_c(self) -> float:
        return self.weather.mean_temperature_c

    @property
    def base_rain_mm(self) -> float:
        return self.weather.normal_daily_rain_mm

    @property
    def initial_nutrient_index(self) -> float:
        return self.initial_soil.nutrient_index


_NESTED_TYPES = {
    "layout": FieldLayout,
    "initial_soil": SoilInitialState,
    "weather": WeatherSchedule,
    "resources": FarmResources,
}
_LEGACY_KEYS = {
    "prefix": (None, "tool_prefix"),
    "crop": (None, "crop_type"),
    "plant_day": (None, "planting_start_day"),
    "num_ridges": ("layout", "ridge_count"),
    "length_m": ("layout", "ridge_length_m"),
    "width_m": ("layout", "ridge_width_m"),
    "drought_window": ("weather", "drought_days"),
    "harvest_rain_window": ("weather", "harvest_rain_days"),
    "mean_temp_c": ("weather", "mean_temperature_c"),
    "base_rain_mm": ("weather", "normal_daily_rain_mm"),
    "initial_nutrient_index": ("initial_soil", "nutrient_index"),
    "irrigation_quota_mm": ("resources", "irrigation_budget_mm"),
    "fertilizer_quota_kg": ("resources", "fertilizer_budget_kg"),
}


def _merge_value(values: dict[str, Any], name: str, value: Any, location: str) -> None:
    integer_minima = {
        "ridge_count": 1, "planting_start_day": 0, "planting_window_days": 1,
        "workable_every_n_days": 1, "late_dry_from_day": 0,
        "sowing_dry_margin_days": 0, "forcing_buffer_days": 0,
    }
    if name in integer_minima:
        _integer(f"{location}{name}", value, minimum=integer_minima[name])
    if name in {"drought_days", "harvest_rain_days"} and isinstance(value, list):
        value = tuple(value)
    if name in values:
        previous = values[name]
        if previous != value or (isinstance(previous, bool) != isinstance(value, bool)):
            raise ValueError(f"Conflicting values for {location}{name}")
    values[name] = value


def parse_farm_config(config: Mapping[str, Any]) -> SeasonFarmPlan:
    """读取具名嵌套配置，同时兼容原 CLI 的扁平 farm_configs。

    新格式必须显式声明 layout 的垄数、长度和宽度。crop_type 缺省为
    soybean；仅旧扁平布局保留 1.1 m 垄宽默认值。同一字段指定了冲突值
    时拒绝配置，未知字段也拒绝，避免拼写错误静默回落到默认值。
    """
    if not isinstance(config, Mapping):
        raise ValueError("Each farm config must be a mapping")
    top_fields = {item.name for item in fields(SeasonFarmPlan)} - set(_NESTED_TYPES)
    unknown = set(config) - top_fields - set(_NESTED_TYPES) - set(_LEGACY_KEYS)
    if unknown:
        raise ValueError(f"Unknown farm config fields: {sorted(unknown, key=str)}")
    top: dict[str, Any] = {}
    nested: dict[str, dict[str, Any]] = {name: {} for name in _NESTED_TYPES}
    for name, nested_type in _NESTED_TYPES.items():
        if name not in config:
            continue
        value = config[name]
        # 调用方的数据类先转为字段值，再由本文件的本地类型重新构造。
        if is_dataclass(value) and not isinstance(value, type):
            value = {item.name: getattr(value, item.name) for item in fields(nested_type)}
        if not isinstance(value, Mapping):
            raise ValueError(f"{name} must be a mapping or {nested_type.__name__}")
        unknown_nested = set(value) - {item.name for item in fields(nested_type)}
        if unknown_nested:
            raise ValueError(f"Unknown {name} fields: {sorted(unknown_nested, key=str)}")
        for key, item_value in value.items():
            _merge_value(nested[name], key, item_value, f"{name}.")
    for name, value in config.items():
        if name in top_fields:
            _merge_value(top, name, value, "")
        elif name in _LEGACY_KEYS:
            group, canonical_name = _LEGACY_KEYS[name]
            destination = top if group is None else nested[group]
            _merge_value(destination, canonical_name, value, f"{group}." if group else "")

    # 仅旧的扁平配置保留隐含宽度；新场景必须让垄宽在声明处可见。
    if "layout" not in config and any(name in config for name in ("num_ridges", "length_m", "width_m")):
        nested["layout"].setdefault("ridge_width_m", 1.1)
    top.setdefault("crop_type", "soybean")
    try:
        return SeasonFarmPlan(**top, **{
            name: nested_type(**nested[name]) for name, nested_type in _NESTED_TYPES.items()
        })
    except TypeError as error:
        raise ValueError(f"Invalid farm config: {error}") from error


# 2. 本场景的工具范围、参数与完整初始化

MIN_SEASON_DAYS_AFTER_PLANTING = 60

_SEASON_TOOLS = {
    "farm": {
        "get_farm_overview", "get_ridge_range_state", "get_inventory",
        "apply_fertigation", "dry_grain", "store_grain",
    },
    "tractor": {
        "attach_implement", "detach_implement", "refuel", "load_fertilizer",
        "load_seeds", "get_status", "level", "base_fertilize", "form_ridges",
        "plant_seeds", "harvest", "unload_grain", "load_fungicide",
        "apply_fungicide", "load_pesticide", "spray_pesticide",
        "mechanical_weed_control", "return_supplies",
    },
    "field_ops": {"irrigate", "get_irrigation_log"},
    "robot": {
        "inspect_crop_health", "inspect_pests", "inspect_emergence",
        "check_status", "charge",
    },
}


@register_scenario("scenario_multi_crop_full_season_rice")
@dataclass
class ScenarioMultiCropFullSeasonRice(Scenario):
    """两场旱直播水稻全季管理：各场独立建立与管理水肥。"""

    farm_configs: list[dict[str, Any]] | None = None
    season_length_days: int | None = None
    monitor_interval_days: int | None = None

    season_settings = SeasonSettings(
        start_date="2026-05-01",
        start_hour_utc=7,
        max_days=180,
        monitor_interval_days=7,
    )

    management_objectives = (
        "每个农场从未整地空地开始，通过工具完成整地、施基肥、起垄和播种。",
        "按各场生长与本场观测安排水肥和病虫草管理，持续巡检所有未完成农场。",
        "按作物自身成熟度、籽粒含水率和本场天气分别选择收获窗口。",
        "每场粮食分别卸粮、达到安全水分后入本场粮仓；所有农场完成后结束。",
    )

    purpose = (
        "Manage two dry direct-seeded rice farms all season, with independent establishment and "
        "water/nutrient decisions."
    )

    farm_plans = (
        # RiceA：500 m² = 0.05 ha = 0.75 亩。
        SeasonFarmPlan(
            farm_id="rice_a",
            tool_prefix="RiceA",
            crop_type="rice",
            layout=FieldLayout(
                ridge_count=5,
                ridge_length_m=100.0,
                ridge_width_m=1.0,
            ),
            planting_start_day=0,
            planting_window_days=6,  # 天数，包含开始日
            initial_soil=SoilInitialState(
                topsoil_vwc=0.26,
                soil_temperature_c=20.0,
                nutrient_index=0.68,
                pest_pressure=0.01,
                disease_pressure=0.01,
            ),
            # 常雨依次被定期作业日、播种日前后停雨、干旱和季末干燥覆盖；收获雨优先。
            weather=WeatherSchedule(
                mean_temperature_c=26.0,
                normal_daily_rain_mm=2.0,
                drought_days=None,
                harvest_rain_days=None,
                workable_every_n_days=7,
                late_dry_from_day=130,
                wind_speed_m_s=2.0,
                solar_radiation_mj_m2_day=15.0,
                daily_temperature_range_c=8.0,
                dry_relative_humidity_pct=65.0,
                rainy_relative_humidity_pct=85.0,
                rainy_humidity_threshold_mm=8.0,
                harvest_rain_mm=10.0,
                latitude_deg=32.0,
                sowing_dry_margin_days=1,
                forcing_buffer_days=8,
                initial_station_rain_mm=0.0,
            ),
            # 本场独立额度；灌溉 mm 为全场等效水深，收储能力为宽松测试值。
            resources=FarmResources(
                irrigation_budget_mm=300.0,
                fertilizer_budget_kg=500.0,
                drying_capacity_kg_per_day=20000.0,
                storage_capacity_kg=100000.0,
            ),
        ),
        # RiceB：840 m² = 0.084 ha = 1.26 亩。
        SeasonFarmPlan(
            farm_id="rice_b",
            tool_prefix="RiceB",
            crop_type="rice",
            layout=FieldLayout(
                ridge_count=7,
                ridge_length_m=120.0,
                ridge_width_m=1.0,
            ),
            planting_start_day=7,
            planting_window_days=6,  # 天数，包含开始日
            initial_soil=SoilInitialState(
                topsoil_vwc=0.26,
                soil_temperature_c=20.0,
                nutrient_index=0.68,
                pest_pressure=0.01,
                disease_pressure=0.01,
            ),
            # 常雨依次被定期作业日、播种日前后停雨、干旱和季末干燥覆盖；收获雨优先。
            weather=WeatherSchedule(
                mean_temperature_c=26.0,
                normal_daily_rain_mm=2.0,
                drought_days=(45, 65),
                harvest_rain_days=None,
                workable_every_n_days=7,
                late_dry_from_day=130,
                wind_speed_m_s=2.0,
                solar_radiation_mj_m2_day=15.0,
                daily_temperature_range_c=8.0,
                dry_relative_humidity_pct=65.0,
                rainy_relative_humidity_pct=85.0,
                rainy_humidity_threshold_mm=8.0,
                harvest_rain_mm=10.0,
                latitude_deg=32.0,
                sowing_dry_margin_days=1,
                forcing_buffer_days=8,
                initial_station_rain_mm=0.0,
            ),
            # 本场独立额度；灌溉 mm 为全场等效水深，收储能力为宽松测试值。
            resources=FarmResources(
                irrigation_budget_mm=300.0,
                fertilizer_budget_kg=500.0,
                drying_capacity_kg_per_day=20000.0,
                storage_capacity_kg=100000.0,
            ),
        ),
    )

    scenario_summary: ClassVar[str] = ""
    environment_description: ClassVar[str] = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.farm_configs is not None:
            self.farm_plans = tuple(parse_farm_config(config) for config in self.farm_configs)
        if self.season_length_days is None:
            self.season_length_days = self.season_settings.max_days
        if self.monitor_interval_days is None:
            self.monitor_interval_days = self.season_settings.monitor_interval_days
        self._validate_season()

        start_date = date.fromisoformat(self.season_settings.start_date)
        self.start_time = datetime.combine(
            start_date, time(hour=self.season_settings.start_hour_utc), tzinfo=timezone.utc,
        ).timestamp()
        self.duration = self.season_length_days * 86400
        self.expects_agent_harvest = True
        self.additional_system_prompt = (
            "One management task spans all named farms for one continuous season. All farms "
            "start unprepared and unplanted. Prepare and sow each farm, then monitor all farms "
            "on the shared clock, respond to local soil/crop conditions, and harvest each crop "
            "only at its own maturity and safe weather/moisture window. Finish only when every "
            "farm's grain has been unloaded, dried if needed, and stored in its own warehouse. "
            "Use shared service tools with explicit farm_id and asset_id from the environment directory. "
            "Inventories and quotas are local; physical assets retain state across farms. Time spent "
            "at one farm ages every other farm. Read each crop profile; rice is dry direct-seeded "
            "non-flooded rice. Crop parameters are deterministic benchmark proxies."
        )

    def _validate_season(self) -> None:
        if len(self.farm_plans) < 2:
            raise ValueError("A multi-farm full-season scenario requires at least two farms")
        if (
            isinstance(self.season_length_days, bool)
            or not isinstance(self.season_length_days, int)
            or not 90 <= self.season_length_days <= 365
        ):
            raise ValueError("season_length_days must be an integer in [90, 365]")
        if (
            isinstance(self.monitor_interval_days, bool)
            or not isinstance(self.monitor_interval_days, int)
            or not 1 <= self.monitor_interval_days <= 14
        ):
            raise ValueError("monitor_interval_days must be an integer in [1, 14]")
        if any(
            plan.planting_start_day >= self.season_length_days - MIN_SEASON_DAYS_AFTER_PLANTING
            for plan in self.farm_plans
        ):
            raise ValueError("Each planting date must leave at least 60 days in the season")

    def oracle_clone(self):
        """参考策略使用独立副本，保留调用方的参数而不推进原场景。"""
        return type(self)(
            farm_configs=self.farm_configs,
            season_length_days=self.season_length_days,
            monitor_interval_days=self.monitor_interval_days,
            seed=self.seed,
            detailed_briefing=self.detailed_briefing,
            crop_backend=self.crop_backend,
            crop_backend_options=dict(self.crop_backend_options),
        )

    def init_and_populate_apps(self, *args, **kwargs) -> None:
        self._create_fleet()
        start_day = datetime.fromtimestamp(self.start_time, timezone.utc).date()
        for plan in self.farm_plans:
            site = self.fleet.get(plan.farm_id)
            self._configure_site(site, plan, start_day)
        self.scenario_input = self._build_briefing()

        # 验收器对照这些初态检查种子扣库、逐场收储和真实生长过程。
        self._initial_inventories = {
            site.spec.farm_id: site.farm.get_inventory() for site in self.fleet.sites
        }
        self._initial_states = {
            site.spec.farm_id: site.farm.get_state() for site in self.fleet.sites
        }

    def _create_fleet(self) -> None:
        """农场保存土地状态；本场景显式声明三项可跨场复用的设备资产。"""
        sites = [
            FarmSite.create(
                plan.farm_id,
                plan.tool_prefix,
                num_ridges=plan.layout.ridge_count,
                field_length_m=plan.layout.ridge_length_m,
                ridge_width_m=plan.layout.ridge_width_m,
                crop_type=plan.crop_type,
                create_devices=False,
            )
            for plan in self.farm_plans
        ]
        farm_ids = tuple(plan.farm_id for plan in self.farm_plans)
        assets = [
            AssetSpec("tractor_shared", "tractor", farm_ids),
            AssetSpec("robot_shared", "robot", farm_ids),
            AssetSpec("drone_shared", "drone", farm_ids),
        ]
        self.fleet = FarmFleet(sites, assets=assets, shared_tools=True, seed=self.seed)
        self.fleet.configure_tools(_SEASON_TOOLS)
        self.runtime_participants = [self.fleet.runtime]
        self.fleet.runtime.definition_metadata = {
            "scenario_id": self.scenario_id,
            "season_length_days": self.season_length_days,
            "monitor_interval_days": self.monitor_interval_days,
            "crop_backend": self.crop_backend,
            "crop_backend_options": deepcopy(self.crop_backend_options),
        }
        self.apps = [AgentUserInterface(), *self.fleet.apps, SystemApp()]

    def _configure_site(self, site: FarmSite, plan: SeasonFarmPlan, start_day: date) -> None:
        for app in site.apps:
            app.set_seed(self.seed)
        site.farm._sim_date = start_day.isoformat()
        self._configure_soil(site, plan)
        self._configure_limits(site, plan, start_day)
        self._configure_weather(site, plan, start_day)

    @staticmethod
    def _configure_soil(site: FarmSite, plan: SeasonFarmPlan) -> None:
        """只设置起始土壤/压力；不注入已播种或已成熟的作物。"""
        soil = plan.initial_soil
        for ridge in site.farm._ridges:
            ridge.soil_vwc = soil.topsoil_vwc
            ridge.soil_temp_c = soil.soil_temperature_c
            ridge.nutrient_index = soil.nutrient_index
            ridge.pest_pressure_base = ridge.pest_pressure = soil.pest_pressure
            ridge.disease_pressure_base = ridge.disease_pressure = soil.disease_pressure

    @staticmethod
    def _configure_limits(site: FarmSite, plan: SeasonFarmPlan, start_day: date) -> None:
        """额度和仓储逐场隔离；播种窗口包含起止两天。"""
        farm = site.farm
        resources = plan.resources
        farm.configure_management_regime(
            irrigation_quota_mm_total=resources.irrigation_budget_mm,
            fertilizer_quota_kg=resources.fertilizer_budget_kg,
        )
        farm.configure_postharvest_market(
            max_storage_moisture_pct=farm.crop_profile.storage_moisture_max_pct,
            drying_capacity_kg_per_day=resources.drying_capacity_kg_per_day,
            storage_capacity_kg=resources.storage_capacity_kg,
        )
        planting_last_day = plan.planting_start_day + plan.planting_window_days - 1
        farm.configure_planting_windows([{
            "start": 0,
            "end": plan.layout.ridge_count - 1,
            "earliest_date": (start_day + timedelta(days=plan.planting_start_day)).isoformat(),
            "latest_date": (start_day + timedelta(days=planting_last_day)).isoformat(),
        }])

    def _configure_weather(self, site: FarmSite, plan: SeasonFarmPlan, start_day: date) -> None:
        """展开确定性逐日天气；停雨不会直接修改土壤含水量。"""
        farm = site.farm
        weather = plan.weather
        farm.configure_physics_profile(
            "multi_farm_full_season", latitude_deg=weather.latitude_deg,
            random_seed=self.seed, auto_season_phase=True,
        )
        for offset in range(self.season_length_days + weather.forcing_buffer_days):
            rain = self._daily_rain_mm(plan, offset)
            farm.physics.set_weather_day_override(
                day=start_day + timedelta(days=offset),
                air_temp_mean_c=weather.mean_temperature_c,
                air_temp_min_c=weather.mean_temperature_c - weather.daily_temperature_range_c / 2,
                air_temp_max_c=weather.mean_temperature_c + weather.daily_temperature_range_c / 2,
                rain_mm=rain,
                wind_ms=weather.wind_speed_m_s,
                solar_rad_mj_m2=weather.solar_radiation_mj_m2_day,
                relative_humidity_pct=(
                    weather.dry_relative_humidity_pct
                    if rain < weather.rainy_humidity_threshold_mm
                    else weather.rainy_relative_humidity_pct
                ),
            )
        site.weather.set_weather(
            date=start_day.isoformat(),
            temp_c=weather.mean_temperature_c,
            humidity_pct=weather.dry_relative_humidity_pct,
            wind_speed_ms=weather.wind_speed_m_s,
            rainfall_mm=weather.initial_station_rain_mm,
            # WeatherApp 用 W/m²；物理引擎的天气声明用 MJ/(m²·day)。
            solar_radiation=weather.solar_radiation_mj_m2_day / 0.0864,
            avg_soil_vwc=plan.initial_soil.topsoil_vwc,
        )

    @staticmethod
    def _daily_rain_mm(plan: SeasonFarmPlan, season_day: int) -> float:
        """每日日雨量，优先级由低到高：常雨→作业/播种/干旱→收获雨。"""
        weather = plan.weather
        rain = weather.normal_daily_rain_mm
        if season_day % weather.workable_every_n_days == 0:
            rain = 0.0
        if (
            plan.planting_start_day - weather.sowing_dry_margin_days
            <= season_day
            <= plan.planting_start_day + weather.sowing_dry_margin_days
        ):
            rain = 0.0
        if weather.drought_days and weather.drought_days[0] <= season_day <= weather.drought_days[1]:
            rain = 0.0
        harvest_rain = bool(
            weather.harvest_rain_days
            and weather.harvest_rain_days[0] <= season_day <= weather.harvest_rain_days[1]
        )
        if harvest_rain:
            rain = weather.harvest_rain_mm
        # 晚季停雨支持田间通行和籽粒自然干燥；指定的收获雨保持最高优先级。
        if season_day >= weather.late_dry_from_day and not harvest_rain:
            rain = 0.0
        return rain

    def _build_briefing(self) -> str:
        """把声明转成 agent 可读任务；面积由实际模拟垄数和尺寸计算。"""
        briefing = [self.purpose]
        directory = self.fleet.describe_environment()
        self.workflow_manifest = deepcopy(self.fleet.runtime.registry.manifest)
        target_summary = {key: directory[key] for key in ("farms", "assets", "weather_stations", "clock") if key in directory}
        briefing.append("Registered environment targets: " + json.dumps(target_summary, ensure_ascii=False, sort_keys=True))
        if self.scenario_summary:
            briefing.append(self.scenario_summary)
        if self.environment_description:
            briefing.append(self.environment_description)
        briefing.extend(self.management_objectives)
        briefing.append(
            "Start with unprepared, unplanted land at every farm. Complete actual field preparation, "
            "sowing, establishment checks, repeated growth monitoring, condition-based care, "
            "maturity/weather assessment, harvest, unloading, drying and local storage. "
            "A completed farm does not end the scenario while another farm is still growing."
        )
        for plan in self.farm_plans:
            profile = self.fleet.get(plan.farm_id).farm.crop_profile
            layout = plan.layout
            planting_last_day = plan.planting_start_day + plan.planting_window_days - 1
            briefing.append(
                f"farm_id={plan.farm_id} ({plan.tool_prefix}): {layout.ridge_count} {plan.crop_type} ridges, "
                f"length {layout.ridge_length_m} m, width {layout.ridge_width_m} m. "
                f"Simulated planted area {layout.area_m2:g} m² "
                f"({layout.area_ha:g} ha; {layout.area_mu:g} mu). "
                f"Plant on season day {plan.planting_start_day}–{planting_last_day} "
                f"using {profile.seed_type}, {profile.planting_depth_cm} cm depth and "
                f"{profile.seed_spacing_cm} cm spacing. "
                f"Irrigation budget {plan.resources.irrigation_budget_mm} field-equivalent mm; "
                f"fertilizer budget {plan.resources.fertilizer_budget_kg} kg. "
                "Read the local station/forecast and soil/canopy before intervention."
            )
        briefing.append(
            "Use shared service tools with explicit farm_id and asset_id. "
            "tractor_shared, robot_shared and drone_shared each identify one physical asset serving all farms; "
            "their fuel, battery, payload and charging state persist across targets. "
            "Read the environment directory for exact tool contracts and target bindings; "
            "return residual tractor supplies to their origin before changing farms."
        )
        briefing.append(
            f"Inspect all growing farms at least every {self.monitor_interval_days} days, "
            f"revisit harvest windows more frequently, and finish within {self.season_length_days} days."
        )
        return "\n".join(briefing)

    def build_events_flow(self):
        """在独立副本推演并构图，不改变本场初态。

        自定义约束使参考策略无法完成时，event_flow_error 记录原因，
        events 保留已实际执行的前缀供诊断；导出 Oracle 时会明确拒绝。
        """
        if getattr(self, "_events_flow_built", False):
            return self.events
        if not self.apps:
            self.setup()
            return self.events

        self.events_manifest = deepcopy(self.fleet.runtime.registry.manifest)
        previous_events = EventRegisterer.last_events
        self.event_flow_error = None
        try:
            aui = self.get_typed_app(AgentUserInterface)
            with EventRegisterer.capture_mode() as briefing_events:
                briefing = (
                    aui.send_message_to_agent(content=self.scenario_input)
                    .with_id("season_briefing")
                    .depends_on(None)
                )
            briefing.operation_type = OperationType.READ
            briefing.workflow_metadata = {
                "phase": "briefing",
                "oracle_reason": "Deliver the complete multi-farm season task before field operations.",
            }
            briefing.record_runtime_timing = True
            self.events = list(briefing_events)

            # 内部推演副本仍有自己的任务事件，但不再次创建推演副本。
            if getattr(self, "_reference_rollout", False):
                self._events_flow_built = True
                return self.events

            rollout = self.oracle_clone()
            rollout._reference_rollout = True
            rollout_engine = Engine(None, rollout)
            rollout.setup()
            rollout_engine._register_scenario_apps()
            manager = _SeasonManager(rollout, record_results=True)
            try:
                reference = manager.run()
            except (RuntimeError, ValueError) as error:
                # 参考策略失败不能阻止 agent 初始化；也不能伪装成完整答案。
                self.event_flow_error = f"{type(error).__name__}: {error}"
                reference = manager.workflow

            apps_by_name = {app.name: app for app in self.apps}
            events_by_id = {}
            with EventRegisterer.capture_mode() as tool_events:
                for step in reference.dag.values():
                    app_name, method_name = step.tool_name.split("__", 1)
                    event = getattr(apps_by_name[app_name], method_name)(**deepcopy(step.tool_args or {}))
                    dependencies = [events_by_id[name] for name in step.depends_on] or [briefing]
                    # 显式 advance_time 已由引擎计时；其余作业耗时保留在图的延迟中。
                    explicit_seconds = 0.0
                    if step.tool_name == "SystemApp__advance_time":
                        args = step.tool_args or {}
                        explicit_seconds = (float(args.get("seconds", 0) or 0)
                                            + 60 * float(args.get("minutes", 0) or 0)
                                            + 3600 * float(args.get("hours", 0) or 0)
                                            + 86400 * float(args.get("days", 0) or 0))
                    action_seconds = float(step.time_after) - float(step.time_before)
                    event.oracle().with_id(step.name).depends_on(
                        dependencies, delay_seconds=max(0.0, action_seconds - explicit_seconds),
                    )
                    event.operation_type = OperationType[step.op_type]
                    event.workflow_metadata = {
                        "phase": step.content["phase"],
                        "oracle_reason": step.content["oracle_reason"],
                    }
                    event.record_runtime_timing = True
                    events_by_id[step.name] = event
            self.events = [*briefing_events, *tool_events]
            self._events_flow_built = True
            return self.events
        finally:
            # 不向其他场景泄漏 EventRegisterer 的全局兜底事件。
            EventRegisterer.last_events = previous_events


    def oracle_solution(self, run_oracle: bool = False) -> None:
        """导出 build_events_flow 的事件图，或在本场执行动态全季管理。"""
        if not run_oracle:
            self.setup()
            if self.event_flow_error:
                raise RuntimeError(f"Cannot export an incomplete season event flow: {self.event_flow_error}")
            self.workflow = Workflow()
            for event in self.events:
                self.workflow.add_node(WorkflowStep(
                    name=event.event_id,
                    content=deepcopy(event.workflow_metadata),
                    op_type=event.operation_type.name,
                    tool_name=f"{event.app.name}__{event.function.__name__}",
                    tool_args=deepcopy(event.kwargs),
                    depends_on=[dependency.event_id for dependency in event.dependencies],
                ))
            return
        if run_oracle:
            self.setup()
            target = self
            # Engine.run_scenario_oracle already supplies a shared clock.  A
            # direct caller may only have run setup(), in which case wire one now.
            managers = {id(app.time_manager) for app in target.apps}
            if len(managers) != 1 or abs(float(target.apps[0].time_manager.start_time)-float(target.start_time)) > 1:
                engine = Engine(None, target)
                engine._register_scenario_apps()
        self.workflow = _SeasonManager(target, record_results=True).run()

    def validate(self: Any, env: Any) -> ScenarioValidationResult:
        """Require a complete observed season at *every* farm under one clock."""
        failures: list[str] = []
        details: dict[str, Any] = {}
        steps = self.fleet.project_workflow_steps(list(env.workflow.dag.values()))
        times = _step_times(steps, env)
        now = float(env.time_manager.time())
        elapsed = (now - self.start_time) / _DAY
        if not steps:
            failures.append("empty workflow cannot manage a full season")
        if elapsed < 30:
            failures.append("insufficient elapsed time for a dynamically grown full season")
        if elapsed > self.season_length_days + 1:
            failures.append("season deadline exceeded")
        for step in steps:
            content = step.content
            method = str(step.tool_name).split("__")[-1]
            observational = method.startswith(("get_", "read_", "inspect_"))
            if step.error_stage or (isinstance(content, dict) and
                                    ("error" in content or ("warning" in content and not observational))):
                failures.append(f"tool failure/warning: {step.tool_name}")

        for plan in self.farm_plans:
            site = self.fleet.get(plan.farm_id)
            farm = site.farm
            physics = farm.physics
            state = farm.get_state()
            initial = self._initial_states[plan.farm_id]
            inventory = state["inventory"]
            initial_inventory = self._initial_inventories[plan.farm_id]
            ridge_ids = set(range(plan.num_ridges))
            prefix = plan.farm_id + ": "
            soil_tools = {f"{site.sensor.name}__read_soil_sensors", f"{site.sensor.name}__read_root_zone_sensors"}
            local_steps = [step for step in steps if (step.tool_args or {}).get("farm_id") == plan.farm_id]
            # Classify writes from the authoritative public contracts. Internal
            # equipment handles deliberately cannot publish another tool catalog.
            local_names = {"Farm": farm.name, "Weather": site.weather.name,
                           "Sensor": site.sensor.name, "FieldOps": site.field_ops.name,
                           "Tractor": f"{site.spec.name}Tractor",
                           "Drone": f"{site.spec.name}Drone", "Robot": f"{site.spec.name}Robot"}
            mutations = set()
            registry = self.fleet.runtime.registry
            for tool_name in registry.names:
                service, _, method = tool_name.partition("__")
                if (service in local_names and
                        registry.contract(tool_name).operation_type == OperationType.WRITE):
                    mutations.add(f"{local_names[service]}__{method}")
            writes = [step for step in local_steps if step.tool_name in mutations]
            def require(condition: bool, message: str) -> None:
                if not condition:
                    failures.append(prefix + message)

            require(all(not ridge["planted"] and not ridge["harvested"] and ridge["seeds_planted"] == 0
                        for ridge in initial["ridges"]), "scenario must begin with blank, unplanted land")
            require(len(state["ridges"]) == plan.num_ridges and
                    {row["ridge_id"] for row in state["ridges"]} == ridge_ids,
                    "configured ridge geometry was changed")
            require(abs(farm.field_length_m-plan.length_m) < 1e-8 and
                    abs(farm.ridge_width_m-plan.width_m) < 1e-8,
                    "field dimensions were changed")
            require(bool(writes), "farm was never managed")
            if writes:
                first_index = steps.index(writes[0])
                before = {step.tool_name for step in steps[:first_index]
                          if (step.tool_args or {}).get("farm_id") == plan.farm_id}
                for app, method in ((farm, "get_farm_overview"), (site.weather, "get_current_weather")):
                    require(f"{app.name}__{method}" in before, f"missing local preflight {app.name}__{method}")
                _, _, tractor_args = self.fleet.route(site.tractor, "get_status", {})
                asset_id = tractor_args["asset_id"]
                require(any(str(step.tool_name).split("__")[-1] == "get_status" and
                            (step.tool_args or {}).get("asset_id") == asset_id
                            for step in steps[:first_index]), "missing preflight status for the selected tractor asset")
                require(bool(before & soil_tools), "missing local preflight soil observations")
                after_last_write = [step for step in steps[steps.index(writes[-1])+1:]
                                    if (step.tool_args or {}).get("farm_id") == plan.farm_id]
                require(any(step.tool_name == f"{farm.name}__get_farm_overview" for step in after_last_write),
                        "missing final local farm observation")

            operations = self.fleet.operation_log(plan.farm_id, "tractor")
            prep = [entry.get("operation") for entry in operations]
            require(all(op in prep for op in ("level", "base_fertilize", "form_ridges")),
                    "field preparation was not actually performed")
            plant_steps = [step for step in local_steps if step.tool_name == f"{site.spec.name}Tractor__plant_seeds"]
            if plant_steps:
                first_plant = steps.index(plant_steps[0])
                for op in ("level", "base_fertilize", "form_ridges"):
                    require(any(step.tool_name == f"{site.spec.name}Tractor__{op}" and
                                (step.tool_args or {}).get("farm_id") == plan.farm_id
                                for step in steps[:first_plant]),
                            f"missing tool-based {op} before planting")
                require(any(step.tool_name == f"{site.weather.name}__get_forecast" and
                            (step.tool_args or {}).get("farm_id") == plan.farm_id
                            for step in steps[:first_plant]),
                        "missing planting weather forecast")
            else:
                require(False, "missing tool-based planting")

            planted_actions = [action for action in physics.action_log if action.action_type == "planting"]
            planted_ids = {rid for action in planted_actions for rid in action.ridge_ids}
            require(planted_ids == ridge_ids, "real planting history does not cover every local ridge")
            require(all(action.parameters.get("seed_type") == farm.crop_profile.seed_type for action in planted_actions),
                    "wrong crop seed was planted")
            season_start_date = datetime.fromtimestamp(self.start_time, timezone.utc).date()
            planting_last_day = plan.planting_start_day + plan.planting_window_days - 1
            planting_days = [
                (datetime.fromtimestamp(action.timestamp, timezone.utc).date() - season_start_date).days
                for action in planted_actions
            ]
            require(all(plan.planting_start_day <= day <= planting_last_day for day in planting_days),
                    "planting fell outside the farm's local planting window")
            consumed_seeds = initial_inventory["seed_stock"][farm.crop_profile.seed_type] - inventory["seed_stock"][farm.crop_profile.seed_type]
            planted_seeds = sum(int(entry.get("seeds_used", 0)) for entry in operations if entry.get("operation") in {"plant_seeds", "replant_ridges"})
            require(consumed_seeds == planted_seeds + site.tractor._seed_hopper and planted_seeds > 0,
                    "local seed mass balance does not match actual sowing")
            require(site.tractor._seed_hopper == 0, "unused seeds remain loaded at season close")
            require(all(inventory["seed_stock"][seed] == stock for seed, stock in initial_inventory["seed_stock"].items()
                        if seed != farm.crop_profile.seed_type), "another crop's local seed stock was consumed")

            phen = physics.phenology.states
            yields = physics.yield_recovery.states
            require(farm.physics_active and physics.last_physics_sim_time is not None and
                    physics.last_physics_sim_time >= self.start_time + 30*_DAY,
                    "missing elapsed physics growth")
            require(all(phen[rid].emerged and phen[rid].emergence_date is not None and
                        phen[rid].maturity_date is not None and phen[rid].planting_date is not None and
                        phen[rid].planting_date < phen[rid].emergence_date <= phen[rid].maturity_date and
                        phen[rid].days_after_planting >= 30 and phen[rid].accumulated_gdd > 0
                        for rid in ridge_ids), "crop lacks real planting, emergence and maturity dates")
            require(all(yields[rid].harvested and yields[rid].harvest_date is not None and
                        yields[rid].maturity_date is not None and
                        yields[rid].harvest_date >= yields[rid].maturity_date and
                        yields[rid].biological_yield_g_m2 > 0 and
                        yields[rid].recovered_yield_g_m2_at_market_moisture > 0 for rid in ridge_ids),
                    "not every ridge produced and recovered dynamically grown grain")
            require(all(row["harvested"] for row in state["ridges"]), "unharvested local ridges remain")
            harvest_actions = [action for action in physics.action_log if action.action_type == "harvest"]
            require({rid for action in harvest_actions for rid in action.ridge_ids} == ridge_ids and
                    all(action.direct_effect_summary.get("yield_engine_used") for action in harvest_actions),
                    "missing real yield-engine harvest history")
            if plan.harvest_rain_window is not None:
                rain_start, rain_end = plan.harvest_rain_window
                require(all(not rain_start <= (datetime.fromtimestamp(action.timestamp, timezone.utc).date()-season_start_date).days <= rain_end
                            for action in harvest_actions), "harvest occurred during the farm's local rainy window")
            recovered_kg = sum(yields[rid].recovered_yield_g_m2_at_market_moisture * farm.ridge_area_m2 / 1000
                               for rid in ridge_ids)
            stored_delta = inventory["warehouse_grain_kg"] - initial_inventory["warehouse_grain_kg"]
            tolerance_kg = max(0.06, 0.011 * len(harvest_actions))
            require(recovered_kg > 0 and abs(stored_delta-recovered_kg) <= tolerance_kg,
                    "local warehouse mass does not match recovered grain and field area")
            require(inventory["harvest_grain_kg"] == 0 and site.tractor._grain_bin_kg == 0 and
                    not state["trailer_grain_ridge_ids"] and not state["pending_bin_grain_ridge_ids"],
                    "grain remains in a local trailer or combine")
            stored_actions = [action for action in physics.action_log if action.action_type == "store_grain"]
            stored_ids = [rid for action in stored_actions for rid in action.direct_effect_summary.get("batch_ridge_ids", [])]
            require(set(stored_ids) == ridge_ids and len(stored_ids) == plan.num_ridges,
                    "storage batch provenance does not cover each local ridge once")
            storage_steps = [step for step in local_steps if step.tool_name == f"{farm.name}__store_grain"]
            require(bool(storage_steps) and all(isinstance(step.content, dict) and
                    step.content.get("moved_kg", 0) > 0 and
                    step.content.get("storage_grain_moisture_pct") is not None and
                    step.content["storage_grain_moisture_pct"] <= farm._postharvest_market.max_storage_moisture_pct + 1e-8
                    for step in storage_steps), "grain was stored without verified safe batch moisture")

            observed_groups = {group: set() for group in ("establishment", "vegetative", "reproductive", "mature")}
            group_dates: dict[str, set[str]] = {group: set() for group in observed_groups}
            soil_dates: set[str] = set()
            soil_times: set[float] = set()
            for step in local_steps:
                timestamp = times.get(id(step))
                date_label = datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat() if timestamp is not None else None
                if step.tool_name in soil_tools and date_label:
                    soil_dates.add(date_label)
                    soil_times.add(timestamp)
                if str(step.tool_name).split("__", 1)[0] != farm.name:
                    continue
                for ridge in _observed_ridges(step.content):
                    rid = ridge.get("ridge_id")
                    if rid not in ridge_ids or ridge.get("harvested"):
                        continue
                    group = _stage_group(str(ridge.get("growth_stage", "")), plan.crop)
                    if group:
                        observed_groups[group].add(rid)
                        if date_label:
                            group_dates[group].add(date_label)
                    # A fast thermal-time proxy can already reach V2 by the first
                    # establishment visit; a dated young living crop is valid.
                    planting_date = phen[rid].planting_date
                    if group and timestamp is not None and planting_date is not None:
                        dap = (datetime.fromtimestamp(timestamp, timezone.utc).date()-planting_date).days
                        if 1 <= dap <= 20:
                            observed_groups["establishment"].add(rid)
                            group_dates["establishment"].add(date_label)
            for group, covered in observed_groups.items():
                require(covered == ridge_ids, f"missing observed {group} checkpoint for every local ridge")
            require(len(soil_dates) >= 3, "missing repeated soil observations on distinct dates")
            require(len(set().union(*group_dates.values())) >= 4, "growth checkpoints do not span four distinct dates")
            first_plant_time = min((action.timestamp for action in planted_actions), default=self.start_time)
            last_harvest_time = max((action.timestamp for action in harvest_actions), default=now)
            monitoring_times = [first_plant_time, *sorted(timestamp for timestamp in soil_times
                                if first_plant_time < timestamp < last_harvest_time), last_harvest_time]
            max_monitoring_gap_days = max(((later-earlier)/_DAY for earlier, later in
                                          zip(monitoring_times, monitoring_times[1:])), default=0)
            require(max_monitoring_gap_days <= self.monitor_interval_days + 1,
                    "monitoring gap exceeded the local season inspection interval")

            # Evaluate care from the engine audit trail rather than the workflow's
            # READ/WRITE label, which an agent normally records as TOOL.
            harvest_timestamps = {rid: action.timestamp for action in harvest_actions for rid in action.ridge_ids}
            care = [action for action in physics.action_log if action.action_type in _CARE_TYPES and action.ridge_ids and
                    any(phen[rid].emergence_date is not None and
                        datetime.fromtimestamp(action.timestamp, timezone.utc).date() >= phen[rid].emergence_date and
                        action.timestamp < harvest_timestamps.get(rid, now+1)
                        for rid in action.ridge_ids)]
            require(bool(care), "missing in-season care after emergence")
            if plan.drought_window is not None:
                lo, hi = plan.drought_window
                irrigated = {rid for action in care if action.action_type == "irrigation" and
                             lo <= (action.timestamp-self.start_time)/_DAY <= hi+1
                             for rid in action.ridge_ids}
                require(irrigated == ridge_ids, "drought-window irrigation did not cover every local ridge")
            # Every high-impact crop decision uses this farm's recent evidence.
            decision_names = {f"{site.spec.name}Tractor__{method}" for method in
                              ("plant_seeds", "harvest", "apply_fertilizer", "apply_pesticide", "spray_pesticide",
                               "apply_fungicide", "apply_herbicide", "mechanical_weed", "mechanical_weed_control")}
            decision_names.add(f"{site.field_ops.name}__irrigate")
            decision_names.add(f"{farm.name}__apply_fertigation")
            for index, step in enumerate(steps):
                if (step.tool_args or {}).get("farm_id") != plan.farm_id or step.tool_name not in decision_names:
                    continue
                decision_time = times.get(id(step))
                for observation_names, method in (({f"{site.weather.name}__get_current_weather"}, "get_current_weather"),
                                                  (soil_tools, "soil observations")):
                    observations = [candidate for candidate in steps[:index]
                                    if (candidate.tool_args or {}).get("farm_id") == plan.farm_id
                                    and candidate.tool_name in observation_names]
                    recent = any(id(observation) in times and decision_time is not None and
                                 0 <= decision_time-times[id(observation)] <= 7*_DAY for observation in observations)
                    require(recent, f"{step.tool_name} lacks recent same-farm {method}")
            regime = state["management_regime"]
            require(not state["pending_irrigation"], "unapplied irrigation remains at season close")
            require(regime["irrigation_used_mm_total"] <= plan.irrigation_quota_mm + 1e-6,
                    "local irrigation quota exceeded")
            require(regime["fertilizer_used_kg"] <= plan.fertilizer_quota_kg + 1e-6,
                    "local fertilizer quota exceeded")
            details[plan.farm_id] = {
                "crop": plan.crop, "ridges": plan.num_ridges, "field_area_m2": farm.field_area_m2,
                "emerged": sum(phen[rid].emerged for rid in ridge_ids),
                "matured": sum(phen[rid].maturity_date is not None for rid in ridge_ids),
                "harvested": sum(yields[rid].harvested for rid in ridge_ids),
                "planting_dates": sorted({str(phen[rid].planting_date) for rid in ridge_ids}),
                "emergence_dates": sorted({str(phen[rid].emergence_date) for rid in ridge_ids}),
                "maturity_dates": sorted({str(phen[rid].maturity_date) for rid in ridge_ids}),
                "harvest_dates": sorted({str(yields[rid].harvest_date) for rid in ridge_ids}),
                "recovered_grain_kg": round(recovered_kg, 3), "warehouse_grain_kg": inventory["warehouse_grain_kg"],
                "yield_kg_ha": round(recovered_kg/farm.field_area_m2*10000, 3),
                "irrigation_used_mm_total": regime["irrigation_used_mm_total"],
                "fertilizer_used_kg": regime["fertilizer_used_kg"], "in_season_care_actions": len(care),
                "observed_checkpoint_dates": {group: sorted(dates) for group, dates in group_dates.items()},
                "soil_observation_dates": sorted(soil_dates),
                "max_monitoring_gap_days": round(max_monitoring_gap_days, 3),
            }
        # De-duplicate repeated pass failures without losing the farm attribution.
        failures = list(dict.fromkeys(failures))
        return ScenarioValidationResult(
            success=not failures,
            message="Every farm completed an observed, dynamically grown full season and safe local storage." if not failures else "; ".join(failures),
            metadata={"farms": details, "failures": failures, "elapsed_days": round(elapsed, 3),
                      "workflow_steps": len(steps), "oracle_kind": "dynamic_multi_farm_full_season",
                      "total_warehouse_grain_kg": round(sum(value["warehouse_grain_kg"] for value in details.values()), 3)},
        )


# 3. 本场景的完整 Oracle：公开观测、逐场管理与共享时钟调度

def _ranges(ridge_ids: list[int], width: int = 10):
    """Group only observed target ridges; never bridge a healthy gap."""
    ids = sorted(set(ridge_ids))
    if not ids:
        return
    start = end = ids[0]
    for ridge_id in ids[1:]:
        if ridge_id == end + 1 and ridge_id - start < width:
            end = ridge_id
        else:
            yield start, end
            start = end = ridge_id
    yield start, end


class _SeasonManager:
    def __init__(self, scenario, *, record_results: bool):
        self.scenario = scenario
        self.workflow = Workflow()
        self.record_results = record_results
        self._asset_farm: dict[str, str] = {}
        self.system = scenario.get_typed_app(SystemApp)
        self.start = float(scenario.start_time)
        self.deadline = self.start + scenario.season_length_days * 86400
        self.interval = int(getattr(scenario, "monitor_interval_days", 7))
        self.local: dict[str, dict[str, Any]] = {
            plan.farm_id: {"prepared": False, "sown_at": None,
                           "complete": False,
                           "next_due": float(plan.plant_day), "harvest_wait": False,
                           "nutrition_rounds": 0, "last_nutrition": -1000.0,
                           "last_insecticide": -1000.0, "last_fungicide": -1000.0,
                           "last_weeding": -1000.0}
            for plan in scenario.farm_plans
        }
        self._writes = {app.name: {tool.name for tool in app.get_tools() if tool.write_operation}
                        for app in scenario.apps}

    def call(self, app, method: str, reason: str, phase: str, **arguments):
        """通过公开共享工具执行；轨迹保留规范目标 ID 和原始返回 envelope。"""
        shared_app, shared_method, canonical_args = self.scenario.fleet.route(app, method, arguments)
        available = {tool.name for tool in shared_app.get_tools()}
        if shared_method not in available:
            raise RuntimeError(f"Reference requested a non-exposed tool: {shared_app.name}__{shared_method}")
        asset_id = canonical_args.get("asset_id")
        farm_id = canonical_args.get("farm_id")
        if asset_id and farm_id and shared_method != "return_supplies" and "return_supplies" in available:
            previous_farm = self._asset_farm.get(asset_id)
            if previous_farm is not None and previous_farm != farm_id:
                self.call(app, "return_supplies",
                    "Return residual material to its recorded origin before this shared tractor serves another farm.",
                    "resource_return")
            self._asset_farm[asset_id] = farm_id
        before = float(self.system.time_manager.time())
        raw_result = getattr(shared_app, shared_method)(**canonical_args)
        after = float(self.system.time_manager.time())
        if isinstance(raw_result, dict) and raw_result.get("ok") is False:
            raise RuntimeError(f"Reference {shared_app.name}__{shared_method} failed: {raw_result}")
        result = raw_result.get("data") if isinstance(raw_result, dict) and raw_result.get("ok") is True else raw_result
        if isinstance(result, dict) and "error" in result:
            raise RuntimeError(f"Reference {shared_app.name}__{shared_method} failed: {result}")
        # Mobility notices describe a completed inspection, not a failed
        # intervention.  The reference normally inspects during dry windows.
        if isinstance(result, dict) and result.get("warning") and not str(result["warning"]).startswith("ground_wet"):
            raise RuntimeError(f"Reference {shared_app.name}__{shared_method} warned: {result}")
        content = deepcopy(raw_result) if self.record_results else {}
        if not isinstance(content, dict):
            content = {"result": content}
        content.update(oracle_reason=reason, phase=phase)
        name = f"step{len(self.workflow)}"
        self.workflow.add_node(WorkflowStep(
            name=name, content=content,
            op_type="WRITE" if shared_method in self._writes[shared_app.name] else "READ",
            tool_name=f"{shared_app.name}__{shared_method}", tool_args=canonical_args,
            depends_on=[f"step{len(self.workflow)-1}"] if len(self.workflow) else [],
            time=datetime.fromtimestamp(after, timezone.utc).isoformat() if self.record_results else None,
            time_before=before if self.record_results else None,
            time_after=after if self.record_results else None))
        return result

    def day(self) -> float:
        return (float(self.system.time_manager.time()) - self.start) / 86400

    def observe(self, site, *, phase="monitor", harvest_wait=False):
        overview = self.call(site.farm, "get_farm_overview",
            "Identify every local ridge's planting, development, harvest and grain-inventory state.", phase)
        weather = self.call(site.weather, "get_current_weather",
            "Use this farm's current station rather than another farm's rain or wind.", phase)
        forecast = self.call(site.weather, "get_forecast",
            "Read the next seven local days before water, field-access and harvest decisions.", phase, days=7)
        soil = self.call(site.sensor, "read_soil_sensors",
            "Measure the complete farm's topsoil moisture and temperature before field work.", phase)
        roots = {"root_zone_sensors": []}
        canopy = {"canopy_sensors": []}
        if not harvest_wait:
            roots = self.call(site.sensor, "read_root_zone_sensors",
                "Measure root-zone water separately from the surface probes before irrigation.", phase)
            canopy = self.call(site.sensor, "read_canopy_sensors",
                "Track the crop canopy; low canopy readings alone do not identify their cause.", phase)
        return {"overview": overview, "weather": weather, "forecast": forecast,
                "soil": soil["soil_sensors"], "roots": roots["root_zone_sensors"],
                "canopy": canopy["canopy_sensors"]}

    def fuel(self, site, required: float, phase: str):
        status = self.call(site.tractor, "get_status",
            "Check local fuel and equipment resources before another machine operation.", phase)
        if status["fuel_tank_l"] < required + 0.1:
            inventory = self.call(site.farm, "get_inventory",
                "Check warehouse fuel before refilling the shared tractor from this farm.", phase)
            liters = min(100.0 - status["fuel_tank_l"], inventory["fuel_liters"])
            if liters <= 0 or status["fuel_tank_l"] + liters < required:
                raise RuntimeError(f"{site.spec.farm_id}: insufficient local fuel for the season")
            self.call(site.tractor, "refuel", "Transfer available fuel from this farm's warehouse.",
                      phase, liters=round(liters, 2))
            status = self.call(site.tractor, "get_status", "Confirm the refill before consuming fuel.", phase)
        return status

    def mount(self, site, implement: str, phase: str):
        status = self.call(site.tractor, "get_status", "Read the mounted implement before changing it.", phase)
        if status["attached_implement"] == implement:
            return
        if status["attached_implement"] is not None:
            self.call(site.tractor, "detach_implement", "Remove the previous implement before mounting another.", phase)
        self.call(site.tractor, "attach_implement", f"Mount the {implement} for this field operation.",
                  phase, implement=implement)

    def prepare(self, site, overview):
        phase = "field_preparation"
        area_ratio = float(overview["field_area_m2"]) / (268.0 * 64 * 1.1)
        self.fuel(site, 24.0 * area_ratio, phase)
        self.mount(site, "grader", phase)
        self.call(site.tractor, "level", "Level the initially unprepared field through the actual grader tool.", phase)
        amount = 200.0 * area_ratio
        self.call(site.tractor, "load_fertilizer", "Load the geometry-scaled base-fertilizer requirement from local stock.",
                  phase, kg=math.ceil(amount*100)/100)
        self.call(site.tractor, "base_fertilize", "Apply the base dose before forming and sowing ridges.", phase)
        self.mount(site, "furrower", phase)
        self.call(site.tractor, "form_ridges", "Create the configured ridges after levelling and base fertilization.",
                  phase, ridge_width_m=overview["ridge_width_m"])
        self.local[site.spec.farm_id]["prepared"] = True

    def sow(self, site, observation):
        overview = observation["overview"]
        profile = overview["crop_profile"]
        phase = "planting"
        n = int(overview["num_ridges"])
        # Geometry/profile are public farm configuration, not hidden crop truth.
        seeds_per_ridge = site.farm.plants_per_ridge_from_spacing(profile["seed_spacing_cm"])
        for lo in range(0, n, 4):
            hi = min(lo + 3, n - 1)
            self.fuel(site, 2.0 * overview["field_length_m"] / 268.0, phase)
            self.call(site.tractor, "load_seeds", "Load exactly this pass's crop-specific seed requirement; leave no unused hopper seed.",
                      phase, seed_type=profile["seed_type"], count=seeds_per_ridge*(hi-lo+1))
            self.call(site.tractor, "plant_seeds", "Sow at the crop profile's depth and spacing; clamp the last pass to the local ridge count.",
                      phase, start_ridge=lo, end_ridge=hi, depth_cm=profile["planting_depth_cm"],
                      seed_spacing_cm=profile["seed_spacing_cm"])
        self.local[site.spec.farm_id]["sown_at"] = float(self.system.time_manager.time())
        self.call(site.farm, "get_farm_overview", "Confirm every local ridge was planted before returning to the fleet.", phase)

    @staticmethod
    def soil_ready(observation, profile):
        low, high = profile["planting_vwc_range"]
        # Probe noise is ±.01 VWC and ±.3°C.  Use zone averages with a
        # small margin rather than pretending the observation is exact truth.
        readings = observation["soil"]
        mean_vwc = sum(r["vwc"] for r in readings)/len(readings)
        mean_temp = sum(r["temp_c"] for r in readings)/len(readings)
        return low + 0.002 <= mean_vwc <= high - 0.005 and mean_temp > profile["planting_min_temp_c"] + 0.3

    def irrigate(self, site, observation, *, preplant=False):
        profile = observation["overview"]["crop_profile"]
        stop = float(profile["irrigation_stop_vwc"])
        trigger = stop - (0.025 if profile["crop_type"] == "rice" else 0.045)
        if preplant:
            trigger = stop - 0.012
        targets = []
        for probe in observation["roots"]:
            if probe["root_vwc"] < trigger:
                targets.extend(range(probe["ridge_start"], probe["ridge_end"]+1))
        if not targets:
            return False
        inventory = self.call(site.farm, "get_inventory", "Check this farm's remaining irrigation budget before opening valves.", "water_management")
        regime = inventory["management_regime"]
        limit = regime["irrigation_quota_mm_total"]
        remaining = math.inf if limit is None else limit - regime["irrigation_used_mm_total"]
        n = observation["overview"]["num_ridges"]
        # A moderate pulse; subsequent observations decide whether another
        # pulse is justified.  The two-hour response delay is never bypassed.
        hours = min(3.0 if not preplant else 2.0, remaining * n / (5.0*len(targets)))
        if hours < 0.25:
            return False
        for lo, hi in _ranges(targets, width=n):
            self.call(site.field_ops, "irrigate", "Root-zone probes are below the crop's irrigation threshold; water only the observed dry ridges within the local quota.",
                      "water_management", start=lo, end=hi, hours=round(hours, 4))
        return True

    def inspect(self, site, observation, age_days: float):
        """Inspect full coverage in legal robot batches and diagnose low canopy."""
        if age_days < 7 or observation["weather"]["rainfall_mm"] > 0:
            return {}
        n = observation["overview"]["num_ridges"]
        health = {}
        for lo in range(0, n, 8):
            hi = min(lo+7, n-1)
            status = self.call(site.robot, "check_status", "Check battery and charging state before a ground inspection.", "crop_monitoring")
            if status["charging"] or status["battery_pct"] < 15 + 5*(hi-lo+1):
                if not status["charging"]:
                    self.call(site.robot, "charge", "Recharge the shared robot before covering the next inspection batch.", "crop_monitoring")
                self.call(self.system, "advance_time", "Allow the robot to charge; the same hour also advances every other farm.", "shared_clock", hours=1)
            method = "inspect_emergence" if age_days < 16 else "inspect_crop_health"
            result = self.call(site.robot, method,
                "Verify emergence and stand coverage." if method == "inspect_emergence" else
                "Ground-check nutrient symptoms, weeds, pests and disease before choosing a treatment.",
                "crop_monitoring", start_ridge=lo, end_ridge=hi)
            health.update({int(ridge_id): details for ridge_id, details in result.get("observations", {}).items()})
        return health

    def care(self, site, observation):
        state = self.local[site.spec.farm_id]
        age = (float(self.system.time_manager.time()) - state["sown_at"])/86400
        if age < 6:
            return
        profile = observation["overview"]["crop_profile"]
        mature = self.mature(observation)
        if mature:
            return
        # Irrigation stops once mature; care continues on the other sites.
        watered = self.irrigate(site, observation)
        health = self.inspect(site, observation, age)
        if not health:
            return
        day = self.day()
        trafficable = max(r["vwc"] for r in observation["soil"]) < 0.38
        sprayable = observation["weather"]["rainfall_mm"] == 0 and observation["weather"]["wind_speed_ms"] < 6.0
        for kind, present_key, confidence_key, cooldown in (
            ("insecticide", "pest_present", "pest_confidence", 14),
            ("fungicide", "disease_present", "disease_confidence", 14),
            ("weeding", "weed_present", "weed_confidence", 21)):
            ids = [rid for rid, item in health.items() if item.get(present_key) and item.get(confidence_key, 0) >= 0.75]
            if kind == "weeding":
                ids = [rid for rid in ids if health[rid].get("weed_pressure_band") in {"medium", "high"}]
            if not ids or not trafficable or day-state[f"last_{kind}"] < cooldown or (kind != "weeding" and not sprayable):
                continue
            inventory = self.call(site.farm, "get_inventory", "Check local treatment stock and application limits after ground diagnosis.", "crop_protection")
            regime = inventory["management_regime"]
            if kind != "weeding":
                cap = regime[f"max_{kind}_applications"]
                if cap is not None and regime[f"{kind}_applications_used"] >= cap:
                    continue
                if inventory["pesticide_liters"] < len(ids)*5.0:
                    continue
                self.call(site.tractor, "load_pesticide" if kind == "insecticide" else "load_fungicide",
                    "Load only the diagnosed target area's required chemical from this farm's stock.", "crop_protection", liters=len(ids)*5.0)
            for lo, hi in _ranges(ids):
                self.fuel(site, 2.0*observation["overview"]["field_length_m"]/268.0, "crop_protection")
                method = {"insecticide": "spray_pesticide", "fungicide": "apply_fungicide", "weeding": "mechanical_weed_control"}[kind]
                args = {"start_ridge": lo, "end_ridge": hi}
                if kind != "weeding":
                    args["liters_per_ridge"] = 5.0
                self.call(site.tractor, method, "Treat the ground-confirmed local problem, using the matching intervention rather than interpreting every canopy anomaly as drought.", "crop_protection", **args)
            state[f"last_{kind}"] = day
        # A nutrition band is an imperfect visible diagnosis, not access to
        # the hidden management engine's nutrient_index.
        deficient = [rid for rid, item in health.items()
                     if item.get("leaf_nutrition_band") == "deficient"
                     and not item.get("disease_present") and not item.get("pest_present")]
        if 20 <= age <= 85 and deficient and state["nutrition_rounds"] < 2 and day-state["last_nutrition"] >= 21:
            inventory = self.call(site.farm, "get_inventory", "Check fertilizer and water budgets before correcting the observed leaf-nutrition deficit.", "nutrition_management")
            regime = inventory["management_regime"]
            cap = regime["fertilizer_quota_kg"]
            remaining = inventory["fertilizer_kg"] if cap is None else min(inventory["fertilizer_kg"], cap-regime["fertilizer_used_kg"])
            dose = min(0.45, remaining/(30.0*len(deficient)))
            if dose >= 0.1:
                # Zero carrier water avoids duplicating a pending irrigation;
                # this tool explicitly permits nutrient-only fertigation.
                for lo, hi in _ranges(deficient):
                    self.call(site.farm, "apply_fertigation", "Ground inspection reports deficient leaf nutrition without confirmed pest/disease; apply a budgeted nutrient dose and reassess at the next visit.",
                              "nutrition_management", start_ridge=lo, end_ridge=hi,
                              nutrient_amount=round(dose, 4), water_mm=0.0)
                state["nutrition_rounds"] += 1
                state["last_nutrition"] = day
        if watered:
            # The next fleet visit is later than the delivery delay.  Do not
            # re-apply based on the still-pending surface response today.
            self.call(site.field_ops, "get_irrigation_log", "Record the completed irrigation setup; defer repeat decisions until the delayed response is observable.", "water_management")

    @staticmethod
    def mature(observation):
        overview = observation["overview"]
        stages = {str(overview["crop_profile"]["mature_stage"]).upper()}
        if overview["crop_type"] == "soybean":
            stages.add("R8_FULL_MATURITY")
        remaining = [ridge for ridge in overview["ridges_overview"] if not ridge["harvested"]]
        return bool(remaining) and all(str(ridge["growth_stage"]).upper() in stages for ridge in remaining)

    def ready_to_harvest(self, observation):
        if not self.mature(observation) or observation["weather"]["rainfall_mm"] > 0:
            return False
        profile = observation["overview"]["crop_profile"]
        if max(r["vwc"] for r in observation["soil"]) > 0.38:
            return False
        # The lower profile bound describes the desirable harvest window;
        # overdry mature grain remains harvestable (with modelled losses).
        # Requiring positive moisture excludes uninitialized grain states.
        return all(0 < ridge["grain_moisture_pct"] <= profile["harvest_moisture_max_pct"]-0.05
                   for ridge in observation["overview"]["ridges_overview"] if not ridge["harvested"])

    def harvest(self, site, observation):
        phase = "harvest_and_storage"
        overview = observation["overview"]
        self.mount(site, "harvester", phase)
        ids = [ridge["ridge_id"] for ridge in overview["ridges_overview"] if not ridge["harvested"]]
        for lo, hi in _ranges(ids, 4):
            self.fuel(site, 2.0*overview["field_length_m"]/268.0, phase)
            self.call(site.tractor, "harvest", "This farm's own observed crop is mature, moisture is safe and the local station is dry; harvest one bounded pass.",
                      phase, start_ridge=lo, end_ridge=hi)
            self.call(site.tractor, "unload_grain", "Unload this pass into its origin farm's trailer before the next combine pass.", phase)
            self.call(site.farm, "dry_grain", "Bring the current local batch to safe storage moisture before closing it.",
                      phase, target_moisture_pct=13.0)
            self.call(site.farm, "store_grain", "Move the dried local batch into this farm's warehouse and empty its trailer.", phase)
        self.call(site.farm, "get_farm_overview", "Verify every local ridge and the completed local grain balance; other farms continue their season.", phase)

    def run(self):
        # Preflight all sites before mutating any of them.  This also proves
        # that the reference started from bare land, rather than harvest snapshots.
        for plan in self.scenario.farm_plans:
            site = self.scenario.fleet.get(plan.farm_id)
            self.observe(site, phase="initial_preflight")
            self.call(site.tractor, "get_status", "Read the selected shared tractor's initial fuel, hopper, implement and combine resources.", "initial_preflight")
        while float(self.system.time_manager.time()) < self.deadline:
            for plan in self.scenario.farm_plans:
                site = self.scenario.fleet.get(plan.farm_id)
                state = self.local[plan.farm_id]
                if state["complete"] or self.day()+1e-6 < state["next_due"]:
                    continue
                observation = self.observe(site, harvest_wait=state["harvest_wait"])
                ridges = observation["overview"]["ridges_overview"]
                if all(ridge["harvested"] for ridge in ridges):
                    state["complete"] = True
                    continue
                if state["sown_at"] is None:
                    if self.day() + 1e-6 < plan.plant_day:
                        state["next_due"] = float(plan.plant_day)
                        continue
                    if not state["prepared"]:
                        self.prepare(site, observation["overview"])
                        observation = self.observe(site, phase="planting_preflight")
                    if self.soil_ready(observation, observation["overview"]["crop_profile"]):
                        self.sow(site, observation)
                        state["next_due"] = (math.floor(self.day()/self.interval)+1)*self.interval
                    else:
                        self.irrigate(site, observation, preplant=True)
                        state["next_due"] = math.floor(self.day())+1
                    continue
                self.care(site, observation)
                if self.ready_to_harvest(observation):
                    self.harvest(site, observation)
                    state["complete"] = True
                elif self.mature(observation):
                    state["harvest_wait"] = True
                    state["next_due"] = math.floor(self.day())+1
                else:
                    state["next_due"] = (math.floor(self.day()/self.interval)+1)*self.interval
            if all(state["complete"] for state in self.local.values()):
                break
            # Use absolute season days so hours spent at another farm cannot
            # drift a weekly observation past a planting or dry-weather window.
            # A mature farm's daily moisture/rain check does not force a
            # second farm through a redundant daily crop-health workup.
            target_day = min(state["next_due"] for state in self.local.values() if not state["complete"])
            target = min(self.deadline, self.start+target_day*86400)
            seconds = max(1, math.ceil(target-float(self.system.time_manager.time())))
            self.call(self.system, "advance_time", "Advance the common clock to the next planting, monitoring or harvest decision; every farm develops during the wait.", "shared_clock", seconds=seconds)
        released_assets: set[str] = set()
        for site in self.scenario.fleet.sites:
            _, _, return_args = self.scenario.fleet.route(site.tractor, "return_supplies", {})
            asset_id = return_args["asset_id"]
            if asset_id not in released_assets:
                self.call(site.tractor, "return_supplies",
                    "Return residual material to its origin before closing all farm inventory accounts.", "resource_return")
                released_assets.add(asset_id)
        final = {}
        for site in self.scenario.fleet.sites:
            overview = self.call(site.farm, "get_farm_overview", "Close the season by checking every farm's ridge completion and separate warehouse inventory.", "final_verification")
            final[site.spec.farm_id] = {"harvested": sum(r["harvested"] for r in overview["ridges_overview"]),
                                        "ridges": overview["num_ridges"],
                                        "warehouse_grain_kg": overview["inventory"]["warehouse_grain_kg"]}
        unfinished = [farm_id for farm_id, summary in final.items() if summary["harvested"] != summary["ridges"]]
        if unfinished:
            raise RuntimeError(f"Full-season reference reached the season limit with unfinished farms: {unfinished}")
        self.call(self.scenario.get_typed_app(AgentUserInterface), "send_message_to_user",
            "Report completion only after all independently developing farms reached local storage.", "completion",
            content=f"Completed the continuous multi-farm season in {self.day():.1f} days. Local harvest and warehouse results: {final}.")
        return self.workflow


# 4. 本场景验收所需的本地时间与生长阶段辅助函数

_DAY = 86400.0


_CST = timezone(timedelta(hours=8))


_CARE_TYPES = {"irrigation", "fertigation", "pesticide", "fungicide", "herbicide",
               "insecticide", "manual_spray", "mechanical_weeding", "weed_control", "mechanical_weed_control"}


def _step_times(steps: list[Any], env: Any) -> dict[int, float]:
    """Use recorded execution times, never a reference plan's target dates."""
    logs = {entry.get("step_name"): entry for entry in getattr(env.engine, "run_log", [])}
    result: dict[int, float] = {}
    for step in steps:
        value = getattr(step, "time_before", None)
        if value is None:
            value = logs.get(step.name, {}).get("sim_timestamp_before")
        if value is None and getattr(step, "time", None):
            try:
                parsed = datetime.fromisoformat(step.time)
                value = (parsed if parsed.tzinfo else parsed.replace(tzinfo=_CST)).timestamp()
            except (TypeError, ValueError):
                pass
        if value is not None:
            result[id(step)] = float(value)
    return result


def _observed_ridges(content: Any) -> list[dict[str, Any]]:
    if not isinstance(content, dict):
        return []
    if "ridges_overview" in content:
        return content["ridges_overview"]
    if "ridges" in content:
        return content["ridges"]
    return [content] if "ridge_id" in content and "growth_stage" in content else []


def _stage_group(stage: str, crop: str) -> str | None:
    value = stage.upper()
    if value in {"VE", "VC", "V1", "EMERGENCE"}:
        return "establishment"
    if value in {"TILLERING", "STEM_ELONGATION", "BOOTING"} or (value.startswith("V") and value != "VT"):
        return "vegetative"
    if value in {"HEADING", "GRAIN_FILLING", "VT"}:
        return "reproductive"
    if value in {"MATURITY", "R8", "R8_FULL_MATURITY"} or (crop == "maize" and value == "R6"):
        return "mature"
    if value.startswith("R") and len(value) >= 2 and value[1].isdigit():
        return "reproductive"
    return None


def run_full_season_oracle(scenario, run_oracle: bool = False) -> Workflow:
    """兼容函数入口，执行本文件场景自身的完整 Oracle 方法。"""
    scenario.oracle_solution(run_oracle=run_oracle)
    return scenario.workflow


def validate_full_season(scenario: Any, env: Any) -> ScenarioValidationResult:
    """兼容函数入口，使用场景自身的完整验收方法。"""
    return scenario.validate(env)
