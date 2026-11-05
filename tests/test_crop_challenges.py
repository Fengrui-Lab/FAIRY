"""Decision challenges: public semantics, physical continuity, and negative controls."""
import json
import importlib
from datetime import date
from types import SimpleNamespace

import pytest

pytest.importorskip("pcse")

from fairy.apps.paddy.models import PaddyField, PaddyPlot, default_soil
from fairy.apps.paddy.observations import crop_report
from fairy.apps.paddy.operations import PaddyOpsApp
from fairy.apps.paddy.machinery import PaddyMachineryApp
from fairy.apps.paddy.world import PaddyWorldApp
from fairy.controllers.engine import Engine
from fairy.scenarios.crop_challenges import artifacts
from fairy.scenarios.crop_challenges.catalog import CHALLENGES, TASKS
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.rice.validation import audit_world


def scenario_engine(sid):
    scenario = get_scenario_class(sid)()
    scenario.setup()
    engine = Engine(None, scenario)
    engine.time_manager.real_time_passed = lambda: 0.
    return scenario, engine


def test_distinct_registry_ids_and_fixed_main_paths():
    assert len(CHALLENGES) == 10 and len(TASKS) == 24
    classes = [get_scenario_class(sid) for sid in TASKS]
    assert len(set(classes)) == 24
    for sid, (source, level, label) in TASKS.items():
        cls = get_scenario_class(sid)
        assert getattr(importlib.import_module(cls.__module__), cls.__name__) is cls
        scenario = get_scenario_class(sid)()
        assert scenario.source_l3_scenario_id == source
        assert scenario.level == level
        assert scenario.crop_backend == "wofost"
        assert scenario.crop_name == CHALLENGES[source].crop
        with pytest.raises(ValueError, match="declared WOFOST"):
            get_scenario_class(sid)(crop_backend="reduced")


@pytest.mark.parametrize("source", CHALLENGES)
def test_reviewed_evidence_and_control_integrity(source):
    data = artifacts.load(source)
    verification = json.loads((artifacts.ARTIFACT_ROOT / f"{source}.verification.json").read_text())
    assert set(data["tasks"]) == {sid for sid, row in TASKS.items() if row[0] == source}
    assert {c["policy"] for c in data["controls"]} == set(CHALLENGES[source].controls)
    for sid, task in data["tasks"].items():
        public_gates = json.JSONDecoder().raw_decode(task["briefing"].split("结果门槛（higher为至少、lower为至多）：", 1)[1])[0]
        assert public_gates == task["gates"]
        assert verification[sid]["replay_verified"]
        assert verification[sid]["pure_build"]
        assert verification[sid]["source_continuation_verified"]
        assert verification[sid]["success"] == (task["status"] == "calibrated")
        assert verification[sid]["physical_state_digest"] == task["endpoint_state_digest"]
        if TASKS[sid][1] != "L3":
            assert task["window_budgets"]
        if task["status"] == "calibrated" and TASKS[sid][1] != "L1":
            assert task["gates"]
            assert any(not c["errors"] and c["matched_time"] and c["matched_weather"] for c in data["controls"])
        plan = (artifacts.load_maize_plans(source, data)[sid]
                if CHALLENGES[source].crop == "maize" else task["plan"])
        assert artifacts.digest(plan) == task["plan_digest"]
        assert all("__" in step["tool_name"] and step["duration_seconds"] >= 0 for step in plan)


@pytest.mark.parametrize("value", [-1., float("nan"), float("inf"), True])
@pytest.mark.parametrize("key", ["puddled_sope_cm_day", "puddled_ksub_cm_day"])
def test_invalid_post_puddling_parameters_rejected(key, value):
    with pytest.raises(ValueError):
        PaddyPlot("p1", 1000., soil=dict(default_soil(), **{key: value}))


def test_per_plot_puddling_survives_real_preparation_and_replay():
    field = PaddyField().to_dict()
    field["plots"][0]["soil"].update(puddled_sope_cm_day=2., puddled_ksub_cm_day=.5)
    world = PaddyWorldApp(field=field)
    ops = PaddyOpsApp(world)
    ops.irrigate("p1", 100.)
    ops.soak("p1", 48)
    PaddyMachineryApp(world).attach_implement("tractor", "puddler")
    ops.puddle_and_level("p1")
    assert world.backends["p1"].water.params.SOPE == 2.
    assert world.backends["p1"].water.params.KSUB == .5
    state = world.get_state()
    replay = PaddyWorldApp(field=field)
    replay.load_state(state)
    world.run_job(86400)
    replay.run_job(86400)
    assert world.get_state() == replay.get_state()
    assert audit_world(world)["success"]


