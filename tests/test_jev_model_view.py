"""Bounded projection contracts, exact grouping and pre-network guard."""
from types import SimpleNamespace as NS
import copy
import pytest
from fairy.agents.jev import management as M
from fairy.agents.jev.model_view import compact,project,request_guard,ContextBudgetError,encode,RECENT_LIMIT
from test_jev_constraints import enhanced


def step(name='FarmWorldApp__get_ridge_state',data=None,at=0.,args=None,failed=False):
    return NS(op_type='TOOL_ERROR' if failed else 'TOOL',tool_name=name,tool_args=args or {},content=data if data is not None else {'value':1},time_after=at)

def view(steps):
    facts=dict(steps=steps,plots=[],ridges=[]);context=M.management_context('task',facts,100.,0)
    return project({'task':'task','farm_now':{},'steps_so_far':['old']},facts,context,100.)


def test_equal_ranges_are_lossless_and_preserve_tail_and_value_types():
    raw={str(i):9.375 for i in range(63)};raw['63']=4.6875
    v=compact(raw,'ridge_product_kg')
    assert v['groups']==[dict(start=0,end=62,value=9.375),dict(start=63,end=63,value=4.6875)]
    decoded={str(i):g['value'] for g in v['groups'] for i in range(g['start'],g['end']+1)}
    assert decoded==raw
    assert len(compact({'0':True,'1':1},'ridge_product_kg')['groups'])==2
    assert compact([0,1,1,3],'requested_ridges')['ranges']=='0-1,1,3'


def test_observation_rows_keep_all_per_ridge_differences():
    raw=[{'ridge_id':i,'moisture':.2 if i<63 else .3,'mature':False} for i in range(64)]
    c=compact(raw);assert len(c['groups'])==2
    decoded=[dict(ridge_id=i,**g['values']) for g in c['groups'] for i in range(g['start'],g['end']+1)]
    assert decoded==raw


def test_interleaved_same_clock_observations_merge_without_hiding_differences():
    a=step(data={'ridges':[{'ridge_id':0,'v':1}]},at=10.)
    steps=[a,step('SystemApp__get_current_time',{'time':10.},at=10.),copy.deepcopy(a)]
    before=copy.deepcopy(steps);v=view(steps)
    obs=next(r for r in v['latest_observations'] if r['action']==a.tool_name)
    assert obs['repeat_count']==2 and obs['status']=='observation_received'
    assert len(v['recent_events'])==2 and all('result' not in r for r in v['recent_events'])
    assert steps==before
    steps.append(step(data={'ridges':[{'ridge_id':0,'v':2}]},at=10.))
    obs=next(r for r in view(steps)['latest_observations'] if r['action']==a.tool_name)
    assert obs.get('repeat_count',1)==1 and obs['result']['ridges']['groups'][0]['values']['v']==2


def test_full_result_equality_and_exact_time_not_truncated_prefix_control_dedup():
    a='x'*1800
    v=view([step(data={'text':a+'A'},at=10.1),step(data={'text':a+'B'},at=10.1)])
    assert len(v['recent_events'])==2
    v=view([step(data={'value':1},at=10.1),step(data={'value':1},at=10.2)])
    assert len(v['recent_events'])==2


def test_long_history_stays_bounded_but_unique_unresolved_failures_survive():
    steps=[step('SystemApp__advance_time',{'status':'ok'},at=i,args={'days':1}) for i in range(1000)]
    steps.insert(0,step('TractorApp__harvest',{'error':'not mature'},at=None,args={'start':63},failed=True))
    v=view(steps)
    assert len(v['recent_events'])<=RECENT_LIMIT
    assert v['unresolved_failures'][0]['result']=={'error':'not mature'}
    assert v['history_summary']['total_actions']==1001 and len(encode(v))<15000
    assert 'steps_so_far' not in v and 'actions_so_far' not in v


