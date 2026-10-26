"""Mixed-crop public boundaries, independent of a particular season scenario.

The fixture explicitly tightens this soybean field's implement requirements.
Maturity fixtures below isolate harvest routing; they do not claim to grow a
season. Full-season integration belongs to the independent mixed scenario.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from fairy.agents.agent.toolset_builder import build_toolset
from fairy.apps.farm_world.drone_app import DroneApp
from fairy.apps.farm_world.equipment import DEFAULT_TRACTOR_IMPLEMENTS, TractorEquipment
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.robot_app import RobotApp
from fairy.apps.farm_world.shared_drone_app import SharedDroneApp
from fairy.apps.farm_world.shared_robot_app import SharedRobotApp
from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.time_manager import SimulationTimeManager


MAIZE_SEED = "MAIZE_EARLY_2026"
SOYBEAN_SEED = "HEINONG84"
START = datetime(2026, 5, 15, 9, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()


def call(app, method, **arguments):
    return next(tool for tool in app.get_tools() if tool.name == method)(**arguments)


def make_mixed():
    weather = WeatherApp()
    weather.set_weather("2026-05-15", 20, 50, 1, 0, 350)
    maize = FarmWorldApp(crop_id="maize", cultivar_id=MAIZE_SEED,
                         farm_id="maize_field", name="MaizeField")
    soybean = FarmWorldApp(crop_id="soybean", cultivar_id=SOYBEAN_SEED,
                           farm_id="soybean_field", name="SoybeanField")
    # Local field configuration, not a change to global soybean compatibility.
    soybean.crop_definition = replace(
        soybean.crop_definition,
        planting_rules=replace(soybean.crop_definition.planting_rules,
                               required_implement="soybean_planter"),
        harvest_rules=replace(soybean.crop_definition.harvest_rules,
                              required_implement="harvester"),
    )
    for world in (maize, soybean):
        for ridge in world._ridges:
            ridge.soil_vwc, ridge.soil_temp_c = .24, 18.0
            ridge.stand_fraction = 1.0
    warehouse = WarehouseApp(WarehouseStock(
        {MAIZE_SEED: 100000, SOYBEAN_SEED: 100000},
        pesticide_liters=100, fertilizer_kg=1200, fuel_liters=500,
    ), storage_capacity_kg=10000)
    env = FarmEnvironment([
        FarmContext(maize.farm_id, maize, weather),
        FarmContext(soybean.farm_id, soybean, weather),
    ], weather, start_time=START, timezone_name="Asia/Shanghai", warehouse=warehouse)
    equipment = TractorEquipment(
        implements=(*DEFAULT_TRACTOR_IMPLEMENTS, "maize_planter", "maize_header", "soybean_planter"),
        ridging_implement="furrower",
    )
    tractor = SharedTractorApp(env, equipment=equipment)
    drone = SharedDroneApp(env, name="SharedMavic")
    robot = SharedRobotApp(env, name="SharedRobot")
    env.sync()
    return SimpleNamespace(env=env, maize=maize, soybean=soybean, warehouse=warehouse,
                           tractor=tractor, drone=drone, robot=robot)


@pytest.fixture
def mixed():
    return make_mixed()


def mount(device, implement):
    if device.get_status()["attached_implement"] is not None:
        assert call(device, "detach_implement")["status"] == "ok"
    assert call(device, "attach_implement", implement=implement)["status"] == "ok"


def prepare(case):
    assert call(case.tractor, "load_fertilizer", kg=400)["status"] == "ok"
    for world in (case.maize, case.soybean):
        mount(case.tractor, "grader")
        assert call(case.tractor, "level", farm_id=world.farm_id)["status"] == "ok"
        assert call(case.tractor, "base_fertilize", farm_id=world.farm_id)["status"] == "ok"
        mount(case.tractor, "furrower")
        assert call(case.tractor, "form_ridges", farm_id=world.farm_id,
                    ridge_width_m=world.ridge_width_m)["status"] == "ok"


def plant_one(case, world, seed, spacing):
    mount(case.tractor, world.crop_definition.planting_rules.required_implement)
    count = world.plants_per_ridge_from_spacing(spacing)
    assert call(case.tractor, "load_seeds", seed_type=seed, count=count)["status"] == "ok"
    result = call(case.tractor, "plant_seeds", farm_id=world.farm_id,
                  start_ridge=0, end_ridge=0, depth_cm=4, seed_spacing_cm=spacing)
    assert result["status"] == "ok", result
    return result


def state(case):
    return deepcopy((case.env.time_manager.time(), case.tractor.get_state(),
                     case.warehouse.get_state(), case.maize.get_state(), case.soybean.get_state()))


def mature_native_fixture(case, world):
    """Set native maturity only for a boundary fixture, not an oracle action."""
    physics = world.physics
    phen, canopy, grain = (engine.states[0] for engine in (
        physics.phenology, physics.canopy, physics.yield_recovery))
    today = world.simulation_date()
    phen.stage = type(phen.stage)(world.crop_definition.harvest_rules.stage_codes[-1])
    phen.emerged, phen.maturity_date = True, today
    canopy.initialized, canopy.yield_potential_g_m2 = True, 300.0
    canopy.aboveground_biomass_g_m2 = 600.0
    grain.maturity_date, grain.grain_moisture_frac = today, .15
    grain.biological_yield_g_m2, grain.last_daily_update_day = 300.0, today
    if world.crop_id == "maize":
        grain.r6_reached = True
    else:
        grain.r8_reached = True
    physics.crop.sync_public_fields(world)


def test_mixed_crop_clock_schema_and_named_field_metadata(mixed):
    assert str(mixed.env.simulation_timezone) == "Asia/Shanghai"
    assert mixed.maize.time_manager is mixed.soybean.time_manager is mixed.warehouse.time_manager
    assert mixed.maize.simulation_date().isoformat() == mixed.soybean.simulation_date().isoformat() == "2026-05-15"
    _, schemas, tools = build_toolset([mixed.maize, mixed.soybean, mixed.warehouse,
                                      mixed.tractor, mixed.drone, mixed.robot])
    assert "MaizeField__get_crop_capabilities" in tools
    assert "SoybeanField__get_crop_capabilities" in tools
    functions = {schema["function"]["name"]: schema["function"] for schema in schemas}
    planting = functions["Tractor__plant_seeds"]
    assert planting["parameters"]["properties"]["farm_id"]["enum"] == ["maize_field", "soybean_field"]
    assert "maize_planter" in planting["description"] and "soybean_planter" in planting["description"]
    assert "farm_id" not in functions["Tractor__load_seeds"]["parameters"]["properties"]
    assert mixed.maize.get_ridge_state(0)["crop_id"] == "maize"
    assert mixed.soybean.get_ridge_state(0)["crop_id"] == "soybean"
    assert mixed.maize.crop_capabilities()["postharvest"]["market_moisture_pct"] == 14
    assert mixed.soybean.crop_capabilities()["postharvest"]["market_moisture_pct"] == 13


def test_shared_hopper_switch_returns_residue_without_mixing_or_charging_fields(mixed):
    stock = deepcopy(mixed.warehouse.stock.seed_stock)
    now = mixed.env.time_manager.time()
    assert call(mixed.tractor, "load_seeds", seed_type=MAIZE_SEED, count=100)["status"] == "ok"
    before = state(mixed)
    assert "error" in call(mixed.tractor, "load_seeds", seed_type=SOYBEAN_SEED, count=100)
    assert state(mixed) == before
    returned = call(mixed.tractor, "return_supplies")
    assert returned["returned"]["seed_type"] == MAIZE_SEED
    assert mixed.warehouse.stock.seed_stock == stock
    assert mixed.tractor.get_status()["seed_type"] is None
    assert call(mixed.tractor, "load_seeds", seed_type=SOYBEAN_SEED, count=100)["status"] == "ok"
    assert mixed.tractor.get_status()["seed_type"] == SOYBEAN_SEED
    assert mixed.env.time_manager.time() == now
    assert mixed.maize._management_regime.fertilizer_used_kg == mixed.soybean._management_regime.fertilizer_used_kg == 0


def test_wrong_crop_seed_and_wrong_planter_are_rejected_before_any_effect(mixed):
    prepare(mixed)
    count = mixed.maize.plants_per_ridge_from_spacing(25)
    assert call(mixed.tractor, "load_seeds", seed_type=MAIZE_SEED, count=count)["status"] == "ok"
    before = state(mixed)
    refused = call(mixed.tractor, "plant_seeds", farm_id="soybean_field",
                   start_ridge=0, end_ridge=0, depth_cm=4, seed_spacing_cm=25)
    assert "not permitted" in refused["error"]
    assert state(mixed) == before
    mount(mixed.tractor, "soybean_planter")
    before = state(mixed)
    refused = call(mixed.tractor, "plant_seeds", farm_id="maize_field",
                   start_ridge=0, end_ridge=0, depth_cm=4, seed_spacing_cm=25)
    assert "maize_planter" in refused["error"]
    assert state(mixed) == before
    mount(mixed.tractor, "maize_planter")
    assert call(mixed.tractor, "plant_seeds", farm_id="maize_field",
                start_ridge=0, end_ridge=0, depth_cm=4, seed_spacing_cm=25)["status"] == "ok"
    assert mixed.maize.get_ridge_state(0)["seed_type"] == MAIZE_SEED
    assert mixed.soybean.get_ridge_state(0)["planted"] is False
    assert mixed.tractor.get_status()["seed_hopper"] == 0
    plant_one(mixed, mixed.soybean, SOYBEAN_SEED, 5)
    assert mixed.soybean.get_ridge_state(0)["seed_type"] == SOYBEAN_SEED
    assert mixed.maize.get_ridge_state(0)["seed_type"] == MAIZE_SEED


def test_mature_mixed_grain_requires_right_header_and_unloading_before_switch(mixed):
    prepare(mixed)
    plant_one(mixed, mixed.maize, MAIZE_SEED, 25)
    plant_one(mixed, mixed.soybean, SOYBEAN_SEED, 5)
    for world in (mixed.maize, mixed.soybean):
        mature_native_fixture(mixed, world)
    for world, wrong in ((mixed.maize, "harvester"), (mixed.soybean, "maize_header")):
        mount(mixed.tractor, wrong)
        before = state(mixed)
        refused = call(mixed.tractor, "harvest", farm_id=world.farm_id, start_ridge=0, end_ridge=0)
        assert "requires attached implement" in refused["error"]
        assert state(mixed) == before
    mount(mixed.tractor, "maize_header")
    maize_grain = call(mixed.tractor, "harvest", farm_id="maize_field", start_ridge=0, end_ridge=0)
    assert maize_grain["grain_kg_added"] > 0
    before = state(mixed)
    assert "contains grain from" in call(mixed.tractor, "harvest", farm_id="soybean_field", start_ridge=0, end_ridge=0)["error"]
    assert state(mixed) == before
    first = call(mixed.tractor, "unload_grain", batch_id="maize-bin")
    assert first["batch"]["crop_id"] == "maize" and first["batch"]["cultivar_id"] == MAIZE_SEED
    mount(mixed.tractor, "harvester")
    soy_grain = call(mixed.tractor, "harvest", farm_id="soybean_field", start_ridge=0, end_ridge=0)
    assert soy_grain["grain_kg_added"] > 0
    second = call(mixed.tractor, "unload_grain", batch_id="soy-bin")
    assert second["batch"]["crop_id"] == "soybean" and second["batch"]["cultivar_id"] == SOYBEAN_SEED
    assert first["batch"]["origin_farm_id"] == "maize_field"
    assert second["batch"]["origin_farm_id"] == "soybean_field"
    assert mixed.maize.physics.yield_recovery.params.market_moisture_frac == .14
    assert mixed.soybean.physics.yield_recovery.params.market_moisture_frac == .13
    assert mixed.warehouse.get_inventory()["harvest_grain_kg"] == pytest.approx(
        maize_grain["grain_kg_added"] + soy_grain["grain_kg_added"])


def test_default_warehouse_limit_keeps_crop_specific_storage_limits(mixed):
    # Prospective batch fixtures exercise admission separately from crop growth.
    for batch, world, cultivar in (("maize-14", mixed.maize, MAIZE_SEED),
                                   ("soy-14", mixed.soybean, SOYBEAN_SEED)):
        mixed.warehouse.receive_grain(batch, world.farm_id, 100, [0], [14.0], [cultivar])
    assert call(mixed.warehouse, "store_grain", batch_id="maize-14")["status"] == "ok"
    before = deepcopy(mixed.warehouse.get_state())
    assert "safe moisture" in call(mixed.warehouse, "store_grain", batch_id="soy-14")["error"]
    assert mixed.warehouse.get_state() == before
    assert "exceeds storage limit 13.5" in call(mixed.warehouse, "dry_grain", batch_id="soy-14", target_moisture_pct=14)["error"]
    assert call(mixed.warehouse, "dry_grain", batch_id="soy-14", target_moisture_pct=13)["status"] == "ok"
    assert call(mixed.warehouse, "store_grain", batch_id="soy-14")["warehouse_grain_kg"] == 200
    assert mixed.warehouse.grain_batches["maize-14"].moisture_pct == 14
    assert mixed.warehouse.grain_batches["soy-14"].moisture_pct == 13


def test_shared_observation_assets_route_products_and_keep_one_battery(mixed):
    maize_counter = mixed.maize.physics.observation_model._product_counter
    soy_counter = mixed.soybean.physics.observation_model._product_counter
    first = call(mixed.drone, "fly_survey", farm_id="maize_field", start_ridge=0, end_ridge=1)
    assert first["status"] == "ok" and first["farm_id"] == "maize_field"
    assert mixed.soybean.physics.observation_model._product_counter == soy_counter
    assert mixed.maize.physics.observation_model._product_counter > maize_counter
    second = call(mixed.drone, "fly_survey", farm_id="soybean_field", start_ridge=0, end_ridge=1)
    assert second["battery_remaining_pct"] == first["battery_remaining_pct"] - 2
    maize_counter = mixed.maize.physics.observation_model._product_counter
    result = call(mixed.robot, "inspect_emergence", farm_id="soybean_field", start_ridge=0, end_ridge=1)
    assert result["farm_id"] == "soybean_field" and set(result["observations"]) == {0, 1}
    assert mixed.maize.physics.observation_model._product_counter == maize_counter
    assert all(item["stand_fraction"] == 0 for item in result["observations"].values())
    maize_diagnosis = call(mixed.robot, "inspect_ridge", farm_id="maize_field", ridge_id=0)["result"]
    assert maize_diagnosis["pest_type"] is None and maize_diagnosis["disease_type"] is None
    assert "generic" in maize_diagnosis["diagnostic_scope"]
    assert mixed.maize.physics.last_physics_sim_time == mixed.soybean.physics.last_physics_sim_time == mixed.env.time_manager.time()


def test_scene_local_implement_rules_survive_same_configuration_restore(mixed):
    prepare(mixed)
    saved = mixed.soybean.get_state()
    fresh = make_mixed()
    fresh.env.time_manager.set_offset(mixed.env.time_manager.offset)
    fresh.soybean.load_state(saved)
    rules = fresh.soybean.get_crop_capabilities()
    assert rules["planting"]["required_implement"] == "soybean_planter"
    assert rules["harvest"]["required_implement"] == "harvester"
    assert "soybean_planter" in next(tool for tool in fresh.tractor.get_tools() if tool.name == "plant_seeds").function_description


@pytest.mark.parametrize("device_class,method", [(DroneApp, "fly_survey"), (RobotApp, "inspect_emergence")])
@pytest.mark.parametrize("has_environment", [True, False])
def test_single_field_mobile_wrapper_resolves_registered_identity_and_clock(device_class, method, has_environment):
    weather = WeatherApp()
    weather.set_weather("2026-05-15", 20, 50, 1, 0, 350)
    world = FarmWorldApp(name="VisibleFieldName", farm_id="registered_field",
                         **({"crop_id": "maize", "cultivar_id": MAIZE_SEED} if has_environment else {}))
    device = device_class(world, weather)
    device_clock = SimulationTimeManager()
    device_clock.reset(START)
    device.register_time_manager(device_clock)
    if has_environment:
        environment = FarmEnvironment([FarmContext("registered_field", world, weather)], weather,
                                      start_time=START, timezone_name="Asia/Shanghai")
        environment.sync()
        clock = environment.time_manager
        product_counter = world.physics.observation_model._product_counter
    else:
        # Preserve the original no-environment wrapper, including name identity.
        world.register_time_manager(device_clock)
        weather.register_time_manager(device_clock)
        clock = device_clock
    before = clock.time()
    device_before = device_clock.time()
    result = call(device, method, start_ridge=0, end_ridge=0)
    assert result["status"] == "ok"
    assert result["farm_id"] == ("registered_field" if has_environment else "VisibleFieldName")
    assert clock.time() > before
    if has_environment:
        assert device._bound_farm() is environment.get_farm("registered_field")
        assert device_clock.time() == device_before
        assert world.physics.last_physics_sim_time == clock.time()
        assert world.physics.observation_model._product_counter > product_counter
    else:
        assert world.farm_environment is None
