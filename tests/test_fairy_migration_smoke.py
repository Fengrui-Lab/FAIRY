from __future__ import annotations

import importlib
import json
import pkgutil
import subprocess
import pytest
from pathlib import Path

import fairy
from fairy.agents.agent.agent import AgentRunLimitExceeded
from fairy.apps.farm_world import FarmWorldApp, WeatherApp
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
from fairy.controllers.agent_builder import AgentBuilder, build_controller_agent
from fairy.controllers.agent_config import ResearchAgentProfileConfig
from fairy.controllers.research_strategies import ResearchStrategyCoordinator
from fairy.scenarios.farm_world_fullseason.scenario_full_season_baseline_balanced_season import (
    ScenarioFullSeasonBalanced,
)
from fairy.scenarios.farm_world_physics.scenario_field_prep_physics_action_tick import (
    ScenarioFarmWorldFieldPrepPhysicsActionTick,
)
from fairy.scenarios.farm_world_physics.scenario_irrigation_physics_action_tick import (
    ScenarioFarmWorldIrrigationPhysicsActionTick,
)
from fairy.scenarios.baseline_farm_world.scenario_field_prep import (
    ScenarioFarmWorldFieldPrep,
)
from fairy.scenarios.registry import list_scenarios
from fairy.scenarios.workflow import Workflow


def test_all_fairy_modules_import() -> None:
    failures = []
    for info in pkgutil.walk_packages(fairy.__path__, fairy.__name__ + "."):
        try:
            importlib.import_module(info.name)
        except Exception as exc:  # pragma: no cover - reported in assertion
            failures.append((info.name, type(exc).__name__, str(exc)))
    assert failures == []


def test_no_are_or_rsare_runtime_imports() -> None:
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["rg", r"from are\.|import are\.|from rsare\.|import rsare\.", "fairy", "tests"],
        cwd=repo,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 1, result.stdout + result.stderr


def test_registry_contains_migrated_farm_scenarios() -> None:
    scenarios = set(list_scenarios())
    assert "scenario_farm_world_field_prep" in scenarios
    assert "scenario_farm_world_field_prep_physics_action_tick" in scenarios
    assert "scenario_full_season_balanced" in scenarios


def test_baseline_field_prep_oracle_sequence() -> None:
    workflow = Engine(None, ScenarioFarmWorldFieldPrep()).run_scenario_oracle(
        run_oracle=False
    )
    assert list(workflow.dag)[:3] == [
        "check_weather",
        "check_forecast",
        "read_soil",
    ]
    assert list(workflow.dag)[-3:] == [
        "attach_furrower",
        "form_ridges",
        "detach_furrower",
    ]


def test_physics_action_tick_oracle_smoke() -> None:
    scenario = ScenarioFarmWorldFieldPrepPhysicsActionTick()
    workflow = Engine(None, scenario).run_scenario_oracle(run_oracle=False)
    assert len(workflow) == 14
    assert next(iter(workflow.dag)) == "oracle_check_weather"
    assert workflow.dag["oracle_attach_grader"].tool_args == {"implement": "grader"}
    assert workflow.dag["oracle_form_ridges"].tool_args == {"ridge_width_m": 1.1}
    assert workflow.dag["oracle_check_weather"].time == "2026-04-25 08:00:00"
    assert workflow.dag["oracle_check_forecast"].time == "2026-04-25 08:00:00"


def test_fullseason_oracle_smoke() -> None:
    workflow = Engine(None, ScenarioFullSeasonBalanced()).run_scenario_oracle(
        run_oracle=False
    )
    assert len(workflow) == 83
    assert "o_store_grain" in workflow.dag
    assert workflow.dag["o_weather_before_planting"].time == "2026-05-04 07:00:00"
    assert workflow.dag["o_wait_to_emergence_window"].time == "2026-05-16 07:00:00"
    assert workflow.dag["o_report"].time == "2026-09-06 13:00:00"


def test_fullseason_scenario_class_defaults_reach_instance() -> None:
    scenario = ScenarioFullSeasonBalanced()

    assert scenario.start_time == ScenarioFullSeasonBalanced.start_time
    assert scenario.duration == ScenarioFullSeasonBalanced.duration
    assert scenario.queue_based_loop is True
    assert scenario.time_increment_in_seconds == 60


def test_system_advance_time_triggers_physics() -> None:
    scenario = ScenarioFarmWorldIrrigationPhysicsActionTick()
    scenario.setup()
    Engine(None, scenario)
    farm_world = scenario.get_typed_app(FarmWorldApp)
    system = scenario.get_typed_app(SystemApp)
    weather = scenario.get_typed_app(WeatherApp)
    assert farm_world.physics_active
    assert farm_world.physics.last_physics_sim_time is None

    result = system.advance_time(hours=24)

    assert result["status"] == "ok"
    assert farm_world.physics.last_physics_sim_time is not None
    assert weather.get_current_weather()["date"] == "2026-05-21"


