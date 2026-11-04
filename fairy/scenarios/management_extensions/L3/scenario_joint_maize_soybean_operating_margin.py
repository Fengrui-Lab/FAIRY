"""L3：两地块联合经营。题设、初始化、评估入口及完整 Oracle 均在本文件。"""

import hashlib
import json
import textwrap
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from typing import ClassVar
from zoneinfo import ZoneInfo

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world.equipment import DEFAULT_TRACTOR_IMPLEMENTS, TractorEquipment
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.sensor_app import SensorApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.system import SystemApp
from fairy.scenarios.management_extensions.runtime import (
    PlanningFarm,
    PlanningTractor,
    crop_options,
)
from fairy.scenarios.scenario import Scenario
from fairy.types import EventRegisterer

from ..apps.operating_accounts_app import OperatingAccounts, OperatingPrices
from ..apps.shared_irrigation_app import PooledIrrigation
from ..china_market_prices import operating_prices
from ..common import capture_step, finish_capture
from ..evaluation.operating_profit import evaluate
from ..oracle_management_plans import manage_joint_fields


class ScenarioJointCropOperatingMargin(Scenario):
    scenario_id = "scenario_l3_joint_maize_soybean_operating_margin"
    level = "L3"
    objective_metric = "net_operating_margin"
    oracle_policy = staticmethod(manage_joint_fields)

    # 本任务的具体环境、资源和目标参数。
    fields: ClassVar = (
        {
            "app_name": "MaizeField",
            "crop_id": "maize",
            "farm_id": "maize",
            "field_length_m": 268.0,
            "ridge_count": 16,
            "ridge_width_m": 0.75,
            "seed_type": "MAIZE_201",
        },
        {
            "app_name": "SoybeanField",
            "crop_id": "soybean",
            "farm_id": "soybean",
            "field_length_m": 268.0,
            "ridge_count": 16,
            "ridge_width_m": 1.1,
            "seed_type": "SOYBEAN_901",
        },
    )
    prices: ClassVar = OperatingPrices(**operating_prices(high_water=False))
    start: ClassVar = datetime(
        2019, 5, 1, 7, 0
    )  # noqa: DTZ001 - 本地日期，由 timezone 解释
    timezone: ClassVar = "Europe/Paris"
    duration_days: ClassVar = 213
    shared_water_m3: ClassVar = 900.0
    field_water_limit_mm: ClassVar = 180.0
    field_fertilizer_limit_kg_ha: ClassVar = 600.0
    initial_fertilizer_kg: ClassVar = 500.0
    initial_fuel_liters: ClassVar = 300.0
    storage_capacity_kg: ClassVar = 15000.0
    drying_capacity_kg_per_day: ClassVar = 10000.0
    safe_moisture_pct: ClassVar = 14.0

    ORACLE_REFERENCE: ClassVar[dict] = {
        "scenario_id": "scenario_l3_joint_maize_soybean_operating_margin",
        "input_fingerprint": "a0ab6d4c7413e711d294b4af02ea9d727e43e576aeaaf654ac2b4d55b331a87f",
        "selected": {
            "currency": "USD",
            "price_book_id": "china_northeast_2025_usd_v1",
            "cny_per_usd": 7.1757,
            "biological_kg_by_crop": {"maize": 3840.804076896348, "soybean": 1790.18432155591},
            "recovered_kg_by_crop": {"maize": 4332.069714638906, "soybean": 1960.0254869596172},
            "stored_kg_by_crop": {"maize": 4332.08, "soybean": 1960.04},
            "production_cost": 252.46567159352807,
            "stored_grain_value": 2484.0316066725195,
            "net_operating_margin": 2231.5659350789915,
        },
        "workflow_steps": 160,
        "candidate_count": 25,
        "feasible_count": 25,
        "scope": "Best feasible candidate among 25 freshly executed USD management candidates, including "
        "the prior literal workflow, a short-list ranked from archived physical receipts, and "
        "explicit crop/water/fertilizer/protection controls. Crop biology, weather and physical "
        "caps unchanged. No claim of global optimum; archived revaluations are rankings, not "
        "fresh execution.",
        "calibration_artifact": "validation_runs/management_usd_china_2025_20261103_220138/newer/scenario_l3_joint_maize_soybean_operating_margin/calibration_reference.json",
    }

    def __init__(self, *, calibrating=False, **kwargs):
        self.calibrating = calibrating
        self.fields = deepcopy(self.fields)
        self.prices = deepcopy(self.prices)
        self._input_override = kwargs.get("scenario_input")
        self._system_override = kwargs.get("additional_system_prompt")
        self._has_system_override = "additional_system_prompt" in kwargs
        if type(kwargs.get("detailed_briefing", True)) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean")
        if kwargs.pop("crop_backend", "wofost") != "wofost":
            raise ValueError("This scenario requires WOFOST")
        requested = kwargs.pop("crop_backend_options", {})
        expected = getattr(self, "backend_options", {})
        if not isinstance(requested, dict) or any(
            expected.get(k) != v for (k, v) in requested.items()
        ):
            raise ValueError(
                "This scenario does not accept non-default crop_backend_options"
            )
        kwargs.setdefault("scenario_id", self.scenario_id)
        ids = [f["farm_id"] for f in self.fields]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("Fields require unique farm IDs; crop IDs may repeat")
        for field in self.fields:
            if (
                min(
                    field["ridge_count"],
                    field["ridge_width_m"],
                    field["field_length_m"],
                )
                <= 0
            ):
                raise ValueError("Field geometry must be positive")
            if (
                field["crop_id"] not in self.prices.crop_per_kg
                or field["seed_type"] not in self.prices.seed_per_unit
            ):
                raise ValueError("Missing crop or seed price")
        super().__init__(
            crop_backend="wofost", crop_backend_options=expected.copy(), **kwargs
        )

    def __post_init__(self):
        super().__post_init__()
        self.timezone_name = self.timezone
        self.start_time = self.start.replace(
            tzinfo=ZoneInfo(self.timezone_name)
        ).timestamp()
        self.duration = self.duration_days * 86400
        self.water_capacity_m3 = self.shared_water_m3

    def setup(self, *args, **kwargs):
        if self.apps:
            return
        if args or kwargs:
            raise ValueError(
                "Declare environment changes in the scenario configuration"
            )
        self.init_and_populate_apps()
        self.scenario_input = (
            self._input_override
            if self._input_override is not None
            else self.task_description(self.detailed_briefing)
        )
        self.additional_system_prompt = (
            self._system_override if self._has_system_override else self.scenario_input
        )
        self.build_events_flow()

    def task_description(self, detailed):
        task = (
            "经营玉米和大豆两个独立地块：玉米面积3216m²、垄距0.75m；"
            "大豆面积4716.8m²、垄距1.1m。两场共用拖拉机、仓库、灌溉水源和作业时间。"
            "完成本季两场的全田种植、成熟收获及安全入库，尽量提高净经营收益。"
            "价格与余额通过 OperatingAccounts.get_accounts 查询，费用以美元核算；"
            "作物、设备和资源限制通过对应工具查询。不同作物的产量分别报告。"
        )
        if not detailed:
            return task
        guidance = textwrap.dedent(
            """\
            管理指导：

            播前核对：分别读取地块概况、作物能力和设备状态，确认种子、播种要求与整地顺序，再查公共库存和各场管理额度。按对应地块的实际规则起垄、播种；使用共享设备前检查余种、机具和载荷，换作物时先处理不匹配的余种。播后核对全田建植，不能把局部检查当成全田完成。

            水分检查与判断：分别用 MaizeSensor.read_soil_sensors 和 SoybeanSensor.read_soil_sensors 查看土壤含水量及探头覆盖范围，结合 WeatherApp.get_current_weather、WeatherApp.get_forecast 和各场的作物阶段判断需水。读数持续偏低、作物仍有需水需求且近期降水不足时，优先检查受影响区域；土壤湿润或预报有可利用降水时可暂缓。探头读数带有噪声，单次偏低不直接等于全田缺水。

            灌水处理与复查：确定需要灌水后，用地块面积换算用水体积，查各场 get_management_status 与公共水量余额，兼顾另一作物和后续生长需要，再根据当前水分与设备限制选择范围、时长及分次方案。灌溉停止阈值是操作限制，不代表最优目标。查看灌溉回执和待完成状态，待实际供水及土壤响应生效后，复读相同覆盖区探头并核对用水账；读数尚未更新时不要立即重复补灌。

            营养检查与判断：用两场的 read_canopy_sensors 观察冠层长势，结合 get_ridge_range_state 的生育阶段、可见营养指标及已施肥记录排查异常。冠层偏弱时，先检查是否尚未出苗、缺水或接近衰老，不能仅凭低 NDVI 就判断缺肥。本场没有独立土壤养分化验工具；可见营养指标只是模拟线索，不能当成实测土壤氮含量或精确施肥处方。

            施肥处理与复查：播前结合各作物需求、已有投入、库存和经营目标决定是否基施；生长期出现持续营养异常，且水分等因素不足以解释、仍处于有效吸收阶段时，再考虑分次追肥。玉米与大豆分别判断，不将玉米的投入方案直接套给大豆；证据不足时先复查。剂量由 Agent 结合可用信息、产品单位、地块面积、已施用量和剩余额度决定，装肥前扣除机上余料。施后核对实际扣量，待响应生效后复查同一区域的水分、冠层及作物状态，再决定后续投入。

            统筹与收储：按两场更早出现的农事需求安排共享设备和等待；异常时缩短复查间隔。分别依据实际成熟阶段、籽粒水分、天气和工具能力安排收获；必要时干燥后安全入库。最终核对全田完成情况、粮批来源、实际消耗与净经营收益。库存转入机具不重复计费，未用物资保留为库存；本场不另计土地、普通人工、折旧和税费。
            """
        ).strip()
        return task + "\n\n" + guidance

    def init_and_populate_apps(self):
        (self.weather, self.system) = (WeatherApp(), SystemApp())
        self.aui = AgentUserInterface()
        self.farms = []
        for field in self.fields:
            farm = PlanningFarm(
                selected_crop=field["crop_id"],
                num_ridges=field["ridge_count"],
                field_length_m=field["field_length_m"],
                ridge_width_m=field["ridge_width_m"],
            )
            farm.farm_id = field["farm_id"]
            farm.name = field["app_name"] or f"Field_{field['farm_id']}"
            farm.configure_management_regime(
                irrigation_quota_mm_total=self.field_water_limit_mm,
                fertilizer_quota_kg=self.field_fertilizer_limit_kg_ha
                * farm.field_area_m2
                / 10000,
            )
            self.farms.append(farm)
        self.sensors = {
            f.farm_id: SensorApp(f, name=f"{f.farm_id.title()}Sensor")
            for f in self.farms
        }
        self.irrigation = {
            f.farm_id: PooledIrrigation(
                f,
                self.weather,
                self.farms,
                self.water_capacity_m3,
                name=f"{f.farm_id.title()}Irrigation",
            )
            for f in self.farms
        }
        seeds = {}
        for field, farm in zip(self.fields, self.farms):
            seeds[field["seed_type"]] = (
                seeds.get(field["seed_type"], 0)
                + crop_options(farm)[field["crop_id"]]["required_seeds"]
            )
        self.warehouse = WarehouseApp(
            WarehouseStock(
                seed_stock=seeds,
                pesticide_liters=0.0,
                fertilizer_kg=self.initial_fertilizer_kg,
                fuel_liters=self.initial_fuel_liters,
            ),
            storage_capacity_kg=self.storage_capacity_kg,
            drying_capacity_kg_per_day=self.drying_capacity_kg_per_day,
            max_storage_moisture_pct=self.safe_moisture_pct,
        )
        contexts = [
            FarmContext(
                f.farm_id,
                f,
                self.weather,
                self.sensors[f.farm_id],
                self.irrigation[f.farm_id],
            )
            for f in self.farms
        ]
        self.farm_environment = FarmEnvironment(
            contexts,
            self.weather,
            warehouse=self.warehouse,
            start_time=self.start_time,
            timezone_name=self.timezone_name,
        )
        self.tractor = PlanningTractor(
            self.farm_environment,
            equipment=TractorEquipment(
                implements=(*DEFAULT_TRACTOR_IMPLEMENTS, "seeder"),
                ridging_implement="furrower",
            ),
        )
        self.initial_machine_fuel = self.tractor._fuel_tank_l
        self.accounts = OperatingAccounts(
            farms=self.farms,
            warehouse=self.warehouse,
            tractor=self.tractor,
            prices=self.prices,
            initial_machine_fuel=self.initial_machine_fuel,
            water_capacity_m3=self.water_capacity_m3,
            operation_deadline=datetime.fromtimestamp(
                self.start_time + self.duration, ZoneInfo(self.timezone_name)
            ).isoformat(),
        )
        self.apps = [
            self.aui,
            *self.farms,
            self.weather,
            *self.sensors.values(),
            *self.irrigation.values(),
            self.warehouse,
            self.tractor,
            self.system,
            self.accounts,
        ]
        self.system.attach_farm_environment(self.farm_environment)
        for app in self.apps:
            app.register_time_manager(self.farm_environment.time_manager)
            app.rng.seed(0)
        self.weather.set_weather(
            date=self.start.date().isoformat(),
            temp_c=12.0,
            humidity_pct=65.0,
            wind_speed_ms=2.0,
            rainfall_mm=0.0,
            solar_radiation=15 / 0.0864,
            avg_soil_vwc=0.26,
        )

    def validate(self, env=None):
        """按本场景目标读取真实执行结果评分。"""
        return evaluate(self)

    def input_signature(self) -> dict:
        configuration = {
            "fields": self.fields,
            "prices": asdict(self.prices),
            "start": self.start,
            "timezone": self.timezone,
            "duration_days": self.duration_days,
            "shared_water_m3": self.shared_water_m3,
            "field_water_limit_mm": self.field_water_limit_mm,
            "field_fertilizer_limit_kg_ha": self.field_fertilizer_limit_kg_ha,
            "initial_fertilizer_kg": self.initial_fertilizer_kg,
            "initial_fuel_liters": self.initial_fuel_liters,
            "storage_capacity_kg": self.storage_capacity_kg,
            "drying_capacity_kg_per_day": self.drying_capacity_kg_per_day,
            "safe_moisture_pct": self.safe_moisture_pct,
        }
        "Comparable physical/economic inputs; excludes mutable episode state."
        from fairy.scenarios.fos.provenance import crop_backend_provenance

        return {
            "schema": 2,
            "scenario_id": self.scenario_id,
            "plan": configuration,
            "prices": asdict(self.prices),
            "initial_resources": {
                "warehouse_stock": asdict(self.warehouse._initial_stock),
                "tractor_fuel_liters": self.initial_machine_fuel,
                "tractor_equipment": asdict(self.tractor.equipment),
                "warehouse_storage_capacity_kg": self.warehouse.storage_capacity_kg,
                "warehouse_drying_capacity_kg_per_day": self.warehouse.drying_capacity_kg_per_day,
                "warehouse_max_storage_moisture_pct": self.warehouse.max_storage_moisture_pct,
            },
            "shared_water_capacity_m3": self.water_capacity_m3,
            "start_time": self.start_time,
            "duration": self.duration,
            "farms": [
                {
                    "farm_id": f.farm_id,
                    "area_m2": f.field_area_m2,
                    "ridge_count": f.num_ridges,
                    "crop_backend": crop_backend_provenance(f),
                    "weather": f.physics.scenario_metadata,
                }
                for f in self.farms
            ],
        }

    def get_oracle_reference(self):
        """A derived scene cannot silently inherit another scenario's benchmark."""
        reference = getattr(self, "ORACLE_REFERENCE", None)
        if reference and reference["scenario_id"] == self.scenario_id:
            return reference
        return None

    def input_fingerprint(self):
        return hashlib.sha256(
            json.dumps(self.input_signature(), sort_keys=True, default=str).encode()
        ).hexdigest()

    def prepare_oracle_capture(self):
        """Validate reference identity; concrete scenes contain the actual actions."""
        if self.calibrating:
            self.events = []
            return False
        reference = self.get_oracle_reference()
        if reference is None:
            raise ValueError("This scenario has no calibrated Oracle reference")
        if reference.get("input_fingerprint") != self.input_fingerprint():
            raise ValueError(
                "Calibrated reference does not match this scene's physical/economic inputs"
            )
        return True

    def verification_state(self):
        return {
            "farms": [farm.get_state() for farm in self.farms],
            "warehouse": self.warehouse.get_state(),
            "tractor": self.tractor.get_state(),
            "irrigation": {
                name: controller.get_state()
                for (name, controller) in self.irrigation.items()
            },
            "clock": self.farm_environment.time_manager.time(),
            "accounts": self.accounts.compute_accounts(),
        }

    def build_events_flow(self):
        if not self.prepare_oracle_capture():
            return []
        apps = {app.name: app for app in self.apps}
        with EventRegisterer.capture_mode() as events:
            previous = None
            previous = capture_step(
                previous,
                apps["OperatingAccounts"].get_accounts(),
                "step0000",
                "执行公开工具 OperatingAccounts__get_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].get_inventory(),
                "step0001",
                "执行公开工具 Warehouse__get_inventory；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["MaizeField"].get_crop_capabilities(),
                "step0002",
                "执行公开工具 MaizeField__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0003",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0004",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["MaizeSensor"].read_soil_sensors(),
                "step0005",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["MaizeField"].get_ridge_range_state(start=0, end=15),
                "step0006",
                "执行公开工具 MaizeField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].get_status(),
                "step0007",
                "执行公开工具 Tractor__get_status；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].attach_implement(implement="grader"),
                "step0008",
                "执行公开工具 Tractor__attach_implement；参数 {'implement': 'grader'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].level(farm_id="maize"),
                "step0009",
                "执行公开工具 Tractor__level；参数 {'farm_id': 'maize'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0010",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].load_fertilizer(kg=96.48),
                "step0011",
                "执行公开工具 Tractor__load_fertilizer；参数 {'kg': 96.48}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].base_fertilize(farm_id="maize", total_kg=96.48),
                "step0012",
                "执行公开工具 Tractor__base_fertilize；参数 {'farm_id': 'maize', 'total_kg': 96.48}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].attach_implement(implement="furrower"),
                "step0013",
                "执行公开工具 Tractor__attach_implement；参数 {'implement': 'furrower'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].form_ridges(farm_id="maize", ridge_width_m=0.75),
                "step0014",
                "执行公开工具 Tractor__form_ridges；参数 {'farm_id': 'maize', 'ridge_width_m': 0.75}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0015",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].attach_implement(implement="seeder"),
                "step0016",
                "执行公开工具 Tractor__attach_implement；参数 {'implement': 'seeder'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].load_seeds(seed_type="MAIZE_201", count=21440),
                "step0017",
                "执行公开工具 Tractor__load_seeds；参数 {'seed_type': 'MAIZE_201', 'count': 21440}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].plant_seeds(
                    farm_id="maize",
                    start_ridge=0,
                    end_ridge=3,
                    depth_cm=5.0,
                    seed_spacing_cm=20.0,
                ),
                "step0018",
                "执行公开工具 Tractor__plant_seeds；参数 {'farm_id': 'maize', 'start_ridge': 0, 'end_ridge': 3, 'depth_cm': 5.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].plant_seeds(
                    farm_id="maize",
                    start_ridge=4,
                    end_ridge=7,
                    depth_cm=5.0,
                    seed_spacing_cm=20.0,
                ),
                "step0019",
                "执行公开工具 Tractor__plant_seeds；参数 {'farm_id': 'maize', 'start_ridge': 4, 'end_ridge': 7, 'depth_cm': 5.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].plant_seeds(
                    farm_id="maize",
                    start_ridge=8,
                    end_ridge=11,
                    depth_cm=5.0,
                    seed_spacing_cm=20.0,
                ),
                "step0020",
                "执行公开工具 Tractor__plant_seeds；参数 {'farm_id': 'maize', 'start_ridge': 8, 'end_ridge': 11, 'depth_cm': 5.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].plant_seeds(
                    farm_id="maize",
                    start_ridge=12,
                    end_ridge=15,
                    depth_cm=5.0,
                    seed_spacing_cm=20.0,
                ),
                "step0021",
                "执行公开工具 Tractor__plant_seeds；参数 {'farm_id': 'maize', 'start_ridge': 12, 'end_ridge': 15, 'depth_cm': 5.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0022",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_crop_capabilities(),
                "step0023",
                "执行公开工具 SoybeanField__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0024",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0025",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0026",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0027",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].get_status(),
                "step0028",
                "执行公开工具 Tractor__get_status；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].attach_implement(implement="grader"),
                "step0029",
                "执行公开工具 Tractor__attach_implement；参数 {'implement': 'grader'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].level(farm_id="soybean"),
                "step0030",
                "执行公开工具 Tractor__level；参数 {'farm_id': 'soybean'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0031",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].attach_implement(implement="furrower"),
                "step0032",
                "执行公开工具 Tractor__attach_implement；参数 {'implement': 'furrower'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].form_ridges(farm_id="soybean", ridge_width_m=1.1),
                "step0033",
                "执行公开工具 Tractor__form_ridges；参数 {'farm_id': 'soybean', 'ridge_width_m': 1.1}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0034",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].attach_implement(implement="seeder"),
                "step0035",
                "执行公开工具 Tractor__attach_implement；参数 {'implement': 'seeder'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].load_seeds(seed_type="SOYBEAN_901", count=188672),
                "step0036",
                "执行公开工具 Tractor__load_seeds；参数 {'seed_type': 'SOYBEAN_901', 'count': 188672}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].plant_seeds(
                    farm_id="soybean",
                    start_ridge=0,
                    end_ridge=3,
                    depth_cm=4.0,
                    seed_spacing_cm=4.545454545454546,
                ),
                "step0037",
                "执行公开工具 Tractor__plant_seeds；参数 {'farm_id': 'soybean', 'start_ridge': 0, 'end_ridge': 3, 'depth_cm': 4.0, 'seed_spacing_cm': 4.545454545454546}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].plant_seeds(
                    farm_id="soybean",
                    start_ridge=4,
                    end_ridge=7,
                    depth_cm=4.0,
                    seed_spacing_cm=4.545454545454546,
                ),
                "step0038",
                "执行公开工具 Tractor__plant_seeds；参数 {'farm_id': 'soybean', 'start_ridge': 4, 'end_ridge': 7, 'depth_cm': 4.0, 'seed_spacing_cm': 4.545454545454546}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].plant_seeds(
                    farm_id="soybean",
                    start_ridge=8,
                    end_ridge=11,
                    depth_cm=4.0,
                    seed_spacing_cm=4.545454545454546,
                ),
                "step0039",
                "执行公开工具 Tractor__plant_seeds；参数 {'farm_id': 'soybean', 'start_ridge': 8, 'end_ridge': 11, 'depth_cm': 4.0, 'seed_spacing_cm': 4.545454545454546}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].plant_seeds(
                    farm_id="soybean",
                    start_ridge=12,
                    end_ridge=15,
                    depth_cm=4.0,
                    seed_spacing_cm=4.545454545454546,
                ),
                "step0040",
                "执行公开工具 Tractor__plant_seeds；参数 {'farm_id': 'soybean', 'start_ridge': 12, 'end_ridge': 15, 'depth_cm': 4.0, 'seed_spacing_cm': 4.545454545454546}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0041",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=3448207.0),
                "step0042",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 3448207.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0043",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0044",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["MaizeSensor"].read_soil_sensors(),
                "step0045",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["MaizeField"].get_ridge_range_state(start=0, end=15),
                "step0046",
                "执行公开工具 MaizeField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0047",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0048",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0049",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0050",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].load_fertilizer(kg=60.300000000000004),
                "step0051",
                "执行公开工具 Tractor__load_fertilizer；参数 {'kg': 60.300000000000004}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].apply_fertilizer(
                    farm_id="maize", start_ridge=0, end_ridge=9, kg_per_ridge=6.03
                ),
                "step0052",
                "执行公开工具 Tractor__apply_fertilizer；参数 {'farm_id': 'maize', 'start_ridge': 0, 'end_ridge': 9, 'kg_per_ridge': 6.03}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].load_fertilizer(kg=36.18),
                "step0053",
                "执行公开工具 Tractor__load_fertilizer；参数 {'kg': 36.18}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].apply_fertilizer(
                    farm_id="maize", start_ridge=10, end_ridge=15, kg_per_ridge=6.03
                ),
                "step0054",
                "执行公开工具 Tractor__apply_fertilizer；参数 {'farm_id': 'maize', 'start_ridge': 10, 'end_ridge': 15, 'kg_per_ridge': 6.03}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1814020.0),
                "step0055",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1814020.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0056",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0057",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["MaizeSensor"].read_soil_sensors(),
                "step0058",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["MaizeField"].get_ridge_range_state(start=0, end=15),
                "step0059",
                "执行公开工具 MaizeField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["MaizeIrrigation"].irrigate(start=0, end=15, hours=8.25),
                "step0060",
                "执行公开工具 MaizeIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 8.25}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0061",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["MaizeSensor"].read_soil_sensors(),
                "step0062",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=229200.0),
                "step0063",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 229200.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0064",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0065",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0066",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0067",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanIrrigation"].irrigate(start=0, end=15, hours=5.0),
                "step0068",
                "执行公开工具 SoybeanIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 5.0}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0069",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0070",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=759300.0),
                "step0071",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 759300.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0072",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0073",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["MaizeSensor"].read_soil_sensors(),
                "step0074",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["MaizeField"].get_ridge_range_state(start=0, end=15),
                "step0075",
                "执行公开工具 MaizeField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["MaizeIrrigation"].irrigate(start=0, end=15, hours=8.25),
                "step0076",
                "执行公开工具 MaizeIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 8.25}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0077",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["MaizeSensor"].read_soil_sensors(),
                "step0078",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=315600.0),
                "step0079",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 315600.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0080",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0081",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0082",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0083",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanIrrigation"].irrigate(start=0, end=15, hours=5.0),
                "step0084",
                "执行公开工具 SoybeanIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 5.0}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0085",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0086",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=932100.0),
                "step0087",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 932100.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0088",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0089",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["MaizeSensor"].read_soil_sensors(),
                "step0090",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["MaizeField"].get_ridge_range_state(start=0, end=15),
                "step0091",
                "执行公开工具 MaizeField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["MaizeIrrigation"].irrigate(start=0, end=15, hours=8.25),
                "step0092",
                "执行公开工具 MaizeIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 8.25}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0093",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["MaizeSensor"].read_soil_sensors(),
                "step0094",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=229200.0),
                "step0095",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 229200.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0096",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0097",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0098",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0099",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanIrrigation"].irrigate(start=0, end=15, hours=5.0),
                "step0100",
                "执行公开工具 SoybeanIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 5.0}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0101",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0102",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=759300.0),
                "step0103",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 759300.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0104",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0105",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["MaizeSensor"].read_soil_sensors(),
                "step0106",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["MaizeField"].get_ridge_range_state(start=0, end=15),
                "step0107",
                "执行公开工具 MaizeField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["MaizeIrrigation"].irrigate(start=0, end=15, hours=8.25),
                "step0108",
                "执行公开工具 MaizeIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 8.25}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0109",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["MaizeSensor"].read_soil_sensors(),
                "step0110",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=2043600.0),
                "step0111",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 2043600.0}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_crop_capabilities(),
                "step0112",
                "执行公开工具 SoybeanField__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0113",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0114",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0115",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].refuel(liters=100.0),
                "step0116",
                "执行公开工具 Tractor__refuel；参数 {'liters': 100.0}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].attach_implement(implement="harvester"),
                "step0117",
                "执行公开工具 Tractor__attach_implement；参数 {'implement': 'harvester'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="soybean", start_ridge=0, end_ridge=3),
                "step0118",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'soybean', 'start_ridge': 0, 'end_ridge': 3}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="soybean-2019-00"),
                "step0119",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'soybean-2019-00'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="soybean-2019-00", target_moisture_pct=13.0
                ),
                "step0120",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'soybean-2019-00', 'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="soybean-2019-00"),
                "step0121",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'soybean-2019-00'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="soybean", start_ridge=4, end_ridge=7),
                "step0122",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'soybean', 'start_ridge': 4, 'end_ridge': 7}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="soybean-2019-04"),
                "step0123",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'soybean-2019-04'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="soybean-2019-04", target_moisture_pct=13.0
                ),
                "step0124",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'soybean-2019-04', 'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="soybean-2019-04"),
                "step0125",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'soybean-2019-04'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="soybean", start_ridge=8, end_ridge=11),
                "step0126",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'soybean', 'start_ridge': 8, 'end_ridge': 11}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="soybean-2019-08"),
                "step0127",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'soybean-2019-08'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="soybean-2019-08", target_moisture_pct=13.0
                ),
                "step0128",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'soybean-2019-08', 'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="soybean-2019-08"),
                "step0129",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'soybean-2019-08'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(
                    farm_id="soybean", start_ridge=12, end_ridge=15
                ),
                "step0130",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'soybean', 'start_ridge': 12, 'end_ridge': 15}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="soybean-2019-12"),
                "step0131",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'soybean-2019-12'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="soybean-2019-12", target_moisture_pct=13.0
                ),
                "step0132",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'soybean-2019-12', 'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="soybean-2019-12"),
                "step0133",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'soybean-2019-12'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0134",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=947396.0),
                "step0135",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 947396.0}",
            )
            previous = capture_step(
                previous,
                apps["MaizeField"].get_crop_capabilities(),
                "step0136",
                "执行公开工具 MaizeField__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0137",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["MaizeField"].get_ridge_range_state(start=0, end=15),
                "step0138",
                "执行公开工具 MaizeField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["MaizeSensor"].read_soil_sensors(),
                "step0139",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].refuel(liters=100.0),
                "step0140",
                "执行公开工具 Tractor__refuel；参数 {'liters': 100.0}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].attach_implement(implement="harvester"),
                "step0141",
                "执行公开工具 Tractor__attach_implement；参数 {'implement': 'harvester'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="maize", start_ridge=0, end_ridge=3),
                "step0142",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'maize', 'start_ridge': 0, 'end_ridge': 3}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="maize-2019-00"),
                "step0143",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'maize-2019-00'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="maize-2019-00", target_moisture_pct=14.0
                ),
                "step0144",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'maize-2019-00', 'target_moisture_pct': 14.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="maize-2019-00"),
                "step0145",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'maize-2019-00'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="maize", start_ridge=4, end_ridge=7),
                "step0146",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'maize', 'start_ridge': 4, 'end_ridge': 7}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="maize-2019-04"),
                "step0147",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'maize-2019-04'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="maize-2019-04", target_moisture_pct=14.0
                ),
                "step0148",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'maize-2019-04', 'target_moisture_pct': 14.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="maize-2019-04"),
                "step0149",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'maize-2019-04'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="maize", start_ridge=8, end_ridge=11),
                "step0150",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'maize', 'start_ridge': 8, 'end_ridge': 11}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="maize-2019-08"),
                "step0151",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'maize-2019-08'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="maize-2019-08", target_moisture_pct=14.0
                ),
                "step0152",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'maize-2019-08', 'target_moisture_pct': 14.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="maize-2019-08"),
                "step0153",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'maize-2019-08'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="maize", start_ridge=12, end_ridge=15),
                "step0154",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'maize', 'start_ridge': 12, 'end_ridge': 15}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="maize-2019-12"),
                "step0155",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'maize-2019-12'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="maize-2019-12", target_moisture_pct=14.0
                ),
                "step0156",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'maize-2019-12', 'target_moisture_pct': 14.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="maize-2019-12"),
                "step0157",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'maize-2019-12'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0158",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["OperatingAccounts"].get_accounts(),
                "step0159",
                "执行公开工具 OperatingAccounts__get_accounts；参数 {}",
            )
        return finish_capture(self, events)
