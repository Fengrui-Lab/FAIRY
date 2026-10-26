"""Maize snapshot continuation, rejected bindings, reset and storage safety.

The growing-crop fixture is produced exclusively by the scene's public tools.
The isolated queue test constructs pending inputs without asserting that an
ordinary tool leaves an uncommitted action behind its read/sync boundary.
"""
from copy import deepcopy
import json
from zoneinfo import ZoneInfo

import pytest

from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.crop_snapshot import restore_physics, snapshot_physics
from fairy.controllers.engine import Engine
from fairy.physics import HarvestAction, ManagementAction, ManagementActionType
from fairy.physics.biotic_pressure_engine import TreatmentApplication, TreatmentType
from fairy.scenarios.maize.scenario_single_farm_maize_full_season import (
    CULTIVAR_ID, ScenarioSingleFarmMaizeFullSeason,
)


def fresh():
    scene = ScenarioSingleFarmMaizeFullSeason()
    scene.setup()
    return scene, Engine(None, scene)


@pytest.mark.parametrize("crop_id,width,rows", [("soybean", 1.1, 2), ("maize", 0.65, 1)])
def test_custom_geometry_belongs_to_the_field_for_every_crop(crop_id, width, rows):
    world = FarmWorldApp(crop_id=crop_id, field_length_m=200.0)
    assert world.field_length_m == 200.0
    assert world.field_geometry.ridge_area_m2 == pytest.approx(200 * width)
    assert world.field_geometry.planted_area_m2 == pytest.approx(64 * 200 * width)
    assert world.plants_per_ridge_from_spacing(20.0) == 1000 * rows


def growing():
    scene, engine = fresh()
    for step, app, method, arguments, _ in scene._reference_actions():
        result = getattr(app, method)(**arguments)
        assert not isinstance(result, dict) or "error" not in result, (step, result)
        if step == "emergence_ground":
            break
    # Emergence itself has zero leaf area on its first day. Let the real
    # public clock produce several days of canopy growth before saving.
    scene.system.advance_time(days=3)
    assert all(state.emerged for state in scene.farm_world.physics.phenology.states.values())
    assert all(state.aboveground_biomass_g_m2 > 0 for state in scene.farm_world.physics.canopy.states.values())
    return scene, engine


def json_copy(value):
    return json.loads(json.dumps(value, allow_nan=False))


def clean(value):
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()
                if key not in {"action_id", "op_id", "mission_id", "inspection_id"}}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value


def test_growing_crop_json_snapshot_continues_weather_growth_and_observations():
    original, _ = growing()
    saved_time = original.farm_environment.time_manager.time()
    snapshot = json_copy(original.farm_world.get_state())
    device_names = ("sensor", "field_ops", "tractor", "mavic", "robot")
    devices = {name: json_copy(getattr(original, name).get_state()) for name in device_names}
    restored, _ = fresh()
    restored.farm_environment.time_manager.set_offset(saved_time - restored.start_time)
    restored.farm_world.load_state(snapshot)
    for name, state in devices.items():
        getattr(restored, name).load_state(state)
    assert restored.sensor.get_state() == devices["sensor"]
    assert restored.farm_world.get_state() == snapshot
    assert restored.farm_world.physics is not original.farm_world.physics
    assert restored.farm_world.physics.profile is not original.farm_world.physics.profile
    assert restored.farm_world.physics.weather_generator is not original.farm_world.physics.weather_generator
    successful_drone_observations = 0
    for days in (7, 13):
        original.system.advance_time(days=days)
        restored.system.advance_time(days=days)
        assert original.weather.get_current_weather() == restored.weather.get_current_weather()
        assert original.sensor.read_soil_sensors() == restored.sensor.read_soil_sensors()
        assert original.sensor.read_canopy_sensors() == restored.sensor.read_canopy_sensors()
        # Both use the restored physical observation stream after it had
        # already been consumed by the real emergence inspection before save.
        drone_original = original.mavic.fly_survey(0, 6)
        drone_restored = restored.mavic.fly_survey(0, 6)
        assert clean(drone_original) == clean(drone_restored)
        if "error" not in drone_original:
            successful_drone_observations += 1
            assert drone_original["status"] == "ok"
        ground_original = original.robot.inspect_crop_health(28, 31)
        ground_restored = restored.robot.inspect_crop_health(28, 31)
        assert clean(ground_original) == clean(ground_restored)
        assert ground_original["status"] == "ok"
        assert clean(original.farm_world.get_state()) == clean(restored.farm_world.get_state())
        assert original.farm_environment.time_manager.time() == restored.farm_environment.time_manager.time()
    assert successful_drone_observations >= 1


