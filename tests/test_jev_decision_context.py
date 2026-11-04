"""Round/scope ambiguity and separate tool/argument requests (offline)."""
import copy
from types import SimpleNamespace as NS

from fairy.agents.jev import management as M, decision_context as C
from fairy.agents.jev.receipts import enhance_snapshot
from test_jev_management import MAIZE, step, rice_facts, RICE
from test_jev_constraints import enhanced


def due_fixture():
    scene, a = enhanced('scenario_maize_l3_normal')
    now = a.time_manager.time()
    f = copy.deepcopy(a._facts)
    for r in f['ridges']: r['planted'] = True
    f['steps'] = [step('TractorApp__plant_seeds', {}, {'planted_ridges': list(range(64))}, time=now-50*86400),
                  step('TractorApp__base_fertilize', {}, {'fertilizer_used_kg': 200.}, time=now-50*86400)]
    for lo in (0, 16, 32, 48):
        f['steps'].append(step('TractorApp__apply_fertilizer', {'start_ridge': lo, 'end_ridge': lo+15},
                              {'status': 'ok', 'fertilized_ridges': list(range(lo, lo+16)), 'fertilizer_used_kg':75.}, time=now-25*86400))
    f['steps'].append(step('SystemApp__advance_time', {'duration': {'days': 25}}, {'status': 'ok'}, time=now))
    f['machines']['TractorApp']['fertilizer_spreader_kg'] = 0.
    f['inventory']['fertilizer_kg'] = 300.
    a._facts=f; a._snapshot_task=MAIZE+'单独追肥不额外添加灌溉水。'
    a._management=M.management_context(a._snapshot_task, f, now, 64)
    return scene, a, now


def test_current_round_is_not_overwritten_by_old_full_coverage_or_recent_history():
    _, a, now=due_fixture(); f=a._facts; before=copy.deepcopy(f)
    state=enhance_snapshot({'task':MAIZE,'farm_now':{},'recent_actions':[{'action':s.tool_name,'result':s.content} for s in f['steps'][-5:]]},f)
    state=C.present(state,f,a._management,now)
    assert state['current_decision']['next_fertilizer_round']['index']==2
    remaining=state['current_decision']['next_fertilizer_round']['remaining_by_ridge_kg']
    assert remaining['groups']==[{'start':0,'end':63,'value':4.6875}]
    work=state['completed_work']['TractorApp__apply_fertilizer']
    assert work['actual_ridges']['ranges']=='0-63'
    assert 'actions_this_run' not in state['farm_now']
    events=[r for r in state['recent_events'] if r['action']=='TractorApp__apply_fertilizer']
    assert all(r['at'] is not None for r in events)
    assert events[-1]['round_boundary']['earliest_incomplete_round_after']==2
    assert 'steps_so_far' not in state
    assert f==before



def test_no_speculative_arguments_in_enhanced_tool_choice_but_selected_args_still_resolve():
    _,a,_=due_fixture(); calls=[]
    pick='SystemApp__advance_time'
    def ask(kind,state,qs):
        calls.append((kind,copy.deepcopy(qs)))
        return {k:dict(choice=pick if k=='next_action' else next(iter(q['criteria'])),confidence=.9,probabilities={pick:1.}) for k,q in qs.items()}
    a._ask=ask
    selected,args,_=a._decide({'task':a._snapshot_task})
    assert selected==pick and args
    assert set(calls[0][1])=={'next_action'}
    assert len(calls)>1 and all('next_action' not in qs for _,qs in calls[1:])
    assert 'Do not repeat an action whose result is already shown' not in calls[0][1]['next_action']['instructions']
    assert 'new required round' in calls[0][1]['next_action']['instructions']


def test_empty_applicator_names_load_prerequisite_without_claiming_round_complete():
    _,a,_=due_fixture()
    names=['TractorApp__load_fertilizer','TractorApp__apply_fertilizer','FarmWorldApp__apply_fertigation','SystemApp__advance_time']
    criteria=a._management_criteria({n:'native operation' for n in names})
    reason=a._management['blocked_actions']['TractorApp__apply_fertilizer'][0]
    assert 'round 2 remains incomplete' in reason and 'Load fertilizer first' in reason
    assert 'all rounds are accounted' not in reason
    assert 'Current fertilizer round 2' in criteria[names[0]] and 'prerequisite' in criteria[names[0]]
    assert 'carrier water to zero' in criteria[names[2]] and criteria[names[2]].startswith('[DUE')
    assert names[3] in criteria and criteria[names[3]].startswith('[DEFER')
    quota=a._facts['inventory']['limits_and_usage']
    quota['fertilizer_quota_kg']=500.;quota['fertilizer_used_kg']=500.
    a._management_criteria({names[1]:'native operation'})
    assert 'quota is insufficient' in a._management['blocked_actions'][names[1]][0]


def test_due_wait_label_says_deferral_not_future_checkpoint():
    _,a,_=due_fixture();menu=a.tool_menus['SystemApp__advance_time'];arg=menu.args[0]
    opts=a._arg_options(menu,arg,{})
    assert any('defer blocked due work' in k for k in opts)
    assert not any('until next task check' in k for k in opts)


