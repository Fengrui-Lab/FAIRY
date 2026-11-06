"""Physical units, signed finances and compatibility contracts for management rebatch."""
from datetime import date
import csv
import json
import sys
from types import SimpleNamespace as NS

import pytest

from scripts import management_replay_metrics as metrics
from scripts import rebatch_fos_from_traces as rebatch
from scripts.replay_management_metrics import primary_args


@pytest.mark.parametrize("agent,oracle,ratio,delta,reason", [
    (120., 100., .2, 20., None),
    (-50., -100., -.5, 50., None),
    (7., 0., None, 7., "zero_oracle_denominator"),
    (None, 5., None, None, "missing_value"),
    (float("nan"), 5., None, None, "nonfinite_value"),
])
def test_signed_gaps_do_not_clip_or_replace_denominator(agent, oracle, ratio, delta, reason):
    result = metrics.relative_gap(agent, oracle)
    assert result["value"] == ratio
    assert result["difference"] == delta
    assert result["reason"] == reason


def _snapshot(records):
    return {**{basis + "_kg": sum(r[basis + "_kg"] for r in records)
               for basis in ("biological", "recovered", "recovered_floor")},
            "records": records,
            "accounts": dict(currency="USD", prices={"grain": 1},
                             production_cost=100, net_operating_margin=200)}


def test_mixed_products_sum_mass_before_ratio_and_keep_per_season_composition():
    oracle = _snapshot([
        metrics._record("field", 2020, "winter_wheat", 100, 120, recovered_floor=120),
        metrics._record("field", 2021, "sugarbeet", 300, 1200, recovered_floor=1200),
    ])
    agent = _snapshot([
        metrics._record("field", 2020, "winter_wheat", 120, 144, recovered_floor=144),
        metrics._record("field", 2021, "sugarbeet", 150, 600, recovered_floor=600),
    ])
    comparison = metrics.comparison(agent, oracle)
    assert comparison["yields"]["biological"]["loss_pct"] == pytest.approx(32.5)
    assert comparison["yields"]["recovered"]["loss_pct"] == pytest.approx(100 * (1 - 744 / 1320))
    assert comparison["details"][0]["biological"]["loss_pct"] == -20
    assert comparison["crop_composition_changed"] is False
    agent["records"][1]["crop_id"] = "maize"
    assert metrics.comparison(agent, oracle)["crop_composition_changed"] is True
    agent["accounts"]["prices"]["grain"] = 2
    assert metrics.comparison(agent, oracle)["economics"]["production_cost"]["reason"] == "currency_or_prices_mismatch"


def test_beet_uses_twso_dry_mass_and_lifted_roots_not_twrt_or_delivery():
    cycle = NS(cycle_id="beet", crop="sugarbeet", sowing_open=date(2020, 4, 1))
    backend = NS(cycle=cycle, harvests={"beet": {"native": {"TWSO": 2000, "TWRT": 99999}}})
    farm = NS(farm_id="arable", ridge_area_m2=1000, backends=[backend], bundle=NS(cycles=[cycle]))
    batch = NS(cycle_id="beet", block_id=0, recovered_net_kg=760, delivered_net_kg=100)
    scene = NS(farm=farm, delivery=NS(ledger=NS(batches={"batch": batch})))
    records = metrics._beet_records(scene, True, 365)
    assert records[0]["biological_kg"] == 200
    assert records[0]["recovered_kg"] == 760
    assert records[0]["recovered_basis"] == "fresh_root_kg"


def test_missing_run_report_recovers_explicit_batch_configuration(tmp_path):
    sid = "scenario_l3_soybean_high_water_price"
    cell = tmp_path / "agent" / "cell"
    cell.mkdir(parents=True)
    (cell / f"{sid}.agent_workflow.json").write_text("{}")
    manifests = tmp_path / "cells"
    manifests.mkdir()
    (manifests / f"{sid}.json").write_text(json.dumps({
        "cell_dir": str(cell), "scenario_kwargs": '{"seed": 19, "detailed_briefing": true}',
        "scenario_initialization_kwargs": '{"water": 42}',
    }))
    bundle = rebatch._load_fairy_run_bundle(cell)
    assert bundle["scenario_kwargs"] == {"seed": 19, "detailed_briefing": True}
    assert bundle["init_kwargs"] == {"water": 42}
    (cell / f"{sid}.run_report.json").write_text(json.dumps({"scenario_kwargs": {"seed": 7}}))
    assert rebatch._load_fairy_run_bundle(cell)["scenario_kwargs"] == {"seed": 7}


