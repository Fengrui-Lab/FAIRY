"""Shared maize configuration and readable, side-effect-free Oracle builders."""
from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world import FarmWorldApp, FieldOpsApp, SensorApp, TractorApp, WeatherApp
from fairy.physics.profiles import PhysicsProfile, get_profile
from fairy.physics.weather_engine import WeatherEvent, WeatherGenerator, default_harbin_soybean_config
from fairy.scenarios.farm_world_fullseason_v2.harbin_l3_scenario_helpers import (
    advance_days, collect_event_graph, harbin_start_time, harvest_range,
    install_common_farm_apps, plant_range,
)
from fairy.scenarios.scenario import Scenario
from fairy.types import EventRegisterer

from .maize_scenario_catalog import MaizeScenarioSpec


class MaizeScenario(Scenario):
    """Shared defaults; individual registered modules declare their own hooks."""

    spec: MaizeScenarioSpec
    crop_name = "maize"
    level = "L3"
    task = "season"

    def __init__(self, **kwargs: Any) -> None:
        backend = kwargs.pop("crop_backend", "wofost")
        if backend != "wofost":
            raise ValueError("Maize scenarios require the WOFOST crop backend")
        options = {**self.spec.backend_options(), **kwargs.pop("crop_backend_options", {})}
        if options["crop_name"] != "maize" or options["variety_name"] != "Grain_maize_201":
            raise ValueError("Maize scenarios require maize / Grain_maize_201")
        if options.get("external_biotic_coupling"):
            raise ValueError("Maize v1 does not enable soybean biotic coupling")
        start = date.fromisoformat(self.spec.start_date)
        kwargs.setdefault("scenario_id", self.spec.scenario_id)
        kwargs.setdefault("start_time", harbin_start_time(start.year, start.month, start.day))
        kwargs.setdefault("duration", 180 * 86400)
        kwargs.setdefault("queue_based_loop", True)
        kwargs.setdefault("time_increment_in_seconds", 60)
        super().__init__(crop_backend=backend, crop_backend_options=options, **kwargs)

    def validate(self, env=None):
        from .validation import validate_maize

        return validate_maize(self, self.spec, workflow=env.workflow if env is not None else self.workflow)


