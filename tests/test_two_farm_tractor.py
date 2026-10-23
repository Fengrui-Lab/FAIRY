from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest

from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.models import GrowthStage
from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
from fairy.apps.farm_world.tractor_app import TractorApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.time_manager import TimeManager


@pytest.fixture
def tractor_scene():
    weather = WeatherApp()
    clock = TimeManager()
    clock.reset(datetime(2026, 5, 10, tzinfo=timezone.utc).timestamp())
    farms = [FarmContext(farm_id, FarmWorldApp(name=farm_id), weather)
             for farm_id in ("farm_a", "farm_b")]
    environment = FarmEnvironment(farms, weather, clock)
    tractor = SharedTractorApp(environment)
    return environment, tractor, farms[0].world, farms[1].world


def test_same_tractor_uses_continuous_fuel_but_keeps_prep_on_each_farm(tractor_scene):
    environment, tractor, farm_a, farm_b = tractor_scene
    assert tractor.attach_implement("grader")["status"] == "ok"
    assert tractor.level("farm_a")["farm_id"] == "farm_a"
    assert farm_a.completed_prep_ops == ["level"]
    assert farm_b.completed_prep_ops == []
    first_duration = environment.time_manager.offset
    assert first_duration > 0
    assert tractor.level("farm_b")["status"] == "ok"
    assert tractor.get_status()["fuel_tank_l"] == 84.0
    assert environment.time_manager.offset == first_duration * 2
    assert [entry["farm_id"] for entry in tractor._operation_log] == ["farm_a", "farm_b"]
    assert "completed_prep_ops" not in tractor.get_state()


def test_trafficability_is_checked_on_target_farm(tractor_scene):
    _, tractor, farm_a, farm_b = tractor_scene
    for ridge in farm_b._ridges:
        ridge.soil_vwc = 0.43
    tractor.attach_implement("grader")
    assert tractor.level("farm_a")["status"] == "ok"
    result = tractor.level("farm_b")
    assert "too wet" in result["error"]
    assert tractor.get_status()["fuel_tank_l"] == 92.0
    assert farm_a.completed_prep_ops == ["level"]
    assert farm_b.completed_prep_ops == []


def test_payload_is_returned_only_to_its_real_origin(tractor_scene):
    _, tractor, farm_a, farm_b = tractor_scene
    before_a = farm_a._inventory.to_dict()
    before_b = farm_b._inventory.to_dict()
    assert tractor.load_seeds("farm_a", "STANDARD", 10000)["status"] == "ok"
    assert tractor.load_fertilizer("farm_a", 50)["status"] == "ok"
    assert tractor.load_pesticide("farm_a", 40)["status"] == "ok"
    assert tractor.load_fungicide("farm_a", 20)["status"] == "ok"
    assert tractor.get_status()["source_farm_id"] == "farm_a"
    assert "error" in tractor.load_fertilizer("farm_b", 10)
    assert "error" in tractor.return_supplies("farm_b")
    assert farm_b._inventory.to_dict() == before_b
    returned = tractor.return_supplies("farm_a")
    assert returned["returned"]["fungicide_liters"] == 20
    assert farm_a._inventory.to_dict() == before_a
    assert farm_a._management_regime.fertilizer_used_kg == 0
    assert tractor.get_status()["source_farm_id"] is None
    assert tractor.load_fertilizer("farm_b", 10)["status"] == "ok"
    assert tractor.get_status()["source_farm_id"] == "farm_b"


def test_using_last_supply_clears_origin_and_allows_next_farm(tractor_scene):
    _, tractor, farm_a, farm_b = tractor_scene
    tractor.load_fertilizer("farm_a", 200)
    assert tractor.base_fertilize("farm_a")["status"] == "ok"
    assert farm_a.completed_prep_ops == ["base_fertilize"]
    assert farm_b.completed_prep_ops == []
    assert tractor.get_status()["source_farm_id"] is None
    assert tractor.load_fertilizer("farm_b", 200)["status"] == "ok"
    assert tractor.base_fertilize("farm_b")["status"] == "ok"
    assert farm_b.completed_prep_ops == ["base_fertilize"]


def test_seed_varieties_do_not_mix_and_failed_load_does_not_change_type(tractor_scene):
    _, tractor, _, _ = tractor_scene
    tractor.load_seeds("farm_a", "STANDARD", 100)
    result = tractor.load_seeds("farm_a", "HEIHE43", 100)
    assert "error" in result
    assert tractor.get_status()["seed_type"] == "STANDARD"
    assert tractor.get_status()["seed_hopper"] == 100


