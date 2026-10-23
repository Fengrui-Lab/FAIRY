"""Exercise the three-farm season through exported, saved public tool calls.

The scenario leaves validate() empty. Completion evidence therefore comes from
the actual tool results, all three farm states and the shared equipment logs.
"""
from collections import Counter
from copy import deepcopy

import pytest

from fairy.agents.agent.toolset_builder import build_toolset
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class, list_scenarios
from fairy.scenarios.workflow import Workflow


SCENE = "scenario_three_farm_full_season_hn84_normal"
FARM_IDS = {"farm_a", "farm_b", "farm_c"}
RIDGES = set(range(64))


def scene():
    scenario = get_scenario_class(SCENE)()
    scenario.setup()
    return scenario, Engine(None, scenario)


def farms(scenario):
    return (
        ("farm_a", scenario.farm_a, scenario.sensor_a, scenario.irrigation_a),
        ("farm_b", scenario.farm_b, scenario.sensor_b, scenario.irrigation_b),
        ("farm_c", scenario.farm_c, scenario.sensor_c, scenario.irrigation_c),
    )


def initial_state(scenario):
    """Read raw state so checking capture does not itself advance physics."""
    return deepcopy({
        "farms": [
            {
                "ridges": [ridge.to_dict() for ridge in world._ridges],
                "prep": list(world.completed_prep_ops),
                "last_physics_time": world.physics.last_physics_sim_time,
            }
            for _, world, _, _ in farms(scenario)
        ],
        "warehouse": scenario.warehouse.get_state(),
        "equipment": [app.get_state() for app in scenario.shared_equipment],
        "clock_offset": scenario.farm_environment.time_manager.offset,
    })


def exported_steps(engine):
    return list(engine.run_scenario_oracle(run_oracle=False).dag.values())


def test_fixed_installations_are_independent_and_actual_mobile_schemas_target_three_farms():
    scenario, engine = scene()
    assert set(scenario.farm_environment.farms) == FARM_IDS
    contexts = farms(scenario)
    for attribute in (1, 2, 3):
        assert len({id(context[attribute]) for context in contexts}) == 3
    assert scenario.farm_environment.warehouse is scenario.warehouse
    assert sum(app is scenario.warehouse for app in scenario.apps) == 1
    assert len({id(world._ridges) for _, world, _, _ in contexts}) == 3
    assert len({id(sensor._soil_sensors) for _, _, sensor, _ in contexts}) == 3
    for farm_id, world, sensor, irrigation in contexts:
        context = scenario.farm_environment.get_farm(farm_id)
        assert context.world is world
        assert context.sensors is sensor
        assert context.irrigation is irrigation
        assert sensor.bound_farm_id == irrigation.bound_farm_id == farm_id
    assert scenario.shared_equipment == [
        scenario.tractor, scenario.mavic, scenario.matrice, scenario.robot,
    ]
    assert len({id(app) for app in scenario.shared_equipment}) == 4
    assert all(app.farm_environment is scenario.farm_environment
               for app in scenario.shared_equipment)
    assert all(app.time_manager is engine.time_manager for app in scenario.apps)

    _, schemas, _ = build_toolset(scenario.apps)
    schemas = {item["function"]["name"]: item["function"] for item in schemas}
    for prefix in ("FarmA", "FarmB", "FarmC"):
        assert f"{prefix}_Sensor__read_soil_sensors" in schemas
        assert f"{prefix}_Irrigation__irrigate" in schemas
        assert f"{prefix}__get_management_status" in schemas
        for method in ("get_inventory", "dry_grain", "store_grain"):
            assert f"{prefix}__{method}" not in schemas
    assert {"Warehouse__get_inventory", "Warehouse__get_grain_batches",
            "Warehouse__dry_grain", "Warehouse__store_grain"} <= schemas.keys()
    for method in ("load_seeds", "load_fertilizer", "refuel", "return_supplies", "unload_grain"):
        assert "farm_id" not in schemas[f"Tractor__{method}"]["parameters"]["properties"]
    targeted = {
        name: schema["parameters"] for name, schema in schemas.items()
        if "farm_id" in schema["parameters"].get("properties", {})
    }
    assert {
        "Tractor__plant_seeds", "Tractor__harvest", "Mavic3M__fly_survey",
        "Matrice4T__fly_survey", "Robot0__inspect_emergence",
    } <= targeted.keys()
    for parameters in targeted.values():
        assert set(parameters["properties"]["farm_id"]["enum"]) == FARM_IDS
        assert "farm_id" in parameters["required"]


