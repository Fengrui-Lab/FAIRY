"""Acceptance for nine redesigned original cases and one held nutrient case.

These tests build fixed captured plans, never execute a season. They protect
identity, source ownership, official inputs, old task constraints, and the
absence of side effects during build. Authorized density changes scale only
TDWI from realized integer plant counts; no yield or total-step target is fixed.
The flowering-nutrition V2 world and fixed plan remain unchanged apart from
version identifiers and public Agent instructions. It is excluded from the
agronomic acceptance contract.
"""
from __future__ import annotations

import ast
from collections import Counter
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import importlib
import inspect
import json
import math
import re
from pathlib import Path

import pytest
import yaml

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world import FarmWorldApp, TractorApp
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.workflow import Workflow, WorkflowStep
from fairy.scenarios.wofost_farm import DATA, WofostFarmScenario
from fairy.tool_utils import OperationType


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "scenario_full_season_"
VERSION_ROWS = json.loads((ROOT / "configs/oracles/wofost_scenario_versions.json").read_text())["rows"]
VERSION_BY_LEGACY = {row["legacy_id"]: row for row in VERSION_ROWS}


def _version(case):
    return VERSION_BY_LEGACY[PREFIX + case[0]]

# File and class identities are the original registered identities, including
# the intentionally different high-weed filename.
CASES = [
    ("hb_base_hn84_std_normal", "hb_base_hn84_std_normal", "ScenarioFullSeasonHBBaseHN84StdNormal", "lille", "SOYBEAN_901"),
    ("hb_dryr5r6_hn84_water_limit", "hb_dryr5r6_hn84_water_limit", "ScenarioFullSeasonHBDryR5R6HN84WaterLimit", "valladolid", "SOYBEAN_903"),
    ("hb_low_nutrient_carryover_flowering_nutrition", "hb_low_nutrient_carryover_flowering_nutrition", "ScenarioFullSeasonHBLowNutrientCarryoverFloweringNutrition", "clermont_ferrand", "SOYBEAN_902"),
    ("hb_high_weed_seedbank_mechanical_only_baseline", "hb_high_weed_seedbank_early_control", "ScenarioFullSeasonHBHighWeedSeedbankMechanicalOnlyBaseline", "lille", "SOYBEAN_901"),
    ("hb_r5_leaf_feeder_defoliation", "hb_r5_leaf_feeder_defoliation", "ScenarioFullSeasonHBR5LeafFeederDefoliation", "bologna", "SOYBEAN_905"),
    ("hb_limited_spray_budget_season", "hb_limited_spray_budget_season", "ScenarioFullSeasonHBLimitedSprayBudgetSeason", "lille", "SOYBEAN_901"),
    ("hb_wetjune_short_spray_window", "hb_wetjune_short_spray_window", "ScenarioFullSeasonHBWetjuneShortSprayWindow", "lille", "SOYBEAN_901"),
    ("hb_disease_then_drought_recovery_tradeoff", "hb_disease_then_drought_recovery_tradeoff", "ScenarioFullSeasonHBDiseaseThenDroughtRecoveryTradeoff", "lille", "SOYBEAN_901"),
    ("hb_weed_then_disease_canopy_confusion", "hb_weed_then_disease_canopy_confusion", "ScenarioFullSeasonHBWeedThenDiseaseCanopyConfusion", "lille", "SOYBEAN_901"),
    ("hb_herbicide_window_missed_rain_delay", "hb_herbicide_window_missed_rain_delay", "ScenarioFullSeasonHBHerbicideWindowMissedRainDelay", "lille", "SOYBEAN_901"),
]
IDS = [row[0] for row in CASES]
HELD_CASE = CASES[2]
HELD_SOURCE_SHA256 = '52881b3807ffc2a54f9962f0cb087266bf5758cfbf234fe7eb9a2a516bc90869'
HELD_REASON = 'Flowering nutrition yield-rescue evidence is insufficient; no new nodulation mechanism is introduced this round.'
RELEASED_CASES = [case for case in CASES if case != HELD_CASE]
RELEASED_IDS = [case[0] for case in RELEASED_CASES]
WEATHER_SHA256 = {
    "lille": "b0322825ef8140d714a9724b3933f18954d51541877459d3f9dd48cf7c80a675",
    "clermont_ferrand": "3c4266484b0c06d8656ecf021c09506bec4a35302a7e18f86ade9748e795c87f",
    "valladolid": "516d3bf4b6f74524f66e3634f6f077fb3d97ad64eb1da9ed9f5d4f6df8eb3627",
    "bologna": "0a4df1380afa7db1b1f6980adafafb3be754c4a6d28ccf7457e749f16e4495a4",
}
CROP_SHA256 = "b65cf37a478542d74564094dc0760c69bd3cda99452eb6e7d327e457f87ba9a9"
# Preserve the original management problems and target regions. Repeated
# initial disease/insect resetting has been replaced with explicit arrivals;
# weed emergence still adds new weeds. All pressures are engineering inputs,
# not measured disease incidence or field-calibrated pest thresholds.
PRESSURE = {
    IDS[0]: [], IDS[1]: [], IDS[2]: [],
    IDS[3]: [("weed", "2019-04-28", "2019-04-29", 0, 63, .18, "set", "once"),
             ("weed", "2019-05-23", "2019-05-25", 0, 63, .25, "add", "daily")],
    IDS[4]: [("insect", "2019-07-17", "2019-07-20", 16, 39, .58, "set", "once")],
    IDS[5]: [("insect", "2019-06-26", "2019-06-27", 12, 31, .24, "set", "once"),
             ("insect", "2019-07-20", "2019-07-22", 18, 45, .58, "set", "once")],
    IDS[6]: [("disease", "2019-06-19", "2019-06-21", 18, 45, .54, "set", "once")],
    IDS[7]: [("disease", "2019-06-19", "2019-06-21", 20, 43, .52, "set", "once")],
    IDS[8]: [("weed", "2019-05-29", "2019-05-31", 4, 23, .24, "add", "daily"),
             ("disease", "2019-06-24", "2019-06-26", 32, 51, .52, "set", "once")],
    IDS[9]: [("weed", "2019-05-24", "2019-05-27", 12, 45, .18, "add", "daily")],
}
CAPS = {
    IDS[3]: {"management_regime": "low_chemical", "active_ingredient_cap_kg": 0.,
             "max_machine_passes": 7, "max_mechanical_weed_ridges": 64},
    IDS[5]: {"max_insecticide_applications": 3, "active_ingredient_cap_kg": .24},
}
REQUIRED_TREATMENTS = {
    IDS[1]: {"irrigate"}, IDS[2]: {"apply_fertilizer"},
    IDS[3]: {"mechanical_weed_control"}, IDS[4]: {"spray_pesticide"},
    IDS[5]: {"spray_pesticide"}, IDS[6]: {"apply_fungicide"},
    IDS[7]: {"apply_fungicide", "irrigate"},
    IDS[8]: {"mechanical_weed_control", "apply_fungicide"},
    IDS[9]: {"apply_herbicide"},
}


