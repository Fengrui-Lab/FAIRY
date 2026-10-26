"""Recalibrate each formal90 Oracle and preserve matched-time intervention evidence.

Cultivar parameters are explicit inputs, never fitted to Oracle yield. Discovery
uses registered public tools. Omission/dose trials replay a fixed observed plan
at the same absolute epochs; a selected candidate is replayed again from a fresh
scene. Operational completion, scenario mechanism coverage and bounded-search
results remain separate outcomes.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.compile_wofost_observed_oracle import clean, digest, save

INTERVENTIONS = {
    "apply_fertigation", "irrigate", "apply_fungicide", "spray_pesticide",
    "apply_pesticide_manual", "apply_herbicide", "mechanical_weed_control",
}
DOSE_KEYS = {
    "apply_fertigation": "nutrient_amount", "irrigate": "hours",
    "apply_fungicide": "liters_per_ridge", "spray_pesticide": "liters_per_ridge",
    "apply_pesticide_manual": "liters_per_ridge", "apply_herbicide": "liters_per_ridge",
}
REFERENCE_DOSES = {"apply_fungicide": 3.8, "spray_pesticide": 8.0,
                   "apply_herbicide": 8.0, "apply_pesticide_manual": 3.0}


def imports():
    from fairy.controllers.engine import Engine
    from fairy.scenarios.registry import get_scenario_class
    from fairy.scenarios.workflow import Workflow, WorkflowStep
    from fairy.agents.agent.toolset_builder import build_toolset
    from fairy.apps.farm_world import FarmWorldApp, WeatherApp, SensorApp
    from fairy.apps.system import SystemApp
    return locals()


def fingerprint():
    files = list((ROOT / "fairy").rglob("*.py"))
    files += [p for p in (ROOT / "fairy/physics/data/wofost").rglob("*")
              if p.is_file() and p.suffix in {".json", ".yaml", ".yml"}]
    files += list((ROOT / "configs/wofost").glob("formal90*.json"))
    files += list((ROOT / "configs/oracles").glob("formal90*.json"))
    files += [Path(__file__), ROOT / "scripts/formal90_calibration_policy.py",
              ROOT / "scripts/compile_wofost_observed_oracle.py", ROOT / "pyproject.toml",
              ROOT / "uv.lock"]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files) if p.is_file()}


def episode_key(name, method):
    """Treat consecutive boom/cultivator passes of one decision as one episode."""
    source = re.sub(r"^v\d+_", "", name)
    source = re.sub(r"_(?:insecticide_spray|manual_spray|spray|mechanical_weed)_\d+_\d+$", "", source)
    return method + ":" + source


def episodes(workflow):
    groups = {}
    for name, step in workflow.dag.items():
        method = (step.tool_name or "").rsplit("__", 1)[-1]
        if method in INTERVENTIONS:
            key = episode_key(name, method)
            groups.setdefault(key, {"key": key, "method": method, "step_ids": []})["step_ids"].append(name)
    return list(groups.values())


def variant_workflow(workflow, changes, Workflow):
    result = Workflow()
    for name, original in workflow.dag.items():
        step = deepcopy(original)
        change = changes.get(name)
        if change:
            method = (step.tool_name or "").rsplit("__", 1)[-1]
            if change["kind"] == "omit":
                step.tool_name = "SystemApp__get_current_time"
                step.tool_args = {}
                step.op_type = "READ"
            elif change["kind"] == "half":
                key = DOSE_KEYS[method]
                if key not in step.tool_args:
                    raise ValueError(f"No dose key {key} in {name}")
                step.tool_args[key] = float(step.tool_args[key]) * 0.5
            elif change["kind"] == "reference_dose":
                step.tool_args[DOSE_KEYS[method]] = REFERENCE_DOSES[method]
            else:
                raise ValueError(f"Unknown experiment {change}")
        result.add_node(step)
    return result


def dose_totals(workflow):
    totals = {"intervention_calls": 0, "fertilizer_product_kg": 0.0,
              "chemical_working_fluid_l": 0.0, "irrigation_ridge_mm": 0.0,
              "carrier_water_ridge_mm": 0.0, "mechanical_ridge_passes": 0}
    for step in workflow.dag.values():
        method = (step.tool_name or "").rsplit("__", 1)[-1]
        if method not in INTERVENTIONS:
            continue
        a = step.tool_args or {}
        first = int(a.get("start_ridge", a.get("start", a.get("ridge_id", 0))))
        last = int(a.get("end_ridge", a.get("end", first)))
        count = int(a.get("ridge_count", last - first + 1))
        totals["intervention_calls"] += 1
        if method == "apply_fertigation":
            totals["fertilizer_product_kg"] += float(a["nutrient_amount"]) * 30 * count
            totals["carrier_water_ridge_mm"] += float(a.get("water_mm", 0)) * count
        elif method == "irrigate":
            totals["irrigation_ridge_mm"] += float(a["hours"]) * 5 * count
        elif method == "mechanical_weed_control":
            totals["mechanical_ridge_passes"] += count
        else:
            totals["chemical_working_fluid_l"] += float(a.get("liters_per_ridge", a.get("liters", 0))) * count
    return totals


def metrics(snapshot, workflow):
    errors, storage_warnings = [], []
    stored_ridges = set()
    for name, step in workflow.dag.items():
        content = step.content
        if isinstance(content, dict):
            if content.get("error") or content.get("status") in {"error", "failed", "partial"}:
                errors.append({"step": name, "content": content})
            if (step.tool_name or "").endswith("__store_grain"):
                if content.get("warning"):
                    storage_warnings.append(content["warning"])
                elif float(content.get("moved_kg", 0)) > 0:
                    stored_ridges.update(content.get("batch_ridge_ids", []))
    farm_results = {}
    stored_mass = native_mass = 0.0
    for name, farm in snapshot["farms"].items():
        world = farm["world"]
        native = farm.get("native_backend") or {}
        area = float(world["field_length_m"]) * float(world["ridge_width_m"])
        native_mass += sum(float(r.get("pcse", {}).get("TWSO") or 0) * area / 10000
                           for r in native.get("ridges", {}).values())
        grain = farm["engines"]["yield_recovery"]
        n = int(world["num_ridges"])
        harvested = sum(bool(s["harvested"]) for s in grain.values())
        matured = sum(bool(s["r8_reached"]) for s in grain.values())
        planted = len(native.get("ridges", {}))
        inv = world.get("inventory", {})
        stored_mass += float(inv.get("warehouse_grain_kg", 0))
        farm_results[name] = {"expected_ridges": n, "native_ridges": planted,
                              "matured_ridges": matured, "harvested_ridges": harvested}
    bins_empty = all(float(state.get("grain_bin_kg", 0)) <= 0.01
                     for state in snapshot["apps"].values() if isinstance(state, dict))
    expected = sum(r["expected_ridges"] for r in farm_results.values())
    complete = (len(stored_ridges) == expected and not errors and not storage_warnings
                and bins_empty and all(r["expected_ridges"] == r["native_ridges"] ==
                                       r["matured_ridges"] == r["harvested_ridges"]
                                       for r in farm_results.values()))
    return {"safe_stored_kg": stored_mass, "native_twso_mass_kg": native_mass,
            "farms": farm_results, "safely_stored_ridges": sorted(stored_ridges),
            "errors": errors, "storage_warnings": storage_warnings,
            "combine_bins_empty": bins_empty, "operational_complete": complete,
            "clock": snapshot["clock"], "intervention_inputs": dose_totals(workflow)}


def trial(compiler, plan, output):
    output.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    scene, engine = compiler.fresh()
    initial = clean(compiler.snapshot_unrecorded(scene, engine))
    save(output / "initial_snapshot.json", initial)
    plan.save_workflow(str(output / "workflow.json"))
    try:
        replay = engine.replay_workflow(plan)
        replay.save_workflow(str(output / "replay.json"))
        final = clean(compiler.snapshot_unrecorded(scene, engine))
        save(output / "final_snapshot.json", final)
        result = metrics(final, replay)
        result.update({"initial_hash": digest(initial), "final_hash": digest(final),
                       "workflow_sha256": digest(plan.to_dict()),
                       "actual_replay_sha256": digest(replay.to_dict())})
    except Exception as exc:
        result = {"operational_complete": False, "exception_type": type(exc).__name__,
                  "message": str(exc), "traceback": traceback.format_exc()}
    result["wall_seconds"] = time.monotonic() - start
    save(output / "summary.json", result)
    return result


def choose_best(candidates, tolerance_kg=0.1):
    feasible = [c for c in candidates if c["metrics"].get("operational_complete")]
    if not feasible:
        return None
    maximum = max(c["metrics"]["safe_stored_kg"] for c in feasible)
    eligible = [c for c in feasible if c["metrics"]["safe_stored_kg"] >= maximum - tolerance_kg]
    def resource_order(c):
        r = c["metrics"]["intervention_inputs"]
        return (r["intervention_calls"], r["chemical_working_fluid_l"],
                r["fertilizer_product_kg"], r["irrigation_ridge_mm"], c["id"])
    return min(eligible, key=resource_order)


def run_experiments(compiler, case_dir, level, i):
    reference = case_dir / "reference"
    workflow = i["Workflow"].load_workflow(str(reference / "observed_workflow.json"))
    baseline_final = json.loads((reference / "replay_final_snapshot.json").read_text())
    baseline_replay = i["Workflow"].load_workflow(str(reference / "fresh_replay.json"))
    baseline = metrics(baseline_final, baseline_replay)
    initial_hash = digest(json.loads((reference / "initial_snapshot.json").read_text()))
    candidates = [{"id": "reference", "directory": "reference", "changes": {}, "metrics": baseline}]
    comparisons = []
    all_omissions = {}
    omission_episodes = set()
    best_episode_choices = {}
    changed_episode_count = 0
    for number, episode in enumerate(episodes(workflow)):
        episode_candidates = []
        kinds = ["omit"]
        if level == "bounded" and episode["method"] in DOSE_KEYS:
            kinds.append("half")
            if episode["method"] in REFERENCE_DOSES and any(
                abs(float(workflow.dag[n].tool_args[DOSE_KEYS[episode["method"]]]) -
                    REFERENCE_DOSES[episode["method"]]) > 1e-9 for n in episode["step_ids"]):
                kinds.append("reference_dose")
        for kind in kinds:
            key = f"e{number:03d}_{kind}"
            changes = {n: {"kind": kind} for n in episode["step_ids"]}
            revised = variant_workflow(workflow, changes, i["Workflow"])
            folder = case_dir / "ablations" / key
            result = trial(compiler, revised, folder)
            if result.get("initial_hash") != initial_hash:
                result["operational_complete"] = False
                result["initial_state_mismatch"] = True
                save(folder / "summary.json", result)
            record = {"id": key, "directory": str(folder.relative_to(case_dir)),
                      "episode": episode, "changes": changes, "metrics": result,
                      "baseline_dir": "reference", "candidate_dir": str(folder.relative_to(case_dir)),
                      "removed_step_ids": episode["step_ids"] if kind == "omit" else [],
                      "changed_step_ids": episode["step_ids"], "candidate_kind": kind}
            if result.get("operational_complete"):
                record["delta_safe_stored_kg"] = result["safe_stored_kg"] - baseline["safe_stored_kg"]
                record["delta_native_twso_mass_kg"] = result["native_twso_mass_kg"] - baseline["native_twso_mass_kg"]
                if kind == "omit" and record["delta_safe_stored_kg"] >= -0.1:
                    all_omissions.update(changes)
                    omission_episodes.add(episode["key"])
            comparisons.append(record)
            candidates.append(record)
            episode_candidates.append(record)
            save(case_dir / "ablations/manifest.json", {"baseline_dir": "reference", "trials": comparisons})
        episode_best = choose_best([candidates[0], *episode_candidates])
        if episode_best and episode_best["id"] != "reference":
            best_episode_choices.update(episode_best["changes"])
            changed_episode_count += 1
    # Interactions must be tested; independently dispensable actions are not
    # assumed jointly dispensable.
    joint_proposals = []
    if len(omission_episodes) > 1:
        joint_proposals.append(("joint_noninferior_omissions", "joint_omission", all_omissions))
    if changed_episode_count > 1 and best_episode_choices != all_omissions:
        joint_proposals.append(("joint_best_episode_choices", "joint_dose_and_omission", best_episode_choices))
    for key, kind, changes in joint_proposals:
        plan = variant_workflow(workflow, changes, i["Workflow"])
        folder = case_dir / "ablations" / key
        result = trial(compiler, plan, folder)
        if result.get("initial_hash") != initial_hash:
            result["operational_complete"] = False
            result["initial_state_mismatch"] = True
            save(folder / "summary.json", result)
        record = {"id": key, "directory": str(folder.relative_to(case_dir)),
                  "changes": changes, "metrics": result, "baseline_dir": "reference",
                  "candidate_dir": str(folder.relative_to(case_dir)),
                  "removed_step_ids": [n for n, change in changes.items() if change["kind"] == "omit"],
                  "changed_step_ids": list(changes), "candidate_kind": kind}
        if result.get("operational_complete"):
            record["delta_safe_stored_kg"] = result["safe_stored_kg"] - baseline["safe_stored_kg"]
            record["delta_native_twso_mass_kg"] = result["native_twso_mass_kg"] - baseline["native_twso_mass_kg"]
        comparisons.append(record)
        candidates.append(record)
    save(case_dir / "ablations/manifest.json", {"baseline_dir": "reference", "trials": comparisons})
    best = choose_best(candidates)
    if best is None:
        return {"status": "no_feasible_candidate", "baseline": baseline, "trial_count": len(comparisons)}
    selected = variant_workflow(workflow, best["changes"], i["Workflow"])
    selected_dir = case_dir / "selected"
    verified = trial(compiler, selected, selected_dir)
    expected_hash = (digest(baseline_final) if best["id"] == "reference"
                     else best["metrics"].get("final_hash"))
    exact = verified.get("final_hash") == expected_hash
    if best["id"] == "reference":
        shutil.copyfile(reference / "fresh_replay.json", selected_dir / "expected_replay.json")
    else:
        shutil.copyfile(case_dir / best["directory"] / "replay.json", selected_dir / "expected_replay.json")
    actual = json.loads((selected_dir / "replay.json").read_text()) if (selected_dir / "replay.json").exists() else {}
    expected = json.loads((selected_dir / "expected_replay.json").read_text())
    fields = ("tool_name", "tool_args", "content", "time_before", "time_after")
    trace_exact = (list(actual) == list(expected) and all(
        clean({k: actual[n].get(k) for k in fields}) == clean({k: expected[n].get(k) for k in fields})
        for n in actual))
    return {"status": "best_tested_candidate_fresh_replay_verified" if exact and trace_exact and
            verified.get("operational_complete") else "selected_candidate_verification_failed",
            "selected_id": best["id"], "selected_directory": "selected",
            "selected_changes": best["changes"], "trial_count": len(comparisons),
            "baseline": baseline, "selected": verified, "fresh_native_state_exact": exact,
            "fresh_tool_trace_and_time_exact": trace_exact,
            "yield_equivalence_tolerance_kg": 0.1,
            "search_scope": "single-episode omit/half/reference-dose; tested joint noninferior omissions and best episode choices; no global optimum claim"}


def run_sowing_comparison(source, sid, config, review, output, i):
    """Test published-density alternatives as separate adaptive management plans.

    Native density currently scales TDWI only. Its yield response cannot identify
    an agronomic density optimum, so this diagnostic never silently replaces a
    scenario's prescribed planting density or an equal-density cultivar contrast.
    """
    from scripts.formal90_calibration_policy import CalibrationCompiler
    document = json.loads((ROOT / "configs/oracles/formal90_sowing_parameter_review_v1.json").read_text())
    row = next(r for r in document["rows"] if r["scenario_id"] == sid)
    save(output / "sowing_parameter_review.json", row)
    proposals = [g for g in row["planting_groups"] if g.get("decision") == "candidate"]
    if not proposals:
        return {"status": "reviewed_no_alternative_density_candidate"}
    revised = deepcopy(source)
    overrides = []
    for group in proposals:
        for name in group["source_step_ids"]:
            if name not in revised.dag:
                raise ValueError(f"Sowing candidate references unknown source step {name}")
            args = revised.dag[name].tool_args
            before = args["seed_spacing_cm"]
            args["seed_spacing_cm"] = group["candidate_spacing_cm"]
            overrides.append({"source_step": name, "seed_type": group["seed_type"],
                              "original_spacing_cm": before,
                              "candidate_spacing_cm": args["seed_spacing_cm"],
                              "reference": group["reference"]})
    folder = output / "sowing_candidate/reference"
    folder.mkdir(parents=True, exist_ok=True)
    revised.save_workflow(str(folder / "candidate_source_workflow.json"))
    save(folder / "changes_from_original_sowing.json", overrides)
    alternative = CalibrationCompiler(sid, config, folder, i, review=review)
    try:
        summary = alternative.compile(revised)
        save(folder / "summary.json", summary)
        if summary.get("completion") != "feasible_operational_reference":
            return {"status": "published_density_candidate_incomplete", "result": summary}
        snapshot = json.loads((folder / "replay_final_snapshot.json").read_text())
        replay = i["Workflow"].load_workflow(str(folder / "fresh_replay.json"))
        baseline = json.loads((output / "reference/replay_final_snapshot.json").read_text())
        baseline_workflow = i["Workflow"].load_workflow(str(output / "reference/fresh_replay.json"))
        initial = json.loads((folder / "initial_snapshot.json").read_text())
        baseline_initial = json.loads((output / "reference/initial_snapshot.json").read_text())
        candidate_metrics = metrics(snapshot, replay)
        baseline_metrics = metrics(baseline, baseline_workflow)
        return {"status": "published_density_alternative_fresh_replayed",
                "directory": "sowing_candidate/reference", "changes": overrides,
                "matched_initial_state": digest(initial) == digest(baseline_initial),
                "candidate": candidate_metrics,
                "delta_safe_stored_kg": candidate_metrics["safe_stored_kg"] - baseline_metrics["safe_stored_kg"],
                "comparison_scope": "published-density alternative with the same public adaptive timing policy, not a matched-time density-only ablation",
                "selection": "original prescribed density retained; native TDWI-only response cannot establish a cultivar density optimum"}
    except Exception as exc:
        return {"status": "published_density_candidate_requires_review",
                "exception_type": type(exc).__name__, "message": str(exc)}
    finally:
        save(folder / "discovery_trace.json", alternative.trace)
        save(folder / "changes.json", alternative.changes)


def run_case(args):
    from scripts.formal90_calibration_policy import CalibrationCompiler
    i = imports()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = json.loads(args.wofost_config.read_text())
    reviews = json.loads(args.review_config.read_text())
    review = deepcopy(next(r for r in reviews["rows"] if r["scenario_id"] == args.scenario))
    adaptation_path = ROOT / "configs/oracles/formal90_runtime_adaptations_v1.json"
    if adaptation_path.exists():
        adaptation = next((r for r in json.loads(adaptation_path.read_text())["rows"]
                           if r["scenario_id"] == args.scenario), None)
        if adaptation:
            config.update(deepcopy(adaptation.get("config_overrides", {})))
            review["runtime_adaptation"] = deepcopy(adaptation)
            review["seed_replacements"] = deepcopy(adaptation.get("seed_replacements", {}))
    save(output / "config.json", config)
    save(output / "case_review.json", review)
    before = fingerprint()
    save(output / "source_before.json", before)
    start = time.monotonic()
    compiler = None
    result = {"scenario_id": args.scenario, "experiments": args.experiments}
    reference = output / "reference"
    reference.mkdir(exist_ok=True)
    try:
        original = i["Engine"](agent=None, scenario=i["get_scenario_class"](args.scenario)())
        source = original.build_oracle_workflow(run_oracle=False)
        source.save_workflow(str(reference / "original_workflow.json"))
        save(output / "provenance.json", {"scenario_id": args.scenario, "source_root": str(ROOT),
             "raw_workflow_sha256": digest(source.to_dict()), "wofost_config": config,
             "production_source_sha256": digest(before), "review_sha256": digest(review),
             "policy_input": "registered public observations; private native states audit/experiments only"})
        compiler = CalibrationCompiler(args.scenario, config, reference, i, review=review)
        reference_result = compiler.compile(source)
        save(reference / "summary.json", {"scenario_id": args.scenario, **reference_result})
        result["reference"] = reference_result
        if reference_result.get("completion") == "feasible_operational_reference":
            if args.experiments != "none":
                result["sowing_comparison"] = run_sowing_comparison(
                    source, args.scenario, config, review, output, i)
                result["calibration"] = run_experiments(compiler, output, args.experiments, i)
            else:
                result["calibration"] = {"status": "reference_only_experiments_not_executed"}
        else:
            result["calibration"] = {"status": "reference_incomplete"}
    except Exception as exc:
        result["exception_type"] = type(exc).__name__
        result["message"] = str(exc)
        result["traceback"] = traceback.format_exc()
        result["calibration"] = {"status": "blocked_or_requires_policy_repair"}
    if compiler is not None:
        save(reference / "discovery_trace.json", compiler.trace)
        save(reference / "changes.json", compiler.changes)
        compiler.workflow.save_workflow(str(reference / "partial_workflow.json"))
    after = fingerprint()
    save(output / "source_after.json", after)
    result["source_changed_during_run"] = [k for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)]
    result["scenario_goal_status"] = (
        "explicit_runtime_adaptation" if review.get("runtime_adaptation") else
        "explicit_model_gaps" if review.get("semantic_model_gaps") else
        "no_specific_gap_identified_in_source_review")
    result["semantic_model_gaps"] = review.get("semantic_model_gaps", [])
    result["wall_seconds"] = time.monotonic() - start
    save(output / "summary.json", result)
    print(json.dumps(clean({k: v for k, v in result.items() if k not in {"traceback", "reference", "semantic_model_gaps"}}), ensure_ascii=False), flush=True)


def batch(args):
    ids = [s for s in (ROOT / "scripts/fullseason/formal_90_scenario_ids.txt").read_text().splitlines() if s.strip()]
    if args.scenario_ids:
        wanted = set(args.scenario_ids.split(","))
        ids = [s for s in ids if s in wanted]
        if wanted != set(ids):
            raise ValueError(f"Unknown formal IDs: {wanted - set(ids)}")
    if args.limit:
        ids = ids[:args.limit]
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": 1, "expected_scenario_count": len(ids),
                "formal90_full_scope": len(ids) == 90, "experiments": args.experiments,
                "cases": [{"scenario_id": s, "case_dir": "cases/" + s} for s in ids]}
    save(root / "manifest.json", manifest)
    save(root / "batch_source_before.json", fingerprint())
    env = os.environ.copy()
    env.pop("USER", None)
    env.update(PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="1",
               OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    def job(sid):
        folder = root / "cases" / sid
        folder.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, str(Path(__file__)), "--scenario", sid,
                   "--wofost-config", str(args.wofost_config.resolve()),
                   "--review-config", str(args.review_config.resolve()),
                   "--output-dir", str(folder), "--experiments", args.experiments]
        with (folder / "worker.log").open("w") as log:
            proc = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        summary = json.loads((folder / "summary.json").read_text()) if (folder / "summary.json").exists() else {}
        return {"scenario_id": sid, "return_code": proc.returncode,
                "calibration_status": summary.get("calibration", {}).get("status", "worker_failed"),
                "message": summary.get("message"), "wall_seconds": summary.get("wall_seconds")}
    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {pool.submit(job, sid): sid for sid in ids}
        for future in as_completed(jobs):
            row = future.result()
            rows.append(row)
            save(root / "batch_progress.json", {"completed": len(rows), "expected": len(ids), "rows": rows})
            print(json.dumps({"completed": len(rows), **row}, ensure_ascii=False), flush=True)
    save(root / "batch_source_after.json", fingerprint())


def replay_selected(args):
    """Run a delivered complete plan with its exact scenario/config adaptations."""
    from scripts.formal90_calibration_policy import CalibrationCompiler
    i = imports()
    case = args.replay_case.resolve()
    original = json.loads((case / "summary.json").read_text())
    config = json.loads((case / "config.json").read_text())
    review = json.loads((case / "case_review.json").read_text())
    source = json.loads((case / "source_before.json").read_text())
    if fingerprint() != source:
        raise ValueError("The calibrated plan's code/data fingerprint differs from this checkout; recalibrate before claiming exact replay")
    compiler = CalibrationCompiler(original["scenario_id"], config, args.output_dir.resolve(), i, review=review)
    workflow = i["Workflow"].load_workflow(str(case / "selected/workflow.json"))
    result = trial(compiler, workflow, args.output_dir.resolve() / "selected")
    expected = json.loads((case / "selected/summary.json").read_text())
    result["matches_delivered_final_state"] = result.get("final_hash") == expected.get("final_hash")
    result["matches_delivered_initial_state"] = result.get("initial_hash") == expected.get("initial_hash")
    save(args.output_dir.resolve() / "replay_verification.json", result)
    print(json.dumps(clean(result), ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--replay-case", type=Path)
    parser.add_argument("--scenario-ids")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--wofost-config", type=Path, default=ROOT / "configs/wofost/formal90_cultivar_mapping_v1.json")
    parser.add_argument("--review-config", type=Path, default=ROOT / "configs/oracles/formal90_review_v1.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--experiments", choices=("none", "omit", "bounded"), default="bounded")
    args = parser.parse_args()
    if sum(map(bool, (args.scenario, args.all, args.replay_case))) != 1:
        parser.error("Choose exactly one of --scenario, --all or --replay-case")
    if args.replay_case:
        replay_selected(args)
    elif args.all:
        batch(args)
    else:
        run_case(args)


if __name__ == "__main__":
    main()
