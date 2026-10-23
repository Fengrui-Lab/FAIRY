"""Device energy and fixed-installation ownership must hold at public boundaries."""
from copy import deepcopy
from datetime import datetime, timezone
import re

import pytest

from fairy.agents.agent.toolset_builder import build_toolset
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.irrigation_app import IrrigationApp
from fairy.apps.farm_world.robot_app import RobotApp
from fairy.apps.farm_world.sensor_app import SensorApp
from fairy.apps.farm_world.shared_drone_app import SharedDroneApp
from fairy.apps.farm_world.shared_robot_app import SharedRobotApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.scenarios.registry import get_scenario_class
from fairy.time_manager import TimeManager


@pytest.fixture
def environment(monkeypatch):
    now = datetime(2026, 5, 12, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: now)
    clock = TimeManager()
    clock.reset(now)
    weather = WeatherApp()
    weather.set_weather("2026-05-12", 20, 50, 2, 0, 200)
    farms = []
    for farm_id in ("farm_a", "farm_b", "farm_c"):
        world = FarmWorldApp(farm_id=farm_id, name=farm_id)
        sensors = SensorApp(world, name=f"{farm_id}_Sensor")
        irrigation = IrrigationApp(world, weather, name=f"{farm_id}_Irrigation")
        farms.append(FarmContext(farm_id, world, weather, sensors, irrigation))
    return FarmEnvironment(farms, weather, clock, warehouse=WarehouseApp(stock=WarehouseStock(
        seed_stock={"STANDARD": 2_000_000}, pesticide_liters=4000.0,
        fertilizer_kg=4000.0, fuel_liters=2000.0,
    )))


@pytest.fixture(params=["shared", "legacy"])
def robot(request, environment):
    if request.param == "shared":
        return SharedRobotApp(environment)
    farm = environment.get_farm("farm_a")
    device = RobotApp(farm.world, farm.weather)
    device.register_time_manager(environment.time_manager)
    return device


def inspect(robot, method, *args):
    if isinstance(robot, SharedRobotApp):
        return getattr(robot, method)("farm_a", *args)
    return getattr(robot, method)(*args)


@pytest.mark.parametrize("battery", [15, 19, 20])
def test_single_ridge_requires_the_full_trip_energy(environment, robot, battery):
    robot.load_state({"battery_pct": battery})
    offset = environment.time_manager.offset
    result = inspect(robot, "inspect_ridge", 0)
    if battery < 20:
        assert "error" in result
        assert robot.get_state()["battery_pct"] == battery
        assert robot.get_state()["inspection_log"] == []
        assert environment.time_manager.offset == offset
    else:
        assert result["status"] == "ok"
        assert result["battery_remaining_pct"] == 0
        assert len(robot.get_state()["inspection_log"]) == 1
        assert environment.time_manager.offset > offset


@pytest.mark.parametrize("method", ["inspect_pests", "inspect_crop_health", "inspect_emergence"])
@pytest.mark.parametrize("battery,covered", [(15, 1), (19, 1), (20, 2), (49, 7), (50, 8)])
def test_range_coverage_keeps_its_return_reserve(environment, robot, method, battery, covered):
    robot.load_state({"battery_pct": battery})
    result = inspect(robot, method, 0, 7)
    assert result["status"] == ("ok" if covered == 8 else "partial")
    assert result["covered_ridges"] == list(range(covered))
    assert result["uncovered_ridges"] == list(range(covered, 8))
    assert set(result["observations"]) == set(range(covered))
    assert result["battery_remaining_pct"] == battery - covered * 5
    assert result["battery_remaining_pct"] >= 10
    assert robot.get_state()["inspection_log"][0]["covered_ridges"] == list(range(covered))


def test_range_below_starting_threshold_has_no_device_or_time_effect(environment, robot):
    robot.load_state({"battery_pct": 14})
    before = deepcopy(robot.get_state())
    offset = environment.time_manager.offset
    assert "error" in inspect(robot, "inspect_pests", 0, 7)
    assert robot.get_state() == before
    assert environment.time_manager.offset == offset


