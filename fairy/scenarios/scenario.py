from __future__ import annotations

from dataclasses import MISSING, dataclass, field, fields
from typing import Any, Type, TypeVar, cast

from fairy.apps.app import App
from fairy.scenarios.workflow import Workflow

T = TypeVar("T", bound=App)


@dataclass
class Scenario:
    scenario_class: str = "base_scenario"
    scenario_id: str = ""
    scenario_input: str = ""
    dynamic_events: list[Any] | None = field(default_factory=list)
    start_time: float | None = None
    duration: float | None = None
    queue_based_loop: bool = False
    time_increment_in_seconds: int = 1
    apps: list[App] | None = field(default_factory=list)
    events: list[Any] = field(default_factory=list)
    workflow: Workflow | None = field(default_factory=Workflow)
    seed: int = 0
    detailed_briefing: bool = True
    expects_agent_harvest: bool = True
    additional_system_prompt: str | None = None

    def __post_init__(self) -> None:
        self._apply_migrated_class_defaults()
        if self.apps is None:
            self.apps = []
        if self.dynamic_events is None:
            self.dynamic_events = []
        if self.workflow is None:
            self.workflow = Workflow()

    def _apply_migrated_class_defaults(self) -> None:
        """Honor ARE-style scenario class attributes on dataclass instances."""
        base_fields = {scenario_field.name: scenario_field for scenario_field in fields(Scenario)}
        for name, scenario_field in base_fields.items():
            if name in {"apps", "dynamic_events", "events", "workflow"}:
                continue
            if name not in self.__class__.__dict__:
                continue
            current_value = getattr(self, name)
            default_value = scenario_field.default
            if default_value is MISSING:
                continue
            if current_value == default_value:
                setattr(self, name, getattr(self.__class__, name))

    def setup(self, *args: Any, **kwargs: Any) -> None:
        if self.apps:
            return
        if hasattr(self, "initiate_scenario"):
            self.initiate_scenario(*args, **kwargs)
        else:
            self.init_and_populate_apps(*args, **kwargs)
        if hasattr(self, "build_events_flow") and not self.events:
            result = self.build_events_flow()
            if result is not None and not self.events:
                self.events = list(result)
            if not self.events:
                from fairy.types import EventRegisterer

                self.events = list(EventRegisterer.last_events)

    def initiate_scenario(self, *args: Any, **kwargs: Any) -> None:
        self.init_and_populate_apps(*args, **kwargs)

    def initialize(self, *args: Any, **kwargs: Any) -> None:
        self.setup(*args, **kwargs)

    def init_and_populate_apps(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("Scenario must implement setup hooks.")

    def oracle_solution(self, run_oracle: bool = False) -> None:
        raise NotImplementedError("Scenario must implement oracle_solution or build_events_flow.")

    def get_typed_app(self, app_type: Type[T], app_name: str | None = None) -> T:
        name = app_name or app_type.__name__
        for app in self.apps or []:
            if isinstance(app, app_type) and app.name == name:
                return cast(T, app)
        raise ValueError(f"App {name} of type {app_type.__name__} not found in scenario.")

    def validate(self):
        return None
