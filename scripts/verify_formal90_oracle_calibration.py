"""Independently verify saved Oracle calibration evidence without running FAIRY.

The verifier deliberately imports neither FAIRY nor the compiler. It checks the
saved public workflows and reported physical snapshots rather than trusting a
``completion`` label. Operational completion, management review, native mechanism
support and matched action experiments are separate conclusions.

Run with ``--output-root PATH``. A manifest may contain ``cases`` as a list of
``{scenario_id, case_dir}`` rows or an ID-to-directory mapping. Without a manifest,
case directories are discovered from summary.json files. A missing/blocked case
is a conclusion, not an operational pass. Snapshot equality covers the exported
backend states; it does not prove equality of every internal PCSE Python object.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from math import isfinite
from pathlib import Path
from typing import Any


UUID_FIELDS = {"op_id", "mission_id", "inspection_id", "action_id"}
TRACE_FIELDS = ("tool_name", "tool_args", "content", "time_before", "time_after")
MANAGEMENT_METHODS = {
    "apply_fungicide", "spray_pesticide", "apply_pesticide", "apply_pesticide_manual",
    "apply_herbicide", "mechanical_weed_control", "apply_fertilizer", "apply_fertigation",
    "irrigate", "irrigate_ridges", "irrigate_ridge", "irrigate_range", "replant_seeds", "incorporate_residue",
}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load(path: Path):
    def reject(value):
        raise ValueError(f"Non-finite JSON number: {value}")
    return json.loads(path.read_text(), object_pairs_hook=_unique_object, parse_constant=reject)


def normalize(value):
    if isinstance(value, dict):
        return {str(k): "<ID>" if k in UUID_FIELDS else normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return value


def digest(value):
    # Same documented canonical JSON convention as the evidence producer;
    # there is no import or call into its implementation.
    return hashlib.sha256(json.dumps(normalize(value), sort_keys=True).encode()).hexdigest()


def file_digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def numeric(value):
    return type(value) in (int, float) and isfinite(value)


def response_error(value):
    return isinstance(value, dict) and bool(
        value.get("error") or value.get("status") in {"error", "failed", "partial"}
    )


def method(step):
    return str(step.get("tool_name", "")).rsplit("__", 1)[-1]


def trace_projection(step):
    return normalize({key: step.get(key) for key in TRACE_FIELDS})


def _steps(workflow):
    if not isinstance(workflow, dict) or not workflow:
        raise ValueError("Workflow must be a non-empty named-step object")
    if not all(isinstance(v, dict) for v in workflow.values()):
        raise ValueError("Workflow contains a non-object step")
    return list(workflow.items())


def _farms(snapshot):
    farms = snapshot.get("farms", {})
    if not isinstance(farms, dict) or not farms:
        raise ValueError("Final snapshot has no farms")
    output = {}
    for name, farm in farms.items():
        world = farm.get("world", {})
        cfg = world.get("farm_config", world)
        fid = str(world.get("farm_id") or cfg.get("farm_id") or name)
        count = cfg.get("num_ridges", world.get("num_ridges"))
        if type(count) is not int or count <= 0 or fid in output:
            raise ValueError(f"Invalid or duplicate farm geometry/identity: {name}")
        output[fid] = {"name": name, "count": count, "state": farm}
    return output


def _step_farm(step, farms):
    args, content = step.get("tool_args") or {}, step.get("content")
    fid = args.get("farm_id")
    if not fid and isinstance(content, dict):
        fid = content.get("farm_id") or content.get("origin_farm_id")
    if fid in farms:
        return fid
    prefix = str(step.get("tool_name", "")).split("__", 1)[0]
    matches = [fid for fid, farm in farms.items() if prefix == farm["name"] or prefix.startswith(farm["name"] + "_")]
    if len(matches) == 1:
        return matches[0]
    if len(farms) == 1:
        return next(iter(farms))
    raise ValueError(f"Cannot resolve farm for {step.get('tool_name')}")


def _requested_ridges(step):
    args = step.get("tool_args") or {}
    if "ridge_id" in args:
        return list(range(int(args["ridge_id"]), int(args["ridge_id"]) + int(args.get("ridge_count", 1))))
    for start, end in (("start_ridge", "end_ridge"), ("start", "end")):
        if start in args and end in args:
            return list(range(int(args[start]), int(args[end]) + 1))
    return list(args.get("ridge_ids", []))


def verify_operations(workflow, snapshot, initial_snapshot=None):
    """Recompute per-ridge completion from receipts AND physical/native states."""
    farms = _farms(snapshot)
    initial_farms = _farms(initial_snapshot) if initial_snapshot and initial_snapshot.get("farms") else {}
    problems, notes, actions = [], [], []
    harvested = {fid: Counter() for fid in farms}
    stored = {fid: Counter() for fid in farms}
    stored_mass = {fid: 0.0 for fid in farms}
    last_rows = {fid: {} for fid in farms}
    last_time = None
    for name, step in _steps(workflow):
        before, after = step.get("time_before"), step.get("time_after")
        if not numeric(before) or not numeric(after) or after < before:
            problems.append({"code": "invalid_time", "step": name})
        elif last_time is not None and before < last_time:
            problems.append({"code": "time_moved_backwards", "step": name})
        if numeric(after):
            last_time = after
        content = step.get("content")
        if response_error(content):
            problems.append({"code": "tool_error", "step": name, "content": content})
        op = method(step)
        if not isinstance(content, dict):
            continue
        if op in {"get_ridge_state", "get_ridge_range_state"}:
            fid = _step_farm(step, farms)
            rows = content.get("ridges", [content.get("ridge", content)])
            for row in rows:
                if isinstance(row, dict) and "ridge_id" in row:
                    last_rows[fid][int(row["ridge_id"])] = row
        if op in MANAGEMENT_METHODS or op == "harvest":
            fid = _step_farm(step, farms)
            targets = _requested_ridges(step)
            stages = {str(rid): last_rows[fid].get(rid, {}).get("growth_stage") for rid in targets}
            actions.append({"step": name, "tool_name": step.get("tool_name"), "farm_id": fid,
                            "ridge_ids": targets, "time_before": before, "time_after": after,
                            "parameters": step.get("tool_args"), "last_public_stages": stages})
        if op == "harvest":
            actual = content.get("harvested_ridges")
            if not isinstance(actual, list) or set(actual) != set(targets):
                problems.append({"code": "harvest_receipt_coverage", "step": name})
            else:
                harvested[fid].update(actual)
            for rid in targets:
                row = last_rows[fid].get(rid, {})
                if not str(row.get("growth_stage", "")).upper().startswith("R8"):
                    problems.append({"code": "no_public_maturity_evidence", "step": name, "ridge_id": rid})
                moisture = row.get("grain_moisture_pct")
                if not numeric(moisture):
                    problems.append({"code": "unknown_harvest_moisture", "step": name, "ridge_id": rid})
        if op == "inspect_crop_health":
            covered = content.get("covered_ridges", [])
            if set(covered) != set(_requested_ridges(step)) or content.get("uncovered_ridges"):
                problems.append({"code": "incomplete_requested_inspection", "step": name})
            for rid, observation in content.get("observations", {}).items():
                for key, value in observation.items():
                    if key.endswith("confidence") and (not numeric(value) or not 0 <= value <= 1):
                        problems.append({"code": "invalid_observation_confidence", "step": name, "ridge_id": rid})
                    elif key.endswith("confidence") and value == 0:
                        notes.append({"code": "zero_confidence_observation", "step": name, "ridge_id": rid, "field": key})
        if op == "store_grain":
            if content.get("warning"):
                problems.append({"code": "storage_warning", "step": name, "warning": content["warning"]})
            if "batch_ridge_ids" in content and float(content.get("moved_kg", 0)) > 0:
                fid = _step_farm(step, farms)
                moisture, limit = content.get("storage_grain_moisture_pct"), content.get("max_storage_moisture_pct")
                if not numeric(moisture) or not numeric(limit) or moisture > limit + 1e-9:
                    problems.append({"code": "unsafe_storage_receipt", "step": name})
                else:
                    stored[fid].update(content["batch_ridge_ids"])
                    stored_mass[fid] += float(content["moved_kg"])
    # New shared Warehouse persists source-farm batches in its state. Legacy
    # storage uses the public store receipts above; never infer coverage from kg.
    for app_name, app in snapshot.get("apps", {}).items():
        if not isinstance(app, dict):
            continue
        if numeric(app.get("grain_bin_kg")) and app["grain_bin_kg"] > 0.01:
            problems.append({"code": "nonempty_combine", "app": app_name})
        batches = app.get("grain_batches")
        if isinstance(batches, (dict, list)):
            batch_rows = batches.items() if isinstance(batches, dict) else ((b.get("batch_id"), b) for b in batches)
            for batch_id, batch in batch_rows:
                fid = batch.get("origin_farm_id")
                if fid not in farms:
                    problems.append({"code": "unknown_batch_origin", "batch": batch_id})
                    continue
                moisture = batch.get("moisture_pct")
                limit = app.get("max_storage_moisture_pct", app.get("facilities", {}).get("max_storage_moisture_pct"))
                farm_limit = farms[fid]["state"].get("world", {}).get("postharvest_market", {}).get("max_storage_moisture_pct")
                if numeric(farm_limit) and numeric(limit):
                    limit = min(limit, farm_limit)
                if batch.get("status") != "stored" or not numeric(moisture) or not numeric(limit) or moisture > limit + 1e-9:
                    problems.append({"code": "unsafe_shared_batch", "batch": batch_id})
                else:
                    stored[fid].update(batch.get("ridge_ids", []))
                    if numeric(batch.get("quantity_kg")):
                        stored_mass[fid] += batch["quantity_kg"]
                    else:
                        problems.append({"code": "unknown_shared_batch_mass", "batch": batch_id})
    farm_results = {}
    for fid, farm in farms.items():
        expected = set(range(farm["count"]))
        physical = farm["state"].get("engines", {})
        ystates = physical.get("yield_recovery", {})
        native = (farm["state"].get("native_backend") or {}).get("ridges", {})
        if set(map(int, ystates)) != expected or set(map(int, native)) != expected:
            problems.append({"code": "incomplete_physical_native_ridges", "farm_id": fid})
        native_yield = 0.0
        for rid in sorted(expected):
            y = ystates.get(str(rid), ystates.get(rid, {}))
            n = native.get(str(rid), native.get(rid, {})).get("pcse", {})
            if not y.get("harvested") or not y.get("r8_reached") or not y.get("maturity_date"):
                problems.append({"code": "physical_not_mature_and_harvested", "farm_id": fid, "ridge_id": rid})
            if not n.get("DOM") or not numeric(n.get("TWSO")) or n["TWSO"] < 0:
                problems.append({"code": "native_maturity_or_dry_yield_missing", "farm_id": fid, "ridge_id": rid})
            else:
                native_yield += n["TWSO"]
        for kind, counts in (("harvest", harvested[fid]), ("storage", stored[fid])):
            if set(counts) != expected or any(count != 1 for count in counts.values()):
                problems.append({"code": f"{kind}_ridge_coverage_not_exactly_once", "farm_id": fid,
                                 "missing": sorted(expected - set(counts)), "counts": dict(counts)})
        inventory = farm["state"].get("world", {}).get("inventory", {})
        if numeric(inventory.get("harvest_grain_kg")) and inventory["harvest_grain_kg"] > 0.01:
            problems.append({"code": "nonempty_legacy_trailer", "farm_id": fid})
        if numeric(inventory.get("warehouse_grain_kg")):
            initial_inventory = initial_farms.get(fid, {}).get("state", {}).get("world", {}).get("inventory", {})
            initial_mass = float(initial_inventory.get("warehouse_grain_kg", 0))
            if abs(inventory["warehouse_grain_kg"] - initial_mass - stored_mass[fid]) > 0.011:
                problems.append({"code": "stored_receipts_disagree_with_final_inventory", "farm_id": fid})
        area = farm["state"].get("world", {}).get("field_area_m2")
        farm_results[fid] = {"expected_ridges": farm["count"], "harvested_receipt_ridges": len(harvested[fid]),
                             "stored_provenance_ridges": len(stored[fid]),
                             "safe_stored_kg": stored_mass[fid],
                             "native_TWSO_kg_ha_sum_over_ridges": native_yield,
                             "native_dry_grain_kg": native_yield * area / farm["count"] / 10000 if numeric(area) else None}
    return {"pass": not problems, "problems": problems, "notes": notes,
            "farms": farm_results, "management_actions": actions}


def verify_review(review, sid, source=None):
    problems = []
    if not isinstance(review, dict):
        return {"status": "not_assessed", "problems": ["case_review.json missing"]}
    if review.get("scenario_id") != sid:
        problems.append("scenario_id mismatch")
    source_only = review.get("review_status") == "source_and_original_workflow_review_complete_not_runtime_calibration_result"
    goal = review.get("scenario_goal_status")
    if source_only:
        goal = "explicit_model_gaps" if review.get("semantic_model_gaps") else "source_review_no_specific_gap_identified"
    elif goal not in {"preserved", "explicitly_unsupported"}:
        problems.append("scenario goal preservation/unsupported conclusion missing")
    actions = review.get("planned_management_actions") if source_only else review.get("actions")
    if not isinstance(actions, list):
        problems.append("per-source-action review missing")
    else:
        for index, action in enumerate(actions):
            required_fields = ("source_step", "public_evidence_required") if source_only else ("source_step", "reason", "parameter_basis")
            if not all(action.get(k) for k in required_fields):
                problems.append(f"action {index} lacks source/rationale/parameter basis")
            if source_only and not (action.get("dose_basis") or action.get("blocker")):
                problems.append(f"action {index} has no dose basis or explicit model blocker")
            if not source_only and action.get("decision") not in {"preserved", "revised", "removed", "not_supported"}:
                problems.append(f"action {index} has no explicit review decision")
    if isinstance(source, dict) and isinstance(actions, list):
        reviewed_methods = MANAGEMENT_METHODS if source_only else MANAGEMENT_METHODS | {"plant_seeds", "harvest", "store_grain"}
        required = {name for name, step in source.items() if method(step) in reviewed_methods}
        covered = set()
        for action in actions:
            steps = action.get("source_step", [])
            covered.update(steps if isinstance(steps, list) else [steps])
        missing = sorted(required - covered)
        if missing:
            problems.append({"unreviewed_source_management_steps": missing})
    return {"status": ("source_reviewed" if source_only else "reviewed") if not problems else "invalid", "goal_status": goal,
            "problems": problems, "action_count": len(actions or [])}


def verify_case(case_dir: Path, sid: str, *, source_root: Path | None = None):
    report = {"scenario_id": sid, "case_dir": str(case_dir), "missing_files": [], "integrity_problems": []}
    evidence = {}
    reference = case_dir / "reference" if (case_dir / "reference").is_dir() else case_dir
    common_names = {"provenance.json", "source_before.json", "source_after.json", "config.json"}
    paths = {}
    names = ("summary.json", "provenance.json", "original_workflow.json", "observed_workflow.json",
             "fresh_replay.json", "discovery_trace.json", "source_before.json", "source_after.json",
             "config.json", "initial_snapshot.json", "discovery_final_snapshot.json", "replay_final_snapshot.json")
    for name in names:
        path = (case_dir if name in common_names else reference) / name
        if name == "summary.json" and not path.is_file():
            path = case_dir / name
        paths[name] = path
        if not path.is_file():
            report["missing_files"].append(name)
            continue
        try:
            evidence[name] = load(path)
        except (ValueError, OSError) as exc:
            report["integrity_problems"].append(f"{name}: {exc}")
    summary, provenance = evidence.get("summary.json", {}), evidence.get("provenance.json", {})
    driver_summary = load(case_dir / "summary.json") if reference != case_dir and (case_dir / "summary.json").is_file() else summary
    report["producer_completion"] = summary.get("completion")
    for key, obj in (("summary", summary), ("provenance", provenance)):
        if obj and obj.get("scenario_id") != sid:
            report["integrity_problems"].append(f"{key} scenario_id mismatch")
    before, after = evidence.get("source_before.json"), evidence.get("source_after.json")
    report["source_unchanged_during_run"] = bool(before) and before == after
    if before is not None and before != after:
        report["integrity_problems"].append("production source changed during run")
    report["frozen_source_digest"] = digest(before) if before else None
    if source_root is not None and before:
        differing = [rel for rel, sha in before.items()
                     if not (source_root / rel).is_file() or file_digest(source_root / rel) != sha]
        report["source_differs_from_current"] = differing
        if differing:
            report["integrity_problems"].append("saved source differs from requested current source")
        compiler = source_root / "scripts/compile_wofost_observed_oracle.py"
        if compiler.is_file() and provenance.get("compiler_sha256") and provenance["compiler_sha256"] != file_digest(compiler):
            report["integrity_problems"].append("compiler source hash mismatch")
    if provenance.get("production_source_sha256") and provenance["production_source_sha256"] != digest(before):
        report["integrity_problems"].append("production source provenance digest mismatch")
    if "config.json" in evidence and evidence["config.json"] != provenance.get("wofost_config"):
        report["integrity_problems"].append("config differs from provenance")
    original = evidence.get("original_workflow.json")
    if original is not None and provenance.get("raw_workflow_sha256") != digest(original):
        report["integrity_problems"].append("original workflow hash mismatch")
    observed, replay = evidence.get("observed_workflow.json"), evidence.get("fresh_replay.json")
    trace = evidence.get("discovery_trace.json")
    if observed is not None and replay is not None:
        try:
            left, right = _steps(observed), _steps(replay)
            differences = []
            if [n for n, _ in left] != [n for n, _ in right]:
                differences.append("step identity/order differs")
            differences.extend(n for (n, a), (_, b) in zip(left, right) if trace_projection(a) != trace_projection(b))
            successful = [row for row in trace or [] if not row.get("discovery_only_rejected_guard")]
            if trace is None or [trace_projection(s) for _, s in left] != [trace_projection(s) for s in successful]:
                differences.append("saved workflow differs from actual successful discovery trace")
            report["replay"] = {"status": "pass" if not differences else "fail", "differences": differences,
                                "steps": len(left), "discovery_rejected_guards": len(trace or []) - len(successful)}
        except ValueError as exc:
            report["replay"] = {"status": "fail", "differences": [str(exc)]}
    else:
        report["replay"] = {"status": "missing"}
    first, second = evidence.get("discovery_final_snapshot.json"), evidence.get("replay_final_snapshot.json")
    if first is not None and second is not None:
        report["physical_snapshot_equality"] = normalize(first) == normalize(second)
        for label, value in (("discovery", first), ("replay", second)):
            if summary.get(f"{label}_state_hash") != digest(value):
                report["integrity_problems"].append(f"{label} physical snapshot hash mismatch")
        if not report["physical_snapshot_equality"]:
            report["integrity_problems"].append("discovery/replay physical snapshots differ")
        for farm in second.get("farms", {}).values():
            config = (farm.get("native_backend") or {}).get("config", {})
            if any(config.get(key) != value for key, value in evidence.get("config.json", {}).items()):
                report["integrity_problems"].append("explicit configuration differs from final native backend")
        try:
            operation = verify_operations(replay, second, evidence.get("initial_snapshot.json")) if replay else {"pass": False, "problems": ["workflow missing"]}
            report["operational"] = {"status": "pass" if operation["pass"] else "fail", **operation}
        except (ValueError, KeyError, TypeError) as exc:
            report["operational"] = {"status": "fail", "problems": [str(exc)]}
    else:
        report["physical_snapshot_equality"] = None
        report["operational"] = {"status": "blocked" if summary.get("completion") == "model_unsupported" else "missing",
                                 "reason": summary.get("message", "independent final snapshots missing")}
    if (case_dir / "case_review.json").is_file():
        try:
            review = load(case_dir / "case_review.json")
        except (ValueError, OSError) as exc:
            review = None
            report["integrity_problems"].append(f"case_review.json: {exc}")
    else:
        review = None
    report["management_review"] = verify_review(review, sid, original)
    if provenance.get("review_sha256") and digest(review) != provenance["review_sha256"]:
        report["integrity_problems"].append("case review differs from executed provenance")
    review_source = (review or {}).get("source", {})
    if review_source.get("path") and review_source.get("current_sha256") and before:
        if before.get(review_source["path"]) != review_source["current_sha256"]:
            report["integrity_problems"].append("case review source version differs from executed source")
    mechanisms = (review or {}).get("native_mechanisms")
    if not isinstance(mechanisms, list) or not mechanisms:
        report["native_support"] = {"status": "not_assessed", "mechanisms": []}
    else:
        valid = all(m.get("name") and m.get("basis") and m.get("status") in
                    {"supported", "empirical_proxy", "unsupported"} for m in mechanisms)
        report["native_support"] = {"status": "invalid" if not valid else
                                    "unsupported_present" if any(m["status"] == "unsupported" for m in mechanisms) else
                                    "empirical_proxy_present" if any(m["status"] == "empirical_proxy" for m in mechanisms) else "supported",
                                    "mechanisms": mechanisms}
    report["initial_state_digest"] = digest(evidence["initial_snapshot.json"]) if "initial_snapshot.json" in evidence else None
    report["evidence_integrity_pass"] = not report["missing_files"] and not report["integrity_problems"]
    report["operational_verified"] = (report["evidence_integrity_pass"] and report["replay"]["status"] == "pass"
                                       and report["physical_snapshot_equality"] is True
                                       and report["operational"]["status"] == "pass")
    block_kind = None
    message = str(driver_summary.get("message", ""))
    if "new native season" in message or "rotations/replanting" in message:
        block_kind = "native_replant_lifecycle_unsupported"
    elif "catchment/run-on" in message or "NOTINF" in message:
        block_kind = "native_catchment_soil_mapping_unsupported"
    common_present = all(name in evidence for name in
                         ("provenance.json", "source_before.json", "source_after.json", "config.json", "original_workflow.json"))
    recorded_block = bool(block_kind and driver_summary.get("exception_type") and driver_summary.get("traceback")
                          and common_present and not report["integrity_problems"]
                          and report["source_unchanged_during_run"]
                          and report["management_review"]["status"] in {"source_reviewed", "reviewed"}
                          and report["native_support"]["status"] == "unsupported_present")
    report["recorded_model_block"] = {"status": "recorded_model_block_not_replay_verified" if recorded_block else "not_verified",
                                      "kind": block_kind, "message": message if block_kind else None}
    if recorded_block and not report["operational_verified"]:
        report["operational"]["status"] = "blocked"
    report["conclusion_record_integrity_pass"] = report["operational_verified"] or recorded_block
    report["artifact_sha256"] = {str(path.relative_to(case_dir)): file_digest(path) for path in paths.values() if path.is_file()}
    return report


def matched_comparison(baseline, candidate, removed_step_ids=(), modified_step_ids=()):
    """Check common absolute schedule; never infer causal control from yield alone."""
    removed, modified = set(removed_step_ids), set(modified_step_ids)
    a, b = dict(_steps(baseline)), dict(_steps(candidate))
    issues = []
    if not removed and not modified:
        issues.append("no declared intervention")
    if not (removed | modified) <= set(a):
        issues.append("declared intervention step absent from baseline")
    for name in removed:
        replacement = b.get(name)
        if replacement is not None and (method(replacement) != "get_current_time"
                                         or replacement.get("tool_args")
                                         or any(replacement.get(key) != a[name].get(key) for key in ("time_before", "time_after"))):
            issues.append(f"removed step {name} replaced by an active operation or different clock interval")
    unchanged_a = [(n, {k: step.get(k) for k in ("tool_name", "tool_args", "time_before", "time_after")})
                   for n, step in a.items() if n not in removed | modified]
    unchanged_b = [(n, {k: step.get(k) for k in ("tool_name", "tool_args", "time_before", "time_after")})
                   for n, step in b.items() if n not in removed | modified]
    if unchanged_a != unchanged_b:
        issues.append("other tool/arguments/absolute times changed")
    for name in modified:
        if name not in b:
            issues.append(f"modified step {name} absent from candidate")
            continue
        if any(a[name].get(k) != b[name].get(k) for k in ("tool_name", "time_before", "time_after")):
            issues.append(f"modified step {name} changed tool or absolute time")
        if a[name].get("tool_args") == b[name].get("tool_args"):
            issues.append(f"modified step {name} has no changed arguments")
    return {"pass": not issues, "problems": issues}


def verify_trial_arm(directory: Path, reference_initial_hash):
    """Verify a driver's intervention arm independently of its reference case."""
    summary = load(directory / "summary.json")
    initial = load(directory / "initial_snapshot.json")
    plan = load(directory / "workflow.json")
    problems = []
    if digest(initial) != reference_initial_hash:
        problems.append("initial physical state differs from reference")
    if not (directory / "replay.json").is_file() or not (directory / "final_snapshot.json").is_file():
        return {"status": "recorded_infeasible_not_replay_verified" if summary.get("exception_type")
                and summary.get("traceback") and not problems else "invalid", "problems": problems,
                "producer_exception": summary.get("message"), "plan": plan, "operational_verified": False}
    replay, final = load(directory / "replay.json"), load(directory / "final_snapshot.json")
    submitted, executed = _steps(plan), _steps(replay)
    fields = ("tool_name", "tool_args", "time_before", "time_after")
    if [n for n, _ in submitted] != [n for n, _ in executed] or any(
        {k: a.get(k) for k in fields} != {k: b.get(k) for k in fields}
        for (_, a), (_, b) in zip(submitted, executed)
    ):
        problems.append("executed tool/arguments/absolute schedule differs from submitted arm")
    for key, value in (("initial_hash", initial), ("final_hash", final),
                       ("workflow_sha256", plan), ("actual_replay_sha256", replay)):
        if summary.get(key) != digest(value):
            problems.append(key + " mismatch")
    operation = verify_operations(replay, final, initial)
    if not operation["pass"]:
        problems.append("arm did not independently complete mature harvest and safe storage")
    return {"status": "verified" if not problems else "invalid", "problems": problems,
            "operational_verified": not problems, "plan": plan, "replay": replay, "final": final,
            "safe_stored_kg": sum(f["safe_stored_kg"] for f in operation["farms"].values()),
            "native_dry_grain_kg": sum(f["native_dry_grain_kg"] for f in operation["farms"].values()
                                        if numeric(f.get("native_dry_grain_kg")))}


