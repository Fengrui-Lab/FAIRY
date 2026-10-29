"""Run the Jev settings on the 19 L3-mini full-season scenarios (review.md sections 13-16).

Every setting gets the same English task text from docs/jev/tasks_en/<scenario_id>.txt,
300 actions, 3600 s and PYTHONHASHSEED=0. Each run is a normal fairy.cli call and
writes the usual run bundle to <output-root>/<setting>__<scenario>/. Runs that
already have a run_report.json are skipped, so the script can resume.

Settings (folder names as in the shared run package):
    llm_alone_react                      gpt-6-luna, ReAct, no done check
    llm_alone_react_done_check           same with --done-check true (fair baseline)
    hybrid_jev_plus_llm                  Jev decides, gpt-6-luna when Jev is unsure
    ablation_hybrid_full_history         hybrid with --jev-state history
    ablation_hybrid_reflex               hybrid with --hybrid-mode reflex
    ablation_llm_with_jev_tool           gpt-6-luna, ReAct, done check, optional ask_jev tool
    ablation_llm_with_jev_tool_and_note  same with a note about Jev in the system prompt

Needs OPENAI_API_KEY and TYPESAFE_API_KEY. Score afterwards with
scripts/rebatch_fos_from_traces.py --root <output-root> --oracle-baselines <dir> --extrapolate.

Usage:
    PYTHONPATH=. python scripts/jev_run_l3mini.py --output-root validation_runs/jev_l3/runs \
        --settings hybrid_jev_plus_llm,llm_alone_react_done_check
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCENARIO_LIST = Path("scripts/fullseason/l3_mini_20_scenario_ids.txt")
SKIPPED = {"scenario_full_season_hb_hn50_hn84_hn58_mixed_stress"}  # no English task text

LLM = [
    "--parallel-tool-calls", "false", "--provider", "openai", "--model", "gpt-6-luna",
    "--reasoning-effort", "medium", "--max-output-tokens", "8192",
]
HYBRID = [
    "--controller", "farm_jev", "--provider", "typesafe", "--model", "jev-latest",
    "--parallel-tool-calls", "true", "--fallback-model", "gpt-6-luna", "--fallback-confidence", "0.4",
]
LLM_JEV_TOOL = [
    *LLM, "--controller", "farm_llm_jev", "--done-check", "true", "--jev-model", "jev-latest",
]

SETTINGS = {
    "llm_alone_react": LLM,
    "llm_alone_react_done_check": [*LLM, "--done-check", "true"],
    "hybrid_jev_plus_llm": HYBRID,
    "ablation_hybrid_full_history": [*HYBRID, "--jev-state", "history"],
    "ablation_hybrid_reflex": [*HYBRID, "--hybrid-mode", "reflex"],
    "ablation_llm_with_jev_tool": LLM_JEV_TOOL,
    "ablation_llm_with_jev_tool_and_note": [*LLM_JEV_TOOL, "--jev-prompt-note", "true"],
}


def l3mini_scenarios() -> list[str]:
    lines = SCENARIO_LIST.read_text(encoding="utf-8").splitlines()
    ids = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
    return [s for s in ids if s not in SKIPPED]


def run_one(args: argparse.Namespace, scenario: str, setting: str) -> None:
    cell = args.output_root / f"{setting}__{scenario}"
    if (cell / f"{scenario}.run_report.json").exists():
        print(f"skip  {cell.name} (already done)", flush=True)
        return
    task = (args.tasks_dir / f"{scenario}.txt").read_text(encoding="utf-8")
    cmd = [
        sys.executable, "-m", "fairy.cli", "-s", scenario, "--agent",
        "--max-tool-calls", str(args.max_tool_calls),
        "--timeout-seconds", str(args.timeout_seconds),
        "--output-dir", str(cell),
        "--scenario-kwargs", json.dumps({"agent_task_override": task}),
        *SETTINGS[setting],
    ]
    if args.dry_run:
        print(" ".join(a if " " not in a else "'<task text>'" for a in cmd))
        return
    cell.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8"}
    started = time.perf_counter()
    with open(cell / "stdout.log", "w", encoding="utf-8") as out, open(
        cell / "stderr.log", "w", encoding="utf-8"
    ) as err:
        code = subprocess.call(cmd, stdout=out, stderr=err, env=env)
    print(f"done  {cell.name}  exit={code}  {time.perf_counter() - started:.0f}s", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--tasks-dir", type=Path, default=Path("docs/jev/tasks_en"))
    parser.add_argument("--settings", default="hybrid_jev_plus_llm,llm_alone_react_done_check")
    parser.add_argument("--scenarios", default=None, help="Comma-separated; default: the 19 L3-mini")
    parser.add_argument("--max-tool-calls", type=int, default=300)
    parser.add_argument("--timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--dry-run", action="store_true", help="Print the commands, run nothing")
    args = parser.parse_args()

    settings = args.settings.split(",")
    unknown = [s for s in settings if s not in SETTINGS]
    if unknown:
        parser.error(f"unknown settings {unknown}; choose from {list(SETTINGS)}")
    scenarios = args.scenarios.split(",") if args.scenarios else l3mini_scenarios()
    for scenario in scenarios:
        for setting in settings:
            run_one(args, scenario, setting)


if __name__ == "__main__":
    main()
