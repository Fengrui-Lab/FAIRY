"""L4：同田两年玉米。题设、初始化、评估入口及完整 Oracle 均在本文件。"""

import hashlib
import json
import textwrap
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, time
from typing import ClassVar
from zoneinfo import ZoneInfo

from fairy.apps.farm_world import FarmWorldApp, SensorApp, TractorApp, WeatherApp
from fairy.physics.profiles import PhysicsProfile, get_profile
from fairy.physics.weather_engine import (
    WeatherEvent,
    WeatherGenerator,
    default_harbin_soybean_config,
)
from fairy.scenarios.farm_world_fullseason_v2.harbin_l3_scenario_helpers import (
    install_common_farm_apps,
)
from fairy.scenarios.scenario import Scenario
from fairy.types import EventRegisterer

from ..apps.season_cycle_app import AnnualCropSeason, SeasonCycle
from ..china_market_prices import operating_prices
from ..common import capture_step, finish_capture
from ..engines.continuous_wofost import ContinuousFarm, ContinuousSeasonBackend
from ..evaluation.multi_season_yield import evaluate
from ..oracle_management_plans import manage_annual_maize


class TwoYearMaizeScenario(Scenario):
    prices: ClassVar = operating_prices()
    scenario_id = "scenario_l4_two_year_maize_soil_carryover"
    level = "L4"
    objective_metric = "total_stored_grain_kg"
    oracle_policy = staticmethod(manage_annual_maize)
    timezone_name = "Asia/Shanghai"

    # 本任务的具体环境、资源和目标参数。
    field: ClassVar = {
        "app_name": "",
        "crop_id": "maize",
        "farm_id": "field",
        "field_length_m": 268.0,
        "ridge_count": 64,
        "ridge_width_m": 0.75,
        "seed_type": "MAIZE_201",
    }
    seasons: ClassVar = (
        AnnualCropSeason(
            sowing_date=date(2026, 5, 5),
            harvest_deadline=date(2026, 10, 31),
            fertilizer_limit_kg=800.0,
            water_limit_mm=300.0,
        ),
        AnnualCropSeason(
            sowing_date=date(2027, 5, 5),
            harvest_deadline=date(2027, 10, 31),
            fertilizer_limit_kg=800.0,
            water_limit_mm=300.0,
        ),
    )
    backend_options: ClassVar = {
        "base_soil_n_kg_ha": 50.0,
        "crop_name": "maize",
        "external_biotic_coupling": False,
        "initial_available_n_kg_ha": 50.0,
        "reference_density_plants_m2": 6.666666666666666,
        "soil_n_mineralization_fraction": 0.002,
        "variety_name": "Grain_maize_201",
    }
    fertilizer_budget_kg: ClassVar = 1200.0
    water_budget_mm: ClassVar = 400.0
    seed_count: ClassVar = 200000
    initial_fuel_liters: ClassVar = 1000.0
    initial_machine_fuel_liters: ClassVar = 100.0
    storage_capacity_kg: ClassVar = 50000.0
    drying_capacity_kg_per_day: ClassVar = 20000.0
    safe_moisture_pct: ClassVar = 14.0
    maximum_harvest_moisture_pct: ClassVar = 25
    initial_soil_vwc: ClassVar = 0.28
    initial_soil_temperature_c: ClassVar = 16
    weather_seed: ClassVar = 101
    horizon_days: ClassVar = 550

    # 原实验实际观测种子，避免 Python 进程 hash 改变传感器观测。
    observation_seeds: ClassVar[dict] = {
        "AgentUserInterface": 3729385368,
        "FarmWorldApp": 1281893346,
        "FieldOpsApp": 3100517573,
        "Mavic3M": 695188145,
        "Robot0": 3339168823,
        "SeasonCycle": 4128923743,
        "SensorApp": 1025542706,
        "SystemApp": 2196534512,
        "TractorApp": 2773417723,
        "WeatherApp": 433245120,
    }

    ORACLE_REFERENCE: ClassVar[dict] = {
        "scenario_id": "scenario_l4_two_year_maize_soil_carryover",
        "input_fingerprint": "b8c1f8bbb285ef4bae80288bf1ae3f3156ef833eb1878200f805eddb1d01c9e6",
        "selected": {
            "currency": "USD",
            "price_book_id": "china_northeast_2025_usd_v1",
            "cny_per_usd": 7.1757,
            "stored_kg_by_crop": {"maize": 29615.04},
            "grain_value": 8914.598770851624,
            "production_cost": 1210.3057593307187,
            "net_operating_margin": 7704.293011520906,
            "total_stored_grain_kg": 29615.04,
            "seasons": [
                {
                    "year": 2026,
                    "stored_grain_kg": 14727.04,
                    "biological_grain_kg": 13056.92737475719,
                    "recovered_grain_kg": 14726.999480830764,
                },
                {
                    "year": 2027,
                    "stored_grain_kg": 14888.0,
                    "biological_grain_kg": 13199.65707460254,
                    "recovered_grain_kg": 14887.985305074959,
                },
            ],
        },
        "workflow_steps": 263,
        "candidate_count": 1,
        "feasible_count": 1,
        "scope": "Best feasible candidate among 1 freshly executed USD management candidates, including "
        "the prior literal workflow, a short-list ranked from archived physical receipts, and "
        "explicit crop/water/fertilizer/protection controls. Crop biology, weather and physical "
        "caps unchanged. No claim of global optimum; archived revaluations are rankings, not "
        "fresh execution. Yield remains the objective; USD accounts are supplemental.",
        "calibration_artifact": "validation_runs/management_usd_china_2025_20261103_220138/newer/scenario_l4_two_year_maize_soil_carryover/calibration_reference.json",
    }

    def __init__(self, *, calibrating=False, **kwargs):
        self.calibrating = calibrating
        self.field = deepcopy(self.field)
        self.prices = deepcopy(self.prices)
        self.backend_options = deepcopy(self.backend_options)
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
        years = [season.year for season in self.seasons]
        if not years or years != sorted(set(years)):
            raise ValueError("Annual seasons must have distinct increasing years")
        if self.backend_options.get("crop_name") != self.field["crop_id"]:
            raise ValueError("The continuous backend and field must use the same crop")
        if (
            self.horizon_days
            < (self.seasons[-1].harvest_deadline - self.seasons[0].sowing_date).days
        ):
            raise ValueError("The simulation horizon must cover every season deadline")
        super().__init__(
            crop_backend="wofost", crop_backend_options=expected.copy(), **kwargs
        )

    def __post_init__(self):
        super().__post_init__()
        self.start_time = datetime.combine(
            self.seasons[0].sowing_date, time(7), ZoneInfo(self.timezone_name)
        ).timestamp()
        self.duration = self.horizon_days * 86400
        self.queue_based_loop = True
        self.time_increment_in_seconds = 60

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
        task = "在面积12864m²、垄距0.75m的同一农田连续经营两个日历年的玉米种植季，每季完成全田成熟收获和安全入库，最大化两季累计安全入库粮。通过 SeasonCycle.get_season_ledger 查询年度计划、额度、库存与价格，作业参数通过作物和设备工具查询。土壤与物资连续过冬；气候为连续合成气候，不包含额外积雪冻土过程。"
        if not detailed:
            return task
        guidance = textwrap.dedent(
            """\
            管理指导：

            首季规划与建植：先读季节计划、作物能力、土壤和设备状态，统筹全周期库存及各季额度。结合当前作物需求、已有投入和后续季节需要决定基施，再按工具要求完成全田建植；不要把后续季节资源提前耗尽。

            水分依据与处理：用 SensorApp.read_root_zone_sensors 及 read_soil_sensors 核对可用水分读数、覆盖区与来源，结合 WeatherApp.get_forecast 和作物阶段判断需水。持续偏干且近期降水不足时，结合面积、设施能力、当季和全周期余额选择范围及时长；偏湿或有可利用降雨则暂缓。响应生效后复读同一区域探头并核对扣量。

            营养依据与处理：结合 read_canopy_sensors、生育阶段、可见营养指标和已施肥记录检查长势。根区工具返回土壤氮模型估计时，先核对有效日期、覆盖与状态，不可用值不能当成零。先排查缺水、未出苗或衰老，持续营养异常且仍可有效吸收时再考虑分次追肥；模型估计不是独立化验，也不直接给出最优剂量。

            施后复查与收储：按产品单位、面积、库存和剩余额度安排投入，装料前核对机上余量；施后等待响应，再复读同区水分、冠层和作物状态。按实际成熟、水分、天气及设备限制完成收割、卸粮和必要干燥，核对全田及本季新增粮批后 close_season。

            跨年衔接：保留土壤、水肥消耗、库存和机器载荷，推进真实冬季日历到计划允许的开季时间，再 open_next_season 并完成次季建植。用首季结季账与次季观测调整资源分配，不重新初始化，也不把首季存粮重复计入次季产量。最后复核各季实际完成和累计安全入库量。

            """
        ).strip()
        return task + "\n\n" + guidance

    def init_and_populate_apps(self):
        farm = ContinuousFarm(
            crop_type=self.field["crop_id"],
            num_ridges=self.field["ridge_count"],
            field_length_m=self.field["field_length_m"],
            ridge_width_m=self.field["ridge_width_m"],
        )
        install_common_farm_apps(self, thermal=False, field_ops=True, farm_world=farm)
        farm.configure_crop_backend("wofost", **self.backend_options)
        farm.physics.crop_backend = ContinuousSeasonBackend(self.backend_options)
        farm.physics.crop_backend.bind_physics(farm.physics)
        farm.set_season_phase("full_season")
        tractor = self.get_typed_app(TractorApp)
        farm._inventory.seed_stock = {self.field["seed_type"]: self.seed_count}
        farm._inventory.fertilizer_kg = float(self.fertilizer_budget_kg)
        farm._inventory.fuel_liters = self.initial_fuel_liters
        farm._inventory.pesticide_liters = 0
        tractor._fuel_tank_l = self.initial_machine_fuel_liters
        tractor.configure_harvest(
            max_grain_moisture_pct=self.maximum_harvest_moisture_pct
        )
        farm.configure_management_regime(
            irrigation_quota_mm_total=min(
                self.seasons[0].water_limit_mm, self.water_budget_mm
            ),
            fertilizer_quota_kg=min(
                self.seasons[0].fertilizer_limit_kg, self.fertilizer_budget_kg
            ),
        )
        farm.configure_postharvest_market(
            market_moisture_pct=self.safe_moisture_pct,
            max_storage_moisture_pct=self.safe_moisture_pct,
            storage_capacity_kg=self.storage_capacity_kg,
            drying_capacity_kg_per_day=self.drying_capacity_kg_per_day,
        )
        farm._postharvest_market.require_safe_moisture = True
        for ridge in farm._ridges:
            ridge.planted = False
            ridge.harvested = False
            ridge.seed_type = None
            ridge.growth_stage = "NOT_PLANTED"
            ridge.soil_vwc = self.initial_soil_vwc
            ridge.soil_temp_c = self.initial_soil_temperature_c
        for soil in farm.physics.soil.states.values():
            soil.top_vwc = soil.root_vwc = self.initial_soil_vwc
            soil.top_temp_c = soil.root_temp_c = self.initial_soil_temperature_c
        weather = self.get_typed_app(WeatherApp)
        config = default_harbin_soybean_config()
        config.monthly = {
            **get_profile("harbin_baseline_2026_seed_101").monthly_climate,
            **config.monthly,
        }
        farm.physics.profile = PhysicsProfile(
            name="continuous_synthetic_harbin_v1",
            location="Synthetic Harbin climate",
            latitude_deg=45.7,
            monthly_climate=config.monthly,
            rng_seed=self.weather_seed,
            start_date=self.seasons[0].sowing_date,
            duration_days=self.horizon_days,
            weather_events=[
                WeatherEvent(
                    "dry_spell", season.sowing_date, 5, label="declared_sowing_window"
                )
                for season in self.seasons
            ],
        )
        farm.physics.weather_generator = WeatherGenerator(
            config, seed=self.weather_seed
        )
        farm.physics.scenario_metadata = {
            "daily_settlement": "completed_calendar_day",
            "weather_source": f"synthetic daily generation, continuous dates {self.seasons[0].year}-{self.seasons[-1].year}; not repeated recorded years",
            "multi_year_adapter": "v1",
            "cross_species_rotation": False,
            "residue_n_credit": False,
            "winter_limitations": "no additional snow/frozen-soil process; uncalibrated continuous CWB/CNB experiment",
        }
        from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs

        _build_weather_inputs(
            weather,
            self.seasons[0].sowing_date,
            physics=farm.physics,
            advance_weather=False,
        )
        self.cycle = SeasonCycle(
            farm,
            tractor,
            seasons=self.seasons,
            fertilizer_budget_kg=self.fertilizer_budget_kg,
            water_budget_mm=self.water_budget_mm,
            prices=self.prices,
        )
        self.apps.append(self.cycle)
        if {app.name for app in self.apps} != set(self.observation_seeds):
            raise ValueError(
                "New app composition requires an explicit observation-seed declaration"
            )
        for app in self.apps:
            app.seed = self.observation_seeds[app.name]
            app.rng.seed(app.seed)
        farm.simulation_timezone = ZoneInfo(self.timezone_name)
        self.get_typed_app(WeatherApp).simulation_timezone = farm.simulation_timezone
        self._initial_inventory = deepcopy(farm._inventory.to_dict())

    def validate(self, env=None):
        """按本场景目标读取真实执行结果评分。"""
        return evaluate(self)

    def input_signature(self) -> dict:
        configuration = {
            "field": self.field,
            "prices": self.prices,
            "seasons": tuple(asdict(season) for season in self.seasons),
            "backend_options": self.backend_options,
            "fertilizer_budget_kg": self.fertilizer_budget_kg,
            "water_budget_mm": self.water_budget_mm,
            "seed_count": self.seed_count,
            "initial_fuel_liters": self.initial_fuel_liters,
            "initial_machine_fuel_liters": self.initial_machine_fuel_liters,
            "storage_capacity_kg": self.storage_capacity_kg,
            "drying_capacity_kg_per_day": self.drying_capacity_kg_per_day,
            "safe_moisture_pct": self.safe_moisture_pct,
            "maximum_harvest_moisture_pct": self.maximum_harvest_moisture_pct,
            "initial_soil_vwc": self.initial_soil_vwc,
            "initial_soil_temperature_c": self.initial_soil_temperature_c,
            "weather_seed": self.weather_seed,
            "horizon_days": self.horizon_days,
        }
        farm = self.get_typed_app(FarmWorldApp)
        config = farm.physics.weather_generator.config
        return {
            "scenario_id": self.scenario_id,
            "plan": configuration,
            "schema": 1,
            "start_time": self.start_time,
            "duration_seconds": self.duration,
            "observation_seed": self.seed,
            "app_random_seeds": {app.name: app.seed for app in self.apps},
            "native_adapter_version": 1,
            "geometry": [farm.num_ridges, farm.field_length_m, farm.ridge_width_m],
            "native_configuration": asdict(farm.physics.crop_backend.config),
            "crop_backend_provenance": farm.physics.crop_backend.snapshot()[
                "provenance"
            ],
            "weather_configuration": asdict(config),
            "profile": asdict(farm.physics.profile),
            "initial_inventory": self._initial_inventory,
            "initial_machine_fuel_l": self.initial_machine_fuel_liters,
            "season_caps": [
                self.seasons[0].fertilizer_limit_kg,
                self.seasons[0].water_limit_mm,
            ],
            "horizon_caps": [self.fertilizer_budget_kg, self.water_budget_mm],
            "metadata": farm.physics.scenario_metadata,
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
            "farm": self.get_typed_app(FarmWorldApp).get_state(),
            "tractor": self.get_typed_app(TractorApp).get_state(),
            "cycle": self.cycle.get_state(),
            "weather": self.get_typed_app(WeatherApp).get_state(),
            "sensors": self.get_typed_app(SensorApp).get_state(),
            "clock": self.get_typed_app(FarmWorldApp).time_manager.time(),
        }

    def build_events_flow(self):
        if not self.prepare_oracle_capture():
            return []
        apps = {app.name: app for app in self.apps}
        with EventRegisterer.capture_mode() as events:
            previous = None
            previous = capture_step(
                previous,
                apps["AgentUserInterface"].send_message_to_agent(
                    content=self.scenario_input
                ),
                "step0000",
                "传递当前任务说明。",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0001",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_inventory(),
                "step0002",
                "执行公开工具 FarmWorldApp__get_inventory；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].attach_implement(implement="grader"),
                "step0003",
                "执行公开工具 TractorApp__attach_implement；参数 {'implement': 'grader'}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].level(),
                "step0004",
                "执行公开工具 TractorApp__level；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].detach_implement(),
                "step0005",
                "执行公开工具 TractorApp__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].load_fertilizer(kg=200.0),
                "step0006",
                "执行公开工具 TractorApp__load_fertilizer；参数 {'kg': 200.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].base_fertilize(total_kg=200.0),
                "step0007",
                "执行公开工具 TractorApp__base_fertilize；参数 {'total_kg': 200.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].attach_implement(implement="furrower"),
                "step0008",
                "执行公开工具 TractorApp__attach_implement；参数 {'implement': 'furrower'}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].form_ridges(ridge_width_m=0.75),
                "step0009",
                "执行公开工具 TractorApp__form_ridges；参数 {'ridge_width_m': 0.75}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].detach_implement(),
                "step0010",
                "执行公开工具 TractorApp__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].load_seeds(seed_type="MAIZE_201", count=85760),
                "step0011",
                "执行公开工具 TractorApp__load_seeds；参数 {'seed_type': 'MAIZE_201', 'count': 85760}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=0, end_ridge=3, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0012",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 0, 'end_ridge': 3, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=4, end_ridge=7, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0013",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 4, 'end_ridge': 7, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=8, end_ridge=11, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0014",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 8, 'end_ridge': 11, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=12, end_ridge=15, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0015",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 12, 'end_ridge': 15, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=16, end_ridge=19, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0016",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 16, 'end_ridge': 19, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=20, end_ridge=23, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0017",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 20, 'end_ridge': 23, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=24, end_ridge=27, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0018",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 24, 'end_ridge': 27, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=28, end_ridge=31, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0019",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 28, 'end_ridge': 31, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=32, end_ridge=35, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0020",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 32, 'end_ridge': 35, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=36, end_ridge=39, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0021",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 36, 'end_ridge': 39, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=40, end_ridge=43, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0022",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 40, 'end_ridge': 43, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=44, end_ridge=47, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0023",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 44, 'end_ridge': 47, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=48, end_ridge=51, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0024",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 48, 'end_ridge': 51, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=52, end_ridge=55, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0025",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 52, 'end_ridge': 55, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=56, end_ridge=59, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0026",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 56, 'end_ridge': 59, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=60, end_ridge=63, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0027",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 60, 'end_ridge': 63, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].commit_daily_physics(),
                "step0028",
                "执行公开工具 FarmWorldApp__commit_daily_physics；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1194558.0),
                "step0029",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1194558.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0030",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0031",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].apply_fertigation(
                    start_ridge=0, end_ridge=63, nutrient_amount=0.078125, water_mm=0.0
                ),
                "step0032",
                "执行公开工具 FarmWorldApp__apply_fertigation；参数 {'start_ridge': 0, 'end_ridge': 63, 'nutrient_amount': 0.078125, 'water_mm': 0.0}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=5),
                "step0033",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 5}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0034",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0035",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0036",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FieldOpsApp"].irrigate(start=0, end=63, hours=7.5),
                "step0037",
                "执行公开工具 FieldOpsApp__irrigate；参数 {'start': 0, 'end': 63, 'hours': 7.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=836700.0),
                "step0038",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 836700.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0039",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0040",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].apply_fertigation(
                    start_ridge=0, end_ridge=63, nutrient_amount=0.078125, water_mm=0.0
                ),
                "step0041",
                "执行公开工具 FarmWorldApp__apply_fertigation；参数 {'start_ridge': 0, 'end_ridge': 63, 'nutrient_amount': 0.078125, 'water_mm': 0.0}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=30),
                "step0042",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 30}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0043",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0044",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0045",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FieldOpsApp"].irrigate(start=0, end=63, hours=7.5),
                "step0046",
                "执行公开工具 FieldOpsApp__irrigate；参数 {'start': 0, 'end': 63, 'hours': 7.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=836700.0),
                "step0047",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 836700.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0048",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0049",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0050",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FieldOpsApp"].irrigate(start=0, end=63, hours=7.5),
                "step0051",
                "执行公开工具 FieldOpsApp__irrigate；参数 {'start': 0, 'end': 63, 'hours': 7.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=836700.0),
                "step0052",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 836700.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0053",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0054",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0055",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FieldOpsApp"].irrigate(start=0, end=63, hours=7.5),
                "step0056",
                "执行公开工具 FieldOpsApp__irrigate；参数 {'start': 0, 'end': 63, 'hours': 7.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1614300.0),
                "step0057",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1614300.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0058",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0059",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0060",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0061",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0062",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0063",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0064",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0065",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0066",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0067",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0068",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0069",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0070",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0071",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].refuel(liters=100.0),
                "step0072",
                "执行公开工具 TractorApp__refuel；参数 {'liters': 100.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=0, end_ridge=3),
                "step0073",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 0, 'end_ridge': 3}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0074",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=4, end_ridge=7),
                "step0075",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 4, 'end_ridge': 7}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0076",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=8, end_ridge=11),
                "step0077",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 8, 'end_ridge': 11}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0078",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=12, end_ridge=15),
                "step0079",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 12, 'end_ridge': 15}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0080",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=16, end_ridge=19),
                "step0081",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 16, 'end_ridge': 19}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0082",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=20, end_ridge=23),
                "step0083",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 20, 'end_ridge': 23}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0084",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=24, end_ridge=27),
                "step0085",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 24, 'end_ridge': 27}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0086",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=28, end_ridge=31),
                "step0087",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 28, 'end_ridge': 31}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0088",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=32, end_ridge=35),
                "step0089",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 32, 'end_ridge': 35}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0090",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=36, end_ridge=39),
                "step0091",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 36, 'end_ridge': 39}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0092",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=40, end_ridge=43),
                "step0093",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 40, 'end_ridge': 43}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0094",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=44, end_ridge=47),
                "step0095",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 44, 'end_ridge': 47}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0096",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=48, end_ridge=51),
                "step0097",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 48, 'end_ridge': 51}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0098",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=52, end_ridge=55),
                "step0099",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 52, 'end_ridge': 55}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0100",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=56, end_ridge=59),
                "step0101",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 56, 'end_ridge': 59}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0102",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=60, end_ridge=63),
                "step0103",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 60, 'end_ridge': 63}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0104",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].dry_grain(target_moisture_pct=14.0),
                "step0105",
                "执行公开工具 FarmWorldApp__dry_grain；参数 {'target_moisture_pct': 14.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].store_grain(),
                "step0106",
                "执行公开工具 FarmWorldApp__store_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SeasonCycle"].close_season(year=2026),
                "step0107",
                "执行公开工具 SeasonCycle__close_season；参数 {'year': 2026}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=22624784.0),
                "step0108",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 22624784.0}",
            )
            previous = capture_step(
                previous,
                apps["SeasonCycle"].open_next_season(year=2027),
                "step0109",
                "执行公开工具 SeasonCycle__open_next_season；参数 {'year': 2027}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0110",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_inventory(),
                "step0111",
                "执行公开工具 FarmWorldApp__get_inventory；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].attach_implement(implement="grader"),
                "step0112",
                "执行公开工具 TractorApp__attach_implement；参数 {'implement': 'grader'}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].level(),
                "step0113",
                "执行公开工具 TractorApp__level；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].detach_implement(),
                "step0114",
                "执行公开工具 TractorApp__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].load_fertilizer(kg=200.0),
                "step0115",
                "执行公开工具 TractorApp__load_fertilizer；参数 {'kg': 200.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].base_fertilize(total_kg=200.0),
                "step0116",
                "执行公开工具 TractorApp__base_fertilize；参数 {'total_kg': 200.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].attach_implement(implement="furrower"),
                "step0117",
                "执行公开工具 TractorApp__attach_implement；参数 {'implement': 'furrower'}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].form_ridges(ridge_width_m=0.75),
                "step0118",
                "执行公开工具 TractorApp__form_ridges；参数 {'ridge_width_m': 0.75}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].detach_implement(),
                "step0119",
                "执行公开工具 TractorApp__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].load_seeds(seed_type="MAIZE_201", count=85760),
                "step0120",
                "执行公开工具 TractorApp__load_seeds；参数 {'seed_type': 'MAIZE_201', 'count': 85760}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=0, end_ridge=3, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0121",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 0, 'end_ridge': 3, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=4, end_ridge=7, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0122",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 4, 'end_ridge': 7, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=8, end_ridge=11, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0123",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 8, 'end_ridge': 11, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=12, end_ridge=15, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0124",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 12, 'end_ridge': 15, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=16, end_ridge=19, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0125",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 16, 'end_ridge': 19, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=20, end_ridge=23, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0126",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 20, 'end_ridge': 23, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=24, end_ridge=27, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0127",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 24, 'end_ridge': 27, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=28, end_ridge=31, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0128",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 28, 'end_ridge': 31, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=32, end_ridge=35, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0129",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 32, 'end_ridge': 35, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=36, end_ridge=39, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0130",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 36, 'end_ridge': 39, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=40, end_ridge=43, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0131",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 40, 'end_ridge': 43, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=44, end_ridge=47, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0132",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 44, 'end_ridge': 47, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=48, end_ridge=51, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0133",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 48, 'end_ridge': 51, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=52, end_ridge=55, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0134",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 52, 'end_ridge': 55, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=56, end_ridge=59, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0135",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 56, 'end_ridge': 59, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=60, end_ridge=63, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0136",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 60, 'end_ridge': 63, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].commit_daily_physics(),
                "step0137",
                "执行公开工具 FarmWorldApp__commit_daily_physics；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1194558.0),
                "step0138",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1194558.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0139",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0140",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].apply_fertigation(
                    start_ridge=0,
                    end_ridge=63,
                    nutrient_amount=0.13020833333333334,
                    water_mm=0.0,
                ),
                "step0141",
                "执行公开工具 FarmWorldApp__apply_fertigation；参数 {'start_ridge': 0, 'end_ridge': 63, 'nutrient_amount': 0.13020833333333334, 'water_mm': 0.0}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=5),
                "step0142",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 5}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0143",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0144",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0145",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=10),
                "step0146",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 10}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0147",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0148",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].apply_fertigation(
                    start_ridge=0,
                    end_ridge=63,
                    nutrient_amount=0.13020833333333334,
                    water_mm=0.0,
                ),
                "step0149",
                "执行公开工具 FarmWorldApp__apply_fertigation；参数 {'start_ridge': 0, 'end_ridge': 63, 'nutrient_amount': 0.13020833333333334, 'water_mm': 0.0}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=30),
                "step0150",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 30}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0151",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0152",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0153",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FieldOpsApp"].irrigate(start=0, end=63, hours=12.5),
                "step0154",
                "执行公开工具 FieldOpsApp__irrigate；参数 {'start': 0, 'end': 63, 'hours': 12.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=818700.0),
                "step0155",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 818700.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0156",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0157",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0158",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FieldOpsApp"].irrigate(start=0, end=63, hours=12.5),
                "step0159",
                "执行公开工具 FieldOpsApp__irrigate；参数 {'start': 0, 'end': 63, 'hours': 12.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=818700.0),
                "step0160",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 818700.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0161",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0162",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0163",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=19),
                "step0164",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 19}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0165",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0166",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0167",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0168",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0169",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0170",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0171",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0172",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0173",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0174",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0175",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0176",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0177",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0178",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0179",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0180",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0181",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0182",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0183",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0184",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0185",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0186",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0187",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0188",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0189",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0190",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0191",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0192",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0193",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0194",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0195",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0196",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0197",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0198",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0199",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0200",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0201",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0202",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0203",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0204",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0205",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0206",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0207",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0208",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0209",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0210",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0211",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0212",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0213",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0214",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0215",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0216",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0217",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0218",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0219",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0220",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0221",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0222",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0223",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(days=1),
                "step0224",
                "执行公开工具 SystemApp__advance_time；参数 {'days': 1}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
                "step0225",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 63}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0226",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].refuel(liters=100.0),
                "step0227",
                "执行公开工具 TractorApp__refuel；参数 {'liters': 100.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=0, end_ridge=3),
                "step0228",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 0, 'end_ridge': 3}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0229",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=4, end_ridge=7),
                "step0230",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 4, 'end_ridge': 7}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0231",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=8, end_ridge=11),
                "step0232",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 8, 'end_ridge': 11}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0233",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=12, end_ridge=15),
                "step0234",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 12, 'end_ridge': 15}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0235",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=16, end_ridge=19),
                "step0236",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 16, 'end_ridge': 19}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0237",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=20, end_ridge=23),
                "step0238",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 20, 'end_ridge': 23}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0239",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=24, end_ridge=27),
                "step0240",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 24, 'end_ridge': 27}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0241",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=28, end_ridge=31),
                "step0242",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 28, 'end_ridge': 31}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0243",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=32, end_ridge=35),
                "step0244",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 32, 'end_ridge': 35}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0245",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=36, end_ridge=39),
                "step0246",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 36, 'end_ridge': 39}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0247",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=40, end_ridge=43),
                "step0248",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 40, 'end_ridge': 43}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0249",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=44, end_ridge=47),
                "step0250",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 44, 'end_ridge': 47}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0251",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=48, end_ridge=51),
                "step0252",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 48, 'end_ridge': 51}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0253",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=52, end_ridge=55),
                "step0254",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 52, 'end_ridge': 55}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0255",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=56, end_ridge=59),
                "step0256",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 56, 'end_ridge': 59}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0257",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=60, end_ridge=63),
                "step0258",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 60, 'end_ridge': 63}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0259",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].dry_grain(target_moisture_pct=14.0),
                "step0260",
                "执行公开工具 FarmWorldApp__dry_grain；参数 {'target_moisture_pct': 14.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].store_grain(),
                "step0261",
                "执行公开工具 FarmWorldApp__store_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SeasonCycle"].close_season(year=2027),
                "step0262",
                "执行公开工具 SeasonCycle__close_season；参数 {'year': 2027}",
            )
        return finish_capture(self, events)
