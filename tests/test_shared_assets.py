from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from fairy.apps.farm_world.assets import AssetSpec, AssetState
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.operations import (
    DroneOperations, OperationContext, RobotOperations, TractorOperations,
    invoke_operation, operation_view,
)
from fairy.apps.farm_world.tractor_app import TractorApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.time_manager import TimeManager


def _world(crop="soybean", count=2):
    clock = TimeManager()
    clock.reset(datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp())
    farms, weather = {}, {}
    for name in ("north", "south"):
        farms[name] = FarmWorldApp(farm_id=name, crop_type=crop, num_ridges=count, field_length_m=80)
        farms[name].register_time_manager(clock)
        weather[name] = WeatherApp()
        weather[name].register_time_manager(clock)
        weather[name].set_weather("2026-05-01", 25, 55, 2, 0, 15)
    return farms, weather, clock


def _ctx(farms, weather, clock, asset, target):
    return OperationContext(farms[target] if target else None,
                            weather[target] if target else None, asset, clock)


def test_one_drone_keeps_battery_and_logs_across_farms_without_rebinding():
    farms, weather, clock = _world()
    asset = AssetState(AssetSpec("drone_1", "drone", ("north", "south")))
    north, south = (_ctx(farms, weather, clock, asset, name) for name in farms)
    north_view = operation_view(north)
    assert invoke_operation(north, "fly_survey", {"start_ridge": 0, "end_ridge": 0})["status"] == "ok"
    first_battery = asset.data["_battery_pct"]
    assert invoke_operation(south, "fly_survey", {"start_ridge": 1, "end_ridge": 1})["status"] == "ok"
    assert asset.data["_battery_pct"] < first_battery < 100
    assert north_view._farm_world_app is farms["north"]
    assert [entry["farm_id"] for entry in asset.data["_mission_log"]] == ["north", "south"]
    assert {entry["asset_id"] for entry in asset.data["_mission_log"]} == {"drone_1"}
    with pytest.raises(AttributeError, match="rebound"):
        north_view._farm_world_app = farms["south"]
    other = AssetState(AssetSpec("drone_2", "drone", ("north", "south")))
    assert other.data["_battery_pct"] == 100


def test_seed_origin_blocks_cross_farm_then_exactly_once_return_unlocks_it():
    farms, weather, clock = _world()
    asset = AssetState(AssetSpec("tractor_1", "tractor", ("north", "south")))
    north, south = (_ctx(farms, weather, clock, asset, name) for name in farms)
    initial = farms["north"].get_inventory()["seed_stock"]["STANDARD"]
    assert invoke_operation(north, "load_seeds", {"seed_type": "STANDARD", "count": 100})["status"] == "ok"
    assert asset.payload_origin_farm_id == "north"
    offset_before = clock.offset
    south_before = farms["south"].get_inventory()
    result = invoke_operation(south, "plant_seeds", {"start_ridge": 0, "end_ridge": 0,
                                                   "depth_cm": 4, "seed_spacing_cm": 8})
    assert result["error_code"] == "payload_origin_mismatch"
    assert clock.offset == offset_before
    assert farms["south"].get_inventory() == south_before
    assert invoke_operation(north, "return_supplies")["returned"]["seeds"] == 100
    assert farms["north"].get_inventory()["seed_stock"]["STANDARD"] == initial
    assert asset.payload_origin_farm_id is None
    assert invoke_operation(north, "return_supplies")["returned"] == {}
    assert farms["north"].get_inventory()["seed_stock"]["STANDARD"] == initial
    assert invoke_operation(south, "load_seeds", {"seed_type": "STANDARD", "count": 20})["status"] == "ok"
    assert asset.payload_origin_farm_id == "south"


def test_return_fertilizer_and_both_chemical_compartments_preserves_stock_and_quota():
    farms, weather, clock = _world()
    asset = AssetState(AssetSpec("tractor_1", "tractor", ("north", "south")))
    ctx = _ctx(farms, weather, clock, asset, "north")
    initial = farms["north"].get_inventory()
    for method, args in (("load_fertilizer", {"kg": 12}),
                         ("load_pesticide", {"liters": 5}),
                         ("load_fungicide", {"liters": 3})):
        assert invoke_operation(ctx, method, args)["status"] == "ok"
    result = invoke_operation(ctx, "return_supplies")
    assert result["returned"]["fertilizer_kg"] == 12
    assert result["returned"]["pesticide_liters"] == 5
    assert result["returned"]["fungicide_liters"] == 3
    final = farms["north"].get_inventory()
    assert final["fertilizer_kg"] == initial["fertilizer_kg"]
    assert final["pesticide_liters"] == initial["pesticide_liters"]
    assert final["management_regime"] == initial["management_regime"]


