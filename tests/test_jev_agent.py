"""Offline checks for the farm_jev controller (no TypeSafe API calls)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from fairy.agents.jev.jev_agent import TOOL_QUESTION_ID
from fairy.agents.jev.menu import MAX_CHOICE_OPTIONS
from fairy.controllers.agent_builder import AgentBuilder, build_controller_agent
from fairy.controllers.engine import Engine
from fairy.controllers.run_artifacts import metric_totals
from fairy.scenarios.baseline_farm_world.scenario_field_prep import (
    ScenarioFarmWorldFieldPrep,
)

TASK = "Check the 3-day forecast, then load 200 kg of fertilizer."


class _ScriptedJev:
    """Stands in for TypeSafeJevClient: answers each question from a script."""

    provider = "typesafe"
    model = "fake-jev"

    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    def system_one(self, state, questions):
        self.requests.append((state, questions))
        picks = self.script.pop(0)
        choices = {}
        for qid, question in questions.items():
            pick = picks[qid]
            assert pick in question["criteria"]
            assert len(question["criteria"]) <= MAX_CHOICE_OPTIONS
            choices[qid] = SimpleNamespace(
                choice=pick,
                confidence=picks.get("_confidence", 0.9),
                probabilities={k: (1.0 if k == pick else 0.0) for k in question["criteria"]},
            )
        return SimpleNamespace(
            choices=choices,
            usage=SimpleNamespace(input_tokens=100, output_tokens=10),
            model="fake-jev-1",
            request_id="req",
        )


class _ScriptedLLM:
    """Stands in for the fallback LLM: each reply is (tool name, arguments) or None (no tool call)."""

    model = "fake-llm"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat_completion(self, messages, tools=None):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        tool_calls = (
            [SimpleNamespace(function=SimpleNamespace(name=reply[0], arguments=json.dumps(reply[1])))]
            if reply else []
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=tool_calls, content="done"))],
            usage=SimpleNamespace(
                prompt_tokens=1000, completion_tokens=20,
                prompt_tokens_details=SimpleNamespace(cached_tokens=0),
            ),
        )


def _run(script, max_tool_calls=20, task=TASK, fallback=None):
    scenario = ScenarioFarmWorldFieldPrep(scenario_input=task)
    scenario.setup()
    llm = _ScriptedJev(script)
    agent = build_controller_agent(
        "farm_jev", llm=llm, toolsets=scenario.apps, fallback_llm=fallback
    )
    engine = Engine(agent=agent, scenario=scenario)
    try:
        workflow = engine.run_scenario_agent(
            max_tool_calls=max_tool_calls, timeout_seconds=60, setup_scenario=False
        )
    except Exception:
        workflow = agent.workflow
    return agent, workflow, llm


def test_farm_jev_is_listed() -> None:
    assert "farm_jev" in AgentBuilder().list_agents()


def test_jev_agent_runs_tools_with_typed_menu_arguments() -> None:
    agent, workflow, llm = _run(
        [
            {TOOL_QUESTION_ID: "WeatherApp__get_forecast"},
            {"arg__days": "3"},
            {TOOL_QUESTION_ID: "TractorApp__load_fertilizer"},
            {"arg__kg": "200"},
            {TOOL_QUESTION_ID: "done"},
        ]
    )
    tools = [s for s in workflow.dag.values() if s.op_type == "TOOL"]
    assert [(s.tool_name, s.tool_args) for s in tools] == [
        ("WeatherApp__get_forecast", {"days": 3}),
        ("TractorApp__load_fertilizer", {"kg": 200.0}),
    ]
    assert agent.stop_reason == "agent_finished"
    # The second state carries the first action and its result, and a farm snapshot.
    assert llm.requests[2][0]["recent_actions"][0]["action"] == "WeatherApp__get_forecast"
    assert "crop" in llm.requests[2][0]["farm_now"]
    totals = metric_totals(agent.messages.runtime_metrics)
    assert totals["llm_call_count"] == 5
    assert totals["token_usage"]["prompt_tokens"] == 500
    assert agent.telemetry["jev_decisions"] == 3
    assert agent.telemetry["avg_action_confidence"] == 0.9


def test_jev_agent_stops_at_max_tool_calls() -> None:
    script = [{TOOL_QUESTION_ID: "WeatherApp__get_current_weather"}] * 5
    agent, workflow, _ = _run(script, max_tool_calls=3)
    assert agent.stop_reason == "max_tool_calls"
    assert agent.tool_call_count == 3


def test_end_ridge_options_start_at_the_chosen_start() -> None:
    agent, workflow, llm = _run(
        [
            {TOOL_QUESTION_ID: "FarmWorldApp__get_ridge_range_state"},
            {"arg__start": "ridge 20"},
            {"arg__end": "ridge 25"},
            {TOOL_QUESTION_ID: "done"},
        ]
    )
    end_options = list(llm.requests[2][1]["arg__end"]["criteria"])
    assert end_options[0] == "ridge 20" and len(end_options) == 44  # 20-63, no pass limit
    step = [s for s in workflow.dag.values() if s.op_type in ("TOOL", "TOOL_ERROR")][0]
    assert step.tool_args == {"start": 20, "end": 25}


def test_wait_is_one_question_in_plain_units() -> None:
    agent, workflow, llm = _run(
        [
            {TOOL_QUESTION_ID: "SystemApp__advance_time"},
            {"arg__duration": "1 day"},
            {TOOL_QUESTION_ID: "done"},
        ]
    )
    assert set(llm.requests[1][1]) == {"arg__duration"}
    step = [s for s in workflow.dag.values() if s.op_type == "TOOL"][0]
    assert step.tool_args == {"days": 1}
    assert step.content["advanced_seconds"] == 86400


def test_done_is_refused_twice_while_ridges_are_unplanted() -> None:
    agent, workflow, llm = _run(
        [{TOOL_QUESTION_ID: "done"}] * 3,
        task="Plant ridges 0-63.",
    )
    assert agent.stop_reason == "agent_finished"
    assert agent.telemetry["done_refusals"] == 2
    assert "not planted" in llm.requests[1][0]["notes"][0]
    assert len(llm.requests) == 3


def test_end_ridge_is_asked_after_start_ridge() -> None:
    agent, workflow, llm = _run(
        [
            {TOOL_QUESTION_ID: "TractorApp__apply_fertilizer"},
            {"arg__start_ridge": "ridge 10", "arg__kg_per_ridge": "3"},
            {"arg__end_ridge": "ridge 19"},
            {TOOL_QUESTION_ID: "done"},
        ]
    )
    first_args, end_only = llm.requests[1][1], llm.requests[2][1]
    assert set(first_args) == {"arg__start_ridge", "arg__kg_per_ridge"}
    assert set(end_only) == {"arg__end_ridge"}
    assert "`start_ridge` = ridge 10" in end_only["arg__end_ridge"]["instructions"]
    # apply_fertilizer covers at most 10 ridges per pass: ridges 10-19.
    assert list(end_only["arg__end_ridge"]["criteria"]) == [f"ridge {r}" for r in range(10, 20)]
    step = [s for s in workflow.dag.values() if s.op_type in ("TOOL", "TOOL_ERROR")][0]
    assert step.tool_args == {"start_ridge": 10, "kg_per_ridge": 3.0, "end_ridge": 19}


def test_low_confidence_hands_the_decision_to_the_llm() -> None:
    fallback = _ScriptedLLM([("WeatherApp__get_forecast", {"days": 2})])
    agent, workflow, llm = _run(
        [
            {TOOL_QUESTION_ID: "WeatherApp__get_forecast", "_confidence": 0.3},
            {"arg__days": "3", "_confidence": 0.3},
            {TOOL_QUESTION_ID: "done"},
        ],
        fallback=fallback,
    )
    step = [s for s in workflow.dag.values() if s.op_type == "TOOL"][0]
    assert step.tool_args == {"days": 2}  # the LLM's call, not Jev's
    assert "farm_now" in fallback.calls[0][1]["content"]
    assert agent.telemetry["llm_fallback_triggers"] == {"low_confidence": 1}
    assert agent.telemetry["llm_decisions"] == 1
    assert agent.telemetry["llm_tokens"]["prompt_tokens"] == 1000
    assert metric_totals(agent.messages.runtime_metrics)["token_usage"]["prompt_tokens"] == 1300


def test_repeat_without_change_goes_to_the_llm() -> None:
    fallback = _ScriptedLLM([None])  # the LLM ends the run
    agent, workflow, _ = _run(
        [{TOOL_QUESTION_ID: "WeatherApp__get_current_weather"}] * 3, fallback=fallback
    )
    assert agent.tool_call_count == 2
    assert agent.telemetry["llm_fallback_triggers"] == {"repeat_without_change": 1}
    assert agent.stop_reason == "agent_finished"


def test_done_refused_twice_goes_to_the_llm() -> None:
    fallback = _ScriptedLLM([("WeatherApp__get_current_weather", {}), None])
    agent, workflow, _ = _run(
        [{TOOL_QUESTION_ID: "done"}] * 4,
        task="Plant ridges 0-63.",
        fallback=fallback,
    )
    steps = [s for s in workflow.dag.values() if s.op_type == "TOOL"]
    assert [s.tool_name for s in steps] == ["WeatherApp__get_current_weather"]
    assert agent.telemetry["done_refusals"] == 2
    assert agent.telemetry["llm_fallback_triggers"] == {"done_refused_twice": 2}
    assert agent.stop_reason == "agent_finished"
