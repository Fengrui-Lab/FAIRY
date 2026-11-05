"""Archived failure mechanisms, enhanced-only; no model or tool execution."""
import copy
from types import SimpleNamespace as NS
import pytest
from fairy.agents.jev import establishment as E, management as M, temporal, state_semantics as S
from fairy.agents.jev.model_view import project
from test_jev_constraints import enhanced,options

SID='scenario_full_season_hb_hn50_hn84_hn58_mixed_stress'
TASK='播种至成熟收获。ridges 0-3: AA seed_spacing_cm=8.2'

def mini():
    from fairy.agents.jev.menu import build_tool_menus
    scene,a=enhanced(SID)
    a.tool_menus=build_tool_menus(a.tools_map,task_text=a._snapshot_task,num_ridges=64,
                                steps=a._facts['steps'],enforced_tool_adaptor=True)
    return scene,a

def step(name,data,args=None,at=10.,failed=False):
    return NS(op_type='TOOL_ERROR' if failed else 'TOOL',tool_name=name,
              tool_args=args or {},content=data,time_after=at)

def facts(steps=(),size=4):
    return dict(steps=list(steps),now=100.,ridges=[dict(ridge_id=i,planted=True,harvested=False,growth_stage='bare') for i in range(size)],inventory={})

def load(seed='AA'):
    return step('TractorApp__load_seeds',{'status':'ok','seed_type':seed,'transferred':1000},{'seed_type':seed,'count':1000},at=0.)

def sow(ids=(0,1,2,3),spacing=8.2,at=1.):
    return step('TractorApp__plant_seeds',{'status':'ok','planted_ridges':list(ids)},
                {'start_ridge':min(ids),'end_ridge':max(ids),'seed_spacing_cm':spacing},at)

def reset(ids=(0,),before=1.,after=1.,resets=None,spacing=8.2,at=50.):
    return step('TractorApp__replant_seeds',{'status':'ok','replanted_ridges':list(ids),
      'phenology_reset_ridges':list(ids) if resets is None else resets,
      'stand_fraction_before':{str(i):before for i in ids},'stand_fraction_after':{str(i):after for i in ids}},
      {'start_ridge':min(ids),'end_ridge':max(ids),'spacing_cm':spacing,'full_replant':True},at)

def test_complete_nonoverlapping_prescription_only_and_no_cross_farm_guess():
    f=facts();assert len(E.prescription(TASK,f))==4
    assert not E.prescription(TASK+'; ridges 2-3: BB seed_spacing_cm=7.9',f)
    assert not E.prescription(TASK.replace('0-3','0-2'),f)
    f['farms']={'a':{}};assert not E.prescription(TASK,f)
    unknown=facts([sow()])
    assert E.summary(TASK,unknown)['unknown_establishment_ridges']==[0,1,2,3]

def test_loaded_cultivar_zone_boundary_spacing_and_exact_batch_are_bound():
    scene,a=mini();f=a._facts;f['machines']['TractorApp'].update(seed_type='HEIHE50',seed_hopper=137277)
    before=copy.deepcopy(f);menu=a.tool_menus['TractorApp__plant_seeds']
    assert set(options(a,menu.tool_name,'start_ridge').values())==set(range(21))
    assert set(a._range_options(menu,{'start_ridge':20},'start_ridge').values())=={20}
    assert set(options(a,menu.tool_name,'seed_spacing_cm',{'start_ridge':20}).values())=={8.2}
    assert not a._range_options(menu,{'start_ridge':21},'start_ridge')
    f['machines']['TractorApp']['seed_hopper']=0
    t=a.tools_map['TractorApp__load_seeds']
    assert E.load_amount(t,'HEIHE50',a._snapshot_task,f)[0]==137277
    f['machines']['TractorApp']['seed_hopper']=137277
    assert f==before

def test_dependent_sowing_resolves_target_before_spacing_without_numeric_model_choice():
    _,a=mini();a._facts['machines']['TractorApp'].update(seed_type='HEIHE50',seed_hopper=137277)
    calls=[]
    def ask(kind,state,qs):
        calls.extend(qs)
        return {k:{'choice':('ridge 20' if k=='arg__start_ridge' else next(iter(v['criteria']))),'confidence':.9} for k,v in qs.items()}
    a._ask=ask
    args,_=a._jev_arguments({'task':a._snapshot_task},'TractorApp__plant_seeds')
    assert args['start_ridge']==args['end_ridge']==20 and args['seed_spacing_cm']==8.2
    assert calls[0]=='arg__start_ridge' and 'arg__seed_spacing_cm' not in calls

