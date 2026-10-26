"""Pure proposals from public crop/scouting responses, never native state.

``decide_crop_management(observation, history=(), config=None)`` does not call
tools or advance time. The runner must re-read resources/weather, execute real
registered tools and add only successful receipts to history before deciding
again. Proposals are bounded management heuristics, not agronomic prescriptions.

Observation keys: now_day, date, farm_id, ridges, ground_observations,
ground_observed_day, management_regime, inventory, equipment_status, weather,
forecast, water_status, soil_sensors, capabilities and previous_observations. Tool ``data`` envelopes and
the Robot's ``observations``/``covered_ridges`` response are accepted. A water
status must identify its publicly observed ridge_ids and observed_day. Optional
root_zone_sensors require an explicit root_zone_adequate_vwc policy threshold.
Previous observations are earlier public snapshots, not private/audit records.
The manual-pesticide path must be explicitly registered in capabilities. Its
3L/ridge backpack reference draws directly from the common warehouse; it cannot
use chemical already loaded into a tractor tank.

History entries describe successful actions: day, operation, start, end, dose;
tool_args plus a registered receipt are also accepted. Explicit failed/partial
receipts do not establish a completed treatment. Intervals below are conservative
policy choices informed by FAIRY residual windows, not API-enforced label rules.
"""
from __future__ import annotations

from collections.abc import Mapping
from math import isfinite


DEFAULTS = {
    "confidence_threshold": 0.6,
    "max_observation_age_days": 3.0,
    "fungicide_interval_days": 14.0,
    "insecticide_interval_days": 10.0,
    "herbicide_interval_days": 18.0,
    "mechanical_interval_days": 7.0,
    "fertilizer_interval_days": 14.0,
    "max_fertilizer_events_per_ridge": 2,
    "nutrient_index_threshold": 0.75,
    "nutrient_persistence_days": 2.0,
    "nutrient_history_max_age_days": 10.0,
    "fertilizer_nutrient_amount": 0.12,
    "fertilizer_water_mm": 0.0,
    "root_zone_adequate_vwc": None,
    "planned_insecticide_reserve_fraction": 0.25,
    "weed_method": "auto",
}
CHEMICALS = {
    "apply_fungicide": ("fungicide", 3.8, "fungicide_tank_l"),
    "spray_pesticide": ("insecticide", 8.0, "pesticide_tank_l"),
    "apply_herbicide": ("herbicide", 8.0, "pesticide_tank_l"),
    "apply_pesticide_manual": ("insecticide", 3.0, None),
}
KINDS = {op: data[0] for op, data in CHEMICALS.items()}
KINDS.update({"apply_pesticide": "insecticide", "apply_pesticide_manual": "insecticide",
              "mechanical_weed_control": "mechanical", "apply_fertigation": "fertilizer",
              "apply_fertilizer": "fertilizer"})


def _unwrap(value):
    value = value if isinstance(value, Mapping) else {}
    return value["data"] if isinstance(value.get("data"), Mapping) else value


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if isfinite(value) else None
    except (ValueError, TypeError):
        return None


def _rows(value):
    if isinstance(value, Mapping):
        value = _unwrap(value).get("ridges", [])
    return {r["ridge_id"]: r for r in (value or [])
            if isinstance(r, Mapping) and type(r.get("ridge_id")) is int}


def _ground(value):
    value = _unwrap(value)
    covered = value.get("covered_ridges")
    values = value.get("observations", value)
    result = {}
    for rid, row in values.items():
        if not isinstance(row, Mapping):
            continue
        try:
            rid = int(row.get("ridge_id", rid))
        except (ValueError, TypeError):
            continue
        if covered is None or rid in covered:
            result[rid] = row
    return result


def _stage(row):
    value = str(row.get("growth_stage", "")).upper()
    if value.startswith("R") and len(value) > 1 and value[1].isdigit():
        return 10 + int(value[1])
    if value.startswith("V") and value not in {"VE", "VC"}:
        return 4
    return 0


