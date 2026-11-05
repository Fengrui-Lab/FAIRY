"""Neutral rotation prompts and isolated, exact late-season weather coverage."""
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.management_extensions.catalog import SCENARIO_IDS
from fairy.scenarios.management_extensions.runtime import WEATHER_EXTENSION_DIR, SEEDS

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "fairy/physics/data/wofost/research/thionville_nasa2019_v1"


def create(sid):
    scene = get_scenario_class(sid)()
    scene.setup()
    return scene, Engine(None, scene)


@pytest.mark.parametrize("sid", SCENARIO_IDS[:2])
@pytest.mark.parametrize("crop", ["maize", "soybean"])
def test_rotation_prompt_exposes_both_paths_without_selecting_the_answer(sid, crop):
    scene, _ = create(sid)
    prompt = scene.scenario_input
    assert prompt == scene.additional_system_prompt
    assert "若选择玉米" in prompt and "若选择大豆" in prompt
    assert "MAIZE_201" in prompt and "SOYBEAN_901" in prompt
    assert "85760粒" in prompt and "514560粒" in prompt
    assert "每1000粒玉米65 DEMO" in prompt and "每6000粒大豆45 DEMO" in prompt
    assert "换种玉米" not in prompt and "继续玉米" not in prompt
    assert "复测SCN仍高" not in prompt
    assert "17218" not in prompt and "7803.40" not in prompt
    assert scene.farm.episode.selection is None
    caps = scene.farm.get_crop_capabilities()
    assert set(caps["candidates"]) == {"maize", "soybean"}
    assert "management_objective" not in caps
    assert "management_objective" not in scene.planning.get_season_context("field")
    receipt = scene.planning.select_crop("field", crop, SEEDS[crop], "preplant-2019")
    assert "error" not in receipt  # Both choices remain executable, without preselection.
    objective = scene.farm.get_crop_capabilities()["management_objective"]
    assert objective["minimum_stored_grain_kg"] == .99*scene.best_tested_yield_kg
    assert objective["maximum_production_cost_minor"] == scene.oracle_cost_minor
    assert scene.farm.crop_type == crop
    assert scene.farm.field_area_m2 == 12864


def test_extension_is_exact_nasa_data_and_does_not_replace_the_base_bundle():
    manifest = json.loads((WEATHER_EXTENSION_DIR / "manifest.json").read_text())
    for kind in ("raw", "weather"):
        raw_bytes = (WEATHER_EXTENSION_DIR / manifest[kind+"_path"]).read_bytes()
        assert hashlib.sha256(raw_bytes).hexdigest() == manifest[kind+"_sha256"]
        assert len(raw_bytes) == manifest[kind+"_byte_count"]
    assert hashlib.sha256((BASE / "weather.json").read_bytes()).hexdigest() == manifest["base_weather_sha256"]
    base = json.loads((BASE / "weather.json").read_text())
    assert base["end_date"] == "2019-11-30"
    raw = json.loads((WEATHER_EXTENSION_DIR / manifest["raw_path"]).read_text())
    normalized = json.loads((WEATHER_EXTENSION_DIR / manifest["weather_path"]).read_text())
    days = [date(2019, 12, 1)+timedelta(days=i) for i in range(38)]
    assert [r["date"] for r in normalized["daily"]] == [d.isoformat() for d in days]
    assert raw["geometry"]["coordinates"] == [6.2, 49.4, 277.87]
    assert raw["header"]["time_standard"] == normalized["time_standard"] == "LST"
    for source, target in manifest["normalization"]["parameter_mapping"].items():
        assert raw["parameters"][source]["units"] == normalized["units"][target]
        for day, row in zip(days, normalized["daily"]):
            assert row[target] == raw["properties"]["parameter"][source][day.strftime("%Y%m%d")]
            assert row[target] != raw["header"]["fill_value"]


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_public_tools_and_final_report_work_through_december_31(sid):
    scene, engine = create(sid)
    if scene.rotation:
        scene.planning.select_crop("field", "maize", "MAIZE_201", "preplant-2019")
    rows = json.loads((BASE / "weather.json").read_text())["daily"]
    rows += json.loads((WEATHER_EXTENSION_DIR / "weather.json").read_text())["daily"]
    expected = {r["date"]: r for r in rows}
    for day in ("2019-11-24", "2019-11-30", "2019-12-01", "2019-12-24", "2019-12-31"):
        target = datetime.fromisoformat(day+"T12:00:00").replace(tzinfo=ZoneInfo("Europe/Paris")).timestamp()
        receipt = scene.system.advance_time(seconds=target-engine.time_manager.time())
        assert receipt["status"] == "ok"
        scene.farm.get_ridge_state(0)
        scene.warehouse.get_inventory()
        scene.tractor.get_status()
        current = scene.weather.get_current_weather()
        assert current["date"] == day
        assert current["rainfall_mm"] == expected[day]["rain_mm"]
        forecast = scene.weather.get_forecast(days=7)["forecast"]
        assert len(forecast) == 7
        for offset, entry in enumerate(forecast, 1):
            forecast_day = (date.fromisoformat(day)+timedelta(days=offset)).isoformat()
            assert entry["date"] == forecast_day
            assert entry["rainfall_mm"] == expected[forecast_day]["rain_mm"]
        report = engine.evaluation_report()
        assert report["validation"]["success"] is False  # Weather extension is not a completion waiver.
    assert "November 30 full-season deadline exceeded" in report["validation"]["message"]
    assert forecast[-1]["date"] == "2020-01-07"


