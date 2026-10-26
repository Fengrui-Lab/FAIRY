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
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.time_manager import TimeManager


@pytest.fixture
def tractor_scene():
    weather = WeatherApp()
    clock = TimeManager()
    clock.reset(datetime(2026, 5, 10, tzinfo=timezone.utc).timestamp())
    farms = [FarmContext(farm_id, FarmWorldApp(name=farm_id), weather)
             for farm_id in ("farm_a", "farm_b")]
    warehouse = WarehouseApp(stock=WarehouseStock(
        seed_stock={"STANDARD": 2_000_000, "HEIHE43": 2_000_000},
        pesticide_liters=4000.0, fertilizer_kg=4000.0, fuel_liters=2000.0,
    ))
    environment = FarmEnvironment(farms, weather, clock, warehouse=warehouse)
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


def test_payload_returns_to_one_warehouse_without_reserving_any_field_quota(tractor_scene):
    environment, tractor, farm_a, farm_b = tractor_scene
    before = environment.warehouse.get_inventory()
    assert tractor.load_seeds("STANDARD", 10000)["status"] == "ok"
    assert tractor.load_fertilizer(50)["status"] == "ok"
    assert tractor.load_pesticide(40)["status"] == "ok"
    assert tractor.load_fungicide(20)["status"] == "ok"
    assert "source_farm_id" not in tractor.get_status()
    assert farm_a._management_regime.fertilizer_used_kg == 0
    assert farm_b._management_regime.fertilizer_used_kg == 0
    returned = tractor.return_supplies()
    assert returned["returned"]["fungicide_liters"] == 20
    assert environment.warehouse.get_inventory() == before


def test_one_payload_can_fertilize_both_fields_and_usage_belongs_to_actual_field(tractor_scene):
    environment, tractor, farm_a, farm_b = tractor_scene
    before = environment.warehouse.get_inventory()["fertilizer_kg"]
    tractor.load_fertilizer(400)
    assert tractor.base_fertilize("farm_a")["status"] == "ok"
    assert farm_a.completed_prep_ops == ["base_fertilize"]
    assert farm_b.completed_prep_ops == []
    assert tractor.get_status()["fertilizer_spreader_kg"] == 200
    assert tractor.base_fertilize("farm_b")["status"] == "ok"
    assert farm_b.completed_prep_ops == ["base_fertilize"]
    assert environment.warehouse.get_inventory()["fertilizer_kg"] == before - 400
    assert farm_a._management_regime.fertilizer_used_kg == 200
    assert farm_b._management_regime.fertilizer_used_kg == 200


def test_seed_varieties_do_not_mix_and_failed_load_does_not_change_type(tractor_scene):
    _, tractor, _, _ = tractor_scene
    tractor.load_seeds("STANDARD", 100)
    result = tractor.load_seeds("HEIHE43", 100)
    assert "error" in result
    assert tractor.get_status()["seed_type"] == "STANDARD"
    assert tractor.get_status()["seed_hopper"] == 100


def test_harvest_keeps_origin_and_unloads_to_named_warehouse_batch(tractor_scene):
    environment, tractor, farm_a, farm_b = tractor_scene
    for world in (farm_a, farm_b):
        ridge = world.get_ridge(0)
        ridge.planted = True
        ridge.seed_type = "STANDARD"
        ridge.growth_stage = GrowthStage.R8.value
        ridge.grain_moisture_pct = 15
        ridge.yield_potential = 0.8
    harvested = tractor.harvest("farm_a", 0, 0)
    assert harvested["status"] == "ok"
    grain = harvested["grain_kg_added"]
    assert grain > 0
    assert tractor.get_status()["grain_origin_farm_id"] == "farm_a"
    assert "error" in tractor.harvest("farm_b", 0, 0)
    assert farm_b.get_ridge(0).planted
    # The farm selector applies to field work; unloading names a traceable batch.
    assert tractor.unload_grain("a-harvest-1")["grain_kg_unloaded"] == grain
    batches = environment.warehouse.get_grain_batches()["batches"]
    assert len(batches) == 1
    assert batches[0]["batch_id"] == "a-harvest-1"
    assert batches[0]["origin_farm_id"] == "farm_a"
    assert batches[0]["ridge_ids"] == [0]
    assert environment.warehouse.get_inventory()["harvest_grain_kg"] == grain
    assert tractor.get_status()["grain_origin_farm_id"] is None
    assert tractor.harvest("farm_b", 0, 0)["status"] == "ok"


