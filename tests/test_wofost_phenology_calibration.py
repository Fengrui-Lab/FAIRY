"""Calibration contract tests; synthetic fixtures are software tests only."""
from __future__ import annotations

import copy
import csv
import builtins
from datetime import date, timedelta
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "calibrate_wofost_phenology.py"
SPEC = importlib.util.spec_from_file_location("phenology_calibrator", SCRIPT)
assert SPEC and SPEC.loader
calibration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(calibration)


def _write(path, value):
    path.write_text(json.dumps(value, default=str), encoding="utf-8")


def _dataset(tmp_path, years=(2020, 2021, 2022)):
    runner = calibration._runner()
    config = copy.deepcopy(runner.load_config(ROOT / "configs/wofost/standalone_xu2026_hailun.json"))
    config.pop("crop_parameter_file", None)
    config.pop("resolved_crop_parameter_file", None)
    config["max_duration"] = 200
    base = tmp_path / "base.json"
    _write(base, config)
    trials = []
    for index, year in enumerate(years):
        sowing = date(year, 5, 10)
        weather = tmp_path / f"weather_{year}.csv"
        with weather.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["DAY", *runner.WEATHER_UNITS])
            writer.writeheader()
            for offset in range(201):
                writer.writerow({"DAY": sowing + timedelta(days=offset), "IRRAD": 18_000_000,
                                 "TMIN": 15 + index, "TMAX": 26 + index, "VAP": 14,
                                 "WIND": 2, "RAIN": 0.6})
        trials.append({
            "id": f"software_{year}", "study": "SYNTHETIC SOFTWARE TEST, NOT FIELD DATA",
            "site": "synthetic_location", "site_resolution": "resolved", "year": year,
            "cultivar": "SYNTHETIC_NOT_HEINONG84", "source_url": f"synthetic://software-tests/{year}",
            "record_type": "synthetic_software_test", "split": "validation" if index == len(years)-1 else "train",
            "sowing_date": str(sowing), "location": config["location"],
            "weather_csv": weather.name, "base_config": base.name,
            "weather_source": {"type": "synthetic_software_test", "source_url": f"synthetic://weather/{year}"},
            "observations": {"DOE": {"date": f"{year}-05-20", "definition": "emergence"},
                             "DOA": {"date": f"{year}-07-01", "definition": "anthesis"},
                             "DOM": {"date": f"{year}-09-01", "definition": "physiological_maturity"}},
        })
    payload = {"schema_version": 1, "target_cultivar": "SYNTHETIC_NOT_HEINONG84",
               "allow_synthetic_software_test": True,
               "parameter_grid": {"TSUM1": [420, 480, 480.0001, 540], "TSUM2": [690, 770, 770.0001, 850]},
               "trials": trials}
    path = tmp_path / "dataset.json"
    _write(path, payload)
    return path, payload


def _duration_dataset(tmp_path, years=(2020, 2021, 2022)):
    path, payload = _dataset(tmp_path, years=years)
    payload["objective"] = "stage_durations"
    for trial in payload["trials"]:
        trial["observations"] = {
            "DOE_DOA": {"duration_days": 41.3, "start_stage": "VE", "end_stage": "R1"},
            "DOA_DOM": {"duration_days": 75.7, "start_stage": "R1", "end_stage": "R7"},
        }
        trial["stage_mapping"] = {
            "VE": {"pcse_event": "DOE", "justification": "Explicit software-test stage mapping."},
            "R1": {"pcse_event": "DOA", "justification": "Explicit software-test first-flower comparison."},
            "R7": {"pcse_event": "DOM", "justification": "Generic native maturity is compared with one-pod R7 as an explicit structural assumption."},
        }
        trial["reference_durations"] = {"VE_R7": 117.1}
    _write(path, payload)
    return path, payload


def test_aggregate_duration_cannot_become_site_year_target(tmp_path, monkeypatch):
    dataset = {"schema_version": 1, "parameter_grid": {"TSUM1": [480], "TSUM2": [770]},
               "trials": [{"id": "official_119", "study": "Cultivar summary", "cultivar": "HEINONG84",
                           "source_url": "https://example.org/registration", "record_type": "cultivar_aggregate_reference",
                           "split": "reference", "reference_duration_days": 119}]}
    path = tmp_path / "aggregate.json"
    _write(path, dataset)
    monkeypatch.setattr(calibration, "_run_trial", lambda *a: pytest.fail("Reference evidence must never run fitting"))
    report = calibration.calibrate(path, tmp_path / "report", "fit")
    assert report["status"] == "fit_blocked"
    assert report["eligible_trial_count"] == 0
    assert any("aggregate cultivar durations" in gap for gap in report["trials"][0]["gaps"])
    assert not (tmp_path / "report/candidate_parameters.json").exists()


