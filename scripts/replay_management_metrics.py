#!/usr/bin/env python3
"""Replay the registered management scenarios through the primary FOS pipeline.

No LLM is invoked. See docs/management-replay-metrics.md for metric definitions.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _has_option(args, name):
    return any(a == name or a.startswith(name + "=") for a in args)


def primary_args(args):
    args = list(args)
    no_extrapolate = "--no-extrapolate" in args
    args = [a for a in args if a != "--no-extrapolate"]
    if no_extrapolate and "--extrapolate" in args:
        raise ValueError("Choose --extrapolate or --no-extrapolate")
    for option in ("--management-only", "--recursive"):
        if not _has_option(args, option):
            args.append(option)
    if not no_extrapolate and "--extrapolate" not in args:
        args.append("--extrapolate")
    for option, default in (("--workers", "3"), ("--extrapolation-max-days", "365")):
        if not _has_option(args, option):
            args.extend([option, default])
    return args


def verify_oracles(argv):
    from scripts.management_replay_metrics import (
        export_management_tables, management_scenario_ids, verify_one_oracle,
    )
    ap = argparse.ArgumentParser(description="Run and strictly replay all registered management Oracles; no LLM.")
    ap.add_argument("--verify-oracles", action="store_true")
    ap.add_argument("--out-root", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--extrapolation-max-days", type=int, default=365)
    args = ap.parse_args(argv)
    args.out_root = args.out_root.resolve()
    args.out_root.mkdir(parents=True, exist_ok=True)
    if args.workers < 1 or args.extrapolation_max_days < 1:
        ap.error("workers and extrapolation-max-days must be positive")
    # PCSE creates a shared user directory on its first import; do this serially.
    import pcse  # noqa: F401

    specs = [(sid, args.out_root, args.extrapolation_max_days)
             for sid in sorted(management_scenario_ids())]
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for job in as_completed([pool.submit(verify_one_oracle, spec) for spec in specs]):
            row = job.result()
            rows.append(row)
            print(json.dumps({k: row.get(k) for k in (
                "scenario", "status", "oracle_self_replay_passed", "verification_seconds", "error")},
                ensure_ascii=False), flush=True)
    rows.sort(key=lambda row: row.get("scenario", ""))
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with (args.out_root / "summary_v2.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    export_management_tables(rows, args.out_root)
    report = dict(total=len(rows), passed=sum(r["oracle_self_replay_passed"] for r in rows),
                  artifact_origin="oracle_replay_selftest", model_calls=0,
                  extrapolation_max_days=args.extrapolation_max_days,
                  results=[{k: row.get(k) for k in (
                      "scenario", "status", "oracle_self_replay_passed", "error")} for row in rows])
    (args.out_root / "oracle_verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Oracle self-replay: {report['passed']}/{report['total']}; {args.out_root}", flush=True)
    return 0 if report["passed"] == report["total"] else 1


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if "--list-scenarios" in args:
        from scripts.management_replay_metrics import management_scenario_ids
        print("\n".join(sorted(management_scenario_ids())))
        return 0
    if "--verify-oracles" in args:
        return verify_oracles(args)
    if "--help" not in args and "-h" not in args:
        import pcse  # noqa: F401
    from scripts.rebatch_fos_from_traces import main as rebatch_main
    sys.argv = [sys.argv[0], *primary_args(args)]
    return rebatch_main()


if __name__ == "__main__":
    raise SystemExit(main())
