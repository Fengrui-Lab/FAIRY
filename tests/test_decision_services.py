from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from types import SimpleNamespace

import httpx
import pytest

from fairy.agents.llm.base_llm import BaseLLM
from fairy.agents.llm.decision_response import DecisionProtocolError, normalize_response
from fairy.agents.llm.system_one_client import DecisionServiceError, SystemOneCompatibleClient, api_root
from fairy.cli import _fallback_config
from fairy.controllers.agent_builder import build_controller_agent
from fairy.controllers.run_artifacts import metric_totals
from fairy.scenarios.baseline_farm_world.scenario_field_prep import ScenarioFarmWorldFieldPrep
from scripts.check_model_service import main as check_service


def questions(n=1):
    return {f"q{i}": {"type": "choice", "instructions": "Pick a.", "criteria": {"a": "first", "b": None}}
            for i in range(n)}


def payload(qs, *, usage=True, confidence=0.3):
    result = {"model": "served-revision", "id": "request-1", "answers": {
        q: {"choice": "a", "probabilities": {"a": 0.8, "b": 0.2}, "confidence": confidence} for q in qs
    }}
    if usage:
        result["usage"] = {"input_tokens": 10, "output_tokens": 0, "cached_tokens": 2}
    return result


def client(handler, **kwargs):
    return SystemOneCompatibleClient("deployed-alias", base_url="http://localhost:9001/v1/",
                                     transport=httpx.MockTransport(handler), **kwargs)


@pytest.mark.parametrize("sdk", [False, True])
def test_normalizes_both_protocol_shapes_without_changing_confidence(sdk):
    raw = payload(questions())
    if sdk:
        raw = SimpleNamespace(choices={q: SimpleNamespace(**a) for q, a in raw["answers"].items()},
                              usage=SimpleNamespace(**raw["usage"]), model="sdk-revision", request_id="sdk-id")
    result = normalize_response(raw, questions())
    assert result.choices["q0"].confidence == 0.3  # NOT max(probability)
    assert result.choices["q0"].probabilities == {"a": 0.8, "b": 0.2}
    assert result.usage.input_tokens == 10
    assert result.model == ("sdk-revision" if sdk else "served-revision")


@pytest.mark.parametrize("mutation", [
    lambda r: r["answers"].clear(),
    lambda r: r["answers"]["q0"].update(choice="missing"),
    lambda r: r["answers"]["q0"]["probabilities"].pop("b"),
    lambda r: r["answers"]["q0"]["probabilities"].update(c=0),
    lambda r: r["answers"]["q0"]["probabilities"].update(a=float("nan")),
    lambda r: r["answers"]["q0"]["probabilities"].update(a=float("inf")),
    lambda r: r["answers"]["q0"]["probabilities"].update(a=-0.1),
    lambda r: r["answers"]["q0"]["probabilities"].update(a=0.4),
    lambda r: r["answers"]["q0"].update(confidence=1.1),
    lambda r: r["answers"]["q0"].update(choice="b"),
    lambda r: r["usage"].update(input_tokens=-1),
    lambda r: r["usage"].update(input_tokens=True),
])
def test_rejects_malformed_answers(mutation):
    raw = payload(questions())
    mutation(raw)
    with pytest.raises(DecisionProtocolError):
        normalize_response(raw, questions())


