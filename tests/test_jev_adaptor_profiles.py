"""The comparison flag must separate wire policies, not just change a label."""
import pytest
from test_jev_agent import _run, TOOL_QUESTION_ID, _ScriptedJev
from test_jev_new_tools import setup, SCENES
from fairy.agents.jev.menu import build_tool_menus, dependent_menu
from fairy.controllers.agent_builder import build_controller_agent


def test_default_baseline_preserves_historical_count_and_fanout():
    agent, workflow, client = _run([
        {TOOL_QUESTION_ID: 'Robot0__inspect_emergence'},
        {'arg__start_ridge': 'ridge 62', 'arg__end_ridge': '4 ridges'},
        {TOOL_QUESTION_ID: 'Robot0__inspect_emergence',
         'arg__Robot0__inspect_emergence__start_ridge': 'ridge 62',
         'arg__Robot0__inspect_emergence__end_ridge': '4 ridges'},
    ], max_tool_calls=2)
    actions = [s for s in workflow.dag.values() if s.op_type in ('TOOL', 'TOOL_ERROR')]
    assert len(actions) == 2
    assert all(s.tool_args == {'start_ridge': 62, 'end_ridge': 65} for s in actions)
    assert all('Invalid ridge range' in str(s.content) for s in actions)
    assert len(client.requests) == 3
    assert agent.telemetry['fanout_hits'] == 1
    assert all('jev_execution_guidance' not in state for state, _ in client.requests)
    assert 'jev_execution_guidance' not in client.requests[0][1]['next_action']['instructions']
    assert agent.telemetry['tool_adaptor_profile'] == 'manos-compatible-v1'
    assert agent.telemetry['enforced_tool_adaptor'] is False
    assert agent.telemetry['seed_amount_adapter_version'] is None


@pytest.mark.parametrize('enabled', [False, True])
def test_seed_route_is_opt_in(enabled):
    _, agent = setup(SCENES[0])
    agent.enforced_tool_adaptor = enabled
    native = agent.tools_map['TractorApp__load_seeds']
    assert dependent_menu(native, enforced_tool_adaptor=enabled) == enabled
    # Ordinary baseline still asks both count and variety; no derived quantity.
    if not enabled:
        _, workflow, client = _run([
            {TOOL_QUESTION_ID: 'TractorApp__load_seeds'},
            {'arg__seed_type': 'HEINONG84', 'arg__count': '300000'},
        ], max_tool_calls=1, task='Load seeds for 64 ridges.')
        assert {'arg__seed_type', 'arg__count'} == set(client.requests[1][1])
        assert any(s.tool_name == 'TractorApp__load_seeds' and s.tool_args['count'] == 300000 for s in workflow.dag.values())


def test_chinese_completion_baseline_keeps_two_refusals():
    agent, _, client = _run([{TOOL_QUESTION_ID: 'done'}]*3, task='播种全部64垄。')
    assert agent.telemetry['done_refusals'] == 2
    assert agent.telemetry['completion_language_version'] == 'zh-en-done-v1'


def test_enhanced_completion_uses_same_language_facts_but_removes_premature_done():
    agent, _, client = _run([{TOOL_QUESTION_ID: 'WeatherApp__get_current_weather'}],
                           max_tool_calls=1, task='播种全部64垄。', enforced_tool_adaptor=True)
    state, questions = client.requests[0]
    assert 'done' not in questions['next_action']['criteria']
    assert state['management_progress']['completion_allowed'] is False
    assert any('not planted' in p for p in state['management_progress']['remaining_requirements'])
    assert agent.telemetry['tool_adaptor_profile'] == 'enforced-v2'


@pytest.mark.parametrize('value', ['false', 1, None])
def test_no_truthy_string_or_invalid_flag(value):
    scene, _ = setup(SCENES[0])
    with pytest.raises(ValueError, match='must be boolean'):
        build_controller_agent('farm_jev', llm=_ScriptedJev([]), toolsets=scene.apps,
                               enforced_tool_adaptor=value)


def test_enhancement_rejected_for_llm_driven_controller():
    with pytest.raises(ValueError, match='requires farm_jev'):
        build_controller_agent('farm_llm_jev', llm=None, enforced_tool_adaptor=True)


def test_pure_llm_snapshot_keeps_pre_switch_input_policy():
    from fairy.agents.jev.execution_guidance import execution_guidance
    from fairy.controllers.engine import Engine
    scene, _ = setup(SCENES[0])
    agent = build_controller_agent('farm_llm_snapshot', llm=_ScriptedJev([]), toolsets=scene.apps)
    Engine(agent=agent, scenario=scene)
    state = agent._state()
    assert state['jev_execution_guidance'] == execution_guidance()
    assert agent.telemetry['tool_adaptor_profile'] == 'not-applicable'
    assert agent.telemetry['enforced_tool_adaptor'] is None
