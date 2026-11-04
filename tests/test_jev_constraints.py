"""Native counterexamples found in the 40-scenario audit, plus scope boundaries."""
from types import SimpleNamespace as NS
import copy
import pytest
from fairy.agents.jev import management as M
from fairy.agents.jev.constraints import family, legal_options, action_blocker
from fairy.agents.jev.receipts import receipt_summary, grain_state, enhance_snapshot
from fairy.controllers.engine import Engine
from fairy.scenarios.workflow import WorkflowStep
from test_jev_new_tools import setup


def enhanced(sid='scenario_rice_l3_normal'):
    scene,a=setup(sid);a.enforced_tool_adaptor=True
    engine=Engine(agent=a,scenario=scene)
    a.workflow.add_node(WorkflowStep(op_type='USER', content=engine._resolve_agent_task(),time='2026-01-01 08:00:00'))
    a._state()
    return scene,a


def options(a,name,arg,scope=None):
    menu=a.tool_menus[name]
    return a._arg_options(menu,next(x for x in menu.args if x.name==arg),scope or {})


@pytest.mark.parametrize('tool,arg,valid',[('PaddyOpsApp__soak','hours',lambda v:type(v)==int and 1<=v<=72),
    ('PaddyOpsApp__transplant','row_spacing_cm',lambda v:v==20),
    ('PaddyOpsApp__transplant','hill_spacing_cm',lambda v:v==20),
    ('PaddyOpsApp__transplant','seedlings_per_hill',lambda v:v==3)])
def test_task_numbers_cannot_escape_hard_contract(tool,arg,valid):
    _,a=enhanced()
    assert options(a,tool,arg) and all(valid(v) for v in options(a,tool,arg).values())


def test_native_seedling_remainder_and_refuel_remainder():
    _,a=enhanced();w=a.tools_map['PaddyOpsApp__load_seedlings'].class_instance.world
    w.field.seedlings.loaded=75000;w.field.seedlings.quantity=60000
    w.machine('tractor').fuel_liters=55.;w.field.fuel_liters=100.
    a._state()
    seed=options(a,'PaddyOpsApp__load_seedlings','quantity',{'batch_id':'ir72_standard'})
    assert seed and 60000 in seed.values() and all(0<v<=60000 for v in seed.values())
    fuel=options(a,'PaddyMachineryApp__refuel','liters',{'machine_id':'tractor'})
    assert fuel and 5. in fuel.values() and all(0<v<=5 for v in fuel.values())
    # The chosen maximums really pass the original tool, no monkeypatched validator.
    a.tools_map['PaddyOpsApp__load_seedlings'](batch_id='ir72_standard',quantity=60000)
    a.tools_map['PaddyMachineryApp__refuel'](machine_id='tractor',liters=5.)
    assert w.field.seedlings.loaded==135000 and w.machine('tractor').fuel_liters==60.


def test_subclass_uses_inherited_public_resources_and_snapshot():
    scene,a=enhanced('scenario_maize_l3_basic_h01_maize204_v1')
    t=a.tools_map['TractorApp__load_fertilizer']
    assert t.class_name=='HeaderMaintenanceTractorApp' and family(t)=='TractorApp'
    assert a._facts['machines']['TractorApp']
    assert M.fertilizer_resources(t,a._facts) is not None
    t(kg=300.)
    a._state();opts=options(a,'TractorApp__load_fertilizer','kg')
    assert all(0<v<=200 for v in opts.values())


def test_native_partial_coverage_is_not_whole_requested_range():
    _,a=enhanced('scenario_maize_l3_normal')
    name=next(n for n in a.tools_map if n.endswith('__inspect_emergence'))
    raw=a.tools_map[name](start_ridge=0,end_ridge=63)
    s=NS(op_type='TOOL',tool_name=name,tool_args={'start_ridge':0,'end_ridge':63},content=raw)
    r=receipt_summary(s)
    assert r['status']=='partial' and r['covered_ridges']==list(range(8))
    snap=enhance_snapshot({'farm_now':{}},{'steps':[s]})
    assert snap['farm_now']['actions_this_run'][name]['actual_ridges']==list(range(8))
    assert 'partial' in snap['steps_so_far'][0] and 'uncovered 8-63' in snap['steps_so_far'][0]
    assert s.content is raw and s.tool_args['end_ridge']==63


