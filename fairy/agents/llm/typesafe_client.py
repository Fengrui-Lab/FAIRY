"""TypeSafe System One client (Jev). Used only by the farm_jev controller.

Jev is a decision model: it answers typed questions about a state and does not
generate chat replies or tool calls, so chat_completion() is not supported.
The API key is read by the SDK from TYPESAFE_API_KEY and is never stored here.
"""

from __future__ import annotations

import math
import os
from typing import Any

from .base_llm import BaseLLM
from .decision_response import normalize_response


class TypeSafeJevClient(BaseLLM):
    llm_class = "TypeSafeJevClient"

    def __init__(self, model, temperature, **kwargs):
        super().__init__(model, temperature, **kwargs)
        from typesafe_sdk import TypeSafeClient, RetryPolicy
        from typesafe_sdk.constants import BASE_URL_ENV, DEFAULT_BASE_URL, DEFAULT_TIMEOUT

        self.provider = "typesafe"
        options = {}
        if self.request_timeout is not None:
            if not math.isfinite(self.request_timeout) or self.request_timeout <= 0:
                raise ValueError("TypeSafe request timeout must be positive and finite")
            options["timeout"] = self.request_timeout
        retries = kwargs.get("max_retries")
        if retries is not None:
            if type(retries) is not int or retries < 0:
                raise ValueError("TypeSafe max_retries must be a nonnegative integer")
            options["retry"] = RetryPolicy(max_retries=retries)
        if kwargs.get("base_url") is not None:
            # The SDK appends /v1/systemone; base_url is the service origin.
            options["base_url"] = kwargs["base_url"]
        self.api_client = TypeSafeClient(model=model, **options)
        self.request_timeout = self.request_timeout if self.request_timeout is not None else DEFAULT_TIMEOUT
        self.sdk_max_retries = retries if retries is not None else RetryPolicy().max_retries
        self.base_url = (options.get("base_url") if "base_url" in options else
                         os.getenv(BASE_URL_ENV, "").strip() or DEFAULT_BASE_URL)

    def system_one(self, state: Any, questions: dict[str, Any]) -> Any:
        return normalize_response(self.api_client.system_one(state=state, questions=questions), questions)

    def close(self):
        self.api_client.close()

    def chat_completion(self, messages, tools=None):
        raise NotImplementedError(
            "Jev does not generate chat replies; use --controller farm_jev."
        )
