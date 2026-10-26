"""Water extensions preserve primary actions and expose real schedule costs."""
from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from fairy.scenarios.workflow import Workflow, WorkflowStep
from scripts.extend_formal90_water_search import (
    doubled_changes, execute_shifted, select_candidate, trace_exact, water_episodes,
)


def plans(primary_hours=1.5, *, omit=False):
    ref, primary = Workflow(), Workflow()
    step = WorkflowStep(name="v00001_o_targeted_irrigation_0_1", tool_name="FieldOpsApp__irrigate",
        tool_args={"start": 0, "end": 1, "hours": 3.0}, time_before=1000, time_after=1010, op_type="WRITE")
    ref.add_node(step)
    current = deepcopy(step)
    current.tool_args["hours"] = primary_hours
    if omit:
        current.tool_name, current.tool_args = "SystemApp__get_current_time", {}
    primary.add_node(current)
    primary.add_node(WorkflowStep(name="later", tool_name="ReadApp__read", tool_args={},
        time_before=1030, time_after=1030, op_type="READ"))
    return ref, primary


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now


def execute(primary, changes, *, duration=22, deadline=2000, receipt=None):
    clock = FakeClock()

    def wait(seconds):
        clock.now += seconds
        return {"status": "ok", "advanced_seconds": seconds}

    def irrigate(**args):
        clock.now += duration
        return receipt or {"status": "irrigation_started", "irrigated_ridges": [0, 1],
                           "duration_hours_per_ridge": args["hours"]}

    tools = {"SystemApp__advance_time": wait,
             "SystemApp__get_current_time": lambda: {"timestamp": clock.now},
             "FieldOpsApp__irrigate": irrigate,
             "ReadApp__read": lambda: {"timestamp": clock.now}}
    return execute_shifted(primary, changes, tools, SimpleNamespace(time_manager=clock), deadline,
                           {"Workflow": Workflow, "WorkflowStep": WorkflowStep})


@pytest.mark.parametrize("omitted", [False, True])
def test_double_uses_original_reference_and_restores_omitted_water(omitted):
    ref, primary = plans(omit=omitted)
    before = deepcopy(primary.to_dict())
    groups = water_episodes(ref)
    changes = doubled_changes(ref, primary, groups)
    changed = changes[next(iter(ref.dag))]
    assert changed["revised_args"] == {"start": 0, "end": 1, "hours": 6.0}
    assert changed["reference_hours"] == 3.0
    assert changed["restores_primary_omission"] is omitted
    assert primary.to_dict() == before


def test_actual_excess_duration_shifts_every_later_slot_without_backdating():
    ref, primary = plans()
    changes = doubled_changes(ref, primary, water_episodes(ref))
    workflow, audit, errors, shift = execute(primary, changes)
    assert not errors and shift == 12
    first = workflow.dag[next(iter(primary.dag))]
    assert (first.time_before, first.time_after) == (1000, 1022)
    assert workflow.dag["later"].time_before == 1042
    assert workflow.dag["later"].tool_args == primary.dag["later"].tool_args
    assert audit[0]["additional_duration_seconds"] == 12
    assert audit[1]["shift_before"] == 12
    assert workflow.dag["water_wait_00001_before"].tool_args == {"seconds": 20}


def test_shorter_action_preserves_original_slot_using_recorded_real_wait():
    ref, primary = plans()
    workflow, audit, errors, shift = execute(primary, {}, duration=4)
    assert not errors and shift == 0
    assert workflow.dag["water_wait_00000_pad"].tool_args == {"seconds": 6}
    assert workflow.dag["later"].time_before == 1030
    assert audit[0]["padded_to_slot_end"]


def test_original_deadline_is_not_extended_for_longer_pumping():
    ref, primary = plans()
    workflow, audit, errors, shift = execute(primary, {}, duration=50, deadline=1040)
    assert errors and "deadline" in errors[0]["message"]
    assert next(iter(primary.dag)) in workflow.dag
    assert "later" not in workflow.dag


@pytest.mark.parametrize("receipt", [{"error": "Irrigation quota exceeded"}, {"status": "partial"},
    {"status": "irrigation_pending", "irrigated_ridges": [0, 1], "duration_hours_per_ridge": 6.0},
    {"status": "irrigation_started", "irrigated_ridges": [0], "duration_hours_per_ridge": 6.0}])
def test_rejected_partial_pending_or_incomplete_irrigation_is_not_a_success(receipt):
    ref, primary = plans()
    changes = doubled_changes(ref, primary, water_episodes(ref))
    workflow, audit, errors, shift = execute(primary, changes, receipt=receipt)
    assert errors and "later" not in workflow.dag


