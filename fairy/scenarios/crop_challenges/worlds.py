"""Fixed synthetic worlds. All disturbances are independent of reference actions."""
from datetime import date, timedelta

from fairy.scenarios.maize.maize_scenario_catalog import MaizeScenarioSpec


def maize_spec(name):
    water = name in {"zonal_water_priority", "compound_water_n_limit", "staggered_water_priority", "rain_aware_irrigation"}
    return MaizeScenarioSpec(name, "玉米分区决策挑战", precipitation_factor=.85 if water else 1.,
        initial_available_n_kg_ha=40., base_soil_n_kg_ha=40.,
        fertilizer_stock_kg=440., fertilizer_quota_kg=440.,
        irrigation_quota_mm=300. if name == "rain_aware_irrigation" else 100. if water else 180.,
        topdress_kg=0., harvest_day=150)


def init_maize(scenario):
    from fairy.apps.farm_world import FarmWorldApp
    from fairy.physics.soil_engine import SoilHydraulicModifier
    from fairy.scenarios.maize.maize_scenario_helpers import init_maize_apps
    from fairy.scenarios.wofost_events import SoilNitrogenEvent, install_scenario_events
    init_maize_apps(scenario, scenario.spec)
    farm = scenario.get_typed_app(FarmWorldApp)
    name = scenario.definition.name
    start = date.fromisoformat(scenario.spec.start_date)
    from zoneinfo import ZoneInfo
    farm.simulation_timezone = ZoneInfo("Asia/Shanghai")
    farm._sim_date = start.isoformat()
    generator = farm.physics.weather_generator
    # Pin the entire forcing once. Forecasts and actual integrations use the
    # same dates, independent of the agent's selected operation sequence.
    trace = generator.generate(start, start + timedelta(days=190), farm.physics.profile.weather_events)
    for index, w in enumerate(trace):
        rain = w.rain_mm
        if name in {"zonal_water_priority", "compound_water_n_limit", "staggered_water_priority"} and 40 <= index <= 65:
            rain = 0.
        if name == "rain_aware_irrigation":
            if 22 <= index <= 80:
                rain = 0.
            if index in (42, 43, 68):
                rain = 30.
        if name == "rainy_harvest_window" and 112 <= index <= 145:
            rain = 12. if index % 8 < 5 else 0.
        generator.set_day_override(start + timedelta(days=index), w.air_temp_mean_c, rain,
            w.wind_ms, w.solar_rad_mj_m2, w.air_temp_min_c, w.air_temp_max_c,
            weather_tags=["synthetic_crop_challenge_v1"], relative_humidity_pct=w.relative_humidity_pct)
    if name in {"zonal_water_priority", "compound_water_n_limit"}:
        zones = list(range(22)) + (list(range(44, 54)) if name == "compound_water_n_limit" else [])
        farm.physics.soil.set_hydraulic_modifiers({rid: SoilHydraulicModifier(
            root_depth_m=.25, field_capacity_vwc=.24, max_infiltration_mm_day=45.) for rid in zones})
    if name in {"zonal_nitrogen_recovery", "compound_water_n_limit"}:
        end = 53 if name == "compound_water_n_limit" else 43
        install_scenario_events(scenario, [SoilNitrogenEvent("local_n_pool_disturbance", farm.farm_id,
            22, end, start + timedelta(days=22), available_n_kg_ha=0., reserve_n_kg_ha=1.)])


def rice_configuration(name):
    from fairy.apps.paddy.models import PaddyField
    field = PaddyField().to_dict()
    weather = {"rain_mm": 1., "overrides": {}}
    if name == "zonal_water_n_allocation":
        field["plots"][0]["soil"].update(NAVAILI=1., NSOILBASE=2.)
        field["plots"][1]["soil"].update(NAVAILI=60., NSOILBASE=80.,
            puddled_sope_cm_day=2., puddled_ksub_cm_day=.5)
        field["fertilizer_kg"] = 75.
        field["channels"][0]["quota_m3"] = 1900.
        weather["rain_mm"] = 0.
    elif name == "infrastructure_water_priority":
        field["plots"][0]["bund_leak_mm_day"] = 8.
        field["plots"][1]["soil"]["initial_vwc"] = .24
        field["channels"][0].update(blockage_fraction=.6, flow_m3_hour=80., open_hour=6, close_hour=10, quota_m3=1800.)
        weather["rain_mm"] = 0.
    elif name == "zonal_crop_protection":
        field["plots"][0].update(pests=.45, disease=.02, weeds=.02)
        field["plots"][1].update(pests=.02, disease=.4, weeds=.35)
        field.update(insecticide_liters=1.2, fungicide_liters=1.5)
        for day in (12, 13, 14, 27, 28, 29):
            weather["overrides"][(date(2026, 1, 1) + timedelta(days=day)).isoformat()] = {"rain_mm": 12., "wind_ms": 7.}
    elif name == "rainy_harvest_capacity":
        field["machines"][2]["grain_capacity_wet_kg"] = 600.
        field["drying_capacity_wet_kg_day"] = 1800.
        field["electricity_kwh"] = 400.
        for day in range(85, 111):
            if day % 7 < 4:
                weather["overrides"][(date(2026, 1, 1) + timedelta(days=day)).isoformat()] = {"rain_mm": 25.}
    else:
        raise ValueError(f"Unknown rice challenge {name}")
    return field, weather
