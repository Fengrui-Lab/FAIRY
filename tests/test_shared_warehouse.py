"""One resource ledger serves every farm; grain retains batch provenance."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from fairy.agents.agent.toolset_builder import build_toolset
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.controllers.engine import Engine
from fairy.scenarios.scenario import Scenario


START = datetime(2026, 5, 12, tzinfo=timezone.utc).timestamp()


def make_environment(**facilities):
    weather = WeatherApp()
    weather.set_weather("2026-05-12", 20, 55, 1, 0, 250)
    farms = [FarmContext(key, FarmWorldApp(farm_id=key, name=key), weather)
             for key in ("farm_a", "farm_b")]
    warehouse = WarehouseApp(stock=WarehouseStock(
        seed_stock={"STANDARD": 100_000}, pesticide_liters=100.0,
        fertilizer_kg=500.0, fuel_liters=200.0,
    ), **facilities)
    return FarmEnvironment(farms, weather, start_time=START, warehouse=warehouse)


@pytest.fixture
def environment(monkeypatch):
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: START)
    return make_environment()


def receive(warehouse, batch_id, farm_id, kg=100.0, moisture=16.0):
    return warehouse.receive_grain(batch_id=batch_id, origin_farm_id=farm_id, kg=kg,
                                   ridge_ids=[0, 1], moistures_pct=[moisture, moisture])


def test_multi_farm_environment_requires_explicit_common_stock():
    weather = WeatherApp()
    farms = [FarmContext(key, FarmWorldApp(), weather) for key in ("a", "b")]
    with pytest.raises(ValueError, match="[Ww]arehouse"):
        FarmEnvironment(farms, weather, start_time=START)
    assert all(farm.world.farm_environment is None for farm in farms)


def test_global_stock_and_local_water_have_distinct_agent_tools(environment):
    warehouse = environment.warehouse
    a, b = (farm.world for farm in environment.farms.values())
    a.configure_management_regime(irrigation_quota_mm_total=15)
    b.configure_management_regime(irrigation_quota_mm_total=30)
    _, schemas, tools = build_toolset([warehouse, a, b])
    assert "Warehouse__get_inventory" in tools
    for key in ("farm_a", "farm_b"):
        assert f"{key}__get_management_status" in tools
        assert f"{key}__get_inventory" not in tools
        assert f"{key}__dry_grain" not in tools
        assert f"{key}__store_grain" not in tools
    inventory = warehouse.get_inventory()
    assert inventory["warehouse_id"] == "Warehouse"
    assert inventory["inventory_scope"] == "scene"
    assert "management_regime" not in inventory
    assert a._management_regime.irrigation_quota_mm_total == 15
    assert b._management_regime.irrigation_quota_mm_total == 30
    functions = {item["function"]["name"]: item["function"] for item in schemas}
    for method in ("dry_grain", "store_grain"):
        params = functions[f"Warehouse__{method}"]["parameters"]
        assert "batch_id" in params["required"]
        assert "farm_id" not in params["properties"]


@pytest.mark.parametrize("registrations", [0, 2])
def test_engine_requires_exactly_one_common_warehouse_registration(environment, registrations):
    scenario = Scenario(start_time=START, apps=[
        environment.weather, *(farm.world for farm in environment.farms.values()),
        *([environment.warehouse] * registrations),
    ])
    scenario.farm_environment = environment
    with pytest.raises(ValueError, match="[Ww]arehouse"):
        Engine(None, scenario)


def test_engine_outcome_reports_stock_once_and_keeps_field_management_local(environment):
    warehouse = environment.warehouse
    receive(warehouse, "a", "farm_a", kg=100, moisture=13)
    warehouse.store_grain("a")
    receive(warehouse, "b", "farm_b", kg=200, moisture=16)
    scenario = Scenario(start_time=START, apps=[
        environment.weather, *(farm.world for farm in environment.farms.values()), warehouse,
    ])
    scenario.farm_environment = environment
    scenario.shared_equipment = []
    outcome = Engine(None, scenario).outcome_summary()
    assert outcome["warehouse"] == {
        "inventory": warehouse.get_inventory(),
        "grain_batches": warehouse.get_grain_batches()["batches"],
    }
    assert set(outcome["farms"]) == {"farm_a", "farm_b"}
    for field in outcome["farms"].values():
        assert field["warehouse_id"] == warehouse.warehouse_id
        assert "management_status" in field
        assert "inventory" not in field


@pytest.mark.parametrize("method,field,amount", [
    ("consume_fuel", "fuel_liters", 200.0),
    ("consume_pesticide", "pesticide_liters", 100.0),
    ("consume_fertilizer", "fertilizer_kg", 500.0),
])
def test_common_resource_can_be_exhausted_only_once(environment, method, field, amount):
    warehouse = environment.warehouse
    consume = getattr(warehouse, method)
    assert consume(amount)
    assert getattr(warehouse.stock, field) == 0
    before = warehouse.get_state()
    assert not consume(0.001)
    assert warehouse.get_state() == before


@pytest.mark.parametrize("amount", [-1.0, 0.0, float("nan"), float("inf"), True])
def test_invalid_stock_withdrawal_is_atomic(environment, amount):
    warehouse = environment.warehouse
    before = warehouse.get_state()
    assert not warehouse.consume_pesticide(amount)
    assert warehouse.get_state() == before


def test_stock_and_seed_reads_are_copies_and_do_not_create_a_second_ledger(environment):
    warehouse = environment.warehouse
    view = warehouse.get_inventory()
    view["seed_stock"]["STANDARD"] = 0
    assert warehouse.consume_seeds("STANDARD", 100_000)
    assert not warehouse.consume_seeds("STANDARD", 1)
    assert warehouse.stock.seed_stock["STANDARD"] == 0
    for farm in environment.farms.values():
        with pytest.raises(RuntimeError, match="[Ww]arehouse"):
            _ = farm.world._inventory


def test_batches_preserve_farm_and_crop_and_dry_independently(environment):
    warehouse = environment.warehouse
    receive(warehouse, "a-1", "farm_a", kg=100, moisture=16)
    receive(warehouse, "b-1", "farm_b", kg=200, moisture=17)
    b_before = deepcopy(warehouse.grain_batches["b-1"])
    assert warehouse.get_inventory()["harvest_grain_kg"] == 300
    dried = warehouse.dry_grain("a-1", 13)
    assert dried["status"] == "ok"
    assert warehouse.grain_batches["a-1"].moisture_pct == 13
    assert warehouse.grain_batches["a-1"].dried
    assert warehouse.grain_batches["b-1"] == b_before
    batch = warehouse.get_grain_batches()["batches"][0]
    assert batch["origin_farm_id"] == "farm_a"
    assert batch["crop_id"] == "soybean"
    assert batch["cultivar_id"] == environment.get_farm("farm_a").world.cultivar_id
    assert batch["ridge_ids"] == [0, 1]
    assert warehouse.store_grain("a-1")["warehouse_grain_kg"] == 100
    inventory = warehouse.get_inventory()
    assert inventory["harvest_grain_kg"] == 200
    assert inventory["warehouse_grain_kg"] == 100
    assert "grain_dried" not in inventory
    assert warehouse.grain_batches["b-1"] == b_before
    warehouse.dry_grain("b-1", 13)
    assert warehouse.store_grain("b-1")["warehouse_grain_kg"] == 300
    before = warehouse.get_state()
    assert "error" in warehouse.store_grain("a-1")
    assert warehouse.get_state() == before


def test_wet_batch_cannot_be_stored_and_another_safe_batch_can(environment):
    warehouse = environment.warehouse
    warehouse.receive_grain("unsafe", "farm_a", 100, [0], [17.0])
    receive(warehouse, "safe", "farm_b", kg=200, moisture=13)
    before = warehouse.get_state()
    assert "error" in warehouse.store_grain("unsafe")
    assert warehouse.get_state() == before
    assert warehouse.store_grain("safe")["warehouse_grain_kg"] == 200
    assert warehouse.get_inventory()["harvest_grain_kg"] == 100


def test_storage_capacity_is_shared_across_origins(monkeypatch):
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: START)
    environment = make_environment(storage_capacity_kg=250)
    warehouse = environment.warehouse
    receive(warehouse, "a", "farm_a", kg=150, moisture=13)
    receive(warehouse, "b", "farm_b", kg=150, moisture=13)
    assert warehouse.store_grain("a")["status"] == "ok"
    before = warehouse.get_state()
    assert "error" in warehouse.store_grain("b")
    assert warehouse.get_state() == before


def test_drying_capacity_is_cumulative_and_shared_across_origins(monkeypatch):
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: START)
    environment = make_environment(drying_capacity_kg_per_day=150)
    warehouse = environment.warehouse
    receive(warehouse, "a", "farm_a", kg=100)
    receive(warehouse, "b", "farm_b", kg=100)
    assert warehouse.dry_grain("a")["status"] == "ok"
    warehouse.store_grain("a")
    before = warehouse.get_state()
    assert "error" in warehouse.dry_grain("b")
    assert warehouse.get_state() == before
    environment.advance_time(86400)
    assert warehouse.dry_grain("b")["status"] == "ok"


def test_one_warehouse_snapshot_roundtrips_without_loading_field_inventory(environment):
    warehouse = environment.warehouse
    warehouse.consume_fuel(20)
    receive(warehouse, "a", "farm_a", kg=100)
    warehouse.dry_grain("a")
    warehouse.store_grain("a")
    receive(warehouse, "b", "farm_b", kg=200)
    snapshot = json.loads(json.dumps(warehouse.get_state(), allow_nan=False))
    fields = {key: farm.world.get_state() for key, farm in environment.farms.items()}
    fresh = make_environment()
    for key, state in fields.items():
        assert "inventory" not in state
        assert {"pending_bin_grain_ridge_ids", "pending_bin_grain_moistures_pct",
                "trailer_grain_ridge_ids", "trailer_grain_moistures_pct"}.isdisjoint(state)
        assert state["warehouse_id"] == warehouse.warehouse_id
        assert state["resource_schema_version"] == 2
        fresh.get_farm(key).world.load_state(state)
    assert fresh.warehouse.stock.fuel_liters == 200
    fresh.warehouse.load_state(snapshot)
    assert fresh.warehouse.get_state() == snapshot
    assert fresh.warehouse.get_inventory()["warehouse_grain_kg"] == 100
    assert fresh.warehouse.get_inventory()["harvest_grain_kg"] == 200
    # A subsequent field restore must not refund stocks or duplicate grain.
    fresh.get_farm("farm_a").world.load_state(fields["farm_a"])
    assert fresh.warehouse.get_state() == snapshot


@pytest.mark.parametrize("corrupt", [
    "identity", "version", "stock", "duplicate_batch", "origin", "empty_ridges", "duplicate_ridges",
])
def test_bad_snapshot_is_rejected_before_any_warehouse_mutation(environment, corrupt):
    warehouse = environment.warehouse
    receive(warehouse, "a", "farm_a")
    before = warehouse.get_state()
    incoming = deepcopy(before)
    if corrupt == "identity":
        incoming["warehouse_id"] = "OtherWarehouse"
    elif corrupt == "version":
        incoming["resource_schema_version"] = 1
    elif corrupt == "stock":
        incoming["stock"]["fertilizer_kg"] = -1
    elif corrupt == "duplicate_batch":
        incoming["grain_batches"].append(deepcopy(incoming["grain_batches"][0]))
    elif corrupt == "origin":
        incoming["grain_batches"][0]["origin_farm_id"] = "unknown"
    elif corrupt == "empty_ridges":
        incoming["grain_batches"][0]["ridge_ids"] = []
    else:
        incoming["grain_batches"][0]["ridge_ids"] = [0, 0]
    with pytest.raises(ValueError):
        warehouse.load_state(incoming)
    assert warehouse.get_state() == before


@pytest.mark.parametrize("corrupt", ["warehouse", "legacy_inventory", "legacy_grain"])
def test_field_snapshot_cannot_replace_or_rebind_the_common_stock(environment, corrupt):
    warehouse = environment.warehouse
    world = environment.get_farm("farm_a").world
    before = world.get_state()
    stock_before = warehouse.get_state()
    incoming = deepcopy(before)
    incoming["completed_prep_ops"] = ["level"]
    if corrupt == "warehouse":
        incoming["warehouse_id"] = "OtherWarehouse"
    elif corrupt == "legacy_inventory":
        incoming["inventory"] = {"fuel_liters": 9999}
    else:
        incoming["pending_bin_grain_ridge_ids"] = [0]
    with pytest.raises(ValueError, match="warehouse"):
        world.load_state(incoming)
    assert world.get_state() == before
    assert warehouse.get_state() == stock_before


def test_field_reset_preserves_common_warehouse_and_warehouse_reset_happens_once(environment):
    warehouse = environment.warehouse
    warehouse.consume_fertilizer(100)
    receive(warehouse, "a", "farm_a")
    before = warehouse.get_state()
    environment.get_farm("farm_a").world.reset()
    assert warehouse.get_state() == before
    environment.get_farm("farm_b").world.reset()
    assert warehouse.get_state() == before
    warehouse.reset()
    assert warehouse.stock.fertilizer_kg == 500
    assert warehouse.get_inventory()["harvest_grain_kg"] == 0
    assert warehouse.get_inventory()["warehouse_grain_kg"] == 0
    assert warehouse.get_grain_batches()["batches"] == []
