"""Public source declarations, model schemas and executed targets agree."""
from __future__ import annotations

import inspect
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from fairy.agents.agent.toolset_builder import build_toolset
from fairy.apps.farm_world.drone_app import DroneApp
from fairy.apps.farm_world.multi_farm import AssetSpec, FarmFleet, FarmSite
from fairy.apps.farm_world.services import SERVICE_CLASSES, DroneService
from fairy.apps.farm_world.services.base import (argument_documentation, service_tool,
                                                validate_declaration)
from fairy.controllers.engine import Engine
from fairy.scenarios.scenario import Scenario
from fairy.tool_utils import OperationType, app_tool
from fairy.types import EventRegisterer


@pytest.fixture
def environment():
    sites = [FarmSite.create(name, name.title(), num_ridges=12, field_length_m=80,
                            create_devices=False) for name in ("north", "south")]
    assets = [AssetSpec(f"{kind}_shared", kind, ("north", "south"),
                        initial_state={"battery_pct": 30} if kind == "drone" else {})
              for kind in ("tractor", "drone", "robot")]
    fleet = FarmFleet(sites, assets=assets, shared_tools=True, seed=19)
    for site in sites:
        site.weather.set_weather("2026-05-12", 25, 55, 2, 0, 400)
    scenario = Scenario(apps=fleet.apps, start_time=datetime(2026, 5, 12, 7, tzinfo=timezone.utc).timestamp())
    scenario.runtime_participants = [fleet.runtime]
    engine = Engine(None, scenario)
    _, schemas, tools = build_toolset(fleet.apps)
    return fleet, engine, {item["function"]["name"]: item["function"] for item in schemas}, tools


def test_every_model_schema_is_an_explicit_python_source_declaration(environment):
    fleet, _, schemas, tools = environment
    expected = {f"{cls.service_name}__{method}": function
                for cls in SERVICE_CLASSES for method, function in cls.declared_tools().items()}
    assert set(schemas) == set(expected) == set(tools)
    assert len(schemas) == 51
    for name, schema in schemas.items():
        function = expected[name]
        source = inspect.unwrap(function)
        signature = inspect.signature(source)
        parameters = set(signature.parameters) - {"self"}
        assert "__signature__" not in vars(function)
        assert "__signature__" not in vars(source)
        assert set(schema["parameters"]["properties"]) == parameters
        assert set(argument_documentation(source)) == parameters
        assert schema["description"] == inspect.getdoc(source)
        assert fleet.runtime.registry.contract(name).metadata["source"] == f"{source.__module__}.{source.__qualname__}"
        for argument, property_schema in schema["parameters"]["properties"].items():
            assert property_schema["description"] == argument_documentation(source)[argument]
            parameter = signature.parameters[argument]
            if parameter.default is not inspect.Parameter.empty:
                assert property_schema["default"] == parameter.default


def test_legacy_docs_or_new_backend_tools_cannot_change_public_contract(monkeypatch, environment):
    _, _, original_schemas, _ = environment
    monkeypatch.setattr(DroneApp.fly_survey, "__doc__", "Stale backend text without any farm ID.")
    def hidden_backend_method(self, legacy_arg: str):
        return {"legacy": legacy_arg}
    monkeypatch.setattr(DroneApp, "accidental_public_method", app_tool(hidden_backend_method), raising=False)
    other_sites = [FarmSite.create(name, name.title(), num_ridges=12, field_length_m=80,
                                  create_devices=False) for name in ("north", "south")]
    other = FarmFleet(other_sites, shared_tools=True, assets=[
        AssetSpec(f"{kind}_shared", kind, ("north", "south")) for kind in ("tractor", "drone", "robot")])
    _, schemas, _ = build_toolset(other.apps)
    actual = {item["function"]["name"]: item["function"] for item in schemas}
    assert actual == original_schemas
    assert "Drone__accidental_public_method" not in actual


