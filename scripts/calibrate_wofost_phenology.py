#!/usr/bin/env python3
"""Inspect observed phenology evidence or fit an explicit native WOFOST 7.2 grid.

Dataset schema (paths are relative to the dataset JSON)::

    {"schema_version": 1, "target_cultivar": "HEINONG84",
     "parameter_grid": {"TSUM1": [450, 480, 520], "TSUM2": [770, 870]},
     "trials": [{"id": "a", "study": "...", "site": "...", "year": 2020,
       "cultivar": "HEINONG84", "source_url": "https://...",
       "record_type": "site_year_observation", "split": "train",
       "site_resolution": "resolved", "sowing_date": "2020-05-10",
       "location": {"latitude": 47.65, "longitude": 126.83, "elevation": 219},
       "weather_csv": "weather.csv", "base_config": "base.json",
       "weather_source": {"type": "gridded_proxy", "source_url": "https://..."},
       "observations": {"DOE": {"date": null, "definition": "emergence"},
         "DOA": {"date": "2020-07-01", "definition": "anthesis"},
         "DOM": {"date": "2020-09-15", "definition": "physiological_maturity"}}}]}

R1/R2 -> DOA and R7/R8 -> DOM require explicit pcse_event_mapping and
mapping_justification inside that observation. Harvest dates never imply DOM.
Cultivar aggregate durations (e.g. 119/123 days) are reference evidence only;
use record_type="cultivar_aggregate_reference", split="reference".

For published phase means, set objective="stage_durations" and observations
to {"DOE_DOA": {"duration_days": 41.3, "start_stage": "VE", "end_stage": "R1"},
"DOA_DOM": {"duration_days": 75.7, "start_stage": "R1", "end_stage": "R7"}}.
Each trial must also supply stage_mapping, e.g. "R7": {"pcse_event": "DOM",
"justification": "Explicit assumption comparing generic native maturity to
observed one-pod R7"}, likewise for VE/DOE and R1/DOA. Fractional durations
remain fractional; no observed calendar dates are manufactured. A published
total duration can be kept in reference_durations but is not a third target.

Only TSUM1/TSUM2 are fitted. All other crop, soil, photoperiod and weather
settings stay fixed. Native runs use run_wofost_standalone.py. No cultivar
profile/default is published. Inspect is the default and never runs PCSE.
Synthetic fixtures require allow_synthetic_software_test=true and are always
labelled software tests, never local observations or agricultural validation.
"""
from __future__ import annotations

import argparse
import copy
from datetime import date, timedelta
import hashlib
import importlib.util
import itertools
import json
import math
from pathlib import Path
import tempfile
from typing import Any
from urllib.parse import urlparse


EVENTS = ("DOE", "DOA", "DOM")
FIT_EVENTS = ("DOA", "DOM")
FIXED_PHENOLOGY = ("TSUMEM", "TBASEM", "TEFFMX", "IDSL", "DLO", "DLC", "DTSMTB", "DVSI", "DVSEND")
DURATION_PHASES = {"DOE_DOA": ("DOE", "DOA"), "DOA_DOM": ("DOA", "DOM")}


