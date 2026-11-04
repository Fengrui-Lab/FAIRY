"""Evaluate the closed-season ledgers, resource balances and signed yield loss."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from fairy.apps.farm_world import FarmWorldApp, TractorApp
from fairy.scenarios.validation_result import ScenarioValidationResult
from .oracle_comparison import compare_to_oracle

if TYPE_CHECKING:
    from ..L4.scenario_two_year_maize_soil_carryover import (
        TwoYearMaizeScenario as Scene,
    )


def evaluate(scene: Scene) -> ScenarioValidationResult:
    farm = scene.get_typed_app(FarmWorldApp)
    tractor = scene.get_typed_app(TractorApp)
    backend = farm.physics.crop_backend
    rows = scene.cycle.closed
    failures = []
    if farm.time_manager.time() > scene.start_time + scene.duration:
        failures.append("Episode exceeded its declared simulation horizon")
    failures.extend(_season_ledger_errors(rows, scene))
    total = sum(row["stored_grain_kg"] for row in rows)
    failures.extend(_terminal_state_errors(farm, tractor, backend, total, scene))
    reference = scene.get_oracle_reference()
    reference_matches = bool(
        reference and reference.get("input_fingerprint") == scene.input_fingerprint()
    )
    reference_yield = (
        reference["selected"].get(
            "stored_grain_kg", reference["selected"].get("total_stored_grain_kg")
        )
        if reference_matches
        else None
    )
    accounts = scene.cycle.compute_accounts()
    accounts["total_stored_grain_kg"] = total
    if reference_matches and not scene.calibrating:
        compare_to_oracle(
            accounts,
            reference["selected"],
            agent_seasons=scene.cycle.yield_seasons(),
            oracle_seasons=reference["selected"].get("seasons", ()),
        )
    return ScenarioValidationResult(
        success=not failures,
        message="; ".join(failures)
        if failures
        else "All planned crops safely stored with continuous native soil",
        metadata={
            **accounts,
            "feasible": not failures,
            "seasons": rows,
            "total_stored_grain_kg": total,
            "reference_stored_grain_kg": reference_yield,
            "calibration_status": "finite_grid_best"
            if reference_matches
            else "development_not_calibrated",
            "global_optimum_claimed": False,
            "provenance": backend.snapshot()["provenance"],
        },
    )


def _season_ledger_errors(rows: list[dict], plan) -> list[str]:
    failures = []
    if [row["year"] for row in rows] != [s.year for s in plan.seasons]:
        failures.append("All planned calendar-year harvests are required")
    previous_fertilizer = previous_water = 0.0
    for row in rows:
        year = row["year"]
        season = next((s for s in plan.seasons if s.year == year), None)
        if season is None:
            failures.append(f"Unexpected crop year {year}")
            continue
        if not row["planting_dates"] or not row["harvest_dates"]:
            failures.append(f"Missing actual planting/harvest dates for {year}")
        for value in (
            row["planting_dates"] + row["harvest_dates"] + [row["closed_date"]]
        ):
            day = date.fromisoformat(value)
            if day.year != year or day > season.harvest_deadline:
                failures.append(f"Crop {year} exceeds its calendar-year deadline")
        fertilizer = row["fertilizer_used_kg_cumulative"]
        water = row["irrigation_used_mm_cumulative"]
        if (
            not 0
            <= fertilizer - previous_fertilizer
            <= season.fertilizer_limit_kg + 1e-8
        ):
            failures.append(f"Season {year} fertilizer cap exceeded")
        if not 0 <= water - previous_water <= season.water_limit_mm + 1e-8:
            failures.append(f"Season {year} irrigation cap exceeded")
        previous_fertilizer, previous_water = fertilizer, water
    return failures


def _terminal_state_errors(
    farm: FarmWorldApp, tractor: TractorApp, backend, total: float, plan
) -> list[str]:
    failures = []
    regime = farm._management_regime
    if (
        regime.fertilizer_used_kg > plan.fertilizer_budget_kg + 1e-8
        or regime.irrigation_used_mm_total > plan.water_budget_mm + 1e-8
    ):
        failures.append("Whole-horizon resource cap exceeded")
    fertilizer_balance = (
        farm._inventory.fertilizer_kg
        + tractor._fertilizer_spreader_kg
        + regime.fertilizer_used_kg
    )
    if abs(fertilizer_balance - plan.fertilizer_budget_kg) > 1e-6:
        failures.append("Fertilizer stock is not conserved")
    if abs(total - farm._inventory.warehouse_grain_kg) > 1e-6:
        failures.append("Season grain ledger differs from actual warehouse")
    if len(backend._runs) != farm.num_ridges or len(
        backend.season_history
    ) != farm.num_ridges * (len(plan.seasons) - 1):
        failures.append(
            "Each ridge must have the planned number of native crop transitions"
        )
    if any(row["soil_before"] != row["soil_after"] for row in backend.season_history):
        failures.append("Native crop transition changed soil pools")
    if tractor._grain_bin_kg or farm._inventory.harvest_grain_kg:
        failures.append("Unstored harvested grain remains")
    return failures