def test_shared_state_round_trip_preserves_payload_and_seed_type(tractor_scene):
    _, tractor, farm_a, _ = tractor_scene
    tractor.load_seeds("STANDARD", 100)
    tractor.load_fungicide(25)
    farm_a.completed_prep_ops.append("level")
    state = tractor.get_state()
    tractor.reset()
    tractor.load_state(state)
    assert tractor.get_state() == state
    assert farm_a.completed_prep_ops == ["level"]
    assert "source_farm_id" not in tractor.get_status()
    assert tractor.load_pesticide(1)["status"] == "ok"
    invalid_state = tractor.get_state()
    invalid_state.update(seed_hopper=20, seed_type=None)
    with pytest.raises(ValueError, match="seed_type"):
        tractor.load_state(invalid_state)


def test_one_seed_payload_can_plant_both_farms(tractor_scene):
    environment, tractor, a, b = tractor_scene
    for world in (a, b):
        world.completed_prep_ops[:] = ["level", "base_fertilize", "form_ridges"]
        world.get_ridge(0).soil_temp_c = 16.0
    seeds_per_ridge = a.plants_per_ridge_from_spacing(5.0)
    initial = environment.warehouse.stock.seed_stock["STANDARD"]
    assert tractor.load_seeds("STANDARD", 2 * seeds_per_ridge)["status"] == "ok"
    assert tractor.plant_seeds("farm_a", 0, 0, 4.0, 5.0)["status"] == "ok"
    assert tractor.plant_seeds("farm_b", 0, 0, 4.0, 5.0)["status"] == "ok"
    assert tractor.get_status()["seed_hopper"] == 0
    assert a.get_ridge(0).seeds_planted == b.get_ridge(0).seeds_planted == seeds_per_ridge
    assert initial - environment.warehouse.stock.seed_stock["STANDARD"] == 2 * seeds_per_ridge


def test_material_exhaustion_rejects_second_machine_load_atomically(tractor_scene):
    environment, tractor, _, _ = tractor_scene
    environment.warehouse.stock.fertilizer_kg = 30.0
    second = SharedTractorApp(environment, name="SecondTractor")
    assert tractor.load_fertilizer(30)["status"] == "ok"
    before, clock = second.get_state(), environment.time_manager.offset
    assert "error" in second.load_fertilizer(1)
    assert second.get_state() == before
    assert environment.time_manager.offset == clock
    assert environment.warehouse.stock.fertilizer_kg == 0
    tractor.return_supplies()
    assert second.load_fertilizer(30)["status"] == "ok"
    assert environment.warehouse.stock.fertilizer_kg + second._fertilizer_spreader_kg == 30


def test_fertilizer_quota_is_checked_when_applying_to_each_field(tractor_scene):
    environment, tractor, a, b = tractor_scene
    a.configure_management_regime(fertilizer_quota_kg=100)
    b.configure_management_regime(fertilizer_quota_kg=250)
    assert tractor.load_fertilizer(400)["status"] == "ok"
    before, clock = tractor.get_state(), environment.time_manager.offset
    assert "error" in tractor.base_fertilize("farm_a")
    assert tractor.get_state() == before
    assert environment.time_manager.offset == clock
    assert tractor.base_fertilize("farm_b")["status"] == "ok"
    assert a._management_regime.fertilizer_used_kg == 0
    assert b._management_regime.fertilizer_used_kg == 200
    tractor.return_supplies()
    assert b._management_regime.fertilizer_used_kg == 200


def test_small_load_and_return_preserve_stock_plus_machine_material(tractor_scene):
    environment, tractor, _, _ = tractor_scene
    before = environment.warehouse.stock.pesticide_liters
    assert tractor.load_pesticide(0.005)["status"] == "ok"
    assert environment.warehouse.stock.pesticide_liters + tractor._pesticide_tank_l == pytest.approx(before)
    tractor.return_supplies()
    assert environment.warehouse.stock.pesticide_liters == pytest.approx(before)