def _load(case):
    version = _version(case)
    path = ROOT / version["wofost_source_path"]
    module = importlib.import_module(".".join(path.relative_to(ROOT).with_suffix("").parts))
    cls = getattr(module, version["wofost_class_name"])
    return module, cls, cls()


def _arguments(event):
    bound = inspect.signature(event.function).bind(event.app, *event.args, **event.kwargs)
    bound.apply_defaults()
    return {key: value for key, value in bound.arguments.items() if key != "self"}


def _method(event):
    return event.function.__name__


def _range(arguments):
    return range(int(arguments.get("start_ridge", arguments.get("start"))),
                 int(arguments.get("end_ridge", arguments.get("end"))) + 1)


def _operation_day(event):
    # Published static IDs carry the local start date; a wait carries its
    # destination date. Real completion/clock equivalence is audited in replay.
    return date.fromisoformat(event.event_id.split('_')[1])


def _operational_snapshot(scene, clock):
    farm = scene.get_typed_app(FarmWorldApp)
    return deepcopy({
        "clock": clock.time(), "farm": farm.get_state(),
        "tractor": scene.get_typed_app(TractorApp).get_state(),
        "messages": scene.get_typed_app(AgentUserInterface).messages,
        "last_physics_time": farm.physics.last_physics_sim_time,
        "action_log": farm.physics.action_log,
        "biotic_states": farm.physics.biotic.states,
        "native": farm.physics.crop_backend.export_state(),
    })


@pytest.fixture(scope="module", params=RELEASED_CASES, ids=RELEASED_IDS)
def built(request):
    case = request.param
    module, cls, scene = _load(case)
    # setup establishes declared initial conditions for Agent and Oracle alike.
    # Building the plan from that world must not perform any farming or growth.
    scene.setup()
    engine = Engine(None, scene)
    before = _operational_snapshot(scene, engine.time_manager)
    events = scene.build_events_flow()  # Idempotent declarations, fresh capture.
    workflow = engine.build_oracle_workflow(run_oracle=False)
    after = _operational_snapshot(scene, engine.time_manager)
    assert all(step.content is None for step in workflow.dag.values())
    return case, module, cls, scene, list(scene.events if events is None else events), before, after



def test_selection_retains_ten_original_formal90_ids_files_and_classes():
    ids = (ROOT / "scripts/fullseason/formal_90_scenario_ids.txt").read_text().splitlines()
    assert len(CASES) == len(set(IDS)) == 10
    assert {PREFIX + row[0] for row in CASES} <= set(ids)
    for case in CASES:
        module, cls, _ = _load(case)
        version = _version(case)
        assert Path(module.__file__).resolve() == (ROOT / version["wofost_source_path"]).resolve()
        assert cls.__name__ == version["wofost_class_name"]
        assert cls.scenario_id == version["wofost_id"]
        assert get_scenario_class(cls.scenario_id) is cls