def test_sensor_alias_is_water_but_canopy_does_not_clear_water_window():
    f=dict(ridges=[dict(ridge_id=i,planted=True) for i in range(64)],steps=[
        NS(op_type='TOOL',tool_name='TractorApp__plant_seeds',tool_args={},content={'planted_ridges':list(range(64))},time_after=0),
        NS(op_type='TOOL',tool_name='SensorApp__read_root_zone_sensors',tool_args={},content={'root_zone_sensors':[{'ridge_start':0,'ridge_end':63,'root_vwc':.3}]},time_after=21*86400)])
    task='施基肥200公斤。参考追肥安排为第25日300公斤。参考灌溉安排为第20日50毫米、第60日50毫米。'
    c=M.management_context(task,f,21*86400,64)
    assert c['ledger']['last_observations']['SensorApp__read_root_zone_sensors:field']==21*86400
    assert all(w.get('reference_day')!=20 and w['at']!=20*86400 for w in c['windows'])
    f['steps'][-1].tool_name='SensorApp__read_canopy_sensor'
    assert any(w['at']==20*86400 for w in M.management_context(task,f,21*86400,64)['windows'])


def test_typical_fertigation_range_is_not_a_hard_contract_and_nonfinite_is_rejected():
    _,a=enhanced('scenario_maize_l3_normal');t=a.tools_map['FarmWorldApp__apply_fertigation']
    arg=next(x for x in a.tool_menus['FarmWorldApp__apply_fertigation'].args if x.name=='nutrient_amount')
    opts=legal_options(t,arg,{'low':.15625,'nan':float('nan'),'bool':True}, {},a._facts)
    assert opts=={'low':.15625}


def test_fixed_drying_target_and_new_batch_safety():
    _,a=enhanced();t=a.tools_map['PaddyOpsApp__dry_grain'];w=t.class_instance.world
    from fairy.apps.paddy.models import GrainBatch
    w.field.grain_batches.append(GrainBatch('test','p1',100.,20.,'reception'))
    a._state()
    opts=options(a,'PaddyOpsApp__dry_grain','target_moisture_pct')
    assert set(opts.values())=={14.}
    assert t(batch_id='test',target_moisture_pct=14.)['status']=='ok'


def test_new_or_empty_batch_cannot_inherit_previous_drying():
    def s(name,d):return NS(op_type='TOOL',tool_name='FarmWorldApp__'+name,tool_args={},content=d)
    steps=[s('dry_grain',dict(status='ok',trailer_grain_kg=100.,target_moisture_pct=13.)),
           s('store_grain',dict(status='ok',moved_kg=100.,storage_grain_moisture_pct=13.,max_storage_moisture_pct=14.)),
           s('unload_grain',dict(status='ok',grain_kg_unloaded=200.))]
    f=dict(inventory={'harvest_grain_kg':200.,'storage':{'max_storage_moisture_pct':14.}},steps=steps)
    assert grain_state(f)['safe_current_batch'] is None
    n=NS(class_name='FarmWorldApp',name='store_grain',class_instance=NS())
    assert action_blocker(n,f,0)
    steps.append(s('dry_grain',dict(status='ok',trailer_grain_kg=200.,target_moisture_pct=13.)))
    assert not action_blocker(n,f,0)
    steps.append(s('store_grain',dict(status='ok',moved_kg=200.,warning='wet grain',batch_ridge_ids=[1])))
    steps.append(s('dry_grain',dict(status='ok',trailer_grain_kg=0.,ridges_dried=0)))
    f['inventory']['harvest_grain_kg']=0.
    assert grain_state(f)['unsafe_stored_batches']
    n.name='dry_grain';assert action_blocker(n,f,0)


