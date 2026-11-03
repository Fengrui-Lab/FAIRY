"""L3：单场大豆高水价经营。题设、初始化、评估入口及完整 Oracle 均在本文件。"""

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


class ScenarioSoybeanHighWaterPrice(Scenario):
    scenario_id = "scenario_l3_soybean_high_water_price"
    level = "L3"
    objective_metric = "net_operating_margin"
    oracle_policy = staticmethod(manage_joint_fields)
    fields: ClassVar = (
        {
            "farm_id": "soybean",
            "crop_id": "soybean",
            "seed_type": "SOYBEAN_901",
            "ridge_count": 16,
            "ridge_width_m": 1.1,
            "field_length_m": 268.0,
            "app_name": "SoybeanField",
        },
    )
    prices: ClassVar = OperatingPrices(**operating_prices(high_water=True))
    start: ClassVar = datetime(2019, 5, 1, 7)  # noqa: DTZ001
    timezone: ClassVar = "Europe/Paris"
    duration_days: ClassVar = 213
    shared_water_m3: ClassVar = 900.0
    field_water_limit_mm: ClassVar = 180.0
    field_fertilizer_limit_kg_ha: ClassVar = 600.0
    initial_fertilizer_kg: ClassVar = 0.0
    initial_fuel_liters: ClassVar = 300.0
    storage_capacity_kg: ClassVar = 15000.0
    drying_capacity_kg_per_day: ClassVar = 10000.0
    safe_moisture_pct: ClassVar = 13.0
    ORACLE_REFERENCE: ClassVar[dict] = {
        "scenario_id": "scenario_l3_soybean_high_water_price",
        "input_fingerprint": "5cd19c2e69faf2c771193c974b4b6e978934ebb062f3ab07453eaedae908df53",
        "selected": {
            "currency": "USD",
            "price_book_id": "china_northeast_2025_usd_v1",
            "cny_per_usd": 7.1757,
            "stored_kg_by_crop": {"soybean": 2021.96},
            "production_cost": 117.0435553325808,
            "stored_grain_value": 1217.2843346293741,
            "net_operating_margin": 1100.2407792967933,
        },
        "workflow_steps": 74,
        "candidate_count": 6,
        "feasible_count": 6,
        "scope": "Best feasible candidate among 6 freshly executed USD management candidates, including "
        "the prior literal workflow, a short-list ranked from archived physical receipts, and "
        "explicit crop/water/fertilizer/protection controls. Crop biology, weather and physical "
        "caps unchanged. No claim of global optimum; archived revaluations are rankings, not "
        "fresh execution.",
        "calibration_artifact": "validation_runs/management_usd_china_2025_20261103_220138/newer/scenario_l3_soybean_high_water_price/calibration_reference.json",
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
        task = "经营面积4716.8m²、垄距1.1m的大豆田，完成本季全田种植、成熟收获及安全入库，在高水价条件下尽量提高净经营收益。价格、余额和任务截止时间通过 OperatingAccounts.get_accounts 查询，作物、设备和资源限制通过对应工具查询。"
        if not detailed:
            return task
        guidance = textwrap.dedent(
            """\
            管理指导：

            播前核对：读 SoybeanField.get_crop_capabilities、地块概况、公共库存和设备状态，按工具返回的品种、播种要求及整地顺序完成建植，再核对全田覆盖。

            水分依据：用 SoybeanSensor.read_soil_sensors 查看各覆盖区含水量，结合 WeatherApp.get_forecast、生育阶段及前次读数辨别持续干燥。作物仍需水、土壤持续偏干且近期降雨不足时考虑灌溉；土壤湿润或近期有可利用降雨时暂缓。单个探头的噪声不代表整场缺水。

            高水价下处理：根据实际缺水范围、地块面积、设施能力、剩余额度和水价选择分次灌水量，为后续生长保留水源。灌溉停止阈值属于操作限制，不能当成最优目标；用水上限也不是必须完成的用量。待供水和土壤响应生效后复读同一区域探头，核对水费与作物响应，再决定后续投入。

            营养与异常：结合 read_canopy_sensors、get_ridge_range_state、生育阶段和已施肥记录检查长势；先排查缺水、未出苗或衰老，不能仅凭低 NDVI 判断缺肥。本场没有独立土壤养分化验入口，营养指标只是模拟线索；库存或证据不足时不凭空追加肥料。

            收储与复核：按实际成熟、粮食水分、天气和设备限制安排分批收获、卸粮及必要干燥，安全入库后核对全田和粮批。最后查经营账，分别报告入库粮、真实耗水、投入成本和净收益；未用库存不按消耗重复收费。

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
                apps["SoybeanField"].get_crop_capabilities(),
                "step0002",
                "执行公开工具 SoybeanField__get_crop_capabilities；参数 {}",
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
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0005",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0006",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
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
                apps["Tractor"].level(farm_id="soybean"),
                "step0009",
                "执行公开工具 Tractor__level；参数 {'farm_id': 'soybean'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0010",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].attach_implement(implement="furrower"),
                "step0011",
                "执行公开工具 Tractor__attach_implement；参数 {'implement': 'furrower'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].form_ridges(farm_id="soybean", ridge_width_m=1.1),
                "step0012",
                "执行公开工具 Tractor__form_ridges；参数 {'farm_id': 'soybean', 'ridge_width_m': 1.1}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0013",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].attach_implement(implement="seeder"),
                "step0014",
                "执行公开工具 Tractor__attach_implement；参数 {'implement': 'seeder'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].load_seeds(seed_type="SOYBEAN_901", count=188672),
                "step0015",
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
                "step0016",
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
                "step0017",
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
                "step0018",
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
                "step0019",
                "执行公开工具 Tractor__plant_seeds；参数 {'farm_id': 'soybean', 'start_ridge': 12, 'end_ridge': 15, 'depth_cm': 4.0, 'seed_spacing_cm': 4.545454545454546}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0020",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=3451966.0),
                "step0021",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 3451966.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0022",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0023",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0024",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0025",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=2160000.0),
                "step0026",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 2160000.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0027",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0028",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0029",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0030",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanIrrigation"].irrigate(start=0, end=15, hours=6.0),
                "step0031",
                "执行公开工具 SoybeanIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 6.0}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0032",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0033",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1187700.0),
                "step0034",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1187700.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0035",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0036",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0037",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0038",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanIrrigation"].irrigate(start=0, end=15, hours=6.0),
                "step0039",
                "执行公开工具 SoybeanIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 6.0}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0040",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0041",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1274100.0),
                "step0042",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1274100.0}",
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
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0045",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0046",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanIrrigation"].irrigate(start=0, end=15, hours=6.0),
                "step0047",
                "执行公开工具 SoybeanIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 6.0}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0048",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0049",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=2915700.0),
                "step0050",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 2915700.0}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_crop_capabilities(),
                "step0051",
                "执行公开工具 SoybeanField__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0052",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0053",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0054",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].refuel(liters=100.0),
                "step0055",
                "执行公开工具 Tractor__refuel；参数 {'liters': 100.0}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].attach_implement(implement="harvester"),
                "step0056",
                "执行公开工具 Tractor__attach_implement；参数 {'implement': 'harvester'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="soybean", start_ridge=0, end_ridge=3),
                "step0057",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'soybean', 'start_ridge': 0, 'end_ridge': 3}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="soybean-2019-00"),
                "step0058",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'soybean-2019-00'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="soybean-2019-00", target_moisture_pct=13.0
                ),
                "step0059",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'soybean-2019-00', 'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="soybean-2019-00"),
                "step0060",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'soybean-2019-00'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="soybean", start_ridge=4, end_ridge=7),
                "step0061",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'soybean', 'start_ridge': 4, 'end_ridge': 7}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="soybean-2019-04"),
                "step0062",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'soybean-2019-04'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="soybean-2019-04", target_moisture_pct=13.0
                ),
                "step0063",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'soybean-2019-04', 'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="soybean-2019-04"),
                "step0064",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'soybean-2019-04'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="soybean", start_ridge=8, end_ridge=11),
                "step0065",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'soybean', 'start_ridge': 8, 'end_ridge': 11}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="soybean-2019-08"),
                "step0066",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'soybean-2019-08'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="soybean-2019-08", target_moisture_pct=13.0
                ),
                "step0067",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'soybean-2019-08', 'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="soybean-2019-08"),
                "step0068",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'soybean-2019-08'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(
                    farm_id="soybean", start_ridge=12, end_ridge=15
                ),
                "step0069",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'soybean', 'start_ridge': 12, 'end_ridge': 15}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="soybean-2019-12"),
                "step0070",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'soybean-2019-12'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="soybean-2019-12", target_moisture_pct=13.0
                ),
                "step0071",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'soybean-2019-12', 'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="soybean-2019-12"),
                "step0072",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'soybean-2019-12'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0073",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
        return finish_capture(self, events)
