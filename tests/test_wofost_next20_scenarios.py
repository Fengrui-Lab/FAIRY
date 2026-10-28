"""Incremental acceptance for the next twenty original WOFOST scenarios.

Only release rows marked validating or complete are instantiated, and these
tests never execute a season. Each case must own its complete fixed plan. Real execution
receipts are checked separately by ``assert_next20_replay_contract`` after
that one case's ordinary CLI replay; no golden yield or step count is used.
"""
from __future__ import annotations

import ast
from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib
import inspect
import json
import math
from pathlib import Path
import re

import pytest

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world import DroneApp, FarmWorldApp, RobotApp, SensorApp, TractorApp
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.wofost_farm import DATA, WofostFarmScenario


ROOT = Path(__file__).resolve().parents[1]
LEGACY_SOURCE = ROOT / "fairy/scenarios/farm_world_fullseason_v2"
NATIVE_SOURCE = ROOT / "fairy/scenarios/wofost"
RELEASE = ROOT / "configs/oracles/wofost_next20_release_status.json"
DOCUMENT = json.loads(RELEASE.read_text()) if RELEASE.exists() else {"cases": []}
CASES = DOCUMENT["cases"]
READY = [case for case in CASES if case["status"] in {"validating", "complete"}]
WEATHER_SHA256 = {
    "lille": "b0322825ef8140d714a9724b3933f18954d51541877459d3f9dd48cf7c80a675",
    "clermont_ferrand": "3c4266484b0c06d8656ecf021c09506bec4a35302a7e18f86ade9748e795c87f",
    "valladolid": "516d3bf4b6f74524f66e3634f6f077fb3d97ad64eb1da9ed9f5d4f6df8eb3627",
    "bologna": "0a4df1380afa7db1b1f6980adafafb3be754c4a6d28ccf7457e749f16e4495a4",
}
CROP_SHA256 = "b65cf37a478542d74564094dc0760c69bd3cda99452eb6e7d327e457f87ba9a9"


def _original_id(case):
    return case.get("original_scenario_id", case["scenario_id"].removesuffix("_V2"))


def _source(case):
    return (ROOT / case["source_path"]).resolve()


def _arguments(event):
    bound = inspect.signature(event.function).bind(event.app, *event.args, **event.kwargs)
    bound.apply_defaults()
    return {key: value for key, value in bound.arguments.items() if key != "self"}


def _method(event):
    return event.function.__name__


def _ridges(arguments):
    return range(arguments.get("start_ridge", arguments.get("start")),
                 arguments.get("end_ridge", arguments.get("end")) + 1)


def _ground_ridges(arguments):
    return {arguments["ridge_id"]} if "ridge_id" in arguments else set(_ridges(arguments))


def _event_day(event):
    return event.event_id.split("_", 2)[1]


def _snapshot(scene, engine):
    farm = scene.get_typed_app(FarmWorldApp)
    return deepcopy({"time": engine.time_manager.time(), "farm": farm.get_state(),
        "tractor": scene.get_typed_app(TractorApp).get_state(),
        "messages": scene.get_typed_app(AgentUserInterface).messages,
        "native": farm.physics.crop_backend.export_state(),
        "actions": farm.physics.action_log, "biotic": farm.physics.biotic.states,
        "physics_time": farm.physics.last_physics_sim_time,
        "events": farm.physics.scenario_metadata,
        # Drone state includes battery, mission log, charge session and RNG.
        # Native aerial observations use the separate observation-model RNG.
        "drones": {app.name: app.get_state() for app in scene.apps if isinstance(app, DroneApp)},
        "observation_rng": farm.physics.observation_model.rng.getstate()})


