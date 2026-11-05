"""Historical eviction never mutates exact facts or resolves a task/blocker."""
import copy
import pytest
from fairy.agents.jev.model_view import (
    request_guard, encode, ContextBudgetError, OBSERVATION_LIMIT, FAILURE_LIMIT,
    HISTORY_MAX_AGE_SECONDS, REQUEST_TARGET_BYTES,
)
from test_jev_model_view import step, view


def row(i,age=0,text='value'):
    return dict(action_index=i,age_seconds=age,result={'text':text},action='Farm__get_state')


def test_project_evicts_aged_raw_receipts_but_keeps_exact_workflow_and_current_facts():
    steps=[step(data={'value':'old'},at=0.,args={'ridge_id':0}),
           step(data={'value':'new'},at=86400.+1,args={'ridge_id':1})]
    from fairy.agents.jev import management as M
    from fairy.agents.jev.model_view import project
    facts=dict(steps=steps,ridges=[],plots=[])
    context=M.management_context('task',facts,86400.+1,0)
    before=copy.deepcopy((facts,context))
    v=project({'task':'task','farm_now':{'date':'today'}},facts,context,86400.+1)
    assert [o['result']['value'] for o in v['latest_observations']]==['new']
    assert v['history_retention']['omitted']['latest_observations']['age']==1
    assert v['farm_now']=={'date':'today'} and (facts,context)==before


def test_age_is_simulation_age_and_unknown_time_is_not_automatically_expired():
    state={'task':'original','latest_observations':[row(1,HISTORY_MAX_AGE_SECONDS+1),
        row(2,HISTORY_MAX_AGE_SECONDS),row(3,None)]}
    out,b=request_guard(state,{})
    assert [r['action_index'] for r in out['latest_observations']]==[2,3]
    assert out['history_retention']['omitted']['latest_observations']=={'age':1}
    assert b['history_retention']==out['history_retention']


def test_many_unique_targets_and_failures_retain_most_recent_five_and_record_omission():
    state={'task':'original','latest_observations':[row(i) for i in reversed(range(100))],
        'unresolved_failures':[row(i) for i in range(100)],
        'management_progress':{'blocked_actions':{'harvest':['not mature']},'remaining_requirements':['harvest']}}
    before=copy.deepcopy(state);out,_=request_guard(state,{})
    assert [r['action_index'] for r in out['latest_observations']]==list(range(95,100))
    assert len(out['latest_observations'])==OBSERVATION_LIMIT
    assert len(out['unresolved_failures'])==FAILURE_LIMIT
    assert out['history_retention']['omitted']['unresolved_failures']['count']==95
    assert out['management_progress']==state['management_progress'] and state==before


def test_no_small_section_cap_evicts_complete_recent_receipts():
    state={'task':'original','latest_observations':[
        dict(row(i),arguments={'long_target':'x'*3000}) for i in range(5)]}
    out,_=request_guard(state,{})
    assert out['latest_observations']==state['latest_observations']
    assert 'history_retention' not in out


def test_large_receipt_and_unicode_warning_remain_complete_without_previews():
    state={'task':'original','latest_observations':[row(1,text='x'*10000),row(2,text='latest')]}
    out,_=request_guard(state,{})
    assert out['latest_observations'][-1]==row(2,text='latest')
    assert out['latest_observations']==state['latest_observations']
    assert 'result_preview' not in out['latest_observations'][0]
    assert 'history_retention' not in out
    state['latest_observations']=[dict(row(3),result={'observations':'中'*2000,'warning':'battery low'})]
    out,_=request_guard(state,{})
    assert out['latest_observations']==state['latest_observations']


def test_total_budget_evicts_oldest_across_sections_before_current_state_or_choices():
    state={'task':'original','farm_now':{'important':'x'*36500},
        'management_progress':{'blocked_actions':{'done':['still growing']}},
        'latest_observations':[row(3,text='o'*2500),row(5,text='n'*2500)],
        'unresolved_failures':[row(2,text='f'*2500)]}
    questions={'next_action':{'criteria':{'wait':'wait for crop','inspect':'inspect crop'}}}
    before=copy.deepcopy((state,questions));out,b=request_guard(state,questions)
    assert b['request_bytes']<=REQUEST_TARGET_BYTES and b['working_target_met']
    assert not out['unresolved_failures']
    assert [r['action_index'] for r in out['latest_observations']]==[5]
    assert out['farm_now']==state['farm_now'] and out['management_progress']==state['management_progress']
    assert (state,questions)==before
    assert out['history_retention']['omitted']['unresolved_failures']=={'request_budget':1}
    again,_=request_guard(out,questions)
    assert again==out


def test_no_32kb_soft_target_removes_history_and_hard_guard_still_protects_task():
    out,b=request_guard({'task':'x'*33000,'latest_observations':[row(1)]},{})
    assert out['latest_observations']==[row(1)] and b['working_target_met']
    assert b['status']=='passed' and out['task']=='x'*33000
    with pytest.raises(ContextBudgetError) as exc:
        request_guard({'task':'x'*41000,'latest_observations':[row(1)]},{})
    assert exc.value.budget['status']=='blocked_before_network'


def test_eviction_is_unknown_history_not_automatically_resolved_or_completed():
    state={'task':'grow then harvest','unresolved_failures':[row(1,HISTORY_MAX_AGE_SECONDS+1)],
           'management_progress':{'completion_allowed':False,'last_blocker':{'error':'not mature'}}}
    out,_=request_guard(state,{})
    assert out['unresolved_failures']==[] and out['management_progress']==state['management_progress']
    assert 'not resolved' in out['history_retention']['meaning']
