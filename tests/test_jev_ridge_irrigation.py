"""Real native water-depth arithmetic and historical request counterexamples."""
import copy
from types import SimpleNamespace as NS
import pytest
from fairy.agents.jev import ridge_irrigation as I, management as M
from fairy.agents.jev.constraints import legal_options
from fairy.agents.jev.snapshot import build_snapshot
from fairy.scenarios.workflow import Workflow
from test_jev_constraints import enhanced


def fixture():
    scene,a=enhanced('scenario_maize_l3_normal');now=a.time_manager.time();f=copy.deepcopy(a._facts)
    for r in f['ridges']:r['planted']=True
    first=NS(op_type='TOOL',tool_name='TractorApp__plant_seeds',tool_args={},content={'planted_ridges':list(range(64))},time_after=now-20*86400)
    sensor=a.tools_map['SensorApp__read_root_zone_sensors']()
    read=NS(op_type='TOOL',tool_name='SensorApp__read_root_zone_sensors',tool_args={},content=sensor,time_after=now)
    f['steps']=[first,read];task=a._snapshot_task
    def context(facts=f,at=now):
        c=M.management_context(task,facts,at,64);c['ridge_irrigation']=I.build(task,facts,c,at);return c
    a._facts=f;a._management=context()
    return scene,a,task,now,context


def test_native_50mm_is_10_hours_and_all_64_ridges_without_model_parameters():
    scene,a,task,now,context=fixture();name='FieldOpsApp__irrigate';t=a.tools_map[name]
    before=[copy.deepcopy(x.get_state()) for x in scene.apps]
    asked=[]
    def forbidden(*args):asked.append(args);raise AssertionError('No numeric/range model question is needed for this explicit whole-field reference')
    a._ask=forbidden
    args,conf=a._jev_arguments({'task':task},name)
    assert args=={'start':0,'end':63,'hours':10.} and not conf and not asked
    assert before==[x.get_state() for x in scene.apps]
    result=t(**args)
    assert result['status']=='irrigation_started'
    assert result['estimated_water_mm_per_ridge']==50 and result['field_equivalent_irrigation_mm']==50
    assert result['irrigated_ridges']==list(range(64))


@pytest.mark.parametrize('name,arg',[('irrigate','hours'),('irrigate_range','duration_hours'),('irrigate_ridge','duration_hours')])
def test_aliases_cannot_offer_zero_negative_nonfinite_or_exceed_actual_quota(name,arg):
    _,a,_,_,_=fixture();t=a.tools_map['FieldOpsApp__'+name];menu=a.tool_menus['FieldOpsApp__'+name];m=next(x for x in menu.args if x.name==arg)
    f=copy.deepcopy(a._facts);f['inventory']['limits_and_usage']['irrigation_quota_mm_total']=300.
    f['inventory']['limits_and_usage']['irrigation_used_mm_total']=295.
    scope={'start':0,'end':63} if name!='irrigate_ridge' else {'ridge_id':63}
    values=legal_options(t,m,{'zero':0.,'negative':-1.,'nan':float('nan'),'infinite':float('inf'),'positive':.5,'ten':10.},scope,f)
    cap=1. if name!='irrigate_ridge' else 64.
    assert values and all(0<v<=cap for v in values.values())
    assert not {'zero','negative','nan','infinite'} & values.keys()


def test_failed_pending_and_repeated_receipts_do_not_fabricate_delivered_water():
    _,a,task,now,context=fixture();f=copy.deepcopy(a._facts)
    f['steps'] += [NS(op_type='TOOL',tool_name='FieldOpsApp__irrigate',tool_args={'start':0,'end':62,'hours':1.},time_before=now,time_after=now+3600,
          content={'status':'irrigation_started','irrigated_ridges':list(range(63)),'estimated_water_mm_per_ridge':5.,'effect_ready_at':now+86400}),
       NS(op_type='TOOL',tool_name='FieldOpsApp__irrigate',tool_args={},time_after=now+3601,content={'status':'irrigation_pending','irrigated_ridges':list(range(63)),'effect_ready_at':now+86400}),
       NS(op_type='TOOL_ERROR',tool_name='FieldOpsApp__irrigate',tool_args={},time_after=now+3602,content={'error':'quota'})]
    c=context(f,now+3602);active=c['ridge_irrigation']['active']
    assert active['remaining_mm_by_ridge']['0']==45. and active['remaining_mm_by_ridge']['63']==50.
    assert c['ridge_irrigation']['pending_ridges']==list(range(63))
    # The old read preceded this same-timestamp operation. It must not be reused.
    assert not c['ridge_irrigation']['observations']['observed_upper_vwc_by_ridge'].get('0')