def test_harvest_cannot_mix_grain_or_unload_it_to_other_farm(tractor_scene):
    _, tractor, farm_a, farm_b = tractor_scene
    for world in (farm_a, farm_b):
        ridge = world.get_ridge(0)
        ridge.planted = True
        ridge.growth_stage = GrowthStage.R8.value
        ridge.grain_moisture_pct = 15
        ridge.yield_potential = 0.8
    initial_a = farm_a._inventory.harvest_grain_kg
    initial_b = farm_b._inventory.harvest_grain_kg
    harvested = tractor.harvest("farm_a", 0, 0)
    assert harvested["status"] == "ok"
    grain = harvested["grain_kg_added"]
    assert grain > 0
    assert tractor.get_status()["grain_origin_farm_id"] == "farm_a"
    assert "error" in tractor.harvest("farm_b", 0, 0)
    assert farm_b.get_ridge(0).planted
    assert "error" in tractor.unload_grain("farm_b")
    assert farm_b._inventory.harvest_grain_kg == initial_b
    assert tractor.unload_grain("farm_a")["grain_kg_unloaded"] == grain
    assert farm_a._inventory.harvest_grain_kg == initial_a + grain
    assert tractor.get_status()["grain_origin_farm_id"] is None
    assert tractor.harvest("farm_b", 0, 0)["status"] == "ok"


def test_shared_state_round_trip_preserves_payload_origin_and_seed_type(tractor_scene):
    _, tractor, farm_a, _ = tractor_scene
    tractor.load_seeds("farm_a", "STANDARD", 100)
    tractor.load_fungicide("farm_a", 25)
    farm_a.completed_prep_ops.append("level")
    state = tractor.get_state()
    tractor.reset()
    tractor.load_state(state)
    assert tractor.get_state() == state
    assert farm_a.completed_prep_ops == ["level"]
    assert tractor.get_status()["source_farm_id"] == "farm_a"
    assert "error" in tractor.load_pesticide("farm_b", 1)
    with pytest.raises(ValueError, match="requires source_farm_id"):
        tractor.load_state({"seed_hopper": 20})


def test_public_schema_exposes_real_farm_parameter_and_rejects_missing_target(tractor_scene):
    _, tractor, _, _ = tractor_scene
    tool = next(tool for tool in tractor.get_tools() if tool.name == "plant_seeds")
    schema = tool.to_open_ai()["function"]["parameters"]
    assert schema["properties"]["farm_id"]["enum"] == ["farm_a", "farm_b"]
    assert "farm_id" in schema["required"]
    assert "local" in schema["properties"]["start_ridge"]["description"]
    assert list(inspect.signature(SharedTractorApp.plant_seeds).parameters) == [
        "self", "farm_id", "start_ridge", "end_ridge", "depth_cm", "seed_spacing_cm"
    ]
    invalid = tool(start_ridge=0, end_ridge=0, depth_cm=4, seed_spacing_cm=10)
    assert "farm_id" in invalid["error"]
    with pytest.raises(TypeError):
        tractor.plant_seeds(start_ridge=0, end_ridge=0, depth_cm=4, seed_spacing_cm=10)
    with pytest.raises(ValueError, match="Unknown farm_id"):
        tractor.level("missing")


def test_legacy_api_uses_same_algorithms_and_the_registered_clock():
    world = FarmWorldApp()
    tractor = TractorApp(world, WeatherApp())
    clock = TimeManager()
    tractor.register_time_manager(clock)
    tractor.attach_implement("grader")
    assert tractor.level()["status"] == "ok"
    assert clock.offset > 0
    assert tractor._completed_prep_ops is world.completed_prep_ops
    assert world.completed_prep_ops == ["level"]
    assert "farm_id" not in inspect.signature(TractorApp.level).parameters


def test_direct_shared_constructor_uses_environment_clock_for_physics_actions(tractor_scene):
    environment, tractor, farm_a, farm_b = tractor_scene
    assert tractor.time_manager is environment.time_manager
    for world in (farm_a, farm_b):
        world.configure_physics_profile("two_farm_tractor_test")
    tractor.load_fertilizer("farm_a", 200)
    assert tractor.base_fertilize("farm_a")["status"] == "ok"
    action = farm_a.physics.action_log[-1]
    assert action.timestamp >= environment.time_manager.start_time + environment.time_manager.offset
    assert action.timestamp <= environment.time_manager.time()
    assert farm_a.physics.last_physics_sim_time == farm_b.physics.last_physics_sim_time
    assert farm_b.physics.action_log == []


def test_shared_tractor_does_not_copy_either_farm_soil_into_common_weather(tractor_scene):
    environment, tractor, farm_a, farm_b = tractor_scene
    environment.weather.set_avg_soil_vwc(0.19)
    for ridge in farm_a._ridges:
        ridge.soil_vwc = 0.25
    for ridge in farm_b._ridges:
        ridge.soil_vwc = 0.43
    tractor.attach_implement("grader")
    assert tractor.level("farm_a")["status"] == "ok"
    assert environment.weather.get_state()["avg_soil_vwc"] == 0.19
    assert "too wet" in tractor.level("farm_b")["error"]
    assert environment.weather.get_state()["avg_soil_vwc"] == 0.19