def init_maize_apps(scenario: Scenario, spec: MaizeScenarioSpec) -> None:
    install_common_farm_apps(
        scenario, thermal=True, field_ops=True,
        farm_world=FarmWorldApp(crop_type="maize", ridge_width_m=0.75),
    )
    # App.set_seed uses Python's process-salted hash. Maize observations instead
    # use a stable local seed so offline artifacts reproduce across processes.
    for app in scenario.apps:
        app.seed = int.from_bytes(hashlib.sha256(
            f"maize:{spec.weather_seed}:{app.name}".encode()).digest()[:4], "big")
        app.rng.seed(app.seed)
    farm = scenario.get_typed_app(FarmWorldApp)
    weather = scenario.get_typed_app(WeatherApp)
    tractor = scenario.get_typed_app(TractorApp)
    farm.set_season_phase("full_season")
    farm.configure_physics_profile(
        profile_name=f"maize_reference_{spec.variant}_v1",
        location="Synthetic Harbin climate; European reference maize, uncalibrated",
        scenario_type="maize_full_season", random_seed=spec.weather_seed,
        seed_type="MAIZE_201", cultivar="Grain_maize_201", start_date=spec.start_date,
        density_target_plants_m2=1.0 / (0.75 * 0.20),
    )
    farm.configure_crop_backend("wofost", **scenario.crop_backend_options)
    farm._inventory.seed_stock = {"MAIZE_201": 100000}
    farm._inventory.fertilizer_kg = spec.fertilizer_stock_kg
    farm._inventory.fuel_liters = 500.0
    farm._inventory.pesticide_liters = 0.0
    tractor._fuel_tank_l = 100.0
    tractor.configure_harvest(max_grain_moisture_pct=25.0)
    farm.configure_management_regime(
        irrigation_quota_mm_total=spec.irrigation_quota_mm,
        fertilizer_quota_kg=spec.fertilizer_quota_kg,
    )
    farm.configure_postharvest_market(
        market_moisture_pct=14.0, max_storage_moisture_pct=14.0,
        drying_capacity_kg_per_day=20000.0, storage_capacity_kg=20000.0,
    )
    for ridge in farm._ridges:
        ridge.planted = False
        ridge.seed_type = None
        ridge.growth_stage = "NOT_PLANTED"
        ridge.soil_vwc = 0.28
        ridge.soil_temp_c = 16.0
        ridge.pest_pressure_base = ridge.pest_pressure = 0.0
        ridge.disease_pressure_base = ridge.disease_pressure = 0.0
    physics = farm.physics
    for soil in physics.soil.states.values():
        soil.top_vwc = soil.root_vwc = 0.28
        soil.top_temp_c = soil.root_temp_c = 16.0
    weather_config = default_harbin_soybean_config()
    weather_config.monthly = {
        **get_profile("harbin_baseline_2026_seed_101").monthly_climate,
        **weather_config.monthly,
    }
    weather_config.monthly = {
        month: replace(climate, precip_mm=climate.precip_mm * spec.precipitation_factor)
        for month, climate in weather_config.monthly.items()
    }
    start = date.fromisoformat(spec.start_date)
    # Explicit dry operation windows are part of the synthetic environment,
    # available identically to the Oracle and any independently acting agent.
    profile = PhysicsProfile(
        name=f"maize_reference_{spec.variant}_v1", location="Synthetic Harbin climate",
        latitude_deg=45.7, monthly_climate=copy.deepcopy(weather_config.monthly),
        rng_seed=spec.weather_seed, start_date=start, duration_days=180,
        weather_events=[
            WeatherEvent("dry_spell", start, 4, label="field_preparation_window"),
            WeatherEvent("dry_spell", start + timedelta(days=130), 35,
                         label="harvest_operation_window"),
        ],
    )
    physics.profile = profile
    physics.weather_generator = WeatherGenerator(weather_config, seed=spec.weather_seed)
    weather.set_weather(date=spec.start_date, temp_c=19.0, humidity_pct=55.0,
                        wind_speed_ms=2.0, rainfall_mm=0.0, solar_radiation=21.5 / 0.0864,
                        avg_soil_vwc=0.28)
    scenario._maize_initial_inventory = copy.deepcopy(farm._inventory.to_dict())
    scenario.scenario_input = (
        f"{spec.description}\n"
        "农田有64垄（0–63），每垄268米、宽0.75米，每垄一行；使用MAIZE_201种子，"
        "播深4厘米、株距20厘米，目标密度约6.67株/平方米。先整平、施基肥200公斤、"
        "起垄，再完成全田播种。参考品种Grain_maize_201尚未经过本地标定。\n"
        f"肥料库存及全季配额分别为{spec.fertilizer_stock_kg:g}和{spec.fertilizer_quota_kg:g}公斤，"
        f"灌溉总配额为{spec.irrigation_quota_mm:g}毫米（全田等效水深）。"
        "根据天气、土壤和作物观测安排水肥，5月开始种植，成熟后结合籽粒水分选择收获窗口。"
        "每次播种/收获最多4垄，保持设备燃油和料仓容量充足。\n"
        "仅在作物达到成熟且籽粒水分不高于25%时收获，卸粮后干燥至14%或更低再入库。"
        "完成全部64垄收获及安全入库，并报告产量、灌溉和肥料使用。"
        "玉米首版不模拟病虫草害，不需要施药。"
    )


