"""Check the independent two-farm season through its real public workflow.

The scenario deliberately has no task validator. These integration checks inspect
the exported plan and the resulting farm/device state directly, rather than
treating Engine.evaluate()'s default result as evidence of a completed season.
"""
from collections import Counter
from copy import deepcopy

import pytest

from fairy.agents.agent.toolset_builder import build_toolset
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class, list_scenarios
from fairy.scenarios.workflow import Workflow


SCENE = "scenario_two_farm_full_season_hn84_normal"
FARM_IDS = {"farm_a", "farm_b"}
RIDGES = set(range(64))


def scene():
    scenario = get_scenario_class(SCENE)()
    scenario.setup()
    return scenario, Engine(None, scenario)


def initial_state(scenario):
    """Read raw setup state without triggering a physics synchronization."""
    return deepcopy({
        "farms": [
            {
                "ridges": [ridge.to_dict() for ridge in farm._ridges],
                "inventory": farm._inventory.to_dict(),
                "prep": list(farm.completed_prep_ops),
                "last_physics_time": farm.physics.last_physics_sim_time,
            }
            for farm in (scenario.farm_a, scenario.farm_b)
        ],
        "equipment": [app.get_state() for app in scenario.shared_equipment],
        "clock_offset": scenario.farm_environment.time_manager.offset,
    })


def exported_steps(scenario, engine):
    workflow = engine.run_scenario_oracle(run_oracle=False)
    return list(workflow.dag.values())


def test_full_season_registry_and_reference_capture_have_no_farm_side_effects():
    assert SCENE in list_scenarios()
    scenario, engine = scene()
    before = initial_state(scenario)
    assert all(not ridge.planted for farm in (scenario.farm_a, scenario.farm_b)
               for ridge in farm._ridges)
    assert all(not farm.completed_prep_ops for farm in (scenario.farm_a, scenario.farm_b))

    scenario.build_events_flow()
    steps = exported_steps(scenario, engine)

    assert steps
    assert initial_state(scenario) == before
    assert scenario.expects_agent_harvest is True


def test_fixed_installations_and_warehouses_are_separate_but_fleet_and_clock_are_shared():
    scenario, engine = scene()
    assert set(scenario.farm_environment.farms) == FARM_IDS
    assert scenario.sensor_a is not scenario.sensor_b
    assert scenario.irrigation_a is not scenario.irrigation_b
    assert scenario.sensor_a._soil_sensors is not scenario.sensor_b._soil_sensors
    assert scenario.farm_a._inventory is not scenario.farm_b._inventory
    assert scenario.farm_a._ridges is not scenario.farm_b._ridges
    for farm_id, world, sensor, irrigation in (
        ("farm_a", scenario.farm_a, scenario.sensor_a, scenario.irrigation_a),
        ("farm_b", scenario.farm_b, scenario.sensor_b, scenario.irrigation_b),
    ):
        context = scenario.farm_environment.get_farm(farm_id)
        assert context.world is world
        assert context.sensors is sensor
        assert context.irrigation is irrigation
        assert sensor.bound_farm_id == farm_id
        assert irrigation.bound_farm_id == farm_id
    assert scenario.shared_equipment == [
        scenario.tractor, scenario.mavic, scenario.matrice, scenario.robot,
    ]
    assert len({id(app) for app in scenario.shared_equipment}) == 4
    assert all(app.farm_environment is scenario.farm_environment
               for app in scenario.shared_equipment)
    assert all(app.time_manager is engine.time_manager for app in scenario.apps)

    _, schemas, _ = build_toolset(scenario.apps)
    schemas = {schema["function"]["name"]: schema["function"] for schema in schemas}
    for name in ("Mavic3M__fly_survey", "Matrice4T__fly_survey",
                 "Robot0__inspect_emergence", "Tractor__plant_seeds", "Tractor__harvest"):
        parameters = schemas[name]["parameters"]
        assert set(parameters["properties"]["farm_id"]["enum"]) == FARM_IDS
        assert "farm_id" in parameters["required"]
    for prefix in ("FarmA", "FarmB"):
        assert f"{prefix}_Sensor__read_soil_sensors" in schemas
        assert f"{prefix}_Irrigation__irrigate" in schemas


