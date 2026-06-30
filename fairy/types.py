from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable


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
    delay_seconds: float = 0.0

    def oracle(self):
        self.is_oracle = True
        return self

    def with_id(self, event_id: str):
        self.event_id = event_id
        return self

    def depends_on(self, dependency: Any, delay_seconds: float = 0.0):
        if dependency is not None:
            self.dependencies.append(dependency)
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


class CompletedEvent:
    pass


class ConditionCheckEvent:
    pass


class EventTimeComparator:
    pass


class EventType:
    pass


class Hint:
    pass


class HintType:
    pass


class ScenarioGUIConfig:
    pass


class ToolAugmentationConfig:
    pass
