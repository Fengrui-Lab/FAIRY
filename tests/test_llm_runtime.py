from __future__ import annotations

import json
import sys

import pytest

from fairy.agents.agent.agent import AgentRunLimitExceeded
from fairy.agents.agent.base_agent import RetryableLLMResponseError
from fairy.agents.llm.base_llm import BaseLLM, DEFAULT_MAX_OUTPUT_TOKENS
from fairy.controllers.agent_builder import build_controller_agent
from fairy.controllers.engine import Engine
from fairy.scenarios.baseline_farm_world.scenario_field_prep import ScenarioFarmWorldFieldPrep


@pytest.fixture(autouse=True)
def _isolated_llm_environment(monkeypatch):
    for name in (
        "FAIRY_LLM_MAX_OUTPUT_TOKENS",
        "FAIRY_PARALLEL_TOOL_CALLS",
        "FAIRY_LLM_REQUEST_TIMEOUT_S",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VLLM_API_KEY", "test-key")
    monkeypatch.setenv("QWEN_API_KEY", "test-key")
    monkeypatch.setenv("FAIRY_AGENT_LLM_CALL_RETRIES", "2")
    monkeypatch.setenv("FAIRY_AGENT_LLM_RETRY_SLEEP_S", "0")
    monkeypatch.setenv("FAIRY_AGENT_RATE_LIMIT_SLEEP_S", "0")


def _sdk_completion(*, content="done", finish_reason="stop", tool_calls=None,
                    reasoning=None, reasoning_content=None, completion_tokens=5):
    from openai.types.chat import ChatCompletion

    return ChatCompletion.model_validate({
        "id": "test-completion",
        "object": "chat.completion",
        "created": 0,
        "model": "fake-model",
        "choices": [{
            "index": 0,
            "finish_reason": finish_reason,
            "message": {
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls,
                "reasoning": reasoning,
                "reasoning_content": reasoning_content,
            },
        }],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": completion_tokens,
            "total_tokens": 11 + completion_tokens,
            "completion_tokens_details": {"reasoning_tokens": 3},
        },
    })


class _ResponseSequenceLLM:
    provider = "vllm"
    model = "fake-model"
    max_output_tokens = 2048
    parallel_tool_calls = True
    enable_thinking = None

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def chat_completion(self, messages, tools=None):
        self.requests.append({
            "messages": json.loads(json.dumps(messages)),
            "tools": json.loads(json.dumps(tools)),
            "max_output_tokens": self.max_output_tokens,
        })
        return self.responses.pop(0)


@pytest.mark.parametrize("reasoning_field", ["reasoning", "reasoning_content", "both"])
def test_agent_excludes_reasoning_from_logs_and_next_request(reasoning_field, tmp_path) -> None:
    from fairy.cli import _append_live_progress, _runtime_log_rows
    from fairy.controllers.run_artifacts import write_jsonl

    diagnostic_reasoning = "diagnostic-only-reasoning"
    first_response = _sdk_completion(
        content=None,
        finish_reason="tool_calls",
        reasoning=diagnostic_reasoning if reasoning_field != "reasoning_content" else None,
        reasoning_content=diagnostic_reasoning if reasoning_field != "reasoning" else None,
        tool_calls=[{
            "id": "inventory-call",
            "type": "function",
            "function": {"name": "FarmWorldApp__get_inventory", "arguments": "{}"},
        }],
    )
    llm = _ResponseSequenceLLM([first_response, _sdk_completion()])
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    agent = build_controller_agent("farm_baseline_react", llm=llm, toolsets=scenario.apps)
    progress_path = tmp_path / "progress.jsonl"
    agent.runtime_event_sink = lambda event: _append_live_progress(progress_path, event)

    Engine(agent, scenario).run_scenario_agent(
        max_tool_calls=5, timeout_seconds=30, setup_scenario=False,
    )

    ends = [e for e in agent.runtime_events if e["event_type"] == "llm_call_end"]
    assert ends[0]["finish_reason"] == "tool_calls"
    assert ends[0]["usage"] == first_response.usage.model_dump()
    assert all(
        not {"reasoning", "reasoning_content", "response"}.intersection(event)
        for event in ends
    )
    runtime_path = tmp_path / "runtime_log.jsonl"
    write_jsonl(runtime_path, _runtime_log_rows(agent.runtime_events))
    for path in (runtime_path, progress_path):
        text = path.read_text()
        rows = [json.loads(line) for line in text.splitlines()]
        assert diagnostic_reasoning not in text
        assert all(
            not {"reasoning", "reasoning_content", "response"}.intersection(row)
            for row in rows if row["record_type"] == "llm_call_end"
        )
    assert ends[0]["usage"]["completion_tokens_details"]["reasoning_tokens"] == 3
    assert ends[0]["rationale"] is None
    assert diagnostic_reasoning not in json.dumps(llm.requests[1])
    assert all(
        "reasoning" not in message and "reasoning_content" not in message
        for message in llm.requests[1]["messages"]
    )
    assert len(llm.requests) == 2
    assert agent.tool_call_count == 1
    assert agent.stop_reason == "agent_finished"


