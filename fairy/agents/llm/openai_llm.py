# llm_clients/openai_client.py

from openai import OpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message_function_tool_call import (
    ChatCompletionMessageFunctionToolCall,
    Function,
)
from openai.types.completion_usage import (
    CompletionTokensDetails,
    CompletionUsage,
    PromptTokensDetails,
)
from fairy.agents.llm.base_llm import BaseLLM


class OpenAILLM(BaseLLM):
    llm_class: str = "OpenAILLM"

    CHAT_COMPLETION_MODELS = {
        "gpt-4o-mini",
        "gpt-4o",
    }

    RESPONSES_API_MODELS = {
        "gpt-5-nano",
        "gpt-5-mini",
        "gpt-5",
        "gpt-6-luna",
        "o1",
        "o3",
    }

    # Chat completions accept function tools for these models only with this
    # reasoning effort (OpenAI 400 error otherwise; docs/jev/PROGRESS.md, Part 2 Step 5).
    # Any other effort goes through the Responses API instead.
    REASONING_EFFORT = {
        "gpt-6-luna": "none",
    }

    def __init__(self, model, temperature=0.1, api_key=None, reasoning_effort=None, **kwargs):
        """
        Initialize the OpenAI client.

        Args:
            model (str): The model name (e.g., "gpt-4o-mini").
            api_key (str, optional): Your OpenAI API key.
            reasoning_effort (str, optional): For models in REASONING_EFFORT, a
                value other than the default uses the Responses API (/v1/responses).
            **kwargs: Additional parameters.
        """
        super().__init__(model, temperature, **kwargs)
        self.provider = "openai"
        self.api_key = api_key
        self.api_client = OpenAI(timeout=self.request_timeout)

        self.reasoning_effort = reasoning_effort or self.REASONING_EFFORT.get(model)
        self.api_mode = self._resolve_api_mode(model)

    def _resolve_api_mode(self, model: str) -> str:
        """
        Determine which OpenAI API mode to use for the given model.
        """
        if model in self.CHAT_COMPLETION_MODELS:
            return "chat_completions"
        elif model in self.RESPONSES_API_MODELS:
            if model in self.REASONING_EFFORT and self.reasoning_effort != self.REASONING_EFFORT[model]:
                return "responses"
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
                **(
                    {"reasoning_effort": self.reasoning_effort}
                    if self.model in self.REASONING_EFFORT
                    else {}
                ),
            )
        elif self.api_mode == "responses":
            response = self._responses_completion(messages, tools)
        else:
            raise RuntimeError(f"Invalid API mode: {self.api_mode}")
        return response

    # Responses API
    def _responses_completion(self, messages, tools=None):
        """
        Call /v1/responses and return the reply as a ChatCompletion, so callers
        see the same object as on the chat route. Stateless (store=False);
        reasoning items are not sent back, as on the chat route.
        """
        response = self.api_client.responses.create(
            model=self.model,
            input=self._responses_input(messages),
            reasoning={"effort": self.reasoning_effort},
            store=False,
            **({"tools": self._responses_tools(tools)} if tools else {}),
            **self.output_token_options(parameter="max_output_tokens"),
            **self.tool_call_options(tools),
        )
        return self._as_chat_completion(response)

    @staticmethod
    def _responses_input(messages):
        """Chat messages (dicts) -> Responses input items."""
        items = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if role == "tool":
                items.append({
                    "type": "function_call_output",
                    "call_id": message["tool_call_id"],
                    "output": str(content or ""),
                })
                continue
            if content:
                items.append({"role": role, "content": str(content)})
            for call in message.get("tool_calls") or []:
                items.append({
                    "type": "function_call",
                    "call_id": call["id"],
                    "name": call["function"]["name"],
                    "arguments": call["function"].get("arguments") or "{}",
                })
        return items

    @staticmethod
    def _responses_tools(tools):
        """Chat tool schemas -> Responses function tools."""
        converted = []
        for tool in tools:
            function = tool.get("function", tool)
            converted.append({
                "type": "function",
                "name": function["name"],
                "description": function.get("description", ""),
                "parameters": function.get("parameters") or {"type": "object", "properties": {}},
                "strict": False,
            })
        return converted

    @staticmethod
    def _as_chat_completion(response):
        text_parts = []
        tool_calls = []
        for item in response.output or []:
            if item.type == "message":
                for part in item.content or []:
                    if getattr(part, "type", None) == "output_text":
                        text_parts.append(part.text)
            elif item.type == "function_call":
                tool_calls.append(ChatCompletionMessageFunctionToolCall(
                    id=item.call_id,
                    type="function",
                    function=Function(name=item.name, arguments=item.arguments or "{}"),
                ))
        incomplete = getattr(response, "incomplete_details", None)
        if response.status == "incomplete" and getattr(incomplete, "reason", None) == "max_output_tokens":
            finish_reason = "length"
        elif tool_calls:
            finish_reason = "tool_calls"
        else:
            finish_reason = "stop"
        usage = response.usage
        input_details = getattr(usage, "input_tokens_details", None)
        output_details = getattr(usage, "output_tokens_details", None)
        return ChatCompletion.model_construct(
            id=response.id,
            object="chat.completion",
            created=int(response.created_at or 0),
            model=response.model,
            choices=[Choice.model_construct(
                index=0,
                finish_reason=finish_reason,
                message=ChatCompletionMessage(
                    role="assistant",
                    content="\n".join(text_parts) or None,
                    tool_calls=tool_calls or None,
                ),
            )],
            usage=CompletionUsage(
                prompt_tokens=usage.input_tokens if usage else 0,
                completion_tokens=usage.output_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
                prompt_tokens_details=PromptTokensDetails(
                    cached_tokens=getattr(input_details, "cached_tokens", 0) or 0
                ),
                completion_tokens_details=CompletionTokensDetails(
                    reasoning_tokens=getattr(output_details, "reasoning_tokens", 0) or 0
                ),
            ),
        )

    def to_dict(self):
        return {
            'llm_class': self.llm_class,
            'model': self.model,
            'temperature': self.temperature,
            'parallel_tool_calls': self.parallel_tool_calls,
            'max_output_tokens': self.max_output_tokens,
            'reasoning_effort': self.reasoning_effort,
            'api_mode': self.api_mode,
        }
