"""Range adaptation regression: never synthesize an out-of-field endpoint."""
import pytest

from fairy.agents.jev.menu import build_tool_menus
from test_jev_agent import _run, TOOL_QUESTION_ID
from test_jev_new_tools import setup as baseline_setup, SCENES

def setup(sid):
    scene, agent = baseline_setup(sid)
    agent.enforced_tool_adaptor = True
    return scene, agent


@pytest.mark.parametrize('start,count,end', [(0, 64, 63), (62, 2, 63), (63, 1, 63)])
def test_robot_range_counts_follow_start(start, count, end):
    _, agent = setup(SCENES[0])
    agent.tool_menus = build_tool_menus(agent.tools_map, task_text='Inspect 64 ridges.', num_ridges=64)
    menu = next(m for n, m in agent.tool_menus.items() if n.endswith('__inspect_emergence'))
    calls = []

    def ask(kind, state, questions):
        calls.append(questions)
        answers = {}
        for key, question in questions.items():
            options = list(question['criteria'])
            pick = f'ridge {start}' if key == 'arg__start_ridge' else ('1 ridge' if count == 1 else f'{count} ridges')
            assert pick in options
            answers[key] = {'choice': pick, 'confidence': .8}
        return answers

    agent._ask = ask
    args, confidence = agent._jev_arguments({}, menu.tool_name)
    assert args == {'start_ridge': start, 'end_ridge': end}
    assert set(calls[0]) == {'arg__start_ridge'}
    assert list(calls[1]['arg__end_ridge']['criteria']) == ['1 ridge'] + [f'{n} ridges' for n in range(2, 65-start)]
    assert len(confidence) == 2


def test_actual_robot_boundary_call_and_speculation():
    agent, workflow, client = _run([
        {TOOL_QUESTION_ID: 'Robot0__inspect_emergence'},
        {'arg__start_ridge': 'ridge 62'},
        {'arg__end_ridge': '2 ridges'},
        {TOOL_QUESTION_ID: 'Robot0__inspect_emergence',
         'arg__Robot0__inspect_emergence__start_ridge': 'ridge 62'},
        {'arg__end_ridge': '2 ridges'},
    ], max_tool_calls=2, enforced_tool_adaptor=True)
    steps = [s for s in workflow.dag.values() if s.op_type in ('TOOL', 'TOOL_ERROR')]
    assert len(steps) == 2
    assert all(s.tool_args == {'start_ridge': 62, 'end_ridge': 63} for s in steps)
    assert 'Invalid ridge range' not in str([s.content for s in steps])
    for _, questions in client.requests:
        assert 'arg__Robot0__inspect_emergence__end_ridge' not in questions
        if 'arg__end_ridge' in questions:
            assert set(questions['arg__end_ridge']['criteria']) == {'1 ridge', '2 ridges'}
    assert agent.stop_reason == 'max_tool_calls'
    assert agent.telemetry['ridge_range_adapter_version'] == 'ridge-range-bounded-v1'


def test_out_of_menu_count_never_reaches_native_tool():
    _, workflow, _ = _run([
        {TOOL_QUESTION_ID: 'Robot0__inspect_emergence'},
        {'arg__start_ridge': 'ridge 62'},
        {'arg__end_ridge': '4 ridges'},
    ], max_tool_calls=1, enforced_tool_adaptor=True)
    assert not [s for s in workflow.dag.values() if s.op_type in ('TOOL', 'TOOL_ERROR')]


@pytest.mark.parametrize('start,end', [(62, 65), (-1, 0), (64, 64), (4, 3), (False, 1), (0, 4)])
def test_adapter_invariant_rejects_out_of_bounds_or_pass_width(start, end):
    _, agent = setup(SCENES[0])
    agent.tool_menus = build_tool_menus(agent.tools_map, task_text='Plant 64 ridges.', num_ridges=64)
    menu = next(m for n, m in agent.tool_menus.items() if n.endswith('__plant_seeds'))
    with pytest.raises(ValueError):
        agent._validate_ridge_ranges(menu, {'start_ridge': start, 'end_ridge': end})


def test_shared_farm_range_resolves_dependencies_even_with_reversed_schema():
    scenario, agent = setup(SCENES[1])
    scenario.farm_b.num_ridges = 10
    scenario.farm_b._ridges = scenario.farm_b._ridges[:10]
    agent.tool_menus = build_tool_menus(agent.tools_map, task_text='Plant 64 ridges at 4 cm.', num_ridges=64)
    menu = next(m for n, m in agent.tool_menus.items() if n.endswith('__plant_seeds'))
    menu.args.reverse()  # JSON schema order must not control dependency order.
    calls = []

    def ask(kind, state, questions):
        calls.extend(questions)
        answers = {}
        for key, question in questions.items():
            opts = list(question['criteria'])
            pick = {'arg__farm_id': 'farm_b', 'arg__start_ridge': 'ridge 8', 'arg__end_ridge': '2 ridges'}.get(key, opts[0])
            assert pick in opts
            if key == 'arg__end_ridge':
                assert opts == ['1 ridge', '2 ridges']
            answers[key] = {'choice': pick, 'confidence': .9}
        return answers

    agent._ask = ask
    args, _ = agent._jev_arguments({}, menu.tool_name)
    assert calls.index('arg__farm_id') < calls.index('arg__start_ridge') < calls.index('arg__end_ridge')
    assert args['farm_id'] == 'farm_b'
    assert (args['start_ridge'], args['end_ridge']) == (8, 9)
