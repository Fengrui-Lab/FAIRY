"""Drying/transfer physical correctness and enhanced Jev receipt interpretation."""
import copy
from types import SimpleNamespace as NS

import pytest

from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.tractor_app import TractorApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.agents.jev.receipts import receipt_summary, grain_state
from test_two_farm_tractor import tractor_scene
from test_rice_toolset import checkpoint
from fairy.apps.paddy.operations import PaddyOpsApp
from fairy.apps.paddy.machinery import PaddyMachineryApp


def test_empty_drying_does_not_repair_stored_grain_or_change_state():
    w = FarmWorldApp()
    w._inventory.harvest_grain_kg = 0
    w._inventory.warehouse_grain_kg = 915.85
    w._inventory.grain_dried = False
    before = copy.deepcopy(w.get_state())
    result = w.dry_grain()
    assert result['code'] == 'no_pending_grain' and 'error' in result
    assert w.get_state() == before
    step = NS(op_type='TOOL', tool_name='FarmWorldApp__dry_grain', tool_args={}, content=result)
    assert receipt_summary(step)['status'] == 'failed'
    assert grain_state({'inventory': w._inventory.to_dict(), 'steps': [step]})['safe_current_batch'] is None


def test_nonempty_drying_and_already_safe_batch():
    w = FarmWorldApp()
    w._inventory.harvest_grain_kg = 100
    w._trailer_grain_moistures_pct = [20.]
    r = w.dry_grain()
    assert r['status'] == 'ok' and w._inventory.grain_dried
    assert w._trailer_grain_moistures_pct == [13.]
    r = w.dry_grain()
    assert r['drying_skipped'] and r['trailer_grain_kg'] == 100


@pytest.mark.parametrize('method,attribute,stock,capacity,unit', [
    ('refuel', '_fuel_tank_l', 'fuel_liters', 100., 'L'),
    ('load_fertilizer', '_fertilizer_spreader_kg', 'fertilizer_kg', 500., 'kg'),
    ('load_pesticide', '_pesticide_tank_l', 'pesticide_liters', 800., 'L'),
    ('refill_pesticide_tank', '_pesticide_tank_l', 'pesticide_liters', 800., 'L'),
    ('load_fungicide', '_fungicide_tank_l', 'pesticide_liters', 800., 'L'),
])
def test_local_transfer_reports_increment_and_conserves_stock(method, attribute, stock, capacity, unit):
    w = FarmWorldApp(); t = TractorApp(w, WeatherApp())
    setattr(t, attribute, capacity - 5)
    before = getattr(w._inventory, stock)
    r = getattr(t, method)(60.)
    assert (r['requested'], r['transferred'], r['onboard'], r['remaining_capacity']) == (60., 5., capacity, 0)
    assert r['transfer_status'] == 'partial' and r['unit'] == unit
    assert r['inventory_remaining'] == before - 5
    state = copy.deepcopy((t.get_state(), w.get_state()))
    noop = getattr(t, method)(1.)
    assert noop['transfer_status'] == 'no_op' and noop['transferred'] == 0
    assert (t.get_state(), w.get_state()) == state
    summary = receipt_summary(NS(op_type='TOOL', tool_name='TractorApp__'+method, tool_args={}, content=r))
    assert summary['transfer']['transferred'] == 5


def test_failed_seed_loading_is_atomic_and_success_keeps_legacy_switch():
    w = FarmWorldApp(); t = TractorApp(w, WeatherApp())
    t.seed_type = 'HEINONG84'; t._seed_hopper = 10
    w._inventory.seed_stock['HEINONG58'] = 0
    before = copy.deepcopy((t.get_state(), w.get_state()))
    for count in (100, 0, -1, True, 1.5):
        assert 'error' in t.load_seeds('HEINONG58', count)
        assert (t.get_state(), w.get_state()) == before
    w._inventory.seed_stock['HEINONG58'] = 100
    r = t.load_seeds('HEINONG58', 50)
    assert t.seed_type == 'HEINONG58' and r['transferred'] == 50 and r['onboard'] == 60


