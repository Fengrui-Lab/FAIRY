from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone, timedelta
import json
import random

import numpy as np
import pytest

from fairy.apps.farm_world.assets import AssetSpec
from fairy.apps.farm_world.multi_farm import FarmFleet, FarmSite
from fairy.apps.farm_world.runtime_state import decode_state, encode_state, restore_runtime, snapshot_runtime
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.physics.management_effect_engine import ManagementAction, ManagementActionType
from fairy.time_manager import TimeManager


def _runtime(*, shared_station=False, physical=True):
    station = WeatherApp() if shared_station else None
    sites = [FarmSite.create(name, name.title(), create_devices=False,
                            station_id="shared" if shared_station else name,
                            weather_app=station, num_ridges=2, field_length_m=80)
             for name in ("north", "south")]
    fleet = FarmFleet(sites, shared_tools=True,
                      assets=[AssetSpec("tractor_1", "tractor", ("north", "south")),
                              AssetSpec("drone_1", "drone", ("north", "south"))])
    runtime = fleet.runtime
    runtime.definition_metadata = {"season": 180, "monitoring": 7}
    clock = TimeManager()
    clock.reset(datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp())
    runtime.bind_clock(clock)
    clock.register_offset_observer("runtime:0", runtime.before_advance, runtime.advance_to)
    if physical:
        for site in sites:
            physics = site.farm.physics
            for day in range(1, 31):
                physics.set_weather_day_override(date(2026, 5, day), 26, 2, 2, 15)
            site.farm.set_ridge_planted(0, "STANDARD", 8)
    runtime.freeze()
    return runtime


def _json_checkpoint(runtime):
    return json.loads(json.dumps(snapshot_runtime(runtime), allow_nan=False))


def test_complete_physics_json_roundtrip_preserves_queues_weather_rng_and_continues():
    runtime = _runtime()
    runtime.clock.add_offset(5 * 86400)
    physics = runtime.farms["north"].farm.physics
    physics.queue_management_action(0, ManagementAction(ManagementActionType.IRRIGATION, amount=7))
    before_physics = encode_state(physics)
    checkpoint = _json_checkpoint(runtime)
    restored = restore_runtime(checkpoint)
    other = restored.farms["north"].farm.physics
    assert encode_state(other) == before_physics
    assert other is not physics
    assert restored.registry.manifest == runtime.registry.manifest
    assert restored._initial_definition == runtime._initial_definition
    assert restored.definition_metadata == runtime.definition_metadata
    assert other.pending_management_actions_by_ridge[0][0].action_type is ManagementActionType.IRRIGATION
    assert restored.farms["north"].sensor.rng.random() == runtime.farms["north"].sensor.rng.random()
    assert other.observation_model.rng.random() == physics.observation_model.rng.random()
    gdd = other.phenology.states[0].accumulated_gdd
    restored.clock.add_offset(86400)
    assert other.phenology.states[0].accumulated_gdd > gdd
    assert not other.pending_management_actions_by_ridge
    assert physics.pending_management_actions_by_ridge  # original world is untouched


def test_shared_station_and_asset_remain_single_objects_after_restore():
    runtime = _runtime(shared_station=True, physical=False)
    tools = {app.name: app for app in runtime.apps}
    assert tools["Tractor"].load_seeds(farm_id="north", asset_id="tractor_1",
                                        seed_type="STANDARD", count=37)["ok"]
    checkpoint = _json_checkpoint(runtime)
    restored = restore_runtime(checkpoint)
    assert restored.farms["north"].weather is restored.farms["south"].weather
    assert restored.farms["north"].weather is not runtime.farms["north"].weather
    assert len(restored.assets) == 2
    assert restored.assets["tractor_1"].data["_seed_hopper"] == 37
    assert restored.assets["tractor_1"].payload_origin_farm_id == "north"
    assert restored.executor.history == runtime.executor.history
    assert restored.fleet.get("north").tractor._shared_asset_state is restored.fleet.get("south").tractor._shared_asset_state
    restored.assets["tractor_1"].data["_fuel_tank_l"] = 75
    assert runtime.assets["tractor_1"].data["_fuel_tank_l"] == 100