def test_split_requests_preserve_state_ids_auth_and_usage(monkeypatch):
    monkeypatch.setenv("LOCAL_DECISION_TEST_KEY", "secret-for-test")
    requests = []
    def handler(request):
        assert str(request.url) == "http://localhost:9001/v1/systemone"
        assert request.headers["authorization"] == "Bearer secret-for-test"
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json=payload(body["questions"]))
    c = client(handler, api_key_env="LOCAL_DECISION_TEST_KEY", max_questions_per_request=2)
    qs = questions(5)
    qs["singleton"] = {"type": "choice", "criteria": {"only": None}}
    result = c.system_one({"中文": [1, 2], "keep": "x" * 10000}, qs)
    assert [len(r["questions"]) for r in requests] == [2, 2, 1]
    assert len({r["state"] for r in requests}) == 1
    assert json.loads(requests[0]["state"])["keep"] == "x" * 10000
    assert all(r["model"] == "deployed-alias" for r in requests)
    assert list(result.choices) == list(qs)
    assert result.usage.tokens() == {"prompt_tokens": 30, "completion_tokens": 0, "total_tokens": 30, "cached_tokens": 6}
    assert len(result.batches) == 3
    assert result.choices["singleton"].deterministic
    assert all(b.wall_time_seconds >= 0 for b in result.batches)
    assert "secret-for-test" not in json.dumps(c.to_dict())
    c.close()


def test_singleton_never_contacts_service():
    def forbidden(request):
        pytest.fail("singleton must not call model")
    c = client(forbidden)
    result = c.system_one("state", {"one": {"type": "choice", "criteria": {"42": None}}})
    assert result.choices["one"].choice == "42"
    assert result.batches == []
    assert result.usage.input_tokens == 0  # Known: no request was made.
    c.close()


@pytest.mark.parametrize("endpoint", ["", "http://host", "http://host/v1/systemone", "http://host/v1?key=secret", "http://u:secret@host/v1"])
def test_endpoint_requires_unambiguous_safe_api_root(endpoint):
    with pytest.raises(ValueError) as caught:
        api_root(endpoint)
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("status", [400, 401, 413, 422, 429, 500, 302])
def test_http_errors_are_explicit_not_retried_or_leaked(status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "secret-key-in-upstream-body: context limit"})
    c = client(handler)
    with pytest.raises(DecisionServiceError) as caught:
        c.system_one("state", questions())
    assert caught.value.status_code == status
    assert "secret-key" not in str(caught.value)
    assert len(calls) == 1
    c.close()


def test_timeout_is_sanitized():
    def handler(request):
        raise httpx.ReadTimeout("secret-key", request=request)
    c = client(handler)
    with pytest.raises(DecisionServiceError, match="timed out") as caught:
        c.system_one("state", questions())
    assert "secret-key" not in str(caught.value)
    c.close()


def make_agent(c, source="provider"):
    scenario = ScenarioFarmWorldFieldPrep(scenario_input="Read weather")
    scenario.setup()
    return build_controller_agent("farm_jev", llm=c, toolsets=scenario.apps, decision_confidence_source=source)


@pytest.mark.parametrize("source,expected", [("provider", 0.3), ("max_probability", 0.8)])
def test_routing_mode_and_real_batch_accounting(source, expected):
    c = client(lambda r: httpx.Response(200, json=payload(json.loads(r.content)["questions"])), max_questions_per_request=1)
    agent = make_agent(c, source)
    result = agent._ask("tools", {"task": "Read weather"}, questions(3))
    assert result["q0"]["confidence"] == expected
    assert result["q0"]["provider_confidence"] == 0.3
    totals = metric_totals(agent.messages.runtime_metrics)
    assert totals["llm_call_count"] == 3
    assert totals["token_usage"]["prompt_tokens"] == 30
    end = agent.runtime_events[-1]
    assert end["provider"] == "system-one-compatible"
    assert end["model_version"] == "served-revision"
    assert end["http_request_count"] == 3
    assert totals["llm_wall_time_seconds"] == pytest.approx(sum(b["wall_time_seconds"] for b in end["batches"]), abs=1e-6)
    c.close()


def test_missing_usage_is_unknown_in_run_summary_and_telemetry():
    c = client(lambda r: httpx.Response(200, json=payload(json.loads(r.content)["questions"], usage=False)))
    agent = make_agent(c)
    agent._ask("tools", {}, questions())
    agent.after_agent_run()
    totals = metric_totals(agent.messages.runtime_metrics)
    assert totals["token_usage"]["prompt_tokens"] is None
    assert totals["token_usage"]["total_tokens"] is None
    assert totals["token_usage"]["source"] == "llm_runtime_metrics_incomplete"
    assert agent.telemetry["jev_input_tokens"] is None
    assert not agent.telemetry["decision_usage_complete"]
    c.close()


