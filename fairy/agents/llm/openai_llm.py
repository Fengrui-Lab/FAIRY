# llm_clients/openai_client.py

import copy

from openai import OpenAI
from openai.types.chat import ChatCompletion
from fairy.agents.llm.base_llm import BaseLLM


class OpenAILLM(BaseLLM):
    llm_class: str = "OpenAILLM"

    CHAT_COMPLETION_MODELS = {
        "gpt-4o-mini",
        "gpt-4o",
    }

    RESPONSES_API_MODELS = {"gpt-6-luna"}

    REASONING_CHAT_MODELS = {
        "gpt-5-nano",
        "gpt-5-mini",
        "gpt-5",
        "o1",
        "o3",
    }

    def __init__(self, model, temperature=0.1, api_key=None, **kwargs):
        """
        Initialize the OpenAI client.

        Args:
            model (str): The model name (e.g., "gpt-4o-mini").
            api_key (str, optional): Your OpenAI API key.
            **kwargs: Additional parameters.
        """
        super().__init__(model, temperature, **kwargs)
        self.provider = "openai"
        self.api_key = api_key
        self.api_client = OpenAI(api_key=api_key, timeout=self.request_timeout)

        self.api_mode = self._resolve_api_mode(model)
        self.reasoning_effort = (
            kwargs.get("reasoning_effort", "medium") if self.api_mode == "responses" else None
        )
        if self.api_mode == "responses" and self.reasoning_effort not in {
            "none", "low", "medium", "high", "xhigh", "max",
        }:
            raise ValueError("Unsupported Luna reasoning_effort")
        self.reasoning_history_policy = (
            "encrypted_tool_context" if self.api_mode == "responses" else "exclude"
        )
        # Unique tool call IDs isolate histories when A2A agents share a client.
        # These protocol items never enter exported messages or runtime logs.
        self._response_turns = {}

    def _resolve_api_mode(self, model: str) -> str:
        """
        Determine which OpenAI API mode to use for the given model.
        """
        if model in self.CHAT_COMPLETION_MODELS:
            return "chat_completions"
        elif model in self.RESPONSES_API_MODELS:
            return "responses"
        elif model in self.REASONING_CHAT_MODELS:
            # NOTE: we still use completions.create with reasoning models
            return "reasoning"
        else:
            raise ValueError(f"Unsupported OpenAI model name: {model}")

    # Chat Completion API
    def chat_completion(self, messages, tools=None):
        """
        Send the conversation history (and tools, if provided) to
        OpenAI's API and return the response.

        Args:
            messages (list): Conversation history.
            tools (list, optional): Tool specifications.
        """
        if self.api_mode == "responses":
            return self._responses_completion(messages, tools)
        if self.api_mode == "chat_completions":
            response = self.api_client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                temperature=self.temperature,
                **self.output_token_options(),
                **self.tool_call_options(tools),
            )
        elif self.api_mode == "reasoning":
            # https://developers.openai.com/api/docs/guides/migrate-to-responses
            response = self.api_client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                **self.output_token_options(parameter="max_completion_tokens"),
                **self.tool_call_options(tools),
            )
        else:
            raise RuntimeError(f"Invalid API mode: {self.api_mode}")
        return response

    def _responses_input(self, messages):
        items = []
        for message in messages:
            if hasattr(message, "model_dump"):
                message = message.model_dump(exclude_none=True)
            role = message["role"]
            if role == "tool":
                items.append({"type": "function_call_output",
                              "call_id": message["tool_call_id"],
                              "output": message.get("content") or ""})
                continue
            calls = message.get("tool_calls") or []
            retained = {call["id"]: call for call in calls}
            cached = self._response_turns.get(calls[0]["id"]) if calls else None
            cached_content = "".join(
                part["text"] for item in (cached or []) if item["type"] == "message"
                for part in item["content"] if part["type"] == "output_text"
            )
            if cached and cached_content == (message.get("content") or "") and all(
                any(item.get("type") == "function_call"
                    and item["call_id"] == call["id"]
                    and item["name"] == call["function"]["name"]
                    and item["arguments"] == call["function"]["arguments"]
                    for item in cached)
                for call in calls
            ):
                # Preserve item ordering without restoring dropped tool calls.
                items.extend(copy.deepcopy(item) for item in cached
                             if item["type"] != "function_call" or item["call_id"] in retained)
                continue
            content = message.get("content")
            if content is not None and (content or not calls):
                items.append({"role": role, "content": content})
            for call in calls:
                items.append({"type": "function_call", "call_id": call["id"],
                              "name": call["function"]["name"],
                              "arguments": call["function"]["arguments"]})
        return items

    def _responses_completion(self, messages, tools):
        options = {}
        if tools is not None:
            options["tools"] = [
                {"type": "function", **tool["function"],
                 "strict": tool["function"].get("strict", False)}
                for tool in tools
            ]
            options.update(self.tool_call_options(tools))
        response = self.api_client.responses.create(
            model=self.model,
            input=self._responses_input(messages),
            reasoning={"effort": self.reasoning_effort},
            max_output_tokens=self.max_output_tokens,
            store=False,
            include=["reasoning.encrypted_content"],
            **options,
        )
        output = [item.model_dump(exclude_none=True) for item in response.output]
        calls = [{"id": item["call_id"], "type": "function",
                  "function": {"name": item["name"], "arguments": item["arguments"]}}
                 for item in output if item["type"] == "function_call"]
        content = "".join(part["text"] for item in output if item["type"] == "message"
                          for part in item["content"] if part["type"] == "output_text")
        refusal = "".join(part["refusal"] for item in output if item["type"] == "message"
                          for part in item["content"] if part["type"] == "refusal")
        finish_reason = "tool_calls" if calls else "stop"
        rejection = None
        if response.status != "completed":
            reason = getattr(response.incomplete_details, "reason", None)
            if reason == "max_output_tokens":
                finish_reason, rejection = "length", "output_truncated"
            else:
                rejection = "response_" + str(response.status)
        if response.status == "completed":
            for call in calls:
                self._response_turns[call["id"]] = output
        usage = response.usage
        normalized_usage = None if usage is None else {
            "prompt_tokens": usage.input_tokens,
            "completion_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
            "prompt_tokens_details": usage.input_tokens_details.model_dump(),
            "completion_tokens_details": usage.output_tokens_details.model_dump(),
        }
        # Keep the Agent's existing response, billing and retry contract.
        return ChatCompletion.model_validate({
            "id": response.id, "object": "chat.completion",
            "created": int(response.created_at), "model": response.model,
            "choices": [{"index": 0, "finish_reason": finish_reason,
                         "message": {"role": "assistant", "content": content or None,
                                     "refusal": refusal or None, "tool_calls": calls or None}}],
            "usage": normalized_usage,
            "response_rejection_reason": rejection,
        })

    def to_dict(self):
        return {
            'llm_class': self.llm_class,
            'model': self.model,
            'temperature': self.temperature,
            'parallel_tool_calls': self.parallel_tool_calls,
            'max_output_tokens': self.max_output_tokens,
            'api_mode': self.api_mode,
            'reasoning_effort': self.reasoning_effort,
        }
