"""Task-level completion, lossless checkpoints and negative maize controls."""
from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("pcse")

from fairy.apps.farm_world import FarmWorldApp, TractorApp
from fairy.controllers.engine import Engine
from fairy.scenarios.maize.farm_checkpoint_state import (
    ROOT, TRACTOR_FIELDS, checkpoint_path, load_checkpoint,
)
from fairy.scenarios.maize.maize_scenario_catalog import TASK_SPECS, SPECS
from fairy.scenarios.maize.validation import task_state
from fairy.scenarios.registry import get_scenario_class, list_scenarios
from fairy.scenarios.workflow import Workflow
from fairy.types import CapturedEvent

IDS = tuple(TASK_SPECS)


def make_engine(sid):
    scenario = get_scenario_class(sid)()
    scenario.setup()
    engine = Engine(None, scenario)
    engine.time_manager.real_time_passed = lambda: 0.0
    return scenario, engine


def without_ids(value):
    if isinstance(value, dict):
        return {key: without_ids(item) for key, item in value.items() if key not in {"op_id", "action_id"}}
    if isinstance(value, list):
        return [without_ids(item) for item in value]
    return value


def physical_state(scenario):
    farm = scenario.get_typed_app(FarmWorldApp)
    tractor = scenario.get_typed_app(TractorApp)
    return {
        "farm": farm.get_state(),
        "native": farm.physics.crop_backend.export_state(),
        "recovery": farm.physics.yield_recovery.get_state(),
        "tractor": without_ids({key: getattr(tractor, key) for key in TRACTOR_FIELDS}),
        "rng": {app.name: app.rng.getstate() for app in scenario.apps
                if app.name not in {"AgentUserInterface", "SystemApp"}},
        "observation_rng": farm.physics.observation_model.rng.getstate(),
    }


@pytest.fixture(scope="module")
def completed():
    results = {}
    for sid in IDS:
        scenario, engine = make_engine(sid)
        workflow = engine.run_scenario_oracle()
        results[sid] = scenario, engine, workflow
    return results


def test_three_tiers_use_explicit_python_modules_and_shared_runtime():
    assert len(TASK_SPECS) == 15
    assert sum(t.level == "L1" for t in TASK_SPECS.values()) == 11
    assert sum(t.level == "L2" for t in TASK_SPECS.values()) == 4
    assert {sid for sid in list_scenarios() if sid.startswith("scenario_maize_")} == set(IDS) | {s.scenario_id for s in SPECS.values()}
    for sid in IDS:
        cls = get_scenario_class(sid)
        path = Path(inspect.getfile(cls))
        assert path.name == sid + ".py"
        assert path.parent.name == "maize_" + cls.task_spec.variant
        assert {"init_and_populate_apps", "build_events_flow"} <= cls.__dict__.keys()
    assert not (ROOT / "oracle_plans").exists()


@pytest.mark.parametrize("sid", IDS)
def test_every_split_oracle_completes_its_own_task(sid, completed):
    scenario, engine, workflow = completed[sid]
    result = engine.evaluate(workflow)
    assert result.success, result.to_dict()
    assert result.metadata["level"] == TASK_SPECS[sid].level
    assert result.metadata["source_l3_scenario_id"] == TASK_SPECS[sid].source_l3_scenario_id
    assert result.metadata["checkpoint_sha256"]
    if scenario.task == "dry":
        assert workflow.dag["o_dry_grain"].content["ridges_dried"] == 64
        assert not workflow.dag["o_dry_grain"].content.get("drying_skipped")
    if scenario.task == "refuel":
        assert scenario._task_initial["fuel"] == 44
        assert scenario.get_typed_app(TractorApp)._fuel_tank_l == 100
        assert result.metadata["tool_errors"] == []


@pytest.mark.parametrize("sid", IDS)
def test_split_replay_preserves_native_equipment_inventory_and_rng(sid, completed):
    original, _, workflow = completed[sid]
    replay, engine = make_engine(sid)
    engine.replay_workflow(workflow)
    assert engine.evaluate().success
    assert physical_state(replay) == physical_state(original)


@pytest.mark.parametrize("sid", IDS)
def test_empty_task_never_passes(sid):
    scenario, engine = make_engine(sid)
    assert not engine.evaluate(Workflow()).success


CRITICAL = {
    "level": "TractorApp__level",
    "base_fertilize": "TractorApp__base_fertilize",
    "form_ridges": "TractorApp__form_ridges",
    "plant": "TractorApp__plant_seeds",
    "refuel": "TractorApp__refuel",
    "harvest": "TractorApp__harvest",
    "unload": "TractorApp__unload_grain",
    "dry": "FarmWorldApp__dry_grain",
    "store": "FarmWorldApp__store_grain",
    "irrigate": "FieldOpsApp__irrigate",
    "fertilize": "FarmWorldApp__apply_fertigation",
    "establishment": "TractorApp__plant_seeds",
    "irrigation_management": "FieldOpsApp__irrigate",
    "nutrition_management": "FarmWorldApp__apply_fertigation",
    "harvest_storage": "FarmWorldApp__dry_grain",
}


