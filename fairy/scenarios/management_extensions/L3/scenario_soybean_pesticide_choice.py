"""L3：单场大豆生长期虫害与真实产品选药经营。题设、初始化、评估入口及完整 Oracle 均在本文件。"""

import hashlib
import json
import textwrap
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
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
    crop_options,
)
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.wofost_events import PressureEvent, install_scenario_events
from fairy.types import EventRegisterer

from ..apps.crop_protection_app import (
    CropProtection,
    CropProtectionAccounts,
    CropProtectionTractor,
)
from ..apps.operating_accounts_app import OperatingPrices
from ..apps.shared_irrigation_app import PooledIrrigation
from ..china_market_prices import CONTRACTS, operating_prices, usd
from ..common import capture_step, finish_capture
from ..evaluation.operating_profit import evaluate
from ..oracle_management_plans import manage_soybean_pest_choice


class ScenarioSoybeanPesticideChoice(Scenario):
    scenario_id = "scenario_l3_soybean_pesticide_choice"
    level = "L3"
    objective_metric = "net_operating_margin"
    oracle_policy = staticmethod(manage_soybean_pest_choice)
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
    prices: ClassVar = OperatingPrices(**operating_prices(high_water=False))
    start: ClassVar = datetime(2019, 5, 1, 7)  # noqa: DTZ001
    timezone: ClassVar = "Europe/Paris"
    duration_days: ClassVar = 213
    shared_water_m3: ClassVar = 900.0
    field_water_limit_mm: ClassVar = 180.0
    field_fertilizer_limit_kg_ha: ClassVar = 600.0
    protection_cash: ClassVar = usd(CONTRACTS["protection_cash_cny"])
    outbreak_day: ClassVar = date(2019, 7, 1)
    outbreak_pressure: ClassVar = 0.62
    initial_fertilizer_kg: ClassVar = 0.0
    initial_fuel_liters: ClassVar = 300.0
    storage_capacity_kg: ClassVar = 15000.0
    drying_capacity_kg_per_day: ClassVar = 10000.0
    safe_moisture_pct: ClassVar = 13.0
    ORACLE_REFERENCE: ClassVar[dict] = {
        "scenario_id": "scenario_l3_soybean_pesticide_choice",
        "input_fingerprint": "ea0acc729de9202feb3196b579c37cc8289329b8100a48f5eb4e4c8e17097daa",
        "selected": {
            "currency": "USD",
            "price_book_id": "china_northeast_2025_usd_v1",
            "cny_per_usd": 7.1757,
            "stored_kg_by_crop": {"soybean": 1988.64},
            "production_cost": 112.2365582706181,
            "stored_grain_value": 1197.224633136837,
            "net_operating_margin": 1084.988074866219,
        },
        "workflow_steps": 186,
        "candidate_count": 5,
        "feasible_count": 5,
        "scope": "Best feasible candidate among 5 freshly executed USD management candidates, including "
        "the prior literal workflow, a short-list ranked from archived physical receipts, and "
        "explicit crop/water/fertilizer/protection controls. Crop biology, weather and physical "
        "caps unchanged. No claim of global optimum; archived revaluations are rankings, not "
        "fresh execution.",
        "calibration_artifact": "validation_runs/management_usd_china_2025_20261103_220138/newer/scenario_l3_soybean_pesticide_choice/calibration_reference.json",
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
            farm.configure_crop_backend(
                "wofost",
                **{
                    **asdict(farm.physics.crop_backend.config),
                    "external_biotic_coupling": True,
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
        self.tractor = CropProtectionTractor(
            self.farm_environment,
            equipment=TractorEquipment(
                implements=(*DEFAULT_TRACTOR_IMPLEMENTS, "seeder"),
                ridging_implement="furrower",
            ),
        )
        self.initial_machine_fuel = self.tractor._fuel_tank_l
        path = Path(__file__).parents[1] / "data/soybean_aphid_products/catalog.json"
        self.product_catalog = json.loads(path.read_text())
        for name, expected_sha in self.product_catalog["source_files"].items():
            if (
                hashlib.sha256(path.with_name(name).read_bytes()).hexdigest()
                != expected_sha
            ):
                raise ValueError("Pinned crop-protection source checksum mismatch")
        self.protection = CropProtection(
            self.farms[0],
            self.weather,
            self.product_catalog,
            purchase_cash=self.protection_cash,
        )
        self.tractor.protection = self.protection
        self.accounts = CropProtectionAccounts(
            protection=self.protection,
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
            self.protection,
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

        install_scenario_events(
            self,
            [
                PressureEvent(
                    event_id="soybean_aphid_colonization",
                    farm_id="soybean",
                    ridge_start=0,
                    ridge_end=15,
                    start=self.outbreak_day,
                    end=date(2019, 7, 2),
                    kind="insect",
                    value=self.outbreak_pressure,
                    mode="add",
                    repeat="once",
                )
            ],
        )
        self._initial_signature = deepcopy(self._make_input_signature())

    def validate(self, env=None):
        """按本场景目标读取真实执行结果评分。"""
        result = evaluate(self)
        backend = self.farms[0].physics.crop_backend
        result.metadata["crop_backend_configuration"] = asdict(backend.config)
        result.metadata["biotic_effect_scope"] = self.product_catalog[
            "simulation_assumptions"
        ]["effect_source"]
        result.metadata["outbreak_events"] = deepcopy(
            self.farms[0].physics.scenario_metadata["wofost_scenario_events"]
        )
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
            "crop_protection_catalog": deepcopy(self.product_catalog),
            "crop_protection_initial_cash": self.protection_cash,
            "biotic_parameters": asdict(self.farms[0].physics.biotic.params),
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
            json.dumps(
                json.loads(json.dumps(self.input_signature(), default=str)),
                sort_keys=True,
            ).encode()
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
            "protection": self.protection.get_state(),
            "app_states": {app.name: app.get_state() for app in self.apps},
            "rng_states": {app.name: app.rng.getstate() for app in self.apps},
        }

    def task_description(self, detailed):
        task = "经营面积4716.8m²、垄距1.1m的大豆田，完成正常种植与水肥管理，并处理生长期出现的模拟虫害压力，成熟收获后安全入库，尽量提高净经营收益。基础价格、余额及截止时间查 OperatingAccounts.get_accounts；具名药品、用量限制与服务报价查 CropProtection.get_products。其他参数通过作物和设备工具查询。"
        if not detailed:
            return task
        guidance = textwrap.dedent(
            """\
            管理指导：

            建植与常规管理：核对作物能力、土壤、天气、库存和机具，按工具要求完成整地和全田播种。通过 SoybeanSensor.read_soil_sensors、天气预报及生育阶段判断需水，持续偏干且降水不足时在额度内分次灌水；待响应生效后复读同一区域探头。

            虫害依据：生长期调用 CropProtection.scout 查看实际作物阶段、虫压诊断和残效，结合前次结果及 read_canopy_sensors 排查长势异常。持续虫压和可防护的作物阶段支持比较防治方案；仅有低冠层读数时先排查水分、出苗和衰老，不直接施药。虫压和蚜虫等效值属于模拟诊断。

            选药与执行：用 get_products 比较目标作物、商品单位、允许剂量、使用间隔、季节限制、采收间隔及含服务的成本，结合实际面积、库存和现金确定方案。按工具限制分区施用，保留采购与施药编号；商品制剂量和配药水分别计算，不能把较高报价当成更强的模拟药效。

            处理后复查：天气不允许时调整作业窗口；处理后等待响应，再用 scout 和同一区域冠层记录检查虫压、残效和长势。只有仍有防治依据且目录允许时再考虑处理，换商品也须核对作用机制和累计限制。既往损失不会因施药自动恢复。

            营养与收储：营养指标仅作辅助，低 NDVI 不等于确诊缺肥；无可靠证据或库存时不追加投入。收获同时满足实际成熟、水分、天气和施药回执允许日期，分批卸粮并安全入库。最后核对产品库存、服务费用和经营账，报告真实净收益。

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
                apps["CropProtection"].get_products(),
                "step0002",
                "执行公开工具 CropProtection__get_products；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_crop_capabilities(),
                "step0003",
                "执行公开工具 SoybeanField__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0004",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0005",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0006",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0007",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].get_status(),
                "step0008",
                "执行公开工具 Tractor__get_status；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].attach_implement(implement="grader"),
                "step0009",
                "执行公开工具 Tractor__attach_implement；参数 {'implement': 'grader'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].level(farm_id="soybean"),
                "step0010",
                "执行公开工具 Tractor__level；参数 {'farm_id': 'soybean'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0011",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].attach_implement(implement="furrower"),
                "step0012",
                "执行公开工具 Tractor__attach_implement；参数 {'implement': 'furrower'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].form_ridges(farm_id="soybean", ridge_width_m=1.1),
                "step0013",
                "执行公开工具 Tractor__form_ridges；参数 {'farm_id': 'soybean', 'ridge_width_m': 1.1}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0014",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].attach_implement(implement="seeder"),
                "step0015",
                "执行公开工具 Tractor__attach_implement；参数 {'implement': 'seeder'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].load_seeds(seed_type="SOYBEAN_901", count=188672),
                "step0016",
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
                "step0017",
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
                "step0018",
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
                "step0019",
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
                "step0020",
                "执行公开工具 Tractor__plant_seeds；参数 {'farm_id': 'soybean', 'start_ridge': 12, 'end_ridge': 15, 'depth_cm': 4.0, 'seed_spacing_cm': 4.545454545454546}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0021",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=4315966.0),
                "step0022",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 4315966.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0023",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0024",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0025",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0026",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanIrrigation"].irrigate(start=0, end=15, hours=5.25),
                "step0027",
                "执行公开工具 SoybeanIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 5.25}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0028",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0029",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=499200.0),
                "step0030",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 499200.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0031",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0032",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0033",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0034",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=345600.0),
                "step0035",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 345600.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0036",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0037",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0038",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0039",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].get_protection_accounts(),
                "step0040",
                "执行公开工具 CropProtection__get_protection_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].get_protection_accounts(),
                "step0041",
                "执行公开工具 CropProtection__get_protection_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0042",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0043",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0044",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0045",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].purchase(
                    product_id="transform_wg",
                    quantity=24.782019063459423,
                    order_id="t0-purchase",
                ),
                "step0046",
                "执行公开工具 CropProtection__purchase；参数 {'product_id': 'transform_wg', 'quantity': 24.782019063459423, 'order_id': 't0-purchase'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="transform_wg",
                    start_ridge=0,
                    end_ridge=3,
                    rate_per_ha=52.53989794661513,
                    application_id="t0-r0",
                ),
                "step0047",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'transform_wg', 'start_ridge': 0, 'end_ridge': 3, 'rate_per_ha': 52.53989794661513, 'application_id': 't0-r0'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="transform_wg",
                    start_ridge=4,
                    end_ridge=7,
                    rate_per_ha=52.53989794661513,
                    application_id="t0-r4",
                ),
                "step0048",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'transform_wg', 'start_ridge': 4, 'end_ridge': 7, 'rate_per_ha': 52.53989794661513, 'application_id': 't0-r4'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="transform_wg",
                    start_ridge=8,
                    end_ridge=11,
                    rate_per_ha=52.53989794661513,
                    application_id="t0-r8",
                ),
                "step0049",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'transform_wg', 'start_ridge': 8, 'end_ridge': 11, 'rate_per_ha': 52.53989794661513, 'application_id': 't0-r8'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="transform_wg",
                    start_ridge=12,
                    end_ridge=15,
                    rate_per_ha=52.53989794661513,
                    application_id="t0-r12",
                ),
                "step0050",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'transform_wg', 'start_ridge': 12, 'end_ridge': 15, 'rate_per_ha': 52.53989794661513, 'application_id': 't0-r12'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].get_protection_accounts(),
                "step0051",
                "执行公开工具 CropProtection__get_protection_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0052",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0053",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=428603.90400004387),
                "step0054",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 428603.90400004387}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0055",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0056",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0057",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0058",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].get_protection_accounts(),
                "step0059",
                "执行公开工具 CropProtection__get_protection_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].get_protection_accounts(),
                "step0060",
                "执行公开工具 CropProtection__get_protection_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0061",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0062",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].purchase(
                    product_id="sefina",
                    quantity=103.40798611111113,
                    order_id="t1-purchase",
                ),
                "step0063",
                "执行公开工具 CropProtection__purchase；参数 {'product_id': 'sefina', 'quantity': 103.40798611111113, 'order_id': 't1-purchase'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="sefina",
                    start_ridge=0,
                    end_ridge=3,
                    rate_per_ha=219.23334911616163,
                    application_id="t1-r0",
                ),
                "step0064",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'sefina', 'start_ridge': 0, 'end_ridge': 3, 'rate_per_ha': 219.23334911616163, 'application_id': 't1-r0'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="sefina",
                    start_ridge=4,
                    end_ridge=7,
                    rate_per_ha=219.23334911616163,
                    application_id="t1-r4",
                ),
                "step0065",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'sefina', 'start_ridge': 4, 'end_ridge': 7, 'rate_per_ha': 219.23334911616163, 'application_id': 't1-r4'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="sefina",
                    start_ridge=8,
                    end_ridge=11,
                    rate_per_ha=219.23334911616163,
                    application_id="t1-r8",
                ),
                "step0066",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'sefina', 'start_ridge': 8, 'end_ridge': 11, 'rate_per_ha': 219.23334911616163, 'application_id': 't1-r8'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="sefina",
                    start_ridge=12,
                    end_ridge=15,
                    rate_per_ha=219.23334911616163,
                    application_id="t1-r12",
                ),
                "step0067",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'sefina', 'start_ridge': 12, 'end_ridge': 15, 'rate_per_ha': 219.23334911616163, 'application_id': 't1-r12'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].get_protection_accounts(),
                "step0068",
                "执行公开工具 CropProtection__get_protection_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0069",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0070",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0071",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0072",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0073",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0074",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanIrrigation"].irrigate(start=0, end=15, hours=5.25),
                "step0075",
                "执行公开工具 SoybeanIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 5.25}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0076",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0077",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=323003.90400004387),
                "step0078",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 323003.90400004387}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0079",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0080",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0081",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0082",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].get_protection_accounts(),
                "step0083",
                "执行公开工具 CropProtection__get_protection_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].get_protection_accounts(),
                "step0084",
                "执行公开工具 CropProtection__get_protection_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0085",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0086",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].purchase(
                    product_id="transform_wg",
                    quantity=24.782019063459423,
                    order_id="t2-purchase",
                ),
                "step0087",
                "执行公开工具 CropProtection__purchase；参数 {'product_id': 'transform_wg', 'quantity': 24.782019063459423, 'order_id': 't2-purchase'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="transform_wg",
                    start_ridge=0,
                    end_ridge=3,
                    rate_per_ha=52.53989794661513,
                    application_id="t2-r0",
                ),
                "step0088",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'transform_wg', 'start_ridge': 0, 'end_ridge': 3, 'rate_per_ha': 52.53989794661513, 'application_id': 't2-r0'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="transform_wg",
                    start_ridge=4,
                    end_ridge=7,
                    rate_per_ha=52.53989794661513,
                    application_id="t2-r4",
                ),
                "step0089",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'transform_wg', 'start_ridge': 4, 'end_ridge': 7, 'rate_per_ha': 52.53989794661513, 'application_id': 't2-r4'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="transform_wg",
                    start_ridge=8,
                    end_ridge=11,
                    rate_per_ha=52.53989794661513,
                    application_id="t2-r8",
                ),
                "step0090",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'transform_wg', 'start_ridge': 8, 'end_ridge': 11, 'rate_per_ha': 52.53989794661513, 'application_id': 't2-r8'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="transform_wg",
                    start_ridge=12,
                    end_ridge=15,
                    rate_per_ha=52.53989794661513,
                    application_id="t2-r12",
                ),
                "step0091",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'transform_wg', 'start_ridge': 12, 'end_ridge': 15, 'rate_per_ha': 52.53989794661513, 'application_id': 't2-r12'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].get_protection_accounts(),
                "step0092",
                "执行公开工具 CropProtection__get_protection_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0093",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0094",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=428603.90399980545),
                "step0095",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 428603.90399980545}",
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
                apps["CropProtection"].scout(),
                "step0099",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=259200.0),
                "step0100",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 259200.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0101",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0102",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0103",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0104",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanIrrigation"].irrigate(start=0, end=15, hours=5.25),
                "step0105",
                "执行公开工具 SoybeanIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 5.25}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0106",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0107",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=240000.0),
                "step0108",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 240000.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0109",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0110",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0111",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0112",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=604800.0),
                "step0113",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 604800.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0114",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0115",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0116",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0117",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=432000.0),
                "step0118",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 432000.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0119",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0120",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0121",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0122",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanIrrigation"].irrigate(start=0, end=15, hours=5.25),
                "step0123",
                "执行公开工具 SoybeanIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 5.25}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0124",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0125",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=67200.0),
                "step0126",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 67200.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0127",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0128",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0129",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0130",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=604800.0),
                "step0131",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 604800.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0132",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0133",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0134",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0135",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1123200.0),
                "step0136",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1123200.0}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_crop_capabilities(),
                "step0137",
                "执行公开工具 SoybeanField__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].get_protection_accounts(),
                "step0138",
                "执行公开工具 CropProtection__get_protection_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0139",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0140",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0141",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0142",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0143",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0144",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0145",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0146",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0147",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0148",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0149",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0150",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0151",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0152",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0153",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0154",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0155",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0156",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0157",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0158",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0159",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0160",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0161",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0162",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0163",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0164",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].refuel(liters=100.0),
                "step0165",
                "执行公开工具 Tractor__refuel；参数 {'liters': 100.0}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].attach_implement(implement="harvester"),
                "step0166",
                "执行公开工具 Tractor__attach_implement；参数 {'implement': 'harvester'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="soybean", start_ridge=0, end_ridge=3),
                "step0167",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'soybean', 'start_ridge': 0, 'end_ridge': 3}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="soybean-2019-00"),
                "step0168",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'soybean-2019-00'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="soybean-2019-00", target_moisture_pct=13.0
                ),
                "step0169",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'soybean-2019-00', 'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="soybean-2019-00"),
                "step0170",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'soybean-2019-00'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="soybean", start_ridge=4, end_ridge=7),
                "step0171",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'soybean', 'start_ridge': 4, 'end_ridge': 7}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="soybean-2019-04"),
                "step0172",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'soybean-2019-04'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="soybean-2019-04", target_moisture_pct=13.0
                ),
                "step0173",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'soybean-2019-04', 'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="soybean-2019-04"),
                "step0174",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'soybean-2019-04'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="soybean", start_ridge=8, end_ridge=11),
                "step0175",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'soybean', 'start_ridge': 8, 'end_ridge': 11}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="soybean-2019-08"),
                "step0176",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'soybean-2019-08'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="soybean-2019-08", target_moisture_pct=13.0
                ),
                "step0177",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'soybean-2019-08', 'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="soybean-2019-08"),
                "step0178",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'soybean-2019-08'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(
                    farm_id="soybean", start_ridge=12, end_ridge=15
                ),
                "step0179",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'soybean', 'start_ridge': 12, 'end_ridge': 15}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="soybean-2019-12"),
                "step0180",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'soybean-2019-12'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="soybean-2019-12", target_moisture_pct=13.0
                ),
                "step0181",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'soybean-2019-12', 'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="soybean-2019-12"),
                "step0182",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'soybean-2019-12'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0183",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].get_protection_accounts(),
                "step0184",
                "执行公开工具 CropProtection__get_protection_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["OperatingAccounts"].get_accounts(),
                "step0185",
                "执行公开工具 OperatingAccounts__get_accounts；参数 {}",
            )
        return finish_capture(self, events)
