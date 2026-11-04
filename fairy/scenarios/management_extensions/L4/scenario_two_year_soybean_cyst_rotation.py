"""L4：跨年大豆胞囊线虫种群与玉米非寄主轮作；官方作物参数，同一地块连续土壤。"""

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
from fairy.scenarios.management_extensions.apps.crop_rotation_app import CropRotationApp
from fairy.scenarios.management_extensions.apps.scn_monitoring_app import (
    ScnRotationFarm,
)
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.types import EventRegisterer

from ..apps.scn_monitoring_app import ScnMonitoring
from ..apps.season_cycle_app import AnnualCropSeason
from ..china_market_prices import operating_prices
from ..evaluation.oracle_comparison import compare_to_oracle
from ..common import capture_step, finish_capture
from ..engines.soybean_cyst_nematode import ScnParameters, SoybeanCystNematodeBackend
from ..oracle_management_plans import manage_scn_rotation


class ScenarioTwoYearSoybeanCystRotation(Scenario):
    scenario_id = "scenario_l4_two_year_soybean_cyst_rotation"
    level = "L4"
    objective_metric = "net_operating_margin"
    oracle_policy = staticmethod(manage_scn_rotation)
    timezone_name = "Asia/Shanghai"
    field: ClassVar = {
        "farm_id": "field",
        "crop_id": "soybean",
        "seed_type": "SOYBEAN_901",
        "ridge_count": 16,
        "ridge_width_m": 0.75,
        "field_length_m": 268.0,
    }
    seasons: ClassVar = tuple(
        AnnualCropSeason(date(y, 5, 5), date(y, 10, 31), 200.0, 300.0)
        for y in (2024, 2025)
    )
    backend_options: ClassVar = {
        "crop_name": "soybean",
        "variety_name": "Soybean_901",
        "reference_density_plants_m2": 40.0,
        "cultivar_map": {"SOYBEAN_901": "Soybean_901"},
        "external_biotic_coupling": False,
        "latitude_deg": 43.9,
        "initial_available_n_kg_ha": 50.0,
        "base_soil_n_kg_ha": 50.0,
        "soil_n_mineralization_fraction": 0.002,
    }
    crop_configurations: ClassVar[dict] = {
        "soybean": backend_options,
        "maize": {
            **backend_options,
            "crop_name": "maize",
            "variety_name": "Grain_maize_201",
            "cultivar_map": {"MAIZE_201": "Grain_maize_201"},
            "reference_density_plants_m2": 20 / 3,
        },
    }
    prices: ClassVar = operating_prices(high_water=False)
    fertilizer_budget_kg: ClassVar = 90.0
    water_budget_mm: ClassVar = 400.0
    seed_count: ClassVar = 100000
    initial_fuel_liters: ClassVar = 1000.0
    initial_machine_fuel_liters: ClassVar = 100.0
    storage_capacity_kg: ClassVar = 50000.0
    drying_capacity_kg_per_day: ClassVar = 20000.0
    safe_moisture_pct: ClassVar = 13.0
    maximum_harvest_moisture_pct: ClassVar = 18
    initial_soil_vwc: ClassVar = 0.28
    initial_soil_temperature_c: ClassVar = 16
    weather_seed: ClassVar = 101
    horizon_days: ClassVar = 550
    observation_seeds: ClassVar[dict] = {
        "AgentUserInterface": 3729385368,
        "FarmWorldApp": 1281893346,
        "FieldOpsApp": 3100517573,
        "Mavic3M": 695188145,
        "Robot0": 3339168823,
        "CropRotation": 4128923743,
        "ScnMonitoring": 291793182,
        "SensorApp": 1025542706,
        "SystemApp": 2196534512,
        "TractorApp": 2773417723,
        "WeatherApp": 433245120,
    }
    scn_parameters: ClassVar[dict] = asdict(ScnParameters())
    ORACLE_REFERENCE: ClassVar[dict] = {
        "scenario_id": "scenario_l4_two_year_soybean_cyst_rotation",
        "input_fingerprint": "76586b787be0931c87b70c560e45060086f6f23e0237eb99da35453279de4786",
        "selected": {
            "currency": "USD",
            "price_book_id": "china_northeast_2025_usd_v1",
            "cny_per_usd": 7.1757,
            "stored_kg_by_crop": {"soybean": 0.0, "maize": 6132.08},
            "grain_value": 1845.8537564279443,
            "production_cost": 231.01168656818984,
            "net_operating_margin": 1614.8420698597545,
            "seasons": [
                {
                    "year": 2024,
                    "stored_grain_kg": 3140.08,
                    "crop_id": "maize",
                    "biological_grain_kg": 2783.985790922705,
                    "recovered_grain_kg": 3140.076996738397,
                },
                {
                    "year": 2025,
                    "stored_grain_kg": 2992.0,
                    "crop_id": "maize",
                    "biological_grain_kg": 2652.7055249365353,
                    "recovered_grain_kg": 2992.005068823768,
                },
            ],
        },
        "workflow_steps": 201,
        "candidate_count": 7,
        "feasible_count": 7,
        "scope": "Best feasible candidate among 7 freshly executed USD management candidates, including "
        "the prior literal workflow, a short-list ranked from archived physical receipts, and "
        "explicit crop/water/fertilizer/protection controls. Crop biology, weather and physical "
        "caps unchanged. No claim of global optimum; archived revaluations are rankings, not "
        "fresh execution.",
        "calibration_artifact": "validation_runs/management_usd_china_2025_20261103_220138/newer/scenario_l4_two_year_soybean_cyst_rotation/calibration_reference.json",
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
            (expected.get(k) != v for k, v in requested.items())
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
        task = "在面积3216m²、垄距0.75m的同一农田跨年经营两个种植季，可自主选择玉米或大豆。结合连续土壤状态、模拟大豆孢囊线虫种群及经营成本完成两季成熟收储，尽量提高净收益。作物、年度计划和价格查 CropRotation.get_crop_options，种群通过 ScnMonitoring.sample_soil 查询，其他参数通过对应工具查询。"
        if not detailed:
            return task
        guidance = textwrap.dedent(
            """\
            管理指导：

            种群与选作物：播前 sample_soil 核对各覆盖区种群及模型假设，再结合宿主关系、历史作物、价格、库存和当前土壤条件比较方案。大豆为寄主、玉米为非寄主，具体种群变化来自本场声明的模拟系数，不是实地化验或已标定预测；不能仅凭轮作名称保证更高利润。

            建植与营养：按选择工具前提确定首季作物，再查询其能力并完成全田整地播种。结合 SensorApp.read_canopy_sensors、地块阶段、施肥记录及根区工具返回的有效土壤氮估计排查异常；氮估计先核对日期和覆盖。冠层偏弱须同时排查水分、种群风险及自然阶段，不能直接以施肥替代病害判断。

            水肥处理与复查：用 read_root_zone_sensors、read_soil_sensors 和近期预报辨别持续干燥，必要时在共享和当季余额内分次供水，生效后复读同区探头。只有持续营养异常有依据且仍可有效吸收时考虑追肥，按产品单位、面积及库存核算并复查；没有独立养分化验，代理值不是精确处方。

            结季采样与跨年：实际成熟、安全收储后 close_season，再 sample_soil 并记录种群、土壤和物资余额。保持相同地块连续过冬，到计划允许的时间用当前采样、历史记录和经营条件重新比较次季作物；换作物前先退回不匹配的种子，再 open_next_crop。

            经营复核：次季同样根据观测管理并完成收储和结季，分作物、分季报告粮批、种群变化、消耗及净收益。不能重新初始化种群或土壤，不把作物售价和投入差造成的利润变化全部归因于线虫作用。

            """
        ).strip()
        return task + "\n\n" + guidance

    def init_and_populate_apps(self):
        farm = ScnRotationFarm(
            crop_type=self.field["crop_id"],
            num_ridges=self.field["ridge_count"],
            field_length_m=self.field["field_length_m"],
            ridge_width_m=self.field["ridge_width_m"],
            required_field_preparation_ops=("level", "form_ridges"),
        )
        install_common_farm_apps(self, thermal=False, field_ops=True, farm_world=farm)
        farm.configure_crop_backend("wofost", **self.backend_options)
        farm.physics.crop_backend = SoybeanCystNematodeBackend(
            self.backend_options, scn_parameters=ScnParameters(**self.scn_parameters)
        )
        farm.physics.crop_backend.bind_physics(farm.physics)
        farm.set_season_phase("full_season")
        tractor = self.get_typed_app(TractorApp)
        farm._inventory.seed_stock = {"MAIZE_201": 100000, "SOYBEAN_901": 300000}
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
            location="Synthetic temperate farm climate; not locally calibrated",
            latitude_deg=43.9,
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
            "multi_year_adapter": "crop_rotation_v1",
            "cross_species_rotation": True,
            "residue_n_credit": False,
            "winter_limitations": "no additional snow/frozen-soil process; uncalibrated continuous CWB/CNB experiment",
        }
        # Explicit synthetic RH forcing is required by soybean grain moisture;
        # the generic weather generator otherwise has no humidity observations.
        from datetime import timedelta

        from fairy.apps.farm_world.physics_orchestrator import (
            _build_weather_inputs,
            _generate_weather_day,
        )

        for offset in range(self.horizon_days + 8):
            day = self.seasons[0].sowing_date + timedelta(days=offset)
            generated = _generate_weather_day(
                farm.physics.weather_generator, day, farm.physics.profile.weather_events
            )
            farm.physics.weather_generator.set_day_override(
                day=day,
                air_temp_mean_c=generated.air_temp_mean_c,
                air_temp_min_c=generated.air_temp_min_c,
                air_temp_max_c=generated.air_temp_max_c,
                rain_mm=generated.rain_mm,
                wind_ms=generated.wind_ms,
                solar_rad_mj_m2=generated.solar_rad_mj_m2,
                relative_humidity_pct=65.0,
                weather_tags=list(generated.weather_tags),
            )
        farm.physics.scenario_metadata["humidity_forcing"] = {
            "source": "declared synthetic constant, not a measured station series",
            "relative_humidity_pct": 65.0,
        }

        _build_weather_inputs(
            weather,
            self.seasons[0].sowing_date,
            physics=farm.physics,
            advance_weather=False,
        )
        self.cycle = CropRotationApp(
            farm,
            tractor,
            seasons=self.seasons,
            fertilizer_budget_kg=self.fertilizer_budget_kg,
            water_budget_mm=self.water_budget_mm,
            crop_configurations=self.crop_configurations,
            prices=self.prices,
            first_crop_locked=False,
            initial_inventory={
                **deepcopy(farm._inventory.to_dict()),
                "machine_fuel_liters": tractor._fuel_tank_l,
            },
        )
        self.scn = ScnMonitoring(farm)
        self.apps.extend([self.cycle, self.scn])
        farm.physics.scenario_metadata["scn_overlay"] = (
            farm.physics.crop_backend.snapshot()["provenance"]["scn_overlay"]
        )
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
        self._initial_signature = {
            "schema": 1,
            "first_crop_locked": False,
            "scenario_id": self.scenario_id,
            "field": deepcopy(self.field),
            "seasons": [asdict(s) for s in self.seasons],
            "crop_configurations": deepcopy(self.crop_configurations),
            "prices": deepcopy(self.prices),
            "initial_inventory": deepcopy(self._initial_inventory),
            "initial_machine_fuel_liters": self.initial_machine_fuel_liters,
            "start_time": self.start_time,
            "duration": self.duration,
            "soil_parameters": asdict(farm.physics.soil.params),
            "initial_native_configuration": asdict(farm.physics.crop_backend.config),
            "weather_profile": asdict(farm.physics.profile),
            "weather_generator": asdict(farm.physics.weather_generator.config),
            "observation_seeds": deepcopy(self.observation_seeds),
            "fertilizer_budget_kg": self.fertilizer_budget_kg,
            "water_budget_mm": self.water_budget_mm,
            "field_preparation": list(farm.required_field_preparation_ops),
            "metadata": deepcopy(farm.physics.scenario_metadata),
        }
        self._initial_signature["schema"] = 2
        self._initial_signature["postharvest_market"] = deepcopy(
            farm._postharvest_market.to_dict()
        )
        self._initial_signature["tractor_configuration"] = {
            "equipment": asdict(tractor.equipment),
            "harvest_moisture_limit_pct": tractor._harvest_moisture_limit_pct,
            "harvest_limit_configured": tractor._harvest_limit_configured,
        }
        self._initial_signature["initial_soil_states"] = {
            str(k): asdict(v) for k, v in farm.physics.soil.states.items()
        }

    def validate(self, env=None):
        farm = self.get_typed_app(FarmWorldApp)
        tractor = self.get_typed_app(TractorApp)
        backend = farm.physics.crop_backend
        failures = []
        if [r["year"] for r in self.cycle.closed] != [s.year for s in self.seasons]:
            failures.append(
                "Every planned season must be actually harvested and safely stored"
            )
        if farm.time_manager.time() > self.start_time + self.duration:
            failures.append("Episode deadline exceeded")
        if (
            abs(
                sum(b["quantity_kg"] for b in farm.stored_batches)
                - farm._inventory.warehouse_grain_kg
            )
            > 1e-07
        ):
            failures.append("Crop-specific warehouse material balance failed")
        if len(backend.season_history) != farm.num_ridges * (len(self.seasons) - 1):
            failures.append("Native crop transitions incomplete")
        if any(r["soil_before"] != r["soil_after"] for r in backend.season_history):
            failures.append("Rotation reset the native soil")
        regime = farm._management_regime
        if (
            regime.fertilizer_used_kg > self.fertilizer_budget_kg + 1e-07
            or regime.irrigation_used_mm_total > self.water_budget_mm + 1e-07
        ):
            failures.append("Whole-horizon resource budget exceeded")
        if (
            abs(
                farm._inventory.fertilizer_kg
                + tractor._fertilizer_spreader_kg
                + regime.fertilizer_used_kg
                - self.fertilizer_budget_kg
            )
            > 1e-06
        ):
            failures.append("Fertilizer material balance failed")
        if tractor._grain_bin_kg or farm._inventory.harvest_grain_kg:
            failures.append("Unstored harvested grain remains")
        account = self.cycle.compute_accounts()
        reference = self.get_oracle_reference()
        if reference and (not self.calibrating):
            if reference["input_fingerprint"] != self.input_fingerprint():
                failures.append("Reference inputs differ")
            account["reference_best_margin"] = reference["selected"][
                "net_operating_margin"
            ]
            account["margin_regret"] = (
                account["reference_best_margin"] - account["net_operating_margin"]
            )
            if reference["input_fingerprint"] == self.input_fingerprint():
                compare_to_oracle(
                    account,
                    reference["selected"],
                    agent_seasons=self.cycle.yield_seasons(),
                    oracle_seasons=reference["selected"].get("seasons", ()),
                )
        return ScenarioValidationResult(
            success=not failures,
            message="; ".join(failures)
            or "Annual crop choices safely stored with conserved soil and crop-specific accounts",
            metadata={
                **account,
                "feasible": not failures,
                "seasons": deepcopy(self.cycle.closed),
                "native_provenance": backend.snapshot()["provenance"],
            },
        )

    def input_signature(self):
        return deepcopy(self._initial_signature)

    def get_oracle_reference(self):
        """A derived scene cannot silently inherit another scenario's benchmark."""
        reference = getattr(self, "ORACLE_REFERENCE", None)
        if reference and reference["scenario_id"] == self.scenario_id:
            return reference
        return None

    def input_fingerprint(self):
        normalized = json.loads(json.dumps(self.input_signature(), default=str))
        return hashlib.sha256(
            json.dumps(normalized, sort_keys=True).encode()
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
            "app_states": {a.name: a.get_state() for a in self.apps},
            "rng_states": {a.name: a.rng.getstate() for a in self.apps},
        }

    def build_events_flow(self):
        if not self.prepare_oracle_capture():
            return []
        apps = {app.name: app for app in self.apps}
        with EventRegisterer.capture_mode() as events:
            previous = None
            previous = capture_step(
                previous,
                apps["ScnMonitoring"].sample_soil(),
                "step0000",
                "执行公开工具 ScnMonitoring__sample_soil；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropRotation"].select_first_crop(crop_id="maize"),
                "step0001",
                "执行公开工具 CropRotation__select_first_crop；参数 {'crop_id': 'maize'}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0002",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0003",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_inventory(),
                "step0004",
                "执行公开工具 FarmWorldApp__get_inventory；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_crop_capabilities(),
                "step0005",
                "执行公开工具 FarmWorldApp__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0006",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].attach_implement(implement="grader"),
                "step0007",
                "执行公开工具 TractorApp__attach_implement；参数 {'implement': 'grader'}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].level(),
                "step0008",
                "执行公开工具 TractorApp__level；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].detach_implement(),
                "step0009",
                "执行公开工具 TractorApp__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].load_fertilizer(kg=45.0),
                "step0010",
                "执行公开工具 TractorApp__load_fertilizer；参数 {'kg': 45.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].base_fertilize(total_kg=45.0),
                "step0011",
                "执行公开工具 TractorApp__base_fertilize；参数 {'total_kg': 45.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].attach_implement(implement="furrower"),
                "step0012",
                "执行公开工具 TractorApp__attach_implement；参数 {'implement': 'furrower'}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].form_ridges(ridge_width_m=0.75),
                "step0013",
                "执行公开工具 TractorApp__form_ridges；参数 {'ridge_width_m': 0.75}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].detach_implement(),
                "step0014",
                "执行公开工具 TractorApp__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].load_seeds(seed_type="MAIZE_201", count=21440),
                "step0015",
                "执行公开工具 TractorApp__load_seeds；参数 {'seed_type': 'MAIZE_201', 'count': 21440}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=0, end_ridge=3, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0016",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 0, 'end_ridge': 3, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=4, end_ridge=7, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0017",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 4, 'end_ridge': 7, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=8, end_ridge=11, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0018",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 8, 'end_ridge': 11, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=12, end_ridge=15, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0019",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 12, 'end_ridge': 15, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].commit_daily_physics(),
                "step0020",
                "执行公开工具 FarmWorldApp__commit_daily_physics；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1205841.0),
                "step0021",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1205841.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0022",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0023",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=432000.0),
                "step0024",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 432000.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0025",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0026",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0027",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FieldOpsApp"].irrigate(start=0, end=15, hours=7.5),
                "step0028",
                "执行公开工具 FieldOpsApp__irrigate；参数 {'start': 0, 'end': 15, 'hours': 7.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=836700.0),
                "step0029",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 836700.0}",
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
                apps["SystemApp"].advance_time(seconds=2592000.0),
                "step0032",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 2592000.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0033",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0034",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0035",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=864000.0),
                "step0036",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 864000.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0037",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0038",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0039",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FieldOpsApp"].irrigate(start=0, end=15, hours=7.5),
                "step0040",
                "执行公开工具 FieldOpsApp__irrigate；参数 {'start': 0, 'end': 15, 'hours': 7.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=836700.0),
                "step0041",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 836700.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0042",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0043",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0044",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FieldOpsApp"].irrigate(start=0, end=15, hours=7.5),
                "step0045",
                "执行公开工具 FieldOpsApp__irrigate；参数 {'start': 0, 'end': 15, 'hours': 7.5}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_crop_capabilities(),
                "step0046",
                "执行公开工具 FarmWorldApp__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1614300.0),
                "step0047",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1614300.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0048",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0049",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0050",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0051",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0052",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0053",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0054",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0055",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0056",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0057",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0058",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0059",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0060",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0061",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].refuel(liters=100.0),
                "step0062",
                "执行公开工具 TractorApp__refuel；参数 {'liters': 100.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=0, end_ridge=3),
                "step0063",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 0, 'end_ridge': 3}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0064",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=4, end_ridge=7),
                "step0065",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 4, 'end_ridge': 7}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0066",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=8, end_ridge=11),
                "step0067",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 8, 'end_ridge': 11}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0068",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=12, end_ridge=15),
                "step0069",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 12, 'end_ridge': 15}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0070",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].dry_grain(target_moisture_pct=14.0),
                "step0071",
                "执行公开工具 FarmWorldApp__dry_grain；参数 {'target_moisture_pct': 14.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].store_grain(),
                "step0072",
                "执行公开工具 FarmWorldApp__store_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropRotation"].close_season(year=2024),
                "step0073",
                "执行公开工具 CropRotation__close_season；参数 {'year': 2024}",
            )
            previous = capture_step(
                previous,
                apps["ScnMonitoring"].sample_soil(),
                "step0074",
                "执行公开工具 ScnMonitoring__sample_soil；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=22633796.0),
                "step0075",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 22633796.0}",
            )
            previous = capture_step(
                previous,
                apps["CropRotation"].get_crop_options(),
                "step0076",
                "执行公开工具 CropRotation__get_crop_options；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropRotation"].get_season_ledger(),
                "step0077",
                "执行公开工具 CropRotation__get_season_ledger；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropRotation"].open_next_crop(year=2025, crop_id="maize"),
                "step0078",
                "执行公开工具 CropRotation__open_next_crop；参数 {'year': 2025, 'crop_id': 'maize'}",
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
                apps["FarmWorldApp"].get_inventory(),
                "step0081",
                "执行公开工具 FarmWorldApp__get_inventory；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_crop_capabilities(),
                "step0082",
                "执行公开工具 FarmWorldApp__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0083",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].attach_implement(implement="grader"),
                "step0084",
                "执行公开工具 TractorApp__attach_implement；参数 {'implement': 'grader'}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].level(),
                "step0085",
                "执行公开工具 TractorApp__level；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].detach_implement(),
                "step0086",
                "执行公开工具 TractorApp__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].load_fertilizer(kg=45.0),
                "step0087",
                "执行公开工具 TractorApp__load_fertilizer；参数 {'kg': 45.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].base_fertilize(total_kg=45.0),
                "step0088",
                "执行公开工具 TractorApp__base_fertilize；参数 {'total_kg': 45.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].attach_implement(implement="furrower"),
                "step0089",
                "执行公开工具 TractorApp__attach_implement；参数 {'implement': 'furrower'}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].form_ridges(ridge_width_m=0.75),
                "step0090",
                "执行公开工具 TractorApp__form_ridges；参数 {'ridge_width_m': 0.75}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].detach_implement(),
                "step0091",
                "执行公开工具 TractorApp__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].load_seeds(seed_type="MAIZE_201", count=21440),
                "step0092",
                "执行公开工具 TractorApp__load_seeds；参数 {'seed_type': 'MAIZE_201', 'count': 21440}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=0, end_ridge=3, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0093",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 0, 'end_ridge': 3, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=4, end_ridge=7, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0094",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 4, 'end_ridge': 7, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=8, end_ridge=11, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0095",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 8, 'end_ridge': 11, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=12, end_ridge=15, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0096",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 12, 'end_ridge': 15, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].commit_daily_physics(),
                "step0097",
                "执行公开工具 FarmWorldApp__commit_daily_physics；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1205841.0),
                "step0098",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1205841.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0099",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0100",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=432000.0),
                "step0101",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 432000.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0102",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0103",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0104",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=864000.0),
                "step0105",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 864000.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0106",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0107",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=2592000.0),
                "step0108",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 2592000.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0109",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0110",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0111",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FieldOpsApp"].irrigate(start=0, end=15, hours=7.5),
                "step0112",
                "执行公开工具 FieldOpsApp__irrigate；参数 {'start': 0, 'end': 15, 'hours': 7.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=836700.0),
                "step0113",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 836700.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0114",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0115",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0116",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FieldOpsApp"].irrigate(start=0, end=15, hours=7.5),
                "step0117",
                "执行公开工具 FieldOpsApp__irrigate；参数 {'start': 0, 'end': 15, 'hours': 7.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=836700.0),
                "step0118",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 836700.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0119",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0120",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0121",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FieldOpsApp"].irrigate(start=0, end=15, hours=7.5),
                "step0122",
                "执行公开工具 FieldOpsApp__irrigate；参数 {'start': 0, 'end': 15, 'hours': 7.5}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_crop_capabilities(),
                "step0123",
                "执行公开工具 FarmWorldApp__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1614300.0),
                "step0124",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1614300.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0125",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0126",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0127",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0128",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0129",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0130",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0131",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0132",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0133",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0134",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0135",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0136",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0137",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0138",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0139",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0140",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0141",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0142",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0143",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0144",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0145",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0146",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0147",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0148",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0149",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0150",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0151",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0152",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0153",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0154",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0155",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0156",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0157",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0158",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0159",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0160",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0161",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0162",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0163",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0164",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0165",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0166",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0167",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0168",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0169",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0170",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0171",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0172",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0173",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0174",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0175",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0176",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0177",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0178",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0179",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0180",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0181",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0182",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0183",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0184",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0185",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0186",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].refuel(liters=100.0),
                "step0187",
                "执行公开工具 TractorApp__refuel；参数 {'liters': 100.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=0, end_ridge=3),
                "step0188",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 0, 'end_ridge': 3}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0189",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=4, end_ridge=7),
                "step0190",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 4, 'end_ridge': 7}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0191",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=8, end_ridge=11),
                "step0192",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 8, 'end_ridge': 11}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0193",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=12, end_ridge=15),
                "step0194",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 12, 'end_ridge': 15}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0195",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].dry_grain(target_moisture_pct=14.0),
                "step0196",
                "执行公开工具 FarmWorldApp__dry_grain；参数 {'target_moisture_pct': 14.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].store_grain(),
                "step0197",
                "执行公开工具 FarmWorldApp__store_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropRotation"].close_season(year=2025),
                "step0198",
                "执行公开工具 CropRotation__close_season；参数 {'year': 2025}",
            )
            previous = capture_step(
                previous,
                apps["ScnMonitoring"].sample_soil(),
                "step0199",
                "执行公开工具 ScnMonitoring__sample_soil；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropRotation"].get_accounts(),
                "step0200",
                "执行公开工具 CropRotation__get_accounts；参数 {}",
            )
        return finish_capture(self, events)
