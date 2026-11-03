"""Real-product units, conserved costs, refusals, retained directions and opt-in scope."""

import json
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from fairy.physics.biotic_pressure_engine import BioticPressureEngine
from fairy.scenarios.management_extensions.apps.crop_protection_app import (
    CropProtection,
    CropProtectionTractor,
)
from fairy.scenarios.management_extensions.L3.scenario_soybean_high_water_price import (
    ScenarioSoybeanHighWaterPrice,
)
from fairy.scenarios.management_extensions.L3.scenario_soybean_pesticide_choice import (
    ScenarioSoybeanPesticideChoice,
)
from fairy.time_manager import SimulationTimeManager


@pytest.fixture
def protection():
    catalog = json.loads(
        (
            Path(__file__).parents[1]
            / "fairy/scenarios/management_extensions/data/soybean_aphid_products/catalog.json"
        ).read_text()
    )
    clock = SimulationTimeManager()
    clock.reset(datetime(2019, 7, 2, 7, tzinfo=timezone.utc).timestamp())
    pending = []
    farm = SimpleNamespace(
        num_ridges=4,
        field_area_m2=800.0,
        ridge_area_m2=200.0,
        crop_id="soybean",
        _ridges=[
            SimpleNamespace(planted=True, harvested=False, growth_stage="R1")
            for _ in range(4)
        ],
        advance_physics_time=lambda: None,
        simulation_date=lambda timestamp: datetime.fromtimestamp(
            timestamp, timezone.utc
        ).date(),
        physics=SimpleNamespace(
            queue_treatment=lambda rid, treatment: pending.append((rid, treatment)),
            biotic=BioticPressureEngine(num_ridges=4),
        ),
        farm_environment=SimpleNamespace(advance_time=clock.add_offset),
    )
    tool = CropProtection(
        farm, SimpleNamespace(is_sprayable=True), catalog, purchase_cash=100.0
    )
    tool.register_time_manager(clock)
    return tool, pending


def buy(tool, key="transform_wg", factor=1.0):
    p = tool.products[key]
    quantity = p["min_rate_per_ha"] * tool.farm.field_area_m2 / 10000 * factor
    receipt = tool.purchase(key, quantity, f"buy-{key}")
    return p, quantity, receipt


def apply(tool, key="transform_wg", application_id="first"):
    return tool.apply(key, 0, 3, tool.products[key]["min_rate_per_ha"], application_id)


def test_uses_actual_area_and_keeps_g_separate_from_ml(protection):
    tool, _ = protection
    rows = tool.get_products()["products"]
    assert [r["unit"] for r in rows] == ["g", "mL"]
    for r in rows:
        assert r["minimum_full_field_quantity"] == pytest.approx(
            r["min_rate_per_ha"] * 0.08
        )
    assert (
        rows[0]["minimum_full_field_product_cost_usd"]
        < rows[1]["minimum_full_field_product_cost_usd"]
    )
    assert json.loads(json.dumps(tool.get_products())) == tool.get_products()


def test_purchase_and_application_idempotency_and_unused_asset_cost(protection):
    tool, pending = protection
    p, quantity, receipt = buy(tool, factor=2.0)
    cash = tool.cash
    assert tool.purchase("transform_wg", quantity, "buy-transform_wg") == receipt
    assert tool.cash == cash
    first = apply(tool)
    before = deepcopy(tool.get_state())
    assert apply(tool) == first
    assert tool.get_state() == before and len(pending) == 4
    account = tool.compute_accounts()
    assert account["consumed_product_cost"] == pytest.approx(
        quantity / 2 * tool.quotes["price_per_unit"]["transform_wg"]
    )
    assert account["unused_inventory_book_value"] == pytest.approx(
        account["consumed_product_cost"]
    )
    assert account["service_cost"] == pytest.approx(
        0.08 * tool.quotes["service_cost_per_ha"]
    )
    assert account["stock"]["transform_wg"] == pytest.approx(quantity / 2)
    assert first["product_quantity"] == pytest.approx(p["min_rate_per_ha"] * 0.08)


@pytest.mark.parametrize("bad_rate", [0, -1, float("nan"), float("inf"), 9999])
def test_invalid_rate_refuses_before_stock_cash_or_treatments_change(
    protection, bad_rate
):
    tool, pending = protection
    buy(tool)
    before = deepcopy(tool.get_state())
    with pytest.raises(ValueError, match="Rate"):
        tool.apply("transform_wg", 0, 3, bad_rate, "bad")
    assert tool.get_state() == before and pending == []


def test_unplanted_rain_and_empty_stock_refuse_without_charging(protection):
    tool, pending = protection
    buy(tool)
    for refusal in ("unplanted", "rain", "stock"):
        tool.farm._ridges[0].planted = refusal != "unplanted"
        tool.weather.is_sprayable = refusal != "rain"
        if refusal == "stock":
            tool.stock["transform_wg"] = 0
        before = deepcopy(tool.get_state())
        with pytest.raises(ValueError):
            apply(tool)
        assert tool.get_state() == before and pending == []


