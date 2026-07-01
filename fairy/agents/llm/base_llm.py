# llm/base_llm.py


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
