"""Task acceptance and resource audits shared by the registered rice scenarios."""
from __future__ import annotations

import json
import os
from pathlib import Path

from fairy.apps.paddy.world import PaddyWorldApp
from fairy.scenarios.validation_result import ScenarioValidationResult


def validate_rice_task(scenario, env):
    world = scenario.get_typed_app(PaddyWorldApp)
    world.advance_physics_time()
    actions = world.actions[scenario._initial_action_count:]
    plots = world.field.plots
    p1 = world.plot("p1")
    if scenario.task in {"season", "harvest_storage", "harvest_batches"}:
        goal = _all_harvested_grain_stored(world)
        if scenario.task == "harvest_batches":
            goal = goal and sum(a["action"] == "harvest" for a in actions) > len(plots)
    elif scenario.task == "establishment":
        goal = all(p.planted and p.puddled and p.levelled for p in plots)
    elif scenario.task == "irrigation_management":
        records = world.daily_records[len(scenario._initial_state["daily_records"]):]
        stress_ok = all(r["rates"].get("RFTRA", 1.) is None or
                        r["rates"].get("RFTRA", 1.) >= .8 for r in records)
        goal = (world.sim_time - scenario._initial_state["sim_time"] >= 10 * 86400 and
                any(a["action"] == "irrigate" for a in actions) and stress_ok)
    elif scenario.task == "irrigate":
        goal = abs(sum(a["water_mm"] for a in actions if a["action"] == "irrigate" and a["plot_id"] == "p1") - 30) < 1e-6
    elif scenario.task == "drain":
        goal = any(a["action"] == "drain" and a["plot_id"] == "p1" and a["actual_mm"] > 0 for a in actions)
    elif scenario.task in {"puddle", "transplant", "harvest"}:
        goal = {"puddle": p1.puddled and p1.levelled, "transplant": p1.planted, "harvest": p1.harvested}[scenario.task]
    elif scenario.task == "observe_water":
        goal = any(k == "water:p1" and v["timestamp"] >= scenario.start_time for k, v in world.observations.items())
    elif scenario.task == "refuel":
        goal = abs(sum(a.get("liters", 0) for a in actions
                       if a["action"] == "refuel" and a["machine_id"] == "tractor") - 10.) < 1e-8
    elif scenario.task in {"dry", "store"}:
        original = next(b for b in scenario._initial_state["field"]["grain_batches"] if b["location"] == "reception")
        batch = world.batch(original["batch_id"])
        goal = batch.moisture_pct <= 14 and batch.location == ("reception" if scenario.task == "dry" else "stored")
    elif scenario.task in {"fertilize", "nutrition_management"}:
        applied = {p.plot_id: sum(a["product_kg"] for a in actions
                   if a["action"] == "apply_fertilizer" and a["plot_id"] == p.plot_id) for p in plots}
        if scenario.task == "fertilize":
            goal = abs(applied["p1"] - p1.unit.mass_kg(150.)) < 1e-6
        else:
            goal = (all(applied[p.plot_id] >= p.unit.mass_kg(150.) - 1e-6 for p in plots)
                    and world.sim_time - scenario.start_time >= 25 * 86400)
    elif scenario.task in {"scout", "crop_protection"}:
        goal = all(f"pests:{p.plot_id}" in world.observations for p in plots)
        goal = goal and any(a["action"] == "fly_survey" for a in actions)
        if scenario.task == "crop_protection":
            goal = goal and all(all(getattr(p, key) < old[key] for key in ("pests", "disease", "weeds"))
                                for p, old in zip(plots, scenario._initial_state["field"]["plots"]))
    elif scenario.task in {"repair_bund", "infrastructure_recovery"}:
        goal = p1.bund_leak_mm_day == 0 and any(a["action"] == "repair_bund" for a in actions)
        if scenario.task == "infrastructure_recovery":
            goal = goal and all(c.blockage_fraction == 0 for c in world.field.channels)
    elif scenario.task == "gap_fill":
        goal = p1.stand_fraction >= .99 and p1.pending_stand_recovery == 0
    else:
        raise ValueError(f"Unknown task: {scenario.task}")
    errors = [s for s in env.workflow.dag.values()
              if s.op_type == "TOOL_ERROR" or
              (isinstance(s.content, dict) and s.content.get("error"))]
    audit = audit_world(world)
    metadata = {"goal_met": goal, "tool_errors": len(errors), "audit": audit,
                "source_l3_scenario_id": scenario.source_l3_scenario_id,
                "source_checkpoint_label": scenario.source_checkpoint_label,
                "initial_checkpoint_sha256": scenario._initial_state["sha256"]}
    baseline_dir = os.environ.get("FOS_ORACLE_BASELINE_DIR")
    if baseline_dir and not getattr(scenario, "_building_baseline", False):
        from fairy.scenarios.rice.evaluation import compare_outcome
        path = Path(baseline_dir) / f"{scenario.scenario_id}.json"
        metadata["rice_outcome"] = compare_outcome(scenario, json.loads(path.read_text()))
    return ScenarioValidationResult(success=bool(goal and not errors and audit["success"]),
        message="Rice task, water/nitrogen balances and resource accounting evaluated",
        metadata=metadata)


