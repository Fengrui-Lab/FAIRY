from __future__ import annotations

from fairy.apps.app import App
from fairy.tool_utils import app_tool
from fairy.types import event_registered


class AgentUserInterface(App):
    def __init__(self, name: str | None = None):
        super().__init__(name or "AgentUserInterface")
        self.messages: list[str] = []

    @app_tool()
    @event_registered()
    def send_message_to_agent(self, content: str) -> str:
        """
        Send a message to the agent.

        This is normally used by scenario setup or replay to deliver the task
        briefing to the agent. Agent runs hide this tool from the agent-facing
        toolset so the model cannot inject new user messages into its own
        conversation.

        Args:
            content: The message content to send to the agent.

        Returns:
            The content that was sent.
        """
        self.messages.append(content)
        return content

    @app_tool()
    @event_registered()
    def send_message_to_user(self, content: str) -> str:
        """
        Send a message to the user.

        Use this as the final communication channel when the task is complete
        or cannot be completed with the available tools.

        Args:
            content: The content to send to the user.

        Returns:
            The content that was sent.
        """
        self.messages.append(content)
        return content
