from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timezone, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from fairy.apps.farm_world.assets import AssetSpec
from fairy.apps.farm_world.multi_farm import FarmSite, FarmFleet
from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs
from fairy.apps.farm_world.runtime_state import restore_runtime, snapshot_runtime
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.physics.weather_engine import WeatherGenerator, default_harbin_soybean_config
from fairy.scenarios.workflow import Workflow, WorkflowStep
from fairy.time_manager import TimeManager
from fairy.tool_execution import WorkflowBundle, ToolExecutionError


def _world(*, generator=True, shared=True, ridges=12):
    station = WeatherApp() if shared else None
    sites = [FarmSite.create(name, name.title(), create_devices=False,
                            weather_app=station, station_id="common" if shared else name,
                            num_ridges=ridges, field_length_m=80)
             for name in ("north", "south")]
    fleet = FarmFleet(sites, shared_tools=True, seed=33,
                      assets=[AssetSpec(f"{kind}_1", kind, ("north", "south"))
                              for kind in ("tractor", "drone", "robot")])
    clock = TimeManager()
    clock.reset(datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp())
    fleet.runtime.bind_clock(clock)
    clock.register_offset_observer("runtime:0", fleet.runtime.before_advance, fleet.runtime.advance_to)
    for site in sites:
        site.weather.set_weather("2026-05-01", 25, 55, 2, 0, 400)
        if generator:
            site.farm.physics.weather_generator = WeatherGenerator(default_harbin_soybean_config(), seed=17)
    return fleet.runtime


def test_same_station_rejects_different_future_forcing_before_any_call():
    runtime = _world()
    for fid, rain in (("north", 0), ("south", 20)):
        runtime.farms[fid].farm.physics.set_weather_day_override(date(2026, 5, 2), 26, rain, 2, 15)
    with pytest.raises(ValueError, match="Conflicting weather forcing"):
        runtime.freeze()
    assert runtime.executor.history == []


def test_one_station_generates_a_date_once_and_all_consumers_use_native_precision(monkeypatch):
    runtime = _world()
    generated = Counter()
    original_generate = WeatherGenerator.generate
    def counted(generator, *args, **kwargs):
        generated[kwargs["start_date"]] += 1
        return original_generate(generator, *args, **kwargs)
    monkeypatch.setattr(WeatherGenerator, "generate", counted)
    day = date(2026, 5, 2)
    for site in runtime.farms.values():
        site.farm.physics.set_weather_day_override(day, 20.123456, 7.123456, 2.123456, 15.123456,
                                                   air_temp_min_c=11.123456, air_temp_max_c=29.876543,
                                                   relative_humidity_pct=67.123456)
    runtime.freeze()
    runtime.clock.set_offset(86400)
    station = runtime.stations["common"]
    updates = []
    original_set = station.set_weather
    def update(**kwargs):
        updates.append(kwargs["date"])
        return original_set(**kwargs)
    monkeypatch.setattr(station, "set_weather", update)
    values = [_build_weather_inputs(runtime.context(fid).weather, day, runtime.farms[fid].farm.physics)
              for fid in ("north", "south", "north")]
    assert updates == [day.isoformat()]
    assert values[0] == values[1] == values[2]
    assert values[0]["soil"].air_temp_min_c == 11.123456
    assert values[0]["soil"].air_temp_max_c == 29.876543
    assert values[0]["soil"].rain_mm == 7.123456
    assert values[0]["humidity_pct"] == 67.123456
    assert all(count == 1 for count in generated.values())
    assert station.get_current_weather_snapshot()["rainfall_mm"] == round(7.123456, 2)


def test_active_engines_cross_dates_without_rolling_back_public_station(monkeypatch):
    from fairy.physics.soil_engine import SoilEngine
    runtime = _world()
    for site in runtime.farms.values():
        for offset in range(4):
            day = date(2026, 5, 1) + timedelta(days=offset)
            site.farm.physics.set_weather_day_override(day, 20.123456, 2.123456, 2, 15,
                                                       air_temp_min_c=11.123456, air_temp_max_c=29.876543)
        site.farm.set_ridge_planted(0, "STANDARD", 8)
    runtime.freeze()
    observed = []
    original = SoilEngine.update_day
    def record(engine, weather, *args, **kwargs):
        observed.append((weather.day, weather.air_temp_min_c, weather.air_temp_max_c, weather.rain_mm))
        return original(engine, weather, *args, **kwargs)
    monkeypatch.setattr(SoilEngine, "update_day", record)
    runtime.clock.add_offset(2 * 86400)
    station = runtime.stations["common"]
    assert station.get_current_weather_snapshot()["date"] == "2026-05-03"
    assert observed and all(item[1:] == (11.123456, 29.876543, 2.123456) for item in observed)
    assert Counter(item[0] for item in observed) == {date(2026, 5, 2): 2, date(2026, 5, 3): 2}
    # An old uncached day must not change the public current observation.
    runtime.weather_inputs("common", date(2026, 4, 30))
    assert station.get_current_weather_snapshot()["date"] == "2026-05-03"


def test_shared_station_ignores_field_moisture_for_identity_and_public_weather():
    sites = []
    for name, water in (("north", .2), ("south", .45)):
        station = WeatherApp()
        station.name = f"{name}Station"
        station.set_avg_soil_vwc(water)
        sites.append(FarmSite.create(name, name.title(), create_devices=False,
                                     station_id="common", weather_app=station, num_ridges=2))
    runtime = FarmFleet(sites, shared_tools=True).runtime
    runtime.freeze()
    weather = next(app for app in runtime.apps if app.name == "Weather")
    result = weather.get_current_weather(farm_id="north")
    assert result["ok"]
    assert "avg_soil_vwc" not in result["data"] and "is_trafficable" not in result["data"]
    protocol = runtime.describe_environment()["response_contract"]
    assert "Weather__get_current_weather" in protocol["applies_to"]
    assert "Weather__expert_agent" not in protocol["applies_to"]
    assert "SystemApp" in protocol["legacy_exceptions"]
    assert "unknown" in protocol["errors"]["partial_effects"]


