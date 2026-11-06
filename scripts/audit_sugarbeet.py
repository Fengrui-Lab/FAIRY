#!/usr/bin/env python3
"""Run three isolated audit processes and a mandatory native-integration gate.

These are automated code auditors, NOT independent LLM/subagents. Exit 2 means
blocked/failed. Successful protocol tests never turn missing PCSE into approval.
"""

from __future__ import annotations
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


def run_test(label, path, root, out, environment):
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        str(path),
        f"--junitxml={out / (label + '.xml')}",
    ]
    p = subprocess.run(
        command,
        cwd=root,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    (out / (label + ".txt")).write_text(p.stdout, encoding="utf-8")
    return {
        "status": "passed_for_declared_scope" if p.returncode == 0 else "failed",
        "returncode": p.returncode,
        "command": command,
        "log": label + ".txt",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--beet-input", type=Path)
    p.add_argument("--rotation-input", type=Path)
    a = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    if a.beet_input:
        env["FAIRY_BEET_INPUT_DIR"] = str(a.beet_input.resolve())
    if a.rotation_input:
        env["FAIRY_ROTATION_INPUT_DIR"] = str(a.rotation_input.resolve())
    results = {}
    for label, file in (
        ("engine_protocol", "test_engine_contracts.py"),
        ("scenario_contracts", "test_scenario_contracts.py"),
        ("oracle_claims", "test_oracle_contracts.py"),
    ):
        results[label] = run_test(
            label, root / "tests/sugarbeet" / file, root, out, env
        )
    missing = []
    for module in ("pcse", "fairy.scenarios.scenario"):
        try:
            if importlib.util.find_spec(module) is None:
                missing.append(module)
        except (ModuleNotFoundError, ImportError):
            missing.append(module)
    for var in ("FAIRY_BEET_INPUT_DIR", "FAIRY_ROTATION_INPUT_DIR"):
        if not env.get(var) or not (Path(env[var]) / "manifest.json").is_file():
            missing.append(var + "/manifest.json")
    if missing:
        results["native_integration"] = {"status": "blocked", "missing": missing}
        (out / "native_integration.txt").write_text(
            "BLOCKED: "
            + ", ".join(missing)
            + "\nNo native model output or optimum was produced.\n",
            encoding="utf-8",
        )
    else:
        results["native_integration"] = run_test(
            "native_integration",
            root / "tests/sugarbeet/test_native_integration.py",
            root,
            out,
            env,
        )
        results["yield_management"] = run_test(
            "yield_management", root / "tests/sugarbeet/test_yield_management.py",
            root, out, env,
        )
    result = dict(
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        python=sys.version,
        independent_llm_agents_used=False,
        process_isolation=True,
        checks=results,
        software_native_gate_passed=all(
            x["status"] == "passed_for_declared_scope" for x in results.values()
        ),
        agronomic_field_validation=False,
        oracle_optimality_certified=False,
        note="A software-native pass still requires full public-tool season replay and finite-grid search; it never proves field accuracy.",
    )
    (out / "audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["software_native_gate_passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
