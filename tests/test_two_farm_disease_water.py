"""Independent full season: A disease management, B local seed-fill irrigation.

Configuration checks protect regional-weather and farm ownership boundaries.
Completion checks run the public Oracle and replay a saved reference from a
fresh scene; an empty scenario validator is not completion evidence.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time, timedelta
import hashlib
import json
from zoneinfo import ZoneInfo

import pytest

from fairy.agents.agent.toolset_builder import build_toolset
from fairy.controllers.engine import Engine
from fairy.physics.profiles import get_profile
from fairy.physics.weather_engine import WeatherGenerator
from fairy.apps.farm_world.physics_orchestrator import _generate_weather_day
from fairy.scenarios.registry import get_scenario_class, list_scenarios
from fairy.scenarios.workflow import Workflow
from fairy.time_manager import SimulationTimeManager


SCENE = "scenario_two_farm_full_season_hn84_disease_water"
PROFILE = "harbin_l3_disease_then_drought_recovery_seed_1628"
FARMS = {"farm_a", "farm_b"}
RIDGES = set(range(64))
TARGET = set(range(20, 40))
RANDOM_ID_FIELDS = {"action_id", "op_id", "mission_id", "inspection_id"}


def scene():
    scenario = get_scenario_class(SCENE)()
    scenario.setup()
    return scenario, Engine(None, scenario)


def raw_initial_state(scenario):
    return deepcopy({
        "farms": {
            farm.farm_id: {
                "ridges": [ridge.to_dict() for ridge in farm._ridges],
                "regime": farm._management_regime.to_dict(),
                "last_physics_time": farm.physics.last_physics_sim_time,
                "prep": farm.completed_prep_ops,
            }
            for farm in (scenario.farm_a, scenario.farm_b)
        },
        "warehouse": scenario.warehouse.get_state(),
        "devices": [app.get_state() for app in scenario.shared_equipment],
        "clock": scenario.farm_environment.time_manager.time(),
    })


def exported(scenario, engine):
    return engine.run_scenario_oracle(run_oracle=False)


def clean_ids(value):
    if is_dataclass(value):
        return clean_ids(asdict(value))
    if isinstance(value, dict):
        return {key: clean_ids(item) for key, item in value.items() if key not in RANDOM_ID_FIELDS}
    if isinstance(value, (list, tuple)):
        return [clean_ids(item) for item in value]
    return value


def final_state(scenario):
    scenario.farm_environment.sync()
    return clean_ids({
        "farms": {
            world.farm_id: {
                "world": world.get_state(),
                "engines": {name: getattr(world.physics, name).states for name in (
                    "soil", "phenology", "canopy", "management", "biotic", "yield_recovery",
                )},
                "actions": world.physics.action_log,
                "last_physics_time": world.physics.last_physics_sim_time,
            }
            for world in (scenario.farm_a, scenario.farm_b)
        },
        "warehouse": scenario.warehouse.get_state(),
        "devices": {app.name: app.get_state() for app in scenario.shared_equipment},
        "fixed": {app.name: app.get_state() for app in (
            scenario.sensor_a, scenario.sensor_b, scenario.irrigation_a, scenario.irrigation_b,
        )},
        "clock": scenario.farm_environment.time_manager.time(),
    })


def test_same_regional_weather_has_independent_profiles_and_does_not_modify_registry():
    registered = get_profile(PROFILE)
    assert registered is not None
    registry_before = deepcopy(registered)
    scenario, _ = scene()
    a, b = scenario.farm_a.physics.profile, scenario.farm_b.physics.profile
    assert a is not b and a is not registered and b is not registered
    assert a.biotic_outbreaks == b.biotic_outbreaks == []
    assert a.biotic_outbreaks is not b.biotic_outbreaks
    assert a.rng_seed == b.rng_seed == 1628
    assert a.weather_events == b.weather_events
    local_rain = [event for event in a.weather_events if event.event_type == "rain_event"]
    registry_rain = [event for event in registered.weather_events if event.event_type == "rain_event"]
    assert len(local_rain) == 4 and len(registry_rain) == 1
    assert registry_rain[0].total_rain_mm == 72.0
    assert all(event.duration_days == 1 and event.total_rain_mm == 18.0 for event in local_rain)
    assert [event.start_date for event in local_rain] == [
        registry_rain[0].start_date + timedelta(days=offset) for offset in range(4)
    ]
    assert sum(event.total_rain_mm for event in local_rain) == 72.0
    assert [event for event in a.weather_events if event.event_type != "rain_event"] == [
        event for event in registered.weather_events if event.event_type != "rain_event"
    ]
    assert a.monthly_climate == b.monthly_climate == registered.monthly_climate
    assert registered == registry_before


def test_declared_daily_rain_preserves_the_existing_complete_weather_sequence():
    scenario, _ = scene()
    profile = scenario.farm_a.physics.profile
    generator = WeatherGenerator(profile.to_weather_generator_config(), seed=profile.rng_seed)
    first, last = date(2026, 5, 5), date(2026, 10, 31)
    trace = [
        asdict(_generate_weather_day(generator, first + timedelta(days=offset), profile.weather_events))
        for offset in range((last - first).days + 1)
    ]
    encoded = json.dumps(trace, sort_keys=True, default=str, separators=(",", ":")).encode()
    # Captured from this scene's actual daily weather before the total-rain
    # bug was fixed; all dates, temperatures, radiation, tags and rain match.
    assert hashlib.sha256(encoded).hexdigest() == "ea6e412e06856a0aa339907add80ab94df83a97443156a71891f5f8c714c7cd0"
    assert sum(day["rain_mm"] for day in trace if day["day"].month == 6) == pytest.approx(140.33)


def test_initial_disease_history_and_local_hydraulics_define_different_farms():
    scenario, _ = scene()
    a, b = scenario.farm_a, scenario.farm_b
    for ridge_id in RIDGES:
        assert a._ridges[ridge_id].disease_pressure_base == pytest.approx(0.20 if ridge_id in TARGET else 0.02)
        assert b._ridges[ridge_id].disease_pressure_base == pytest.approx(0.02)
        a_params = a.physics.soil.params_for_ridge(ridge_id)
        b_params = b.physics.soil.params_for_ridge(ridge_id)
        assert a_params == a.physics.soil.params_for_ridge(0)
        if ridge_id in TARGET:
            assert b_params.field_capacity_vwc < a_params.field_capacity_vwc
            assert b_params.root_depth_m < a_params.root_depth_m
        else:
            assert b_params == a_params
    for world in (a, b):
        assert world._management_regime.irrigation_quota_mm_total == 15
        assert world._management_regime.max_fungicide_applications == 1
        assert not any(ridge.planted for ridge in world._ridges)


def test_fixed_systems_are_per_farm_and_mobile_schema_targets_the_shared_directory():
    scenario, engine = scene()
    assert set(scenario.farm_environment.farms) == FARMS
    assert isinstance(engine.time_manager, SimulationTimeManager)
    assert scenario.farm_environment.warehouse is scenario.warehouse
    assert sum(app is scenario.warehouse for app in scenario.apps) == 1
    assert scenario.sensor_a is not scenario.sensor_b
    assert scenario.irrigation_a is not scenario.irrigation_b
    assert scenario.sensor_a._soil_sensors is not scenario.sensor_b._soil_sensors
    assert scenario.shared_equipment == [scenario.tractor, scenario.mavic, scenario.matrice, scenario.robot]
    assert len({id(app) for app in scenario.shared_equipment}) == 4
    assert all(app.time_manager is engine.time_manager for app in scenario.apps)
    _, schemas, _ = build_toolset(scenario.apps)
    functions = {entry["function"]["name"]: entry["function"] for entry in schemas}
    for prefix, farm_id in (("FarmA", "farm_a"), ("FarmB", "farm_b")):
        for tool in (f"{prefix}_Sensor__read_soil_sensors", f"{prefix}_Irrigation__irrigate"):
            assert tool in functions
            assert "farm_id" not in functions[tool]["parameters"]["properties"]
            assert f"Bound farm: {farm_id}" in functions[tool]["description"]
        assert f"{prefix}__get_management_status" in functions
        for method in ("get_inventory", "dry_grain", "store_grain"):
            assert f"{prefix}__{method}" not in functions
    assert {"Warehouse__get_inventory", "Warehouse__get_grain_batches",
            "Warehouse__dry_grain", "Warehouse__store_grain"} <= functions.keys()
    for method in ("load_fungicide", "load_seeds", "load_fertilizer", "refuel", "return_supplies", "unload_grain"):
        assert "farm_id" not in functions[f"Tractor__{method}"]["parameters"]["properties"]
    for tool in ("Tractor__apply_fungicide", "Tractor__harvest", "Matrice4T__fly_survey", "Robot0__inspect_crop_health"):
        properties = functions[tool]["parameters"]["properties"]
        assert set(properties["farm_id"]["enum"]) == FARMS
        assert "farm_id" in functions[tool]["parameters"]["required"]


def test_reference_is_complete_exportable_and_capture_has_no_effects(tmp_path):
    assert SCENE in list_scenarios()
    scenario, engine = scene()
    before = raw_initial_state(scenario)
    workflow = exported(scenario, engine)
    assert raw_initial_state(scenario) == before
    assert workflow.dag
    path = tmp_path / "reference.json"
    workflow.save_workflow(str(path))
    assert Workflow.load_workflow(str(path)).to_dict() == workflow.to_dict()
    assert len(workflow) == len(scenario.events)
    seen = set()
    for name, step in workflow.dag.items():
        assert name and not name.startswith("step")
        assert name not in seen and set(step.depends_on) <= seen
        seen.add(name)
    for farm_id in FARMS:
        for operation in ("plant_seeds", "harvest"):
            passes = [step for step in workflow.dag.values()
                      if step.tool_name == f"Tractor__{operation}" and step.tool_args["farm_id"] == farm_id]
            assert Counter(ridge for step in passes for ridge in range(
                step.tool_args["start_ridge"], step.tool_args["end_ridge"] + 1,
            )) == {ridge: 1 for ridge in RIDGES}
            assert all(step.tool_args["end_ridge"] - step.tool_args["start_ridge"] + 1 <= 4 for step in passes)


def test_reference_observes_real_four_ridge_samples_and_treats_only_the_intended_farm():
    scenario, engine = scene()
    steps = list(exported(scenario, engine).dag.values())
    ground = [step for step in steps if step.tool_name.startswith("Robot0__inspect_")]
    assert ground and {step.tool_args["farm_id"] for step in ground} == FARMS
    assert all(1 <= step.tool_args["end_ridge"] - step.tool_args["start_ridge"] + 1 <= 4 for step in ground)
    fungicide = [step for step in steps if step.tool_name == "Tractor__apply_fungicide"]
    assert len(fungicide) == 2
    assert all(step.tool_args["farm_id"] == "farm_a" for step in fungicide)
    assert Counter(ridge for step in fungicide for ridge in range(
        step.tool_args["start_ridge"], step.tool_args["end_ridge"] + 1,
    )) == {ridge: 1 for ridge in TARGET}
    assert sum((step.tool_args["end_ridge"] - step.tool_args["start_ridge"] + 1)
               * step.tool_args["liters_per_ridge"] for step in fungicide) == pytest.approx(76)
    irrigation = [step for step in steps if step.tool_name.endswith("_Irrigation__irrigate")]
    assert len(irrigation) == 2
    assert all(step.tool_name == "FarmB_Irrigation__irrigate" for step in irrigation)
    assert all(set(range(step.tool_args["start"], step.tool_args["end"] + 1)) == TARGET
               and step.tool_args["hours"] == 4 for step in irrigation)


@pytest.fixture(scope="module")
def full_execution(tmp_path_factory):
    output = tmp_path_factory.mktemp("disease_water_reference")
    source, export_engine = scene()
    reference = exported(source, export_engine)
    initial = raw_initial_state(source)
    path = output / "reference.json"
    reference.save_workflow(str(path))
    direct, oracle_engine = scene()
    oracle = oracle_engine.run_scenario_oracle(run_oracle=True)
    fresh, replay_engine = scene()
    replay = replay_engine.replay_workflow(Workflow.load_workflow(str(path)))
    for workflow in (oracle, replay):
        assert len(workflow) == len(reference)
        failures = [(step.name, step.content) for step in workflow.dag.values()
                    if step.error_stage or isinstance(step.content, dict)
                    and ("error" in step.content or step.content.get("status") == "partial")]
        assert failures == []
    return initial, direct, oracle, fresh, replay


def test_actual_oracle_and_saved_replay_have_the_same_physics_resources_and_times(full_execution):
    _, direct, oracle, fresh, replay = full_execution
    assert final_state(direct) == final_state(fresh)
    for expected, actual in zip(oracle.dag.values(), replay.dag.values()):
        assert expected.tool_name == actual.tool_name
        assert expected.tool_args == actual.tool_args
        assert (expected.time_before, expected.time_after, expected.time) == (
            actual.time_before, actual.time_after, actual.time,
        )
        assert clean_ids(expected.content) == clean_ids(actual.content)


def test_shared_material_consumption_and_local_application_and_water_caps(full_execution):
    initial, _, _, fresh, replay = full_execution
    a, b = fresh.farm_a, fresh.farm_b
    assert a._management_regime.fungicide_applications_used == 1
    assert b._management_regime.fungicide_applications_used == 0
    assert a._management_regime.active_ingredient_used_kg == pytest.approx(0.076)
    assert b._management_regime.active_ingredient_used_kg == 0
    assert fresh.warehouse.stock.pesticide_liters == pytest.approx(
        initial["warehouse"]["stock"]["pesticide_liters"] - 76)
    for world in (a, b):
        expected_water = 0
        for step in replay.dag.values():
            if step.tool_name == f"{world.name}__apply_fertigation":
                args = step.tool_args
                expected_water += args["water_mm"] * (args["end_ridge"] - args["start_ridge"] + 1) / 64
            elif step.tool_name == f"{world.name}_Irrigation__irrigate":
                args = step.tool_args
                expected_water += args["hours"] * 5 * (args["end"] - args["start"] + 1) / 64
        assert world._management_regime.irrigation_used_mm_total == pytest.approx(expected_water)
        assert expected_water <= world._management_regime.irrigation_quota_mm_total == 15
    assert b._management_regime.irrigation_used_mm_total > a._management_regime.irrigation_used_mm_total
    for farm in (a, b):
        for ridge_id, state in farm.physics.management.states.items():
            assert state.cumulative_pesticide_applications == int(farm is a and ridge_id in TARGET)


def test_every_field_is_safely_stored_and_shared_equipment_finishes_without_foreign_payload(full_execution):
    _, _, _, fresh, replay = full_execution
    for world in (fresh.farm_a, fresh.farm_b):
        assert sum(state.harvested for state in world.physics.yield_recovery.states.values()) == 64
        stores = [step.content["batch"] for step in replay.dag.values()
                  if step.tool_name == "Warehouse__store_grain"
                  and step.content["batch"]["origin_farm_id"] == world.farm_id]
        assert len(stores) == 16
        assert all(batch["crop_id"] == "soybean" and batch["cultivar_id"] == "HEINONG84"
                   and batch["cultivar_ids"] == ["HEINONG84"] for batch in stores)
        assert Counter(ridge for batch in stores for ridge in batch["ridge_ids"]) == {
            ridge: 1 for ridge in RIDGES
        }
        assert all(batch["status"] == "stored" and batch["moisture_pct"] <= 13.5
                   and batch["quantity_kg"] > 0 for batch in stores)
        assert sum(batch["quantity_kg"] for batch in stores) == pytest.approx(sum(
            batch.quantity_kg for batch in fresh.warehouse.grain_batches.values()
            if batch.origin_farm_id == world.farm_id
        ))
    inventory = fresh.warehouse.get_inventory()
    assert inventory["harvest_grain_kg"] == 0
    assert inventory["warehouse_grain_kg"] == pytest.approx(sum(
        batch.quantity_kg for batch in fresh.warehouse.grain_batches.values()
    ))
    tractor = fresh.tractor.get_state()
    assert "source_farm_id" not in tractor and fresh.tractor.grain_origin_farm_id is None
    assert all(tractor[key] == 0 for key in (
        "seed_hopper", "fertilizer_spreader_kg", "pesticide_tank_l", "fungicide_tank_l", "grain_bin_kg",
    ))
    for entry in fresh.robot.get_state()["inspection_log"]:
        assert len(entry["covered_ridges"]) <= 4
    observations = [step.content for step in replay.dag.values() if step.tool_name.startswith("Robot0__inspect_")]
    assert all(item["pest_confidence"] > 0 and item["disease_confidence"] > 0
               for observation in observations for item in observation["observations"].values())
    multispectral = [step for step in replay.dag.values() if step.tool_name == "Mavic3M__fly_survey"]
    assert multispectral
    for step in multispectral:
        before = datetime.fromtimestamp(step.time_before, tz=ZoneInfo("Asia/Shanghai"))
        after = datetime.fromtimestamp(step.time_after, tz=ZoneInfo("Asia/Shanghai"))
        assert before.date() == after.date()
        assert time(7) <= before.time() <= after.time() <= time(18)
