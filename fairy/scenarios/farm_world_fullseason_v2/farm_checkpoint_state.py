"""Checkpoint export/restore helpers for standalone FARM L2/L1 splits.

The trace CSVs are good human evidence, but they are not enough to resume a
small L2 world: weather RNG/cache, engine state, hidden profile modifiers, and
postharvest buffers can all affect what happens after the checkpoint.  These
helpers keep that state together in a JSON-safe payload.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date
from enum import Enum
from typing import Any, Mapping

from fairy.apps.farm_world.farm_action_record import FarmActionRecord
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.physics.biotic_pressure_engine import (
    BioticPressureState, TreatmentApplication, TreatmentType,
)
from fairy.physics.management_effect_engine import ManagementAction, ManagementActionType
from fairy.physics.canopy_biomass_engine import (
    CanopyBiomassState,
    SeedType as CanopySeedType,
)
from fairy.physics.management_effect_engine import ManagementEffectState
from fairy.physics.phenology_engine import (
    PhenologyState,
    SeedType as PhenologySeedType,
    SoybeanStage,
)
from fairy.physics.soil_engine import RidgeSoilState, SoilHydraulicModifier, SoilParameters
from fairy.physics.weather_engine import WeatherDay
from fairy.physics.yield_recovery_engine import HarvestAction, YieldRecoveryState


def export_farm_checkpoint_state(
    *,
    farm_world: FarmWorldApp,
    weather_app: WeatherApp | None,
    scenario_id: str,
    checkpoint_label: str,
) -> dict[str, Any]:
    """Return a JSON-safe checkpoint for a physics-backed FarmWorldApp."""

    physics = getattr(farm_world, "_physics", None)
    current_time = float(farm_world.time_manager.time())
    payload: dict[str, Any] = {
        "schema_version": 1,
        "scenario_id": scenario_id,
        "checkpoint_label": checkpoint_label,
        "sim_time": current_time,
        "farm_world_state": _to_jsonable(farm_world.get_state()),
        "weather_app_state": _to_jsonable(weather_app.get_state())
        if weather_app is not None
        else None,
        "physics_state": None,
    }
    if ("crop_configuration" in payload["farm_world_state"]
            and "physics_state" in payload["farm_world_state"]):
        # The World format is authoritative for every crop. Do not export a
        # second soybean-specific copy of the native models alongside it.
        payload["schema_version"] = 2
        payload.pop("physics_state")
        return payload
    if physics is None:
        return payload

    weather_generator = getattr(physics, "weather_generator", None)
    payload["physics_state"] = {
        "profile_name": physics.profile_name,
        "location": physics.location,
        "scenario_type": physics.scenario_type,
        "latitude_deg": physics.latitude_deg,
        "random_seed": physics.random_seed,
        "engines_active": physics.engines_active,
        "last_physics_sim_time": physics.last_physics_sim_time,
        "crop_backend_name": physics.crop_backend_name,
        "crop_backend_state": (
            physics.crop_backend.export_state()
            if physics.crop_backend is not None else None
        ),
        "scenario_metadata": _to_jsonable(getattr(physics, "scenario_metadata", {})),
        "soil_parameters": _to_jsonable(physics.soil.params),
        "soil_states": _to_jsonable(physics.soil.get_state()),
        "soil_hydraulic_modifiers": _to_jsonable(
            getattr(physics.soil, "hydraulic_modifiers", {})
        ),
        "phenology_states": _to_jsonable(physics.phenology.get_state()),
        "canopy_states": _to_jsonable(physics.canopy.get_state()),
        "biotic_states": _to_jsonable(physics.biotic.get_state()),
        "management_states": _to_jsonable(physics.management.get_state()),
        "yield_recovery_states": _to_jsonable(physics.yield_recovery.get_state()),
        "action_log": _to_jsonable(physics.action_log),
        "pending_management_actions_by_ridge": _to_jsonable(
            physics.pending_management_actions_by_ridge
        ),
        "pending_treatments_by_ridge": _to_jsonable(physics.pending_treatments_by_ridge),
        "pending_harvest_actions_by_ridge": _to_jsonable(physics.pending_harvest_actions_by_ridge),
        "weather_generator": _export_weather_generator(weather_generator),
    }
    if getattr(farm_world, "crop_name", "soybean") == "maize":
        # Maize scenes use local, versioned synthetic weather profiles rather
        # than global soybean profile names. Preserve future forcing as well
        # as the already-generated day cache when resuming a checkpoint.
        payload["physics_state"]["physics_profile"] = _to_jsonable(
            getattr(physics, "profile", None)
        )
        if weather_generator is not None:
            payload["physics_state"]["weather_generator"].update({
                "config": _to_jsonable(weather_generator.config),
                "day_overrides": {
                    day.isoformat(): _to_jsonable(value)
                    for day, value in weather_generator._day_overrides.items()
                },
            })
    return payload


def restore_farm_checkpoint_state(
    *,
    farm_world: FarmWorldApp,
    weather_app: WeatherApp | None,
    checkpoint_state: Mapping[str, Any],
    target_sim_time: float | None = None,
) -> dict[str, Any]:
    """Restore a checkpoint into a FarmWorldApp/WeatherApp pair."""

    world_state = dict(checkpoint_state["farm_world_state"])
    physics_state = checkpoint_state.get("physics_state") or {}
    embedded = world_state.get("physics_state") or {}
    native_view = (world_state.get("crop_backend") or {}).get("backend") == "wofost"
    if native_view or physics_state.get("crop_backend_name") == "wofost":
        native_history = embedded.get("crop_backend_state") or physics_state.get("crop_backend_state")
        if not native_history:
            raise ValueError("WOFOST checkpoint is missing native model history")
        if (embedded.get("crop_backend_state") is not None
                and physics_state.get("crop_backend_state") is not None
                and embedded["crop_backend_state"] != physics_state["crop_backend_state"]):
            raise ValueError("WOFOST checkpoint contains conflicting native model histories")

    # Modern World snapshots already contain native crop/environment state,
    # including the scenario's own profile, coefficients and weather stream.
    # Reconfiguring that profile from the registry would replace saved local
    # weather overrides and restart its generator before continuation.
    if "crop_configuration" in world_state and isinstance(world_state.get("physics_state"), Mapping):
        previous_weather = farm_world._weather_app
        restored_weather = weather_app if weather_app is not None else previous_weather
        weather_state = world_state.get("weather_state") or checkpoint_state.get("weather_app_state")
        if restored_weather is None and weather_state is not None:
            # The old full-checkpoint API permits weather_app=None. Preserve
            # an embedded station as detached domain data instead of dropping
            # its forecast or requiring the caller to construct another App.
            restored_weather = WeatherApp()
            restored_weather.load_state(dict(weather_state))
            restored_weather.name = weather_state.get("app_name", restored_weather.name)
            restored_weather.register_time_manager(farm_world.time_manager)
        if restored_weather is not None:
            farm_world.attach_weather_app(restored_weather)
        try:
            farm_world.load_state(world_state)
        except Exception:
            # Validate a detached snapshot before making the new station part
            # of this world. A rejected restore must retain the old binding.
            farm_world._weather_app = previous_weather
            raise
        if (restored_weather is not None and world_state.get("weather_state") is None
                and checkpoint_state.get("weather_app_state")):
            restored_weather.load_state(dict(checkpoint_state["weather_app_state"]))
        if restored_weather is not None:
            restored_weather.simulation_timezone = farm_world.simulation_timezone
        physics = farm_world._physics
        if physics is not None and target_sim_time is not None:
            physics.last_physics_sim_time = float(target_sim_time)
        return _checkpoint_restore_result(farm_world, checkpoint_state)

    # Historical checkpoints kept ridge shadows and engine state separately.
    # Loading the shadows deliberately clears old engines. Create the profile
    # only afterwards, so its generator exists when RNG/cache are restored.
    field_state = dict(checkpoint_state["farm_world_state"])
    if ((native_view or physics_state.get("crop_backend_name") == "wofost")
            and (physics_state.get("crop_backend_name") != "wofost"
                 or not physics_state.get("crop_backend_state"))):
        raise ValueError("WOFOST checkpoint is missing native model history")
    profile_name = physics_state.get("profile_name")
    if profile_name:
        farm_world.configure_physics_profile(
            profile_name=str(profile_name),
            location=physics_state.get("location"),
            scenario_type=physics_state.get("scenario_type"),
            latitude_deg=physics_state.get("latitude_deg"),
            random_seed=physics_state.get("random_seed"),
            **dict(physics_state.get("scenario_metadata") or {}),
        )
    if physics_state:
        # This codec also restores the complete engines, queues and native
        # history below. Ordinary flat-view loads cannot make that guarantee.
        farm_world._load_field_state(field_state)
    else:
        farm_world.load_state(field_state)
    if weather_app is not None and checkpoint_state.get("weather_app_state"):
        weather_app.load_state(dict(checkpoint_state["weather_app_state"]))

    physics = farm_world.physics
    if physics_state:
        physics.profile_name = physics_state.get("profile_name")
        physics.location = physics_state.get("location")
        physics.scenario_type = physics_state.get("scenario_type")
        physics.latitude_deg = float(physics_state.get("latitude_deg", 45.7))
        physics.random_seed = int(physics_state.get("random_seed", 0))
        physics.engines_active = bool(physics_state.get("engines_active", True))
        if physics_state.get("scenario_metadata"):
            physics.scenario_metadata = dict(physics_state["scenario_metadata"])  # type: ignore[attr-defined]

        if isinstance(physics_state.get("soil_parameters"), Mapping):
            physics.soil.params = SoilParameters(**_dataclass_init_data(
                SoilParameters, dict(physics_state["soil_parameters"])
            ))
        physics.soil.set_state(
            _state_map(physics_state.get("soil_states", {}), RidgeSoilState)
        )
        physics.soil.hydraulic_modifiers = _state_map(
            physics_state.get("soil_hydraulic_modifiers", {}),
            SoilHydraulicModifier,
        )
        physics.phenology.states = _state_map(
            physics_state.get("phenology_states", {}),
            PhenologyState,
            date_fields=("planting_date", "emergence_date", "maturity_date"),
            enum_fields={"seed_type": PhenologySeedType, "stage": SoybeanStage},
        )
        physics.canopy.states = _state_map(
            physics_state.get("canopy_states", {}),
            CanopyBiomassState,
            enum_fields={"seed_type": CanopySeedType},
        )
        physics.biotic.states = _state_map(
            physics_state.get("biotic_states", {}),
            BioticPressureState,
            date_fields=("last_daily_update_day",),
        )
        physics.management.states = _state_map(
            physics_state.get("management_states", {}),
            ManagementEffectState,
            date_fields=("planting_date", "last_nutrient_decay_day", "last_growth_uptake_day"),
        )
        physics.yield_recovery.states = _state_map(
            physics_state.get("yield_recovery_states", {}),
            YieldRecoveryState,
            date_fields=("maturity_date", "harvest_date", "last_daily_update_day"),
        )
        physics.action_log = [
            FarmActionRecord(**dict(record))
            for record in physics_state.get("action_log", [])
        ]
        physics.pending_management_actions_by_ridge = {
            int(rid): [ManagementAction(**{
                **action, "action_type": ManagementActionType(action["action_type"])
            }) for action in actions]
            for rid, actions in physics_state.get("pending_management_actions_by_ridge", {}).items()
        }
        physics.pending_treatments_by_ridge = {
            int(rid): [TreatmentApplication(**{
                **treatment, "treatment_type": TreatmentType(treatment["treatment_type"])
            }) for treatment in treatments]
            for rid, treatments in physics_state.get("pending_treatments_by_ridge", {}).items()
        }
        physics.pending_harvest_actions_by_ridge = {
            int(rid): HarvestAction(**action)
            for rid, action in physics_state.get("pending_harvest_actions_by_ridge", {}).items()
        }
        backend_name = physics_state.get("crop_backend_name", "legacy")
        if backend_name == "wofost":
            from fairy.physics.wofost_backend import WofostBackend

            backend_state = physics_state.get("crop_backend_state")
            if not backend_state:
                raise ValueError("WOFOST checkpoint is missing native model history")
            physics.crop_backend = WofostBackend.from_state(backend_state)
            physics.crop_backend_name = "wofost"
            if physics.crop_backend.config.crop_name == "maize":
                # Restore crop-specific downstream accounting as well as the
                # native model. Old checkpoints retain soybean defaults.
                physics.crop_backend.bind_physics(physics)
        elif backend_name == "legacy":
            physics.crop_backend = None
            physics.crop_backend_name = "legacy"
        else:
            raise ValueError(f"Unsupported checkpoint crop backend: {backend_name!r}")
        physics.yield_recovery.params.biological_yield_is_dry_matter = backend_name == "wofost"
        _restore_embedded_weather(physics, physics_state)
        _restore_weather_generator(
            getattr(physics, "weather_generator", None),
            physics_state.get("weather_generator") or {},
        )
        physics.last_physics_sim_time = (
            float(target_sim_time)
            if target_sim_time is not None
            else _float_or_none(physics_state.get("last_physics_sim_time"))
        )

    return _finish_checkpoint_restore(farm_world, weather_app, checkpoint_state)


def _finish_checkpoint_restore(
    farm_world: FarmWorldApp, weather_app: WeatherApp | None,
    checkpoint_state: Mapping[str, Any],
) -> dict[str, Any]:
    """Refresh public shadows without rebuilding the restored environment."""
    from fairy.apps.farm_world.physics_orchestrator import (
        sync_compatibility_fields_from_physics,
    )

    sync_compatibility_fields_from_physics(farm_world)
    if weather_app is not None:
        weather_app.set_avg_soil_vwc(farm_world.get_avg_vwc())
    return _checkpoint_restore_result(farm_world, checkpoint_state)


def _checkpoint_restore_result(
    farm_world: FarmWorldApp, checkpoint_state: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "status": "ok",
        "scenario_id": checkpoint_state.get("scenario_id"),
        "checkpoint_label": checkpoint_state.get("checkpoint_label"),
        "sim_time": farm_world.time_manager.time(),
        "profile_name": getattr(farm_world._physics, "profile_name", None),
    }


def _restore_embedded_weather(physics: Any, state: Mapping[str, Any]) -> None:
    """Restore optional self-contained weather data; historical caches omit it."""
    from fairy.physics.profiles import BioticOutbreak, PhysicsProfile
    from fairy.physics.weather_engine import (
        MonthlyClimate, WeatherEvent, WeatherGenerator, WeatherGeneratorConfig,
    )

    profile = state.get("physics_profile")
    if profile:
        profile = dict(profile)
        profile["start_date"] = date.fromisoformat(profile["start_date"])
        profile["monthly_climate"] = {
            int(month): MonthlyClimate(**values)
            for month, values in profile["monthly_climate"].items()
        }
        profile["weather_events"] = [WeatherEvent(**{
            **event, "start_date": date.fromisoformat(event["start_date"])
        }) for event in profile.get("weather_events", [])]
        profile["biotic_outbreaks"] = [BioticOutbreak(**{
            **event, "pressure_type": TreatmentType(event["pressure_type"])
        }) for event in profile.get("biotic_outbreaks", [])]
        physics.profile = PhysicsProfile(**profile)
    weather = state.get("weather_generator") or {}
    if weather.get("config"):
        config = dict(weather["config"])
        config["monthly"] = {
            int(month): MonthlyClimate(**values)
            for month, values in config["monthly"].items()
        }
        physics.weather_generator = WeatherGenerator(
            WeatherGeneratorConfig(**config), seed=physics.random_seed
        )
        physics.weather_generator._day_overrides = {
            date.fromisoformat(day): _weather_day_from_dict(value)
            for day, value in weather.get("day_overrides", {}).items()
        }


def _export_weather_generator(generator: Any) -> dict[str, Any] | None:
    if generator is None:
        return None
    cache = getattr(generator, "_day_cache", {}) or {}
    return {
        "rng_state": _to_jsonable(generator.rng.bit_generator.state),
        "day_cache": {
            key.isoformat(): _to_jsonable(value) for key, value in cache.items()
        },
    }


def _restore_weather_generator(generator: Any, state: Mapping[str, Any]) -> None:
    if generator is None or not state:
        return
    if state.get("rng_state"):
        generator.rng.bit_generator.state = dict(state["rng_state"])
    generator._day_cache = {  # type: ignore[attr-defined]
        date.fromisoformat(str(day)): _weather_day_from_dict(dict(value))
        for day, value in (state.get("day_cache") or {}).items()
    }


def _weather_day_from_dict(data: dict[str, Any]) -> WeatherDay:
    data = _dataclass_init_data(WeatherDay, data)
    data["day"] = _date_or_none(data.get("day"))
    return WeatherDay(**data)


def _state_map(
    data: Mapping[str, Any] | Mapping[int, Any],
    cls: type[Any],
    *,
    date_fields: tuple[str, ...] = (),
    enum_fields: Mapping[str, type[Enum]] | None = None,
) -> dict[int, Any]:
    restored: dict[int, Any] = {}
    enum_fields = enum_fields or {}
    for key, raw_item in data.items():
        item = _dataclass_init_data(cls, dict(raw_item))
        for field_name in date_fields:
            item[field_name] = _date_or_none(item.get(field_name))
        for field_name, enum_cls in enum_fields.items():
            if item.get(field_name) is not None:
                item[field_name] = enum_cls(item[field_name])
        restored[int(key)] = cls(**item)
    return restored


def _dataclass_init_data(cls: type[Any], data: dict[str, Any]) -> dict[str, Any]:
    allowed = {field.name for field in fields(cls)}
    return {key: value for key, value in data.items() if key in allowed}


def _date_or_none(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _float_or_none(value: Any) -> float | None:
    return None if value is None else float(value)


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _to_jsonable(val) for key, val in vars(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(_to_jsonable(key)): _to_jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        try:
            return value.item()
        except ValueError:
            pass
    return value
