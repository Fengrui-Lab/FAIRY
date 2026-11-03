#!/usr/bin/env python3
"""Summarize one frozen H01 A/B pair without running or replaying the model."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys


def finite_number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return {"invalid_nonfinite_number": repr(value)}
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def extract_arm(evaluation, started):
    evaluation = evaluation if isinstance(evaluation, dict) else {}
    metadata = evaluation.get("metadata", {})
    issues = []
    if not isinstance(metadata, dict):
        metadata = {}
        issues.append("metadata_not_an_object")
    h01 = metadata.get("h01", {})
    if not isinstance(h01, dict):
        h01 = {}
    warehouse = metadata.get("warehouse_kg_at_14pct")
    for field in ("execution_complete", "production_success"):
        if not isinstance(metadata.get(field), bool):
            issues.append("missing_or_non_boolean:" + field)
    if not isinstance(evaluation.get("success"), bool):
        issues.append("missing_or_non_boolean:native_success")
    if evaluation.get("success") != metadata.get("production_success"):
        issues.append("native_success_disagrees_with_production_success")
    if metadata.get("execution_complete") is not True:
        issues.append("execution_not_complete")
    if not isinstance(metadata.get("failures"), list) or metadata["failures"]:
        issues.append("missing_or_nonempty_candidate_failures")
    if not finite_number(warehouse):
        issues.append("missing_or_invalid_warehouse_quantity")
    if h01.get("ledger_valid") is not True:
        issues.append("mechanical_ledger_not_validated")
    if not isinstance(h01.get("ledger_failures"), list) or h01["ledger_failures"]:
        issues.append("missing_or_nonempty_mechanical_ledger_failures")
    metrics = {
        "mature_TWSO_kg_DM_ha": metadata.get("mature_TWSO_kg_DM_ha"),
        "recovered_dm_kg": h01.get("recovered_dm_kg"),
        "machine_loss_dm_kg": h01.get("machine_loss_dm_kg"),
    }
    for name, value in metrics.items():
        if not finite_number(value):
            issues.append("missing_or_invalid_metric:" + name)
    primary = None
    if not issues:
        if (metadata["production_success"] is True and warehouse > 0
                and metadata.get("status") == "completed"):
            primary = warehouse
        elif (metadata["production_success"] is False and warehouse == 0
              and metadata.get("status") == "zero_yield_completed"):
            primary = warehouse
        else:
            issues.append("inconsistent_closed_outcome_flags")
    return dict(
        started=json_safe(deepcopy(started)), evaluation_result=json_safe(deepcopy(evaluation)),
        primary_outcome=primary, primary_outcome_unit="kg_at_14pct",
        metrics=json_safe(metrics), adapter_issues=issues,
    )


def build_pair_summary(evaluation_a, started_a, evaluation_b, started_b):
    """A and B are the declared policies; differences always retain A-B signs."""
    arms = {"A": extract_arm(evaluation_a, started_a), "B": extract_arm(evaluation_b, started_b)}
    failures = []
    for label, started in (("A", started_a), ("B", started_b)):
        if started.get("arm") != label or started.get("candidate") != "H01":
            failures.append(label + ":wrong_arm_or_candidate_identity")
        failures.extend(label + ":" + issue for issue in arms[label]["adapter_issues"])
    for field in ("scenario_id", "identity_sha256", "initial_state_sha256", "seed"):
        a, b = started_a.get(field), started_b.get(field)
        present = field in started_a and field in started_b
        if field == "seed":
            well_typed = isinstance(a, int) and not isinstance(a, bool) and isinstance(b, int) and not isinstance(b, bool)
        else:
            well_typed = isinstance(a, str) and bool(a) and isinstance(b, str) and bool(b)
        if not present or not well_typed or a != b:
            failures.append("unmatched_or_missing_pair_identity:" + field)
    metadata_a = evaluation_a.get("metadata")
    metadata_b = evaluation_b.get("metadata")
    version_a = metadata_a.get("scenario_version") if isinstance(metadata_a, dict) else None
    version_b = metadata_b.get("scenario_version") if isinstance(metadata_b, dict) else None
    if not isinstance(version_a, str) or not version_a or version_a != version_b:
        failures.append("unmatched_evaluation_version")
    valid = not failures
    a, b = arms["A"]["primary_outcome"], arms["B"]["primary_outcome"]
    delta = a - b if valid else None
    result = dict(
        summary_version="h01-pair-summary-v1", pair_valid=valid, pair_failures=failures,
        difference_convention="A_minus_B", primary_outcome_unit="kg_at_14pct", arms=arms,
        delta_A_minus_B_kg_at_14pct=delta,
        relative_delta_A_minus_B_over_B=(delta / b if valid and b > 0 else None),
        relative_delta_unavailable_reason=(None if valid and b > 0 else
                                           "zero_B_denominator" if valid else "invalid_pair"),
        simulation_executed_by_summarizer=False,
        validation_authority="actual candidate validator; this reader checks reported fields and pair identities",
    )
    for field in ("mature_TWSO_kg_DM_ha", "recovered_dm_kg", "machine_loss_dm_kg"):
        result["delta_A_minus_B_" + field] = (
            arms["A"]["metrics"][field] - arms["B"]["metrics"][field] if valid else None)
    return result


def read_json(path):
    data = path.read_bytes()
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError(str(path) + " must contain a JSON object")
    return value, dict(path=str(path.resolve()), sha256=hashlib.sha256(data).hexdigest())


def read_or_record_failure(path):
    try:
        return read_json(path)
    except (OSError, ValueError, TypeError) as error:
        return {}, dict(path=str(path.resolve()), read_error=str(error))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-a", type=Path, required=True)
    parser.add_argument("--run-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("--output must not already exist")
    try:
        evaluation_a, source_a = read_or_record_failure(args.run_a / "evaluation.json")
        started_a, identity_a = read_or_record_failure(args.run_a / "started.json")
        evaluation_b, source_b = read_or_record_failure(args.run_b / "evaluation.json")
        started_b, identity_b = read_or_record_failure(args.run_b / "started.json")
        result = build_pair_summary(evaluation_a, started_a, evaluation_b, started_b)
        result["sources"] = {"A": {"evaluation": source_a, "started": identity_a},
                             "B": {"evaluation": source_b, "started": identity_b}}
        for label, sources in result["sources"].items():
            for kind, source in sources.items():
                if "read_error" in source:
                    result["pair_failures"].append(label + ":unreadable_input:" + kind)
        payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(payload)
    except (OSError, ValueError, TypeError) as error:
        print("summarize_maize_h01: " + str(error), file=sys.stderr)
        return 2
    print(str(args.output))
    return 0 if result["pair_valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
