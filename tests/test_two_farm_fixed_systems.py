"""Fixed installations belong to one farm; tools report their real binding."""
from copy import deepcopy
from datetime import datetime, timezone
import inspect

import pytest

from fairy.agents.agent.toolset_builder import build_toolset
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.irrigation_app import IrrigationApp
from fairy.apps.farm_world.manual_ops_app import ManualOpsApp
from fairy.apps.farm_world.sensor_app import SensorApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.app import App
from fairy.tool_utils import app_tool
from fairy.time_manager import TimeManager


@pytest.fixture
def installations():
    clock = TimeManager()
    clock.reset(datetime(2026, 5, 12, tzinfo=timezone.utc).timestamp())
    weather = WeatherApp()
    weather.set_weather("2026-05-12", 22, 55, 2, 0, 350)
    farms = []
    for index, farm_id in enumerate(("farm_a", "farm_b")):
        world = FarmWorldApp(farm_id=farm_id, name=farm_id)
        for ridge in world._ridges:
            ridge.soil_vwc = 0.18 + index * 0.09
        sensor = SensorApp(world, name=f"{farm_id}_Sensor")
        irrigation = IrrigationApp(world, weather, name=f"{farm_id}_Irrigation")
        farms.append(FarmContext(farm_id, world, weather, sensor, irrigation))
    environment = FarmEnvironment(farms, weather, clock)
    return environment, farms[0], farms[1]


def test_fixed_probe_sets_are_independent_and_local_ids_are_qualified_by_app(installations):
    _, a, b = installations
    assert a.sensors is not b.sensors
    assert a.sensors._soil_sensors is not b.sensors._soil_sensors
    ra = a.sensors.read_soil_sensor("S1")
    rb = b.sensors.read_soil_sensor("S1")
    assert ra["farm_id"] == "farm_a" and rb["farm_id"] == "farm_b"
    assert 0.17 <= ra["vwc"] <= 0.19
    assert 0.26 <= rb["vwc"] <= 0.28
    _, schemas, _ = build_toolset([a.sensors, b.sensors])
    names = {schema["function"]["name"] for schema in schemas}
    assert "farm_a_Sensor__read_soil_sensor" in names
    assert "farm_b_Sensor__read_soil_sensor" in names


def test_irrigation_pending_and_water_quota_are_owned_by_each_farm(installations):
    environment, a, b = installations
    before_b = deepcopy(b.world.get_state())
    offset = environment.time_manager.offset
    result = a.irrigation.irrigate(start=0, end=3, hours=1)
    assert result["farm_id"] == "farm_a"
    assert result["status"] == "irrigation_started"
    assert a.world.get_pending_irrigation_for_ridges([0])
    assert not b.world.get_pending_irrigation_for_ridges([0])
    assert b.irrigation.get_state()["irrigation_log"] == []
    assert b.world.get_state()["management_regime"] == before_b["management_regime"]
    assert environment.time_manager.offset == offset + 3900
    assert a.world.time_manager is b.world.time_manager is environment.time_manager
    again = a.irrigation.irrigate(0, 3, 1)
    assert again["status"] == "irrigation_pending"
    # The other controller can accept its own run, regardless of A's pending delivery.
    other = b.irrigation.irrigate(0, 3, 0.2)
    assert other["status"] == "irrigation_started"
    assert other["farm_id"] == "farm_b"


def test_fixed_irrigation_catalog_does_not_expose_manual_sprayer(installations):
    _, a, b = installations
    _, _, tools = build_toolset([a.irrigation, b.irrigation])
    assert set(tools) == {f"{farm.farm_id}_Irrigation__{name}"
                          for farm in (a, b) for name in ("irrigate", "get_irrigation_log")}
    for tool in tools.values():
        assert "farm_id" not in {arg.name for arg in tool.args}
        assert f"Bound farm: {tool.class_instance.bound_farm_id}" in tool.function_description


def test_manual_operator_draws_only_selected_farms_inventory(installations):
    environment, a, b = installations
    manual = ManualOpsApp(environment)
    assert manual.time_manager is environment.time_manager
    initial_a, initial_b = a.world._inventory.pesticide_liters, b.world._inventory.pesticide_liters
    result = manual.apply_pesticide_manual("farm_b", 0, 1)
    assert result["farm_id"] == "farm_b" and result["status"] == "ok"
    assert a.world._inventory.pesticide_liters == initial_a
    assert b.world._inventory.pesticide_liters == initial_b - 6
    assert manual.get_state()["manual_spray_log"][0]["farm_id"] == "farm_b"


@pytest.mark.parametrize("dose", [float("nan"), float("inf"), "NaN", True])
def test_bad_manual_dose_cannot_contaminate_inventory_or_advance_time(installations, dose):
    environment, a, _ = installations
    manual = ManualOpsApp(environment)
    before = deepcopy(a.world._inventory.to_dict())
    offset = environment.time_manager.offset
    assert "error" in manual.apply_pesticide_manual("farm_a", 0, 0, dose)
    assert a.world._inventory.to_dict() == before
    assert environment.time_manager.offset == offset


def test_physics_irrigation_reports_its_actual_application_time(installations):
    environment, a, _ = installations
    a.world.configure_physics_profile("test_fixed_irrigation")
    result = a.irrigation.irrigate(0, 3, 0.2)
    assert result["eta_minutes_to_confirmation"] == 0
    assert result["effect_ready_at"] <= environment.time_manager.time()
    assert "soil engine" in result["message"]


def test_model_schema_uses_actual_defaults_docs_and_farm_choices(installations):
    environment, a, _ = installations
    manual = ManualOpsApp(environment)
    _, schemas, _ = build_toolset([manual, a.irrigation])
    schema = next(s["function"] for s in schemas if s["function"]["name"] == "ManualOps__apply_pesticide_manual")
    params = schema["parameters"]
    assert params["properties"]["farm_id"]["enum"] == ["farm_a", "farm_b"]
    assert params["properties"]["liters_per_ridge"]["default"] == 3.0
    assert "litres" in params["properties"]["liters_per_ridge"]["description"]
    assert set(params["required"]) == {"farm_id", "start_ridge", "end_ridge"}
    assert params["additionalProperties"] is False
    assert set(params["properties"]) == set(inspect.signature(manual.apply_pesticide_manual).parameters)


def test_registration_refuses_duplicate_app_tool_names(installations):
    _, a, _ = installations
    with pytest.raises(ValueError, match="Duplicate tool name"):
        build_toolset([a.sensors, a.sensors])


@pytest.mark.parametrize("description", [
    "Read.\n\nReturns:\n    Value.",
    "Read.\n\nArgs:\n    old_farm: Removed name.\n\nReturns:\n    Value.",
])
def test_explicit_tools_refuse_missing_or_stale_parameter_docs(description):
    class Broken(App):
        require_explicit_tool_docs = True

        @app_tool()
        def read(self, farm_id: str):
            return farm_id
    Broken.read.__doc__ = description
    with pytest.raises(ValueError, match="Args must match"):
        Broken().get_tools()
