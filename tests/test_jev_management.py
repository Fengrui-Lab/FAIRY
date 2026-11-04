from types import SimpleNamespace as NS
from datetime import datetime, timezone, timedelta
import copy
import pytest
from fairy.agents.jev import management as M

RICE = ('管理水稻全季，三轮施肥都按尿素产品质量填写：p1三轮依次为300、300、300千克/公顷；'
        'p2三轮依次为300、300、300千克/公顷。每隔7个UTC日分别读取两田水分。'
        '约在各田移栽后第18日，确认处于分蘖后，各按尿素产品300千克/公顷完成第二轮肥。'
        '约在各田移栽后第38日，复核生育阶段后，各按尿素产品300千克/公顷完成第三轮肥。收获并入库。')
MAIZE = ('完成玉米全季，施基肥200公斤。参考追肥安排为第25日300公斤、第50日300公斤。'
         '参考灌溉安排为第20日50毫米、第60日50毫米、第70日50毫米、第80日50毫米。收获全部64垄并入库。')
def step(name, args, receipt, time='2026-01-03 17:00:00', failed=False):
    return NS(tool_name=name, tool_args=args, content=receipt, time=time, op_type='TOOL_ERROR' if failed else 'TOOL')
def rice_facts():
    return dict(plots=[dict(plot_id='p1',area_m2=1000,planted=True,harvested=False),dict(plot_id='p2',area_m2=1500,planted=True,harvested=False)],
                machines={'tractor':dict(fertilizer_kg=5.,fertilizer_capacity_kg=80.)},
                inventory={'fertilizer':{'stock_kg':220.}},steps=[
                 step('PaddyOpsApp__apply_fertilizer',{'plot_id':'p1'},{'status':'ok','product_kg':30.}),
                 step('PaddyOpsApp__apply_fertilizer',{'plot_id':'p2'},{'status':'ok','product_kg':45.})])
def native(cls,tool):return NS(class_name=cls,name=tool,class_instance=NS(name='TractorApp'))

def test_rice_80_plus_5_counterexample_is_automatically_70():
    f=rice_facts();p=M.task_plan(RICE,f,0);a=M.ledger(p,f);n=native('PaddyOpsApp','load_fertilizer')
    before=copy.deepcopy(f)
    assert M.derive_fertilizer(n,'kg',{},p,a,f)[0]==70
    assert M.fertilizer_resources(n,f)['load_limit_kg']==75
    assert f['inventory']==before['inventory'] and f['machines']==before['machines']
    assert M.derive_fertilizer(native('PaddyOpsApp','apply_fertilizer'),'kg_per_ha',{'plot_id':'p1'},p,a,f)[0]==300


@pytest.mark.parametrize('stock,carried,expected',[(20.,5.,20.),(220.,75.,None),(220.,80.,None),(0.,5.,None)])
def test_batch_load_is_demand_and_capacity_bounded(stock,carried,expected):
    f=rice_facts();f['inventory']['fertilizer']['stock_kg']=stock;f['machines']['tractor']['fertilizer_kg']=carried
    p=M.task_plan(RICE,f,0);v=M.derive_fertilizer(native('PaddyOpsApp','load_fertilizer'),'kg',{},p,M.ledger(p,f),f)
    assert (v[0] if v else None)==expected


def test_failed_or_partial_receipt_does_not_finish_round():
    f=rice_facts();f['steps']=[step('PaddyOpsApp__apply_fertilizer',{'plot_id':'p1'},'capacity error',failed=True),
        step('PaddyOpsApp__apply_fertilizer',{'plot_id':'p1'},{'status':'ok','product_kg':15.})]
    p=M.task_plan(RICE,f,0);a=M.ledger(p,f)
    assert M.paddy_round(p,a,'p1')=={'index':1,'remaining_kg_ha':150.}
    assert M.paddy_round(p,a,'p2')=={'index':1,'remaining_kg_ha':300.}


