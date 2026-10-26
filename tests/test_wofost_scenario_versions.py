"""Independent legacy/WOFOST identities for the thirteen versioned tasks.

The original formal90 IDs remain legacy defaults. Their WOFOST counterparts
own separate _V2 files, classes and registrations. Both plans are only built
here; scientific outcomes and ordinary CLI replays are separately validated.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path

import pytest

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world import DroneApp, FarmWorldApp, TractorApp
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class, list_scenarios
from fairy.scenarios.wofost_farm import WofostFarmScenario

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "fairy/scenarios/farm_world_fullseason_v2"
MANIFEST = ROOT / "configs/oracles/wofost_scenario_versions.json"
DOCUMENT = json.loads(MANIFEST.read_text())
ROWS = DOCUMENT["rows"]
LEGACY_REF = "e0a302c3d3de9cf532ea5fd01bc79ebb3e9bb864"
# Computed independently from git multi-farm at LEGACY_REF. Tests do not
# require that historical commit to be available in a shallow CI checkout.
EXPECTED_LEGACY_SHA256 = {
    "scenario_full_season_hb_base_hn84_std_normal": "51724af584cc617396e0592cbefb5e5547753c3ce2fcd542adcf2534fc3560d3",
    "scenario_full_season_hb_dryr5r6_hn84_water_limit": "64d08c0d889295de46c37ba89bb3cfa8a7cb1fc6b70bf6ae6be6a3658c5f06f7",
    "scenario_full_season_hb_low_nutrient_carryover_flowering_nutrition": "ff2ed5d3cc77bcc4439805786b10d8df1680496334d0d52b78fe45f10dc19b17",
    "scenario_full_season_hb_high_weed_seedbank_mechanical_only_baseline": "fb91242c2cbe9b8ee214a8f3be497a9628b8b484102645398a68918ea5087e37",
    "scenario_full_season_hb_r5_leaf_feeder_defoliation": "0f5ec6926272334574febff027704f57984282dc52fadcbeab7dffa473332474",
    "scenario_full_season_hb_limited_spray_budget_season": "1202c7e21b54d144c21fd452ef30c4313fbef75fe6596eb33e2615b9823124cb",
    "scenario_full_season_hb_wetjune_short_spray_window": "b0118ce1ef27f7d70821db5940a38b6090f7d5f0c9d5d83e732a08f3b1d4ee6f",
    "scenario_full_season_hb_disease_then_drought_recovery_tradeoff": "8b430191b6f186378e98111a3e25d34c8ec05cd1785503fa183b0a650048f0be",
    "scenario_full_season_hb_weed_then_disease_canopy_confusion": "e6f2468c69ad062c74561d249f22befeb53d79e43614b24e66c86c296dbf0398",
    "scenario_full_season_hb_herbicide_window_missed_rain_delay": "abc482181143d88f5b99e3166700baa0e212ae192b4f4d697fd4965888701304",
    "scenario_full_season_fastdraining_dry_patch_irrigation": "a0858fbe804e4535b78417e9549bf5d4d28d656312ca56c5f115317d62b4bbae",
    "scenario_full_season_hb_two_dry_patches_one_irrigation": "a8b3c554baeff827a2dc6a5087fb966fbb962ddd496039b75bba4fb13c691dd6",
    "scenario_full_season_hb_hn60_high_fastdrain_dryr5r6": "448f5786aaf04e8d7f72a2d8c54523338d34de19894ccdbf74b38ef921bc8545"
}
UNCALIBRATED = "scenario_full_season_hb_low_nutrient_carryover_flowering_nutrition"


def _source(path):
    result = (ROOT / path).resolve()
    assert result.parent == SOURCE
    return result


def _load(row, kind):
    path = _source(row[kind + "_source_path"])
    name = ".".join(path.relative_to(ROOT).with_suffix("").parts)
    module = importlib.import_module(name)
    cls = getattr(module, row[kind + "_class_name"])
    return path, module, cls


def _snapshot(scene, engine):
    farm = scene.get_typed_app(FarmWorldApp)
    backend = farm.physics.crop_backend
    return deepcopy({
        "clock": engine.time_manager.time(), "farm": farm.get_state(),
        "tractor": scene.get_typed_app(TractorApp).get_state(),
        "messages": scene.get_typed_app(AgentUserInterface).messages,
        "drones": {app.name: app.get_state() for app in scene.apps if isinstance(app, DroneApp)},
        "physics_time": farm.physics.last_physics_sim_time,
        "actions": farm.physics.action_log,
        "native": backend.export_state() if backend is not None else None,
    })


def test_version_manifest_preserves_the_original_formal90_namespace_and_legacy_reference():
    assert DOCUMENT["schema_version"] == 1 and DOCUMENT["legacy_ref"] == LEGACY_REF
    assert len(ROWS) == 13
    legacy_ids = [row["legacy_id"] for row in ROWS]
    native_ids = [row["wofost_id"] for row in ROWS]
    assert len(set(legacy_ids)) == len(set(native_ids)) == 13
    assert set(legacy_ids) == set(EXPECTED_LEGACY_SHA256)
    assert not set(legacy_ids) & set(native_ids)
    formal = (ROOT / "scripts/fullseason/formal_90_scenario_ids.txt").read_text().splitlines()
    assert len(formal) == len(set(formal)) == 90
    assert set(legacy_ids) <= set(formal) and not set(native_ids) & set(formal)
    registered = set(list_scenarios())
    assert set(legacy_ids + native_ids) <= registered
    for row in ROWS:
        assert row["wofost_id"] == row["legacy_id"] + "_V2"
        legacy_path = _source(row["legacy_source_path"])
        assert _source(row["wofost_source_path"]) == legacy_path.with_name(legacy_path.stem + "_V2.py")
        assert row["wofost_class_name"] == row["legacy_class_name"] + "_V2"
    held = [row for row in ROWS if row["calibration_status"] == "uncalibrated"]
    assert [row["legacy_id"] for row in held] == [UNCALIBRATED]
    assert all(row["calibration_status"] in {"calibrated", "uncalibrated"} for row in ROWS)


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["legacy_id"])
def test_version_sources_and_registered_classes_are_independent_without_alias_overrides(row):
    legacy_path, legacy_module, legacy_cls = _load(row, "legacy")
    native_path, native_module, native_cls = _load(row, "wofost")
    assert row["legacy_sha256"] == EXPECTED_LEGACY_SHA256[row["legacy_id"]]
    current = row["legacy_current_sha256"]
    assert isinstance(current, str) and len(current) == 64
    assert hashlib.sha256(legacy_path.read_bytes()).hexdigest() == current
    assert legacy_cls is not native_cls and not issubclass(legacy_cls, WofostFarmScenario)
    assert native_cls.__bases__ == (WofostFarmScenario,)
    assert not any(value is legacy_cls for value in vars(native_module).values())
    assert not any(value is native_cls for value in vars(legacy_module).values())
    for kind, path, module, cls in (("legacy", legacy_path, legacy_module, legacy_cls),
                                    ("wofost", native_path, native_module, native_cls)):
        assert Path(module.__file__).resolve() == path and cls.__module__ == module.__name__
        assert module.SCENARIO_ID == cls.scenario_id == row[kind + "_id"]
        assert get_scenario_class(row[kind + "_id"]) is cls
        declarations = [node for node in ast.parse(path.read_text()).body if isinstance(node, ast.ClassDef)]
        assert [node.name for node in declarations] == [row[kind + "_class_name"]]
    native_tree = ast.parse(native_path.read_text())
    assert {"WORLD", "build_events_flow"} <= native_cls.__dict__.keys()
    if row["legacy_id"] == UNCALIBRATED:
        assert native_module.CALIBRATION_STATUS == "uncalibrated"
    assert not hasattr(native_cls, "execute_oracle_workflow")
    for node in ast.walk(native_tree):
        if isinstance(node, ast.ImportFrom):
            name = node.module or ""
            assert not name.startswith(("scripts", "json", "fairy.scenarios.farm_world_fullseason_v2.scenario_"))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"read_text", "read_bytes", "load_workflow"}


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["legacy_id"])
def test_default_backends_and_pure_plan_builds_remain_separate_for_each_pair(row):
    scenes = []
    for kind, expected_backend in (("legacy", "legacy"), ("wofost", "wofost")):
        _, _, cls = _load(row, kind)
        scene = cls()
        assert scene.crop_backend == expected_backend
        scene.setup()
        engine = Engine(None, scene)
        farm = scene.get_typed_app(FarmWorldApp)
        assert farm.physics.crop_backend_name == expected_backend
        assert (farm.physics.crop_backend is None) == (kind == "legacy")
        before = _snapshot(scene, engine)
        workflow = engine.build_oracle_workflow(run_oracle=False)
        assert workflow.dag and all(step.content is None for step in workflow.dag.values())
        assert _snapshot(scene, engine) == before
        assert engine.time_manager.time() == scene.start_time
        if kind == "wofost":
            assert before["native"]["runs"] == {} and before["native"]["last_day"] is None
        else:
            assert before["native"] is None
        scenes.append(scene)
    assert scenes[0] is not scenes[1]
    assert scenes[0].get_typed_app(FarmWorldApp) is not scenes[1].get_typed_app(FarmWorldApp)
