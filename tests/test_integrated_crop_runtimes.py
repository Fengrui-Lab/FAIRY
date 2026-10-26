"""Preserve the three source branches' explicit growth and snapshot choices."""
import json
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from fairy.apps.farm_world.crop_snapshot import restore_physics, snapshot_physics
from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
from fairy.apps.farm_world.maize_dynamics import MaizeDynamics
from fairy.apps.farm_world.soybean_dynamics import ReducedCropDynamics, SoybeanDynamics
from fairy.physics import PlantingConfig, SeedType, SoilWeatherInput


START = date(2026, 5, 5)


def test_explicit_maize_runtime_is_distinct_from_historical_crop_type_proxy():
    soybean = FarmPhysicsState(num_ridges=1)
    proxy = FarmPhysicsState(num_ridges=1, crop_type="maize")
    registered = FarmPhysicsState(num_ridges=1, crop_id="maize")
    assert type(soybean.crop) is SoybeanDynamics
    assert type(proxy.crop) is ReducedCropDynamics
    assert proxy.crop.compatibility_proxy
    assert proxy.crop_id is None and proxy.crop_type == "maize"
    assert type(registered.crop) is MaizeDynamics
    assert registered.crop_id == "maize" and registered.crop_type == "maize"
    for physics in (soybean, proxy, registered):
        assert physics.phenology is physics.crop.phenology
        assert physics.canopy is physics.crop.canopy
        assert physics.yield_recovery is physics.crop.yield_recovery


@pytest.mark.parametrize("crop_type", ["maize", "rice"])
def test_historical_crop_proxy_snapshot_keeps_species_geometry_and_implicit_selection(crop_type):
    physics = FarmPhysicsState(num_ridges=2, crop_type=crop_type,
                               field_length_m=120., ridge_width_m=.8)
    saved = json.loads(json.dumps(snapshot_physics(physics)))
    restored = restore_physics(saved, 2, None, crop_type=crop_type,
                               field_length_m=120., ridge_width_m=.8)
    assert restored.crop_id is None
    assert type(restored.crop) is ReducedCropDynamics
    assert snapshot_physics(restored) == saved
    with pytest.raises(ValueError, match="snapshot"):
        restore_physics(saved, 2, "maize")
    with pytest.raises(ValueError, match="geometry"):
        restore_physics(saved, 2, None, ridge_width_m=.75)


def weather(day):
    return SoilWeatherInput(day, 22., 16., 28., 8., 18., 2.)


@pytest.mark.parametrize("crop_type,seed", [("soybean", SeedType.SOYBEAN_901),
                                           ("maize", SeedType.MAIZE_201)])
def test_complete_snapshot_restores_native_history_pending_n_and_future_weather(crop_type, seed):
    pytest.importorskip("pcse")
    from fairy.physics.wofost_backend import WofostBackend
    options = {"crop_name": crop_type}
    if crop_type == "soybean":
        options["cultivar_map"] = {"SOYBEAN_901": "Soybean_901"}
    physics = FarmPhysicsState(num_ridges=1, crop_type=crop_type, ridge_width_m=.75)
    physics.crop_backend_name = "wofost"
    physics.crop_backend = WofostBackend(options)
    physics.yield_recovery.params.biological_yield_is_dry_matter = True
    physics.phenology.plant_ridges([0], PlantingConfig(START, seed_type=seed))
    physics.management.states[0].stand_fraction = 1.
    physics.crop_backend.advance_day(physics, START, weather(START))
    effective_day = START + timedelta(days=1)
    physics.crop_backend.apply_soil_nitrogen_event(event_id="storm_n_loss", day=effective_day,
        ridge_ids=[0], available_n_kg_ha=4., reserve_n_kg_ha=3.)
    physics.scenario_metadata = {"wofost_scenario_events": {
        "applied_soil_nitrogen_events": [{"event_id": "storm_n_loss"}],
        "last_checked_day": effective_day.isoformat(),
    }}
    physics.set_weather_day_override(effective_day, 22., 8., 2., 18., 16., 28.,
                                     relative_humidity_pct=60.)
    saved = json.loads(json.dumps(snapshot_physics(physics)))
    restored = restore_physics(saved, 1, None, crop_type=crop_type, ridge_width_m=.75)
    assert restored.crop_backend.snapshot() == physics.crop_backend.snapshot()
    assert restored.weather_generator._day_overrides == physics.weather_generator._day_overrides
    assert restored.scenario_metadata == physics.scenario_metadata
    assert restored.phenology is restored.crop.phenology
    for current in (physics, restored):
        current.crop_backend.advance_day(current, effective_day, weather(effective_day))
    assert snapshot_physics(restored) == snapshot_physics(physics)


@pytest.mark.parametrize("crop_type,crop_id", [("soybean", None), ("maize", None), ("maize", "maize")])
def test_legacy_runtime_codec_uses_crop_snapshot_and_preserves_engine_aliases(crop_type, crop_id):
    from fairy.apps.farm_world.runtime_state import decode_state, encode_state
    physics = FarmPhysicsState(num_ridges=1, crop_type=crop_type, crop_id=crop_id)
    restored = decode_state(json.loads(json.dumps(encode_state(physics))))
    assert type(restored.crop) is type(physics.crop)
    for name in ("phenology", "canopy", "yield_recovery"):
        engine = getattr(restored, name)
        assert engine is getattr(restored.crop, name)
        assert engine is getattr(restored.crop.model, name)
        assert engine is not getattr(physics, name)
    assert snapshot_physics(restored) == snapshot_physics(physics)
    # The implementation object is deliberately not added to a generic object
    # allowlist; its registered crop identity and domain codec own restoration.
    with pytest.raises(ValueError, match="Unregistered checkpoint object"):
        encode_state(physics.crop)


