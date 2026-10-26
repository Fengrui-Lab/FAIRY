"""Task goals and resource conservation for maize at any point in the season."""
from __future__ import annotations

import json

from fairy.apps.farm_world import FarmWorldApp, TractorApp
from fairy.scenarios.validation_result import ScenarioValidationResult


def task_state(scenario):
    """Read internal validation evidence without advancing the world."""
    farm = scenario.get_typed_app(FarmWorldApp)
    tractor = scenario.get_typed_app(TractorApp)
    backend = farm.physics.crop_backend
    inputs = {}
    for ridge in farm._ridges:
        rid = ridge.ridge_id
        run = backend._runs.get(rid)
        # A running crop already includes preplant totals in its cumulative input.
        if run:
            water, fertilizer = run.cumulative_irrigation_mm, run.cumulative_fertilizer_kg
        else:
            preplant = backend._preplant_totals.get(rid, {})
            water, fertilizer = preplant.get("irrigation_mm", 0), preplant.get("fertilizer_kg", 0)
        pending = backend._pending.get(rid, {})
        water += pending.get("irrigation_mm", 0)
        fertilizer += pending.get("fertilizer_kg", 0)
        for action in farm.physics.pending_management_actions_by_ridge.get(rid, []):
            kind = getattr(action.action_type, "value", action.action_type)
            meta = action.metadata or {}
            if kind == "IRRIGATION":
                water += float(meta.get("water_mm", action.amount))
            elif kind == "FERTIGATION":
                water += float(meta.get("water_mm", 0))
            if kind in {"FERTIGATION", "BASE_FERTILIZER"}:
                fertilizer += float(meta.get("fertilizer_kg_per_ridge", meta.get("kg_per_ridge", 0)))
        inputs[rid] = {"water": water, "fertilizer": fertilizer}
    native = list(backend._runs.values())
    mean = lambda key: sum(float(run.pcse.get(key) or 0) for run in native) / max(1, len(native))
    return {
        "time": farm.time_manager.time(),
        "planted": {r.ridge_id for r in farm._ridges if r.planted},
        "harvested": {r.ridge_id for r in farm._ridges if r.harvested},
        "emerged": {rid for rid, run in backend._runs.items() if run.pcse.get("DOE")},
        "mature": {rid for rid, run in backend._runs.items() if run.pcse.get("DOM")},
        "inputs": inputs,
        "fertilizer_used": farm._management_regime.fertilizer_used_kg,
        "water_used": farm._management_regime.irrigation_used_mm_total,
        "inventory": farm._inventory.to_dict(),
        "seed_hopper": tractor._seed_hopper,
        "fuel": tractor._fuel_tank_l,
        "spreader": tractor._fertilizer_spreader_kg,
        "grain_bin": tractor._grain_bin_kg,
        "trailer": farm._inventory.harvest_grain_kg,
        "warehouse": farm._inventory.warehouse_grain_kg,
        "moisture": farm._trailer_grain_moisture_pct(),
        "prep": list(tractor._completed_prep_ops),
        "operation_count": len(tractor._operation_log),
        "native_last_day": str(backend._last_day),
        "rftra": mean("RFTRA"), "n_uptake": mean("NuptakeTotal"), "biomass": mean("TAGP"),
        "stress_days": sum(s.cumulative_stress_days for s in farm.physics.canopy.states.values()) / farm.num_ridges,
    }


