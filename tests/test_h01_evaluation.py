"""Small contract tests; no model run, replay, or full-season fixture."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from fairy.scenarios.maize.h01_evaluation import augment_h01_evaluation
from fairy.scenarios.validation_result import ScenarioValidationResult


spec = importlib.util.spec_from_file_location(
    "h01_summary", Path(__file__).resolve().parents[1] / "scripts" / "summarize_maize_h01.py")
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)


def ledger_fixture():
    area, biological, quality, machine_fraction = 201.0, 100.0, 0.7, 0.055
    state = SimpleNamespace(
        biological_yield_g_m2=biological, field_loss_fraction=0.0,
        machine_loss_fraction=machine_fraction,
        recovered_yield_g_m2_at_market_moisture=biological * (1 - machine_fraction) / 0.86,
        harvested=True,
    )
    rows = []
    for ridge in range(2):
        mass = biological * area / 1000
        rows.append(dict(
            ridge=ridge, area_m2=area, biological_dm_kg=mass, field_loss_dm_kg=0.0,
            harvestable_dm_kg=mass, machine_loss_dm_kg=mass * machine_fraction,
            recovered_dm_kg=mass * (1 - machine_fraction),
            standard_grain_kg=mass * (1 - machine_fraction) / 0.86,
            field_loss_fraction=0.0, machine_loss_fraction=machine_fraction,
            loss_components=dict(raw=machine_fraction, clipped=machine_fraction,
                                 clip_upper_bound=0.25, machine_quality=(1 - quality) * 0.1,
                                 matches_native=True),
        ))
    batch = dict(operation_id="real-action-1", ridge_ids=[0, 1], q_pass=quality,
                 action_machine_quality=quality, harvest_started_at=1.0,
                 harvest_finished_at=2.0, harvest_registered_at=2.0,
                 condition_at_start="maintenance_required", per_ridge=rows)
    for field in ("area_m2", "biological_dm_kg", "field_loss_dm_kg", "harvestable_dm_kg",
                  "machine_loss_dm_kg", "recovered_dm_kg", "standard_grain_kg"):
        batch[field] = sum(row[field] for row in rows)
    farm = SimpleNamespace(num_ridges=2, ridge_area_m2=area, physics=SimpleNamespace(
        yield_recovery=SimpleNamespace(states={0: deepcopy(state), 1: deepcopy(state)},
                                      params=SimpleNamespace(biological_yield_is_dry_matter=True,
                                                             market_moisture_frac=0.14))))
    tractor = SimpleNamespace(harvest_batches=[batch], maintenance_events=[])
    base = ScenarioValidationResult(success=True, message="completed", metadata=dict(
        status="completed", scenario_version="basic-management-v1.1", execution_complete=True,
        production_success=True, failures=[], warehouse_kg_at_14pct=44.17,
        mature_TWSO_kg_DM_ha=1000.0, legacy_native_validation={"success": True}))
    return base, farm, tractor


def evaluation(warehouse, *, complete=True, zero=False):
    return dict(success=complete and not zero, metadata=dict(
        scenario_version="basic-h01-v0.1", status="zero_yield_completed" if zero else "completed" if complete else "incomplete",
        execution_complete=complete, production_success=complete and not zero,
        failures=[] if complete else ["unfinished"], warehouse_kg_at_14pct=warehouse,
        mature_TWSO_kg_DM_ha=0.0 if zero else 1000.0,
        h01=dict(ledger_valid=True, ledger_failures=[], recovered_dm_kg=0.0 if zero else 800.0,
                 machine_loss_dm_kg=0.0 if zero else 20.0)))


def identity(arm):
    return dict(candidate="H01", arm=arm, scenario_id="scenario_h01", identity_sha256="same-code",
                initial_state_sha256="same-initial-state", seed=0)


def test_ledger_reads_native_quantities_and_preserves_base_result():
    base, farm, tractor = ledger_fixture()
    original = deepcopy(base.to_dict())
    result = augment_h01_evaluation(base, farm=farm, tractor=tractor)
    assert result.success is True
    assert result.metadata["h01"]["ledger_valid"] is True
    assert result.metadata["h01"]["recovered_dm_kg"] == pytest.approx(37.989)
    assert result.metadata["warehouse_kg_at_14pct"] == 44.17
    assert base.to_dict() == original


@pytest.mark.parametrize("corruption", ["duplicate", "mass", "q", "missing"])
def test_corrupt_mechanical_ledger_fails_without_erasing_original(corruption):
    base, farm, tractor = ledger_fixture()
    if corruption == "duplicate":
        tractor.harvest_batches.append(deepcopy(tractor.harvest_batches[0]))
    elif corruption == "mass":
        tractor.harvest_batches[0]["per_ridge"][0]["recovered_dm_kg"] += 1
    elif corruption == "q":
        tractor.harvest_batches[0]["action_machine_quality"] = 0.95
    else:
        tractor.harvest_batches = []
    result = augment_h01_evaluation(base, farm=farm, tractor=tractor)
    assert result.success is False
    assert result.metadata["execution_complete"] is False
    assert result.metadata["warehouse_kg_at_14pct"] == 44.17
    assert result.metadata["h01"]["base_validation"]["success"] is True


def test_signed_pair_difference_is_not_absolute_or_clipped():
    positive = summary.build_pair_summary(evaluation(100), identity("A"), evaluation(90), identity("B"))
    negative = summary.build_pair_summary(evaluation(90), identity("A"), evaluation(100), identity("B"))
    assert positive["delta_A_minus_B_kg_at_14pct"] == 10
    assert negative["delta_A_minus_B_kg_at_14pct"] == -10


def test_incomplete_positive_warehouse_is_preserved_but_not_scored():
    result = summary.build_pair_summary(evaluation(100), identity("A"),
                                        evaluation(90, complete=False), identity("B"))
    assert result["pair_valid"] is False
    assert result["delta_A_minus_B_kg_at_14pct"] is None
    assert result["arms"]["B"]["primary_outcome"] is None
    assert result["arms"]["B"]["evaluation_result"]["metadata"]["warehouse_kg_at_14pct"] == 90


def test_completed_zero_yield_is_zero_with_undefined_relative_difference():
    result = summary.build_pair_summary(evaluation(100), identity("A"), evaluation(0, zero=True), identity("B"))
    assert result["pair_valid"] is True
    assert result["arms"]["B"]["primary_outcome"] == 0
    assert result["arms"]["B"]["evaluation_result"]["success"] is False
    assert result["delta_A_minus_B_kg_at_14pct"] == 100
    assert result["relative_delta_A_minus_B_over_B"] is None


@pytest.mark.parametrize("quantity", [None, True, -1.0, float("nan"), float("inf")])
def test_invalid_quantity_is_never_zero_filled(quantity):
    result = summary.build_pair_summary(evaluation(quantity), identity("A"), evaluation(90), identity("B"))
    assert result["pair_valid"] is False
    assert result["arms"]["A"]["primary_outcome"] is None
    assert result["delta_A_minus_B_kg_at_14pct"] is None


def test_missing_quantity_cannot_fall_back_to_legacy_and_pair_identity_is_required():
    missing = evaluation(100)
    del missing["metadata"]["warehouse_kg_at_14pct"]
    missing["metadata"]["legacy_native_validation"] = {"metadata": {"warehouse_grain_kg_at_14pct": 100}}
    mismatch = identity("B")
    mismatch["initial_state_sha256"] = "different-environment"
    result = summary.build_pair_summary(missing, identity("A"), evaluation(90), mismatch)
    assert result["pair_valid"] is False
    assert result["delta_A_minus_B_kg_at_14pct"] is None