@pytest.mark.parametrize("attribute", ["sensors", "irrigation"])
def test_fixed_installation_rejects_other_farm_before_writing_any_state(environment, attribute):
    target = getattr(environment.get_farm("farm_a"), attribute)
    source = getattr(environment.get_farm("farm_c"), attribute)
    saved = deepcopy(source.get_state())
    if attribute == "sensors":
        saved["soil_sensors"][0]["vwc"] = 0.87
        saved["canopy_sensors"][0]["ndvi_proxy"] = 0.91
    else:
        saved["irrigation_log"] = [{"farm_id": "farm_c", "marker": "foreign"}]
    before = deepcopy(target.get_state())
    with pytest.raises(ValueError, match="farm_c.*farm_a"):
        target.load_state(saved)
    assert target.get_state() == before
    assert target.bound_farm_id == "farm_a"


@pytest.mark.parametrize("attribute", ["sensors", "irrigation"])
@pytest.mark.parametrize("identity", ["same_farm", "missing", "none"])
def test_fixed_installation_accepts_own_or_unidentified_legacy_snapshot(environment, attribute, identity):
    target = getattr(environment.get_farm("farm_a"), attribute)
    saved = deepcopy(target.get_state())
    if attribute == "sensors":
        saved["soil_sensors"][0]["vwc"] = 0.27
    else:
        saved["irrigation_log"] = [{"farm_id": "farm_a", "marker": "restored"}]
    if identity == "missing":
        saved.pop("farm_id")
    elif identity == "none":
        saved["farm_id"] = None
    target.load_state(saved)
    assert target.bound_farm_id == "farm_a"
    restored = target.get_state()
    assert restored["farm_id"] == "farm_a"
    for key in saved.keys() - {"farm_id"}:
        assert restored[key] == saved[key]


@pytest.mark.parametrize("attribute", ["sensors", "irrigation"])
def test_unbound_legacy_installation_load_does_not_claim_snapshot_identity(environment, attribute):
    world = FarmWorldApp()
    target = (SensorApp(world) if attribute == "sensors"
              else IrrigationApp(world, environment.weather))
    saved = deepcopy(getattr(environment.get_farm("farm_c"), attribute).get_state())
    assert target.bound_farm_id is None
    target.load_state(saved)
    assert target.bound_farm_id is None
    assert target.get_state()["farm_id"] is None


def test_real_three_farm_schemas_have_no_two_farm_assumption_and_keep_targets():
    scenario = get_scenario_class("scenario_three_farm_full_season_hn84_normal")()
    scenario.setup()
    _, schemas, _ = build_toolset(scenario.apps)
    targeted = []
    for item in schemas:
        function = item["function"]
        assert not re.search(r"\b(?:both|either|two)\s+farms?\b", function["description"], re.I)
        properties = function["parameters"]["properties"]
        if "farm_id" in properties:
            targeted.append(function["name"])
            assert properties["farm_id"]["enum"] == ["farm_a", "farm_b", "farm_c"]
            assert "farm_id" in function["parameters"]["required"]
    assert {"Tractor__harvest", "Mavic3M__fly_survey", "Robot0__inspect_ridge"} <= set(targeted)
    functions = {item["function"]["name"]: item["function"] for item in schemas}
    for app, methods in (
        ("Tractor", ("attach_implement", "detach_implement", "get_status")),
        ("Mavic3M", ("check_status", "charge")),
        ("Matrice4T", ("check_status", "charge")),
        ("Robot0", ("check_status", "charge")),
    ):
        for method in methods:
            assert "farm_id" not in functions[f"{app}__{method}"]["parameters"]["properties"]
    assert "less than 20 percent" in functions["Robot0__inspect_ridge"]["description"]
    assert "at least 10 percent" in functions["Robot0__inspect_pests"]["description"]


@pytest.mark.parametrize("minimum,battery,covered", [(20, 23, 2), (30, 35, 4), (30, 31, 0)])
def test_drone_partial_mission_respects_configured_return_minimum(environment, minimum, battery, covered):
    drone = SharedDroneApp(environment, min_battery_pct=minimum, effective_ridges_per_pass=2)
    drone.load_state({"battery_pct": battery})
    result = drone.fly_survey("farm_a", 0, 7)
    assert result["status"] == "partial"
    assert result["surveyed_ridges"] == list(range(covered))
    assert result["battery_remaining_pct"] == battery - covered
    assert result["battery_remaining_pct"] >= minimum
