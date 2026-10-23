"""Area-aware rice outcomes; deliberately separate from ridge/R8 FOS metrics."""
from __future__ import annotations

import copy

from fairy.apps.paddy.world import PaddyWorldApp
from fairy.controllers.engine import Engine
from fairy.scenarios.fos.provenance import validate_baseline_provenance
from fairy.scenarios.registry import get_scenario_class

SCHEMA = "rice_outcome_v2"
METRICS = ("biological_dry_kg", "harvested_dry_kg", "stored_kg_at_14pct")


def focus_units(scenario):
    if scenario.task in {"puddle", "transplant", "irrigate", "drain", "harvest", "observe_water", "dry", "store", "fertilize", "repair_bund", "gap_fill"}:
        return ["p1"]
    return [p.plot_id for p in scenario.get_typed_app(PaddyWorldApp).field.plots]


def project_outcome(world, *, max_days=220):
    """Project a private full-state copy to maturity without further operations.

    Biological yield is projected, while harvest/storage remain realized. An
    unplanted plot stays unplanted. Failed native maturity is never scored.
    """
    if isinstance(max_days, bool) or not isinstance(max_days, int) or max_days < 0:
        raise ValueError("Rice projection max_days must be a nonnegative integer")
    projected = PaddyWorldApp(start_date=world.start_date, field=world.initial_field,
                              weather=world.weather_config)
    projected.load_state(world.get_state())
    if any(0 < p.transplanted_area_m2 < p.area_m2 and not p.planted for p in projected.field.plots):
        raise ValueError("Cannot project an unfinished partial transplant; complete the hydraulic plot first")
    days = 0
    while any(p.planted and projected.backends[p.plot_id].maturity is None for p in projected.field.plots):
        if days >= max_days:
            raise RuntimeError("Rice projection did not reach native maturity within max_days")
        projected.run_job(86400)
        days += 1
    result = projected.outcome_summary()
    result["projection"] = {"days": days, "management": "none", "max_days": max_days,
                            "until": "all_planted_plots_native_maturity"}
    return result


def totals(outcome, unit_ids):
    selected = [u for u in outcome["units"] if u["unit_id"] in unit_ids]
    if len(selected) != len(unit_ids):
        raise ValueError("Rice outcome is missing focus units")
    area = sum(u["area_m2"] for u in selected)
    result = {metric: sum(u[metric] for u in selected) for metric in METRICS}
    return {**result, "area_m2": area, "biological_dry_kg_ha": result["biological_dry_kg"] / area * 10000}


def build_baseline(scenario_id, *, include_donothing=True, max_days=220):
    """Run a reference and independent no-action world from the same checkpoint."""
    cls = get_scenario_class(scenario_id)
    scenario = cls(crop_backend="wofost")
    scenario._building_baseline = True
    engine = Engine(None, scenario)
    engine.run_scenario_oracle(run_oracle=True)
    validation = engine.evaluate()
    if not validation.success:
        raise RuntimeError(f"Rice reference failed: {validation.to_dict()}")
    world = scenario.get_typed_app(PaddyWorldApp)
    result = {"schema_version": 4, "outcome_schema": SCHEMA, "scenario_id": scenario_id,
              "crop_backend_provenance": world.crop_backend_provenance(),
              "initial_checkpoint_sha256": scenario._initial_state["sha256"],
              "source_l3_scenario_id": scenario.source_l3_scenario_id,
              "source_checkpoint_label": scenario.source_checkpoint_label,
              "focus_unit_ids": focus_units(scenario), "projection_max_days": max_days,
              "oracle": project_outcome(world, max_days=max_days),
              "validation": validation.to_dict()}
    if include_donothing:
        no_action = cls(crop_backend="wofost")
        no_action.setup()
        if no_action._initial_state["sha256"] != result["initial_checkpoint_sha256"]:
            raise ValueError("Rice reference and no-action initial checkpoints differ")
        result["donothing"] = project_outcome(no_action.get_typed_app(PaddyWorldApp), max_days=max_days)
    return result


def compare_outcome(scenario, baseline):
    world = scenario.get_typed_app(PaddyWorldApp)
    if baseline.get("schema_version") != 4 or baseline.get("outcome_schema") != SCHEMA:
        raise ValueError("Rice requires a unit-based rice_outcome_v2 baseline")
    validate_baseline_provenance(baseline, world.crop_backend_provenance(), scenario.scenario_id)
    if (baseline["scenario_id"] != scenario.scenario_id or
            baseline["initial_checkpoint_sha256"] != scenario._initial_state["sha256"] or
            baseline["focus_unit_ids"] != focus_units(scenario)):
        raise ValueError("Rice baseline scenario/checkpoint/focus-unit mismatch")
    ids = focus_units(scenario)
    actual = totals(project_outcome(world, max_days=baseline["projection_max_days"]), ids)
    oracle = totals(baseline["oracle"], ids)
    result = {"outcome_schema": SCHEMA, "focus_unit_ids": ids, "agent": actual, "oracle": oracle}
    if "donothing" in baseline:
        dn = totals(baseline["donothing"], ids)
        result["donothing"] = dn
        result["relative_gain"] = {
            metric: ((actual[metric] - dn[metric]) / (oracle[metric] - dn[metric])
                     if abs(oracle[metric] - dn[metric]) > 1e-8 else None)
            for metric in METRICS}
        result["relative_gain_note"] = "Unclipped; null means no reference/no-action separation, not zero performance."
    return copy.deepcopy(result)
