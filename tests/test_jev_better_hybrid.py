"""Offline checks for the better-hybrid options of farm_jev (no API calls)."""

from __future__ import annotations

import json

import pytest

from fairy.agents.jev.jev_agent import PLAN_ARG, TOOL_QUESTION_ID
from fairy.controllers.agent_builder import build_controller_agent
from fairy.controllers.engine import Engine
from fairy.scenarios.baseline_farm_world.scenario_field_prep import ScenarioFarmWorldFieldPrep
from tests.test_jev_agent import TASK, _ScriptedJev, _ScriptedLLM

UNSURE = {TOOL_QUESTION_ID: "WeatherApp__get_current_weather", "_confidence": 0.1}


def _run(script, replies, **options):
    scenario = ScenarioFarmWorldFieldPrep(scenario_input=TASK)
    scenario.setup()
    jev = _ScriptedJev(script)
    fallback = _ScriptedLLM(replies)
    agent = build_controller_agent(
        "farm_jev", llm=jev, toolsets=scenario.apps, fallback_llm=fallback, **options
    )
    Engine(agent=agent, scenario=scenario).run_scenario_agent(
        max_tool_calls=20, timeout_seconds=60, setup_scenario=False
    )
    return agent, jev, fallback


def _state_of(message: dict) -> dict:
    return json.loads(message["content"].split("Current state:\n", 1)[1])


def test_defaults_are_off() -> None:
    agent, jev, fallback = _run(
        [UNSURE, {TOOL_QUESTION_ID: "done"}], [("WeatherApp__get_forecast", {"days": 2})]
    )
    assert agent.fallback_memory == "full" and not agent.plan_note and not agent.budget_note
    assert "steps_so_far" in _state_of(fallback.calls[0][-1])
    state, questions = jev.requests[-1]
    assert "plan_from_advisor" not in state and "action_budget" not in state
    assert "plan_from_advisor" not in questions[TOOL_QUESTION_ID]["instructions"]


def test_lean_memory_is_append_only_and_drops_the_step_list() -> None:
    _, _, fallback = _run(
        [UNSURE, UNSURE, UNSURE, {TOOL_QUESTION_ID: "done"}],
        [("WeatherApp__get_forecast", {"days": n}) for n in (1, 2, 3)],
        fallback_memory="lean",
    )
    first, second, third = fallback.calls
    assert second[: len(first)] == first and third[: len(second)] == second
    assert "steps_so_far" not in _state_of(first[-1])
    assert "inventory" in _state_of(first[-1])["farm_now"]
    assert "inventory" not in _state_of(second[-1])["farm_now"]  # unchanged since the first


def test_plan_note_reaches_jev_and_not_the_tool() -> None:
    note = "advance 3 days, then read the soil sensors"
    agent, jev, fallback = _run(
        [UNSURE, {TOOL_QUESTION_ID: "done"}],
        [("WeatherApp__get_forecast", {"days": 2, PLAN_ARG: note})],
        plan_note=True,
    )
    state, questions = jev.requests[-1]
    assert state["plan_from_advisor"]["next_steps"] == note
    assert "plan_from_advisor" in questions[TOOL_QUESTION_ID]["instructions"]
    assert agent.telemetry["plans_written"] == 1
    calls = [s for s in agent.workflow.dag.values() if s.op_type == "TOOL"]
    assert calls[0].tool_args == {"days": 2}


def test_plan_note_is_replayed_as_sent() -> None:
    note = "then wait"
    _, _, fallback = _run(
        [UNSURE, UNSURE, {TOOL_QUESTION_ID: "done"}],
        [("WeatherApp__get_forecast", {"days": 2, PLAN_ARG: note}), None],
        plan_note=True,
    )
    replayed = next(m for m in fallback.calls[1] if m.get("tool_calls"))
    assert json.loads(replayed["tool_calls"][0]["function"]["arguments"])[PLAN_ARG] == note


def test_budget_note_counts_actions() -> None:
    _, jev, _ = _run([{TOOL_QUESTION_ID: "done"}], [], budget_note=True)
    budget = jev.requests[0][0]["action_budget"]
    assert budget["actions_used"] == 0 and budget["actions_left"] == 20
    assert "warning" in budget  # 20 actions cannot cover a whole-field harvest


def test_options_are_only_for_farm_jev() -> None:
    with pytest.raises(ValueError):
        build_controller_agent("farm_baseline_react", llm=object(), toolsets=[], plan_note=True)