def _driver_ablations(case_dir, manifest):
    baseline_dir = case_dir / manifest["baseline_dir"]
    baseline_plan = load(baseline_dir / "observed_workflow.json")
    initial_hash = digest(load(baseline_dir / "initial_snapshot.json"))
    baseline_replay = load(baseline_dir / "fresh_replay.json")
    baseline_final = load(baseline_dir / "replay_final_snapshot.json")
    baseline_operations = verify_operations(baseline_replay, baseline_final, load(baseline_dir / "initial_snapshot.json"))
    base_mass = sum(f["safe_stored_kg"] for f in baseline_operations["farms"].values())
    results, arms = [], {"reference": {"plan": baseline_plan, "replay": baseline_replay,
                                      "final": baseline_final, "safe_stored_kg": base_mass,
                                      "operational_verified": baseline_operations["pass"]}}
    for row in manifest["trials"]:
        result = {"name": row.get("id"), "candidate_kind": row.get("candidate_kind")}
        try:
            arm = verify_trial_arm(case_dir / row["candidate_dir"], initial_hash)
            removed = row.get("removed_step_ids", [])
            modified = list(set(row.get("changed_step_ids", [])) - set(removed))
            match = matched_comparison(baseline_plan, arm["plan"], removed, modified)
            result.update({key: value for key, value in arm.items() if key not in {"plan", "replay", "final"}})
            result["problems"].extend(match["problems"])
            if not baseline_operations["pass"]:
                result["problems"].append("reference arm did not independently complete")
            if result["problems"]:
                result["status"] = "invalid"
            elif arm["operational_verified"]:
                result["status"] = "verified_matched_experiment"
            arms[row["id"]] = arm
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result.update(status="invalid", problems=[str(exc)])
        results.append(result)
    selected_report = {"status": "not_executed"}
    if (case_dir / "selected/summary.json").is_file():
        selected_report = {"status": "invalid", "problems": []}
        try:
            selected = verify_trial_arm(case_dir / "selected", initial_hash)
            selected_id = load(case_dir / "summary.json").get("calibration", {}).get("selected_id")
            best = arms.get(selected_id)
            if not selected["operational_verified"] or not best or not best.get("operational_verified"):
                selected_report["problems"].append("selected arm or its declared original candidate is not verified")
            else:
                expected = load(case_dir / "selected/expected_replay.json")
                for label, left, right in (("fresh tool trace", selected["replay"], expected),
                                           ("candidate expected trace", best["replay"], expected),
                                           ("fresh final physical state", selected["final"], best["final"])):
                    if normalize(left) != normalize(right):
                        selected_report["problems"].append(label + " differs")
                maximum = max(arm["safe_stored_kg"] for arm in arms.values() if arm.get("operational_verified"))
                tolerance = load(case_dir / "summary.json").get("calibration", {}).get("yield_equivalence_tolerance_kg")
                if not numeric(tolerance) or tolerance < 0:
                    selected_report["problems"].append("yield equivalence tolerance missing/invalid")
                elif selected["safe_stored_kg"] < maximum - tolerance - 1e-9:
                    selected_report["problems"].append("selected yield is below the best verified tested candidate beyond tolerance")
                selected_report.update(selected_id=selected_id, selected_safe_stored_kg=selected["safe_stored_kg"],
                                       maximum_verified_tested_safe_stored_kg=maximum,
                                       yield_equivalence_tolerance_kg=tolerance)
            selected_report["problems"].extend(selected["problems"])
            if not selected_report["problems"]:
                selected_report["status"] = "fresh_selected_candidate_verified"
        except (OSError, ValueError, KeyError, TypeError) as exc:
            selected_report["problems"].append(str(exc))
    valid_count = sum(r["status"] == "verified_matched_experiment" for r in results)
    invalid_count = sum(r["status"] == "invalid" for r in results)
    return {"status": "invalid" if invalid_count or selected_report["status"] == "invalid" else
            "verified" if valid_count else "not_tested", "experiments": results,
            "verified_matched_count": valid_count,
            "recorded_infeasible_count": sum(r["status"] == "recorded_infeasible_not_replay_verified" for r in results),
            "selected_candidate": selected_report,
            "interpretation": "Bounded local interventions at matched times; no global optimum or field-efficacy calibration claim."}


