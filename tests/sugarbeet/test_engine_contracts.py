"""ENGINE auditor: units, input timing and state continuity, not agronomic accuracy."""

from dataclasses import replace
from datetime import date, timedelta
import pytest


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True])
def test_bad_quantities(C, value):
    with pytest.raises(ValueError):
        C.finite(value, "dose")


@pytest.mark.parametrize("dose", [1, 25, 100])
def test_pure_n_cap(C, beet, dose):
    beet.check_nitrogen(beet.sowing_open, 0, dose)
    with pytest.raises(ValueError):
        beet.check_nitrogen(beet.sowing_open, 180, dose)


def test_dates_roundtrip(C, beet):
    assert C.CropCycle.from_dict(beet.to_dict()) == beet


def test_n_cutoff(beet):
    with pytest.raises(ValueError):
        beet.check_nitrogen(beet.nitrogen_close + timedelta(days=1), 0, 1)


def test_sowing_window(beet):
    with pytest.raises(ValueError):
        beet.check_sowing(beet.sowing_close + timedelta(days=1))


@pytest.mark.parametrize("gap", [0, 1, 19])
def test_withholding_rejected(beet, gap):
    with pytest.raises(ValueError):
        beet.check_harvest(beet.harvest_open, beet.harvest_open - timedelta(days=gap))


def test_withholding_boundary(beet):
    beet.check_harvest(beet.harvest_open, beet.harvest_open - timedelta(days=20))


def test_bad_depth(beet):
    with pytest.raises(ValueError):
        replace(beet, sowing_depth_cm=5)


def test_daily_aggregation_and_units(make_backend, beet):
    b = make_backend([beet])
    b.queue("s", "sow")
    b.queue("n1", "fertilize", 20)
    b.queue("n2", "fertilize", 30)
    b.queue("w1", "irrigate", 20)
    b.queue("w2", "irrigate", 15)
    b.advance_day()
    ns = [x for x in b.model.calls if x.get("signal") == "nitrogen"]
    ws = [x for x in b.model.calls if x.get("signal") == "water"]
    assert len(ns) == len(ws) == 1 and ns[0]["N_amount"] == 50
    assert ws[0]["amount"] == 3.5 and ws[0]["efficiency"] == 0.85
    assert b.n_by_cycle[beet.cycle_id] == 50 and not b.pending


def test_repeated_queue_id_no_double_dose(make_backend, beet):
    b = make_backend([beet])
    a = b.queue("n", "fertilize", 10)
    assert b.queue("n", "fertilize", 10) == a and len(b.pending) == 1
    with pytest.raises(ValueError):
        b.queue("n", "fertilize", 11)
    assert b.n_by_cycle[beet.cycle_id] == 10


def test_failed_input_does_not_book_n(make_backend, beet):
    b = make_backend([beet])
    b.queue("n", "fertilize", 180)
    with pytest.raises(ValueError):
        b.queue("n2", "fertilize", 1)
    assert len(b.receipts) == 1 and b.n_by_cycle[beet.cycle_id] == 180


def test_beet_dom_does_not_freeze(make_backend, beet):
    b = make_backend([beet])
    b.sown = True
    b.model.crop = object()
    b.model.values.update(DOM=beet.harvest_open, TWSO=123.0, DOE=beet.sowing_open)
    b.advance_day()
    assert b.maturity is None
    b.model.values["TWSO"] = 456.0
    b.advance_day()
    assert b.values["TWSO"] == 456.0  # supplied fixture, NOT a growth prediction


def test_wheat_dom_snapshot_is_preserved(make_backend, wheat):
    b = make_backend([wheat])
    b.sown = True
    b.model.values.update(DOM=wheat.harvest_open, TWSO=123.0)
    b.advance_day()
    b.model.values["TWSO"] = 456.0
    b.advance_day()
    assert b.maturity["TWSO"] == 123.0 and b.values["TWSO"] == 123.0


def test_crop_deletion_preserves_soil(make_backend, beet):
    b = make_backend([beet], beet.harvest_open)
    b.sown = True
    b.model.crop = object()
    b.model.values.update(DOE=beet.sowing_open, TWSO=2000.0)
    b.values = b._read()
    soil = b.model.soil
    before = b.model.values["SM"]
    first = b.harvest_now("h")
    assert (
        b.model.crop is None and b.model.soil is soil and b.model.values["SM"] == before
    )
    assert b.harvest_now("h") == first
    with pytest.raises(ValueError):
        b.harvest_now("h2")


def test_native_soil_replacement_detected(make_backend, beet):
    b = make_backend([beet])
    b.model.soil = object()
    with pytest.raises(RuntimeError):
        b.advance_day()


def test_native_failure_is_terminal(make_backend, beet):
    b = make_backend([beet])

    def broken(days):
        raise RuntimeError("deliberate protocol test")

    b.model.run = broken
    with pytest.raises(RuntimeError):
        b.advance_day()
    assert b.failed
    with pytest.raises(RuntimeError):
        b.queue("n", "fertilize", 2)


def test_same_soil_rotation_and_pending_guard(make_backend, wheat, beet):
    b = make_backend([wheat, beet], beet.prepare_open)
    b.harvests[wheat.cycle_id] = {"fixture": True}
    old = b.model.soil
    b.model.values.update(SM=0.174, NAVAIL=11.0)
    b.begin_next_cycle()
    assert (
        b.model.soil is old and b.cycle.crop == "sugarbeet" and b.values["SM"] == 0.174
    )
    assert b.rotation_audit[0]["before"] == b.rotation_audit[0]["after"]


def test_cannot_skip_previous_crop(make_backend, wheat, beet):
    b = make_backend([wheat, beet], beet.prepare_open)
    with pytest.raises(ValueError):
        b.begin_next_cycle()


def test_cannot_skip_fallow(make_backend, wheat, beet):
    b = make_backend([wheat, beet], wheat.harvest_close)
    b.harvests[wheat.cycle_id] = {}
    with pytest.raises(ValueError):
        b.begin_next_cycle()


@pytest.mark.parametrize(
    "unit,factor", [("MJ/m^2/day", 1.0), ("kW-hr/m^2/day", 3.6), ("kWh/m^2/day", 3.6)]
)
def test_weather_radiation_unit_conversion(unit, factor):
    from conftest import load, ROOT

    m = load("isolated_beet_prepare", ROOT / "scripts/prepare_sugarbeet_inputs.py")
    assert m.radiation_factor(unit) == factor


def test_unknown_radiation_unit_rejected():
    from conftest import load, ROOT

    m = load(
        "isolated_beet_prepare_badunit", ROOT / "scripts/prepare_sugarbeet_inputs.py"
    )
    with pytest.raises(ValueError):
        m.radiation_factor("unknown")


def test_download_calendar_covers_wheat_fallow_beet(C):
    from conftest import load, ROOT

    m = load(
        "isolated_beet_prepare_calendar", ROOT / "scripts/prepare_sugarbeet_inputs.py"
    )
    cycles = tuple(C.CropCycle.from_dict(x) for x in m.cycle_data(2021, True))
    assert cycles[0].sowing_open.year == 2019 and cycles[0].harvest_close.year == 2020
    assert cycles[1].sowing_open.year == cycles[1].harvest_close.year == 2021
    C.Calendar(cycles[0].prepare_open, date(2021, 11, 5), cycles)
