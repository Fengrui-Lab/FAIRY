from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "scripts" / "fullseason" / "run_l3_skill_retrieval_experiments.py"

MAPPED_LIBRARY_SCENARIOS = [
    "scenario_full_season_hb_heihe43_early_density_weed_nutrient_recovery",
    "scenario_full_season_hb_coldspring_planting_window_heihe50",
    "scenario_full_season_hb_wetcold_high_residue_establishment",
    "scenario_full_season_heinong84_staggered_planting",
    "scenario_full_season_hb_fertilizer_quota_edge_lowfertility",
    "scenario_full_season_hb_insect_after_fungicide_budget_conflict",
    "scenario_full_season_hb_two_dry_patches_one_irrigation",
    "scenario_full_season_hb_wetjune_shortwindow_trafficability",
    "scenario_full_season_hb_storage_capacity_limit_batching",
    "scenario_full_season_hb_three_cultivar_wet_disease_dry_harvest_sequence",
]

ADDITIONAL_MANAGEMENT_SCENARIOS = [
    "scenario_full_season_hb_heinong58_water_chemical_priority_under_dual_stress",
    "scenario_full_season_hb_r5_leaf_feeder_defoliation",
    "scenario_full_season_hb_heinong60_highdensity_fertigation_irrigation_water_budget",
    "scenario_full_season_hb_lowcarbon_batch_operations_wetdisease",
    "scenario_full_season_hb_laterain_insect_risk",
    "scenario_full_season_hb_planter_skip_rows_stand_gap",
    "scenario_full_season_hb_high_weed_seedbank_mechanical_only_baseline",
    "scenario_full_season_hb_wetjune_disease_recheck_after_fungicide",
    "scenario_full_season_hb_potassium_deficit_dry_podfill_interaction",
    "scenario_full_season_hb_disease_then_drought_recovery_tradeoff",
]

ALL_TARGET_SCENARIOS = MAPPED_LIBRARY_SCENARIOS + ADDITIONAL_MANAGEMENT_SCENARIOS

ALL20_GROUPS = [
    "l2_textsim_grouped_differ",
    "l2_pathsim_grouped_differ",
    "l3_pathsim_same",
    "l3_pathsim_differ",
    "l3_textsim_differ",
]


def _csv(items: list[str]) -> str:
    return ",".join(items)