def test_repeat_interval_and_product_switch_cannot_stack_same_day(protection):
    tool, _ = protection
    buy(tool, factor=4.0)
    buy(tool, "sefina")
    apply(tool)
    before = deepcopy(tool.get_state())
    with pytest.raises(ValueError, match="seven days"):
        apply(tool, "sefina", "switch-too-soon")
    tool.time_manager.add_offset(7 * 86400)
    with pytest.raises(ValueError, match="minimum application interval"):
        apply(tool, application_id="repeat-too-soon")
    assert tool.get_state() == before
    tool.time_manager.add_offset(7 * 86400)
    apply(tool, application_id="allowed-repeat")
    assert len(tool.applications) == 2


def test_preharvest_interval_checked_by_scene_tractor(protection):
    tool, _ = protection
    buy(tool)
    apply(tool)
    tractor = CropProtectionTractor.__new__(CropProtectionTractor)
    tractor.protection = tool
    response = tractor._operate_harvest(SimpleNamespace(world=tool.farm), 0, 3)
    assert "preharvest interval" in response["error"]
    tool.time_manager.add_offset(7 * 86400)
    assert tool.harvest_restriction(range(4)) is None


def test_json_checkpoint_preserves_costs_stock_and_rejects_unbalanced_restore(
    protection,
):
    tool, _ = protection
    buy(tool, factor=2.0)
    apply(tool)
    state = json.loads(json.dumps(tool.get_state()))
    expected = deepcopy(tool.compute_accounts())
    clone = CropProtection(tool.farm, tool.weather, tool.catalog, purchase_cash=100.0)
    clone.register_time_manager(tool.time_manager)
    clone.load_state(state)
    assert clone.compute_accounts() == expected
    state["cash"] += 1
    before = deepcopy(clone.get_state())
    with pytest.raises(ValueError, match="cash balance"):
        clone.load_state(state)
    assert clone.get_state() == before


def test_new_scene_official_crop_and_outbreak_opt_in_leave_old_scene_unchanged():
    new = ScenarioSoybeanPesticideChoice(calibrating=True)
    new.setup()
    old = ScenarioSoybeanHighWaterPrice(calibrating=True)
    old.setup()
    assert new.farms[0].physics.crop_backend.config.external_biotic_coupling is True
    assert old.farms[0].physics.crop_backend.config.external_biotic_coupling is False
    config = new.farms[0].physics.crop_backend.config
    assert config.variety_name == "Soybean_901"
    assert not config.cultivar_profile and not config.parameter_overrides
    event = new.farms[0].physics.scenario_metadata["wofost_scenario_events"]["events"][
        0
    ]
    assert event["start"] == date(2019, 7, 1).isoformat()
    assert event["repeat"] == "once" and event["mode"] == "add"
    assert "wofost_scenario_events" not in old.farms[0].physics.scenario_metadata
    assert old.input_fingerprint() == old.ORACLE_REFERENCE["input_fingerprint"]


def test_consecutive_product_limit_requires_actual_rotation(protection):
    tool, _ = protection
    buy(tool, factor=4.0)
    buy(tool, "sefina")
    apply(tool)
    tool.time_manager.add_offset(14 * 86400)
    apply(tool, application_id="second")
    tool.time_manager.add_offset(14 * 86400)
    before = deepcopy(tool.get_state())
    with pytest.raises(ValueError, match="consecutive-application"):
        apply(tool, application_id="third-forbidden")
    assert tool.get_state() == before
    apply(tool, "sefina", "rotate")
    tool.time_manager.add_offset(14 * 86400)
    apply(tool, application_id="third-after-rotation")
    assert len(tool.applications) == 4


def test_sorted_json_keys_do_not_reorder_product_rotation_history(protection):
    tool, _ = protection
    buy(tool, factor=4.0)
    buy(tool, "sefina")
    apply(tool, application_id="z-first")
    tool.time_manager.add_offset(7 * 86400)
    apply(tool, "sefina", "a-second")
    tool.time_manager.add_offset(7 * 86400)
    apply(tool, application_id="m-third")
    state = json.loads(json.dumps(tool.get_state(), sort_keys=True))
    clone = CropProtection(tool.farm, tool.weather, tool.catalog, purchase_cash=100.0)
    clone.register_time_manager(tool.time_manager)
    clone.load_state(state)
    clone.time_manager.add_offset(14 * 86400)
    apply(clone, application_id="fourth")
    assert len(clone.applications) == 4


def test_checkpoint_rejects_a_different_product_price_or_label(protection):
    tool, _ = protection
    state = tool.get_state()
    changed = deepcopy(tool.catalog)
    changed["simulation_assumptions"]["price_per_unit"]["transform_wg"] += 0.01
    clone = CropProtection(tool.farm, tool.weather, changed, purchase_cash=100.0)
    with pytest.raises(ValueError, match="another product catalogue"):
        clone.load_state(state)