def test_only_applied_fertilizer_charges_quota_and_return_does_not_refund_it():
    farms, weather, clock = _world()
    farm = farms["north"]
    farm.configure_management_regime(fertilizer_quota_kg=5)
    asset = AssetState(AssetSpec("tractor_1", "tractor", ("north", "south")))
    ctx = _ctx(farms, weather, clock, asset, "north")
    assert invoke_operation(ctx, "load_fertilizer", {"kg": 12})["status"] == "ok"
    assert farm._management_regime.fertilizer_used_kg == 0
    assert invoke_operation(ctx, "apply_fertilizer", {"start_ridge": 0, "end_ridge": 0,
                                                    "kg_per_ridge": 3})["status"] == "ok"
    assert farm._management_regime.fertilizer_used_kg == 3
    offset = clock.offset
    assert "error" in invoke_operation(ctx, "apply_fertilizer", {"start_ridge": 1, "end_ridge": 1,
                                                               "kg_per_ridge": 3})
    assert clock.offset == offset
    assert asset.data["_fertilizer_spreader_kg"] == 9
    assert invoke_operation(ctx, "return_supplies")["returned"]["fertilizer_kg"] == 9
    assert farm._management_regime.fertilizer_used_kg == 3


def test_preparation_stays_on_land_and_is_visible_to_another_machine():
    farms, weather, clock = _world()
    asset = AssetState(AssetSpec("tractor_1", "tractor", ("north", "south")))
    north, south = (_ctx(farms, weather, clock, asset, name) for name in farms)
    assert invoke_operation(north, "attach_implement", {"implement": "grader"})["status"] == "ok"
    assert invoke_operation(north, "level")["status"] == "ok"
    assert "level" in operation_view(north)._completed_prep_ops
    assert operation_view(south)._completed_prep_ops == []
    other = AssetState(AssetSpec("tractor_2", "tractor", ("north",)))
    assert "level" in operation_view(_ctx(farms, weather, clock, other, "north"))._completed_prep_ops
    legacy = TractorApp(farms["north"], weather["north"])
    assert "level" in legacy._completed_prep_ops
    legacy.reset()
    assert "level" in legacy._completed_prep_ops


def _mature(farm):
    for ridge in farm._ridges:
        ridge.planted = True
        ridge.seed_type = farm.crop_profile.seed_type
        ridge.growth_stage = farm.crop_profile.mature_stage
        ridge.grain_moisture_pct = 14 if farm.crop_type == "soybean" else 22


def test_two_combines_keep_separate_source_batches_until_their_own_unload():
    farms, weather, clock = _world()
    farm = farms["north"]
    _mature(farm)
    assets = [AssetState(AssetSpec(f"tractor_{i}", "tractor", ("north", "south"))) for i in (1, 2)]
    contexts = [_ctx(farms, weather, clock, asset, "north") for asset in assets]
    for ridge, ctx in enumerate(contexts):
        assert invoke_operation(ctx, "harvest", {"start_ridge": ridge, "end_ridge": ridge})["status"] == "ok"
    assert assets[0].grain_lots[0]["ridge_ids"] == [0]
    assert assets[1].grain_lots[0]["ridge_ids"] == [1]
    assert farm._pending_bin_grain_ridge_ids == []
    wrong = _ctx(farms, weather, clock, assets[0], "south")
    assert invoke_operation(wrong, "unload_grain")["error_code"] == "payload_origin_mismatch"
    first_kg = assets[0].data["_grain_bin_kg"]
    second_kg = assets[1].data["_grain_bin_kg"]
    assert invoke_operation(contexts[0], "unload_grain")["status"] == "ok"
    assert farm._trailer_grain_ridge_ids == [0]
    assert farm._inventory.harvest_grain_kg == pytest.approx(first_kg)
    assert assets[1].grain_lots[0]["ridge_ids"] == [1]
    assert invoke_operation(contexts[1], "unload_grain")["status"] == "ok"
    assert farm._trailer_grain_ridge_ids == [0, 1]
    assert farm._inventory.harvest_grain_kg == pytest.approx(first_kg + second_kg)
    assert all(not asset.grain_lots and asset.payload_origin_farm_id is None for asset in assets)