def test_maize_exact_dose_and_remaining_ridges():
    f=dict(ridges=[dict(ridge_id=i) for i in range(64)],steps=[],inventory={'fertilizer_kg':600.},machines={'TractorApp':{'fertilizer_spreader_kg':300.}})
    p=M.task_plan(MAIZE,f,64);a=M.ledger(p,f);r=M.ridge_round(p,a)
    assert r['per_ridge_kg']==4.6875 and sum(r['remaining_by_ridge_kg'].values())==300
    assert M.derive_fertilizer(native('TractorApp','apply_fertilizer'),'kg_per_ridge',{'start_ridge':0},p,a,f)[0]==4.6875
    f['steps']=[step('TractorApp__base_fertilize',{}, {'fertilizer_used_kg':200.}),
                step('TractorApp__apply_fertilizer',{}, {'fertilized_ridges':list(range(60)),'fertilizer_used_kg':281.25})]
    a=M.ledger(p,f);r=M.ridge_round(p,a)
    assert list(r['remaining_by_ridge_kg'])==[60,61,62,63]
    f['steps'].append(step('TractorApp__apply_fertilizer',{}, {'fertilized_ridges':[60,61,62,63],'fertilizer_used_kg':18.75}))
    assert M.ridge_round(p,M.ledger(p,f))['index']==2


def test_utc_schedule_and_bounded_wait_have_no_hidden_state():
    f=rice_facts();f['steps'] += [step('PaddyOpsApp__transplant',{'plot_id':'p1'},{'completed':True}),
                                step('PaddyOpsApp__transplant',{'plot_id':'p2'},{'completed':True})]
    now=datetime(2026,1,10,12,tzinfo=timezone.utc).timestamp()
    c=M.management_context(RICE,f,now,0)
    assert c['clocks']['utc'].endswith('+00:00') and c['clocks']['utc_plus_08'].endswith('+08:00')
    assert any(w['kind']=='water_check' and w['status'].startswith('DUE') for w in c['windows'])
    assert c['wait_limit_seconds']==86400
    assert c['plan']['rice_fertilizer_days']==[18,38]


def test_ambiguous_or_missing_prescriptions_do_not_invent_doses():
    f=rice_facts();p=M.task_plan('照顾水稻全季，按实际情况施肥。',f,0)
    assert p['kind'] is None
    assert M.derive_fertilizer(native('PaddyOpsApp','apply_fertilizer'),'kg_per_ha',{'plot_id':'p1'},p,M.ledger(p,f),f) is None


def test_native_rice_capacity_rejection_then_calculated_load_succeeds():
    from test_jev_new_tools import setup
    from fairy.controllers.engine import Engine
    from fairy.agents.jev.snapshot import build_snapshot
    from fairy.scenarios.workflow import Workflow
    scene, agent = setup('scenario_rice_l3_normal')
    Engine(agent=agent,scenario=scene)
    tool = agent.tools_map['PaddyOpsApp__load_fertilizer']
    world = tool.class_instance.world
    world.machine('tractor').fertilizer_kg = 5.
    world.field.fertilizer_kg = 220.
    with pytest.raises(ValueError,match='capacity exceeded'):
        tool(kg=80.,product_id='urea')
    _, f=build_snapshot(scene.apps,Workflow(),scene.start_time)
    f['steps']=rice_facts()['steps']
    plan=M.task_plan(RICE,f,0)
    value,_=M.derive_fertilizer(tool,'kg',{},plan,M.ledger(plan,f),f)
    assert value==70.
    receipt=tool(kg=value,product_id='urea')
    assert receipt['loaded_kg']==75.
    assert world.field.fertilizer_kg==150.


