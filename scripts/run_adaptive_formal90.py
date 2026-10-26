"""Run independent adaptive-coverage cases, without claiming paired yield gains.

Each subprocess discovers a state-dependent plan and checks its fresh replay.
Only a complete case with matching code/data, parameters and replay evidence is
resumed. Earlier incomplete or stale directories are archived before a retry.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from threading import Lock
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCOPE = "Adaptive coverage and fresh replay only; no per-case matched control or proven yield gain."
ENVIRONMENT_OVERRIDES = {"PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1",
                         "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


def read_json(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def runner_fingerprint():
    # Same inputs as the runner's provenance, without initializing any scene.
    from scripts.calibrate_formal90_oracles import fingerprint
    result = fingerprint()
    for path in sorted((ROOT / "scripts").glob("adaptive_*.py")):
        result[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def select_scenarios(review_path, requested=(), limit=None):
    review = read_json(review_path)
    if not isinstance(review, dict) or not isinstance(review.get("rows"), list):
        raise ValueError("Review must contain scenario rows")
    ids = [row["scenario_id"] for row in review["rows"]]
    if len(ids) != len(set(ids)) or any(not re.fullmatch(r"[A-Za-z0-9_\-]+", sid) for sid in ids):
        raise ValueError("Review has duplicate or unsafe scenario IDs")
    requested = [sid for value in requested for sid in value.split(",") if sid]
    if len(requested) != len(set(requested)):
        raise ValueError("Requested scenario IDs must be unique")
    unknown = set(requested) - set(ids)
    if unknown:
        raise ValueError("Unknown scenarios: " + ", ".join(sorted(unknown)))
    ids = requested or ids
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        ids = ids[:limit]
    return ids


def collect_case(sid, folder, expected_source, water_parameters=None, returncode=0):
    summary = read_json(folder / "summary.json", {})
    provenance = read_json(folder / "provenance.json", {})
    exact = (summary.get("replay_exact_physical_state") is True and
             summary.get("replay_exact_tool_trace_and_time") is True and
             summary.get("replay_error_count") == 0)
    metrics = summary.get("metrics") or {}
    complete = (summary.get("completion") == "feasible_operational_reference" and
                metrics.get("operational_complete") is True and exact)
    source_matches = provenance.get("source_sha256") == expected_source
    settings_match = (provenance.get("scenario_id") == sid and provenance.get("mode") == "adaptive"
                      and provenance.get("crop_management_enabled") is True
                      and provenance.get("water_parameters") == water_parameters)
    evidence = all((folder / name).is_file() for name in (
        "observed_workflow.json", "fresh_replay.json", "initial_snapshot.json",
        "discovery_final_snapshot.json", "replay_final_snapshot.json", "final_state.json"))
    error_evidence = (read_json(folder / "fresh_replay_errors.json") == [] and
                      read_json(folder / "fresh_replay_trace_differences.json") == [])
    if not summary:
        status, reason = "process_failed", "Runner produced no readable summary"
    elif not source_matches or not settings_match:
        status, reason = "stale_or_mismatched_output", "Code/data fingerprint or adaptive run settings differ"
    elif returncode:
        status, reason = "process_failed", f"Runner exited with code {returncode}"
    elif complete and evidence and error_evidence:
        status, reason = "completed_exact_replay", None
    elif summary.get("completion") == "blocked":
        status, reason = "blocked", summary.get("message", "Registered execution blocked")
    else:
        status, reason = "incomplete", summary.get("message", "Completion or fresh replay evidence is incomplete")
    final = read_json(folder / "final_state.json", {})
    water = {}
    for name, farm in final.get("farms", {}).items():
        regime = farm.get("world", {}).get("management_regime", {})
        water[name] = {key: regime.get(key) for key in
                       ("irrigation_quota_mm_total", "irrigation_used_mm_total")}
    return {"scenario_id": sid, "directory": str(folder), "status": status,
            "completion": summary.get("completion"), "block_reason": reason,
            "source_matches": source_matches, "settings_match": settings_match,
            "exact_replay": exact, "evidence_files_complete": evidence and error_evidence,
            "operational_complete": metrics.get("operational_complete", False),
            "safe_stored_kg": metrics.get("safe_stored_kg") if status == "completed_exact_replay" else None,
            "recorded_warehouse_grain_kg_not_comparable_if_incomplete": summary.get("warehouse_grain_kg"),
            "water_quota": water, "adaptive_water_actions": summary.get("adaptive_water_actions", 0),
            "adaptive_crop_actions": summary.get("adaptive_crop_actions", 0),
            "semantic_model_gaps": summary.get("semantic_model_gaps", []),
            "model_blocks": summary.get("model_blocks", []), "returncode": returncode}


def run_case(sid, root, source, *, python=sys.executable, water_parameter_file=None,
             water_parameters=None, resume=True, timeout=None, execute=subprocess.run):
    folder = root / "cases" / sid / "adaptive"
    if resume and folder.exists():
        old = collect_case(sid, folder, source, water_parameters)
        if old["status"] == "completed_exact_replay":
            return {**old, "resumed": True}
    if folder.exists():
        archive = folder.parent / "archive" / ("adaptive_" + str(time.time_ns()))
        archive.parent.mkdir(parents=True, exist_ok=True)
        folder.rename(archive)
    folder.mkdir(parents=True, exist_ok=True)
    command = [str(python), str(ROOT / "scripts/adaptive_management_runner.py"),
               "--scenario", sid, "--output-dir", str(folder), "--mode", "adaptive"]
    if water_parameter_file is not None:
        command += ["--water-parameters", str(water_parameter_file)]
    env = dict(os.environ)
    env.pop("USER", None)
    env.update(ENVIRONMENT_OVERRIDES)
    write_json(folder / "batch_invocation.json", {"command": command,
        "environment_overrides": {"USER": None, **ENVIRONMENT_OVERRIDES},
        "source_sha256": source, "scope": SCOPE})
    started = time.monotonic()
    failure, code = None, -1
    try:
        with (folder / "stdout.log").open("w") as stdout, (folder / "stderr.log").open("w") as stderr:
            process = execute(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                              stdout=stdout, stderr=stderr, timeout=timeout, check=False)
        code = process.returncode
    except subprocess.TimeoutExpired:
        failure = f"Runner timeout after {timeout} seconds"
    except OSError as exc:
        failure = f"Unable to launch runner: {exc}"
    result = collect_case(sid, folder, source, water_parameters, code)
    if failure:
        result.update(status="process_failed", block_reason=failure, safe_stored_kg=None)
    result.update(resumed=False, elapsed_seconds=round(time.monotonic() - started, 3))
    write_json(folder / "batch_result.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--review", type=Path, default=ROOT / "configs/oracles/formal90_review_v1.json")
    parser.add_argument("--scenarios", nargs="+", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--water-parameters", type=Path)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--timeout-seconds", type=float)
    args = parser.parse_args(argv)
    if args.workers <= 0 or args.timeout_seconds is not None and args.timeout_seconds <= 0:
        parser.error("workers and timeout must be positive")
    try:
        ids = select_scenarios(args.review, args.scenarios, args.limit)
        parameters = None
        if args.water_parameters:
            parameters = json.loads(args.water_parameters.read_text())
            if not isinstance(parameters, dict):
                raise ValueError("Water parameters must be a JSON object")
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    root = args.output_dir.resolve()
    source = runner_fingerprint()
    rows = {sid: {"scenario_id": sid, "status": "queued"} for sid in ids}
    lock = Lock()
    manifest = {"schema_version": 1, "scope": SCOPE, "scenario_ids": ids,
                "started_at": datetime.now(timezone.utc).isoformat(), "workers": args.workers,
                "source_sha256": source, "water_parameters": parameters,
                "batch_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "environment_overrides": {"USER": None, **ENVIRONMENT_OVERRIDES}}
    write_json(root / "manifest.json", manifest)

    def progress(sid=None, row=None):
        with lock:
            if sid is not None:
                rows[sid] = row
            payload = {"schema_version": 1, "scope": SCOPE, "total": len(ids),
                       "counts": dict(Counter(r["status"] for r in rows.values())),
                       "rows": [rows[s] for s in ids]}
            write_json(root / "progress.json", payload)

    def work(sid):
        progress(sid, {"scenario_id": sid, "status": "running"})
        try:
            result = run_case(sid, root, source, python=args.python,
                water_parameter_file=args.water_parameters.resolve() if args.water_parameters else None,
                water_parameters=parameters, resume=not args.no_resume, timeout=args.timeout_seconds)
        except Exception as exc:
            result = {"scenario_id": sid, "status": "driver_error", "block_reason": str(exc)}
        progress(sid, result)
        return result

    progress()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(work, sid) for sid in ids]
        for future in as_completed(futures):
            row = future.result()
            print(json.dumps({k: row.get(k) for k in ("scenario_id", "status", "safe_stored_kg", "block_reason")},
                             ensure_ascii=False), flush=True)
    result = read_json(root / "progress.json")
    result.update(finished_at=datetime.now(timezone.utc).isoformat(),
                  source_unchanged_during_batch=runner_fingerprint() == source)
    if not result["source_unchanged_during_batch"]:
        result["run_warning"] = "Source changed during the batch; current-code reproducibility is not established."
    write_json(root / "summary.json", result)
    return result


if __name__ == "__main__":
    main()
