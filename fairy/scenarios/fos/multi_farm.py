"""Farm-qualified yield baselines and shared-clock maturity for FOS."""
from __future__ import annotations

import hashlib
import json

from fairy.apps.farm_world.multi_farm import farm_world_apps
from fairy.scenarios.fos.provenance import crop_backend_provenance


def farms_for_scenario(scenario):
    return farm_world_apps(getattr(scenario, "apps", None) or [])


def yield_is_mature(state):
    """Soybean/generic yield states use R8; native maize uses R6."""
    return bool(getattr(state, "r8_reached", False) or getattr(state, "r6_reached", False))


def farm_identity(farm):
    return {
        "farm_id": farm.farm_id,
        "num_ridges": farm.num_ridges,
        "field_length_m": farm.field_length_m,
        "ridge_width_m": farm.ridge_width_m,
        "crop_type": farm.crop_type,
        "profile_name": getattr(getattr(farm, "_physics", None), "profile_name", None),
        "crop_backend_provenance": crop_backend_provenance(farm),
    }


def fleet_provenance(scenario):
    farms = farms_for_scenario(scenario)
    identities = {farm.farm_id: farm_identity(farm) for farm in farms}
    if len(identities) != len(farms):
        raise ValueError("Multi-farm yield baselines require unique farm_id values")
    encoded = json.dumps(identities, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {"backend": "multi_farm", "config_fingerprint": hashlib.sha256(encoded).hexdigest(),
            "farms": identities}


def yield_provenance(scenario, single_farm=None):
    if len(farms_for_scenario(scenario)) > 1:
        return fleet_provenance(scenario)
    return crop_backend_provenance(single_farm)


def extrapolate_fleet(scenario, max_days):
    """Advance all farms together, through the same SystemApp as live runs."""
    from fairy.apps.system import SystemApp

    farms = farms_for_scenario(scenario)

    def maturity(farm):
        physics = getattr(farm, "_physics", None)
        if not getattr(physics, "engines_active", False):
            return None
        ids = [rid for rid, state in physics.phenology.states.items() if state.planted]
        return all(yield_is_mature(physics.yield_recovery.states.get(rid))
                   for rid in ids)

    status = {farm.farm_id: maturity(farm) for farm in farms}
    if any(value is None for value in status.values()):
        return {"status": "skipped", "reason": "physics_inactive", "days_ticked": 0,
                "reached_maturity": False, "farms": status}
    days = 0
    system = scenario.get_typed_app(SystemApp)
    while not all(status.values()) and days < max_days:
        result = system.advance_time(days=1)
        if isinstance(result, dict) and result.get("error"):
            return {"status": "error", "error": result["error"], "days_ticked": days,
                    "reached_maturity": False, "max_days": max_days, "farms": status}
        days += 1
        status = {farm.farm_id: maturity(farm) for farm in farms}
    return {"status": "advanced" if days else "noop", "days_ticked": days,
            "reached_maturity": all(status.values()), "max_days": max_days, "farms": status}


def fleet_yields(scenario):
    """Keep local ridge IDs inside their owning farm and apply its own area."""
    farms = {}
    for farm in farms_for_scenario(scenario):
        physics = getattr(farm, "_physics", None)
        if not getattr(physics, "engines_active", False):
            raise ValueError(f"Farm {farm.farm_id} has no active physics; biological yield is unavailable")
        area = farm.field_length_m * farm.ridge_width_m
        ridges = {}
        for rid, state in sorted(physics.yield_recovery.states.items()):
            phen = physics.phenology.states.get(rid)
            planted = bool(getattr(phen, "planted", False))
            bio = float(state.biological_yield_g_m2)
            harvested = bool(getattr(state, "harvested", False))
            ridges[str(rid)] = {
                "ridge_id": rid, "planted": planted, "mature": yield_is_mature(state),
                "harvested": harvested, "biological_yield_g_m2": bio,
                "biological_yield_kg": bio * area / 1000 if planted or bio > 0 else 0.0,
                "recovered_yield_kg": float(state.recovered_yield_g_m2_at_market_moisture) * area / 1000 if harvested else 0.0,
            }
        farms[farm.farm_id] = {**farm_identity(farm), "ridge_area_m2": area, "ridges": ridges,
            "biological_yield_kg_total": sum(r["biological_yield_kg"] for r in ridges.values()),
            "recovered_yield_kg_total": sum(r["recovered_yield_kg"] for r in ridges.values())}
    return {"farms": farms,
            "biological_yield_kg_total": sum(f["biological_yield_kg_total"] for f in farms.values()),
            "recovered_yield_kg_total": sum(f["recovered_yield_kg_total"] for f in farms.values())}
