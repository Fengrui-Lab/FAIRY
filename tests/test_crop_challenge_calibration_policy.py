from types import SimpleNamespace as NS
import pytest
from fairy.scenarios.crop_challenges import runtime
from fairy.scenarios.rice import validation

def scenario(monkeypatch,*,status='experimental',audit_ok=True,stored=True,tool_error=False,late=False,fingerprint='same',gate=False,budget=False):
 monkeypatch.setattr(validation,'audit_world',lambda world:{'success':audit_ok})
 monkeypatch.setattr(validation,'_all_harvested_grain_stored',lambda world:stored)
 monkeypatch.setattr(runtime,'measurements',lambda s:dict(time=200*86400 if late else 0,day='2026-01-01',crop_fingerprint=fingerprint,water_used=10))
 task=dict(status=status,calibration_note='review not complete',reference=dict(crop_fingerprint='same'),gates=[dict(metric='water_used',direction='lower',threshold=1)] if gate else [],window_budgets={'water_used':1} if budget else {})
 step=lambda op:NS(op_type=op,tool_name='PaddyOpsApp__irrigate',error_type='Error' if tool_error else None,content={})
 return NS(crop_name='rice',level='L3',workflow=NS(dag={1:step('WRITE'),2:step('READ')}),get_typed_app=lambda t:object(),_source_start=0,definition=NS(deadline_days=180),_challenge_evidence={'tasks':{'test':task}},scenario_id='test',_initial_measurements={'water_used':0},source_l3_scenario_id='test',_initial_checkpoint_digest='digest')

def test_experimental_status_is_diagnostic(monkeypatch):
 s=scenario(monkeypatch);r=runtime.CropChallengeScenario.validate(s)
 assert r.success and r.metadata['execution_success']
 assert r.metadata['calibrated'] is False and r.metadata['calibration_warning']
 assert r.metadata['calibration_required_for_validation'] is False

@pytest.mark.parametrize('kwargs,reason',[
 ({'audit_ok':False},'water/nitrogen/resource audit failed'),
 ({'stored':False},'all harvested rice must be safely stored'),
 ({'tool_error':True},'workflow contains tool errors'),
 ({'late':True},'season deadline exceeded'),
 ({'fingerprint':'changed'},'crop configuration differs'),
 ({'gate':True},'outcome gate failed'),
 ({'budget':True},'window resource budget exceeded'),
])
def test_actual_failures_still_reject(monkeypatch,kwargs,reason):
 r=runtime.CropChallengeScenario.validate(scenario(monkeypatch,**kwargs));assert not r.success and reason in r.message

def test_calibrated_case_has_no_warning(monkeypatch):
 r=runtime.CropChallengeScenario.validate(scenario(monkeypatch,status='calibrated'));assert r.success and r.metadata['calibrated'] and r.metadata['calibration_warning'] is None
