"""Named configuration must preserve geometry, legacy inputs and validation."""
from dataclasses import FrozenInstanceError, asdict
from math import inf, nan

import pytest

from fairy.scenarios.farm_world_diverse.full_season_config import (
    FarmResources,
    FieldLayout,
    SeasonFarmPlan,
    SeasonSettings,
    SoilInitialState,
    WeatherSchedule,
    parse_farm_config,
)


def _nested_config():
    return {
        "farm_id": "maize", "tool_prefix": "Maize", "crop_type": "maize",
        "layout": {"ridge_count": 7, "ridge_length_m": 140, "ridge_width_m": 0.75},
        "planting_start_day": 7,
        "weather": {"drought_days": [50, 75]},
    }


@pytest.mark.parametrize("count,length,width,area", [
    (5, 120, 1.1, 660), (7, 140, 0.75, 735), (9, 100, 1, 900),
    (100, 1000, 1, 100000),
])
def test_cultivated_area_is_derived_from_explicit_geometry(count, length, width, area):
    layout = FieldLayout(ridge_count=count, ridge_length_m=length, ridge_width_m=width)
    assert layout.field_width_m == pytest.approx(count * width)
    assert layout.area_m2 == pytest.approx(area)
    assert layout.area_ha == pytest.approx(area / 10000)
    assert layout.area_mu == pytest.approx(area * 0.0015)


@pytest.mark.parametrize("overrides", [
    {"ridge_count": True}, {"ridge_count": 0}, {"ridge_count": 1.5},
    {"ridge_length_m": 0}, {"ridge_length_m": -1}, {"ridge_length_m": True},
    {"ridge_width_m": inf}, {"ridge_width_m": nan}, {"ridge_width_m": "1.1"},
    {"ridge_length_m": 1e308, "ridge_width_m": 1e308},
])
def test_invalid_geometry_is_rejected(overrides):
    config = {"ridge_count": 5, "ridge_length_m": 120, "ridge_width_m": 1.1}
    with pytest.raises(ValueError):
        FieldLayout(**(config | overrides))


def test_config_is_named_only_frozen_and_keeps_legacy_read_properties():
    with pytest.raises(TypeError):
        FieldLayout(5, 120, 1.1)
    plan = parse_farm_config(_nested_config())
    with pytest.raises(FrozenInstanceError):
        plan.layout.ridge_count = 9
    with pytest.raises(FrozenInstanceError):
        plan.prefix = "Other"
    assert (plan.prefix, plan.num_ridges, plan.length_m, plan.width_m) == ("Maize", 7, 140, .75)
    assert (plan.crop, plan.plant_day, plan.drought_window) == ("maize", 7, (50, 75))
    assert plan.harvest_rain_window is None
    assert (plan.irrigation_quota_mm, plan.fertilizer_quota_kg) == (300, 500)
    assert (plan.mean_temp_c, plan.base_rain_mm, plan.initial_nutrient_index) == (26, 2, .68)


def test_old_flat_cli_config_preserves_defaults_and_all_overrides():
    plan = parse_farm_config({
        "farm_id": "old", "prefix": "Old", "num_ridges": 5, "length_m": 120,
        "plant_day": 7, "drought_window": [40, 68], "harvest_rain_window": [92, 108],
        "irrigation_quota_mm": 250, "fertilizer_quota_kg": 450,
        "mean_temp_c": 25, "base_rain_mm": 1.5, "initial_nutrient_index": .6,
    })
    assert plan.crop_type == "soybean"
    assert plan.layout == FieldLayout(ridge_count=5, ridge_length_m=120, ridge_width_m=1.1)
    assert plan.planting_window_days == 6
    assert plan.weather == WeatherSchedule(
        drought_days=(40, 68), harvest_rain_days=(92, 108),
        mean_temperature_c=25, normal_daily_rain_mm=1.5,
    )
    assert plan.initial_soil.nutrient_index == .6
    assert plan.resources == FarmResources(irrigation_budget_mm=250, fertilizer_budget_kg=450)


