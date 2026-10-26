"""Test doubled-reference irrigation as a separate legal plan comparison.

The primary508-file simulation source remains frozen. Each irrigation episode
is restored from the observed reference and doubled, even if primary selection
omitted or halved it. Other primary actions stay unchanged. Real excess tool
duration shifts every later slot; shorter actions retain their original slot.
This is a water-and-schedule bundle, not a matched-time pure water effect.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from copy import deepcopy
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.calibrate_formal90_oracles import episodes, fingerprint, imports, metrics
from scripts.compile_wofost_observed_oracle import clean, digest, save

COMPARISON_KIND = "water_and_schedule_plan_comparison_not_matched_time_dose_effect"
TRACE_FIELDS = ("tool_name", "tool_args", "content", "time_before", "time_after")
TOLERANCE_KG = 0.1


def load(path):
    return json.loads(Path(path).read_text())


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def response_error(value):
    value = clean(value)
    return isinstance(value, dict) and bool(value.get("error") or
        value.get("status") in {"error", "failed", "partial"})


def water_episodes(reference):
    return [{**episode, "id": f"e{index:03d}_double_reference_water",
             "reference_hours_by_step": {name: float(reference.dag[name].tool_args["hours"])
                                         for name in episode["step_ids"]}}
            for index, episode in enumerate(e for e in episodes(reference)
                                            if e["method"] == "irrigate")]


def doubled_changes(reference, primary, episode_list):
    changes = {}
    for episode in episode_list:
        for name in episode["step_ids"]:
            original = reference.dag[name]
            current = primary.dag[name]
            hours = float(original.tool_args["hours"])
            if not isfinite(hours) or hours <= 0:
                raise ValueError(f"Invalid original irrigation duration at {name}")
            args = deepcopy(original.tool_args)
            args["hours"] = hours * 2
            changes[name] = {"kind": "double_reference_irrigation",
                "reference_tool_name": original.tool_name,
                "reference_args": deepcopy(original.tool_args),
                "reference_hours": hours, "revised_args": args,
                "primary_tool_name": current.tool_name,
                "primary_args": deepcopy(current.tool_args),
                "restores_primary_omission": current.tool_name != original.tool_name}
    return changes


def trace_exact(expected, actual):
    return list(expected.dag) == list(actual.dag) and all(
        clean({k: getattr(expected.dag[n], k) for k in TRACE_FIELDS}) ==
        clean({k: getattr(actual.dag[n], k) for k in TRACE_FIELDS})
        for n in expected.dag)


def execute_shifted(primary, changes, tools, engine, deadline, i):
    """Execute real tools and record honest timestamps, without replay padding.

    Returned partial workflows retain a rejected call for audit. There is no
    adaptive rescouting, resource top-up, guard retry or management retiming.
    Extra waits are real registered SystemApp calls; their names are distinct
    from every preserved primary step ID.
    """
    result = i["Workflow"]()
    audit, errors = [], []
    shift, last = 0.0, None
    system = next((name.rsplit("__", 1)[0] for name in tools
                   if name.endswith("__advance_time") and name.startswith("System")), None)
    if system is None:
        raise ValueError("Registered System advance_time tool unavailable")

    def call(name, tool, args, op):
        nonlocal last
        if name in result.dag or name in primary.dag and name.startswith("water_wait_"):
            raise ValueError(f"Duplicate/reserved workflow step {name}")
        before = engine.time_manager.time()
        if before > deadline + 1e-6:
            raise RuntimeError("Original scenario deadline exceeded before operation")
        try:
            content = tools[tool](**deepcopy(args)) if tool else None
        except Exception as exc:
            content = {"error": str(exc), "exception_type": type(exc).__name__}
        after = engine.time_manager.time()
        result.add_node(i["WorkflowStep"](name=name, tool_name=tool,
            tool_args=deepcopy(args), content=clean(content), op_type=op,
            depends_on=[last] if last else [], time_before=before, time_after=after))
        last = name
        if response_error(content):
            raise RuntimeError(f"{tool}: {clean(content)}")
        if after < before - 1e-6 or after > deadline + 1e-6:
            raise RuntimeError("Operation time is invalid or exceeds original scenario deadline")
        return content

    def wait_until(target, name):
        now = engine.time_manager.time()
        if target < now - 1e-6:
            raise RuntimeError("Scheduled slot precedes actual current clock")
        if target > deadline + 1e-6:
            raise RuntimeError("Shifted plan exceeds original scenario deadline")
        seconds = target - now
        if seconds > 1e-6:
            rounded = round(seconds)
            if abs(seconds - rounded) > 1e-6:
                raise ValueError("Public System advance_time cannot represent a fractional-second idle slot")
            call(name, system + "__advance_time", {"seconds": int(rounded)}, "READ")

    for index, (name, original) in enumerate(primary.dag.items()):
        record = {"source_step": name, "source_before": original.time_before,
                  "source_after": original.time_after, "shift_before": shift}
        try:
            before, after = original.time_before, original.time_after
            if (type(before) not in (int, float) or type(after) not in (int, float)
                    or not isfinite(before) or not isfinite(after) or after < before):
                raise ValueError(f"Invalid primary slot at {name}")
            wait_until(before + shift, f"water_wait_{index:05d}_before")
            change = changes.get(name)
            tool = change["reference_tool_name"] if change else original.tool_name
            args = deepcopy(change["revised_args"] if change else original.tool_args or {})
            content = call(name, tool, args, "WRITE" if change else original.op_type)
            actual = result.dag[name]
            record.update(actual_before=actual.time_before, actual_after=actual.time_after,
                          original_slot_end=after + shift, changed_water=bool(change))
            if change:
                targets = list(range(int(args["start"]), int(args["end"]) + 1))
                if (not isinstance(content, dict) or content.get("status") != "irrigation_started"
                        or content.get("irrigated_ridges") != targets
                        or abs(float(content.get("duration_hours_per_ridge", -1)) - args["hours"]) > 1e-9):
                    raise RuntimeError("Doubled irrigation did not actually apply its entire requested range/duration")
            excess = max(0.0, engine.time_manager.time() - (after + shift))
            record["additional_duration_seconds"] = excess
            record["padded_to_slot_end"] = engine.time_manager.time() < after + shift - 1e-6
            wait_until(max(engine.time_manager.time(), after + shift), f"water_wait_{index:05d}_pad")
            shift += excess
            record["shift_after"] = shift
            record["slot_end_after_padding"] = engine.time_manager.time()
        except Exception as exc:
            errors.append({"source_step": name, "exception_type": type(exc).__name__, "message": str(exc)})
            record.update(error=errors[-1], shift_after=shift)
            audit.append(record)
            break
        audit.append(record)
    return result, audit, errors, shift


def select_candidate(primary_metrics, trials, tolerance=TOLERANCE_KG):
    """Higher irrigation must beat primary by more than the yield tolerance."""
    improved = [t for t in trials if t.get("verified") and
                t["metrics"].get("operational_complete") and
                t["metrics"]["safe_stored_kg"] > primary_metrics["safe_stored_kg"] + tolerance]
    if not improved:
        return None
    best_yield = max(t["metrics"]["safe_stored_kg"] for t in improved)
    near = [t for t in improved if t["metrics"]["safe_stored_kg"] >= best_yield - tolerance]
    return min(near, key=lambda t: (t["metrics"]["intervention_inputs"]["irrigation_ridge_mm"],
                                    t["metrics"]["intervention_inputs"]["intervention_calls"], t["id"]))


def run_trial(compiler, primary, changes, destination, expected_initial, i):
    destination.mkdir(parents=True, exist_ok=True)
    scene, engine = compiler.fresh()
    initial = clean(compiler.snapshot_unrecorded(scene, engine))
    save(destination / "initial_snapshot.json", initial)
    deadline = engine.start_time + float(scene.duration)
    workflow = i["Workflow"]()
    answer = {"verified": False, "deadline_timestamp": deadline,
              "initial_hash": digest(initial), "expected_initial_hash": expected_initial,
              "initial_state_exact": digest(initial) == expected_initial,
              "comparison_kind": COMPARISON_KIND, "changes": changes}
    save(destination / "changes.json", changes)
    try:
        if not answer["initial_state_exact"]:
            raise ValueError("Fresh trial initial state differs from primary selected initial state")
        _, _, tools = i["build_toolset"](list(scene.apps))
        workflow, audit, errors, shift = execute_shifted(primary, changes, tools, engine, deadline, i)
        workflow.save_workflow(str(destination / "workflow.json"))
        workflow.save_workflow(str(destination / "expected_replay.json"))
        save(destination / "schedule_audit.json", audit)
        final = clean(compiler.snapshot_unrecorded(scene, engine))
        save(destination / "final_snapshot.json", final)
        actual_metrics = metrics(final, workflow)
        actual_metrics["operational_complete"] &= not errors and float(final["clock"]) <= deadline + 1e-6
        answer.update(metrics=actual_metrics, errors=errors, schedule_shift_seconds=shift,
                      final_hash=digest(final), workflow_sha256=digest(workflow.to_dict()))
        if errors or not actual_metrics["operational_complete"]:
            answer["status"] = "infeasible_real_execution"
        else:
            fresh, replay_engine = compiler.fresh()
            replay_initial = clean(compiler.snapshot_unrecorded(fresh, replay_engine))
            save(destination / "replay_initial_snapshot.json", replay_initial)
            replay = replay_engine.replay_workflow(workflow)
            replay.save_workflow(str(destination / "replay.json"))
            replay_final = clean(compiler.snapshot_unrecorded(fresh, replay_engine))
            save(destination / "replay_final_snapshot.json", replay_final)
            replay_metrics = metrics(replay_final, replay)
            answer.update(fresh_initial_state_exact=digest(replay_initial) == expected_initial,
                fresh_final_state_exact=digest(final) == digest(replay_final),
                fresh_trace_and_time_exact=trace_exact(workflow, replay),
                replay_final_hash=digest(replay_final), replay_metrics=replay_metrics)
            answer["verified"] = (answer["fresh_initial_state_exact"] and
                answer["fresh_final_state_exact"] and answer["fresh_trace_and_time_exact"] and
                replay_metrics["operational_complete"] and float(replay_final["clock"]) <= deadline + 1e-6)
            answer["status"] = "fresh_replay_verified" if answer["verified"] else "fresh_replay_mismatch"
    except Exception as exc:
        answer.update(status="execution_or_replay_exception", exception_type=type(exc).__name__,
                      message=str(exc), traceback=traceback.format_exc())
    answer.setdefault("metrics", {"operational_complete": False})
    answer["operational_complete"] = answer["metrics"].get("operational_complete", False)
    save(destination / "summary.json", answer)
    return answer


def publish_selected(base, case, selected, primary_metrics, primary_summary):
    """Retain both primary evidence and the full selected supplemental plan."""
    directory = base / "selected"
    directory.mkdir(exist_ok=True)
    origin = base / selected["directory"] if selected else case / "selected"
    for name in ("workflow.json", "replay.json", "expected_replay.json", "initial_snapshot.json",
                 "final_snapshot.json", "replay_initial_snapshot.json", "replay_final_snapshot.json",
                 "schedule_audit.json", "changes.json"):
        if (origin / name).is_file():
            shutil.copyfile(origin / name, directory / name)
    if not selected:
        shutil.copyfile(origin / "initial_snapshot.json", directory / "replay_initial_snapshot.json")
        shutil.copyfile(origin / "final_snapshot.json", directory / "replay_final_snapshot.json")
        save(directory / "changes.json", {})
        save(directory / "schedule_audit.json", [])
    record = {**(selected or {}), "id": selected["id"] if selected else "primary_selected",
              "directory": "selected", "metrics": selected["metrics"] if selected else primary_metrics,
              "verified": selected["verified"] if selected else True,
              "proof_origin": "supplemental_actual_and_fresh_replay" if selected else "primary_fresh_replay",
              "primary_fresh_final_state_exact": primary_summary["fresh_native_state_exact"],
              "primary_fresh_trace_and_time_exact": primary_summary["fresh_tool_trace_and_time_exact"]}
    save(directory / "summary.json", record)
    return record


def process_case(case):
    from scripts.formal90_calibration_policy import CalibrationCompiler
    case = Path(case).resolve()
    base = case / "supplemental_water_search"
    base.mkdir(parents=True, exist_ok=True)
    source = load(case / "source_before.json")
    summary = load(case / "summary.json")
    before = fingerprint()
    answer = {"schema_version": 1, "scenario_id": summary["scenario_id"],
        "comparison_kind": COMPARISON_KIND, "production_source_matches": source == before,
        "production_source_sha256": digest(source),
        "production_source_file_sha256": file_sha(case / "source_before.json"),
        "supplement_script_path": str(Path(__file__).relative_to(ROOT)),
        "supplement_script_sha256": file_sha(__file__), "trials": [],
        "yield_improvement_required_kg": TOLERANCE_KG,
        "primary_summary_file_sha256": file_sha(case / "summary.json")}
    try:
        if source != before or load(case / "source_after.json") != source:
            raise ValueError("Primary/frozen/live508 source fingerprints do not match")
        cal = summary.get("calibration", {})
        if not (cal.get("status") == "best_tested_candidate_fresh_replay_verified" and
                cal.get("fresh_native_state_exact") and cal.get("fresh_tool_trace_and_time_exact")):
            answer.update(status="primary_not_fresh_verified", selected_verified=False)
            return answer
        i = imports()
        primary = i["Workflow"].load_workflow(str(case / "selected/workflow.json"))
        primary_replay = i["Workflow"].load_workflow(str(case / "selected/replay.json"))
        reference = i["Workflow"].load_workflow(str(case / "reference/observed_workflow.json"))
        initial = load(case / "selected/initial_snapshot.json")
        final = load(case / "selected/final_snapshot.json")
        primary_metrics = metrics(final, primary_replay)
        if not primary_metrics["operational_complete"]:
            raise ValueError("Primary selected evidence is not operationally complete")
        answer["primary"] = {"id": "primary_selected", "directory": "../selected",
            "workflow": "../selected/workflow.json", "metrics": primary_metrics,
            "initial_hash": digest(initial), "final_hash": digest(final),
            "workflow_file_sha256": file_sha(case / "selected/workflow.json")}
        groups = water_episodes(reference)
        answer["episodes"] = groups
        if not groups:
            answer.update(status="reviewed_no_irrigation_episode", selected_id="primary_selected",
                selected_directory="../selected", selected_metrics=primary_metrics, selected_verified=True,
                selection_reason="No registered reference irrigate episode to double")
            return answer
        compiler = CalibrationCompiler(summary["scenario_id"], load(case / "config.json"),
            base / "factory", i, review=load(case / "case_review.json"))
        answer["deadline_timestamp"] = compiler.deadline
        for episode in groups:
            changes = doubled_changes(reference, primary, [episode])
            result = run_trial(compiler, primary, changes, base / episode["id"], digest(initial), i)
            record = {**result, "id": episode["id"], "directory": episode["id"],
                      "episode_keys": [episode["key"]]}
            if result["metrics"].get("safe_stored_kg") is not None:
                record["delta_safe_stored_kg"] = result["metrics"]["safe_stored_kg"] - primary_metrics["safe_stored_kg"]
            answer["trials"].append(record)
        improved_groups = [group for group, trial in zip(groups, answer["trials"])
                           if trial.get("verified") and trial.get("delta_safe_stored_kg", float("-inf")) > TOLERANCE_KG]
        if len(improved_groups) > 1:
            changes = doubled_changes(reference, primary, improved_groups)
            identity = "joint_individually_improved_double_water"
            result = run_trial(compiler, primary, changes, base / identity, digest(initial), i)
            record = {**result, "id": identity, "directory": identity,
                      "episode_keys": [g["key"] for g in improved_groups]}
            if result["metrics"].get("safe_stored_kg") is not None:
                record["delta_safe_stored_kg"] = result["metrics"]["safe_stored_kg"] - primary_metrics["safe_stored_kg"]
            answer["trials"].append(record)
        selected = select_candidate(primary_metrics, answer["trials"])
        effective = publish_selected(base, case, selected, primary_metrics, cal)
        answer.update(status="supplemental_search_completed", selected_id=effective["id"],
            selected_directory="selected", selected_metrics=effective["metrics"],
            selected_verified=effective["verified"],
            selection_reason="Verified higher-water legal plan improves safe stored mass by more than0.1kg" if selected
                else "Primary retained; no feasible fresh-verified higher-water plan beats primary by more than0.1kg")
    except Exception as exc:
        answer.update(status="supplemental_search_blocked", selected_verified=False,
            exception_type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
    finally:
        after = fingerprint()
        answer["production_source_changed_during_search"] = [p for p in sorted(set(before) | set(after)) if before.get(p) != after.get(p)]
        answer["production_source_matches"] &= source == after
        if not answer["production_source_matches"]:
            answer["selected_verified"] = False
        save(base / "summary.json", answer)
    return answer


def replay_case(case, output):
    from scripts.formal90_calibration_policy import CalibrationCompiler
    case, output = Path(case).resolve(), Path(output).resolve()
    base = case / "supplemental_water_search"
    summary = load(base / "summary.json")
    if not summary.get("selected_verified") or not summary.get("production_source_matches"):
        raise ValueError("Supplemental selection is not verified")
    if fingerprint() != load(case / "source_before.json") or file_sha(__file__) != summary["supplement_script_sha256"]:
        raise ValueError("Original508 source or supplemental script fingerprint differs; cannot claim exact replay")
    if output == case or case in output.parents:
        raise ValueError("Replay output must not overwrite original case evidence")
    output.mkdir(parents=True, exist_ok=False)
    chosen = (base / summary["selected_directory"]).resolve()
    i = imports()
    compiler = CalibrationCompiler(summary["scenario_id"], load(case / "config.json"),
        output / "factory", i, review=load(case / "case_review.json"))
    scene, engine = compiler.fresh()
    initial = clean(compiler.snapshot_unrecorded(scene, engine))
    save(output / "initial_snapshot.json", initial)
    plan = i["Workflow"].load_workflow(str(chosen / "workflow.json"))
    expected = i["Workflow"].load_workflow(str(chosen / "replay.json"))
    replay = engine.replay_workflow(plan)
    replay.save_workflow(str(output / "replay.json"))
    final = clean(compiler.snapshot_unrecorded(scene, engine))
    save(output / "final_snapshot.json", final)
    result = {"initial_state_exact": digest(initial) == digest(load(chosen / "initial_snapshot.json")),
        "final_state_exact": digest(final) == digest(load(chosen / "final_snapshot.json")),
        "trace_and_time_exact": trace_exact(expected, replay), "metrics": metrics(final, replay),
        "within_original_deadline": final["clock"] <= compiler.deadline + 1e-6,
        "production_source_matches": fingerprint() == load(case / "source_before.json"),
        "supplement_script_sha256": file_sha(__file__)}
    result["verified"] = all(result[k] for k in ("initial_state_exact", "final_state_exact",
        "trace_and_time_exact", "within_original_deadline", "production_source_matches")) and result["metrics"]["operational_complete"]
    save(output / "replay_verification.json", result)
    return result


def run_batch(args):
    root = args.output_root.resolve()
    manifest = load(root / "manifest.json")
    cases = {row["scenario_id"]: root / row["case_dir"] for row in manifest["cases"]}
    if args.scenario_ids:
        wanted = set(args.scenario_ids.split(","))
        if wanted - cases.keys():
            raise ValueError(f"Unknown scenario IDs: {wanted - cases.keys()}")
        cases = {sid: case for sid, case in cases.items() if sid in wanted}
    pending, active, done = dict(cases), {}, {}
    env = os.environ.copy()
    env.pop("USER", None)
    env.update(PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="1",
               OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    def job(case):
        base = case / "supplemental_water_search"
        base.mkdir(exist_ok=True)
        with (base / "worker.log").open("w") as log:
            completed = subprocess.run([sys.executable, str(Path(__file__)), "--case-dir", str(case)],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        return completed.returncode
    def progress():
        save(root / "supplemental_water_search_progress.json", {"schema_version": 1,
            "expected_case_count": len(cases), "completed_case_count": len(done),
            "pending_case_count": len(pending), "running_case_count": len(active),
            "supplement_script_sha256": file_sha(__file__), "comparison_kind": COMPARISON_KIND,
            "cases": list(done.values())})
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        while pending or active:
            for sid, case in list(pending.items()):
                if len(active) >= args.workers:
                    break
                if not (case / "summary.json").is_file():
                    continue
                saved = case / "supplemental_water_search/summary.json"
                if saved.is_file() and load(saved).get("supplement_script_sha256") == file_sha(__file__):
                    done[sid] = {"scenario_id": sid, **{k: load(saved).get(k) for k in
                        ("status", "selected_id", "selected_verified", "production_source_matches")}}
                    del pending[sid]
                    continue
                active[pool.submit(job, case)] = sid
                del pending[sid]
            if active:
                finished, _ = wait(active, timeout=5, return_when=FIRST_COMPLETED)
                for future in finished:
                    sid = active.pop(future)
                    returncode = future.result()
                    path = cases[sid] / "supplemental_water_search/summary.json"
                    saved = load(path) if path.exists() else {}
                    done[sid] = {"scenario_id": sid, "returncode": returncode,
                        **{k: saved.get(k) for k in ("status", "selected_id", "selected_verified", "production_source_matches")}}
                    print(json.dumps(done[sid], ensure_ascii=False), flush=True)
            elif pending:
                if not args.watch:
                    break
                time.sleep(5)
            progress()
    progress()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--scenario-ids")
    parser.add_argument("--case-dir", type=Path)
    parser.add_argument("--replay-case", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if sum(map(bool, (args.output_root, args.case_dir, args.replay_case))) != 1:
        parser.error("Choose --output-root, --case-dir or --replay-case")
    if args.replay_case:
        if args.output_dir is None:
            parser.error("--replay-case requires --output-dir")
        print(json.dumps(clean(replay_case(args.replay_case, args.output_dir)), ensure_ascii=False))
    elif args.case_dir:
        result = process_case(args.case_dir)
        print(json.dumps({k: result.get(k) for k in ("scenario_id", "status", "selected_id", "selected_verified")}, ensure_ascii=False))
    else:
        run_batch(args)


if __name__ == "__main__":
    main()
