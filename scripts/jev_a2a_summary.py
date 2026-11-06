"""One line per A2A run: outcome, delegation counts, tokens and cost.

Reads every *.run_report.json under --root, and grain loss from scoring
summary_v2.csv when --scoring is given (rebatch_fos_from_traces.py output).

Prices: gpt-6-luna $0.10 / M input, $0.01 / M cached, $0.50 / M output; Jev $0.042 / M input.
In hybrid experts the experts' cost is split into Jev and the local LLM by each call's source.

Usage: python scripts/jev_a2a_summary.py --root <runs dir> [--scoring <summary_v2.csv>] [--csv out.csv]
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
from pathlib import Path


def llm_cost(tokens: dict) -> float:
    prompt = int(tokens.get("prompt_tokens") or 0)
    cached = int(tokens.get("cached_tokens") or 0)
    output = int(tokens.get("completion_tokens") or 0)
    return ((prompt - cached) * 0.10 + cached * 0.01 + output * 0.50) / 1e6


def row_for(path: Path, scores: dict) -> dict:
    report = json.loads(path.read_text(encoding="utf-8"))
    metrics = report.get("metrics") or {}
    a2a = report.get("a2a") or {}
    traces = a2a.get("expert_traces") or []
    jobs = [j for t in traces for j in t.get("jobs", [])]
    statuses = collections.Counter(j.get("status") or ("limit" if j.get("limit") else "?") for j in jobs)
    expert_tokens = (a2a.get("expert_metrics") or {}).get("token_usage") or {}
    metrics_all = [m for t in traces for m in t.get("runtime_metrics", [])]
    local = {
        key: sum(
            int((m.get("tokens") or {}).get(key) or 0)
            for m in metrics_all if m.get("source") == "llm_fallback"
        )
        for key in ("prompt_tokens", "cached_tokens", "completion_tokens")
    }
    main_tokens = metrics.get("token_usage") or {}
    kind = a2a.get("expert_kind")
    main_cost = llm_cost(main_tokens)
    if kind == "jev":
        jev_input = int(expert_tokens.get("prompt_tokens") or 0) - local["prompt_tokens"]
        expert_cost = jev_input * 0.042 / 1e6 + llm_cost(local)
    else:
        expert_cost = llm_cost(expert_tokens)
    score = scores.get(path.parent.name, {})
    actions = sum(1 for j in jobs for _ in j.get("tools", []))
    return {
        "run": path.parent.name,
        "status": report.get("status"),
        "stop": report.get("stop_reason") or report.get("stopped_reason"),
        "minutes": round(float(report.get("wall_time_seconds") or 0) / 60, 1),
        "actions_total": report.get("tool_call_count") or metrics.get("tool_call_count"),
        "jobs": len(jobs),
        "expert_actions": actions or sum(j.get("actions", 0) for j in jobs),
        "job_status": dict(statuses),
        "jev_requests": sum(j.get("jev_requests") or 0 for j in jobs),
        "local_llm_calls": sum(1 for m in metrics_all if m.get("source") == "llm_fallback"),
        "cost_local_llm": round(llm_cost(local), 3),
        "cost_main": round(main_cost, 3),
        "cost_experts": round(expert_cost, 3),
        "cost_total": round(main_cost + expert_cost, 3),
        "grain_loss_pct": score.get("recovered_yield_loss(%)"),
        "missing_ridges": score.get("farm_fos_v2_missing_harvest_ridges"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--scoring", type=Path)
    parser.add_argument("--csv", type=Path)
    args = parser.parse_args()
    scores: dict = {}
    if args.scoring and args.scoring.exists():
        with args.scoring.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                for key in ("cell", "cell_id", "cell_dir", "run_dir"):
                    if row.get(key):
                        scores[Path(row[key]).name] = row
    rows = [row_for(p, scores) for p in sorted(args.root.rglob("*.run_report.json"))]
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
    if args.csv and rows:
        with args.csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    main()
