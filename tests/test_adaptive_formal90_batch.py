"""Lightweight batch tests: no crop engine or full-season job is launched."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_adaptive_formal90 as batch


SOURCE = {"fairy/example.py": "current"}


def completed_case(folder, *, source=SOURCE, parameters=None):
    folder.mkdir(parents=True, exist_ok=True)
    batch.write_json(folder / "summary.json", {"scenario_id": "case_a", "mode": "adaptive",
        "completion": "feasible_operational_reference", "replay_exact_physical_state": True,
        "replay_exact_tool_trace_and_time": True, "replay_error_count": 0,
        "warehouse_grain_kg": 100, "adaptive_water_actions": 2, "adaptive_crop_actions": 3,
        "metrics": {"operational_complete": True, "safe_stored_kg": 100}})
    batch.write_json(folder / "provenance.json", {"scenario_id": "case_a", "mode": "adaptive",
        "source_sha256": source, "water_parameters": parameters, "crop_management_enabled": True})
    for name in ("observed_workflow.json", "fresh_replay.json", "initial_snapshot.json",
                 "discovery_final_snapshot.json", "replay_final_snapshot.json"):
        batch.write_json(folder / name, {})
    for name in ("fresh_replay_errors.json", "fresh_replay_trace_differences.json"):
        batch.write_json(folder / name, [])
    batch.write_json(folder / "final_state.json", {"farms": {"Farm": {"world": {"management_regime": {
        "irrigation_quota_mm_total": 8, "irrigation_used_mm_total": 7}}}}})


def test_resume_requires_complete_current_settings_and_exact_replay_evidence(tmp_path):
    completed_case(tmp_path)
    result = batch.collect_case("case_a", tmp_path, SOURCE)
    assert result["status"] == "completed_exact_replay"
    assert result["safe_stored_kg"] == 100
    assert result["water_quota"]["Farm"]["irrigation_used_mm_total"] == 7
    assert batch.collect_case("case_a", tmp_path, {"other": "source"})["status"] == "stale_or_mismatched_output"
    assert batch.collect_case("case_a", tmp_path, SOURCE, {"threshold": .3})["status"] == "stale_or_mismatched_output"
    (tmp_path / "fresh_replay.json").unlink()
    assert batch.collect_case("case_a", tmp_path, SOURCE)["status"] == "incomplete"


def test_incomplete_or_blocked_grain_is_never_presented_as_comparable_safe_yield(tmp_path):
    completed_case(tmp_path)
    result = batch.read_json(tmp_path / "summary.json")
    result.update(completion="blocked", message="Native replant unsupported", warehouse_grain_kg=20)
    batch.write_json(tmp_path / "summary.json", result)
    row = batch.collect_case("case_a", tmp_path, SOURCE)
    assert row["status"] == "blocked"
    assert row["safe_stored_kg"] is None
    assert row["recorded_warehouse_grain_kg_not_comparable_if_incomplete"] == 20
    assert row["block_reason"] == "Native replant unsupported"


def test_completed_resume_launches_no_subprocess(tmp_path):
    folder = tmp_path / "cases/case_a/adaptive"
    completed_case(folder)
    row = batch.run_case("case_a", tmp_path, SOURCE,
        execute=lambda *args, **kwargs: pytest.fail("Current completed case should resume"))
    assert row["resumed"] is True
    assert not (folder.parent / "archive").exists()


def test_stale_result_archived_and_stub_process_receives_fixed_environment(tmp_path, monkeypatch):
    folder = tmp_path / "cases/case_a/adaptive"
    completed_case(folder, source={"old": "source"})
    monkeypatch.setenv("USER", "must-not-leak")
    monkeypatch.setenv("PYTHONHASHSEED", "random")
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "64")
    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        assert kwargs["env"]["PYTHONHASHSEED"] == "0"
        for key in ("PYTHONDONTWRITEBYTECODE", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
            assert kwargs["env"][key] == "1"
        assert "USER" not in kwargs["env"]
        assert command[command.index("--mode") + 1] == "adaptive"
        assert command[command.index("--scenario") + 1] == "case_a"
        assert Path(command[command.index("--output-dir") + 1]) == folder
        kwargs["stdout"].write("stub output\n")
        kwargs["stderr"].write("stub diagnostic\n")
        completed_case(folder)
        return SimpleNamespace(returncode=0)

    row = batch.run_case("case_a", tmp_path, SOURCE, execute=execute)
    assert len(calls) == 1
    assert row["status"] == "completed_exact_replay" and row["resumed"] is False
    archives = list((folder.parent / "archive").iterdir())
    assert len(archives) == 1
    assert batch.read_json(archives[0] / "provenance.json")["source_sha256"] == {"old": "source"}
    assert (folder / "stdout.log").read_text() == "stub output\n"
    assert (folder / "stderr.log").read_text() == "stub diagnostic\n"


def test_scenario_selection_keeps_explicit_order_and_rejects_unknown_duplicate_ids(tmp_path):
    review = tmp_path / "review.json"
    batch.write_json(review, {"rows": [{"scenario_id": sid} for sid in ("case_a", "case_b", "case_c")]})
    assert batch.select_scenarios(review, ["case_c,case_a"]) == ["case_c", "case_a"]
    assert batch.select_scenarios(review, limit=1) == ["case_a"]
    with pytest.raises(ValueError, match="Unknown"):
        batch.select_scenarios(review, ["unknown"])
    with pytest.raises(ValueError, match="unique"):
        batch.select_scenarios(review, ["case_a,case_a"])


def test_failed_process_without_summary_is_explicit_and_does_not_invent_zero_yield(tmp_path):
    row = batch.run_case("case_a", tmp_path, SOURCE,
                         execute=lambda *args, **kwargs: SimpleNamespace(returncode=3))
    assert row["status"] == "process_failed"
    assert row["safe_stored_kg"] is None
    assert row["returncode"] == 3


def test_main_stub_batch_records_coverage_scope_and_per_case_progress(tmp_path, monkeypatch):
    review = tmp_path / "review.json"
    batch.write_json(review, {"rows": [{"scenario_id": "case_a"}, {"scenario_id": "case_b"}]})
    monkeypatch.setattr(batch, "runner_fingerprint", lambda: SOURCE)
    calls = []

    def run(sid, root, source, **kwargs):
        calls.append((sid, kwargs))
        return {"scenario_id": sid, "status": "completed_exact_replay", "safe_stored_kg": 100,
                "exact_replay": True, "operational_complete": True}

    monkeypatch.setattr(batch, "run_case", run)
    output = tmp_path / "run"
    result = batch.main(["--review", str(review), "--output-dir", str(output), "--workers", "2"])
    assert result["counts"] == {"completed_exact_replay": 2}
    assert result["source_unchanged_during_batch"] is True
    assert "no per-case matched control" in result["scope"]
    assert [row["scenario_id"] for row in result["rows"]] == ["case_a", "case_b"]
    assert batch.read_json(output / "progress.json")["counts"] == {"completed_exact_replay": 2}
    assert {sid for sid, _ in calls} == {"case_a", "case_b"}