def test_a2a_trace_file_excludes_reasoning_without_mutating_sdk_history(tmp_path):
    from fairy.controllers.app_agent import AppAgent, collect_a2a_traces
    from fairy.controllers.run_artifacts import write_json

    diagnostic_reasoning = "a2a-diagnostic-only-reasoning"
    response = _sdk_completion(
        content="task complete",
        reasoning=diagnostic_reasoning,
        reasoning_content=diagnostic_reasoning,
    )
    llm = _ResponseSequenceLLM([response])
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    expert = build_controller_agent("farm_baseline_react", llm=llm, toolsets=scenario.apps)
    wrapper = AppAgent(
        wrapped_app=scenario.apps[0], app_agent=expert, app_agent_name="test_expert",
    )
    wrapper.expert_agent("Finish without calling tools.")
    sdk_message = expert.messages.messages[-1]
    before_export = sdk_message.model_dump()

    traces = collect_a2a_traces([wrapper])
    path = tmp_path / "a2a_traces.json"
    write_json(path, traces)

    saved = json.loads(path.read_text())
    assert diagnostic_reasoning not in path.read_text()
    exported_message = saved[0]["messages"][-1]
    assert exported_message == {
        key: value for key, value in before_export.items()
        if key not in {"reasoning", "reasoning_content"}
    }
    assert exported_message["content"] == "task complete"
    assert sdk_message.model_dump() == before_export
    assert sdk_message.reasoning == diagnostic_reasoning
    assert sdk_message.reasoning_content == diagnostic_reasoning


@pytest.mark.parametrize(
    ("content", "finish_reason", "with_tool", "expected_reason"),
    [
        (None, "length", False, "output_truncated"),
        ("partial answer", "length", False, "output_truncated"),
        ("partial answer", "length", True, "output_truncated"),
        (None, "stop", False, "empty_response"),
        ("  \n", "stop", False, "empty_response"),
    ],
)
def test_agent_retries_rejected_responses_with_feedback_only_for_empty(
    monkeypatch, content, finish_reason, with_tool, expected_reason,
) -> None:
    monkeypatch.setenv("FAIRY_AGENT_LLM_CALL_RETRIES", "2")
    monkeypatch.setenv("FAIRY_AGENT_LLM_RETRY_SLEEP_S", "0")
    rejected = _sdk_completion(
        content=content,
        finish_reason=finish_reason,
        reasoning="reasoning-is-diagnostic-only",
        completion_tokens=2048,
        tool_calls=[{
            "id": "must-not-execute",
            "type": "function",
            "function": {"name": "FarmWorldApp__get_inventory", "arguments": "{}"},
        }] if with_tool else None,
    )
    llm = _ResponseSequenceLLM([rejected, _sdk_completion()])
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    agent = build_controller_agent("farm_baseline_react", llm=llm, toolsets=scenario.apps)

    Engine(agent, scenario).run_scenario_agent(
        max_tool_calls=5, timeout_seconds=30, setup_scenario=False,
    )

    assert len(llm.requests) == 2
    feedback = "上次未返回可用正文或工具调用，请继续任务并按工具协议输出。"
    if expected_reason == "empty_response":
        assert llm.requests[1] == {
            **llm.requests[0],
            "messages": llm.requests[0]["messages"] + [{"role": "user", "content": feedback}],
        }
    else:
        assert llm.requests[0] == llm.requests[1]
    assert llm.requests[0]["max_output_tokens"] == 2048
    assert llm.enable_thinking is None
    assert agent.tool_call_count == 0
    assert agent.llm_turn_count == 1
    assert agent.telemetry["llm_calls"] == 1
    assert agent.telemetry["error_count"] == 0
    assert agent.stop_reason == "agent_finished"
    assert len(agent.messages.messages) == (4 if expected_reason == "empty_response" else 3)
    metrics = agent.messages.runtime_metrics
    assert [m["accepted"] for m in metrics] == [False, True]
    assert sum(m["tokens"]["completion_tokens"] for m in metrics) == 2053
    ends = [e for e in agent.runtime_events if e["event_type"] == "llm_call_end"]
    assert [e["status"] for e in ends] == ["rejected", "ok"]
    assert "response" not in ends[0]
    assert "reasoning" not in ends[0] and "reasoning_content" not in ends[0]
    assert "reasoning-is-diagnostic-only" not in json.dumps(agent.runtime_events)
    assert ends[0]["usage"] == rejected.usage.model_dump()
    assert ends[0]["finish_reason"] == finish_reason
    assert ends[0]["rejection_reason"] == expected_reason
    retries = [e for e in agent.runtime_events if e["event_type"] == "llm_call_retry"]
    assert len(retries) == 1
    assert retries[0]["rejection_reason"] == expected_reason
    assert retries[0]["retry_feedback"] == (feedback if expected_reason == "empty_response" else None)
    assert not any(e["event_type"] == "tool_call_start" for e in agent.runtime_events)