def _runner():
    path = Path(__file__).with_name("run_wofost_standalone.py")
    spec = importlib.util.spec_from_file_location("native_standalone_phenology_runner", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str, allow_nan=False) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _source_url(value: Any, synthetic: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return bool(parsed.netloc) and parsed.scheme in ({"http", "https", "synthetic"} if synthetic else {"http", "https"})


def _event(event: str, raw: Any) -> tuple[dict[str, Any] | None, str | None]:
    if raw is None or isinstance(raw, dict) and raw.get("date") is None:
        return None, None
    if not isinstance(raw, dict) or _day(raw.get("date")) is None:
        return None, f"{event}: date must be an ISO date or null"
    definition = str(raw.get("definition", "")).strip().lower()
    ordinary = {"DOE": {"emergence"}, "DOA": {"anthesis"}, "DOM": {"physiological_maturity"}}
    explicit = {"DOE": {"ve"}, "DOA": {"r1", "r2"}, "DOM": {"r7", "r8"}}
    mapping_assumption = definition in explicit[event]
    if definition not in ordinary[event]:
        if not (mapping_assumption and raw.get("pcse_event_mapping") == event and
                isinstance(raw.get("mapping_justification"), str) and raw["mapping_justification"].strip()):
            return None, f"{event}: unknown/incompatible stage definition {definition!r}; no implicit harvest or R-stage mapping"
    return {**raw, "date": str(_day(raw["date"])), "mapping_assumption": mapping_assumption}, None


def _duration(phase: str, raw: Any, mappings: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw, dict) or raw.get("duration_days") is None:
        return None, None
    value = raw.get("duration_days")
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
        return None, f"{phase}: duration_days must be a positive finite number, not NA or an inferred date"
    if not isinstance(mappings, dict):
        return None, f"{phase}: explicit stage_mapping and justification are required"
    resolved = {}
    for field, expected in zip(("start_stage", "end_stage"), DURATION_PHASES[phase]):
        observed_stage = raw.get(field)
        mapping = mappings.get(observed_stage) if isinstance(observed_stage, str) else None
        if (not observed_stage or observed_stage.strip().upper() in {"HARVEST", "HARVEST_DATE", "DOH"} or
                not isinstance(mapping, dict) or mapping.get("pcse_event") != expected or
                not isinstance(mapping.get("justification"), str) or not mapping["justification"].strip()):
            return None, f"{phase}: {field} requires explicit {expected} stage_mapping and justification; harvest cannot imply maturity"
        resolved[observed_stage] = mapping
    return {**raw, "duration_days": float(value), "stage_mapping": resolved,
            "native_maturity_comparison_assumption": "DOM" in DURATION_PHASES[phase]}, None


def _grid(raw: Any) -> tuple[dict[str, list[float]], list[str]]:
    result, errors = {}, []
    if not isinstance(raw, dict) or set(raw) != {"TSUM1", "TSUM2"}:
        return {}, ["parameter_grid must specify exactly TSUM1 and TSUM2"]
    for key in ("TSUM1", "TSUM2"):
        values = raw[key]
        if (not isinstance(values, list) or not values or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0
                for v in values)):
            errors.append(f"parameter_grid.{key} must be an explicit non-empty list of positive finite values")
        else:
            result[key] = sorted(set(float(v) for v in values))
    return result, errors