@pytest.mark.parametrize("case", RELEASED_CASES, ids=RELEASED_IDS)
def test_each_original_source_owns_a_static_complete_plan(case):
    module, cls, _ = _load(case)
    tree = ast.parse(Path(module.__file__).read_text())
    declared = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == cls.__name__)
    assert cls.__bases__ == (WofostFarmScenario,)
    assert "WORLD" in cls.__dict__ and "build_events_flow" in cls.__dict__
    assert not hasattr(cls, "execute_oracle_workflow")
    world = next(node.value for node in declared.body if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "WORLD" for t in node.targets))
    assert isinstance(world, ast.Call) and isinstance(world.func, ast.Name) and world.func.id == "FarmDefinition"
    assert {"reference_id", "seed_type", "timezone_name", "sowing_date", "end_date", "farm_id",
            "num_ridges", "field_length_m", "ridge_width_m", "initial_vwc", "soil_depth_m",
            "initial_available_n_kg_ha", "base_soil_n_kg_ha", "base_fertilizer_kg",
            "seed_stock", "warehouse_fertilizer_kg", "warehouse_pesticide_l", "warehouse_fuel_l",
            "tractor_fuel_l", "irrigation_quota_mm", "active_ingredient_cap_kg",
            "max_machine_passes", "external_biotic_coupling", "planting_density_plants_m2",
            "required_field_preparation_ops"} <= {kw.arg for kw in world.keywords}
    assert isinstance(module.FARMING_PLAN, (tuple, list)) and module.FARMING_PLAN
    assert all(isinstance(item, str) and re.search(r'[\u4e00-\u9fff]', item)
               for item in module.FARMING_PLAN)
    assert not any('validation_runs' in item or '.json' in item for item in module.FARMING_PLAN)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith(("scripts", "json"))
            assert "batch_scenario" not in (node.module or "")
            assert not (node.module or "").startswith("fairy.scenarios.wofost_reference")
        if isinstance(node, ast.Import):
            assert not any(name.name.startswith(("scripts", "json")) for name in node.names)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "eval", "exec", "build_batch_events", "WofostOracleTools"}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"read_text", "read_bytes", "load_workflow"}
    plan = next(node for node in declared.body if isinstance(node, ast.FunctionDef) and node.name == "build_events_flow")
    assert not any(isinstance(node, (ast.If, ast.While, ast.Try, ast.Match, ast.IfExp, ast.ListComp,
                                    ast.SetComp, ast.DictComp, ast.GeneratorExp)) for node in ast.walk(plan))
    for node in ast.walk(plan):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"physics", "_physics", "_runs", "pcse", "content", "response", "result",
                                     "execute", "execute_oracle_workflow", "read_text", "read_bytes", "run_until"}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id in {"install_scenario_events", "PressureEvent", "DroughtEvent",
                                    "WeatherWindowEvent", "date", "list"}
    capture_blocks = [node for node in ast.walk(plan) if isinstance(node, ast.With)
                      and any(isinstance(item.context_expr, ast.Call)
                              and isinstance(item.context_expr.func, ast.Attribute)
                              and item.context_expr.func.attr == "capture_mode" for item in node.items)]
    assert len(capture_blocks) == 1
    for node in ast.walk(plan):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in {"aui", "farm", "tractor", "weather", "sensor", "robot", "field_ops", "system"}):
            assert capture_blocks[0].lineno < node.lineno <= capture_blocks[0].end_lineno
    # The only source loop marks captured events for real tool timing; it does
    # not generate farm work or decide on a response at build time.
    loops = [node for node in ast.walk(plan) if isinstance(node, ast.For)]
    assert all(isinstance(loop.iter, ast.Name) and loop.iter.id == "captured" for loop in loops)


def test_held_original_nutrient_case_is_unchanged_registered_and_buildable():
    # The pre-version source was independently matched to the archived source.
    # Remove only version identifiers and the authorized public task text;
    # the held world and workflow must not acquire a new mechanism.
    module, cls, scene = _load(HELD_CASE)
    assert HELD_CASE not in RELEASED_CASES and len(RELEASED_CASES) == 9
    assert HELD_REASON
    version = _version(HELD_CASE)
    assert version["calibration_status"] == "uncalibrated"
    text = Path(module.__file__).read_text()
    tree = ast.parse(text)
    cls_node = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    detail = [node for node in cls_node.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == 'DETAILED_BRIEFING'
                      for target in node.targets)]
    assert len(detail) == 1 and isinstance(ast.literal_eval(detail[0].value), str)
    lines = text.splitlines(keepends=True)
    text = ''.join(lines[:detail[0].lineno - 1] + lines[detail[0].end_lineno:])
    marker = "CALIBRATION_STATUS = 'uncalibrated'\n"
    assert text.count(marker) == 1
    unversioned = text.replace(marker, "").replace(version["wofost_id"], version["legacy_id"])
    unversioned = unversioned.replace(version["wofost_class_name"], version["legacy_class_name"])
    assert hashlib.sha256(unversioned.encode()).hexdigest() == HELD_SOURCE_SHA256
    assert get_scenario_class(cls.scenario_id) is cls
    scene.setup()
    engine = Engine(None, scene)
    before = _operational_snapshot(scene, engine.time_manager)
    workflow = engine.build_oracle_workflow(run_oracle=False)
    assert workflow.dag and all(step.content is None for step in workflow.dag.values())
    assert _operational_snapshot(scene, engine.time_manager) == before
    assert scene.WORLD.required_field_preparation_ops == ('level', 'base_fertilize', 'form_ridges')


def test_default_native_official_identity_geometry_and_pinned_data(built):
    case, _, _, scene, _, _, _ = built
    world = scene.WORLD
    assert scene.crop_backend == "wofost"
    assert world.reference_id == case[3] and world.seed_type == case[4]
    assert scene.reference["variety"] == case[4].replace("SOYBEAN_", "Soybean_")
    assert (world.num_ridges, world.field_length_m, world.ridge_width_m) == (64, 268., 1.1)
    assert world.num_ridges * world.field_length_m * world.ridge_width_m == pytest.approx(18867.2)
    assert world.sowing_date == date(2019, 4, 30 if case[3] in {"valladolid", "bologna"} else 28)
    assert world.end_date == date(2019, 11, 15)
    assert scene.crop_backend_options["cultivar_map"] == {world.seed_type: scene.reference["variety"]}
    # Forty is the adapter's biomass normalization, not an official optimum.
    assert scene.crop_backend_options["reference_density_plants_m2"] == 40.
    assert math.isfinite(world.planting_density_plants_m2) and world.planting_density_plants_m2 > 0
    assert scene.crop_backend_options.get("parameter_overrides", {}) == {}
    assert scene.crop_backend_options.get("cultivar_profiles", {}) == {}
    assert scene.reference["parameter_overrides"] == {} and scene.reference["native_parameter_count"] == 78
    assert scene.reference["field_validation_available"] is False
    assert scene.reference["weather_sha256"] == WEATHER_SHA256[world.reference_id]
    assert hashlib.sha256((DATA / scene.reference["weather_path"]).read_bytes()).hexdigest() == WEATHER_SHA256[world.reference_id]
    manifest = json.loads((DATA / "manifest.json").read_text())
    assert manifest["crop_source"]["sha256"] == CROP_SHA256
    assert hashlib.sha256((DATA / manifest["crop_source"]["path"]).read_bytes()).hexdigest() == CROP_SHA256
    assert len(scene.daily_weather) == 275
    assert scene.daily_weather[0]["date"] == "2019-03-01" and scene.daily_weather[-1]["date"] == "2019-11-30"
    farm = scene.get_typed_app(FarmWorldApp)
    assert farm.physics.crop_backend_name == "wofost"
    native = farm.physics.crop_backend.config
    assert native.parameter_overrides == {} and native.cultivar_profile is None
    assert native.cultivar_map == scene.crop_backend_options["cultivar_map"]
    assert world.required_field_preparation_ops == ('level', 'form_ridges')
    assert farm.required_field_preparation_ops == world.required_field_preparation_ops
    assert farm.completed_prep_ops == []


