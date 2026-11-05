"""Public evidence semantics, lossless encoding and enhanced-only integration."""
import copy
from types import SimpleNamespace as NS

from fairy.agents.jev import management as M, state_semantics as S, temporal
from fairy.agents.jev.model_view import project, encode, request_guard


def step(name, data, args=None, at=10., failed=False):
    return NS(tool_name=name, content=data, tool_args=args or {}, time_after=at,
              op_type='TOOL_ERROR' if failed else 'TOOL')


def facts(steps=(), size=4):
    return dict(steps=list(steps), plots=[], ridges=[dict(ridge_id=i, planted=True,
                harvested=False, growth_stage='bare') for i in range(size)])


def view(f, task='播种至成熟收获', now=100.):
    context=M.management_context(task, f, now, len(f['ridges']))
    context['postharvest']={'pending_kg':0,'unsafe_stored_batches':[],'evidence':'dry unknown grain'}
    return project({'task':task,'farm_now':{}},f,context,now)


def test_column_roundtrip_preserves_types_missing_values_and_different_tail():
    raw={'nested':{str(i):dict(stand=1. if i<63 else 0., wet=False if i<32 else 0,
                             detail={'a':None,'b':'中文'}, time=10+i) for i in range(64)}}
    before=copy.deepcopy(raw); packed=S.pack_columns(raw)
    assert len(encode(packed))<len(encode(raw))
    assert encode(S.unpack_columns(packed))==encode(raw)
    assert raw==before and S.pack_columns(packed)==packed
    assert S.pack_columns({'0':{'a':1},'1':{'b':1}})=={'0':{'a':1},'1':{'b':1}}


def test_live_integer_keys_and_archived_string_keys_both_pack_without_type_loss():
    live={i:dict(ridge_id=i,stand_fraction=0.,pest_present=False,detail='same long observation'*3) for i in range(64)}
    archived={str(i):v for i,v in live.items()}
    for raw in (live,archived):
        packed=S.pack_columns(raw)
        assert packed['encoding']==S.COLUMN_ENCODING
        assert S.unpack_columns(packed)==raw
        assert type(packed['row_keys'][0]) is type(next(iter(raw)))
        assert len(encode(packed))<len(encode(raw))
        assert S.pack_columns(packed)==packed
    colliding={0:live[0],'0':live[0]}
    assert S.pack_columns(colliding)==colliding


def test_same_clock_superset_dedup_requires_actual_equal_rows_scope_and_metadata():
    def obs(i, ids, at=10., source='Farm__get_state', scope='a', tail=1):
        return dict(action_index=i,action=source,_when=at,_args={'farm_id':scope,'start':0,'end':3},
                    _raw_result={'ridges':[{'ridge_id':r,'value':tail} for r in ids],'unit':'fraction'})
    a,b=obs(1,[0,1]),obs(2,[0,1,2,3])
    assert S.superseded_observations([a,b])==([b],1)
    for c in (obs(2,[0,1,2,3],at=11.),obs(2,[0,1,2,3],source='Robot__get_state'),
              obs(2,[0,1,2,3],scope='b'),obs(2,[0,1,2,3],tail=0)):
        assert S.superseded_observations([a,c])[1]==0
    c=copy.deepcopy(b);c['_raw_result']['unit']='percent'
    assert S.superseded_observations([a,c])[1]==0


def test_failure_resolution_requires_successful_actual_coverage_with_same_context():
    bad=step('Tractor__plant_seeds',{'error':'insufficient seed'},
             {'start':0,'end':3,'seed_type':'A'},failed=True)
    def success(ids, seed='A', farm=None):
        args={'start':min(ids),'end':max(ids),'seed_type':seed}
        if farm:args['farm_id']=farm
        return step(bad.tool_name,{'status':'ok','planted_ridges':ids},args)
    assert not S.resolved_failure(bad,[success([0,1])])
    assert not S.resolved_failure(bad,[success([0,1,2,3],'B')])
    assert not S.resolved_failure(bad,[success([0,1,2,3],farm='other')])
    assert S.resolved_failure(bad,[success([0,1]),success([2,3])])
    assert not S.resolved_failure(bad,[step('Tractor__load_seeds',{'status':'ok','onboard':100})])
    assert not S.resolved_failure(bad,[step(bad.tool_name,{'status':'partial'},bad.tool_args)])
    assert view(facts([bad,step(bad.tool_name,{'status':'ok','planted_ridges':[0]},bad.tool_args)]))['unresolved_failures']
    original=copy.deepcopy(bad)
    v=view(facts([bad,success([0,1]),success([2,3])]))
    assert not v['unresolved_failures'] and v['history_summary']['resolved_failed_targets']==1
    assert bad==original