def test_native_maize_round_covers_all_64_without_hand_picking_dose():
    from fairy.scenarios.registry import get_scenario_class
    from fairy.controllers.agent_builder import build_controller_agent
    from fairy.controllers.engine import Engine
    from fairy.agents.jev.menu import build_tool_menus
    from fairy.agents.jev.snapshot import build_snapshot
    from fairy.scenarios.workflow import Workflow
    from test_jev_agent import _ScriptedJev
    scene=get_scenario_class('scenario_maize_l3_normal')(seed=0,detailed_briefing=True);scene.setup()
    agent=build_controller_agent('farm_jev',llm=_ScriptedJev([]),toolsets=scene.apps,enforced_tool_adaptor=True)
    engine=Engine(agent=agent,scenario=scene)
    task=engine._resolve_agent_task()
    load=agent.tools_map['TractorApp__load_fertilizer']
    assert load(kg=300.)['fertilizer_spreader_kg']==300.
    agent.tool_menus=build_tool_menus(agent.tools_map,task_text=task,num_ridges=64,enforced_tool_adaptor=True)
    successful=[];asked=[]
    def ask(kind,state,questions):
        asked.extend(questions)
        return {k:dict(choice=list(q['criteria'])[0] if k=='arg__start_ridge' else list(q['criteria'])[-1],confidence=.9) for k,q in questions.items()}
    agent._ask=ask
    for _ in range(7):
        _, f=build_snapshot(scene.apps,Workflow(),agent.time_manager.time());f['steps']=successful
        agent._facts=f;agent._management=M.management_context(task,f,agent.time_manager.time(),64)
        args,_=agent._jev_arguments({'task':task},'TractorApp__apply_fertilizer')
        assert args['kg_per_ridge']==4.6875
        receipt=agent.tools_map['TractorApp__apply_fertilizer'](**args)
        assert receipt.get('status')=='ok', receipt
        successful.append(step('TractorApp__apply_fertilizer',args,receipt))
    assert {i for s in successful for i in s.content['fertilized_ridges']}==set(range(64))
    assert sum(s.content['fertilizer_used_kg'] for s in successful)==300.
    assert 'arg__kg_per_ridge' not in asked
    assert agent.telemetry['tool_adaptor_profile']=='enforced-v2'


def test_agent_fills_rice_quantity_without_asking_jev_and_keeps_valid_scopes():
    from test_jev_new_tools import setup
    from fairy.agents.jev.menu import build_tool_menus
    scene,agent=setup('scenario_rice_l3_normal');agent.enforced_tool_adaptor=True
    f=rice_facts();agent._facts=f;agent._management=M.management_context(RICE,f,0,0)
    agent.tool_menus=build_tool_menus(agent.tools_map,task_text=RICE,num_ridges=0,enforced_tool_adaptor=True)
    questions=[]
    def ask(kind,state,qs):
        questions.extend(qs)
        return {k:dict(choice=list(q['criteria'])[0],confidence=.9) for k,q in qs.items()}
    agent._ask=ask
    args,_=agent._jev_arguments({'task':RICE},'PaddyOpsApp__load_fertilizer')
    assert args=={'product_id':'urea','kg':70.}
    assert 'arg__kg' not in questions
    # Supplying the whole round makes load unnecessary, while apply becomes feasible.
    agent._facts['machines']['tractor']['fertilizer_kg']=75.
    agent._snapshot_task=RICE
    options=agent._management_criteria({'done':'done','PaddyOpsApp__load_fertilizer':'load','PaddyOpsApp__apply_fertilizer':'apply'})
    assert 'done' not in options and 'PaddyOpsApp__load_fertilizer' not in options
    assert 'PaddyOpsApp__apply_fertilizer' in options


def test_closed_utc_canal_is_not_offered_as_immediate_irrigation():
    f=rice_facts();f['inventory']['channels']=[dict(channel_id='supply',open_hour=6,close_hour=20,flow_m3_hour=80.,efficiency=.9,quota_m3=12000.,withdrawn_m3=0.,blockage_fraction=0.,connected_plots=['p1','p2'])]
    now=datetime(2026,1,1,3,20,tzinfo=timezone.utc).timestamp()
    context=M.management_context(RICE,f,now,0);canal=context['canal_limits'][0]
    assert not canal['is_open'] and canal['seconds_until_open']==9600.
    assert '11:20' in context['clocks']['utc_plus_08']
    assert context['wait_limit_seconds']==9600.
    open_time=datetime(2026,1,1,19,30,tzinfo=timezone.utc).timestamp()
    cap=M.canal_limits(f,open_time)[0]['max_delivery_mm_by_plot']
    assert cap['p1']==36. and cap['p2']==24.


