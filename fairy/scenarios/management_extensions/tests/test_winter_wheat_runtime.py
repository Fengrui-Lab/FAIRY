"""Real PCSE inputs, daily management, units, recovery and native grain mass."""

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.management_extensions.apps.winter_wheat_app import (
    WheatResources,
    WinterWheatRuntime,
    WinterWheatApp,
)
from fairy.scenarios.management_extensions.engines.winter_wheat_wofost import (
    InputBundle,
    WinterWheatBackend,
)

INPUTS = Path(__file__).resolve().parents[1] / "data/winter_wheat_ncp_2019_2020"


def world(resources=None):
    return WinterWheatApp(
        WinterWheatRuntime(
            WinterWheatBackend(InputBundle(INPUTS)), resources or WheatResources()
        )
    )


def sow(app):
    app.prepare_field("prepare")
    app.wait(9)
    app.sow("sow")


def test_same_day_inputs_sum_once_in_native_model_but_service_costs_follow_real_calls():
    separate, combined = world(), world()
    for app in (separate, combined):
        sow(app)
    separate.apply_nitrogen("n1", 25)
    separate.apply_nitrogen("n2", 35)
    separate.irrigate("w1", 20)
    separate.irrigate("w2", 30)
    combined.apply_nitrogen("n", 60)
    combined.irrigate("w", 50)
    for app in (separate, combined):
        app.wait(1)
    a, b = separate.runtime, combined.runtime
    assert a.backend.values == b.backend.values
    assert a.backend.values["TOTIRR"] == pytest.approx(50 / 10 * a.backend.efficiency)
    assert a.resources.fertilizer_stock_kg - a.inventory[
        "fertilizer_product_kg"
    ] == pytest.approx(60 / 0.46)
    assert a.resources.water_stock_m3 - a.inventory["water_m3"] == pytest.approx(500)
    extra = a.resources.fertilize_pass_usd_ha + a.resources.irrigate_pass_usd_ha
    assert a.cost_usd - b.cost_usd == pytest.approx(extra)


@pytest.mark.parametrize("dose", [-1, float("nan"), float("inf"), True])
def test_invalid_dose_has_no_resource_cost_or_native_queue_side_effect(dose):
    app = world()
    sow(app)
    before = app.get_state()
    with pytest.raises(ValueError):
        app.apply_nitrogen("invalid", dose)
    assert app.get_state() == before


def test_failed_calls_and_retries_are_transactional():
    app = world(replace(WheatResources(), water_stock_m3=0))
    before = app.get_state()
    with pytest.raises(ValueError):
        app.harvest("early")
    assert app.get_state() == before
    sow(app)
    before = app.get_state()
    with pytest.raises(ValueError):
        app.irrigate("dry", 10)
    assert app.get_state() == before
    receipt = app.apply_nitrogen("n", 20)
    after = app.get_state()
    assert app.apply_nitrogen("n", 20) == receipt
    assert app.get_state() == after
    with pytest.raises(ValueError):
        app.apply_nitrogen("n", 21)
    assert app.get_state() == after


def test_new_year_and_leap_day_do_not_reset_the_crop_or_duplicate_days():
    app = world()
    sow(app)
    app.wait(
        143
    )  # Longer waits are permitted; native daily integration remains continuous.
    runtime = app.runtime
    assert runtime.today == date(2020, 3, 1)
    days = [entry["day"] for entry in runtime.backend.journal]
    assert len(days) == len(set(days)) == (runtime.today - runtime.season.start).days
    assert "2020-01-01" in days and "2020-02-29" in days
    assert runtime.backend.values["DOE"].startswith("2019-")
    assert runtime.backend.values["ISVERNALISED"] is True
    assert runtime.backend.values["NfixTotal"] == 0
    assert runtime.observe()["previous_complete_day_weather"]["day"] == "2020-02-29"


def test_native_grain_is_converted_once_and_usd_components_balance():
    scene = get_scenario_class("scenario_l3_winter_wheat_full_season")()
    scene.setup()
    engine = Engine(None, scene)
    engine.run_scenario_oracle(run_oracle=True)
    m = engine.evaluate().metadata
    r = scene.world.runtime
    p = r.resources
    assert engine.evaluate().success
    assert m["dry_grain_kg"] == pytest.approx(m["native"]["values"]["TWSO"] * p.area_ha)
    assert m["stored_grain_kg"] * (1 - p.storage_moisture_fraction) == pytest.approx(
        m["dry_grain_kg"]
    )
    assert sum(m["cost_components"].values()) == pytest.approx(m["production_cost"])
    assert m["net_operating_margin"] == pytest.approx(
        m["stored_grain_value"] - m["production_cost"]
    )
    assert m["yield_loss_pct_by_crop"]["winter_wheat"] == pytest.approx(0)


