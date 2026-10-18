"""TypeSafe System One client (Jev). Used only by the farm_jev controller.

Jev is a decision model: it answers typed questions about a state and does not
generate chat replies or tool calls, so chat_completion() is not supported.
The API key is read by the SDK from TYPESAFE_API_KEY and is never stored here.
"""

from __future__ import annotations

from typing import Any

from .base_llm import BaseLLM


class TypeSafeJevClient(BaseLLM):
    llm_class = "TypeSafeJevClient"

    def __init__(self, model, temperature, **kwargs):
        super().__init__(model, temperature, **kwargs)
        from typesafe_sdk import TypeSafeClient

        self.provider = "typesafe"
        self.base_url = None
        self.api_client = TypeSafeClient(model=model)

    def system_one(self, state: Any, questions: dict[str, Any]) -> Any:
        return self.api_client.system_one(state=state, questions=questions)

    def chat_completion(self, messages, tools=None):
        raise NotImplementedError(
            "Jev does not generate chat replies; use --controller farm_jev."
        )
