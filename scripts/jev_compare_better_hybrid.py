"""New hybrid (3 repeats) against the existing LLM-alone and hybrid runs (1 run each).

Usage:
    python scripts/jev_compare_better_hybrid.py --new <full dir> --new-scoring <full_scoring dir> \
        --old-summary <runs_summary.csv> [--csv <out.csv>]
"""

from __future__ import annotations

import argparse
import csv
import random
import statistics as st
from pathlib import Path

PREFIX = "scenario_full_season_hb_"
TEST_SCENARIOS = {  # used in the 4-scenario test, so not held out
    "compacted_headland_stand_recovery",
    "drought_recovery_false_disease_signal",
    "dryer_capacity_batch_harvest_storage",
    "soy_after_soy_wetjune_disease",
}
REPEATS = 10000


def short(name: str) -> str:
    return name.removeprefix(PREFIX).removeprefix("scenario_full_season_")


def load_new(full: Path, scoring: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for rep in sorted(p.name for p in scoring.iterdir() if p.is_dir()):
        logged = {r["scenario"]: r for r in csv.DictReader((full / f"{rep}.csv").open(encoding="utf-8"))}
        for row in csv.DictReader((scoring / rep / "summary_v2.csv").open(encoding="utf-8")):
            name = short(row["scenario"])
            base = logged[name]
            missing = row.get("farm_fos_v2_missing_harvest_ridges") or row.get("missing_harvest_ridges")
            out.setdefault(name, []).append({
                "rep": rep,
                "loss": float(row["recovered_yield_loss(%)"]),
                "finished": int(float(missing or 0)) == 0,
                "cost": float(base["cost"]),
                "cost_llm": float(base["cost_llm"]),
                "cost_jev": float(base["cost_jev"]),
                "minutes": float(base["minutes"]),
                "actions": int(base["actions"]),
                "share": float(base["jev_share_pct"]),
                "switch": float(base["tool_switch_pct"] or 0),
                "llm_calls": int(base["llm_calls"]),
                "stop": base["stop"],
            })
    return out


def load_old(path: Path) -> tuple[dict, dict]:
    llm: dict[str, dict] = {}
    hybrid: dict[str, dict] = {}
    for row in csv.DictReader(path.open(encoding="utf-8")):
        entry = {
            "loss": float(row["grain_loss_pct"]),
            "finished": row["season_finished"] == "True",
            "cost": float(row["cost_total_usd"]),
            "minutes": float(row["wall_time_min"]),
            "actions": int(row["actions"]),
        }
        if row["in_fair_llm_baseline"] == "True":
            llm[short(row["scenario"])] = entry
        elif row["setting"] == "hybrid_jev_plus_llm":
            hybrid[short(row["scenario"])] = entry
    return llm, hybrid


def interval(diffs: list[float]) -> tuple[float, float]:
    """95% bootstrap interval of the mean difference, resampling scenarios."""
    rng = random.Random(0)
    means = sorted(st.mean(rng.choices(diffs, k=len(diffs))) for _ in range(REPEATS))
    return means[int(0.025 * REPEATS)], means[int(0.975 * REPEATS)]


def block(title: str, names: list[str], new: dict, llm: dict, hybrid: dict) -> None:
    runs = [r for n in names for r in new[n]]
    mean_new = {n: st.mean(r["loss"] for r in new[n]) for n in names}
    print(f"\n{title} ({len(names)} scenarios)")
    print(f"{'':16}{'finished':>10}{'loss':>8}{'median':>8}{'$/run':>8}{'min/run':>9}{'actions':>9}")
    for label, data in (("LLM alone", llm), ("old hybrid", hybrid)):
        rows = [data[n] for n in names]
        print(f"{label:16}{sum(r['finished'] for r in rows):>6}/{len(rows):<3}"
              f"{st.mean(r['loss'] for r in rows):>8.1f}{st.median(r['loss'] for r in rows):>8.1f}"
              f"{st.mean(r['cost'] for r in rows):>8.3f}{st.mean(r['minutes'] for r in rows):>9.1f}"
              f"{st.mean(r['actions'] for r in rows):>9.0f}")
    print(f"{'new hybrid':16}{sum(r['finished'] for r in runs):>6}/{len(runs):<3}"
          f"{st.mean(r['loss'] for r in runs):>8.1f}{st.median(r['loss'] for r in runs):>8.1f}"
          f"{st.mean(r['cost'] for r in runs):>8.3f}{st.mean(r['minutes'] for r in runs):>9.1f}"
          f"{st.mean(r['actions'] for r in runs):>9.0f}")
    for label, data in (("LLM alone", llm), ("old hybrid", hybrid)):
        diffs = [mean_new[n] - data[n]["loss"] for n in names]
        low, high = interval(diffs)
        better = sum(d < 0 for d in diffs)
        print(f"new minus {label}: {st.mean(diffs):+.1f} points, 95% interval {low:+.1f} to {high:+.1f}; "
              f"new lower on {better} of {len(diffs)} scenarios")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--new", type=Path, required=True)
    ap.add_argument("--new-scoring", type=Path, required=True)
    ap.add_argument("--old-summary", type=Path, required=True)
    ap.add_argument("--csv", type=Path)
    args = ap.parse_args()
    new = load_new(args.new, args.new_scoring)
    llm, hybrid = load_old(args.old_summary)
    names = sorted(new)
    assert all(len(new[n]) == 3 for n in names), {n: len(new[n]) for n in names}

    block("All", names, new, llm, hybrid)
    block("Not used in the 4-scenario test", [n for n in names if n not in TEST_SCENARIOS], new, llm, hybrid)
    block("Without compacted headland", [n for n in names if "compacted" not in n], new, llm, hybrid)

    runs = [r for n in names for r in new[n]]
    print("\nNew hybrid per repeat:")
    for rep in sorted({r["rep"] for r in runs}):
        group = [r for r in runs if r["rep"] == rep]
        print(f"  {rep}: finished {sum(r['finished'] for r in group)}/19  loss {st.mean(r['loss'] for r in group):.1f}%"
              f"  ${sum(r['cost'] for r in group):.2f}")
    print(f"Jev cost ${sum(r['cost_jev'] for r in runs) / 3:.2f}, LLM cost ${sum(r['cost_llm'] for r in runs) / 3:.2f} per 19 runs;"
          f" Jev share {st.mean(r['share'] for r in runs):.0f}%; LLM calls/run {st.mean(r['llm_calls'] for r in runs):.0f};"
          f" tool switch {st.mean(r['switch'] for r in runs):.0f}%")
    spread = [max(r["loss"] for r in new[n]) - min(r["loss"] for r in new[n]) for n in names]
    print(f"Spread across the 3 repeats of one scenario: median {st.median(spread):.1f} points, largest {max(spread):.1f}")

    print("\nscenario | LLM alone | old hybrid | new rep1 | rep2 | rep3 | new mean")
    table = []
    for n in names:
        losses = [r["loss"] for r in new[n]]
        marks = ["" if r["finished"] else " X" for r in new[n]]
        print(f"{n[:42]} | {llm[n]['loss']:.1f} | {hybrid[n]['loss']:.1f}{'' if hybrid[n]['finished'] else ' X'} | "
              + " | ".join(f"{v:.1f}{m}" for v, m in zip(losses, marks)) + f" | {st.mean(losses):.1f}")
        table.append([n, llm[n]["loss"], hybrid[n]["loss"], *losses, round(st.mean(losses), 2)])
    if args.csv:
        with args.csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["scenario", "llm_alone", "old_hybrid", "new_rep1", "new_rep2", "new_rep3", "new_mean"])
            writer.writerows(table)


if __name__ == "__main__":
    main()
