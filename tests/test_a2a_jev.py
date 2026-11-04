"""Offline checks for A2A with Jev experts (no API calls)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from fairy.agents.agent.agent import Agent
from fairy.agents.jev.a2a_expert import JevAppAgentBuilder
from fairy.agents.jev.jev_agent import TOOL_QUESTION_ID
from fairy.controllers.agent_config import AppAgentConfigBuilder
from fairy.controllers.app_agent import (
    SharedTraceAppAgent,
    apply_a2a_to_apps,
    attach_main_agent,
    collect_a2a_traces,
)
from fairy.controllers.engine import Engine
from fairy.scenarios.baseline_farm_world.scenario_field_prep import ScenarioFarmWorldFieldPrep

from tests.test_jev_agent import _ScriptedJev


def _setup(script, max_tool_calls=8):
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    jev = _ScriptedJev(script)
    apps = list(scenario.apps)
    result = apply_a2a_to_apps(
        apps,
        llm_factory=lambda: jev,
        app_agent_builder=JevAppAgentBuilder(apps, scenario_task="load 321 kg"),
        app_agent_config_builder=AppAgentConfigBuilder(),
        app_prop=1.0,
        seed=0,
        max_tool_calls=max_tool_calls,
        wrapper_class=SharedTraceAppAgent,
    )
    scenario.apps = result.apps
    main = Agent(name="main", llm=SimpleNamespace(provider="openai"), toolsets=result.apps)
    attach_main_agent(result.apps, main)
    engine = Engine(agent=main, scenario=scenario)
    engine._register_scenario_apps()
    main.set_time_manager(engine.time_manager)
    return main, {a.name: a for a in result.apps}, jev


DONE = {TOOL_QUESTION_ID: "done"}
# First pick of a tool: tool, then its arguments in a second request. Later picks: one
# request, with the argument question riding along (fan-out).
FORECAST = [{TOOL_QUESTION_ID: "WeatherApp__get_forecast"}, {"arg__days": "3"}]
FORECAST_AGAIN = {TOOL_QUESTION_ID: "WeatherApp__get_forecast", "arg__WeatherApp__get_forecast__days": "3"}


def test_expert_actions_land_in_the_main_run():
    main, apps, jev = _setup([*FORECAST, DONE])
    report = json.loads(apps["WeatherApp"].expert_agent("Get the 3-day forecast."))
    assert report["status"] == "finished"
    assert [a["action"] for a in report["actions"]] == ["get_forecast"]
    steps = [s for s in main.workflow.dag.values() if s.op_type == "TOOL"]
    assert [s.tool_name for s in steps] == ["WeatherApp__get_forecast"]
    assert steps[0].tool_args == {"days": 3}
    assert any(e["event_type"] == "jev_action" for e in main.runtime_events)
    # Only this app's tools are offered.
    criteria = jev.requests[0][1][TOOL_QUESTION_ID]["criteria"]
    assert set(criteria) == {"WeatherApp__get_current_weather", "WeatherApp__get_forecast", "done"}
    assert jev.requests[0][0]["task"] == "Get the 3-day forecast."


def test_numbers_in_job_and_scenario_task_are_menu_options():
    main, apps, jev = _setup([DONE])
    apps["TractorApp"].expert_agent("Load 77 kg of fertilizer.")
    menu = apps["TractorApp"].app_agent.tool_menus["TractorApp__load_fertilizer"]
    assert {"77", "321"} <= set(menu.args[0].options)


def test_low_confidence_hands_the_job_back_without_acting():
    main, apps, jev = _setup([{TOOL_QUESTION_ID: "WeatherApp__get_forecast", "_confidence": 0.1}, {"arg__days": "3"}])
    report = json.loads(apps["WeatherApp"].expert_agent("Do something about the weather."))
    assert report["status"] == "unsure"
    assert report["actions"] == []
    assert "expert_top_options" in report
    assert not [s for s in main.workflow.dag.values() if s.op_type == "TOOL"]


def test_repeat_without_change_is_stuck():
    main, apps, jev = _setup([*FORECAST, FORECAST_AGAIN, FORECAST_AGAIN])
    report = json.loads(apps["WeatherApp"].expert_agent("Get the 3-day forecast."))
    assert report["status"] == "stuck"
    assert len(report["actions"]) == 2


def test_action_limit_and_main_budget():
    main, apps, jev = _setup([*FORECAST, {TOOL_QUESTION_ID: "WeatherApp__get_current_weather"}], max_tool_calls=2)
    report = json.loads(apps["WeatherApp"].expert_agent("Get the 3-day forecast."))
    assert report["status"] == "action_limit"
    assert len(report["actions"]) == 2
    assert main.tool_call_count == 1  # + the delegation's own count in call_function = 2


def test_trace_and_tool_description():
    main, apps, jev = _setup([*FORECAST, DONE])
    apps["WeatherApp"].expert_agent("Get the 3-day forecast.")
    trace = next(t for t in collect_a2a_traces(list(apps.values())) if t["wrapper_app_name"] == "WeatherApp")
    assert trace["job_count"] == 1 and trace["tool_call_count"] == 1
    assert trace["runtime_metrics"]
    assert "get_forecast" in main.tools_map["WeatherApp__expert_agent"].function_description


def test_snapshot_and_outcome_see_through_wrappers():
    main, apps, jev = _setup([DONE])
    from fairy.agents.jev.snapshot import build_snapshot

    snap, _ = build_snapshot(list(apps.values()), main.workflow, main.time_manager.time())
    assert snap["farm_now"]["crop"]
