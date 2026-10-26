"""Conditional stand retention never invents native replant capability."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from scripts.adaptive_replant_policy import decide_replant_candidate
from scripts import adaptive_management_runner as runner


def public_stand(value=.84, count=4):
    return {"ridges": [{"ridge_id": rid, "planted": True, "harvested": False,
                        "growth_stage": "VE", "stand_fraction": value} for rid in range(count)]}


@pytest.mark.parametrize("stand", [.70, .82, .84, .85])
def test_complete_adequate_public_stand_retained_without_economic_claim(stand):
    observation = public_stand(stand)
    source = {"source_label": "old_fixed_replant", "arguments": {"full_replant": True}}
    result = decide_replant_candidate(observation, start=0, end=3, source_requirement=source)
    assert result["action"] == "retain_existing_stand"
    assert result["skip_fixed_replant"] is True
    assert [row["stand_fraction"] for row in result["ridges"]] == [stand] * 4
    assert result["threshold"] == .70
    assert result["economic_benefit_established"] is False
    assert result["native_replant_support_established"] is False
    assert result["source_requirement"] == source
    assert observation == public_stand(stand)


@pytest.mark.parametrize("stand", [.52, .57, .64, .699])
def test_missing_stand_enters_candidate_evaluation_without_skipping_original_request(stand):
    observation = public_stand(.85)
    observation["ridges"][2]["stand_fraction"] = stand
    result = decide_replant_candidate(observation, start=0, end=3)
    assert result["action"] == "evaluate_replant_candidate"
    assert result["skip_fixed_replant"] is False
    assert result["below_candidate_line_ridges"] == [2]
    assert result["economic_benefit_established"] is False


@pytest.mark.parametrize("missing", ["coverage", "duplicate", "stand", "stage", "unknown_stage", "unplanted_stage", "planted", "harvested", "nonfinite"])
def test_incomplete_or_ambiguous_public_diagnosis_cannot_skip_replant(missing):
    observation = public_stand()
    row = observation["ridges"][2]
    if missing == "coverage": observation["ridges"].pop(2)
    if missing == "duplicate": observation["ridges"].append(deepcopy(row))
    if missing == "stand": row.pop("stand_fraction")
    if missing == "stage": row.pop("growth_stage")
    if missing == "unknown_stage": row["growth_stage"] = "unknown"
    if missing == "unplanted_stage": row["growth_stage"] = "NOT_PLANTED"
    if missing == "planted": row["planted"] = False
    if missing == "harvested": row["harvested"] = True
    if missing == "nonfinite": row["stand_fraction"] = float("nan")
    result = decide_replant_candidate(observation, start=0, end=3)
    assert result["action"] == "insufficient_public_diagnosis"
    assert result["skip_fixed_replant"] is False
    assert result["diagnostic_issues"]
    json.dumps(result, allow_nan=False)


def test_service_envelope_and_narrow_target_use_only_requested_public_ridges():
    result = decide_replant_candidate({"data": public_stand(.84, 8)}, start=4, end=7)
    assert result["skip_fixed_replant"] is True
    assert [row["ridge_id"] for row in result["ridges"]] == [4, 5, 6, 7]


@pytest.mark.parametrize("args", [{"start": True, "end": 3}, {"start": 4, "end": 3},
                                  {"start": 0, "end": 3, "threshold": float("inf")}])
def test_invalid_target_or_threshold_rejected(args):
    with pytest.raises(ValueError):
        decide_replant_candidate(public_stand(), **args)


def fake_runner(monkeypatch, observation):
    value = runner.AdaptiveManagementCompiler.__new__(runner.AdaptiveManagementCompiler)
    value.engine = SimpleNamespace(time_manager=SimpleNamespace(time=lambda: 1000.))
    value.deadline = 100000.
    value._in_management_review = False
    value._source_steps = {}
    value.trace, value.decisions, value.changes = [], [], []
    calls = []

    def replant(**args):
        raise RuntimeError("Native replant lifecycle unsupported")

    value.tools = {"Farm__get_ridge_range_state": lambda **args: deepcopy(observation),
                   "System__get_current_time": lambda: {"current_timestamp": 1000.},
                   "Tractor__replant_seeds": replant}

    def registered_call(self, label, tool, args, **kwargs):
        calls.append((tool, deepcopy(args)))
        result = self.tools[tool](**args)
        self.trace.append({"name": label, "source_label": label, "tool_name": tool,
                           "content": deepcopy(result), "time_after": 1000.})
        return result

    monkeypatch.setattr(runner.FrozenWeatherCompiler, "call", registered_call)
    return value, calls


def test_wrapper_replaces_only_unjustified_fixed_request_with_real_public_reads(monkeypatch):
    value, calls = fake_runner(monkeypatch, public_stand(.84))
    args = {"start_ridge": 0, "end_ridge": 3, "depth_cm": 4., "spacing_cm": 7.9, "full_replant": True}
    result = value.call("source_replant", "Tractor__replant_seeds", args, op="WRITE")
    assert result == {"current_timestamp": 1000.}
    assert [tool for tool, _ in calls] == ["Farm__get_ridge_range_state", "System__get_current_time"]
    assert value.decisions[-1]["decision"]["action"] == "retain_existing_stand"
    assert value.changes[-1]["source_requirement"]["arguments"] == args
    assert value.changes[-1]["economic_benefit_established"] is False


@pytest.mark.parametrize("insufficient", [False, True])
def test_wrapper_preserves_actual_native_block_for_severe_or_insufficient_diagnosis(monkeypatch, insufficient):
    observation = public_stand(.64)
    if insufficient: observation["ridges"].pop()
    value, calls = fake_runner(monkeypatch, observation)
    args = {"start_ridge": 0, "end_ridge": 3, "depth_cm": 4., "spacing_cm": 7.9}
    with pytest.raises(RuntimeError, match="Native replant lifecycle unsupported"):
        value.call("source_replant", "Tractor__replant_seeds", args, op="WRITE")
    assert calls[-1] == ("Tractor__replant_seeds", args)
    assert value.changes == []
    assert value.decisions[-1]["decision"]["skip_fixed_replant"] is False


def test_wrapper_links_recorded_public_ground_but_uses_fresh_ridge_stand(monkeypatch):
    value, _ = fake_runner(monkeypatch, public_stand(.84))
    value.trace.append({"name": "previous_ground", "source_label": "earlier_ground", "tool_name": "Robot__inspect_emergence",
        "time_after": 500., "content": {"covered_ridges": [0, 1, 2, 3], "observations": {
            str(r): {"ridge_id": r, "stand_fraction": .64} for r in range(4)}}})
    value.call("source_replant", "Tractor__replant_seeds", {"start_ridge": 0, "end_ridge": 3})
    record = value.decisions[-1]
    assert record["decision"]["action"] == "retain_existing_stand"
    assert all(r["stand_fraction"] == .84 for r in record["decision"]["ridges"])
    assert len(record["existing_public_ground_links"]) == 4
    assert all(link["public_stand_fraction"] == .64 for link in record["existing_public_ground_links"])
