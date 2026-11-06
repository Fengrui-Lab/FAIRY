#!/usr/bin/env python3
"""Release gate for all six L3 cases and two same-land L4 rotations.

Runs native integration BEFORE searches. Never certifies global optimality or
Chinese field calibration. --max-candidates intentionally creates partial evidence.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--beet-input", required=True, type=Path)
    p.add_argument("--rotation-input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--max-candidates", type=int)
    a = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    audit = [
        sys.executable,
        str(root / "scripts/audit_sugarbeet.py"),
        "--output",
        str(out / "audit"),
        "--beet-input",
        str(a.beet_input.resolve()),
        "--rotation-input",
        str(a.rotation_input.resolve()),
    ]
    code = subprocess.run(audit, cwd=root).returncode
    report = dict(
        native_gate_passed=code == 0,
        scenarios={},
        field_validated=False,
        global_optimum_proven=False,
    )
    if code == 0:
        for name in (
            "full_season",
            "water_limit",
            "nitrogen_limit",
            "high_water_price",
            "rotation",
            "seedling_rescue",
            "soil_water_priority",
            "shared_resources",
        ):
            directory = out / name
            directory.mkdir(exist_ok=True)
            inputs = a.rotation_input if name in {"rotation", "shared_resources"} else a.beet_input
            cmd = [
                sys.executable,
                str(root / "scripts/sugarbeet_oracle.py"),
                "--scenario",
                name,
                "--input-dir",
                str(inputs.resolve()),
                "--output",
                str(directory),
            ]
            if a.max_candidates is not None:
                cmd += ["--max-candidates", str(a.max_candidates)]
            with (directory / "execution.log").open("w", encoding="utf-8") as stream:
                rc = subprocess.run(
                    cmd, cwd=root, stdout=stream, stderr=subprocess.STDOUT
                ).returncode
            item = {"returncode": rc, "finite_grid_and_replay_verified": False}
            s = directory / "search_report.json"
            ref = directory / "oracle_reference.json"
            if s.exists():
                summary = json.loads(s.read_text(encoding="utf-8"))
                item.update(status=summary["status"], complete=summary["complete"])
                item["finite_grid_and_replay_verified"] = (
                    rc == 0 and summary["complete"] and ref.is_file()
                )
            report["scenarios"][name] = item
    report["all_finite_grid_references_verified"] = len(
        report["scenarios"]
    ) == 8 and all(
        x["finite_grid_and_replay_verified"] for x in report["scenarios"].values()
    )
    (out / "suite_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0 if report["all_finite_grid_references_verified"] else 2


if __name__ == "__main__":
    sys.exit(main())
