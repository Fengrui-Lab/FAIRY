# llm_clients/openai_client.py
import os
from openai import OpenAI

from fairy.agents.llm.base_llm import BaseLLM

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

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
        self.provider = "openai"
        self.api_key = DEEPSEEK_API_KEY
        # self.api_client = OpenAI()
        # self.model = "deepseek-reasoner"
        self.model = "deepseek-chat"
        self.base_url="https://api.deepseek.com"
        self.api_client = OpenAI(api_key=self.api_key, base_url=self.base_url)


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
        response = self.api_client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            temperature=self.temperature,
        )

        return response

    def to_dict(self):
        return {
            'client_class': self.client_class,
            'model': self.model,
            'temperature': self.temperature
        }