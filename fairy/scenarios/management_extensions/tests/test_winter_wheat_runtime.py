"""Real native block independence, existing device constraints and restoration."""

from dataclasses import replace
from datetime import datetime
import json
import pytest
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.management_extensions.apps.winter_wheat_accounts_app import SEED
from fairy.scenarios.management_extensions.engines.winter_wheat_wofost import (
    InputBundle,
    WinterWheatBackend,
)
from fairy.scenarios.management_extensions.winter_wheat_oracles import DEFAULT_INPUTS


def field(blocks=2):
    scene = get_scenario_class("scenario_l3_winter_wheat_full_season")(calibrating=True)
    scene.resources = replace(scene.resources, block_count=blocks)
    scene.setup()
    Engine(None, scene)
    return scene


def sow_one(s, i=0):
    if "level" not in s.farm.completed_prep_ops:
        s.tractor.attach_implement("grader")
        assert "error" not in s.tractor.prepare_field()
    if s.farm.simulation_date().isoformat() < "2019-10-15":
        s.system.advance_time(days=14)
    if s.tractor._attached_implement != "seeder":
        s.tractor.detach_implement()
        s.tractor.attach_implement("seeder")
    assert "error" not in s.tractor.load_seeds(SEED, s.resources.seeds_per_block)
    assert "error" not in s.tractor.sow(i, i)


def test_real_block_inputs_are_independent_and_units_balance():
    s = field()
    sow_one(s)
    sow_one(s, 1)
    s.tractor.load_fertilizer(2.0)
    assert "error" not in s.tractor.fertilize(0, 0, 2.0)
    assert "error" not in s.irrigation.irrigate(1, 1, 10.0)
    s.system.advance_time(days=1)
    a, b = s.farm.backends
    assert a.values["NAVAIL"] > b.values["NAVAIL"]
    assert b.values["SM"] > a.values["SM"]
    receipts = [
        [r for r in x.receipts.values() if r["kind"] == "fertilize"] for x in (a, b)
    ]
    assert receipts[0][0]["amount"] == pytest.approx(2 * 0.46 / 0.0625)
    assert receipts[1] == []
    ledger = s.accounts.compute_accounts()
    assert ledger["fertilizer_product_kg"] == pytest.approx(2.0)
    assert ledger["water_m3"] == pytest.approx(10 * 625 / 1000)
    assert ledger["consumed_seeds"][SEED] == 2 * s.resources.seeds_per_block
    assert sum(ledger["cost_components"].values()) == ledger["production_cost"]
    assert ledger["fuel_liters"] > 0


@pytest.mark.parametrize(
    "start,end,dose", [(0, 2, 2.0), (-1, 0, 2.0), (0, 0, -1.0), (0, 0, float("nan"))]
)
def test_rejected_fertilizer_does_not_consume_or_queue(start, end, dose):
    s = field()
    before = s.farm.get_state(), s.warehouse.get_state(), s.tractor.get_state()
    assert "error" in s.tractor.fertilize(start, end, dose)
    assert (
        s.farm.get_state(),
        s.warehouse.get_state(),
        s.tractor.get_state(),
    ) == before


def test_original_hopper_loading_and_recovery_after_refusal():
    s = field()
    s.farm.completed_prep_ops.append("level")
    s.system.advance_time(days=14)
    s.tractor.detach_implement()
    s.tractor.attach_implement("seeder")
    assert "error" in s.tractor.sow(0, 0)
    assert not s.farm._ridges[0].planted
    s.tractor.load_seeds(SEED, 1000000)
    assert s.tractor._seed_hopper == 300000  # Unmodified shared hopper capacity.
    assert "error" not in s.tractor.sow(0, 0)
    assert s.tractor._seed_hopper == 50000
    assert not s.farm._ridges[1].planted


def test_pending_inputs_and_machine_inventory_survive_json_checkpoint():
    s = field()
    sow_one(s)
    s.tractor.load_fertilizer(2.0)
    s.tractor.fertilize(0, 0, 2.0)
    saved = {app.name: json.loads(json.dumps(app.get_state())) for app in s.apps}
    epoch = s.farm_environment.time_manager.time()
    other = field()
    other.farm_environment.time_manager.reset(epoch)
    for app in other.apps:
        app.load_state(saved[app.name])
    assert other.farm.get_state() == s.farm.get_state()
    assert other.tractor.get_state() == s.tractor.get_state()
    s.system.advance_time(days=1)
    other.system.advance_time(days=1)
    assert other.farm.get_state() == s.farm.get_state()
    assert other.accounts.compute_accounts() == s.accounts.compute_accounts()