def verify_ablations(case_dir: Path):
    path = case_dir / "ablations/manifest.json"
    if not path.is_file():
        return {"status": "not_tested", "experiments": []}
    manifest = load(path)
    if isinstance(manifest, dict) and "trials" in manifest:
        result = _driver_ablations(case_dir, manifest)
        if (case_dir / "source_before.json").is_file() and (case_dir / "source_after.json").is_file():
            unchanged = load(case_dir / "source_before.json") == load(case_dir / "source_after.json")
            result["production_source_unchanged_during_case"] = unchanged
            if not unchanged:
                result["status_before_source_check"] = result["status"]
                result["status"] = "provisional_source_changed"
                selected = result.get("selected_candidate", {})
                if selected.get("status") == "fresh_selected_candidate_verified":
                    selected["status"] = "fresh_selected_candidate_verified_provisional_source"
        return result
    rows = manifest if isinstance(manifest, list) else manifest.get("experiments", [])
    results = []
    for row in rows:
        experiment = {"name": row.get("name"), "problems": []}
        try:
            base, candidate = case_dir / row["baseline_dir"], case_dir / row["candidate_dir"]
            sid = load(base / "summary.json")["scenario_id"]
            a, b = verify_case(base, sid), verify_case(candidate, sid)
            if not a["operational_verified"] or not b["operational_verified"]:
                experiment["problems"].append("both arms must independently pass replay and operational checks")
            if not a["initial_state_digest"] or a["initial_state_digest"] != b["initial_state_digest"]:
                experiment["problems"].append("initial physical states differ or are missing")
            if load(base / "config.json") != load(candidate / "config.json") or a["frozen_source_digest"] != b["frozen_source_digest"]:
                experiment["problems"].append("source/config differs between arms")
            matching = matched_comparison(load(base / "observed_workflow.json"), load(candidate / "observed_workflow.json"),
                                          row.get("removed_step_ids", []), row.get("modified_step_ids", []))
            experiment["problems"].extend(matching["problems"])
            experiment["native_dry_grain_kg"] = {
                label: sum(f["native_dry_grain_kg"] for f in report.get("operational", {}).get("farms", {}).values()
                           if numeric(f.get("native_dry_grain_kg")))
                for label, report in (("baseline", a), ("candidate", b))}
            experiment["safe_stored_kg"] = {label: sum(f["safe_stored_kg"] for f in report.get("operational", {}).get("farms", {}).values())
                                             for label, report in (("baseline", a), ("candidate", b))}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            experiment["problems"].append(str(exc))
        experiment["status"] = "verified_matched_experiment" if not experiment["problems"] else "invalid"
        results.append(experiment)
    return {"status": "verified" if results and all(r["status"] == "verified_matched_experiment" for r in results)
            else "invalid", "experiments": results,
            "interpretation": "A matched local comparison does not prove a global optimum or field-calibrated efficacy."}


