"""Farm-specific context stays accurate without changing tools or field state."""
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from fairy.apps.app import App
from fairy.apps.farm_world import FarmWorldApp, WeatherApp
from fairy.apps.farm_world.sensor_app import SensorApp
from fairy.controllers.agent_builder import AppAgentBuilder, build_controller_agent
from fairy.controllers.agent_config import AppAgentConfigBuilder, WEATHER_APP_AGENT_ADDENDUM
from fairy.time_manager import SimulationTimeManager


@pytest.mark.parametrize("family", [
    "farm_planner_executor", "farm_reflective_memory", "farm_multi_specialist",
    "farm_adaptive_verifier", "farm_rewoo_modular", "farm_tree_search",
    "farm_critic_refiner", "farm_graph_memory",
])
def test_default_farm_context_preserves_controller_family_instructions(family):
    agent = build_controller_agent(family, SimpleNamespace(provider="openai"),
                                   toolsets=[FarmWorldApp()])
    assert "experienced farm manager" in agent.system_message
    assert "<research_family_instructions>" in agent.system_message
    explicit = build_controller_agent(family, SimpleNamespace(provider="openai"),
                                      toolsets=[FarmWorldApp()], system_message="Custom task rules")
    assert explicit.system_message == "Custom task rules"


def test_agricultural_delegate_preserves_specialization_and_other_app_defaults():
    llm = SimpleNamespace(provider="openai")
    builder = AppAgentBuilder()
    config = AppAgentConfigBuilder().build("weather_expert_app_agent")
    agricultural = builder.build(config, llm, WeatherApp())
    assert "farm work delegated to you" in agricultural.system_message
    assert "MetaOSSAgent" not in agricultural.system_message
    assert agricultural.system_message.endswith(WEATHER_APP_AGENT_ADDENDUM)
    generic = builder.build(config, llm, App(name="OtherApp"))
    assert generic.system_message == config.system_prompt
    custom = AppAgentConfigBuilder(app_system_prompt="Custom delegated role").build("default_app_agent")
    assert builder.build(custom, llm, WeatherApp()).system_message == "Custom delegated role"


def test_task_start_time_uses_scene_timezone_and_does_not_advance_clock():
    agent = build_controller_agent("farm_baseline_react", SimpleNamespace(provider="openai"),
                                   toolsets=[FarmWorldApp()])
    clock = SimulationTimeManager()
    start = datetime(2019, 4, 28, 5, tzinfo=timezone.utc).timestamp()
    clock.reset(start)
    agent.time_manager = clock
    agent.simulation_timezone = ZoneInfo("Europe/Paris")
    agent.messages.messages = [{"role": "system", "content": agent.system_message}]
    agent._ensure_current_time_system_prompt()
    assert "Task start time: 2019-04-28 07:00+02:00 (Europe/Paris)" in agent.messages.messages[0]["content"]
    assert clock.time() == start
    clock.add_offset(86400)
    agent._ensure_current_time_system_prompt()
    content = agent.messages.messages[0]["content"]
    assert "Task start time: 2019-04-29 07:00+02:00 (Europe/Paris)" in content
    assert content.count("Task start time:") == 1
    assert clock.time() == start + 86400


def test_soil_readout_description_matches_actual_water_source_without_starting_crop():
    shallow = FarmWorldApp(num_ridges=1)
    root_only = FarmWorldApp(crop_type="maize", num_ridges=1)
    root_only.configure_crop_backend("wofost", crop_name="maize", variety_name="Grain_maize_201")
    for world, expected in [(shallow, "at 5 cm depth"), (root_only, "not an independent 5 cm water measurement")]:
        clock = SimulationTimeManager()
        clock.reset(1_800_000_000)
        world.register_time_manager(clock)
        probes = SensorApp(world)
        probes.register_time_manager(clock)
        before = clock.time()
        schema = next(t.to_open_ai()["function"] for t in probes.get_tools() if t.name == "read_soil_sensors")
        assert expected in schema["description"]
        assert schema["parameters"]["properties"] == {}
        assert clock.time() == before
    assert root_only.physics.crop_backend._runs == {}