def test_build_only_captures_without_changing_time_resources_or_bare_crops(built):
    _, _, _, scene, events, before, after = built
    assert before == after
    assert before["clock"] == scene.start_time
    assert before["last_physics_time"] in (None, scene.start_time)
    assert before["native"]["runs"] == {} and before["native"]["last_day"] is None
    assert not before["action_log"]
    assert all(not row["planted"] and not row["harvested"] and row["seeds_planted"] == 0
               for row in before["farm"]["ridges"])
    assert before["messages"] == []
    assert scene.events == events and events
    assert all(event.app in scene.apps for event in events)
    work = [event for event in events if event.is_oracle]
    assert len({event.event_id for event in work}) == len(work)
    assert all(isinstance(event.event_id, str) and event.event_id for event in work)
    for previous, event in zip([None] + work[:-1], work):
        assert event.dependencies == ([] if previous is None else [previous])
        assert math.isfinite(event.delay_seconds) and event.delay_seconds >= 0
        assert event.record_runtime_timing is True
        if _method(event) != "send_message_to_agent":
            assert event.is_oracle is True
        _arguments(event)  # Every literal call binds to the actual public API.
    waits = [event for event in events if isinstance(event.app, SystemApp) and _method(event) == "advance_time"]
    assert waits, "Seasonal waiting must be explicit real System tool work"
    assert all(float(_arguments(event)["seconds"]) > 0 for event in waits)


def test_captured_full_season_has_real_sowing_management_and_storage_paths(built):
    case, _, _, scene, events, _, _ = built
    methods = {_method(event) for event in events}
    assert {"level", "form_ridges", "load_seeds", "plant_seeds",
            "get_current_weather", "get_forecast", "read_soil_sensors", "get_ridge_range_state",
            "harvest", "unload_grain", "store_grain"} <= methods
    base_events = [event for event in events if _method(event) == 'base_fertilize']
    if scene.WORLD.base_fertilizer_kg:
        assert sum(_arguments(event)['total_kg'] for event in base_events) == pytest.approx(scene.WORLD.base_fertilizer_kg)
        assert 'load_fertilizer' in methods
    else:
        assert not base_events, 'No zero-dose or fictitious base-fertilizer operation'
        sowing = next(index for index, event in enumerate(events) if _method(event) == 'plant_seeds')
        assert not any(_method(event) == 'load_fertilizer' for event in events[:sowing])
    assert REQUIRED_TREATMENTS.get(case[0], set()) <= methods
    for name in ("plant_seeds", "harvest"):
        rows = [rid for event in events if _method(event) == name for rid in _range(_arguments(event))]
        assert Counter(rows) == Counter(range(64)), (name, rows)
    farm = scene.get_typed_app(FarmWorldApp)
    spacing_cm = 200. / (scene.WORLD.ridge_width_m * scene.WORLD.planting_density_plants_m2)
    per_ridge = int(round(scene.WORLD.field_length_m * 2. * 100. / spacing_cm))
    assert farm.crop_profile.rows_per_ridge == 2
    assert farm.plants_per_ridge_from_spacing(spacing_cm) == per_ridge
    sown, loaded, load_calls = 0, 0, 0
    for event in events:
        args, name = _arguments(event), _method(event)
        if name == "load_seeds":
            assert args["seed_type"] == scene.WORLD.seed_type
            assert 0 < args["count"] <= 300000 - (loaded - sown)
            loaded += args["count"]
            load_calls += 1
        elif name == "plant_seeds":
            assert args["depth_cm"] == 4.0
            assert args["seed_spacing_cm"] == pytest.approx(spacing_cm)
            assert len(_range(args)) <= 4
            sown += per_ridge * len(_range(args))
            assert loaded >= sown, "Seeds must be loaded before each actual sowing block"
    assert sown == per_ridge * 64
    assert sown <= loaded <= scene.WORLD.seed_stock
    minimum_loads = math.ceil(sown / 300000)
    assert minimum_loads <= load_calls <= minimum_loads + 1
    assert sum(_method(event) == "plant_seeds" for event in events) == 16
    assert sum(_method(event) == "harvest" for event in events) == 16
    assert all(len(_range(_arguments(event))) <= 4 for event in events if _method(event) == "harvest")
    assert all(event.operation_type in {OperationType.READ, OperationType.WRITE, None} for event in events)
    in_tractor, awaiting_store = False, False
    for event in events:
        name, args = _method(event), _arguments(event)
        if name == "harvest":
            in_tractor = True
        elif name == "unload_grain":
            assert in_tractor
            in_tractor, awaiting_store = False, True
        elif name == "dry_grain":
            assert awaiting_store
            assert 0 < args["target_moisture_pct"] <= 13.5
        elif name == "store_grain":
            assert awaiting_store, "Storage must follow the actual unload, with drying when required"
            awaiting_store = False
    assert not in_tractor and not awaiting_store