@pytest.fixture(scope="module", params=READY, ids=lambda case: case["scenario_id"])
def built(request):
    case = request.param
    module = importlib.import_module(".".join(_source(case).relative_to(ROOT).with_suffix("").parts))
    cls = getattr(module, case["class_name"])
    scene = cls()
    scene.setup()
    engine = Engine(None, scene)
    before = _snapshot(scene, engine)
    scene.build_events_flow()
    workflow = engine.build_oracle_workflow(run_oracle=False)
    after = _snapshot(scene, engine)
    return case, module, cls, scene, scene.events, workflow, before, after


def test_release_selects_twenty_distinct_original_cases_without_replacing_the_first_ten():
    assert RELEASE.exists(), "Publish the selected IDs and per-case release status"
    assert DOCUMENT["schema_version"] == 1
    assert len(CASES) == 20
    assert [case["number"] for case in CASES] == list(range(1, 21))
    ids = [_original_id(case) for case in CASES]
    formal = (ROOT / "scripts/fullseason/formal_90_scenario_ids.txt").read_text().splitlines()
    from test_wofost_formal10_scenarios import CASES as first_ten
    assert len(set(ids)) == 20 and set(ids) <= set(formal)
    assert not set(ids) & {"scenario_full_season_" + case[0] for case in first_ten}
    complete_numbers = [case["number"] for case in CASES if case["status"] == "complete"]
    assert complete_numbers == list(range(1, len(complete_numbers) + 1))
    assert sum(case["status"] in {"in_progress", "validating"} for case in CASES) <= 1
    for case in CASES:
        path = _source(case)
        expected_source = NATIVE_SOURCE if case["scenario_id"].endswith("_V2") else LEGACY_SOURCE
        assert path.parent == expected_source and path.is_file()
        assert case["status"] in {"pending", "in_progress", "validating", "complete"}
        assert case["original_core"]
        tree = ast.parse(path.read_text())
        assert any(isinstance(node, ast.ClassDef) and node.name == case["class_name"]
                   for node in tree.body)


def test_completed_source_owns_its_world_events_and_literal_plan(built):
    case, module, cls, _, _, _, _, _ = built
    assert Path(module.__file__).resolve() == _source(case)
    assert get_scenario_class(case["scenario_id"]) is cls
    assert cls.scenario_id == case["scenario_id"] and cls.__bases__ == (WofostFarmScenario,)
    assert {"WORLD", "build_events_flow"} <= cls.__dict__.keys()
    assert not hasattr(cls, "execute_oracle_workflow")
    tree = ast.parse(_source(case).read_text())
    assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id == "DroneApp" and any(
                   keyword.arg == "name" and isinstance(keyword.value, ast.Constant)
                   and keyword.value.value == "SurveyDrone" for keyword in node.keywords)
               for node in ast.walk(tree)), "Declare the real SurveyDrone explicitly in this scene"
    declaration = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                       and node.name == cls.__name__)
    world = next(node.value for node in declaration.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "WORLD" for target in node.targets))
    assert isinstance(world, ast.Call) and isinstance(world.func, ast.Name) and world.func.id == "FarmDefinition"
    assert {"reference_id", "seed_type", "timezone_name", "sowing_date", "end_date",
            "farm_id", "num_ridges", "field_length_m", "ridge_width_m", "initial_vwc",
            "soil_depth_m", "base_fertilizer_kg", "irrigation_quota_mm",
            "planting_density_plants_m2", "required_field_preparation_ops"} <= {kw.arg for kw in world.keywords}
    assert isinstance(module.FARMING_PLAN, (tuple, list)) and module.FARMING_PLAN
    for text in module.FARMING_PLAN:
        assert isinstance(text, str) and re.search(r"[\u4e00-\u9fff]", text)
        assert re.search(r"\d{1,2}月\d{1,2}日|\d{4}-\d{2}-\d{2}", text)
        assert "validation_runs" not in text and ".json" not in text
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            name = node.module or ""
            assert not name.startswith(("scripts", "json", "fairy.scenarios.farm_world_fullseason_v2", "fairy.scenarios.wofost.scenario_"))
            assert "batch_scenario" not in name and "wofost_reference" not in name
        elif isinstance(node, ast.Import):
            assert not any(alias.name.startswith(("scripts", "json")) for alias in node.names)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in {"open", "eval", "exec", "build_batch_events", "WofostOracleTools"}
            elif isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"read_text", "read_bytes", "load_workflow"}
    plan = next(node for node in declaration.body if isinstance(node, ast.FunctionDef)
                and node.name == "build_events_flow")
    assert not any(isinstance(node, (ast.If, ast.While, ast.Try, ast.IfExp, ast.Match,
                                    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
                   for node in ast.walk(plan))
    for node in ast.walk(plan):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"physics", "_physics", "_runs", "pcse", "content", "response",
                                     "result", "execute", "run_until", "advance_physics_time"}
        elif isinstance(node, ast.For):
            assert isinstance(node.iter, ast.Name) and node.iter.id == "captured"
    captures = [node for node in ast.walk(plan) if isinstance(node, ast.With)
                and any(isinstance(item.context_expr, ast.Call)
                        and isinstance(item.context_expr.func, ast.Attribute)
                        and item.context_expr.func.attr == "capture_mode" for item in node.items)]
    assert len(captures) == 1
    aliases = {target.id for node in ast.walk(plan) if isinstance(node, ast.Assign)
               and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
               and node.value.func.attr == "get_typed_app"
               for target in node.targets if isinstance(target, ast.Name)}
    for node in ast.walk(plan):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id in aliases):
            assert captures[0].lineno < node.lineno <= captures[0].end_lineno


