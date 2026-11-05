"""A real native mixed-crop season must complete independently for both farms.

One module fixture runs the public Oracle and a JSON-saved reference in a fresh
world.  Assertions compare actual state, time, materials and grain provenance;
there is no golden yield, fake maturity or direct call to a crop's daily loop.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta

import pytest

from fairy.agents.agent.toolset_builder import build_toolset
from fairy.apps.farm_world.shared_drone_app import SharedDroneApp
from fairy.apps.farm_world.shared_robot_app import SharedRobotApp
from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.workflow import Workflow


SCENE = "scenario_two_farm_wofost_soybean_maize_full_season"
CLASS_NAME = "ScenarioTwoFarmWofostSoybeanMaizeFullSeason"
RIDGES = Counter(range(64))
IDENTITIES = {
    "soybean_field": ("soybean", "SOYBEAN_901", "Soybean_901", 1.1, 2),
    "maize_field": ("maize", "MAIZE_201", "Grain_maize_201", .75, 1),
}
RANDOM_ID_FIELDS = {"action_id", "op_id", "mission_id", "inspection_id"}


def create_scene():
    pytest.importorskip("pcse")
    scene = get_scenario_class(SCENE)()
    scene.setup()
    return scene, Engine(None, scene)


def clean_ids(value):
    """Remove only documented operation/inspection UUID fields."""
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {key: clean_ids(item) for key, item in value.items() if key not in RANDOM_ID_FIELDS}
    if isinstance(value, (tuple, list)):
        return [clean_ids(item) for item in value]
    return value


def oracle_receipt_for_comparison(step):
    """Separate declared captured-event notes from the actual tool receipt."""
    receipt = deepcopy(step.content)
    if isinstance(receipt, dict):
        receipt.pop("oracle_reason", None)
        # Engine wraps non-dict returns to attach captured-event metadata.
        # These two AUI tools specifically return the original string.
        if (step.tool_name in {
                "AgentUserInterface__send_message_to_agent",
                "AgentUserInterface__send_message_to_user",
            } and set(receipt) == {"result"} and isinstance(receipt["result"], str)):
            return receipt["result"]
    return receipt


def world_state(scene):
    return deepcopy(clean_ids({
        "clock": scene.farm_environment.time_manager.time(),
        "farms": {world.farm_id: world.get_state() for world in (scene.soybean, scene.maize)},
        "weather": scene.weather.get_state(),
        "warehouse": scene.warehouse.get_state(),
        "shared": {app.name: app.get_state() for app in scene.shared_equipment},
        "fixed": {app.name: app.get_state() for app in (
            scene.soybean_sensor, scene.maize_sensor,
            scene.soybean_irrigation, scene.maize_irrigation,
        )},
    }))


def assert_no_failed_tools(workflow):
    failed = [(step.name, step.error_stage, step.content) for step in workflow.dag.values()
              if step.error_stage or isinstance(step.content, dict)
              and (step.content.get("error") or step.content.get("status") == "partial")]
    assert failed == []


def test_native_models_fixed_facilities_and_shared_resources_are_explicit():
    scene, engine = create_scene()
    assert type(scene).__name__ == CLASS_NAME
    assert set(scene.farm_environment.farms) == set(IDENTITIES)
    assert scene.farm_environment.simulation_timezone.key == "Europe/Paris"
    assert len({app.name for app in scene.apps}) == len(scene.apps)
    assert all(app.time_manager is engine.time_manager for app in scene.apps)
    assert scene.soybean.physics is not scene.maize.physics
    assert scene.soybean.physics.crop_backend is not scene.maize.physics.crop_backend
    assert scene.soybean.shared_warehouse is scene.maize.shared_warehouse is scene.warehouse
    for world in (scene.soybean, scene.maize):
        crop, seed, variety, width, rows = IDENTITIES[world.farm_id]
        assert world.crop_type == crop
        assert world.num_ridges == 64 and world.field_length_m == 268
        assert world.ridge_width_m == width and world.rows_per_ridge == rows
        assert world.physics.crop_backend_name == "wofost"
        assert world.physics.crop_backend.config.crop_name == crop
        config = world.physics.crop_backend.config
        assert config.cultivar_map[seed] == variety
        assert config.latitude_deg == pytest.approx(49.4)
        assert config.longitude_deg == pytest.approx(6.2)
        assert world.simulation_timezone.key == "Europe/Paris"
        assert world.physics.scenario_metadata["daily_settlement"] == "completed_calendar_day"
        assert world.physics.crop_backend.export_state()["runs"] == {}
        assert world._legacy_inventory is None
    assert scene.maize_irrigation.bound_farm_id == "maize_field"
    assert scene.soybean_irrigation.bound_farm_id == "soybean_field"
    assert scene.maize_sensor.bound_farm_id == "maize_field"
    assert scene.soybean_sensor.bound_farm_id == "soybean_field"
    assert scene.maize_irrigation is not scene.soybean_irrigation
    assert scene.maize_sensor is not scene.soybean_sensor
    assert Counter(type(app) for app in scene.shared_equipment) == Counter({
        SharedTractorApp: 1, SharedDroneApp: 1, SharedRobotApp: 1,
    })
    functions = {row["function"]["name"]: row["function"]
                 for row in build_toolset(scene.apps)[1]}
    for method in ("plant_seeds", "harvest", "apply_fertilizer"):
        schema = functions[f"{scene.tractor.name}__{method}"]["parameters"]
        assert set(schema["properties"]["farm_id"]["enum"]) == set(IDENTITIES)
        assert "farm_id" in schema["required"]
    for method in ("load_seeds", "load_fertilizer", "refuel", "unload_grain"):
        schema = functions[f"{scene.tractor.name}__{method}"]["parameters"]
        assert "farm_id" not in schema["properties"]


def test_export_is_static_complete_and_does_not_advance_physical_time(tmp_path):
    scene, engine = create_scene()
    before = world_state(scene)
    plan = engine.run_scenario_oracle(False)
    assert plan.dag
    assert all(step.content.get("oracle_reason") for step in plan.dag.values())
    assert world_state(scene) == before
    assert all(step.time_before is None and step.time_after is None for step in plan.dag.values())
    seen = set()
    for name, step in plan.dag.items():
        assert name and not name.startswith("step")
        assert set(step.depends_on) <= seen
        seen.add(name)
    for farm_id in IDENTITIES:
        for method in ("plant_seeds", "harvest"):
            passes = [step for step in plan.dag.values()
                      if step.tool_name == f"{scene.tractor.name}__{method}"
                      and step.tool_args["farm_id"] == farm_id]
            assert Counter(ridge for step in passes for ridge in range(
                step.tool_args["start_ridge"], step.tool_args["end_ridge"] + 1)) == RIDGES
            assert all(1 <= step.tool_args["end_ridge"] - step.tool_args["start_ridge"] + 1 <= 4
                       for step in passes)
    ground = [step for step in plan.dag.values() if "__inspect_" in step.tool_name]
    assert ground and {step.tool_args["farm_id"] for step in ground} == set(IDENTITIES)
    assert all(step.tool_args["end_ridge"] - step.tool_args["start_ridge"] + 1 <= 4 for step in ground)
    path = tmp_path / "reference.json"
    plan.save_workflow(str(path))
    assert Workflow.load_workflow(str(path)).to_dict() == plan.to_dict()


@pytest.fixture(scope="module")
def complete_season(tmp_path_factory):
    source, exporter = create_scene()
    initial = world_state(source)
    plan = exporter.run_scenario_oracle(False)
    path = tmp_path_factory.mktemp("native_mixed_crop_reference") / "reference.json"
    plan.save_workflow(str(path))
    direct, oracle_engine = create_scene()
    oracle = oracle_engine.run_scenario_oracle(True)
    fresh, replay_engine = create_scene()
    replay = replay_engine.replay_workflow(Workflow.load_workflow(str(path)))
    for workflow in (oracle, replay):
        assert list(workflow.dag) == list(plan.dag)
        assert_no_failed_tools(workflow)
    assert oracle_engine.evaluate().success
    result = replay_engine.evaluate()
    assert result.success, result.message
    return initial, direct, oracle_engine, oracle, fresh, replay_engine, replay


def test_real_oracle_and_json_reference_replay_have_identical_full_state_and_time(complete_season):
    _, direct, oracle_engine, oracle, fresh, replay_engine, replay = complete_season
    assert world_state(direct) == world_state(fresh)
    assert oracle_engine.time_manager.time() == replay_engine.time_manager.time()
    for expected, actual in zip(oracle.dag.values(), replay.dag.values()):
        assert expected.tool_name == actual.tool_name
        assert expected.tool_args == actual.tool_args
        assert expected.depends_on == actual.depends_on
        assert (expected.time, expected.time_before, expected.time_after) == (
            actual.time, actual.time_before, actual.time_after)
        assert clean_ids(oracle_receipt_for_comparison(expected)) == clean_ids(actual.content)


def test_each_native_crop_finishes_all_64_ridges_in_its_own_safe_traceable_batches(complete_season):
    _, _, _, _, scene, engine, _ = complete_season
    native_count = 0
    batches = list(scene.warehouse.grain_batches.values())
    operations = scene.tractor.get_state()["operation_log"]
    for world in (scene.soybean, scene.maize):
        crop, seed, _, _, _ = IDENTITIES[world.farm_id]
        runs = world.physics.crop_backend.export_state()["runs"]
        assert set(map(int, runs)) == set(range(64))
        native_count += len(runs)
        assert all(state.harvested for state in world.physics.yield_recovery.states.values())
        own = [batch for batch in batches if batch.origin_farm_id == world.farm_id]
        assert own and Counter(ridge for batch in own for ridge in batch.ridge_ids) == RIDGES
        limit = min(scene.warehouse.max_storage_moisture_pct,
                    world.crop_definition.storage_moisture_pct)
        assert all(batch.crop_id == crop and batch.cultivar_ids == [seed]
                   and batch.status == "stored" and batch.quantity_kg > 0
                   and batch.moisture_pct is not None and batch.moisture_pct <= limit + 1e-9
                   for batch in own)
        assert sum(batch.quantity_kg for batch in own) == pytest.approx(sum(
            row["grain_kg_added"] for row in operations
            if row["operation"] == "harvest" and row["farm_id"] == world.farm_id))
        assert world.physics.last_physics_sim_time == engine.time_manager.time()
    assert native_count == 128
    assert {batch.origin_farm_id for batch in batches} == set(IDENTITIES)
    inventory = scene.warehouse.get_inventory()
    assert inventory["harvest_grain_kg"] == 0
    assert inventory["warehouse_grain_kg"] == pytest.approx(sum(batch.quantity_kg for batch in batches))
    machine = scene.tractor.get_state()
    assert machine["grain_bin_kg"] == machine["seed_hopper"] == 0
    assert scene.tractor.grain_origin_farm_id is None


def test_common_material_accounts_and_each_fields_water_quota_match_real_receipts(complete_season):
    initial, _, _, _, scene, _, workflow = complete_season
    first_stock = initial["warehouse"]["stock"]
    stock = scene.warehouse.get_state()["stock"]
    operations = scene.tractor.get_state()["operation_log"]
    fertilizer_applied = 0
    for world in (scene.soybean, scene.maize):
        seed = IDENTITIES[world.farm_id][1]
        planted = [row for row in operations
                   if row["operation"] == "plant_seeds" and row["farm_id"] == world.farm_id]
        assert Counter(ridge for row in planted for ridge in row["ridge_ids"]) == RIDGES
        seed_used = sum(row["seeds_used"] for row in planted)
        assert seed_used == sum(world.plants_per_ridge_from_spacing(row["seed_spacing_cm"])
                                * len(row["ridge_ids"]) for row in planted)
        assert first_stock["seed_stock"][seed] - stock["seed_stock"][seed] == seed_used
        applied = sum(row["fertilizer_used_kg"] for row in operations
                      if row["operation"] in {"base_fertilize", "apply_fertilizer"}
                      and row["farm_id"] == world.farm_id)
        fertilizer_applied += applied
        regime = world._management_regime
        assert regime.fertilizer_used_kg == pytest.approx(applied)
        if regime.fertilizer_quota_kg is not None:
            assert applied <= regime.fertilizer_quota_kg + 1e-9
        irrigation = (scene.soybean_irrigation if world is scene.soybean else scene.maize_irrigation)
        water = sum(step.tool_args["hours"] * 5
                    * (step.tool_args["end"] - step.tool_args["start"] + 1) / 64
                    for step in workflow.dag.values()
                    if step.tool_name == f"{irrigation.name}__irrigate")
        assert regime.irrigation_used_mm_total == pytest.approx(water)
        assert regime.irrigation_quota_mm_total is not None
        assert water <= regime.irrigation_quota_mm_total + 1e-9
    assert first_stock["fertilizer_kg"] - stock["fertilizer_kg"] == pytest.approx(fertilizer_applied)
    assert scene.tractor.get_state()["fertilizer_spreader_kg"] == 0
    assert stock["fuel_liters"] >= 0 and stock["fertilizer_kg"] >= 0
    assert all(value >= 0 for value in stock["seed_stock"].values())


def test_public_weather_uses_today_while_native_models_settle_the_previous_day(complete_season):
    _, _, _, _, scene, engine, _ = complete_season
    today = datetime.fromtimestamp(engine.time_manager.time(), scene.farm_environment.simulation_timezone).date()
    assert scene.weather.get_current_weather_snapshot()["date"] == today.isoformat()
    for world in (scene.soybean, scene.maize):
        settled = world.physics.crop_backend.snapshot()["last_day"]
        assert date.fromisoformat(settled) == today - timedelta(days=1)


def test_an_empty_native_mixed_crop_scene_cannot_pass_completion():
    _, engine = create_scene()
    assert not engine.evaluate().success


@pytest.mark.parametrize("farm_id", list(IDENTITIES))
def test_one_successful_crop_cannot_hide_the_other_fields_missing_storage(complete_season, farm_id):
    _, _, _, _, scene, _, _ = complete_season
    own = [batch for batch in scene.warehouse.grain_batches.values() if batch.origin_farm_id == farm_id]
    prior = [batch.status for batch in own]
    try:
        for batch in own:
            batch.status = "pending"
        result = scene.validate()
        assert not result.success
        assert farm_id in result.message
    finally:
        for batch, status in zip(own, prior):
            batch.status = status


@pytest.mark.parametrize("farm_id", list(IDENTITIES))
def test_other_crop_grain_cannot_substitute_for_the_fields_own_harvest(complete_season, farm_id):
    _, _, _, _, scene, _, _ = complete_season
    batch = next(batch for batch in scene.warehouse.grain_batches.values() if batch.origin_farm_id == farm_id)
    other = next(identity for key, identity in IDENTITIES.items() if key != farm_id)
    original = (batch.crop_id, batch.cultivar_id, list(batch.cultivar_ids))
    try:
        batch.crop_id, batch.cultivar_id, batch.cultivar_ids = other[0], other[1], [other[1]]
        result = scene.validate()
        assert not result.success
        assert farm_id in result.message
    finally:
        batch.crop_id, batch.cultivar_id, batch.cultivar_ids = original
