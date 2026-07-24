from __future__ import annotations

import os

from openai import OpenAI

from fairy.agents.llm.base_llm import BaseLLM


class OpenAICompatibleClient(BaseLLM):
    llm_class: str = "OpenAICompatibleClient"

    def __init__(self, model, temperature=0.1, api_key=None, **kwargs):
        super().__init__(model, temperature, **kwargs)
        self.provider = "llama-api"
        self.api_key = api_key or os.getenv("LLAMA_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.base_url = kwargs.get("base_url") or os.getenv("LLAMA_API_BASE")
        self.api_client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.request_timeout,
        )

    def chat_completion(self, messages, tools=None):
        return self.api_client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            temperature=self.temperature,
            **self.output_token_options(),
            **self.tool_call_options(tools),
        )

    def to_dict(self):
        return {
            "llm_class": self.llm_class,
            "model": self.model,
            "temperature": self.temperature,
            "base_url": self.base_url,
            "parallel_tool_calls": self.parallel_tool_calls,
            "max_output_tokens": self.max_output_tokens,
        }
