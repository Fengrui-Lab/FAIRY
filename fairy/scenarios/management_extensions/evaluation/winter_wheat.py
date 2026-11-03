"""Winter-wheat operational feasibility and signed USD/Oracle outcomes."""

from __future__ import annotations

import math

from fairy.scenarios.validation_result import ScenarioValidationResult
from .oracle_comparison import compare_to_oracle


def evaluate(scenario, env=None):
    runtime = scenario.world.runtime
    result = runtime.outcome_summary()
    p = runtime.resources
    failures = []
    if not result["operational_success"]:
        failures.append(
            "Native maturity, harvest, drying and full-field storage are required"
        )
    if runtime.failed or runtime.backend.failed:
        failures.append("Native model failed")
    if env is not None and not len(env.workflow):
        failures.append("Empty workflow")
    if any(value < -1e-7 for value in runtime.inventory.values()):
        failures.append("Negative resource inventory")
    if runtime.cost_usd > p.budget_usd + 1e-7:
        failures.append("Operating budget exceeded")
    if not math.isclose(
        sum(result["cost_components"].values()), result["production_cost"], abs_tol=1e-7
    ):
        failures.append("Cost components do not balance")
    native_inputs = list(runtime.backend.receipts.values())
    n = sum(row["amount"] for row in native_inputs if row["kind"] == "fertilize")
    water = sum(row["amount"] for row in native_inputs if row["kind"] == "irrigate")
    product = p.fertilizer_stock_kg - runtime.inventory["fertilizer_product_kg"]
    if not math.isclose(product * p.fertilizer_n_fraction / p.area_ha, n, abs_tol=1e-7):
        failures.append("Product fertilizer and native elemental N do not balance")
    if not math.isclose(
        p.water_stock_m3 - runtime.inventory["water_m3"],
        water * p.area_ha * 10,
        abs_tol=1e-7,
    ):
        failures.append("Gross irrigation and water inventory do not balance")
    if runtime.sown and not math.isclose(
        p.seed_stock_kg - runtime.inventory["seed_kg"],
        p.seed_kg_ha * p.area_ha,
        abs_tol=1e-7,
    ):
        failures.append("Seed inventory does not balance")
    native = result["native"]["values"]
    if runtime.harvested and not math.isclose(
        runtime.dry_grain_kg, native["TWSO"] * p.area_ha, abs_tol=1e-7
    ):
        failures.append("Harvested dry grain differs from native TWSO")
    if runtime.stored and (
        runtime.grain_moisture > p.storage_moisture_fraction + 1e-9
        or result["stored_grain_kg"] > p.warehouse_capacity_kg + 1e-7
    ):
        failures.append("Unsafe or over-capacity storage")
    reference = scenario.ORACLE_REFERENCE
    if reference and not scenario.calibrating:
        if scenario.input_fingerprint() != reference["input_fingerprint"]:
            failures.append(
                "Oracle reference does not match current inputs/resources/prices"
            )
        else:
            compare_to_oracle(result, reference["selected"])
    elif not scenario.calibrating:
        failures.append("Validated Oracle reference is missing")
    result.update(
        objective="net_operating_margin",
        oracle_scope=reference.get("scope") if reference else "exploration",
        yield_kg_per_mu=result["stored_grain_kg"] / (p.area_ha * 15),
        production_cost_usd_per_mu=result["production_cost"] / (p.area_ha * 15),
        field_validated=False,
    )
    return ScenarioValidationResult(
        success=not failures,
        message="; ".join(failures)
        or "Native winter wheat harvested and safely stored",
        metadata=result,
    )