def test_typed_source_rejects_bad_python_binding_but_json_tool_returns_receipt(environment):
    fleet, engine, _, tools = environment
    drone = next(app for app in fleet.apps if app.name == "Drone")
    before = deepcopy(fleet.runtime.assets["drone_shared"].snapshot())
    offset = engine.time_manager.offset
    with pytest.raises(TypeError):
        drone.fly_survey(asset_id="drone_shared", start_ridge=0, end_ridge=0)
    with pytest.raises(TypeError):
        drone.fly_survey(farm_id="north", asset_id="drone_shared", start_ridge=0, end_ridge=0, field_id="north")
    for arguments in (
        {"asset_id": "drone_shared", "start_ridge": 0, "end_ridge": 0},
        {"farm_id": "north", "asset_id": "drone_shared", "start_ridge": 0, "end_ridge": 0, "field_id": "north"},
    ):
        result = tools["Drone__fly_survey"](**arguments)
        assert not result["ok"]
        assert result["error"]["code"] == "INVALID_ARGUMENT"
        assert result["error"]["partial_effects"] is False
    assert fleet.runtime.assets["drone_shared"].snapshot() == before
    assert engine.time_manager.offset == offset


def test_aerial_partial_coverage_and_cross_farm_battery_match_public_description(environment):
    fleet, engine, schemas, tools = environment
    schema = schemas["Drone__fly_survey"]
    source_signature = inspect.signature(DroneService.fly_survey)
    arguments = {"farm_id": "south", "asset_id": "drone_shared", "start_ridge": 0, "end_ridge": 11}
    source_signature.bind(next(app for app in fleet.apps if app.name == "Drone"), **arguments)
    before = engine.time_manager.offset
    result = tools["Drone__fly_survey"](**arguments)
    assert result["ok"] and result["farm_id"] == "south"
    assert result["data"]["status"] == "partial"
    assert result["data"]["surveyed_ridges"] == list(range(7))
    assert result["data"]["battery_remaining_pct"] == 23
    assert "partial coverage" in schema["description"]
    assert engine.time_manager.offset > before
    second = tools["Drone__fly_survey"](farm_id="north", asset_id="drone_shared", start_ridge=0, end_ridge=0)
    assert second["ok"] and second["farm_id"] == "north"
    assert second["data"]["battery_remaining_pct"] == 22
    assert fleet.runtime.assets["drone_shared"].last_farm_id == "north"


def test_capture_keeps_the_source_signature_and_executes_exactly_one_mission(environment):
    fleet, _, _, tools = environment
    asset = fleet.runtime.assets["drone_shared"]
    previous = EventRegisterer.last_events
    try:
        with EventRegisterer.capture_mode() as events:
            event = tools["Drone__fly_survey"](farm_id="south", asset_id="drone_shared", start_ridge=0, end_ridge=0)
        assert len(events) == 1
        assert asset.data["_battery_pct"] == 30
        assert tuple(inspect.signature(event.function).parameters) == ("self", "farm_id", "asset_id", "start_ridge", "end_ridge")
        result = event.execute()
        assert result["ok"] and result["farm_id"] == "south"
        assert asset.data["_battery_pct"] == 29
        assert len(asset.data["_mission_log"]) == 1
    finally:
        EventRegisterer.last_events = previous


@pytest.mark.parametrize("doc", [
    "Read.\n\nReturns:\n    Result.",
    "Read.\n\nArgs:\n    old_farm: Stale parameter.\n\nReturns:\n    Result.",
])
def test_registration_rejects_missing_or_stale_argument_descriptions(doc):
    @service_tool(OperationType.READ, routing=("farm_id",))
    def wrong(self, farm_id: str) -> dict:
        return {}
    inspect.unwrap(wrong).__doc__ = doc
    with pytest.raises(ValueError, match="Args differ from signature"):
        validate_declaration(wrong)