def test_machine_prerequisites_are_filtered_without_executing_operations():
    scene,a=enhanced();before=[copy.deepcopy(x.get_state()) for x in scene.apps]
    criteria=a._management_criteria({n:m.description for n,m in a.tool_menus.items()})
    assert 'PaddyOpsApp__puddle_and_level' not in criteria
    assert 'PaddyMachineryApp__attach_implement' in criteria
    assert before==[x.get_state() for x in scene.apps]


def test_transplant_scope_binds_seedlings_fuel_remaining_area_and_midnight():
    _,a=enhanced();f=copy.deepcopy(a._facts)
    f['inventory']['seedlings']['loaded']=7500;f['machines']['transplanter']['fuel_liters']=50.
    f['now']=86399.5
    t=a.tools_map['PaddyOpsApp__transplant'];menu=a.tool_menus['PaddyOpsApp__transplant']
    arg=next(x for x in menu.args if x.name=='area_m2')
    # With less than 1 native whole second left, no positive batch can fit.
    assert not legal_options(t,arg,arg.options,{'plot_id':'p1'},f)
    f['now']=0.
    opts=legal_options(t,arg,arg.options,{'plot_id':'p1'},f)
    assert opts and max(opts.values())==100. and None not in opts.values()


def test_water_observation_invalidated_by_same_plot_work_or_utc_rollover_only():
    from fairy.agents.jev.observations import latest, derive_water, chinese_durations
    def step(method,pid,data,t):return NS(op_type='TOOL',tool_name='PaddyOpsApp__'+method,tool_args={'plot_id':pid},content=data,time_after=t)
    f={'plots':[{'plot_id':'p1','area_m2':1000}], 'inventory':{}, 'steps':[
        step('read_water_sensors','p1',{'surface_water_mm':8.,'timestamp':1000.},1000.)]}
    assert latest(f,'read_water_sensors','p1',2000.)['fresh']
    t=NS(name='irrigate')
    assert derive_water(t,'water_mm',{'plot_id':'p1'},'p1灌溉至20毫米',f,2000.)[0]==12.
    f['steps'].append(step('irrigate','p2',{'status':'ok'},2100.))
    assert latest(f,'read_water_sensors','p1',2200.)['fresh']
    f['steps'].append(step('irrigate','p1',{'status':'ok'},2300.))
    assert not latest(f,'read_water_sensors','p1',2400.)['fresh']
    assert derive_water(t,'water_mm',{'plot_id':'p1'},'p1灌溉至20毫米',f,2400.) is None
    f['steps']=f['steps'][:1]
    assert not latest(f,'read_water_sensors','p1',86401.)['fresh']
    assert chinese_durations('等待90分钟，浸田24小时，复查在第7天')==[('minutes',90.),('hours',24.),('days',7.)]


def test_native_crop_contract_overrides_legacy_soybean_depth_range():
    _,a=enhanced('scenario_maize_l3_normal')
    t=a.tools_map['TractorApp__plant_seeds'];arg=next(x for x in a.tool_menus['TractorApp__plant_seeds'].args if x.name=='depth_cm')
    from fairy.agents.jev.menu import scene_world
    rules=scene_world(t).crop_definition.planting_rules.depth_cm
    candidates={str(v):v for v in [1.,3.,4.,5.,6.,8.]}
    opts=legal_options(t,arg,candidates,{},a._facts)
    assert all(rules.validate(v,'depth') is None for v in opts.values())
    assert opts=={k:v for k,v in candidates.items() if rules.validate(v,'depth') is None}


def test_deterministic_supply_does_not_consume_chemical_pool_for_an_invented_dose():
    from fairy.agents.jev.constraints import derive_transfer
    _,a=enhanced();t=a.tools_map['PaddyOpsApp__load_seedlings']
    assert derive_transfer(t,'quantity',{},a._facts)[0]==150000
    r=a.tools_map['PaddyMachineryApp__refuel']
    assert derive_transfer(r,'liters',{'machine_id':'tractor'},a._facts)[0] == 40. # 20 L onboard / 60 L capacity
    _,m=enhanced('scenario_maize_l3_normal')
    t=m.tools_map['TractorApp__load_fungicide']
    assert derive_transfer(t,'liters',{},m._facts) is None


