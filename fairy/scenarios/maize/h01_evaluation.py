"""Candidate-only H01 recovery-ledger validation.

The growth and terminal validator remains authoritative. This module adds an
audit of the real harvest batches against the native recovery states; it never
applies another loss or derives a loss from the A/B outcome difference.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import math

from fairy.scenarios.validation_result import ScenarioValidationResult


MASS_FIELDS = (
    "biological_dm_kg", "field_loss_dm_kg", "harvestable_dm_kg",
    "machine_loss_dm_kg", "recovered_dm_kg", "standard_grain_kg",
)


def finite_number(value, *, minimum=0.0, maximum=None):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value) and value >= minimum and (maximum is None or value <= maximum)
    except OverflowError:
        return False


def close_quantity(left, right):
    return (finite_number(left) and finite_number(right)
            and math.isclose(left, right, rel_tol=1e-10, abs_tol=1e-8))


def audit_h01_ledger(*, farm, tractor):
    """Audit stored, immutable batch observations against actual native states."""
    batches = deepcopy(tractor.harvest_batches)
    failures = []
    expected = set(range(farm.num_ridges))
    recovery = farm.physics.yield_recovery
    states = recovery.states
    params = recovery.params
    area = farm.ridge_area_m2
    moisture = params.market_moisture_frac
    if not finite_number(area) or area <= 0:
        failures.append("invalid_native_ridge_area")
    if (params.biological_yield_is_dry_matter is not True
            or not close_quantity(moisture, 0.14)):
        failures.append("unsupported_native_mass_basis")
    if set(states) != expected:
        failures.append("native_recovery_ridge_coverage")

    native = {}
    for ridge in sorted(expected):
        state = states.get(ridge)
        if state is None:
            continue
        quantities = {
            "biological_yield_g_m2": state.biological_yield_g_m2,
            "field_loss_fraction": state.field_loss_fraction,
            "machine_loss_fraction": state.machine_loss_fraction,
            "recovered_yield_g_m2_at_market_moisture": state.recovered_yield_g_m2_at_market_moisture,
        }
        if (not all(finite_number(value) for value in quantities.values())
                or not finite_number(state.field_loss_fraction, maximum=1.0)
                or not finite_number(state.machine_loss_fraction, maximum=1.0)
                or not finite_number(area) or area <= 0
                or not finite_number(moisture, maximum=0.999999999)):
            failures.append(f"invalid_native_recovery_quantity:{ridge}")
            continue
        if state.harvested is not True:
            failures.append(f"native_ridge_not_harvested:{ridge}")
        biological = state.biological_yield_g_m2 * area / 1000.0
        field_loss = biological * state.field_loss_fraction
        harvestable = biological - field_loss
        machine_loss = harvestable * state.machine_loss_fraction
        standard = state.recovered_yield_g_m2_at_market_moisture * area / 1000.0
        recovered = standard * (1.0 - moisture)
        row = dict(ridge=ridge, area_m2=area, **quantities,
                   biological_dm_kg=biological, field_loss_dm_kg=field_loss,
                   harvestable_dm_kg=harvestable, machine_loss_dm_kg=machine_loss,
                   recovered_dm_kg=recovered, standard_grain_kg=standard)
        if not close_quantity(harvestable, machine_loss + recovered):
            failures.append(f"native_recovery_mass_balance:{ridge}")
        native[ridge] = row

    coverage = Counter()
    operation_ids = set()
    if not isinstance(batches, list):
        failures.append("harvest_batches_not_a_list")
        batches = []
    for index, batch in enumerate(batches):
        prefix = f"batch:{index}:"
        if not isinstance(batch, dict):
            failures.append(prefix + "not_an_object")
            continue
        operation_id = batch.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id or operation_id in operation_ids:
            failures.append(prefix + "missing_or_duplicate_operation_id")
        else:
            operation_ids.add(operation_id)
        q = batch.get("q_pass")
        recorded_q = batch.get("action_machine_quality")
        if (not finite_number(q, maximum=1.0)
                or not finite_number(recorded_q, maximum=1.0)
                or not close_quantity(q, recorded_q)):
            failures.append(prefix + "invalid_or_mismatched_quality_snapshot")
        times = [batch.get(name) for name in (
            "harvest_started_at", "harvest_finished_at", "harvest_registered_at")]
        if not all(finite_number(value) for value in times) or not times[0] <= times[1] <= times[2]:
            failures.append(prefix + "invalid_harvest_times")
        rows = batch.get("per_ridge")
        ids = batch.get("ridge_ids")
        if not isinstance(rows, list) or not isinstance(ids, list):
            failures.append(prefix + "missing_ridge_rows")
            continue
        row_ids = []
        valid_rows = []
        for row in rows:
            if not isinstance(row, dict):
                failures.append(prefix + "non_object_ridge_row")
                continue
            ridge = row.get("ridge")
            if not isinstance(ridge, int) or isinstance(ridge, bool) or ridge not in expected:
                failures.append(prefix + "invalid_ridge_id")
                continue
            row_ids.append(ridge)
            coverage[ridge] += 1
            reference = native.get(ridge)
            if reference is None:
                failures.append(prefix + f"missing_native_reference:{ridge}")
                continue
            for field in ("area_m2", *MASS_FIELDS, "field_loss_fraction", "machine_loss_fraction"):
                if not close_quantity(row.get(field), reference[field]):
                    failures.append(prefix + f"native_quantity_mismatch:{ridge}:{field}")
            components = row.get("loss_components")
            if not isinstance(components, dict) or components.get("matches_native") is not True:
                failures.append(prefix + f"unverified_loss_components:{ridge}")
            else:
                raw = components.get("raw")
                clipped = components.get("clipped")
                upper = components.get("clip_upper_bound")
                if (not all(finite_number(value) for value in (raw, clipped, upper))
                        or not close_quantity(clipped, reference["machine_loss_fraction"])
                        or not close_quantity(clipped, min(upper, max(0.0, raw)))):
                    failures.append(prefix + f"invalid_loss_clipping:{ridge}")
                q_component = components.get("machine_quality")
                if (not finite_number(q, maximum=1.0)
                        or not close_quantity(q_component, (1.0 - q) * 0.10)):
                    failures.append(prefix + f"quality_component_mismatch:{ridge}")
            valid_rows.append(row)
        if (any(not isinstance(rid, int) or isinstance(rid, bool) for rid in ids)
                or sorted(ids) != sorted(row_ids) or len(row_ids) != len(set(row_ids))):
            failures.append(prefix + "batch_ridge_coverage")
        for field in ("area_m2", *MASS_FIELDS):
            values = [row.get(field) for row in valid_rows]
            if (len(values) != len(rows) or not all(finite_number(value) for value in values)
                    or not close_quantity(batch.get(field), sum(values))):
                failures.append(prefix + "batch_total_mismatch:" + field)
    if set(coverage) != expected or any(coverage[ridge] != 1 for ridge in expected):
        failures.append("all_native_ridges_must_appear_in_one_harvest_batch")

    totals = {
        name: sum(row[name] for row in native.values()) if len(native) == len(expected) else None
        for name in MASS_FIELDS
    }
    return dict(
        ledger_version="h01-native-recovery-ledger-v1",
        ledger_valid=not failures,
        ledger_failures=failures,
        market_moisture_frac=moisture,
        machine_loss_scope="total native machine loss; not q-only loss",
        native_recovery_per_ridge=list(native.values()),
        harvest_batches=batches,
        maintenance_events=deepcopy(tractor.maintenance_events),
        **totals,
    )


def augment_h01_evaluation(base_result, *, farm, tractor, scenario_version="basic-h01-v0.1"):
    """Return a new result; never mutate or silently replace the base result."""
    metadata = deepcopy(base_result.metadata)
    h01 = audit_h01_ledger(farm=farm, tractor=tractor)
    for field in ("warehouse_kg_at_14pct", "mature_TWSO_kg_DM_ha"):
        if not finite_number(metadata.get(field)):
            h01["ledger_failures"].append("invalid_terminal_quantity:" + field)
    h01["ledger_valid"] = not h01["ledger_failures"]
    h01["base_validation"] = deepcopy(base_result.to_dict())
    metadata["h01"] = h01
    metadata["scenario_version"] = scenario_version
    if not h01["ledger_valid"]:
        metadata.setdefault("failures", []).extend("h01:" + failure for failure in h01["ledger_failures"])
        metadata.update(status="incomplete", execution_complete=False, production_success=False)
        return ScenarioValidationResult(success=False, message="incomplete", metadata=metadata)
    return ScenarioValidationResult(success=base_result.success, message=base_result.message,
                                    rationale=base_result.rationale, metadata=metadata)
