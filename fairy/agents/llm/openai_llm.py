# llm_clients/openai_client.py

from openai import OpenAI
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
        self.api_client = OpenAI(timeout=self.request_timeout)

        self.api_mode = self._resolve_api_mode(model)

    def _resolve_api_mode(self, model: str) -> str:
        """
        Determine which OpenAI API mode to use for the given model.
        """
        if model in self.CHAT_COMPLETION_MODELS:
            return "chat_completions"
        elif model in self.RESPONSES_API_MODELS:
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
            )
        else:
            raise RuntimeError(f"Invalid API mode: {self.api_mode}")
        return response

    def to_dict(self):
        return {
            'llm_class': self.llm_class,
            'model': self.model,
            'temperature': self.temperature,
            'parallel_tool_calls': self.parallel_tool_calls,
            'max_output_tokens': self.max_output_tokens,
        }