@pytest.mark.parametrize("planted,mature,dvs,lai,rate,dated,expected", [
    (False, False, None, 0., None, False, "unknown"),
    (True, False, .17, .3, .6, True, "elevated"),
    (True, False, .17, .3, 1., True, "low"),
    (True, False, .3, .3, 1., True, "unknown"),
    (True, False, .17, 1., 1., True, "unknown"),
    (True, False, .17, .3, None, True, "unknown"),
    (True, False, .17, .3, float("nan"), True, "unknown"),
    (True, False, .17, .3, .5, False, "unknown"),
    (True, True, 2., 0., 1., True, "unknown"),
])
def test_nitrogen_signal_requires_dated_juvenile_evidence(planted, mature, dvs, lai, rate, dated, expected):
    backend = SimpleNamespace(crop_values={"DVS": dvs, "LAI": lai}, maturity=mature,
                              last_rates={"RFRGRL": rate},
                              journal=[{"kind": "day", "day": "2026-01-08"}] if dated else [])
    report = crop_report(SimpleNamespace(backends={"p1": backend}), SimpleNamespace(plot_id="p1", planted=planted))
    assert report["nitrogen_stress_signal"] == expected
    assert report["nitrogen_signal_applicable"] == (expected != "unknown")
    assert report["nitrogen_signal_date"] == ("2026-01-08" if dated else None)
    assert not {"NAVAIL", "DVS", "LAI", "TWSO"} & report.keys()


@pytest.mark.parametrize("sid", [sid for sid, (_, level, _) in TASKS.items() if level == "L1"])
def test_l1_no_action_fails_but_captured_public_action_passes(sid):
    scenario, engine = scenario_engine(sid)
    assert not engine.evaluate().success
    before = scenario.export_checkpoint("pure_build")
    plan = engine.build_oracle_workflow(run_oracle=False)
    assert scenario.export_checkpoint("pure_build") == before
    engine.replay_workflow(plan)
    assert engine.evaluate().success


def test_wrong_zone_fertilizer_does_not_pass():
    scenario, engine = scenario_engine("scenario_maize_l1_targeted_fertilization")
    plan = engine.build_oracle_workflow(run_oracle=False)
    for step in plan.dag.values():
        if step.tool_name == "FarmWorldApp__apply_fertigation":
            count = step.tool_args["end_ridge"] - step.tool_args["start_ridge"] + 1
            step.tool_args = dict(step.tool_args, start_ridge=0, end_ridge=count-1)
    engine.replay_workflow(plan)
    result = engine.evaluate()
    assert not result.success
    assert "targeted action dose/coverage mismatch" in result.message


def test_l1_cannot_consume_later_repair_budget():
    scenario, engine = scenario_engine("scenario_rice_l1_channel_clearance")
    engine.build_oracle_workflow(run_oracle=True)
    assert engine.evaluate().success
    from fairy.apps.paddy.infrastructure import PaddyInfrastructureApp
    scenario.get_typed_app(PaddyInfrastructureApp).repair_bund("p1")
    result = engine.evaluate()
    assert not result.success
    assert "window resource budget exceeded: repair_used_kg" in result.message


def test_unknown_nitrogen_candidate_never_counts_as_calibrated():
    source = "scenario_rice_l3_zonal_water_n_allocation"
    data = artifacts.load(source)
    assert all(task["status"] == "experimental" for task in data["tasks"].values())
    assert not data["nitrogen_observability"]["p1"]["elevated_dates"]


def test_independent_water_by_nitrogen_probe_does_not_claim_a_diagnostic_window():
    from scripts.probe_rice_nitrogen_observability import probe
    evidence = probe()
    assert set(evidence["groups"]) == {"dry_low_n", "dry_high_n", "wet_low_n", "wet_high_n"}
    assert all(len(rows) == 7 for rows in evidence["groups"].values())
    assert not evidence["three_day_n_observability_gate"]


@pytest.mark.parametrize("control_yield,expected", [(1100., "experimental"), (1005., "calibrated"), (0., "experimental")])
def test_water_saving_requires_comparable_output(control_yield, expected):
    from scripts.build_crop_challenges import gates_for
    definition = CHALLENGES["scenario_maize_l3_rain_aware_irrigation"]
    reference = {"water_used": 100., "biological_dry_kg": 1000.}
    controls = [{"policy": "immediate", "errors": [], "matched_time": True, "matched_weather": True,
                 "outcomes": {"season": {"water_used": 120., "biological_dry_kg": control_yield}}}]
    gates, status, _ = gates_for(definition, "L3", "water_used", reference, controls)
    assert status == expected
    if status == "calibrated":
        assert gates[1]["threshold"] == pytest.approx(.99*control_yield)