def omit_action(workflow, tool):
    control = Workflow()
    for step in workflow.dag.values():
        if step.tool_name == tool:
            content = step.content or {}
            seconds = content.get("total_duration_minutes", content.get("duration_minutes", 0)) * 60
            step = replace(step, tool_name="SystemApp__advance_time", tool_args={"seconds": int(round(seconds))})
        control.add_node(step)
    return control


@pytest.mark.parametrize("sid", IDS)
def test_missing_critical_operation_fails(sid, completed):
    original, _, workflow = completed[sid]
    scenario, engine = make_engine(sid)
    engine.replay_workflow(omit_action(workflow, CRITICAL[original.task]))
    assert not engine.evaluate().success


@pytest.mark.parametrize("sid", ["scenario_maize_l1_plant", "scenario_maize_l1_unload", "scenario_maize_l1_dry", "scenario_maize_l1_store", "scenario_maize_l1_irrigate"])
def test_checkpoint_restores_exact_device_state_and_native_history(sid):
    scenario, _ = make_engine(sid)
    saved = scenario._checkpoint
    tractor = scenario.get_typed_app(TractorApp)
    assert {key: getattr(tractor, key) for key in TRACTOR_FIELDS} == saved["apps"]["TractorApp"]["exact_state"]
    farm = scenario.get_typed_app(FarmWorldApp)
    assert farm.physics.crop_backend.export_state() == saved["farm"]["physics_state"]["crop_backend_state"]
    assert scenario.start_time == saved["farm"]["sim_time"]
    assert farm.get_state() == saved["farm"]["farm_world_state"]


def test_capture_builds_no_oracle_and_advances_no_future_day(monkeypatch):
    from fairy.physics.wofost_backend import WofostBackend

    def reject(*args, **kwargs):
        pytest.fail("setup/build must not execute source tools or future daily growth")

    monkeypatch.setattr(CapturedEvent, "execute", reject)
    monkeypatch.setattr(WofostBackend, "advance_day", reject)
    # Restoration may rebuild historical PCSE objects via _advance_native.
    scenario, engine = make_engine("scenario_maize_l2_nutrition_management")
    before = physical_state(scenario)
    workflow = engine.build_oracle_workflow(run_oracle=False)
    assert len(workflow) > 0
    assert before == physical_state(scenario)


@pytest.mark.parametrize("kind", ["missing", "checksum", "source_config"])
def test_artifact_integrity_failures_are_actionable(tmp_path, kind):
    manifest = json.loads((ROOT / "scenario_artifacts.json").read_text())
    path = checkpoint_path("normal", "after_seed_loading")
    data = (ROOT / path).read_bytes()
    if kind != "missing":
        if kind == "source_config":
            payload = json.loads(data)
            payload["source_fingerprint"] = "different-source"
            data = json.dumps(payload).encode()
            manifest["files"][path.as_posix()] = hashlib.sha256(data).hexdigest()
        elif kind == "checksum":
            data += b" "
        (tmp_path / path).parent.mkdir(parents=True)
        (tmp_path / path).write_bytes(data)
    (tmp_path / "scenario_artifacts.json").write_text(json.dumps(manifest))
    with pytest.raises((ValueError, FileNotFoundError), match="build_maize_scenario_artifacts"):
        load_checkpoint("normal", "after_seed_loading", root=tmp_path)


@pytest.mark.parametrize("task", ["irrigation_management", "nutrition_management"])
def test_fixed_thresholds_separate_matched_controls(task, completed):
    sid = "scenario_maize_l2_" + task
    managed, _, workflow = completed[sid]
    control, engine = make_engine(sid)
    engine.replay_workflow(omit_action(workflow, CRITICAL[task]))
    reference = json.loads((ROOT / "scenario_artifacts.json").read_text())["management_thresholds"][task]
    m, c = task_state(managed), task_state(control)
    metric = reference["metric"]
    assert m[metric] == pytest.approx(reference["managed"])
    assert c[metric] == pytest.approx(reference["control"])
    assert reference["threshold"] == pytest.approx((m[metric] + c[metric]) / 2)
    original_native = managed.get_typed_app(FarmWorldApp).physics.crop_backend
    control_native = control.get_typed_app(FarmWorldApp).physics.crop_backend
    unchanged = "fertilizer_kg" if task == "irrigation_management" else "irrigation_mm"
    for rid, run in original_native._runs.items():
        other = control_native._runs[rid]
        assert [(r["day"], r["weather"], r["inputs"][unchanged]) for r in run.journal] == [
            (r["day"], r["weather"], r["inputs"][unchanged]) for r in other.journal]
    assert not engine.evaluate().success


