import copy
from types import SimpleNamespace as NS
import pytest
from fairy.agents.jev import temporal,management as M
from fairy.agents.jev.constraints import action_blocker,legal_options,transplant_capacity
from fairy.agents.jev.feasibility import ToolNotReady
from test_jev_constraints import enhanced


def partial_rice():
    _,a=enhanced('scenario_rice_l3_infrastructure_water_priority');f=a._facts
    f['now']=23*3600
    for p in f['plots']:p.update(puddled=True,levelled=True)
    f['plots'][0].update(planted=True,transplanted_area_m2=1000.)
    f['plots'][1].update(planted=False,transplanted_area_m2=1000.)
    f['inventory']['seedlings']['loaded']=0
    f['machines']['transplanter']['fuel_liters']=6.
    return a,f


def test_empty_seedlings_block_tool_selector_and_area_using_same_capacity():
    a,f=partial_rice();t=a.tools_map['PaddyOpsApp__transplant'];menu=a.tool_menus['PaddyOpsApp__transplant']
    assert 'load_seedlings' in action_blocker(t,f,f['now'])
    assert transplant_capacity({'plot_id':'p2'},f)==0
    selector=next(x for x in menu.args if x.name=='plot_id')
    assert not legal_options(t,selector,{'p2':'p2'},{},f)
    area=next(x for x in menu.args if x.name=='area_m2')
    assert not legal_options(t,area,{'all':None,'1000':1000.},{'plot_id':'p2'},f)
    # The exact real counterexample: 500m2 left, 37,500 seedlings needed.
    f['inventory']['seedlings']['loaded']=37500
    assert transplant_capacity({'plot_id':'p2'},f)==500
    assert legal_options(t,area,{'all':None,'1000':1000.},{'plot_id':'p2'},f)=={'500.0':500.}
    assert not action_blocker(t,f,f['now'])


def test_native_midnight_fuel_and_seed_constraints_share_positive_candidates():
    a,f=partial_rice();f['inventory']['seedlings']['loaded']=37500
    f['now']=86399.5;t=a.tools_map['PaddyOpsApp__transplant']
    assert transplant_capacity({'plot_id':'p2'},f)==0
    assert 'midnight' in action_blocker(t,f,f['now'])
    f['now']=3600.;f['machines']['transplanter']['fuel_liters']=0.
    assert 'refuel' in action_blocker(t,f,f['now'])
    f['machines']['transplanter']['fuel_liters']=.01
    assert transplant_capacity({'plot_id':'p2'},f)==5.


def test_local_empty_branch_reselects_tool_without_executing_or_hiding_native_errors():
    _,a=enhanced('scenario_maize_l3_normal');bad='FarmWorldApp__get_ridge_range_state';good='WeatherApp__get_current_weather';requests=[]
    original=a._jev_arguments
    def args(state,pick,*rest):
        if pick==bad:raise ToolNotReady(pick,'end',{'start':63})
        return original(state,pick,*rest)
    a._jev_arguments=args
    def ask(kind,state,qs):
        requests.append((copy.deepcopy(state),copy.deepcopy(qs)))
        pick=bad if len(requests)==1 else good
        return {'next_action':dict(choice=pick,confidence=.8,probabilities={pick:.8})}
    a._ask=ask
    before=copy.deepcopy(a._facts);pick,values,conf=a._decide({'task':a._snapshot_task})
    assert pick==good and values=={} and a._facts==before
    assert bad not in requests[1][1]['next_action']['criteria']
    assert requests[1][0]['local_constraints']['unavailable_tools_this_decision']==[bad]
    assert not [s for s in a.workflow.dag.values() if s.op_type in ('TOOL','TOOL_ERROR')]


def observations():
    steps=[NS(op_type='TOOL',tool_name='Robot0__inspect_emergence',tool_args={'start_ridge':i,'end_ridge':i+3},
              content={'status':'ok','covered_ridges':list(range(i,i+4))},time_after=1000.+i*10) for i in range(0,64,4)]
    facts=dict(steps=steps,ridges=[dict(ridge_id=i,planted=True,harvested=False) for i in range(64)])
    return facts


def test_lifecycle_intent_and_full_inspection_memory_do_not_require_full_season_phrase():
    f=observations();before=copy.deepcopy(f)
    g=temporal.build('播种后检查出苗，成熟后收获并入库。',f,3000.)
    assert g['seasonal_task'] and g['observation_loop_pressure'] and f==before
    assert g['observation_coverage'][0]['field_coverage_complete']
    assert g['observation_coverage'][0]['cycle_covered_ridges']==list(range(64))
    c=temporal.criteria({'Robot0__inspect_emergence':'read','SystemApp__advance_time':'wait'},g)
    assert c['Robot0__inspect_emergence'].startswith('[OBSERVATION MEMORY') and c['SystemApp__advance_time'].startswith('[SEASONAL')
    assert 'not_observed_ridges' not in g['observation_coverage'][0]


def test_crop_change_next_date_and_unknown_coverage_never_claim_old_inspection_current():
    f=observations();task='播种到成熟收获。'
    assert not temporal.build(task,f,3000.+86400)['observation_coverage']
    f['steps'].append(NS(op_type='TOOL',tool_name='FieldOpsApp__irrigate',tool_args={},content={'status':'irrigation_started'},time_after=3000.))
    assert not temporal.build(task,f,3100.)['observation_coverage']
    f=observations()
    for s in f['steps']:s.content={'status':'ok'}
    assert not temporal.build(task,f,3000.)['observation_coverage'][0]['field_coverage_complete']
    assert not temporal.build('只检查出苗，不要收获。',f,3000.)['observation_loop_pressure']