def test_inspect_never_imports_native_pcse_or_runs_the_model(tmp_path, monkeypatch):
    path, _ = _dataset(tmp_path)
    original_import = builtins.__import__

    def checked_import(name, *args, **kwargs):
        if name == "pcse" or name.startswith("pcse."):
            pytest.fail("Inspect must validate evidence without importing native PCSE")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked_import)
    report = calibration.calibrate(path, tmp_path / "inspection")
    assert report["mode"] == "inspect"
    assert report["status"] == "ready_for_fit"
    assert not (tmp_path / "inspection/candidate_scores.json").exists()


@pytest.mark.parametrize("mode,status,expected_code", [
    ("fit", "fitted_candidate_only", 0),
    ("fit", "fitted_candidate_validation_incomplete", 2),
    ("fit", "fit_blocked", 2),
    ("fit", "no_candidate_with_complete_training_phenology", 2),
    ("inspect", "blocked_missing_or_incompatible_evidence", 0),
])
def test_cli_exit_code_requires_complete_independent_validation(tmp_path, monkeypatch, capsys, mode, status, expected_code):
    """Automation must not treat a failed/incomplete holdout as successful fitting."""
    calls = []

    def calibration_result(dataset, output, selected_mode):
        calls.append((dataset, output, selected_mode))
        return {"mode": selected_mode, "status": status, "trial_count": 2,
                "eligible_trial_count": 2, "fit_blockers": []}

    monkeypatch.setattr(calibration, "calibrate", calibration_result)
    dataset, output = tmp_path / "dataset.json", tmp_path / "output"
    code = calibration.main(["--dataset", str(dataset), "--output-dir", str(output), "--mode", mode])
    assert code == expected_code
    assert calls == [(dataset, output, mode)]
    assert json.loads(capsys.readouterr().out)["status"] == status


def test_same_case_group_cannot_cross_training_and_validation(tmp_path):
    path, payload = _dataset(tmp_path, years=(2020, 2021))
    duplicate = copy.deepcopy(payload["trials"][0])
    duplicate.update(id="different_id_same_field", split="validation")
    payload["trials"].append(duplicate)
    _write(path, payload)
    report = calibration.calibrate(path, tmp_path / "leak", "fit")
    assert report["status"] == "fit_blocked"
    assert report["leaking_case_groups"] == [["synthetic_location", 2020, "synthetic_not_heinong84"]]
    assert any("holdout leakage" in gap for gap in report["fit_blockers"])


@pytest.mark.parametrize("definition", ["harvest", "unknown", "maturity", "R7", "R8"])
def test_unknown_or_unmapped_maturity_is_not_dom(tmp_path, definition):
    path, payload = _dataset(tmp_path)
    payload["trials"][0]["observations"]["DOM"]["definition"] = definition
    _write(path, payload)
    report, _ = calibration.inspect_dataset(path)
    assert report["trials"][0]["eligible"] is False
    assert any("no implicit harvest or R-stage mapping" in gap for gap in report["trials"][0]["gaps"])


def test_r8_requires_explicit_comparison_assumption(tmp_path):
    path, payload = _dataset(tmp_path)
    payload["trials"][0]["observations"]["DOM"].update(
        definition="R8", pcse_event_mapping="DOM",
        mapping_justification="Software-test assumption only; not proof R8 equals native physiological maturity.",
    )
    _write(path, payload)
    report, _ = calibration.inspect_dataset(path)
    assert report["trials"][0]["eligible"] is True
    assert report["trials"][0]["observations"]["DOM"]["mapping_assumption"] is True


def test_no_independent_validation_blocks_fit(tmp_path):
    path, payload = _dataset(tmp_path)
    for trial in payload["trials"]:
        trial["split"] = "train"
    _write(path, payload)
    report = calibration.calibrate(path, tmp_path / "missing_validation", "fit")
    assert report["status"] == "fit_blocked"
    assert any("no eligible independent validation" in gap for gap in report["fit_blockers"])


