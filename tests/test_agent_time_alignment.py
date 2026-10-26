"""Agent time labels must represent the sampled epochs on every execution path."""
from datetime import datetime, timedelta, timezone
import os
import time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from fairy.agents.agent.agent import Agent, AgentRunLimitExceeded, RecoverableToolCallError
from fairy.agents.agent.base_agent import BaseAgent
from fairy.scenarios.workflow_validation import _normalize_workflow_times
from fairy.time_manager import TimeManager


START = datetime(2026, 5, 5, 23, 59, 50, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()


class CountingClock:
    def __init__(self, now):
        self.now = now
        self.reads = 0

    def time(self):
        self.reads += 1
        return self.now


def make_agent(zone):
    # call_function and the pre-LLM run limit exercise real Agent paths offline.
    agent = Agent("time-test", SimpleNamespace(provider="openai"))
    agent.set_time_manager(CountingClock(START))
    agent.simulation_timezone = ZoneInfo(zone) if zone is not None else None
    return agent


def tool_call(arguments="{}"):
    return SimpleNamespace(
        id="time-call", type="function",
        function=SimpleNamespace(name="Test__act", arguments=arguments),
    )


def test_formatting_a_sampled_epoch_does_not_read_the_clock():
    agent = BaseAgent("format", SimpleNamespace(provider="openai"))
    clock = CountingClock(START + 100)
    agent.set_time_manager(clock)
    agent.simulation_timezone = ZoneInfo("Asia/Shanghai")
    assert agent.format_sim_time(START) == "2026-05-05 23:59:50+08:00"
    assert clock.reads == 0
    assert agent.env_time_str() == "2026-05-06 00:01:30+08:00"
    assert clock.reads == 1


@pytest.mark.parametrize("zone,expected", [
    ("Asia/Shanghai", "2026-05-06 00:00:10+08:00"),
    ("UTC", "2026-05-05 16:00:10+00:00"),
    ("America/New_York", "2026-05-05 12:00:10-04:00"),
    (None, "2026-05-06 00:00:10"),
])
def test_successful_tool_message_and_workflow_format_the_same_post_call_epoch(zone, expected, capsys):
    agent = make_agent(zone)

    def act():
        agent.time_manager.now += 20
        return {"status": "ok"}

    agent.tools_map = {"Test__act": act}
    assert agent.call_function(tool_call()) == {"status": "ok"}
    step = next(iter(agent.workflow.dag.values()))
    assert step.time_before == START
    assert step.time_after == START + 20
    assert step.time == agent.messages.messages[-1]["time"] == expected
    assert f"[Env Time: {agent.format_sim_time(START)}]" in capsys.readouterr().out
    if zone is not None:
        assert datetime.fromisoformat(step.time).timestamp() == step.time_after


@pytest.mark.parametrize("arguments,error_stage", [("{}", "tool_call"), ("{", "tool_args_parse")])
@pytest.mark.parametrize("zone,offset", [
    ("Asia/Shanghai", "+08:00"), ("UTC", "+00:00"), ("America/New_York", "-04:00"),
])
def test_error_message_and_workflow_use_the_configured_timezone(arguments, error_stage, zone, offset):
    agent = make_agent(zone)

    def fail():
        agent.time_manager.now += 20
        raise ValueError("test failure")

    agent.tools_map = {"Test__act": fail}
    with pytest.raises(RecoverableToolCallError):
        agent.call_function(tool_call(arguments))
    step = next(iter(agent.workflow.dag.values()))
    expected_epoch = START + 20 if error_stage == "tool_call" else START
    assert step.op_type == "TOOL_ERROR"
    assert step.error_stage == error_stage
    assert step.time_before == START
    assert step.time_after == expected_epoch
    assert step.time == agent.messages.messages[-1]["time"]
    assert step.time.endswith(offset)
    assert datetime.fromisoformat(step.time).timestamp() == expected_epoch


def test_user_message_uses_the_same_formatter_without_calling_an_llm():
    agent = make_agent("Asia/Shanghai")
    with pytest.raises(AgentRunLimitExceeded):
        agent.run("task", max_tool_calls=0)
    step = next(iter(agent.workflow.dag.values()))
    assert step.op_type == "USER"
    user_message = next(item for item in agent.messages.messages if item.get("role") == "user")
    assert step.time == user_message["time"] == "2026-05-05 23:59:50+08:00"
    assert agent.llm_turn_count == 0


@pytest.fixture(params=["UTC", "Asia/Tokyo"])
def host_timezone(request):
    original = os.environ.get("TZ")
    os.environ["TZ"] = request.param
    time.tzset()
    try:
        yield request.param
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        time.tzset()


def test_legacy_naive_workflow_times_are_cst_on_every_host(host_timezone):
    expected = datetime(2026, 5, 5, 7, tzinfo=timezone(timedelta(hours=8))).timestamp()
    workflow = {
        "legacy": {"time": "2026-05-05 07:00:00", "time_before": expected, "time_after": expected},
        "aware": {"time": "2026-05-05 07:00:00+08:00"},
    }
    _normalize_workflow_times(workflow)
    assert workflow["legacy"]["time"] == workflow["aware"]["time"] == expected
    assert workflow["legacy"]["time_before"] == workflow["legacy"]["time_after"] == expected


def test_aware_offsets_are_respected_and_bad_or_numeric_values_keep_their_contract(host_timezone):
    workflow = {
        "utc": {"time": "2026-05-04T23:00:00Z"},
        "tokyo": {"time": "2026-05-05T08:00:00+09:00"},
        "bad": {"time": "not a datetime"},
        "numeric": {"time": 123.5},
        "empty": {"time": None},
    }
    _normalize_workflow_times(workflow)
    expected = datetime(2026, 5, 4, 23, tzinfo=timezone.utc).timestamp()
    assert workflow["utc"]["time"] == workflow["tokyo"]["time"] == expected
    assert workflow["bad"]["time"] is None
    assert workflow["numeric"]["time"] == 123.5
    assert workflow["empty"]["time"] is None


def test_default_clock_still_counts_wall_time_between_tools(monkeypatch):
    wall = [100.0]
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: wall[0])
    clock = TimeManager()
    clock.reset(START)
    clock.add_offset(60)
    wall[0] += 20
    assert clock.time() == START + 80