def test_onboard_grain_does_not_lock_unrelated_field_operations(tractor_scene):
    _, tractor, a, b = tractor_scene
    ridge = a.get_ridge(0)
    ridge.planted = True
    ridge.seed_type = "STANDARD"
    ridge.growth_stage = GrowthStage.R8.value
    ridge.grain_moisture_pct = 15
    ridge.yield_potential = 0.8
    assert tractor.harvest("farm_a", 0, 0)["status"] == "ok"
    grain_kg = tractor.get_state()["grain_bin_kg"]
    assert tractor.load_fertilizer(200)["status"] == "ok"
    assert tractor.base_fertilize("farm_b")["status"] == "ok"
    assert b.completed_prep_ops == ["base_fertilize"]
    assert tractor.get_state()["grain_bin_kg"] == grain_kg
    assert tractor.get_state()["grain_origin_farm_id"] == "farm_a"


def test_duplicate_or_blank_batch_id_does_not_spend_unload_time_or_clear_grain(tractor_scene):
    environment, tractor, a, _ = tractor_scene
    for rid in (0, 1):
        ridge = a.get_ridge(rid)
        ridge.planted = True
        ridge.seed_type = "STANDARD"
        ridge.growth_stage = GrowthStage.R8.value
        ridge.grain_moisture_pct = 15
        ridge.yield_potential = 0.8
    assert tractor.harvest("farm_a", 0, 0)["status"] == "ok"
    assert tractor.unload_grain("first")["status"] == "ok"
    assert tractor.harvest("farm_a", 1, 1)["status"] == "ok"
    before, stock = tractor.get_state(), environment.warehouse.get_state()
    clock = environment.time_manager.offset
    for batch_id in ("first", "   "):
        assert "error" in tractor.unload_grain(batch_id)
        assert tractor.get_state() == before
        assert environment.warehouse.get_state() == stock
        assert environment.time_manager.offset == clock


def test_grain_bin_snapshot_can_unload_without_field_staging_metadata(tractor_scene):
    environment, tractor, a, _ = tractor_scene
    ridge = a.get_ridge(0)
    ridge.planted = True
    ridge.seed_type = "STANDARD"
    ridge.growth_stage = GrowthStage.R8.value
    ridge.grain_moisture_pct = 15
    ridge.yield_potential = 0.8
    assert tractor.harvest("farm_a", 0, 0)["status"] == "ok"
    saved = tractor.get_state()
    assert saved["grain_ridge_ids"] == [0]
    assert saved["grain_moistures_pct"] == [15]
    assert saved["grain_cultivar_ids"] == ["STANDARD"]
    assert a._pending_bin_grain_ridge_ids == []
    assert a._pending_bin_grain_moistures_pct == []
    stock = environment.warehouse.get_state()
    tractor.reset()
    tractor.load_state(saved)
    assert tractor.get_state() == saved
    assert environment.warehouse.get_state() == stock
    result = tractor.unload_grain("restored-a")
    assert result["status"] == "ok"
    batch = environment.warehouse.grain_batches["restored-a"]
    assert batch.origin_farm_id == "farm_a"
    assert batch.ridge_ids == [0]
    assert batch.moisture_pct == 15
    assert batch.cultivar_id == "STANDARD"
    assert batch.quantity_kg == saved["grain_bin_kg"]


@pytest.mark.parametrize("corrupt", ["missing_origin", "missing_moisture", "nan_mass"])
def test_bad_grain_bin_snapshot_is_rejected_before_machine_or_warehouse_changes(tractor_scene, corrupt):
    environment, tractor, _, _ = tractor_scene
    before = tractor.get_state()
    stock = environment.warehouse.get_state()
    incoming = {**before, "grain_bin_kg": 100, "grain_origin_farm_id": "farm_a",
                "grain_ridge_ids": [0], "grain_moistures_pct": [15],
                "grain_cultivar_ids": ["STANDARD"]}
    if corrupt == "missing_origin":
        incoming["grain_origin_farm_id"] = None
    elif corrupt == "missing_moisture":
        incoming["grain_moistures_pct"] = []
    else:
        incoming["grain_bin_kg"] = float("nan")
    with pytest.raises(ValueError):
        tractor.load_state(incoming)
    assert tractor.get_state() == before
    assert environment.warehouse.get_state() == stock


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
    before = tractor.get_state()
    offset = tractor.farm_environment.time_manager.offset
    result = tractor.level("missing")
    assert "choose one of" in result["error"]
    assert tractor.get_state() == before
    assert tractor.farm_environment.time_manager.offset == offset


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
    tractor.load_fertilizer(200)
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
