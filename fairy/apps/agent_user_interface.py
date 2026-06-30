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
        self.messages.append(content)
        return content

    @app_tool()
    @event_registered()
    def send_message_to_user(self, content: str) -> str:
        self.messages.append(content)
        return content