def test_ambiguous_site_and_missing_anthesis_are_visible_gaps(tmp_path):
    path, payload = _dataset(tmp_path)
    payload["trials"][0]["site_resolution"] = "ambiguous"
    payload["trials"][0]["observations"]["DOA"] = None
    _write(path, payload)
    report, _ = calibration.inspect_dataset(path)
    trial = report["trials"][0]
    assert trial["eligible"] is False
    assert "DOA" in trial["missing_observed_phenology"]
    assert any("location is ambiguous" in gap for gap in trial["gaps"])
    assert any("identify TSUM1/TSUM2" in gap for gap in trial["gaps"])


def test_model_derived_yields_cannot_validate_their_parent_model(tmp_path):
    path, payload = _dataset(tmp_path)
    payload["trials"][0]["record_type"] = "model_derived"
    _write(path, payload)
    report, _ = calibration.inspect_dataset(path)
    assert report["trials"][0]["eligible"] is False
    assert any("model-derived targets" in gap for gap in report["trials"][0]["gaps"])


def test_different_fixed_thermal_definitions_cannot_share_one_grid(tmp_path):
    path, payload = _dataset(tmp_path)
    altered = json.loads((tmp_path / "base.json").read_text())
    altered["crop_parameters"]["DTSMTB"] = [0, 0, 8, 0, 37, 29, 45, 29]
    _write(tmp_path / "different_thermal.json", altered)
    payload["trials"][0]["base_config"] = "different_thermal.json"
    _write(path, payload)
    report, _ = calibration.inspect_dataset(path)
    assert any("do not mix thermal/photoperiod conventions" in gap for gap in report["fit_blockers"])


def test_fractional_phase_observations_do_not_manufacture_calendar_dates(tmp_path):
    path, _ = _duration_dataset(tmp_path)
    report, _ = calibration.inspect_dataset(path)
    assert report["status"] == "ready_for_fit"
    assert report["objective"] == "stage_durations"
    trial = report["trials"][0]
    assert trial["calendar_observations_synthesized"] is False
    assert set(trial["observations"]) == {"DOE_DOA", "DOA_DOM"}
    assert trial["observations"]["DOE_DOA"]["duration_days"] == 41.3
    assert trial["observations"]["DOA_DOM"]["duration_days"] == 75.7
    assert all("date" not in observation for observation in trial["observations"].values())
    assert trial["reference_durations"] == {"VE_R7": 117.1}
    assert report["rules"]["fit_events"] == ["DOE_DOA", "DOA_DOM"]


@pytest.mark.parametrize("stage", ["VE", "R1", "R7"])
def test_duration_objective_requires_explicit_stage_mapping(tmp_path, stage):
    path, payload = _duration_dataset(tmp_path)
    del payload["trials"][0]["stage_mapping"][stage]["justification"]
    _write(path, payload)
    report, _ = calibration.inspect_dataset(path)
    assert report["trials"][0]["eligible"] is False
    assert any("stage_mapping and justification" in gap for gap in report["trials"][0]["gaps"])


def test_na_phase_duration_is_not_fitted_or_imputed(tmp_path):
    path, payload = _duration_dataset(tmp_path)
    payload["trials"][0]["observations"]["DOA_DOM"]["duration_days"] = "NA"
    _write(path, payload)
    report, _ = calibration.inspect_dataset(path)
    assert report["trials"][0]["eligible"] is False
    assert "DOA_DOM" in report["trials"][0]["missing_observed_phenology"]