def test_partial_batch_failure_keeps_known_usage_and_counts_failed_attempt():
    attempts = []
    def handler(request):
        attempts.append(request)
        if len(attempts) == 2:
            return httpx.Response(413, json={"error": "context too long; secret-token"})
        return httpx.Response(200, json=payload(json.loads(request.content)["questions"]))
    c = client(handler, max_questions_per_request=1)
    agent = make_agent(c)
    with pytest.raises(DecisionServiceError):
        agent._ask("tools", {}, questions(3))
    totals = metric_totals(agent.messages.runtime_metrics)
    assert totals["llm_call_count"] == 2
    assert totals["token_usage"]["prompt_tokens"] is None
    assert totals["token_usage"]["known_tokens"]["prompt_tokens"] == 10
    assert agent.runtime_events[-1]["status_code"] == 413
    assert "secret-token" not in json.dumps(agent.runtime_events)
    c.close()


def test_service_model_must_not_change_mid_batch():
    attempts = []
    def handler(request):
        attempts.append(request)
        raw = payload(json.loads(request.content)["questions"])
        raw["model"] = f"revision-{len(attempts)}"
        return httpx.Response(200, json=raw)
    c = client(handler, max_questions_per_request=1)
    with pytest.raises(DecisionServiceError, match="identity changed"):
        c.system_one({}, questions(2))
    c.close()


def test_missing_confidence_requires_explicit_probability_mode():
    c = client(lambda r: httpx.Response(200, json=payload(questions(), confidence=None)))
    with pytest.raises(DecisionProtocolError, match="omitted confidence"):
        make_agent(c)._ask("tools", {}, questions())
    assert make_agent(c, "max_probability")._ask("tools", {}, questions())["q0"]["confidence"] == 0.8
    c.close()


def fallback_args(**overrides):
    values = dict(fallback_provider="vllm", fallback_model="local-qwen", temperature=0.1,
                  max_output_tokens=2048, fallback_endpoint=None, fallback_api_key_env=None,
                  fallback_max_output_tokens=None, fallback_enable_thinking=None,
                  endpoint="http://decision-only/v1")
    values.update(overrides)
    return argparse.Namespace(**values)


def test_fallback_defaults_do_not_inherit_decision_endpoint():
    config = _fallback_config(fallback_args())
    assert "base_url" not in config and "enable_thinking" not in config and "api_key" not in config
    assert config["max_output_tokens"] == 2048
    assert config["parallel_tool_calls"] is False