def test_agent_rejected_response_retry_exhaustion_is_not_completed(monkeypatch) -> None:
    monkeypatch.setenv("FAIRY_AGENT_LLM_CALL_RETRIES", "2")
    monkeypatch.setenv("FAIRY_AGENT_LLM_RETRY_SLEEP_S", "0")
    llm = _ResponseSequenceLLM([
        _sdk_completion(content=None, finish_reason="length", completion_tokens=2048)
        for _ in range(3)
    ])
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    agent = build_controller_agent("farm_baseline_react", llm=llm, toolsets=scenario.apps)

    with pytest.raises(RetryableLLMResponseError, match="output_truncated"):
        Engine(agent, scenario).run_scenario_agent(
            max_tool_calls=5, timeout_seconds=30, setup_scenario=False,
        )

    assert len(llm.requests) == 3
    assert all(request == llm.requests[0] for request in llm.requests)
    assert agent.stop_reason == "output_truncated"
    assert agent.llm_turn_count == 0
    assert len(agent.messages.messages) == 2
    assert sum(m["tokens"]["completion_tokens"] for m in agent.messages.runtime_metrics) == 6144
    assert len([e for e in agent.runtime_events if e["event_type"] == "llm_call_retry"]) == 2
    assert any(e["event_type"] == "agent_run_error" for e in agent.runtime_events)
    assert not any(e["event_type"] == "agent_run_end" for e in agent.runtime_events)


def test_cli_rejected_response_exhaustion_writes_failed_report(monkeypatch, tmp_path) -> None:
    from fairy.cli import main

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FAIRY_AGENT_LLM_CALL_RETRIES", "2")
    monkeypatch.setenv("FAIRY_AGENT_LLM_RETRY_SLEEP_S", "0")
    llm = _ResponseSequenceLLM([
        _sdk_completion(content=None, finish_reason="length", completion_tokens=2048)
        for _ in range(3)
    ])
    monkeypatch.setattr(BaseLLM, "llm_builder", lambda cfg: llm)
    scenario_id = "scenario_farm_world_field_prep"
    output = tmp_path / "failed-run"

    monkeypatch.setattr(sys, "argv", [
        "fairy", "-s", scenario_id, "--agent", "--controller", "farm_baseline_react",
        "--provider", "vllm", "--model", "fake-model",
        "--max-output-tokens", "2048", "--max-tool-calls", "5", "--timeout-seconds", "30",
        "--output-dir", str(output),
    ])
    with pytest.raises(RuntimeError, match="Agent run failed: RetryableLLMResponseError"):
        main()

    report = json.loads((output / f"{scenario_id}.run_report.json").read_text())
    assert report["status"] == "failed"
    assert report["stopped_reason"] == "output_truncated"
    assert report["error"]["type"] == "RetryableLLMResponseError"
    assert report["metrics"]["llm_call_count"] == 3
    assert report["metrics"]["token_usage"]["completion_tokens"] == 6144
    assert report["limits"]["max_output_tokens"] == 2048
    rows = [
        json.loads(line)
        for line in (output / f"{scenario_id}.runtime_log.jsonl").read_text().splitlines()
    ]
    ends = [row for row in rows if row["record_type"] == "llm_call_end"]
    assert len(ends) == 3
    assert all(row["status"] == "rejected" for row in ends)
    assert all(row["finish_reason"] == "length" for row in ends)
    assert all("response" not in row for row in ends)
    assert all(row["usage"]["completion_tokens"] == 2048 for row in ends)


