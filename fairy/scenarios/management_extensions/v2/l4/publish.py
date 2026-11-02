"""Freeze a finite-search reference into a literal, public-tool workflow."""

import argparse
import hashlib
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import json
from pathlib import Path

HERE = Path(__file__).parent


def publish(directory: Path):
    rows = [
        json.loads(path.read_text()) for path in sorted(directory.glob("f*_w*.json"))
    ]
    feasible = [row for row in rows if row["feasible"] and row.get("validation")]
    required = {
        (fertilizer, water)
        for fertilizer in (400.0, 600.0, 800.0)
        for water in (100.0, 200.0, 300.0)
    }
    observed = {(row["first_fertilizer"], row["first_water"]) for row in rows}
    if not required <= observed or not feasible:
        raise ValueError(
            "Publish requires all nine candidates and at least one feasible result"
        )
    refinement = json.loads((directory / "refinement.json").read_text())
    if not refinement["stopped_without_local_improvement"]:
        raise ValueError(
            "Finish the documented neighborhood refinement before publishing"
        )
    maximum = max(row["stored_grain_kg"] for row in feasible)
    certified = []
    for row in feasible:
        if abs(row["stored_grain_kg"] - maximum) > 1e-8:
            continue
        fertilizer, water = row["first_fertilizer"], row["first_water"]
        neighbors = {
            (fertilizer + fertilizer_delta, water + water_delta)
            for fertilizer_delta in (-100, 0, 100)
            for water_delta in (-50, 0, 50)
            if (fertilizer_delta or water_delta)
            and 400 <= fertilizer + fertilizer_delta <= 800
            and 100 <= water + water_delta <= 300
        }
        if neighbors <= observed:
            certified.append((row, sorted(neighbors)))
    if not certified:
        raise ValueError(
            "No best-yield candidate has a fully evaluated adjacent neighborhood"
        )
    selected, certified_neighbors = min(
        certified,
        key=lambda item: (item[0]["first_fertilizer"], item[0]["first_water"]),
    )
    summary = []
    for row in rows:
        summary.append(
            {
                key: value
                for key, value in row.items()
                if key not in {"trace", "seasons", "input_signature"}
            }
        )
        summary[-1]["irrigation_schedule"] = [
            {
                "date": datetime.fromtimestamp(
                    step["time_before"], ZoneInfo("Asia/Shanghai")
                ).isoformat(),
                "field_mm": step["result"]["field_equivalent_irrigation_mm"],
            }
            for step in row["trace"]
            if step["method"] == "irrigate"
        ]
        if row.get("seasons"):
            summary[-1]["seasons"] = [
                {
                    key: value
                    for key, value in season.items()
                    if key not in {"native_soil_pools", "inventory"}
                }
                for season in row["seasons"]
            ]
    from .scene import TwoYearMaizeScenario

    scene = TwoYearMaizeScenario(calibrating=True)
    scene.setup()
    for row in rows:
        embedded = row.get("input_fingerprint")
        if embedded is not None and embedded != scene.input_fingerprint:
            raise ValueError(
                "Candidate input fingerprint differs from the published experiment"
            )
    missing_fingerprints = sum("input_fingerprint" not in row for row in rows)
    input_provenance = (
        f"{missing_fingerprints} of {len(rows)} candidate artifacts lack embedded input fingerprints. "
        "For those artifacts the common input declaration is reconstructed from fixed configuration "
        "and observable traces; original files remain unchanged. Other candidates embed a matching "
        "signature. The selected result must additionally pass independent execution and fresh replay."
        if missing_fingerprints
        else f"All {len(rows)} candidate artifacts embed input fingerprints matching this fixed experiment. "
        "The selected result must additionally pass independent execution and fresh replay."
    )
    reference = {
        "candidate_artifacts": [
            {
                "path": os.path.relpath(path.resolve(), Path.cwd()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "input_fingerprint_embedded": "input_fingerprint"
                in json.loads(path.read_text()),
            }
            for path in sorted(directory.glob("f*_w*.json"))
        ],
        "coarse_grid_input_provenance": input_provenance,
        "reference_information_scope": "Offline retrospective reference for one fixed complete synthetic weather sequence; no claim of online robustness or agronomic field optimum.",
        "input_signature": scene.input_signature,
        "input_fingerprint": scene.input_fingerprint,
        "objective": "Maximize cumulative safely stored grain from two calendar-year crops",
        "scope": "Nine-point coarse grid plus full adjacent-neighborhood refinement of first-season fertilizer allocations [400,600,800] kg product and water caps [100,200,300] mm; second-season fertilizer is remaining 1200 kg; water cap is min(300, 400 minus actual first-season use). Full adjacent two-dimensional eight-point neighborhood refinement uses 100 kg product and 50 mm steps inside the original allocation bounds until no improvement. Fixed May 5 sowing, base fertilizer 200 kg, remaining fertilizer split days 15/30, four irrigation windows days 20/60/70/80. An irrigation window is skipped when any publicly observed soil-probe VWC >=0.28 (including a margin for sensor noise). Cultivar, dates, weather and geometry are fixed. This is not a global optimum.",
        "weather": "Continuous reproducible synthetic Harbin climate, seed 101, 2026-2027 distinct dates, declared five-day May 5 dry sowing windows in each year.",
        "winter_limitations": "Native CWB/CNB soil continues daily. No added snow or frozen-soil process; uncalibrated winter and reference maize cultivar. Not a regional agronomic recommendation.",
        "cross_species_rotation": False,
        "residue_n_credit": False,
        "field_area_m2": 12864,
        "fertilizer_n_fraction": 0.46,
        "season_caps": {"fertilizer_product_kg": 800, "irrigation_mm": 300},
        "horizon_caps": {"fertilizer_product_kg": 1200, "irrigation_mm": 400},
        "candidate_count": len(rows),
        "feasible_count": len(feasible),
        "selected": next(
            row
            for row in summary
            if row["first_fertilizer"] == selected["first_fertilizer"]
            and row["first_water"] == selected["first_water"]
        ),
        "candidates": summary,
        "refinement": refinement,
        "certified_best_adjacent_candidates": certified_neighbors,
        "interseason_tradeoff_example": {
            "compared_first_season_allocations": [[400, 200], [400, 300]],
            "interpretation": "Joint allocation/timing effect, not isolated causality of total second-year water. The higher first-year cap changes carried allowance, per-event dose, soil state and triggered windows; compare each candidate irrigation_schedule and yearly grain ledgers.",
        },
        "global_optimum_claimed": False,
        "workflow_steps": len(selected["trace"]) + 1,
        "yield_loss_definition": "100 * (1 - actual_two_season_stored_kg / reference_two_season_stored_kg); signed, never clipped",
    }
    (directory / "search_manifest.json").write_text(
        json.dumps(
            {
                "input_fingerprint": scene.input_fingerprint,
                "input_signature": scene.input_signature,
                "candidate_artifacts": reference["candidate_artifacts"],
                "input_provenance_statement": reference["coarse_grid_input_provenance"],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    lines = [
        '"""Frozen public-tool Oracle selected by the documented finite-candidate search."""',
        "from fairy.types import EventRegisterer",
        "from fairy.scenarios.management_extensions.common import capture_step, finish_capture",
        "",
        "def capture_reference(scene):",
        "    apps = {app.name: app for app in scene.apps}",
        "    with EventRegisterer.capture_mode() as events:",
        '        previous = apps["AgentUserInterface"].send_message_to_agent(content=scene.scenario_input).with_id("briefing")',
    ]
    purposes = {
        "advance_time": "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        "get_ridge_range_state": "核对全田公开成熟阶段和籽粒水分",
        "read_soil_sensors": "核对各覆盖区VWC；读数≥0.28时跳过该灌溉窗口，保留未用水",
        "close_season": "核验当年真实成熟收获和安全入库，并冻结本季增量粮账",
        "open_next_season": "沿用原生土壤、设备、库存和共享额度开启第二年作物",
    }
    for index, step in enumerate(selected["trace"]):
        arguments = ", ".join(f"{key}={value!r}" for key, value in step["args"].items())
        method = step["method"]
        reason = purposes.get(method, f"执行公开农场工具 {method}；参数 {step['args']}")
        if method == "read_soil_sensors":
            maximum_vwc = max(probe["vwc"] for probe in step["result"]["soil_sensors"])
            decision = (
                "达到0.28阈值，本窗口跳过灌溉并保留未用水"
                if maximum_vwc >= 0.28
                else "低于0.28阈值，随后按本季分配剂量灌溉"
            )
            reason = f"公开覆盖区观测中最大VWC为{maximum_vwc:.4f}；{decision}"
        lines.append(
            f'        previous = capture_step(previous, apps[{step["app"]!r}].{method}({arguments}), "l4_{index:03d}", {reason!r})'
        )
    lines.append("    return finish_capture(scene, events)")
    HERE.joinpath("oracle.py").write_text("\n".join(lines) + "\n")
    HERE.joinpath("reference.json").write_text(
        json.dumps(reference, ensure_ascii=False, indent=2, default=str)
    )
    print(json.dumps(reference["selected"], ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    publish(parser.parse_args().input)
