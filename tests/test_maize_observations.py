"""Maize observations keep crop identity, target coverage and operation time truthful."""
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from fairy.agents.agent.agent import Agent
from fairy.apps.farm_world.drone_app import DroneApp
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.robot_app import RobotApp
from fairy.apps.farm_world.tractor_app import TractorApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.controllers.agent_config import get_farm_world_system_prompt


def call(app, name, **arguments):
    return next(tool for tool in app.get_tools() if tool.name == name)(**arguments)


@pytest.fixture
def field():
    world, weather = FarmWorldApp(crop_id="maize", field_length_m=200.0), WeatherApp()
    for ridge in world._ridges:
        ridge.soil_vwc, ridge.soil_temp_c = 0.24, 18.0
    world._ridges[7].pest_pressure_base = 0.8
    world._ridges[7].disease_pressure_base = 0.75
    weather.set_weather(date="2026-05-15", temp_c=20.0, humidity_pct=50.0,
                        wind_speed_ms=1.0, rainfall_mm=0.0,
                        solar_radiation=350.0, avg_soil_vwc=0.24)
    world.configure_physics_profile("maize_observation_static_weather")
    start = datetime(2026, 5, 15, 12, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
    env = FarmEnvironment([FarmContext("maize", world, weather)], weather,
                          start_time=start, timezone_name="Asia/Shanghai")
    env.sync()
    drone = DroneApp(world, weather, speed_ms=5.0, effective_ridges_per_pass=2)
    robot = RobotApp(world, weather)
    for app in (drone, robot):
        app.register_time_manager(env.time_manager)
    return env, world, drone, robot


def test_maize_single_ground_inspection_uses_noisy_product_for_actual_target(field, monkeypatch):
    env, world, _, robot = field
    observer = world.physics.observation_model
    original = observer.observe_ground_inspection
    calls = []

    def inspect(**arguments):
        calls.append(arguments)
        products = original(**arguments)
        # Force a false negative in the returned product: the App must use the
        # product, rather than turning hidden pressure into a deterministic label.
        products[0].values[7] = {"pest_present": False, "confidence": 0.123}
        products[1].values[7] = {"disease_present": False, "confidence": 0.234}
        return products

    monkeypatch.setattr(observer, "observe_ground_inspection", inspect)
    start = env.time_manager.time()
    result = call(robot, "inspect_ridge", ridge_id=7)
    assert result["status"] == "ok"
    assert len(calls) == 1 and calls[0]["ridge_ids"] == [7]
    assert list(calls[0]["truth_by_ridge"]) == [7]
    assert calls[0]["truth_by_ridge"][7].insect_pressure == pytest.approx(0.8)
    observation = result["result"]
    assert observation["pest_detected"] is False
    assert observation["pest_confidence"] == 0.123
    assert observation["disease_detected"] is False
    assert observation["disease_confidence"] == 0.234
    assert observation["pest_type"] is observation["disease_type"] is None
    assert observation["pest_count_estimate"] == "not_estimated"
    assert "not diagnosed" in observation["diagnostic_scope"]
    assert env.time_manager.time() - start == int(200.0 * 2 / 0.8) + 30
    assert result["battery_remaining_pct"] == 80.0


def test_maize_ground_range_claims_only_actual_observation_coverage(field):
    env, world, _, robot = field
    start = env.time_manager.time()
    result = call(robot, "inspect_emergence", start_ridge=3, end_ridge=12)
    maximum = 8
    expected = list(range(3, 3 + maximum))
    assert result["status"] == "partial"
    assert result["covered_ridges"] == expected
    assert result["uncovered_ridges"] == list(range(3 + maximum, 13))
    assert list(result["observations"]) == expected
    assert all(observation["stand_fraction"] == 0.0
               for observation in result["observations"].values())
    assert env.time_manager.time() - start == (int(200 * 2 / 0.8) + 30) * maximum
    assert result["battery_remaining_pct"] == 100 - 5 * maximum


def test_maize_drone_uses_actual_length_and_native_root_water_threshold(field, monkeypatch):
    env, world, drone, _ = field
    world.physics.soil.states[3].root_vwc = 0.21
    observer = world.physics.observation_model
    original = observer.observe_uav_thermal
    truths = {}

    def observe(**arguments):
        truths.update(arguments["truth_by_ridge"])
        return original(**arguments)

    monkeypatch.setattr(observer, "observe_uav_thermal", observe)
    start = env.time_manager.time()
    result = call(drone, "fly_survey", start_ridge=3, end_ridge=7)
    assert result["status"] == "ok"
    assert result["surveyed_ridges"] == [3, 4, 5, 6, 7]
    assert set(truths) == {3, 4, 5, 6, 7}
    threshold = world.physics.crop.observation_traits.unstressed_root_vwc
    assert truths[3].canopy_temp_c == pytest.approx(20 + 2 + (threshold - 0.21) * 25)
    assert env.time_manager.time() - start == 30 + 3 * int(200.0 / 5.0)
    assert [item["ridge_id"] for item in result["observations"]] == result["surveyed_ridges"]


class RequestRecorder:
    provider, model = "openai", "offline-request-recorder"

    def __init__(self):
        self.requests = []

    def chat_completion(self, messages, tools=None):
        self.requests.append((messages, tools))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="checked", tool_calls=None))],
            usage=None,
        )


def test_real_agent_request_contains_maize_schema_and_crop_neutral_prompt(field):
    env, world, drone, robot = field
    tractor = TractorApp(world, env.weather)
    llm = RequestRecorder()
    prompt = get_farm_world_system_prompt("fairy")
    agent = Agent("maize", llm, system_message=prompt, toolsets=[world, tractor, drone, robot])
    agent.time_manager = env.time_manager
    agent.simulation_timezone = env.simulation_timezone
    agent.run("Read this maize field's capabilities before making a planting decision.")
    assert len(llm.requests) == 1
    messages, tools = llm.requests[0]
    system = "\n".join(message.get("content", "") for message in messages if message["role"] == "system")
    assert "farms and crops configured in this scenario" in system
    assert "soybean farms" not in system
    functions = {schema["function"]["name"]: schema["function"] for schema in tools}
    assert "FarmWorldApp__get_crop_capabilities" in functions
    seed = functions["TractorApp__load_seeds"]["parameters"]["properties"]["seed_type"]
    assert seed["enum"] == ["MAIZE_EARLY_2026"]
    assert "3–6 cm" in functions["TractorApp__plant_seeds"]["description"]
    assert "R6_MATURITY" in functions["TractorApp__harvest"]["description"]
    assert "30%" in functions["TractorApp__harvest"]["description"]
