from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from fairy.agents.agent.agent import Agent
from fairy.agents.agent.toolset_builder import build_toolset
from fairy.apps.farm_world.multi_farm import FarmSite, FarmFleet, AssetSpec
from fairy.apps.farm_world.runtime import FarmWeatherView
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.controllers.engine import Engine
from fairy.scenarios.scenario import Scenario
from fairy.types import EventRegisterer


def _fleet(count=2, shared_station=False):
    station = WeatherApp() if shared_station else None
    sites = [FarmSite.create(f"farm_{i}", f"Site{i}", num_ridges=3+i, field_length_m=80,
                            create_devices=False, station_id="common" if shared_station else None,
                            weather_app=station) for i in range(count)]
    ids = tuple(site.spec.farm_id for site in sites)
    fleet = FarmFleet(sites, shared_tools=True, seed=42,
                      assets=[AssetSpec(f"{kind}_1", kind, ids) for kind in ("tractor", "drone", "robot")])
    for site in sites:
        site.weather.set_weather("2026-05-12", 25, 55, 2, 0, 400)
        for ridge in site.farm._ridges:
            ridge.soil_vwc = .26
    scenario = Scenario(apps=fleet.apps, start_time=datetime(2026, 5, 12, 7, tzinfo=timezone.utc).timestamp())
    scenario.runtime_participants = [fleet.runtime]
    engine = Engine(None, scenario)
    return fleet, engine


def test_tool_count_is_independent_of_farm_count_and_schema_matches_targets():
    two, _ = _fleet(2)
    five, _ = _fleet(5)
    _, schemas2, tools2 = build_toolset(two.apps)
    _, schemas5, tools5 = build_toolset(five.apps)
    assert set(tools2) == set(tools5)
    assert len(schemas2) == len(schemas5)
    assert not any(name.startswith("Site") for name in tools2)
    schema = next(item["function"]["parameters"] for item in schemas5
                  if item["function"]["name"] == "Tractor__plant_seeds")
    assert schema["properties"]["farm_id"]["enum"] == sorted(five.runtime.farms)
    assert schema["properties"]["asset_id"]["enum"] == ["tractor_1"]
    assert schema["properties"]["start_ridge"]["type"] == "integer"
    assert "cm" in schema["properties"]["depth_cm"]["description"]
    assert set(schema["required"]) == {"farm_id", "asset_id", "start_ridge", "end_ridge", "depth_cm", "seed_spacing_cm"}
    assert schema["additionalProperties"] is False
    assert all(not site._legacy_devices for site in five.sites)


@pytest.mark.parametrize("changes", [
    {"farm_id": "missing"}, {"asset_id": "robot_1"}, {"start_ridge": True},
    {"start_ridge": 100}, {"extra": 2}, {"depth_cm": float("nan")},
])
def test_wrong_shared_calls_do_not_consume_inventory_asset_or_simulation_offset(changes):
    fleet, engine = _fleet()
    _, _, tools = build_toolset(fleet.apps)
    before = [deepcopy(site.farm._inventory.to_dict()) for site in fleet.sites]
    asset = deepcopy(fleet.runtime.assets["tractor_1"].snapshot())
    offset = engine.time_manager.offset
    arguments = {"farm_id": "farm_0", "asset_id": "tractor_1", "start_ridge": 0,
                 "end_ridge": 0, "depth_cm": 4., "seed_spacing_cm": 8., **changes}
    result = tools["Tractor__plant_seeds"](**arguments)
    assert result["ok"] is False
    assert result["error"]["partial_effects"] is False
    assert before == [site.farm._inventory.to_dict() for site in fleet.sites]
    assert asset == fleet.runtime.assets["tractor_1"].snapshot()
    assert engine.time_manager.offset == offset


def test_same_station_keeps_field_trafficability_independent_and_updates_once():
    fleet, engine = _fleet(shared_station=True)
    dry, wet = fleet.sites
    for ridge in dry.farm._ridges:
        ridge.soil_vwc = .25
    for ridge in wet.farm._ridges:
        ridge.soil_vwc = .45
    assert dry.weather is wet.weather
    assert len(fleet.runtime.stations) == 1
    assert FarmWeatherView(dry.weather, dry.farm).is_trafficable is True
    assert FarmWeatherView(wet.weather, wet.farm).is_trafficable is False
    original = dry.weather.set_weather
    calls = []
    def record(**arguments):
        calls.append(arguments["date"])
        return original(**arguments)
    dry.weather.set_weather = record
    engine.time_manager.add_offset(86400)
    assert len(calls) == 1
    assert FarmWeatherView(wet.weather, wet.farm).is_trafficable is False


