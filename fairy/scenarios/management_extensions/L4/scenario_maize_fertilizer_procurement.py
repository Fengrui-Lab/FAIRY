"""L4：同田两年玉米的跨年肥料采购与现金备货决策；每一步均使用真实库存和原生作物过程。"""

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
from fairy.scenarios.management_extensions.apps.crop_rotation_farm_app import (
    CropRotationFarm,
)
from fairy.scenarios.management_extensions.apps.fertilizer_market_app import (
    FertilizerMarket,
)
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.types import EventRegisterer

from ..apps.season_cycle_app import AnnualCropSeason
from ..china_market_prices import CONTRACTS, operating_prices, usd
from ..evaluation.oracle_comparison import compare_to_oracle
from ..common import capture_step, finish_capture
from ..engines.crop_rotation_wofost import CropRotationBackend
from ..oracle_management_plans import manage_rotating_crops


class ScenarioTwoYearMaizeFertilizerProcurement(Scenario):
    scenario_id = "scenario_l4_maize_fertilizer_procurement"
    level = "L4"
    objective_metric = "net_operating_margin"
    oracle_policy = staticmethod(manage_rotating_crops)
    initial_fertilizer_kg: ClassVar = 125.0
    initial_purchase_cash: ClassVar = usd(CONTRACTS["fertilizer_purchase_cash_cny"])
    fertilizer_offers: ClassVar = (
        {
            "offer_id": "advance_stock",
            "announced_on": "2024-05-01",
            "valid_from": "2024-05-01",
            "valid_until": "2025-04-30",
            "unit_price": usd(CONTRACTS["fertilizer_advance_cny_kg"]),
        },
        {
            "offer_id": "spring_spot",
            "announced_on": "2024-10-01",
            "valid_from": "2025-05-01",
            "valid_until": "2025-10-31",
            "unit_price": usd(CONTRACTS["fertilizer_spring_cny_kg"]),
        },
    )
    timezone_name = "Asia/Shanghai"
    field: ClassVar = {
        "farm_id": "field",
        "crop_id": "maize",
        "seed_type": "MAIZE_201",
        "ridge_count": 16,
        "ridge_width_m": 0.75,
        "field_length_m": 268.0,
    }
    seasons: ClassVar = tuple(
        AnnualCropSeason(date(y, 5, 5), date(y, 10, 31), 200.0, 300.0)
        for y in (2024, 2025)
    )
    backend_options: ClassVar = {
        "crop_name": "maize",
        "variety_name": "Grain_maize_201",
        "reference_density_plants_m2": 20 / 3,
        "cultivar_map": {"MAIZE_201": "Grain_maize_201"},
        "external_biotic_coupling": False,
        "latitude_deg": 43.9,
        "initial_available_n_kg_ha": 50.0,
        "base_soil_n_kg_ha": 50.0,
        "soil_n_mineralization_fraction": 0.002,
    }
    crop_configurations: ClassVar[dict] = {"maize": backend_options}
    prices: ClassVar = operating_prices(high_water=False)
    fertilizer_budget_kg: ClassVar = 300.0
    water_budget_mm: ClassVar = 400.0
    seed_count: ClassVar = 100000
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
    observation_seeds: ClassVar[dict] = {
        "AgentUserInterface": 3729385368,
        "FarmWorldApp": 1281893346,
        "FieldOpsApp": 3100517573,
        "Mavic3M": 695188145,
        "Robot0": 3339168823,
        "CropRotation": 4128923743,
        "SensorApp": 1025542706,
        "SystemApp": 2196534512,
        "TractorApp": 2773417723,
        "WeatherApp": 433245120,
        "FertilizerMarket": 8836172,
    }
    ORACLE_REFERENCE: ClassVar[dict] = {
        "scenario_id": "scenario_l4_maize_fertilizer_procurement",
        "input_fingerprint": "33bcd3b316eff7a2b7dbaa369890a8e086efb7e4d0601432a11c7764a93a337c",
        "selected": {
            "currency": "USD",
            "price_book_id": "china_northeast_2025_usd_v1",
            "cny_per_usd": 7.1757,
            "stored_kg_by_crop": {"maize": 7351.0},
            "grain_value": 2212.7680923115513,
            "production_cost": 296.48215077377256,
            "net_operating_margin": 1916.2859415377789,
            "seasons": [
                {
                    "year": 2024,
                    "stored_grain_kg": 3496.84,
                    "crop_id": "maize",
                    "biological_grain_kg": 3100.293852065068,
                    "recovered_grain_kg": 3496.843065701296,
                },
                {
                    "year": 2025,
                    "stored_grain_kg": 3854.16,
                    "crop_id": "maize",
                    "biological_grain_kg": 3417.0764597263915,
                    "recovered_grain_kg": 3854.14437899372,
                },
            ],
        },
        "workflow_steps": 213,
        "candidate_count": 8,
        "feasible_count": 8,
        "scope": "Best feasible candidate among 8 freshly executed USD management candidates, including "
        "the prior literal workflow, a short-list ranked from archived physical receipts, and "
        "explicit crop/water/fertilizer/protection controls. Crop biology, weather and physical "
        "caps unchanged. No claim of global optimum; archived revaluations are rankings, not "
        "fresh execution.",
        "calibration_artifact": "validation_runs/management_usd_china_2025_20261103_220138/newer/scenario_l4_maize_fertilizer_procurement/calibration_reference.json",
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
        task = "在面积3216m²、垄距0.75m的同一玉米田连续经营两个日历年的种植季，在有限采购现金及跨季库存下完成成熟收储，尽量提高两季净经营收益。年度计划与基础价格查 CropRotation.get_crop_options，供应合同、有效期和现金查 FertilizerMarket.get_offers；其余资源及作业参数通过对应工具查询。"
        if not detailed:
            return task
        guidance = textwrap.dedent(
            """\
            管理指导：

            统筹与建植：读取 CropRotation.get_season_ledger、作物能力、库存、机上载荷、土壤和天气，比较首季投入与次季备货需要。依据真实需求决定基施及后续保留量，按工具要求完成全田建植，不将采购付款直接视为已施肥。

            水分判断：结合 SensorApp.read_root_zone_sensors、read_soil_sensors、天气预报与作物阶段检查水分。持续偏干且近期降雨不足时在当季和跨季余额内分次供水；待供水生效后复读相同覆盖区。湿润或有可利用降雨时暂缓，灌溉上限不是目标用量。

            营养判断：用 read_canopy_sensors、生育阶段、投入记录及可见营养指标识别持续异常，先排除缺水和自然阶段变化。土壤氮模型估计须核对日期和覆盖，不可用不代表缺氮。结合产品单位、面积和全周期库存考虑基施或分次追肥，等待响应后复查；低 NDVI 不能直接当成测土配方。

            查价与备货：随季节推进重新查 get_offers，比较当时已公布且有效的合同、可支付现金、剩余库存和次季需求。按实际报价计算拟采购量和付款，保留 order_id 并核对收据与仓库增量；未来未公布报价不当作已知，过期报价不可沿用。用 get_purchase_accounts 区分付款、已消耗成本和未用库存资产。

            跨季与结算：每季按实际成熟、水分、天气和容量收储后 close_season。保留真实土壤、存货及现金，到计划允许的时间通过 open_next_crop 接续玉米生产。次季依据实际余额和观测重新安排投入，不假定自动补货；最后分季核对粮批、消耗、采购及净收益。

            """
        ).strip()
        return task + "\n\n" + guidance

    def init_and_populate_apps(self):
        farm = CropRotationFarm(
            crop_type=self.field["crop_id"],
            num_ridges=self.field["ridge_count"],
            field_length_m=self.field["field_length_m"],
            ridge_width_m=self.field["ridge_width_m"],
            required_field_preparation_ops=("level", "form_ridges"),
        )
        install_common_farm_apps(self, thermal=False, field_ops=True, farm_world=farm)
        farm.configure_crop_backend("wofost", **self.backend_options)
        farm.physics.crop_backend = CropRotationBackend(self.backend_options)
        farm.physics.crop_backend.bind_physics(farm.physics)
        farm.set_season_phase("full_season")
        tractor = self.get_typed_app(TractorApp)
        farm._inventory.seed_stock = {"MAIZE_201": 100000}
        farm._inventory.fertilizer_kg = float(self.initial_fertilizer_kg)
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
            initial_inventory={
                **deepcopy(farm._inventory.to_dict()),
                "machine_fuel_liters": tractor._fuel_tank_l,
            },
        )
        self.apps.append(self.cycle)
        self.market = FertilizerMarket(
            farm,
            tractor,
            cash=self.initial_purchase_cash,
            initial_fertilizer_kg=self.initial_fertilizer_kg,
            initial_unit_cost=self.prices["fertilizer_per_kg"],
            offers=self.fertilizer_offers,
        )
        self.apps.append(self.market)
        self.cycle.fertilizer_cost_reader = self.market.consumed_cost
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
            "schema": 2,
            "scenario_id": self.scenario_id,
            "field": deepcopy(self.field),
            "seasons": [asdict(s) for s in self.seasons],
            "crop_configurations": deepcopy(self.crop_configurations),
            "prices": deepcopy(self.prices),
            "initial_inventory": deepcopy(self._initial_inventory),
            "initial_machine_fuel_liters": self.initial_machine_fuel_liters,
            "postharvest_market": deepcopy(farm._postharvest_market.to_dict()),
            "tractor_configuration": {
                "equipment": asdict(tractor.equipment),
                "harvest_moisture_limit_pct": tractor._harvest_moisture_limit_pct,
                "harvest_limit_configured": tractor._harvest_limit_configured,
            },
            "initial_soil_states": {
                str(k): asdict(v) for k, v in farm.physics.soil.states.items()
            },
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
        self._initial_signature["fertilizer_market"] = {
            "cash": self.initial_purchase_cash,
            "offers": self.fertilizer_offers,
            "initial_inventory_cost": self.prices["fertilizer_per_kg"],
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
                - self.initial_fertilizer_kg
                - sum(o["kg"] for o in self.market.orders.values())
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
        account["purchase_accounts"] = self.market.compute_purchase_accounts()
        if any(r["crop_id"] != "maize" for r in self.cycle.closed):
            failures.append("This task requires two maize crops")
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
            "farm": self.get_typed_app(FarmWorldApp).get_state(),
            "tractor": self.get_typed_app(TractorApp).get_state(),
            "cycle": self.cycle.get_state(),
            "weather": self.get_typed_app(WeatherApp).get_state(),
            "sensors": self.get_typed_app(SensorApp).get_state(),
            "clock": self.get_typed_app(FarmWorldApp).time_manager.time(),
            "fertilizer_market": self.market.get_state(),
        }

    def build_events_flow(self):
        if not self.prepare_oracle_capture():
            return []
        apps = {app.name: app for app in self.apps}
        with EventRegisterer.capture_mode() as events:
            previous = None
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0000",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0001",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_inventory(),
                "step0002",
                "执行公开工具 FarmWorldApp__get_inventory；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_crop_capabilities(),
                "step0003",
                "执行公开工具 FarmWorldApp__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0004",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_inventory(),
                "step0005",
                "执行公开工具 FarmWorldApp__get_inventory；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].get_status(),
                "step0006",
                "执行公开工具 TractorApp__get_status；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_inventory(),
                "step0007",
                "执行公开工具 FarmWorldApp__get_inventory；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].attach_implement(implement="grader"),
                "step0008",
                "执行公开工具 TractorApp__attach_implement；参数 {'implement': 'grader'}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].level(),
                "step0009",
                "执行公开工具 TractorApp__level；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].detach_implement(),
                "step0010",
                "执行公开工具 TractorApp__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].load_fertilizer(kg=50.0),
                "step0011",
                "执行公开工具 TractorApp__load_fertilizer；参数 {'kg': 50.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].base_fertilize(total_kg=50.0),
                "step0012",
                "执行公开工具 TractorApp__base_fertilize；参数 {'total_kg': 50.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].attach_implement(implement="furrower"),
                "step0013",
                "执行公开工具 TractorApp__attach_implement；参数 {'implement': 'furrower'}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].form_ridges(ridge_width_m=0.75),
                "step0014",
                "执行公开工具 TractorApp__form_ridges；参数 {'ridge_width_m': 0.75}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].detach_implement(),
                "step0015",
                "执行公开工具 TractorApp__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].load_seeds(seed_type="MAIZE_201", count=21440),
                "step0016",
                "执行公开工具 TractorApp__load_seeds；参数 {'seed_type': 'MAIZE_201', 'count': 21440}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=0, end_ridge=3, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0017",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 0, 'end_ridge': 3, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=4, end_ridge=7, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0018",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 4, 'end_ridge': 7, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=8, end_ridge=11, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0019",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 8, 'end_ridge': 11, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=12, end_ridge=15, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0020",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 12, 'end_ridge': 15, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].commit_daily_physics(),
                "step0021",
                "执行公开工具 FarmWorldApp__commit_daily_physics；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1205841.0),
                "step0022",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1205841.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0023",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0024",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].apply_fertigation(
                    start_ridge=0, end_ridge=15, nutrient_amount=0.078125, water_mm=0.0
                ),
                "step0025",
                "执行公开工具 FarmWorldApp__apply_fertigation；参数 {'start_ridge': 0, 'end_ridge': 15, 'nutrient_amount': 0.078125, 'water_mm': 0.0}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=432000.0),
                "step0026",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 432000.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0027",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0028",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0029",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FieldOpsApp"].irrigate(start=0, end=15, hours=7.5),
                "step0030",
                "执行公开工具 FieldOpsApp__irrigate；参数 {'start': 0, 'end': 15, 'hours': 7.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=836700.0),
                "step0031",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 836700.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0032",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0033",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].apply_fertigation(
                    start_ridge=0, end_ridge=15, nutrient_amount=0.078125, water_mm=0.0
                ),
                "step0034",
                "执行公开工具 FarmWorldApp__apply_fertigation；参数 {'start_ridge': 0, 'end_ridge': 15, 'nutrient_amount': 0.078125, 'water_mm': 0.0}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=2592000.0),
                "step0035",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 2592000.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0036",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0037",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0038",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=864000.0),
                "step0039",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 864000.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0040",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0041",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0042",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FieldOpsApp"].irrigate(start=0, end=15, hours=7.5),
                "step0043",
                "执行公开工具 FieldOpsApp__irrigate；参数 {'start': 0, 'end': 15, 'hours': 7.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=836700.0),
                "step0044",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 836700.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0045",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0046",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0047",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FieldOpsApp"].irrigate(start=0, end=15, hours=7.5),
                "step0048",
                "执行公开工具 FieldOpsApp__irrigate；参数 {'start': 0, 'end': 15, 'hours': 7.5}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_crop_capabilities(),
                "step0049",
                "执行公开工具 FarmWorldApp__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1614300.0),
                "step0050",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1614300.0}",
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
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0062",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0063",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0064",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].refuel(liters=100.0),
                "step0065",
                "执行公开工具 TractorApp__refuel；参数 {'liters': 100.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=0, end_ridge=3),
                "step0066",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 0, 'end_ridge': 3}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0067",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=4, end_ridge=7),
                "step0068",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 4, 'end_ridge': 7}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0069",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=8, end_ridge=11),
                "step0070",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 8, 'end_ridge': 11}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0071",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=12, end_ridge=15),
                "step0072",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 12, 'end_ridge': 15}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0073",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].dry_grain(target_moisture_pct=14.0),
                "step0074",
                "执行公开工具 FarmWorldApp__dry_grain；参数 {'target_moisture_pct': 14.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].store_grain(),
                "step0075",
                "执行公开工具 FarmWorldApp__store_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropRotation"].close_season(year=2024),
                "step0076",
                "执行公开工具 CropRotation__close_season；参数 {'year': 2024}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=3971396.0),
                "step0077",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 3971396.0}",
            )
            previous = capture_step(
                previous,
                apps["FertilizerMarket"].get_offers(),
                "step0078",
                "执行公开工具 FertilizerMarket__get_offers；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_inventory(),
                "step0079",
                "执行公开工具 FarmWorldApp__get_inventory；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].get_status(),
                "step0080",
                "执行公开工具 TractorApp__get_status；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FertilizerMarket"].purchase_fertilizer(
                    offer_id="advance_stock",
                    kg=174.99999999999997,
                    order_id="next-season-reserve",
                ),
                "step0081",
                "执行公开工具 FertilizerMarket__purchase_fertilizer；参数 {'offer_id': 'advance_stock', 'kg': 174.99999999999997, 'order_id': 'next-season-reserve'}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=18662400.0),
                "step0082",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 18662400.0}",
            )
            previous = capture_step(
                previous,
                apps["CropRotation"].get_crop_options(),
                "step0083",
                "执行公开工具 CropRotation__get_crop_options；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropRotation"].get_season_ledger(),
                "step0084",
                "执行公开工具 CropRotation__get_season_ledger；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropRotation"].open_next_crop(year=2025, crop_id="maize"),
                "step0085",
                "执行公开工具 CropRotation__open_next_crop；参数 {'year': 2025, 'crop_id': 'maize'}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0086",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0087",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_inventory(),
                "step0088",
                "执行公开工具 FarmWorldApp__get_inventory；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_crop_capabilities(),
                "step0089",
                "执行公开工具 FarmWorldApp__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0090",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_inventory(),
                "step0091",
                "执行公开工具 FarmWorldApp__get_inventory；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].get_status(),
                "step0092",
                "执行公开工具 TractorApp__get_status；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FertilizerMarket"].get_offers(),
                "step0093",
                "执行公开工具 FertilizerMarket__get_offers；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_inventory(),
                "step0094",
                "执行公开工具 FarmWorldApp__get_inventory；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].attach_implement(implement="grader"),
                "step0095",
                "执行公开工具 TractorApp__attach_implement；参数 {'implement': 'grader'}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].level(),
                "step0096",
                "执行公开工具 TractorApp__level；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].detach_implement(),
                "step0097",
                "执行公开工具 TractorApp__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].load_fertilizer(kg=50.0),
                "step0098",
                "执行公开工具 TractorApp__load_fertilizer；参数 {'kg': 50.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].base_fertilize(total_kg=50.0),
                "step0099",
                "执行公开工具 TractorApp__base_fertilize；参数 {'total_kg': 50.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].attach_implement(implement="furrower"),
                "step0100",
                "执行公开工具 TractorApp__attach_implement；参数 {'implement': 'furrower'}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].form_ridges(ridge_width_m=0.75),
                "step0101",
                "执行公开工具 TractorApp__form_ridges；参数 {'ridge_width_m': 0.75}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].detach_implement(),
                "step0102",
                "执行公开工具 TractorApp__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].load_seeds(seed_type="MAIZE_201", count=21440),
                "step0103",
                "执行公开工具 TractorApp__load_seeds；参数 {'seed_type': 'MAIZE_201', 'count': 21440}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=0, end_ridge=3, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0104",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 0, 'end_ridge': 3, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=4, end_ridge=7, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0105",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 4, 'end_ridge': 7, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=8, end_ridge=11, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0106",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 8, 'end_ridge': 11, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=12, end_ridge=15, depth_cm=4.0, seed_spacing_cm=20.0
                ),
                "step0107",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 12, 'end_ridge': 15, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].commit_daily_physics(),
                "step0108",
                "执行公开工具 FarmWorldApp__commit_daily_physics；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1205841.0),
                "step0109",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1205841.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0110",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0111",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].apply_fertigation(
                    start_ridge=0,
                    end_ridge=15,
                    nutrient_amount=0.13020812499999998,
                    water_mm=0.0,
                ),
                "step0112",
                "执行公开工具 FarmWorldApp__apply_fertigation；参数 {'start_ridge': 0, 'end_ridge': 15, 'nutrient_amount': 0.13020812499999998, 'water_mm': 0.0}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=432000.0),
                "step0113",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 432000.0}",
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
                apps["SystemApp"].advance_time(seconds=864000.0),
                "step0117",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 864000.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0118",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0119",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].apply_fertigation(
                    start_ridge=0,
                    end_ridge=15,
                    nutrient_amount=0.13020812499999998,
                    water_mm=0.0,
                ),
                "step0120",
                "执行公开工具 FarmWorldApp__apply_fertigation；参数 {'start_ridge': 0, 'end_ridge': 15, 'nutrient_amount': 0.13020812499999998, 'water_mm': 0.0}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=2592000.0),
                "step0121",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 2592000.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0122",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0123",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0124",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FieldOpsApp"].irrigate(start=0, end=15, hours=12.5),
                "step0125",
                "执行公开工具 FieldOpsApp__irrigate；参数 {'start': 0, 'end': 15, 'hours': 12.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=818700.0),
                "step0126",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 818700.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0127",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0128",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0129",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FieldOpsApp"].irrigate(start=0, end=15, hours=12.5),
                "step0130",
                "执行公开工具 FieldOpsApp__irrigate；参数 {'start': 0, 'end': 15, 'hours': 12.5}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=818700.0),
                "step0131",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 818700.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0132",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0133",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0134",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_crop_capabilities(),
                "step0135",
                "执行公开工具 FarmWorldApp__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1641600.0),
                "step0136",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1641600.0}",
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
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0187",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0188",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0189",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0190",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0191",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0192",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0193",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0194",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0195",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0196",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0197",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0198",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].refuel(liters=100.0),
                "step0199",
                "执行公开工具 TractorApp__refuel；参数 {'liters': 100.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=0, end_ridge=3),
                "step0200",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 0, 'end_ridge': 3}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0201",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=4, end_ridge=7),
                "step0202",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 4, 'end_ridge': 7}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0203",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=8, end_ridge=11),
                "step0204",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 8, 'end_ridge': 11}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0205",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=12, end_ridge=15),
                "step0206",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 12, 'end_ridge': 15}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0207",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].dry_grain(target_moisture_pct=14.0),
                "step0208",
                "执行公开工具 FarmWorldApp__dry_grain；参数 {'target_moisture_pct': 14.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].store_grain(),
                "step0209",
                "执行公开工具 FarmWorldApp__store_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropRotation"].close_season(year=2025),
                "step0210",
                "执行公开工具 CropRotation__close_season；参数 {'year': 2025}",
            )
            previous = capture_step(
                previous,
                apps["CropRotation"].get_accounts(),
                "step0211",
                "执行公开工具 CropRotation__get_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FertilizerMarket"].get_purchase_accounts(),
                "step0212",
                "执行公开工具 FertilizerMarket__get_purchase_accounts；参数 {}",
            )
        return finish_capture(self, events)
