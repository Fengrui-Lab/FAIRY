"""Build a provenance-aware report from formal90 calibration evidence.

This is a read-only consumer of model/run evidence. It writes reports and copies
verified complete workflows; it never runs or changes a crop model or selects
an unexecuted experiment. Usage: --output-root <completed batch directory>.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import csv
import hashlib
import json
from pathlib import Path
import shutil
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Shanghai")
METHODS = {"apply_fertigation", "apply_fertilizer", "irrigate", "irrigate_range", "irrigate_ridge", "apply_fungicide", "spray_pesticide", "apply_herbicide", "apply_pesticide", "apply_pesticide_manual", "mechanical_weed_control", "replant_seeds", "incorporate_residue"}
UUID_FIELDS = {"op_id", "mission_id", "inspection_id", "action_id"}


def load(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalize(value):
    if isinstance(value, dict):
        return {k: "<ID>" if k in UUID_FIELDS else normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return value


def exact_replay(expected, actual):
    if expected is None or actual is None or list(expected) != list(actual):
        return False
    fields = ("tool_name", "tool_args", "content", "time_before", "time_after")
    return all(normalize({f: expected[n].get(f) for f in fields}) == normalize({f: actual[n].get(f) for f in fields}) for n in expected)


def supplemental_water_choice(case, primary_metrics, production_before, primary_verified):
    """Validate a separate water+schedule experiment before publishing it.

    This deliberately does not compare its timestamps with the primary plan:
    its longer real water delivery can shift all later operations. Fresh replay
    must instead exactly reproduce that new, explicitly saved schedule.
    """
    base = case / "supplemental_water_search"
    summary = load(base / "summary.json")
    if summary is None:
        return {"status": "not_executed", "publish_water_plan": False}
    selected = base / summary.get("selected_directory", "selected")
    evidence_names = ("initial_snapshot.json", "replay_initial_snapshot.json", "final_snapshot.json", "replay_final_snapshot.json", "expected_replay.json", "replay.json", "workflow.json")
    evidence = {name: load(selected / name) for name in evidence_names}
    initial_exact = bool(evidence["initial_snapshot.json"] is not None and evidence["replay_initial_snapshot.json"] is not None and digest(evidence["initial_snapshot.json"]) == digest(evidence["replay_initial_snapshot.json"]))
    primary_initial = load(case / "selected/initial_snapshot.json")
    initial_matches_primary = bool(primary_initial is not None and evidence["initial_snapshot.json"] is not None and digest(primary_initial) == digest(evidence["initial_snapshot.json"]))
    final_exact = bool(evidence["final_snapshot.json"] is not None and evidence["replay_final_snapshot.json"] is not None and digest(evidence["final_snapshot.json"]) == digest(evidence["replay_final_snapshot.json"]))
    trace_exact = exact_replay(evidence["expected_replay.json"], evidence["replay.json"])
    metrics = summary.get("selected_metrics", {})
    deadline = summary.get("deadline_timestamp")
    within_deadline = bool(deadline is not None and metrics.get("clock") is not None and float(metrics["clock"]) <= float(deadline))
    source_matches = bool(summary.get("production_source_matches") is True and production_before is not None and summary.get("production_source_sha256") == digest(production_before))
    primary_yield, candidate_yield = primary_metrics.get("safe_stored_kg"), metrics.get("safe_stored_kg")
    improved = bool(primary_yield is not None and candidate_yield is not None and candidate_yield > primary_yield + .1)
    verified = bool(primary_verified and summary.get("selected_verified") is True and metrics.get("operational_complete") is True and source_matches and initial_exact and initial_matches_primary and final_exact and trace_exact and within_deadline and evidence["workflow.json"] is not None)
    trials = []
    for trial in summary.get("trials", []):
        complete = trial.get("operational_complete") is True or trial.get("metrics", {}).get("operational_complete") is True
        trials.append({"id": trial.get("id"), "directory": str(base / trial.get("directory", "")), "changes": trial.get("changes", {}), "operational_complete": complete, "verified": trial.get("verified", False), "delta_safe_stored_kg": trial.get("delta_safe_stored_kg") if complete else None, "schedule_shift_seconds": trial.get("schedule_shift_seconds"), "comparison_kind": "water_and_schedule_plan_comparison_not_matched_time_dose_effect", "infeasible_partial_mass_is_not_a_yield_comparison": not complete})
    return {"status": summary.get("status"), "summary_path": str(base / "summary.json"), "comparison_kind": summary.get("comparison_kind"), "selected_id": summary.get("selected_id"), "selected_directory": str(selected), "selected_metrics": metrics, "selected_changes": load(selected / "changes.json", {}) or {}, "reported_selected_verified": summary.get("selected_verified"), "fresh_initial_exact": initial_exact, "initial_matches_primary": initial_matches_primary, "fresh_final_exact": final_exact, "fresh_tools_and_time_exact": trace_exact, "within_original_deadline": within_deadline, "production_source_matches": source_matches, "independently_verified": verified, "improves_primary_by_more_than_0_1kg": improved, "publish_water_plan": verified and improved, "selection_reason": summary.get("selection_reason"), "supplement_script_sha256": summary.get("supplement_script_sha256"), "trials": trials, "trial_count": len(trials), "attribution_limit": "2x the reference irrigation hours changes delivered water and real operation duration, so later plans can shift. This is a complete plan comparison under the original deadline/quotas, not a matched-time pure water-volume effect."}


def model_inputs(case, selected_directory):
    """Print actual per-ridge native specification, never profile prose defaults."""
    choices = [selected_directory / "replay_final_snapshot.json", selected_directory / "final_snapshot.json", case / "reference/replay_final_snapshot.json", case / "reference/discovery_final_snapshot.json"]
    snapshot_path = next((p for p in choices if p.is_file()), None)
    snapshot = load(snapshot_path, {}) if snapshot_path else {}
    groups = {}
    for farm, content in (snapshot or {}).get("farms", {}).items():
        for ridge, native in (content.get("native_backend") or {}).get("ridges", {}).items():
            spec = native.get("specification", {})
            soil, site, crop = (spec.get(k, {}) for k in ("soil_parameters", "site_parameters", "crop_parameters"))
            values = {"farm": farm, "seed_type": spec.get("seed_type"), "RDMSOL_cm": soil.get("RDMSOL"), "SMW": soil.get("SMW"), "SMFCF": soil.get("SMFCF"), "SM0": soil.get("SM0"), "NAVAILI_kg_N_ha": site.get("NAVAILI"), "NSOILBASE_kg_N_ha": site.get("NSOILBASE"), "NFIX_FR": crop.get("NFIX_FR")}
            key = digest(values)
            groups.setdefault(key, {**values, "ridge_ids": []})["ridge_ids"].append(int(ridge))
    for group in groups.values():
        ordered = sorted(group["ridge_ids"])
        spans = []
        for ridge in ordered:
            if spans and ridge == spans[-1][1] + 1:
                spans[-1][1] = ridge
            else:
                spans.append([ridge, ridge])
        group["ridge_ranges"] = spans
    return {"source_snapshot": str(snapshot_path) if snapshot_path else None, "source": "actual WofostBackend ridge specification soil/site/crop_parameters", "groups": list(groups.values()), "scope_note": "Profile background/validation prose does not override these actual scenario inputs. These soil values are not locally measured-soil calibrations. NAVAILI/NSOILBASE are native initial inputs, not final available N; NFIX_FR is demand-proportional fixation, not an independent nodulation-failure model."}


def runtime_capability_addendum(sid):
    """Post-run source review only; never rewrite frozen run configuration."""
    if sid == "scenario_full_season_hb_split_irrigation_schedule_power_limit":
        return [{"code": "independent_pump_power_or_energy_budget_not_modelled", "status": "unsupported", "basis": "SPEC management_regime contains irrigation_quota_mm_total=8 only; FieldOpsApp has no kW/kWh, electrical energy, pump power or simultaneous water-supply capacity budget", "validated_scope": "8mm field-equivalent water quota, actual serial irrigation operation time and original deadline", "not_established": "electric-power scheduling, energy feasibility or simultaneous pump capacity", "necessity_caveat": "本结果只验证8mm水额度、真实串行灌溉时间与原期限等已有约束；没有独立kW/kWh/泵功率或同时供水能力限制，不能称电力调度已校准。", "input_unchanged": True}]
    if sid == "scenario_full_season_hb_fuel_limit_irrigation_harvest_ops":
        return [{"code": "tractor_fuel_is_not_pump_energy_and_pass_counter_is_limited", "status": "partial", "basis": "SPEC declares tractor_fuel_l=260, irrigation_quota_mm_total=5 and max_machine_passes=36; physical fuel is tractor onboard/warehouse inventory, while check_machine_pass/record_machine_pass are called by mechanical weed control only", "validated_scope": "existing tractor fuel inventory,5mm water quota, actual tool times and any implemented mechanical-weeding pass limits", "not_established": "pump diesel/electric consumption, pump kW/kWh constraints or a universal36-pass budget across preparation/planting/spraying/harvest", "necessity_caveat": "本场拖拉机油料限制不等于水泵柴油或电耗预算；灌溉只验证水额度和已建模串行作业时间。max_machine_passes的当前计数入口仅机械除草，不能推断全部机作统一受36次限制。", "input_unchanged": True}]
    return []


def method(step):
    return (step.get("tool_name") or "").rsplit("__", 1)[-1]


def china_time(timestamp):
    return datetime.fromtimestamp(float(timestamp), TZ).isoformat() if timestamp is not None else None


def planned_timestamp(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return (parsed.replace(tzinfo=TZ) if parsed.tzinfo is None else parsed).timestamp()


def md(value):
    if value is None:
        return "未记录"
    def display(v):
        if isinstance(v, float):
            return float(f"{v:.8g}")
        if isinstance(v, dict):
            return {k: display(x) for k, x in v.items()}
        if isinstance(v, list):
            return [display(x) for x in v]
        return v
    if isinstance(value, (dict, list)):
        value = json.dumps(display(value), ensure_ascii=False, separators=(",", ":"))
    elif isinstance(value, float):
        value = f"{value:.8g}"
    return str(value).replace("|", "\\|").replace("\n", " ")


def link(label, path):
    target = str(Path(path).resolve())
    return f"[{label}](<{target}>)"


def dose(step, config):
    """Report actual API units, including manual multi-ridge operations."""
    if not step or method(step) not in METHODS:
        return None
    args = step.get("tool_args") or {}
    first = int(args.get("start_ridge", args.get("start", args.get("ridge_id", 0))))
    default_end = first + int(args.get("ridge_count", 1)) - 1
    last = int(args.get("end_ridge", args.get("end", default_end)))
    count = last - first + 1
    result = {"method": method(step), "ridge_range": [first, last], "target_ridges": count}
    if method(step) == "apply_fertigation":
        kg = float(args["nutrient_amount"]) * 30 * count
        result.update(product_kg=kg, nitrogen_kg=kg * float(config.get("fertilizer_n_fraction", .46)), carrier_water_mm_per_target_ridge=float(args.get("water_mm", 0)))
    elif method(step) == "apply_fertilizer":
        kg = float(args["kg_per_ridge"]) * count
        result.update(product_kg=kg, nitrogen_kg=kg * float(config.get("fertilizer_n_fraction", .46)))
    elif method(step).startswith("irrigat"):
        hours = float(args.get("hours", args.get("duration_hours", 0)))
        result.update(hours_per_target_ridge=hours, estimated_water_mm_per_target_ridge=hours * 5, irrigation_ridge_mm=hours * 5 * count)
    elif "liters_per_ridge" in args:
        result.update(working_fluid_l_per_ridge=float(args["liters_per_ridge"]), total_working_fluid_l=float(args["liters_per_ridge"]) * count)
    elif method(step) == "mechanical_weed_control":
        result["mechanical_ridge_passes"] = count
    return result


def stage_observations(workflow):
    """Associate each operation with the latest actually returned public stages."""
    observed, output = {}, {}
    for name, step in workflow.items():
        content = step.get("content") or {}
        if method(step) == "get_ridge_range_state" and isinstance(content, dict):
            for ridge in content.get("ridges", []):
                observed[int(ridge["ridge_id"])] = {"growth_stage": ridge.get("growth_stage"), "observed_at": step.get("time_after"), "observation_step": name}
        if method(step) in METHODS:
            args = step.get("tool_args") or {}
            first = int(args.get("start_ridge", args.get("start", args.get("ridge_id", 0))))
            last = int(args.get("end_ridge", args.get("end", first + int(args.get("ridge_count", 1)) - 1)))
            targets = [observed[r] for r in range(first, last + 1) if r in observed]
            output[name] = {"stage_counts": dict(Counter(r["growth_stage"] for r in targets)), "observed_target_ridges": len(targets), "expected_target_ridges": last - first + 1, "observation_steps": sorted({r["observation_step"] for r in targets}), "native_DVS": None, "native_DVS_note": "not collected at selected action; reference native audit is reported separately and is not substituted here"}
    return output


def audit_stage(record):
    before = (record or {}).get("before", {})
    values = [r.get("DVS") for r in before.get("native_audit_only", {}).values() if r.get("DVS") is not None]
    return {"stage_counts": before.get("stage_counts"), "native_DVS_range": [min(values), max(values)] if values else None, "native_data_use": "audit only; not policy input", "clock": before.get("clock"), "china_time": china_time(before.get("clock"))}


def trial_check(case, trial, reference, reference_initial_hash, source_stable):
    directory = case / trial.get("candidate_dir", trial.get("directory", ""))
    summary = load(directory / "summary.json", trial.get("metrics", {})) or {}
    initial = load(directory / "initial_snapshot.json")
    initial_exact = (digest(initial) == reference_initial_hash if initial is not None and reference_initial_hash is not None else None)
    replay = load(directory / "replay.json")
    changed = set(trial.get("changed_step_ids", trial.get("changes", {})))
    differences = []
    if replay is None:
        timing_exact = None
    else:
        if list(replay) != list(reference):
            differences.append({"kind": "step_order_or_coverage"})
        for name, expected in reference.items():
            actual = replay.get(name)
            if actual is None:
                continue
            for field in ("time_before", "time_after"):
                if actual.get(field) != expected.get(field):
                    differences.append({"step": name, "field": field, "reference": expected.get(field), "candidate": actual.get(field)})
            if name not in changed:
                for field in ("tool_name", "tool_args"):
                    if actual.get(field) != expected.get(field):
                        differences.append({"step": name, "field": field})
        timing_exact = not differences
    feasible = summary.get("operational_complete") is True
    attempted = bool((directory / "summary.json").is_file() or initial is not None or summary.get("wall_seconds") is not None)
    comparable = bool(source_stable and feasible and initial_exact is True and timing_exact is True)
    kind = trial.get("candidate_kind", "unknown")
    # A rejected planting or chemical-cap trial is a valid negative feasibility
    # result, not a lower-yield full season or a source-integrity failure.
    delta = trial.get("delta_safe_stored_kg") if feasible else None
    verdict = "executed_infeasible_under_original_constraints" if attempted else "not_executed"
    if feasible:
        verdict = "incomparable_initial_timing_or_source" if not comparable else "tested_candidate_comparable"
        if comparable and delta is not None and kind in {"omit", "joint_omission"}:
            verdict = "omission_noninferior_within_0_1kg_in_this_case" if delta >= -.1 else "omission_reduced_safe_yield_in_this_case"
    return {"trial_id": trial.get("id"), "candidate_kind": kind, "changed_step_ids": sorted(changed), "step_changes": trial.get("changes", {}), "candidate_directory": str(directory), "executed": attempted, "operational_complete": feasible, "feasibility": "feasible_fullseason" if feasible else "infeasible_candidate" if attempted else "not_executed", "constraint_rejections": summary.get("errors", [])[:8], "exception_or_rejection_message": summary.get("message"), "partial_stored_mass_not_a_complete_yield": summary.get("safe_stored_kg") if attempted and not feasible else None, "matched_initial_state": initial_exact, "matched_absolute_times_and_unchanged_tools": timing_exact, "timing_or_tool_differences_count": len(differences), "first_differences": differences[:5], "source_stable": source_stable, "attribution_valid_for_this_bounded_comparison": comparable, "delta_safe_stored_kg": delta, "delta_native_twso_mass_kg": trial.get("delta_native_twso_mass_kg") if feasible else None, "verdict": verdict, "attribution_limit": "Omitting fertigation changes fertilizer and carrier water together. Half irrigation changes water volume and intrinsic delivery-ready time even when the original start and all other tool epochs are matched. Joint dose/omission plans change several inputs together. None is automatically a pure single-input marginal effect."}


def action_reviews(review, original, reference, selected, trace, audits, trials, config, unsupported):
    reference_stages = stage_observations(reference)
    selected_stages = stage_observations(selected)
    by_label = {}
    for row in trace:
        if method(row) in METHODS:
            by_label.setdefault(row.get("source_label"), []).append(row)
    audit_by_label = {r.get("before", {}).get("source_label"): r for r in audits}
    result = []
    actions = review.get("planned_management_actions", [])
    if not actions:
        actions = [{"source_step": name, "tool_name": s.get("tool_name"), "original_arguments": s.get("tool_args"), "original_absolute_time": s.get("time")} for name, s in original.items() if method(s) in METHODS]
    for planned in actions:
        label = planned["source_step"]
        source = original.get(label, {"tool_name": planned.get("tool_name"), "tool_args": planned.get("original_arguments"), "time": planned.get("original_absolute_time")})
        actual = by_label.get(label, [])
        ids = [a["name"] for a in actual if a.get("name") in reference]
        # A rejected original action is absent from the executable reference but
        # still has its actual attempted stage in the audit file.
        audit = audit_by_label.get(label)
        reference_status = "not_reached"
        if actual:
            failed = any(isinstance(a.get("content"), dict) and a["content"].get("error") for a in actual)
            reference_status = "not_supported" if failed and method(source) == "replant_seeds" else "failed" if failed else "executed"
        status = "not_supported" if unsupported and method(source) == "replant_seeds" and actual else "not_reached"
        entries = []
        for name in ids:
            candidate = selected.get(name)
            if candidate is not None:
                entries.append({"step_id": name, "tool_name": candidate.get("tool_name"), "actual_arguments": candidate.get("tool_args"), "clock_before": candidate.get("time_before"), "clock_after": candidate.get("time_after"), "china_time": china_time(candidate.get("time_before")), "dose": dose(candidate, config), "public_stage_evidence": selected_stages.get(name)})
        parameter_status = "not_reached"
        timing_status = "not_reached"
        if entries:
            if all(method(selected[e["step_id"]]) not in METHODS for e in entries):
                status = parameter_status = "removed"
                timing_status = "matched_original_reference_epoch"
            else:
                args_changed = any(e["actual_arguments"] != source.get("tool_args") or e["tool_name"] != source.get("tool_name") for e in entries)
                parameter_status = "revised" if args_changed else "preserved"
                original_clock = planned_timestamp(source.get("time"))
                time_changed = original_clock is not None and any(e["clock_before"] != original_clock for e in entries)
                timing_status = "revised" if time_changed else "preserved"
                status = "revised" if args_changed or time_changed else "preserved"
        related = [t for t in trials if set(t["changed_step_ids"]) & set(ids)]
        necessity = ("bounded paired evidence only; successful tool return is not evidence that management was necessary" if any(t["attribution_valid_for_this_bounded_comparison"] for t in related) else "trials_executed_but_initial_time_or_source_not_comparable" if related else "no_executed_matched_intervention_comparison")
        gaps = {g["code"] for g in review.get("semantic_model_gaps", [])}
        caveats = []
        if method(source) in {"apply_fertigation", "apply_fertilizer"} and "nutrient_proxy_not_explicit_local_native_N_stock" in gaps:
            caveats.append("当前尚未建立源低肥/分区原生N库差异；删除不减产仅是当前模拟输入结果，不能证明原低肥任务中的追肥多余。")
        if "nodulation_failure_not_native_Nfix_intervention" in gaps:
            caveats.append("PCSE已有按氮需求比例固氮，当前参考档案NFIX_FR=0.8；缺口是源根瘤失效只降低营养代理，未接入NFIX_FR或独立根瘤状态，不能写成PCSE完全没有固氮。")
        if method(source) in {"apply_fungicide", "spray_pesticide", "apply_herbicide", "apply_pesticide_manual", "apply_pesticide", "mechanical_weed_control"}:
            caveats.append("收益限于FAIRY经验药效/病虫草压力及场景外部forcing；持续病虫事件可能逐日重新设压，不能外推为田间药效或WOFOST原生病理验证。")
        if method(source).startswith("irrigat"):
            caveats.append("半量hours同时改变供水量与固有delivery_ready时刻；其他调用绝对时刻相同也不构成纯水量独立效应。2x灌溉另属含作业顺延的计划比较。")
        for addendum in review.get("runtime_capability_addendum", []):
            caveats.append(addendum["necessity_caveat"])
        if related and not any(t["operational_complete"] for t in related):
            necessity = "only_infeasible_candidates_observed; rejection under original constraints is not a complete-yield comparison"
        if caveats:
            necessity += " | " + " ".join(caveats)
        result.append({"source_step": label, "original": {"tool_name": source.get("tool_name"), "arguments": source.get("tool_args"), "planned_china_time": source.get("time"), "dose": dose(source, config)}, "reference_execution": {"status": reference_status, "compiled_step_ids": ids, "audit": audit_stage(audit), "public_stage_evidence": {name: reference_stages.get(name) for name in ids}, "attempted_receipts": [{k: a.get(k) for k in ("name", "time_before", "time_after", "content")} for a in actual]}, "selected_disposition": status, "selected_parameter_disposition": parameter_status, "selected_timing_disposition": timing_status, "selected_actual_operations": entries, "matched_trials": [{k: t.get(k) for k in ("trial_id", "candidate_kind", "candidate_directory", "matched_initial_state", "matched_absolute_times_and_unchanged_tools", "attribution_valid_for_this_bounded_comparison", "delta_safe_stored_kg", "delta_native_twso_mass_kg", "verdict")} for t in related], "necessity_verdict": necessity, "necessity_scope_caveats": caveats, "model_mechanism_limits": sorted(gaps)})
    return result


def case_report(root, sid, case, review, scheduled):
    summary = load(case / "summary.json", {}) or {}
    original = load(case / "reference/original_workflow.json", {}) or {}
    config = load(case / "config.json", {}) or {}
    reference = load(case / "reference/fresh_replay.json", {}) or {}
    selected = load(case / "selected/replay.json", {}) or {}
    calibration = summary.get("calibration", {})
    reference_summary = summary.get("reference", load(case / "reference/summary.json", {}) or {})
    before, after = load(case / "source_before.json"), load(case / "source_after.json")
    stable = bool(before is not None and after is not None and before == after and not summary.get("source_changed_during_run"))
    unsupported = "new native season" in summary.get("message", "") or "rotations/replanting" in summary.get("message", "") or bool(load(case / "reference/calibration_block.json"))
    primary_verified = bool(stable and calibration.get("status") == "best_tested_candidate_fresh_replay_verified" and calibration.get("fresh_native_state_exact") is True and calibration.get("fresh_tool_trace_and_time_exact") is True and calibration.get("selected", {}).get("operational_complete") is True and selected)
    primary_metrics = calibration.get("selected", {})
    water = supplemental_water_choice(case, primary_metrics, before, primary_verified)
    selected_directory = case / "selected"
    selection_kind = "primary_bounded_matched_epoch_search"
    selected_metrics = primary_metrics
    selected_id = calibration.get("selected_id")
    state_exact = calibration.get("fresh_native_state_exact")
    trace_exact = calibration.get("fresh_tool_trace_and_time_exact")
    if water["publish_water_plan"]:
        selected_directory = Path(water["selected_directory"])
        selected = load(selected_directory / "replay.json", {}) or {}
        selected_metrics = water["selected_metrics"]
        selected_id = "supplemental_water:" + str(water.get("selected_id"))
        selection_kind = "supplemental_2x_water_and_schedule_plan_comparison"
        state_exact = water["fresh_final_exact"]
        trace_exact = water["fresh_tools_and_time_exact"]
    selected_verified = primary_verified and (water["independently_verified"] if water["publish_water_plan"] else True)
    reference_complete = reference_summary.get("completion") == "feasible_operational_reference"
    if not summary:
        status = "not_executed" if scheduled else "not_scheduled_in_this_manifest"
    elif unsupported:
        status = "native_replanting_unsupported"
    elif not stable:
        status = "provisional_or_missing_source_integrity"
    elif selected_verified:
        status = "calibrated_best_tested_candidate_verified"
    elif reference_complete and calibration.get("status") == "reference_only_experiments_not_executed":
        status = "reference_only_no_calibration_experiments"
    else:
        status = calibration.get("status", "requires_review")
    initial = load(case / "reference/initial_snapshot.json")
    initial_hash = digest(initial) if initial is not None else None
    manifest = load(case / "ablations/manifest.json", {}) or {}
    trials = [trial_check(case, t, reference, initial_hash, stable) for t in manifest.get("trials", [])]
    trace = load(case / "reference/discovery_trace.json", []) or []
    audits = load(case / "reference/management_actions_audit.json", []) or []
    addenda = runtime_capability_addendum(sid)
    action_review_context = {**review, "runtime_capability_addendum": addenda}
    actions = action_reviews(action_review_context, original, reference, selected, trace, audits, trials, config, unsupported)
    if water["publish_water_plan"]:
        for action in actions:
            restored = [step for step in action["reference_execution"]["compiled_step_ids"] if water.get("selected_changes", {}).get(step, {}).get("restores_primary_omission") is True]
            if restored:
                restoration_note = "原剂量及原时程下省去未显示超过0.1kg的损失；较高灌水剂量与时程组合有收益，因此最终恢复并改量。不能沿用primary把最终水管理标成多余或删除。"
                action["restored_from_primary_omission"] = restored
                action["necessity_scope_caveats"].append(restoration_note)
                action["necessity_verdict"] += " | " + restoration_note
            caveat = "最终工作流来自2x灌溉及后续时程一起改变的完整计划比较；本行matched_trials仍对应primary参考时刻下的候选，不是最终高水计划的单操作边际效应。"
            action["necessity_scope_caveats"].append(caveat)
            action["necessity_verdict"] += " | " + caveat
    original_labels = {a["source_step"] for a in actions}
    added_management = [
        {"source_label": r.get("source_label"), "compiled_step_id": r.get("name"),
         "tool_name": r.get("tool_name"), "arguments": r.get("tool_args"),
         "reference_china_time": china_time(r.get("time_before")),
         "reference_dose": dose(r, config),
         "selected_step": selected.get(r.get("name")),
         "reason_status": "new policy action; inspect changes.json for its declared reason"}
        for r in trace if method(r) in METHODS and r.get("source_label") not in original_labels
    ]
    timing = load(case / "reference/timing_policy_audit.json", []) or []
    late = [r for r in timing if r.get("outside_declared_latest_stage") is True]
    changes = load(case / "reference/changes.json", []) or []
    adjustment_counts = Counter(r.get("kind", "unknown") for r in changes)
    guard_rejections = load(case / "reference/discovery_rejected_guards.json", []) or []
    adaptation = review.get("runtime_adaptation")
    sowing = summary.get("sowing_comparison", {"status": "not_executed"})
    selected_yield = selected_metrics.get("safe_stored_kg")
    reference_yield = calibration.get("baseline", {}).get("safe_stored_kg", reference_summary.get("warehouse_grain_kg"))
    native_gap_count = len(review.get("semantic_model_gaps", []))
    exported, unsupported_export = None, None
    target = root / "calibrated_workflows" / f"{sid}.json"
    if selected_verified and (selected_directory / "workflow.json").is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(selected_directory / "workflow.json", target)
        exported = str(target)
    elif target.exists():
        target.unlink()  # Remove only this script's stale generated export.
    target_unsupported = root / "unsupported_original_workflows" / f"{sid}.json"
    if unsupported and original:
        target_unsupported.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(case / "reference/original_workflow.json", target_unsupported)
        unsupported_export = str(target_unsupported)
    elif target_unsupported.exists():
        target_unsupported.unlink()
    selected_doses = Counter(a["selected_disposition"] for a in actions)
    loaded_seeds = sorted({s.get("tool_args", {}).get("seed_type") for s in selected.values() if method(s) == "load_seeds" and s.get("tool_args", {}).get("seed_type")})
    row = {"scenario_id": sid, "case_directory": str(case), "status": status, "scheduled_in_manifest": scheduled, "summary_present": bool(summary), "source_stable": stable, "production_source_fingerprint": digest(before) if before is not None else None, "source_changed_during_run": summary.get("source_changed_during_run"), "reference_operational_complete": reference_complete, "selected_operational_complete": selected_metrics.get("operational_complete", False), "selected_fresh_state_exact": calibration.get("fresh_native_state_exact"), "selected_fresh_tools_and_time_exact": calibration.get("fresh_tool_trace_and_time_exact"), "selected_verified": selected_verified, "scenario_goal_status": summary.get("scenario_goal_status", "source_review_only_no_runtime_result"), "semantic_model_gap_count": native_gap_count, "semantic_model_gaps": review.get("semantic_model_gaps", []), "native_mechanisms": review.get("native_mechanisms", []), "runtime_adaptation": adaptation, "actual_loaded_seed_types": loaded_seeds, "profile_ids_for_loaded_seeds": {seed: config.get("cultivar_profiles", {}).get(seed, config.get("cultivar_profile") if seed == "HEINONG84" else None) for seed in loaded_seeds}, "reference_safe_stored_kg": reference_yield, "selected_safe_stored_kg": selected_yield, "selected_minus_reference_kg": selected_yield - reference_yield if selected_yield is not None and reference_yield is not None else None, "selected_id": calibration.get("selected_id"), "search_status": calibration.get("status", "not_executed"), "actual_trial_count": len(trials), "comparable_trial_count": sum(t["attribution_valid_for_this_bounded_comparison"] for t in trials), "failed_or_incomparable_trial_count": sum(not t["attribution_valid_for_this_bounded_comparison"] for t in trials), "action_count": len(actions), "selected_action_dispositions": dict(selected_doses), "late_window_risk_count": len(late), "late_window_risks": late, "policy_adjustment_counts": dict(adjustment_counts), "discovery_zero_mutation_rejections": len(guard_rejections), "sowing_comparison": sowing, "calibrated_workflow": exported, "unsupported_original_workflow": unsupported_export, "message": summary.get("message"), "report": str(case / "report.md"), "action_review": str(case / "action_review.json"), "reproduce_command": f"env -u USER .venv/bin/python scripts/calibrate_formal90_oracles.py --replay-case '{case}' --output-dir /tmp/formal90-replay-{sid}" if selected_verified else None}
    row["added_management_call_count"] = len(added_management)
    row["reproduce_command"] = row["reproduce_command"].replace("env -u USER .venv/bin/python", "env -u USER PYTHONHASHSEED=0 .venv/bin/python") if row["reproduce_command"] else None
    inputs = model_inputs(case, selected_directory)
    row["actual_native_model_inputs"] = inputs
    row["runtime_capability_addendum"] = addenda
    row["report_capability_addendum_count"] = len(addenda)
    row["mechanism_limits_count_including_report_addenda"] = native_gap_count + len(addenda)
    row["reported_scenario_goal_status"] = "report_level_capability_limit_added_to_original_source_review" if addenda else row["scenario_goal_status"]
    row.update({"selection_kind": selection_kind, "selected_directory": str(selected_directory), "selected_id": selected_id, "selected_fresh_state_exact": state_exact, "selected_fresh_tools_and_time_exact": trace_exact, "primary_selected_verified": primary_verified, "primary_selected_id": calibration.get("selected_id"), "primary_selected_safe_stored_kg": primary_metrics.get("safe_stored_kg"), "supplemental_water_search": water, "water_plan_trial_count": water.get("trial_count", 0), "infeasible_matched_trial_count": sum(t["executed"] and not t["operational_complete"] for t in trials), "feasible_but_unmatched_or_provisional_trial_count": sum(t["operational_complete"] and not t["attribution_valid_for_this_bounded_comparison"] for t in trials)})
    if water["publish_water_plan"]:
        row["reproduce_command"] = f"env -u USER PYTHONHASHSEED=0 .venv/bin/python scripts/extend_formal90_water_search.py --replay-case '{case}' --output-dir /tmp/formal90-water-replay-{sid}"
    save(case / "action_review.json", {"scenario_id": sid, "scope": "original management calls -> reference actual audit -> selected actual replay; native DVS is audit-only", "selected_verification_status": status, "selection_kind": selection_kind, "actual_native_model_inputs": inputs, "runtime_capability_addendum": addenda, "frozen_case_review_unchanged": True, "actions": actions, "added_management_calls": added_management, "matched_trial_checks": trials, "supplemental_water_search": water, "late_window_risks": late, "policy_changes": changes, "zero_mutation_rejections_evidence": str(case / "reference/discovery_rejected_guards.json"), "sowing_comparison": sowing})
    text = [f"# {sid}", "", review.get("case_specific_review", "该ID尚无逐场源码复核信息。"), "", "| 判断轴 | 结果 |", "|---|---|", f"| 当前证据状态 | `{status}` |", f"| 修订参考全季操作完成 | {reference_complete} |", f"| 选定候选全季操作完成 | {selected_metrics.get('operational_complete', False)} |", f"| 选定候选状态/工具/时钟鲜场景重放 | {calibration.get('fresh_native_state_exact')} / {calibration.get('fresh_tool_trace_and_time_exact')} |", f"| 原场景机制边界 | {md(row['scenario_goal_status'])}；{native_gap_count}项明确缺口 |", f"| 实际候选试验/可归因配对 | {len(trials)} / {row['comparable_trial_count']} |", f"| 参考 / 选定安全入库kg | {md(reference_yield)} / {md(selected_yield)} |", f"| 源码和数据运行期间保持一致 | {stable} |", ""]
    if summary.get("message"):
        text += ["运行信息：" + md(summary["message"]), ""]
    text += [f"最终发布层：`{selection_kind}`；primary选定入库 {md(primary_metrics.get('safe_stored_kg'))} kg，最终发布入库 {md(selected_yield)} kg。primary匹配试验中，不可行候选 {row['infeasible_matched_trial_count']}，可行但初态/时程/源码未匹配 {row['feasible_but_unmatched_or_provisional_trial_count']}，二者分列。不可行候选的部分收获/入库质量不用于全季产量比较。", ""]
    if adaptation:
        text += ["## 显式场景适应变体", "", md(adaptation.get("reason")), "", md(adaptation.get("original_goal_change")), "", "该变体保留原始控制证据，不计作原固定品种或原未解释水文假设已获验证。", ""]
        text += [f"- [{md(s.get('title', '依据'))}]({s['url']})" for s in adaptation.get("sources", []) if s.get("url")]
        text += [""]
    text += ["## 实际原生模型输入", "", "以下取实际每垄WOFOST specification，按相同输入分组；品种档案的背景/校验文字不覆盖本场输入。本轮未做本地测土标定。NAVAILI/NSOILBASE是初始N输入，不是季末可用N。", "", "| 农场/垄区 | 实际种子 | RDMSOL(cm) | SMW / SMFCF / SM0 | NAVAILI / NSOILBASE(kg N/ha) | NFIX_FR |", "|---|---|---:|---|---|---:|"]
    for group in inputs["groups"]:
        text.append(f"| {md(group['farm'])} / {md(group['ridge_ranges'])} | {md(group['seed_type'])} | {md(group['RDMSOL_cm'])} | {md([group['SMW'],group['SMFCF'],group['SM0']])} | {md([group['NAVAILI_kg_N_ha'],group['NSOILBASE_kg_N_ha']])} | {md(group['NFIX_FR'])} |")
    text += ["", link("实际输入所在快照", inputs["source_snapshot"]) if inputs["source_snapshot"] else "本例尚未创建可读取的原生垄模型，不用档案背景补造实际土壤输入。", ""]
    text += ["## 逐原管理调用", "", "原计划时刻、参考执行时刻和选定候选时刻分别报告。参考DVS来自实际审计；选定候选没有采集同位置DVS时明确留空。`not_reached`表示未取得选定执行证据，不抹去已经执行的参考记录。", "", "| 原节点 | 原参数/时刻 | 参考阶段/DVS/时刻 | 选定状态/实际剂量 | 配对试验 | 必要性判断的模型边界 |", "|---|---|---|---|---|---|"]
    for action in actions:
        original_cell = md(action["original"]["arguments"]) + "；" + md(action["original"]["planned_china_time"])
        evidence = action["reference_execution"]["audit"]
        actual_cell = md(evidence.get("stage_counts")) + " / " + md(evidence.get("native_DVS_range")) + "；" + md(evidence.get("china_time"))
        actual_cell += "；" + action["reference_execution"]["status"]
        selected_cell = action["selected_disposition"] + "；" + md([e["dose"] for e in action["selected_actual_operations"]])
        trial_links = "；".join(link(f"{t['trial_id']} Δ={md(t['delta_safe_stored_kg'])} {'可归因' if t['attribution_valid_for_this_bounded_comparison'] else '不可归因'}", Path(t["candidate_directory"]) / "summary.json") for t in action["matched_trials"]) or "未执行匹配试验"
        text.append(f"| `{action['source_step']}` | {original_cell} | {actual_cell} | {selected_cell} | {trial_links} | {md(action['necessity_scope_caveats']) if action['necessity_scope_caveats'] else '仅限实际匹配候选集合，不以工具成功证明必要'} |")
    text += ["", "完整参数、原始响应、选定候选公开阶段证据及归因检查见 " + link("action_review.json", case / "action_review.json") + "。", "", "## 时机与执行修改", "", md(dict(adjustment_counts)), "", f"晚窗口风险：{len(late)}；零副作用拒绝另存：{len(guard_rejections)}。补种失败保留；种子补载只转移已有库存，航测/机器人覆盖与充电检查不等于新增农事投入必要性。", "", link("全部时机审计", case / "reference/timing_policy_audit.json") + "；" + link("全部修改", case / "reference/changes.json"), "", "## 原任务机制边界", ""]
    text += [f"- `{g['code']}`：{md(g.get('basis'))}；{md(g.get('treatment'))}" for g in review.get("semantic_model_gaps", [])] or ["逐场源码复核未另列特定缺口；这不构成田间校准证明。"]
    if addenda:
        text += ["", "## 运行后能力补查（不改变冻结输入）", "", "本节独立补充源码能力口径，不改原case_review、配置或运行参数。", "", "| 机制 | 支持状态 | 本轮实际验证范围 | 未建立的能力 |", "|---|---|---|---|"]
        text += [f"| `{a['code']}` | {a['status']} | {md(a['validated_scope'])} | {md(a['not_established'])} |" for a in addenda]
        text += ["", " ".join(a["necessity_caveat"] for a in addenda), ""]
    text += ["", "## 播种参数独立诊断", "", md(sowing), "", "播距候选是另跑的公开密度参考诊断，不是匹配时刻的单一密度因果试验，也不会自动替换正式工作流。当前原生密度仅缩放TDWI，不能据其增产选择最优密度。", ""]
    text += ["## 附加高水量与作业时程计划比较", "", md(water), "", "本层尝试原reference灌溉hours的2倍，实际水量和作业时间同时增加，后续计划允许依法顺延；原期限、库存和配额仍不变。只有完整可行、鲜场景初终态与工具时钟一致、且比primary增益超过0.1kg的候选才取代primary。此层不作matched-time纯水量归因，primary证据与工作流始终保留。", ""]
    if exported:
        text += ["## 完整可执行候选", "", link("本场完整工作流", exported), "", "```bash", row["reproduce_command"], "```", "", "回放入口会检查已保存的代码与数据指纹；不匹配时应重新校准，不能继续声称精确复现。", ""]
    elif unsupported_export:
        text += ["## 保留的未支持原流程", "", link("原始完整工作流（非校准成功）", unsupported_export), ""]
    else:
        text += ["没有满足冻结源码、已执行选择及鲜场景验证条件的完整校准工作流导出。", ""]
    (case / "report.md").write_text("\n".join(text))
    return row


def build(output_root):
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    ids = [s for s in (ROOT / "scripts/fullseason/formal_90_scenario_ids.txt").read_text().splitlines() if s]
    reviews = {r["scenario_id"]: r for r in load(ROOT / "configs/oracles/formal90_review_v1.json", {})["rows"]}
    manifest = load(root / "manifest.json", {}) or {}
    case_dirs = {r["scenario_id"]: root / r["case_dir"] for r in manifest.get("cases", [])}
    if not manifest or not isinstance(manifest.get("cases"), list):
        raise ValueError("--output-root must be a batch directory with manifest.json/cases; refusing to overwrite a single-case summary.json")
    rows = []
    for sid in ids:
        case = case_dirs.get(sid, root / "cases" / sid)
        review = load(case / "case_review.json", reviews[sid]) or reviews[sid]
        rows.append(case_report(root, sid, case, review, sid in case_dirs))
    counts = Counter(r["status"] for r in rows)
    selected_counts = Counter()
    for row in rows:
        selected_counts.update(row["selected_action_dispositions"])
    aggregate = {"formal_scenario_count": len(ids), "manifest_scenario_count": len(case_dirs), "case_summary_count": sum(r["summary_present"] for r in rows), "status_counts": dict(counts), "verified_selected_workflow_count": sum(r["selected_verified"] for r in rows), "unsupported_original_workflow_count": sum(bool(r["unsupported_original_workflow"]) for r in rows), "source_stable_case_count": sum(r["source_stable"] for r in rows), "distinct_saved_production_fingerprints": len({r["production_source_fingerprint"] for r in rows if r["production_source_fingerprint"]}), "original_management_call_count": sum(r["action_count"] for r in rows), "selected_action_disposition_counts": dict(selected_counts), "actual_matched_trial_count": sum(r["actual_trial_count"] for r in rows), "comparable_trial_count": sum(r["comparable_trial_count"] for r in rows), "runtime_adaptation_case_count": sum(bool(r["runtime_adaptation"]) for r in rows), "late_window_risk_count": sum(r["late_window_risk_count"] for r in rows), "sowing_alternative_executed_count": sum(r["sowing_comparison"].get("status") == "published_density_alternative_fresh_replayed" for r in rows), "precision": "Operational completion, original mechanism coverage, tested bounded search and field calibration are distinct. Missing/unexecuted experiments never count as passed."}
    aggregate.update({"infeasible_matched_trial_count": sum(r["infeasible_matched_trial_count"] for r in rows), "feasible_but_unmatched_or_provisional_trial_count": sum(r["feasible_but_unmatched_or_provisional_trial_count"] for r in rows), "supplemental_water_search_executed_case_count": sum(r["supplemental_water_search"].get("status") != "not_executed" for r in rows), "actual_supplemental_water_plan_trial_count": sum(r["water_plan_trial_count"] for r in rows), "published_supplemental_water_plan_count": sum(r["selection_kind"] == "supplemental_2x_water_and_schedule_plan_comparison" for r in rows)})
    aggregate["report_level_runtime_capability_addendum_count"] = sum(r["report_capability_addendum_count"] for r in rows)
    save(root / "summary.json", {"report_schema_version": 1, "aggregate": aggregate, "rows": rows})
    fields = ["scenario_id", "status", "source_stable", "reference_operational_complete", "selected_operational_complete", "selected_verified", "selection_kind", "scenario_goal_status", "semantic_model_gap_count", "reference_safe_stored_kg", "primary_selected_safe_stored_kg", "selected_safe_stored_kg", "selected_minus_reference_kg", "selected_id", "search_status", "actual_trial_count", "comparable_trial_count", "infeasible_matched_trial_count", "feasible_but_unmatched_or_provisional_trial_count", "water_plan_trial_count", "action_count", "late_window_risk_count", "discovery_zero_mutation_rejections", "calibrated_workflow", "unsupported_original_workflow", "message"]
    fields.extend(["reported_scenario_goal_status", "report_capability_addendum_count"])
    with (root / "summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: r.get(k) for k in fields} for r in rows)
    save(root / "calibrated_workflow_manifest.json", {"scope": "only selected complete workflows verified under stable saved code/data; final choice compares preserved primary and independently fresh-verified supplemental water plans", "count": aggregate["verified_selected_workflow_count"], "workflows": [{"scenario_id": r["scenario_id"], "path": r["calibrated_workflow"], "file_sha256": file_sha(r["calibrated_workflow"]), "case_directory": r["case_directory"], "kind": r["selection_kind"], "selected_directory": r["selected_directory"], "primary_selected_id": r["primary_selected_id"], "primary_selected_safe_stored_kg": r["primary_selected_safe_stored_kg"], "final_safe_stored_kg": r["selected_safe_stored_kg"], "reproduce_command": r["reproduce_command"], "supplement_script_sha256": r["supplemental_water_search"].get("supplement_script_sha256"), "runtime_adaptation": bool(r["runtime_adaptation"]), "semantic_model_gap_count": r["semantic_model_gap_count"]} for r in rows if r["calibrated_workflow"]]})
    save(root / "unsupported_workflow_manifest.json", {"count": aggregate["unsupported_original_workflow_count"], "workflows": [{"scenario_id": r["scenario_id"], "path": r["unsupported_original_workflow"], "status": r["status"]} for r in rows if r["unsupported_original_workflow"]]})
    text = ["# 正式90场景 Oracle 重新校准报告", "", f"正式清单覆盖{len(ids)}例，本输出manifest安排{len(case_dirs)}例，已有运行summary {aggregate['case_summary_count']}例。冻结源码、已执行选择且鲜场景状态/工具/时钟验证的完整候选为{aggregate['verified_selected_workflow_count']}例；保留未支持原流程{aggregate['unsupported_original_workflow_count']}例。未执行、源码变化中的预览、无匹配试验或未验证候选均不计作校准通过。", "", "## 证据边界", "", "- 六种实际大豆身份使用各自完整参考档案。新增地方物候参数由公开近似成熟期与独立哈尔滨2017气象约束共同热量缩放比例，2018/2019只作冻结后诊断；没有用这90例Oracle产量反调品种参数。这是工程参数转移，不是地方品种田间标定。", "- 90例播距另作来源/几何复核，12例有公开密度候选；只有实际另跑结果才登记已执行。该诊断不自动选择密度，不把原生TDWI随密度变化误称最优密度。", "- 凉八月改实际品种、poor-drainage显式外来水边界为两类运行时适应变体。是否应用以每场保存case_review为准，原任务变化和未支持机制单列，不能计作原固定品种或原未解释水文假设已验证。", "- 病虫草动态、农药防效和工作液参考量仍来自FAIRY经验模块；WOFOST负责耦合后的原生生长。工作液升数不是有效成分药量，也不是产品标签推荐。", "- 每个逻辑干预进行省略/半量/参考剂量及已实际运行的联合省略候选比较；结论仅限实际候选集合。水肥整动作省略同时改变氮和载水，不能单独归因为氮。", "- 匹配试验独立核对初态、全部绝对时刻及未改工具/参数；产量取安全入库标准水分质量，同时报告原生TWSO。工具成功不证明管理必要。", "", link("品种依据与工程标定", ROOT / "docs/oracle-cultivar-mapping.md") + "；" + link("播距来源审查", ROOT / "docs/oracle-sowing-parameter-review.md") + "；" + link("运行时适应登记", ROOT / "configs/oracles/formal90_runtime_adaptations_v1.json"), "", "## 汇总", "", "```json", json.dumps(aggregate, ensure_ascii=False, indent=2), "```", "", "## 逐场完整清单", "", "| 场景ID/明细 | 证据状态 | 原任务机制 | 配对试验/可归因 | 参考→选定入库kg | 动作保留/修改/移除 | 晚窗口风险 | 完整工作流 |", "|---|---|---|---|---|---|---:|---|"]
    boundary = text.index("## 汇总")
    text[boundary:boundary] = ["- 12例初始低肥/局部营养proxy未建立对应原生N库差异。此设定下的‘删除不减产’不能证明原低肥任务中追肥多余，该限制同时写在逐动作必要性判断旁。PCSE已有需求比例固氮，本轮参考档案NFIX_FR=0.8；根瘤故障缺口是源失效没有接入该参数或独立根瘤状态。", "- half灌溉即使固定原请求起点及其他工具绝对时刻，仍同时改变水量和固有delivery_ready时间，不能标为纯水量独立效应。joint_dose_and_omission是实际测试的多输入联合候选。", "- 附加2x灌溉搜索是独立的水量与作业时程计划比较：真实增加作业耗时并顺延后续计划，守原deadline/配额。最终发布从primary与鲜场景严格验证且提高超过0.1kg的水候选中选择，primary证明保留。", "- 因减水后播床低于0.20而拒播、提高参考药量后超药剂额度等，是不可行候选的合法负对照；不计作源码完整性错误，也不把部分入库质量与完整全季产量比较。", ""]
    for row in rows:
        d = row["selected_action_dispositions"]
        file = row["calibrated_workflow"] or row["unsupported_original_workflow"]
        text.append(f"| {link(row['scenario_id'], row['report'])} | `{row['status']}` | {md(row['reported_scenario_goal_status'])}；源缺口{row['semantic_model_gap_count']}/补查{row['report_capability_addendum_count']} | {row['actual_trial_count']}/{row['comparable_trial_count']} | {md(row['reference_safe_stored_kg'])}→{md(row['selected_safe_stored_kg'])} | {d.get('preserved',0)}/{d.get('revised',0)}/{d.get('removed',0)} | {row['late_window_risk_count']} | {link('高水计划' if row['selection_kind']=='supplemental_2x_water_and_schedule_plan_comparison' else '校准候选' if row['calibrated_workflow'] else '未支持原流程',file) if file else '未导出'} |")
    text += ["", "## 复现", "", "每个有完整候选的case报告给出可直接运行的命令。通用形式：", "", "```bash", "env -u USER .venv/bin/python scripts/calibrate_formal90_oracles.py \\", "  --replay-case <本报告cases目录下的完整场景目录> \\", "  --output-dir /tmp/formal90-replay", "```", "", "该入口强校验保存的代码/数据指纹；输出的replay_verification.json分别确认初态、终态和完整全季操作。原生不支持的补种场景保存原完整工作流，须补足生命周期能力后重新校准。", "", "结构化总表为summary.json/csv；每场action_review.json包含逐原管理调用的参数、时刻、参考阶段/DVS、选定实际剂量和关联配对证据。"]
    text = [entry.replace("env -u USER .venv/bin/python", "env -u USER PYTHONHASHSEED=0 .venv/bin/python") for entry in text]
    (root / "REPORT.md").write_text("\n".join(text) + "\n")
    return aggregate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output_root), ensure_ascii=False))


if __name__ == "__main__":
    main()