def test_unknown_plan_load_menu_still_cannot_exceed_free_capacity():
    from test_jev_new_tools import setup
    from fairy.agents.jev.menu import build_tool_menus
    _,agent=setup('scenario_rice_l3_normal');agent.enforced_tool_adaptor=True
    f=rice_facts();agent._facts=f;agent._management=M.management_context('按观测决定施肥',f,0,0)
    agent.tool_menus=build_tool_menus(agent.tools_map,task_text='库存220公斤，容量80公斤',num_ridges=0,enforced_tool_adaptor=True)
    menu=agent.tool_menus['PaddyOpsApp__load_fertilizer'];arg=next(a for a in menu.args if a.name=='kg')
    opts=agent._arg_options(menu,arg,{})
    assert opts and all(0 < v <= 75 for v in opts.values())
    assert 80 not in opts.values() and 220 not in opts.values()


def test_wait_options_end_before_task_deadline_and_manager_is_read_only():
    from test_jev_new_tools import setup
    from fairy.controllers.engine import Engine
    from fairy.agents.jev.menu import build_tool_menus, DURATION_ARG
    scene,agent=setup('scenario_rice_l3_normal');agent.enforced_tool_adaptor=True
    Engine(agent=agent,scenario=scene)
    f=rice_facts();agent._facts=f
    now=datetime(2026,1,10,12,tzinfo=timezone.utc).timestamp()
    f['steps'] += [step('PaddyOpsApp__transplant',{'plot_id':'p1'},{'completed':True})]
    agent._management=M.management_context(RICE,f,now,0)
    assert agent._management['wait_limit_seconds']==86400
    agent.tool_menus=build_tool_menus(agent.tools_map,task_text=RICE,num_ridges=0,enforced_tool_adaptor=True)
    menu=agent.tool_menus['SystemApp__advance_time'];arg=next(a for a in menu.args if a.name==DURATION_ARG)
    before=[copy.deepcopy(a.get_state()) for a in scene.apps]
    opts=agent._arg_options(menu,arg,{})
    scale=dict(days=86400,hours=3600,minutes=60,seconds=1)
    assert all(0 < sum(v[k]*scale[k] for k in v) <= 86400 for v in opts.values())
    assert before==[a.get_state() for a in scene.apps]
    agent.time_manager=NS(time=lambda:now)
    criteria=agent._management_criteria({'PaddyOpsApp__read_water_sensors':'read','done':'done'})
    assert criteria['PaddyOpsApp__read_water_sensors'].startswith('[DUE management')


def test_done_is_available_after_actual_visible_requirements_complete():
    from test_jev_new_tools import setup
    _,agent=setup('scenario_rice_l3_normal');agent.enforced_tool_adaptor=True
    f=rice_facts()
    for p in f['plots']:p['harvested']=True
    agent._facts=f;agent._snapshot_task='完成水稻收获与入库。'
    agent._management=M.management_context(agent._snapshot_task,f,0,0)
    assert 'done' in agent._management_criteria({'done':'done'})


def test_equivalent_fertigation_tool_uses_same_product_ledger_not_a_second_budget():
    task=MAIZE+'单独追肥不额外添加灌溉水。'
    f=dict(ridges=[dict(ridge_id=i,planted=True) for i in range(64)],steps=[],inventory={'fertilizer_kg':600.},machines={})
    p=M.task_plan(task,f,64);a=M.ledger(p,f);n=native('FarmWorldApp','apply_fertigation')
    assert M.derive_fertilizer(n,'nutrient_amount',{'start_ridge':0},p,a,f)[0]==.15625
    assert M.derive_fertilizer(n,'water_mm',{},p,a,f)[0]==0.
    f['steps']=[step('FarmWorldApp__apply_fertigation',{}, {'fertigated_ridges':list(range(64)),'fertilizer_kg_used':300.})]
    assert M.ridge_round(p,M.ledger(p,f))['index']==2
    no_zero=M.task_plan(MAIZE,f,64)
    assert M.derive_fertilizer(n,'water_mm',{},no_zero,M.ledger(no_zero,f),f) is None


def test_explicit_pest_crop_and_daily_maturity_checks_are_scheduled():
    task=RICE+'每14天检查两田长势和生育阶段。每14天逐田检查虫、病、草。移栽后约第85日起每天检查成熟。'
    f=rice_facts();f['steps'].append(step('PaddyOpsApp__transplant',{'plot_id':'p1'},{'completed':True}))
    now=datetime(2026,4,1,tzinfo=timezone.utc).timestamp()
    c=M.management_context(task,f,now,0)
    assert {'crop_check','pest_check','maturity_check'} <= {w['kind'] for w in c['windows']}
    assert all(w.get('status') for w in c['windows'])