def test_units_defaults_and_probe_selectors_come_from_the_declared_types(environment):
    _, _, schemas, _ = environment
    planting = schemas["Tractor__plant_seeds"]["parameters"]
    assert planting["properties"]["depth_cm"]["x-unit"] == "cm"
    assert planting["properties"]["depth_cm"]["exclusiveMinimum"] == 0
    assert schemas["FieldOps__apply_pesticide_manual"]["parameters"]["properties"]["liters_per_ridge"]["default"] == 3.0
    assert schemas["Tractor__spray_pesticide"]["parameters"]["properties"]["liters_per_ridge"]["default"] == 8.0
    assert set(schemas["Tractor__return_supplies"]["parameters"]["properties"]) == {"asset_id"}
    probe = schemas["Sensor__read_soil_sensor"]["parameters"]["properties"]
    assert set(probe) == {"sensor_id"}
    assert all(identifier.startswith(("north:S", "south:S")) for identifier in probe["sensor_id"]["enum"])


@pytest.mark.parametrize("method", ["inspect_pests", "inspect_crop_health", "inspect_emergence"])
def test_ground_ranges_without_physics_return_observations_and_actual_coverage(environment, method):
    fleet, engine, schemas, tools = environment
    farm = fleet.runtime.farms["north"].farm
    assert not farm.physics_active
    pest_ridge, disease_ridge = farm.get_ridge(0), farm.get_ridge(1)
    pest_ridge.pest_pressure = pest_ridge.pest_pressure_base = 0.4
    disease_ridge.disease_pressure = disease_ridge.disease_pressure_base = 0.4
    robot = fleet.runtime.assets["robot_shared"]
    before_battery = robot.data["_battery_pct"]
    before_time = engine.time_manager.offset
    result = tools[f"Robot__{method}"](
        farm_id="north", asset_id="robot_shared", start_ridge=0, end_ridge=11,
    )
    assert result["ok"], result
    assert result["farm_id"] == "north"
    assert result["data"]["covered_ridges"] == list(range(8))
    assert result["data"]["uncovered_ridges"] == list(range(8, 12))
    assert set(result["data"]["observations"]) == {str(ridge) for ridge in range(8)}
    assert result["data"]["observations"]["0"]["pest_present"] is True
    assert result["data"]["observations"]["1"]["disease_present"] is True
    for observation in result["data"]["observations"].values():
        assert observation["weed_present"] is None
        assert observation["weed_confidence"] == 0
        assert observation["weed_pressure_band"] == "unknown"
        assert "leaf_nutrition_band" not in observation
    assert robot.data["_battery_pct"] < before_battery
    assert engine.time_manager.offset > before_time
    assert len(robot.data["_inspection_log"]) == 1
    description = schemas[f"Robot__{method}"]["description"].lower()
    assert any(word in description for word in ("unavailable", "missing"))
    assert "unknown" in description or "not confirmed" in description


def test_registration_rejects_a_fabricated_signature_on_an_ordinary_method():
    @service_tool(OperationType.READ, routing=("farm_id",))
    def forged(self, farm_id: str) -> dict:
        """Read a farm.

        Args:
            farm_id: Actual farm identifier.

        Returns:
            Farm data.
        """
        return {}

    source = inspect.unwrap(forged)
    assert source.__code__.co_argcount == 2
    assert all(parameter.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
               for parameter in inspect.signature(source).parameters.values())
    forged.__signature__ = inspect.Signature([
        *inspect.signature(source).parameters.values(),
        inspect.Parameter("asset_id", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=str),
    ])
    with pytest.raises(ValueError, match="Signature overrides are forbidden"):
        validate_declaration(forged)


def test_registration_rejects_a_real_public_variadic_method():
    @service_tool(OperationType.READ)
    def variadic(self, *args: str, **kwargs: str) -> dict:
        """A public method cannot conceal its arguments in varargs.

        Args:
            args: Positional arguments whose public fields are undeclared.
            kwargs: Keyword arguments whose public fields are undeclared.

        Returns:
            Arbitrary data.
        """
        return {}

    source = inspect.unwrap(variadic)
    assert "__signature__" not in vars(variadic)
    assert "__signature__" not in vars(source)
    assert inspect.signature(source).parameters["args"].kind is inspect.Parameter.VAR_POSITIONAL
    assert inspect.signature(source).parameters["kwargs"].kind is inspect.Parameter.VAR_KEYWORD
    with pytest.raises(ValueError, match="Signature differs from source arguments"):
        validate_declaration(variadic)