def test_completed_world_uses_unchanged_official_inputs_and_actual_resource_caps(built):
    case, _, _, scene, _, _, _, _ = built
    world = scene.WORLD
    assert (world.reference_id, world.seed_type) == (case["reference_id"], case["seed_type"])
    assert (world.num_ridges, world.field_length_m, world.ridge_width_m) == (64, 268., 1.1)
    assert scene.crop_backend == "wofost"
    assert scene.reference["variety"] == world.seed_type.replace("SOYBEAN_", "Soybean_")
    assert scene.reference["parameter_overrides"] == {} and scene.reference["native_parameter_count"] == 78
    assert scene.reference["field_validation_available"] is False
    expected_weather = WEATHER_SHA256[world.reference_id]
    assert scene.reference["weather_sha256"] == expected_weather
    assert hashlib.sha256((DATA / scene.reference["weather_path"]).read_bytes()).hexdigest() == expected_weather
    data_manifest = json.loads((DATA / "manifest.json").read_text())
    assert data_manifest["crop_source"]["sha256"] == CROP_SHA256
    assert hashlib.sha256((DATA / data_manifest["crop_source"]["path"]).read_bytes()).hexdigest() == CROP_SHA256
    assert scene.crop_backend_options["reference_density_plants_m2"] == 40.
    assert not scene.crop_backend_options.get("parameter_overrides")
    farm = scene.get_typed_app(FarmWorldApp)
    config = farm.physics.crop_backend.config
    assert config.parameter_overrides == {} and config.cultivar_profile is None
    assert config.cultivar_map == {world.seed_type: scene.reference["variety"]}
    assert farm.required_field_preparation_ops == world.required_field_preparation_ops == ('level', 'form_ridges')
    assert world.base_fertilizer_kg == 0., "Normal-fixation soybean tasks do not require routine mineral N"
    regime = farm.get_state()["management_regime"]
    assert regime["regime"] == world.management_regime
    for public, configured in {"irrigation_quota_mm_total": "irrigation_quota_mm",
            "active_ingredient_cap_kg": "active_ingredient_cap_kg", "max_machine_passes": "max_machine_passes",
            "max_mechanical_weed_ridges": "max_mechanical_weed_ridges",
            "max_insecticide_applications": "max_insecticide_applications",
            "max_fungicide_applications": "max_fungicide_applications"}.items():
        assert regime[public] == getattr(world, configured)


