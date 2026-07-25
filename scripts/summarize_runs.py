from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


FIELDS = [
    "run_dir",
    "run_type",
    "scenario_id",
    "controller_id",
    "system_prompt_mode",
    "model",
    "status",
    "stopped_reason",
    "success",
    "wall_time_seconds",
    "workflow_steps",
    "tool_call_count",
    "total_tokens",
    "cached_tokens",
    "warehouse_grain_kg",
    "harvested_ridges",
    "yield_g_m2",
]


def nested(data: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = data
    for key in path.split("."):
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def row_from_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    return {
        "run_dir": str(path.parent),
        "run_type": report.get("run_type"),
        "scenario_id": report.get("scenario_id"),
        "controller_id": report.get("controller_id"),
        "system_prompt_mode": report.get("system_prompt_mode"),
        "model": report.get("model"),
        "status": report.get("status"),
        "stopped_reason": report.get("stopped_reason"),
        "success": nested(report, "evaluation.validation.success"),
        "wall_time_seconds": nested(report, "metrics.wall_time_seconds"),
        "workflow_steps": nested(report, "metrics.workflow_steps"),
        "tool_call_count": nested(report, "metrics.tool_call_count"),
        "total_tokens": nested(report, "metrics.token_usage.total_tokens"),
        "cached_tokens": nested(report, "metrics.token_usage.cached_tokens"),
        "warehouse_grain_kg": nested(report, "outcome.inventory.warehouse_grain_kg"),
        "harvested_ridges": nested(report, "outcome.yield_recovery.harvested_ridges"),
        "yield_g_m2": nested(
            report,
            "outcome.yield_recovery.avg_recovered_yield_g_m2_at_market_moisture",
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize FAIRY run_report.json files")
    parser.add_argument("runs_dir", nargs="?", default="validation_runs")
    parser.add_argument("--csv", help="Optional CSV output path")
    args = parser.parse_args()

    rows = [
        row_from_report(path)
        for path in sorted(Path(args.runs_dir).glob("**/*.run_report.json"))
    ]
    if args.csv:
        output = Path(args.csv)
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    print("\t".join(FIELDS))
    for row in rows:
        print("\t".join("" if row.get(field) is None else str(row.get(field)) for field in FIELDS))


if __name__ == "__main__":
    main()
