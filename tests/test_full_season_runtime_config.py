"""配置声明必须实际作用于地块、局地天气和共享时钟。"""
from datetime import date, datetime, timezone

import pytest

from fairy.scenarios.farm_world_diverse.full_season_config import SeasonSettings
from fairy.scenarios.farm_world_diverse.full_season_runtime import FullSeasonMultiFarmScenario


def test_nested_configuration_drives_real_initial_state_and_local_weather():
    class CustomSeason(FullSeasonMultiFarmScenario):
        season_settings = SeasonSettings(
            start_date="2026-06-02", start_hour_utc=3,
            max_days=120, monitor_interval_days=3,
        )

    first = {
        "farm_id": "a", "tool_prefix": "A", "crop_type": "maize",
        "layout": {"ridge_count": 2, "ridge_length_m": 80, "ridge_width_m": 0.75},
        "planting_start_day": 3, "planting_window_days": 4,
        "initial_soil": {
            "topsoil_vwc": 0.31, "soil_temperature_c": 21,
            "nutrient_index": 0.73, "pest_pressure": 0.02, "disease_pressure": 0.03,
        },
        "resources": {
            "irrigation_budget_mm": 210, "fertilizer_budget_kg": 80,
            "drying_capacity_kg_per_day": 700, "storage_capacity_kg": 1400,
        },
        "weather": {
            "mean_temperature_c": 25, "daily_temperature_range_c": 10,
            "normal_daily_rain_mm": 3, "workable_every_n_days": 4,
            "sowing_dry_margin_days": 0, "drought_days": [5, 7],
            "harvest_rain_days": [6, 6], "harvest_rain_mm": 12,
            "late_dry_from_day": 8, "wind_speed_m_s": 1.5,
            "solar_radiation_mj_m2_day": 14, "latitude_deg": 35,
            "dry_relative_humidity_pct": 60, "rainy_relative_humidity_pct": 90,
            "rainy_humidity_threshold_mm": 6, "initial_station_rain_mm": 2,
            "forcing_buffer_days": 3,
        },
    }
    second = {"farm_id": "b", "prefix": "B", "num_ridges": 3, "length_m": 100}
    scenario = CustomSeason(farm_configs=[first, second])
    scenario.setup()

    assert scenario.start_time == datetime(2026, 6, 2, 3, tzinfo=timezone.utc).timestamp()
    assert scenario.duration == 120 * 86400
    assert scenario.monitor_interval_days == 3
    site = scenario.fleet.get("a")
    state = site.farm.get_state()
    assert state["field_area_m2"] == 120
    assert state["management_regime"]["irrigation_quota_mm_total"] == 210
    assert state["management_regime"]["fertilizer_quota_kg"] == 80
    assert state["postharvest_market"]["drying_capacity_kg_per_day"] == 700
    assert state["postharvest_market"]["storage_capacity_kg"] == 1400
    window = state["planting_windows"][0]
    assert {key: window[key] for key in ("start", "end", "earliest_date", "latest_date")} == {
        "start": 0, "end": 1, "earliest_date": "2026-06-05", "latest_date": "2026-06-08",
    }
    for ridge in state["ridges"]:
        assert ridge["soil_vwc"] == 0.31
        assert ridge["soil_temp_c"] == 21
        assert ridge["nutrient_index"] == 0.73
        assert ridge["pest_pressure"] == 0.02
        assert ridge["disease_pressure"] == 0.03
        assert not ridge["planted"]

    forcing = site.farm.physics.weather_generator._day_overrides
    assert len(forcing) == 123
    assert forcing[date(2026, 6, 4)].rain_mm == 3      # 常雨
    assert forcing[date(2026, 6, 5)].rain_mm == 0      # 播种日
    assert forcing[date(2026, 6, 6)].rain_mm == 0      # 定期作业日
    assert forcing[date(2026, 6, 7)].rain_mm == 0      # 干旱首日
    assert forcing[date(2026, 6, 8)].rain_mm == 12     # 收获雨优先于干旱
    assert forcing[date(2026, 6, 11)].rain_mm == 0     # 晚季停雨
    rainy_day = forcing[date(2026, 6, 8)]
    assert (rainy_day.air_temp_min_c, rainy_day.air_temp_max_c) == (20, 30)
    assert rainy_day.relative_humidity_pct == 90
    assert rainy_day.solar_rad_mj_m2 == 14
    assert site.farm.physics.latitude_deg == 35
    assert "120 m² (0.012 ha; 0.18 mu)" in scenario.scenario_input

    # A 的自定义土壤、资源和天气不会覆盖 B。
    other = scenario.fleet.get("b")
    assert other.farm._ridges[0].soil_vwc == 0.26
    assert other.farm.get_state()["management_regime"]["irrigation_quota_mm_total"] == 300
    assert other.farm.physics.weather_generator._day_overrides[date(2026, 6, 4)].rain_mm == 2


def test_legacy_flat_and_nested_configs_create_identical_farm_physics():
    legacy = [
        {"farm_id": "soy", "prefix": "Soy", "num_ridges": 5, "length_m": 120},
        {
            "farm_id": "maize", "prefix": "Maize", "crop": "maize",
            "num_ridges": 7, "length_m": 140, "width_m": 0.75,
            "plant_day": 7, "drought_window": (50, 75),
        },
    ]
    nested = [
        {
            "farm_id": "soy", "tool_prefix": "Soy", "crop_type": "soybean",
            "layout": {"ridge_count": 5, "ridge_length_m": 120, "ridge_width_m": 1.1},
        },
        {
            "farm_id": "maize", "tool_prefix": "Maize", "crop_type": "maize",
            "layout": {"ridge_count": 7, "ridge_length_m": 140, "ridge_width_m": 0.75},
            "planting_start_day": 7, "planting_window_days": 6,
            "weather": {"drought_days": [50, 75]},
        },
    ]
    old_style = FullSeasonMultiFarmScenario(farm_configs=legacy)
    new_style = FullSeasonMultiFarmScenario(farm_configs=nested)
    old_style.setup()
    new_style.setup()
    assert old_style._initial_states == new_style._initial_states
    assert old_style._initial_inventories == new_style._initial_inventories
    for old_site, new_site in zip(old_style.fleet.sites, new_style.fleet.sites):
        assert (
            old_site.farm.physics.weather_generator._day_overrides
            == new_site.farm.physics.weather_generator._day_overrides
        )


def test_oracle_clone_preserves_resolved_constructor_overrides():
    configs = [
        {"farm_id": "a", "prefix": "A", "num_ridges": 3, "length_m": 100},
        {"farm_id": "b", "prefix": "B", "num_ridges": 5, "length_m": 120},
    ]
    scenario = FullSeasonMultiFarmScenario(
        farm_configs=configs, season_length_days=160,
        monitor_interval_days=4, seed=7, detailed_briefing=False,
        crop_backend_options={"example": "retained until backend setup"},
    )
    clone = scenario.oracle_clone()
    assert clone.season_length_days == 160
    assert clone.monitor_interval_days == 4
    assert clone.seed == 7
    assert clone.detailed_briefing is False
    assert clone.crop_backend_options == scenario.crop_backend_options
    assert clone.crop_backend_options is not scenario.crop_backend_options
    assert clone.farm_plans == scenario.farm_plans
    assert clone.start_time == pytest.approx(scenario.start_time)
    assert not clone.apps
