"""Two real crops, evidence-based interventions, and an in-memory fresh replay.

No filesystem fixtures or CLI calls: JSON serialization is exercised in memory.
Counterfactuals retain the successful operation durations and sample raw physics
at matched checkpoints without issuing extra observation tools.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, is_dataclass
import json
from statistics import mean
from types import SimpleNamespace

import pytest

from fairy.controllers.engine import Engine
from fairy.apps.farm_world.crop_snapshot import snapshot_physics
from fairy.physics.profiles import get_profile
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.two_farm.scenario_two_farm_maize_soybean_full_season import (
    ScenarioTwoFarmMaizeSoybeanFullSeason,
)
from fairy.scenarios.two_farm.scenario_two_farm_soybean_maize_disease_water import (
    BASE_WEATHER_PROFILE, SCENARIO_ID, TARGET_RIDGES,
    ScenarioTwoFarmSoybeanMaizeDiseaseWater,
)
from fairy.scenarios.workflow import Workflow, WorkflowStep


CHECKPOINTS = {"disease_followup_28", "drought_second_crop_recheck"}
RANDOM_IDS = {"action_id", "op_id", "mission_id", "inspection_id"}


def create_scene(cls=ScenarioTwoFarmSoybeanMaizeDiseaseWater):
    scene = cls(seed=37)
    scene.setup()
    return scene, Engine(None, scene)


def normalize(value):
    if is_dataclass(value):
        return normalize(asdict(value))
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items() if key not in RANDOM_IDS}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    return value


def raw_state(scene):
    """Read backing state only; FarmWorldApp.get_state applies due irrigation."""
    return deepcopy({
        "clock": scene.farm_environment.time_manager.time(),
        "farms": {
            farm.farm_id: {
                "ridges": [ridge.to_dict() for ridge in farm._ridges],
                "physics": snapshot_physics(farm.physics),
                "regime": farm._management_regime.to_dict(),
                "prep": farm.completed_prep_ops,
                "pending_irrigation": farm._pending_irrigation,
            }
            for farm in (scene.soybean, scene.maize)
        },
        "warehouse": scene.warehouse.get_state(),
        "weather": scene.weather.get_state(),
        "devices": {app.name: app.get_state() for app in scene.shared_equipment},
        "fixed": {app.name: app.get_state() for app in (
            scene.soybean_sensor, scene.maize_sensor,
            scene.soybean_irrigation, scene.maize_irrigation,
        )},
        "rng": {app.name: app.rng.getstate() for app in scene.apps if hasattr(app, "rng")},
    })


def json_roundtrip(workflow):
    result = Workflow()
    for name, values in json.loads(json.dumps(workflow.to_dict())).items():
        result.add_node(WorkflowStep(name=name, **{
            key: value for key, value in values.items() if key != "name"
        }))
    return result


def checkpoint(scene):
    return {
        "time": scene.farm_environment.time_manager.time(),
        "farms": {
            farm.farm_id: {
                "disease": mean(farm.physics.biotic.states[r].disease_pressure for r in TARGET_RIDGES),
                "root_vwc": mean(farm.physics.soil.states[r].root_vwc for r in TARGET_RIDGES),
                "surface_vwc": mean(farm.physics.soil.states[r].top_vwc for r in TARGET_RIDGES),
            }
            for farm in (scene.soybean, scene.maize)
        },
    }


def instrument_actions(scene, actions):
    """Wrap only checkpoint actions; preserve their public identity and metadata."""
    captured = {}
    wrapped = []
    for name, app, method, arguments, reason in actions:
        if name in CHECKPOINTS:
            original = getattr(app, method)

            def invoke(_original=original, _name=name, **kwargs):
                result = _original(**kwargs)
                captured[_name] = checkpoint(scene)
                return result

            invoke._event_operation_type = getattr(original, "_event_operation_type", None)
            app = SimpleNamespace(name=app.name, **{method: invoke})
        wrapped.append((name, app, method, arguments, reason))
    scene._reference_actions = lambda: wrapped
    return captured


def assert_no_tool_failures(workflow):
    assert not [(step.name, step.content) for step in workflow.dag.values()
                if step.error_stage or isinstance(step.content, dict)
                and (step.content.get("error") or step.content.get("ok") is False
                     or step.content.get("status") in {"error", "failed", "partial"})]


@pytest.fixture(scope="module")
def completed():
    scene, engine = create_scene()
    captured = instrument_actions(scene, scene._reference_actions())
    workflow = engine.run_scenario_oracle(True)
    assert_no_tool_failures(workflow)
    assert set(captured) == CHECKPOINTS
    result = engine.evaluate()
    assert result.success, result.message
    return SimpleNamespace(scene=scene, engine=engine, workflow=workflow, checkpoints=captured)


def test_registration_crop_geometry_and_source_profiles_are_isolated():
    before_profile = deepcopy(get_profile(BASE_WEATHER_PROFILE))
    baseline, _ = create_scene(ScenarioTwoFarmMaizeSoybeanFullSeason)
    baseline_before = raw_state(baseline)
    scene, engine = create_scene()
    assert get_scenario_class(SCENARIO_ID) is ScenarioTwoFarmSoybeanMaizeDiseaseWater
    assert raw_state(baseline) == baseline_before
    assert get_profile(BASE_WEATHER_PROFILE) == before_profile
    assert set(scene.farm_environment.farms) == {"soybean_field", "maize_field"}
    assert scene.plot_labels == {"soybean_field": "farm plot A", "maize_field": "farm plot B"}
    assert scene.soybean.num_ridges == scene.maize.num_ridges == 64
    assert scene.soybean.crop_id == "soybean" and scene.maize.crop_id == "maize"
    assert scene.soybean.cultivar_id == "HEINONG84"
    assert scene.maize.cultivar_id == "MAIZE_EARLY_2026"
    assert scene.soybean.field_geometry.planted_area_m2 == pytest.approx(18867.2)
    assert scene.maize.field_geometry.planted_area_m2 == pytest.approx(11148.8)
    assert scene.soybean.physics is not scene.maize.physics
    assert scene.soybean.physics.profile is not scene.maize.physics.profile
    assert scene.soybean.shared_warehouse is scene.maize.shared_warehouse is scene.warehouse
    assert all(app.time_manager is engine.time_manager for app in scene.apps)
    assert len({app.name for app in scene.apps}) == len(scene.apps)
    assert {app.name for app in scene.shared_equipment} == {"Tractor", "Mavic3M", "Matrice4T", "Robot0"}
    for farm, sensor, irrigation in (
        (scene.soybean, scene.soybean_sensor, scene.soybean_irrigation),
        (scene.maize, scene.maize_sensor, scene.maize_irrigation),
    ):
        assert sensor.bound_farm_id == irrigation.bound_farm_id == farm.farm_id
        for ridge in farm._ridges:
            expected = .20 if farm is scene.soybean and ridge.ridge_id in TARGET_RIDGES else .02
            assert ridge.disease_pressure == expected
    low = scene.maize.physics.soil.hydraulic_modifiers[28]
    assert low.field_capacity_vwc < scene.maize.physics.soil.hydraulic_modifiers[0].field_capacity_vwc
    assert low.field_capacity_vwc < scene.soybean.physics.soil.hydraulic_modifiers[28].field_capacity_vwc


def test_export_has_no_physical_effects_and_has_closed_dependencies():
    scene, engine = create_scene()
    before = raw_state(scene)
    plan = engine.run_scenario_oracle(False)
    assert raw_state(scene) == before
    assert len(plan) > 0
    known = set()
    for name, step in plan.dag.items():
        assert step.name == name and step.tool_name
        assert set(step.depends_on) <= known
        known.add(name)
    assert len(scene.events) == len(plan) + 1


def test_real_oracle_and_fresh_json_replay_have_identical_world_and_responses(completed):
    untouched, exporter = create_scene()
    plan = json_roundtrip(exporter.run_scenario_oracle(False))
    fresh, engine = create_scene()
    replay = engine.replay_workflow(plan)
    assert_no_tool_failures(replay)
    assert engine.evaluate().success
    assert normalize(raw_state(fresh)) == normalize(raw_state(completed.scene))
    assert len(replay) == len(completed.workflow)
    for expected, actual in zip(completed.workflow.dag.values(), replay.dag.values()):
        assert expected.tool_name == actual.tool_name
        assert expected.tool_args == actual.tool_args
        assert (expected.time_before, expected.time_after) == (actual.time_before, actual.time_after)
        # Oracle reasons are annotations; engine replay returns the tool response.
        expected_content = {k: v for k, v in expected.content.items() if k != "oracle_reason"}
        actual_content = actual.content if isinstance(actual.content, dict) else {"result": actual.content}
        actual_content = {k: v for k, v in actual_content.items() if k != "oracle_reason"}
        assert normalize(expected_content) == normalize(actual_content)
    assert not untouched.warehouse.grain_batches


def test_interventions_are_local_and_both_crops_are_safely_stored(completed):
    scene = completed.scene
    fungicide = [op for op in scene.tractor.get_state()["operation_log"]
                 if op["operation"] == "apply_fungicide"]
    assert len(fungicide) == 2
    assert all(op["farm_id"] == "soybean_field" for op in fungicide)
    assert Counter(r for op in fungicide for r in op["ridge_ids"]) == Counter(TARGET_RIDGES)
    assert sum(op["fungicide_used_liters"] for op in fungicide) == pytest.approx(76)
    assert scene._initial_stock.pesticide_liters - scene.warehouse.stock.pesticide_liters == pytest.approx(76)
    assert scene.maize._management_regime.irrigation_used_mm_total == pytest.approx(12.5)
    assert scene.soybean._management_regime.irrigation_used_mm_total == 0
    for farm in (scene.soybean, scene.maize):
        batches = [b for b in scene.warehouse.grain_batches.values() if b.origin_farm_id == farm.farm_id]
        assert all(r.harvested for r in farm._ridges)
        assert Counter(r for b in batches for r in b.ridge_ids) == Counter(range(64))
        assert all(b.crop_id == farm.crop_id and b.status == "stored" and b.quantity_kg > 0
                   and b.moisture_pct <= farm._postharvest_market.max_storage_moisture_pct for b in batches)
    tractor = scene.tractor.get_state()
    assert tractor["grain_bin_kg"] == tractor["seed_hopper"] == 0
    assert tractor["fungicide_tank_l"] == 0


@pytest.mark.parametrize("omitted", ["fungicide", "irrigation"])
def test_equal_time_omissions_fail_and_lose_the_targeted_physical_benefit(completed, omitted):
    scene, engine = create_scene()
    modified, count = [], 0
    for name, app, method, args, reason in scene._reference_actions():
        remove = ((omitted == "fungicide" and method == "apply_fungicide")
                  or (omitted == "irrigation" and app is scene.maize_irrigation and method == "irrigate"))
        if remove:
            actual = completed.workflow.dag[name]
            duration = actual.time_after - actual.time_before
            assert duration > 0
            app, method, args = scene.system, "advance_time", {"seconds": duration}
            reason = "Matched-time control omits only the intervention."
            count += 1
        modified.append((name, app, method, args, reason))
    assert count == 2
    captured = instrument_actions(scene, modified)
    workflow = engine.run_scenario_oracle(True)
    assert_no_tool_failures(workflow)
    result = engine.evaluate()
    assert not result.success
    target = "soybean_field" if omitted == "fungicide" else "maize_field"
    other = "maize_field" if omitted == "fungicide" else "soybean_field"
    key = "disease_followup_28" if omitted == "fungicide" else "drought_second_crop_recheck"
    baseline, control = completed.checkpoints[key], captured[key]
    assert control["time"] == baseline["time"]
    if omitted == "fungicide":
        assert control["farms"][target]["disease"] > baseline["farms"][target]["disease"]
    else:
        assert control["farms"][target]["root_vwc"] < baseline["farms"][target]["root_vwc"]
    assert control["farms"][other] == baseline["farms"][other]
    assert engine.time_manager.time() == completed.engine.time_manager.time()


def intervention_steps(workflow, method):
    return [step for step in workflow.dag.values() if step.tool_name.split("__")[-1] == method]


def test_equivalent_evidence_is_valid_after_renaming_all_workflow_nodes(completed):
    altered = json_roundtrip(completed.workflow)
    aliases = {name: f"public_action_{index}" for index, name in enumerate(altered.dag)}
    renamed = Workflow()
    for name, step in altered.dag.items():
        step.name = aliases[name]
        step.depends_on = [aliases[dependency] for dependency in step.depends_on]
        renamed.add_node(step)
    before = raw_state(completed.scene)
    result = completed.engine.evaluate(renamed)
    assert result.success, result.message
    assert raw_state(completed.scene) == before


@pytest.mark.parametrize("evidence", ["before_disease", "after_disease", "next_day_water"])
def test_missing_actual_observation_evidence_fails_even_with_completed_world(completed, evidence):
    altered = json_roundtrip(completed.workflow)
    sprays = intervention_steps(altered, "apply_fungicide")
    waters = intervention_steps(altered, "irrigate")
    first_spray = min(step.time_before for step in sprays)
    last_spray = max(step.time_after for step in sprays)
    omitted = []
    for name, step in list(altered.dag.items()):
        method = step.tool_name.split("__")[-1]
        args = step.tool_args or {}
        soybean_ground = method == "inspect_crop_health" and args.get("farm_id") == "soybean_field"
        remove = (
            evidence == "before_disease" and soybean_ground and step.time_after <= first_spray
            or evidence == "after_disease" and soybean_ground
            and last_spray < step.time_before < last_spray + 9 * 86400
            or evidence == "next_day_water" and step.tool_name == "Maize_Sensor__read_soil_sensors"
            and any(w.time_after + 20 * 3600 <= step.time_before <= w.time_after + 2 * 86400 for w in waters)
        )
        if remove:
            omitted.append(name)
            del altered.dag[name]
    assert omitted, f"No real {evidence} evidence selected"
    for step in altered.dag.values():
        step.depends_on = [name for name in step.depends_on if name not in omitted]
    before = raw_state(completed.scene)
    assert not completed.engine.evaluate(altered).success
    assert raw_state(completed.scene) == before


def test_wrong_treatment_target_in_trace_cannot_borrow_correct_world_logs(completed):
    altered = json_roundtrip(completed.workflow)
    for step in intervention_steps(altered, "apply_fungicide"):
        step.tool_args["farm_id"] = "maize_field"
        step.content["farm_id"] = "maize_field"
    before = raw_state(completed.scene)
    assert not completed.engine.evaluate(altered).success
    assert raw_state(completed.scene) == before


@pytest.mark.parametrize("tool,field", [
    ("Tractor__apply_fungicide", "sprayed_ridges"),
    ("SoybeanFarm__get_ridge_range_state", "ridges"),
    ("Robot0__inspect_crop_health", "observations"),
])
def test_malformed_receipts_fail_without_changing_the_world(completed, tool, field):
    altered = json_roundtrip(completed.workflow)
    for step in altered.dag.values():
        if step.tool_name == tool:
            step.content[field] = None
    before = raw_state(completed.scene)
    result = completed.engine.evaluate(altered)
    assert not result.success
    assert "Malformed" in result.message
    assert raw_state(completed.scene) == before


def test_validation_does_not_change_clock_world_logs_or_random_streams(completed):
    for scene, engine in ((completed.scene, completed.engine), create_scene()):
        before = raw_state(scene)
        first = engine.evaluate()
        assert raw_state(scene) == before
        second = engine.evaluate()
        assert raw_state(scene) == before
        assert first.to_dict() == second.to_dict()
    assert not first.success
