"""Offline checks for farm_llm_jev: the LLM runs the farm, Jev is its ask_jev tool (no API calls)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletionMessage
from openai.types.chat.chat_completion_message_function_tool_call import (
    ChatCompletionMessageFunctionToolCall,
    Function,
)

from fairy.agents.jev.llm_driven_agent import ASK_JEV_TOOL, JEV_PRICE_PER_INPUT_TOKEN
from fairy.controllers.agent_builder import AgentBuilder, build_controller_agent
from fairy.controllers.engine import Engine
from fairy.controllers.run_artifacts import metric_totals
from fairy.scenarios.baseline_farm_world.scenario_field_prep import (
    ScenarioFarmWorldFieldPrep,
)

ASK = {
    "state": {"date": "2026-05-01", "soil_moisture": "high", "rain_next_3_days_mm": 25},
    "question": "Should the farm agent plant now or wait?",
    "options": ["plant now", "wait 3 days"],
}


class _FakeJev:
    provider = "typesafe"
    model = "fake-jev"

    def __init__(self):
        self.requests = []

    def system_one(self, state, questions):
        self.requests.append((state, questions))
        (qid, question), = questions.items()
        options = list(question["criteria"])
        return SimpleNamespace(
            choices={qid: SimpleNamespace(
                choice=options[-1], confidence=0.8,
                probabilities={o: (0.8 if o == options[-1] else 0.2 / (len(options) - 1)) for o in options},
            )},
            usage=SimpleNamespace(input_tokens=200, output_tokens=5),
            model="fake-jev-1",
            request_id="req",
        )


class _ScriptedLLM:
    """The main LLM: each reply is a list of (tool, arguments) calls, or None for a final answer."""

    provider = "openai"
    model = "fake-llm"
    max_output_tokens = 100
    parallel_tool_calls = False

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat_completion(self, messages, tools=None):
        self.calls.append((messages, tools))
        reply = self.replies.pop(0) if self.replies else None
        tool_calls = [
            ChatCompletionMessageFunctionToolCall(
                id=f"call_{len(self.calls)}_{i}", type="function",
                function=Function(name=name, arguments=args if isinstance(args, str) else json.dumps(args)),
            )
            for i, (name, args) in enumerate(reply or [])
        ]
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=ChatCompletionMessage(
                    role="assistant", content=None if tool_calls else "done", tool_calls=tool_calls or None
                ),
                finish_reason="tool_calls" if tool_calls else "stop",
            )],
            usage=SimpleNamespace(
                prompt_tokens=1000, completion_tokens=10, total_tokens=1010,
                prompt_tokens_details=SimpleNamespace(cached_tokens=600),
            ),
        )


def _run(replies, task="Check the 3-day forecast, then load 200 kg of fertilizer.", done_check=False, max_tool_calls=20):
    scenario = ScenarioFarmWorldFieldPrep(scenario_input=task)
    scenario.setup()
    llm, jev = _ScriptedLLM(replies), _FakeJev()
    agent = build_controller_agent(
        "farm_llm_jev", llm=llm, toolsets=scenario.apps, jev_llm=jev, done_check=done_check
    )
    engine = Engine(agent=agent, scenario=scenario)
    try:
        workflow = engine.run_scenario_agent(max_tool_calls=max_tool_calls, timeout_seconds=60, setup_scenario=False)
    except Exception:
        workflow = agent.workflow
    return agent, workflow, llm, jev


def _events(agent, kind):
    return [e for e in agent.runtime_events if e.get("event_type") == kind]


def test_farm_llm_jev_is_listed() -> None:
    assert "farm_llm_jev" in AgentBuilder().list_agents()


def test_llm_sees_the_baseline_tools_plus_ask_jev() -> None:
    agent, _, llm, _ = _run([None])
    scenario = ScenarioFarmWorldFieldPrep(scenario_input="x")
    scenario.setup()
    baseline = build_controller_agent("farm_baseline_react", llm=llm, toolsets=scenario.apps)
    names = [t["function"]["name"] for t in llm.calls[0][1]]
    assert names == [t["function"]["name"] for t in baseline.tool_schemas] + [ASK_JEV_TOOL]
    # Same system prompt as the baseline: Jev is only explained in the tool description.
    assert llm.calls[0][0][0]["content"].startswith(baseline.messages.messages[0]["content"])


def test_ask_jev_returns_pick_and_is_not_a_farm_action() -> None:
    agent, workflow, llm, jev = _run([
        [(ASK_JEV_TOOL, ASK)],
        [("WeatherApp__get_forecast", {"days": 3})],
        None,
    ])
    # Jev got the LLM's own state and its options, nothing else.
    state, questions = jev.requests[0]
    assert state == ASK["state"]
    assert questions["question"]["instructions"] == ASK["question"]
    assert list(questions["question"]["criteria"]) == ASK["options"]
    # The answer goes back to the LLM as the tool result.
    tool_msg = next(m for m in llm.calls[1][0] if m.get("role") == "tool")
    assert json.loads(tool_msg["content"]) == {
        "pick": "wait 3 days", "probabilities": {"plant now": 0.2, "wait 3 days": 0.8}, "confidence": 0.8,
    }
    # Only farm tools are in the workflow and count as actions.
    tools = [s.tool_name for s in workflow.dag.values() if s.op_type in ("TOOL", "TOOL_ERROR")]
    assert tools == ["WeatherApp__get_forecast"]
    assert agent.tool_call_count == 1 and agent.stop_reason == "agent_finished"
    # Logged and counted.
    (event,) = _events(agent, "ask_jev")
    assert event["question"] == ASK["question"] and event["pick"] == "wait 3 days"
    assert event["confidence"] == 0.8 and event["state_chars"] == len(json.dumps(ASK["state"]))
    assert event["cost_usd"] == pytest.approx(200 * JEV_PRICE_PER_INPUT_TOKEN)
    t = agent.telemetry
    assert t["ask_jev_calls"] == 1 and t["farm_actions"] == 1 and t["ask_jev_per_action"] == 1.0
    assert t["actions_after_ask"] == 1 and t["jev_input_tokens"] == 200
    assert t["tool_calls"] == 1  # the baseline's own counter: farm tools only
    assert t["llm_tokens"] == {"prompt_tokens": 3000, "cached_tokens": 1800, "completion_tokens": 30}
    # Run-report totals include Jev's tokens next to the LLM's.
    assert metric_totals(agent.messages.runtime_metrics)["token_usage"]["prompt_tokens"] == 3200


def test_bad_ask_goes_back_as_an_error_and_the_run_continues() -> None:
    agent, workflow, llm, jev = _run([
        [(ASK_JEV_TOOL, {"state": {"a": 1}, "question": "Which?", "options": ["only one"]})],
        [(ASK_JEV_TOOL, "not json")],
        None,
    ])
    assert jev.requests == []
    tool_msgs = [m for m in llm.calls[2][0] if m.get("role") == "tool"]
    assert all("error" in json.loads(m["content"]) for m in tool_msgs) and len(tool_msgs) == 2
    assert agent.telemetry["ask_jev_calls"] == 0 and agent.telemetry["ask_jev_errors"] == 2
    assert agent.stop_reason == "agent_finished" and len(workflow) == 1  # only the USER step


def test_asks_do_not_use_up_the_action_limit() -> None:
    agent, _, _, jev = _run(
        [[(ASK_JEV_TOOL, ASK)]] * 4 + [[("WeatherApp__get_current_weather", {})]] * 5,
        max_tool_calls=2,
    )
    assert len(jev.requests) == 4
    assert agent.stop_reason == "max_tool_calls" and agent.tool_call_count == 2


def test_done_check_refuses_early_done() -> None:
    agent, _, llm, _ = _run([None, None, None], task="Plant ridges 0-63.", done_check=True)
    assert len(llm.calls) == 3 and agent.done_refusals == 2
    assert agent.stop_reason == "agent_finished"
    assert agent.response_policy()["done_check"] is True


def test_needs_a_jev_client_and_only_this_agent_takes_one() -> None:
    scenario = ScenarioFarmWorldFieldPrep(scenario_input="x")
    scenario.setup()
    with pytest.raises(ValueError):
        build_controller_agent("farm_llm_jev", llm=_ScriptedLLM([]), toolsets=scenario.apps)
    with pytest.raises(ValueError):
        build_controller_agent("farm_baseline_react", llm=_ScriptedLLM([]), toolsets=scenario.apps, jev_llm=_FakeJev())
