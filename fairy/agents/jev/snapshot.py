"""Short farm snapshot for Jev, built by code before every decision.

Replaces the full action history (see docs/jev/PROGRESS.md, Part 2). Rules:

- Only values that the agent's own read tools report (farm overview, inventory,
  weather, sensor zones, machine status), plus Jev's own past action results.
  Never other hidden simulator fields, the oracle or the evaluator.
- Nothing is written to the simulation. The farm-overview and sensor tools
  advance the physics to the current time, and the physics depends on how
  often that happens, so calling them would change the season. Instead their
  values are read as stored after the last physics update (normally the end of
  Jev's last action): ridge fields as the overview shows them, and zone soil
  moisture/temperature and canopy NDVI averaged exactly as the sensors average
  them, without sensor noise. Weather, inventory and machine status come from
  their pure read tools. Checked with scripts/jev_offline_check.py --no-snapshot.
- Reads are not recorded as agent actions and are not scored.

`build_snapshot` returns (snapshot for Jev, raw facts for menus and checks).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

CST = timezone(timedelta(hours=8))
RECENT_ACTIONS = 5
RESULT_CHARS = 300
NOTIFICATIONS = 3
REPEAT_WARNING_AT = 3

# Result fields that announce when an effect will be ready (absolute sim time).
READY_AT_FIELDS = ("effect_ready_at", "charge_complete_at")
# Start/end argument pairs that name a ridge range.
RANGE_ARGS = (("start_ridge", "end_ridge"), ("start", "end"))


def ridge_ranges(ids: list[int]) -> str:
    """[0, 1, 2, 5] -> '0-2, 5'."""
    ids = sorted(set(ids))
    parts: list[str] = []
    start = prev = None
    for i in ids:
        if start is None:
            start = prev = i
        elif i == prev + 1:
            prev = i
        else:
            parts.append(f"{start}-{prev}" if start != prev else f"{start}")
            start = prev = i
    if start is not None:
        parts.append(f"{start}-{prev}" if start != prev else f"{start}")
    return ", ".join(parts)


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=CST).strftime("%Y-%m-%d %H:%M")


def _short(value: Any, limit: int = RESULT_CHARS) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _apps(toolsets: list[Any]) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for app in toolsets:
        out.setdefault(type(app).__name__, []).append(app)
    return out


def _ridges(farm: Any) -> list[dict[str, Any]]:
    """The farm-overview fields of every ridge, as stored (no refresh)."""
    return [
        {
            "ridge_id": r.ridge_id,
            "planted": r.planted,
            "harvested": r.harvested,
            "growth_stage": r.growth_stage,
            "grain_moisture_pct": round(r.grain_moisture_pct, 1),
        }
        for r in farm._ridges
    ]


def _zones(sensor_app: Any, farm: Any) -> tuple[list[str], list[str]]:
    """Soil and canopy readings per sensor zone, averaged as SensorApp._sync_sensors does."""
    physics = farm._physics  # never the `physics` property: first access switches physics on
    live = physics is not None and physics.engines_active and physics.last_physics_sim_time is not None
    soil, canopy = [], []
    for s in sensor_app._soil_sensors:
        ids = range(s["ridge_start"], s["ridge_end"] + 1)
        if live:
            vwc = sum(physics.soil.states[r].top_vwc for r in ids) / len(ids)
            temp = sum(physics.soil.states[r].top_temp_c for r in ids) / len(ids)
        else:
            vwc = sum(farm._ridges[r].soil_vwc for r in ids) / len(ids)
            temp = sum(farm._ridges[r].soil_temp_c for r in ids) / len(ids)
        soil.append(f"{s['sensor_id']} ridges {ids.start}-{ids.stop - 1}: vwc {vwc:.3f}, temp {temp:.1f} C")
    for s in sensor_app._canopy_sensors:
        ids = range(s["ridge_start"], s["ridge_end"] + 1)
        if live:
            states = [physics.canopy.states[r] for r in ids]
            ndvi = None if any(not st.initialized for st in states) else sum(st.ndvi_proxy for st in states) / len(states)
        else:
            planted = [farm._ridges[r] for r in ids if farm._ridges[r].planted]
            ndvi = sum(r.ndvi for r in planted) / len(planted) if planted else None
        if ndvi is not None:
            canopy.append(f"{s['sensor_id']} ridges {ids.start}-{ids.stop - 1}: ndvi {ndvi:.2f}")
    return soil, canopy


def _crop(ridges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group neighbouring ridges that share planted/harvested/stage."""
    groups: list[dict[str, Any]] = []
    for r in ridges:
        key = (r["planted"], r["harvested"], r["growth_stage"])
        if groups and groups[-1]["key"] == key and groups[-1]["ids"][-1] == r["ridge_id"] - 1:
            groups[-1]["ids"].append(r["ridge_id"])
            groups[-1]["moist"].append(r["grain_moisture_pct"])
        else:
            groups.append({"key": key, "ids": [r["ridge_id"]], "moist": [r["grain_moisture_pct"]]})
    out = []
    for g in groups:
        planted, harvested, stage = g["key"]
        row: dict[str, Any] = {"ridges": ridge_ranges(g["ids"])}
        if harvested:
            row["status"] = "harvested"
        elif not planted:
            row["status"] = "not planted"
        else:
            row["stage"] = stage
            lo, hi = min(g["moist"]), max(g["moist"])
            if hi > 0:
                row["grain_moisture_pct"] = lo if lo == hi else f"{lo}-{hi}"
        out.append(row)
    return out


