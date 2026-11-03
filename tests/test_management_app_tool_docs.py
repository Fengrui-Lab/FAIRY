"""Extension tool instructions must reach the model without changing shared tools."""

import ast
import importlib
import inspect
from pathlib import Path

import pytest

from fairy.agents.agent.toolset_builder import build_toolset
from fairy.apps.farm_world.irrigation_app import IrrigationApp
from fairy.scenarios.management_extensions import SCENARIO_MODULES
from fairy.scenarios.management_extensions.apps.shared_irrigation_app import (
    PooledIrrigation,
)
from fairy.scenarios.scenario import Scenario
from fairy.tool_utils import _argument_descriptions


APP_MODULE = "fairy.scenarios.management_extensions.apps."


def extension_scenario_classes():
    classes = []
    for name in SCENARIO_MODULES:
        if not name.startswith(("L3.", "L4.")):
            continue
        module = importlib.import_module(
            f"fairy.scenarios.management_extensions.{name}"
        )
        classes.extend(
            cls
            for _, cls in inspect.getmembers(module, inspect.isclass)
            if cls.__module__ == module.__name__ and issubclass(cls, Scenario)
        )
    return classes


SCENARIOS = extension_scenario_classes()


@pytest.fixture(scope="module")
def scene_toolsets():
    result = {}
    for cls in SCENARIOS:
        scene = cls(seed=0, detailed_briefing=True)
        scene.setup()
        tools, schemas, tool_map = build_toolset(list(scene.apps))
        result[cls.scenario_id] = (
            scene,
            tools,
            {item["function"]["name"]: item["function"] for item in schemas},
            tool_map,
        )
    return result


@pytest.mark.parametrize("scenario_id", [cls.scenario_id for cls in SCENARIOS])
def test_model_receives_extension_tool_instructions_arguments_and_returns(
    scene_toolsets, scenario_id
):
    _, tools, schemas, _ = scene_toolsets[scenario_id]
    for tool in tools:
        if not tool.function.__module__.startswith(APP_MODULE):
            continue
        name = f"{tool.app_name}__{tool.name}"
        schema = schemas[name]
        documented = _argument_descriptions(tool.function)
        parameters = set(inspect.signature(tool.function).parameters) - {"self"}
        assert "Returns:" in schema["description"], name
        assert inspect.getdoc(tool.function) in schema["description"], name
        assert set(documented) == parameters, name
        assert set(schema["parameters"]["properties"]) == parameters, name
        for parameter in parameters:
            assert documented[parameter], (name, parameter)
            assert (
                schema["parameters"]["properties"][parameter]["description"]
                == documented[parameter]
            ), (name, parameter)


def test_every_extension_app_declaration_is_exercised_by_real_scene_toolsets(
    scene_toolsets,
):
    package = importlib.import_module(APP_MODULE.rstrip("."))
    expected = set()
    for path in Path(package.__path__[0]).glob("*.py"):
        for cls in (
            node for node in ast.parse(path.read_text()).body
            if isinstance(node, ast.ClassDef)
        ):
            for method in cls.body:
                if isinstance(method, ast.FunctionDef) and any(
                    ast.unparse(decorator).startswith("app_tool")
                    for decorator in method.decorator_list
                ):
                    expected.add(f"{APP_MODULE}{path.stem}.{cls.name}.{method.name}")
    discovered = {
        f"{tool.function.__module__}.{tool.function.__qualname__}"
        for _, tools, _, _ in scene_toolsets.values()
        for tool in tools
    }
    assert expected <= discovered


def test_variety_and_product_units_are_visible_in_model_parameter_descriptions(
    scene_toolsets,
):
    _, _, variety, tools = scene_toolsets[
        "scenario_l3_soybean_variety_high_water_price"
    ]
    seed = variety["VarietySelection__select_variety"]["parameters"]["properties"][
        "seed_type"
    ]
    assert "get_options" in seed["description"]
    assert "not the official" in seed["description"]
    assert tools["VarietySelection__get_options"]()["options"]
    for scenario_id in (
        "scenario_l3_soybean_pesticide_choice",
        "scenario_l3_soybean_fungicide_choice",
    ):
        _, _, schemas, _ = scene_toolsets[scenario_id]
        arguments = schemas["CropProtection__apply"]["parameters"]["properties"]
        assert "g/ha" in arguments["rate_per_ha"]["description"]
        assert "mL/ha" in arguments["rate_per_ha"]["description"]
        assert "inclusive" in arguments["end_ridge"]["description"]
        assert "identical" in arguments["application_id"]["description"]


def test_local_shared_water_notes_do_not_change_inherited_irrigation_dispatch(
    scene_toolsets,
):
    scene, _, _, _ = scene_toolsets[
        "scenario_l3_joint_maize_soybean_operating_margin"
    ]
    pooled = next(app for app in scene.apps if isinstance(app, PooledIrrigation))
    legacy = IrrigationApp(
        pooled._farm_world_app, pooled._weather_app, name="LegacyIrrigation"
    )
    before = [tool.to_open_ai() for tool in legacy.get_tools()]
    inherited_doc = inspect.getdoc(IrrigationApp.irrigate)
    pooled_tools = {tool.name: tool for tool in pooled.get_tools()}
    irrigation = pooled_tools["irrigate"].to_open_ai()["function"]
    history = pooled_tools["get_irrigation_log"].to_open_ai()["function"]
    assert "shared_water_remaining_m3" in irrigation["description"]
    assert "5 mm" in irrigation["description"]
    assert "Returns:" in irrigation["description"]
    assert "estimated_water_mm" in history["description"]
    assert inspect.unwrap(pooled_tools["irrigate"].function) is inspect.unwrap(
        IrrigationApp.irrigate
    )
    legacy_irrigation = next(
        item["function"] for item in before
        if item["function"]["name"] == "LegacyIrrigation__irrigate"
    )
    assert irrigation["parameters"] == legacy_irrigation["parameters"]
    assert [tool.to_open_ai() for tool in legacy.get_tools()] == before
    assert inspect.getdoc(IrrigationApp.irrigate) == inherited_doc
