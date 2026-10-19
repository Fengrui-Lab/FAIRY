"""Step 5: Jev vs LLM comparison table (one row per scenario + average).

Reads the scored runs (rebatch summary_v2.csv) and each run's run_report.json,
and writes a CSV with empty columns for ARE results to be added later.

Score columns use FAIRY's existing exact-argument comparison with the oracle:
  step_match = core_path_correctness (how close the action sequence is)
  coverage   = coverage_v1 (share of the oracle's distinct actions performed)
  order      = ktc (whether shared actions come in the oracle's order)

Cost: LLM gpt-4o-mini $0.15 / $0.60 per million input / output tokens (price
table in scripts/iclr_validation_runner.py); Jev $0.042 per million input
tokens, output free (docs.typesafe.ai/models).

"Stuck" run: the same action with the same arguments 3 or more times in a row
(the oracle never repeats an identical action even twice in these scenarios).

Rows: one per scenario, then AVERAGE (all 15), AVERAGE_JEV_WON (scenarios where
Jev's mean step match is higher) and AVERAGE_LLM_WON (the rest). Aggregate rows
pool the runs of their scenarios (3 per scenario, so equal weight); counts are
totals.

Usage:
    PYTHONPATH=. python scripts/jev_compare_table.py \
        --scoring validation_runs/jev_mvp/step4_final_scoring/summary_v2.csv \
        --out docs/jev/results/comparison.csv
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
from collections import defaultdict
from pathlib import Path

from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class

AGENTS = {"farm_baseline_react": "llm", "farm_jev": "jev"}
PRICE = {
    "llm": {"in": 0.15, "out": 0.60},
    "jev": {"in": 0.042, "out": 0.0},
}
ARE_COLUMNS = [
    "are_step_match", "are_coverage", "are_actions", "are_cost_per_run_usd", "are_time_per_run_s",
]
STUCK_REPEATS = 3


def _longest_identical_repeat(workflow_path: Path) -> int:
    workflow = json.load(open(workflow_path, encoding="utf-8"))
    best = current = 0
    previous = None
    for step in workflow.values():
        if step["op_type"] not in ("TOOL", "TOOL_ERROR"):
            continue
        key = step["tool_name"] + json.dumps(step["tool_args"] or {}, sort_keys=True)
        current = current + 1 if key == previous else 1
        previous = key
        best = max(best, current)
    return best


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _oracle_actions(scenario_id: str) -> int:
    with contextlib.redirect_stdout(io.StringIO()):
        wf = Engine(agent=None, scenario=get_scenario_class(scenario_id)()).build_oracle_workflow(
            run_oracle=False
        )
    return sum(1 for step in wf.dag.values() if step.tool_name)


def load_runs(scoring_csv: Path) -> dict[tuple[str, str], list[dict]]:
    runs: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in csv.DictReader(open(scoring_csv, encoding="utf-8")):
        cell_dir = row["cell_dir"]
        agent, scenario, _ = os.path.basename(cell_dir.rstrip("/\\")).split("__")
        report = json.load(open(Path(cell_dir) / f"{scenario}.run_report.json", encoding="utf-8"))
        metrics = report["metrics"]
        tokens = metrics["token_usage"]
        who = AGENTS[agent]
        runs[(scenario, who)].append(
            {
                "step_match": float(row["core_path_correctness(%)"] or 0),
                "coverage": float(row["coverage_v1(%)"] or 0),
                "order": float(row["ktc(%)"] or 0),
                "actions": metrics["tool_call_count"],
                "hit_limit": report["stopped_reason"] == "max_tool_calls",
                "cost": tokens["prompt_tokens"] * PRICE[who]["in"] / 1e6
                + tokens["completion_tokens"] * PRICE[who]["out"] / 1e6,
                "time": metrics["wall_time_seconds"],
                "confidence": (report.get("controller_telemetry") or {}).get(
                    "avg_action_confidence"
                ),
                "stuck": _longest_identical_repeat(
                    Path(cell_dir) / f"{scenario}.agent_workflow.json"
                )
                >= STUCK_REPEATS,
            }
        )
    return runs


def agent_columns(prefix: str, runs: list[dict]) -> dict[str, object]:
    cols = {
        f"{prefix}_runs": len(runs),
        f"{prefix}_step_match": round(_mean([r["step_match"] for r in runs]), 1),
        f"{prefix}_step_match_min": round(min(r["step_match"] for r in runs), 1),
        f"{prefix}_step_match_max": round(max(r["step_match"] for r in runs), 1),
        f"{prefix}_coverage": round(_mean([r["coverage"] for r in runs]), 1),
        f"{prefix}_order": round(_mean([r["order"] for r in runs]), 1),
        f"{prefix}_actions": round(_mean([r["actions"] for r in runs]), 1),
        f"{prefix}_runs_hit_limit": sum(r["hit_limit"] for r in runs),
        f"{prefix}_runs_stuck": sum(r["stuck"] for r in runs),
        f"{prefix}_cost_per_run_usd": round(_mean([r["cost"] for r in runs]), 4),
        f"{prefix}_time_per_run_s": round(_mean([r["time"] for r in runs]), 1),
    }
    if prefix == "jev":
        stuck = [r["confidence"] for r in runs if r["stuck"]]
        other = [r["confidence"] for r in runs if not r["stuck"]]
        cols["jev_avg_confidence"] = round(_mean([r["confidence"] for r in runs]), 2)
        cols["jev_confidence_stuck_runs"] = round(_mean(stuck), 2) if stuck else ""
        cols["jev_confidence_other_runs"] = round(_mean(other), 2) if other else ""
    return cols


def build_row(name: str, scenarios: list[str], runs, oracle_actions: dict[str, int]) -> dict:
    row: dict[str, object] = {
        "scenario": name,
        "scenarios": len(scenarios),
        "oracle_actions": round(_mean([oracle_actions[s] for s in scenarios]), 1),
    }
    for prefix in ("llm", "jev"):
        row.update(agent_columns(prefix, [r for s in scenarios for r in runs[(s, prefix)]]))
    row.update({c: "" for c in ARE_COLUMNS})
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scoring", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    runs = load_runs(args.scoring)
    scenarios = sorted({scenario for scenario, _ in runs})
    oracle_actions = {s: _oracle_actions(s) for s in scenarios}
    rows = [build_row(s, [s], runs, oracle_actions) for s in scenarios]
    jev_won = [r["scenario"] for r in rows if r["jev_step_match"] > r["llm_step_match"]]
    llm_won = [s for s in scenarios if s not in jev_won]
    rows.append(build_row("AVERAGE", scenarios, runs, oracle_actions))
    rows.append(build_row("AVERAGE_JEV_WON", jev_won, runs, oracle_actions))
    rows.append(build_row("AVERAGE_LLM_WON", llm_won, runs, oracle_actions))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {args.out} ({len(scenarios)} scenarios + 3 aggregate rows)")


if __name__ == "__main__":
    main()
