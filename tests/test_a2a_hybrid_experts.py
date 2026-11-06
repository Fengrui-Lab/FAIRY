"""Offline checks for A2A with the new hybrid inside each expert (no API calls)."""

from __future__ import annotations

import json

from fairy.agents.jev.jev_agent import PLAN_ARG, TOOL_QUESTION_ID

from tests.test_a2a_jev import DONE, FORECAST, _setup

UNSURE = {TOOL_QUESTION_ID: "WeatherApp__get_current_weather", "_confidence": 0.1}
GET_WEATHER = {TOOL_QUESTION_ID: "WeatherApp__get_current_weather"}
PLANNED = ("WeatherApp__get_forecast", {"days": 2, PLAN_ARG: "read the current weather next"})


def _farm_steps(main):
    return [s for s in main.workflow.dag.values() if s.op_type == "TOOL"]


def _job(apps, text="Get the weather."):
    return json.loads(apps["WeatherApp"].expert_agent(text))


def test_local_llm_takes_over_and_the_job_stays_in_the_expert():
    main, apps, jev = _setup([UNSURE, GET_WEATHER, DONE], replies=[PLANNED])
    report = _job(apps)
    assert report["status"] == "finished"
    assert "expert_top_options" not in report
    assert [s.tool_name for s in _farm_steps(main)] == [
        "WeatherApp__get_forecast",
        "WeatherApp__get_current_weather",
    ]
    assert _farm_steps(main)[0].tool_args == {"days": 2}  # next_steps never reaches the tool


def test_plan_reaches_jev_until_the_job_ends():
    main, apps, jev = _setup([UNSURE, DONE, GET_WEATHER, DONE], replies=[PLANNED])
    _job(apps)
    state, questions = jev.requests[1]
    assert state["plan_from_advisor"]["next_steps"] == "read the current weather next"
    assert "plan_from_advisor" in questions[TOOL_QUESTION_ID]["instructions"]
    assert "advance time" not in questions[TOOL_QUESTION_ID]["instructions"]
    _job(apps, "Get the weather again.")
    assert "plan_from_advisor" not in jev.requests[2][0]  # a new job starts with no plan


def test_stuck_also_goes_to_the_local_llm():
    from tests.test_a2a_jev import FORECAST_AGAIN

    main, apps, jev = _setup(
        [*FORECAST, FORECAST_AGAIN, FORECAST_AGAIN, DONE],
        replies=[("WeatherApp__get_current_weather", {PLAN_ARG: "stop after this"})],
    )
    report = _job(apps, "Get the 3-day forecast.")
    assert report["status"] == "finished"
    assert _farm_steps(main)[-1].tool_name == "WeatherApp__get_current_weather"


def test_local_llm_done_ends_the_job_with_its_note():
    main, apps, jev = _setup([UNSURE], replies=[None])
    report = _job(apps, "Water ridge 5.")
    assert report["status"] == "no_action"
    assert report["expert_note"] == "done"  # _ScriptedLLM's reply text


def test_budget_counts_the_run_not_the_job():
    main, apps, jev = _setup([*FORECAST, DONE], max_tool_calls=8, replies=[])
    _job(apps, "Get the 3-day forecast.")
    budget = jev.requests[-1][0]["action_budget"]
    assert budget["actions_used"] == 1 and budget["actions_left"] == 299


def test_local_llm_sees_only_this_job_and_this_app():
    main, apps, jev = _setup([*FORECAST, DONE, UNSURE, DONE], replies=[PLANNED])
    _job(apps, "Get the 3-day forecast.")
    _job(apps, "Get the weather.")
    local = apps["WeatherApp"].app_agent.local_llm
    system, first, *_, last = local.calls[0]
    assert system["content"] == "rules"
    assert "Task:\nGet the weather." in first["content"]
    assert "No actions since your last decision." in last["content"]
    assert all(name.startswith("WeatherApp__") for name in local.tools[0])


def test_local_llm_tokens_are_tagged_for_cost():
    main, apps, jev = _setup([UNSURE, DONE], replies=[PLANNED])
    _job(apps)
    sources = {m.get("source") for m in apps["WeatherApp"].all_runtime_metrics}
    assert {"jev", "llm_fallback"} <= sources