def test_station_rng_and_daily_cache_roundtrip_before_next_unseen_date():
    runtime = _world()
    runtime.freeze()
    runtime.weather_inputs("common", date(2026, 5, 2))
    checkpoint = json.loads(json.dumps(snapshot_runtime(runtime), allow_nan=False))
    restored = restore_runtime(checkpoint)
    day = date(2026, 5, 20)  # beyond the previously generated seven-day forecast
    assert restored.weather_inputs("common", day) == runtime.weather_inputs("common", day)
    assert restored.registry.manifest == runtime.registry.manifest
    assert restored._station_forcing["common"]["generator"] is not runtime._station_forcing["common"]["generator"]


def test_actual_physics_parameters_and_forcing_are_in_initial_fingerprint():
    baseline, changed = _world(shared=False), _world(shared=False)
    physics = changed.farms["north"].farm.physics
    physics.soil.params = replace(physics.soil.params, field_capacity_vwc=.34)
    baseline.freeze(); changed.freeze()
    assert baseline.registry.manifest["scenario_config_fingerprint"] != changed.registry.manifest["scenario_config_fingerprint"]
    other = _world(shared=False)
    other.farms["north"].farm.physics.set_weather_day_override(date(2026, 5, 20), 28, 0, 3, 20)
    other.freeze()
    assert other.registry.manifest["scenario_config_fingerprint"] != baseline.registry.manifest["scenario_config_fingerprint"]


def test_shared_initial_fingerprint_is_stable_across_python_hash_seeds():
    source = """
from fairy.apps.farm_world.assets import AssetSpec
from fairy.apps.farm_world.multi_farm import FarmSite,FarmFleet
sites=[FarmSite.create(n,n.title(),create_devices=False,num_ridges=2) for n in ('north','south')]
fleet=FarmFleet(sites,shared_tools=True,seed=33,assets=[AssetSpec('drone_1','drone',('north','south'))])
for s in sites:s.farm.physics.set_weather_day_override(__import__('datetime').date(2026,5,1),26,2,2,15)
fleet.runtime.freeze()
print(fleet.runtime.registry.manifest['scenario_config_fingerprint'])
"""
    results = []
    for seed in ("17", "91"):
        result = subprocess.run([sys.executable, "-c", source], check=True, capture_output=True, text=True,
                                cwd=Path(__file__).resolve().parents[1], env={**os.environ, "PYTHONHASHSEED": seed})
        results.append(result.stdout.strip())
    assert results[0] == results[1]


def test_whole_workflow_preflight_rejects_later_invalid_target_before_first_write():
    runtime = _world(generator=False)
    runtime.freeze()
    workflow = Workflow()
    workflow.add_node(WorkflowStep(name="load", tool_name="Tractor__load_seeds",
                                  tool_args={"farm_id": "north", "asset_id": "tractor_1",
                                             "seed_type": "STANDARD", "count": 30}))
    workflow.add_node(WorkflowStep(name="bad_plant", depends_on=["load"], tool_name="Tractor__plant_seeds",
                                  tool_args={"farm_id": "north", "asset_id": "tractor_1",
                                             "start_ridge": 11, "end_ridge": 12, "depth_cm": 4, "seed_spacing_cm": 8}))
    before = deepcopy(runtime.farms["north"].farm._inventory.to_dict())
    with pytest.raises(ToolExecutionError, match="range"):
        WorkflowBundle(workflow, runtime.registry.manifest).validate(runtime.registry)
    assert before == runtime.farms["north"].farm._inventory.to_dict()
    assert runtime.assets["tractor_1"].data["_seed_hopper"] == 0
    assert runtime.executor.history == []


@pytest.mark.parametrize("tool,args", [
    ("Tractor__plant_seeds", {"start_ridge": 0, "end_ridge": 4, "depth_cm": 4, "seed_spacing_cm": 8}),
    ("Tractor__plant_seeds", {"start_ridge": 0, "end_ridge": 0, "depth_cm": 9, "seed_spacing_cm": 8}),
    ("Tractor__load_seeds", {"seed_type": "MAIZE_STANDARD", "count": 20}),
    ("FieldOps__apply_pesticide_manual", {"start_ridge": 0, "end_ridge": 2}),
])
def test_static_joint_constraints_reject_without_operations(tool, args):
    runtime = _world(generator=False)
    runtime.freeze()
    args = {"farm_id": "north", **args}
    if tool.startswith("Tractor"):
        args["asset_id"] = "tractor_1"
    with pytest.raises(ToolExecutionError):
        runtime.registry.validate_static(tool, args)
    assert not runtime.executor.history


def test_robot_and_drone_large_requests_keep_actual_partial_or_multi_pass_semantics():
    runtime = _world(generator=False)
    runtime.freeze()
    runtime.registry.validate_static("Robot__inspect_pests", {"farm_id": "north", "asset_id": "robot_1",
                                                             "start_ridge": 0, "end_ridge": 11})
    runtime.registry.validate_static("Drone__fly_survey", {"farm_id": "north", "asset_id": "drone_1",
                                                          "start_ridge": 0, "end_ridge": 11})
