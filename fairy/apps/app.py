from __future__ import annotations

import inspect
import random
from enum import Enum, auto
from typing import Any, Callable

from fairy.time_manager import TimeManager
from fairy.tool_utils import AppTool, ToolAttributeName, build_tool


class Protocol(Enum):
    FILE_SYSTEM = "FILE_SYSTEM"


class ToolType(Enum):
    APP = auto()
    USER = auto()
    ENV = auto()
    DATA = auto()


class App:
    """Base app used by FAIRY controllers and tool discovery."""

    def __init__(self, name: str | None = None, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.name = self.__class__.__name__ if name is None else name
        self.is_state_modified = False
        self.add_event_callbacks: dict[str, Callable[[Any], None]] = {}
        self.schedule_event_callbacks: dict[str, Callable[[Any], None]] = {}
        self.failure_probability: float | None = None
        self.time_manager = TimeManager()
        self.set_seed(0)

    def register_time_manager(self, time_manager: TimeManager) -> None:
        self.time_manager = time_manager

    def set_seed(self, seed: int) -> None:
        combined_seed = f"{seed}_{self.name}"
        self.seed = hash(combined_seed) % (2**32)
        self.rng = random.Random(self.seed)

    def register_to_env(self, key: str, add_event: Callable[[Any], None]) -> None:
        self.add_event_callbacks[key] = add_event

    def add_event(self, event: Any) -> None:
        for callback in self.add_event_callbacks.values():
            callback(event)

    def register_event_scheduler(
        self, key: str, schedule_event: Callable[[Any], None]
    ) -> None:
        self.schedule_event_callbacks[key] = schedule_event

    def schedule_event(self, event: Any) -> None:
        for callback in self.schedule_event_callbacks.values():
            callback(event)

    def get_implemented_protocols(self) -> list[Protocol]:
        return []

    def connect_to_protocols(self, protocols: dict[Protocol, Any]) -> None:
        pass

    def get_state(self) -> dict[str, Any] | None:
        return None

    def load_state(self, state_dict: dict[str, Any]) -> None:
        pass

    def reset(self) -> None:
        self.rng = random.Random(self.seed)

    def app_name(self) -> str:
        return self.name

    def set_failure_probability(self, failure_probability: float) -> None:
        self.failure_probability = failure_probability

    def get_tools_with_attribute(
        self, attribute: ToolAttributeName, tool_type: ToolType
    ) -> list[AppTool]:
        attr_name = attribute.value
        tools: list[AppTool] = []
        seen: set[str] = set()
        for cls in inspect.getmro(self.__class__):
            for name, value in cls.__dict__.items():
                if name in seen:
                    continue
                if callable(value) and hasattr(value, attr_name):
                    tools.append(build_tool(self, value, self.failure_probability))
                    seen.add(name)
        return tools

    def get_tools(self) -> list[AppTool]:
        return self.get_tools_with_attribute(ToolAttributeName.APP, ToolType.APP)

    def get_user_tools(self) -> list[AppTool]:
        return self.get_tools_with_attribute(ToolAttributeName.USER, ToolType.USER)

    def get_env_tools(self) -> list[AppTool]:
        return self.get_tools_with_attribute(ToolAttributeName.ENV, ToolType.ENV)

    def get_data_tools(self) -> list[AppTool]:
        return self.get_tools_with_attribute(ToolAttributeName.DATA, ToolType.DATA)

