"""Block completion, native input conservation and existing signed USD metrics."""

import math
from fairy.scenarios.validation_result import ScenarioValidationResult
from .oracle_comparison import compare_to_oracle


def evaluate(scene, env=None):
    f, r = scene.farm, scene.resources
    scene.farm_environment.sync()
    result = scene.accounts.compute_accounts()
    failures = []
    if any(not block.harvested for block in f._ridges):
        failures.append("Every block must reach native maturity and be harvested")
    if any(b.failed for b in f.backends):
        failures.append("Native model failed")
    batches = list(scene.warehouse.grain_batches.values())
    if (
        not batches
        or any(b.status != "stored" for b in batches)
        or scene.tractor._grain_bin_kg > 1e-8
    ):
        failures.append("All recovered grain must be unloaded and safely stored")
    if result["production_cost"] > r.budget_usd + 1e-7:
        failures.append("Operating cost limit exceeded")
    receipts = [a for b in f.backends for a in b.receipts.values()]
    area_ha = f.ridge_area_m2 / 10000
    n = sum(a["amount"] * area_ha for a in receipts if a["kind"] == "fertilize")
    water = sum(a["amount"] * area_ha * 10 for a in receipts if a["kind"] == "irrigate")
    if not math.isclose(
        n, result["fertilizer_product_kg"] * r.fertilizer_n_fraction, abs_tol=1e-6
    ):
        failures.append("Urea product and native pure-N inputs do not balance")
    if not math.isclose(water, result["water_m3"], abs_tol=1e-6):
        failures.append("Water ledger and native gross depth do not balance")
    native_dry = sum((b.values.get("TWSO") or 0) * area_ha for b in f.backends)
    expected = sum(
        (f.backends[i].values.get("TWSO") or 0)
        * area_ha
        * 0.95
        / (1 - r.storage_moisture_pct / 100)
        for i, block in enumerate(f._ridges)
        if block.harvested
    )
    stored = result["stored_kg_by_crop"]["winter_wheat"]
    if (
        all(block.harvested for block in f._ridges)
        and abs(expected - stored) > 0.01 * f.num_ridges
    ):
        failures.append(
            "Stored mass differs from native grain, machine recovery and moisture conversion"
        )
    result.update(
        stored_grain_kg=stored,
        dry_grain_kg=native_dry,
        management_unit="flat_block",
        block_count=f.num_ridges,
        harvested_blocks=[i for i, x in enumerate(f._ridges) if x.harvested],
        area_m2=f.field_area_m2,
        yield_kg_per_mu=stored / (r.area_ha * 15),
        production_cost_usd_per_mu=result["production_cost"] / (r.area_ha * 15),
        pure_n_applied_kg=n,
        operational_success=not failures,
        field_validated=False,
        objective="net_operating_margin",
        native_provenance=f.crop_backend_provenance(),
    )
    reference = scene.ORACLE_REFERENCE
    if reference and not scene.calibrating:
        if scene.input_fingerprint() != reference["input_fingerprint"]:
            failures.append("Oracle inputs/resources/prices differ from this scene")
        else:
            compare_to_oracle(result, reference["selected"])
    elif not scene.calibrating:
        failures.append("Validated block-management Oracle reference missing")
    return ScenarioValidationResult(
        success=not failures,
        message="; ".join(failures) or "All wheat blocks harvested and stored",
        metadata=result,
    )
