"""Guidance changes input only; scenario detail, state and execution stay separate."""
import copy
import hashlib
import json

import pytest

from fairy.agents.agent.agent import AgentRunLimitExceeded
from fairy.agents.jev.execution_guidance import (
    EXECUTION_GUIDANCE_VERSION, EXECUTION_GUIDANCE_SHA256, EXECUTION_RULES,
    execution_guidance,
)
from fairy.agents.jev.menu import build_tool_menus
from fairy.controllers.agent_builder import build_controller_agent
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from test_jev_agent import _ScriptedJev, _ScriptedLLM, _run, TOOL_QUESTION_ID


def test_version_hash_and_payload_are_stable_and_isolated():
    assert EXECUTION_GUIDANCE_SHA256 == hashlib.sha256('\n'.join(EXECUTION_RULES).encode()).hexdigest()
    payload = execution_guidance()
    payload['rules'].clear()
    assert len(execution_guidance()['rules']) == 5


@pytest.mark.parametrize('detail', [False, True])
@pytest.mark.parametrize('state_mode', ['snapshot', 'history'])
def test_detail_does_not_select_guidance_or_rewrite_task(detail, state_mode):
    scenario = get_scenario_class('scenario_maize_l3_normal')(seed=0, detailed_briefing=detail)
    scenario.setup()
    client = _ScriptedJev([{TOOL_QUESTION_ID: 'WeatherApp__get_current_weather'}])
    agent = build_controller_agent('farm_jev', llm=client, toolsets=scenario.apps, enforced_tool_adaptor=True)
    agent.state_mode = state_mode
    engine = Engine(agent=agent, scenario=scenario)
    task = engine._resolve_agent_task()
    menus_before = build_tool_menus(agent.tools_map, task_text=task, num_ridges=agent._num_ridges, enforced_tool_adaptor=True)
    with pytest.raises(AgentRunLimitExceeded, match="max_tool_calls"):
        engine.run_scenario_agent(max_tool_calls=1, timeout_seconds=60, setup_scenario=False)
    assert client.requests[0][0]['task'] == task
    assert client.requests[0][0]['jev_execution_guidance'] == execution_guidance()
    assert scenario.detailed_briefing is detail
    assert agent.tool_call_count == 1
    assert agent.telemetry['execution_guidance_version'] == EXECUTION_GUIDANCE_VERSION
    assert agent.telemetry['execution_guidance_sha256'] == EXECUTION_GUIDANCE_SHA256
    # Read-only weather lookup adds no dynamic entities or task-derived values.
    assert agent.tool_menus == menus_before
    before = [copy.deepcopy(app.get_state()) for app in scenario.apps]
    workflow_before = copy.deepcopy(agent.workflow)
    agent._state()
    assert before == [app.get_state() for app in scenario.apps]
    assert agent.workflow.dag == workflow_before.dag


@pytest.mark.parametrize('mode', ['full', 'reflex'])
def test_guidance_is_visible_in_jev_and_hybrid_requests_without_extra_actions(mode):
    llm = _ScriptedLLM([('WeatherApp__get_forecast', {'days': 2})])
    agent, workflow, client = _run([
        {TOOL_QUESTION_ID: 'WeatherApp__get_forecast', '_confidence': .1},
        *([{'arg__days': '3'}] if mode == 'full' else []),
    ], max_tool_calls=1, fallback=llm, hybrid_mode=mode, enforced_tool_adaptor=True)
    assert all(state['jev_execution_guidance'] == execution_guidance() for state, _ in client.requests)
    assert EXECUTION_GUIDANCE_VERSION in json.dumps(llm.calls)
    assert agent.tool_call_count == 1
    assert [s.tool_name for s in workflow.dag.values() if s.op_type == 'TOOL'] == ['WeatherApp__get_forecast']
