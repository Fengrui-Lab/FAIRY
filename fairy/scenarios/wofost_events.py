"""Scenario-owned disturbances applied on physical days, before crop growth.

Call ``install_scenario_events(self, [...])`` in ``build_events_flow`` after
declaring farms and pinning their research weather with ``set_day_override``.
Dates use each farm's simulation calendar and intervals are[start,end).
Stopping an event stops injections; it never erases the resulting pressure.
The existing full farm checkpoint codec persists declarations and applied days.
These disturbances and the existing biotic coupling are engineering scenarios,
not field-calibrated pesticide efficacy or crop damage functions.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from math import isfinite
from typing import Literal


_KEY = "wofost_scenario_events"
_PRESSURE_FIELDS = {"disease": "disease_pressure", "insect": "insect_pressure", "weed": "weed_pressure"}


def _interval(event):
    if (not isinstance(event.event_id, str) or not event.event_id.strip()
            or not isinstance(event.farm_id, str) or not event.farm_id.strip()):
        raise ValueError("Scenario events require explicit event_id and farm_id")
    if type(event.start) is not date or type(event.end) is not date or event.start >= event.end:
        raise ValueError("Event dates must define a nonempty absolute[start,end) interval")


@dataclass(frozen=True)
class DroughtEvent:
    """Multiply only pinned daily rain; no direct soil/yield/temperature edits."""
    event_id: str
    farm_id: str
    start: date
    end: date
    rain_multiplier: float = 0.0

    def __post_init__(self):
        _interval(self)
        if isinstance(self.rain_multiplier, bool) or not isfinite(self.rain_multiplier) or not 0 <= self.rain_multiplier <= 1:
            raise ValueError("Drought rain_multiplier must be finite in[0,1]")


@dataclass(frozen=True)
class WeatherWindowEvent:
    """Set declared daily rain/wind in an explicit operational weather window.

    Values apply to every pinned day in[start,end); None leaves that original
    weather field unchanged. Rain is mm/day, not the whole-window total. This
    is a declared synthetic scenario intervention, not an observed NASA value.
    Temperature, humidity and radiation are never altered by this event.
    """
    event_id: str
    farm_id: str
    start: date
    end: date
    rain_mm: float | None = None
    wind_ms: float | None = None

    def __post_init__(self):
        _interval(self)
        if self.rain_mm is None and self.wind_ms is None:
            raise ValueError("WeatherWindowEvent must specify rain_mm and/or wind_ms")
        for name in ("rain_mm", "wind_ms"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not isfinite(value) or value < 0):
                raise ValueError(f"WeatherWindowEvent {name} must be finite and nonnegative")


@dataclass(frozen=True)
class PressureEvent:
    """Inject an explicit set or clipped increment into local biotic pressure.

    once/add is the default. daily/set deliberately reimposes the target every
    active day, potentially overwriting management reductions; its warning is
    retained in the event manifest. end does not clear remaining pressure.
    """
    event_id: str
    farm_id: str
    ridge_start: int
    ridge_end: int
    start: date
    end: date
    kind: Literal["disease", "insect", "weed"]
    value: float
    mode: Literal["set", "add"] = "add"
    repeat: Literal["once", "daily"] = "once"

    def __post_init__(self):
        _interval(self)
        if (type(self.ridge_start) is not int or type(self.ridge_end) is not int
                or not 0 <= self.ridge_start <= self.ridge_end):
            raise ValueError("Pressure event requires an inclusive nonnegative integer ridge range")
        if self.kind not in _PRESSURE_FIELDS or self.mode not in {"set", "add"} or self.repeat not in {"once", "daily"}:
            raise ValueError("Unknown pressure kind, mode or repeat")
        if isinstance(self.value, bool) or not isfinite(self.value) or not (-1 if self.mode == "add" else 0) <= self.value <= 1:
            raise ValueError("Pressure set requires[0,1]; add requires a finite increment in[-1,1]")


@dataclass(frozen=True)
class SoilNitrogenEvent:
    """Set real native CNB nitrogen pools once, before the declared day's growth.

    Values are kg N/ha, not fertilizer product or a 0-1 fertility index. The
    remaining reserve can change, but its initial release-rate reference stays
    unchanged. This external disturbance is recorded separately from Agent
    fertilizer applications; it neither consumes inventory nor applies recovery.
    Targets must already have a native soil run on the effective day.
    """
    event_id: str
    farm_id: str
    ridge_start: int
    ridge_end: int
    day: date
    available_n_kg_ha: float | None = None
    reserve_n_kg_ha: float | None = None

    def __post_init__(self):
        if (not isinstance(self.event_id, str) or not self.event_id.strip()
                or not isinstance(self.farm_id, str) or not self.farm_id.strip()):
            raise ValueError("Soil nitrogen events require explicit event_id and farm_id")
        if type(self.day) is not date:
            raise ValueError("Soil nitrogen event day must be an absolute calendar date")
        if (type(self.ridge_start) is not int or type(self.ridge_end) is not int
                or not 0 <= self.ridge_start <= self.ridge_end):
            raise ValueError("Soil nitrogen event requires an inclusive nonnegative integer ridge range")
        if self.available_n_kg_ha is None and self.reserve_n_kg_ha is None:
            raise ValueError("Soil nitrogen event must set an available and/or reserve pool")
        for value in (self.available_n_kg_ha, self.reserve_n_kg_ha):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not isfinite(value) or value < 0):
                raise ValueError("Soil nitrogen pool values must be finite nonnegative kg N/ha")


def _declaration(event):
    kind = ("drought" if isinstance(event, DroughtEvent) else "weather_window"
            if isinstance(event, WeatherWindowEvent) else "soil_nitrogen"
            if isinstance(event, SoilNitrogenEvent) else "pressure")
    return {"type": kind,
            **{key: value.isoformat() if type(value) is date else value for key, value in asdict(event).items()}}


def scenario_events_snapshot(farm):
    """JSON-safe audit view; full checkpoints already preserve this metadata."""
    return deepcopy((getattr(farm.physics, "scenario_metadata", None) or {}).get(_KEY, {}))


def install_scenario_events(scenario, events):
    """Bind a complete declaration once, using the same runtime for every runner.

    Reinstalling an identical plan preserves its injection ledger, including
    after checkpoint restore. Conflicting plans or unpinned weather days fail
    before changing any farm. Simultaneous pressure events follow file order.
    """
    from fairy.apps.farm_world.multi_farm import farm_world_apps

    events = list(events)
    if not events:
        return {}
    if any(not isinstance(event, (DroughtEvent, WeatherWindowEvent, PressureEvent, SoilNitrogenEvent)) for event in events):
        raise TypeError("Use DroughtEvent, WeatherWindowEvent, PressureEvent or SoilNitrogenEvent declarations")
    if len({event.event_id for event in events}) != len(events):
        raise ValueError("Scenario event IDs must be unique")
    start_time = getattr(scenario, "start_time", None)
    if start_time is None or not isfinite(start_time):
        raise ValueError("Scenario events require an explicit finite scenario start_time")
    worlds = farm_world_apps(scenario.apps or [])
    farms = {farm.farm_id: farm for farm in worlds}
    if len(farms) != len(worlds):
        raise ValueError("Scenario events require unique farm IDs")
    if any(event.farm_id not in farms for event in events):
        raise ValueError("Scenario event refers to an unknown farm_id")
    prepared = []
    for farm_id in dict.fromkeys(event.farm_id for event in events):
        farm = farms[farm_id]
        selected = [event for event in events if event.farm_id == farm_id]
        initial_day = datetime.fromtimestamp(start_time, farm.simulation_timezone).date()
        if any((event.day if isinstance(event, SoilNitrogenEvent) else event.start) < initial_day for event in selected):
            raise ValueError("Scenario events cannot start before the scenario's initial day")
        if any(isinstance(event, SoilNitrogenEvent) and event.day == initial_day for event in selected):
            raise ValueError("Use WORLD initial nitrogen for the initial day; soil nitrogen events require a started native run")
        declarations = [_declaration(event) for event in selected]
        prior = scenario_events_snapshot(farm)
        if prior:
            if prior.get("schema_version") != 1 or prior.get("events") != declarations:
                raise ValueError("Cannot replace an installed scenario event plan")
            prepared.append((farm, None, []))
            continue
        if date.fromisoformat(farm._sim_date) != initial_day:
            raise ValueError("Farm initial date must match the explicit scenario start before installing events")
        if not farm.physics.engines_active:
            raise ValueError("Configure active farm physics before installing scenario events")
        if farm.physics.last_physics_sim_time is not None:
            raise ValueError("Install new scenario events before advancing farm physics")
        weather_changes, occupied_fields = [], set()
        for event in selected:
            if isinstance(event, (PressureEvent, SoilNitrogenEvent)):
                if event.ridge_end >= farm.num_ridges:
                    raise ValueError("Scenario event exceeds the target farm's ridge range")
                if isinstance(event, SoilNitrogenEvent) and not callable(getattr(
                        farm.physics.crop_backend, "apply_soil_nitrogen_event", None)):
                    raise ValueError("Soil nitrogen events require the native WOFOST CNB backend")
                continue
            generator = farm.physics.weather_generator
            if generator is None:
                raise ValueError("Weather events require a configured pinned weather generator")
            if any(other is not farm and other.physics.weather_generator is generator for other in worlds):
                raise ValueError("A farm-specific weather event requires an independent weather generator")
            environment = getattr(farm, "farm_environment", None)
            if environment is not None and len(environment.farms) > 1:
                raise ValueError("A farm-specific weather event requires independent weather, not a shared regional provider")
            day = event.start
            while day < event.end:
                baseline = getattr(generator, "_day_overrides", {}).get(day)
                if baseline is None:
                    raise ValueError(f"Weather event day{day} must have an explicit pinned baseline forcing")
                if isinstance(event, DroughtEvent):
                    updates = {"rain_mm": baseline.rain_mm * event.rain_multiplier}
                else:
                    updates = {name: getattr(event, name) for name in ("rain_mm", "wind_ms")
                               if getattr(event, name) is not None}
                # No implicit precedence: two declarations cannot own the
                # same farm/day/field, including rain shared with DroughtEvent.
                # Independent rain-only and wind-only windows may overlap.
                if any((day, name) in occupied_fields for name in updates):
                    raise ValueError("Overlapping weather declarations for the same day/field are ambiguous")
                occupied_fields.update((day, name) for name in updates)
                weather_changes.append((event, baseline, updates))
                day += timedelta(days=1)
        warnings = [event.event_id + ": daily/set reimposes pressure before growth and can overwrite management reductions"
                    for event in selected if isinstance(event, PressureEvent) and event.repeat == "daily" and event.mode == "set"]
        state = {"schema_version": 1, "farm_id": farm_id, "events": declarations,
                 "applied_pressure_days": {}, "pressure_journal": [], "weather_changes": [],
                 "warnings": warnings, "stop_semantics": "Stop injection at end; never automatically clear pressure",
                 "pressure_order": "Declaration order, after legacy profile outbreaks and before management/crop growth"}
        if any(isinstance(event, SoilNitrogenEvent) for event in selected):
            state["applied_soil_nitrogen_events"] = []
            state["soil_nitrogen_semantics"] = (
                "Once before native daily growth; preserve initial reserve release reference; "
                "external nitrogen changes recorded in native journal, separate from fertilizer")
        prepared.append((farm, state, weather_changes))
    for farm, state, weather_changes in prepared:
        if state is None:
            continue
        for event, baseline, updates in weather_changes:
            # Read the current pin so a disjoint earlier wind/rain declaration
            # on this day is preserved rather than reset to the original row.
            current = farm.physics.weather_generator._day_overrides[baseline.day]
            tag = "scenario_drought:" if isinstance(event, DroughtEvent) else "scenario_weather_window:"
            farm.physics.weather_generator.set_day_override(
                current.day, current.air_temp_mean_c, updates.get("rain_mm", current.rain_mm),
                updates.get("wind_ms", current.wind_ms), current.solar_rad_mj_m2,
                air_temp_min_c=current.air_temp_min_c, air_temp_max_c=current.air_temp_max_c,
                relative_humidity_pct=current.relative_humidity_pct,
                weather_tags=[*current.weather_tags, tag + event.event_id])
            if isinstance(event, DroughtEvent):
                # Preserve the existing DroughtEvent ledger contract.
                record = {"event_id": event.event_id, "day": baseline.day.isoformat(),
                          "baseline_rain_mm": baseline.rain_mm, "rain_mm": updates["rain_mm"]}
            else:
                record = {"event_id": event.event_id, "day": baseline.day.isoformat(),
                          "type": "weather_window",
                          "before": {name: getattr(baseline, name) for name in updates},
                          "after": dict(updates)}
            state["weather_changes"].append(record)
        metadata = getattr(farm.physics, "scenario_metadata", None)
        if metadata is None:
            farm.physics.scenario_metadata = {}
        farm.physics.scenario_metadata[_KEY] = state
        # Initial-day disturbances are initial conditions, applied after the
        # normal physics seed so that the first daily boundary cannot erase them.
        start_time = getattr(scenario, "start_time", None)
        if start_time is not None:
            initial_day = date.fromisoformat(farm._sim_date)
            if any(isinstance(event, PressureEvent) and event.start == initial_day for event in events if event.farm_id == farm.farm_id):
                farm.sync_initial_physics_state(start_time)
                apply_scenario_events_for_day(farm, initial_day)
    # A World can build its initial forecast before build_events_flow installs
    # these declarations. Refresh the existing public view after replacing any
    # pin, so Agent/Oracle forecast and daily physics cannot disagree at startup.
    from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs

    for farm, _, _ in prepared:
        weather = getattr(farm, "_weather_app", None)
        if weather is not None:
            _build_weather_inputs(weather, date.fromisoformat(farm._sim_date),
                                  physics=farm.physics, advance_weather=False)
    return {farm.farm_id: scenario_events_snapshot(farm) for farm, _, _ in prepared}


def apply_scenario_events_for_day(farm, day: date):
    """Apply pressures and native N edits once, before physical growth."""
    state = (getattr(farm.physics, "scenario_metadata", None) or {}).get(_KEY)
    if not state:
        return []
    if state.get("schema_version") != 1 or state.get("farm_id") != farm.farm_id:
        raise ValueError("Scenario event checkpoint does not belong to this farm")
    previous = state.get("last_checked_day")
    if previous is not None and day.isoformat() < previous:
        raise ValueError("Scenario events cannot advance backwards")
    emitted = []
    for event in state["events"]:
        if event["type"] == "soil_nitrogen":
            if event["day"] != day.isoformat():
                continue
            applied = state.setdefault("applied_soil_nitrogen_events", [])
            if any(record["event_id"] == event["event_id"] for record in applied):
                continue
            farm.physics.crop_backend.apply_soil_nitrogen_event(
                event_id=event["event_id"], day=day,
                ridge_ids=list(range(event["ridge_start"], event["ridge_end"] + 1)),
                available_n_kg_ha=event["available_n_kg_ha"],
                reserve_n_kg_ha=event["reserve_n_kg_ha"])
            record = {**event, "status": "applied_before_native_growth"}
            applied.append(record)
            emitted.append(deepcopy(record))
            continue
        if event["type"] != "pressure" or not event["start"] <= day.isoformat() < event["end"]:
            continue
        applied = state["applied_pressure_days"].get(event["event_id"], [])
        if day.isoformat() in applied or event["repeat"] == "once" and (applied or day.isoformat() != event["start"]):
            continue
        field = _PRESSURE_FIELDS[event["kind"]]
        changes = []
        for rid in range(event["ridge_start"], event["ridge_end"] + 1):
            before = float(getattr(farm.physics.biotic.states[rid], field))
            value = event["value"] if event["mode"] == "set" else before + event["value"]
            after = max(0., min(1., value))
            farm.physics.biotic.set_pressure([rid], **{field: after})
            changes.append({"ridge_id": rid, "before": before, "after": after})
        record = {"event_id": event["event_id"], "day": day.isoformat(), "farm_id": farm.farm_id,
                  "kind": event["kind"], "mode": event["mode"], "repeat": event["repeat"], "changes": changes}
        state["applied_pressure_days"].setdefault(event["event_id"], []).append(day.isoformat())
        state["pressure_journal"].append(record)
        emitted.append(deepcopy(record))
    state["last_checked_day"] = day.isoformat()
    return emitted
