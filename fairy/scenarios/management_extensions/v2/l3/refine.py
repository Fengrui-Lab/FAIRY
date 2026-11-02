"""Local refinement and +/-7 day irrigation counterexamples after the coarse search."""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
from .calibrate import execute_candidate, choose, publish
from .runtime import Prices
from dataclasses import asdict


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coarse", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for result_path in args.coarse.glob("*.json"):
        value = json.loads(result_path.read_text())
        if "candidate" in value:
            rows.append(value)
    assert len(rows) == 48, (
        "Refinement requires all 48 coarse candidates, including refusals"
    )
    coarse, base = choose(rows)
    center = base["candidate"]
    candidates = []
    for dim, delta, cap in ((0, 75.0, 600.0), (1, 15.0, 180.0), (2, 15.0, 180.0)):
        for direction in (-1, 1):
            point = list(center)
            point[dim] += direction * delta
            if 0 <= point[dim] <= cap:
                candidates.append(tuple(point))
    for shift in (-7, 7):
        candidates.append((*center[:3], shift))
    seen = {tuple(row["candidate"]) for row in rows}
    candidates = sorted(set(candidates) - seen)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(execute_candidate, *v): v for v in candidates}
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            slug = "_".join(f"{x:g}" for x in row["candidate"])
            (args.output / (slug + ".json")).write_text(
                json.dumps(row, ensure_ascii=False, indent=2)
            )
            print(
                row["candidate"],
                row["feasible"],
                row.get("net_operating_margin"),
                row.get("error"),
                flush=True,
            )
    reference, selected = choose(rows)
    reference["scope"] += (
        " Plus one axial refinement around coarse best: fertilizer +/-75 kg product/ha, each crop water +/-15mm within bounds, and all irrigation dates shifted +/-7 days. Harvest uses observed readiness from September windows through deadline."
    )
    reference["coarse_best"] = coarse["selected"]
    reference["refinement_candidates"] = candidates
    reference["prices"] = asdict(Prices())
    reference["input_manifest_sha256"] = hashlib.sha256(
        (args.coarse / "input_manifest.json").read_bytes()
    ).hexdigest()
    reference["candidate_results_sha256"] = {
        str(
            result_path.resolve().relative_to(Path(__file__).resolve().parents[5])
        ): hashlib.sha256(result_path.read_bytes()).hexdigest()
        for directory in (args.coarse, args.output)
        for result_path in directory.glob("*.json")
        if "candidate" in json.loads(result_path.read_text())
    }
    reference["notes"] = [
        "Individual crop yield maxima need not be simultaneously feasible.",
        "No preset yield threshold. Feasibility and operating-margin regret are distinct metrics.",
        "Costs are consumed resources; grain revenue is ending stored-grain valuation, not a cash sale.",
        "Weather/crop/soil parameters and prices were not tuned to candidate results.",
    ]
    (args.output / "summary.json").write_text(
        json.dumps(reference, ensure_ascii=False, indent=2)
    )
    if args.publish:
        publish(reference, selected)
    print(json.dumps(reference, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
