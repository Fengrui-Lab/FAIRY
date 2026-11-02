"""Two actual maize seasons on one unchanged field, using continuous synthetic climate.

Registration belongs to the extension family's explicit module list; importing
this module has no registry side effects. The reference is a finite-search
result with a separately verified static public-tool workflow.
"""

from datetime import date
import json
import hashlib
from dataclasses import asdict
from pathlib import Path
from fairy.apps.farm_world import FarmWorldApp, TractorApp, WeatherApp
from fairy.physics.profiles import PhysicsProfile, get_profile
from fairy.physics.weather_engine import (
    WeatherGenerator,
    default_harbin_soybean_config,
    WeatherEvent,
)
from fairy.scenarios.maize.maize_scenario_helpers import MaizeScenario
from fairy.scenarios.maize.maize_scenario_catalog import get_spec
from fairy.scenarios.farm_world_fullseason_v2.harbin_l3_scenario_helpers import (
    install_common_farm_apps,
)
from fairy.scenarios.validation_result import ScenarioValidationResult
from .backend import ContinuousSeasonBackend
from .runtime import ContinuousFarm, SeasonCycle
from .randomness import initialize_app_randomness


class TwoYearMaizeScenario(MaizeScenario):
    spec = get_spec("normal")
    scenario_id = "scenario_l4_two_year_maize_soil_carryover"
    level = "L4"

    def __init__(self, *, calibrating=False, **kwargs):
        self.calibrating = calibrating
        requested_options = kwargs.get("crop_backend_options", {})
        default_options = self.spec.backend_options()
        if not isinstance(requested_options, dict) or any(
            key not in default_options or value != default_options[key]
            for key, value in requested_options.items()
        ):
            raise ValueError(
                "This fixed L4 experiment does not accept non-default crop_backend_options"
            )
        self._input_override = kwargs.get("scenario_input")
        self._system_prompt_override = kwargs.get("additional_system_prompt")
        self._has_system_prompt_override = "additional_system_prompt" in kwargs
        if type(kwargs.get("detailed_briefing", True)) is not bool:
            raise ValueError("detailed_briefing must be a boolean")
        kwargs.setdefault("scenario_id", self.scenario_id)
        kwargs.setdefault("duration", 550 * 86400)
        super().__init__(**kwargs)

    def init_and_populate_apps(self, *args, **kwargs):
        farm = ContinuousFarm(crop_type="maize", ridge_width_m=0.75)
        install_common_farm_apps(self, thermal=False, field_ops=True, farm_world=farm)
        farm.configure_crop_backend("wofost", **self.spec.backend_options())
        farm.physics.crop_backend = ContinuousSeasonBackend(self.spec.backend_options())
        farm.physics.crop_backend.bind_physics(farm.physics)
        farm.set_season_phase("full_season")
        farm._inventory.seed_stock = {"MAIZE_201": 200000}
        farm._inventory.fertilizer_kg = 1200.0
        farm._inventory.fuel_liters = 1000.0
        farm._inventory.pesticide_liters = 0
        tractor = self.get_typed_app(TractorApp)
        tractor._fuel_tank_l = 100.0
        tractor.configure_harvest(max_grain_moisture_pct=25)
        farm.configure_management_regime(
            irrigation_quota_mm_total=300.0, fertilizer_quota_kg=800.0
        )
        farm.configure_postharvest_market(
            market_moisture_pct=14.0,
            max_storage_moisture_pct=14.0,
            storage_capacity_kg=50000.0,
            drying_capacity_kg_per_day=20000.0,
        )
        farm._postharvest_market.require_safe_moisture = True
        for ridge in farm._ridges:
            ridge.planted = False
            ridge.harvested = False
            ridge.seed_type = None
            ridge.growth_stage = "NOT_PLANTED"
            ridge.soil_vwc = 0.28
            ridge.soil_temp_c = 16
        for soil in farm.physics.soil.states.values():
            soil.top_vwc = soil.root_vwc = 0.28
            soil.top_temp_c = soil.root_temp_c = 16
        config = default_harbin_soybean_config()
        config.monthly = {
            **get_profile("harbin_baseline_2026_seed_101").monthly_climate,
            **config.monthly,
        }
        farm.physics.profile = PhysicsProfile(
            name="l4_two_year_synthetic_harbin_v1",
            location="Synthetic Harbin climate",
            latitude_deg=45.7,
            monthly_climate=config.monthly,
            rng_seed=101,
            start_date=date(2026, 5, 5),
            duration_days=550,
            weather_events=[
                WeatherEvent(
                    "dry_spell", date(year, 5, 5), 5, label="declared_sowing_window"
                )
                for year in (2026, 2027)
            ],
        )
        farm.physics.weather_generator = WeatherGenerator(config, seed=101)
        farm.physics.scenario_metadata = {
            "daily_settlement": "completed_calendar_day",
            "weather_source": "synthetic daily generation, continuous dates 2026-2027; not repeated recorded years",
            "multi_year_adapter": "v1",
            "cross_species_rotation": False,
            "residue_n_credit": False,
            "winter_limitations": "no additional snow/frozen-soil process; uncalibrated continuous CWB/CNB experiment",
        }
        from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs

        _build_weather_inputs(
            self.get_typed_app(WeatherApp),
            date(2026, 5, 5),
            physics=farm.physics,
            advance_weather=False,
        )
        self.cycle = SeasonCycle(farm, tractor)
        self.apps.append(self.cycle)
        initialize_app_randomness(self.apps)
        self.scenario_input = (
            "经营同一块64垄玉米田，从2026年5月到2027年秋完成两次播种、收获和安全入库。"
            "每垄268米、宽0.75米，使用MAIZE_201、播深4厘米、株距20厘米。两季合计肥料产品1200kg、灌水400mm；每季最多800kg产品和300mm水，库存不按年补充。"
            "每季完成实际收获入库后调用SeasonCycle.close_season，跨年逐日物理结算后于2027年5月调用open_next_season。"
            "土壤水氮、设备、库存及总额度跨季延续。最大化两季合计安全入库粮，不能把第一季库存重复计作第二季产量。"
            "每季须在当年10月31日前完成收获入库。天气为公开声明的连续合成气候；不模拟残茬固碳、轮作固氮奖励或真实田间校准。"
            "冬季低温和降水驱动现有CWB/CNB逐日结算，但该基础实验未增加积雪和冻土模块，不作为寒地越冬的农艺推荐。产量参考正在离线探索，未预设门槛。"
        )
        self.input_signature = {
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
            "initial_inventory": farm._inventory.to_dict(),
            "initial_machine_fuel_l": tractor._fuel_tank_l,
            "season_caps": [800, 300],
            "horizon_caps": [1200, 400],
            "metadata": farm.physics.scenario_metadata,
        }
        self.input_fingerprint = hashlib.sha256(
            json.dumps(self.input_signature, sort_keys=True, default=str).encode()
        ).hexdigest()
        reference_path = Path(__file__).with_name("reference.json")
        if reference_path.exists():
            reference = json.loads(reference_path.read_text())
            self.scenario_input = self.scenario_input.replace(
                "产量参考正在离线探索，未预设门槛。",
                f"已测试候选最佳两季安全入库量为{reference['selected']['stored_grain_kg']:.2f}kg。"
                "该值是固定环境和有限管理搜索的参考，不是全局最优或硬性达标比例。",
            )
        if not self.detailed_briefing:
            self.scenario_input = (
                "在同一64垄田于2026、2027年各完成一季玉米成熟收获和安全入库，最大化累计入库粮。"
                "每季10/31截止；肥料产品每季≤800kg、两季≤1200kg，灌水每季≤300mm、两季≤400mm。"
                "使用SeasonCycle关闭已入库季节并于次年5月开启下一季；土壤、设备、库存和额度连续。"
                "2026/2027为连续合成气候，不含积雪冻土过程；参考品种与越冬过程未做当地校准。"
            )
        if self._input_override is not None:
            self.scenario_input = self._input_override
        self.additional_system_prompt = (
            self._system_prompt_override
            if self._has_system_prompt_override
            else self.scenario_input
        )

    def build_events_flow(self):
        if self.calibrating:
            self.events = []
            return
        oracle = Path(__file__).with_name("oracle.py")
        if oracle.exists():
            reference_path = Path(__file__).with_name("reference.json")
            if not reference_path.exists():
                raise ValueError("Published Oracle requires its calibration reference")
            reference = json.loads(reference_path.read_text())
            if reference.get("input_fingerprint") != self.input_fingerprint:
                raise ValueError(
                    "Published Oracle input fingerprint differs; recalibrate before capture"
                )
            from .oracle import capture_reference

            capture_reference(self)
        else:
            self.events = []

    def validate(self, env=None):
        farm = self.get_typed_app(FarmWorldApp)
        tractor = self.get_typed_app(TractorApp)
        backend = farm.physics.crop_backend
        rows = self.cycle.closed
        failures = []
        if farm.time_manager.time() > self.start_time + self.duration:
            failures.append("Episode exceeded its declared simulation horizon")
        if [row["year"] for row in rows] != [2026, 2027]:
            failures.append("Two successive calendar-year harvests are required")
        previous_fertilizer = previous_water = 0.0
        for row in rows:
            year = row["year"]
            if not row["planting_dates"] or not row["harvest_dates"]:
                failures.append(f"Missing actual planting/harvest dates for {year}")
            for value in (
                row["planting_dates"] + row["harvest_dates"] + [row["closed_date"]]
            ):
                day = date.fromisoformat(value)
                if day.year != year or day > date(year, 10, 31):
                    failures.append(f"Crop {year} exceeds its calendar-year deadline")
            fertilizer = row["fertilizer_used_kg_cumulative"]
            water = row["irrigation_used_mm_cumulative"]
            if not 0 <= fertilizer - previous_fertilizer <= 800 + 1e-8:
                failures.append(f"Season {year} fertilizer cap exceeded")
            if not 0 <= water - previous_water <= 300 + 1e-8:
                failures.append(f"Season {year} irrigation cap exceeded")
            previous_fertilizer, previous_water = fertilizer, water
        regime = farm._management_regime
        if (
            regime.fertilizer_used_kg > 1200 + 1e-8
            or regime.irrigation_used_mm_total > 400 + 1e-8
        ):
            failures.append("Whole-horizon resource cap exceeded")
        fertilizer_balance = (
            farm._inventory.fertilizer_kg
            + tractor._fertilizer_spreader_kg
            + regime.fertilizer_used_kg
        )
        if abs(fertilizer_balance - 1200) > 1e-6:
            failures.append("Fertilizer stock is not conserved")
        total = sum(row["stored_grain_kg"] for row in rows)
        if abs(total - farm._inventory.warehouse_grain_kg) > 1e-6:
            failures.append("Season grain ledger differs from actual warehouse")
        if (
            len(backend._runs) != farm.num_ridges
            or len(backend.season_history) != farm.num_ridges
        ):
            failures.append("Each ridge must have exactly one native second-crop start")
        if any(
            row["soil_before"] != row["soil_after"] for row in backend.season_history
        ):
            failures.append("Native crop transition changed soil pools")
        if tractor._grain_bin_kg or farm._inventory.harvest_grain_kg:
            failures.append("Unstored harvested grain remains")
        reference_path = Path(__file__).with_name("reference.json")
        reference = (
            json.loads(reference_path.read_text()) if reference_path.exists() else None
        )
        reference_matches = bool(
            reference and reference.get("input_fingerprint") == self.input_fingerprint
        )
        reference_yield = (
            reference["selected"]["stored_grain_kg"] if reference_matches else None
        )
        return ScenarioValidationResult(
            success=not failures,
            message="; ".join(failures)
            if failures
            else "Two calendar-year crops safely stored with continuous native soil",
            metadata={
                "feasible": not failures,
                "seasons": rows,
                "total_stored_grain_kg": total,
                "reference_stored_grain_kg": reference_yield,
                "yield_loss_pct": 100 * (1 - total / reference_yield)
                if reference_yield
                else None,
                "calibration_status": "finite_grid_best"
                if reference_matches
                else "development_not_calibrated",
                "global_optimum_claimed": False,
                "provenance": backend.snapshot()["provenance"],
            },
        )
