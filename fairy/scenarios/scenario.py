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
    crop_backend: str = "legacy"
    crop_backend_options: dict[str, Any] = field(default_factory=dict)

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
        if self.crop_backend != "legacy" or self.crop_backend_options:
            from fairy.apps.farm_world.multi_farm import farm_world_apps, unwrap_app

            farms = farm_world_apps(self.apps or [])
            # Paddy worlds declare their own native adapter instead of using
            # ridge physics. Keep their configuration separate from farm fields.
            other_worlds = [unwrap_app(app) for app in self.apps or []
                            if getattr(unwrap_app(app), "simulation_world", False)]
            if not farms and not other_worlds:
                raise ValueError("Crop backend configured for a scenario without a FarmWorldApp or simulation world")
            if self.crop_backend == "wofost":
                from zoneinfo import ZoneInfo
                # Native day boundaries must follow the scene's forcing calendar.
                # Historical scenes default to China; explicit locations override it.
                calendar = ZoneInfo(getattr(self, "timezone_name", "Asia/Shanghai"))
                for farm_world in farms:
                    farm_world.simulation_timezone = calendar
                    if farm_world._weather_app is not None:
                        farm_world._weather_app.simulation_timezone = calendar
            for farm_world in [*farms, *other_worlds]:
                farm_world.configure_crop_backend(
                    self.crop_backend, **self.crop_backend_options
                )
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
        from fairy.apps.farm_world.multi_farm import iter_apps_of_type

        candidates = iter_apps_of_type(self.apps or [], app_type)
        if app_name is not None:
            candidates = [app for app in candidates if app.name == app_name]
        if len(candidates) == 1:
            return cast(T, candidates[0])
        if len(candidates) > 1:
            raise ValueError(
                f"Ambiguous app type {app_type.__name__}: "
                f"{[app.name for app in candidates]}. Pass an explicit app_name."
            )
        raise ValueError(f"App {app_name or app_type.__name__} of type {app_type.__name__} not found in scenario.")

    def validate(self):
        return None
