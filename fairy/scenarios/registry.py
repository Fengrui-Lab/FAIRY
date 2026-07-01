from __future__ import annotations

from typing import Type

from fairy.scenarios.scenario import Scenario

_REGISTRY: dict[str, Type[Scenario]] = {}


def register_scenario(scenario_id: str):
    def decorator(cls: Type[Scenario]) -> Type[Scenario]:
        cls.scenario_id = scenario_id
        _REGISTRY[scenario_id] = cls
        return cls

    return decorator


def get_scenario_class(scenario_id: str) -> Type[Scenario]:
    if scenario_id not in _REGISTRY:
        _import_known_scenarios()
    return _REGISTRY[scenario_id]


def list_scenarios() -> list[str]:
    _import_known_scenarios()
    return sorted(_REGISTRY)


class _RegistryCompat:
    def get_scenario(self, scenario_id: str) -> Type[Scenario]:
        return get_scenario_class(scenario_id)


registry = _RegistryCompat()


def _import_known_scenarios() -> None:
    import importlib
    import pkgutil

    for package in (
        "fairy.scenarios.baseline_farm_world",
        "fairy.scenarios.farm_world_physics",
        "fairy.scenarios.farm_worldpp_physics",
        "fairy.scenarios.farm_world_fullseason",
        "fairy.scenarios.farm_world_fullseason_v2",
    ):
        mod = importlib.import_module(package)
        for info in pkgutil.walk_packages(mod.__path__, package + "."):
            if not info.ispkg:
                imported = importlib.import_module(info.name)
                for value in vars(imported).values():
                    if (
                        isinstance(value, type)
                        and issubclass(value, Scenario)
                        and value is not Scenario
                        and getattr(value, "scenario_id", "")
                    ):
                        _REGISTRY.setdefault(value.scenario_id, value)