@pytest.mark.parametrize("incompatible", ["crop", "geometry", "timezone", "cultivar"])
def test_wrong_snapshot_binding_is_rejected_before_world_changes(incompatible):
    source, _ = growing()
    snapshot = json_copy(source.farm_world.get_state())
    if incompatible == "crop":
        target = FarmWorldApp()
    elif incompatible == "geometry":
        target = FarmWorldApp(crop_id="maize", field_length_m=300.0)
        target.simulation_timezone = ZoneInfo("Asia/Shanghai")
    else:
        target = FarmWorldApp(crop_id="maize")
        if incompatible == "cultivar":
            target.simulation_timezone = ZoneInfo("Asia/Shanghai")
            snapshot["crop_configuration"]["cultivar_id"] = "WRONG_MAIZE"
    before = deepcopy(target.get_state())
    previous_physics = target._physics
    with pytest.raises(ValueError, match="crop|geometry"):
        target.load_state(snapshot)
    assert target.get_state() == before
    assert target._physics is previous_physics


def test_pending_management_treatment_and_harvest_json_round_trip():
    scene, _ = growing()
    physics = scene.farm_world.physics
    physics.queue_management_action(3, ManagementAction(
        action_type=ManagementActionType.IRRIGATION, amount=12.0,
        metadata={"unit": "mm", "fixture": "pending snapshot boundary"},
    ))
    physics.queue_treatment(7, TreatmentApplication(
        treatment_type=TreatmentType.FUNGICIDE, efficacy_multiplier=0.4,
    ))
    # An uncompleted machine pass is a harmless pending harvest input; the
    # test checks serialization, rather than harvesting this immature crop.
    physics.queue_harvest(9, HarvestAction(machine_quality=0.8, pass_completed=False))
    before = json_copy(snapshot_physics(physics))
    after = restore_physics(before, 64)
    assert snapshot_physics(after) == before
    assert after.pending_management_actions_by_ridge[3][0].action_type is ManagementActionType.IRRIGATION
    assert after.pending_treatments_by_ridge[7][0].treatment_type is TreatmentType.FUNGICIDE
    assert not after.pending_harvest_actions_by_ridge[9].pass_completed
    assert after.pending_management_actions_by_ridge is not physics.pending_management_actions_by_ridge


def test_reset_discards_physics_and_pending_actions_but_retains_maize_configuration():
    scene, _ = growing()
    world = scene.farm_world
    old_physics = world.physics
    old_geometry = world.field_geometry
    old_environment = world.farm_environment
    world.reset()
    assert world._physics is None
    assert world.crop_id == "maize" and world.cultivar_id == CULTIVAR_ID
    assert world.field_geometry is old_geometry
    assert world.farm_environment is old_environment
    assert world._inventory.seed_stock == {}
    assert world._inventory.fertilizer_kg == 0
    assert world._inventory.fuel_liters == 0
    assert world._inventory.pesticide_liters == 0
    assert world._inventory.warehouse_grain_kg == 0
    assert world._postharvest_market.max_storage_moisture_pct == 14.0
    assert not world.completed_prep_ops
    assert not any(ridge.planted or ridge.harvested for ridge in world._ridges)
    assert world.physics is not old_physics
    assert not world.physics.pending_management_actions_by_ridge
    assert not world.physics.pending_harvest_actions_by_ridge
    assert not any(state.planted for state in world.physics.phenology.states.values())


@pytest.mark.parametrize("moisture", [None, 18.0])
def test_maize_unknown_or_wet_batch_is_denied_before_inventory_changes(moisture):
    # Minimal postharvest batch fixture: moisture-admission rules do not need
    # a second complete season, which is tested through real tools elsewhere.
    world = FarmWorldApp(crop_id="maize")
    world._inventory.harvest_grain_kg = 1000.0
    world._inventory.warehouse_grain_kg = 200.0
    world._trailer_grain_ridge_ids = [0, 1, 2, 3]
    world._trailer_grain_moistures_pct = [] if moisture is None else [moisture]
    before = deepcopy(world.get_state())
    result = world.store_grain()
    assert "error" in result
    assert world.get_state() == before


def test_legacy_soybean_wet_batch_preserves_existing_warning_and_admission():
    world = FarmWorldApp()
    world._inventory.harvest_grain_kg = 1000.0
    world._inventory.warehouse_grain_kg = 200.0
    world._trailer_grain_moistures_pct = [18.0]
    result = world.store_grain()
    assert "error" not in result
    assert "warning" in result
    assert world._inventory.warehouse_grain_kg == 1200.0
    assert world._inventory.harvest_grain_kg == 0.0
