"""Versioned, allowlisted JSON checkpoints for a complete FarmRuntime.

No pickle, eval, import-by-payload, or arbitrary object construction is used.
Only named domain dataclasses, engine field sets, explicit metadata containers
and the crop-domain snapshot codec below are restorable.
Checkpoints are taken between public tool operations and restore into a new
runtime, leaving any currently running world untouched on validation failure.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import fields, is_dataclass, MISSING
from datetime import date, datetime
from enum import Enum
import hashlib
import json
import math
import random
from types import SimpleNamespace
from typing import Any

import numpy as np

from fairy.apps.farm_world.assets import AssetSpec
from fairy.apps.farm_world import models, crop_profiles, farm_action_record, farm_physics_state
from fairy.physics import (soil_engine, phenology_engine, canopy_biomass_engine,
                           biotic_pressure_engine, management_effect_engine,
                           yield_recovery_engine, observation_model, weather_engine,
                           profiles)


_TYPE_NAMES = {
    models: "RidgeState InventoryState ManagementRegimeState PostHarvestMarketPreset WeatherState SeedType GrowthStage SeasonPhase",
    crop_profiles: "CropProfile",
    farm_action_record: "FarmActionRecord",
    farm_physics_state: "FarmPhysicsState",
    soil_engine: "SoilParameters SoilHydraulicModifier RidgeSoilState WeatherInput SoilDayResult",
    phenology_engine: "SoybeanStage SeedType SeedTypeParameters PhenologyParameters PhenologyWeatherInput PhenologySoilInput PlantingConfig PhenologyState PhenologyDayResult",
    canopy_biomass_engine: "GrowthStage SeedType SeedGrowthParameters CanopyBiomassParameters GrowthWeatherInput GrowthSoilInput PhenologyInput ManagementStressInput CanopyBiomassState CanopyBiomassDayResult",
    biotic_pressure_engine: "GrowthStage TreatmentType BioticPressureParameters SeedBioticResistanceParameters BioticWeatherInput BioticSoilInput BioticCropInput TreatmentApplication BioticPressureState BioticPressureDayResult",
    management_effect_engine: "ManagementActionType GrowthStage ManagementEffectParameters ManagementWeatherInput ManagementSoilInput ManagementCropInput ManagementAction ManagementEffectState ManagementEffectDayResult",
    yield_recovery_engine: "GrowthStage YieldRecoveryParameters YieldWeatherInput YieldPhenologyInput YieldGrowthInput YieldStressInput HarvestAction YieldRecoveryState YieldRecoveryDayResult",
    observation_model: "ObservationModality ObservationProductType ObservationModelParameters HiddenRidgeTruth SensorAsset ObservationProduct",
    weather_engine: "MonthlyClimate WeatherEvent WeatherDay WeatherGeneratorConfig",
    profiles: "BioticOutbreak PhysicsProfile",
}
_TYPES = {f"{module.__name__}.{name}": getattr(module, name)
          for module, names in _TYPE_NAMES.items() for name in names.split()}
_OBJECT_FIELDS = {
    soil_engine.SoilEngine: ({"params", "hydraulic_modifiers", "states"}, set()),
    phenology_engine.ThermalTimePhenologyEngine: ({"params", "seed_type_params", "states"}, set()),
    canopy_biomass_engine.CanopyBiomassGrowthEngine: ({"params", "seed_params", "states"}, set()),
    biotic_pressure_engine.BioticPressureEngine: ({"params", "seed_resistance_params", "states"}, set()),
    management_effect_engine.ManagementEffectEngine: ({"params", "states"}, set()),
    yield_recovery_engine.YieldRecoveryEngine: ({"params", "states"}, set()),
    observation_model.ObservationModel: ({"params", "assets", "rng", "_product_counter"}, set()),
    weather_engine.WeatherGenerator: ({"config", "rng", "_day_overrides"}, {"_day_cache"}),
}
_TYPES.update({f"{cls.__module__}.{cls.__name__}": cls for cls in _OBJECT_FIELDS})
_PHYSICS_EXTRA = {"crop_profile", "scenario_metadata", "profile"}
_FARM_FIELDS = {
    "_ridges", "_inventory", "_management_regime", "_postharvest_market",
    "_planting_windows", "_sim_date", "_season_phase", "_pending_irrigation",
    "_pending_bin_grain_ridge_ids", "_pending_bin_grain_moistures_pct",
    "_trailer_grain_ridge_ids", "_trailer_grain_moistures_pct",
    "_field_preparation_ops", "_physics", "crop_profile", "rng", "seed",
    "is_state_modified", "failure_probability", "tool_allowlist",
}
_SENSOR_FIELDS = {"_sensor_zones", "_soil_sensors", "_canopy_sensors", "rng", "seed", "is_state_modified"}
_FIELD_OPS_FIELDS = {"_irrigation_log", "_manual_spray_log", "rng", "seed", "is_state_modified"}
_STATION_FIELDS = {"_weather", "_avg_soil_vwc", "rng", "seed", "is_state_modified"}
_BIT_GENERATORS = {name: getattr(np.random, name) for name in ("PCG64", "MT19937", "Philox", "SFC64")}


def _key(cls: type) -> str:
    return f"{cls.__module__}.{cls.__name__}"


def encode_state(value: Any, *, _depth: int = 0) -> Any:
    if _depth > 150:
        raise ValueError("State nesting exceeds checkpoint limit")
    child = lambda item: encode_state(item, _depth=_depth + 1)
    if isinstance(value, Enum):
        name = _key(type(value))
        if name not in _TYPES:
            raise ValueError(f"Unregistered enum {name}")
        return {"$kind": "enum", "type": name, "value": child(value.value)}
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"$kind": "float", "value": repr(value)}
    if isinstance(value, np.generic):
        return child(value.item())
    if isinstance(value, datetime):
        return {"$kind": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"$kind": "date", "value": value.isoformat()}
    if isinstance(value, random.Random):
        return {"$kind": "random", "state": child(value.getstate())}
    if isinstance(value, np.random.Generator):
        name = type(value.bit_generator).__name__
        if name not in _BIT_GENERATORS:
            raise ValueError(f"Unsupported numpy bit generator {name}")
        return {"$kind": "numpy_random", "type": name, "state": child(value.bit_generator.state)}
    if isinstance(value, np.ndarray):
        if value.dtype.kind not in "biuf":
            raise ValueError("Checkpoint arrays must have numeric dtype")
        return {"$kind": "array", "dtype": value.dtype.str, "shape": list(value.shape), "values": child(value.tolist())}
    if type(value) is SimpleNamespace:
        return {"$kind": "namespace", "fields": {key: child(item) for key, item in vars(value).items()}}
    if isinstance(value, dict):
        items = [[child(key), child(item)] for key, item in value.items()]
        items.sort(key=lambda pair: json.dumps(pair[0], sort_keys=True, separators=(",", ":"), allow_nan=False))
        return {"$kind": "dict", "items": items}
    if isinstance(value, (list, tuple, set, frozenset)):
        kind = {list: "list", tuple: "tuple", set: "set", frozenset: "frozenset"}[type(value)]
        items = [child(item) for item in value]
        if isinstance(value, (set, frozenset)):
            items.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False))
        return {"$kind": kind, "items": items}
    from fairy.physics.wofost_backend import WofostBackend
    if isinstance(value, WofostBackend):
        return {"$kind": "wofost", "state": child(value.export_state())}
    if isinstance(value, farm_physics_state.FarmPhysicsState):
        allowed = {item.name for item in fields(value)} | _PHYSICS_EXTRA
        if set(vars(value)) - allowed:
            raise ValueError("Unregistered fields on farm physics state")
        # The crop codec owns runtime selection and engine aliases. Serializing
        # adapter plus engine fields independently would create two crop states
        # on restore, or require exposing implementation classes to the payload.
        from fairy.apps.farm_world.crop_snapshot import snapshot_physics
        return {"$kind": "farm_physics", "state": child(snapshot_physics(value))}
    cls, name = type(value), _key(type(value))
    if name not in _TYPES:
        raise ValueError(f"Unregistered checkpoint object {name}")
    attributes = vars(value)
    if is_dataclass(value):
        allowed = {item.name for item in fields(value)}
        if cls is farm_physics_state.FarmPhysicsState:
            allowed |= _PHYSICS_EXTRA
        if set(attributes) - allowed:
            raise ValueError(f"Unregistered fields on {name}: {sorted(set(attributes)-allowed)}")
    else:
        required, optional = _OBJECT_FIELDS[cls]
        if not required <= set(attributes) or set(attributes) - required - optional:
            raise ValueError(f"Unregistered or missing engine fields on {name}")
    return {"$kind": "object", "type": name, "fields": {key: child(item) for key, item in attributes.items()}}


def decode_state(value: Any, *, _depth: int = 0) -> Any:
    if _depth > 150:
        raise ValueError("State nesting exceeds checkpoint limit")
    child = lambda item: decode_state(item, _depth=_depth + 1)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Nonfinite checkpoint floats need an explicit typed representation")
        return value
    if not isinstance(value, dict) or not isinstance(value.get("$kind"), str):
        raise ValueError("Malformed typed checkpoint value")
    kind = value["$kind"]
    if kind in {"list", "tuple", "set", "frozenset"}:
        items = value.get("items")
        if not isinstance(items, list):
            raise ValueError("Checkpoint collection requires items")
        decoded = [child(item) for item in items]
        return {"list": list, "tuple": tuple, "set": set, "frozenset": frozenset}[kind](decoded)
    if kind == "dict":
        result = {}
        if not isinstance(value.get("items"), list):
            raise ValueError("Checkpoint mapping requires items")
        for pair in value["items"]:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("Malformed checkpoint mapping entry")
            key, item = child(pair[0]), child(pair[1])
            if key in result:
                raise ValueError("Duplicate checkpoint mapping key")
            result[key] = item
        return result
    if kind == "float":
        values = {"inf": math.inf, "-inf": -math.inf, "nan": math.nan}
        if value.get("value") not in values:
            raise ValueError("Unknown special float")
        return values[value["value"]]
    if kind in {"date", "datetime"}:
        return (date if kind == "date" else datetime).fromisoformat(value["value"])
    if kind == "random":
        rng = random.Random()
        rng.setstate(child(value["state"]))
        return rng
    if kind == "numpy_random":
        if value.get("type") not in _BIT_GENERATORS:
            raise ValueError("Unknown numpy bit generator")
        bit_generator = _BIT_GENERATORS[value["type"]]()
        bit_generator.state = child(value["state"])
        return np.random.Generator(bit_generator)
    if kind == "array":
        dtype = np.dtype(value["dtype"])
        if dtype.kind not in "biuf":
            raise ValueError("Checkpoint arrays must have numeric dtype")
        shape = value.get("shape")
        if (not isinstance(shape, list) or any(type(size) is not int or size < 0 for size in shape)
                or math.prod(shape) > 2_000_000):
            raise ValueError("Invalid checkpoint array shape")
        array = np.asarray(child(value["values"]), dtype=dtype)
        if list(array.shape) != shape:
            raise ValueError("Checkpoint array shape does not match its values")
        return array
    if kind == "namespace":
        attributes = value.get("fields")
        if not isinstance(attributes, dict) or any(not isinstance(key, str) for key in attributes):
            raise ValueError("Checkpoint metadata namespace requires named fields")
        return SimpleNamespace(**{key: child(item) for key, item in attributes.items()})
    if kind == "farm_physics":
        from fairy.apps.farm_world.crop_snapshot import restore_physics
        snapshot = child(value["state"])
        if not isinstance(snapshot, dict) or type(snapshot.get("num_ridges")) is not int:
            raise ValueError("Malformed farm physics checkpoint")
        return restore_physics(snapshot, snapshot["num_ridges"])
    if kind == "wofost":
        from fairy.physics.wofost_backend import WofostBackend
        return WofostBackend.from_state(child(value["state"]))
    if kind not in {"enum", "object"} or value.get("type") not in _TYPES:
        raise ValueError("Unknown checkpoint object type")
    cls = _TYPES[value["type"]]
    if kind == "enum":
        if not issubclass(cls, Enum):
            raise ValueError("Checkpoint type is not an enum")
        return cls(child(value["value"]))
    attributes = value.get("fields")
    if not isinstance(attributes, dict):
        raise ValueError("Checkpoint object requires fields")
    if is_dataclass(cls):
        definitions = fields(cls)
        allowed = {item.name for item in definitions}
        if cls is farm_physics_state.FarmPhysicsState:
            allowed |= _PHYSICS_EXTRA
        required = {item.name for item in definitions if item.init and item.default is MISSING and item.default_factory is MISSING}
        if set(attributes) - allowed or required - set(attributes):
            raise ValueError("Unregistered or missing dataclass fields")
        decoded = {key: child(item) for key, item in attributes.items()}
        result = cls(**{item.name: decoded[item.name] for item in definitions if item.init and item.name in decoded})
        for key, item in decoded.items():
            object.__setattr__(result, key, item)
        if cls is farm_physics_state.FarmPhysicsState:
            # Historical object checkpoints predate CropDynamics. Retain their
            # decoded engines as the sole state behind the newly built facade.
            for name in ("phenology", "canopy", "yield_recovery"):
                engine = getattr(result, name)
                setattr(result.crop, name, engine)
                setattr(result.crop.model, name, engine)
            if result.crop_backend is not None:
                saved_yield_params = result.yield_recovery.params
                result.crop_backend.bind_physics(result)
                result.yield_recovery.params = saved_yield_params
        return result
    if cls not in _OBJECT_FIELDS:
        raise ValueError("Type is not a restorable engine")
    required, optional = _OBJECT_FIELDS[cls]
    if not required <= set(attributes) or set(attributes) - required - optional:
        raise ValueError("Unregistered or missing engine fields")
    result = object.__new__(cls)
    for key, item in attributes.items():
        object.__setattr__(result, key, child(item))
    return result


def _read_fields(obj, names):
    return encode_state({name: getattr(obj, name) for name in names})


def _write_fields(obj, payload, names):
    values = decode_state(payload)
    if not isinstance(values, dict) or set(values) != names:
        raise ValueError("Checkpoint entity fields do not match this schema")
    for key, value in values.items():
        setattr(obj, key, value)


def snapshot_runtime(runtime) -> dict[str, Any]:
    """Return a JSON-safe complete world checkpoint at an operation boundary."""
    if getattr(runtime, "_active", False):
        raise ValueError("Take a runtime checkpoint between tool operations")
    runtime.freeze()
    captured = float(runtime.clock.time())
    if not math.isfinite(captured):
        raise ValueError("Cannot snapshot an invalid simulation clock")
    return {
        "format": "fairy-farm-runtime", "version": 1,
        "clock": {"start_time": float(runtime.clock.start_time), "captured_time": captured},
        "seed": runtime.seed, "bindings": deepcopy(runtime.bindings),
        "tool_allowlists": {key: sorted(value) for key, value in runtime.tool_allowlists.items()},
        "manifest": deepcopy(runtime.registry.manifest),
        "initial_definition": encode_state(runtime._initial_definition),
        "definition_metadata": encode_state(runtime.definition_metadata),
        "last_advance": runtime._last_advance,
        "farms": [{"spec": {"farm_id": site.spec.farm_id, "name": site.spec.name,
                               "crop_type": site.spec.crop_type, "num_ridges": site.spec.num_ridges,
                               "field_length_m": site.spec.field_length_m, "ridge_width_m": site.spec.ridge_width_m},
                   "station_id": site.station_id,
                   "farm": _read_fields(site.farm, _FARM_FIELDS),
                   "sensor": _read_fields(site.sensor, _SENSOR_FIELDS),
                   "field_ops": _read_fields(site.field_ops, _FIELD_OPS_FIELDS)}
                  for site in runtime.fleet.sites],
        "stations": {sid: {"name": station.name, "state": _read_fields(station, _STATION_FIELDS)}
                     for sid, station in runtime.stations.items()},
        "station_forcing": encode_state(runtime._station_forcing),
        "station_daily_inputs": encode_state(runtime._station_daily_inputs),
        "assets": [asset.snapshot() for asset in runtime.assets.values()],
        "tool_history": encode_state(runtime.executor.history),
    }


def _validate_farm(site, captured):
    farm, expected = site.farm, set(range(site.spec.num_ridges))
    if len(farm._ridges) != site.spec.num_ridges or {ridge.ridge_id for ridge in farm._ridges} != expected:
        raise ValueError("Checkpoint ridge identity does not match its farm")
    physics = farm._physics
    if physics is not None:
        if (not isinstance(physics, farm_physics_state.FarmPhysicsState)
                or physics.num_ridges != site.spec.num_ridges or physics.crop_type != site.spec.crop_type
                or physics.field_length_m != site.spec.field_length_m or physics.ridge_width_m != site.spec.ridge_width_m):
            raise ValueError("Checkpoint physics identity does not match its farm")
        if physics.last_physics_sim_time is not None and physics.last_physics_sim_time > captured + 0.01:
            raise ValueError("Checkpoint physics is ahead of the captured clock")
        for engine in (physics.soil, physics.phenology, physics.canopy, physics.biotic,
                       physics.management, physics.yield_recovery):
            if set(engine.states) != expected:
                raise ValueError("Checkpoint physical engine has the wrong ridge domain")
        for queue in (physics.pending_management_actions_by_ridge, physics.pending_treatments_by_ridge,
                      physics.pending_harvest_actions_by_ridge):
            if set(queue) - expected:
                raise ValueError("Checkpoint action queue targets unknown ridges")
        if any(set(action.ridge_ids) - expected for action in physics.action_log):
            raise ValueError("Checkpoint action history targets unknown ridges")
    zones = site.sensor._sensor_zones
    if zones != site.sensor._zones_for_ridges(farm.num_ridges):
        raise ValueError("Checkpoint sensor coverage does not match its farm")


def restore_runtime(snapshot: dict[str, Any]):
    """Validate and restore into a separate runtime; never mutate a live world."""
    from fairy.apps.farm_world.multi_farm import FarmSite, FarmFleet
    from fairy.apps.farm_world.weather_app import WeatherApp
    from fairy.time_manager import TimeManager

    if not isinstance(snapshot, dict) or snapshot.get("format") != "fairy-farm-runtime" or type(snapshot.get("version")) is not int or snapshot["version"] != 1:
        raise ValueError("Unsupported farm runtime checkpoint")
    if not isinstance(snapshot.get("farms"), list) or not snapshot["farms"]:
        raise ValueError("A runtime checkpoint must contain farms")
    clock_state = snapshot["clock"]
    start, captured = clock_state["start_time"], clock_state["captured_time"]
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in (start, captured)):
        raise ValueError("Invalid runtime checkpoint clock")
    if captured < start:
        raise ValueError("Checkpoint clock precedes the season start")
    stations = {}
    for sid, saved in snapshot["stations"].items():
        if not isinstance(sid, str) or not sid:
            raise ValueError("Invalid weather station ID")
        station = WeatherApp()
        station.name = saved["name"]
        _write_fields(station, saved["state"], _STATION_FIELDS)
        stations[sid] = station
    sites = []
    for saved in snapshot["farms"]:
        spec, sid = saved["spec"], saved["station_id"]
        if sid not in stations:
            raise ValueError("Checkpoint farm references an unknown station")
        site = FarmSite.create(**spec, create_devices=False, station_id=sid, weather_app=stations[sid])
        _write_fields(site.farm, saved["farm"], _FARM_FIELDS)
        _write_fields(site.sensor, saved["sensor"], _SENSOR_FIELDS)
        _write_fields(site.field_ops, saved["field_ops"], _FIELD_OPS_FIELDS)
        _validate_farm(site, captured)
        sites.append(site)
    specs = [AssetSpec(**saved["spec"]) for saved in snapshot["assets"]]
    fleet = FarmFleet(sites, shared_tools=True, assets=specs, seed=snapshot["seed"], bindings=snapshot["bindings"])
    runtime = fleet.runtime
    runtime.configure_tools({key: set(value) for key, value in snapshot["tool_allowlists"].items()})
    for saved in snapshot["assets"]:
        asset = runtime.assets[saved["spec"]["asset_id"]]
        asset.load_snapshot(saved)
        for lot in asset.grain_lots:
            site = runtime.farms[lot["farm_id"]]
            if lot["crop_type"] != site.farm.crop_type or set(lot["ridge_ids"]) - set(range(site.farm.num_ridges)):
                raise ValueError("Checkpoint grain batch does not match its origin farm")
    # FarmSite construction seeds shared stations; apply the saved stream once,
    # after all sites have been linked to their unique station object.
    for sid, saved in snapshot["stations"].items():
        _write_fields(runtime.stations[sid], saved["state"], _STATION_FIELDS)
    clock = TimeManager()
    clock.reset(float(start))
    clock.set_offset(float(captured) - float(start))
    runtime.bind_clock(clock)
    runtime._last_advance = snapshot.get("last_advance")
    runtime._initial_definition = decode_state(snapshot["initial_definition"])
    runtime.definition_metadata = decode_state(snapshot["definition_metadata"])
    runtime._station_forcing = decode_state(snapshot["station_forcing"])
    runtime._station_daily_inputs = decode_state(snapshot["station_daily_inputs"])
    if (not isinstance(runtime._station_forcing, dict) or not isinstance(runtime._station_daily_inputs, dict)
            or set(runtime._station_forcing) != set(runtime.stations)
            or set(runtime._station_daily_inputs) != set(runtime.stations)):
        raise ValueError("Checkpoint weather forcing does not match its stations")
    expected_manifest = snapshot["manifest"]
    initial_fingerprint = hashlib.sha256(json.dumps(runtime._initial_definition, sort_keys=True,
                                                   allow_nan=False).encode()).hexdigest()
    if initial_fingerprint != expected_manifest["scenario_config_fingerprint"]:
        raise ValueError("Checkpoint initial definition does not match its configuration fingerprint")
    runtime.registry.freeze(runtime._environment_structure(),
                            scenario_config_fingerprint=expected_manifest["scenario_config_fingerprint"])
    if runtime.registry.manifest != expected_manifest:
        raise ValueError("Checkpoint tool catalog no longer matches the current contracts")
    runtime._frozen = True
    runtime.restored_from_snapshot = True
    history = decode_state(snapshot["tool_history"])
    if not isinstance(history, list) or any(not isinstance(item, dict) for item in history):
        raise ValueError("Malformed checkpoint tool history")
    runtime.executor.history = history
    clock.register_offset_observer("runtime:0", runtime.before_advance, runtime.advance_to)
    return runtime