def test_capture_records_future_operation_but_execution_checks_current_state():
    fleet, engine = _fleet()
    tractor = next(app for app in fleet.apps if app.name == "Tractor")
    previous = EventRegisterer.last_events
    before = engine.time_manager.offset
    try:
        with EventRegisterer.capture_mode() as events:
            event = tractor.harvest(farm_id="farm_0", asset_id="tractor_1", start_ridge=0, end_ridge=0)
        assert len(events) == 1 and events[0] is event
        assert engine.time_manager.offset == before
        result = event.execute()
        assert result["ok"] is False
        assert engine.time_manager.offset == before
        assert len(events) == 1
    finally:
        EventRegisterer.last_events = previous


def test_public_ridge_views_hide_latent_truth_and_probes_have_global_identity():
    fleet, _ = _fleet()
    _, _, tools = build_toolset(fleet.apps)
    result = tools["Farm__get_ridge_range_state"](farm_id="farm_0", start=0, end=2)
    assert result["ok"]
    encoded = json.dumps(result["data"])
    for hidden in ("nutrient_index", "stand_fraction", "ndvi_proxy"):
        assert hidden not in encoded
    probe = tools["Sensor__read_soil_sensor"](sensor_id="farm_1:S1")
    assert probe["ok"] and probe["farm_id"] == "farm_1"
    assert tools["Sensor__read_soil_sensor"](sensor_id="S1")["ok"] is False


class _SchemaDrivenLLM:
    provider = "openai"
    model = "schema-test"
    max_output_tokens = 1024
    parallel_tool_calls = True
    enable_thinking = None

    def __init__(self):
        self.requests = []

    def chat_completion(self, messages, tools):
        from openai.types.chat import ChatCompletion
        self.requests.append(deepcopy(tools))
        turn = len(self.requests)
        schema = next(tool["function"] for tool in tools if tool["function"]["name"] == "Drone__fly_survey")
        fields = schema["parameters"]["properties"]
        assert fields["farm_id"]["enum"] == ["farm_0", "farm_1"]
        calls = None
        if turn <= 2:
            args = {"farm_id": fields["farm_id"]["enum"][turn-1],
                    "asset_id": fields["asset_id"]["enum"][0], "start_ridge": 0, "end_ridge": 0}
            calls = [{"id": f"call_{turn}", "type": "function",
                      "function": {"name": schema["name"], "arguments": json.dumps(args)}}]
        return ChatCompletion.model_validate({
            "id": f"response_{turn}", "object": "chat.completion", "created": 0, "model": self.model,
            "choices": [{"index": 0, "finish_reason": "tool_calls" if calls else "stop",
                         "message": {"role": "assistant", "content": None if calls else "done", "tool_calls": calls}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})


def test_agent_receives_real_schema_and_uses_one_drone_across_farms():
    fleet, engine = _fleet()
    llm = _SchemaDrivenLLM()
    agent = Agent("schema-agent", llm, toolsets=fleet.apps)
    agent.set_time_manager(engine.time_manager)
    assert agent.run("Survey one ridge in each farm using the same drone.", max_tool_calls=3) == "done"
    calls = [step for step in agent.workflow.dag.values() if step.tool_name == "Drone__fly_survey"]
    assert [step.tool_args["farm_id"] for step in calls] == ["farm_0", "farm_1"]
    assert all(step.content["ok"] for step in calls)
    assert fleet.runtime.assets["drone_1"].data["_battery_pct"] == 98
    assert len(fleet.runtime.assets) == 3


def test_a2a_preserves_direct_catalog_and_expert_target_information():
    from fairy.controllers.app_agent import apply_a2a_to_apps, AppAgent
    from fairy.controllers.agent_builder import AppAgentBuilder
    from fairy.controllers.agent_config import AppAgentConfigBuilder
    fleet, _ = _fleet()
    result = apply_a2a_to_apps(fleet.apps, llm_factory=_SchemaDrivenLLM,
                             app_agent_builder=AppAgentBuilder(),
                             app_agent_config_builder=AppAgentConfigBuilder(), app_prop=1,
                             policy="typed_experts")
    world = next(app for app in result.apps if app.name == "World")
    assert not isinstance(world, AppAgent)
    wrapper = next(app for app in result.apps if app.name == "Drone")
    assert isinstance(wrapper, AppAgent)
    assert "World__describe_environment" in wrapper.app_agent.tools_map
    delegation = wrapper.get_tools()[0]
    description = delegation.function_description
    assert "Drone__fly_survey" in description and "drone_1" in description and "farm_1" in description
    assert delegation.write_operation is True
    assert delegation.metadata["response_format"] == "text"
    assert delegation.metadata["may_modify_state"] is True
    assert "Drone__fly_survey" in delegation.metadata["delegated_tools"]
    receipt_tools = world.describe_environment()["data"]["response_contract"]["applies_to"]
    assert "Drone__fly_survey" in receipt_tools
    assert "Drone__expert_agent" not in receipt_tools
