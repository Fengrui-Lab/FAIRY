"""Independent conservation, completion, chronology and reference checks."""

import math
from datetime import date
from fairy.scenarios.validation_result import ScenarioValidationResult
from ..sugarbeet.contracts import DELIVERY_WEIGHING_TOLERANCE_KG


def performance_indices(results, baseline, objective, eligible):
    """Separate task completion from reference-relative management performance.

    Ratios may exceed one. Signed margin uses an improvement index so a negative
    reference margin does not reverse the ranking. Rotation retains its declared
    lexicographic objective instead of adding incompatible crop masses.
    """
    if not baseline:
        return dict(status="reference_unavailable", objective_score=None)
    ratios = {
        key: results[key] / baseline[key]
        for key in ("root_yield", "wheat_yield")
        if baseline.get(key, 0) > 0
    }
    margin = baseline.get("net_operating_margin")
    margin_index = (1 + (results["net_operating_margin"] - margin) / max(abs(margin), 1.0)) if margin is not None else None
    scores = dict(root_yield=ratios.get("root_yield"), net_operating_margin=margin_index,
                  rotation_yield=[ratios.get("root_yield"), ratios.get("wheat_yield"), margin_index])
    return dict(status="comparable" if eligible else "operationally_ineligible",
                objective_score=scores[objective] if eligible else None,
                yield_ratios=ratios, margin_improvement_index=margin_index,
                root_shortfall_pct=100 * (1 - ratios["root_yield"]) if "root_yield" in ratios else None,
                global_optimum_proven=False)