def _inventory(inv: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in inv.items() if k not in ("management_regime", "postharvest_market")}
    regime = inv.get("management_regime") or {}
    limits = {k: v for k, v in regime.items() if v not in (None, 0, 0.0) and k != "regime"}
    if limits:
        out["limits_and_usage"] = limits
    market = inv.get("postharvest_market") or {}
    out["storage"] = {
        k: market.get(k)
        for k in ("max_storage_moisture_pct", "drying_capacity_kg_per_day", "storage_capacity_kg")
        if market.get(k) is not None
    }
    return out


def _tool_steps(workflow: Any) -> list[Any]:
    return [s for s in workflow.dag.values() if s.op_type in ("TOOL", "TOOL_ERROR")]


def _failed(step: Any) -> bool:
    return step.op_type == "TOOL_ERROR" or (
        isinstance(step.content, dict) and "error" in step.content
    )


def _range_of(args: dict[str, Any]) -> list[int] | None:
    for start, end in RANGE_ARGS:
        if isinstance(args.get(start), int) and isinstance(args.get(end), int):
            return list(range(args[start], args[end] + 1))
    if isinstance(args.get("ridge_id"), int):
        return [args["ridge_id"]]
    return None


def work_done(steps: list[Any]) -> dict[str, str]:
    """Successful actions of this run: ridge ranges covered, or a count."""
    ridges: dict[str, list[int]] = {}
    counts: dict[str, int] = {}
    for step in steps:
        if _failed(step) or getattr(step, "op_type", "") != "TOOL":
            continue
        name = step.tool_name
        rng = _range_of(step.tool_args or {})
        if rng is not None:
            ridges.setdefault(name, []).extend(rng)
        else:
            counts[name] = counts.get(name, 0) + 1
    out = {name: f"ridges {ridge_ranges(ids)}" for name, ids in ridges.items()}
    out.update({name: f"{n} times" for name, n in counts.items()})
    return out


def pending_effects(steps: list[Any], now: float) -> list[dict[str, Any]]:
    """Effects announced in Jev's own results that are not ready yet."""
    out = []
    for step in steps:
        result = step.content
        if _failed(step) or not isinstance(result, dict):
            continue
        for field in READY_AT_FIELDS:
            ready = result.get(field)
            if isinstance(ready, (int, float)) and ready > now:
                rng = _range_of(step.tool_args or {})
                out.append(
                    {
                        "from_action": step.tool_name,
                        "ridges": ridge_ranges(rng) if rng else None,
                        "ready_at": _fmt_time(ready),
                        "seconds_left": int(round(ready - now)),
                    }
                )
    return out


def repeat_count(steps: list[Any]) -> int:
    """How many times the last action (same arguments) was repeated in a row."""
    if not steps:
        return 0
    last = (steps[-1].tool_name, json.dumps(steps[-1].tool_args or {}, sort_keys=True))
    n = 0
    for step in reversed(steps):
        if (step.tool_name, json.dumps(step.tool_args or {}, sort_keys=True)) != last:
            break
        n += 1
    return n


def build_snapshot(toolsets: list[Any], workflow: Any, now: float) -> tuple[dict[str, Any], dict[str, Any]]:
    apps = _apps(toolsets)
    farm = apps["FarmWorldApp"][0]
    ridges = _ridges(farm)
    snap: dict[str, Any] = {
        "time": _fmt_time(now),
        "season_phase": farm._season_phase,
        "crop": _crop(ridges),
        "inventory": _inventory(farm.get_inventory()),
    }
    if "WeatherApp" in apps:
        weather = apps["WeatherApp"][0]
        snap["weather_today"] = weather.get_current_weather()
        snap["forecast_3_days"] = weather.get_forecast(3).get("forecast", [])
    if "SensorApp" in apps:
        soil, canopy = _zones(apps["SensorApp"][0], farm)
        snap["soil_by_sensor_zone"] = soil
        if canopy:
            snap["canopy_ndvi_by_sensor_zone"] = canopy
    machines: dict[str, Any] = {}
    for tractor in apps.get("TractorApp", []):
        status = tractor.get_status()
        status.pop("available_implements", None)
        machines[tractor.name] = status
    for kind in ("DroneApp", "RobotApp"):
        for app in apps.get(kind, []):
            status = app.check_status()  # battery from the charge timestamps; no state change
            machines[app.name] = {
                k: status[k] for k in ("battery_pct", "charging", "eta_minutes_to_full") if k in status
            }
    snap["machines"] = machines

    steps = _tool_steps(workflow)
    snap["actions_this_run"] = work_done(steps)
    snap["pending_effects"] = pending_effects(steps, now)
    notes = [s for s in workflow.dag.values() if s.op_type == "system"]
    if notes:
        snap["notifications"] = [
            {"time": s.time, "message": _short(s.content)} for s in notes[-NOTIFICATIONS:]
        ]
    recent = [
        {
            "action": s.tool_name,
            "arguments": s.tool_args or {},
            "failed": _failed(s),
            "result": _short(s.content),
        }
        for s in steps[-RECENT_ACTIONS:]
    ]
    repeats = repeat_count(steps)
    if repeats >= REPEAT_WARNING_AT:
        snap["warning"] = (
            f"The last action was repeated {repeats} times in a row with the same arguments; "
            "repeating it again will not change the result."
        )
    facts = {
        "ridges": ridges,
        "inventory": snap["inventory"],
        "machines": machines,
        "pending": snap["pending_effects"],
        "steps": steps,
    }
    return {"farm_now": snap, "recent_actions": recent}, facts
