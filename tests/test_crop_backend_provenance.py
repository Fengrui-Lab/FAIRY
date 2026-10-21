from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from fairy.controllers.run_artifacts import build_run_report
from fairy.scenarios.fos.evaluation import (
    _load_donothing_baseline_biological_kg,
    _load_focus_ridge_baselines,
    _load_oracle_baseline_biological_kg,
    _load_oracle_baseline_recovered_yield_kg,
    evaluate_fos,
)
from fairy.scenarios.fos.provenance import crop_backend_provenance
from scripts.build_oracle_baselines import BaselineResult, _baseline_to_dict
from scripts import build_oracle_baselines as baseline_builder
from fairy.scenarios.fos import evaluation as fos_evaluation


def _wofost_provenance(fingerprint: str = "config-a") -> dict:
    return {
        "backend": "wofost",
        "model": "Wofost81_NWLP_CWB_CNB",
        "config_fingerprint": fingerprint,
        "config": {"crop": "soybean"},
    }


def _write_baseline(tmp_path, provenance=None, donothing_provenance=None):
    data = {
        "biological_yield_kg_total": 100.0,
        "recovered_yield_kg_total": 80.0,
        "biological_yield_g_m2_per_ridge": [20.0, 30.0],
        "donothing": {
            "biological_yield_kg_total": 50.0,
            "biological_yield_g_m2_per_ridge": [10.0, 15.0],
        },
    }
    if provenance is not None:
        data["crop_backend_provenance"] = provenance
    if donothing_provenance is not None:
        data["donothing"]["crop_backend_provenance"] = donothing_provenance
    (tmp_path / "scenario_test.json").write_text(json.dumps(data), encoding="utf-8")


def test_old_legacy_baseline_remains_compatible(tmp_path):
    _write_baseline(tmp_path)
    assert _load_oracle_baseline_biological_kg("scenario_test", tmp_path) == 100.0
    assert _load_oracle_baseline_recovered_yield_kg("scenario_test", tmp_path) == 80.0
    assert _load_donothing_baseline_biological_kg("scenario_test", tmp_path) == 50.0
    assert _load_focus_ridge_baselines("scenario_test", tmp_path, [1], 100.0) == (
        3.0, 1.5
    )


@pytest.mark.parametrize("cached", [None, {"backend": "legacy"}, _wofost_provenance("other")])
@pytest.mark.parametrize("loader", [
    _load_oracle_baseline_biological_kg,
    _load_oracle_baseline_recovered_yield_kg,
    _load_donothing_baseline_biological_kg,
])
def test_wofost_rejects_legacy_or_changed_config(tmp_path, cached, loader):
    _write_baseline(tmp_path, cached)
    with pytest.raises(ValueError, match="Regenerate this baseline"):
        loader("scenario_test", tmp_path, provenance=_wofost_provenance())


def test_matching_wofost_baseline_and_donothing_are_loaded(tmp_path):
    provenance = _wofost_provenance()
    _write_baseline(tmp_path, provenance, provenance)
    assert _load_oracle_baseline_biological_kg(
        "scenario_test", tmp_path, provenance=provenance
    ) == 100.0
    assert _load_donothing_baseline_biological_kg(
        "scenario_test", tmp_path, provenance=provenance
    ) == 50.0
    assert _load_focus_ridge_baselines(
        "scenario_test", tmp_path, [1], 100.0, provenance=provenance
    ) == (3.0, 1.5)


def test_wofost_rejects_untagged_donothing_in_matching_cache(tmp_path):
    provenance = _wofost_provenance()
    _write_baseline(tmp_path, provenance)
    with pytest.raises(ValueError, match="donothing"):
        _load_donothing_baseline_biological_kg(
            "scenario_test", tmp_path, provenance=provenance
        )
    with pytest.raises(ValueError, match="donothing"):
        _load_focus_ridge_baselines(
            "scenario_test", tmp_path, [1], 100.0, provenance=provenance
        )


def test_legacy_rejects_wofost_cache(tmp_path):
    _write_baseline(tmp_path, _wofost_provenance())
    with pytest.raises(ValueError, match="provenance mismatch"):
        _load_oracle_baseline_biological_kg("scenario_test", tmp_path)


def test_backend_provenance_excludes_dynamic_diagnostics_and_is_copied():
    stable = _wofost_provenance()
    backend = SimpleNamespace(snapshot=lambda: {"provenance": stable, "ridges": {0: {"LAI": 2.0}}})
    physics = SimpleNamespace(crop_backend_name="wofost", crop_backend=backend)
    result = crop_backend_provenance(SimpleNamespace(_physics=physics))
    assert result == stable
    result["config"]["crop"] = "changed"
    assert stable["config"]["crop"] == "soybean"


def test_wofost_requires_initialized_provenance():
    with pytest.raises(ValueError, match="Initialize the backend"):
        crop_backend_provenance(SimpleNamespace(crop_backend_name="wofost", crop_backend=None))