def test_crop_harvest_limit_is_resolved_from_explicit_target_not_first_farm():
    farms, weather, clock = _world()
    farms["south"] = FarmWorldApp(farm_id="south", crop_type="maize", num_ridges=2, field_length_m=80)
    farms["south"].register_time_manager(clock)
    _mature(farms["south"])
    asset = AssetState(AssetSpec("tractor_1", "tractor", ("north", "south")))
    assert operation_view(_ctx(farms, weather, clock, asset, "north"))._harvest_moisture_limit_pct == 18
    assert operation_view(_ctx(farms, weather, clock, asset, "south"))._harvest_moisture_limit_pct == 25
    assert invoke_operation(_ctx(farms, weather, clock, asset, "south"), "harvest",
                            {"start_ridge": 0, "end_ridge": 0})["status"] == "ok"


def test_snapshot_restores_one_asset_payload_and_rng_and_invalid_load_is_atomic():
    farms, weather, clock = _world()
    spec = AssetSpec("tractor_1", "tractor", ("north", "south"))
    asset = AssetState(spec, seed=123)
    assert invoke_operation(_ctx(farms, weather, clock, asset, "north"), "load_seeds",
                            {"seed_type": "STANDARD", "count": 30})["status"] == "ok"
    snapshot = json.loads(json.dumps(asset.snapshot()))
    expected_random = asset.rng.random()
    restored = AssetState(spec)
    restored.load_snapshot(snapshot)
    assert restored.data["_seed_hopper"] == 30
    assert restored.payload_origin_farm_id == "north"
    assert restored.rng.random() == expected_random
    before = restored.snapshot()
    bad = deepcopy(snapshot)
    bad["payload_origin_farm_id"] = "missing"
    with pytest.raises(ValueError, match="origin"):
        restored.load_snapshot(bad)
    assert restored.snapshot() == before


def test_asset_only_charge_and_restore_keep_remaining_charge_time():
    farms, weather, clock = _world()
    spec = AssetSpec("robot_1", "robot", ("north", "south"), initial_state={"battery_pct": 20})
    asset = AssetState(spec)
    ctx = _ctx(farms, weather, clock, asset, None)
    assert "error" not in invoke_operation(ctx, "charge")
    clock.add_offset(1800)
    status = invoke_operation(ctx, "check_status")
    snapshot = json.loads(json.dumps(asset.snapshot()))
    other = AssetState(spec)
    other.load_snapshot(snapshot)
    restored = invoke_operation(_ctx(farms, weather, clock, other, None), "check_status")
    assert restored["battery_pct"] == status["battery_pct"]
    assert restored["eta_minutes_to_full"] == pytest.approx(status["eta_minutes_to_full"], abs=.01)
    assert 20 < status["battery_pct"] < 100


@pytest.mark.parametrize("initial", [
    {"seed_hopper": 3, "seed_type": "STANDARD"},
    {"grain_bin_kg": 10, "payload_origin_farm_id": "north"},
    {"battery_pct": float("nan")},
])
def test_invalid_initial_assets_are_rejected(initial):
    kind = "drone" if "battery_pct" in initial else "tractor"
    with pytest.raises(ValueError):
        AssetState(AssetSpec("asset_1", kind, ("north", "south"), initial_state=initial))


def test_asset_capabilities_reject_unknown_target_before_mutation():
    farms, weather, clock = _world()
    asset = AssetState(AssetSpec("tractor_1", "tractor", ("north",)))
    before = asset.snapshot()
    assert invoke_operation(_ctx(farms, weather, clock, asset, "south"), "load_fertilizer",
                            {"kg": 10})["error_code"] == "asset_farm_not_allowed"
    assert asset.snapshot() == before