def test_native_calendar_keeps_winter_and_leap_day_without_week_limit():
    s = field(1)
    sow_one(s)
    target = datetime(2020, 3, 1, 7, tzinfo=s.simulation_timezone).timestamp()
    s.system.advance_time(seconds=target - s.farm_environment.time_manager.time())
    b = s.farm.backends[0]
    dates = [j["day"] for j in b.journal]
    assert dates.count("2020-02-29") == 1 and dates.count("2020-01-01") == 1
    assert b.next_day.isoformat() == "2020-03-01" and b.sown
    assert b.parameters["IDSL"] == 2
    assert b.values["VERN"] is not None


def test_native_same_day_water_n_are_aggregated_before_one_daily_signal():
    bundle = InputBundle(DEFAULT_INPUTS)
    a, b = WinterWheatBackend(bundle), WinterWheatBackend(bundle)
    for backend in (a, b):
        while backend.next_day.isoformat() < "2019-10-15":
            backend.advance_day()
        backend.queue("sow", "sow")
    a.queue("n1", "fertilize", 10)
    a.queue("n2", "fertilize", 20)
    a.queue("w1", "irrigate", 5)
    a.queue("w2", "irrigate", 10)
    b.queue("n", "fertilize", 30)
    b.queue("w", "irrigate", 15)
    a.advance_day()
    b.advance_day()
    assert a.values == b.values


def test_immature_harvest_refuses_before_fuel_time_or_grain_change():
    s = field()
    sow_one(s)
    s.tractor.detach_implement()
    s.tractor.attach_implement("harvester")
    before = (
        s.farm.get_state(),
        s.tractor.get_state(),
        s.farm_environment.time_manager.time(),
    )
    assert "error" in s.tractor.harvest_blocks(0, 0)
    assert (
        s.farm.get_state(),
        s.tractor.get_state(),
        s.farm_environment.time_manager.time(),
    ) == before


def test_batched_adjacent_blocks_use_real_working_width_and_queue_after_completion():
    from fairy.apps.farm_world.tractor_operations import _fuel_per_pass

    s = field()
    sow_one(s)
    sow_one(s, 1)
    s.tractor.load_fertilizer(2.0)
    # Start 3 min before midnight. A 2-block spreader job takes 3 paths,
    # so the input belongs to the following date, not the first path's date.
    target = datetime(2019, 10, 15, 23, 57, tzinfo=s.simulation_timezone).timestamp()
    s.system.advance_time(seconds=target - s.farm_environment.time_manager.time())
    before = s.tractor._fuel_tank_l
    assert "error" not in s.tractor.fertilize(0, 1, 1.0)
    assert before - s.tractor._fuel_tank_l == pytest.approx(3 * _fuel_per_pass(s.farm))
    for backend in s.farm.backends:
        pending = [a for a in backend.pending if a["kind"] == "fertilize"]
        assert len(pending) == 1 and pending[0]["day"] == "2019-10-16"
        assert not any(
            a["kind"] == "fertilize" for d in backend.journal for a in d["actions"]
        )


def test_block_inspection_is_compact_and_rejects_out_of_bounds():
    s = field()
    result = s.farm.inspect_blocks(0, 1)
    assert len(result["blocks"]) == 2
    assert {r["block_id"] for r in result["blocks"]} == {0, 1}
    assert result["units"]["NAVAIL"] == "kg N/ha"
    assert "values" not in result["blocks"][0]
    assert "error" in s.farm.inspect_blocks(0, 2)


def test_input_delivered_after_maturity_still_enters_native_soil_once():
    from fairy.scenarios.management_extensions.winter_wheat_oracles import DEFAULT_PLANS

    plan = DEFAULT_PLANS["full_season"]
    b = WinterWheatBackend(InputBundle(DEFAULT_INPUTS))
    actions = {plan["sowing_date"]: [("sow", 0)]}
    for key, dates, kind in (
        ("nitrogen_kg_ha", "nitrogen_dates", "fertilize"),
        ("irrigation_mm", "water_dates", "irrigate"),
    ):
        for day, amount in zip(plan[dates], plan[key]):
            actions.setdefault(day, []).append((kind, amount))
    while b.maturity is None:
        for kind, amount in actions.get(b.next_day.isoformat(), []):
            b.queue(f"a_{len(b.receipts)}", kind, amount)
        b.advance_day()
    grain = b.values["TWSO"]
    day = b.next_day.isoformat()
    b.queue("in_flight_delivery", "fertilize", 10.0)
    b.advance_day()
    assert b.failed is None and b.values["TWSO"] == grain
    assert b.journal[-1]["day"] == day
    assert b.journal[-1]["actions"][0]["id"] == "in_flight_delivery"