def test_correction_requires_correct_hopper_and_success_clears_repair_target():
    _,a=mini();f=a._facts;task=a._snapshot_task
    f['ridges'][8]['planted']=True
    f['steps']=[load('HEINONG84'),sow((8,),7.9)]
    f['machines']['TractorApp'].update(seed_type='HEINONG84',seed_hopper=100000)
    t=a.tools_map['TractorApp__replant_seeds'];assert E.blocker(t,task,f)
    f['machines']['TractorApp']['seed_type']='HEIHE50';f['steps'].append(load('HEIHE50'))
    assert not E.blocker(t,task,f)
    assert set(options(a,'TractorApp__replant_seeds','full_replant',{'start_ridge':8}).values())=={True}
    f['steps'].append(reset((8,),spacing=8.2))
    assert 8 not in E.target_sets(task,f)[3]
    assert E.blocker(t,task,f)

def test_gap_fill_is_distinct_from_cultivar_correction():
    f=facts([load(),sow(),step('Robot__inspect_emergence',{'observations':{'0':{'ridge_id':0,'stand_fraction':.6}}})])
    assert E.target_sets(TASK,f)[3]=={0}
    # The policy is tested on a real native tool contract, not a fabricated enum.
    _,a=enhanced(SID);a._facts['steps']=f['steps'];a._snapshot_task=TASK
    a._facts['ridges']=f['ridges'];a._facts['machines']['TractorApp'].update(seed_type='AA',seed_hopper=10000)
    opts=E.options(a.tools_map['TractorApp__replant_seeds'],'full_replant',{'yes':True,'no':False},{'start_ridge':0},TASK,a._facts)
    assert opts=={'no':False}

def test_reset_ledger_uses_actual_receipts_and_preserves_initial_schedule():
    f=facts([sow(at=0.),reset((1,2),at=10.),reset((3,),resets=[],before=.4,after=.8,at=20.),
             step('TractorApp__replant_seeds',{'error':'fuel'},{'full_replant':True},at=30.,failed=True)])
    c=M.management_context('施基肥200公斤。参考追肥安排为第25日300公斤。',f,40.,4)
    assert c['ledger']['first_planting_timestamps']=={str(i):0. for i in range(4)}
    assert c['ledger']['planting_timestamps']=={'0':0.,'1':10.,'2':10.,'3':0.}
    assert c['windows'][0]['at']==25*86400

def test_pre_reset_observation_is_unknown_after_reset_not_a_current_mismatch():
    bad=step('Farm__get_ridge_state',{'ridges':[dict(ridge_id=0,seed_type='BB',seed_spacing_cm=8.2)]},at=5.)
    f=facts([bad,reset()]);r=S.task_compliance(TASK,f)['sources'][0]
    assert not r['mismatches'] and r['unknown_ridges']==[0,1,2,3]
    fresh=step('Farm__get_ridge_state',{'ridges':[dict(ridge_id=0,seed_type='AA',seed_spacing_cm=8.2)]},at=60.)
    f['steps'].append(fresh);assert S.task_compliance(TASK,f)['sources'][0]['verified_ridges']==[0]

def test_nonimproving_reset_does_not_suppress_pressure_or_erase_other_ridges():
    obs=lambda i:step('Robot__inspect_emergence',{'covered_ridges':[0,1,2,3]},at=10.+i)
    f=facts([load(),sow()]+[obs(i) for i in range(16)]+[reset(at=30.)])
    g=temporal.build(TASK,f,100.)
    assert g['observation_loop_pressure'] and not g['material_progress_recent']
    row=g['observation_coverage'][0]
    assert row['cycle_covered_ridges']==[1,2,3] and not row['field_coverage_complete']
    f['steps'].append(reset(before=.4,after=.9,resets=[],at=40.))
    assert not temporal.build(TASK,f,100.)['observation_loop_pressure']

