"""Two distinct crop fields compete for water and one physical tractor."""

from datetime import datetime
from dataclasses import asdict
import hashlib
from pathlib import Path
import json
from zoneinfo import ZoneInfo

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world.equipment import TractorEquipment, DEFAULT_TRACTOR_IMPLEMENTS
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.sensor_app import SensorApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.apps.system import SystemApp
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.scenarios.management_extensions.runtime import (
    PlanningFarm,
    PlanningTractor,
    crop_options,
)
from .runtime import OperatingAccounts, PooledIrrigation, Prices

REFERENCE_PATH = Path(__file__).with_name("reference.json")


class ScenarioJointCropOperatingMargin(Scenario):
    scenario_id = "scenario_l3_joint_maize_soybean_operating_margin"
    level = "L3"
    timezone_name = "Europe/Paris"

    def __init__(self, *, calibrating=False, **kwargs):
        self.calibrating = calibrating
        self._briefing_input_override = kwargs.get("scenario_input", "")
        super().__init__(**kwargs)

    def __post_init__(self):
        super().__post_init__()
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean")
        self.start_time = datetime(
            2019, 5, 1, 7, tzinfo=ZoneInfo(self.timezone_name)
        ).timestamp()
        self.duration = 213 * 86400
        self.crop_backend = "wofost"
        self.prices = Prices()
        self.water_capacity_m3 = 900.0

    def setup(self, *args, **kwargs):
        if self.apps:
            return
        if args or kwargs:
            raise ValueError("This fixed experimental scene has no setup overrides")
        self.init_and_populate_apps()
        self.build_events_flow()

    def init_and_populate_apps(self):
        self.weather, self.system = WeatherApp(), SystemApp()
        self.aui = AgentUserInterface()
        self.farms = []
        for crop, width in (("maize", 0.75), ("soybean", 1.1)):
            farm = PlanningFarm(
                selected_crop=crop,
                num_ridges=16,
                field_length_m=268.0,
                ridge_width_m=width,
            )
            farm.farm_id = crop
            farm.name = "MaizeField" if crop == "maize" else "SoybeanField"
            self.farms.append(farm)
        self.sensors = {
            f.crop_id: SensorApp(f, name=f"{f.crop_id.title()}Sensor")
            for f in self.farms
        }
        self.irrigation = {
            f.crop_id: PooledIrrigation(
                f,
                self.weather,
                self.farms,
                self.water_capacity_m3,
                name=f"{f.crop_id.title()}Irrigation",
            )
            for f in self.farms
        }
        seeds = {
            "MAIZE_201": crop_options(self.farms[0])["maize"]["required_seeds"],
            "SOYBEAN_901": crop_options(self.farms[1])["soybean"]["required_seeds"],
        }
        self.warehouse = WarehouseApp(
            WarehouseStock(seeds, 0.0, 500.0, 300.0),
            storage_capacity_kg=15000.0,
            drying_capacity_kg_per_day=10000.0,
            max_storage_moisture_pct=14.0,
        )
        contexts = [
            FarmContext(
                f.crop_id,
                f,
                self.weather,
                self.sensors[f.crop_id],
                self.irrigation[f.crop_id],
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
        self.accounts = OperatingAccounts(self)
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
            date="2019-05-01",
            temp_c=12.0,
            humidity_pct=65.0,
            wind_speed_ms=2.0,
            rainfall_mm=0.0,
            solar_radiation=15 / 0.0864,
            avg_soil_vwc=0.26,
        )
        detailed_briefing = (
            "经营两个独立地块的2019完整种植季：maize为16垄×268m×0.75m=3216m²，"
            "soybean为16垄×268m×1.1m=4716.8m²。两场共用拖拉机、仓库、时钟与900m³灌溉总量。"
            "已承诺种植并完成两场的全田成熟收获及安全入库，目标是在真实可执行的经营方案中最大化净经营收益。"
            "读取各场能力、天气、土壤及OperatingAccounts价格和余额后，自行决定肥水管理与作业。"
            "净收益按各作物安全入库量乘公开固定粮价，减实际消耗种子、肥料、燃油、灌水及干燥成本；"
            "这不是现金销售，不计土地租金、人工、折旧和税费。所有价格为合成DEMO条件，不是市场报价。"
            "库存装入机具只是转移，未使用物资不计消耗。不同作物产量分别核算，不能相加作为产量目标。"
            "每场最多180mm水、600kg/ha肥料产品；共享水量900m³。播种和收获每趟最多4垄。"
            "玉米MAIZE_201，单行株距20cm、播深5cm；大豆SOYBEAN_901，双行约4.545cm株距、播深4cm。"
            "参考作物未作当地田间校准；此场没有额外病虫压力。截止2019-11-30。"
            "无预设产量门槛；评分比较本环境重新探索的可行候选最佳收益，报告搜索范围，不声称全局最优。"
        )
        basic_briefing = (
            "经营2019季两个独立地块：3216m²玉米、4716.8m²大豆，各16垄。"
            "两场共用拖拉机、仓库和900m³季节灌水，单场上限180mm水、600kg/ha肥料产品。"
            "须在2019-11-30前完成两场全田播种、成熟收获及安全入库；最大化净经营收益。"
            "收益为各作物安全存粮的固定价值减实际消耗的种子、肥料、燃油、水和干燥成本。"
            "通过公开工具读取物理限制、合成DEMO价格和物资余额后自行制定管理方案。"
            "不同作物产量分别报告，无预设产量门槛；费用不计土地、人工、折旧、税费。"
        )
        self.scenario_input = self._briefing_input_override or (
            detailed_briefing if self.detailed_briefing else basic_briefing
        )
        if self.additional_system_prompt is None:
            self.additional_system_prompt = self.scenario_input

    def input_signature(self):
        """Comparable physical/economic inputs; excludes mutable episode state."""
        from fairy.scenarios.fos.provenance import crop_backend_provenance

        return {
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

    def input_fingerprint(self):
        return hashlib.sha256(
            json.dumps(self.input_signature(), sort_keys=True).encode()
        ).hexdigest()

    def build_events_flow(self):
        if self.calibrating:
            self.events = []
            return []
        reference = json.loads(REFERENCE_PATH.read_text())
        if reference.get("input_fingerprint") != self.input_fingerprint():
            raise ValueError(
                "Calibrated reference does not match this scene's physical/economic inputs"
            )
        from .oracle import capture_reference

        return capture_reference(self)

    def validate(self, env=None):
        errors = []
        if self.farm_environment.time_manager.time() > self.start_time + self.duration:
            errors.append("Season deadline exceeded")
        for farm in self.farms:
            if not all(r.harvested for r in farm._ridges):
                errors.append(f"Incomplete planted/harvested field: {farm.farm_id}")
            if not all(farm.is_ridge_mature(i) for i in range(farm.num_ridges)):
                errors.append(f"Harvest maturity not satisfied: {farm.farm_id}")
            planted = [
                rid
                for op in self.tractor._operation_log
                if op.get("operation") == "plant_seeds"
                and op.get("farm_id") == farm.farm_id
                for rid in op["ridge_ids"]
            ]
            if sorted(planted) != list(range(farm.num_ridges)):
                errors.append(f"Incomplete or duplicate planting: {farm.farm_id}")
            batches = [
                b
                for b in self.warehouse.grain_batches.values()
                if b.origin_farm_id == farm.farm_id
            ]
            ids = [rid for b in batches for rid in b.ridge_ids]
            if sorted(ids) != list(range(farm.num_ridges)) or any(
                b.status != "stored"
                or b.moisture_pct is None
                or b.moisture_pct > farm._postharvest_market.max_storage_moisture_pct
                or b.crop_id != farm.crop_id
                or b.cultivar_ids
                != ["MAIZE_201" if farm.crop_id == "maize" else "SOYBEAN_901"]
                for b in batches
            ):
                errors.append(f"Unsafe/incomplete batch provenance: {farm.farm_id}")
        account = self.accounts.compute_accounts()
        if account["water_m3"] > self.water_capacity_m3 + 1e-7:
            errors.append("Shared water exceeded")
        for farm in self.farms:
            regime = farm._management_regime
            if (
                regime.irrigation_used_mm_total > 180.0 + 1e-7
                or regime.fertilizer_used_kg > 600 * farm.field_area_m2 / 10000 + 1e-7
            ):
                errors.append(f"Field quota exceeded: {farm.farm_id}")
        stock = self.warehouse.stock
        if (
            min(
                stock.fertilizer_kg,
                stock.fuel_liters,
                *stock.seed_stock.values(),
                self.tractor._fuel_tank_l,
                self.tractor._fertilizer_spreader_kg,
                self.tractor._seed_hopper,
            )
            < -1e-8
        ):
            errors.append("Negative resource stock")
        applied_fertilizer = sum(
            f._management_regime.fertilizer_used_kg for f in self.farms
        )
        if abs(account["fertilizer_product_kg"] - applied_fertilizer) > 1e-7:
            errors.append("Fertilizer material balance mismatch")
        if self.tractor._grain_bin_kg > 1e-8:
            errors.append("Grain remains in machine")
        if any(
            x < -1e-7
            for x in (
                account["fertilizer_product_kg"],
                account["fuel_liters"],
                *account["consumed_seeds"].values(),
            )
        ):
            errors.append("Negative material consumption")
        reference = (
            json.loads(REFERENCE_PATH.read_text())
            if REFERENCE_PATH.exists() and not self.calibrating
            else None
        )
        if reference:
            if reference.get("input_fingerprint") != self.input_fingerprint():
                errors.append("Reference inputs do not match current scenario")
            account["reference_best_margin"] = reference["selected"][
                "net_operating_margin"
            ]
            account["margin_regret"] = (
                reference["selected"]["net_operating_margin"]
                - account["net_operating_margin"]
            )
            account["reference_scope"] = reference["scope"]
        account["feasible"] = not errors
        return ScenarioValidationResult(
            success=not errors,
            message="; ".join(errors) or "Both crops safely stored",
            metadata=account,
        )
