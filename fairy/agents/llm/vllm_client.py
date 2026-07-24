from __future__ import annotations

import os
from typing import Any

from openai import OpenAI

from fairy.agents.llm.base_llm import BaseLLM

VLLM_API_BASE = os.getenv("VLLM_API_BASE", "http://localhost:8000/v1")


def _env_bool(name: str) -> bool | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class VLLMClient(BaseLLM):
    llm_class: str = "VLLMClient"

    def __init__(self, model, temperature=0.1, api_key=None, **kwargs):
        super().__init__(model, temperature, **kwargs)
        self.provider = "vllm"
        self.api_key = api_key or os.getenv("VLLM_API_KEY", "EMPTY")
        self.base_url = kwargs.get("base_url") or VLLM_API_BASE
        self.api_client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.request_timeout,
        )
        self.enable_thinking = kwargs.get("enable_thinking")
        if self.enable_thinking is None:
            self.enable_thinking = _env_bool("FAIRY_VLLM_ENABLE_THINKING")
        if self.enable_thinking is None and "qwen" in str(model).lower():
            self.enable_thinking = False

    def chat_completion(self, messages, tools=None):
        request: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "temperature": self.temperature,
            **self.output_token_options(),
            **self.tool_call_options(tools),
        }
        if self.enable_thinking is not None:
            request["extra_body"] = {
                "chat_template_kwargs": {
                    "enable_thinking": bool(self.enable_thinking),
                }
            }
        return self.api_client.chat.completions.create(**request)

    def to_dict(self):
        return {
            "llm_class": self.llm_class,
            "model": self.model,
            "temperature": self.temperature,
            "base_url": self.base_url,
            "enable_thinking": self.enable_thinking,
            "parallel_tool_calls": self.parallel_tool_calls,
            "max_output_tokens": self.max_output_tokens,
        }