def test_freeform_profile_metadata_is_explicit_json_data_and_keeps_dates():
    physics = FarmPhysicsState(num_ridges=1)
    physics.profile = SimpleNamespace(weather_events=[], start_date=START,
                                      notes=SimpleNamespace(kind="synthetic"))
    physics.scenario_metadata = {"observation": SimpleNamespace(unit="mm")}
    saved = json.loads(json.dumps(snapshot_physics(physics)))
    restored = restore_physics(saved, 1)
    assert restored.profile.start_date == START
    assert restored.profile.notes.kind == "synthetic"
    assert restored.scenario_metadata["observation"].unit == "mm"
    assert snapshot_physics(restored) == saved


def test_historical_typed_physics_checkpoint_reconnects_its_crop_facade():
    from fairy.apps.farm_world.runtime_state import decode_state, encode_state
    physics = FarmPhysicsState(num_ridges=1, crop_type="maize")
    # The pre-runtime-split schema serialized only the engine fields. It had
    # no crop adapter object; construct that historical representation here.
    saved = {"$kind": "object", "type": "fairy.apps.farm_world.farm_physics_state.FarmPhysicsState",
             "fields": {key: encode_state(value) for key, value in vars(physics).items()
                        if key != "crop"}}
    restored = decode_state(json.loads(json.dumps(saved)))
    for name in ("phenology", "canopy", "yield_recovery"):
        assert getattr(restored, name) is getattr(restored.crop, name)
        assert getattr(restored, name) is getattr(restored.crop.model, name)
    assert snapshot_physics(restored) == snapshot_physics(physics)


def test_runtime_codec_preserves_explicit_crop_profile_overrides():
    from fairy.apps.farm_world.runtime_state import decode_state, encode_state
    physics = FarmPhysicsState(num_ridges=1, crop_type="maize")
    physics.crop_profile = replace(physics.crop_profile, yield_kg_m2=1.73)
    restored = decode_state(json.loads(json.dumps(encode_state(physics))))
    assert restored.crop_profile == physics.crop_profile
    assert snapshot_physics(restored) == snapshot_physics(physics)


def test_legacy_rice_robot_has_generic_observation_traits_without_a_new_factory():
    from fairy.apps.farm_world.crop_dynamics import create_crop_dynamics, get_crop_observation_traits
    from fairy.apps.farm_world.farm_world_app import FarmWorldApp
    from fairy.apps.farm_world.robot_app import RobotApp
    from fairy.apps.farm_world.weather_app import WeatherApp
    traits = get_crop_observation_traits("rice")
    assert traits.diagnosed_pest_type is None and traits.diagnosed_disease_type is None
    with pytest.raises(ValueError, match="Unsupported crop dynamics"):
        create_crop_dynamics("rice", 1)
    world = FarmWorldApp(crop_type="rice", num_ridges=1)
    assert not world.physics_active
    result = RobotApp(world, WeatherApp()).inspect_ridge(0)
    assert result["status"] == "ok"
    assert result["result"]["ridge_id"] == 0
    assert result["result"]["pest_type"] is None and result["result"]["disease_type"] is None


def test_full_checkpoint_without_weather_argument_retains_its_station_and_future_forecast():
    pytest.importorskip("pcse")
    from fairy.apps.farm_world.farm_world_app import FarmWorldApp
    from fairy.apps.farm_world.weather_app import WeatherApp
    from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs
    from fairy.scenarios.farm_world_fullseason_v2.farm_checkpoint_state import (
        export_farm_checkpoint_state, restore_farm_checkpoint_state,
    )
    original = FarmWorldApp(num_ridges=1)
    original.simulation_timezone = ZoneInfo("Europe/Paris")
    station = WeatherApp()
    station.set_weather(date=START.isoformat(), temp_c=22., humidity_pct=60.,
        wind_speed_ms=2., rainfall_mm=0., solar_radiation=250., forecast=[{
            "date": (START + timedelta(days=1)).isoformat(), "temp_c": 21.,
            "rainfall_mm": 17., "humidity_pct": 65., "wind_speed_ms": 2.,
            "solar_radiation": 240.,
        }])
    original.attach_weather_app(station)
    original.configure_crop_backend("wofost")
    saved = export_farm_checkpoint_state(farm_world=original, weather_app=None,
        scenario_id="optional_weather", checkpoint_label="before_tomorrow")
    restored = FarmWorldApp(num_ridges=1)
    restore_farm_checkpoint_state(farm_world=restored, weather_app=None, checkpoint_state=saved)
    assert restored._weather_app is not station
    assert restored._weather_app.get_state() == station.get_state()
    assert restored._weather_app.time_manager is restored.time_manager
    assert restored._weather_app.simulation_timezone == ZoneInfo("Europe/Paris")
    tomorrow = _build_weather_inputs(restored._weather_app, START + timedelta(days=1),
                                     physics=restored.physics)
    assert tomorrow["soil"].rain_mm == 17.