def test_weather_is_available_before_rotation_selection_and_isolated_from_old_scenes():
    from fairy.physics.weather_engine import default_harbin_soybean_config
    scene, _ = create(SCENARIO_IDS[0])
    generator = scene.farm.physics.weather_generator
    assert generator.generate(date(2019, 12, 31), date(2020, 1, 7))[-1].day == date(2020, 1, 7)
    assert scene.farm.episode.selection is None
    old, _ = create("scenario_two_farm_wofost_soybean_maize_full_season")
    assert old.daily_weather[-1]["date"] == "2019-11-30"
    for farm in (old.soybean, old.maize):
        assert date(2019, 12, 1) not in farm.physics.weather_generator._day_overrides
        assert "weather_extension_sha256" not in farm.physics.scenario_metadata
    assert set(default_harbin_soybean_config().monthly) == {5, 6, 7, 8, 9}


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_only_b_scenes_override_october_rain_and_preserve_all_other_weather(sid):
    scene, engine = create(sid)
    rows = json.loads((BASE / "weather.json").read_text())["daily"]
    rows += json.loads((WEATHER_EXTENSION_DIR / "weather.json").read_text())["daily"]
    for selected in (False, True) if scene.rotation else (True,):
        if selected and scene.rotation:
            scene.planning.select_crop("field", "maize", "MAIZE_201", "preplant-2019")
        for row in rows:
            day = date.fromisoformat(row["date"])
            actual = scene.farm.physics.weather_generator.generate(day, day)[0]
            dry = scene.rotation and day.year == 2019 and day.month == 10
            assert actual.rain_mm == (0. if dry else row["rain_mm"])
            assert actual.air_temp_min_c == row["tmin_c"]
            assert actual.air_temp_max_c == row["tmax_c"]
            assert actual.relative_humidity_pct == row["relative_humidity_pct"]
            assert actual.wind_ms == row["wind_2m_m_s"]
            assert actual.solar_rad_mj_m2 == row["shortwave_mj_m2_day"]
    target = datetime(2019, 9, 30, 12, tzinfo=ZoneInfo("Europe/Paris")).timestamp()
    scene.system.advance_time(seconds=target-engine.time_manager.time())
    forecast = scene.weather.get_forecast(days=7)["forecast"]
    expected = {r["date"]: r["rain_mm"] for r in rows}
    assert all(e["rainfall_mm"] == (0. if scene.rotation else expected[e["date"]]) for e in forecast)
    scene.system.advance_time(days=1)
    assert scene.weather.get_current_weather()["rainfall_mm"] == (0. if scene.rotation else expected["2019-10-01"])
    saved = scene.farm.get_state()
    scene.farm.load_state(saved)
    assert scene.farm.episode.rain_free_october == scene.rotation
    assert scene.farm.physics.weather_generator.generate(date(2019, 10, 15), date(2019, 10, 15))[0].rain_mm == (0. if scene.rotation else expected["2019-10-15"])