def _actions(history):
    result = []
    for entry in history:
        if not isinstance(entry, Mapping) or entry.get("success") is False:
            continue
        receipt = _unwrap(entry.get("receipt", entry.get("result", entry.get("response", {}))))
        if receipt.get("error") or receipt.get("status") in {"error", "partial", "failed"}:
            continue
        op = str(entry.get("operation", entry.get("tool_name", ""))).rsplit("__", 1)[-1]
        if op not in KINDS:
            continue
        args = entry.get("tool_args", entry.get("args", {}))
        first = entry.get("start", args.get("start_ridge", args.get("start", args.get("ridge_id"))))
        count = args.get("ridge_count", 1)
        default_last = first + count - 1 if type(first) is int and type(count) is int else first
        last = entry.get("end", args.get("end_ridge", args.get("end", default_last)))
        day = _number(entry.get("day", entry.get("now_day")))
        if day is None or type(first) is not int or type(last) is not int or first > last:
            raise ValueError("Successful management history needs day/start/end")
        chemical_liters = None
        if KINDS[op] == "insecticide" and (entry.get("success") is True or receipt.get("status") in {"ok", "success"}):
            # A real receipt is stronger evidence than a requested dose. Older
            # successful records without either leave their contribution unknown.
            chemical_liters = _number(receipt.get("pesticide_used_liters"))
            if chemical_liters is None:
                dose = entry.get("dose", args.get("liters_per_ridge"))
                per_ridge = _number(dose.get("liters_per_ridge") if isinstance(dose, Mapping) else dose)
                if per_ridge is not None and per_ridge > 0:
                    chemical_liters = per_ridge * (last - first + 1)
            if chemical_liters is not None and chemical_liters < 0:
                chemical_liters = None
        result.append({"kind": KINDS[op], "day": day, "start": first, "end": last,
                       "chemical_liters": chemical_liters})
    return result


def _ranges(ids, width=10):
    group = []
    for rid in sorted(set(ids)):
        if group and (rid != group[-1] + 1 or len(group) == width):
            yield group
            group = []
        group.append(rid)
    if group:
        yield group


def _water_adequate(observation, rid, day, config):
    status = _unwrap(observation.get("water_status", {}))
    age = _number(status.get("observed_day"))
    if (status.get("adequate") is True and rid in status.get("ridge_ids", [])
            and age is not None and 0 <= day - age <= config["max_observation_age_days"]):
        return True
    threshold = config["root_zone_adequate_vwc"]
    root = _unwrap(observation.get("root_zone", {}))
    if threshold is None:
        return False
    for sensor in root.get("root_zone_sensors", observation.get("root_zone_sensors", [])):
        water = _number(sensor.get("root_vwc"))
        if sensor.get("ridge_start", -1) <= rid <= sensor.get("ridge_end", -1):
            if water is not None and water >= threshold:
                return True
    return False