def _all_harvested_grain_stored(world):
    """Complete storage means every recovered grain batch reached the warehouse.

    Resource conservation also holds when grain remains in the combine or
    reception area, so a successful balance audit alone cannot establish this
    task goal. Check the physical batches as well as each plot's derived totals.
    """
    tolerance = 1e-7
    batches = world.field.grain_batches
    if not all(b.location == "stored" and 0 <= b.moisture_pct <= 14 for b in batches):
        return False
    return all(
        p.harvested and p.stored_dry_kg > 0 and p.storage_moisture_pct == 14
        and abs(p.loaded_grain_dry_kg) <= tolerance
        and abs(p.unloaded_grain_dry_kg) <= tolerance
        and abs(p.stored_dry_kg - p.harvested_dry_kg) <= tolerance
        and abs(sum(b.dry_kg for b in batches if b.plot_id == p.plot_id)
                - p.harvested_dry_kg) <= tolerance
        for p in world.field.plots
    )


def audit_world(world):
    failures = []
    for p in world.field.plots:
        b = world.backends[p.plot_id]
        if abs(b.water.audit()["balance_residual_mm"]) > 1e-6:
            failures.append(f"{p.plot_id}: water ledger")
        accounted = p.loaded_grain_dry_kg + p.unloaded_grain_dry_kg + p.stored_dry_kg
        if abs(accounted - p.harvested_dry_kg) > 1e-7:
            failures.append(f"{p.plot_id}: grain accounting")
        if p.harvested:
            bio = p.unit.mass_kg(float(b.crop_values.get("TWSO") or 0))
            if abs(bio - p.harvested_dry_kg - p.harvest_loss_dry_kg - p.field_loss_dry_kg) > 1e-7:
                failures.append(f"{p.plot_id}: harvest accounting")
        if abs(b.nitrogen.audit()["balance_residual_n_kg_ha"]) > 1e-6:
            failures.append(f"{p.plot_id}: nitrogen ledger")
    batch = world.field.seedlings
    original = world.initial_field["seedlings"]
    if batch.quantity + batch.loaded + sum(p.seedlings_planted for p in world.field.plots) != original["quantity"] + original["loaded"]:
        failures.append("seedling accounting")
    supply = world.channel("supply")
    if supply.withdrawn_m3 > supply.quota_m3 + 1e-7:
        failures.append("water quota")
    delivered = sum(p.unit.volume_m3(world.backends[p.plot_id].water.ledger()["irrigation_mm"]) for p in world.field.plots)
    if abs(delivered - supply.delivered_m3) > 1e-6 or abs(supply.withdrawn_m3 * supply.efficiency - delivered) > 1e-6:
        failures.append("canal delivery accounting")
    drained = sum(p.unit.volume_m3(world.backends[p.plot_id].water.ledger()["drainage_mm"]) for p in world.field.plots)
    if abs(drained - world.channel("drain").discharged_m3) > 1e-6:
        failures.append("canal drainage accounting")
    if sum(p.stored_dry_kg / .86 for p in world.field.plots) > world.field.storage_capacity_kg + 1e-7:
        failures.append("grain storage capacity")
    if world.field.fuel_liters < 0:
        failures.append("negative fuel")
    f, initial = world.field, world.initial_field
    fuel = f.fuel_liters + sum(m.fuel_liters for m in f.machines) + f.fuel_used_liters
    if abs(fuel - initial["fuel_liters"] - sum(m["fuel_liters"] for m in initial["machines"])) > 1e-6:
        failures.append("fuel accounting")
    fertilizer = f.fertilizer_kg + sum(m.fertilizer_kg for m in f.machines) + f.fertilizer_applied_kg
    if abs(fertilizer - initial["fertilizer_kg"] - sum(m["fertilizer_kg"] for m in initial["machines"])) > 1e-6:
        failures.append("fertilizer accounting")
    applied_n = sum(p.unit.mass_kg(world.backends[p.plot_id].nitrogen.audit()["applied_n_kg_ha"]) for p in f.plots)
    if abs(applied_n - f.fertilizer_applied_kg * .46) > 1e-6:
        failures.append("fertilizer nitrogen accounting")
    for stock, used in (("electricity_kwh", "energy_used_kwh"), ("repair_material_kg", "repair_used_kg")):
        if abs(getattr(f, stock) + getattr(f, used) - initial[stock] - initial[used]) > 1e-6:
            failures.append(f"{stock} accounting")
    for key, used in f.chemicals_used.items():
        if abs(getattr(f, key) + used - initial[key] - initial["chemicals_used"][key]) > 1e-6:
            failures.append(f"{key} accounting")
    for p in f.plots:
        if abs(sum(b.dry_kg for b in f.grain_batches if b.plot_id == p.plot_id) - p.harvested_dry_kg) > 1e-6:
            failures.append(f"{p.plot_id}: batch accounting")
    if sum(b.wet_kg for b in f.grain_batches if b.location == "combine") > world.machine("combine").grain_capacity_wet_kg + 1e-6:
        failures.append("combine capacity")
    if not 0 <= f.drone_battery_pct <= 100:
        failures.append("drone battery bounds")
    return {"success": not failures, "failures": failures}
