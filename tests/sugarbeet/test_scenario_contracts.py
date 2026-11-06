"""SCENARIO auditor: physical product accounting, rotation chronology and overlay."""

from copy import deepcopy
from dataclasses import replace
from datetime import date
import ast
import pytest


def test_l4_chronology(C, wheat, beet):
    calendar = C.Calendar(wheat.prepare_open, beet.harvest_close, (wheat, beet))
    assert calendar.cycles == (wheat, beet)
    assert (beet.prepare_open - wheat.harvest_close).days > 180


def test_overlapping_crops_rejected(C, wheat, beet):
    b = replace(beet, prepare_open=wheat.harvest_open)
    with pytest.raises(ValueError):
        C.Calendar(wheat.prepare_open, beet.harvest_close, (wheat, b))


def test_wrong_crop_sequence_rejected(C, wheat, beet):
    with pytest.raises(ValueError):
        C.Calendar(wheat.prepare_open, beet.harvest_close, (beet, wheat))


def ledger(C, **kwargs):
    return C.RootLedger(C.RootContract(**kwargs), date(2021, 9, 25), date(2021, 11, 3))


def test_dry_fresh_net_gross_do_not_double_tare(C):
    ledger_state = ledger(C)
    b = ledger_state.add("b", "beet", 0, date(2021, 10, 1), 1000)
    assert b["recovered_net_kg"] == 4750
    r = ledger_state.deliver("t", "b", 4750, date(2021, 10, 1))
    assert r["net_kg"] == 4750 and r["gross_kg"] == pytest.approx(4750 / 0.92)
    assert r["revenue_usd"] == pytest.approx(237.5)
    assert r["tare_kg"] + r["net_kg"] == r["gross_kg"]


def test_delivery_retry_is_free(C):
    ledger_state = ledger(C)
    ledger_state.add("b", "beet", 0, date(2021, 10, 1), 1000)
    a = ledger_state.deliver("t", "b", 1000, date(2021, 10, 1))
    assert ledger_state.deliver("t", "b", 1000, date(2021, 11, 20)) == a
    assert (
        len(ledger_state.transactions) == 1
        and ledger_state.totals()["delivered_net_kg"] == 1000
    )
    with pytest.raises(ValueError):
        ledger_state.deliver("t", "b", 1001, date(2021, 10, 1))


def test_oversell_rejected(C):
    ledger_state = ledger(C)
    ledger_state.add("b", "beet", 0, date(2021, 10, 1), 1000)
    with pytest.raises(ValueError):
        ledger_state.deliver("t", "b", 5000, date(2021, 10, 1))
    assert not ledger_state.transactions


@pytest.mark.parametrize(
    "day", [date(2021, 9, 30), date(2021, 10, 5), date(2021, 11, 4)]
)
def test_holding_or_window_invalid(C, day):
    ledger_state = ledger(C)
    ledger_state.add("b", "beet", 0, date(2021, 10, 1), 1000)
    with pytest.raises(ValueError):
        ledger_state.deliver("t", "b", 1000, day)


def test_capacity_uses_gross_not_net(C):
    ledger_state = ledger(C, truck_gross_capacity_kg=1000)
    ledger_state.add("b", "beet", 0, date(2021, 10, 1), 1000)
    with pytest.raises(ValueError):
        ledger_state.deliver("t", "b", 950, date(2021, 10, 1))
    ledger_state.deliver("t", "b", 920, date(2021, 10, 1))


def test_daily_receiving_capacity(C):
    ledger_state = ledger(C, delivery_daily_gross_kg=2000)
    ledger_state.add("b", "beet", 0, date(2021, 10, 1), 1000)
    ledger_state.deliver("a", "b", 1000, date(2021, 10, 1))
    with pytest.raises(ValueError):
        ledger_state.deliver("b", "b", 1000, date(2021, 10, 1))
    ledger_state.deliver("b", "b", 1000, date(2021, 10, 2))


def test_ledger_checkpoint_replays_and_rejects_forgery(C):
    ledger_state = ledger(C)
    ledger_state.add("b", "beet", 0, date(2021, 10, 1), 1000)
    ledger_state.deliver("t", "b", 1000, date(2021, 10, 1))
    saved = ledger_state.export()
    other = ledger(C)
    other.load(saved)
    assert saved == other.export()
    bad = deepcopy(saved)
    bad["batches"][0]["recovered_net_kg"] += 1
    with pytest.raises(ValueError):
        other.load(bad)
    assert other.export() == saved


@pytest.mark.parametrize(
    "kwargs",
    [
        {"dry_matter_fraction": 0},
        {"sucrose_fraction_fresh": 0.3},
        {"machine_recovery": 2},
        {"maximum_holding_days": -1},
    ],
)
def test_quality_contract_bounds(C, kwargs):
    with pytest.raises(ValueError):
        C.RootContract(**kwargs)


def test_active_sugarbeet_scenarios():
    from fairy.scenarios.registry import list_scenarios
    from scripts.sugarbeet_oracle import SCENARIOS

    active_ids = {name for name in list_scenarios() if "sugarbeet" in name}
    assert active_ids == {
        "scenario_l3_sugarbeet_full_season",
        "scenario_l3_sugarbeet_water_limit",
        "scenario_l3_sugarbeet_nitrogen_limit",
        "scenario_l3_sugarbeet_high_water_price",
        "scenario_l4_wheat_sugarbeet_rotation",
        "scenario_l3_sugarbeet_seedling_rescue",
        "scenario_l3_sugarbeet_soil_water_priority",
        "scenario_l4_wheat_sugarbeet_shared_resources",
    }
    assert set(SCENARIOS) == {
        "full_season",
        "water_limit",
        "nitrogen_limit",
        "high_water_price",
        "rotation",
        "seedling_rescue",
        "soil_water_priority",
        "shared_resources",
    }


def test_reuse_and_rotation_source_boundaries():
    from conftest import EXT

    scenario = ast.parse((EXT / "sugarbeet/scenario.py").read_text())
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "initialize_wheat_farm"
        for node in ast.walk(scenario)
    )
    backend = (EXT / "engines/sugarbeet_wofost.py").read_text()
    tree = ast.parse(backend)
    cls = next(
        n
        for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "SugarBeetBackend"
    )
    transition = next(
        n
        for n in cls.body
        if isinstance(n, ast.FunctionDef) and n.name == "begin_next_cycle"
    )
    assert not any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "__init__"
        for n in ast.walk(transition)
    )
    assert not any(
        isinstance(node, ast.Attribute)
        and node.attr == "soil"
        and isinstance(node.ctx, ast.Store)
        for node in ast.walk(transition)
    )