def test_partial_first_batch_leaves_last_ridge_explicit_and_automatically_reachable():
    _,a,task,now,context=fixture();f=copy.deepcopy(a._facts)
    f['steps'].append(NS(op_type='TOOL',tool_name='FieldOpsApp__irrigate',tool_args={'start':0,'end':62,'hours':10.},time_before=now,time_after=now,
        content={'status':'irrigation_started','irrigated_ridges':list(range(63)),'estimated_water_mm_per_ridge':50.}))
    c=context(f,now);target=I.target(a.tools_map['FieldOpsApp__irrigate'],f,c)
    assert target['arguments']=={'start':63,'end':63,'hours':10.}


def test_pending_full_reference_blocks_duplicate_operation_until_recheck():
    _,a,task,now,context=fixture();f=copy.deepcopy(a._facts)
    f['steps'].append(NS(op_type='TOOL',tool_name='FieldOpsApp__irrigate',tool_args={},time_before=now,time_after=now,
        content={'status':'irrigation_started','irrigated_ridges':list(range(64)),'estimated_water_mm_per_ridge':50.,'effect_ready_at':now+86400}))
    c=context(f,now)
    assert not c['ridge_irrigation']['active']['remaining_mm_by_ridge']
    assert I.blocker(a.tools_map['FieldOpsApp__irrigate'],f,c)


def test_stale_or_wet_observation_needs_inspection_or_deferral_not_automatic_water():
    _,a,task,now,context=fixture();f=copy.deepcopy(a._facts)
    c=context(f,now+86400)
    assert I.target(a.tools_map['FieldOpsApp__irrigate'],f,c) is None
    assert I.blocker(a.tools_map['FieldOpsApp__irrigate'],f,c)
    f['steps'][-1].content['root_zone_sensors'][0]['root_vwc']=.99
    c=context(f,now);target=I.target(a.tools_map['FieldOpsApp__irrigate'],f,c)
    assert target and target['arguments']['start']>10 # observed-wet zone deferred, not marked complete


def test_native_quota_conversion_is_field_equivalent_and_program_amount_fits():
    _,a,task,now,context=fixture();f=copy.deepcopy(a._facts)
    f['inventory']['limits_and_usage']['irrigation_quota_mm_total']=300.
    f['inventory']['limits_and_usage']['irrigation_used_mm_total']=295.
    target=I.target(a.tools_map['FieldOpsApp__irrigate'],f,context(f,now))
    assert target['arguments']=={'start':0,'end':63,'hours':1.}
    # Fewer target ridges can use greater per-ridge depth under the same field quota.
    f['steps'][-1].content['root_zone_sensors']=[{'ridge_start':63,'ridge_end':63,'root_vwc':.2}]
    target=I.target(a.tools_map['FieldOpsApp__irrigate'],f,context(f,now))
    assert target['arguments']=={'start':63,'end':63,'hours':10.}


def test_ambiguous_or_zoned_task_is_not_promoted_to_whole_field_reference():
    _,a,task,now,context=fixture();f=a._facts;c=M.management_context(task+'仅对缺水区域定向处理。',f,now,64)
    c['ridge_irrigation']=I.build(task+'仅对缺水区域定向处理。',f,c,now)
    assert c['ridge_irrigation']['scope'] is None
    assert I.target(a.tools_map['FieldOpsApp__irrigate'],f,c) is None