def test_entrypoint_preserves_explicit_old_projection_settings():
    assert primary_args(["--workers=1", "--extrapolation-max-days", "180", "--no-extrapolate"]) == [
        "--workers=1", "--extrapolation-max-days", "180", "--management-only", "--recursive"]
    defaults = primary_args([])
    assert defaults[defaults.index("--extrapolation-max-days") + 1] == "365"
    assert "--extrapolate" in defaults


def test_workflow_columns_equal_original_metric_functions(tmp_path, monkeypatch):
    from fairy.scenarios import workflow_validation as wf
    from fairy.scenarios.fos.path_correctness_v2 import evaluate_path_correctness_v2
    from fairy.scenarios.fos.spatiotemporal import baseline_bfcl
    oracle = {"a": dict(name="a", tool_name="Farm__irrigate", tool_args={"amount": 10}, time=None),
              "b": dict(name="b", tool_name="Farm__harvest", tool_args={"ridge_id": 0}, time=None)}
    agent = {"a": dict(oracle["a"], tool_args={"amount": 11})}
    monkeypatch.setattr(wf, "workflow_from_oracle_events", lambda _: oracle)
    monkeypatch.setattr(wf, "ensure_oracle_workflow", lambda _: oracle)
    monkeypatch.setattr(wf, "workflow_from_event_log", lambda _: agent)
    out = tmp_path / "fos.json"
    out.write_text("{}")
    row = {}
    rebatch._add_workflow_columns(row, NS(), NS(event_log=NS(list_view=lambda: [])), out)
    exact, relaxed = wf.evaluate_workflows(oracle, agent), evaluate_path_correctness_v2(oracle, agent, tol_ratio=2.)
    assert row["ktc(%)"] == rebatch._pct(exact["ktc_raw"])
    assert row["coverage_v1(%)"] == rebatch._pct(exact["coverage"])
    assert row["coverage(%)"] == rebatch._pct(relaxed["coverage_v2"])
    assert row["bfcl_success(%)"] == rebatch._pct(baseline_bfcl(oracle, agent))


def test_oracle_cache_does_not_accept_another_input_context(tmp_path, monkeypatch):
    # A mismatched fresh fingerprint must be rejected before executing an Oracle.
    scene = NS(scenario_id="example", _replay_initial_fingerprint="agent-input")
    monkeypatch.setattr(rebatch, "_instantiate_scenario_for_replay", lambda *a: NS(_replay_initial_fingerprint="other-input"))
    with pytest.raises(ValueError, match="fingerprints differ"):
        metrics.oracle_reference(scene, {}, tmp_path, extrapolate=True, max_days=365)


def test_registered_management_set_has_39_unique_scenes():
    ids = metrics.management_scenario_ids()
    assert len(ids) == 39
    assert "scenario_l3_sugarbeet_delivery_window" not in ids
    assert "scenario_l4_wheat_sugarbeet_rotation" in ids


def test_checkpoint_clock_is_restored_before_recorded_takeover_is_checked(monkeypatch):
    from fairy.scenarios.registry import registry
    from fairy.controllers import engine

    class Checkpoint:
        __module__ = "fairy.scenarios.management_extensions.L4.test"

        def __init__(self):
            self.start_time = 100

        def _load_initial_checkpoint(self):
            pass

        def setup(self):
            assert self.start_time == 100  # Must retain the constructor epoch.
            self.start_time = 200

        def input_fingerprint(self):
            return "initial"

    monkeypatch.setattr(registry, "get_scenario", lambda _: Checkpoint)
    monkeypatch.setattr(engine, "Engine", lambda *a: None)
    scene = rebatch._instantiate_scenario_for_replay("test", 200, 0)
    assert scene.start_time == 200
    with pytest.raises(rebatch.ReplayDivergenceError, match="takeover start"):
        rebatch._instantiate_scenario_for_replay("test", 201, 0)


