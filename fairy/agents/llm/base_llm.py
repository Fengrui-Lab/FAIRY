# llm/base_llm.py

import os


def _coerce_bool(value, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return True
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{field_name} must be a boolean value, got {value!r}")


class BaseLLM:
    llm_class: str = "BaseLLM"

    def __init__(self, model, temperature, **kwargs):
        """
        Initialize the base LLM client.

        Args:
            model (str): The name of the model to use.
            **kwargs: Additional keyword arguments (e.g., API keys).
        """
        self.model = model
        self.temperature = temperature
        # Store any additional initialization parameters (e.g., api_key)
        self.params = kwargs
        self.llm_class = self.__class__.llm_class
        raw_timeout = kwargs.get("timeout", os.getenv("FAIRY_LLM_REQUEST_TIMEOUT_S"))
        self.request_timeout = (
            float(raw_timeout) if raw_timeout not in (None, "") else None
        )
        raw_max_tokens = kwargs.get(
            "max_output_tokens",
            kwargs.get("max_tokens", os.getenv("FAIRY_LLM_MAX_OUTPUT_TOKENS", "2048")),
        )
        self.max_output_tokens = int(raw_max_tokens)
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be a positive integer")
        raw_parallel_tool_calls = kwargs.get(
            "parallel_tool_calls", os.getenv("FAIRY_PARALLEL_TOOL_CALLS", "true")
        )
        self.parallel_tool_calls = _coerce_bool(
            raw_parallel_tool_calls, "parallel_tool_calls"
        )

    def tool_call_options(self, tools=None):
        if tools is None:
            return {}
        return {"parallel_tool_calls": self.parallel_tool_calls}

    def output_token_options(self, *, parameter: str = "max_tokens"):
        return {parameter: self.max_output_tokens}

    def chat_completion(self, messages, tools=None):
        """
        Given a conversation history (messages) and an optional list of tools,
        return a response from the language model.

        Args:
            messages (list): A list of message dictionaries representing the conversation history.
            tools (list, optional): A list of tool specifications available for function calling.

        Returns:
            dict: A dictionary containing the model's response, input tokens, output tokens, etc.
        """
        raise NotImplementedError(
            "chat_completion() must be implemented by subclasses.")

    def client_info(self):
        return {
            'llm_class': self.llm_class,
            'model': self.model
        }

    @classmethod
    def llm_builder(cls, cfg: dict) -> "BaseLLM":
        """
        Create an LLM instance based on the provided configuration.

        The configuration is expected to include at least:
            - provider: a string indicating the provider type ("openai", "anthropic", "ollama", or "vllm").
            - model: the model name.
            - temperature: the temperature parameter (with a default provided if missing).
            - Any additional keys will be forwarded as keyword arguments.

        Args:
            cfg (dict): Configuration dictionary.

        Returns:
            BaseLLM: An instance of the appropriate client subclass.
        """
        provider = cfg.get("provider", "openai").lower()
        model = cfg.get("model", "gpt-4o-mini")
        temperature = cfg.get("temperature", 0.1)
        # Gather any additional parameters.
        extra_params = {
            k: v for k,
            v in cfg.items() if k not in [
                "client",
                "model",
                "temperature"]}

        # NOTE:  This could also be a standalone factory function, for example
        # `create_llm_endpoint(cfg: dict) -> BaseLLM` but don't really like factories
        match provider:
            case "default"|"openai":
                from .openai_llm import OpenAILLM
                return OpenAILLM(model, temperature, **extra_params)
            case "llama-api" | "openai-compatible":
                from .openai_compatible_client import OpenAICompatibleClient
                return OpenAICompatibleClient(model, temperature, **extra_params)
            case "deepseek" | "deepseek-json":
                # deepseek-json is a legacy ARE config label; FAIRY uses
                # OpenAI-compatible function calling through the same client.
                from .deepseek_client import DeepSeekClient
                return DeepSeekClient(model, temperature, **extra_params)
            case "qwen" | "qwen-json":
                # qwen-json is a legacy ARE label; FAIRY keeps Qwen on the
                # OpenAI-compatible function-calling path.
                from .qwen_client import QwenClient
                return QwenClient(model, temperature, **extra_params)
            case "anthropic":
                from .anthropic_client import AnthropicClient
                return AnthropicClient(model, temperature, **extra_params)
            case "ollama":
                from .ollama_client import OllamaClient
                return OllamaClient(model, temperature, **extra_params)
            case "vllm":
                from .vllm_client import VLLMClient
                return VLLMClient(model, temperature, **extra_params)
            case _:
                raise ValueError(f"Unsupported LLM Provider: {provider}")
