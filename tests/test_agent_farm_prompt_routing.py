"""Agent/CLI context follows actual worlds rather than an ambiguous crop label."""
from types import SimpleNamespace
import sys

import pytest

from fairy.apps.farm_world import FarmWorldApp
from fairy.controllers.agent_builder import (
    build_controller_agent, get_farm_world_system_prompt_for_apps,
)
from fairy.controllers.agent_config import get_farm_world_system_prompt
from fairy.scenarios.scenario import Scenario


def native_maize():
    world = FarmWorldApp(name="MaizeFarm", farm_id="maize", crop_type="maize", num_ridges=1)
    world.configure_crop_backend("wofost", crop_name="maize", variety_name="Grain_maize_201")
    return world


@pytest.mark.parametrize("mode", ["fairy", "are"])
def test_proxy_rice_and_explicit_reduced_maize_use_generic_actual_tool_guidance(mode):
    expected = get_farm_world_system_prompt(mode, parallel_tool_calls=False)
    for world in (FarmWorldApp(crop_type="rice"), FarmWorldApp(crop_id="maize")):
        prompt = get_farm_world_system_prompt_for_apps([world], mode, parallel_tool_calls=False)
        assert prompt == expected
        assert "PaddyOpsApp" not in prompt
        assert "Crop stages are coarse observations" not in prompt
        assert "Only ONE tool call is allowed per turn." in prompt


def test_only_a_single_native_maize_world_selects_native_maize_instructions():
    world = native_maize()
    prompt = get_farm_world_system_prompt_for_apps([world])
    assert prompt == get_farm_world_system_prompt(crop="maize")
    # A wrapper or repeated reference must not create a fictitious second field.
    assert get_farm_world_system_prompt_for_apps([SimpleNamespace(wrapped_app=world), world]) == prompt
    assert world.physics.crop_backend._runs == {}


@pytest.mark.parametrize("reverse", [False, True])
def test_mixed_farms_do_not_inherit_the_first_crops_prompt(reverse):
    worlds = [FarmWorldApp(name="SoyFarm", farm_id="soy"), native_maize()]
    if reverse:
        worlds.reverse()
    expected = get_farm_world_system_prompt()
    assert get_farm_world_system_prompt_for_apps(worlds) == expected
    # Shared services keep their domain fields behind the public Apps.
    service = SimpleNamespace(runtime=SimpleNamespace(domain_apps=worlds))
    assert get_farm_world_system_prompt_for_apps([service]) == expected


def test_only_an_independent_paddy_world_gets_transplanting_instructions():
    from fairy.apps.paddy.world import PaddyWorldApp

    paddy = PaddyWorldApp()
    expected = get_farm_world_system_prompt(crop="rice")
    assert get_farm_world_system_prompt_for_apps([paddy]) == expected
    assert "PaddyOpsApp" in expected and "transplant" in expected
    assert get_farm_world_system_prompt_for_apps([paddy, FarmWorldApp()]) == get_farm_world_system_prompt()
    # An unrelated App's crop label is not a paddy world declaration.
    assert get_farm_world_system_prompt_for_apps([SimpleNamespace(crop_name="rice")]) == get_farm_world_system_prompt()


def test_controller_default_and_explicit_prompt_use_the_same_public_boundary():
    world = FarmWorldApp(crop_type="rice")
    llm = SimpleNamespace(provider="openai")
    agent = build_controller_agent("farm_baseline_react", llm, toolsets=[world])
    assert agent.system_message == get_farm_world_system_prompt()
    explicit = build_controller_agent("farm_baseline_react", llm, toolsets=[world], system_message="Task-specific prompt")
    assert explicit.system_message == "Task-specific prompt"


@pytest.mark.parametrize("kind,misleading_label", [("proxy_rice", "rice"), ("mixed", "maize"), ("native_maize", "soybean")])
def test_cli_uses_real_apps_instead_of_scenario_crop_label(tmp_path, monkeypatch, kind, misleading_label):
    from fairy import cli

    class TestScenario(Scenario):
        scenario_id = "scenario_prompt_routing_test"
        crop_name = misleading_label

        def init_and_populate_apps(self):
            if kind == "proxy_rice":
                self.apps = [FarmWorldApp(crop_type="rice")]
            elif kind == "native_maize":
                self.apps = [native_maize()]
            else:
                self.apps = [FarmWorldApp(name="SoyFarm", farm_id="soy"), native_maize()]

    expected = get_farm_world_system_prompt(crop="maize" if kind == "native_maize" else "soybean")

    class OfflineLLM:
        provider, model = "vllm", "offline-prompt-routing"
        calls = 0

        def chat_completion(self, messages, tools=None):
            self.calls += 1
            assert messages[0]["content"] == (
                expected + "\n\nToday's date in 'YYYY-MM-DD HH' format is 1970-01-01 08"
            )
            assert tools
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(role="assistant", content="Observed actual tool catalog.", tool_calls=None),
                finish_reason="stop",
            )], usage=None)

    llm = OfflineLLM()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.BaseLLM, "llm_builder", staticmethod(lambda config: llm))
    monkeypatch.setattr(cli, "get_scenario_class", lambda scenario_id: TestScenario)
    monkeypatch.setattr(sys, "argv", [
        "fairy.cli", "--scenario", TestScenario.scenario_id, "--agent",
        "--provider", "vllm", "--model", llm.model,
        "--max-tool-calls", "3", "--timeout-seconds", "30",
        "--output-dir", str(tmp_path / "run"),
    ])
    cli.main()
    assert llm.calls == 1
