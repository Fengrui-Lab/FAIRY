from __future__ import annotations

import os

from openai import OpenAI

from fairy.agents.llm.base_llm import BaseLLM

VLLM_API_BASE = os.getenv("VLLM_API_BASE", "http://localhost:8000/v1")


class VLLMClient(BaseLLM):
    llm_class: str = "VLLMClient"

    def __init__(self, model, temperature=0.1, api_key=None, **kwargs):
        super().__init__(model, temperature, **kwargs)
        self.provider = "vllm"
        self.api_key = api_key or os.getenv("VLLM_API_KEY", "EMPTY")
        self.base_url = kwargs.get("base_url") or VLLM_API_BASE
        self.api_client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def chat_completion(self, messages, tools=None):
        return self.api_client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            temperature=self.temperature,
        )

    def to_dict(self):
        return {
            "llm_class": self.llm_class,
            "model": self.model,
            "temperature": self.temperature,
            "base_url": self.base_url,
        }