def test_existing_wait_values_deduplicate_without_losing_deadline_or_pending_limits():
    opts={'1 day':{'days':1},'24 hours':{'hours':24},'defer blocked due work (1d)':{'seconds':86400},'until charge ready':{'seconds':30}}
    result=temporal.wait_options(opts,True)
    assert len(result)==2 and any('defer blocked' in k for k in result)
    assert any(v=={'seconds':30} for v in result.values())


def test_inherited_shared_tool_uses_native_contract_only_in_enhanced_mode():
    from fairy.scenarios.registry import get_scenario_class
    from fairy.agents.agent.toolset_builder import build_toolset
    from fairy.controllers.agent_builder import FARM_AGENT_HIDDEN_TOOL_NAMES
    from fairy.agents.jev.menu import build_arg_menu,arg_descriptions
    s=get_scenario_class('scenario_multiobjective_seed_discount')(seed=0,detailed_briefing=True);s.setup()
    tools=build_toolset(s.apps,excluded_tool_names=FARM_AGENT_HIDDEN_TOOL_NAMES)[2]
    t=next(t for t in tools.values() if t.class_name=='PlanningTractor' and t.name=='unload_grain')
    arg=next(a for a in t.args if a.name=='batch_id');kw=dict(descriptions=arg_descriptions(t.function_description),numbers=[],num_ridges=32)
    with pytest.raises(ValueError,match='No menu rule'):build_arg_menu(t,arg,**kw)
    m=build_arg_menu(t,arg,**kw,enforced_tool_adaptor=True)
    assert list(m.options.values())==['jev-batch-000001'] and t.class_name=='PlanningTractor'


def test_overridden_methods_do_not_silently_inherit_a_different_tool_contract():
    from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
    from fairy.agents.jev.menu import canonical_tool
    class Changed(SharedTractorApp):
        def unload_grain(self,other_parameter):return None
    t=NS(class_instance=object.__new__(Changed),class_name='Changed',name='unload_grain')
    assert canonical_tool(t) is t


def test_receipt_based_partial_transplant_deadline_does_not_claim_wait_repairs_expiry():
    a,f=partial_rice();f['inventory']['seedlings']['loaded']=37500;f['now']=86401.
    f['steps']=[NS(op_type='TOOL',tool_name='PaddyOpsApp__transplant',tool_args={'plot_id':'p2'},content={'status':'ok','completed':False,'transplanted_area_m2':1000.},time_after=80000.)]
    assert transplant_capacity({'plot_id':'p2'},f)==0
    assert 'expired' in action_blocker(a.tools_map['PaddyOpsApp__transplant'],f,f['now'])


def test_entity_catalogs_come_from_acquired_receipts_and_preserve_offer_quantity_dependency():
    from fairy.agents.jev.entities import choices
    t=NS(class_name='SeedMarket',name='purchase_seed');arg=lambda n:NS(name=n)
    assert choices(t,arg('offer_id'),{},[])[0]==[]
    read=NS(op_type='TOOL',tool_name='SeedMarket__list_offers',tool_args={},content={'offers':[{'offer_id':'a','quantity':100,'available_lots':1},{'offer_id':'b','quantity':200,'available_lots':1}]})
    assert choices(t,arg('offer_id'),{},[read])[0]==['a','b']
    assert choices(t,arg('quantity'),{'offer_id':'b'},[read])[0]==[200]
    orders=NS(op_type='TOOL',tool_name='SeedMarket__get_purchase_records',tool_args={},content={'order1':{'offer_id':'b','quantity':200,'order_id':'order1'}})
    assert choices(t,arg('offer_id'),{},[read,orders])[0]==['a']


def test_nonspatial_observations_do_not_invent_per_ridge_inspection_obligations():
    f=observations();f['steps']=[NS(op_type='TOOL',tool_name='WeatherApp__get_current_weather',tool_args={},content={'rain':0},time_after=1000.)]
    g=temporal.build('播种到成熟收获。',f,1100.)
    assert 'not_observed_ridges' not in g['observation_coverage'][0]
    assert not g['observation_coverage'][0]['coverage_known']
    assert 'not automatically to-do' in g['coverage_interpretation']


def test_partial_spatial_observation_is_evidence_not_a_remaining_inspection_queue():
    f=observations();f['steps']=f['steps'][:1]
    g=temporal.build('播种到成熟收获。',f,1100.)
    row=g['observation_coverage'][0]
    assert row['cycle_covered_ridges']==[0,1,2,3]
    assert not row['field_coverage_complete'] and 'not_observed_ridges' not in row


def test_crop_selector_and_report_ids_respect_acquired_catalog_and_farm_scope():
    from fairy.agents.jev.entities import choices
    t=NS(class_name='SeasonPlanning',name='select_crop');arg=lambda n:NS(name=n)
    catalog=NS(op_type='TOOL',tool_name='SeasonPlanning__get_crop_options',tool_args={'farm_id':'a'},content={'maize':{'seed_type':'MAIZE_201'},'soybean':{'seed_type':'SOYBEAN_901'}})
    report=NS(op_type='TOOL',tool_name='SeasonPlanning__get_season_context',tool_args={'farm_id':'b'},content={'soil_report':{'report_id':'foreign'}})
    assert choices(t,arg('crop_id'),{'farm_id':'a'},[catalog])[0]==['maize','soybean']
    assert choices(t,arg('cultivar_id'),{'farm_id':'a','crop_id':'maize'},[catalog])[0]==['MAIZE_201']
    assert choices(t,arg('crop_id'),{'farm_id':'b'},[catalog])[0]==[]
    assert choices(t,arg('report_id'),{'farm_id':'a'},[catalog,report])[0]==[]