def test_reference_capture_has_no_farm_side_effects_and_semantic_dependencies_are_closed():
    assert SCENE in list_scenarios()
    scenario, engine = scene()
    before = initial_state(scenario)
    assert all(not ridge.planted for _, world, _, _ in farms(scenario)
               for ridge in world._ridges)
    assert all(not world.completed_prep_ops for _, world, _, _ in farms(scenario))

    scenario.build_events_flow()
    steps = exported_steps(engine)
    assert steps
    assert initial_state(scenario) == before
    assert scenario.expects_agent_harvest is True
    for farm_id in FARM_IDS:
        assert farm_id in scenario.scenario_input

    ids = [event.event_id for event in scenario.events]
    assert len(steps) == len(ids) == len(set(ids))
    assert all(event_id and not event_id.startswith("step") for event_id in ids)
    mobile_names = {app.name for app in scenario.shared_equipment}
    fixed_prefixes = {"FarmA": "farm_a", "FarmB": "farm_b", "FarmC": "farm_c"}
    seen = set()
    observed_targets = set()
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
            observed_targets.add(farm_id)
        for prefix, farm_id in fixed_prefixes.items():
            if app_name.startswith(prefix):
                assert farm_id in step.name
                assert all(other not in step.name for other in FARM_IDS - {farm_id})
        if app_name in mobile_names and method in {
            "level", "base_fertilize", "form_ridges", "plant_seeds", "harvest",
            "fly_survey", "inspect_emergence", "inspect_crop_health", "inspect_pests",
        }:
            assert arguments.get("farm_id") in FARM_IDS
    assert observed_targets == FARM_IDS


@pytest.mark.parametrize("operation", ["plant_seeds", "harvest"])
def test_each_farm_has_complete_four_ridge_passes_and_traceable_warehouse_batches(operation):
    _, engine = scene()
    steps = exported_steps(engine)
    for farm_id in FARM_IDS:
        passes = [step for step in steps
                  if step.tool_name == f"Tractor__{operation}"
                  and step.tool_args["farm_id"] == farm_id]
        coverage = Counter()
        for step in passes:
            arguments = step.tool_args
            start, end = arguments["start_ridge"], arguments["end_ridge"]
            assert 0 <= start <= end < 64
            assert end - start + 1 == 4
            coverage.update(range(start, end + 1))
            if operation == "plant_seeds":
                assert arguments["depth_cm"] == 4.0
                assert arguments["seed_spacing_cm"] == 7.9
        assert len(passes) == 16
        assert set(coverage) == RIDGES
        assert set(coverage.values()) == {1}
    if operation == "harvest":
        for index, step in enumerate(steps):
            if step.tool_name == "Tractor__harvest":
                assert steps[index + 1].tool_name == "Tractor__unload_grain"
                args = step.tool_args
                assert steps[index + 1].tool_args == {
                    "batch_id": f"{args['farm_id']}_{args['start_ridge']}_{args['end_ridge']}"
                }


def test_robot_observations_are_real_samples_and_both_drones_cover_all_three_farms():
    _, engine = scene()
    steps = exported_steps(engine)
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


def test_task_validation_remains_explicitly_unimplemented():
    scenario, engine = scene()
    assert scenario.validate() is None
    assert scenario.validate(engine.environment()) is None


