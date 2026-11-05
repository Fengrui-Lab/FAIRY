"""TypeSafe System One client (Jev). Used only by the farm_jev controller.

Jev is a decision model: it answers typed questions about a state and does not
generate chat replies or tool calls, so chat_completion() is not supported.
Credentials are explicit for custom endpoints; hosted defaults use TYPESAFE_API_KEY.
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
        key_env = kwargs.get("api_key_env")
        if kwargs.get("api_key") is not None:
            options["api_key"] = kwargs["api_key"]
        elif key_env:
            key = os.getenv(key_env)
            if not key:
                raise ValueError("Missing service credential")
            options["api_key"] = key
        elif kwargs.get("base_url") is not None:
            # Explicit custom endpoints must never inherit the hosted secret.
            options["api_key"] = "local-no-auth"
        if kwargs.get("max_questions_per_request") is not None:
            raise ValueError("SDK requests are not implicitly split; omit max_questions_per_request")
        self.api_client = TypeSafeClient(model=model, **options)
        self.request_timeout = self.request_timeout if self.request_timeout is not None else DEFAULT_TIMEOUT
        self.sdk_max_retries = retries if retries is not None else RetryPolicy().max_retries
        self.base_url = (options.get("base_url") if "base_url" in options else
                         os.getenv(BASE_URL_ENV, "").strip() or DEFAULT_BASE_URL)

    def system_one(self, state: Any, questions: dict[str, Any]) -> Any:
        response = self.api_client.system_one(state=state, questions=questions)
        if hasattr(response, "raw_http_response"):
            # SDK request_id raises when the optional TypeSafe header is absent
            # (e.g. vLLM). Use public HTTP metadata without inventing an ID.
            raw = response.model_dump()
            headers = response.raw_http_response.headers
            raw["request_id"] = headers.get("x-typesafe-request-id") or headers.get("x-request-id")
        else:
            raw = response
        return normalize_response(raw, questions)

    def close(self):
        self.api_client.close()

    def chat_completion(self, messages, tools=None):
        raise NotImplementedError(
            "Jev does not generate chat replies; use --controller farm_jev."
        )