def test_unknown_recovery_is_explicit_and_wrapped_error_text_is_retained():
    bad=step('Tractor__harvest',{'ok':False,'error':'not mature'},{'ridge_id':3},failed=True)
    row=view(facts([bad]))['unresolved_failures'][0]
    assert row['result']['error']=='not mature'
    assert row['recovery_status'].startswith('unknown')


def test_shared_lifecycle_unknown_schedule_and_bare_planted_are_distinct():
    f=facts();task='从播种到成熟收获'
    c=M.management_context(task,f,100.,4);v=view(f,task)
    assert c['plan']['long_horizon']==temporal.build(task,f,100.)['seasonal_task']
    assert c['plan']['long_horizon'] is True
    assert S.lifecycle('inspect equipment')['recognition']=='unknown'
    assert not S.lifecycle('full season; do not harvest')['seasonal_task']
    assert 'not parsed' in v['current_decision']['schedule_interpretation']
    field=v['management_progress']['field_progress']
    assert 'remaining_ridges' not in field and field['fertilizer_schedule_status']=='not_parsed'
    assert v['farm_now']['crop']['groups'][0]['values']==dict(planted=True,harvested=False,growth_stage='bare')
    assert v['management_progress']['postharvest']==dict(pending_kg=0,status='no_pending_batch')


def test_explicit_zone_comparison_retains_sources_unknowns_and_observation_dates():
    task='ridges 0-3: AA seed_spacing_cm=8.2'
    a=step('Farm__get_ridge_state',{'ridges':[dict(ridge_id=0,seed_type='BB',seed_spacing_cm=8.2),
                                                   dict(ridge_id=1,seed_type='AA',seed_spacing_cm=8.2)]})
    b=step('Robot__inspect',{'ridges':[dict(ridge_id=0,stand_fraction=0)]},at=20.)
    f=facts([a,b]);before=copy.deepcopy(f);result=S.task_compliance(task,f)
    assert len(result['sources'])==1
    farm=result['sources'][0]
    assert farm['mismatches'][0]['ridge_id']==0
    assert farm['mismatches'][0]['at']==10. and farm['unknown_ridges']==[2,3]
    # Stand-only evidence remains available to establishment/observations;
    # it does not create a second, irrelevant cultivar/spacing source.
    assert f==before
    assert S.task_compliance(task+'; ridges 2-3: BB seed_spacing_cm=8.2',f)['status']=='unknown'


def test_staggered_planting_clocks_are_grouped_without_averaging():
    rows=[step('TractorApp__plant_seeds',{'planted_ridges':[0,1]},at=0.),
          step('TractorApp__plant_seeds',{'planted_ridges':[2,3]},at=86400.)]
    v=view(facts(rows),now=2*86400.)
    cohorts=v['management_progress']['planting_cohorts']['groups']
    assert [(r['start'],r['end'],r['elapsed_days_bounds']) for r in cohorts]==[(0,1,[2.,2.]),(2,3,[1.,1.])]


def test_guard_packs_without_removing_required_values_or_mutating_input():
    raw={'task':'original','latest_observations':[{str(i):{'value':1,'unit':'kg','extra':'x'*50} for i in range(64)}]}
    before=copy.deepcopy(raw)
    out,info=request_guard(raw,{},limit=len(encode(raw))-100)
    assert info['status']=='passed' and S.unpack_columns(out)==raw and raw==before
    assert not info['removed_optional_sections']
