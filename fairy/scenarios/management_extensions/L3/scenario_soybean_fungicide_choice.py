"""L3：单场大豆生长期病害与真实商品杀菌剂选药经营。题设、初始化、评估入口及完整 Oracle 均在本文件。"""

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


class ScenarioSoybeanFungicideChoice(Scenario):
    scenario_id = "scenario_l3_soybean_fungicide_choice"
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
    outbreak_pressure: ClassVar = 0.60
    initial_fertilizer_kg: ClassVar = 0.0
    initial_fuel_liters: ClassVar = 300.0
    storage_capacity_kg: ClassVar = 15000.0
    drying_capacity_kg_per_day: ClassVar = 10000.0
    safe_moisture_pct: ClassVar = 13.0
    ORACLE_REFERENCE: ClassVar[dict] = {
        "scenario_id": "scenario_l3_soybean_fungicide_choice",
        "input_fingerprint": "d24f7ff8c93d04ce519a3775612029fe53f3da6abaeecc765ded62a149a7e1db",
        "selected": {
            "currency": "USD",
            "price_book_id": "china_northeast_2025_usd_v1",
            "cny_per_usd": 7.1757,
            "biological_kg_by_crop": {"soybean": 1692.5288125256518},
            "recovered_kg_by_crop": {"soybean": 1842.8849935095961},
            "stored_kg_by_crop": {"soybean": 1842.88},
            "production_cost": 97.9333692183341,
            "stored_grain_value": 1109.4724695848488,
            "net_operating_margin": 1011.5391003665146,
        },
        "workflow_steps": 202,
        "candidate_count": 5,
        "feasible_count": 5,
        "scope": "Best feasible candidate among 5 freshly executed USD management candidates, including "
        "the prior literal workflow, a short-list ranked from archived physical receipts, and "
        "explicit crop/water/fertilizer/protection controls. Crop biology, weather and physical "
        "caps unchanged. No claim of global optimum; archived revaluations are rankings, not "
        "fresh execution.",
        "calibration_artifact": "validation_runs/management_usd_china_2025_20261103_220138/newer/scenario_l3_soybean_fungicide_choice/calibration_reference.json",
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
        path = (
            Path(__file__).parents[1] / "data/soybean_fungicide_products/catalog.json"
        )
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
                    event_id="soybean_disease_risk",
                    farm_id="soybean",
                    ridge_start=0,
                    ridge_end=15,
                    start=self.outbreak_day,
                    end=date(2019, 7, 2),
                    kind="disease",
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
        task = "经营面积4716.8m²、垄距1.1m的大豆田，完成全季管理并应对生长期的模拟病害压力，成熟收获后安全入库，尽量提高净经营收益。基础价格、余额及截止时间查 OperatingAccounts.get_accounts；具名杀菌剂、剂量限制和服务报价查 CropProtection.get_products，其他参数通过对应工具查询。"
        if not detailed:
            return task
        guidance = textwrap.dedent(
            """\
            管理指导：

            建植与水分：读取作物能力、库存、土壤、天气和设备状态，按实际要求完成全田建植。结合 SoybeanSensor.read_soil_sensors、预报和生育阶段判断水分需求；持续偏干且降雨不足时在额度内分次供水，待响应生效后复测同一区域。

            病害判断：用 CropProtection.scout 连续查看病害压力、作物阶段和残效，再与 read_canopy_sensors 的长势变化及水分情况对照。压力上升、作物仍可受保护且目录指引支持时比较处理方案；冠层偏弱本身不能证明病害或缺肥。这里的通用病害压力不是实验室病原确诊。

            选药与费用：比较 get_products 的适用作物、商品单位、允许用量、间隔、季节累计和采收限制，按面积换算制剂需求，并保留后续作业所需现金。商品资料、模拟药效和报价分别核对；换商品不等于换作用机制，不能用不同名称绕过同组连续使用限制。

            处理与复查：在天气与作业条件允许时按工具覆盖范围施用，保存订单及施药编号。等待实际响应后复查 scout、同区域冠层与残效，依据持续压力及目录限制决定是否再处理，不预设固定施药次数，也不把施药当作追回既往产量。

            成熟与核算：只有实际成熟、水分、天气及 harvest_allowed_from 都允许时收获，按批卸粮、必要干燥并安全入库。营养代理值不能替代养分化验；无可靠证据时不额外施肥。最后核对药品消耗、服务费用、余料和实际净收益。

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
                apps["SoybeanIrrigation"].irrigate(start=0, end=15, hours=4.5),
                "step0027",
                "执行公开工具 SoybeanIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 4.5}",
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
                apps["SystemApp"].advance_time(seconds=501900.0),
                "step0030",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 501900.0}",
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
                apps["SystemApp"].advance_time(days=4),
                "step0035",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 4}",
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
                    product_id="tebustar_36l",
                    quantity=103.40798611111111,
                    order_id="t0-purchase",
                ),
                "step0046",
                "执行公开工具 CropProtection__purchase；参数 {'product_id': 'tebustar_36l', 'quantity': 103.40798611111111, 'order_id': 't0-purchase'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="tebustar_36l",
                    start_ridge=0,
                    end_ridge=3,
                    rate_per_ha=219.2333491161616,
                    application_id="t0-r0",
                ),
                "step0047",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'tebustar_36l', 'start_ridge': 0, 'end_ridge': 3, 'rate_per_ha': 219.2333491161616, 'application_id': 't0-r0'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="tebustar_36l",
                    start_ridge=4,
                    end_ridge=7,
                    rate_per_ha=219.2333491161616,
                    application_id="t0-r4",
                ),
                "step0048",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'tebustar_36l', 'start_ridge': 4, 'end_ridge': 7, 'rate_per_ha': 219.2333491161616, 'application_id': 't0-r4'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="tebustar_36l",
                    start_ridge=8,
                    end_ridge=11,
                    rate_per_ha=219.2333491161616,
                    application_id="t0-r8",
                ),
                "step0049",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'tebustar_36l', 'start_ridge': 8, 'end_ridge': 11, 'rate_per_ha': 219.2333491161616, 'application_id': 't0-r8'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="tebustar_36l",
                    start_ridge=12,
                    end_ridge=15,
                    rate_per_ha=219.2333491161616,
                    application_id="t0-r12",
                ),
                "step0050",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'tebustar_36l', 'start_ridge': 12, 'end_ridge': 15, 'rate_per_ha': 219.2333491161616, 'application_id': 't0-r12'}",
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
                apps["SystemApp"].advance_time(days=2),
                "step0059",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 2}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0060",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0061",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0062",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0063",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanIrrigation"].irrigate(start=0, end=15, hours=4.5),
                "step0064",
                "执行公开工具 SoybeanIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 4.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0065",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0066",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0067",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0068",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0069",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0070",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].get_protection_accounts(),
                "step0071",
                "执行公开工具 CropProtection__get_protection_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].get_protection_accounts(),
                "step0072",
                "执行公开工具 CropProtection__get_protection_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=69900.0),
                "step0073",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 69900.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0074",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0075",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0076",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0077",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0078",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0079",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0080",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0081",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0082",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0083",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].purchase(
                    product_id="tebustar_36l",
                    quantity=103.40798611111111,
                    order_id="t1-purchase",
                ),
                "step0084",
                "执行公开工具 CropProtection__purchase；参数 {'product_id': 'tebustar_36l', 'quantity': 103.40798611111111, 'order_id': 't1-purchase'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="tebustar_36l",
                    start_ridge=0,
                    end_ridge=3,
                    rate_per_ha=219.2333491161616,
                    application_id="t1-r0",
                ),
                "step0085",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'tebustar_36l', 'start_ridge': 0, 'end_ridge': 3, 'rate_per_ha': 219.2333491161616, 'application_id': 't1-r0'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="tebustar_36l",
                    start_ridge=4,
                    end_ridge=7,
                    rate_per_ha=219.2333491161616,
                    application_id="t1-r4",
                ),
                "step0086",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'tebustar_36l', 'start_ridge': 4, 'end_ridge': 7, 'rate_per_ha': 219.2333491161616, 'application_id': 't1-r4'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="tebustar_36l",
                    start_ridge=8,
                    end_ridge=11,
                    rate_per_ha=219.2333491161616,
                    application_id="t1-r8",
                ),
                "step0087",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'tebustar_36l', 'start_ridge': 8, 'end_ridge': 11, 'rate_per_ha': 219.2333491161616, 'application_id': 't1-r8'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="tebustar_36l",
                    start_ridge=12,
                    end_ridge=15,
                    rate_per_ha=219.2333491161616,
                    application_id="t1-r12",
                ),
                "step0088",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'tebustar_36l', 'start_ridge': 12, 'end_ridge': 15, 'rate_per_ha': 219.2333491161616, 'application_id': 't1-r12'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].get_protection_accounts(),
                "step0089",
                "执行公开工具 CropProtection__get_protection_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0090",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0091",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0092",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0093",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0094",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0095",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=428603.90400004387),
                "step0096",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 428603.90400004387}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0097",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0098",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0099",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0100",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].get_protection_accounts(),
                "step0101",
                "执行公开工具 CropProtection__get_protection_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].get_protection_accounts(),
                "step0102",
                "执行公开工具 CropProtection__get_protection_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=4),
                "step0103",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 4}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0104",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].purchase(
                    product_id="tebustar_36l",
                    quantity=103.40798611111111,
                    order_id="t2-purchase",
                ),
                "step0105",
                "执行公开工具 CropProtection__purchase；参数 {'product_id': 'tebustar_36l', 'quantity': 103.40798611111111, 'order_id': 't2-purchase'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="tebustar_36l",
                    start_ridge=0,
                    end_ridge=3,
                    rate_per_ha=219.2333491161616,
                    application_id="t2-r0",
                ),
                "step0106",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'tebustar_36l', 'start_ridge': 0, 'end_ridge': 3, 'rate_per_ha': 219.2333491161616, 'application_id': 't2-r0'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="tebustar_36l",
                    start_ridge=4,
                    end_ridge=7,
                    rate_per_ha=219.2333491161616,
                    application_id="t2-r4",
                ),
                "step0107",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'tebustar_36l', 'start_ridge': 4, 'end_ridge': 7, 'rate_per_ha': 219.2333491161616, 'application_id': 't2-r4'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="tebustar_36l",
                    start_ridge=8,
                    end_ridge=11,
                    rate_per_ha=219.2333491161616,
                    application_id="t2-r8",
                ),
                "step0108",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'tebustar_36l', 'start_ridge': 8, 'end_ridge': 11, 'rate_per_ha': 219.2333491161616, 'application_id': 't2-r8'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].apply(
                    product_id="tebustar_36l",
                    start_ridge=12,
                    end_ridge=15,
                    rate_per_ha=219.2333491161616,
                    application_id="t2-r12",
                ),
                "step0109",
                "执行公开工具 CropProtection__apply；参数 {'product_id': 'tebustar_36l', 'start_ridge': 12, 'end_ridge': 15, 'rate_per_ha': 219.2333491161616, 'application_id': 't2-r12'}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].get_protection_accounts(),
                "step0110",
                "执行公开工具 CropProtection__get_protection_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0111",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0112",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0113",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0114",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0115",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0116",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0117",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0118",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0119",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0120",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanIrrigation"].irrigate(start=0, end=15, hours=4.5),
                "step0121",
                "执行公开工具 SoybeanIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 4.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0122",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0123",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=152903.90399980545),
                "step0124",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 152903.90399980545}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0125",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0126",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0127",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0128",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=7),
                "step0129",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0130",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0131",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0132",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0133",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=5),
                "step0134",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 5}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0135",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0136",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0137",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0138",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanIrrigation"].irrigate(start=0, end=15, hours=4.5),
                "step0139",
                "执行公开工具 SoybeanIrrigation__irrigate；参数 {'start': 0, 'end': 15, 'hours': 4.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0140",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0141",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=69900.0),
                "step0142",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 69900.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0143",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0144",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0145",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0146",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=7),
                "step0147",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0148",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0149",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanSensor"].read_soil_sensors(),
                "step0150",
                "执行公开工具 SoybeanSensor__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].scout(),
                "step0151",
                "执行公开工具 CropProtection__scout；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=13),
                "step0152",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 13}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_crop_capabilities(),
                "step0153",
                "执行公开工具 SoybeanField__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].get_protection_accounts(),
                "step0154",
                "执行公开工具 CropProtection__get_protection_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0155",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0156",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0157",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0158",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0159",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0160",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0161",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0162",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0163",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0164",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0165",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0166",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0167",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0168",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0169",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0170",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0171",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0172",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0173",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0174",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0175",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0176",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0177",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0178",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0179",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
                "step0180",
                "执行公开工具 SoybeanField__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].refuel(liters=100.0),
                "step0181",
                "执行公开工具 Tractor__refuel；参数 {'liters': 100.0}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].attach_implement(implement="harvester"),
                "step0182",
                "执行公开工具 Tractor__attach_implement；参数 {'implement': 'harvester'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="soybean", start_ridge=0, end_ridge=3),
                "step0183",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'soybean', 'start_ridge': 0, 'end_ridge': 3}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="soybean-2019-00"),
                "step0184",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'soybean-2019-00'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="soybean-2019-00", target_moisture_pct=13.0
                ),
                "step0185",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'soybean-2019-00', 'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="soybean-2019-00"),
                "step0186",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'soybean-2019-00'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="soybean", start_ridge=4, end_ridge=7),
                "step0187",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'soybean', 'start_ridge': 4, 'end_ridge': 7}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="soybean-2019-04"),
                "step0188",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'soybean-2019-04'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="soybean-2019-04", target_moisture_pct=13.0
                ),
                "step0189",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'soybean-2019-04', 'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="soybean-2019-04"),
                "step0190",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'soybean-2019-04'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(farm_id="soybean", start_ridge=8, end_ridge=11),
                "step0191",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'soybean', 'start_ridge': 8, 'end_ridge': 11}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="soybean-2019-08"),
                "step0192",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'soybean-2019-08'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="soybean-2019-08", target_moisture_pct=13.0
                ),
                "step0193",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'soybean-2019-08', 'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="soybean-2019-08"),
                "step0194",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'soybean-2019-08'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].harvest(
                    farm_id="soybean", start_ridge=12, end_ridge=15
                ),
                "step0195",
                "执行公开工具 Tractor__harvest；参数 {'farm_id': 'soybean', 'start_ridge': 12, 'end_ridge': 15}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].unload_grain(batch_id="soybean-2019-12"),
                "step0196",
                "执行公开工具 Tractor__unload_grain；参数 {'batch_id': 'soybean-2019-12'}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].dry_grain(
                    batch_id="soybean-2019-12", target_moisture_pct=13.0
                ),
                "step0197",
                "执行公开工具 Warehouse__dry_grain；参数 {'batch_id': 'soybean-2019-12', 'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["Warehouse"].store_grain(batch_id="soybean-2019-12"),
                "step0198",
                "执行公开工具 Warehouse__store_grain；参数 {'batch_id': 'soybean-2019-12'}",
            )
            previous = capture_step(
                previous,
                apps["Tractor"].detach_implement(),
                "step0199",
                "执行公开工具 Tractor__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropProtection"].get_protection_accounts(),
                "step0200",
                "执行公开工具 CropProtection__get_protection_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["OperatingAccounts"].get_accounts(),
                "step0201",
                "执行公开工具 OperatingAccounts__get_accounts；参数 {}",
            )
        return finish_capture(self, events)