def test_harvested_grain_uses_receipt_state_without_copying_weather(monkeypatch):
    state = NS(harvested=True, biological_yield_g_m2=100,
               recovered_yield_g_m2_at_market_moisture=110)
    physics = NS(yield_recovery=NS(states={0: state}), phenology=NS(states={0: NS(planted=True)}))
    farm = NS(farm_id="field", crop_id="soybean", ridge_area_m2=100,
              physics=physics, _ridges=[NS(planted=True, harvested=True)])
    def no_copy(*args):
        raise AssertionError("A harvested crop needs no projection copy")
    monkeypatch.setattr(metrics, "deepcopy", no_copy)
    record = metrics._regular_farm_record(NS(start_time=0), farm, 2020, True, 365)
    assert record["biological_kg"] == 10
    assert record["recovered_kg"] == 11


def test_recursive_cli_keeps_duplicate_names_and_excludes_oracle_selftests(tmp_path, monkeypatch):
    sid = "scenario_l3_sugarbeet_full_season"
    root = tmp_path / "input"
    for mode in ("task", "expert", "oracle"):
        cell = root / mode / "same_cell"
        cell.mkdir(parents=True)
        (cell / f"{sid}.agent_workflow.json").write_text("{}")
        (cell / f"{sid}.run_report.json").write_text(json.dumps({
            "scenario_id": sid, "run_type": "oracle" if mode == "oracle" else "agent"}))
    def replay(cell, out, *args):
        return dict(scenario=sid, status="ok", cell_output_rel=args[-1].as_posix())
    monkeypatch.setattr(rebatch, "_replay_one_cell_safe", replay)
    monkeypatch.setattr(metrics, "export_management_tables", lambda *a: None)
    output = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["replay", "--root", str(root), str(root / "task"),
                                     "--out-root", str(output), "--management-only", "--recursive", "--workers", "1"])
    assert rebatch.main() == 0
    with (output / "summary_v2.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2  # Overlapping roots do not duplicate the task cell.
    assert len({r["cell_output_rel"] for r in rows}) == 2
    assert all("oracle" not in r["cell_output_rel"] for r in rows)


def test_failed_physical_replay_keeps_only_trace_metrics(tmp_path, monkeypatch):
    step = dict(name="a", tool_name="Farm__read", tool_args={}, op_type="READ",
                time=100., time_before=100., time_after=100., content={})
    bundle = dict(scenario_id="test", workflow={"a": step})
    monkeypatch.setattr(rebatch, "_instantiate_scenario_for_replay", lambda *a: NS(scenario_id="test"))
    monkeypatch.setattr(metrics, "oracle_reference", lambda *a, **kw: ({"workflow": {}}, tmp_path / "oracle.json"))
    def score(row, *a, **kw):
        row["bfcl_success(%)"] = "50.00"
    monkeypatch.setattr(rebatch, "_add_workflow_columns", score)
    row = metrics.workflow_metrics_after_replay_failure(
        bundle, {"status": "replay_failed"}, tmp_path, tmp_path / "cell",
        extrapolate=True, max_days=365, path_correctness_v2=True, pc2_tol=2.)
    assert row["physical_replay_verified"] is False
    assert row["workflow_metrics_source"] == "recorded_trace_only"
    assert row["bfcl_success(%)"] == "50.00"
    assert "yield_loss(%)" not in row and "relative_operating_cost_gap(%)" not in row


def test_oracle_selftest_does_not_accept_rounded_zero(tmp_path):
    comp = {"yields": {key: {"value": 0.} for key in ("biological", "recovered")},
            "economics": {key: {"value": 0.} for key in ("production_cost", "net_operating_margin")}}
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps({"comparison": comp}))
    row = {"status": "ok", "management_metrics_path": str(path), "yield_loss(%)": "0.00"}
    assert metrics.oracle_self_replay_matches(row)
    comp["yields"]["biological"]["value"] = .00002  # Still displays 0.00 percent.
    path.write_text(json.dumps({"comparison": comp}))
    assert not metrics.oracle_self_replay_matches(row)
