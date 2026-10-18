"""Step 4: run the LLM agent and the Jev agent on the 15 small farm scenarios.

Same limits for both agents; both get the approved English task text from
docs/jev/tasks_en/<scenario_id>.txt. Each run is a normal fairy.cli call and
writes the usual run bundle to <output-root>/<agent>__<scenario>__r<N>/.
Runs that already have a run_report.json are skipped, so the script can resume.

Usage:
    PYTHONPATH=. python scripts/jev_run_small15.py --output-root validation_runs/jev_mvp/step4 --repeats 3
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SCENARIOS = [
    "scenario_farm_world_drone_survey",
    "scenario_farm_world_drone_survey_plus",
    "scenario_farm_world_fertilizer",
    "scenario_farm_world_field_prep",
    "scenario_farm_world_field_prep_planting",
    "scenario_farm_world_field_prep_plus",
    "scenario_farm_world_harvest",
    "scenario_farm_world_irrigation",
    "scenario_farm_world_pesticide",
    "scenario_farm_world_pesticide_outbreak",
    "scenario_farm_world_pesticide_outbreak_plus",
    "scenario_farm_world_planting",
    "scenario_farm_world_planting_plus",
    "scenario_farm_world_survey_fertilizer_irrigation",
    "scenario_farm_world_survey_pesticide_irrigation",
]

AGENTS = {
    "farm_baseline_react": [
        "--controller", "farm_baseline_react", "--provider", "openai",
        "--model", "gpt-4o-mini", "--temperature", "0.1",
    ],
    "farm_jev": [
        "--controller", "farm_jev", "--provider", "typesafe", "--model", "jev-latest",
    ],
}


def run_one(args: argparse.Namespace, scenario: str, agent: str, repeat: int) -> None:
    cell = args.output_root / f"{agent}__{scenario}__r{repeat}"
    if (cell / f"{scenario}.run_report.json").exists():
        print(f"skip  {cell.name} (already done)", flush=True)
        return
    task = (args.tasks_dir / f"{scenario}.txt").read_text(encoding="utf-8")
    cell.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "fairy.cli", "-s", scenario, "--agent",
        *AGENTS[agent],
        "--max-tool-calls", str(args.max_tool_calls),
        "--timeout-seconds", str(args.timeout_seconds),
        "--scenario-kwargs", json.dumps({"scenario_input": task}),
        "--output-dir", str(cell),
    ]
    started = time.perf_counter()
    with open(cell / "stdout.log", "w", encoding="utf-8") as out, open(
        cell / "stderr.log", "w", encoding="utf-8"
    ) as err:
        code = subprocess.call(cmd, stdout=out, stderr=err)
    print(f"done  {cell.name}  exit={code}  {time.perf_counter() - started:.0f}s", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--tasks-dir", type=Path, default=Path("docs/jev/tasks_en"))
    parser.add_argument("--max-tool-calls", type=int, default=60)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--agents", default=",".join(AGENTS))
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--repeats", type=int, default=1, help="Runs per agent per scenario")
    args = parser.parse_args()

    for repeat in range(1, args.repeats + 1):
        for scenario in args.scenarios.split(","):
            for agent in args.agents.split(","):
                run_one(args, scenario, agent, repeat)


if __name__ == "__main__":
    main()