def test_event_declarations_preserve_original_problems_and_explicit_arrivals(built):
    case, _, _, scene, _, _, _ = built
    farm = scene.get_typed_app(FarmWorldApp)
    ledger = farm.physics.scenario_metadata.get("wofost_scenario_events", {})
    declarations = ledger.get("events", [])
    assert len({row["event_id"] for row in declarations}) == len(declarations)
    # An initial seed-bank declaration may be installed at setup; no later
    # daily injection or crop journal is allowed before actual execution.
    assert all(day == scene.WORLD.sowing_date.isoformat()
               for days in ledger.get("applied_pressure_days", {}).values() for day in days)
    actual = []
    for row in declarations:
        assert row["farm_id"] == scene.WORLD.farm_id
        assert scene.WORLD.sowing_date <= date.fromisoformat(row["start"]) < date.fromisoformat(row["end"]) <= scene.WORLD.end_date
        if row["type"] == "pressure":
            assert 0 <= row["ridge_start"] <= row["ridge_end"] < 64
            assert row["value"] > 0, "Ending exposure must not forcibly clear the resulting pressure"
            actual.append((row["kind"], row["start"], row["end"], row["ridge_start"],
                           row["ridge_end"], row["value"], row["mode"], row["repeat"]))
    expected = PRESSURE[case[0]]
    assert len(actual) == len(expected)
    for observed, original in zip(actual, expected):
        if original[7] == 'once':
            # A once-arrival's end merely bounds its eligible interval;
            # it does not repeat inoculum or reset treatment on later days.
            assert observed[:2] == original[:2]
            assert observed[3:] == original[3:]
        else:
            assert observed == original
    if declarations:
        assert "never automatically clear" in ledger["stop_semantics"]


def test_declared_water_evidence_and_original_chemical_machine_caps_are_respected(built):
    case, module, _, scene, events, _, _ = built
    world = scene.WORLD
    for name in ("active_ingredient_cap_kg", "max_machine_passes",
                 "max_mechanical_weed_ridges", "max_insecticide_applications",
                 "max_fungicide_applications"):
        assert getattr(world, name) == CAPS.get(case[0], {}).get(name)
    assert world.management_regime == CAPS.get(case[0], {}).get("management_regime", "conventional")
    if case[0] in {IDS[1], IDS[7]}:
        reference = module.IRRIGATION_REFERENCE_MM
        assert isinstance(reference, (int, float)) and not isinstance(reference, bool)
        assert math.isfinite(reference) and 0 < world.irrigation_quota_mm < reference
        quota, expected_reference = (240., 260.) if case[0] == IDS[1] else (11.25, 13.125)
        assert world.irrigation_quota_mm == quota and reference == expected_reference
        assert module.IRRIGATION_SELECTION_NOTES
        assert isinstance(module.IRRIGATION_SELECTION_NOTES, (str, tuple, list, dict))
        notes = json.dumps(module.IRRIGATION_SELECTION_NOTES, ensure_ascii=False)
        assert len(notes.strip()) > 20
        assert not any(claim in notes.lower() for claim in ('达到产量平台99%', 'minimum_tested_99pct', 'global optimum proven'))
        tree = ast.parse(Path(module.__file__).read_text())
        local_names = {target.id for node in tree.body if isinstance(node, ast.Assign)
                       for target in node.targets if isinstance(target, ast.Name)}
        assert {"IRRIGATION_REFERENCE_MM", "IRRIGATION_SELECTION_NOTES"} <= local_names
    else:
        assert world.irrigation_quota_mm is None
    used_mm, chemical_kg = 0., 0.
    for event in events:
        args, name = _arguments(event), _method(event)
        if name == "irrigate":
            used_mm += 5. * args["hours"] * len(_range(args)) / 64
        if name in {"spray_pesticide", "apply_fungicide", "apply_herbicide"}:
            chemical_kg += .001 * args["liters_per_ridge"] * len(_range(args))
    if world.irrigation_quota_mm is not None:
        assert used_mm <= world.irrigation_quota_mm + 1e-7
    if world.active_ingredient_cap_kg is not None:
        assert chemical_kg <= world.active_ingredient_cap_kg + 1e-7
    if case[0] == IDS[3]:
        weed = [event for event in events if _method(event) == "mechanical_weed_control"]
        assert len(weed) <= 7
        covered = [rid for event in weed for rid in _range(_arguments(event))]
        assert Counter(covered) == Counter(range(64))
        assert all(len(_range(_arguments(event))) <= 10 for event in weed)
        assert chemical_kg == 0.
    if case[0] in {IDS[1], IDS[7]}:
        first, last = (22, 43) if case[0] == IDS[1] else (20, 43)
        soil = scene.get_typed_app(FarmWorldApp).physics.soil
        assert set(soil.hydraulic_modifiers) == set(range(first, last + 1))
        for rid in range(first, last + 1):
            hydraulic = soil.params_for_ridge(rid)
            assert hydraulic.field_capacity_vwc == .31
            assert hydraulic.root_drainage_rate == .26
            assert hydraulic.rainfall_capture_efficiency == .82
            assert hydraulic.irrigation_efficiency == .86
            assert hydraulic.max_infiltration_mm_day == 85.
    if case[0] == IDS[2]:
        baseline = _load(CASES[0])[2].WORLD
        assert world.initial_available_n_kg_ha < baseline.initial_available_n_kg_ha
        assert world.base_soil_n_kg_ha < baseline.base_soil_n_kg_ha
        assert world.base_fertilizer_kg <= 2.