def test_shared_resource_receipts(tractor_scene):
    env, t, *_ = tractor_scene
    t._fuel_tank_l = 95
    before = env.warehouse.stock.fuel_liters
    r = t.refuel(60.)
    assert r['transferred'] == 5 and r['inventory_remaining'] == before - 5
    t._seed_hopper = 299950; t.seed_type = 'STANDARD'
    before = env.warehouse.stock.seed_stock['STANDARD']
    r = t.load_seeds('STANDARD', 100)
    assert r['transferred'] == 50 and r['inventory_remaining'] == before - 50


def test_paddy_transfers_reject_atomically_and_report_exact_increment():
    w = checkpoint('after_transplant'); ops = PaddyOpsApp(w); m = PaddyMachineryApp(w)
    w.machine('tractor').fuel_liters = 55.; w.field.fuel_liters = 100.
    before = copy.deepcopy(w.get_state())
    with pytest.raises(ValueError, match='remaining_capacity=5'):
        m.refuel('tractor', 60.)
    assert w.get_state() == before
    r = m.refuel('tractor', 5.)
    assert r['transferred'] == 5 and r['onboard'] == 60 and r['inventory_remaining'] == 95
    w.field.seedlings.loaded = 75000; w.field.seedlings.quantity = 60000
    before = copy.deepcopy(w.get_state())
    with pytest.raises(ValueError, match='stock'):
        ops.load_seedlings('ir72_standard', 112500)
    assert w.get_state() == before
    r = ops.load_seedlings('ir72_standard', 60000)
    assert r['transferred'] == 60000 and r['onboard'] == 135000 and r['inventory_remaining'] == 0
    before = copy.deepcopy(w.get_state())
    with pytest.raises(ValueError, match='Unknown fertilizer product'):
        ops.load_fertilizer(1., 'invalid')
    assert w.get_state() == before
    before_stock = w.field.fertilizer_kg
    r = ops.load_fertilizer(5.)
    assert r['transferred'] == 5 and r['inventory_remaining'] == before_stock - 5


@pytest.mark.parametrize('method,attribute,stock', [
    ('refuel', '_fuel_tank_l', 'fuel_liters'),
    ('load_fertilizer', '_fertilizer_spreader_kg', 'fertilizer_kg'),
    ('load_pesticide', '_pesticide_tank_l', 'pesticide_liters'),
    ('refill_pesticide_tank', '_pesticide_tank_l', 'pesticide_liters'),
    ('load_fungicide', '_fungicide_tank_l', 'pesticide_liters'),
])
def test_insufficient_local_stock_and_invalid_numbers_do_not_mutate(method, attribute, stock):
    w = FarmWorldApp(); t = TractorApp(w, WeatherApp())
    setattr(t, attribute, 0.); setattr(w._inventory, stock, 2.)
    before = copy.deepcopy((t.get_state(), w.get_state()))
    for value in (10., 0., -1., float('nan'), float('inf'), True):
        r = getattr(t, method)(value)
        assert 'error' in r
        assert (t.get_state(), w.get_state()) == before
    assert getattr(t, method)(10.)['available'] == 2.


def test_enhanced_receipts_do_not_count_noop_as_completed_transfer():
    from fairy.agents.jev.receipts import enhance_snapshot
    from fairy.agents.jev.model_view import classify
    w = FarmWorldApp(); t = TractorApp(w, WeatherApp())
    r = t.refuel(1.)  # Starts full.
    step = NS(op_type='TOOL', tool_name='TractorApp__refuel', tool_args={'liters': 1.}, content=r)
    assert receipt_summary(step)['status'] == 'no_op' and classify(step) == 'no_op'
    snapshot = enhance_snapshot({'farm_now': {}}, {'steps': [step]})
    row = snapshot['farm_now']['actions_this_run']['TractorApp__refuel']
    assert row['successful_receipts'] == 0 and row['no_op_calls'] == 1
    assert 'transferred' in snapshot['steps_so_far'][0]