def decide_crop_management(observation, history=(), config=None):
    """Return executable proposals plus explicit skips and mechanism limits.

    Every proposal has operation/start/end/dose/reasons/risks. Chemical working
    fluid uses the existing FAIRY references: fungicide3.8 and insect/herbicide8
    L/ridge, or3L/ridge through a registered manual backpack path. A fertilizer dose is a small simulated N amendment; its index is
    converted by the API to30kg product/ridge per1.0, not a soil-test prescription.
    """
    supplied = dict(config or {})
    unknown = set(supplied) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"Unknown crop policy parameters: {sorted(unknown)}")
    config = {**DEFAULTS, **supplied}
    for key, value in config.items():
        if key == "weed_method":
            if value not in {"auto", "mechanical", "chemical"}:
                raise ValueError("weed_method must be auto/mechanical/chemical")
        elif key == "root_zone_adequate_vwc" and value is None:
            continue
        elif _number(value) is None or float(value) < 0:
            raise ValueError(f"Invalid policy parameter: {key}")
    if not 0 <= config["confidence_threshold"] <= 1:
        raise ValueError("confidence_threshold must be0..1")
    reserve_fraction = _number(config["planned_insecticide_reserve_fraction"])
    if not 0 <= reserve_fraction <= 1:
        raise ValueError("planned_insecticide_reserve_fraction must be0..1")
    day = _number(observation.get("now_day"))
    if day is None or day < 0:
        raise ValueError("now_day must be a finite nonnegative scenario-relative day")
    ridges = _rows(observation.get("ridges", []))
    ground = _ground(observation.get("ground_observations", {}))
    actions = _actions(history)
    regime = _unwrap(observation.get("management_regime", observation.get("management", {})))
    regime = regime.get("management_regime", regime)
    inventory = _unwrap(observation.get("inventory", {}))
    machine = _unwrap(observation.get("equipment_status", {}))
    weather = _unwrap(observation.get("weather", {}))
    capabilities = _unwrap(observation.get("capabilities", {}))
    surface = observation.get("soil_sensors", observation.get("surface", {}))
    sensors = surface if isinstance(surface, list) else _unwrap(surface).get("soil_sensors", [])
    surface_values = [_number(sensor.get("vwc")) for sensor in sensors if isinstance(sensor, Mapping)]
    wet_surface = any(value is not None and value > .35 for value in surface_values)
    manual_preferred = capabilities.get("manual_pesticide_registered") is True and (
        capabilities.get("prefer_manual_pesticide") is True or wet_surface)
    ingredient_cap = _number(regime.get("active_ingredient_cap_kg"))
    ingredient_used = _number(regime.get("active_ingredient_used_kg")) or 0.0
    chemical_allowance_exhausted = ingredient_cap is not None and ingredient_cap <= ingredient_used + 1e-9
    proposals, skipped = [], []
    unsupported = [
        "Public nutrition/leaf-color signals do not establish native local N stocks, K/micronutrient deficiency or nodulation failure.",
        "Ground pest/disease booleans are not measured insect counts or pathogen severity; SPAD/native pressures are not assumed available.",
    ]
    confidence = config["confidence_threshold"]
    candidates = {op: [] for op in [*CHEMICALS, "mechanical_weed_control", "apply_fertigation"]}

    def skip(rid, reason):
        skipped.append({"ridge_ids": [rid] if type(rid) is int else list(rid), "reason": reason})

    def recent(rid, kind):
        return [a for a in actions if a["kind"] == kind and a["start"] <= rid <= a["end"]]

    for rid, row in sorted(ridges.items()):
        stage = _stage(row)
        if not row.get("planted") or row.get("harvested") or not 1 <= stage <= 16:
            continue
        diagnosis = ground.get(rid)
        if diagnosis is None:
            skip(rid, "No covered public ground diagnosis; no treatment inferred from NDVI or private pressure")
            continue
        observed = _number(diagnosis.get("observed_day", observation.get("ground_observed_day", day)))
        if observed is None or not 0 <= day - observed <= config["max_observation_age_days"]:
            skip(rid, "Ground diagnosis stale or from the future; rescout")
            continue
        for signal, op in [("disease", "apply_fungicide"), ("pest", "spray_pesticide"), ("weed", "apply_herbicide")]:
            score = _number(diagnosis.get(signal + "_confidence"))
            if diagnosis.get(signal + "_present") is not True or score is None or score < confidence:
                continue
            kind = KINDS[op]
            if signal == "pest" and manual_preferred:
                op = "apply_pesticide_manual"
            if signal == "weed" and (config["weed_method"] == "mechanical" or
                    config["weed_method"] == "auto" and (chemical_allowance_exhausted or
                        regime.get("regime") in {"organic", "low_input_organic"})):
                op, kind = "mechanical_weed_control", "mechanical"
                if stage > 13:
                    skip(rid, "Conservative mechanical-weeding window ends at R3; no automatic organic herbicide substitution")
                    continue
            if (signal == "weed" and op == "apply_herbicide" and ingredient_cap is not None
                    and diagnosis.get("weed_pressure_band") == "low"):
                skip(rid, "Finite shared chemical allowance: low-band weed signal requires reinspection, not immediate herbicide")
                continue
            prior = recent(rid, kind)
            if any(day - a["day"] < config[kind + "_interval_days"] for a in prior):
                skip(rid, f"{kind} policy interval still active; observe response instead of repeating")
                continue
            if kind == "insecticide" and not prior:
                days_ago = _number(row.get("pesticide_applied_days_ago"))
                if days_ago is not None and 0 <= days_ago < config["insecticide_interval_days"]:
                    skip(rid, "Public days-since-pesticide indicates a recent insecticide application")
                    continue
            candidates[op].append(rid)

        visible_deficit = diagnosis.get("leaf_nutrition_band") == "deficient" or diagnosis.get("nutrient_deficiency_signal") is True
        nutrition = _number(row.get("nutrient_index"))
        if not visible_deficit or nutrition is None or nutrition >= config["nutrient_index_threshold"]:
            continue
        if stage > 13:
            skip(rid, "Conservative nutrition window ends at R3; late-season leaf decline is not automatically fertilized")
            continue
        clear = all(diagnosis.get(s + "_present") is False and
                    (_number(diagnosis.get(s + "_confidence")) or 0) >= confidence
                    for s in ["disease", "pest", "weed"])
        if not clear or not _water_adequate(observation, rid, day, config):
            skip(rid, "Fertilizer needs affirmative water adequacy and confident biotic-negative diagnosis")
            continue
        persistent = False
        for previous in observation.get("previous_observations", []):
            previous_day = _number(previous.get("now_day"))
            previous_row = _rows(previous.get("ridges", [])).get(rid, {})
            previous_n = _number(previous_row.get("nutrient_index"))
            if (previous_day is not None and config["nutrient_persistence_days"] <= day - previous_day <= config["nutrient_history_max_age_days"]
                    and previous_n is not None and previous_n < config["nutrient_index_threshold"]):
                persistent = True
        prior = recent(rid, "fertilizer")
        if not persistent:
            skip(rid, "No separated earlier public low-nutrition observation; confirm persistence first")
        elif len(prior) >= config["max_fertilizer_events_per_ridge"] or any(day - a["day"] < config["fertilizer_interval_days"] for a in prior):
            skip(rid, "Fertilizer interval or per-ridge seasonal policy limit reached")
        else:
            candidates["apply_fertigation"].append(rid)

    # Reserve all returned proposals against one shared stock/quota ledger.
    chemical_stock = _number(inventory.get("pesticide_liters"))
    fertilizer_stock = _number(inventory.get("fertilizer_kg"))
    tanks = {key: max(0.0, _number(machine.get(key)) or 0.0) for key in ["fungicide_tank_l", "pesticide_tank_l"]}
    ingredient_used = _number(regime.get("active_ingredient_used_kg")) or 0.0
    fertilizer_used = _number(regime.get("fertilizer_used_kg")) or 0.0
    water_used = _number(regime.get("irrigation_used_mm_total")) or 0.0
    machine_used = _number(regime.get("machine_passes_used")) or 0.0
    weed_ridges_used = _number(regime.get("mechanical_weed_ridges_treated")) or 0.0
    raining = _number(weather.get("rainfall_mm"))
    wind = _number(weather.get("wind_speed_ms"))
    organic = regime.get("regime") in {"organic", "low_input_organic"}
    num_ridges = int(observation.get("num_ridges", len(ridges) or 1))
    # This transparent engineering reserve is activated by the source plan's
    # public manual-insecticide objective, not by private future outbreaks.
    # Unclassified legacy use is not assumed to have met that objective.
    reserve_enabled = capabilities.get("prefer_manual_pesticide") is True and ingredient_cap is not None
    reserve_target = max(0., ingredient_cap) * reserve_fraction if reserve_enabled else 0.
    insect_history = [a for a in actions if a["kind"] == "insecticide" and a["day"] <= day]
    known_insect_kg = sum(a["chemical_liters"] * .001 for a in insect_history if a["chemical_liters"] is not None)
    credited_insect_kg = min(max(0., ingredient_used), known_insect_kg)
    remaining_reserve = max(0., reserve_target - credited_insect_kg)
    chemical_budget_audit = {"reserve_enabled": reserve_enabled,
        "planned_insecticide_reserve_fraction": reserve_fraction,
        "active_ingredient_cap_kg": ingredient_cap, "public_active_ingredient_used_kg": ingredient_used,
        "planned_reserve_kg": reserve_target, "known_successful_insecticide_used_kg": known_insect_kg,
        "credited_insecticide_used_kg": credited_insect_kg,
        "insecticide_history_entries_without_known_dose": sum(a["chemical_liters"] is None for a in insect_history),
        "remaining_reserve_before_proposals_kg": remaining_reserve,
        "planning_only_not_physical_quota_deduction": True,
        "unknown_history_rule": "Public use without an explicit success receipt/flag and a known insecticide dose does not release the reserve; known history credit never exceeds public total use.",
        "basis": "Reserve from the source's explicit manual insecticide objective;0.25 is a searchable engineering policy parameter, not a literature prescription or proven optimum."}

    # Plan scarce mechanical passes before allocating their budget. A continuous
    # machine window can include inspected negatives only when an explicit
    # half of that completely observed window has medium/high weed evidence.
    # Exact symptomatic fragments remain candidates after the stronger windows.
    mechanical_plans, mechanical_planning_audit = [], []
    confirmed = set(candidates["mechanical_weed_control"])
    window_covered = set()
    for start in range(0, num_ridges, 10):
        ids = list(range(start, min(start + 10, num_ridges)))
        if not confirmed.intersection(ids):
            continue
        covered = [rid for rid in ids if rid in ground and
                   type(ground[rid].get("weed_present")) is bool and
                   _number(ground[rid].get("weed_confidence")) is not None]
        fresh = [rid for rid in covered if
                 (observed := _number(ground[rid].get("observed_day", observation.get("ground_observed_day", day)))) is not None
                 and 0 <= day - observed <= config["max_observation_age_days"]]
        positive = [rid for rid in fresh if ground[rid]["weed_present"] is True and
                    _number(ground[rid]["weed_confidence"]) >= confidence and
                    ground[rid].get("weed_pressure_band") in {"medium", "high"}]
        high = [rid for rid in positive if ground[rid]["weed_pressure_band"] == "high"]
        checks = {"all_public_ridges_available": all(rid in ridges for rid in ids),
                  "all_planted_unharvested": all(ridges.get(rid, {}).get("planted") and not
                      ridges.get(rid, {}).get("harvested") for rid in ids),
                  "all_stages_V1_through_R3": all(1 <= _stage(ridges.get(rid, {})) <= 13 for rid in ids),
                  "all_ground_observed": len(covered) == len(ids),
                  "all_ground_fresh": len(fresh) == len(ids),
                  "no_recent_mechanical_treatment": not any(day - a["day"] < config["mechanical_interval_days"]
                      for rid in ids for a in recent(rid, "mechanical")),
                  "medium_high_positive_fraction_at_least_half": len(positive) / len(ids) >= .5}
        audit = {"kind": "continuous_observed_machine_window", "start": ids[0], "end": ids[-1],
                 "window_ridge_count": len(ids), "observed_ridge_count": len(covered),
                 "fresh_ridge_count": len(fresh), "medium_high_positive_count": len(positive),
                 "high_positive_count": len(high), "positive_fraction": len(positive) / len(ids),
                 "observed_single_inspection_negative_ridges": [rid for rid in covered if ground[rid]["weed_present"] is False],
                 "checks": checks, "eligible": all(checks.values())}
        mechanical_planning_audit.append(audit)
        if audit["eligible"]:
            mechanical_plans.append({"ids": ids, "audit": audit})
            window_covered.update(ids)
    mechanical_plans.sort(key=lambda p: (-p["audit"]["positive_fraction"],
                                         -p["audit"]["high_positive_count"], p["ids"][0]))
    fragments = [{"ids": group, "audit": {"kind": "exact_confirmed_fragment",
                  "confirmed_ridge_count": len(group), "includes_observed_negative_ridges": False}}
                 for group in _ranges(confirmed - window_covered)]
    fragments.sort(key=lambda p: (-len(p["ids"]), -sum(ground[rid].get("weed_pressure_band") == "high"
                                                    for rid in p["ids"]), p["ids"][0]))
    mechanical_plans.extend(fragments)

    def cap_ok(name, used, extra):
        cap = regime.get(name)
        return cap is None or (_number(cap) is not None and used + extra <= float(cap) + 1e-9)

    for op, ids in candidates.items():
        plans = mechanical_plans if op == "mechanical_weed_control" else [
            {"ids": group} for group in _ranges(ids, width=2 if op == "apply_pesticide_manual" else 10)]
        for plan in plans:
            group = plan["ids"]
            count, dose = len(group), {}
            resources = {}
            risks = ["Re-read current weather, target field state, stock and machine status immediately before execution; tool preflight remains authoritative."]
            if op in CHEMICALS:
                kind, liters, tank = CHEMICALS[op]
                used = _number(regime.get(kind + "_applications_used")) or 0.0
                already_today = regime.get("last_" + kind + "_application_day") == observation.get("date") and observation.get("date") is not None
                if organic:
                    skip(group, f"{kind} forbidden by organic regime")
                    continue
                if raining != 0 or wind is None or wind >= 6.5:
                    skip(group, "Spraying requires a public dry-weather reading and wind below6.5m/s")
                    continue
                if kind in {"fungicide", "insecticide"} and not cap_ok("max_" + kind + "_applications", used, 0 if already_today else 1):
                    skip(group, f"{kind} seasonal application-day cap exhausted")
                    continue
                required = count * liters
                onboard = tanks[tank] if tank is not None else 0.0
                if chemical_stock is None or chemical_stock + onboard < required - 1e-9:
                    skip(group, "Insufficient common warehouse chemical stock for manual spraying" if tank is None else
                         "Insufficient known common chemical stock plus the correct onboard tank")
                    continue
                if not cap_ok("active_ingredient_cap_kg", ingredient_used, required * 0.001):
                    skip(group, "Modeled chemical active-ingredient quota exhausted")
                    continue
                if kind != "insecticide" and not cap_ok("active_ingredient_cap_kg", ingredient_used,
                                                       required * .001 + remaining_reserve):
                    skip(group, "Preserve the remaining planning reserve for the source's explicit insecticide objective; recheck other treatment priority")
                    continue
                used_tank = min(required, onboard)
                if tank is not None:
                    tanks[tank] -= used_tank
                chemical_stock -= required - used_tank;ingredient_used += required * 0.001
                if kind == "insecticide":
                    remaining_reserve = max(0., remaining_reserve - required * .001)
                dose = {"liters_per_ridge": liters}
                resources = {"chemical_liters": required, "modeled_active_ingredient_kg": required * 0.001}
                risks.append("FAIRY working-fluid reference and its fixed0.001kg/L quota conversion are simulation assumptions, not product labels or field prescriptions.")
                reasons = [f"Fresh covered {kind} symptom diagnosis with confidence>={confidence}"]
                if reserve_enabled:
                    reasons.append(f"Explicit source insecticide task: reserve fraction{reserve_fraction} is a planning constraint, not an additional physical quota charge")
                    risks.append("The insecticide reserve fraction is a searchable engineering choice, not a published prescription or proven optimum.")
                if tank is None:
                    resources["chemical_source"] = "common_warehouse_only"
                    reasons.append("Registered backpack path selected by explicit preference or public wet surface; no tractor-tank borrowing")
                    risks.append("Each manual pass must consume the registered operator time; do not retain zero-duration spray parameters.")
            elif op == "mechanical_weed_control":
                if raining is None or raining > 0:
                    skip(group, "Defer mechanical work during rain or missing weather; recheck local trafficability")
                    continue
                if wet_surface:
                    skip(group, "Public surface probe exceeds0.35VWC; defer mechanical work and recheck trafficability")
                    continue
                if not cap_ok("max_machine_passes", machine_used, 1) or not cap_ok("max_mechanical_weed_ridges", weed_ridges_used, count):
                    skip(group, "Mechanical-weeding pass or treated-ridge budget exhausted")
                    continue
                machine_used += 1;weed_ridges_used += count
                resources = {"machine_passes": 1, "mechanically_treated_ridges": count}
                reasons = ["Fresh covered weed diagnosis; use the permitted mechanical path"]
                if plan["audit"]["kind"] == "continuous_observed_machine_window":
                    audit = plan["audit"]
                    reasons.append(f"Continuous machine window: {audit['medium_high_positive_count']}/{count} medium/high weed positives; all ridges observed freshly, planted and V1–R3, with no recent mechanical treatment")
                    reasons.append(f"Window includes {len(audit['observed_single_inspection_negative_ridges'])} already-observed single-inspection negatives; no unobserved ridges are treated")
                    risks.append("Window prevalence is a bounded policy rule over diagnosed ridges, not measured weed cover or an agronomic economic threshold.")
                if config["weed_method"] == "auto" and chemical_allowance_exhausted:
                    reasons.append("Public remaining chemical active-ingredient allowance is zero; select legal mechanical weed control")
                risks.append("The current machine-pass counter applies to mechanical weeding, not every tractor operation.")
            else:
                amount, carrier = config["fertilizer_nutrient_amount"], config["fertilizer_water_mm"]
                kg, mm = amount * 30 * count, carrier * count / max(1, num_ridges)
                if amount <= 0 or fertilizer_stock is None or fertilizer_stock < kg or not cap_ok("fertilizer_quota_kg", fertilizer_used, kg) or not cap_ok("irrigation_quota_mm_total", water_used, mm):
                    skip(group, "Fertilizer/carrier-water stock, positive dose or field quota unavailable")
                    continue
                fertilizer_stock -= kg;fertilizer_used += kg;water_used += mm
                dose = {"nutrient_amount": amount, "water_mm": carrier}
                resources = {"fertilizer_product_kg": kg, "field_equivalent_irrigation_mm": mm}
                reasons = ["Visible deficiency plus persistent public low nutrition; water adequate and observed biotic causes excluded"]
                risks.append("This is a bounded simulated nitrogen amendment; it does not establish K/micronutrient or biological-fixation recovery.")
            proposal = {"operation": op, "start": group[0], "end": group[-1], "dose": dose,
                              "farm_id": observation.get("farm_id"), "reasons": reasons, "risks": risks,
                              "resource_requirements": resources, "recheck_after_days": 3.0}
            if op == "mechanical_weed_control":
                proposal["audit"] = plan["audit"]
            proposals.append(proposal)
    chemical_budget_audit["remaining_reserve_after_proposals_kg"] = remaining_reserve
    chemical_budget_audit["projected_active_ingredient_used_kg"] = ingredient_used
    return {"proposals": proposals, "skipped": skipped, "unsupported": unsupported,
            "mechanical_planning_audit": mechanical_planning_audit,
            "chemical_budget_audit": chemical_budget_audit}
