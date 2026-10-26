"""Corrupted evidence must not become an Oracle calibration success."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.verify_formal90_oracle_calibration import (
    digest, discover_cases, load, matched_comparison, verify_batch, verify_case,
    verify_operations, verify_review, verify_ablations,
)


SID = "example_full_season"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def fixture():
    rows = [{"ridge_id": rid, "growth_stage": "R8", "grain_moisture_pct": 14} for rid in range(2)]
    workflow = {
        "scout": {"tool_name": "Farm__get_ridge_range_state", "tool_args": {"start": 0, "end": 1},
                  "content": {"ridges": rows}, "time_before": 1, "time_after": 1},
        "fert": {"tool_name": "Farm__apply_fertigation", "tool_args": {"start_ridge": 0, "end_ridge": 1, "nutrient_amount": 0.1},
                 "content": {"status": "ok", "action_id": "original-id"}, "time_before": 1, "time_after": 1},
        "harvest": {"tool_name": "Tractor__harvest", "tool_args": {"start_ridge": 0, "end_ridge": 1},
                    "content": {"status": "ok", "harvested_ridges": [0, 1], "grain_kg_added": 15}, "time_before": 2, "time_after": 3},
        "store": {"tool_name": "Farm__store_grain", "tool_args": {}, "time_before": 3, "time_after": 3,
                  "content": {"status": "ok", "batch_ridge_ids": [0, 1], "moved_kg": 15,
                              "storage_grain_moisture_pct": 13, "max_storage_moisture_pct": 13.5}},
    }
    for name, step in workflow.items():
        step["name"] = name
    config = {"external_biotic_coupling": True}
    snapshot = {"clock": 3, "farms": {"Farm": {
        "world": {"farm_id": "default", "num_ridges": 2, "field_area_m2": 200,
                  "inventory": {"harvest_grain_kg": 0}, "postharvest_market": {"max_storage_moisture_pct": 13.5}},
        "engines": {"yield_recovery": {str(rid): {"harvested": True, "r8_reached": True,
                                                  "maturity_date": "2026-09-10"} for rid in range(2)}},
        "native_backend": {"config": config, "ridges": {str(rid): {"pcse": {"DOM": "2026-09-11", "DVS": 2,
                                                                                                "TWSO": 1000}} for rid in range(2)}},
    }}, "apps": {"Tractor": {"grain_bin_kg": 0}}}
    review = {"scenario_id": SID, "scenario_goal_status": "preserved",
              "actions": [{"source_step": name, "decision": "preserved", "reason": "Reviewed for this scenario",
                           "parameter_basis": "Explicit simulator reference"} for name in ("fert", "harvest", "store")],
              "native_mechanisms": [{"name": "biotic_assimilation", "status": "empirical_proxy", "basis": "FAIRY coupling"}]}
    return workflow, snapshot, config, review


def write_case(root: Path, *, nested=False):
    workflow, snapshot, config, review = fixture()
    reference = root / "reference" if nested else root
    files = {
        "original_workflow.json": workflow, "observed_workflow.json": workflow,
        "fresh_replay.json": workflow, "discovery_trace.json": list(workflow.values()),
        "initial_snapshot.json": {"clock": 0, "farms": {}},
        "discovery_final_snapshot.json": snapshot, "replay_final_snapshot.json": snapshot,
        "summary.json": {"scenario_id": SID, "completion": "feasible_operational_reference",
                         "discovery_state_hash": digest(snapshot), "replay_state_hash": digest(snapshot)},
    }
    for name, value in files.items():
        save(reference / name, value)
    save(root / "source_before.json", {"fairy/test.py": "frozen"})
    save(root / "source_after.json", {"fairy/test.py": "frozen"})
    save(root / "config.json", config)
    save(root / "case_review.json", review)
    save(root / "provenance.json", {"scenario_id": SID, "raw_workflow_sha256": digest(workflow), "wofost_config": config})
    return workflow, snapshot


def test_independently_passes_legacy_evidence_layout(tmp_path):
    write_case(tmp_path)
    result = verify_case(tmp_path, SID)
    assert result["operational_verified"]
    assert result["management_review"]["status"] == "reviewed"
    assert result["native_support"]["status"] == "empirical_proxy_present"
    assert result["operational"]["farms"]["default"]["native_dry_grain_kg"] == 20


def test_independently_passes_new_nested_reference_layout(tmp_path):
    write_case(tmp_path, nested=True)
    assert verify_case(tmp_path, SID)["operational_verified"]


def test_completion_label_does_not_replace_physical_evidence(tmp_path):
    write_case(tmp_path)
    (tmp_path / "replay_final_snapshot.json").unlink()
    report = verify_case(tmp_path, SID)
    assert report["producer_completion"] == "feasible_operational_reference"
    assert not report["operational_verified"]
    assert report["operational"]["status"] == "missing"


def test_replay_argument_tampering_is_rejected(tmp_path):
    write_case(tmp_path)
    replay = load(tmp_path / "fresh_replay.json")
    replay["fert"]["tool_args"]["nutrient_amount"] = 100
    save(tmp_path / "fresh_replay.json", replay)
    assert verify_case(tmp_path, SID)["replay"]["status"] == "fail"


def test_only_declared_random_receipt_ids_are_normalized(tmp_path):
    write_case(tmp_path)
    replay = load(tmp_path / "fresh_replay.json")
    replay["fert"]["content"]["action_id"] = "new-random-id"
    save(tmp_path / "fresh_replay.json", replay)
    assert verify_case(tmp_path, SID)["operational_verified"]
    replay["fert"]["content"]["batch_id"] = "different-provenance"
    save(tmp_path / "fresh_replay.json", replay)
    assert not verify_case(tmp_path, SID)["operational_verified"]


def test_config_provenance_and_executed_native_config_both_checked(tmp_path):
    write_case(tmp_path)
    save(tmp_path / "config.json", {"external_biotic_coupling": False})
    report = verify_case(tmp_path, SID)
    assert "config differs from provenance" in report["integrity_problems"]
    assert "explicit configuration differs from final native backend" in report["integrity_problems"]


def test_public_maturity_cannot_be_replaced_by_successful_harvest_label():
    workflow, snapshot, _, _ = fixture()
    workflow["scout"]["content"]["ridges"][0]["growth_stage"] = "R7"
    result = verify_operations(workflow, snapshot)
    assert not result["pass"]
    assert any(p["code"] == "no_public_maturity_evidence" for p in result["problems"])


@pytest.mark.parametrize("failure", ["wet", "duplicate", "bin", "native"])
def test_safe_coverage_is_not_inferred_from_positive_warehouse_mass(failure):
    workflow, snapshot, _, _ = fixture()
    if failure == "wet":
        workflow["store"]["content"]["storage_grain_moisture_pct"] = 22
    elif failure == "duplicate":
        workflow["store"]["content"]["batch_ridge_ids"] = [0, 0, 1]
    elif failure == "bin":
        snapshot["apps"]["Tractor"]["grain_bin_kg"] = 1
    else:
        snapshot["farms"]["Farm"]["native_backend"]["ridges"]["0"]["pcse"]["DOM"] = None
    assert not verify_operations(workflow, snapshot)["pass"]


def test_shared_batch_list_checks_origin_and_stricter_farm_storage_limit():
    workflow, snapshot, _, _ = fixture()
    del workflow["store"]
    snapshot["apps"]["Warehouse"] = {"grain_batches": [{"batch_id": "a", "origin_farm_id": "default",
        "ridge_ids": [0, 1], "quantity_kg": 15, "status": "stored", "moisture_pct": 13}],
        "facilities": {"max_storage_moisture_pct": 14}}
    assert verify_operations(workflow, snapshot)["pass"]
    snapshot["apps"]["Warehouse"]["grain_batches"][0]["moisture_pct"] = 13.8
    assert not verify_operations(workflow, snapshot)["pass"]


def test_requested_inspection_coverage_is_verified():
    workflow, snapshot, _, _ = fixture()
    workflow["inspect"] = {"tool_name": "Robot__inspect_crop_health", "tool_args": {"start_ridge": 0, "end_ridge": 7},
        "content": {"status": "ok", "covered_ridges": [0, 1, 2, 3], "uncovered_ridges": [4, 5, 6, 7]},
        "time_before": 4, "time_after": 5}
    assert any(p["code"] == "incomplete_requested_inspection" for p in verify_operations(workflow, snapshot)["problems"])


def test_management_review_and_model_support_are_separate_from_feasibility(tmp_path):
    write_case(tmp_path)
    (tmp_path / "case_review.json").unlink()
    report = verify_case(tmp_path, SID)
    assert report["operational_verified"]
    assert report["management_review"]["status"] == "not_assessed"
    assert report["native_support"]["status"] == "not_assessed"


def test_source_review_does_not_claim_runtime_management_calibration():
    workflow, _, _, _ = fixture()
    review = {"scenario_id": SID, "review_status": "source_and_original_workflow_review_complete_not_runtime_calibration_result",
        "semantic_model_gaps": [{"code": "no_native_replant"}], "planned_management_actions": [
            {"source_step": "fert", "dose_basis": "Simulator coefficient", "public_evidence_required": ["soil"]}]}
    result = verify_review(review, SID, workflow)
    assert result["status"] == "source_reviewed"
    assert result["goal_status"] == "explicit_model_gaps"
    review["planned_management_actions"] = []
    assert verify_review(review, SID, workflow)["status"] == "invalid"


def test_matched_omission_keeps_original_time_as_idle_interval():
    workflow, _, _, _ = fixture()
    candidate = deepcopy(workflow)
    workflow["fert"]["time_after"] = candidate["fert"]["time_after"] = 1.5
    candidate["fert"]["tool_name"] = "System__get_current_time"
    candidate["fert"]["tool_args"] = {}
    assert matched_comparison(workflow, candidate, ["fert"])["pass"]
    candidate["harvest"]["time_before"] += 1
    assert not matched_comparison(workflow, candidate, ["fert"])["pass"]


def test_half_dose_cannot_change_other_tools_or_times():
    baseline, _, _, _ = fixture()
    candidate = deepcopy(baseline)
    candidate["fert"]["tool_args"]["nutrient_amount"] *= 0.5
    assert matched_comparison(baseline, candidate, modified_step_ids=["fert"])["pass"]
    candidate["fert"]["time_after"] += 1
    assert not matched_comparison(baseline, candidate, modified_step_ids=["fert"])["pass"]


def test_batch_requires_every_id_and_rejects_duplicate_ids(tmp_path):
    write_case(tmp_path / "case")
    save(tmp_path / "manifest.json", {"cases": [{"scenario_id": SID, "case_dir": "case"}]})
    report = verify_batch(tmp_path, [SID, "missing"])
    assert report["missing_ids"] == ["missing"] and not report["all_ids_have_conclusion"]
    save(tmp_path / "manifest.json", {"cases": [{"scenario_id": SID, "case_dir": "case"}] * 2})
    _, duplicate = discover_cases(tmp_path, {SID})
    assert duplicate == [SID]


@pytest.mark.parametrize("text", ['{"x": NaN}', '{"x": 1, "x": 2}'])
def test_invalid_json_evidence_cannot_be_silently_accepted(tmp_path, text):
    p = tmp_path / "bad.json"
    p.write_text(text)
    with pytest.raises(ValueError):
        load(p)


def write_driver_experiment(root, *, initial_mismatch=False, delayed=False, bad_selection=False):
    workflow, snapshot = write_case(root, nested=True)
    initial = load(root / "reference/initial_snapshot.json")
    plan = deepcopy(workflow)
    plan["fert"]["tool_args"]["nutrient_amount"] *= 0.5
    if delayed:
        plan["harvest"]["time_before"] += 0.1
    final = deepcopy(snapshot)
    replay = deepcopy(plan)
    # A deliberately tiny synthetic fixture: the verifier must read the
    # receipt's mass, not the producer's independently editable metric label.
    replay["store"]["content"]["moved_kg"] = 15.2
    for folder, p, r, f in ((root / "ablations/half", plan, replay, final),
                            (root / "selected", workflow if bad_selection else plan,
                             workflow if bad_selection else replay, snapshot if bad_selection else final)):
        start = deepcopy(initial)
        if initial_mismatch and folder.name == "half":
            start["clock"] += 1
        for name, value in (("workflow.json", p), ("replay.json", r), ("initial_snapshot.json", start), ("final_snapshot.json", f)):
            save(folder / name, value)
        save(folder / "summary.json", {"initial_hash": digest(start), "final_hash": digest(f),
            "workflow_sha256": digest(p), "actual_replay_sha256": digest(r),
            "safe_stored_kg": 99999, "operational_complete": True})
    save(root / "selected/expected_replay.json", workflow if bad_selection else replay)
    save(root / "summary.json", {"scenario_id": SID, "calibration": {"selected_id": "reference" if bad_selection else "half",
        "yield_equivalence_tolerance_kg": 0.1}})
    save(root / "ablations/manifest.json", {"baseline_dir": "reference", "trials": [{"id": "half",
        "candidate_dir": "ablations/half", "candidate_kind": "half", "changed_step_ids": ["fert"], "removed_step_ids": []}]})


def test_driver_experiment_and_selected_fresh_replay_are_independently_verified(tmp_path):
    write_driver_experiment(tmp_path)
    report = verify_ablations(tmp_path)
    assert report["status"] == "verified"
    assert report["verified_matched_count"] == 1
    assert report["experiments"][0]["safe_stored_kg"] == 15.2
    assert report["selected_candidate"]["status"] == "fresh_selected_candidate_verified"
    assert report["selected_candidate"]["maximum_verified_tested_safe_stored_kg"] == 15.2


def test_driver_source_changes_keep_correct_local_comparisons_provisional(tmp_path):
    write_driver_experiment(tmp_path)
    save(tmp_path / "source_after.json", {"fairy/test.py": "changed"})
    report = verify_ablations(tmp_path)
    assert report["status"] == "provisional_source_changed"
    assert report["status_before_source_check"] == "verified"
    assert report["verified_matched_count"] == 1
    assert report["selected_candidate"]["status"] == "fresh_selected_candidate_verified_provisional_source"


@pytest.mark.parametrize("failure", ["initial_mismatch", "delayed", "bad_selection"])
def test_driver_trial_rejects_changed_initial_state_schedule_or_wrong_selected_candidate(tmp_path, failure):
    write_driver_experiment(tmp_path, **{failure: True})
    assert verify_ablations(tmp_path)["status"] == "invalid"


def test_explicit_model_block_has_a_conclusion_but_never_an_operational_pass(tmp_path):
    write_case(tmp_path)
    for name in ("observed_workflow.json", "fresh_replay.json", "discovery_final_snapshot.json", "replay_final_snapshot.json"):
        (tmp_path / name).unlink()
    save(tmp_path / "summary.json", {"scenario_id": SID, "exception_type": "RuntimeError",
        "message": "WOFOST requires a new native season for replanting", "traceback": "actual persisted traceback",
        "calibration": {"status": "blocked_or_requires_policy_repair"}})
    review = load(tmp_path / "case_review.json")
    review["scenario_goal_status"] = "explicitly_unsupported"
    review["native_mechanisms"] = [{"name": "replant", "status": "unsupported", "basis": "Native lifecycle guard"}]
    save(tmp_path / "case_review.json", review)
    report = verify_case(tmp_path, SID)
    assert report["conclusion_record_integrity_pass"]
    assert report["recorded_model_block"]["status"] == "recorded_model_block_not_replay_verified"
    assert report["operational"]["status"] == "blocked"
    assert not report["operational_verified"]