@pytest.mark.parametrize("finish_reason", ["length", "stop"])
def test_agent_timeout_stops_response_retries(monkeypatch, finish_reason) -> None:
    monkeypatch.setenv("FAIRY_AGENT_LLM_CALL_RETRIES", "2")
    monkeypatch.setenv("FAIRY_AGENT_LLM_RETRY_SLEEP_S", "0")

    class _DeadlineLLM(_ResponseSequenceLLM):
        def chat_completion(self, messages, tools=None):
            response = super().chat_completion(messages, tools)
            agent.run_started_at_wall -= 31
            return response

    llm = _DeadlineLLM([_sdk_completion(content=None, finish_reason=finish_reason)])
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    agent = build_controller_agent("farm_baseline_react", llm=llm, toolsets=scenario.apps)

    with pytest.raises(AgentRunLimitExceeded, match="timeout_seconds"):
        Engine(agent, scenario).run_scenario_agent(
            max_tool_calls=5, timeout_seconds=30, setup_scenario=False,
        )

    assert len(llm.requests) == 1
    assert len(agent.messages.messages) == 2
    assert agent.stop_reason == "timeout"
    assert not any(e["event_type"] == "llm_call_retry" for e in agent.runtime_events)
    assert agent.runtime_events[-1]["event_type"] == "agent_run_end"
    assert agent.runtime_events[-1]["status"] == "stopped"