def test_charging_keeps_long_wait_but_delivery_and_management_cutoff_remain():
    _,a=enhanced('scenario_maize_l3_normal');f=a._facts;a._management['wait_limit_seconds']=None
    f['pending']=[dict(from_action='Robot0__charge',seconds_left=3600)]
    opts=options(a,'SystemApp__advance_time','duration')
    secs=lambda d:sum(v*{'days':86400,'hours':3600,'minutes':60,'seconds':1}[k] for k,v in d.items())
    assert max(map(secs,opts.values()))>=86400 and 3600 in map(secs,opts.values())
    f['pending'].append(dict(from_action='FieldOpsApp__irrigate',seconds_left=1800))
    assert max(map(secs,options(a,'SystemApp__advance_time','duration').values()))==1800
    f['pending']=[];a._management['wait_limit_seconds']=7200
    assert max(map(secs,options(a,'SystemApp__advance_time','duration').values()))==7200

def test_report_dedup_ignores_queries_charge_and_nonimproving_reset():
    f=facts([load(),sow()]);signature=E.report_signature(TASK,f)
    f['steps'].append(step('AgentUserInterface__send_message_to_user',{'status':'ok'},{'content':E.CHECKPOINT+signature}))
    f['steps'] += [step('Robot__check_status',{'battery_pct':100}),reset()]
    assert not E.report_allowed(TASK,f)
    f['steps'].append(reset(before=.4,after=.9,resets=[]));assert E.report_allowed(TASK,f)
    assert E.report_allowed('只发送一次消息',f)

def test_generated_report_is_a_bounded_delivery_fact_without_changing_raw_workflow():
    s=step('AgentUserInterface__send_message_to_user',{'status':'ok','content':'x'*10000},{'content':'x'*10000})
    f=facts([s]);c=M.management_context(TASK,f,100.,4);before=copy.deepcopy(f)
    v=project({'task':TASK,'farm_now':{}},f,c,100.)
    assert len(str(v['recent_events']))<1000 and f==before
    assert v['recent_events'][0]['result']['report_sent']

def test_explicit_staggered_phase_uses_previous_completion_not_wall_clock_or_charge():
    _,a=enhanced(SID);f=a._facts;task=a._snapshot_task
    assert E.planting_phase(task,f)['target_ridges']==list(range(21))
    for r in f['ridges'][:21]:r['planted']=True
    now=f['now'];f['steps']=[sow(tuple(range(21)),at=now)]
    phase=E.planting_phase(task,f)
    assert phase['status']=='UPCOMING' and phase['seconds_until']==5*86400
    f['now']+=5*86400
    assert E.planting_phase(task,f)['status']=='READY'
    assert E.planting_phase(task.replace('播种时序约束','其他说明'),f) is None
    f['steps']=[]
    assert E.planting_phase(task,f)['status']=='TIMING_UNKNOWN'


def test_new_error_can_be_reported_and_failed_delivery_does_not_suppress_reporting():
    f=facts([load(),sow()]);signature=E.report_signature(TASK,f)
    content={'content':E.CHECKPOINT+signature}
    f['steps'].append(step('AgentUserInterface__send_message_to_user',{'error':'delivery'},content,failed=True))
    assert E.report_allowed(TASK,f)
    f['steps'][-1]=step('AgentUserInterface__send_message_to_user',{'status':'ok'},content)
    assert not E.report_allowed(TASK,f)
    f['steps'].append(step('TractorApp__harvest',{'error':'fuel'},failed=True))
    assert E.report_allowed(TASK,f)


def test_report_checkpoints_keep_plot_and_farm_identity():
    f=facts();f['ridges']=[];f['plots']=[dict(plot_id='p1',planted=False)]
    a=E.report_signature(TASK,f);f['plots'][0]['planted']=True
    assert E.report_signature(TASK,f)!=a
    f['plots']=[];f['farms']={'a':{'ridges':[dict(ridge_id=0,planted=True)]},'b':{'ridges':[dict(ridge_id=0,planted=False)]}}
    a=E.report_signature(TASK,f);f['farms']['b']['ridges'][0]['planted']=True
    assert E.report_signature(TASK,f)!=a
    f['steps']=[sow((0,)),sow((0,),at=20.)]
    assert 1 in E.material_indices(TASK,f)