def test_new_baseline_serialization_records_backend_identity():
    provenance = _wofost_provenance()
    result = BaselineResult(
        scenario_id="scenario_test",
        biological_yield_g_m2_per_ridge=[10.0],
        biological_yield_kg_total=2.0,
        recovered_yield_g_m2_per_ridge=[8.0],
        recovered_yield_kg_total=1.6,
        ridges_planted=1,
        ridges_r8=1,
        ridges_harvested=1,
        extrapolation={},
        duration_s=0.0,
        crop_backend_provenance=provenance,
    )
    payload = _baseline_to_dict(result)
    assert payload["schema_version"] == 3
    assert payload["crop_backend_provenance"] == provenance


def test_fos_report_keeps_backend_provenance_without_cached_comparison():
    scenario = SimpleNamespace(scenario_id="scenario_test", apps=[])
    report = evaluate_fos(scenario, SimpleNamespace(), gates=[])
    assert report.to_dict()["crop_backend_provenance"] == {"backend": "legacy"}


def test_run_report_records_explicit_backend_identity():
    provenance = _wofost_provenance()
    report = build_run_report(
        scenario_id="scenario_test", controller_id=None, provider=None,
        model=None, temperature=None, run_type="oracle", stopped_reason="completed",
        wall_time_seconds=0.0, max_tool_calls=None, timeout_seconds=None,
        parallel_tool_calls=None, max_output_tokens=None, workflow_steps=0,
        tool_call_count=0, runtime_metrics=[], artifacts={},
        crop_backend_provenance=provenance,
    )
    assert report["crop_backend_provenance"] == provenance


@pytest.mark.parametrize("backend,with_config,expected", [
    (None, False, "legacy"),
    ("wofost", False, "wofost"),
    (None, True, "wofost"),
])
def test_baseline_cli_selects_backend_and_forwards_config(
    tmp_path, monkeypatch, backend, with_config, expected
):
    config = {"variety": "Soybean_901"}
    config_path = tmp_path / "wofost.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    argv = [
        "build_oracle_baselines.py", "--scenarios", "scenario_test",
        "--output-dir", str(tmp_path / "baselines"), "--include-donothing",
    ]
    if backend is not None:
        argv.extend(["--crop-backend", backend])
    if with_config:
        argv.extend(["--wofost-config", str(config_path)])
    captured = {}

    def build(scenario_id, **kwargs):
        captured.update(kwargs)
        return BaselineResult(
            scenario_id=scenario_id,
            biological_yield_g_m2_per_ridge=[], biological_yield_kg_total=0.0,
            recovered_yield_g_m2_per_ridge=[], recovered_yield_kg_total=0.0,
            ridges_planted=0, ridges_r8=0, ridges_harvested=0,
            extrapolation={}, duration_s=0.0,
        )

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(baseline_builder, "_build_one_baseline", build)
    assert baseline_builder.main() == 0
    assert captured["crop_backend"] == expected
    assert captured["crop_backend_options"] == (config if with_config else {})
    assert captured["include_donothing"] is True


def test_baseline_cli_rejects_legacy_with_wofost_config(tmp_path, monkeypatch):
    config_path = tmp_path / "wofost.json"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("sys.argv", [
        "build_oracle_baselines.py", "--crop-backend", "legacy",
        "--wofost-config", str(config_path),
    ])
    with pytest.raises(SystemExit) as exc:
        baseline_builder.main()
    assert exc.value.code == 2


@pytest.mark.parametrize("extrapolation", [
    {"status": "error", "error": "IRRAD outside allowed range"},
    {"status": "advanced", "days_ticked": 180, "reached_maturity": False},
])
def test_wofost_baseline_rejects_failed_or_incomplete_native_season(extrapolation):
    physics = SimpleNamespace(
        crop_backend_name="wofost",
        phenology=SimpleNamespace(states={0: SimpleNamespace(planted=True)}),
        yield_recovery=SimpleNamespace(states={0: SimpleNamespace(r8_reached=False)}),
    )
    with pytest.raises(RuntimeError, match="No WOFOST baseline was written"):
        baseline_builder._require_wofost_maturity(physics, extrapolation, "scenario_test")
    # The historical reduced-backend behavior remains unchanged.
    physics.crop_backend_name = "legacy"
    baseline_builder._require_wofost_maturity(physics, extrapolation, "scenario_test")


def test_wofost_baseline_accepts_maturity_or_unplanted_donothing():
    physics = SimpleNamespace(
        crop_backend_name="wofost",
        phenology=SimpleNamespace(states={0: SimpleNamespace(planted=True)}),
        yield_recovery=SimpleNamespace(states={0: SimpleNamespace(r8_reached=True)}),
    )
    baseline_builder._require_wofost_maturity(physics, {"status": "noop"}, "scenario_test")
    physics.phenology.states[0].planted = False
    physics.yield_recovery.states[0].r8_reached = False
    baseline_builder._require_wofost_maturity(
        physics, {"status": "skipped", "reason": "physics_never_ticked"}, "scenario_test"
    )


