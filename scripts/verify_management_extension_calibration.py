"""Independently recompute finite-candidate selection and costs from real replay receipts."""
from collections import Counter
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fairy.scenarios.management_extensions.catalog import SCENARIO_IDS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT/"validation_runs/management_extensions_normal_scale")
    args = parser.parse_args()
    rows = []
    for sid in SCENARIO_IDS:
        proof = json.loads((args.root/"calibration"/(sid+".json")).read_text())
        feasible = [c for c in proof["candidates"] if c["feasible"]]
        highest = max(c["stored_grain_kg"] for c in feasible)
        acceptable = [c for c in feasible if c["stored_grain_kg"] >= .99*highest]
        lowest = min(c["production_cost_minor"] for c in acceptable)
        selected = proof["selected"]
        assert selected["stored_grain_kg"] >= .99*highest and selected["production_cost_minor"] == lowest
        folder = args.root/"replay"/sid
        replay = json.loads((folder/(sid+".replay.json")).read_text())
        report = json.loads((folder/(sid+".run_report.json")).read_text())["evaluation"]
        assert report["validation"]["success"], report["validation"]["message"]
        initial = replay["inventory"]["content"]
        final = replay["final_inventory"]["content"]
        before_machine = replay["tractor"]["content"]
        after_machine = replay["final_machine"]["content"]
        fertilizer = initial["fertilizer_kg"]-final["fertilizer_kg"]-after_machine["fertilizer_spreader_kg"]
        fuel = initial["fuel_liters"]+before_machine["fuel_tank_l"]-final["fuel_liters"]-after_machine["fuel_tank_l"]
        water_mm = sum(s["content"]["field_equivalent_irrigation_mm"] for s in replay.values() if s["tool_name"] == "Irrigation__irrigate")
        batches = [step["content"]["batch"] for step in replay.values() if step["tool_name"] == "Warehouse__store_grain"]
        grain = sum(batch["quantity_kg"] for batch in batches)
        drying_kg = sum(batch["quantity_kg"] for batch in batches if batch["dried"])
        area_m2 = replay["final_field"]["content"]["field_area_m2"]
        if "purchase" in replay:
            receipt = replay["purchase"]["content"]
            seed_cost = receipt["seed_minor"]-receipt["discount_minor"]+receipt["delivery_minor"]
            assert seed_cost == receipt["total_minor"]
            quotes = replay["quotes"]["content"]["offers"]
            assert seed_cost == min(o["seed_minor"]-o["discount_minor"]+o["delivery_minor"] for o in quotes)
        else:
            seed_type = "MAIZE_201"
            used_seeds = initial["seed_stock"][seed_type]-final["seed_stock"][seed_type]-after_machine["seed_hopper"]
            seed_cost = 6500*used_seeds/1000  # same per-seed replacement value, actual consumption
        cost = round(seed_cost+50*fertilizer+100*fuel+2*(water_mm*area_m2/1000)+10*drying_kg)
        assert cost == selected["production_cost_minor"] == report["validation"]["metadata"]["production_cost_minor"]
        assert abs(grain-selected["stored_grain_kg"]) < 1e-8 and grain >= .99*highest
        assert len(batches) == 16 and all(b["status"] == "stored" and len(b["ridge_ids"]) == 4 for b in batches)
        assert Counter(rid for b in batches for rid in b["ridge_ids"]) == Counter(range(64))
        assert grain <= 20000 and sum(b["quantity_kg"] for b in batches if b["dried"]) <= 20000
        assert cost <= report["validation"]["metadata"]["production_budget_minor"]
        assert area_m2 == selected["area_m2"]
        planting = [step for step in replay.values() if step["tool_name"] == "Tractor__plant_seeds"]
        harvesting = [step for step in replay.values() if step["tool_name"] == "Tractor__harvest"]
        loading = [step for step in replay.values() if step["tool_name"] == "Tractor__load_seeds"]
        assert len(planting) == len(harvesting) == 16
        assert all(step["tool_args"]["end_ridge"]-step["tool_args"]["start_ridge"]+1 <= 4 for step in planting+harvesting)
        assert all(step["tool_args"]["count"] <= 300000 for step in loading)
        assert sum(step["tool_args"]["count"] for step in loading) == (754688 if "discount" in sid else 85760)
        assert water_mm <= 180+1e-8 and fertilizer <= area_m2*.06+1e-7
        rows.append({"scenario_id":sid, "passed":True, "candidate_count":len(proof["candidates"]),
            "feasible_count":len(feasible), "area_m2":area_m2, "grain_batches":len(batches), "highest_tested_kg":highest, "selected_stored_kg":grain,
            "retained_yield_pct":100*grain/highest, "cost_minor":cost,
            "cost_components_minor":{"seed":seed_cost,"fertilizer":50*fertilizer,"fuel":100*fuel,
                "water":2*water_mm*area_m2/1000,"drying":10*drying_kg}})
        print(sid, "PASS", grain, cost, flush=True)
    (args.root/"independent_verification.json").write_text(json.dumps(rows,indent=2)+"\n")


if __name__ == "__main__":
    main()
