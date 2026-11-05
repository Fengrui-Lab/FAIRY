"""Targeted entry/branch checks; no PCSE season or farm tool calls."""
import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_maize_h01_reference as runner


def gate_for(identity):
    return {
        "status": "passed", "candidate": "H01", "scenario_id": runner.SCENARIO_ID,
        "identity": identity, "identity_sha256": runner.base.digest(identity),
    }


def test_matching_gate_accepts_current_identity():
    identity = {"source": "a", "schedule": "07:00"}
    runner.require_matching_gate(gate_for(identity), identity)


def test_native_briefing_strip_preserves_exact_raw_task_requirement():
    frozen = "公开 H01 任务\n下一行的空格必须  保留\n"
    result = runner.check_native_task(frozen.strip(), frozen, frozen)
    assert result["native_task_normalization"] == "Engine briefing str.strip()"
    assert result["actual_engine_task_utf8_sha256"] == result["normalized_task_utf8_sha256"]
    assert result["raw_task_utf8_sha256"] != result["normalized_task_utf8_sha256"]
    with pytest.raises(RuntimeError, match="exact frozen"):
        runner.check_native_task(frozen.strip(), frozen.strip(), frozen)
    with pytest.raises(RuntimeError, match="native-normalized"):
        runner.check_native_task(frozen.strip().replace("必须  保留", "必须 保留"), frozen, frozen)


@pytest.mark.parametrize("change", ["source", "scenario", "status", "digest"])
def test_stale_or_wrong_gate_rejected(change):
    identity = {"source": "a", "schedule": "07:00"}
    gate = gate_for(identity)
    if change == "source":
        identity = {**identity, "source": "b"}
    elif change == "scenario":
        gate["scenario_id"] = "scenario_maize_l3_basic_n01_v1"
    elif change == "status":
        gate["status"] = "failed"
    else:
        gate["identity_sha256"] = "incorrect"
    with pytest.raises(RuntimeError, match="no farm actions"):
        runner.require_matching_gate(gate, identity)


class PublicExecutorFixture:
    def __init__(self, condition="maintenance_required", service_status="service_completed"):
        self.last_public_observation = {
            "id": "obs-public-001", "time": 1000,
            "crop": {"ridges_overview": [
                {"ridge_id": rid, "growth_stage": "MATURE", "harvested": False}
                for rid in range(64)
            ]},
        }
        self.time = 1000
        self.calls = 0
        self.events = []
        self.logs = []
        self.condition = condition
        self.service_status = service_status

    def now(self):
        return self.time

    def log(self, event):
        self.logs.append(copy.deepcopy(event))

    def required(self, tool):
        started = self.time
        self.calls += 1
        if tool == runner.INSPECT_TOOL:
            self.time += 600
            receipt = {"status": "inspection_completed", "condition": self.condition}
        elif tool == runner.SERVICE_TOOL:
            self.time += 3600
            self.condition = "serviceable"
            receipt = {"status": self.service_status, "condition": self.condition}
        else:
            raise AssertionError("Unexpected tool outside public fixture: " + tool)
        self.events.append({"tool": tool, "time_before": started, "time_after": self.time, "receipt": receipt})
        return receipt


def test_two_arms_share_inspection_and_keep_real_service_delay():
    a, b = PublicExecutorFixture(), PublicExecutorFixture()
    da = runner.inspect_and_branch(a, "A")
    db = runner.inspect_and_branch(b, "B")
    assert da["common_prefix_sha256"] == db["common_prefix_sha256"]
    assert da["common_prefix_calls"] == db["common_prefix_calls"] == 1
    assert a.events[0] == b.events[0]
    assert [event["tool"] for event in a.events] == [runner.INSPECT_TOOL, runner.SERVICE_TOOL]
    assert [event["tool"] for event in b.events] == [runner.INSPECT_TOOL]
    assert da["continued_at"] - db["continued_at"] == 3600
    assert a.condition == "serviceable"
    assert b.condition == "maintenance_required"


def test_serviceable_public_receipt_does_not_trigger_unnecessary_service():
    executor = PublicExecutorFixture(condition="serviceable")
    decision = runner.inspect_and_branch(executor, "A")
    assert executor.calls == 1
    assert decision["action"] == "already_serviceable"


def test_unknown_public_condition_stops_without_service():
    executor = PublicExecutorFixture(condition="unavailable")
    with pytest.raises(runner.base.PilotStop, match="inspection receipt"):
        runner.inspect_and_branch(executor, "A")
    assert executor.calls == 1


def test_incomplete_service_is_not_treated_as_success():
    executor = PublicExecutorFixture(service_status="partial")
    with pytest.raises(runner.base.PilotStop, match="did not establish"):
        runner.inspect_and_branch(executor, "A")


def test_common_trigger_uses_complete_public_maturity_before_any_new_action():
    executor = PublicExecutorFixture()
    executor.last_public_observation["crop"]["ridges_overview"][9]["growth_stage"] = "REPRODUCTIVE"
    with pytest.raises(runner.base.PilotStop, match="public all-mature"):
        runner.inspect_and_branch(executor, "A")
    assert executor.calls == 0


def test_existing_output_is_never_replaced(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "old.json"
    marker.write_text("old evidence")
    with pytest.raises(FileExistsError):
        runner.run("A", tmp_path / "unused-gate.json", output)
    assert marker.read_text() == "old evidence"


def test_failed_gate_preserves_failure_and_never_sets_up_farm(tmp_path, monkeypatch):
    identity = {"source": "frozen"}
    monkeypatch.setattr(runner, "identity", lambda: identity)
    monkeypatch.setattr(runner, "setup_scenario", lambda: pytest.fail("Farm setup must not run after rejected gate"))
    gate_path = tmp_path / "gate.json"
    gate_path.write_text(json.dumps({**gate_for(identity), "status": "failed"}))
    output = tmp_path / "failed-run"
    assert runner.run("A", gate_path, output) == 1
    status = json.loads((output / "run_status.json").read_text())
    assert status["tool_calls"] == 0
    assert status["controller_completed"] is False
    assert status["evaluation_available"] is False
    assert status["failures"][0]["stage"] == "gate"
    assert not (output / "evaluation.json").exists()
