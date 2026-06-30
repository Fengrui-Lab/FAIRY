from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "scripts" / "iclr_validation_runner.py"
KWOO_CONTEXT_ENV_VAR = "FARM_FAIRY_KWOO_CONTEXT_PATH"

DEFAULT_SCENARIOS = [
    "scenario_full_season_hb_heihe43_early_density_weed_nutrient_recovery",
    "scenario_full_season_hb_coldspring_planting_window_heihe50",
    "scenario_full_season_hb_wetcold_high_residue_establishment",
    "scenario_full_season_heinong84_staggered_planting",
]

GROUPS: dict[str, object] = {
    "detail_false": False,
    "detail_kwoo": "kwoo",
    "detail_library": "library",
    "detail_true": True,
}


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parser = argparse.ArgumentParser(
        description=(
            "Run L3 context ablation through scripts/iclr_validation_runner.py "
            "for no-context, Kwoo-context, library-context, and human-context."
        )
    )
    parser.add_argument(
        "--groups",
        default=",".join(GROUPS),
        help="Comma-separated subset of detail_false,detail_kwoo,detail_library,detail_true.",
    )
    parser.add_argument(
        "--scenarios",
        default=",".join(DEFAULT_SCENARIOS),
        help="Comma-separated scenario IDs.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "rebatch_outputs" / f"l3_context_ablation_{stamp}",
    )
    parser.add_argument("--families", default="farm_baseline_react")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--cost-cap-dollars", type=float, default=10.0)
    parser.add_argument("--max-concurrent", type=int, default=1)
    parser.add_argument("--cell-timeout-s", type=int, default=1800)
    parser.add_argument("--cell-timeout-grace-s", type=int, default=120)
    parser.add_argument("--agent-max-iterations", type=int, default=300)
    parser.add_argument("--wait-for-user-input-timeout", type=float, default=5.0)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--kwoo-context-file",
        type=Path,
        default=Path("scripts/kwoo_expansion_result.json"),
        help="JSON/text file used when detailed_briefing='kwoo'.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without launching agent runs.",
    )
    return parser.parse_args()


def build_command(args: argparse.Namespace, group: str) -> list[str]:
    scenario_kwargs = json.dumps(
        {"detailed_briefing": GROUPS[group]}, ensure_ascii=False, separators=(",", ":")
    )
    cmd = [
        sys.executable,
        str(RUNNER),
        "--phase",
        f"l3_context_{group}",
        "--output-root",
        str(args.output_root / group),
        "--families",
        args.families,
        "--scenarios",
        args.scenarios,
        "--repeats",
        str(args.repeats),
        "--model",
        args.model,
        "--provider",
        args.provider,
        "--cost-cap-dollars",
        str(args.cost_cap_dollars),
        "--max-concurrent",
        str(args.max_concurrent),
        "--cell-timeout-s",
        str(args.cell_timeout_s),
        "--cell-timeout-grace-s",
        str(args.cell_timeout_grace_s),
        "--agent-max-iterations",
        str(args.agent_max_iterations),
        "--wait-for-user-input-timeout",
        str(args.wait_for_user_input_timeout),
        "--log-level",
        args.log_level,
        "--scenario-kwargs",
        scenario_kwargs,
    ]
    if args.endpoint:
        cmd.extend(["--endpoint", args.endpoint])
    return cmd


def main() -> int:
    args = parse_args()
    groups = _csv(args.groups)
    unknown = [group for group in groups if group not in GROUPS]
    if unknown:
        raise SystemExit(f"Unknown group(s): {', '.join(unknown)}")

    if "detail_kwoo" in groups and not args.kwoo_context_file.is_file():
        raise SystemExit(f"Kwoo context file not found: {args.kwoo_context_file}")

    args.output_root.mkdir(parents=True, exist_ok=True)
    for group in groups:
        cmd = build_command(args, group)
        env = os.environ.copy()
        if group == "detail_kwoo":
            env[KWOO_CONTEXT_ENV_VAR] = str(args.kwoo_context_file.resolve())

        print("\n" + " ".join(cmd), flush=True)
        if group == "detail_kwoo":
            print(
                f"{KWOO_CONTEXT_ENV_VAR}={args.kwoo_context_file.resolve()}",
                flush=True,
            )
        if args.dry_run:
            continue

        result = subprocess.run(cmd, cwd=REPO_ROOT, env=env)
        if result.returncode != 0:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
