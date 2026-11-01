# llm_clients/openai_client.py
import os
from openai import OpenAI

from fairy.agents.llm.base_llm import BaseLLM

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_BASE = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")

class DeepSeekClient(BaseLLM):
    client_class: str = "DeepSeekClient"

    def __init__(self, model, temperature=1.0, api_key=None, **kwargs):
        """
        Initialize the OpenAI client.

        Args:
            model (str): The model name (e.g., "gpt-4o-mini").
            api_key (str, optional): Your OpenAI API key.
            **kwargs: Additional parameters.
        """
        super().__init__(model, temperature, **kwargs)
        self.provider = "deepseek"
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.model = model
        self.reasoning_history_policy = "provider_required_transport_only"
        self._tool_reasoning = {}
        self.base_url = kwargs.get("base_url") or DEEPSEEK_API_BASE
        self.api_client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.request_timeout,
        )


    # Chat Completion API
    def chat_completion(self, messages, tools=None):
        """
        Send the conversation history (and tools, if provided) to 
        OpenAI's API and return the response.

        Args:
            messages (list): Conversation history.
            tools (list, optional): Tool specifications.

        Returns:
        """
        # The agent keeps reasoning out of its request logs. DeepSeek thinking
        # tool turns nevertheless require the original field on the wire.
        # Restore it here on fresh dictionaries, scoped to this client session.
        transport_messages = []
        for message in messages:
            copied = dict(message)
            if copied.get("role") == "assistant":
                for call in copied.get("tool_calls") or []:
                    call_id = call.get("id")
                    if call_id in self._tool_reasoning:
                        copied["reasoning_content"] = self._tool_reasoning[call_id]
                        break
            transport_messages.append(copied)
        response = self.api_client.chat.completions.create(
            model=self.model,
            messages=transport_messages,
            tools=tools,
            temperature=self.temperature,
            **self.output_token_options(),
            **self.tool_call_options(tools),
        )

        if response.choices:
            message = response.choices[0].message
            reasoning = getattr(message, "reasoning_content", None)
            if reasoning is not None:
                for call in getattr(message, "tool_calls", None) or []:
                    self._tool_reasoning[call.id] = reasoning
        return response

    def to_dict(self):
        return {
            'client_class': self.client_class,
            'model': self.model,
            'temperature': self.temperature,
            'parallel_tool_calls': self.parallel_tool_calls,
            'max_output_tokens': self.max_output_tokens,
        }
