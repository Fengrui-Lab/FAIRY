"""Public function schemas must describe the values accepted by real tools."""
from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional, Union

import pytest
from jsonschema import Draft202012Validator, ValidationError

from fairy.agents.agent.toolset_builder import build_tool_schema
from fairy.apps.app import App
from fairy.tool_utils import AppTool, AppToolArg, app_tool


class TypedApp(App):
    @app_tool()
    def manage(self, plots: list[str], weights: dict[str, list[float | None]],
               nullable: Optional[int], area: float | None = None,
               enabled: bool = False, metadata: Any = None):
        return plots, weights, nullable, area, enabled, metadata

    @app_tool()
    def legacy_typing(self, groups: List[Dict[str, Union[int, str]]],
                      values: Optional[List[float]] = None):
        return groups, values


@pytest.mark.parametrize("callable_fallback", [False, True])
def test_schema_validates_nested_arguments_and_preserves_optional_semantics(callable_fallback):
    app = TypedApp()
    tool = app.manage if callable_fallback else next(t for t in app.get_tools() if t.name == "manage")
    schema = build_tool_schema(tool)["function"]["parameters"]
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(json.loads(json.dumps(schema)))
    assert schema["required"] == ["plots", "weights", "nullable"]
    args = {"plots": ["p1", "p2"], "weights": {"p1": [1.2, None]}, "nullable": None}
    validator.validate(args)
    assert tool(**args) == (["p1", "p2"], {"p1": [1.2, None]}, None, None, False, None)
    validator.validate({**args, "area": 400, "enabled": True, "metadata": {"note": [1, None]}})
    validator.validate({**args, "area": None})
    for invalid in (
        {**args, "plots": "p1,p2"},
        {**args, "plots": [1]},
        {**args, "weights": {"p1": ["1.2"]}},
        {**args, "area": "400"},
        {**args, "enabled": "false"},
        {**args, "nullable": True},
        {key: value for key, value in args.items() if key != "nullable"},
    ):
        with pytest.raises(ValidationError):
            validator.validate(invalid)


def test_typing_aliases_and_union_members_are_preserved():
    tool = next(t for t in TypedApp().get_tools() if t.name == "legacy_typing")
    schema = tool.to_open_ai()["function"]["parameters"]
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for args in ({"groups": [{"p1": 3, "p2": "small"}]},
                 {"groups": [], "values": None},
                 {"groups": [], "values": [1, 2.5]}):
        validator.validate(args)
    for args in ({"groups": [{"p1": 1.5}]}, {"groups": [], "values": [False]}):
        with pytest.raises(ValidationError):
            validator.validate(args)


def test_manually_constructed_legacy_arguments_keep_string_type_contract():
    tool = AppTool("Legacy", "Legacy", "call", None,
                   [AppToolArg("name", "str"),
                    AppToolArg("amount", "float", "Quantity", True, 1.0)],
                   lambda self, **kwargs: kwargs, None)
    schema = tool.to_open_ai()["function"]["parameters"]
    assert schema == {"type": "object", "properties": {
        "name": {"type": "string", "description": ""},
        "amount": {"type": "number", "description": "Quantity"}}, "required": ["name"]}


def test_unannotated_callable_keeps_legacy_string_default():
    def command(value, limit: int = 1):
        return value, limit

    schema = build_tool_schema(command)["function"]["parameters"]
    assert schema["properties"]["value"]["type"] == "string"
    assert schema["properties"]["limit"]["type"] == "integer"
    assert schema["required"] == ["value"]


def test_real_rice_schema_rejects_the_strings_that_previously_failed_at_runtime():
    from fairy.apps.paddy.drone import PaddyDroneApp
    from fairy.apps.paddy.machinery import PaddyMachineryApp
    from fairy.apps.paddy.observations import PaddyObservationApp
    from fairy.apps.paddy.operations import PaddyOpsApp

    tools = {tool.name: tool for app in (PaddyDroneApp(None), PaddyOpsApp(None),
                                        PaddyMachineryApp(None), PaddyObservationApp(None))
             for tool in app.get_tools()}
    for tool in tools.values():
        Draft202012Validator.check_schema(tool.to_open_ai()["function"]["parameters"])
    cases = [
        ("fly_survey", {"plot_ids": ["p1", "p2"]}, {"plot_ids": "p1,p2"}),
        ("transplant", {"plot_id": "p1", "batch_id": "ir72_standard", "area_m2": 500},
         {"plot_id": "p1", "batch_id": "ir72_standard", "area_m2": "500"}),
        ("harvest", {"plot_id": "p1", "area_m2": 400}, {"plot_id": "p1", "area_m2": "400"}),
    ]
    for name, valid, invalid in cases:
        validator = Draft202012Validator(tools[name].to_open_ai()["function"]["parameters"])
        validator.validate(valid)
        with pytest.raises(ValidationError):
            validator.validate(invalid)
        if "area_m2" in valid:
            validator.validate({**valid, "area_m2": None})
            validator.validate({key: value for key, value in valid.items() if key != "area_m2"})
    Draft202012Validator(tools["get_machine_status"].to_open_ai()["function"]["parameters"]).validate(
        {"machine_id": None})


def test_schema_validated_rice_arguments_execute_actual_survey_and_partial_operations():
    pytest.importorskip("pcse")
    from fairy.apps.paddy.drone import PaddyDroneApp
    from fairy.apps.paddy.operations import PaddyOpsApp
    from fairy.apps.paddy.world import PaddyWorldApp
    from fairy.scenarios.rice.scenarios import configuration, reference_checkpoints

    def world_at(label):
        field, weather = configuration("normal")
        world = PaddyWorldApp(field=field, weather=weather)
        world.load_state(copy.deepcopy(reference_checkpoints("normal")[label]))
        return world

    def call(app, name, **kwargs):
        tool = next(t for t in app.get_tools() if t.name == name)
        validator = Draft202012Validator(tool.to_open_ai()["function"]["parameters"])
        # Simulate the JSON transport used by the model-facing function interface.
        payload = json.loads(json.dumps(kwargs))
        validator.validate(payload)
        return tool(**payload)

    world = world_at("before_transplant")
    survey = call(PaddyDroneApp(world), "fly_survey", plot_ids=["p1", "p2"])
    assert [product["plot_id"] for product in survey["products"]] == ["p1", "p2"]
    ops = PaddyOpsApp(world)
    call(ops, "load_seedlings", batch_id="ir72_standard", quantity=75000)
    first = call(ops, "transplant", plot_id="p1", batch_id="ir72_standard", area_m2=500)
    assert first["transplanted_area_m2"] == 500 and not first["completed"]
    assert call(ops, "transplant", plot_id="p1", batch_id="ir72_standard", area_m2=None)["completed"]

    world = world_at("before_harvest")
    ops = PaddyOpsApp(world)
    first = call(ops, "harvest", plot_id="p1", area_m2=400)
    assert first["harvested_area_m2"] == 400 and not first["completed"]
    assert call(ops, "harvest", plot_id="p1")["completed"]
