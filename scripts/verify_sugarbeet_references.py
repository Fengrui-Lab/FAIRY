#!/usr/bin/env python3
"""Verify registered beet references through the normal FAIRY CLI without search.

This complements audit_sugarbeet.py: every frozen public workflow must build,
replay, conserve resources and score one against its own reference. It does not
prove optimality outside the finite search that produced each reference.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
import json
from pathlib import Path
import subprocess
import sys

from scripts.sugarbeet_oracle import SCENARIOS


def verify(name, output, root):
    module, class_name = SCENARIOS[name]
    cls = getattr(import_module("fairy.scenarios.management_extensions." + module), class_name)
    directory = output / name
    directory.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "fairy.cli", "--scenario", cls.scenario_id,
               "--build-oracle", "--replay", "--evaluate", "--output-dir", str(directory)]
    with (directory / "cli.log").open("w", encoding="utf-8") as stream:
        result = subprocess.run(command, cwd=root, stdout=stream, stderr=subprocess.STDOUT)
    report_path = directory / (cls.scenario_id + ".run_report.json")
    record = dict(scenario_id=cls.scenario_id, returncode=result.returncode, verified=False)
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        validation = report.get("evaluation", {}).get("validation", {})
        metrics = validation.get("metadata", {})
        score = metrics.get("management_performance", {}).get("objective_score")
        score_one = score == 1 or score == [1, 1, 1]
        record.update(verified=result.returncode == 0 and validation.get("success", False) and score_one,
                      operational_success=validation.get("success"), objective_score=score,
                      root_kg_mu=metrics.get("fresh_root_kg_per_mu"), wheat_kg=metrics.get("wheat_yield"),
                      water_m3=metrics.get("water_m3"), pure_n_kg=metrics.get("pure_n_applied_kg"),
                      report=str(report_path))
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=2, choices=(1, 2, 3))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(lambda name: verify(name, output, root), SCENARIOS))
    summary = dict(all_verified=all(row["verified"] for row in rows), scenarios=rows,
                   field_validated=False, global_optimum_proven=False)
    (output / "reference_verification.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["all_verified"] else 2


if __name__ == "__main__":
    sys.exit(main())
