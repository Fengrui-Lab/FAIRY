"""L3：单场大豆官方品种选择与高水价经营。题设、初始化、评估入口及完整 Oracle 均在本文件。"""

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
    PlanningTractor,
    crop_options,
)
from fairy.scenarios.scenario import Scenario
from fairy.types import EventRegisterer

from ..apps.operating_accounts_app import OperatingAccounts, OperatingPrices
from ..apps.shared_irrigation_app import PooledIrrigation
from ..apps.variety_selection_app import VarietySelection, VarietySelectionFarm
from ..china_market_prices import operating_prices
from ..common import capture_step, finish_capture
from ..evaluation.operating_profit import evaluate
from ..oracle_management_plans import manage_soybean_variety_choice


class ScenarioSoybeanVarietyHighWaterPrice(Scenario):
    scenario_id = "scenario_l3_soybean_variety_high_water_price"
    level = "L3"
    objective_metric = "net_operating_margin"
    oracle_policy = staticmethod(manage_soybean_variety_choice)
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
    varieties: ClassVar = {
        "SOYBEAN_901": "Soybean_901",
        "SOYBEAN_902": "Soybean_902",
        "SOYBEAN_903": "Soybean_903",
    }
    initial_fertilizer_kg: ClassVar = 0.0
    initial_fuel_liters: ClassVar = 300.0
    storage_capacity_kg: ClassVar = 15000.0
    drying_capacity_kg_per_day: ClassVar = 10000.0
    safe_moisture_pct: ClassVar = 13.0
    ORACLE_REFERENCE: ClassVar[dict] = {
        "scenario_id": "scenario_l3_soybean_variety_high_water_price",
        "input_fingerprint": "2b774f8450793b525ff51409514d9c4a0614e58dda23ba6e459fe89c6e258cfc",
        "selected": {
            "currency": "USD",
            "price_book_id": "china_northeast_2025_usd_v1",
            "cny_per_usd": 7.1757,
            "stored_kg_by_crop": {"soybean": 2146.92},
            "production_cost": 133.51603885335228,
            "stored_grain_value": 1292.5142355449643,
            "net_operating_margin": 1158.998196691612,
        },
        "workflow_steps": 115,
        "candidate_count": 10,
        "feasible_count": 10,
        "scope": "Best feasible candidate among 10 freshly executed USD management candidates, including "
        "the prior literal workflow, a short-list ranked from archived physical receipts, and "
        "explicit crop/water/fertilizer/protection controls. Crop biology, weather and physical "
        "caps unchanged. No claim of global optimum; archived revaluations are rankings, not "
        "fresh execution.",
        "calibration_artifact": "validation_runs/management_usd_china_2025_20261103_220138/newer/scenario_l3_soybean_variety_high_water_price/calibration_reference.json",
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
            farm = VarietySelectionFarm(
                selected_crop=field["crop_id"],
                num_ridges=field["ridge_count"],
                field_length_m=field["field_length_m"],
                ridge_width_m=field["ridge_width_m"],
            )
            farm.farm_id = field["farm_id"]
            farm.name = field["app_name"] or f"Field_{field['farm_id']}"
            farm.configure_crop_backend(
                "wofost",
                **{
                    **asdict(farm.physics.crop_backend.config),
                    "cultivar_map": self.varieties,
                },
            )
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
        quantity = seeds["SOYBEAN_901"]
        seeds = {seed: quantity for seed in self.varieties}
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
        self.selection = VarietySelection(
            self.farms[0], self.tractor, self.fields[0], self.varieties
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
            self.selection,
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

        self._initial_signature = deepcopy(self._make_input_signature())

    def validate(self, env=None):
        """按本场景目标读取真实执行结果评分。"""
        result = evaluate(self)
        result.metadata["selected_official_variety"] = self.selection.selected_seed
        result.metadata["native_crop_water_units"] = {
            "WTRAT": "cm, native cumulative crop transpiration",
            "EVST": "cm, native cumulative soil evaporation",
            "TOTIRR": "cm, native effective irrigation after efficiency",
            "DOE_DOA_DOM": "ISO calendar dates",
        }
        result.metadata["native_crop_water"] = [
            {
                "ridge_id": rid,
                **{k: run.pcse.get(k) for k in ("WTRAT", "EVST", "TOTIRR")},
                **{
                    k: run.pcse[k].isoformat() if run.pcse.get(k) is not None else None
                    for k in ("DOE", "DOA", "DOM")
                },
            }
            for rid, run in self.farms[0].physics.crop_backend._runs.items()
        ]
        return result

    def _make_input_signature(self) -> dict:
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
            "schema": 3,
            "official_variety_choices": self.varieties,
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

    def input_signature(self):
        return deepcopy(self._initial_signature)

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
            "app_states": {a.name: a.get_state() for a in self.apps},
            "rng_states": {a.name: a.rng.getstate() for a in self.apps},
        }

    def task_description(self, detailed):
        task = "经营面积4716.8m²、垄距1.1m的大豆田，在播前可选的官方参考品种中自主选择，完成全季成熟收储，在高水价条件下尽量提高净经营收益。品种通过 VarietySelection.get_options 查询；价格、余额和截止时间通过 OperatingAccounts.get_accounts 查询，其他作业参数通过对应工具查询。"
        if not detailed:
            return task
        guidance = textwrap.dedent(
            """\
            管理指导：

            选种依据：比较 get_options 返回的品种参数与来源，结合本季环境、可用资源及成熟风险作选择；官方生育参数差异不等于已标定的抗旱排名。按 select_variety 的前提在田间准备和装种前完成选择，再查询当前作物能力，核对与之匹配的种子和播种要求。

            建植与观察：检查土壤、天气、库存和机具后完成全田整地播种。播后用 SoybeanSensor.read_canopy_sensors 配合地块状态观察建植及长势，区分尚未出苗、缺水和后期衰老；异常时复查覆盖区，不能把局部读数当成全田结论。

            高水价下灌溉：用 read_soil_sensors 对照前次读数、作物阶段和近期降雨。土壤持续偏干且作物仍需水时，结合受影响范围、面积、设施能力和费用选择分次供水；土壤湿润或有可利用降雨则暂缓。考虑后续用水与预期增益，不能因某品种名称就假定它更省水。

            复查与营养：灌后核对实际水量与费用，待供水响应生效后复读相同探头和冠层。营养判断结合生育阶段、可见代理指标和投入记录；没有独立养分化验，低 NDVI 不能直接确诊缺肥，也不能凭空添加库存。

            收储与经营复核：根据实际成熟、水分、天气和工具限制完成收获、卸粮、必要干燥及安全入库。报告实际品种、入库粮、用水、成本和净收益，不预告未来产量，也不把更高单产直接等同于更高利润。

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
                apps["VarietySelection"].get_options(),
                "step0000",
                "执行公开工具 VarietySelection__get_options；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["VarietySelection"].select_variety(seed_type="SOYBEAN_902"),
                "step0001",
                "执行公开工具 VarietySelection__select_variety；参数 {'seed_type': 'SOYBEAN_902'}",
            )
            previous = capture_step(
                previous,
                apps["OperatingAccounts"].get_accounts(),
                "step0002",
                "执行公开工具 OperatingAccounts__get_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].get_inventory(),
                "step0003",
                "执行公开工具 Warehouse__get_inventory；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_crop_capabilities(),
                "step0004",
                "执行公开工具 SoybeanField__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0005",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0006",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0007",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0008",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].get_status(),
                "step0009",
                "执行公开工具 Tractor__get_status；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].attach_implement(implement="grader"),
                "step0010",
                "执行公开工具 Tractor__attach_implement；参数 {'implement': 'grader'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].level(farm_id="soybean"),
                "step0011",
                "执行公开工具 Tractor__level；参数 {'farm_id': 'soybean'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0012",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].attach_implement(implement="furrower"),
                "step0013",
                "执行公开工具 Tractor__attach_implement；参数 {'implement': 'furrower'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].form_ridges(farm_id="soybean", ridge_width_m=1.1),
                "step0014",
                "执行公开工具 Tractor__form_ridges；参数 {'farm_id': 'soybean', 'ridge_width_m': 1.1}",
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
                apps["Tractor"].load_seeds(seed_type="SOYBEAN_902", count=188672),
                "step0017",
                "执行公开工具 Tractor__load_seeds；参数 {'seed_type': 'SOYBEAN_902', 'count': 188672}",
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
                "step0018",
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
                "step0019",
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
                "step0020",
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
                "step0021",
                "执行公开工具 Tractor__plant_seeds；参数 {'farm_id': 'soybean', 'start_ridge': 12, 'end_ridge': 15, 'depth_cm': 4.0, 'seed_spacing_cm': 4.545454545454546}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0022",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=3451966.0),
                "step0023",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 3451966.0}",
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
                apps["SystemApp"].advance_time(seconds=2160000.0),
                "step0028",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 2160000.0}",
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
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0031",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0032",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanIrrigation"].irrigate(start=0, end=15, hours=8.0),
                "step0033",
                "执行公开工具 SoybeanIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 8.0}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0034",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0035",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1180500.0),
                "step0036",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1180500.0}",
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
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0039",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0040",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanIrrigation"].irrigate(start=0, end=15, hours=8.0),
                "step0041",
                "执行公开工具 SoybeanIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 8.0}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0042",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0043",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1266900.0),
                "step0044",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1266900.0}",
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
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0047",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0048",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanIrrigation"].irrigate(start=0, end=15, hours=8.0),
                "step0049",
                "执行公开工具 SoybeanIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 8.0}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0050",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0051",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=2217300.0),
                "step0052",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 2217300.0}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_crop_capabilities(),
                "step0053",
                "执行公开工具 SoybeanField__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0054",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0055",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0056",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0057",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0058",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0059",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0060",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0061",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0062",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0063",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0064",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0065",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0066",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0067",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0068",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0069",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0070",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0071",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0072",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0073",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0074",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0075",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0076",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0077",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0078",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0079",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0080",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0081",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0082",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0083",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0084",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0085",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0086",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0087",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0088",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0089",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0090",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0091",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0092",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0093",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0094",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0095",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].refuel(liters=100.0),
                "step0096",
                "执行公开工具 Tractor__refuel；参数 {'liters': 100.0}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].attach_implement(implement="harvester"),
                "step0097",
                "执行公开工具 Tractor__attach_implement；参数 {'implement': 'harvester'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="soybean", start_ridge=0, end_ridge=3),
                "step0098",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'soybean', 'start_ridge': 0, 'end_ridge': 3}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="soybean-2019-00"),
                "step0099",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'soybean-2019-00'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="soybean-2019-00", target_moisture_pct=13.0
                ),
                "step0100",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'soybean-2019-00', 'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="soybean-2019-00"),
                "step0101",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'soybean-2019-00'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="soybean", start_ridge=4, end_ridge=7),
                "step0102",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'soybean', 'start_ridge': 4, 'end_ridge': 7}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="soybean-2019-04"),
                "step0103",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'soybean-2019-04'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="soybean-2019-04", target_moisture_pct=13.0
                ),
                "step0104",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'soybean-2019-04', 'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="soybean-2019-04"),
                "step0105",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'soybean-2019-04'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="soybean", start_ridge=8, end_ridge=11),
                "step0106",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'soybean', 'start_ridge': 8, 'end_ridge': 11}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="soybean-2019-08"),
                "step0107",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'soybean-2019-08'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="soybean-2019-08", target_moisture_pct=13.0
                ),
                "step0108",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'soybean-2019-08', 'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="soybean-2019-08"),
                "step0109",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'soybean-2019-08'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(
                    farm_id="soybean", start_ridge=12, end_ridge=15
                ),
                "step0110",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'soybean', 'start_ridge': 12, 'end_ridge': 15}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="soybean-2019-12"),
                "step0111",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'soybean-2019-12'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="soybean-2019-12", target_moisture_pct=13.0
                ),
                "step0112",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'soybean-2019-12', 'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="soybean-2019-12"),
                "step0113",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'soybean-2019-12'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0114",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
        return finish_capture(self, events)
