from __future__ import annotations

import os

from openai import OpenAI

from fairy.agents.llm.base_llm import BaseLLM, _coerce_optional_bool

QWEN_API_BASE = os.getenv(
    "QWEN_API_BASE",
    os.getenv("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
)


class QwenClient(BaseLLM):
    llm_class: str = "QwenClient"

    def __init__(self, model, temperature=0.1, api_key=None, **kwargs):
        super().__init__(model, temperature, **kwargs)
        self.provider = "qwen"
        # Main-agent entry points supply explicit defaults. Unconfigured shared
        # clients (including A2A) retain their existing server-default behavior.
        self.enable_thinking = _coerce_optional_bool(
            kwargs.get("enable_thinking"), "enable_thinking"
        )
        self.preserve_thinking = _coerce_optional_bool(
            kwargs.get("preserve_thinking"), "preserve_thinking"
        )
        if self.preserve_thinking and self.enable_thinking is not True:
            raise ValueError("preserve_thinking=true requires enable_thinking=true")
        self.api_key = api_key or os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        self.base_url = kwargs.get("base_url") or QWEN_API_BASE
        self.api_client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.request_timeout,
        )

    def chat_completion(self, messages, tools=None):
        thinking_options = {
            name: value for name, value in (
                ("enable_thinking", self.enable_thinking),
                ("preserve_thinking", self.preserve_thinking),
            ) if value is not None
        }
        return self.api_client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            temperature=self.temperature,
            **self.output_token_options(),
            **self.tool_call_options(tools),
            **({"extra_body": thinking_options} if thinking_options else {}),
        )

    def to_dict(self):
        return {
            "llm_class": self.llm_class,
            "model": self.model,
            "temperature": self.temperature,
            "base_url": self.base_url,
            "parallel_tool_calls": self.parallel_tool_calls,
            "max_output_tokens": self.max_output_tokens,
            **({"enable_thinking": self.enable_thinking}
               if self.enable_thinking is not None else {}),
            **({"preserve_thinking": self.preserve_thinking}
               if self.preserve_thinking is not None else {}),
        }