def _inspect_trial(raw: Any, index: int, directory: Path, dataset: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"id": str(index), "eligible": False, "gaps": ["trial must be an object"], "split": None}
    result = {"index": index, "id": raw.get("id", str(index)), "study": raw.get("study"),
              "site": raw.get("site"), "year": raw.get("year"), "cultivar": raw.get("cultivar"),
              "record_type": raw.get("record_type"), "split": raw.get("split"),
              "source_url": raw.get("source_url"), "gaps": [], "source_files": {}}
    result["source_record"] = raw  # Preserve reference values, locators and caveats without converting them to targets.
    objective = dataset.get("objective", "calendar_dates")
    result["objective"] = objective
    gaps = result["gaps"]
    for key in ("id", "study", "site", "cultivar"):
        if not isinstance(raw.get(key), str) or not raw[key].strip() or raw[key].strip().lower() in {"unknown", "ambiguous"}:
            gaps.append(f"{key} is missing or unresolved")
    year = raw.get("year")
    if isinstance(year, bool) or not isinstance(year, int) or not 1800 <= year <= 2200:
        gaps.append("year must identify a single observed growing season")
    synthetic = raw.get("record_type") == "synthetic_software_test"
    if not _source_url(raw.get("source_url"), synthetic):
        gaps.append("source_url must identify the source record")
    if raw.get("record_type") == "cultivar_aggregate_reference":
        gaps.append("aggregate cultivar durations are reference evidence, not site-year observations")
    elif raw.get("record_type") == "model_derived":
        gaps.append("model-derived targets cannot independently calibrate/validate this model")
    elif raw.get("record_type") not in {"site_year_observation", "synthetic_software_test"}:
        gaps.append("record_type is missing or not an eligible observed site-year record")
    if synthetic and dataset.get("allow_synthetic_software_test") is not True:
        gaps.append("synthetic data require allow_synthetic_software_test=true and cannot claim agricultural validation")
    if raw.get("split") not in {"train", "validation"}:
        gaps.append("split must be train or validation for fitting")
    if raw.get("site_resolution") != "resolved" or raw.get("site_ambiguous") is True:
        gaps.append("site location is ambiguous or has not been explicitly resolved")
    if dataset.get("target_cultivar") and raw.get("cultivar") != dataset["target_cultivar"]:
        gaps.append("cultivar differs from target_cultivar")
    if isinstance(raw.get("site"), str) and isinstance(year, int) and isinstance(raw.get("cultivar"), str):
        site_id = raw.get("site_id") if isinstance(raw.get("site_id"), str) and raw["site_id"].strip() else raw["site"]
        result["case_group"] = [site_id.strip().casefold(), year, raw["cultivar"].strip().casefold()]
    observed = raw.get("observations") if isinstance(raw.get("observations"), dict) else {}
    result["observations"] = {}
    targets = EVENTS if objective == "calendar_dates" else tuple(DURATION_PHASES)
    for target in targets:
        value, error = (_event(target, observed.get(target)) if objective == "calendar_dates" else
                        _duration(target, observed.get(target), raw.get("stage_mapping")))
        result["observations"][target] = value
        if error:
            gaps.append(error)
    result["missing_observed_phenology"] = [event for event, value in result["observations"].items() if value is None]
    for target in FIT_EVENTS if objective == "calendar_dates" else DURATION_PHASES:
        if result["observations"][target] is None:
            gaps.append(f"observed {target} is required to identify TSUM1/TSUM2 separately")
    if objective == "stage_durations":
        result["stage_mapping"] = raw.get("stage_mapping")
        result["calendar_observations_synthesized"] = False
        result["reference_durations"] = raw.get("reference_durations", {})
        if all(result["observations"].values()):
            result["observed_phase_sum_days"] = sum(o["duration_days"] for o in result["observations"].values())
            reference = result["reference_durations"].get("VE_R7") if isinstance(result["reference_durations"], dict) else None
            if isinstance(reference, (int, float)) and not isinstance(reference, bool) and math.isfinite(reference):
                result["reference_total_minus_phase_sum_days"] = reference - result["observed_phase_sum_days"]
    sowing = _day(raw.get("sowing_date"))
    result["sowing_date"] = str(sowing) if sowing else None
    if sowing is None or sowing.year != year:
        gaps.append("sowing_date must be an observed ISO date matching year")
    previous = sowing
    for event in EVENTS if objective == "calendar_dates" else ():
        observation = result["observations"][event]
        if observation:
            current = _day(observation["date"])
            if previous and current < previous:
                gaps.append(f"{event} precedes sowing or the previous observed stage")
            previous = current
    location = raw.get("location")
    if (not isinstance(location, dict) or any(
            isinstance(location.get(k), bool) or not isinstance(location.get(k), (int, float)) or not math.isfinite(location[k])
            for k in ("latitude", "longitude", "elevation"))):
        gaps.append("location requires explicit finite latitude, longitude and elevation")
        location = None
    elif not (-90 <= location["latitude"] <= 90 and -180 <= location["longitude"] <= 180 and -300 <= location["elevation"] <= 6000):
        gaps.append("location is outside native PCSE latitude/longitude/elevation ranges")
        location = None
    weather_source = raw.get("weather_source")
    if (not isinstance(weather_source, dict) or weather_source.get("type") not in
            {"station_observation", "gridded_proxy", "synthetic_software_test"} or
            not _source_url(weather_source.get("source_url"), synthetic)):
        gaps.append("weather_source requires its type and source_url; gridded weather is a proxy")
    result["weather_source"] = weather_source
    if isinstance(weather_source, dict) and weather_source.get("type") == "synthetic_software_test" and not synthetic:
        gaps.append("synthetic forcing cannot be labelled an observed agricultural validation trial")
    for field in ("base_config", "weather_csv"):
        value = raw.get(field)
        path = (directory / value).resolve() if isinstance(value, str) and value else None
        if path is None or not path.is_file():
            gaps.append(f"{field} file is missing")
        else:
            result["source_files"][field] = {"path": str(path), "sha256": _sha(path)}
            result[f"_{field}"] = path
    if "_base_config" in result:
        try:
            config = _runner().load_config(result["_base_config"])
            if sowing:
                config.update(sowing_date=sowing, year=year)
            if location:
                config["location"] = location
            result["_config"] = config
            result["fixed_phenology"] = {key: config["crop_parameters"].get(key) for key in FIXED_PHENOLOGY}
            if crop_file := config.get("resolved_crop_parameter_file"):
                path = Path(crop_file)
                result["source_files"]["crop_parameters"] = {"path": str(path), "sha256": _sha(path)}
            if sowing and "_weather_csv" in result:
                _runner().read_weather(result["_weather_csv"], config)
                last_day = sowing + timedelta(days=config["max_duration"])
                if previous and previous > last_day:
                    gaps.append("observed phenology exceeds the explicit model max_duration/weather window")
                if objective == "stage_durations" and all(result["observations"].values()):
                    minimum_observed_span = sum(o["duration_days"] for o in result["observations"].values())
                    if minimum_observed_span > config["max_duration"]:
                        gaps.append("observed phase durations exceed the explicit model max_duration/weather window")
        except (ValueError, OSError, TypeError) as error:
            gaps.append(f"native input validation: {error}")
    result["eligible"] = not gaps
    return result