def test_reference_nodes_have_unique_semantic_ids_closed_dependencies_and_exact_targets():
    scenario, engine = scene()
    events = scenario.events
    ids = [event.event_id for event in events]
    assert len(ids) == len(set(ids))
    assert all(event_id and not event_id.startswith("step") for event_id in ids)

    steps = exported_steps(scenario, engine)
    assert len(steps) == len(events)
    seen = set()
    mobile_names = {app.name for app in scenario.shared_equipment}
    for step in steps:
        assert set(step.depends_on) <= seen
        if seen:
            assert step.depends_on
        seen.add(step.name)
        app_name, method = step.tool_name.split("__", 1)
        arguments = step.tool_args or {}
        if "farm_id" in arguments:
            farm_id = arguments["farm_id"]
            assert farm_id in FARM_IDS
            assert farm_id in step.name
            assert app_name in mobile_names | {"ManualOps"}
        if app_name.startswith("FarmA"):
            assert "farm_a" in step.name
            assert "farm_b" not in step.name
        if app_name.startswith("FarmB"):
            assert "farm_b" in step.name
            assert "farm_a" not in step.name
        if app_name in mobile_names and method in {
            "level", "base_fertilize", "form_ridges", "plant_seeds", "harvest",
            "fly_survey", "inspect_emergence", "inspect_crop_health", "inspect_pests",
            "load_seeds", "load_fertilizer", "return_supplies", "unload_grain", "refuel",
        }:
            assert arguments.get("farm_id") in FARM_IDS


@pytest.mark.parametrize("operation", ["plant_seeds", "harvest"])
def test_both_farms_receive_exact_full_field_four_ridge_passes(operation):
    scenario, engine = scene()
    steps = exported_steps(scenario, engine)
    for farm_id in FARM_IDS:
        passes = [step for step in steps
                  if step.tool_name == f"Tractor__{operation}"
                  and step.tool_args["farm_id"] == farm_id]
        coverage = Counter()
        for step in passes:
            arguments = step.tool_args
            start, end = arguments["start_ridge"], arguments["end_ridge"]
            assert 0 <= start <= end < 64
            assert end - start + 1 <= 4
            coverage.update(range(start, end + 1))
            if operation == "plant_seeds":
                assert arguments["depth_cm"] == 4.0
                assert arguments["seed_spacing_cm"] == 7.9
        assert set(coverage) == RIDGES
        assert set(coverage.values()) == {1}
        assert len(passes) == 16
    if operation == "harvest":
        for farm_id in FARM_IDS:
            own_harvests = [index for index, step in enumerate(steps)
                            if step.tool_name == "Tractor__harvest"
                            and step.tool_args["farm_id"] == farm_id]
            for index in own_harvests:
                assert steps[index + 1].tool_name == "Tractor__unload_grain"
                assert steps[index + 1].tool_args["farm_id"] == farm_id


def test_ground_observations_are_eight_ridge_samples_and_aerial_checks_cover_each_field():
    scenario, engine = scene()
    steps = exported_steps(scenario, engine)
    expected_samples = {
        ("inspect_emergence", 0, 7): 1,
        ("inspect_crop_health", 28, 35): 2,
        ("inspect_pests", 56, 63): 1,
    }
    for farm_id in FARM_IDS:
        samples = Counter()
        for step in steps:
            if step.tool_name.startswith("Robot0__inspect_") and step.tool_args["farm_id"] == farm_id:
                arguments = step.tool_args
                start, end = arguments["start_ridge"], arguments["end_ridge"]
                assert end - start + 1 == 8
                assert "sample" in step.name
                samples[(step.tool_name.split("__")[1], start, end)] += 1
        assert samples == expected_samples
        multispectral = [step.tool_args for step in steps
                         if step.tool_name == "Mavic3M__fly_survey"
                         and step.tool_args["farm_id"] == farm_id]
        assert len(multispectral) == 3
        assert all((args["start_ridge"], args["end_ridge"]) == (0, 63)
                   for args in multispectral)
        thermal = [step.tool_args for step in steps
                   if step.tool_name == "Matrice4T__fly_survey"
                   and step.tool_args["farm_id"] == farm_id]
        assert [(args["start_ridge"], args["end_ridge"]) for args in thermal] == [(0, 31), (32, 63)]


