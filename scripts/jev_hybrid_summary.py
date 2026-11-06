"""One row per hybrid run from its runtime log; means per setting. Uses the README prices.

Run cells are named <setting>__<scenario> (scripts/jev_run_l3mini.py) or
<setting>/<scenario> (the shared run package). Grain loss comes from an optional
FAIRY scoring CSV (--scores, recovered_yield_loss(%)).

Usage:
    python scripts/jev_hybrid_summary.py --root <runs dir> [--scores <summary_v2.csv>] [--csv <out.csv>]
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

JEV_INPUT = 0.042 / 1e6
LLM_INPUT = 0.10 / 1e6
LLM_CACHED = 0.01 / 1e6
LLM_OUTPUT = 0.50 / 1e6
PREFIX = "scenario_full_season_hb_"
TOTAL_RIDGES = 64


def short(scenario: str) -> str:
    return scenario.removeprefix(PREFIX).removeprefix("scenario_full_season_")


def run_row(log: Path) -> dict:
    cell = log.parent
    setting, scenario = (
        cell.name.split("__", 1) if "__" in cell.name else (cell.parent.name, cell.name)
    )
    c: Counter = Counter()
    sources: Counter = Counter()
    harvested: set[int] = set()
    stop = None
    last_date = None
    last_jev = None
    switched = 0
    for line in log.open(encoding="utf-8"):
        e = json.loads(line)
        kind = e["record_type"]
        if kind == "jev_request_end":
            c["jev_tokens"] += e["tokens"]["prompt_tokens"]
            c["jev_requests"] += 1
            c["jev_seconds"] += float(e["wall_time_seconds"])
            last_jev = e["answers"].get("next_action", last_jev)
        elif kind == "llm_call_end" or kind == "llm_fallback_end":
            t = e.get("tokens") or {}
            c["llm_calls"] += 1
            c["llm_prompt"] += t.get("prompt_tokens", 0)
            c["llm_cached"] += t.get("cached_tokens", 0)
            c["llm_output"] += t.get("completion_tokens", 0)
            c["llm_seconds"] += float(e.get("wall_time_seconds") or 0)
            decision = e.get("decision")
            if decision and e.get("reason") == "low_confidence" and last_jev:
                c["handoffs"] += 1
                switched += decision[0] != last_jev["choice"]
            if e.get("plan"):
                c["plans"] += 1
        elif kind == "jev_action":
            sources[e["source"]] += 1
        elif kind == "tool_call_end":
            c["actions"] += 1
            last_date = e["sim_time"][:10]
            preview = str(e.get("content_preview", ""))
            if e["tool_name"] == "TractorApp__harvest" and "harvested_ridges" in preview:
                args = e.get("tool_args") or {}
                if "error" not in preview and "start_ridge" in args:
                    harvested.update(range(args["start_ridge"], args["end_ridge"] + 1))
        elif kind == "agent_run_end":
            stop = e.get("stopped_reason")
            c["wall"] = float(e.get("wall_time_seconds") or 0)
    uncached = c["llm_prompt"] - c["llm_cached"]
    cost_jev = c["jev_tokens"] * JEV_INPUT
    cost_llm = uncached * LLM_INPUT + c["llm_cached"] * LLM_CACHED + c["llm_output"] * LLM_OUTPUT
    decisions = sum(sources.values()) or 1
    return {
        "setting": setting,
        "scenario": short(scenario),
        "stop": stop,
        "last_date": last_date,
        "actions": c["actions"],
        "harvested": len(harvested),
        "minutes": round(c["wall"] / 60, 2),
        "jev_share_pct": round(100 * sources["jev"] / decisions, 1),
        "llm_calls": c["llm_calls"],
        "tool_switch_pct": round(100 * switched / c["handoffs"], 1) if c["handoffs"] else None,
        "llm_tok_per_call": round(c["llm_prompt"] / c["llm_calls"]) if c["llm_calls"] else 0,
        "cached_pct": round(100 * c["llm_cached"] / c["llm_prompt"], 1) if c["llm_prompt"] else 0,
        "plans": c["plans"],
        "cost_jev": round(cost_jev, 4),
        "cost_llm": round(cost_llm, 4),
        "cost": round(cost_jev + cost_llm, 4),
    }


def load_scores(path: Path | None) -> dict[tuple[str, str], float]:
    if path is None:
        return {}
    out = {}
    for row in csv.DictReader(path.open(encoding="utf-8")):
        cell = row.get("cell") or ""
        value = row.get("recovered_yield_loss(%)")
        scenario = row.get("scenario_id") or row.get("scenario") or ""
        if value not in (None, "") and cell:
            setting = Path(cell).name.split("__", 1)[0]
            out[(setting, short(scenario))] = float(value)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--scores", type=Path)
    ap.add_argument("--csv", type=Path)
    args = ap.parse_args()
    scores = load_scores(args.scores)
    rows = [run_row(p) for p in sorted(args.root.rglob("*.runtime_log.jsonl"))]
    for row in rows:
        row["grain_loss_pct"] = scores.get((row["setting"], row["scenario"]))
    if args.csv:
        with args.csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    cols = ["scenario", "stop", "last_date", "actions", "harvested", "minutes", "jev_share_pct",
            "llm_calls", "tool_switch_pct", "llm_tok_per_call", "cached_pct", "plans",
            "cost_jev", "cost_llm", "cost", "grain_loss_pct"]
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["setting"]].append(row)
    for setting, group in groups.items():
        print(f"\n== {setting} ({len(group)} runs)")
        print(" | ".join(cols))
        for row in sorted(group, key=lambda r: r["scenario"]):
            print(" | ".join(str(row[c])[:30] for c in cols))
        losses = [r["grain_loss_pct"] for r in group if r["grain_loss_pct"] is not None]
        print(
            f"finished {sum(r['harvested'] == TOTAL_RIDGES for r in group)}/{len(group)}"
            f"  cost total ${sum(r['cost'] for r in group):.2f}"
            f" (jev ${sum(r['cost_jev'] for r in group):.2f}, llm ${sum(r['cost_llm'] for r in group):.2f})"
            f"  minutes/run {statistics.mean(r['minutes'] for r in group):.1f}"
            f"  actions/run {statistics.mean(r['actions'] for r in group):.0f}"
            f"  jev share {statistics.mean(r['jev_share_pct'] for r in group):.0f}%"
            + (f"  grain loss {statistics.mean(losses):.1f}%" if losses else "")
        )


if __name__ == "__main__":
    main()
