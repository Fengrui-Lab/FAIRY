from __future__ import annotations

from typing import Type
from pathlib import Path
import json

from fairy.scenarios.scenario import Scenario

_REGISTRY: dict[str, Type[Scenario]] = {}


def _quarantined_scenarios() -> dict:
    manifest = Path(__file__).with_name("未验证的场景") / "manifest.json"
    if not manifest.exists():
        return {}
    return json.loads(manifest.read_text(encoding="utf-8"))["scenarios"]



def register_scenario(scenario_id: str):
    def decorator(cls: Type[Scenario]) -> Type[Scenario]:
        cls.scenario_id = scenario_id
        _REGISTRY[scenario_id] = cls
        return cls

    return decorator


def get_scenario_class(scenario_id: str) -> Type[Scenario]:
    excluded = _quarantined_scenarios()
    if scenario_id in excluded:
        raise ValueError(
            f"Scenario {scenario_id} is quarantined in 未验证的场景: "
            + excluded[scenario_id]["reason"]
        )
    if scenario_id not in _REGISTRY:
        _import_known_scenarios()
    return _REGISTRY[scenario_id]


def list_scenarios() -> list[str]:
    _import_known_scenarios()
    return sorted(set(_REGISTRY) - set(_quarantined_scenarios()))


class _RegistryCompat:
    def get_scenario(self, scenario_id: str) -> Type[Scenario]:
        return get_scenario_class(scenario_id)


registry = _RegistryCompat()


def _import_known_scenarios() -> None:
    import importlib
    import pkgutil

    # Each package is visited once; all three integrated scenario families remain.
    for package in (
        "fairy.scenarios.baseline_farm_world",
        "fairy.scenarios.farm_world_physics",
        "fairy.scenarios.farm_worldpp_physics",
        "fairy.scenarios.farm_world_fullseason",
        "fairy.scenarios.farm_world_fullseason_v2",
        "fairy.scenarios.wofost",
        "fairy.scenarios.farm_world_diverse",
        "fairy.scenarios.two_farm",
        "fairy.scenarios.three_farm",
        "fairy.scenarios.rice",
        "fairy.scenarios.maize",
        "fairy.scenarios.crop_challenges",
        "fairy.scenarios.management_extensions",
    ):
        mod = importlib.import_module(package)
        explicit_modules = getattr(mod, "SCENARIO_MODULES", None)
        module_names = ([package + "." + name for name in explicit_modules]
                        if explicit_modules is not None else
                        [info.name for info in pkgutil.walk_packages(mod.__path__, package + ".") if not info.ispkg])
        for module_name in module_names:
            imported = importlib.import_module(module_name)
            for value in vars(imported).values():
                if (
                    isinstance(value, type)
                    and issubclass(value, Scenario)
                    and value is not Scenario
                    and getattr(value, "scenario_id", "")
                ):
                    _REGISTRY.setdefault(value.scenario_id, value)