def test_paddy_storage_needs_actual_batch_moisture_not_other_batch_drying():
    from fairy.agents.jev.receipts import paddy_batches
    _,a=enhanced();t=a.tools_map['PaddyOpsApp__store_grain']
    f=copy.deepcopy(a._facts)
    f['inventory']['grain_batches']=[dict(batch_id='one',plot_id='p1',location='reception',wet_kg=100.),dict(batch_id='two',plot_id='p2',location='reception',wet_kg=100.)]
    f['steps']=[NS(op_type='TOOL',tool_name='PaddyOpsApp__dry_grain',tool_args={'batch_id':'one'},content={'status':'ok','moisture_pct':14.})]
    arg=NS(name='batch_id',arg_type='str')
    opts=legal_options(t,arg,{'one':'one','two':'two'}, {},f)
    assert opts=={'one':'one'}
    assert next(b for b in paddy_batches(f) if b['batch_id']=='two')['moisture_pct'] is None


def test_full_fuel_tanks_and_wrong_machine_selector_are_not_offered():
    _,a=enhanced();w=a.tools_map['PaddyMachineryApp__refuel'].class_instance.world
    for m in w.field.machines:m.fuel_liters=m.tank_capacity_liters
    a._state()
    criteria=a._management_criteria({n:m.description for n,m in a.tool_menus.items()})
    assert 'PaddyMachineryApp__refuel' not in criteria
    assert not options(a,'PaddyMachineryApp__refuel','machine_id')
    m=w.machine('tractor');m.implement='puddler'
    a._state()
    criteria=a._management_criteria({n:m.description for n,m in a.tool_menus.items()})
    assert 'PaddyMachineryApp__attach_implement' not in criteria
    assert 'PaddyMachineryApp__detach_implement' in criteria


def test_single_or_shallow_probe_is_not_a_complete_root_zone_check():
    f=dict(ridges=[dict(ridge_id=i,planted=True) for i in range(64)],steps=[
        NS(op_type='TOOL',tool_name='TractorApp__plant_seeds',tool_args={},content={'planted_ridges':list(range(64))},time_after=0),
        NS(op_type='TOOL',tool_name='SensorApp__read_root_zone_sensors',tool_args={},content={'root_zone_sensors':[{'ridge_start':0,'ridge_end':7,'root_vwc':.3}]},time_after=21*86400)])
    task='施基肥200公斤。参考灌溉安排为第20日50毫米。'
    assert any(w['kind']=='water_check' for w in M.management_context(task,f,21*86400,64)['windows'])
    f['steps'][-1].tool_name='SensorApp__read_soil_sensors'
    assert not M.ledger(M.task_plan(task,f,64),f)['root_water_by_ridge']


def test_whole_harvest_cannot_finish_on_an_unplanted_field_but_direct_negation_is_respected():
    from fairy.agents.jev.completion import problems
    f={'ridges':[dict(ridge_id=0,planted=False,harvested=False)]}
    assert problems('完成全季管理并收获全部田垄',f,None)
    assert not problems('只查询天气，不需要收获',f,None)


def test_long_jobs_disclose_the_shared_clock_and_crossed_checks_without_advancing_it():
    from fairy.agents.jev.operation_clock import annotation
    t=NS(class_name='PaddyOpsApp',name='soak',class_instance=NS())
    f={'now':100.,'plots':[]};context={'windows':[dict(kind='water_check',target='p2',at=1000.,utc='example')]}
    before=copy.deepcopy((f,context))
    r=annotation(t,{'hours':24},f,context)
    assert r['shared_clock'] and r['estimated_seconds']==86400 and r['crossed_checks'][0]['target']=='p2'
    assert (f,context)==before


