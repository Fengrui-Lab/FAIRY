"""Behavioral checks for local balances, refusal atomicity and objective choice."""

from copy import deepcopy
import re

import pytest

from fairy.controllers.engine import Engine
from fairy.scenarios.management_extensions.L3.scenario_joint_maize_soybean_operating_margin import (
    ScenarioJointCropOperatingMargin,
)
from fairy.scenarios.management_extensions.management_oracles import choose


def create():
    s = ScenarioJointCropOperatingMargin(calibrating=True)
    s.setup()
    Engine(None, s)
    return s


def test_loading_inputs_is_not_consumption_and_accounts_are_pure():
    s = create()
    before = s.accounts.compute_accounts()
    s.tractor.load_seeds(seed_type="MAIZE_201", count=100)
    s.tractor.load_fertilizer(kg=10.0)
    state = (
        deepcopy(s.warehouse.get_state()),
        deepcopy(s.tractor.get_state()),
        s.farm_environment.time_manager.time(),
    )
    after = s.accounts.compute_accounts()
    assert before["production_cost"] == after["production_cost"] == 0
    assert after["consumed_seeds"]["MAIZE_201"] == 0
    assert after["fertilizer_product_kg"] == 0
    assert state == (
        s.warehouse.get_state(),
        s.tractor.get_state(),
        s.farm_environment.time_manager.time(),
    )


def test_shared_water_rejection_is_atomic_and_other_field_is_counted():
    s = create()
    before = (deepcopy(s.farms[0].get_state()), s.farm_environment.time_manager.time())
    # 16 ridges x 201m2 x 300mm = 964.8m3, exceeding the common 900m3 supply.
    result = s.irrigation["maize"]._start_irrigation(list(range(16)), 60.0)
    assert "error" in result and "Shared" in result["error"]
    assert before == (s.farms[0].get_state(), s.farm_environment.time_manager.time())
    s.farms[1]._management_regime.irrigation_used_mm_total = 180.0
    result = s.irrigation["maize"]._start_irrigation(list(range(16)), 10.0)
    assert "error" in result and "Shared" in result["error"]


def test_empty_episode_is_infeasible_even_with_zero_cost():
    s = create()
    result = s.validate()
    assert not result.success
    assert result.metadata["production_cost"] == 0
    assert result.metadata["feasible"] is False


def test_profit_selection_differs_from_gross_revenue_and_keeps_pareto():
    common = {"feasible": True, "fertilizer_product_kg": 10.0, "trace": []}
    expensive = {
        **common,
        "candidate": [1],
        "stored_kg_by_crop": {"maize": 100.0, "soybean": 100.0},
        "stored_grain_value": 100.0,
        "production_cost": 90.0,
        "net_operating_margin": 10.0,
        "water_m3": 100.0,
    }
    economical = {
        **common,
        "candidate": [2],
        "stored_kg_by_crop": {"maize": 90.0, "soybean": 90.0},
        "stored_grain_value": 90.0,
        "production_cost": 50.0,
        "net_operating_margin": 40.0,
        "water_m3": 50.0,
    }
    reference, selected = choose([expensive, economical, {"feasible": False}])
    assert selected is economical
    assert reference["maximum_joint_grain_value"]["candidate"] == [1]
    assert len(reference["pareto"]) == 2
    assert reference["candidate_count"] == 3 and reference["feasible_count"] == 2
    with pytest.raises(RuntimeError):
        choose([{"feasible": False}])


def test_briefings_preserve_explicit_task_and_reject_invalid_flag():
    explicit = ScenarioJointCropOperatingMargin(
        calibrating=True,
        scenario_input="User task",
        additional_system_prompt="System instruction",
    )
    explicit.setup()
    assert explicit.scenario_input == "User task"
    assert explicit.additional_system_prompt == "System instruction"
    compact = ScenarioJointCropOperatingMargin(
        calibrating=True, detailed_briefing=False
    )
    compact.setup()
    detailed = ScenarioJointCropOperatingMargin(
        calibrating=True, detailed_briefing=True
    )
    detailed.setup()
    assert len(compact.scenario_input) < len(detailed.scenario_input)
    for scene in (compact, detailed):
        assert set(re.findall(r"\d+(?:\.\d+)?", scene.scenario_input)) == {
            "3216",
            "0.75",
            "4716.8",
            "1.1",
        }
        assert "OperatingAccounts.get_accounts" in scene.scenario_input
    assert "read_soil_sensors" not in compact.scenario_input
    assert "read_soil_sensors" in detailed.scenario_input
    assert "read_canopy_sensors" in detailed.scenario_input
    assert "不能仅凭低 NDVI 就判断缺肥" in detailed.scenario_input
    with pytest.raises(ValueError, match="JSON boolean"):
        ScenarioJointCropOperatingMargin(detailed_briefing="false")


def test_reference_rejects_changed_economic_inputs():
    from dataclasses import replace

    scene = create()
    original = scene.input_fingerprint()
    scene.prices = replace(scene.prices, water_per_m3=0.21)
    assert scene.input_fingerprint() != original
    scene.calibrating = False
    with pytest.raises(ValueError, match="physical/economic inputs"):
        scene.build_events_flow()


def test_initial_inventory_fingerprint_is_stable_during_loading():
    scene = create()
    fingerprint = scene.input_fingerprint()
    scene.tractor.load_fertilizer(kg=10.0)
    assert scene.input_fingerprint() == fingerprint
    scene.warehouse._initial_stock.fertilizer_kg += 1
    assert scene.input_fingerprint() != fingerprint


def test_drying_uses_actual_throughput_and_repeated_safe_requests_are_free():
    from fairy.apps.farm_world.warehouse_app import GrainBatch

    scene = create()
    warehouse = scene.warehouse
    # Isolate the real postharvest tool with a pending, wet grain fixture.
    warehouse.grain_batches["wet-maize"] = GrainBatch(
        batch_id="wet-maize",
        origin_farm_id="maize",
        crop_id="maize",
        cultivar_id="MAIZE_201",
        cultivar_ids=["MAIZE_201"],
        ridge_ids=[0],
        quantity_kg=100.0,
        moisture_pct=20.0,
    )
    assert scene.accounts.compute_accounts()["cost_components"]["drying"] == 0
    rejected = warehouse.dry_grain(batch_id="wet-maize", target_moisture_pct=15.0)
    assert "error" in rejected
    assert scene.accounts.compute_accounts()["drying_throughput_kg"] == 0
    first = warehouse.dry_grain(batch_id="wet-maize", target_moisture_pct=14.0)
    assert first["status"] == "ok" and not first.get("drying_skipped")
    charged = scene.accounts.compute_accounts()
    assert charged["drying_throughput_kg"] == 100.0
    assert charged["cost_components"]["drying"] == pytest.approx(100 * 0.04 / 7.1757)
    repeated = warehouse.dry_grain(batch_id="wet-maize", target_moisture_pct=13.0)
    assert repeated["drying_skipped"] is True
    assert scene.accounts.compute_accounts() == charged
    assert warehouse.grain_batches["wet-maize"].moisture_pct == 14.0
