"""Freeze one declared daily weather input for every management comparison.

This is experiment setup, never an Agent tool or a management decision. The
existing generator is copied and queried in a declared date order; its actual
values, including any existing cache, are retained without fitting weather to
yield. Old runs with a different query order are historical references only.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from scripts.compile_wofost_observed_oracle import clean, save
from scripts.formal90_calibration_policy import CalibrationCompiler


def _hash(value):
    return hashlib.sha256(json.dumps(clean(value), sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _bindings(scenario):
    from fairy.apps.farm_world.multi_farm import farm_world_apps

    result = []
    for farm in sorted(farm_world_apps(scenario.apps or []), key=lambda f: f.name):
        physics = farm.physics
        generator = physics.weather_generator
        events = getattr(getattr(physics, "profile", None), "weather_events", []) or []
        weather = getattr(farm, "_weather_app", None)
        # Managed fleets own a station generator separate from the farm's
        # declaration. Pin the actual source as well as the declaration.
        runtime = getattr(weather, "runtime", None)
        station_id = getattr(weather, "station_id", None)
        source = getattr(runtime, "_station_forcing", {}).get(station_id)
        actual = source.get("generator") if source is not None else generator
        if source is not None:
            events = source.get("events", [])
        if actual is None or not hasattr(actual, "set_day_override"):
            raise ValueError(f"Farm {farm.name} requires a declared pinnable weather generator")
        station = getattr(weather, "station", weather)
        result.append({"farm": farm, "generator": actual, "declaration": generator,
                       "weather": station, "events": events})
    if not result:
        raise ValueError("No farm weather generators to freeze")
    return result


def _signature(binding):
    generator = binding["generator"]
    return _hash({"generator_class": type(generator).__module__ + "." + type(generator).__name__,
                  "config": generator.config, "rng_state": generator.rng.bit_generator.state,
                  "day_cache": getattr(generator, "_day_cache", {}),
                  "day_overrides": getattr(generator, "_day_overrides", {}),
                  "events": binding["events"]})


def _groups(bindings):
    groups = []
    for binding in bindings:
        matches = [group for group in groups if any(
            item["generator"] is binding["generator"]
            or (binding["weather"] is not None and item["weather"] is binding["weather"])
            for item in group)]
        combined = [binding]
        for group in matches:
            combined.extend(group)
            groups.remove(group)
        groups.append(combined)
    return sorted(groups, key=lambda group: min(item["farm"].name for item in group))


def _identity(scenario, scenario_id):
    return {"scenario_id": scenario_id or scenario.scenario_id,
            "start_timestamp": float(scenario.start_time),
            "duration_seconds": float(scenario.duration)}


def _source_files():
    root = Path(__file__).resolve().parents[1]
    return {path: hashlib.sha256((root/path).read_bytes()).hexdigest() for path in (
        "fairy/physics/weather_engine.py", "fairy/physics/profiles.py",
        "fairy/apps/farm_world/physics_orchestrator.py",
    )}


def freeze_weather_manifest(scenario, *, scenario_id=None):
    """Copy all station sources and freeze their complete daily input range."""
    from fairy.apps.farm_world.physics_orchestrator import _generate_weather_day

    groups = _groups(_bindings(scenario))
    identity = _identity(scenario, scenario_id)
    first = datetime.fromtimestamp(identity["start_timestamp"], timezone.utc).date()
    last = datetime.fromtimestamp(identity["start_timestamp"] + identity["duration_seconds"],
                                  timezone.utc).date() + timedelta(days=8)
    for group in groups:
        for binding in group:
            cache = getattr(binding["generator"], "_day_cache", {})
            if cache:
                first = min(first, min(cache))
    manifest = {"schema_version": 1, **identity, "date_start": first.isoformat(),
                "date_end": last.isoformat(),
                "generation_order": "ascending dates on a deepcopy; existing cache retained",
                "scope": "Common experiment forcing, not a replay of old query-order weather",
                "source_files": _source_files(),
                "bindings": {}, "forcings": {}}
    for index, group in enumerate(groups):
        signatures = {_signature(item) for item in group}
        if len(signatures) != 1:
            raise ValueError("Farms sharing weather have conflicting generator declarations")
        binding = group[0]
        generator = deepcopy(binding["generator"])
        forcing_id = f"forcing_{index:03d}"
        days = {}
        day = first
        while day <= last:
            days[day.isoformat()] = clean(_generate_weather_day(generator, day, binding["events"]))
            day += timedelta(days=1)
        manifest["forcings"][forcing_id] = {
            "input_signature": next(iter(signatures)),
            "generator_class": type(generator).__module__ + "." + type(generator).__name__,
            "generator_config": clean(generator.config),
            "events": clean(binding["events"]), "days": days,
        }
        for item in group:
            farm = item["farm"]
            manifest["bindings"][farm.name] = {
                "farm_id": farm.farm_id, "forcing_id": forcing_id,
                "weather_app_name": getattr(item["weather"], "name", None),
            }
    manifest["manifest_sha256"] = _hash(manifest)
    return manifest


def install_frozen_weather(scenario, manifest, *, scenario_id=None):
    """Install the same input into every actual and declared station generator."""
    payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if manifest.get("schema_version") != 1 or manifest.get("manifest_sha256") != _hash(payload):
        raise ValueError("Frozen weather manifest integrity mismatch")
    if any(manifest.get(key) != value for key, value in _identity(scenario, scenario_id).items()):
        raise ValueError("Frozen weather manifest belongs to a different scene or time range")
    if manifest.get("source_files") != _source_files():
        raise ValueError("Frozen weather source files changed")
    bindings = _bindings(scenario)
    if set(manifest["bindings"]) != {item["farm"].name for item in bindings}:
        raise ValueError("Frozen weather farm bindings do not match this scene")
    first, last = date.fromisoformat(manifest["date_start"]), date.fromisoformat(manifest["date_end"])
    identity = _identity(scenario, scenario_id)
    required_first = datetime.fromtimestamp(identity["start_timestamp"], timezone.utc).date()
    required_last = datetime.fromtimestamp(identity["start_timestamp"] + identity["duration_seconds"],
                                          timezone.utc).date() + timedelta(days=8)
    if first > required_first or last < required_last:
        raise ValueError("Frozen weather does not cover the scene and forecast horizon")
    expected_days = {(first + timedelta(days=i)).isoformat() for i in range((last-first).days+1)}
    plans = []
    for item in bindings:
        farm = item["farm"]
        binding = manifest["bindings"][farm.name]
        if binding["farm_id"] != farm.farm_id or binding["weather_app_name"] != getattr(item["weather"], "name", None):
            raise ValueError("Frozen weather target farm/station identity mismatch")
        forcing = manifest["forcings"][binding["forcing_id"]]
        if forcing["input_signature"] != _signature(item):
            raise ValueError("Frozen weather source configuration or initial cache changed")
        if set(forcing["days"]) != expected_days:
            raise ValueError("Frozen weather daily input coverage is incomplete")
        plans.append((item, forcing))
    # Validate every original source before pinning any shared generator.
    installed = set()
    for item, forcing in plans:
        for generator in (item["generator"], item["declaration"]):
            if generator is None or id(generator) in installed:
                continue
            for day, value in forcing["days"].items():
                if value["day"] != day:
                    raise ValueError("Frozen weather date does not match its daily value")
                generator.set_day_override(
                    date.fromisoformat(day), air_temp_mean_c=value["air_temp_mean_c"],
                    air_temp_min_c=value["air_temp_min_c"], air_temp_max_c=value["air_temp_max_c"],
                    rain_mm=value["rain_mm"], wind_ms=value["wind_ms"],
                    solar_rad_mj_m2=value["solar_rad_mj_m2"],
                    relative_humidity_pct=value.get("relative_humidity_pct"),
                    weather_tags=value.get("weather_tags", []),
                )
            installed.add(id(generator))


class FrozenWeatherCompiler(CalibrationCompiler):
    """CalibrationCompiler with one reusable, explicitly frozen weather input."""

    def __init__(self, sid, config, output, imports, review=None, forcing_manifest=None):
        self.forcing_manifest = deepcopy(forcing_manifest)
        super().__init__(sid, config, output, imports, review=review)

    def fresh(self):
        scenario, engine = super().fresh()
        if self.forcing_manifest is None:
            self.forcing_manifest = freeze_weather_manifest(scenario, scenario_id=self.sid)
        install_frozen_weather(scenario, self.forcing_manifest, scenario_id=self.sid)
        initialize = scenario.init_and_populate_apps

        def initialize_with_frozen_weather(*args, **kwargs):
            initialize(*args, **kwargs)
            install_frozen_weather(scenario, self.forcing_manifest, scenario_id=self.sid)

        scenario.init_and_populate_apps = initialize_with_frozen_weather
        save(self.output / "frozen_weather_manifest.json", self.forcing_manifest)
        if self._fresh_count == 1:
            save(self.output / "initial_snapshot.json", self.snapshot_unrecorded(scenario, engine))
        return scenario, engine
