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
        f"{prefix}_cost_per_run_usd": round(_mean([r["cost"] for r in runs]), 4),
        f"{prefix}_time_per_run_s": round(_mean([r["time"] for r in runs]), 1),
    }
    if prefix == "jev":
        cols["jev_avg_confidence"] = round(_mean([r["confidence"] for r in runs]), 2)
    return cols


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scoring", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    runs = load_runs(args.scoring)
    scenarios = sorted({scenario for scenario, _ in runs})
    rows = []
    for scenario in scenarios:
        row: dict[str, object] = {
            "scenario": scenario,
            "oracle_actions": _oracle_actions(scenario),
        }
        row.update(agent_columns("llm", runs[(scenario, "llm")]))
        row.update(agent_columns("jev", runs[(scenario, "jev")]))
        row.update({c: "" for c in ARE_COLUMNS})
        rows.append(row)

    average: dict[str, object] = {"scenario": "AVERAGE"}
    for key in rows[0]:
        if key == "scenario" or key in ARE_COLUMNS:
            continue
        values = [float(r[key]) for r in rows]
        total = key.endswith("_runs_hit_limit") or key.endswith("_runs")
        digits = 4 if key.endswith("_usd") else 2 if key == "jev_avg_confidence" else 1
        average[key] = int(sum(values)) if total else round(_mean(values), digits)
    average.update({c: "" for c in ARE_COLUMNS})
    rows.append(average)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {args.out} ({len(rows) - 1} scenarios + average)")


if __name__ == "__main__":
    main()
