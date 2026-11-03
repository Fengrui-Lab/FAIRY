"""L4：固定首季玉米之后检索已发布政策，比较次年玉米或大豆并实际申请、核验、领取补贴。"""

import hashlib
import json
import textwrap
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, time
from pathlib import Path
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
from fairy.scenarios.management_extensions.apps.crop_subsidy_app import CropSubsidyApp
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.types import EventRegisterer

from ..apps.season_cycle_app import AnnualCropSeason
from ..china_market_prices import operating_prices
from ..evaluation.oracle_comparison import compare_to_oracle
from ..common import capture_step, finish_capture
from ..engines.crop_rotation_wofost import CropRotationBackend
from ..oracle_management_plans import manage_rotating_crops


class ScenarioMaizeSoybeanPolicyChoice(Scenario):
    scenario_id = "scenario_l4_maize_soybean_policy_choice"
    level = "L4"
    objective_metric = "net_operating_margin"
    oracle_policy = staticmethod(manage_rotating_crops)
    checkpoint_payload_sha256 = (
        "6c63d660b13b7fc787a243dccbb299ca301b9ced82430c34b17055073520216e"
    )
    checkpoint_prefix_sha256 = (
        "77360bf4cc69aa347d11f9f8fa0cd7cac5025fe7242c11213608326c6a95c122"
    )
    registered_county: ClassVar = "榆树市"
    prices: ClassVar = operating_prices(high_water=False)
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
    crop_configurations: ClassVar[dict] = {
        "maize": backend_options,
        "soybean": {
            **backend_options,
            "crop_name": "soybean",
            "variety_name": "Soybean_901",
            "cultivar_map": {"SOYBEAN_901": "Soybean_901"},
            "reference_density_plants_m2": 40.0,
        },
    }
    fertilizer_budget_kg: ClassVar = 125.0
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
        "CropSubsidy": 8819931,
    }
    ORACLE_REFERENCE: ClassVar[dict] = {
        "scenario_id": "scenario_l4_maize_soybean_policy_choice",
        "input_fingerprint": "0f9f43db17d8b337cfe7e464e9ee6294b19ab0b3919e74236e3f7a9d57ab29d5",
        "selected": {
            "currency": "USD",
            "price_book_id": "china_northeast_2025_usd_v1",
            "cny_per_usd": 7.1757,
            "stored_kg_by_crop": {"maize": 3496.84, "soybean": 979.84},
            "grain_value": 1642.4994355951335,
            "production_cost": 199.74016442096215,
            "net_operating_margin": 1812.5071703338351,
            "seasons": [
                {"year": 2024, "stored_grain_kg": 3496.84, "crop_id": "maize"},
                {
                    "year": 2025,
                    "stored_grain_kg": 979.8400000000001,
                    "crop_id": "soybean",
                },
            ],
        },
        "workflow_steps": 121,
        "candidate_count": 6,
        "feasible_count": 4,
        "scope": "Best feasible candidate among 6 freshly executed USD management candidates, including "
        "the prior literal workflow, a short-list ranked from archived physical receipts, and "
        "explicit crop/water/fertilizer/protection controls. Crop biology, weather and physical "
        "caps unchanged. No claim of global optimum; archived revaluations are rankings, not "
        "fresh execution.",
        "calibration_artifact": "validation_runs/management_usd_china_2025_20261103_220138/newer/scenario_l4_maize_soybean_policy_choice/calibration_reference.json",
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
        self._load_initial_checkpoint()
        self.scenario_input = (
            self._input_override
            if self._input_override is not None
            else self.task_description(self.detailed_briefing)
        )
        self.additional_system_prompt = (
            self._system_override if self._has_system_override else self.scenario_input
        )
        self.build_events_flow()

    def _load_initial_checkpoint(self):
        """Load a genuine public-tool prefix; runtime setup never executes management."""
        from fairy.time_manager import SimulationTimeManager

        path = (
            Path(__file__).parents[1]
            / "data/checkpoints/maize_2024_growing_policy_takeover.json"
        )
        asset = json.loads(path.read_text())
        payload = asset["payload"]
        manifest = asset["manifest"]
        source_fp = payload["source_input_fingerprint"]
        binding = manifest.get("usd_economic_binding")
        expected_fp = binding["input_fingerprint"] if binding else source_fp
        if self.input_fingerprint() != expected_fp:
            raise ValueError(
                "Initial checkpoint does not match the declared initial field, soil, inventory and environment"
            )
        if binding:
            # Historical source facts remain untouched. Only the price table may
            # differ in the explicitly declared current economic binding.
            bound_signature = deepcopy(binding["input_signature"])
            source_signature = deepcopy(manifest["source_manifest"]["input_signature"])
            bound_hash = hashlib.sha256(
                json.dumps(bound_signature, sort_keys=True).encode()
            ).hexdigest()
            bound_signature.pop("prices")
            source_signature.pop("prices")
            if (
                binding["source_input_fingerprint"] != source_fp
                or bound_hash != expected_fp
                or bound_signature != source_signature
            ):
                raise ValueError(
                    "USD checkpoint binding may only replace economic prices"
                )
        signature_fp = hashlib.sha256(
            json.dumps(
                manifest["source_manifest"]["input_signature"],
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        if (
            signature_fp != source_fp
            or manifest["source_manifest"]["input_fingerprint"] != source_fp
        ):
            raise ValueError(
                "Checkpoint source manifest disagrees with its bound source input signature"
            )

        def canonical(value):
            return json.dumps(
                value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()

        if (
            hashlib.sha256(canonical(payload)).hexdigest()
            != self.checkpoint_payload_sha256
            or manifest["payload_sha256"] != self.checkpoint_payload_sha256
        ):
            raise ValueError(
                "Initial native checkpoint content differs from the frozen source"
            )
        if (
            hashlib.sha256(canonical(manifest["prefix_workflow"])).hexdigest()
            != self.checkpoint_prefix_sha256
            or manifest["prefix_workflow_sha256"] != self.checkpoint_prefix_sha256
        ):
            raise ValueError(
                "Initial checkpoint public-tool prefix provenance is inconsistent"
            )
        if payload["dynamic_events"] or payload["schema"] != 1:
            raise ValueError(
                "This checkpoint requires the declared empty dynamic-event queue"
            )
        clock = SimulationTimeManager()
        clock.reset(payload["clock"])

        def tuples(value):
            return tuple(tuples(v) for v in value) if isinstance(value, list) else value

        if set(payload["states"]) != {a.name for a in self.apps}:
            raise ValueError("Checkpoint App composition mismatch")
        for app in self.apps:
            app.register_time_manager(clock)
            if payload["states"][app.name] is not None:
                app.load_state(payload["states"][app.name])
            app.seed = payload["seeds"][app.name]
            app.rng.setstate(tuples(payload["rng_states"][app.name]))
        end = self.start_time + self.duration
        self.start_time = payload["clock"]
        self.duration = end - self.start_time
        self.dynamic_events = []
        self._initial_signature["start_time"] = self.start_time
        self._initial_signature["duration"] = self.duration
        self._initial_signature["initial_checkpoint"] = {
            "path": path.name,
            "payload_sha256": self.checkpoint_payload_sha256,
            "economic_binding_fingerprint": expected_fp,
            "prefix_workflow_sha256": manifest["prefix_workflow_sha256"],
            "source_input_fingerprint": payload["source_input_fingerprint"],
            "prefix_steps": manifest["prefix_steps"],
            "past_inputs_cost_treatment": "Included once as fixed historical constants in whole-horizon accounts; no retrospective actions permitted",
        }

    def task_description(self, detailed):
        task = "接管面积3216m²、垄距0.75m、已经建植且仍在生长的首季玉米田，完成当季收储，再经营次年的玉米或大豆。以吉林省榆树市的模拟申报身份检索当时已公布的政策，合规种植、申报并实际领取补贴，尽量提高两季实际净收益。作物、年度计划和价格查 CropRotation.get_crop_options；政策地区、年度、金额及办理窗口查 CropSubsidy.search_policies。其他参数通过库存和设备工具查询。"
        if not detailed:
            return task
        guidance = textwrap.dedent(
            """\
            管理指导：

            接管核对：读取 CropRotation.get_season_ledger、地块概况、作物能力、库存和机器状态，确认首季已发生的投入与作物进度。继续管理现有玉米，不重新播种或回溯安排过去操作；历史费用按实际账本计入，不能重复计算。

            水肥依据：用 SensorApp.read_root_zone_sensors、read_soil_sensors、read_canopy_sensors，结合天气、作物阶段与投入记录排查需水和营养异常。持续偏干且降水不足时按余量分次供水，待生效后复读同区探头；低冠层或营养代理值不能直接确诊缺肥。土壤氮模型估计须核对日期和覆盖，缺失不当成零；无实际肥料来源时不能假设施肥。

            首季收储与衔接：根据真实成熟、水分、天气和设备容量完成全田收割、卸粮、必要干燥及安全入库，再 close_season。保留土壤、余料和历史账，按计划推进冬季；不能把首季存粮记为次季新增产量。

            政策与选作物：春播前按工具返回的计划年度、登记地榆树市检索已公布文件，核对适用地区、作物、发布时间及办理窗口，再结合价格、库存、土壤和作物需求比较次季方案。未来未公开标准不可当作已知，补贴也不保证某作物必然最赚钱。选作物前处理种箱余种，再 open_next_crop 并按实际规则建植。

            申报与复查：全田实际种植后，在工具公布的窗口按真实作物和面积 apply_for_subsidy，核对登记收据。季内继续依据土壤、冠层、天气与阶段管理；干预后复测并核账，种子、肥料和水量不会自动恢复。模拟办理窗口与政府文件的发布及补贴事实分别核对。

            领取与结算：次季成熟安全收储并结季后，重新检索当时已公布的最终标准，在支付窗口 collect_subsidy 并检查实际到账。只有已支付补贴计入收益，检索或登记本身不产生收入。最后分季、分作物核对粮批与消耗，报告补贴前收益及已到账补贴。

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
        policy_path = Path(__file__).parents[1] / "data/jilin_2025_policy/notices.json"
        self.policy_documents = json.loads(policy_path.read_text())
        self.subsidy = CropSubsidyApp(
            farm,
            self.cycle,
            county=self.registered_county,
            year=2025,
            documents=self.policy_documents,
            application_from="2025-05-01",
            application_until="2025-06-30",
            payment_from="2025-09-11",
            payment_until="2025-10-31",
        )
        self.apps.append(self.subsidy)
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
        self._initial_signature["policy"] = {
            "registered_county": self.registered_county,
            "documents": deepcopy(self.policy_documents),
            "processing_windows": {
                "application": ["2025-05-01", "2025-06-30"],
                "payment": ["2025-09-11", "2025-10-31"],
            },
            "processing_window_status": "Explicit simulation assumption, not a quoted official deadline",
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
        account["operating_margin_before_subsidy"] = account["net_operating_margin"]
        account["paid_subsidy"] = self.subsidy.paid_income()
        account["net_operating_margin"] += self.subsidy.paid_income()
        account["policy_accounts"] = self.subsidy.get_state()
        if self.cycle.closed and self.cycle.closed[0]["crop_id"] != "maize":
            failures.append("First-season maize is a fixed planting obligation")
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
                    agent_seasons=self.cycle.closed,
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
            "policy": self.subsidy.get_state(),
        }

    def build_events_flow(self):
        if not self.prepare_oracle_capture():
            return []
        apps = {app.name: app for app in self.apps}
        with EventRegisterer.capture_mode() as events:
            previous = None
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_crop_capabilities(),
                "step0000",
                "执行公开工具 FarmWorldApp__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1614300.0),
                "step0001",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1614300.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0002",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0003",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0004",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0005",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0006",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0007",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0008",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0009",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0010",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0011",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0012",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0013",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0014",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0015",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].refuel(liters=100.0),
                "step0016",
                "执行公开工具 TractorApp__refuel；参数 {'liters': 100.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=0, end_ridge=3),
                "step0017",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 0, 'end_ridge': 3}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0018",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=4, end_ridge=7),
                "step0019",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 4, 'end_ridge': 7}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0020",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=8, end_ridge=11),
                "step0021",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 8, 'end_ridge': 11}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0022",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=12, end_ridge=15),
                "step0023",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 12, 'end_ridge': 15}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0024",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].dry_grain(target_moisture_pct=14.0),
                "step0025",
                "执行公开工具 FarmWorldApp__dry_grain；参数 {'target_moisture_pct': 14.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].store_grain(),
                "step0026",
                "执行公开工具 FarmWorldApp__store_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropRotation"].close_season(year=2024),
                "step0027",
                "执行公开工具 CropRotation__close_season；参数 {'year': 2024}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=19091396.0),
                "step0028",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 19091396.0}",
            )
            previous = capture_step(
                previous,
                apps["CropSubsidy"].search_policies(year=2025, county="榆树市"),
                "step0029",
                "执行公开工具 CropSubsidy__search_policies；参数 {'year': 2025, 'county': '榆树市'}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=3542400.0),
                "step0030",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 3542400.0}",
            )
            previous = capture_step(
                previous,
                apps["CropRotation"].get_crop_options(),
                "step0031",
                "执行公开工具 CropRotation__get_crop_options；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropRotation"].get_season_ledger(),
                "step0032",
                "执行公开工具 CropRotation__get_season_ledger；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropRotation"].open_next_crop(year=2025, crop_id="soybean"),
                "step0033",
                "执行公开工具 CropRotation__open_next_crop；参数 {'year': 2025, 'crop_id': 'soybean'}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0034",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0035",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_inventory(),
                "step0036",
                "执行公开工具 FarmWorldApp__get_inventory；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_crop_capabilities(),
                "step0037",
                "执行公开工具 FarmWorldApp__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0038",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].attach_implement(implement="grader"),
                "step0039",
                "执行公开工具 TractorApp__attach_implement；参数 {'implement': 'grader'}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].level(),
                "step0040",
                "执行公开工具 TractorApp__level；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].detach_implement(),
                "step0041",
                "执行公开工具 TractorApp__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].attach_implement(implement="furrower"),
                "step0042",
                "执行公开工具 TractorApp__attach_implement；参数 {'implement': 'furrower'}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].form_ridges(ridge_width_m=0.75),
                "step0043",
                "执行公开工具 TractorApp__form_ridges；参数 {'ridge_width_m': 0.75}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].detach_implement(),
                "step0044",
                "执行公开工具 TractorApp__detach_implement；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].load_seeds(seed_type="SOYBEAN_901", count=128640),
                "step0045",
                "执行公开工具 TractorApp__load_seeds；参数 {'seed_type': 'SOYBEAN_901', 'count': 128640}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=0,
                    end_ridge=3,
                    depth_cm=4.0,
                    seed_spacing_cm=6.666666666666667,
                ),
                "step0046",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 0, 'end_ridge': 3, 'depth_cm': 4.0, 'seed_spacing_cm': 6.666666666666667}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=4,
                    end_ridge=7,
                    depth_cm=4.0,
                    seed_spacing_cm=6.666666666666667,
                ),
                "step0047",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 4, 'end_ridge': 7, 'depth_cm': 4.0, 'seed_spacing_cm': 6.666666666666667}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=8,
                    end_ridge=11,
                    depth_cm=4.0,
                    seed_spacing_cm=6.666666666666667,
                ),
                "step0048",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 8, 'end_ridge': 11, 'depth_cm': 4.0, 'seed_spacing_cm': 6.666666666666667}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].plant_seeds(
                    start_ridge=12,
                    end_ridge=15,
                    depth_cm=4.0,
                    seed_spacing_cm=6.666666666666667,
                ),
                "step0049",
                "执行公开工具 TractorApp__plant_seeds；参数 {'start_ridge': 12, 'end_ridge': 15, 'depth_cm': 4.0, 'seed_spacing_cm': 6.666666666666667}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].commit_daily_physics(),
                "step0050",
                "执行公开工具 FarmWorldApp__commit_daily_physics；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropSubsidy"].apply_for_subsidy(
                    year=2025,
                    crop_id="soybean",
                    county="榆树市",
                    document_id="jilin_2025_march_program",
                ),
                "step0051",
                "执行公开工具 CropSubsidy__apply_for_subsidy；参数 {'year': 2025, 'crop_id': 'soybean', 'county': '榆树市', 'document_id': 'jilin_2025_march_program'}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1206222.0),
                "step0052",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1206222.0}",
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
                apps["SystemApp"].advance_time(seconds=432000.0),
                "step0055",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 432000.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0056",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0057",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0058",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=864000.0),
                "step0059",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 864000.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0060",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0061",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=2592000.0),
                "step0062",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 2592000.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0063",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0064",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0065",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FieldOpsApp"].irrigate(start=0, end=15, hours=10.0),
                "step0066",
                "执行公开工具 FieldOpsApp__irrigate；参数 {'start': 0, 'end': 15, 'hours': 10.0}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=827700.0),
                "step0067",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 827700.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0068",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0069",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0070",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FieldOpsApp"].irrigate(start=0, end=15, hours=10.0),
                "step0071",
                "执行公开工具 FieldOpsApp__irrigate；参数 {'start': 0, 'end': 15, 'hours': 10.0}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=827700.0),
                "step0072",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 827700.0}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_forecast(days=7),
                "step0073",
                "执行公开工具 WeatherApp__get_forecast；参数 {'days': 7}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_farm_overview(),
                "step0074",
                "执行公开工具 FarmWorldApp__get_farm_overview；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SensorApp"].read_soil_sensors(),
                "step0075",
                "执行公开工具 SensorApp__read_soil_sensors；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_crop_capabilities(),
                "step0076",
                "执行公开工具 FarmWorldApp__get_crop_capabilities；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1641600.0),
                "step0077",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1641600.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0078",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0079",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0080",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0081",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0082",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0083",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0084",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0085",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0086",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0087",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0088",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0089",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0090",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0091",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0092",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0093",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0094",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0095",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0096",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0097",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0098",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0099",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0100",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=86400.0),
                "step0101",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 86400.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].get_ridge_range_state(start=0, end=15),
                "step0102",
                "执行公开工具 FarmWorldApp__get_ridge_range_state；参数 {'start': 0, 'end': 15}",
            )
            previous = capture_step(
                previous,
                apps["WeatherApp"].get_current_weather(),
                "step0103",
                "执行公开工具 WeatherApp__get_current_weather；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].refuel(liters=100.0),
                "step0104",
                "执行公开工具 TractorApp__refuel；参数 {'liters': 100.0}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=0, end_ridge=3),
                "step0105",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 0, 'end_ridge': 3}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0106",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=4, end_ridge=7),
                "step0107",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 4, 'end_ridge': 7}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0108",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=8, end_ridge=11),
                "step0109",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 8, 'end_ridge': 11}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0110",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].harvest(start_ridge=12, end_ridge=15),
                "step0111",
                "执行公开工具 TractorApp__harvest；参数 {'start_ridge': 12, 'end_ridge': 15}",
            )
            previous = capture_step(
                previous,
                apps["TractorApp"].unload_grain(),
                "step0112",
                "执行公开工具 TractorApp__unload_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].dry_grain(target_moisture_pct=13.0),
                "step0113",
                "执行公开工具 FarmWorldApp__dry_grain；参数 {'target_moisture_pct': 13.0}",
            )
            previous = capture_step(
                previous,
                apps["FarmWorldApp"].store_grain(),
                "step0114",
                "执行公开工具 FarmWorldApp__store_grain；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropRotation"].close_season(year=2025),
                "step0115",
                "执行公开工具 CropRotation__close_season；参数 {'year': 2025}",
            )
            previous = capture_step(
                previous,
                apps["SystemApp"].advance_time(seconds=1897796.0),
                "step0116",
                "执行公开工具 SystemApp__advance_time；参数 {'seconds': 1897796.0}",
            )
            previous = capture_step(
                previous,
                apps["CropSubsidy"].search_policies(year=2025, county="榆树市"),
                "step0117",
                "执行公开工具 CropSubsidy__search_policies；参数 {'year': 2025, 'county': '榆树市'}",
            )
            previous = capture_step(
                previous,
                apps["CropSubsidy"].collect_subsidy(year=2025),
                "step0118",
                "执行公开工具 CropSubsidy__collect_subsidy；参数 {'year': 2025}",
            )
            previous = capture_step(
                previous,
                apps["CropRotation"].get_accounts(),
                "step0119",
                "执行公开工具 CropRotation__get_accounts；参数 {}",
            )
            previous = capture_step(
                previous,
                apps["CropSubsidy"].get_subsidy_accounts(),
                "step0120",
                "执行公开工具 CropSubsidy__get_subsidy_accounts；参数 {}",
            )
        return finish_capture(self, events)