def test_paddy_rounds_and_unknown_clock_remain_target_scoped():
    f=rice_facts();now=0.;context=M.management_context(RICE,f,now,0)
    f['steps'][0].time=None
    snap={'task':RICE,'farm_now':{},'recent_actions':[{'action':s.tool_name} for s in f['steps']]}
    out=C.present(snap,f,context,now)
    first=out['recent_events'][0]
    assert first['at'] is None
    assert first['round_boundary']['plot_id']=='p1'
    assert first['round_boundary']['earliest_incomplete_round_after']==2
    assert out['current_decision']['plot_progress'][0]['next_fertilizer_round']['index']==2


def test_labels_do_not_treat_failed_or_pending_receipts_as_new_round_completion():
    _,a,now=due_fixture();f=a._facts
    f['steps'] += [step('TractorApp__apply_fertilizer',{}, {'error':'insufficient supply'},time=now,failed=True),
                   step('SystemApp__wait_for_notification',{}, {'status':'ok'},time=now)]
    labels=C.round_labels(f,a._management)
    assert len(f['steps'])-1 not in labels and len(f['steps']) not in labels


def test_paddy_insufficient_supply_reports_incomplete_plot_rounds_separately():
    _,a=enhanced('scenario_rice_l3_normal');f=rice_facts()
    f['machines']['tractor']['fertilizer_kg']=0.
    a._facts=f;a._management=M.management_context(RICE,f,a.time_manager.time(),0)
    name='PaddyOpsApp__apply_fertilizer'
    a._management_criteria({name:'apply'})
    reason=a._management['blocked_actions'][name][0]
    assert 'remain incomplete' in reason and 'load the prescribed batch first' in reason
    # Complete all three rounds using actual per-plot product receipts.
    f['steps'] *= 3
    a._management=M.management_context(RICE,f,a.time_manager.time(),0)
    a._management_criteria({name:'apply'})
    assert 'All explicit fertilizer doses' in a._management['blocked_actions'][name][0]


def test_history_mode_receipts_keep_unknown_dates_and_are_not_deleted():
    f={'steps':[NS(op_type='TOOL_ERROR',tool_name='x',tool_args={},content='failure')]}
    context=M.management_context('task',f,0.,0)
    state={'task':'task','actions_so_far':[{'action':'x','result':'failure'}]}
    out=C.present(state,f,context,0.)
    assert len(out['unresolved_failures'])==1
    assert out['unresolved_failures'][0]['result']=='failure'
    assert out['unresolved_failures'][0]['at'] is None
    assert f['steps'][0].content=='failure'


def test_future_fertilizer_is_not_presented_as_due_or_made_illegal():
    _,a,now=due_fixture();f=a._facts
    # Reuse the same second-round balance, but its reference is still future.
    for s in f['steps']:
        if s.tool_name.endswith('__plant_seeds'):s.time=now-40*86400
    f['machines']['TractorApp']['fertilizer_spreader_kg']=300.
    a._management=M.management_context(a._snapshot_task,f,now,64)
    before=copy.deepcopy(a._management)
    out=C.present({'task':a._snapshot_task,'farm_now':{}},f,a._management,now)
    r=out['current_decision']['next_fertilizer_round']
    assert r['timing_status']=='UPCOMING_REFERENCE' and r['seconds_until_reference']==10*86400
    assert out['management_progress']['field_progress']['days_since_last_planting']==40.
    assert 'not maturity' in out['management_progress']['field_progress']['planting_age_basis']
    assert a._management==before
    name='TractorApp__apply_fertilizer'
    choices=a._management_criteria({name:'apply'})
    assert name in choices and choices[name].startswith('[UPCOMING')
    load='TractorApp__load_fertilizer'
    assert load not in a._management_criteria({load:'load'})
    assert 'reference timing' in a._management['blocked_actions'][load][0]


def test_dose_timing_remains_unknown_without_an_established_anchor():
    from fairy.agents.jev.model_view import fertilizer_reference
    c={'next_ridge_fertilizer_round':{'index':1,'reference_day':25},'windows':[]}
    assert fertilizer_reference(c,100.)['timing_status']=='TIMING_UNKNOWN'
    c['windows']=[{'kind':'fertilizer','target':'field','reference_day':25,'at':100.}]
    assert fertilizer_reference(c,100.)['timing_status']=='DUE_REFERENCE'


def test_fresh_root_check_does_not_hide_feasible_undelivered_irrigation_reference():
    from test_jev_ridge_irrigation import fixture
    from fairy.agents.jev.model_view import project
    _,a,task,now,context=fixture();before=copy.deepcopy(a._management)
    assert not [w for w in before['windows'] if w['kind']=='water_check' and w['at']<=now]
    name='FieldOpsApp__irrigate'
    choices=a._management_criteria({name:'water','SystemApp__advance_time':'wait'})
    assert choices[name].startswith('[DUE irrigation reference 1:')
    assert 'sensor read is not watering' in choices[name]
    water=project({'task':task,'farm_now':{}},a._facts,a._management,now)['management_progress']['ridge_irrigation']
    assert water['active_reference_index']==1 and 'active' not in water
    assert a._management['ledger']==before['ledger']
    assert a._management['ridge_irrigation']==before['ridge_irrigation']