def test_pending_fertilizer_is_counted_once_and_duplicate_input_is_rejected(completed):
    scenario, engine, workflow = completed["scenario_maize_l1_fertilize"]
    farm = scenario.get_typed_app(FarmWorldApp)
    assert engine.evaluate(workflow).success
    # This action is still in the daily native queue at the L1 endpoint.
    assert farm.physics.crop_backend._pending or farm.physics.pending_management_actions_by_ridge
    farm._inventory.fertilizer_kg += 1
    try:
        assert not engine.evaluate(workflow).success
    finally:
        farm._inventory.fertilizer_kg -= 1


def test_harvest_window_starts_above_harvest_moisture_limit():
    scenario, engine = make_engine("scenario_maize_l2_harvest_storage")
    farm = scenario.get_typed_app(FarmWorldApp)
    assert len(task_state(scenario)["mature"]) == 64
    assert farm._ridges[0].grain_moisture_pct > 25
    result = scenario.get_typed_app(TractorApp).harvest(0, 3)
    assert result.get("error")


def test_source_normal_requires_real_drying_and_other_source_dates_stay_fixed():
    assert SPECS["normal"].harvest_day == 101
    assert SPECS["water_limit"].harvest_day == SPECS["nitrogen_limit"].harvest_day == 145
    wet = load_checkpoint("normal", "before_drying")
    assert min(wet["farm"]["farm_world_state"]["trailer_grain_moistures_pct"]) > 14
    dry = load_checkpoint("normal", "before_storage")
    assert max(dry["farm"]["farm_world_state"]["trailer_grain_moistures_pct"]) <= 14


@pytest.fixture(scope="module")
def source_runs():
    results = {}
    for variant in ("normal", "water_limit"):
        scenario, engine = make_engine(SPECS[variant].scenario_id)
        workflow = engine.run_scenario_oracle()
        assert engine.evaluate().success
        results[variant] = scenario, workflow
    return results


@pytest.mark.parametrize("sid", [
    "scenario_maize_l1_plant", "scenario_maize_l1_harvest", "scenario_maize_l1_unload",
    "scenario_maize_l1_dry", "scenario_maize_l1_store", "scenario_maize_l1_irrigate",
])
def test_real_checkpoint_suffix_matches_uninterrupted_source(sid, source_runs):
    from fairy.scenarios.maize.maize_scenario_catalog import CHECKPOINT_EVENTS
    spec = TASK_SPECS[sid]
    source, workflow = source_runs[spec.variant]
    position, event_name = CHECKPOINT_EVENTS[spec.variant][spec.checkpoint_label]
    rows = list(workflow.dag.values())
    index = next(i for i, step in enumerate(rows) if step.name == event_name)
    if position == "after":
        index += 1
    suffix = Workflow()
    for step in rows[index:]:
        suffix.add_node(step)
    restored, engine = make_engine(sid)
    engine.replay_workflow(suffix)
    assert physical_state(restored) == physical_state(source)


def test_rechecks_are_required_even_after_successful_actions(completed):
    scenario, engine, workflow = completed["scenario_maize_l1_dry"]
    without_recheck = Workflow()
    for step in workflow.dag.values():
        if not step.name.startswith("o_recheck"):
            without_recheck.add_node(step)
    assert not engine.evaluate(without_recheck).success


def test_validation_does_not_run_any_simulation(completed, monkeypatch):
    scenario, engine, workflow = completed["scenario_maize_l2_nutrition_management"]
    farm = scenario.get_typed_app(FarmWorldApp)
    monkeypatch.setattr(farm.physics.crop_backend, "advance_day", lambda *a, **kw: pytest.fail("validation advanced growth"))
    monkeypatch.setattr(farm, "advance_physics_time", lambda *a, **kw: pytest.fail("validation advanced physics"))
    assert scenario.validate(type("Environment", (), {"workflow": workflow})()).success


def test_scripted_agent_receives_subtask_endpoint_and_live_tools():
    from types import SimpleNamespace as NS
    from fairy.controllers.agent_builder import build_controller_agent

    class ScriptedLLM:
        provider, model = "openai", "scripted-maize-subtask"
        calls = 0

        def chat_completion(self, messages, tools=None):
            assert "Complete only the standalone maize subtask" in messages[0]["content"]
            assert "grain in the machine" in messages[0]["content"]
            assert tools
            self.calls += 1
            if self.calls == 1:
                call = NS(id="inventory", type="function", function=NS(
                    name="FarmWorldApp__get_inventory", arguments="{}"))
                message = NS(content=None, tool_calls=[call])
            else:
                assert "MAIZE_201" in str(messages)
                message = NS(content="Inventory inspected; the harvest task remains incomplete.", tool_calls=None)
            return NS(choices=[NS(message=message)], usage=None)

    scenario, _ = make_engine("scenario_maize_l1_harvest")
    agent = build_controller_agent("farm_baseline_react", ScriptedLLM(), toolsets=scenario.apps)
    engine = Engine(agent, scenario)
    engine.time_manager.real_time_passed = lambda: 0.0
    workflow = engine.run_scenario_agent(max_tool_calls=5, timeout_seconds=30, setup_scenario=False)
    assert any(s.tool_name == "FarmWorldApp__get_inventory" for s in workflow.dag.values())
    assert not engine.evaluate(workflow).success