def test_reports_use_history_prefix_and_crop_changes_without_visible_hashes():
    f=facts([load(),sow()])
    f['steps'].append(step('AgentUserInterface__send_message_to_user',{'status':'ok'},
                           {'content':'Crop now: [{"stage":"VE"}]'}))
    f['steps'].append(step('Robot__check_status',{'battery_pct':100}))
    assert not E.report_allowed(TASK,f,'Crop now: [{"stage":"VE"}]')
    assert E.report_allowed(TASK,f,'Crop now: [{"stage":"V1"}]')
    assert E.report_allowed(TASK,f,[{'stage':'V1'}])
    f['steps'][-2].tool_args['content']='Crop now: {"a":{"stage":"VE","inventory":{"fuel":10}}}'
    assert not E.report_allowed(TASK,f,'Crop now: {"a":{"stage":"VE","inventory":{"fuel":9}}}')
    _,a=mini();assert E.CHECKPOINT not in a._report_text()


def test_native_string_echo_report_is_recognized_without_a_dict_success_status():
    f=facts([load(),sow()]);text='Crop now: [{"stage":"VE"}]'
    f['steps'].append(step('AgentUserInterface__send_message_to_user',text,{'content':text}))
    f['steps'].append(step('Robot__check_status',{'battery_pct':100}))
    assert not E.report_allowed(TASK,f,[{'stage':'VE'}])
    assert E.report_allowed(TASK,f,[{'stage':'V1'}])


def observed_stand(value, **fields):
    return step('Robot0__inspect_emergence',{'observations':{'0':dict(ridge_id=0,stand_fraction=value,**fields)}},at=20.)


@pytest.mark.parametrize('fields',[{}, {'growth_stage':'bare'},
    {'growth_stage':'PLANTED_PRE_EMERGENCE'}, {'emerged':False},
    {'emerged':False,'growth_stage':'V1'}])
def test_zero_stand_before_or_without_emergence_is_not_a_replant_target(fields):
    f=facts([load(),sow(),observed_stand(0.,**fields)])
    f['now']=100*86400  # Elapsed days alone must never invent failed emergence.
    assert not E.target_sets(TASK,f)[3]
    summary=E.summary(TASK,f)
    assert summary['stand_diagnosis_deferred']['ridges']==[0]
    assert 'mandatory inspection queue' in summary['stand_diagnosis_deferred']['reason']


@pytest.mark.parametrize('fields',[{'growth_stage':'VE'},{'growth_stage':'V2'},
    {'growth_stage':'VT'},{'growth_stage':'R1'},{'stage':'R8_FULL_MATURITY'},{'emerged':True}])
def test_fresh_zero_stand_with_confirmed_emergence_remains_repairable(fields):
    f=facts([load(),sow(),observed_stand(0.,**fields)])
    assert E.target_sets(TASK,f)[3]=={0}


def test_confirmed_emergence_precedes_total_loss_but_resets_invalidate_it():
    f=facts([load(),sow(),observed_stand(1.),observed_stand(0.)])
    assert E.target_sets(TASK,f)[3]=={0}
    f['steps'] += [reset(),observed_stand(0.)]
    assert not E.target_sets(TASK,f)[3]
    # A new cycle must establish emergence again.
    f['steps'].append(observed_stand(.6))
    assert E.target_sets(TASK,f)[3]=={0}


def test_later_phase_cannot_reinterpret_an_old_pre_emergence_zero():
    f=facts([load(),sow(),observed_stand(0.)])
    f['steps'].append(step('FarmWorldApp__get_ridge_state',{'ridge_id':0,'growth_stage':'V1'},at=30.))
    assert not E.target_sets(TASK,f)[3]
    f['steps'].append(observed_stand(0.))
    assert E.target_sets(TASK,f)[3]=={0}


def test_receipt_stand_base_does_not_prove_emergence_or_requeue_a_gap_fill():
    f=facts([load(),sow(),reset(before=.4,after=.8),observed_stand(0.)])
    assert not E.target_sets(TASK,f)[3]
    f=facts([load(),sow(),observed_stand(.6),reset(before=.6,after=.84,resets=[])])
    assert not E.target_sets(TASK,f)[3]
    f['steps'].append(observed_stand(.84))
    assert E.target_sets(TASK,f)[3]=={0}


@pytest.mark.parametrize('value',[None,True,-.1,1.1,float('nan'),float('inf')])
def test_invalid_stand_values_are_not_failure_evidence(value):
    f=facts([load(),sow(),observed_stand(value,emerged=True)])
    assert not E.target_sets(TASK,f)[3]


