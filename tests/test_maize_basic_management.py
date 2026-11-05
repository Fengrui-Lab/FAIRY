import copy
import json
import subprocess
import sys
from pathlib import Path
import pytest
from fairy.scenarios.maize.basic_management import terminal_result, DATA
from fairy.scenarios.registry import get_scenario_class
from fairy.apps.farm_world import FarmWorldApp

def record(yield_value=0):
    state=dict(mature=list(range(64)),harvested=list(range(64)),grain_bin=0,trailer=0,warehouse=0 if yield_value==0 else 100)
    per=[dict(ridge=i,DOM='2026-08-13',TWSO=yield_value) for i in range(64)]
    return state,per

def test_zero_is_complete_not_production_success():
    s,p=record();r=terminal_result(s,p,[],['legacy positive yield required'],False)
    assert r['execution_complete'] and not r['production_success']
    assert r['status']=='zero_yield_completed'

@pytest.mark.parametrize('case',['missing','nan','bool','duplicate','unharvested','grain','pending','audit'])
def test_zero_does_not_mask_failures(case):
    s,p=record();audit=[];pending=False
    if case=='missing':p.pop()
    if case=='nan':p[0]['TWSO']=float('nan')
    if case=='bool':p[0]['TWSO']=False
    if case=='duplicate':p[0]['ridge']=1
    if case=='unharvested':s['harvested'].pop()
    if case=='grain':s['grain_bin']=1
    if case=='pending':pending=True
    if case=='audit':audit=['resource mismatch']
    assert not terminal_result(s,p,audit,[],pending)['execution_complete']

def test_positive_has_no_exact_reference_dose_requirement():
    s,p=record(1234)
    s.update(actual_N=83,irrigation_dose=7,reference_grid_obeyed=False)
    assert terminal_result(s,p,[],[],False)['production_success']
    assert not terminal_result(s,p,[],['unsafe grain'],False)['production_success']

@pytest.mark.parametrize('key,water',[('w01',150),('n01',0)])
def test_registration_task_and_initial_validation(key,water):
    s=get_scenario_class(f'scenario_maize_l3_basic_{key}_v1')(seed=0);s.setup()
    farm=s.get_typed_app(FarmWorldApp)
    assert farm._inventory.fertilizer_kg==360
    assert farm._management_regime.irrigation_quota_mm_total==water
    assert not any(r.planted for r in farm._ridges)
    assert '施基肥200' not in s.scenario_input
    assert 'N120' not in s.scenario_input
    assert len(s.events)>200
    assert not s.validate().metadata['execution_complete']

def test_stale_gate_blocks_before_tools(tmp_path):
    script=Path(__file__).resolve().parents[1]/'scripts/run_maize_basic_reference.py'
    gate=tmp_path/'gate.json';gate.write_text(json.dumps({'status':'passed','candidate':'W01','identity':{}}))
    out=tmp_path/'run'
    p=subprocess.run([sys.executable,str(script),'run','--candidate','W01','--gate',str(gate),'--output',str(out)],capture_output=True,text=True)
    assert p.returncode!=0 and 'Stale or mismatched' in p.stderr
    assert not out.exists()

@pytest.mark.parametrize('case,expected',[
    ('mixed_zero_wet',True), ('positive_wet',False),
    ('zero_twso_with_grain',False), ('positive_twso_zero_recovery',False),
    ('zero_unharvested',False), ('missing_maturity',False),
    ('unsettled_buffer',False), ('pending',False), ('budget_failure',False),
])
def test_mixed_grain_terminal(case,expected):
    from types import SimpleNamespace
    from fairy.scenarios.maize.basic_management import candidate_stored_goals
    state,per=record(1234)
    per[-1]['TWSO']=0
    recovery={i:SimpleNamespace(harvested=True,recovered_yield_g_m2_at_market_moisture=1.,
                               drying_required=False,grain_moisture_frac=.14) for i in range(64)}
    recovery[63].recovered_yield_g_m2_at_market_moisture=0
    recovery[63].drying_required=True
    recovery[63].grain_moisture_frac=.2381
    if case=='positive_wet':recovery[0].drying_required=True;recovery[0].grain_moisture_frac=.2381
    if case=='zero_twso_with_grain':recovery[63].recovered_yield_g_m2_at_market_moisture=1
    if case=='positive_twso_zero_recovery':per[63]['TWSO']=1
    if case=='zero_unharvested':recovery[63].harvested=False;state['harvested'].remove(63)
    if case=='missing_maturity':per[63]['DOM']=None
    if case=='unsettled_buffer':state['trailer']=1
    goals=candidate_stored_goals(state,per,recovery)
    r=terminal_result(state,per,['budget exceeded'] if case=='budget_failure' else [],goals,case=='pending')
    assert r['production_success'] is expected
    if expected:assert r['execution_complete'] and r['status']=='completed'
