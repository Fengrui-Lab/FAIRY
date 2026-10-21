"""Reusable64-ridge WOFOST farm populated from an external complete-season config.

This scenario creates apps and fixed initial conditions only. Policies and
weather are supplied by the caller, e.g. run_wofost_complete_season.py.
"""
from __future__ import annotations

import copy
from dataclasses import replace
from datetime import date, datetime, time, timezone
from fairy.apps.farm_world import FarmWorldApp, WeatherApp, SensorApp, RobotApp
from fairy.apps.farm_world.field_ops_app import FieldOpsApp
from fairy.apps.farm_world.tractor_app import TractorApp
from fairy.apps.system import SystemApp
from fairy.scenarios.scenario import Scenario

class WofostCompleteScenario(Scenario):
    """External JSON configuration, without changing global scenario defaults."""

    def __init__(self, *, complete_config, **kwargs):
        self.complete_config = copy.deepcopy(complete_config)
        kwargs.setdefault("scenario_id", complete_config["scenario_id"])
        kwargs.setdefault("crop_backend", "wofost")
        kwargs.setdefault("crop_backend_options", copy.deepcopy(complete_config["crop_backend_options"]))
        kwargs.setdefault("start_time", datetime.combine(
            date.fromisoformat(complete_config["start_date"]), time(8), timezone.utc).timestamp())
        super().__init__(**kwargs)

    def init_and_populate_apps(self):
        config = self.complete_config
        field, initial = config["field"], config["initial_soil"]
        farm, weather = FarmWorldApp(), WeatherApp()
        farm.set_season_phase("full_season")
        farm.ridge_width_m = field["ridge_width_m"]
        for ridge in farm._ridges:
            ridge.soil_vwc, ridge.soil_temp_c = initial["vwc"], initial["temp_c"]
            ridge.pest_pressure_base = ridge.pest_pressure = 0.0
            ridge.disease_pressure_base = ridge.disease_pressure = 0.0
        farm._inventory.seed_stock[field["seed_type"]] = 600000
        farm._inventory.fertilizer_kg = 1000.0
        farm._inventory.fuel_liters = 1200.0
        farm._inventory.pesticide_liters = 2500.0
        tractor = TractorApp(farm, weather)
        tractor.configure_harvest(max_grain_moisture_pct=config["management"]["harvest_moisture_max_pct"])
        farm.configure_postharvest_market(
            market_moisture_pct=13.0, max_storage_moisture_pct=13.5,
            drying_capacity_kg_per_day=config.get("postharvest", {}).get("drying_capacity_kg_per_day", 10000.0),
            storage_capacity_kg=config.get("postharvest", {}).get("storage_capacity_kg", 20000.0))
        self.apps = [farm, weather, SensorApp(farm), RobotApp(farm, weather, name="Robot0"),
                     tractor, FieldOpsApp(farm, weather), SystemApp()]
        physics = farm.physics
        native_soil = config["crop_backend_options"].get("soil_overrides", {})
        changes = {"root_depth_m": initial["root_depth_m"]}
        for native, reduced in (("SMW", "wilting_point_vwc"), ("SMFCF", "field_capacity_vwc"), ("SM0", "saturation_vwc")):
            if native in native_soil:
                changes[reduced] = native_soil[native]
        physics.soil.params = replace(physics.soil.params, **changes)
