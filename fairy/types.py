from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Callable

from fairy.tool_utils import OperationType


def _function_name(function: Callable[..., Any] | None) -> str | None:
    if function is None:
        return None
    return getattr(function, "__name__", function.__class__.__name__)


@dataclass
class CapturedEvent:
    app: Any
    function: Callable[..., Any]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    operation_type: Any = None
    event_id: str | None = None
    is_oracle: bool = False
    dependencies: list[Any] = field(default_factory=list)
    successors: list[Any] = field(default_factory=list)
    delay_seconds: float = 0.0

    def oracle(self):
        self.is_oracle = True
        return self

    def with_id(self, event_id: str):
        self.event_id = event_id
        return self

    def depends_on(self, dependency: Any, delay_seconds: float = 0.0):
        if dependency is not None:
            dependencies = dependency if isinstance(dependency, list) else [dependency]
            for event in dependencies:
                self.dependencies.append(event)
                if hasattr(event, "successors"):
                    event.successors.append(self)
        self.delay_seconds = delay_seconds
        return self

    def execute(self) -> Any:
        return self.function(self.app, *self.args, **self.kwargs)


class EventRegisterer:
    _stack: list[list[CapturedEvent]] = []
    last_events: list[CapturedEvent] = []

    @classmethod
    def is_capturing(cls) -> bool:
        return bool(cls._stack)

    @classmethod
    def add(cls, event: CapturedEvent) -> CapturedEvent:
        if cls._stack:
            cls._stack[-1].append(event)
        return event

    @classmethod
    @contextmanager
    def capture_mode(cls):
        events: list[CapturedEvent] = []
        cls._stack.append(events)
        try:
            yield events
        finally:
            cls._stack.pop()
            cls.last_events = events


def event_registered(operation_type: Any = None):
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(self, *args: Any, **kwargs: Any) -> Any:
            if EventRegisterer.is_capturing():
                return EventRegisterer.add(
                    CapturedEvent(
                        app=self,
                        function=func,
                        args=args,
                        kwargs=kwargs,
                        operation_type=operation_type,
                    )
                )
            return func(self, *args, **kwargs)

        setattr(wrapper, "_event_operation_type", operation_type)
        return wrapper

    return decorator


class EventType(Enum):
    AGENT = "AGENT"
    ENV = "ENV"
    CONDITION = "CONDITION"
    VALIDATION = "VALIDATION"
    USER = "USER"
    STOP = "STOP"


@dataclass
class Action:
    function: Callable[..., Any]
    args: dict[str, Any] = field(default_factory=dict)
    resolved_args: dict[str, Any] = field(default_factory=dict)
    app: Any | None = None
    action_id: str | None = None
    operation_type: OperationType | None = OperationType.READ
    tool_metadata: Any | None = None

    def execute(self) -> Any:
        args = self.resolved_args if self.resolved_args else self.args
        if self.app is not None:
            return self.function(**{k: v for k, v in args.items() if k != "self"})
        return self.function(**{k: v for k, v in args.items() if k != "self"})

    @property
    def function_name(self) -> str | None:
        return _function_name(self.function)

    @property
    def class_name(self) -> str | None:
        return self.app.__class__.__name__ if self.app is not None else None

    @property
    def app_name(self) -> str | None:
        if self.app is None:
            return self.class_name
        return getattr(self.app, "name", self.class_name)


@dataclass
class EventMetadata:
    return_value: Any | None = None
    exception: str | None = None
    exception_stack_trace: str | None = None
    completed: bool = True


@dataclass(order=True)
class CompletedEvent:
    event_type: EventType = EventType.AGENT
    event_time: float = 0.0
    event_relative_time: float | None = None
    event_id: str = ""
    action: Action | Any | None = None
    metadata: EventMetadata | None = None
    dependencies: list[Any] = field(default_factory=list, compare=False)
    successors: list[Any] = field(default_factory=list, compare=False)

    def app_class_name(self) -> str | None:
        action = self.action
        app = getattr(action, "app", None)
        return app.__class__.__name__ if app is not None else None

    def app_name(self) -> str | None:
        action = self.action
        app = getattr(action, "app", None)
        return getattr(app, "name", None) if app is not None else None

    def function_name(self) -> str | None:
        return getattr(self.action, "function_name", None)

    def failed(self) -> bool:
        return bool(self.metadata and self.metadata.exception is not None)

    def get_args(self) -> dict[str, Any]:
        action = self.action
        if action is None:
            return {}
        return dict(getattr(action, "resolved_args", None) or getattr(action, "args", {}) or {})

    def copy(self) -> "CompletedEvent":
        return CompletedEvent(
            event_type=self.event_type,
            event_time=self.event_time,
            event_relative_time=self.event_relative_time,
            event_id=self.event_id,
            action=self.action,
            metadata=self.metadata,
            dependencies=list(self.dependencies),
            successors=list(self.successors),
        )


@dataclass
class EventLog:
    past_events: list[CompletedEvent] = field(default_factory=list)

    def put(self, event: CompletedEvent | list[CompletedEvent]) -> None:
        events = event if isinstance(event, list) else [event]
        self.past_events.extend(events)

    def __len__(self) -> int:
        return len(self.past_events)

    def list_view(self) -> list[CompletedEvent]:
        return sorted(self.past_events, key=lambda event: float(event.event_time or 0.0))

    @staticmethod
    def from_list_view(events: list[CompletedEvent]) -> "EventLog":
        return EventLog(list(events))


class CapabilityTag:
    pass


class AbstractEvent:
    pass


class Event:
    pass


class OracleEvent:
    pass


class EnvironmentState:
    pass


class AbstractEnvironment:
    pass


class ActionDescription:
    pass


class ConditionCheckEvent:
    pass


class EventTimeComparator:
    pass


class Hint:
    pass


class HintType:
    pass


class ScenarioGUIConfig:
    pass


class ToolAugmentationConfig:
    pass