def discover_cases(root: Path, expected, manifest_path: Path | None = None):
    if manifest_path is None and (root / "manifest.json").is_file():
        manifest_path = root / "manifest.json"
    if manifest_path is not None:
        manifest = load(manifest_path)
        rows = manifest.get("cases", {})
        if isinstance(rows, dict):
            rows = [{"scenario_id": key, "case_dir": value.get("case_dir") if isinstance(value, dict) else value}
                    for key, value in rows.items()]
    else:
        rows = []
        for summary in sorted(root.rglob("summary.json")):
            # Experiment arms are subordinate evidence, not duplicate main cases.
            if "ablations" in summary.relative_to(root).parts:
                continue
            value = load(summary)
            if value.get("scenario_id") in expected:
                rows.append({"scenario_id": value["scenario_id"], "case_dir": str(summary.parent.relative_to(root))})
    result, duplicate = {}, []
    for row in rows:
        sid = row.get("scenario_id")
        if sid in result:
            duplicate.append(sid)
        result[sid] = root / row["case_dir"]
    return result, sorted(set(duplicate))


def verify_batch(root: Path, expected, *, manifest_path=None, source_root=None):
    found, duplicate = discover_cases(root, set(expected), manifest_path)
    cases = []
    for sid in expected:
        if sid not in found:
            continue
        report = verify_case(found[sid], sid, source_root=source_root)
        try:
            report["ablation_evidence"] = verify_ablations(found[sid])
        except (OSError, ValueError, TypeError) as exc:
            report["ablation_evidence"] = {"status": "invalid", "problems": [str(exc)]}
        cases.append(report)
    missing, extra = sorted(set(expected) - set(found)), sorted(set(found) - set(expected))
    source_sets = {case["frozen_source_digest"] for case in cases if case.get("frozen_source_digest")}
    return {"verifier_schema": 1, "output_root": str(root), "expected_count": len(expected),
            "concluded_case_count": len(cases), "missing_ids": missing, "extra_ids": extra,
            "duplicate_ids": duplicate, "same_frozen_production_source": len(source_sets) == 1,
            "all_ids_have_conclusion": not missing and not extra and not duplicate,
            "operational_verified_count": sum(case["operational_verified"] for case in cases),
            "management_reviewed_count": sum(case["management_review"]["status"] in {"reviewed", "source_reviewed"} for case in cases),
            "ablation_verified_case_count": sum(case["ablation_evidence"]["status"] == "verified" for case in cases),
            "fresh_selected_candidate_verified_count": sum(case["ablation_evidence"].get("selected_candidate", {}).get("status")
                                                            == "fresh_selected_candidate_verified" for case in cases),
            "recorded_model_block_count": sum(case["recorded_model_block"]["status"] == "recorded_model_block_not_replay_verified" for case in cases),
            "native_scope_distribution": dict(Counter(case["native_support"]["status"] for case in cases)),
            "evidence_integrity_pass": (not missing and not extra and not duplicate and len(source_sets) == 1
                                         and all(case["evidence_integrity_pass"] for case in cases)),
            "all_operationally_verified": len(cases) == len(expected) and not duplicate and not extra
                                          and all(case["operational_verified"] for case in cases),
            "all_conclusions_have_sufficient_saved_evidence": not missing and not extra and not duplicate
                and len(source_sets) == 1 and all(case["conclusion_record_integrity_pass"] for case in cases),
            "cases": cases,
            "scope": "Independent saved-evidence checks; no claim of field cultivar/efficacy calibration or globally maximal yield."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--scenario-ids", type=Path,
                        default=Path(__file__).resolve().parent / "fullseason/formal_90_scenario_ids.txt")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--require-all-operational", action="store_true")
    args = parser.parse_args(argv)
    expected = [line.strip() for line in args.scenario_ids.read_text().splitlines() if line.strip() and not line.startswith("#")]
    if len(expected) != len(set(expected)):
        parser.error("scenario IDs contain duplicates")
    report = verify_batch(args.output_root.resolve(), expected, manifest_path=args.manifest, source_root=args.source_root)
    destination = args.report or args.output_root / "independent_verification.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, ensure_ascii=False))
    return 0 if report["all_conclusions_have_sufficient_saved_evidence"] and (not args.require_all_operational or report["all_operationally_verified"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
