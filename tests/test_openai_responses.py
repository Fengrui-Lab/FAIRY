"""Offline checks for the OpenAI Responses API route (no API calls)."""

from __future__ import annotations

from types import SimpleNamespace

from fairy.agents.llm.openai_llm import OpenAILLM


def _llm(monkeypatch, **kwargs):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    return OpenAILLM("gpt-6-luna", **kwargs)


def test_route_depends_on_reasoning_effort(monkeypatch):
    assert _llm(monkeypatch).api_mode == "reasoning"
    assert _llm(monkeypatch, reasoning_effort="none").api_mode == "reasoning"
    assert _llm(monkeypatch, reasoning_effort="medium").api_mode == "responses"


def test_chat_history_becomes_responses_input():
    messages = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "App__tool", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "result"},
    ]
    assert OpenAILLM._responses_input(messages) == [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "task"},
        {"type": "function_call", "call_id": "c1", "name": "App__tool", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c1", "output": "result"},
    ]


def test_reply_looks_like_chat_completion():
    response = SimpleNamespace(
        id="r1", created_at=1, model="gpt-6-luna", status="completed", incomplete_details=None,
        output=[
            SimpleNamespace(type="reasoning"),
            SimpleNamespace(type="function_call", call_id="c2", name="App__tool", arguments='{"x": 1}'),
        ],
        usage=SimpleNamespace(
            input_tokens=100, output_tokens=20, total_tokens=120,
            input_tokens_details=SimpleNamespace(cached_tokens=80),
            output_tokens_details=SimpleNamespace(reasoning_tokens=12),
        ),
    )
    completion = OpenAILLM._as_chat_completion(response)
    choice = completion.choices[0]
    assert choice.finish_reason == "tool_calls"
    assert choice.message.tool_calls[0].id == "c2"
    assert choice.message.tool_calls[0].function.arguments == '{"x": 1}'
    assert completion.usage.prompt_tokens == 100
    assert completion.usage.prompt_tokens_details.cached_tokens == 80

    response.status = "incomplete"
    response.incomplete_details = SimpleNamespace(reason="max_output_tokens")
    assert OpenAILLM._as_chat_completion(response).choices[0].finish_reason == "length"