def test_native_fertigation_route_also_has_no_dose_or_carrier_model_questions():
    from fairy.scenarios.registry import get_scenario_class
    from fairy.controllers.agent_builder import build_controller_agent
    from fairy.controllers.engine import Engine
    from fairy.agents.jev.snapshot import build_snapshot
    from fairy.agents.jev.menu import build_tool_menus
    from fairy.scenarios.workflow import Workflow
    from test_jev_agent import _ScriptedJev
    scene=get_scenario_class('scenario_maize_l3_normal')(seed=0,detailed_briefing=True);scene.setup()
    agent=build_controller_agent('farm_jev',llm=_ScriptedJev([]),toolsets=scene.apps,enforced_tool_adaptor=True)
    engine=Engine(agent=agent,scenario=scene);task=engine._resolve_agent_task()
    _,f=build_snapshot(scene.apps,Workflow(),agent.time_manager.time());agent._facts=f
    agent._management=M.management_context(task,f,agent.time_manager.time(),64)
    agent.tool_menus=build_tool_menus(agent.tools_map,task_text=task,num_ridges=64,enforced_tool_adaptor=True)
    asked=[]
    def ask(kind,state,qs):
        asked.extend(qs)
        return {k:dict(choice=list(q['criteria'])[0] if k=='arg__start_ridge' else list(q['criteria'])[-1],confidence=.9) for k,q in qs.items()}
    agent._ask=ask
    args,_=agent._jev_arguments({'task':task},'FarmWorldApp__apply_fertigation')
    assert args=={'start_ridge':0,'end_ridge':63,'nutrient_amount':.15625,'water_mm':0.}
    assert set(asked)=={'arg__start_ridge','arg__end_ridge'}
    receipt=agent.tools_map['FarmWorldApp__apply_fertigation'](**args)
    assert receipt['status']=='ok' and receipt['fertilizer_kg_used']==300.
    assert receipt['carrier_water_mm']==0.


def test_negated_and_conflicting_prescriptions_are_not_automatic_plans():
    f=rice_facts()
    assert M.task_plan(RICE+'本次不要施肥。',f,0)['kind'] is None
    assert M.task_plan(RICE+'p1三轮依次为100、100、100千克/公顷。',f,0)['kind'] is None


def test_native_canal_closing_limit_and_closed_action_filter_match_real_tool():
    from test_jev_new_tools import setup
    from fairy.controllers.engine import Engine
    from fairy.agents.jev.snapshot import build_snapshot
    from fairy.scenarios.workflow import Workflow
    scene,agent=setup('scenario_rice_l3_normal');agent.enforced_tool_adaptor=True
    engine=Engine(agent=agent,scenario=scene);task=engine._resolve_agent_task()
    tool=agent.tools_map['PaddyOpsApp__irrigate'];world=tool.class_instance.world
    supply=next(c for c in world.field.channels if c.channel_id=='supply')
    supply.open_hour,supply.close_hour=6,20
    _,f=build_snapshot(scene.apps,Workflow(),agent.time_manager.time());agent._facts=f
    agent._snapshot_task=task;agent._management=M.management_context(task,f,agent.time_manager.time(),0)
    assert not agent._management['canal_limits'][0]['is_open']
    assert 'PaddyOpsApp__irrigate' not in agent._management_criteria({'PaddyOpsApp__irrigate':'irrigate','SystemApp__advance_time':'wait'})
    world.run_job(int(19.5*3600))
    _,f=build_snapshot(scene.apps,Workflow(),agent.time_manager.time())
    cap=M.canal_limits(f,agent.time_manager.time())[0]['max_delivery_mm_by_plot']['p1']
    assert cap==36.
    with pytest.raises(ValueError,match='job must fit UTC'):
        tool(plot_id='p1',water_mm=100.)
    result=tool(plot_id='p1',water_mm=cap)
    assert result['status']=='ok' and result['delivered_mm']==36.
