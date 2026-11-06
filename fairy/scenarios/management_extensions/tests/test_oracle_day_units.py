"""Whole-day management Oracle waits use days without moving their clocks."""

import ast
from fractions import Fraction
from importlib import import_module
from pathlib import Path

import pytest

from fairy.apps.system import SystemApp
from fairy.scenarios.management_extensions import SCENARIO_MODULES
from fairy.scenarios.management_extensions.oracle_time import oracle_time_arguments
from fairy.scenarios.scenario import Scenario
from fairy.time_manager import SimulationTimeManager


@pytest.mark.parametrize("seconds,expected", [
    (86400, {"days": 1}), (172800., {"days": 2}),
    (259200, {"days": 3}), (345600, {"days": 4}),
    (3600, {"seconds": 3600}), (86400.5, {"seconds": 86400.5}),
    (86399.999999, {"seconds": 86399.999999}), (0, {"seconds": 0}),
])
def test_whole_days_and_precise_partial_days(seconds, expected):
    assert oracle_time_arguments(seconds) == expected
    first, second = SystemApp(), SystemApp()
    for system in (first, second):
        clock = SimulationTimeManager()
        clock.reset(1000)
        system.register_time_manager(clock)
    first.advance_time(seconds=seconds)
    second.advance_time(**oracle_time_arguments(seconds))
    assert first.time_manager.time() == second.time_manager.time()


def _constant(node):
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return Fraction(str(node.value))
    if isinstance(node, ast.BinOp):
        a, b = _constant(node.left), _constant(node.right)
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Div):
            return a / b
    raise ValueError("Dynamic duration")


def test_registered_scene_sources_have_no_whole_days_encoded_as_seconds():
    base = Path(__file__).resolve().parents[1]
    violations = []
    for name in SCENARIO_MODULES:
        path = base / (name.replace(".", "/") + ".py")
        for node in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "advance_time"):
                continue
            for kw in node.keywords:
                if kw.arg not in ("seconds", "hours", "minutes"):
                    continue
                try:
                    value = _constant(kw.value) * {"seconds": 1, "hours": 3600, "minutes": 60}[kw.arg]
                except ValueError:
                    continue
                if value > 0 and value % 86400 == 0:
                    violations.append((name, node.lineno))
    assert not violations


@pytest.mark.parametrize("module_name", SCENARIO_MODULES)
def test_every_registered_oracle_captures_whole_days_as_days(module_name):
    module = import_module("fairy.scenarios.management_extensions." + module_name)
    cls = next(cls for cls in vars(module).values()
               if isinstance(cls, type) and issubclass(cls, Scenario)
               and cls.__module__ == module.__name__)
    scene = cls(seed=0)
    scene.setup()
    for event in scene.events:
        if getattr(event.function, "__name__", "") != "advance_time":
            continue
        args = event.kwargs
        total = sum(args.get(key, 0) * unit for key, unit in (
            ("days", 86400), ("hours", 3600), ("minutes", 60), ("seconds", 1)))
        if total > 0 and total % 86400 == 0:
            assert args.get("days") == total // 86400, (scene.scenario_id, args)
            assert not any(args.get(key) for key in ("seconds", "hours", "minutes"))