def _audit(scenario, state, workflow):
    farm = scenario.get_typed_app(FarmWorldApp)
    tractor = scenario.get_typed_app(TractorApp)
    spec = scenario.spec
    failures = []
    inventory = farm._inventory
    if any(v < -1e-6 for v in state["inventory"].values() if isinstance(v, (int, float))):
        failures.append("negative inventory")
    if any(v < 0 for v in inventory.seed_stock.values()):
        failures.append("negative seed inventory")
    if min(state["seed_hopper"], state["spreader"], state["fuel"], state["grain_bin"]) < -1e-6:
        failures.append("negative equipment inventory")
    if state["water_used"] > spec.irrigation_quota_mm + 1e-6:
        failures.append("irrigation quota exceeded")
    if state["fertilizer_used"] > spec.fertilizer_quota_kg + 1e-6:
        failures.append("fertilizer quota exceeded")
    if state["warehouse"] > farm._postharvest_market.storage_capacity_kg + 1e-6:
        failures.append("storage capacity exceeded")
    applied = sum(row["fertilizer"] for row in state["inputs"].values())
    if abs(inventory.fertilizer_kg + state["spreader"] + applied - spec.fertilizer_stock_kg) > 1e-5:
        failures.append("fertilizer inventory and native input accounting disagree")
    # Loading transfers warehouse stock to machinery. Only field application
    # consumes a farm's management quota; outstanding payload stays in stock.
    if abs(state["fertilizer_used"] - applied) > 1e-5:
        failures.append("fertilizer usage ledger disagrees with applied amounts")
    water = sum(row["water"] for row in state["inputs"].values()) / farm.num_ridges
    if abs(water - state["water_used"]) > 1e-5:
        failures.append("irrigation quota and native soil inputs disagree")
    planted_seeds = sum(item.get("seeds_used", 0) for item in tractor._operation_log
                        if item.get("operation") in {"plant_seeds", "replant_seeds"})
    initial = scenario._maize_initial_inventory
    if inventory.seed_stock.get("MAIZE_201", 0) + state["seed_hopper"] + planted_seeds != initial["seed_stock"]["MAIZE_201"]:
        failures.append("seed inventory and planting accounting disagree")
    recovered = sum(s.recovered_yield_g_m2_at_market_moisture
                    for s in farm.physics.yield_recovery.states.values() if s.harvested) * 268 * farm.ridge_width_m / 1000
    if abs(recovered - state["grain_bin"] - state["trailer"] - state["warehouse"]) > 0.2:
        failures.append("recovered grain and bin/trailer/warehouse accounting disagree")
    steps = list(workflow.dag.values()) if workflow is not None else []
    errors = [s.name for s in steps if s.error_type or s.op_type == "TOOL_ERROR"
              or isinstance(s.content, dict) and (s.content.get("error") or s.content.get("warning"))]
    if errors:
        failures.append("tool errors or unsafe-storage warnings occurred")
    return failures, errors, steps


def _stored_goals(scenario, state, failures):
    farm = scenario.get_typed_app(FarmWorldApp)
    if len(state["mature"]) != farm.num_ridges:
        failures.append("all 64 ridges must reach native physiological maturity")
    if len(state["harvested"]) != farm.num_ridges:
        failures.append("all 64 ridges must be harvested")
    if any(not s.harvested or s.drying_required or s.grain_moisture_frac is None
           or s.grain_moisture_frac > .14 + 1e-9 for s in farm.physics.yield_recovery.states.values()):
        failures.append("all harvested grain must be dried to at most 14% moisture")
    if state["warehouse"] <= 0 or state["trailer"] > 1e-6 or state["grain_bin"] > 1e-6:
        failures.append("all positive grain yield must be stored")


def _result(scenario, state, failures, errors, **metadata):
    return ScenarioValidationResult(
        success=not failures,
        message="; ".join(failures) if failures else "Maize task and resource checks passed",
        metadata={"scenario_id": scenario.scenario_id, "level": scenario.level, "task": scenario.task,
                  "failures": failures, "tool_errors": errors,
                  "harvested_ridges": len(state["harvested"]),
                  "warehouse_grain_kg_at_14pct": state["warehouse"],
                  "irrigation_used_mm": state["water_used"], "fertilizer_used_kg": state["fertilizer_used"],
                  "crop_config_fingerprint": scenario.get_typed_app(FarmWorldApp).physics.crop_backend.snapshot()["provenance"]["config_fingerprint"],
                  **metadata},
    )