def _public(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if not key.startswith("_")}


def inspect_dataset(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = Path(path).resolve()
    dataset = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(dataset, dict) or dataset.get("schema_version") != 1 or not isinstance(dataset.get("trials"), list):
        raise ValueError("Dataset requires schema_version=1 and a trials list")
    objective = dataset.get("objective", "calendar_dates")
    if objective not in {"calendar_dates", "stage_durations"}:
        raise ValueError("objective must be calendar_dates or stage_durations")
    trials = [_inspect_trial(raw, i, path.parent, dataset) for i, raw in enumerate(dataset["trials"])]
    blockers = []
    grid, grid_errors = _grid(dataset.get("parameter_grid"))
    blockers.extend(grid_errors)
    groups: dict[str, set[str]] = {}
    ids = [str(record["id"]) for record in trials]
    if len(ids) != len(set(ids)):
        blockers.append("trial ids must be unique")
    for trial in trials:
        if "case_group" in trial and trial["split"] in {"train", "validation"}:
            groups.setdefault(json.dumps(trial["case_group"]), set()).add(trial["split"])
    leakage = [json.loads(group) for group, splits in groups.items() if len(splits) > 1]
    if leakage:
        blockers.append("site-year-cultivar case groups cross train/validation; holdout leakage")
    eligible = [trial for trial in trials if trial["eligible"]]
    for split in ("train", "validation"):
        if not any(trial["split"] == split for trial in eligible):
            targets = "DOA and DOM" if objective == "calendar_dates" else "DOE_DOA and DOA_DOM durations"
            blockers.append(f"no eligible independent {split} trial with observed {targets}")
    if len({trial["cultivar"] for trial in eligible}) > 1:
        blockers.append("one shared TSUM1/TSUM2 grid cannot calibrate multiple cultivars; set target_cultivar")
    if len({trial["record_type"] for trial in eligible}) > 1:
        blockers.append("real observations and synthetic software fixtures cannot be mixed")
    if len({json.dumps(trial["fixed_phenology"], sort_keys=True) for trial in eligible}) > 1:
        blockers.append("fixed phenology definitions differ across trials; do not mix thermal/photoperiod conventions")
    result = {
        "mode": "inspect", "status": "ready_for_fit" if not blockers else "blocked_missing_or_incompatible_evidence",
        "objective": objective,
        "dataset": {"path": str(path), "sha256": _sha(path)},
        "target_cultivar": dataset.get("target_cultivar"), "parameter_grid": grid,
        "trial_count": len(trials), "eligible_trial_count": len(eligible),
        "eligible_train_count": sum(t["split"] == "train" for t in eligible),
        "eligible_validation_count": sum(t["split"] == "validation" for t in eligible),
        "fit_blockers": blockers, "leaking_case_groups": leakage,
        "trials": [_public(trial) for trial in trials],
        "evidence_scope": "synthetic_software_test_only" if eligible and all(t["record_type"] == "synthetic_software_test" for t in eligible) else "published_observation_inventory_not_yet_fitted",
        "rules": {"fit_events": list(FIT_EVENTS if objective == "calendar_dates" else DURATION_PHASES), "fixed_parameters": list(FIXED_PHENOLOGY),
                  "selection": "Training mean squared day error only for the two declared targets; validation never selects a candidate.",
                  "reference": "Aggregate durations and model-derived products do not become site-year observations.",
                  "calendar": "Compare unmodified native PCSE dates against explicitly mapped observed stages.",
                  "stage_durations": "Compare native DOA-DOE and DOM-DOA with original fractional phase durations; no inferred observed dates and no duplicate total-duration objective.",
                  "unobserved_emergence": "Duration fitting is conditional on fixed TSUMEM and model-predicted DOE; it does not recover an observed emergence date or calibrate emergence.",
                  "weather": "Gridded weather remains an explicit forcing proxy, not a field observation.",
                  "promotion": "No cultivar profile or default is changed by this script."},
    }
    return result, trials


def _prediction(trial: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    result = {"id": trial["id"], "case_group": trial["case_group"], "split": trial["split"],
              "events": {}, "missing_simulated_phenology": [],
              "missing_observed_phenology": trial["missing_observed_phenology"],
              "model": summary["model"], "pcse_version": summary["pcse_version"],
              "objective": trial["objective"]}
    native = summary["native_crop_summary"]
    if trial["objective"] == "stage_durations":
        result["native_calendar"] = {event: str(native[event]) if native.get(event) else None for event in EVENTS}
        result["missing_simulated_phenology"] = [event for event in EVENTS if native.get(event) is None]
        result["calendar_observations_synthesized"] = False
        result["phase_durations"] = {}
        for phase, (start, end) in DURATION_PHASES.items():
            observation = trial["observations"][phase]
            simulated = (_day(native[end]) - _day(native[start])).days if native.get(start) and native.get(end) else None
            observed = observation["duration_days"] if observation else None
            result["phase_durations"][phase] = {
                "observed_duration_days": observed, "simulated_duration_days": simulated,
                "error_days": simulated - observed if simulated is not None and observed is not None else None,
                "used_for_training_objective": trial["split"] == "train",
                "observation_and_mapping": observation,
            }
        return result
    for event in EVENTS:
        observed = trial["observations"][event]
        simulated = native.get(event)
        if simulated is None:
            result["missing_simulated_phenology"].append(event)
        result["events"][event] = {
            "observed_date": observed["date"] if observed else None,
            "simulated_date": str(simulated) if simulated else None,
            "error_days": (_day(simulated) - _day(observed["date"])).days if simulated and observed else None,
            "used_for_training_objective": event in FIT_EVENTS and trial["split"] == "train",
        }
    return result


def _metrics(predictions: list[dict[str, Any]], objective: str = "calendar_dates") -> dict[str, Any]:
    per_event, errors, missing = {}, [], 0
    targets = EVENTS if objective == "calendar_dates" else tuple(DURATION_PHASES)
    container = "events" if objective == "calendar_dates" else "phase_durations"
    observed_field = "observed_date" if objective == "calendar_dates" else "observed_duration_days"
    for event in targets:
        observed_count = sum(p[container][event][observed_field] is not None for p in predictions)
        values = [p[container][event]["error_days"] for p in predictions if p[container][event]["error_days"] is not None]
        per_event[event] = {"n_observed": observed_count, "n_predicted": len(values),
                            "mae_days": sum(abs(v) for v in values) / len(values) if values else None,
                            "rmse_days": math.sqrt(sum(v*v for v in values) / len(values)) if values else None,
                            "bias_days": sum(values) / len(values) if values else None}
        if objective == "stage_durations" or event in FIT_EVENTS:
            errors.extend(values)
            missing += observed_count - len(values)
    score = sum(v*v for v in errors) / len(errors) if errors and not missing else None
    return {"objective": objective, "objective_mse_days2": score,
            "DOA_DOM_mse_days2": score if objective == "calendar_dates" else None,
            "phase_duration_mse_days2": score if objective == "stage_durations" else None,
            "missing_required_predictions": missing,
            "per_event" if objective == "calendar_dates" else "per_phase": per_event}


def _run_trial(trial: dict[str, Any], parameters: dict[str, float], destination: Path) -> dict[str, Any]:
    config = copy.deepcopy(trial["_config"])
    config.pop("crop_parameter_file", None)
    config.pop("resolved_crop_parameter_file", None)
    config["crop_parameters"].update(parameters)
    config["calibration_trial"] = {"id": trial["id"], "source_url": trial["source_url"],
                                   "record_type": trial["record_type"], "split": trial["split"]}
    path = destination / "candidate_input.json"
    _write(path, config)
    return _prediction(trial, _runner().run(path, trial["_weather_csv"], destination))


def calibrate(dataset_path: str | Path, output_dir: str | Path, mode: str = "inspect") -> dict[str, Any]:
    if mode not in {"inspect", "fit"}:
        raise ValueError("mode must be inspect or fit")
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report, trials = inspect_dataset(dataset_path)
    report["mode"] = mode
    source_files = {"calibrator": Path(__file__).resolve(), "native_runner": Path(__file__).with_name("run_wofost_standalone.py").resolve()}
    report["software_sources"] = {key: {"path": str(path), "sha256": _sha(path)} for key, path in source_files.items()}
    _write(output_dir / "inventory.json", report)
    _write(output_dir / "gaps_report.json", {"fit_blockers": report["fit_blockers"], "trials": [
        {"id": t["id"], "eligible": t["eligible"], "gaps": t["gaps"],
         "missing_observed_phenology": t.get("missing_observed_phenology", list(EVENTS))} for t in trials]})
    if mode == "inspect" or report["fit_blockers"]:
        if mode == "fit":
            report["status"] = "fit_blocked"
        _write(output_dir / "report.json", report)
        return report
    training = [t for t in trials if t["eligible"] and t["split"] == "train"]
    validation = [t for t in trials if t["eligible"] and t["split"] == "validation"]
    grid = report["parameter_grid"]
    objective = report["objective"]
    candidates = []
    with tempfile.TemporaryDirectory(prefix="phenology_candidates_", dir=output_dir) as temporary:
        work = Path(temporary)
        for index, values in enumerate(itertools.product(grid["TSUM1"], grid["TSUM2"])):
            parameters = dict(zip(("TSUM1", "TSUM2"), values))
            predictions, errors = [], []
            for trial in training:
                try:
                    predictions.append(_run_trial(trial, parameters, work / f"trial_{trial['index']}"))
                except Exception as error:
                    errors.append({"id": trial["id"], "error_type": type(error).__name__, "message": str(error)})
            metrics = _metrics(predictions, objective)
            score = metrics["objective_mse_days2"] if not errors else None
            candidates.append({"index": index, "parameters": parameters, "training_score": score,
                               "training_metrics": metrics, "training_predictions": predictions,
                               "native_errors": errors, "selectable": score is not None})
    _write(output_dir / "candidate_scores.json", candidates)
    valid = [c for c in candidates if c["selectable"]]
    if not valid:
        report.update(status="no_candidate_with_complete_training_phenology", candidate_count=len(candidates))
        _write(output_dir / "report.json", report)
        return report
    best = min(valid, key=lambda c: (c["training_score"], c["parameters"]["TSUM1"], c["parameters"]["TSUM2"]))
    equivalent = [c["parameters"] for c in valid if abs(c["training_score"] - best["training_score"]) <= 1e-12]
    selected_training = [_run_trial(t, best["parameters"], output_dir / "selected" / "train" / f"trial_{t['index']}") for t in training]
    selected_validation, validation_errors = [], []
    for trial in validation:
        try:
            selected_validation.append(_run_trial(trial, best["parameters"], output_dir / "selected" / "validation" / f"trial_{trial['index']}"))
        except Exception as error:
            validation_errors.append({"id": trial["id"], "error_type": type(error).__name__, "message": str(error)})
    validation_metrics = _metrics(selected_validation, objective)
    validation_complete = not validation_errors and validation_metrics["missing_required_predictions"] == 0
    report.update(
        status="fitted_candidate_only" if validation_complete else "fitted_candidate_validation_incomplete",
        candidate_count=len(candidates), selected_parameters=best["parameters"],
        equivalent_best_parameters=equivalent, equivalent_best_count=len(equivalent),
        selection_tie_break="Minimum training MSE, then smallest TSUM1, then smallest TSUM2; validation unused.",
        selected_on_grid_boundary={key: best["parameters"][key] in {min(grid[key]), max(grid[key])} for key in grid},
        equivalent_set_touches_grid_boundary={key: any(p[key] in {min(grid[key]), max(grid[key])} for p in equivalent) for key in grid},
        training_metrics=_metrics(selected_training, objective), validation_metrics=validation_metrics,
        training_predictions=selected_training, validation_predictions=selected_validation,
        validation_native_errors=validation_errors,
        agricultural_validation_claim=False if report["evidence_scope"] == "synthetic_software_test_only" else (
            "Observed phase-duration comparison only; native maturity/R-stage mapping remains an explicit assumption. No yield calibration or cultivar-profile promotion."
            if objective == "stage_durations" else "Observed stage-date comparison only; no yield calibration or cultivar-profile promotion."),
    )
    if report["evidence_scope"] != "synthetic_software_test_only":
        report["evidence_scope"] = "published_site_year_observation_candidate_fit"
    _write(output_dir / "candidate_parameters.json", {
        "status": "candidate_only_not_published", "parameters": best["parameters"],
        "objective": objective,
        "fixed_phenology": training[0]["fixed_phenology"],
        "equivalent_best_parameters": equivalent, "dataset": report["dataset"],
        "evidence_scope": report["evidence_scope"],
    })
    _write(output_dir / "report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--mode", choices=("inspect", "fit"), default="inspect")
    args = parser.parse_args(argv)
    try:
        report = calibrate(args.dataset, args.output_dir, args.mode)
    except (ValueError, OSError) as error:
        parser.exit(2, f"Phenology evidence error: {error}\n")
    print(json.dumps({key: report[key] for key in ("mode", "status", "trial_count", "eligible_trial_count", "fit_blockers")}, ensure_ascii=False, indent=2))
    return 2 if args.mode == "fit" and report["status"] != "fitted_candidate_only" else 0


if __name__ == "__main__":
    raise SystemExit(main())
