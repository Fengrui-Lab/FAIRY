from types import SimpleNamespace
from unittest.mock import Mock

from fairy.agents.llm.deepseek_client import DeepSeekClient


def test_required_reasoning_roundtrips_only_on_transport_without_mutating_history():
    client = DeepSeekClient("deepseek-flash", api_key="unit-test-placeholder")
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        reasoning_content="provider-required-thinking",
        tool_calls=[SimpleNamespace(id="call-1"), SimpleNamespace(id="call-2")],
    ))])
    create = Mock(return_value=response)
    client.api_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    client.chat_completion([{"role": "user", "content": "check inventory"}])
    # The agent may retain only one call when parallel calls are disabled.
    assistant = {"role": "assistant", "content": None, "tool_calls": [{"id": "call-2"}]}
    history = [{"role": "user", "content": "check inventory"}, assistant,
               {"role": "tool", "tool_call_id": "call-2", "content": "ok"}]
    client.chat_completion(history)
    sent = create.call_args.kwargs["messages"]
    assert sent[1]["reasoning_content"] == "provider-required-thinking"
    assert "reasoning_content" not in assistant
    assert "reasoning_content" not in sent[0] and "reasoning_content" not in sent[2]
    assert client.reasoning_history_policy == "provider_required_transport_only"
