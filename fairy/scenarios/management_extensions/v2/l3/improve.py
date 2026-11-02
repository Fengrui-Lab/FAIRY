"""Two-start discrete neighborhood exploration until no neighboring improvement.

Each spatial neighborhood includes all combinations of +/-75 kg product/ha
maize fertilizer and +/-15 mm irrigation for both crops. Temporal alternatives
shift all irrigation dates by -7/0/+7 days at the center's doses. This is a local
certificate on a stated grid, not a global optimum over agronomic controls.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import product
import json
import hashlib
from pathlib import Path
from .calibrate import execute_candidate, choose, publish

ROOT = Path(__file__).resolve().parents[5]


def neighbors(center):
    axes = []
    for value, step, cap in zip(center[:3], (75.0, 15.0, 15.0), (600.0, 180.0, 180.0)):
        axes.append([x for x in (value - step, value, value + step) if 0 <= x <= cap])
    result = {(*values, center[3]) for values in product(*axes)}
    result.update((*center[:3], shift) for shift in (-7, 0, 7))
    result.discard(tuple(center))
    return sorted(result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coarse", type=Path, required=True)
    parser.add_argument("--refinement", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = {}
    paths = {}
    for directory in (args.coarse, args.refinement, args.output):
        for result_path in directory.glob("*.json"):
            row = json.loads(result_path.read_text())
            if "candidate" in row:
                rows[tuple(row["candidate"])] = row
                paths[tuple(row["candidate"])] = result_path
    good = [row for row in rows.values() if row.get("feasible")]
    starts = [
        max(good, key=lambda row: row["net_operating_margin"])["candidate"],
        max(
            (row for row in good if row["candidate"][0] == 0),
            key=lambda row: row["net_operating_margin"],
        )["candidate"],
    ]
    history = []
    endpoints = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for branch, start in enumerate(starts):
            center = tuple(start)
            iteration = 0
            while True:
                region = neighbors(center)
                missing = [v for v in region if v not in rows]
                futures = {pool.submit(execute_candidate, *v): v for v in missing}
                for future in as_completed(futures):
                    row = future.result()
                    key = tuple(row["candidate"])
                    rows[key] = row
                    result_path = args.output / (
                        "_".join(f"{x:g}" for x in key) + ".json"
                    )
                    paths[key] = result_path
                    result_path.write_text(
                        json.dumps(row, ensure_ascii=False, indent=2)
                    )
                    print(
                        "candidate",
                        key,
                        row["feasible"],
                        row.get("net_operating_margin"),
                        row.get("error"),
                        flush=True,
                    )
                feasible = [rows[v] for v in [center, *region] if rows[v]["feasible"]]
                best = max(
                    feasible,
                    key=lambda row: (
                        row["net_operating_margin"],
                        -row["water_m3"],
                        -row["fertilizer_product_kg"],
                    ),
                )
                improved = (
                    best["net_operating_margin"]
                    > rows[center]["net_operating_margin"] + 1e-8
                )
                event = {
                    "branch": branch,
                    "iteration": iteration,
                    "center": center,
                    "center_margin": rows[center]["net_operating_margin"],
                    "neighbors": region,
                    "new_evaluations": len(missing),
                    "best": best["candidate"],
                    "best_margin": best["net_operating_margin"],
                    "improved": improved,
                }
                history.append(event)
                (args.output / "search_history.json").write_text(
                    json.dumps(history, indent=2)
                )
                print("round", json.dumps(event), flush=True)
                if not improved:
                    endpoints.append(
                        {
                            "center": center,
                            "net_operating_margin": rows[center][
                                "net_operating_margin"
                            ],
                            "neighbor_count": len(region),
                            "all_neighbors_evaluated": True,
                        }
                    )
                    break
                center = tuple(best["candidate"])
                iteration += 1
    reference, selected = choose(list(rows.values()))
    reference["scope"] += (
        " Plus full adjacent dose combinations at steps (75kg product/ha,15mm,15mm), and center-dose irrigation-date alternatives {-7,0,+7} days; two starts (best refined and best zero-fertilizer), both stopped only after no improving neighbor. No optimization over sowing date, density, field geometry, N timing or arbitrary management schedules."
    )
    reference["local_neighborhood_definition"] = {
        "maize_fertilizer_step_kg_product_ha": 75,
        "maize_water_step_mm": 15,
        "soybean_water_step_mm": 15,
        "dose_combinations": "full adjacent Cartesian product",
        "center_dose_irrigation_shift_days": [-7, 0, 7],
        "stopping_rule": "No feasible evaluated neighbor improves margin by more than 1e-8 DEMO.",
    }
    reference["search_starts"] = starts
    reference["local_optima"] = endpoints
    reference["search_history"] = history
    reference["prices"] = selected["prices"]
    reference["input_manifest_sha256"] = hashlib.sha256(
        (args.coarse / "input_manifest.json").read_bytes()
    ).hexdigest()
    reference["candidate_results_sha256"] = {
        str(result_path.resolve().relative_to(ROOT)): hashlib.sha256(
            result_path.read_bytes()
        ).hexdigest()
        for result_path in paths.values()
    }
    reference["notes"] = [
        "Cropwise maximum yields are marginal bounds and need not be jointly achievable.",
        "Harvest follows publicly observed maturity/moisture and rain-free dates after September check windows.",
        "No preset yield threshold; report feasibility, margin regret, crop-specific yields, costs and shared water separately.",
    ]
    if args.publish:
        publish(reference, selected)
    (args.output / "summary.json").write_text(
        json.dumps(reference, ensure_ascii=False, indent=2)
    )
    print(
        "FINAL",
        json.dumps(
            {
                k: reference[k]
                for k in (
                    "candidate_count",
                    "feasible_count",
                    "selected",
                    "local_optima",
                )
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