@pytest.mark.parametrize("provider", ["vllm", "openai-compatible"])
def test_fallback_configuration_reaches_chat_request(provider, monkeypatch):
    monkeypatch.setenv("TEST_QWEN_KEY", "fallback-secret")
    config = _fallback_config(fallback_args(fallback_provider=provider, fallback_endpoint="http://qwen-host/v1/",
                                          fallback_api_key_env="TEST_QWEN_KEY", fallback_enable_thinking=False,
                                          fallback_max_output_tokens=777))
    captured = {}
    c = BaseLLM.llm_builder(config)
    actual_client = c.api_client
    c.api_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: captured.update(kw))))
    c.chat_completion([{"role": "user", "content": "hi"}], tools=[])
    assert c.base_url == "http://qwen-host/v1"
    assert c.api_key == "fallback-secret"
    assert captured["max_tokens"] == 777
    assert captured["parallel_tool_calls"] is False
    assert captured["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert "fallback-secret" not in json.dumps(c.to_dict())
    actual_client.close()


def test_missing_explicit_key_fails_instead_of_using_unrelated_credentials(monkeypatch):
    monkeypatch.delenv("MISSING_TEST_KEY", raising=False)
    with pytest.raises(ValueError, match="unset or empty"):
        _fallback_config(fallback_args(fallback_api_key_env="MISSING_TEST_KEY"))


@pytest.fixture
def local_server():
    received = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, dict(self.headers), body))
            if self.path == "/v1/systemone":
                response = {"model": "local-test", "answers": {q: {
                    "choice": next(iter(v["criteria"])), "confidence": 1.0,
                    "probabilities": {k: float(i == 0) for i, k in enumerate(v["criteria"])},
                } for q, v in body["questions"].items()}}
            else:
                response = {"id": "chat-1", "object": "chat.completion", "created": 1, "model": "local-qwen",
                            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                                "role": "assistant", "tool_calls": [{"id": "call-1", "type": "function", "function": {
                                    "name": "report_number", "arguments": '{"value":7}'}}]}}]}
            data = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", received
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_contract_checker_against_local_decision_and_chat_services(local_server, monkeypatch, capsys):
    endpoint, received = local_server
    monkeypatch.setenv("CONTRACT_KEY", "contract-secret")
    assert check_service(["--kind", "decision", "--endpoint", endpoint, "--model", "mica-alias",
                          "--api-key-env", "CONTRACT_KEY", "--question-count", "17", "--option-count", "64",
                          "--max-questions-per-request", "16"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["http_request_count"] == 2
    assert result["usage"]["prompt_tokens"] is None
    assert [len(r[2]["questions"]) for r in received] == [16, 1]
    assert check_service(["--kind", "chat", "--endpoint", endpoint, "--model", "qwen-alias",
                          "--api-key-env", "CONTRACT_KEY", "--enable-thinking", "false"]) == 0
    output = capsys.readouterr().out
    assert "contract-secret" not in output
    assert json.loads(output)["tools_executed"] == 0
    path, headers, body = received[-1]
    assert path == "/v1/chat/completions"
    assert headers["Authorization"] == "Bearer contract-secret"
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["parallel_tool_calls"] is False


def test_new_provider_does_not_import_typesafe(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "typesafe_sdk", None)
    c = BaseLLM.llm_builder({"provider": "system-one-compatible", "model": "local", "base_url": "http://localhost:1/v1"})
    assert callable(c.system_one)
    c.close()


def test_cli_routes_independent_services_and_records_safe_config(local_server, monkeypatch, tmp_path):
    import sys
    from fairy.cli import main
    endpoint, received = local_server
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLI_DECISION_KEY", "decision-secret")
    monkeypatch.setenv("CLI_QWEN_KEY", "qwen-secret")
    monkeypatch.setattr(sys, "argv", [
        "fairy-run", "--agent", "--scenario", "scenario_farm_world_field_prep",
        "--controller", "farm_jev", "--provider", "system-one-compatible",
        "--endpoint", endpoint, "--model", "decision-alias",
        "--decision-api-key-env", "CLI_DECISION_KEY", "--decision-max-questions", "2",
        "--decision-confidence-source", "max_probability",
        "--fallback-provider", "vllm", "--fallback-model", "qwen-alias",
        "--fallback-endpoint", endpoint, "--fallback-api-key-env", "CLI_QWEN_KEY",
        "--fallback-max-output-tokens", "321", "--fallback-enable-thinking", "false",
        "--max-tool-calls", "1", "--timeout-seconds", "10", "--output-dir", str(tmp_path / "run"),
    ])
    main()
    report = json.loads(next((tmp_path / "run").glob("*.run_report.json")).read_text())
    config = report["controller_telemetry"]["fallback_config"]
    assert config["base_url"] == endpoint
    assert config["max_output_tokens"] == 321
    assert config["enable_thinking"] is False
    assert report["controller_telemetry"]["decision_confidence_source"] == "max_probability"
    assert received and received[0][1]["Authorization"] == "Bearer decision-secret"
    logs = "".join(p.read_text() for p in (tmp_path / "run").glob("*.json*"))
    assert "decision-secret" not in logs and "qwen-secret" not in logs
