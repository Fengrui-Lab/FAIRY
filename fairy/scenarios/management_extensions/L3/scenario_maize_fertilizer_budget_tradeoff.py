"""L3：单场玉米有限肥料与作业成本权衡。题设、初态和完整Oracle均在本文件。"""

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


class ScenarioMaizeFertilizerBudgetTradeoff(Scenario):
    scenario_id = "scenario_l3_maize_fertilizer_budget_tradeoff"
    level = "L3"
    objective_metric = "net_operating_margin"
    oracle_policy = staticmethod(manage_joint_fields)
    fields: ClassVar = (
        {
            "farm_id": "maize",
            "crop_id": "maize",
            "seed_type": "MAIZE_201",
            "ridge_count": 16,
            "ridge_width_m": 0.75,
            "field_length_m": 268.0,
            "app_name": "MaizeField",
        },
    )
    prices: ClassVar = OperatingPrices(**operating_prices(high_water=False))
    start: ClassVar = datetime(2019, 5, 1, 7)  # noqa: DTZ001
    timezone: ClassVar = "Europe/Paris"
    duration_days: ClassVar = 213
    shared_water_m3: ClassVar = 900.0
    field_water_limit_mm: ClassVar = 180.0
    field_fertilizer_limit_kg_ha: ClassVar = 150.0
    initial_fertilizer_kg: ClassVar = 48.24
    initial_fuel_liters: ClassVar = 300.0
    storage_capacity_kg: ClassVar = 15000.0
    drying_capacity_kg_per_day: ClassVar = 10000.0
    safe_moisture_pct: ClassVar = 14.0
    ORACLE_REFERENCE: ClassVar[dict] = {
        "scenario_id": "scenario_l3_maize_fertilizer_budget_tradeoff",
        "input_fingerprint": "ef49b03fc45b21fe8f119e26b829f6be770a2221cff6505b684ec9c1ea5ac9f5",
        "selected": {
            "currency": "USD",
            "price_book_id": "china_northeast_2025_usd_v1",
            "cny_per_usd": 7.1757,
            "biological_kg_by_crop": {"maize": 3313.8653956166436},
            "recovered_kg_by_crop": {"maize": 3737.7318997071434},
            "stored_kg_by_crop": {"maize": 3737.72},
            "production_cost": 123.53700400709053,
            "stored_grain_value": 1125.1132572431957,
            "net_operating_margin": 1001.5762532361051,
        },
        "workflow_steps": 84,
        "candidate_count": 5,
        "feasible_count": 5,
        "scope": "Best feasible candidate among 5 freshly executed USD management candidates, including "
        "the prior literal workflow, a short-list ranked from archived physical receipts, and "
        "explicit crop/water/fertilizer/protection controls. Crop biology, weather and physical "
        "caps unchanged. No claim of global optimum; archived revaluations are rankings, not "
        "fresh execution.",
        "calibration_artifact": "validation_runs/management_usd_china_2025_20261103_220138/newer/scenario_l3_maize_fertilizer_budget_tradeoff/calibration_reference.json",
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

    def task_description(self, detailed):
        task = "经营面积3216m²、垄距0.75m的玉米田，在有限肥料库存下完成全季种植、成熟收获及安全入库，尽量提高净经营收益。价格、余额和任务截止时间通过 OperatingAccounts.get_accounts 查询；播种要求、实际库存、设备和资源限制通过对应工具查询。"
        if not detailed:
            return task
        guidance = textwrap.dedent(
            """\
            管理指导：

            播前规划：查 MaizeField.get_crop_capabilities、Warehouse.get_inventory、Tractor.get_status 和各场管理额度。比较基施与分次追施对当前作物需求、后续库存、额外作业及成本的影响，决定是否及如何施基肥，再完成整地和全田建植；不预设必须把肥料一次用尽。

            营养依据：用 MaizeSensor.read_canopy_sensors 观察覆盖区长势，结合 get_ridge_range_state 的生育阶段、可见营养指标和投入记录。低冠层读数先排查出苗、水分和自然衰老；持续异常且仍处有效吸收阶段时才进一步比较追肥。没有独立土壤养分化验，不能把代理指标当成确诊缺氮或精确剂量。

            施肥与复查：按产品单位、面积、已施用量和剩余库存计算拟施用量，兼顾后续需求及作业成本；装料前核对机上余肥。施后核对实际扣量和田间覆盖，待响应生效后复查同一区域的冠层、作物及水分，再决定后续投入。没有库存时不执行假装肥或假施肥。

            水分依据与处理：用 read_soil_sensors 对照前次含水量、生育阶段和 WeatherApp.get_forecast。持续偏干且近期降水不足时，结合范围、面积、设施能力和水量余额分次灌溉；偏湿或有可利用降雨则暂缓。待实际供水生效后复测，避免在读数尚未更新时重复补灌。

            收储核算：根据真实成熟、籽粒水分和天气窗口收割，随批卸粮，必要时干燥后安全入库。核对全田完成、粮批、种肥水油和干燥费用，以实际净收益评价方案。

            """
        ).strip()
        return task + "\n\n" + guidance

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
                apps["Tractor"].load_fertilizer(kg=48.24),
                "step0011",
                "执行公开工具 Tractor__load_fertilizer；参数 {'kg': 48.24}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].base_fertilize(farm_id="maize", total_kg=48.24),
                "step0012",
                "执行公开工具 Tractor__base_fertilize；参数 {'farm_id': 'maize', 'total_kg': 48.24}",
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
                apps["SystemApp"].advance_time(seconds=1637841.0),
                "step0023",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1637841.0}",
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
                apps["MaizeSensor"].read_soil_sensors(),
                "step0026",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["MaizeField"].get_ridge_range_state(start=0, end=15),
                "step0027",
                "执行公开工具 MaizeField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=3628800.0),
                "step0028",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 3628800.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0029",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0030",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["MaizeSensor"].read_soil_sensors(),
                "step0031",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["MaizeField"].get_ridge_range_state(start=0, end=15),
                "step0032",
                "执行公开工具 MaizeField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["MaizeIrrigation"].irrigate(start=0, end=15, hours=7.5),
                "step0033",
                "执行公开工具 MaizeIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 7.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0034",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["MaizeSensor"].read_soil_sensors(),
                "step0035",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1095900.0),
                "step0036",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1095900.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0037",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0038",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["MaizeSensor"].read_soil_sensors(),
                "step0039",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["MaizeField"].get_ridge_range_state(start=0, end=15),
                "step0040",
                "执行公开工具 MaizeField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["MaizeIrrigation"].irrigate(start=0, end=15, hours=7.5),
                "step0041",
                "执行公开工具 MaizeIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 7.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0042",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["MaizeSensor"].read_soil_sensors(),
                "step0043",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1355100.0),
                "step0044",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1355100.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0045",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0046",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["MaizeSensor"].read_soil_sensors(),
                "step0047",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["MaizeField"].get_ridge_range_state(start=0, end=15),
                "step0048",
                "执行公开工具 MaizeField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["MaizeIrrigation"].irrigate(start=0, end=15, hours=7.5),
                "step0049",
                "执行公开工具 MaizeIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 7.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0050",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["MaizeSensor"].read_soil_sensors(),
                "step0051",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1095900.0),
                "step0052",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1095900.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0053",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0054",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["MaizeSensor"].read_soil_sensors(),
                "step0055",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["MaizeField"].get_ridge_range_state(start=0, end=15),
                "step0056",
                "执行公开工具 MaizeField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["MaizeIrrigation"].irrigate(start=0, end=15, hours=7.5),
                "step0057",
                "执行公开工具 MaizeIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 7.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0058",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["MaizeSensor"].read_soil_sensors(),
                "step0059",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=2996700.0),
                "step0060",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 2996700.0}",
            )
            previous = capture_step(
                previous,
                apps["MaizeField"].get_crop_capabilities(),
                "step0061",
                "执行公开工具 MaizeField__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0062",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["MaizeField"].get_ridge_range_state(start=0, end=15),
                "step0063",
                "执行公开工具 MaizeField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["MaizeSensor"].read_soil_sensors(),
                "step0064",
                "执行公开工具 MaizeSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].refuel(liters=100.0),
                "step0065",
                "执行公开工具 Tractor__refuel；参数 {'liters': 100.0}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].attach_implement(implement="harvester"),
                "step0066",
                "执行公开工具 Tractor__attach_implement；参数 {'implement': 'harvester'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="maize", start_ridge=0, end_ridge=3),
                "step0067",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'maize', 'start_ridge': 0, 'end_ridge': 3}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="maize-2019-00"),
                "step0068",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'maize-2019-00'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="maize-2019-00", target_moisture_pct=14.0
                ),
                "step0069",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'maize-2019-00', 'target_moisture_pct': 14.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="maize-2019-00"),
                "step0070",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'maize-2019-00'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="maize", start_ridge=4, end_ridge=7),
                "step0071",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'maize', 'start_ridge': 4, 'end_ridge': 7}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="maize-2019-04"),
                "step0072",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'maize-2019-04'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="maize-2019-04", target_moisture_pct=14.0
                ),
                "step0073",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'maize-2019-04', 'target_moisture_pct': 14.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="maize-2019-04"),
                "step0074",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'maize-2019-04'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="maize", start_ridge=8, end_ridge=11),
                "step0075",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'maize', 'start_ridge': 8, 'end_ridge': 11}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="maize-2019-08"),
                "step0076",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'maize-2019-08'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="maize-2019-08", target_moisture_pct=14.0
                ),
                "step0077",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'maize-2019-08', 'target_moisture_pct': 14.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="maize-2019-08"),
                "step0078",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'maize-2019-08'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="maize", start_ridge=12, end_ridge=15),
                "step0079",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'maize', 'start_ridge': 12, 'end_ridge': 15}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="maize-2019-12"),
                "step0080",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'maize-2019-12'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="maize-2019-12", target_moisture_pct=14.0
                ),
                "step0081",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'maize-2019-12', 'target_moisture_pct': 14.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="maize-2019-12"),
                "step0082",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'maize-2019-12'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0083",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
        return finish_capture(self, events)
