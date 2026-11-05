#!/usr/bin/env python3
"""Produce a small, reviewable index of the checked challenge evidence."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fairy.scenarios.crop_challenges import artifacts
from fairy.scenarios.crop_challenges.catalog import CHALLENGES


def summary():
    rows = []
    for source, definition in CHALLENGES.items():
        data = artifacts.load(source)
        valid = [c["policy"] for c in data["controls"]
                 if not c["errors"] and c["matched_time"] and c["matched_weather"]]
        rows.append({"source": source, "metric": definition.metric,
                     "valid_controls": valid,
                     "interpretation": ("Omission contrast only; allocation priority remains unverified"
                                        if valid == ["omit"] else
                                        "Delivery-window contrast; optimal harvest timing remains unverified"
                                        if valid == ["miss_window"] else
                                        "Interpret only against the listed valid controls"),
                     "reference": data["tasks"][source]["reference"][definition.metric],
                     "tasks": {sid: {"status": t["status"], "note": t["calibration_note"],
                                     "gates": t["gates"], "window_budgets": t["window_budgets"]}
                               for sid, t in data["tasks"].items()},
                     "controls": [{"policy": c["policy"],
                                   "value": c["outcomes"]["season"][definition.metric],
                                   "errors": c["errors"], "matched_time": c["matched_time"],
                                   "matched_weather": c["matched_weather"]} for c in data["controls"]]})
    return rows


if __name__ == "__main__":
    print(json.dumps(summary(), ensure_ascii=False, indent=2, allow_nan=False))