def test_failure_is_cleared_only_by_success_with_same_tool_arguments():
    s=step('TractorApp__harvest',{'error':'wet'},args={'ridge_id':63},failed=True)
    assert view([s,step('TractorApp__harvest',{'status':'ok'},args={'ridge_id':62})])['unresolved_failures']
    assert view([s,step('TractorApp__harvest',{'status':'ok'},args={'ridge_id':63})])['unresolved_failures']
    assert not view([s,step('TractorApp__harvest',{'status':'ok','harvested_ridges':[63]},args={'ridge_id':63})])['unresolved_failures']


def test_budget_includes_questions_and_reserves_protected_fields():
    state={'task':'原始任务','unresolved_failures':[{'error':'blocked'}],'recent_events':['x'*1000],'completed_work':{'old':'x'*1000}}
    qs={'next_action':{'criteria':{'wait':'wait for maturity'},'instructions':'choose'}}
    before=copy.deepcopy((state,qs));out,b=request_guard(state,qs,limit=400)
    assert 'recent_events' not in out and 'completed_work' not in out
    assert out['task']==state['task'] and out['unresolved_failures']==state['unresolved_failures']
    assert (state,qs)==before and b['request_bytes']<=400
    with pytest.raises(ContextBudgetError):request_guard(state,{'x':{'criteria':{'a':'x'*1000}}},limit=400)


def test_oversized_protected_request_stops_before_service_call():
    _,a=enhanced('scenario_maize_l3_normal');calls=[]
    a.llm.system_one=lambda *args,**kwargs:calls.append(args)
    with pytest.raises(ContextBudgetError):a._ask('tool',{'task':'x'*50000},{'next_action':{'criteria':{'done':'done'}}})
    assert not calls


def test_precise_internal_ledger_is_not_mutated_or_exposed_as_raw_maps():
    facts=dict(steps=[],ridges=[],plots=[]);c=M.management_context('task',facts,0.,0)
    c['ledger']['root_water_by_ridge']={str(i):100. for i in range(64)}
    c['ledger']['ridge_product_kg']={str(i):9.375 for i in range(64)}
    before=copy.deepcopy(c);v=project({'task':'task','farm_now':{}},facts,c,0.)
    assert c==before and 'ledger' not in v['management_progress']
    assert v['management_progress']['product_accounting']['ridge_product_kg']['groups']==[dict(start=0,end=63,value=9.375)]


def test_partial_and_pending_receipts_never_count_requested_or_skipped_ridges_complete():
    s=step('TractorApp__harvest',{'status':'partial','harvested_ridges':[0], 'skipped_ridges':[63],'uncovered_ridges':[1,2]},args={'start':0,'end':63})
    v=view([s]);assert v['completed_work']['TractorApp__harvest']['actual_ridges']['ranges']=='0'
    failure=step('FieldOpsApp__irrigate',{'error':'blocked'},args={'start':0},failed=True)
    pending=step('FieldOpsApp__irrigate',{'status':'irrigation_pending'},args={'start':0})
    assert view([failure,pending])['unresolved_failures']


def test_native_irrigation_amount_complete_is_distinct_from_due_and_pending():
    from test_jev_ridge_irrigation import fixture
    _,a,task,now,context=fixture();f=copy.deepcopy(a._facts)
    f['steps'].append(NS(op_type='TOOL',tool_name='FieldOpsApp__irrigate',tool_args={},time_before=now,time_after=now,
                        content={'status':'irrigation_started','irrigated_ridges':list(range(64)),
                                 'estimated_water_mm_per_ridge':50.,'effect_ready_at':now+100.}))
    assert context(f,now)['ridge_irrigation']['active']['status']=='AMOUNT_ACCOUNTED_PENDING_EFFECT'
    c=context(f,now+101)
    assert c['ridge_irrigation']['active']['status']=='REFERENCE_AMOUNT_ACCOUNTED'
    v=project({'task':task,'farm_now':{}},f,c,now+101)
    water=v['management_progress']['ridge_irrigation']
    assert 'active' not in water
    assert water['rounds'][0]['status']=='REFERENCE_AMOUNT_ACCOUNTED'
    assert c['ridge_irrigation']['rounds'][0]['assigned_mm_by_ridge']['63']==50.