def _capture_requests(monkeypatch, client):
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return _sdk_completion()

    monkeypatch.setattr(client.api_client.chat.completions, "create", create)
    return requests


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (None, None),
        ("false", False),
        ("true", True),
        (" OFF ", False),
        (" YES ", True),
        (False, False),
        (True, True),
    ],
)
def test_vllm_thinking_override_is_strict(
    monkeypatch, configured, expected,
):
    client = BaseLLM.llm_builder({
        "provider": "vllm", "model": "Qwen3.6-35B-A3B-FP8",
        "enable_thinking": configured,
    })
    requests = _capture_requests(monkeypatch, client)

    client.chat_completion([{"role": "user", "content": "finish"}], tools=[])

    assert client.enable_thinking is expected
    assert requests[0]["max_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS
    if expected is None:
        assert "extra_body" not in requests[0]
    else:
        assert requests[0]["extra_body"]["chat_template_kwargs"]["enable_thinking"] is expected


@pytest.mark.parametrize("value", ["typo", "2", 1, [], {}])
def test_vllm_rejects_invalid_explicit_thinking(value):
    with pytest.raises(ValueError, match="enable_thinking"):
        BaseLLM.llm_builder({
            "provider": "vllm", "model": "fake-model", "enable_thinking": value,
        })


@pytest.mark.parametrize("value", ["true", "false", "typo"])
def test_vllm_ignores_removed_thinking_environment(monkeypatch, value):
    monkeypatch.setenv("FAIRY_VLLM_ENABLE_THINKING", value)
    client = BaseLLM.llm_builder({"provider": "vllm", "model": "fake-model"})
    requests = _capture_requests(monkeypatch, client)

    client.chat_completion([{"role": "user", "content": "finish"}], tools=[])

    assert client.enable_thinking is None
    assert "extra_body" not in requests[0]
    assert requests[0]["max_tokens"] == 2048


def test_qwen_leaves_thinking_to_server(monkeypatch):
    client = BaseLLM.llm_builder({
        "provider": "qwen", "model": "fake-model", "enable_thinking": None,
    })
    requests = _capture_requests(monkeypatch, client)

    client.chat_completion([{"role": "user", "content": "finish"}], tools=[])

    assert "extra_body" not in requests[0]
    assert "enable_thinking" not in requests[0]
    assert requests[0]["max_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS


@pytest.mark.parametrize("max_output_tokens", [None, 2048, 4096])
def test_cli_persists_actual_llm_configuration_and_response_policy(
    monkeypatch, tmp_path, max_output_tokens,
):
    from fairy.cli import main

    original_builder = BaseLLM.llm_builder
    clients = []

    def build(cfg):
        client = original_builder(cfg)
        _capture_requests(monkeypatch, client)
        clients.append(client)
        return client

    monkeypatch.setattr(BaseLLM, "llm_builder", build)
    monkeypatch.chdir(tmp_path)
    scenario_id = "scenario_farm_world_field_prep"
    output = tmp_path / "success-run"
    command = [
        "fairy", "-s", scenario_id, "--agent", "--controller", "farm_baseline_react",
        "--provider", "vllm", "--model", "fake-model", "--parallel-tool-calls", "false",
        "--max-tool-calls", "5", "--timeout-seconds", "30", "--output-dir", str(output),
    ]
    if max_output_tokens is not None:
        command.extend(["--max-output-tokens", str(max_output_tokens)])
    monkeypatch.setattr(sys, "argv", command)

    main()

    report = json.loads((output / f"{scenario_id}.run_report.json").read_text())
    rows = [json.loads(line) for line in (
        output / f"{scenario_id}.runtime_log.jsonl"
    ).read_text().splitlines()]
    llm_start = next(row for row in rows if row["record_type"] == "llm_call_start")
    run_start = next(row for row in rows if row["record_type"] == "agent_run_start")
    config = report["llm_config"]
    expected_limit = max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS
    assert DEFAULT_MAX_OUTPUT_TOKENS == 2048
    assert config["max_output_tokens"] == expected_limit
    assert config["max_output_tokens"] == clients[0].max_output_tokens
    assert config["parallel_tool_calls"] is False
    assert config["enable_thinking_override"] is None
    assert config["reasoning_history_policy"] == "exclude"
    assert config["sdk_max_retries"] == clients[0].api_client.max_retries
    assert llm_start["llm_config"] == config
    assert run_start["llm_config"] == config
    assert "test-key" not in json.dumps(config)
    assert report["limits"]["max_output_tokens"] == expected_limit
    policy = report["response_policy"]
    assert policy["max_llm_call_retries"] == 2
    assert policy["max_llm_call_attempts"] == 3
    assert policy["retry_rejection_reasons"] == ["output_truncated", "empty_response"]
    assert policy["retry_changes_request"] is True
    assert run_start["response_policy"] == policy


def test_runner_default_and_saved_override_preserve_token_limit(tmp_path):
    from scripts.iclr_validation_runner import CellSpec, _build_cell_command, _parse_args

    command = _build_cell_command(
        CellSpec(family="farm_baseline_react", scenario="scenario_x", repeat=1),
        model="fake-model", provider="vllm", output_dir=tmp_path,
    )
    assert command[command.index("--max-output-tokens") + 1] == str(DEFAULT_MAX_OUTPUT_TOKENS)
    config_path = tmp_path / "historical-config.json"
    config_path.write_text(json.dumps({
        "phase": "paper_matrix", "output_root": str(tmp_path),
        "families": "farm_baseline_react", "scenarios": "scenario_x",
        "max_output_tokens": 2048,
    }))
    saved = _parse_args(["--config", str(config_path)])
    assert saved.max_output_tokens == 2048
    override = _parse_args(["--config", str(config_path), "--max-output-tokens", "4096"])
    assert override.max_output_tokens == 4096


def test_stop_response_at_token_limit_is_not_inferred_to_be_truncated():
    llm = _ResponseSequenceLLM([_sdk_completion(completion_tokens=2048)])
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    agent = build_controller_agent("farm_baseline_react", llm=llm, toolsets=scenario.apps)

    Engine(agent, scenario).run_scenario_agent(
        max_tool_calls=5, timeout_seconds=30, setup_scenario=False,
    )

    assert agent.stop_reason == "agent_finished"
    assert len(llm.requests) == 1
    assert not any(event["event_type"] == "llm_call_retry" for event in agent.runtime_events)


@pytest.mark.parametrize("value", [True, False, 2048.5, 2048.0, None])
def test_output_token_limit_rejects_noninteger_values(value):
    with pytest.raises(ValueError, match="positive integer"):
        BaseLLM("fake-model", temperature=0.1, max_output_tokens=value)


@pytest.mark.parametrize("value", [4096, "4096"])
def test_output_token_limit_accepts_integer_or_integer_string(value):
    client = BaseLLM("fake-model", temperature=0.1, max_output_tokens=value)
    assert client.max_output_tokens == 4096


def test_empty_choices_are_accounted_for_and_retried_without_history():
    empty_response = _sdk_completion(completion_tokens=17).model_copy(update={"choices": []})
    llm = _ResponseSequenceLLM([empty_response, empty_response, _sdk_completion()])
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    agent = build_controller_agent("farm_baseline_react", llm=llm, toolsets=scenario.apps)

    Engine(agent, scenario).run_scenario_agent(
        max_tool_calls=5, timeout_seconds=30, setup_scenario=False,
    )

    assert len(llm.requests) == 3
    feedback = {"role": "user", "content": "上次未返回可用正文或工具调用，请继续任务并按工具协议输出。"}
    assert llm.requests[1]["messages"] == llm.requests[0]["messages"] + [feedback]
    assert llm.requests[2] == llm.requests[1]
    assert len(agent.messages.messages) == 4  # system, user, feedback, accepted final
    assert agent.llm_turn_count == 1
    assert agent.tool_call_count == 0
    assert agent.stop_reason == "agent_finished"
    metrics = agent.messages.runtime_metrics
    assert [metric["accepted"] for metric in metrics] == [False, False, True]
    assert sum(metric["tokens"]["completion_tokens"] for metric in metrics) == 39
    ends = [event for event in agent.runtime_events if event["event_type"] == "llm_call_end"]
    assert [event["status"] for event in ends] == ["rejected", "rejected", "ok"]
    for event in ends[:2]:
        assert event["rejection_reason"] == "empty_response"
        assert "response" not in event
        assert "reasoning" not in event and "reasoning_content" not in event
        assert event["finish_reason"] is None
        assert event["usage"] == empty_response.usage.model_dump()
        assert event["assistant_content"] is None
        assert event["tool_calls"] == []
    retries = [event for event in agent.runtime_events if event["event_type"] == "llm_call_retry"]
    assert len(retries) == 2
    assert all(event["rejection_reason"] == "empty_response" for event in retries)


def test_negative_agent_retry_budget_fails_configuration(monkeypatch):
    monkeypatch.setenv("FAIRY_AGENT_LLM_CALL_RETRIES", "-1")
    with pytest.raises(ValueError, match="FAIRY_AGENT_LLM_CALL_RETRIES must be nonnegative"):
        build_controller_agent(
            "farm_baseline_react", llm=_ResponseSequenceLLM([]), toolsets=[],
        )


@pytest.mark.parametrize("content", [None, "  \n"])
def test_empty_response_prints_full_reasoning_without_history_or_runtime_leaks(
    capsys, content, tmp_path,
):
    from fairy.cli import _append_live_progress, _runtime_log_rows
    from fairy.controllers.run_artifacts import write_jsonl

    reasoning = "先检查农场、天气和土壤；\n" * 500
    reasoning_content = "接着判断播种条件，完整保留推理。\n" * 500
    llm = _ResponseSequenceLLM([
        _sdk_completion(
            content=content, reasoning=reasoning, reasoning_content=reasoning_content,
        ),
        _sdk_completion(),
    ])
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    agent = build_controller_agent("farm_baseline_react", llm=llm, toolsets=scenario.apps)
    progress_path = tmp_path / "progress.jsonl"
    agent.runtime_event_sink = lambda event: _append_live_progress(progress_path, event)

    Engine(agent, scenario).run_scenario_agent(
        max_tool_calls=5, timeout_seconds=30, setup_scenario=False,
    )

    marker = "empty_response reasoning fields: "
    diagnostics = [
        line.split(marker, 1)[1]
        for line in capsys.readouterr().out.splitlines() if marker in line
    ]
    assert len(diagnostics) == 1
    assert json.loads(diagnostics[0]) == {
        "reasoning": reasoning, "reasoning_content": reasoning_content,
    }
    assert "先检查农场" in diagnostics[0]
    assert "接着判断播种条件" in diagnostics[0]
    assert len(llm.requests) == 2
    feedback = {"role": "user", "content": "上次未返回可用正文或工具调用，请继续任务并按工具协议输出。"}
    assert llm.requests[1]["messages"] == llm.requests[0]["messages"] + [feedback]
    assert len(agent.messages.messages) == 4  # system, user, feedback, accepted final
    assert [metric["accepted"] for metric in agent.messages.runtime_metrics] == [False, True]
    assert agent.stop_reason == "agent_finished"
    runtime_path = tmp_path / "runtime_log.jsonl"
    write_jsonl(runtime_path, _runtime_log_rows(agent.runtime_events))
    for path in (runtime_path, progress_path):
        text = path.read_text()
        assert "先检查农场" not in text
        assert "接着判断播种条件" not in text
    serialized_state = json.dumps({
        "history": agent._jsonable(agent.messages.messages),
        "requests": llm.requests,
        "events": agent.runtime_events,
        "metrics": agent.messages.runtime_metrics,
    }, ensure_ascii=False)
    assert "先检查农场" not in serialized_state
    assert "接着判断播种条件" not in serialized_state


def test_empty_response_prints_null_when_reasoning_fields_are_absent(capsys):
    from fairy.agents.agent.base_agent import BaseAgent

    response = _sdk_completion(content=None)
    del response.choices[0].message.reasoning
    del response.choices[0].message.reasoning_content
    agent = BaseAgent("test", _ResponseSequenceLLM([response]))

    with pytest.raises(RetryableLLMResponseError, match="empty_response"):
        agent.chat_completion([{"role": "user", "content": "Finish the task."}])

    marker = "empty_response reasoning fields: "
    diagnostics = [
        line.split(marker, 1)[1]
        for line in capsys.readouterr().out.splitlines() if marker in line
    ]
    assert len(diagnostics) == 1
    assert diagnostics[0] == '{"reasoning": null, "reasoning_content": null}'
    assert agent.messages.messages == []
    assert agent.messages.runtime_metrics[0]["accepted"] is False


@pytest.mark.parametrize(
    ("content", "finish_reason", "with_tool"),
    [("task complete", "stop", False), (None, "tool_calls", True), (None, "length", False)],
)
def test_reasoning_diagnostic_is_not_printed_for_other_response_states(
    capsys, content, finish_reason, with_tool,
):
    from fairy.agents.agent.base_agent import BaseAgent

    response = _sdk_completion(
        content=content, finish_reason=finish_reason,
        reasoning="do-not-print-reasoning", reasoning_content="do-not-print-reasoning-content",
        tool_calls=[{
            "id": "inventory-call",
            "type": "function",
            "function": {"name": "FarmWorldApp__get_inventory", "arguments": "{}"},
        }] if with_tool else None,
    )
    agent = BaseAgent("test", _ResponseSequenceLLM([response]))
    messages = [{"role": "user", "content": "Finish the task."}]

    if finish_reason == "length":
        with pytest.raises(RetryableLLMResponseError, match="output_truncated"):
            agent.chat_completion(messages)
        assert agent.messages.messages == []
    else:
        assert agent.chat_completion(messages) is response.choices[0].message

    output = capsys.readouterr().out
    assert "empty_response reasoning fields:" not in output
    assert "do-not-print-reasoning" not in output
    assert "do-not-print-reasoning" not in json.dumps(agent.runtime_events)


def test_empty_retry_feedback_persists_without_rejected_reasoning():
    feedback = "上次未返回可用正文或工具调用，请继续任务并按工具协议输出。"
    llm = _ResponseSequenceLLM([
        _sdk_completion(content=None, reasoning="rejected-reasoning"),
        _sdk_completion(content=None, finish_reason="tool_calls", tool_calls=[{
            "id": "inventory-after-feedback", "type": "function",
            "function": {"name": "FarmWorldApp__get_inventory", "arguments": "{}"},
        }]),
        _sdk_completion(),
    ])
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    agent = build_controller_agent("farm_baseline_react", llm=llm, toolsets=scenario.apps)
    Engine(agent, scenario).run_scenario_agent(
        max_tool_calls=5, timeout_seconds=30, setup_scenario=False,
    )
    assert len(llm.requests) == 3
    assert feedback not in json.dumps(llm.requests[0], ensure_ascii=False)
    for request in llm.requests[1:]:
        assert sum(message.get("content") == feedback for message in request["messages"]) == 1
        assert "rejected-reasoning" not in json.dumps(request)
    assert agent.tool_call_count == 1
    assert agent.llm_turn_count == 2
    assert len(agent.messages.runtime_metrics) == 4  # three replies and one tool
    retries = [event for event in agent.runtime_events if event["event_type"] == "llm_call_retry"]
    assert [event["retry_feedback"] for event in retries] == [feedback]
    starts = [event for event in agent.runtime_events if event["event_type"] == "llm_call_start"]
    assert starts[1]["messages"] == llm.requests[1]["messages"]
    assert feedback in json.dumps(starts[2]["messages"], ensure_ascii=False)


@pytest.mark.parametrize("max_retries", [0, 2])
def test_empty_retry_feedback_respects_budget_and_exhaustion(monkeypatch, max_retries):
    monkeypatch.setenv("FAIRY_AGENT_LLM_CALL_RETRIES", str(max_retries))
    llm = _ResponseSequenceLLM([
        _sdk_completion(content=None, reasoning="must-not-enter-history")
        for _ in range(max_retries + 1)
    ])
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    agent = build_controller_agent("farm_baseline_react", llm=llm, toolsets=scenario.apps)
    with pytest.raises(RetryableLLMResponseError, match="empty_response"):
        Engine(agent, scenario).run_scenario_agent(
            max_tool_calls=5, timeout_seconds=30, setup_scenario=False,
        )
    feedback = "上次未返回可用正文或工具调用，请继续任务并按工具协议输出。"
    assert len(llm.requests) == max_retries + 1
    assert agent.stop_reason == "empty_response"
    assert agent.llm_turn_count == agent.tool_call_count == 0
    assert len(agent.messages.messages) == (3 if max_retries else 2)
    assert sum(message.get("content") == feedback for message in agent.messages.messages) == bool(max_retries)
    assert "must-not-enter-history" not in json.dumps(agent.messages.messages)
    if max_retries:
        assert llm.requests[1:] == [llm.requests[1]] * max_retries
    assert len(agent.messages.runtime_metrics) == max_retries + 1


def test_transport_retry_does_not_add_empty_response_feedback():
    class TransportFailureLLM(_ResponseSequenceLLM):
        def chat_completion(self, messages, tools=None):
            response = super().chat_completion(messages, tools)
            if isinstance(response, Exception):
                raise response
            return response

    llm = TransportFailureLLM([ConnectionError("temporary connection failure"), _sdk_completion()])
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    agent = build_controller_agent("farm_baseline_react", llm=llm, toolsets=scenario.apps)
    Engine(agent, scenario).run_scenario_agent(
        max_tool_calls=5, timeout_seconds=30, setup_scenario=False,
    )
    assert llm.requests[0] == llm.requests[1]
    assert len(agent.messages.messages) == 3
    retries = [event for event in agent.runtime_events if event["event_type"] == "llm_call_retry"]
    assert len(retries) == 1
    assert retries[0]["retry_feedback"] is None


@pytest.mark.parametrize("second_failure", ["length", "transport"])
def test_empty_feedback_is_not_duplicated_by_other_retry_failures(second_failure):
    class MixedFailureLLM(_ResponseSequenceLLM):
        def chat_completion(self, messages, tools=None):
            response = super().chat_completion(messages, tools)
            if isinstance(response, Exception):
                raise response
            return response

    failure = (_sdk_completion(content="partial", finish_reason="length")
               if second_failure == "length" else ConnectionError("temporary failure"))
    llm = MixedFailureLLM([_sdk_completion(content=None), failure, _sdk_completion()])
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    agent = build_controller_agent("farm_baseline_react", llm=llm, toolsets=scenario.apps)
    Engine(agent, scenario).run_scenario_agent(
        max_tool_calls=5, timeout_seconds=30, setup_scenario=False,
    )
    feedback = {"role": "user", "content": "上次未返回可用正文或工具调用，请继续任务并按工具协议输出。"}
    assert len(llm.requests) == 3
    assert llm.requests[1]["messages"] == llm.requests[0]["messages"] + [feedback]
    assert llm.requests[2] == llm.requests[1]
    retries = [event for event in agent.runtime_events if event["event_type"] == "llm_call_retry"]
    assert [event["retry_feedback"] for event in retries] == [feedback["content"]] * 2
    assert len(agent.messages.messages) == 4


def test_retry_sleep_deadline_does_not_append_unsent_feedback(monkeypatch):
    from fairy.agents.agent import agent as agent_module

    clock = {"now": 100.0}
    monkeypatch.setattr(agent_module.time, "perf_counter", lambda: clock["now"])
    monkeypatch.setattr(agent_module.time, "sleep", lambda seconds: clock.__setitem__("now", clock["now"] + seconds))
    monkeypatch.setenv("FAIRY_AGENT_LLM_RETRY_SLEEP_S", "10")
    llm = _ResponseSequenceLLM([_sdk_completion(content=None)])
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    agent = build_controller_agent("farm_baseline_react", llm=llm, toolsets=scenario.apps)
    with pytest.raises(AgentRunLimitExceeded, match="timeout_seconds"):
        Engine(agent, scenario).run_scenario_agent(
            max_tool_calls=5, timeout_seconds=1, setup_scenario=False,
        )
    assert len(llm.requests) == 1
    assert len(agent.messages.messages) == 2
    assert agent.stop_reason == "timeout"
    assert clock["now"] == 101.0