def test_json_checkpoint_loaded_after_engine_binding_preserves_shared_clock():
    cls = get_scenario_class("scenario_l3_winter_wheat_full_season")
    control = cls()
    control.setup()
    a = Engine(None, control)
    sow(control.world)
    control.world.wait(100)
    saved = json.loads(json.dumps(control.world.get_state(), sort_keys=True))
    clone = cls()
    clone.setup()
    b = Engine(None, clone)
    clone.world.load_state(saved)
    assert a.time_manager.time() == b.time_manager.time()
    control.world.wait(45)
    clone.world.wait(45)
    assert control.world.get_state() == clone.world.get_state()


def test_area_scales_resource_amounts_but_not_native_per_hectare_dose():
    app = world(replace(WheatResources(), area_ha=2, seed_stock_kg=360))
    sow(app)
    app.apply_nitrogen("n", 30)
    app.irrigate("water", 20)
    p = app.runtime.resources
    assert p.seed_stock_kg - app.runtime.inventory["seed_kg"] == 360
    assert p.fertilizer_stock_kg - app.runtime.inventory[
        "fertilizer_product_kg"
    ] == pytest.approx(30 * 2 / 0.46)
    assert p.water_stock_m3 - app.runtime.inventory["water_m3"] == pytest.approx(
        20 * 2 * 10
    )
    assert (
        sum(
            r["amount"] for r in app.runtime.backend.pending if r["kind"] == "fertilize"
        )
        == 30
    )


def test_pending_sowing_and_nitrogen_survive_json_checkpoint_without_double_charging():
    cls = get_scenario_class("scenario_l3_winter_wheat_full_season")
    control = cls()
    control.setup()
    Engine(None, control)
    sow(control.world)
    control.world.apply_nitrogen("pending_n", 20)
    saved = json.loads(json.dumps(control.world.get_state(), sort_keys=True))
    clone = cls()
    clone.setup()
    Engine(None, clone)
    clone.world.load_state(saved)
    assert len(clone.world.runtime.backend.pending) == 2
    assert clone.world.get_state() == control.world.get_state()
    control.world.wait(1)
    clone.world.wait(1)
    assert clone.world.get_state() == control.world.get_state()
    runtime = clone.world.runtime
    assert runtime.resources.fertilizer_stock_kg - runtime.inventory[
        "fertilizer_product_kg"
    ] == pytest.approx(20 / 0.46)
    assert (
        sum(
            row["amount"]
            for row in runtime.backend.receipts.values()
            if row["kind"] == "fertilize"
        )
        == 20
    )


@pytest.mark.parametrize("control", ["zero_N", "zero_water"])
def test_four_application_zero_input_controls_keep_dates_and_execute_natively(control):
    from fairy.scenarios.management_extensions.winter_wheat_oracles import (
        low_input_controls,
        run_candidate,
    )

    parameters = {
        "sowing_date": "2019-10-15",
        "nitrogen_kg_ha": [60.0, 70.0, 60.0, 40.0],
        "nitrogen_dates": ["2019-10-15", "2020-02-27", "2020-04-02", "2020-04-20"],
        "irrigation_mm": [50.0] * 4,
        "water_dates": ["2020-04-02", "2020-04-20", "2020-05-05", "2020-05-20"],
    }
    candidate = low_input_controls(parameters)[control]
    assert candidate["nitrogen_dates"] == parameters["nitrogen_dates"]
    assert candidate["water_dates"] == parameters["water_dates"]
    assert len(candidate["nitrogen_kg_ha"]) == len(candidate["nitrogen_dates"]) == 4
    assert len(candidate["irrigation_mm"]) == len(candidate["water_dates"]) == 4
    row = run_candidate(candidate)
    assert row["feasible"], row.get("error")
    assert row["outcome"]["stored_grain_kg"] > 0
    metric = "nitrogen_applied_kg_ha" if control == "zero_N" else "water_used_m3"
    assert row["outcome"][metric] == 0