def test_saved_reference_replays_public_tools_from_fresh_state_with_three_safe_harvests(tmp_path):
    original, export_engine = scene()
    before = initial_state(original)
    workflow = export_engine.run_scenario_oracle(run_oracle=False)
    path = tmp_path / "three_farm_full_season.reference.json"
    workflow.save_workflow(str(path))
    assert initial_state(original) == before

    fresh, replay_engine = scene()
    replayed = replay_engine.replay_workflow(Workflow.load_workflow(str(path)))
    failures = [
        (step.name, step.content)
        for step in replayed.dag.values()
        if step.error_stage or isinstance(step.content, dict)
        and ("error" in step.content or step.content.get("status") == "partial")
    ]
    assert failures == []
    assert len(replayed) == len(workflow)
    tractor_state = fresh.tractor.get_state()
    for farm_id, world, _, _ in farms(fresh):
        assert sum(ridge.harvested for ridge in world._ridges) == 64
        assert set(world.completed_prep_ops) == {"level", "base_fertilize", "form_ridges"}
        planting = [entry for entry in tractor_state["operation_log"]
                    if entry["operation"] == "plant_seeds" and entry["farm_id"] == farm_id]
        assert all(entry["seed_spacing_cm"] == 7.9 and entry["depth_cm"] == 4.0
                   for entry in planting)
        for operation in ("plant_seeds", "harvest"):
            entries = [entry for entry in tractor_state["operation_log"]
                       if entry["operation"] == operation and entry["farm_id"] == farm_id]
            assert len(entries) == 16
            assert Counter(ridge_id for entry in entries for ridge_id in entry["ridge_ids"]) == {
                ridge_id: 1 for ridge_id in RIDGES
            }
        stores = [step.content["batch"] for step in replayed.dag.values()
                  if step.tool_name == "Warehouse__store_grain"
                  and step.content["batch"]["origin_farm_id"] == farm_id]
        assert len(stores) == 16
        assert all(batch["crop_id"] == "soybean" and batch["cultivar_id"] == "HEINONG84"
                   and batch["cultivar_ids"] == ["HEINONG84"] for batch in stores)
        assert all(batch["quantity_kg"] > 0 and batch["moisture_pct"] <= 13.5
                   and batch["status"] == "stored" for batch in stores)
        assert Counter(ridge_id for batch in stores for ridge_id in batch["ridge_ids"]) == {
            ridge_id: 1 for ridge_id in RIDGES
        }

    assert 3_000_000 - fresh.warehouse.stock.seed_stock["HEINONG84"] == sum(
        entry["seeds_used"] for entry in tractor_state["operation_log"]
        if entry["operation"] == "plant_seeds"
    )
    inventory = fresh.warehouse.get_inventory()
    assert inventory["harvest_grain_kg"] == 0
    assert inventory["warehouse_grain_kg"] == pytest.approx(sum(
        batch.quantity_kg for batch in fresh.warehouse.grain_batches.values()
    ))
    assert "source_farm_id" not in fresh.tractor.get_state()
    assert fresh.tractor.grain_origin_farm_id is None
    assert all(tractor_state[key] == 0 for key in (
        "grain_bin_kg", "seed_hopper", "fertilizer_spreader_kg", "pesticide_tank_l", "fungicide_tank_l",
    ))
    for drone in (fresh.mavic, fresh.matrice):
        missions = drone.get_state()["mission_log"]
        assert {mission["farm_id"] for mission in missions} == FARM_IDS
        assert all(not mission["aborted"] for mission in missions)
        assert all(mission["surveyed_ridges"] == mission["target_ridges"] for mission in missions)
    robot_entries = fresh.robot.get_state()["inspection_log"]
    assert Counter(entry["farm_id"] for entry in robot_entries) == {
        "farm_a": 4, "farm_b": 4, "farm_c": 4,
    }
    assert all(len(entry["covered_ridges"]) == 8 for entry in robot_entries)
    expected_coverage = Counter({
        **{("emergence", rid): 1 for rid in range(8)},
        **{("crop_health", rid): 2 for rid in range(28, 36)},
        **{("pest", rid): 1 for rid in range(56, 64)},
    })
    for farm_id in FARM_IDS:
        actual_coverage = Counter((entry["modality"], rid)
                                  for entry in robot_entries if entry["farm_id"] == farm_id
                                  for rid in entry["covered_ridges"])
        assert actual_coverage == expected_coverage
    assert len({world._sim_date for _, world, _, _ in farms(fresh)}) == 1
    assert fresh.farm_environment.time_manager is replay_engine.time_manager
    assert fresh.validate(replay_engine.environment()) is None