def test_native_duration_pipeline_preserves_means_and_uses_two_phases(tmp_path):
    """Known native parameters test machinery; these are not field observations."""
    pytest.importorskip("pcse")
    path, payload = _duration_dataset(tmp_path)
    runner = calibration._runner()
    for trial in payload["trials"]:
        config = json.loads((tmp_path / "base.json").read_text())
        config.update(sowing_date=trial["sowing_date"], year=trial["year"], location=trial["location"])
        config["crop_parameters"].update(TSUM1=480, TSUM2=770)
        truth_path = tmp_path / f"phase_truth_{trial['year']}.json"
        _write(truth_path, config)
        truth = runner.run(truth_path, tmp_path / trial["weather_csv"], tmp_path / f"phase_truth_{trial['year']}")
        assert truth["matured"]
        native = truth["native_crop_summary"]
        trial["observations"]["DOE_DOA"]["duration_days"] = (native["DOA"] - native["DOE"]).days + 0.3
        trial["observations"]["DOA_DOM"]["duration_days"] = (native["DOM"] - native["DOA"]).days - 0.2
        trial["reference_durations"]["VE_R7"] = 999.1  # Deliberately inconsistent reference total must not influence fit.
    _write(path, payload)
    destination = tmp_path / "duration_fit"
    report = calibration.calibrate(path, destination, "fit")
    assert report["status"] == "fitted_candidate_only"
    assert report["selected_parameters"] == {"TSUM1": 480, "TSUM2": 770}
    assert report["agricultural_validation_claim"] is False
    assert report["training_metrics"]["phase_duration_mse_days2"] == pytest.approx(0.065)
    assert report["validation_metrics"]["phase_duration_mse_days2"] == pytest.approx(0.065)
    assert report["training_metrics"]["DOA_DOM_mse_days2"] is None
    assert set(report["training_metrics"]["per_phase"]) == {"DOE_DOA", "DOA_DOM"}
    for prediction in report["training_predictions"] + report["validation_predictions"]:
        assert prediction["events"] == {}
        assert prediction["calendar_observations_synthesized"] is False
        assert set(prediction["phase_durations"]) == {"DOE_DOA", "DOA_DOM"}
        assert all("observed_date" not in p for p in prediction["phase_durations"].values())
    candidates = json.loads((destination / "candidate_scores.json").read_text())
    assert all(c["training_metrics"]["objective"] == "stage_durations" for c in candidates)
    assert all(all(p["split"] == "train" for p in c["training_predictions"]) for c in candidates)


def test_native_synthetic_pipeline_holdout_ties_and_boundary_flags(tmp_path):
    """Recover known native parameters to test software, not local agronomy."""
    pytest.importorskip("pcse")
    path, payload = _dataset(tmp_path)
    runner = calibration._runner()
    base_sha = calibration._sha(tmp_path / "base.json")
    for trial in payload["trials"]:
        config = json.loads((tmp_path / "base.json").read_text())
        config.update(sowing_date=trial["sowing_date"], year=trial["year"], location=trial["location"])
        config["crop_parameters"].update(TSUM1=480, TSUM2=770)
        truth_path = tmp_path / f"truth_{trial['year']}.json"
        _write(truth_path, config)
        truth = runner.run(truth_path, tmp_path / trial["weather_csv"], tmp_path / f"truth_{trial['year']}")
        assert truth["matured"]
        for event in calibration.EVENTS:
            trial["observations"][event]["date"] = str(truth["native_crop_summary"][event])
    _write(path, payload)
    destination = tmp_path / "fit"
    report = calibration.calibrate(path, destination, "fit")
    assert report["status"] == "fitted_candidate_only"
    assert report["evidence_scope"] == "synthetic_software_test_only"
    assert report["agricultural_validation_claim"] is False
    assert report["selected_parameters"] == {"TSUM1": 480, "TSUM2": 770}
    assert report["training_metrics"]["DOA_DOM_mse_days2"] == 0
    assert report["validation_metrics"]["DOA_DOM_mse_days2"] == 0
    assert report["equivalent_best_count"] >= 2  # Native date resolution does not imply a unique thermal sum.
    assert report["selected_on_grid_boundary"] == {"TSUM1": False, "TSUM2": False}
    assert len(report["training_predictions"]) == 2
    assert len(report["validation_predictions"]) == 1
    candidates = json.loads((destination / "candidate_scores.json").read_text())
    assert len(candidates) == 16
    assert all(all(p["split"] == "train" for p in c["training_predictions"]) for c in candidates)
    assert calibration._sha(tmp_path / "base.json") == base_sha
    candidate = json.loads((destination / "candidate_parameters.json").read_text())
    assert set(candidate["parameters"]) == {"TSUM1", "TSUM2"}
    assert candidate["status"] == "candidate_only_not_published"
    payload["parameter_grid"] = {"TSUM1": [480], "TSUM2": [770]}
    _write(path, payload)
    boundary = calibration.calibrate(path, tmp_path / "boundary", "fit")
    assert boundary["selected_on_grid_boundary"] == {"TSUM1": True, "TSUM2": True}
