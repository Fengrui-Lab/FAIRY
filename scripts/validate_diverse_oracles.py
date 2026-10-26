"""Export and replay diverse-farm episode or full-season oracles without an LLM.

Produces native CLI run bundles plus a summary. --references-dir optionally
copies reason-annotated workflows into a versioned reference directory.
Exit status is nonzero if any oracle fails execution OR outcome validation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from fairy.scenarios.farm_world_diverse.scenarios import SCENARIO_IDS
from fairy.scenarios.farm_world_diverse.full_season import FULL_SEASON_SCENARIO_IDS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("episodes", "full-season", "all"), default="episodes")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--references-dir", type=Path)
    args = parser.parse_args()
    default_output = "validation_runs/full_season_oracles" if args.suite == "full-season" else "validation_runs/diverse_oracles"
    root = (args.output_dir or Path(default_output)).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if args.references_dir:
        args.references_dir.mkdir(parents=True, exist_ok=True)
    results = []
    scenario_ids = (FULL_SEASON_SCENARIO_IDS if args.suite == "full-season" else
                    (*SCENARIO_IDS, *FULL_SEASON_SCENARIO_IDS) if args.suite == "all" else SCENARIO_IDS)
    for scenario_id in scenario_ids:
        directory = root / scenario_id
        directory.mkdir(parents=True, exist_ok=True)
        oracle_path = directory / "oracle.json"
        manifest_path = oracle_path.with_suffix(".manifest.json")
        command = [sys.executable, "-m", "fairy.cli", "-s", scenario_id,
                   "--build-oracle", "--replay", "--evaluate", "--workflow", str(oracle_path),
                   "--output-dir", str(directory)]
        process = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True)
        (directory / "command.log").write_text(process.stdout + process.stderr, encoding="utf-8")
        report_path = directory / f"{scenario_id}.run_report.json"
        report = json.loads(report_path.read_text()) if report_path.exists() else {}
        validation = report.get("evaluation", {}).get("validation", {})
        ok = (process.returncode == 0 and report.get("status") == "completed"
              and validation.get("success") is True
              and oracle_path.is_file() and manifest_path.is_file())
        result = {"scenario_id": scenario_id, "success": ok,
                  "workflow_steps": validation.get("metadata", {}).get("workflow_steps"),
                  "farms": validation.get("metadata", {}).get("farms", {}),
                  "elapsed_days": validation.get("metadata", {}).get("elapsed_days"),
                  "validation_message": validation.get("message", "No report generated"),
                  "report": str(report_path), "oracle": str(oracle_path),
                  "manifest": str(manifest_path)}
        results.append(result)
        if ok and args.references_dir:
            shutil.copyfile(oracle_path, args.references_dir / f"{scenario_id}.json")
            shutil.copyfile(manifest_path, args.references_dir / f"{scenario_id}.manifest.json")
        print(f"{'PASS' if ok else 'FAIL'} {scenario_id}: {result['workflow_steps']} steps", flush=True)
    summary = {"suite": args.suite, "oracle_kind": "dynamic_multi_farm_full_season" if args.suite == "full-season" else "operational_reference", "total": len(results),
               "passed": sum(r["success"] for r in results), "results": results}
    (root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return 0 if summary["passed"] == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
