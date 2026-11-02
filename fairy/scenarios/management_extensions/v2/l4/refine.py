"""Full two-dimensional neighborhood refinement, retaining every evaluated point."""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
from .calibrate import run_candidate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    rows = [json.loads(path.read_text()) for path in args.directory.glob("f*_w*.json")]
    if len(rows) < 9:
        raise ValueError("Run the nine-point coarse grid first")
    seen = {(row["first_fertilizer"], row["first_water"]) for row in rows}
    rounds = []
    while True:
        feasible = [row for row in rows if row["feasible"] and row.get("validation")]
        best = max(feasible, key=lambda row: row["stored_grain_kg"])
        fertilizer, water = best["first_fertilizer"], best["first_water"]
        points = {
            (fertilizer + fertilizer_delta, water + water_delta)
            for fertilizer_delta in (-100, 0, 100)
            for water_delta in (-50, 0, 50)
            if fertilizer_delta or water_delta
        }
        points = sorted(
            point
            for point in points - seen
            if 400 <= point[0] <= 800 and 100 <= point[1] <= 300
        )
        if not points:
            break
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            jobs = {pool.submit(run_candidate, *point): point for point in points}
            for future in as_completed(jobs):
                row = future.result()
                rows.append(row)
                fertilizer, water = jobs[future]
                seen.add((fertilizer, water))
                (args.directory / f"f{fertilizer:g}_w{water:g}.json").write_text(
                    json.dumps(row, ensure_ascii=False, indent=2, default=str)
                )
                print(
                    fertilizer,
                    water,
                    row.get("stored_grain_kg"),
                    row.get("error"),
                    flush=True,
                )
        new_best = max(
            (row for row in rows if row["feasible"] and row.get("validation")),
            key=lambda row: row["stored_grain_kg"],
        )
        rounds.append(
            {
                "center": [best["first_fertilizer"], best["first_water"]],
                "points": points,
                "before_kg": best["stored_grain_kg"],
                "after_kg": new_best["stored_grain_kg"],
            }
        )
        if new_best["stored_grain_kg"] <= best["stored_grain_kg"] + 1e-8:
            break
    (args.directory / "refinement.json").write_text(
        json.dumps(
            {
                "rounds": rounds,
                "step_kg_product": 100,
                "step_mm": 50,
                "bounds": [[400, 800], [100, 300]],
                "stopped_without_local_improvement": True,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