def validate_maize(scenario, spec, *, workflow=None):
    state = task_state(scenario)
    failures, errors, _ = _audit(scenario, state, workflow if workflow is not None else scenario.workflow)
    _stored_goals(scenario, state, failures)
    return _result(scenario, state, failures, errors)


def validate_maize_task(scenario, *, workflow=None):
    state, initial, spec = task_state(scenario), scenario._task_initial, scenario.task_spec
    farm, tractor = scenario.get_typed_app(FarmWorldApp), scenario.get_typed_app(TractorApp)
    failures, errors, steps = _audit(scenario, state, workflow if workflow is not None else scenario.workflow)
    task = spec.task
    target = set(range(spec.target_ridges[0], spec.target_ridges[1] + 1))
    water = state["water_used"] - initial["water_used"]
    fertilizer = state["fertilizer_used"] - initial["fertilizer_used"]
    if water < -1e-6 or water > spec.water_budget_mm + 1e-6:
        failures.append("task irrigation budget exceeded or ledger reversed")
    if fertilizer < -1e-6 or fertilizer > spec.fertilizer_budget_kg + 1e-6:
        failures.append("task fertilizer budget exceeded or ledger reversed")
    elapsed = state["time"] - initial["time"]
    if elapsed < -1e-6 or elapsed > (spec.window_days + 3) * 86400:
        failures.append("task deadline exceeded")
    new_ops = tractor._operation_log[initial["operation_count"]:]
    if task in {"level", "form_ridges", "base_fertilize"}:
        if state["prep"].count(task) - initial["prep"].count(task) != 1:
            failures.append("one new preparation operation is required")
        if task in {"level", "form_ridges"} and tractor._attached_implement is not None:
            failures.append("preparation implement must be detached")
    if task == "form_ridges" and abs(farm.ridge_width_m - .75) > 1e-9:
        failures.append("maize ridge width must be 0.75 m")
    if task in {"plant", "establishment"}:
        if state["planted"] - initial["planted"] != target:
            failures.append("new planting must cover exactly the target ridges")
        for rid in target:
            ridge = farm._ridges[rid]
            if ridge.seed_type != "MAIZE_201" or ridge.seed_spacing_cm != 20 or ridge.seeds_planted != 1340:
                failures.append("incorrect seed identity, spacing or stand density")
                break
        planting = [op for op in new_ops if op.get("operation") == "plant_seeds"]
        if not planting or any(op.get("depth_cm") != 4.0 for op in planting):
            failures.append("planting depth must be 4 cm")
        if task == "establishment" and state["emerged"] != target:
            failures.append("all target ridges must have emerged")
    if task in {"base_fertilize", "establishment", "fertilize", "nutrition_management", "irrigate", "irrigation_management"}:
        kind = "water" if task in {"irrigate", "irrigation_management"} else "fertilizer"
        expected = spec.water_budget_mm if kind == "water" else spec.fertilizer_budget_kg / len(target)
        amounts = {rid: row[kind] - initial["inputs"][rid][kind] for rid, row in state["inputs"].items()}
        # L1 actions have prescribed doses. L2 management may use less if its
        # independently validated physiological outcome still meets the goal.
        if spec.level == "L1" or task == "establishment":
            if any(abs(value - (expected if rid in target else 0)) > 1e-5 for rid, value in amounts.items()):
                failures.append("target input amount or coverage is incorrect")
        elif not all(amounts[rid] > 0 for rid in target):
            failures.append("management must reach every target ridge")
    if task == "refuel":
        transferred = 100.0 - initial["fuel"]
        if transferred <= 0 or abs(state["fuel"] - 100.0) > 1e-6 or abs(initial["inventory"]["fuel_liters"] - state["inventory"]["fuel_liters"] - transferred) > 1e-6:
            failures.append("fill the 100-litre tank and account for the actual warehouse transfer")
    if task == "harvest":
        if state["harvested"] - initial["harvested"] != target or state["grain_bin"] <= initial["grain_bin"]:
            failures.append("target batch must be newly harvested into the grain bin")
        if state["trailer"] != initial["trailer"] or state["warehouse"] != initial["warehouse"]:
            failures.append("harvest-only task must retain grain in the bin")
    if task == "unload":
        if initial["grain_bin"] <= 0 or abs(state["grain_bin"]) > 1e-6 or abs(state["trailer"] - initial["trailer"] - initial["grain_bin"]) > 1e-6 or state["warehouse"] != initial["warehouse"]:
            failures.append("the initial grain-bin batch must move completely to the trailer")
    if task == "dry":
        if initial["moisture"] is None or initial["moisture"] <= 14 or state["moisture"] is None or state["moisture"] > 14 or not farm._inventory.grain_dried:
            failures.append("wet grain must actually be dried to at most 14%")
        if abs(state["trailer"] - initial["trailer"]) > 1e-6 or state["warehouse"] != initial["warehouse"]:
            failures.append("drying must preserve standardized grain mass in the trailer")
    if task == "store":
        if initial["trailer"] <= 0 or initial["moisture"] is None or initial["moisture"] > 14 or state["trailer"] > 1e-6 or abs(state["warehouse"] - initial["warehouse"] - initial["trailer"]) > 1e-6:
            failures.append("the safe initial trailer batch must move completely to storage")
    if task == "harvest_storage":
        _stored_goals(scenario, state, failures)
    if spec.window_days:
        if elapsed < spec.window_days * 86400:
            failures.append("the complete management observation window must elapse")
    tools = [s.tool_name or "" for s in steps]
    # Physical outcome alone cannot prove the required post-operation recheck.
    writes = [i for i, s in enumerate(steps) if s.op_type == "WRITE" and not (s.tool_name or "").startswith("AgentUserInterface__")]
    reads_after = tools[(writes[-1] + 1) if writes else len(tools):]
    if not any(name.startswith("FarmWorldApp__get_") for name in reads_after):
        failures.append("a post-operation farm recheck is required")
    if spec.level == "L2" and task in {"irrigation_management", "nutrition_management"}:
        # Generated offline from equal-weather/equal-duration managed and omitted
        # action runs. Validation never runs a control or finishes the season.
        from .farm_checkpoint_state import ARTIFACT_ROOT, REBUILD_COMMAND
        data = json.loads((ARTIFACT_ROOT / "scenario_artifacts.json").read_text())
        reference = data.get("management_thresholds", {}).get(task)
        if reference and (reference.get("initial_checkpoint_sha256") != scenario._checkpoint["sha256"]
                          or reference.get("source_fingerprint") != scenario._checkpoint["source_fingerprint"]):
            failures.append("management reference does not match the source checkpoint")
        if not reference:
            failures.append(f"missing management reference; rebuild with {REBUILD_COMMAND}")
        else:
            if state["native_last_day"] != reference["native_last_day"]:
                failures.append("management must finish on the calibrated observation day")
            key = reference["metric"]
            value = state[key]
            good = value <= reference["threshold"] if reference["direction"] == "lower" else value >= reference["threshold"]
            if not good:
                failures.append(f"management outcome {key} did not meet the fixed reference threshold")
        if "SensorApp__read_soil_sensors" not in reads_after:
            failures.append("management must finish with a soil observation")
    return _result(scenario, state, failures, errors,
                   source_l3_scenario_id=spec.source_l3_scenario_id,
                   source_checkpoint_label=spec.checkpoint_label,
                   checkpoint_sha256=scenario._checkpoint["sha256"],
                   task_elapsed_days=elapsed / 86400,
                   task_irrigation_mm=water, task_fertilizer_kg=fertilizer,
                   response={key: state[key] for key in ("rftra", "stress_days", "n_uptake", "biomass")})