def test_parser_supports_typed_nested_objects_and_dataclass_round_trip():
    plan = parse_farm_config(_nested_config())
    assert parse_farm_config(asdict(plan)) == plan
    assert parse_farm_config(_nested_config() | {"layout": plan.layout}) == plan
    assert parse_farm_config(_nested_config() | {"prefix": "Maize", "num_ridges": 7,
                                               "drought_window": (50, 75)}) == plan


@pytest.mark.parametrize("extra", [
    {"prefix": "Other"}, {"num_ridges": 9}, {"crop": "rice"},
    {"plant_day": 8}, {"drought_window": [51, 75]}, {"width_m": 1},
])
def test_conflicting_flat_and_nested_settings_are_rejected(extra):
    with pytest.raises(ValueError, match="Conflicting"):
        parse_farm_config(_nested_config() | extra)


def test_integer_alias_cannot_hide_an_invalid_float_in_nested_layout():
    config = _nested_config()
    config["layout"]["ridge_count"] = 7.0
    config["num_ridges"] = 7
    with pytest.raises(ValueError, match="ridge_count must be an integer"):
        parse_farm_config(config)


@pytest.mark.parametrize("change", [
    {"unknown": 1}, {"layout": {"ridge_counts": 7}},
    {"weather": {"daily_rain": 2}}, {"resources": {"budget": 300}},
    {"initial_soil": {"soil_temp": 20}},
])
def test_unknown_fields_are_not_silently_ignored(change):
    with pytest.raises(ValueError, match="Unknown"):
        parse_farm_config(_nested_config() | change)


def test_new_layout_cannot_silently_reuse_the_old_width_default():
    config = _nested_config()
    del config["layout"]["ridge_width_m"]
    with pytest.raises(ValueError, match="ridge_width_m"):
        parse_farm_config(config)


@pytest.mark.parametrize("factory,change", [
    (SoilInitialState, {"topsoil_vwc": 1.1}),
    (SoilInitialState, {"nutrient_index": 0}),
    (SoilInitialState, {"disease_pressure": True}),
    (WeatherSchedule, {"normal_daily_rain_mm": -1}),
    (WeatherSchedule, {"drought_days": (8, 7)}),
    (WeatherSchedule, {"drought_days": (True, 7)}),
    (WeatherSchedule, {"harvest_rain_days": [7, 8]}),
    (WeatherSchedule, {"workable_every_n_days": 0}),
    (WeatherSchedule, {"solar_radiation_mj_m2_day": nan}),
    (WeatherSchedule, {"daily_temperature_range_c": -1}),
    (WeatherSchedule, {"dry_relative_humidity_pct": 101}),
    (WeatherSchedule, {"rainy_relative_humidity_pct": -1}),
    (WeatherSchedule, {"latitude_deg": 91}),
    (WeatherSchedule, {"sowing_dry_margin_days": True}),
    (WeatherSchedule, {"forcing_buffer_days": -1}),
    (FarmResources, {"irrigation_budget_mm": -1}),
    (FarmResources, {"drying_capacity_kg_per_day": inf}),
    (SeasonSettings, {"start_date": "2026-02-30"}),
    (SeasonSettings, {"start_date": "20260501"}),
    (SeasonSettings, {"start_hour_utc": 24}),
    (SeasonSettings, {"max_days": True}),
    (SeasonSettings, {"max_days": 89}),
    (SeasonSettings, {"monitor_interval_days": 15}),
])
def test_nested_and_season_settings_validate_their_units_and_bounds(factory, change):
    with pytest.raises(ValueError):
        factory(**change)


@pytest.mark.parametrize("change", [
    {"farm_id": ""}, {"tool_prefix": "bad-prefix"}, {"crop_type": "wheat"},
    {"planting_start_day": -1}, {"planting_window_days": False},
    {"layout": {}},
])
def test_typed_farm_plan_rejects_malformed_settings(change):
    settings = dict(farm_id="a", tool_prefix="A", crop_type="soybean",
                    layout=FieldLayout(ridge_count=5, ridge_length_m=120, ridge_width_m=1.1))
    with pytest.raises(ValueError):
        SeasonFarmPlan(**(settings | change))