def test_crop_checks_do_not_depend_on_parsing_a_fertilizer_prescription():
    f=dict(plots=[dict(plot_id='p1',area_m2=1000,planted=True,harvested=False)],steps=[
        NS(op_type='TOOL',tool_name='PaddyOpsApp__transplant',tool_args={'plot_id':'p1'},content={'completed':True},time_after=0)])
    c=M.management_context('每隔7个UTC日分别读取两田水分。按实际情况施肥。',f,8*86400,0)
    assert c['plan']['kind'] is None and any(w['kind']=='water_check' for w in c['windows'])


def test_unknown_fertigation_plan_still_has_positive_resource_bounded_multiplier():
    _,a=enhanced('scenario_maize_l3_normal')
    t=a.tools_map['FarmWorldApp__apply_fertigation'];menu=a.tool_menus['FarmWorldApp__apply_fertigation']
    arg=next(x for x in menu.args if x.name=='nutrient_amount')
    f=copy.deepcopy(a._facts);f['inventory']['fertilizer_kg']=30.
    result=legal_options(t,arg,{'zero':0.,'valid':.1,'too much':2.}, {'start_ridge':0,'end_ridge':9},f)
    assert result and all(0<v<=.1 for v in result.values())


def test_native_preparation_contract_blocks_premature_sowing_without_hidden_reads():
    scene,a=enhanced('scenario_maize_l3_normal')
    t=a.tools_map['TractorApp__plant_seeds']
    before=[copy.deepcopy(x.get_state()) for x in scene.apps]
    assert 'preparation' in action_blocker(t,a._facts,a._facts['now'])
    assert before==[x.get_state() for x in scene.apps]


def test_enhanced_history_keeps_repeat_compression_and_original_receipts():
    steps=[NS(op_type='TOOL',tool_name='SystemApp__advance_time',tool_args={'days':1},content={'status':'ok'},time_after=i*86400) for i in range(1000)]
    before=copy.deepcopy(steps)
    state=enhance_snapshot({'farm_now':{}},{'steps':steps})
    assert len(state['steps_so_far'])==1 and 'x1000' in state['steps_so_far'][0]
    assert 'recorded time' in state['steps_so_far'][0]
    assert len(state['recent_receipt_status'])==5 and steps==before


def test_state_size_telemetry_includes_current_blocker_explanations():
    import json
    from test_jev_agent import _run
    a,_,client=_run([{'next_action':'WeatherApp__get_current_weather'}],max_tool_calls=1,enforced_tool_adaptor=True)
    state=client.requests[0][0]
    assert 'blocked_actions' in state['management_progress']
    assert a.telemetry['max_state_chars']==len(json.dumps(state,default=str,ensure_ascii=False))


def test_post_basal_empty_spreader_cannot_create_an_empty_speculative_choice():
    # Actual first-pilot failure: no parsed basal prescription in this mini task,
    # then a successful default basal call empties the spreader. The next tool
    # request used to include its now-empty speculative total_kg Choice.
    from test_jev_agent import _ScriptedJev
    _,a=enhanced('scenario_full_season_hb_heinong58_resistant_biotic_water_budget_priority')
    a.tools_map['TractorApp__load_fertilizer'](kg=500.)
    receipt=a.tools_map['TractorApp__base_fertilize'](total_kg=500.)
    assert receipt.get('status')=='ok'
    state=a._state()
    from fairy.agents.jev.menu import build_tool_menus
    a.tool_menus=build_tool_menus(a.tools_map,task_text=state['task'],num_ridges=a._num_ridges,enforced_tool_adaptor=True)
    a._last_tool_probabilities={'TractorApp__base_fertilize':.99}
    choices=a._management_criteria({n:m.description for n,m in a.tool_menus.items()})
    assert 'TractorApp__base_fertilize' not in choices
    a.llm=_ScriptedJev([{'next_action':'WeatherApp__get_current_weather'}])
    picked,_,_=a._decide(state)
    assert picked=='WeatherApp__get_current_weather'
    assert all(q['criteria'] for _,qs in a.llm.requests for q in qs.values())