def test_build_captures_valid_calls_without_farming_or_advancing_the_world(built):
    _, _, _, scene, events, workflow, before, after = built
    assert before == after
    assert before["time"] == scene.start_time and not before["actions"]
    assert before["native"]["runs"] == {} and before["native"]["last_day"] is None
    assert before["messages"] == []
    assert set(before["drones"]) == {"SurveyDrone"}
    assert before["drones"]["SurveyDrone"]["mission_log"] == []
    assert all(not row["planted"] and not row["harvested"] for row in before["farm"]["ridges"])
    work = [event for event in events if event.is_oracle]
    assert work and len({event.event_id for event in work}) == len(work)
    assert all(step.content is None for step in workflow.dag.values())
    for previous, event in zip([None] + work[:-1], work):
        assert event.app in scene.apps and event.dependencies == ([] if previous is None else [previous])
        assert event.record_runtime_timing is True and math.isfinite(event.delay_seconds) and event.delay_seconds >= 0
        assert re.match(r"^\d+_\d{4}-\d{2}-\d{2}_.+", event.event_id)
        _arguments(event)  # Bind every literal call to the real tool signature.
    waits = [event for event in work if _method(event) == "advance_time"]
    assert waits and all(_arguments(event)["seconds"] > 0 for event in waits)


def test_main_diagnosis_uses_sensor_then_aerial_localization_then_ground_confirmation(built):
    """At least one genuine diagnostic chain, without mandating routine flights."""
    _, _, _, scene, events, _, _, _ = built
    drones = [app for app in scene.apps if isinstance(app, DroneApp)]
    assert len(drones) == 1 and drones[0].name == "SurveyDrone"
    assert drones[0].min_battery_pct >= 20.
    work = [event for event in events if event.is_oracle]
    flights = [(index, event) for index, event in enumerate(work)
               if isinstance(event.app, DroneApp) and _method(event) == "fly_survey"]
    assert flights, "Every anomaly task needs at least one aerial localization window"
    for index, event in flights:
        day, arguments = _event_day(event), _arguments(event)
        assert event.app is drones[0]
        assert set(arguments) == {"start_ridge", "end_ridge"}
        coverage = set(_ridges(arguments))
        assert coverage and coverage <= set(range(scene.WORLD.num_ridges))
        assert any(isinstance(prior.app, SensorApp)
                   and _method(prior) in {"read_root_zone_sensors", "read_canopy_sensors"}
                   and _event_day(prior) == day for prior in work[:index]), \
            "Use a same-day coarse sensor signal before choosing the aerial survey"
        assert any(isinstance(later.app, RobotApp)
                   and _method(later) in {"inspect_crop_health", "inspect_ridge"}
                   and _event_day(later) == day
                   and _ground_ridges(_arguments(later)) <= coverage
                   for later in work[index + 1:]), \
            "Follow aerial localization with covered same-day ground diagnosis"


