"""Farm identity, private domain state, and explicit fleet composition.

Shared fleets register one service surface and independently configured assets.
A site does not allocate equipment. Lazy namespaced devices exist only for the
legacy single-farm interface; shared operation views hold no device state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Type, TypeVar

from fairy.apps.app import App
from fairy.apps.farm_world.drone_app import DroneApp
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.field_ops_app import FieldOpsApp
from fairy.apps.farm_world.robot_app import RobotApp
from fairy.apps.farm_world.sensor_app import SensorApp
from fairy.apps.farm_world.tractor_app import TractorApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.farm_world.assets import AssetSpec

T = TypeVar("T", bound=App)


def unwrap_app(app: Any) -> Any:
    """Unwrap controller adapters while tolerating a malformed wrapper cycle."""
    seen: set[int] = set()
    while hasattr(app, "wrapped_app") and id(app) not in seen:
        seen.add(id(app))
        app = app.wrapped_app
    return app


def iter_apps_of_type(apps: Iterable[Any], app_type: Type[T]) -> list[T]:
    result: list[T] = []
    seen: set[int] = set()
    for app in apps:
        candidate = unwrap_app(app)
        candidates = [candidate]
        runtime = getattr(candidate, "runtime", None)
        if runtime is not None:
            candidates.extend(runtime.domain_apps)
        for item in candidates:
            if isinstance(item, app_type) and id(item) not in seen:
                result.append(item)
                seen.add(id(item))
    return result


def farm_world_apps(apps: Iterable[Any]) -> list[FarmWorldApp]:
    return iter_apps_of_type(apps, FarmWorldApp)


@dataclass(frozen=True)
class FarmSpec:
    farm_id: str
    name: str
    crop_type: str = "soybean"
    num_ridges: int = 64
    field_length_m: float = 268.0
    ridge_width_m: float = 1.1

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", self.farm_id):
            raise ValueError("farm_id must start with a letter and contain letters, numbers or underscores")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", self.name):
            raise ValueError("Farm name prefix must contain only letters, numbers or underscores")


@dataclass
class FarmSite:
    spec: FarmSpec
    farm: FarmWorldApp
    weather: WeatherApp
    field_ops: FieldOpsApp
    sensor: SensorApp
    station_id: str = ""
    _legacy_mode: bool = True
    _legacy_devices: dict[str, App] = field(default_factory=dict, repr=False)
    _runtime: Any = field(default=None, repr=False)

    @classmethod
    def create(cls, farm_id: str, name: str, *, create_devices: bool = True,
               station_id: str | None = None, weather_app: WeatherApp | None = None,
               **kwargs: Any) -> "FarmSite":
        return cls.from_spec(FarmSpec(farm_id=farm_id, name=name, **kwargs),
                             create_devices=create_devices, station_id=station_id,
                             weather_app=weather_app)

    @classmethod
    def from_spec(cls, spec: FarmSpec, *, create_devices: bool = True,
                  station_id: str | None = None,
                  weather_app: WeatherApp | None = None) -> "FarmSite":
        farm = FarmWorldApp(
            farm_id=spec.farm_id,
            name=f"{spec.name}Farm",
            crop_type=spec.crop_type,
            num_ridges=spec.num_ridges,
            field_length_m=spec.field_length_m,
            ridge_width_m=spec.ridge_width_m,
        )
        weather = weather_app or WeatherApp()
        if weather_app is None:
            weather.name = f"{spec.name}Weather"
        field_ops = FieldOpsApp(farm, weather)
        field_ops.name = f"{spec.name}FieldOps"
        sensor = SensorApp(farm)
        sensor.name = f"{spec.name}Sensor"
        farm.attach_weather_app(weather)
        site = cls(spec, farm, weather, field_ops, sensor,
                   station_id or f"{spec.farm_id}_station", create_devices)
        # Some legacy constructors have fixed default names. Reseed after
        # namespacing so independent sites also have independent sensor noise.
        for app in site.private_apps:
            app.set_seed(0)
        return site

    def _device(self, kind: str):
        if self._runtime is not None:
            return self._runtime.device_view(self.spec.farm_id, kind)
        if not self._legacy_mode:
            raise RuntimeError("Register this site in a shared FarmFleet before selecting assets")
        if kind not in self._legacy_devices:
            classes = {"tractor": TractorApp, "drone": DroneApp, "robot": RobotApp}
            self._legacy_devices[kind] = classes[kind](
                self.farm, self.weather, name=f"{self.spec.name}{kind.title()}")
        return self._legacy_devices[kind]

    @property
    def tractor(self):
        return self._device("tractor")

    @property
    def drone(self):
        return self._device("drone")

    @property
    def robot(self):
        return self._device("robot")

    @property
    def private_apps(self) -> list[App]:
        return [self.farm, self.weather, self.field_ops, self.sensor]

    @property
    def apps(self) -> list[App]:
        if self._runtime is not None or not self._legacy_mode:
            return self.private_apps
        return [self.farm, self.weather, self.tractor, self.field_ops, self.sensor, self.drone, self.robot]


class FarmFleet:
    def __init__(self, sites: Iterable[FarmSite], *, assets=None,
                 shared_tools: bool = False, seed: int = 0, bindings=None):
        self.sites = list(sites)
        ids = [site.spec.farm_id for site in self.sites]
        private = {id(app): app for site in self.sites for app in site.private_apps}
        names = [app.name for app in private.values()]
        if not self.sites:
            raise ValueError("A farm fleet must contain at least one site")
        if len(ids) != len(set(ids)):
            raise ValueError("Farm IDs must be unique within a fleet")
        if len(names) != len(set(names)):
            raise ValueError("Farm app names must be unique within a fleet")
        self.shared_tools = shared_tools
        self.runtime = None
        if shared_tools:
            from fairy.apps.farm_world.runtime import FarmRuntime
            self.runtime = FarmRuntime(self, assets or [], seed=seed, bindings=bindings)
            for site in self.sites:
                site._runtime = self.runtime
                site._legacy_devices.clear()

    @property
    def apps(self) -> list[App]:
        if self.runtime is not None:
            return self.runtime.apps
        return [app for site in self.sites for app in site.apps]

    def get(self, farm_id: str) -> FarmSite:
        for site in self.sites:
            if site.spec.farm_id == farm_id:
                return site
        raise KeyError(f"Unknown farm_id {farm_id!r}; available: {[s.spec.farm_id for s in self.sites]}")

    def configure_tools(self, allowlist: dict[str, set[str]]) -> None:
        if self.runtime is not None:
            self.runtime.configure_tools(allowlist)

    def route(self, app, method: str, arguments: dict[str, Any]):
        if self.runtime is None:
            return app, method, dict(arguments)
        return self.runtime.route(app, method, arguments)

    def project_workflow_steps(self, steps):
        if self.runtime is None:
            return list(steps)
        return self.runtime.project_workflow_steps(steps)

    def operation_log(self, farm_id: str, kind: str = "tractor"):
        if self.runtime is None:
            return getattr(self.get(farm_id), kind)._operation_log
        return self.runtime.operation_log(farm_id, kind)

    def describe_environment(self):
        return self.runtime.describe_environment() if self.runtime else {}
