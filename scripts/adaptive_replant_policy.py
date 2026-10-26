"""Condition an old replant prescription on a fresh public stand response.

The 0.70 line is FAIRY inspect_emergence guidance for entering candidate review.
It is not an agronomic/economic optimum or evidence that replanting pays. A
below-line response preserves the original request and its native capability
boundary; this helper never changes stand, seeds or crop-model state.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from math import isfinite
import re


def _finite_fraction(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) and 0 <= number <= 1 else None


def decide_replant_candidate(observation, *, start, end, threshold=.70, source_requirement=None):
    """Return retain/evaluate/insufficient; caller owns fresh registered reads.

    Retain only when every requested ridge is explicitly planted, unharvested
    and has a finite public stand fraction at or above the declared candidate
    line. Any missing/ambiguous diagnosis prevents skipping the old request.
    """
    if type(start) is not int or type(end) is not int or not 0 <= start <= end:
        raise ValueError("Replant target must be an inclusive nonnegative integer range")
    line = _finite_fraction(threshold)
    if line is None:
        raise ValueError("Replant candidate threshold must be finite in0..1")
    response = observation if isinstance(observation, Mapping) else {}
    if isinstance(response.get("data"), Mapping):
        response = response["data"]
    values = response.get("ridges", [])
    values = values if isinstance(values, list) else []
    target = set(range(start, end + 1))
    rows, issues = {}, []
    for row in values:
        if not isinstance(row, Mapping) or type(row.get("ridge_id")) is not int:
            continue
        rid = row["ridge_id"]
        if rid not in target:
            continue
        if rid in rows:
            issues.append({"ridge_id": rid, "reason": "Duplicate public ridge diagnosis"})
            continue
        rows[rid] = {key: row.get(key) for key in
                     ("ridge_id", "planted", "harvested", "growth_stage", "stand_fraction")}
        stand = _finite_fraction(row.get("stand_fraction"))
        rows[rid]["stand_fraction"] = stand
        if stand is None:
            issues.append({"ridge_id": rid, "reason": "Missing or invalid finite public stand fraction"})
        if row.get("planted") is not True or row.get("harvested") is not False:
            issues.append({"ridge_id": rid, "reason": "Target not explicitly planted and unharvested"})
        stage = row.get("growth_stage")
        if not isinstance(stage, str) or not re.fullmatch(r"VE|VC|V[1-9]\d*|R[1-8]", stage):
            issues.append({"ridge_id": rid, "reason": "Public growth stage unavailable or unrecognized"})
    for rid in sorted(target - rows.keys()):
        issues.append({"ridge_id": rid, "reason": "Target ridge missing from public response"})
    below = [rid for rid in sorted(rows) if _finite_fraction(rows[rid]["stand_fraction"]) is not None
             and rows[rid]["stand_fraction"] < line]
    if issues:
        action = "insufficient_public_diagnosis"
        reasons = ["Incomplete or ambiguous public target diagnosis: the fixed replant request is not skipped"]
    elif below:
        action = "evaluate_replant_candidate"
        reasons = [f"Public stand below the{line} engineering candidate line on ridges{below}; preserve the original native replant capability boundary"]
    else:
        action = "retain_existing_stand"
        reasons = [f"Every target ridge is planted/unharvested with fresh public stand>={line}; retain the existing population in this candidate policy",
                   "Replant economic benefit has not been demonstrated; the threshold only decides entry into candidate evaluation"]
    return {"action": action, "skip_fixed_replant": action == "retain_existing_stand",
            "target": {"start": start, "end": end}, "threshold": line,
            "ridges": [rows[rid] for rid in sorted(rows)], "below_candidate_line_ridges": below,
            "diagnostic_issues": issues, "source_requirement": deepcopy(source_requirement),
            "reasons": reasons, "economic_benefit_established": False,
            "native_replant_support_established": False,
            "threshold_basis": "FAIRY Robot.inspect_emergence tool guidance below0.70; engineering candidate line, not a cultivar-specific economic prescription"}