def test_leaf_feeder_description_does_not_claim_native_leaf_area_removal():
    module, _, scene = _load(CASES[4])
    text = Path(module.__file__).read_text()
    assert "PGASS" in text or "总同化" in text or "光合" in text
    assert "非原生" in text or "不模拟" in text or "not native" in text or "不直接" in text
    assert "Soybean_905" in scene.reference_briefing()


def test_original_management_problem_is_preserved_in_events_and_operations(built):
    """A shorter plan must still answer the original management question.

    These are task/region/window assertions, not golden totals or yield fits.
    Exact legal execution days remain free inside the relevant task window.
    """
    case, _, _, scene, events, _, _ = built
    number = IDS.index(case[0]) + 1
    farm = scene.get_typed_app(FarmWorldApp)
    declarations = farm.physics.scenario_metadata.get('wofost_scenario_events', {}).get('events', [])
    operations = {}
    for event in events:
        operations.setdefault(_method(event), []).append(event)

    def covered(method):
        return Counter(rid for event in operations.get(method, [])
                       for rid in _range(_arguments(event)))

    def doses(method, value):
        assert operations.get(method)
        assert all(_arguments(event)['liters_per_ridge'] == value
                   for event in operations[method])

    # Normal functioning biological N fixation is not a reason for a routine
    # mineral-N application in every task. The low-N task is the sole exception.
    if number != 3:
        assert scene.WORLD.base_fertilizer_kg == 0.
        assert 'base_fertilize' not in operations and 'apply_fertilizer' not in operations
    for event in operations.get('inspect_crop_health', []) + operations.get('inspect_emergence', []):
        assert len(_range(_arguments(event))) <= 4, 'A requested sample cannot pretend to cover a whole problem zone'

    if number == 1:
        assert declarations == [], 'Normal season must not acquire hidden rain or a forced problem'
        assert not {'spray_pesticide', 'apply_fungicide', 'apply_herbicide', 'mechanical_weed_control'} & set(operations)
        assert all(5. * _arguments(event)['hours'] >= 20.
                   for event in operations.get('irrigate', [])), 'Normal plan uses useful irrigation rounds, not tiny quota tails'
    elif number == 2:
        drought, = [row for row in declarations if row['type'] == 'drought']
        assert (drought['start'], drought['end'], drought['rain_multiplier']) == ('2019-06-25', '2019-07-21', 0.)
        assert not any(row['type'] == 'pressure' for row in declarations)
        assert all(5. * _arguments(event)['hours'] >= 5.
                   for event in operations['irrigate']), 'No sub-millimeter budget-filling operation'
    elif number == 3:
        assert scene.WORLD.initial_available_n_kg_ha == scene.WORLD.base_soil_n_kg_ha == 0.
        assert declarations == [], 'Low-N signal must arise from native nutrient inputs'
        assert covered('apply_fertilizer') == Counter(range(64))
        assert len({_operation_day(event) for event in operations['apply_fertilizer']}) == 1
        assert all(_arguments(event)['kg_per_ridge'] > 0 for event in operations['apply_fertilizer'])
    elif number == 4:
        assert covered('mechanical_weed_control') == Counter(range(64))
        assert len({_operation_day(event) for event in operations['mechanical_weed_control']}) == 1
        assert all(date(2019, 5, 25) <= _operation_day(event) <= date(2019, 6, 1)
                   for event in operations['mechanical_weed_control'])
        assert not {'spray_pesticide', 'apply_fungicide', 'apply_herbicide'} & set(operations)
    elif number == 5:
        doses('spray_pesticide', 8.)
        assert covered('spray_pesticide') == Counter(range(16, 40))
        assert all(date(2019, 7, 17) <= _operation_day(event) <= date(2019, 7, 26)
                   for event in operations['spray_pesticide'])
    elif number == 6:
        arrivals = [row for row in declarations if row['type'] == 'pressure']
        assert len(arrivals) == 2 and arrivals[0]['value'] < arrivals[1]['value']
        assert all(row['repeat'] == 'once' for row in arrivals), 'Keep two distinct arrivals without daily overwriting of treatment'
        assert 'inspect_ridge' in operations, 'Use existing public pest_count_estimate, not private pressure or confidence as severity'
        doses('spray_pesticide', 8.)
        assert covered('spray_pesticide') == Counter(range(18, 46))
        assert len({_operation_day(event) for event in operations['spray_pesticide']}) == 1
        assert all(_operation_day(event) >= date(2019, 7, 20) for event in operations['spray_pesticide'])
        cap = scene.WORLD.active_ingredient_cap_kg
        heavy = .001 * 8 * 28
        both = .001 * 8 * (20 + 28)
        assert heavy <= cap < both, 'The budget can fund the heavy episode fully, but not both full treatments'
    elif number == 7:
        window, = [row for row in declarations if row['type'] == 'weather_window'
                   and row['start'] == '2019-06-22' and row['end'] == '2019-06-25']
        assert window['rain_mm'] == 0. and window['wind_ms'] == 2.
        doses('apply_fungicide', 3.8)
        assert covered('apply_fungicide') == Counter(range(18, 46))
        assert all(date.fromisoformat(window['start']) <= _operation_day(event) < date.fromisoformat(window['end'])
                   for event in operations['apply_fungicide']), 'Oracle must use the short legal window rather than redefine the task as July recovery only'
        rains = [row for row in declarations if row['type'] == 'weather_window' and (row.get('rain_mm') or 0.) > 0.]
        assert any(row['end'] <= window['start'] for row in rains)
        assert any(row['start'] >= window['end'] for row in rains)
    elif number == 8:
        drought, = [row for row in declarations if row['type'] == 'drought']
        assert (drought['start'], drought['end'], drought['rain_multiplier']) == ('2019-08-01', '2019-08-17', 0.)
        doses('apply_fungicide', 3.8)
        assert covered('apply_fungicide') == Counter(range(20, 44))
        water, = operations['irrigate']
        assert list(_range(_arguments(water))) == list(range(20, 44))
        assert 5. * _arguments(water)['hours'] == 30.
        assert date.fromisoformat(drought['start']) - timedelta(days=7) <= _operation_day(water) < date.fromisoformat(drought['end'])
        assert max(_operation_day(event) for event in operations['apply_fungicide']) < _operation_day(water)
    elif number == 9:
        assert covered('mechanical_weed_control') == Counter(range(4, 24))
        assert covered('apply_fungicide') == Counter(range(32, 52))
        doses('apply_fungicide', 3.8)
        assert max(_operation_day(event) for event in operations['mechanical_weed_control']) < date(2019, 6, 24)
        assert min(_operation_day(event) for event in operations['apply_fungicide']) >= date(2019, 6, 24)
    elif number == 10:
        rain, = [row for row in declarations if row['type'] == 'weather_window']
        assert (rain['start'], rain['end']) == ('2019-05-24', '2019-05-30')
        assert rain['rain_mm'] == pytest.approx(64. / 6.)
        pressure, = [row for row in declarations if row['type'] == 'pressure']
        overlap_days = (min(date.fromisoformat(pressure['end']), date.fromisoformat(rain['end']))
                        - max(date.fromisoformat(pressure['start']), date.fromisoformat(rain['start']))).days
        assert overlap_days > 0, 'Weeds must be present while rain blocks recovery'
        doses('apply_herbicide', 8.)
        assert covered('apply_herbicide') == Counter(range(12, 46))
        first_legal = date.fromisoformat(rain['end'])
        assert all(first_legal <= _operation_day(event) <= first_legal + timedelta(days=7)
                   for event in operations['apply_herbicide']), 'Preserve rain-after recovery, not pre-rain prevention'
        assert 'mechanical_weed_control' not in operations


