#!/usr/bin/env python3
"""Author, replay and audit crop challenges using the ordinary public tools.

Candidates without outcome separation remain explicitly experimental. Numeric
thresholds are derived from paired controls, never from a desired yield bonus.
Use --sources comma-separated source IDs for development; no LLM service is used.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import fcntl
import json
import os
from pathlib import Path
import pprint
import random
import shutil
import sys
import tempfile
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.crop_challenges import artifacts
from fairy.scenarios.crop_challenges.catalog import CHALLENGES, TASKS
from fairy.scenarios.crop_challenges.runtime import measurements
from scripts.crop_challenge_policy import Recorder, RiceRecorder, maize_reference, rice_reference


def author_engine(sid):
    scenario = get_scenario_class(sid)()
    scenario._authoring = True
    scenario.setup()
    engine = Engine(None, scenario)
    engine.time_manager.real_time_passed = lambda: 0.
    return scenario, engine


def plan_from_steps(steps):
    return [{"tool_name": s.tool_name, "tool_args": s.tool_args,
             "duration_seconds": s.time_after - s.time_before} for s in steps]


def normalize(value):
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items() if k not in {"action_id", "op_id", "sha256"}}
    if isinstance(value, (tuple, list)):
        return [normalize(v) for v in value]
    return value


def authoring_digest():
    """Author provenance is checked offline; installed runtimes need no scripts."""
    root = Path(__file__).resolve().parent
    return artifacts.digest({name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                             for name in ("build_crop_challenges.py", "crop_challenge_policy.py")})


def transformed(step, policy, definition, active):
    """Matched action contrasts; the caller restores the exact reference time."""
    app, method = step.tool_name.split("__")
    args = copy.deepcopy(step.tool_args)
    if not active:
        return app, method, args
    crop, name = definition.crop, definition.name
    water = method == "irrigate"
    fertilizer = method in {"apply_fertigation", "apply_fertilizer"}
    protection = method in {"apply_pesticide", "apply_fungicide", "control_weeds"}
    repair = method in {"clear_channel", "repair_bund"}
    if crop == "maize":
        if policy == "omit" and (water or fertilizer):
            return None
        if policy == "water_only" and fertilizer or policy == "nitrogen_only" and water:
            return None
        if policy in {"uniform", "wrong_zone"} and (water or fertilizer):
            first, last = ("start", "end") if water else ("start_ridge", "end_ridge")
            count = args[last] - args[first] + 1
            if policy == "uniform":
                args[first], args[last] = 0, 63
                key = "hours" if water else "nutrient_amount"
                args[key] *= count / 64
            else:
                other_start = 0 if args[first] >= 22 else 44
                args[first], args[last] = other_start, other_start + count - 1
        # Same-weather no-harvest-at-the-window control; it does not fabricate
        # grain loss. Failure to deliver by the fixed deadline is the outcome.
        if policy == "miss_window" and method in {"harvest", "unload_grain", "dry_grain", "store_grain"}:
            return None
    else:
        if name == "zonal_crop_protection":
            if policy == "omit" and protection:
                return None
            if policy == "wrong_zone" and protection:
                args["plot_id"] = "p2" if args["plot_id"] == "p1" else "p1"
            if policy == "uniform" and protection:
                # Half-dose uniform chemical application is not an available
                # tool. This control is authored separately; never invent it.
                return app, method, args
        elif name == "infrastructure_water_priority":
            if policy == "omit" and repair:
                return None
        else:
            if policy == "omit" and (water or fertilizer):
                return None
            if policy == "water_only" and fertilizer or policy == "nitrogen_only" and water:
                return None
            if policy == "wrong_zone" and fertilizer:
                args["plot_id"] = "p2" if args["plot_id"] == "p1" else "p1"
                # Keep product kg equal across the 1000/1500 m² plots.
                args["kg_per_ha"] *= 1000/1500 if args["plot_id"] == "p2" else 1500/1000
        if policy == "miss_window" and method in {"harvest", "unload_grain", "dry_grain", "store_grain", "measure_grain_moisture"}:
            return None
    return app, method, args


def replay_control(sid, reference, policy):
    scenario, engine = author_engine(sid)
    recorder = Recorder(scenario, engine)
    marks = {v["step"]: label for label, v in reference.endpoints.items()}
    observed, errors = {}, []
    queued_extras = []
    deferred_repairs = []
    immediate_added = False
    definition = scenario.definition
    for index, step in enumerate(reference.workflow.dag.values()):
        before, after = step.time_before, step.time_after
        if recorder.now() < before:
            recorder.call(recorder.system, "advance_time", seconds=before-recorder.now())
        offset = 8*3600 if definition.crop == "maize" else 0
        if recorder.now() > before + 1e-5 and int((recorder.now()+offset)//86400) != int((before+offset)//86400):
            errors.append({"step": index, "error": "control crossed a non-ablated operation's native day"})
        entry = transformed(step, policy, definition, index >= reference.boundaries["diagnosis"])
        method = step.tool_name.split("__")[1]
        active = index >= reference.boundaries["diagnosis"]
        if definition.crop == "rice" and active:
            if policy == "uniform" and definition.name == "zonal_crop_protection" and method in {"apply_pesticide", "apply_fungicide"}:
                app, action, args = entry
                args = dict(args, plot_id="p2" if args["plot_id"] == "p1" else "p1")
                queued_extras.append((app, action, args))
            if definition.name == "infrastructure_water_priority":
                if policy == "irrigate_first" and method in {"clear_channel", "repair_bund"}:
                    deferred_repairs.append(entry)
                    entry = None
                elif policy == "irrigate_first" and method == "irrigate" and deferred_repairs:
                    queued_extras.extend(deferred_repairs)
                    deferred_repairs = []
                elif policy == "repair_all_first" and method == "irrigate" and step.tool_args.get("water_mm") == 20.:
                    entry = None
        # Extra policy operations use the next waiting slot, leaving all later
        # non-ablated actions on the same absolute timeline.
        if method == "advance_time" and after-before > 12*3600:
            if policy == "immediate" and not immediate_added and active and definition.crop == "maize":
                day = (before-scenario._source_start)/86400
                if 39 <= day <= 43:
                    queued_extras.append(("FieldOpsApp", "irrigate", {"start": 0, "end": 63, "hours": 4.}))
                    immediate_added = True
            for extra_app, extra_method, extra_args in queued_extras:
                try:
                    recorder.call(extra_app, extra_method, **extra_args)
                except (ValueError, RuntimeError) as exc:
                    errors.append({"step": index, "error": str(exc)})
            queued_extras = []
            entry = None
        # Primary biological outcomes do not depend on the managed reference's
        # grain-bin schedule, which can be illegal after a yield intervention.
        if definition.metric == "biological_dry_kg" and step.tool_name.split("__")[1] in {"harvest", "unload_grain", "dry_grain", "store_grain"}:
            entry = None
        if definition.metric == "biological_dry_kg" and method == "measure_grain_moisture" and step.tool_args.get("batch_id"):
            entry = None
        try:
            if entry:
                app, method, args = entry
                if definition.crop == "rice" and method == "refuel":
                    status = recorder.call("PaddyMachineryApp", "get_machine_status", machine_id=args["machine_id"])["machines"][0]
                    args = dict(args, liters=min(args["liters"], status["tank_capacity_liters"]-status["fuel_liters"]))
                    if args["liters"] <= 1e-8:
                        entry = None
                if entry:
                    recorder.call(app, method, **args)
        except (ValueError, RuntimeError) as exc:
            errors.append({"step": index, "error": str(exc)})
        if recorder.now() < after:
            recorder.call(recorder.system, "advance_time", seconds=after-recorder.now())
        if index+1 in marks:
            observed[marks[index+1]] = measurements(scenario)
    observed["season"] = measurements(scenario)
    return {"policy": policy, "errors": errors, "matched_time": abs(recorder.now()-reference.now()) < 1e-5,
            "matched_weather": weather_digest(scenario) == weather_digest(reference.scenario),
            "outcomes": observed}


def weather_digest(scenario):
    if scenario.crop_name == "maize":
        from fairy.apps.farm_world import FarmWorldApp
        runs = scenario.get_typed_app(FarmWorldApp).physics.crop_backend._runs
        forcing = {rid: [(e["day"], e["weather"]) for e in run.journal] for rid, run in runs.items()}
    else:
        from fairy.apps.paddy.world import PaddyWorldApp
        backends = scenario.get_typed_app(PaddyWorldApp).backends
        forcing = {pid: [(e["day"], e["weather"]) for e in b.journal if e["kind"] == "day"] for pid, b in backends.items()}
    return artifacts.digest(forcing)


def gates_for(definition, level, metric, reference, controls):
    values = [c["outcomes"].get("season" if level == "L3" else "diagnosis") for c in controls]
    valid = [(v, c) for v, c in zip(values, controls)
             if v is not None and not c["errors"] and c["matched_time"] and c["matched_weather"]]
    usable = [v for v, _ in valid]
    if not usable:
        return [], "experimental", "No valid matched control"
    if definition.name == "staggered_water_priority" and not any(
            c["policy"] in {"uniform", "wrong_zone"} for _, c in valid):
        return [], "experimental", "Allocation priority needs a feasible uniform or wrong-zone contrast"
    if metric == "water_used":
        # Water minimization is meaningful only with comparable crop output.
        comparable = [v for v in usable
                      if v["biological_dry_kg"] >= .99 * reference["biological_dry_kg"]
                      and reference["biological_dry_kg"] >= .99 * v["biological_dry_kg"]]
        if not comparable or min(v[metric] for v in comparable) <= reference[metric] + 1e-6:
            return [], "experimental", "Water saving with yield preservation not demonstrated"
        threshold = (reference[metric] + min(v[metric] for v in comparable)) / 2
        yield_floor = .99 * max(reference["biological_dry_kg"], max(v["biological_dry_kg"] for v in comparable))
        return [{"metric": metric, "direction": "lower", "threshold": threshold},
                {"metric": "biological_dry_kg", "direction": "higher", "threshold": yield_floor}], "calibrated", ""
    strongest = max(v[metric] for v in usable)
    if reference[metric] <= strongest + max(1e-6, abs(reference[metric]) * 1e-6):
        return [], "experimental", "Reference does not separate from the strongest matched control"
    return [{"metric": metric, "direction": "higher", "threshold": (reference[metric]+strongest)/2}], "calibrated", ""


def build_source(sid, root):
    definition = CHALLENGES[sid]
    scenario, engine = author_engine(sid)
    recorder = (Recorder if definition.crop == "maize" else RiceRecorder)(scenario, engine)
    recorder.save("initial")
    (maize_reference if definition.crop == "maize" else rice_reference)(recorder)
    scenario.workflow = recorder.workflow
    validation = scenario.validate()
    if not validation.success:
        raise RuntimeError(f"Reference failed: {sid}: {validation.message}")
    print(f"{sid}: reference {len(recorder.workflow)} tools", flush=True)
    controls = []
    for policy in definition.controls:
        control = replay_control(sid, recorder, policy)
        controls.append(control)
        print(f"  {policy}: {control['outcomes']['season'][definition.metric]:.4f}, errors={len(control['errors'])}", flush=True)
    steps = list(recorder.workflow.dag.values())
    data = {"schema_version": artifacts.SCHEMA, "source_id": sid,
            "source_digest": artifacts.source_digest(definition.crop),
            "authoring_digest": authoring_digest(),
            "controls": controls, "checkpoints": recorder.checkpoints, "tasks": {},
            "weather_digest": weather_digest(scenario)}
    # Public observations establish whether the proposed N-diagnosis mechanism
    # actually had a usable window; missing/unknown samples never count as low.
    if definition.crop == "rice":
        rows = [s.content for s in steps if s.tool_name.endswith("__inspect_crop")]
        data["nitrogen_observability"] = {
            pid: {"applicable_dates": sorted({r["nitrogen_signal_date"] for r in rows
                  if r.get("plot_id") == pid and r.get("nitrogen_signal_applicable")}),
                  "elevated_dates": sorted({r["nitrogen_signal_date"] for r in rows
                  if r.get("plot_id") == pid and r.get("nitrogen_stress_signal") == "elevated"})}
            for pid in ("p1", "p2")}
    maize_plans = {}
    for task_id, (source, level, label) in TASKS.items():
        if source != sid:
            continue
        begin = 0 if level == "L3" else recorder.boundaries[label]
        end = len(steps) if level == "L3" else recorder.endpoints[label]["step"]
        reference = measurements(scenario) if level == "L3" else recorder.endpoints[label]["measurements"]
        metric = definition.metric if level == "L3" else ("stored_kg_at_14pct" if "harvest" in definition.name else "biomass_dry_kg")
        gates, status, reason = gates_for(definition, level, metric, reference, controls)
        if level == "L1":
            # Execution skills assert exact target coverage/ledger transfer or
            # local repair/protection, independently of source yield calibration.
            gates, status, reason = [], "calibrated", "Action contract; not an agronomic yield claim"
        if definition.name == "zonal_water_n_allocation":
            # A separate observability experiment is required before this
            # candidate can claim a publicly solvable N-diagnosis mechanism.
            status, reason = "experimental", "Juvenile nitrogen observability gate pending"
        checkpoint = recorder.checkpoints["initial" if level == "L3" else label]
        plan = plan_from_steps(steps[begin:end])
        # Budget the window itself, rather than granting a short split all the
        # inputs intended for the remaining season. Outcomes allow other paths.
        resource_keys = ("water_used", "fertilizer_used", "energy_used_kwh",
                         "insecticide_used_liters", "fungicide_used_liters", "repair_used_kg")
        initial = measurements_from_checkpoint(scenario, checkpoint)
        budgets = {key: max(0., reference[key] - initial[key]) * (1.01 if level == "L1" else 1.1)
                   for key in resource_keys if key in reference} if level != "L3" else {}
        endpoint_state = scenario.export_checkpoint("endpoint") if level == "L3" else recorder.endpoints[label]["state"]
        contract = ""
        if level == "L1":
            actions = [s for s in plan if s["tool_name"].split("__")[1] in
                       {"irrigate", "apply_fertigation", "apply_pesticide", "apply_fungicide", "control_weeds", "clear_channel"}]
            contract = "执行目标（完成后复查）：" + json.dumps(actions, ensure_ascii=False)
        task = dict(status=status, calibration_note=reason, reference=reference, gates=gates,
                    window_budgets=budgets, endpoint_state_digest=artifacts.digest(normalize(endpoint_state)),
                    initial_checkpoint_digest=artifacts.digest(checkpoint), plan_digest=artifacts.digest(plan),
                    briefing=f"本任务级别{level}；观察终点为{reference['day']}。窗口增量预算：{json.dumps(budgets)}。"
                             + "水额单位：玉米为全田面积加权mm，水稻为取水m³；肥料为产品kg；其余单位见字段名。"
                             + "结果门槛（higher为至少、lower为至多）：" + json.dumps(gates)
                             + contract
                             + ("本候选尚未通过农艺校准，不计入正式成功率。" if status != "calibrated" else ""))
        if definition.crop == "maize":
            maize_plans[task_id] = plan
        else:
            task["plan"] = plan
        data["tasks"][task_id] = task
    return data, maize_plans


def measurements_from_checkpoint(scenario, checkpoint):
    """Read opening ledgers without replaying the season for each split."""
    if scenario.crop_name == "maize":
        state = checkpoint["farm"]["farm_world_state"]
        regime = state["management_regime"]
        return {"water_used": regime["irrigation_used_mm_total"],
                "fertilizer_used": regime["fertilizer_used_kg"]}
    field = checkpoint["field"]
    supply = next(c for c in field["channels"] if c["channel_id"] == "supply")
    return {"water_used": supply["withdrawn_m3"], "fertilizer_used": field["fertilizer_applied_kg"],
            "energy_used_kwh": field["energy_used_kwh"], "repair_used_kg": field["repair_used_kg"],
            "insecticide_used_liters": field["chemicals_used"]["insecticide_liters"],
            "fungicide_used_liters": field["chemicals_used"]["fungicide_liters"]}


def verify_source(sid, root):
    """Pure build, real execution, and independent replay all use production Engine."""
    data = artifacts.load(sid)
    if data.get("reviewed_by_digest", data["authoring_digest"]) != authoring_digest():
        raise ValueError("Authoring code changed; rebuild challenge evidence")
    result = {}
    for task_id in data["tasks"]:
        scenario = get_scenario_class(task_id)()
        scenario.setup()
        engine = Engine(None, scenario)
        engine.time_manager.real_time_passed = lambda: 0.
        before = normalize(scenario.export_checkpoint("verify"))
        plan = engine.build_oracle_workflow(run_oracle=False)
        if normalize(scenario.export_checkpoint("verify")) != before:
            raise RuntimeError("Building a challenge plan mutated the world")
        engine.build_oracle_workflow(run_oracle=True)
        captured = artifacts.digest(normalize(scenario.export_checkpoint("endpoint")))
        if captured != data["tasks"][task_id]["endpoint_state_digest"]:
            raise RuntimeError(f"Captured execution differs from source continuation: {task_id}")
        replay = get_scenario_class(task_id)()
        replay.setup()
        other = Engine(None, replay)
        other.time_manager.real_time_passed = lambda: 0.
        other.replay_workflow(plan)
        if artifacts.digest(normalize(replay.export_checkpoint("endpoint"))) != captured:
            raise RuntimeError(f"Independent physical replay differs: {task_id}")
        actual = measurements(replay)
        expected = data["tasks"][task_id]["reference"]
        if actual != expected:
            differences = {k: (actual[k], expected[k]) for k in actual if actual[k] != expected[k]}
            raise RuntimeError(f"Reference replay diverged for {task_id}: {differences}")
        validation = other.evaluate()
        if data["tasks"][task_id]["status"] == "calibrated" and not validation.success:
            raise RuntimeError(f"Task validation failed: {task_id}: {validation.to_dict()}")
        result[task_id] = {"replay_verified": True, "pure_build": True, "source_continuation_verified": True,
                           "physical_state_digest": captured, "success": validation.success,
                           "status": data["tasks"][task_id]["status"]}
        print(f"  verified {task_id}: {result[task_id]['status']}", flush=True)
    return result


def review_calibration(data):
    """Reassess frozen observations without inventing new trajectories.

    Keep the original authoring provenance. A review changes only the decision
    criteria/briefing; the ordinary verifier still replays every task in full.
    Use a full build to change the policy, initial world, or controls.
    """
    definition = CHALLENGES[data["source_id"]]
    previous = {}
    for sid, task in data["tasks"].items():
        _, level, _ = TASKS[sid]
        previous[sid] = {"status": task["status"], "gates": task["gates"], "note": task["calibration_note"]}
        if level == "L1" or definition.name == "zonal_water_n_allocation":
            continue
        metric = definition.metric if level == "L3" else ("stored_kg_at_14pct" if "harvest" in definition.name else "biomass_dry_kg")
        gates, status, note = gates_for(definition, level, metric, task["reference"], data["controls"])
        marker = "结果门槛（higher为至少、lower为至多）："
        prefix, separator, suffix = task["briefing"].partition(marker)
        if not separator:
            raise ValueError(f"Missing briefing gate marker: {sid}")
        _, end = json.JSONDecoder().raw_decode(suffix)
        task["briefing"] = prefix + marker + json.dumps(gates) + suffix[end:]
        warning = "本候选尚未通过农艺校准，不计入正式成功率。"
        task["briefing"] = task["briefing"].replace(warning, "") + (warning if status == "experimental" else "")
        task.update(gates=gates, status=status, calibration_note=note)
    data.setdefault("calibration_reviews", []).append({"reviewer_code_digest": authoring_digest(), "previous": previous})
    data["reviewed_by_digest"] = authoring_digest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", default=",".join(CHALLENGES))
    parser.add_argument("--output-root", type=Path, default=artifacts.ARTIFACT_ROOT)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--review-only", action="store_true", help="Recompute gates from frozen evidence, then independently replay all tasks")
    args = parser.parse_args()
    ids = args.sources.split(",")
    if any(sid not in CHALLENGES for sid in ids):
        parser.error("Unknown source ID")
    if args.verify_only and args.review_only:
        parser.error("Choose either --verify-only or --review-only")
    args.output_root.mkdir(parents=True, exist_ok=True)
    for sid in ids:
        if args.verify_only:
            artifacts.ARTIFACT_ROOT = args.output_root
            verify_source(sid, args.output_root)
            continue
        if args.review_only:
            artifacts.ARTIFACT_ROOT = args.output_root
            data = artifacts.load(sid)
            additions = artifacts.load_maize_plans(sid, data) if CHALLENGES[sid].crop == "maize" else {}
            review_calibration(data)
        # Candidate artifacts are invisible to normal runtime until every task
        # passes pure build, captured execution, and independent physical replay.
        with tempfile.TemporaryDirectory(prefix="fairy-challenge-") as temporary:
            stage = Path(temporary)
            artifacts.ARTIFACT_ROOT = stage
            if not args.review_only:
                rng = random.Random(sid)
                with patch("uuid.uuid4", lambda: uuid.UUID(int=rng.getrandbits(128))):
                    data, additions = build_source(sid, stage)
            if additions:
                raw = ("# Reviewed public-tool plans, generated offline.\nPLANS = "
                       + pprint.pformat(additions, width=115, sort_dicts=False) + "\n").encode()
                (stage / f"{sid}.plan.py").write_bytes(raw)
                data["python_plan_sha256"] = hashlib.sha256(raw).hexdigest()
            candidate = {"schema_version": artifacts.SCHEMA, "files": {}}
            artifacts.write(stage, sid, data, candidate)
            verification = verify_source(sid, stage)
            (stage / f"{sid}.verification.json").write_text(json.dumps(verification, indent=2)+"\n")
            # Independent source builds may run concurrently; merge under a
            # short lock and publish the checksum manifest last (fail closed).
            with (args.output_root / ".publish.lock").open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                path = args.output_root / "manifest.json"
                manifest = json.loads(path.read_text()) if path.exists() else candidate
                if manifest.get("schema_version") != artifacts.SCHEMA:
                    manifest = {"schema_version": artifacts.SCHEMA, "files": {}}
                for file in stage.glob(f"{sid}.*"):
                    target = args.output_root / file.name
                    temporary_target = target.with_suffix(target.suffix + ".tmp")
                    shutil.copyfile(file, temporary_target)
                    os.replace(temporary_target, target)
                manifest["files"].update(candidate["files"])
                temporary_manifest = path.with_suffix(".tmp")
                temporary_manifest.write_bytes(artifacts.canonical(manifest)+b"\n")
                os.replace(temporary_manifest, path)


if __name__ == "__main__":
    main()