def test_task_validation_is_explicitly_unimplemented():
    scenario, engine = scene()
    assert scenario.validate() is None
    assert scenario.validate(engine.environment()) is None


def test_saved_reference_replays_public_tools_from_fresh_initial_state(tmp_path):
    original, export_engine = scene()
    before = initial_state(original)
    workflow = export_engine.run_scenario_oracle(run_oracle=False)
    path = tmp_path / "two_farm_full_season.reference.json"
    workflow.save_workflow(str(path))
    assert initial_state(original) == before

    fresh, replay_engine = scene()
    replayed = replay_engine.replay_workflow(Workflow.load_workflow(str(path)))
    errors = [
        (step.name, step.content)
        for step in replayed.dag.values()
        if step.error_stage or isinstance(step.content, dict) and "error" in step.content
    ]
    assert errors == []
    assert len(replayed) == len(workflow)
    for farm_id, farm in (("farm_a", fresh.farm_a), ("farm_b", fresh.farm_b)):
        assert sum(ridge.harvested for ridge in farm._ridges) == 64
        assert farm._inventory.warehouse_grain_kg > 0
        assert farm._inventory.harvest_grain_kg == 0
        assert farm._inventory.grain_dried is True
        assert set(farm.completed_prep_ops) == {"level", "base_fertilize", "form_ridges"}
        # Harvest clears the visible sowing fields. Check the retained planting
        # log and actual HEINONG84 stock consumption instead of expecting a bare
        # harvested ridge to retain its old seed labels.
        plant_entries = [entry for entry in fresh.tractor.get_state()["operation_log"]
                         if entry["operation"] == "plant_seeds" and entry["farm_id"] == farm_id]
        assert all(entry["seed_spacing_cm"] == 7.9 and entry["depth_cm"] == 4.0
                   for entry in plant_entries)
        assert 1_000_000 - farm._inventory.seed_stock["HEINONG84"] == sum(
            entry["seeds_used"] for entry in plant_entries
        )
        for operation in ("plant_seeds", "harvest"):
            entries = [entry for entry in fresh.tractor.get_state()["operation_log"]
                       if entry["operation"] == operation and entry["farm_id"] == farm_id]
            assert len(entries) == 16
            assert {ridge_id for entry in entries for ridge_id in entry["ridge_ids"]} == RIDGES
    assert fresh.tractor.source_farm_id is None
    assert fresh.tractor.grain_origin_farm_id is None
    assert fresh.tractor.get_state()["grain_bin_kg"] == 0
    for drone in (fresh.mavic, fresh.matrice):
        missions = drone.get_state()["mission_log"]
        assert {mission["farm_id"] for mission in missions} == FARM_IDS
        assert all(not mission["aborted"] for mission in missions)
        assert all(mission["surveyed_ridges"] == mission["target_ridges"] for mission in missions)
    robot_entries = fresh.robot.get_state()["inspection_log"]
    assert Counter(entry["farm_id"] for entry in robot_entries) == {"farm_a": 4, "farm_b": 4}
    assert all(len(entry["covered_ridges"]) == 8 for entry in robot_entries)
    assert fresh.farm_a._sim_date == fresh.farm_b._sim_date
    assert fresh.farm_environment.time_manager is replay_engine.time_manager
    assert fresh.validate(replay_engine.environment()) is None