def test_realized_integer_density_changes_only_tdwi_from_original_78_parameters(built):
    _, _, _, scene, events, _, _ = built
    world = scene.WORLD
    farm = scene.get_typed_app(FarmWorldApp)
    backend = farm.physics.crop_backend
    official_document = yaml.safe_load((DATA / "../../soybean.yaml").read_text())
    official = {key: deepcopy(value[0]) for key, value in
                official_document["CropParameters"]["Varieties"][scene.reference["variety"]].items()
                if key != "Metadata"}
    assert len(official) == 78 and official["TDWI"] == 120.
    assert backend._crop_parameters(scene.reference["variety"], world.seed_type) == official
    sow = next(event for event in events if _method(event) == "plant_seeds")
    spacing = _arguments(sow)["seed_spacing_cm"]
    assert spacing == pytest.approx(200. / (world.ridge_width_m * world.planting_density_plants_m2))
    count = int(round(world.field_length_m * 2. * 100. / spacing))
    realized = count / (world.field_length_m * world.ridge_width_m)
    assert abs(realized - world.planting_density_plants_m2) <= .5 / farm.ridge_area_m2 + 1e-12
    # Construct only a native input specification. No PCSE crop is started and
    # no day is advanced. The temporary phenology input is restored afterwards.
    original = farm.physics.phenology.states[0]
    initial = deepcopy(original)
    initial.seed_type, initial.planting_date = world.seed_type, world.sowing_date
    farm.physics.phenology.states[0] = initial
    original_management = farm.physics.management.states[0]
    planted_management = deepcopy(original_management)
    planted_management.stand_fraction = 1.  # Nominal sowing, not the bare-field zero stand.
    farm.physics.management.states[0] = planted_management
    try:
        specification = backend._specification(farm.physics, 0, world.sowing_date, realized)
    finally:
        farm.physics.phenology.states[0] = original
        farm.physics.management.states[0] = original_management
    effective = specification["crop_parameters"]
    assert specification["initial_stand_fraction"] == 1.
    assert specification["density_method"] == "TDWI_initial_biomass_scaling_only"
    assert effective["TDWI"] == pytest.approx(120. * realized / 40.)
    assert {key: value for key, value in effective.items() if key != "TDWI"} == {
        key: value for key, value in official.items() if key != "TDWI"}
    assert backend.export_state()["runs"] == {} and backend.last_day is None


def test_fixed_plan_does_not_repeat_same_request_without_work_or_real_wait(built):
    _, _, _, _, events, _, _ = built
    seen = set()
    for event in (item for item in events if item.is_oracle):
        # System.advance_time is currently labeled READ; its real state/time
        # effect makes it a boundary just like an ordinary WRITE operation.
        if event.operation_type != OperationType.READ or (
                isinstance(event.app, SystemApp) and _method(event) == "advance_time") or event.delay_seconds > 0:
            seen.clear()
            continue
        key = (event.app.name, _method(event), json.dumps(_arguments(event), sort_keys=True))
        assert key not in seen, f"No intervening work or time: duplicate request {event.event_id} {key}"
        seen.add(key)


