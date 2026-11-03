from types import SimpleNamespace
from fairy.agents.jev.seed_candidates import seed_amount_hint

WORLD = SimpleNamespace(num_ridges=64, plants_per_ridge_from_spacing=lambda x: round(53600/x))
TASK = 'ridges 0–31: HEINONG84，seed_spacing_cm=7.9；ridges 32–63: HEINONG58，seed_spacing_cm=8.4'
def event(name, data):
    return dict(tool_name='TractorApp__'+name, content=data, op_type='TOOL')
def test_exact_quantity_and_no_observation():
    assert seed_amount_hint(WORLD,'HEINONG84',TASK,[],300000)[0] is None
    assert seed_amount_hint(WORLD,'HEINONG84',TASK,[event('get_status',dict(seed_hopper=0,seed_type=None))],300000)[0] == 217120

def test_remaining_demand_and_failure():
    steps=[event('get_status',dict(seed_hopper=30000,seed_type='HEINONG84')),
           event('plant_seeds',dict(planted_ridges=[0,1,2,3],seeds_used=27140)),
           event('plant_seeds',dict(error='rain',planted_ridges=[4]))]
    assert seed_amount_hint(WORLD,'HEINONG84',TASK,steps,300000)[0] == 187120

def test_conflict_and_receipt():
    steps=[event('get_status',dict(ok=True,error=None,data=dict(seed_hopper=12,seed_type='HEINONG58')))]
    value,note=seed_amount_hint(WORLD,'HEINONG84',TASK,steps,300000)
    assert value is None and 'another variety' in note

def test_capacity_and_ambiguous_plan():
    steps=[event('get_status',dict(seed_hopper=0,seed_type=None))]
    assert seed_amount_hint(WORLD,'HEINONG84',TASK,steps,100000)[0] == 100000
    assert seed_amount_hint(WORLD,'HEINONG84',TASK+';ridges 0-2: HEINONG84 seed_spacing_cm=7.9',steps,300000)[0] is None

def test_actual_agent_selects_variety_before_exact_amount():
    from test_jev_agent import _run, TOOL_QUESTION_ID
    agent, workflow, client = _run([
        {TOOL_QUESTION_ID: 'TractorApp__load_seeds'},
        {'arg__seed_type': 'HEINONG84'},
        {TOOL_QUESTION_ID: 'done'},
    ], task=TASK, enforced_tool_adaptor=True)
    amount_requests=[q for state,q in client.requests if 'arg__count' in q]
    assert not amount_requests
    assert any(s.tool_name == 'TractorApp__load_seeds' and s.tool_args['count'] == 217120
               for s in workflow.dag.values())


def test_snapshot_overrides_stale_hopper_and_caps_stock():
    snap=dict(machine=dict(seed_hopper=1000, seed_type='HEINONG84'),
              inventory=dict(seed_stock={'HEINONG84':5000}), ridges=[])
    value,_=seed_amount_hint(WORLD,'HEINONG84',TASK,[],300000,snapshot=snap)
    assert value == 5000

def test_chinese_completion_checks_use_same_facts():
    from fairy.agents.jev.done_check import done_problems
    facts=dict(ridges=[dict(ridge_id=0,planted=True,harvested=False),
                       dict(ridge_id=1,planted=False,harvested=False)],
               inventory=dict(harvest_grain_kg=10),machines={})
    assert done_problems('播种，收获，然后入库',facts,None) == done_problems('plant, harvest, store',facts,None)
    assert done_problems('检查天气',facts,None) == []