def candidate(identity, mass, *, verified=True, complete=True, water=1):
    return {"id": identity, "verified": verified, "metrics": {"safe_stored_kg": mass,
        "operational_complete": complete, "intervention_inputs": {
            "irrigation_ridge_mm": water, "intervention_calls": 1}}}


def test_extra_water_requires_material_improvement_over_primary_and_verified_completion():
    primary = {"safe_stored_kg": 1000}
    assert select_candidate(primary, [candidate("equal", 1000), candidate("tiny", 1000.05),
        candidate("unverified", 2000, verified=False), candidate("incomplete", 2000, complete=False)]) is None
    better = candidate("better", 1001)
    assert select_candidate(primary, [better]) is better


def test_near_equal_water_plans_choose_lower_water_without_sacrificing_material_yield():
    lower = candidate("less", 1001, water=2)
    near = candidate("more", 1001.05, water=4)
    assert select_candidate({"safe_stored_kg": 1000}, [lower, near]) is lower
    assert select_candidate({"safe_stored_kg": 1000}, [lower, candidate("gain", 1002, water=4)])["id"] == "gain"


def test_trace_equality_normalizes_only_ids_and_never_time():
    ref, primary = plans()
    actual = deepcopy(primary)
    first = next(iter(primary.dag))
    primary.dag[first].content = {"op_id": "one", "value": 1}
    actual.dag[first].content = {"op_id": "two", "value": 1}
    assert trace_exact(primary, actual)
    actual.dag[first].time_after += 1
    assert not trace_exact(primary, actual)


def replay_fixture(tmp_path, monkeypatch):
    import scripts.extend_formal90_water_search as search
    import scripts.formal90_calibration_policy as policy

    case = tmp_path / "case"
    chosen = case / "supplemental_water_search/selected"
    chosen.mkdir(parents=True)
    initial, final = {"clock": 1000, "value": "initial"}, {"clock": 1010, "value": "final"}
    source = {"original.py": "original508fingerprint"}
    summary = {"scenario_id": "example", "selected_verified": True,
        "production_source_matches": True, "selected_directory": "selected",
        "supplement_script_sha256": search.file_sha(search.__file__)}
    for path, obj in [(case / "source_before.json", source), (case / "config.json", {}),
        (case / "case_review.json", {}), (chosen.parent / "summary.json", summary),
        (chosen / "initial_snapshot.json", initial), (chosen / "final_snapshot.json", final)]:
        path.write_text(json.dumps(obj))
    plan = Workflow()
    plan.add_node(WorkflowStep(name="original_step", tool_name="Fake__read", tool_args={},
        content={"value": 1}, time_before=1000, time_after=1010))
    for name in ("workflow.json", "replay.json"):
        plan.save_workflow(str(chosen / name))

    class FakeEngine:
        did_run = False

        def replay_workflow(self, workflow):
            self.did_run = True
            return deepcopy(workflow)

    class FakeCompiler:
        deadline = 2000

        def __init__(self, *args, **kwargs):
            pass

        def fresh(self):
            return object(), FakeEngine()

        def snapshot_unrecorded(self, scene, engine):
            return final if engine.did_run else initial

    monkeypatch.setattr(policy, "CalibrationCompiler", FakeCompiler)
    monkeypatch.setattr(search, "fingerprint", lambda: source)
    monkeypatch.setattr(search, "imports", lambda: {"Workflow": Workflow})
    monkeypatch.setattr(search, "metrics", lambda snapshot, workflow: {"operational_complete": True})
    return search, case, summary


def test_replay_entry_verifies_saved_selection_from_new_initial_state(tmp_path, monkeypatch):
    search, case, summary = replay_fixture(tmp_path, monkeypatch)
    output = tmp_path / "new_replay"
    result = search.replay_case(case, output)
    assert result["verified"] and result["initial_state_exact"] and result["final_state_exact"]
    assert (output / "replay_verification.json").is_file()
    assert (case / "supplemental_water_search/summary.json").read_text() == json.dumps(summary)


def test_replay_entry_refuses_changed_script_and_evidence_overwrite(tmp_path, monkeypatch):
    search, case, summary = replay_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="overwrite"):
        search.replay_case(case, case / "selected")
    summary["supplement_script_sha256"] = "changed"
    (case / "supplemental_water_search/summary.json").write_text(json.dumps(summary))
    with pytest.raises(ValueError, match="fingerprint differs"):
        search.replay_case(case, tmp_path / "new_replay")