def test_saved_workflow_names_persist_date_purpose_and_dose_without_using_responses(built, tmp_path):
    _, module, cls, scene, events, _, _ = built
    data = scene.workflow.to_dict()
    assert data and all(row["content"] is None for row in data.values())
    for step_id, row in data.items():
        assert step_id == row["name"]
        assert re.match(r"^\d+_\d{4}-\d{2}-\d{2}_.+", step_id)
        assert re.search(r"[\u4e00-\u9fff]", step_id)
    target = tmp_path / "fixed_plan_with_visible_purposes.json"
    scene.workflow.save_workflow(str(target))
    assert Workflow.load_workflow(str(target)).to_dict() == data
    # Execute only one ordinary public READ in a fresh world to verify name
    # persistence through actual replay; no farming or calendar day is run.
    step_id, original = next((name, row) for name, row in data.items()
                             if row["tool_name"].endswith("__get_inventory"))
    one = Workflow()
    one.add_node(WorkflowStep(**{**original, "depends_on": []}))
    fresh = cls()
    engine = Engine(None, fresh)
    replayed = engine.replay_workflow(one)
    assert list(replayed.dag) == [step_id]
    assert replayed.dag[step_id].name == step_id
    assert replayed.dag[step_id].content is not None
    assert engine.time_manager.time() == fresh.start_time
    if any(_method(event) == "dry_grain" for event in events):
        text = Path(module.__file__).read_text().lower()
        assert any(word in text for word in ("即时", "瞬时", "零耗时", "instant", "zero-time"))
        assert "干燥" in text or "dry" in text


def assert_public_replay_storage_contract(replay, *, num_ridges=64):
    """Check actual saved public receipts; useful for independent CLI audits.

    The current tool's grain_kg_added/bin mass is standardized at13% moisture.
    A conservative wet-mass check uses each pass's maximum *public* observed
    moisture plus0.1 percentage point for its rounding, never native state.
    """
    moisture, standard_bin, wet_bin = {}, 0., 0.
    harvested, stored = [], []
    for step in replay.values():
        tool, content = step.get("tool_name", ""), step.get("content") or {}
        assert not content.get("error") and content.get("status") not in {"partial", "error", "failed"}
        if tool.endswith("__get_ridge_range_state"):
            for row in content.get("ridges", []):
                if not row.get("harvested"):
                    moisture[row["ridge_id"]] = row["grain_moisture_pct"]
        elif tool.endswith("__harvest"):
            ids = content["harvested_ridges"]
            assert ids and len(ids) <= 4
            assert all(rid in moisture and 0 < moisture[rid] <= 18. for rid in ids)
            standard_bin += content["grain_kg_added"]
            wet_bin += content["grain_kg_added"] * .87 / (1. - (max(moisture[rid] for rid in ids) + .1) / 100.)
            assert standard_bin <= 2000. + 1e-9
            assert wet_bin <= 2000. + 1e-9
            assert content["grain_bin_kg"] == pytest.approx(standard_bin, abs=.051)
            harvested.extend(ids)
        elif tool.endswith("__unload_grain"):
            assert standard_bin > 0
            assert content["grain_kg_unloaded"] == pytest.approx(standard_bin, abs=.011)
            assert content["grain_bin_kg"] == 0.
            standard_bin, wet_bin = 0., 0.
        elif tool.endswith("__store_grain"):
            assert content["moved_kg"] > 0 and not content.get("warning")
            assert content["storage_grain_moisture_pct"] <= 13.5
            stored.extend(content["batch_ridge_ids"])
    assert standard_bin == 0. and wet_bin == 0.
    assert Counter(harvested) == Counter(range(num_ridges))
    assert Counter(stored) == Counter(range(num_ridges))


def _sample_public_storage_replay(*, mass=1800., moisture=14.):
    return {
        "observe": {"tool_name": "FarmWorldApp__get_ridge_range_state", "content": {"ridges": [
            {"ridge_id": rid, "grain_moisture_pct": moisture, "harvested": False} for rid in range(2)]}},
        "harvest": {"tool_name": "TractorApp__harvest", "content": {"status": "ok",
            "harvested_ridges": [0, 1], "grain_kg_added": mass, "grain_bin_kg": mass}},
        "unload": {"tool_name": "TractorApp__unload_grain", "content": {"status": "ok",
            "grain_kg_unloaded": mass, "grain_bin_kg": 0.}},
        "store": {"tool_name": "FarmWorldApp__store_grain", "content": {"status": "ok",
            "moved_kg": mass, "storage_grain_moisture_pct": 13., "batch_ridge_ids": [0, 1]}},
    }


def test_public_storage_audit_accepts_a_safe_actual_batch():
    assert_public_replay_storage_contract(_sample_public_storage_replay(), num_ridges=2)


@pytest.mark.parametrize("problem", ["standard_mass_overflow", "wet_mass_only_overflow", "no_public_moisture",
                                    "unload_mass_mismatch", "unsafe_storage", "partial_harvest", "missing_origin"])
def test_public_storage_audit_rejects_false_completion_evidence(problem):
    data = _sample_public_storage_replay()
    if problem == "standard_mass_overflow":
        data = _sample_public_storage_replay(mass=2001., moisture=13.)
    elif problem == "wet_mass_only_overflow":
        data = _sample_public_storage_replay(mass=1950., moisture=18.)
    elif problem == "no_public_moisture":
        data.pop("observe")
    elif problem == "unload_mass_mismatch":
        data["unload"]["content"]["grain_kg_unloaded"] -= 5.
    elif problem == "unsafe_storage":
        data["store"]["content"]["storage_grain_moisture_pct"] = 14.
    elif problem == "partial_harvest":
        data["harvest"]["content"]["status"] = "partial"
    elif problem == "missing_origin":
        data["store"]["content"]["batch_ridge_ids"] = [0]
    with pytest.raises(AssertionError):
        assert_public_replay_storage_contract(data, num_ridges=2)
