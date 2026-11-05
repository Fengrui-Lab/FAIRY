"""Export four static references, then replay each file in a separate CLI process."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fairy.scenarios.management_extensions.catalog import SCENARIO_IDS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "validation_runs/management_extensions_normal_scale/replay")
    parser.add_argument("--references-dir", type=Path, default=ROOT / "configs/oracles/management_extensions")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.references_dir.mkdir(parents=True, exist_ok=True)
    sources = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in (ROOT / "fairy/scenarios/management_extensions").rglob("*") if p.suffix in {".py", ".json"} and p.name != "scenarios.py"}
    for relative in ("fairy/scenarios/registry.py", "scripts/calibrate_management_extension_oracles.py",
                     "scripts/verify_management_extension_calibration.py", "scripts/validate_management_extension_oracles.py"):
        sources[relative] = hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()
    rows = []
    for sid in SCENARIO_IDS:
        folder = args.output_dir / sid
        folder.mkdir(parents=True, exist_ok=True)
        reference = args.references_dir / f"{sid}.json"
        base = [sys.executable, "-m", "fairy.cli", "-s", sid, "--workflow", str(reference), "--output-dir", str(folder)]
        commands = [base + ["--build-oracle"], base + ["--replay", "--evaluate"]]
        for index, command in enumerate(commands):
            with (folder / f"{index}.log").open("w") as log:
                subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        evaluation = json.loads((folder / f"{sid}.run_report.json").read_text())["evaluation"]
        row = {"scenario_id": sid, "success": evaluation["validation"]["success"],
               "metadata": evaluation["validation"]["metadata"]}
        # Provenance sidecar is an audit record, not a shared-runtime manifest.
        reference.with_suffix(".provenance.json").write_text(json.dumps({
            "schema": 1, "sources": sources, "workflow_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
            "source_scope": "Extension package, registry and audit scripts; not a complete native runtime fingerprint.",
            "commands": commands}, indent=2) + "\n")
        rows.append(row)
        print(f"{sid}: {'PASS' if row['success'] else 'FAIL'}", flush=True)
    (args.output_dir / "summary.json").write_text(json.dumps(rows, indent=2) + "\n")
    if not all(row["success"] for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
