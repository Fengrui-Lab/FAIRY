"""Feasibility checks and signed operating-margin regret for the joint crop task."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fairy.scenarios.validation_result import ScenarioValidationResult
from .oracle_comparison import (
    biological_grain_kg,
    compare_to_oracle,
    recovered_grain_kg,
)

if TYPE_CHECKING:
    from ..L3.scenario_joint_maize_soybean_operating_margin import (
        ScenarioJointCropOperatingMargin as Scene,
    )


def evaluate(scene: Scene) -> ScenarioValidationResult:
    errors = []
    if scene.farm_environment.time_manager.time() > scene.start_time + scene.duration:
        errors.append("Season deadline exceeded")
    for farm in scene.farms:
        errors.extend(_field_errors(scene, farm))
    account = scene.accounts.compute_accounts()
    biological, recovered = {}, {}
    deadline = scene.start_time + scene.duration
    for farm in scene.farms:
        crop = farm.crop_id
        biological[crop] = biological.get(crop, 0.0) + biological_grain_kg(
            farm, deadline=deadline
        )
        recovered[crop] = recovered.get(crop, 0.0) + recovered_grain_kg(farm)
    account["biological_kg_by_crop"] = biological
    account["recovered_kg_by_crop"] = recovered
    errors.extend(_resource_errors(scene, account))
    _compare_reference(scene, account, errors)
    account["feasible"] = not errors
    return ScenarioValidationResult(
        success=not errors,
        message="; ".join(errors) or "All crop fields safely stored",
        metadata=account,
    )


def _field_errors(scene: Scene, farm) -> list[str]:
    errors = []
    if not all(r.harvested for r in farm._ridges):
        errors.append(f"Incomplete planted/harvested field: {farm.farm_id}")
    if not all(farm.is_ridge_mature(i) for i in range(farm.num_ridges)):
        errors.append(f"Harvest maturity not satisfied: {farm.farm_id}")
    planted = [
        rid
        for op in scene.tractor._operation_log
        if op.get("operation") == "plant_seeds" and op.get("farm_id") == farm.farm_id
        for rid in op["ridge_ids"]
    ]
    if sorted(planted) != list(range(farm.num_ridges)):
        errors.append(f"Incomplete or duplicate planting: {farm.farm_id}")
    batches = [
        b
        for b in scene.warehouse.grain_batches.values()
        if b.origin_farm_id == farm.farm_id
    ]
    ids = [rid for b in batches for rid in b.ridge_ids]
    expected_seed = next(
        field["seed_type"] for field in scene.fields if field["farm_id"] == farm.farm_id
    )
    if sorted(ids) != list(range(farm.num_ridges)) or any(
        b.status != "stored"
        or b.moisture_pct is None
        or b.moisture_pct > farm._postharvest_market.max_storage_moisture_pct
        or b.crop_id != farm.crop_id
        or b.cultivar_ids != [expected_seed]
        for b in batches
    ):
        errors.append(f"Unsafe/incomplete batch provenance: {farm.farm_id}")
    return errors


def _resource_errors(scene: Scene, account: dict) -> list[str]:
    errors = []
    if account["water_m3"] > scene.water_capacity_m3 + 1e-7:
        errors.append("Shared water exceeded")
    for farm in scene.farms:
        regime = farm._management_regime
        if (
            regime.irrigation_used_mm_total > scene.field_water_limit_mm + 1e-7
            or regime.fertilizer_used_kg
            > scene.field_fertilizer_limit_kg_ha * farm.field_area_m2 / 10000 + 1e-7
        ):
            errors.append(f"Field quota exceeded: {farm.farm_id}")
    stock = scene.warehouse.stock
    if (
        min(
            stock.fertilizer_kg,
            stock.fuel_liters,
            *stock.seed_stock.values(),
            scene.tractor._fuel_tank_l,
            scene.tractor._fertilizer_spreader_kg,
            scene.tractor._seed_hopper,
        )
        < -1e-8
    ):
        errors.append("Negative resource stock")
    applied_fertilizer = sum(
        f._management_regime.fertilizer_used_kg for f in scene.farms
    )
    if abs(account["fertilizer_product_kg"] - applied_fertilizer) > 1e-7:
        errors.append("Fertilizer material balance mismatch")
    if scene.tractor._grain_bin_kg > 1e-8:
        errors.append("Grain remains in machine")
    if any(
        x < -1e-7
        for x in (
            account["fertilizer_product_kg"],
            account["fuel_liters"],
            *account["consumed_seeds"].values(),
        )
    ):
        errors.append("Negative material consumption")
    return errors


def _compare_reference(scene: Scene, account: dict, errors: list[str]) -> None:
    reference = None if scene.calibrating else scene.get_oracle_reference()
    if reference:
        if reference.get("input_fingerprint") != scene.input_fingerprint():
            errors.append("Reference inputs do not match current scenario")
        account["reference_best_margin"] = reference["selected"]["net_operating_margin"]
        account["margin_regret"] = (
            reference["selected"]["net_operating_margin"]
            - account["net_operating_margin"]
        )
        account["reference_scope"] = reference["scope"]
        if reference.get("input_fingerprint") == scene.input_fingerprint():
            compare_to_oracle(account, reference["selected"])