def test_explicit_pre_emergence_contradicts_positive_stand_and_stale_loss():
    f=facts([load(),sow(),observed_stand(.6,emerged=False)])
    assert not E.target_sets(TASK,f)[3]
    f['steps']=[load(),sow(),observed_stand(.6),
        step('FarmWorldApp__get_ridge_state',{'ridge_id':0,'growth_stage':'bare'},at=30.)]
    assert not E.target_sets(TASK,f)[3]


def test_pre_emergence_cultivar_and_spacing_corrections_are_not_suppressed():
    f=facts([load('BB'),sow(spacing=7.9),observed_stand(0.,emerged=False)])
    assert E.target_sets(TASK,f)[3]=={0,1,2,3}


def test_formal_soil_scene_replant_and_seed_loading_are_blocked_for_early_zero():
    _,a=enhanced('scenario_full_season_hb_local_soil_constraint_nutrition_patch')
    f=a._facts
    for r in f['ridges']:r['planted']=True
    f['steps']=[load('HEINONG84'),sow(tuple(range(64)),7.9),observed_stand(0.)]
    f['machines']['TractorApp'].update(seed_type='HEINONG84',seed_hopper=100000)
    before=copy.deepcopy(f)
    replant=a.tools_map['TractorApp__replant_seeds']
    seed=a.tools_map['TractorApp__load_seeds']
    assert E.blocker(replant,a._snapshot_task,f)
    assert not E.options(replant,'start_ridge',{'0':0},{},a._snapshot_task,f)
    assert E.load_amount(seed,'HEINONG84',a._snapshot_task,f) is None
    assert a._adaptor_metadata()['establishment_adapter_version']==E.VERSION
    assert f==before


@pytest.mark.parametrize('before,after',[(.92,.92),(.8,.6)])
def test_nonimproving_gap_fill_blocks_unchanged_observations_not_new_stand_loss(before,after):
    f=facts([load(),sow(),observed_stand(before),reset(before=before,after=after,resets=[]),observed_stand(after)])
    assert not E.target_sets(TASK,f)[3]
    assert E.summary(TASK,f)['nonimproving_stand_repairs']['ridges']==[0]
    # Date/phase changes and repeated reads alone do not restore this target.
    f['now']+=86400
    f['steps'].append(observed_stand(after,growth_stage='V2'))
    assert not E.target_sets(TASK,f)[3]
    f['steps'].append(observed_stand(after/2,growth_stage='V2'))
    assert E.target_sets(TASK,f)[3]=={0}


def test_nonimproving_gap_fill_does_not_hide_prescription_corrections_or_new_cycles():
    f=facts([load('BB'),sow(),observed_stand(.92),reset(before=.92,after=.92,resets=[]),observed_stand(.92)])
    assert E.target_sets(TASK,f)[3]=={0,1,2,3}
    f=facts([load(),sow(),observed_stand(.92),reset(before=.92,after=.92,resets=[]),reset(),observed_stand(.6)])
    assert E.target_sets(TASK,f)[3]=={0}


def test_harvested_targets_do_not_remain_deferred_or_stalled_work():
    f=facts([load(),sow(),observed_stand(0.)])
    f['ridges'][0]['harvested']=True
    assert 'stand_diagnosis_deferred' not in E.summary(TASK,f)
    f['steps']=[load(),sow(),observed_stand(.92),reset(before=.92,after=.92,resets=[]),observed_stand(.92)]
    assert 'nonimproving_stand_repairs' not in E.summary(TASK,f)


@pytest.mark.parametrize('intervening',[
    {'stand_fraction':0.,'emerged':False},
    {'stand_fraction':.6,'growth_stage':'bare'},
    {'stand_fraction':.6,'emerged':False,'growth_stage':'V2'},
])
def test_pre_emergence_or_conflicting_change_cannot_clear_nonimprovement(intervening):
    f=facts([load(),sow(),observed_stand(.92,emerged=True),
             reset(before=.92,after=.92,resets=[]),
             observed_stand(intervening['stand_fraction'],**{k:v for k,v in intervening.items() if k!='stand_fraction'}),
             observed_stand(.92,emerged=True)])
    assert not E.target_sets(TASK,f)[3]
    assert E.evidence(TASK,f)[1][0]['stand_repair_plateau']['value']==.92
    f['steps'].append(observed_stand(.5,emerged=True))
    assert E.target_sets(TASK,f)[3]=={0}