def evaluate(scene, env=None):
    scene.farm_environment.sync()
    f, r = scene.farm, scene.resources
    failures = []
    results = scene.accounts.compute_accounts()
    area = f.ridge_area_m2 / 10000
    harvests = [h for b in f.backends for h in b.harvests.values()]
    for b in f.backends:
        if b.failed:
            failures.append(f"Native error: {b.failed}")
        for c in f.bundle.cycles:
            total_n = 0.0
            sow_receipts = [
                a
                for a in b.receipts.values()
                if a["cycle_id"] == c.cycle_id and a["kind"] == "sow"
            ]
            if len(sow_receipts) != 1:
                failures.append(f"{c.cycle_id}: expected exactly one sowing")
            for a in sow_receipts:
                try:
                    c.check_sowing(date.fromisoformat(a["day"]))
                except ValueError as e:
                    failures.append(str(e))
            for a in b.receipts.values():
                if a["cycle_id"] == c.cycle_id and a["kind"] == "fertilize":
                    try:
                        c.check_nitrogen(
                            date.fromisoformat(a["day"]), total_n, a["amount"]
                        )
                    except ValueError as e:
                        failures.append(str(e))
                    total_n += a["amount"]
            h = b.harvests.get(c.cycle_id)
            if h is None:
                failures.append(f"Missing {c.cycle_id} harvest")
                continue
            last = (
                date.fromisoformat(h["last_irrigation"])
                if h["last_irrigation"]
                else None
            )
            try:
                c.check_harvest(date.fromisoformat(h["day"]), last)
            except ValueError as e:
                failures.append(str(e))
            minimum = max(c.minimum_dry_yield_kg_ha,
                          getattr(scene, "minimum_wheat_dry_kg_ha", 0) if c.crop == "winter_wheat" else 0)
            if h["native"]["TWSO"] + 1e-8 < minimum:
                failures.append(f"{c.cycle_id}: minimum native dry yield not attained")
            if c.crop == "winter_wheat" and not h["native"].get("DOM"):
                failures.append("Wheat harvested before native maturity")
        if len(b.rotation_audit) != len(f.bundle.cycles) - 1:
            failures.append("Missing native same-soil rotation transition")
        if any(x["before"] != x["after"] for x in b.rotation_audit):
            failures.append("Soil was altered at crop transition")
    receipts = [a for b in f.backends for a in b.receipts.values()]
    n = sum(a["amount"] * area for a in receipts if a["kind"] == "fertilize")
    water = sum(a["amount"] * area * 10 for a in receipts if a["kind"] == "irrigate")
    if not math.isclose(
        n, results["fertilizer_product_kg"] * r.fertilizer_n_fraction, abs_tol=1e-6
    ):
        failures.append("Fertilizer product and native pure N do not balance")
    if not math.isclose(water, results["water_m3"], abs_tol=1e-6):
        failures.append("Water resources and native gross irrigation do not balance")
    if (
        water > r.water_stock_m3 + 1e-6
        or results["production_cost"] > r.budget_usd + 1e-6
    ):
        failures.append("Resource or operating budget exceeded")
    dry_by_crop = {"winter_wheat": 0.0, "sugarbeet": 0.0}
    for h in harvests:
        dry_by_crop[h["crop"]] += h["native"]["TWSO"] * area
    root = scene.delivery.ledger.totals()
    expected_root = (
        dry_by_crop["sugarbeet"]
        * scene.root_contract.machine_recovery
        / scene.root_contract.dry_matter_fraction
    )
    if not math.isclose(
        root["recovered_net_kg"], expected_root, rel_tol=1e-9, abs_tol=0.01
    ):
        failures.append("Native dry matter differs from harvested roots")
    # Delivery quantities may be rounded independently for each harvested batch.
    # Check each batch so many settled batches cannot hide one unfinished load.
    if any(
        not math.isclose(
            batch.delivered_net_kg,
            batch.recovered_net_kg,
            rel_tol=1e-9,
            abs_tol=DELIVERY_WEIGHING_TOLERANCE_KG,
        )
        for batch in scene.delivery.ledger.batches.values()
    ):
        failures.append("Undelivered roots exceed per-batch weighing tolerance")
    expected_grain = (
        dry_by_crop["winter_wheat"] * 0.95 / (1 - r.storage_moisture_pct / 100)
    )
    stored = results["stored_kg_by_crop"].get("winter_wheat", 0)
    if not math.isclose(expected_grain, stored, abs_tol=0.02 * f.num_ridges):
        failures.append("Native wheat and stored grain do not balance")
    if scene.tractor._grain_bin_kg > 1e-8 or any(
        b.status != "stored" for b in scene.warehouse.grain_batches.values()
    ):
        failures.append("Unfinished wheat unloading/drying/storage")
    results.update(
        root_yield=root["delivered_net_kg"],
        undelivered_root_kg=root["recovered_net_kg"] - root["delivered_net_kg"],
        delivery_weighing_tolerance_kg_per_batch=DELIVERY_WEIGHING_TOLERANCE_KG,
        wheat_yield=stored,
        dry_yield_by_crop=dry_by_crop,
        root_yield_kg_ha=root["delivered_net_kg"] / r.area_ha,
        fresh_root_kg_per_mu=root["delivered_net_kg"] / (r.area_ha * 15),
        pure_n_applied_kg=n,
        field_validated=False,
        global_optimum_proven=False,
        objective=scene.objective_metric,
        input_fingerprint=scene.input_fingerprint(),
        operational_success=not failures,
        quality_model="fixed_external_assumption",
    )
    results["root_yield_by_block_kg"] = {
        str(i): sum(batch.delivered_net_kg for batch in scene.delivery.ledger.batches.values() if batch.block_id == i)
        for i in range(f.num_ridges)
    }
    ref = scene.ORACLE_REFERENCE
    baseline = None
    if ref:
        if ref.get("input_fingerprint") != scene.input_fingerprint():
            failures.append("Stale oracle inputs/code")
        results["oracle_scope"] = ref.get("search_scope")
        baseline = ref.get("selected", {})
        results["oracle_delta"] = {
            k: results[k] - baseline[k]
            for k in ("root_yield", "wheat_yield", "net_operating_margin")
            if k in baseline
        }
    else:
        results["oracle_scope"] = "unavailable_for_current_configuration"
    results["operational_success"] = not failures
    results["management_performance"] = performance_indices(results, baseline, scene.objective_metric, not failures)
    return ScenarioValidationResult(
        success=not failures,
        message="; ".join(sorted(set(failures)))
        or "All cycles conserved and products settled",
        metadata=results,
    )