def test_invalid_restore_never_mutates_original_and_rejects_changed_initial_definition():
    runtime = _runtime(physical=False)
    checkpoint = _json_checkpoint(runtime)
    bad = deepcopy(checkpoint)
    bad["farms"][0]["spec"]["num_ridges"] = 3
    with pytest.raises(ValueError, match="ridge identity"):
        restore_runtime(bad)
    assert runtime.farms["north"].farm.num_ridges == 2
    bad = deepcopy(checkpoint)
    initial = decode_state(bad["initial_definition"])
    initial["seed"] += 1
    bad["initial_definition"] = encode_state(initial)
    with pytest.raises(ValueError, match="fingerprint"):
        restore_runtime(bad)
    assert runtime.seed == 0


def test_snapshot_during_operation_is_rejected():
    runtime = _runtime(physical=False)
    runtime._active = True
    with pytest.raises(ValueError, match="between tool operations"):
        snapshot_runtime(runtime)


def test_codec_restores_typed_keys_dates_tuples_and_numpy_random_without_pickle():
    value = {date(2026, 5, 1): (ManagementActionType.IRRIGATION, np.asarray([1, 2, 3], dtype=np.int64)),
             7: {"random": random.Random(12), "numpy": np.random.default_rng(14)}}
    restored = decode_state(json.loads(json.dumps(encode_state(value), allow_nan=False)))
    assert date(2026, 5, 1) in restored and 7 in restored
    assert isinstance(restored[date(2026, 5, 1)], tuple)
    assert restored[date(2026, 5, 1)][0] is ManagementActionType.IRRIGATION
    np.testing.assert_array_equal(restored[date(2026, 5, 1)][1], [1, 2, 3])
    assert restored[7]["random"].random() == value[7]["random"].random()
    assert restored[7]["numpy"].random() == value[7]["numpy"].random()


def test_codec_rejects_unregistered_types_fields_and_object_arrays():
    with pytest.raises(ValueError, match="Unknown checkpoint object"):
        decode_state({"$kind": "object", "type": "os.system", "fields": {}})
    payload = encode_state(ManagementAction(ManagementActionType.IRRIGATION))
    payload["fields"]["callback"] = "not allowed"
    with pytest.raises(ValueError, match="Unregistered"):
        decode_state(payload)
    with pytest.raises(ValueError, match="numeric dtype"):
        encode_state(np.asarray([object()], dtype=object))


def test_native_wofost_checkpoint_uses_supported_journal_and_continues():
    pytest.importorskip("pcse")
    from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
    from fairy.physics import PlantingConfig, SeedType, SoilWeatherInput
    from fairy.physics.wofost_backend import WofostBackend, WofostConfig

    physics = FarmPhysicsState(num_ridges=1)
    start = date(2026, 5, 1)
    physics.phenology.plant_ridges([0], PlantingConfig(start, SeedType.STANDARD))
    physics.management.states[0].planted = True
    physics.management.states[0].stand_fraction = 1
    physics.crop_backend_name = "wofost"
    physics.crop_backend = WofostBackend(WofostConfig())
    physics.crop_backend.bind_physics(physics)

    def advance(bundle, offset):
        day = start + timedelta(days=offset)
        weather = SoilWeatherInput(day, air_temp_mean_c=22, air_temp_min_c=16,
                                   air_temp_max_c=28, rain_mm=2, solar_rad_mj_m2=20, wind_ms=2)
        bundle.crop_backend.advance_day(physics=bundle, day=day, weather=weather,
                                        density_by_ridge={0: 40}, ridge_area_m2=80,
                                        humidity_pct=55)

    for offset in range(3):
        advance(physics, offset)
    restored = decode_state(json.loads(json.dumps(encode_state(physics), allow_nan=False)))
    assert restored.crop_backend is not physics.crop_backend
    assert restored.crop_backend.export_state() == physics.crop_backend.export_state()
    advance(physics, 3)
    advance(restored, 3)
    assert restored.crop_backend.snapshot() == physics.crop_backend.snapshot()
    assert restored.phenology.states == physics.phenology.states