def test_operation_handles_do_not_initialize_or_copy_legacy_equipment(monkeypatch):
    """Creating another target handle must leave the physical asset untouched."""
    from fairy.apps.farm_world.drone_app import DroneApp
    from fairy.apps.farm_world.robot_app import RobotApp

    farms, weather, clock = _world()

    def forbidden_constructor(*args, **kwargs):
        raise AssertionError("A compatibility handle initialized another machine")

    for app in (TractorApp, DroneApp, RobotApp):
        monkeypatch.setattr(app, "__init__", forbidden_constructor)
    for kind, expected_class in (("tractor", TractorOperations),
                                 ("drone", DroneOperations),
                                 ("robot", RobotOperations)):
        asset = AssetState(AssetSpec(f"{kind}_1", kind, ("north", "south")))
        before = asset.snapshot()
        north = operation_view(_ctx(farms, weather, clock, asset, "north"))
        south = operation_view(_ctx(farms, weather, clock, asset, "south"))
        assert type(north) is expected_class
        assert type(south) is expected_class
        assert north._shared_asset_state is south._shared_asset_state is asset
        assert north.rng is south.rng is asset.rng
        assert asset.snapshot() == before


def test_direct_compatibility_handle_keeps_payload_gate_and_single_asset_state():
    farms, weather, clock = _world()
    asset = AssetState(AssetSpec("tractor_1", "tractor", ("north", "south"),
                                initial_state={"fuel_tank_l": 40}))
    north = operation_view(_ctx(farms, weather, clock, asset, "north"))
    south = operation_view(_ctx(farms, weather, clock, asset, "south"))
    assert north.refuel(5)["status"] == "ok"
    assert south.get_status()["fuel_tank_l"] == north.get_status()["fuel_tank_l"] == 45
    assert north.load_seeds("STANDARD", 30)["status"] == "ok"
    before_asset, before_inventory = asset.snapshot(), farms["south"].get_inventory()
    before_offset = clock.offset
    result = south.load_seeds("STANDARD", 10)
    assert result["error_code"] == "payload_origin_mismatch"
    assert asset.snapshot() == before_asset
    assert farms["south"].get_inventory() == before_inventory
    assert clock.offset == before_offset
    # Loading invoked once, through the explicit method and provenance gate.
    assert north.get_status()["seed_hopper"] == south.get_status()["seed_hopper"] == 30


@pytest.mark.parametrize("kind,method,args", [
    ("tractor", "load_seeds", {"seed_type": "STANDARD", "count": 10}),
    ("drone", "fly_survey", {"start_ridge": 0, "end_ridge": 0}),
    ("robot", "inspect_ridge", {"ridge_id": 0}),
])
def test_internal_operation_handles_cannot_be_captured(kind, method, args):
    from fairy.types import EventRegisterer

    farms, weather, clock = _world()
    asset = AssetState(AssetSpec(f"{kind}_1", kind, ("north", "south")))
    handle = operation_view(_ctx(farms, weather, clock, asset, "north"))
    before_asset, before_inventory = asset.snapshot(), farms["north"].get_inventory()
    before_offset = clock.offset
    with EventRegisterer.capture_mode() as events:
        with pytest.raises(RuntimeError, match="shared public service"):
            getattr(handle, method)(**args)
    assert events == []
    assert asset.snapshot() == before_asset
    assert farms["north"].get_inventory() == before_inventory
    assert clock.offset == before_offset


def test_compatibility_handle_rejects_all_dependency_rebinding():
    farms, weather, clock = _world()
    asset = AssetState(AssetSpec("drone_1", "drone", ("north", "south")))
    handle = operation_view(_ctx(farms, weather, clock, asset, "north"))
    for field, replacement in (("_farm_world_app", farms["south"]),
                               ("_weather_app", weather["south"]),
                               ("time_manager", TimeManager()),
                               ("name", "another_drone")):
        with pytest.raises(AttributeError, match="rebound"):
            setattr(handle, field, replacement)
    with pytest.raises(AttributeError):
        handle._operation_context = _ctx(farms, weather, clock, asset, "south")
    assert handle.farm_id == "north"
    assert handle.asset_id == "drone_1"
    assert handle.time_manager is clock


@pytest.mark.parametrize("kind", ["tractor", "drone", "robot"])
def test_internal_equipment_handles_cannot_publish_a_second_tool_catalog(kind):
    farms, weather, clock = _world()
    asset = AssetState(AssetSpec(f"{kind}_1", kind, ("north", "south")))
    handle = operation_view(_ctx(farms, weather, clock, asset, "north"))
    with pytest.raises(ValueError, match="shared public services from fleet.apps"):
        handle.get_tools()