def test_native_baseline_cli_reports_failure_and_writes_no_cache(tmp_path, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise RuntimeError("Invalid native forcing; no usable baseline")

    monkeypatch.setattr(baseline_builder, "_build_one_baseline", fail)
    monkeypatch.setattr("sys.argv", [
        "build_oracle_baselines.py", "--crop-backend", "wofost",
        "--scenarios", "scenario_test", "--output-dir", str(tmp_path),
    ])
    assert baseline_builder.main() == 1
    assert "Invalid native forcing" in capsys.readouterr().err
    assert not (tmp_path / "scenario_test.json").exists()


@pytest.mark.parametrize("helper", [
    fos_evaluation.compute_donothing_per_ridge_yields,
    fos_evaluation.compute_donothing_biological_kg,
])
def test_inline_donothing_helpers_recreate_selected_backend_and_configuration(monkeypatch, helper):
    from fairy.apps.farm_world import FarmWorldApp
    from fairy.apps.farm_world.farm_world_app import DEFAULT_RIDGE_WIDTH_M, FIELD_LENGTH_M
    from fairy.scenarios.registry import registry
    from fairy.scenarios.scenario import Scenario

    instances = []
    provenance = _wofost_provenance()

    class BaselineScenario(Scenario):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.constructor_kwargs = kwargs
            instances.append(self)

        def initialize(self, **kwargs):
            self.initialization_kwargs = kwargs
            farm = FarmWorldApp()
            farm.num_ridges = 1
            farm._ridges = farm._ridges[:1]
            physics = farm.physics
            physics.engines_active = True
            physics.crop_backend_name = self.crop_backend
            physics.crop_backend = SimpleNamespace(snapshot=lambda: {"provenance": provenance})
            physics.phenology.states[0].planted = True
            physics.yield_recovery.states[0].r8_reached = True
            physics.yield_recovery.states[0].biological_yield_g_m2 = 20.0
            self.apps = [farm]

    monkeypatch.setattr(registry, "get_scenario", lambda sid: BaselineScenario)
    monkeypatch.setattr(fos_evaluation, "_extrapolate_physics_to_maturity", lambda *args, **kwargs: {"status": "noop"})
    result = helper(
        "scenario_test", start_time=1234.0, seed=17,
        crop_backend="wofost", crop_backend_options={"co2_ppm": 410.0},
        scenario_kwargs={"detailed_briefing": False}, init_kwargs={"sensor_count": 2},
        expected_provenance=provenance,
    )
    total = result[0] if isinstance(result, tuple) else result
    assert total == pytest.approx(20.0 * DEFAULT_RIDGE_WIDTH_M * FIELD_LENGTH_M / 1000)
    instance = instances[-1]
    assert instance.constructor_kwargs["crop_backend"] == "wofost"
    assert instance.constructor_kwargs["crop_backend_options"] == {"co2_ppm": 410.0}
    assert instance.constructor_kwargs["detailed_briefing"] is False
    assert instance.initialization_kwargs == {"sensor_count": 2}
    assert instance.seed == 17
    assert instance.apps[0].time_manager.time() == pytest.approx(1234.0, abs=0.1)
    with pytest.raises(ValueError, match="provenance mismatch"):
        helper("scenario_test", crop_backend="wofost", expected_provenance=_wofost_provenance("other"))


@pytest.mark.parametrize("inline_provenance", [None, {"backend": "legacy"}, _wofost_provenance("other")])
def test_wofost_inline_yield_cannot_bypass_provenance(inline_provenance):
    provenance = _wofost_provenance()
    farm = SimpleNamespace(_physics=SimpleNamespace(
        crop_backend_name="wofost",
        crop_backend=SimpleNamespace(snapshot=lambda: {"provenance": provenance}),
    ))
    scenario = SimpleNamespace(scenario_id="scenario_test", get_typed_app=lambda cls: farm)
    with pytest.raises(ValueError, match="inline do-nothing baseline"):
        evaluate_fos(
            scenario, SimpleNamespace(), gates=[], donothing_biological_kg=5.0,
            donothing_provenance=inline_provenance,
        )


def test_wofost_inline_yield_accepts_matching_provenance(monkeypatch):
    provenance = _wofost_provenance()
    legacy = evaluate_fos(SimpleNamespace(scenario_id="legacy", apps=[]), SimpleNamespace(), gates=[])
    monkeypatch.setattr(fos_evaluation, "_compute_outcome", lambda *args, **kwargs: (0.5, legacy.outcome_breakdown))
    farm = SimpleNamespace(_physics=SimpleNamespace(
        crop_backend_name="wofost",
        crop_backend=SimpleNamespace(snapshot=lambda: {"provenance": provenance}),
    ))
    scenario = SimpleNamespace(scenario_id="scenario_test", get_typed_app=lambda cls: farm)
    report = evaluate_fos(
        scenario, SimpleNamespace(), gates=[], donothing_biological_kg=5.0,
        donothing_provenance=provenance,
    )
    assert report.crop_backend_provenance == provenance