def test_plan_covers_real_sowing_observation_and_complete_storage(built):
    _, module, _, scene, events, _, _, _ = built
    methods = {_method(event) for event in events}
    assert {"level", "form_ridges", "load_seeds", "plant_seeds", "get_current_weather",
            "get_forecast", "read_soil_sensors", "get_ridge_range_state", "harvest",
            "unload_grain", "store_grain"} <= methods
    assert not {"base_fertilize", "apply_fertilizer"} & methods
    for name in ("plant_seeds", "harvest"):
        covered = [rid for event in events if _method(event) == name for rid in _ridges(_arguments(event))]
        assert Counter(covered) == Counter(range(64))
        assert all(len(_ridges(_arguments(event))) <= 4 for event in events if _method(event) == name)
    farm = scene.get_typed_app(FarmWorldApp)
    spacing = 200. / (scene.WORLD.ridge_width_m * scene.WORLD.planting_density_plants_m2)
    per_ridge = farm.plants_per_ridge_from_spacing(spacing)
    loaded = sown = 0
    grain_in_machine = awaiting_storage = False
    water_mm = 0.
    for event in events:
        method, args = _method(event), _arguments(event)
        if method == "load_seeds":
            assert args["seed_type"] == scene.WORLD.seed_type
            assert 0 < args["count"] <= 300000 - (loaded - sown)
            loaded += args["count"]
        elif method == "plant_seeds":
            assert args["depth_cm"] == 4. and args["seed_spacing_cm"] == pytest.approx(spacing)
            sown += per_ridge * len(_ridges(args))
            assert sown <= loaded
        elif method in {"inspect_crop_health", "inspect_emergence"}:
            assert len(_ridges(args)) <= 4, "Ground samples must not claim whole-zone coverage"
        elif method == "irrigate":
            depth = 5. * args["hours"]
            assert depth >= 20., "Use meaningful irrigation rounds rather than daily pulses or quota tails"
            water_mm += depth * len(_ridges(args)) / 64.
        elif method == "harvest":
            grain_in_machine = True
        elif method == "unload_grain":
            assert grain_in_machine
            grain_in_machine, awaiting_storage = False, True
        elif method == "dry_grain":
            assert awaiting_storage and 0 < args["target_moisture_pct"] <= 13.5
        elif method == "store_grain":
            assert awaiting_storage
            awaiting_storage = False
    assert sown == per_ridge * 64 and sown <= loaded <= scene.WORLD.seed_stock
    assert not grain_in_machine and not awaiting_storage
    if scene.WORLD.irrigation_quota_mm is not None:
        assert water_mm <= scene.WORLD.irrigation_quota_mm + 1e-7
        assert math.isfinite(module.IRRIGATION_REFERENCE_MM)
        assert 0 < scene.WORLD.irrigation_quota_mm < module.IRRIGATION_REFERENCE_MM
        assert module.IRRIGATION_SELECTION_NOTES


@pytest.mark.parametrize("case", [case for case in READY if _original_id(case) ==
                         "scenario_full_season_fastdraining_dry_patch_irrigation"],
                         ids=lambda case: case["scenario_id"])
def test_fastdraining_task_keeps_a_real_native_soil_contrast_on_its_original_patch(case):
    scene = get_scenario_class(case["scenario_id"])()
    scene.setup()
    farm = scene.get_typed_app(FarmWorldApp)
    soil = farm.physics.soil
    assert set(soil.hydraulic_modifiers) == set(range(20, 32))
    ordinary, patch = soil.params_for_ridge(0), soil.params_for_ridge(20)
    # These are native CWB inputs. A change to the unused legacy drainage
    # proxy alone cannot establish this task's causal spatial contrast.
    assert (patch.root_depth_m, patch.field_capacity_vwc, patch.rainfall_capture_efficiency,
            patch.max_infiltration_mm_day) != (
            ordinary.root_depth_m, ordinary.field_capacity_vwc, ordinary.rainfall_capture_efficiency,
            ordinary.max_infiltration_mm_day)
    specifications = []
    for rid in (0, 20):
        initial = farm.physics.phenology.states[rid]
        management = farm.physics.management.states[rid]
        farm.physics.phenology.states[rid] = deepcopy(initial)
        farm.physics.phenology.states[rid].seed_type = scene.WORLD.seed_type
        farm.physics.phenology.states[rid].planting_date = scene.WORLD.sowing_date
        farm.physics.management.states[rid] = deepcopy(management)
        farm.physics.management.states[rid].stand_fraction = 1.
        try:
            specifications.append(farm.physics.crop_backend._specification(
                farm.physics, rid, scene.WORLD.sowing_date, scene.WORLD.planting_density_plants_m2))
        finally:
            farm.physics.phenology.states[rid] = initial
            farm.physics.management.states[rid] = management
    reference, target = specifications
    assert (target['soil_parameters']['SMFCF'], target['soil_parameters']['RDMSOL'],
            target['site_parameters']['NOTINF']) != (
            reference['soil_parameters']['SMFCF'], reference['soil_parameters']['RDMSOL'],
            reference['site_parameters']['NOTINF'])
    assert not farm.physics.crop_backend.has_started
    ledger = farm.physics.scenario_metadata["wofost_scenario_events"]["events"]
    assert any(event["type"] == "drought" for event in ledger)
    local_water = [_arguments(event) for event in scene.events if _method(event) == "irrigate"
                   and len(_ridges(_arguments(event))) < 64]
    assert local_water
    assert all(set(_ridges(args)) <= set(range(20, 32)) for args in local_water)