def build_maize_events(scenario: Scenario, spec: MaizeScenarioSpec) -> None:
    aui = scenario.get_typed_app(AgentUserInterface)
    farm = scenario.get_typed_app(FarmWorldApp)
    tractor = scenario.get_typed_app(TractorApp)
    weather = scenario.get_typed_app(WeatherApp)
    sensor = scenario.get_typed_app(SensorApp)
    field_ops = scenario.get_typed_app(FieldOpsApp)

    with EventRegisterer.capture_mode():
        briefing = aui.send_message_to_agent(content=scenario.scenario_input).with_id("briefing")
        prev = weather.get_current_weather().oracle().with_id("o_preparation_weather").depends_on(briefing)
        prev = farm.get_inventory().oracle().with_id("o_initial_inventory").depends_on(prev)
        prev = sensor.read_soil_sensors().oracle().with_id("o_seedbed_soil").depends_on(prev)
        prev = build_maize_establishment(scenario, prev)

        # These fixed operation windows are calibrated offline through the same
        # public tools. Building this graph does not execute a crop simulation.
        previous_day = 0
        for day in sorted({15, 25, 40, 50, 70, 100, spec.harvest_day, *spec.irrigation_days}):
            prev = advance_days(scenario, prev, day - previous_day, f"o_wait_to_day_{day:03d}")
            previous_day = day
            prev = weather.get_forecast(days=7).oracle().with_id(f"o_day_{day:03d}_forecast").depends_on(prev)
            prev = sensor.read_soil_sensors().oracle().with_id(f"o_day_{day:03d}_soil").depends_on(prev)
            prev = farm.get_farm_overview().oracle().with_id(f"o_day_{day:03d}_crop").depends_on(prev)
            if day in (25, 50) and spec.topdress_kg > 0:
                # Existing fertigation units are 30 kg product/ridge; split
                # the specified whole-field product mass into two dressings.
                prev = farm.apply_fertigation(
                    start_ridge=0, end_ridge=63,
                    nutrient_amount=spec.topdress_kg / 2.0 / (30.0 * 64), water_mm=0.0,
                ).oracle().with_id(f"o_day_{day:03d}_topdress").depends_on(prev)
            if day in spec.irrigation_days:
                # FieldOps irrigation accepts hours at 5 mm per ridge/hour.
                prev = field_ops.irrigate(0, 63, spec.irrigation_mm / 5.0).oracle().with_id(
                    f"o_day_{day:03d}_irrigate"
                ).depends_on(prev)

        prev = tractor.refuel(100.0).oracle().with_id("o_refuel_before_harvest").depends_on(prev)
        prev = harvest_range(tractor, farm, prev, start_ridge=0, end_ridge=63,
                             id_prefix="o_maize", drying_target_moisture_pct=14.0)
        prev = farm.get_inventory().oracle().with_id("o_final_inventory").depends_on(prev)
        aui.send_message_to_user(
            content="玉米全季操作结束；请结合库存、全田收获覆盖和水分记录核实安全入库结果。"
        ).oracle().with_id("o_report").depends_on(prev)
        scenario.events = collect_event_graph(briefing)


def build_maize_establishment(scenario, prev):
    tractor = scenario.get_typed_app(TractorApp)
    farm = scenario.get_typed_app(FarmWorldApp)
    prev = tractor.attach_implement("grader").oracle().with_id("o_attach_grader").depends_on(prev)
    prev = tractor.level().oracle().with_id("o_level_field").depends_on(prev)
    prev = tractor.detach_implement().oracle().with_id("o_detach_grader").depends_on(prev)
    prev = tractor.load_fertilizer(200.0).oracle().with_id("o_load_base_fertilizer").depends_on(prev)
    prev = tractor.base_fertilize(total_kg=200.0).oracle().with_id("o_apply_base_fertilizer").depends_on(prev)
    prev = tractor.attach_implement("furrower").oracle().with_id("o_attach_furrower").depends_on(prev)
    prev = tractor.form_ridges(0.75).oracle().with_id("o_form_single_row_ridges").depends_on(prev)
    prev = tractor.detach_implement().oracle().with_id("o_detach_furrower").depends_on(prev)
    prev = plant_range(tractor, prev, start_ridge=0, end_ridge=63, seed_type="MAIZE_201",
                       spacing_cm=20.0, id_prefix="o_maize")
    prev = farm.commit_daily_physics().oracle().with_id("o_commit_planting").depends_on(prev)
    return prev