def test_staggered_priority_cannot_be_validated_against_omission_alone():
    from scripts.build_crop_challenges import gates_for
    definition = CHALLENGES["scenario_maize_l3_staggered_water_priority"]
    controls = [{"policy": "omit", "errors": [], "matched_time": True, "matched_weather": True,
                 "outcomes": {"season": {"biological_dry_kg": 500.}}}]
    gates, status, _ = gates_for(definition, "L3", "biological_dry_kg", {"biological_dry_kg": 1000.}, controls)
    assert status == "experimental" and not gates


def test_calibration_review_preserves_recorded_evidence_and_author_provenance():
    from scripts.build_crop_challenges import review_calibration
    sid = "scenario_maize_l3_rain_aware_irrigation"
    reference = {"water_used": 100., "biological_dry_kg": 1000.}
    controls = [{"policy": "immediate", "errors": [], "matched_time": True, "matched_weather": True,
                 "outcomes": {"season": {"water_used": 120., "biological_dry_kg": 1100.}}}]
    data = {"source_id": sid, "authoring_digest": "original-author", "controls": controls,
            "checkpoints": {"initial": {"unchanged": True}},
            "tasks": {sid: {"status": "calibrated", "gates": [{"direction": "lower", "metric": "water_used", "threshold": 110.}], "calibration_note": "",
                            "reference": reference, "plan_digest": "frozen-plan",
                            "briefing": '结果门槛（higher为至少、lower为至多）：[{"metric": "water_used", "direction": "lower", "threshold": 110.0}]执行合同保留'}}}
    before = artifacts.digest([data["controls"], data["checkpoints"], reference])
    review_calibration(data)
    assert artifacts.digest([data["controls"], data["checkpoints"], data["tasks"][sid]["reference"]]) == before
    assert data["authoring_digest"] == "original-author"
    assert data["tasks"][sid]["plan_digest"] == "frozen-plan"
    assert data["tasks"][sid]["status"] == "experimental"
    assert "：[]执行合同保留" in data["tasks"][sid]["briefing"]
    assert data["calibration_reviews"][0]["previous"][sid]["status"] == "calibrated"


def test_staggered_native_histories_keep_first_sowing_and_single_base_input():
    data = artifacts.load("scenario_maize_l3_staggered_water_priority")
    backend = data["checkpoints"]["diagnosis"]["farm"]["farm_world_state"]["physics_state"]["crop_backend_state"]
    runs = backend["runs"]
    starts = [date.fromisoformat(runs[str(r)]["specification"]["planting_date"]) for r in (0, 22, 44)]
    assert starts[0] < starts[1] < starts[2]
    assert (starts[2]-starts[0]).days >= 16
    assert len(runs["0"]["journal"]) > len(runs["22"]["journal"]) > len(runs["44"]["journal"])
    for run in runs.values():
        days = [date.fromisoformat(e["day"]) for e in run["journal"]]
        assert all((b-a).days == 1 for a, b in zip(days, days[1:]))
        # Preplant fertilizer enters either the opening state or the first
        # native daily input, and must never enter both.
        total = run["specification"]["preplant_inputs"]["fertilizer_kg"]
        total += sum(e["inputs"]["fertilizer_kg"] for e in run["journal"])
        assert total == pytest.approx(200/64)


def test_missing_corrupt_and_stale_artifacts_fail_closed(tmp_path, monkeypatch):
    source = "scenario_rice_l3_zonal_crop_protection"
    raw = (artifacts.ARTIFACT_ROOT / f"{source}.json.gz").read_bytes()
    manifest = (artifacts.ARTIFACT_ROOT / "manifest.json").read_bytes()
    monkeypatch.setattr(artifacts, "ARTIFACT_ROOT", tmp_path)
    with pytest.raises(FileNotFoundError, match="rebuild"):
        artifacts.load(source)
    (tmp_path / "manifest.json").write_bytes(manifest)
    target = tmp_path / f"{source}.json.gz"
    target.write_bytes(raw + b"bad")
    with pytest.raises(ValueError, match="checksum"):
        artifacts.load(source)
    target.write_bytes(raw)
    monkeypatch.setattr(artifacts, "source_digest", lambda _: "different-code")
    with pytest.raises(ValueError, match="source changed"):
        artifacts.load(source)