def assert_next20_replay_contract(plan, replay, report, simulation_timezone, *,
                                 minimum_drone_battery_pct=20.):
    """Independent artifact audit after one case's real CLI execution.

    Intended for the per-case audit script as well as manual inspection. It
    does not load another scenario or run physics, and makes no yield-fit claim.
    """
    from test_wofost_formal10_scenarios import assert_public_replay_storage_contract
    assert list(plan) == list(replay) and plan
    fields = ("name", "tool_name", "tool_args", "depends_on", "op_type", "time")
    harvested, stored = [], []
    sensor_days, flights, ground_samples = set(), [], []
    last_epoch = report["start_time"]
    for name, step in replay.items():
        assert plan[name]["content"] is None
        assert all(plan[name].get(field) == step.get(field) for field in fields)
        before, after = step["time_before"], step["time_after"]
        assert math.isfinite(before) and math.isfinite(after) and last_epoch <= before <= after
        last_epoch = after
        assert datetime.fromtimestamp(after, simulation_timezone).strftime("%Y-%m-%d %H:%M:%S") == step["time"]
        content = step.get("content")
        if isinstance(content, dict):
            assert not content.get("error") and content.get("status") not in {"partial", "error", "failed"}
            app, method = step["tool_name"].split("__", 1)
            day = datetime.fromtimestamp(before, simulation_timezone).date()
            if app == "SensorApp" and method in {"read_root_zone_sensors", "read_canopy_sensors"}:
                sensor_days.add(day)
            elif app == "SurveyDrone" and method == "fly_survey":
                coverage = list(_ridges(step["tool_args"]))
                assert day in sensor_days, "Aerial survey must follow a same-day coarse sensor reading"
                assert content["status"] == "ok" and content["surveyed_ridges"] == coverage
                assert Counter(row["ridge_id"] for row in content["observations"]) == Counter(coverage)
                assert minimum_drone_battery_pct <= content["battery_remaining_pct"] <= 100.
                assert after > before and content["duration_minutes"] > 0
                flights.append((day, after, set(coverage)))
            elif app.startswith("Robot") and method in {"inspect_crop_health", "inspect_ridge"}:
                ground_ids = _ground_ridges(step["tool_args"])
                if method == "inspect_crop_health":
                    assert set(content["covered_ridges"]) == ground_ids
                else:
                    assert {content["result"]["ridge_id"]} == ground_ids
                ground_samples.append((day, before, ground_ids))
            if step["tool_name"].endswith("__harvest"):
                harvested.extend(content["harvested_ridges"])
            elif step["tool_name"].endswith("__store_grain"):
                stored.extend(content["batch_ridge_ids"])
    assert Counter(harvested) == Counter(stored) == Counter(range(64))
    assert flights, "The replay must actually execute the scene's aerial diagnostic mission"
    assert all(any(ground_day == day and ground_before >= flight_after and ground_ids <= coverage
                   for ground_day, ground_before, ground_ids in ground_samples)
               for day, flight_after, coverage in flights), \
        "Aerial observations require subsequent same-day covered ground confirmation"
    assert_public_replay_storage_contract(replay, num_ridges=64)
    validation = report["evaluation"]["validation"]
    assert report["status"] == "completed" and validation["success"] is True
    assert validation["metadata"]["harvested_ridges"] == 64
    assert validation["metadata"]["field_area_m2"] == pytest.approx(18867.2)
    assert report["metrics"]["workflow_steps"] == len(replay)