def _read_reference_scenarios(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    config = payload.get("iclr_validation_runner", payload)
    scenarios = config.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError(f"Config has no non-empty scenarios list: {path}")
    return [str(item) for item in scenarios]


def _write_combined_candidate_root(
    output_root: Path,
    candidate_roots: list[Path],
    target_scenarios: list[str],
) -> Path:
    combined = output_root / "candidate_detail_false_combined"
    combined.mkdir(parents=True, exist_ok=True)
    out_path = combined / "results.csv"
    wanted = set(target_scenarios)
    rows_by_scenario: dict[str, dict[str, str]] = {}
    header: list[str] | None = None
    for root in candidate_roots:
        results = root / "results.csv"
        if not results.is_file():
            raise FileNotFoundError(f"Candidate results.csv not found: {results}")
        with results.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if header is None:
                header = list(reader.fieldnames or [])
            for row in reader:
                scenario = str(row.get("scenario") or "")
                if scenario not in wanted:
                    continue
                if str(row.get("return_code")) != "0":
                    continue
                rows_by_scenario.setdefault(scenario, row)

    missing = [scenario for scenario in target_scenarios if scenario not in rows_by_scenario]
    if missing:
        raise RuntimeError(
            "No successful DETAIL=false candidate row for scenario(s): "
            + ", ".join(missing)
        )
    if header is None:
        raise RuntimeError("No candidate rows were read")

    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for scenario in target_scenarios:
            writer.writerow(rows_by_scenario[scenario])
    print(f"[candidate-root] wrote {len(target_scenarios)} rows to {out_path}", flush=True)
    return combined


def _run(cmd: list[str], *, dry_run: bool) -> int:
    print("\n" + " ".join(cmd), flush=True)
    if dry_run:
        return 0
    return subprocess.run(cmd, cwd=REPO_ROOT).returncode


def parse_args() -> argparse.Namespace:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parser = argparse.ArgumentParser(
        description=(
            "Run the DeepSeek-JSON 20-L3 retrieval matrix. Five automatic "
            "retrieval modes and l2_human_differ run on all 20 targets."
        )
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "validation_runs" / f"deepseek_json_l3_20_retrieval_{stamp}",
    )
    parser.add_argument(
        "--selected10-candidate-root",
        type=Path,
        default=REPO_ROOT / "validation_runs/deepseek_selected10_detail_false2/phase5_paper_matrix",
    )
    parser.add_argument(
        "--remaining80-candidate-root",
        type=Path,
        default=REPO_ROOT
        / "validation_runs/deepseek_json_remaining80_detail_false_l3_farm_baseline_react/phase5_paper_matrix",
    )
    parser.add_argument(
        "--reference-config",
        type=Path,
        default=REPO_ROOT / "scripts/iclr_validation_runner.deepseek_json_detail_true_full90.json",
    )
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--families", default="farm_baseline_react")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-concurrent", type=int, default=1)
    parser.add_argument("--cost-cap-dollars", type=float, default=200.0)
    parser.add_argument("--cell-timeout-s", type=int, default=1200)
    parser.add_argument("--cell-timeout-grace-s", type=int, default=60)
    parser.add_argument("--agent-max-iterations", type=int, default=200)
    parser.add_argument(
        "--parallel-tool-calls",
        choices=("true", "false"),
        default="true",
    )
    parser.add_argument("--wait-for-user-input-timeout", type=float, default=5.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _base_runner_cmd(args: argparse.Namespace) -> list[str]:
    return [
        sys.executable,
        str(RUNNER),
        "--families",
        args.families,
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
        "--parallel-tool-calls",
        args.parallel_tool_calls,
        "--wait-for-user-input-timeout",
        str(args.wait_for_user_input_timeout),
    ]


def main() -> int:
    args = parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    references = _read_reference_scenarios(args.reference_config)
    missing_refs = [scenario for scenario in ALL_TARGET_SCENARIOS if scenario not in references]
    if missing_refs:
        raise RuntimeError(
            "Reference config does not include target scenario(s): "
            + ", ".join(missing_refs)
        )

    candidate_root = _write_combined_candidate_root(
        args.output_root,
        [args.selected10_candidate_root, args.remaining80_candidate_root],
        ALL_TARGET_SCENARIOS,
    )

    print("\n[target-set] all20:")
    for scenario in ALL_TARGET_SCENARIOS:
        print(f"  - {scenario}")
    print("\n[target-set] l2_human_differ mapped20:")
    for scenario in ALL_TARGET_SCENARIOS:
        print(f"  - {scenario}")

    all20_cmd = _base_runner_cmd(args) + [
        "--groups",
        _csv(ALL20_GROUPS),
        "--scenarios",
        _csv(ALL_TARGET_SCENARIOS),
        "--reference-scenarios",
        _csv(references),
        "--candidate-output-root",
        str(candidate_root),
        "--output-root",
        str(args.output_root / "all20_auto_retrieval"),
        "--preview-context-dir",
        str(args.output_root / "context_previews" / "all20_auto_retrieval"),
    ]
    if args.dry_run:
        all20_cmd.append("--dry-run")
    rc = _run(all20_cmd, dry_run=False)
    if rc != 0:
        return rc

    human_cmd = _base_runner_cmd(args) + [
        "--groups",
        "l2_human_differ",
        "--scenarios",
        _csv(ALL_TARGET_SCENARIOS),
        "--reference-scenarios",
        _csv(references),
        "--output-root",
        str(args.output_root / "mapped20_l2_human_differ"),
        "--preview-context-dir",
        str(args.output_root / "context_previews" / "mapped20_l2_human_differ"),
    ]
    if args.dry_run:
        human_cmd.append("--dry-run")
    return _run(human_cmd, dry_run=False)


if __name__ == "__main__":
    raise SystemExit(main())
