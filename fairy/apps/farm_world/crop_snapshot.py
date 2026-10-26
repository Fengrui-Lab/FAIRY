"""Versioned, JSON-native snapshots for a complete crop/environment bundle.

Crop state, environmental engines, pending queues and random streams are saved
together. Public ridge shadows alone cannot restore a growing crop. Legacy
lightweight world snapshots are handled explicitly by FarmWorldApp.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import date
from enum import Enum
from types import SimpleNamespace
from typing import Any


_UNSPECIFIED_CROP_ID = object()


def _encode(value: Any) -> Any:
    if type(value) is SimpleNamespace:
        from fairy.apps.farm_world.runtime_state import encode_state
        return {"$kind": "profile_metadata", "state": encode_state(vars(value))}
    if is_dataclass(value):
        return _encode(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(_encode(key)): _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    return value


def snapshot_physics(physics) -> dict | None:
    if physics is None:
        return None
    from fairy.apps.farm_world.runtime_state import encode_state
    generator = physics.weather_generator
    return _encode({
        "version": 1, "crop_id": physics.crop_id, "num_ridges": len(physics.soil.states),
        "crop_type": physics.crop_type,
        "crop_profile": encode_state(physics.crop_profile),
        "geometry": {"field_length_m": physics.field_length_m,
                     "ridge_width_m": physics.ridge_width_m},
        "crop_backend_name": physics.crop_backend_name,
        "crop_backend_state": (physics.crop_backend.export_state()
                               if physics.crop_backend is not None else None),
        "crop": physics.crop.get_state(),
        "metadata": {name: getattr(physics, name) for name in (
            "profile_name", "location", "scenario_type", "latitude_deg", "random_seed",
            "last_physics_sim_time", "engines_active")},
        "scenario_metadata": getattr(physics, "scenario_metadata", {}),
        "soil": {"parameters": physics.soil.params,
                 "modifiers": physics.soil.hydraulic_modifiers, "states": physics.soil.states},
        "management": {"parameters": physics.management.params, "states": physics.management.states},
        "biotic": {"parameters": physics.biotic.params, "states": physics.biotic.states,
                   "seed_resistance": physics.biotic.seed_resistance_params},
        "observation": {"parameters": physics.observation_model.params,
                        "assets": physics.observation_model.assets,
                        "random_state": physics.observation_model.rng.getstate(),
                        "product_counter": physics.observation_model._product_counter},
        "weather_generator": None if generator is None else {
            "configuration": generator.config, "random_state": generator.rng.bit_generator.state,
            "day_cache": getattr(generator, "_day_cache", {}),
            "day_overrides": getattr(generator, "_day_overrides", {}),
        },
        "profile": getattr(physics, "profile", None),
        "action_log": physics.action_log,
        "pending_management": physics.pending_management_actions_by_ridge,
        "pending_treatments": physics.pending_treatments_by_ridge,
        "pending_harvest": physics.pending_harvest_actions_by_ridge,
    })


def _restore_states(raw: dict, state_type, num_ridges: int, date_fields=()) -> dict:
    result = {}
    for key, row in raw.items():
        values = deepcopy(row)
        for name in date_fields:
            if values.get(name) is not None:
                values[name] = date.fromisoformat(values[name])
        rid = int(key)
        if values["ridge_id"] != rid:
            raise ValueError("Crop snapshot has inconsistent ridge identities")
        result[rid] = state_type(**values)
    if set(result) != set(range(num_ridges)):
        raise ValueError("Crop snapshot does not cover the complete field")
    return result


def _tuple_tree(value):
    return tuple(_tuple_tree(item) for item in value) if isinstance(value, list) else value


def _metadata(value):
    if isinstance(value, dict):
        if value.get("$kind") == "profile_metadata":
            from fairy.apps.farm_world.runtime_state import decode_state
            attributes = decode_state(value["state"])
            if not isinstance(attributes, dict) or any(not isinstance(key, str) for key in attributes):
                raise ValueError("Profile metadata requires named fields")
            return SimpleNamespace(**attributes)
        return {key: _metadata(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_metadata(item) for item in value]
    return value


def restore_physics(snapshot: dict | None, num_ridges: int,
                    crop_id: str | None = _UNSPECIFIED_CROP_ID, *,
                    crop_type: str | None = None, field_length_m: float | None = None,
                    ridge_width_m: float | None = None):
    """Build a detached bundle; reject incompatible data before installing it."""
    if snapshot is None:
        return None
    if (snapshot.get("version") != 1
            or (crop_id is not _UNSPECIFIED_CROP_ID and snapshot.get("crop_id") != crop_id)
            or snapshot.get("num_ridges") != num_ridges):
        raise ValueError("Unsupported crop physics snapshot")
    saved_crop_type = snapshot.get("crop_type", snapshot.get("crop_id") or "soybean")
    if crop_type is not None and saved_crop_type != crop_type:
        raise ValueError("Crop snapshot species does not match the field")
    geometry = snapshot.get("geometry", {})
    for name, expected in (("field_length_m", field_length_m), ("ridge_width_m", ridge_width_m)):
        if expected is not None and name in geometry and geometry[name] != expected:
            raise ValueError("Crop snapshot geometry does not match the field")
    from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
    from fairy.apps.farm_world.farm_action_record import FarmActionRecord
    from fairy.physics.soil_engine import SoilParameters, SoilHydraulicModifier, RidgeSoilState
    from fairy.physics.management_effect_engine import (
        ManagementEffectParameters, ManagementEffectState, ManagementAction, ManagementActionType,
    )
    from fairy.physics.biotic_pressure_engine import (
        BioticPressureParameters, BioticPressureState, SeedBioticResistanceParameters,
        TreatmentApplication, TreatmentType,
    )
    from fairy.physics.observation_model import (
        ObservationModelParameters, SensorAsset, ObservationModality,
    )
    from fairy.physics.weather_engine import (
        WeatherGenerator, WeatherGeneratorConfig, MonthlyClimate, WeatherDay, WeatherEvent,
    )
    from fairy.physics.profiles import PhysicsProfile, BioticOutbreak
    from fairy.physics import HarvestAction

    physics = FarmPhysicsState(num_ridges=num_ridges, crop_id=snapshot["crop_id"],
                              crop_type=saved_crop_type,
                              field_length_m=geometry.get("field_length_m", field_length_m or 268.0),
                              ridge_width_m=geometry.get("ridge_width_m", ridge_width_m or 1.1))
    if "crop_profile" in snapshot:
        from fairy.apps.farm_world.runtime_state import decode_state
        from fairy.apps.farm_world.crop_profiles import CropProfile
        profile = decode_state(snapshot["crop_profile"])
        if not isinstance(profile, CropProfile) or profile.crop_type != saved_crop_type:
            raise ValueError("Crop snapshot profile does not match its species")
        physics.crop_profile = profile
    physics.crop.load_state(snapshot["crop"])
    for name, value in snapshot["metadata"].items():
        if name not in {"profile_name", "location", "scenario_type", "latitude_deg",
                         "random_seed", "last_physics_sim_time", "engines_active"}:
            raise ValueError(f"Unknown crop snapshot metadata {name!r}")
        setattr(physics, name, value)
    physics.scenario_metadata = _metadata(deepcopy(snapshot["scenario_metadata"]))
    physics.soil.params = SoilParameters(**snapshot["soil"]["parameters"])
    physics.soil.hydraulic_modifiers = {
        int(rid): SoilHydraulicModifier(**row) for rid, row in snapshot["soil"]["modifiers"].items()
    }
    physics.soil.states = _restore_states(snapshot["soil"]["states"], RidgeSoilState, num_ridges)
    physics.management.params = ManagementEffectParameters(**snapshot["management"]["parameters"])
    physics.management.states = _restore_states(
        snapshot["management"]["states"], ManagementEffectState, num_ridges,
        ("planting_date", "last_nutrient_decay_day", "last_growth_uptake_day"),
    )
    physics.biotic.params = BioticPressureParameters(**snapshot["biotic"]["parameters"])
    physics.biotic.states = _restore_states(
        snapshot["biotic"]["states"], BioticPressureState, num_ridges, ("last_daily_update_day",),
    )
    physics.biotic.seed_resistance_params = {
        key: SeedBioticResistanceParameters(**row)
        for key, row in snapshot["biotic"]["seed_resistance"].items()
    }
    observation = snapshot["observation"]
    physics.observation_model.params = ObservationModelParameters(**observation["parameters"])
    physics.observation_model.assets = {
        key: SensorAsset(**{**row, "modality": ObservationModality(row["modality"])})
        for key, row in observation["assets"].items()
    }
    physics.observation_model.rng.setstate(_tuple_tree(observation["random_state"]))
    physics.observation_model._product_counter = observation["product_counter"]
    raw_generator = snapshot["weather_generator"]
    if raw_generator is not None:
        configuration = deepcopy(raw_generator["configuration"])
        configuration["monthly"] = {int(key): MonthlyClimate(**row)
                                    for key, row in configuration["monthly"].items()}
        generator = WeatherGenerator(WeatherGeneratorConfig(**configuration))
        generator.rng.bit_generator.state = deepcopy(raw_generator["random_state"])
        generator._day_cache = {date.fromisoformat(key): WeatherDay(
            **{**row, "day": date.fromisoformat(row["day"])})
            for key, row in raw_generator["day_cache"].items()}
        generator._day_overrides = {date.fromisoformat(key): WeatherDay(
            **{**row, "day": date.fromisoformat(row["day"])})
            for key, row in raw_generator.get("day_overrides", {}).items()}
        physics.weather_generator = generator
    raw_profile = snapshot["profile"]
    if isinstance(raw_profile, dict) and raw_profile.get("$kind") == "profile_metadata":
        physics.profile = _metadata(raw_profile)
    elif raw_profile is not None:
        profile = deepcopy(raw_profile)
        profile["start_date"] = date.fromisoformat(profile["start_date"])
        profile["monthly_climate"] = {int(key): MonthlyClimate(**row)
                                      for key, row in profile["monthly_climate"].items()}
        profile["weather_events"] = [WeatherEvent(**{**row, "start_date": date.fromisoformat(row["start_date"])})
                                     for row in profile["weather_events"]]
        profile["biotic_outbreaks"] = [BioticOutbreak(**{**row, "pressure_type": TreatmentType(row["pressure_type"])})
                                      for row in profile["biotic_outbreaks"]]
        physics.profile = PhysicsProfile(**profile)
    physics.action_log = [FarmActionRecord(**row) for row in snapshot["action_log"]]
    physics.pending_management_actions_by_ridge = {
        int(key): [ManagementAction(**{**row, "action_type": ManagementActionType(row["action_type"])})
                   for row in rows] for key, rows in snapshot["pending_management"].items()
    }
    physics.pending_treatments_by_ridge = {
        int(key): [TreatmentApplication(**{**row, "treatment_type": TreatmentType(row["treatment_type"])})
                   for row in rows] for key, rows in snapshot["pending_treatments"].items()
    }
    physics.pending_harvest_actions_by_ridge = {
        int(key): HarvestAction(**row) for key, row in snapshot["pending_harvest"].items()
    }
    backend_name = snapshot.get("crop_backend_name", "legacy")
    backend_state = snapshot.get("crop_backend_state")
    if backend_name == "wofost":
        if not backend_state:
            raise ValueError("WOFOST crop snapshot is missing native model history")
        if physics.crop_id == "maize":
            raise ValueError("WOFOST cannot restore into the independent reduced maize runtime")
        from fairy.physics.wofost_backend import WofostBackend
        physics.crop_backend = WofostBackend.from_state(backend_state)
        physics.crop_backend_name = "wofost"
        saved_yield_params = physics.yield_recovery.params
        physics.crop_backend.bind_physics(physics)
        # Binding installs maize defaults for new worlds. A complete snapshot
        # already owns its downstream moisture/loss parameters and overrides.
        physics.yield_recovery.params = saved_yield_params
    elif backend_name != "legacy" or backend_state is not None:
        raise ValueError("Invalid crop snapshot backend configuration")
    return physics