def test_end_to_end_oracle_replay_evaluate(tmp_path: Path) -> None:
    build_engine = Engine(None, ScenarioFarmWorldFieldPrepPhysicsActionTick())
    oracle_workflow = build_engine.build_oracle_workflow(run_oracle=False)
    oracle_path = tmp_path / "oracle.json"
    oracle_workflow.save_workflow(str(oracle_path))

    replay_engine = Engine(None, ScenarioFarmWorldFieldPrepPhysicsActionTick())
    replay_workflow = replay_engine.replay_workflow(Workflow.load_workflow(str(oracle_path)))
    replay_path = tmp_path / "replay.json"
    replay_workflow.save_workflow(str(replay_path))

    report = replay_engine.evaluation_report(replay_workflow)
    evaluation_path = tmp_path / "evaluation.json"
    evaluation_path.write_text(json.dumps(report), encoding="utf-8")

    assert oracle_path.exists()
    assert replay_path.exists()
    assert evaluation_path.exists()
    assert report["validation"]["success"] is True
    assert report["validation"]["metadata"]["score"] == 1.0
    assert report["validation"]["metadata"]["workflow_steps"] == 14


class _DummyLLM:
    provider = "openai"

    def chat_completion(self, messages, tools=None):  # pragma: no cover - not called
        raise AssertionError("controller construction should not call the LLM")


class _PromptDetails:
    cached_tokens = 3


class _Usage:
    prompt_tokens = 11
    completion_tokens = 5
    total_tokens = 16
    prompt_tokens_details = _PromptDetails()


class _FunctionCall:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _ToolCall:
    type = "function"

    def __init__(self, name: str, arguments: str = "{}") -> None:
        self.id = f"call_{name}"
        self.function = _FunctionCall(name, arguments)


class _Message:
    def __init__(self, content: str | None = None, tool_calls=None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, message: _Message) -> None:
        self.message = message


class _Response:
    usage = _Usage()

    def __init__(self, message: _Message) -> None:
        self.choices = [_Choice(message)]


class _ScriptedLLM:
    provider = "openai"
    model = "fake-model"

    def __init__(self, messages: list[_Message]) -> None:
        self.messages = list(messages)

    def chat_completion(self, messages, tools=None):
        if not self.messages:
            return _Response(_Message(content="done", tool_calls=None))
        return _Response(self.messages.pop(0))


def test_controller_families_include_react_and_rewoo() -> None:
    families = AgentBuilder().list_agents()
    assert "farm_baseline_react" in families
    assert "farm_rewoo_modular" in families
    assert "farm_tree_search" in families
    assert "farm_critic_refiner" in families


def test_rewoo_strategy_builds_plan_context() -> None:
    profile = ResearchAgentProfileConfig.for_family("farm_rewoo_modular")
    telemetry = {"family_id": profile.family_id, "planning_mode": profile.planning_mode}
    strategy = ResearchStrategyCoordinator(profile)
    strategy.reset(telemetry)

    context = strategy.build_context("1. Check weather\n2. Read soil\n3. Irrigate")

    assert "ReWOO plan-work-solve" in context
    assert "Worker now executes: Check weather" in context
    assert telemetry["planned_steps"] == 3


def test_controller_builder_creates_tool_enabled_agent() -> None:
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    agent = build_controller_agent(
        "farm_rewoo_modular",
        llm=_DummyLLM(),
        toolsets=scenario.apps,
    )

    assert agent.name == "farm_rewoo_modular"
    assert "FarmWorldApp__get_inventory" in agent.tools_map
    assert agent.controller_profile.rewoo.enabled


def test_agent_runtime_events_capture_llm_tool_metrics() -> None:
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    llm = _ScriptedLLM(
        [
            _Message(tool_calls=[_ToolCall("FarmWorldApp__get_inventory")]),
            _Message(content="done", tool_calls=None),
        ]
    )
    agent = build_controller_agent(
        "farm_baseline_react",
        llm=llm,
        toolsets=scenario.apps,
    )
    engine = Engine(agent, scenario)

    workflow = engine.run_scenario_agent(
        max_tool_calls=5,
        timeout_seconds=30,
        setup_scenario=False,
    )

    event_types = [event["event_type"] for event in agent.runtime_events]
    assert "llm_call_start" in event_types
    assert "llm_call_end" in event_types
    assert "tool_call_start" in event_types
    assert "tool_call_end" in event_types
    assert "agent_run_end" in event_types
    assert agent.tool_call_count == 1
    assert len(workflow) == 2
    assert agent.messages.runtime_metrics[0]["tokens"]["total_tokens"] == 16


def test_agent_runtime_events_capture_limits_and_parse_errors() -> None:
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    limited_agent = build_controller_agent(
        "farm_baseline_react",
        llm=_ScriptedLLM([_Message(tool_calls=[_ToolCall("FarmWorldApp__get_inventory")])]),
        toolsets=scenario.apps,
    )
    limited_engine = Engine(limited_agent, scenario)

    with pytest.raises(AgentRunLimitExceeded):
        limited_engine.run_scenario_agent(
            max_tool_calls=0,
            timeout_seconds=30,
            setup_scenario=False,
        )
    assert any(
        event["event_type"] == "agent_limit_exceeded"
        for event in limited_agent.runtime_events
    )

    parse_scenario = ScenarioFarmWorldFieldPrep()
    parse_scenario.setup()
    parse_agent = build_controller_agent(
        "farm_baseline_react",
        llm=_ScriptedLLM(
            [_Message(tool_calls=[_ToolCall("FarmWorldApp__get_inventory", "{bad json")])]
        ),
        toolsets=parse_scenario.apps,
    )
    parse_engine = Engine(parse_agent, parse_scenario)

    with pytest.raises(json.JSONDecodeError):
        parse_engine.run_scenario_agent(
            max_tool_calls=5,
            timeout_seconds=30,
            setup_scenario=False,
        )
    assert any(
        event["event_type"] == "tool_args_parse_error"
        for event in parse_agent.runtime_events
    )
