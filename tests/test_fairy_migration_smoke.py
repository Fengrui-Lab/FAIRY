from __future__ import annotations

import argparse
import csv
import importlib
import io
import json
import pkgutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

import fairy
from fairy.agents.agent.agent import AgentRunLimitExceeded
from fairy.agents.agent.base_agent import CST
from fairy.agents.llm.base_llm import BaseLLM
from fairy.apps.farm_world import FarmWorldApp, WeatherApp
from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs
from fairy.apps.system import SystemApp
from fairy.controllers.agent_builder import (
    AgentBuilder,
    AppAgentBuilder,
    ResearchARESimulationAgent,
    build_controller_agent,
)
from fairy.controllers.agent_config import (
    AgentConfigBuilder,
    AppAgentConfigBuilder,
    ResearchAgentProfileConfig,
    get_farm_world_system_prompt,
)
from fairy.controllers.app_agent import (
    AppAgent,
    apply_a2a_to_apps,
    collect_a2a_traces,
    resolve_a2a_agent_name_for_app,
)
from fairy.controllers.engine import Engine
from fairy.controllers.research_strategies import ResearchStrategyCoordinator
from fairy.controllers.skill_library import DynamicSkillLibrary
from fairy.scenarios.baseline_farm_world.scenario_field_prep import (
    ScenarioFarmWorldFieldPrep,
)
from fairy.scenarios.farm_world_fullseason.scenario_full_season_baseline_balanced_season import (
    ScenarioFullSeasonBalanced,
)
from fairy.scenarios.farm_world_fullseason_v2.scenario_full_season_hb_base_hn84_std_normal import (
    ScenarioFullSeasonHBBaseHN84StdNormal,
)
from fairy.scenarios.farm_world_physics.scenario_field_prep_physics_action_tick import (
    ScenarioFarmWorldFieldPrepPhysicsActionTick,
)
from fairy.scenarios.farm_world_physics.scenario_irrigation_physics_action_tick import (
    ScenarioFarmWorldIrrigationPhysicsActionTick,
)
from fairy.scenarios.registry import get_scenario_class, list_scenarios
from fairy.scenarios.workflow import Workflow, WorkflowStep


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


def test_workflow_save_creates_parent_directory(tmp_path: Path) -> None:
    workflow = Workflow()
    workflow.add_node(WorkflowStep(name="check_weather", tool_name="WeatherApp__get_current_weather"))
    path = tmp_path / "new" / "nested" / "workflow.json"

    workflow.save_workflow(str(path))

    assert Workflow.load_workflow(str(path)).to_dict() == workflow.to_dict()


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
    assert len(workflow) == 15
    assert next(iter(workflow.dag)) == "field_prep_briefing"
    assert workflow.dag["oracle_check_weather"].depends_on == ["field_prep_briefing"]
    assert workflow.dag["oracle_attach_grader"].tool_args == {"implement": "grader"}
    assert workflow.dag["oracle_form_ridges"].tool_args == {"ridge_width_m": 1.1}
    assert workflow.dag["oracle_check_weather"].time == "2026-04-25 08:00:07"
    assert workflow.dag["oracle_check_forecast"].time == "2026-04-25 08:00:08"


def test_fullseason_oracle_smoke() -> None:
    workflow = Engine(None, ScenarioFullSeasonBalanced()).run_scenario_oracle(
        run_oracle=False
    )
    assert len(workflow) == 84
    assert next(iter(workflow.dag)) == "briefing"
    assert "o_store_grain" in workflow.dag
    assert workflow.dag["o_weather_before_planting"].time == "2026-05-04 07:00:07"
    assert workflow.dag["o_wait_to_emergence_window"].time == "2026-05-16 07:00:51"
    assert workflow.dag["o_report"].time == "2026-09-06 13:02:15"


def test_fullseason_v2_formal90_registered() -> None:
    formal_ids = [
        line.strip()
        for line in Path("scripts/fullseason/formal_90_scenario_ids.txt").read_text().splitlines()
        if line.strip()
    ]
    registered = set(list_scenarios())

    assert len(formal_ids) == 90
    assert not [scenario_id for scenario_id in formal_ids if scenario_id not in registered]


def test_fullseason_v2_l2_skill_72_registered() -> None:
    skill_ids = [
        line.strip()
        for line in Path("scripts/fullseason/l2_skill_scenario_ids.txt").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    source_l3_ids = [
        line.strip()
        for line in Path("scripts/fullseason/l3_skill_source_ids.txt").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    registered = set(list_scenarios())

    assert len(skill_ids) == 72
    assert len(source_l3_ids) == 20
    assert not [scenario_id for scenario_id in skill_ids if scenario_id not in registered]


def test_fullseason_v2_oracle_replay_evaluate_smoke(tmp_path: Path) -> None:
    build_engine = Engine(None, ScenarioFullSeasonHBBaseHN84StdNormal())
    oracle_workflow = build_engine.build_oracle_workflow(run_oracle=False)
    oracle_path = tmp_path / "v2_oracle.json"
    oracle_workflow.save_workflow(str(oracle_path))

    replay_engine = Engine(None, ScenarioFullSeasonHBBaseHN84StdNormal())
    replay_workflow = replay_engine.replay_workflow(Workflow.load_workflow(str(oracle_path)))
    report = replay_engine.evaluation_report(replay_workflow)

    assert len(oracle_workflow) == 242
    assert next(iter(oracle_workflow.dag)) == "briefing"
    assert oracle_workflow.dag["briefing"].time == "2026-05-05 07:00:05"
    assert oracle_workflow.dag["o_weather_before_prep"].depends_on == ["briefing"]
    assert oracle_workflow.dag["o_report"].time == "2026-09-08 11:04:55"
    assert len(replay_workflow) == 242
    assert report["validation"]["success"] is True


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


def test_weather_event_rain_event_is_physics_input_not_framework_event() -> None:
    scenario_cls = get_scenario_class("scenario_full_season_hb_wetjune_short_spray_window")
    scenario = scenario_cls()
    scenario.setup()
    farm_world = scenario.get_typed_app(FarmWorldApp)
    weather = scenario.get_typed_app(WeatherApp)

    inputs = _build_weather_inputs(weather, date(2026, 6, 15), farm_world.physics)
    current_weather = weather.get_current_weather()

    assert farm_world.physics.profile.name == "harbin_l3_wetjune_short_spray_window_seed_1521"
    assert inputs["soil"].rain_mm > 80.0
    assert current_weather["date"] == "2026-06-15"
    assert current_weather["rainfall_mm"] == round(inputs["soil"].rain_mm, 2)
    assert "weather_tags" not in current_weather
    assert "rain_event" not in current_weather


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
    assert report["validation"]["metadata"]["workflow_steps"] == 15


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


class _FailingLLM:
    provider = "openai"
    model = "failing-model"

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def chat_completion(self, messages, tools=None):
        raise self.exc


class _FlakyLLM:
    provider = "openai"
    model = "flaky-model"

    def __init__(self, exc: Exception, message: _Message) -> None:
        self.exc = exc
        self.message = message
        self.calls = 0

    def chat_completion(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            raise self.exc
        return _Response(self.message)


def test_controller_families_include_react_and_rewoo() -> None:
    families = AgentBuilder().list_agents()
    assert "farm_baseline_react" in families
    assert "farm_rewoo_modular" in families
    assert "farm_tree_search" in families
    assert "farm_critic_refiner" in families
    assert "farm_skill_rag" not in families
    with pytest.raises(ValueError):
        AgentConfigBuilder().build("farm_skill_rag")


def test_farm_controller_prompt_uses_are_farm_context_with_function_calling() -> None:
    config = AgentConfigBuilder().build("farm_baseline_react")
    prompt = config.base_agent_config.system_prompt

    assert "soybean farm in Harbin, Heilongjiang" in prompt
    assert "64 ridges across a 268m x 71m field" in prompt
    assert "provided function tools" in prompt
    assert "do not hand-write JSON action blobs" in prompt
    assert "Don't call tools unnecessarily" not in prompt
    assert "Action:" not in prompt


def test_are_system_prompt_mode_ports_compatible_legacy_behavior_rules() -> None:
    fairy_prompt = get_farm_world_system_prompt("fairy")
    are_prompt = get_farm_world_system_prompt("are")
    compatible_are_rules = (
        "Thought: briefly explain what you are thinking and why a tool is needed.",
        "Only ONE tool call is allowed per turn.",
        "For booleans, use true/false in lowercase.",
        "Do NOT generate or fabricate the Observation",
        "If a tool call fails, analyze the error and try a different approach.",
        "Don't call tools unnecessarily - use your reasoning when you can solve something directly.",
        "Pay attention to tool outputs and use them to inform subsequent actions.",
    )

    for rule in compatible_are_rules:
        assert rule not in fairy_prompt
        assert rule in are_prompt
    assert "provided function tools" in are_prompt
    assert "do not hand-write JSON action blobs" in are_prompt
    assert "\nAction:\n" not in are_prompt
    assert "<end_action>" not in are_prompt
    assert '"action_input"' not in are_prompt
    assert "FORMAT SPECIFICATION" not in are_prompt
    assert "EXAMPLE CYCLE" not in are_prompt
    with pytest.raises(ValueError, match="Unknown FARM system prompt mode"):
        get_farm_world_system_prompt("unknown")


def test_app_agent_profiles_match_are_names_and_prompts() -> None:
    builder = AppAgentConfigBuilder()

    assert builder.list_agents() == [
        "default_app_agent",
        "weather_expert_app_agent",
        "sensor_expert_app_agent",
        "machinery_expert_app_agent",
        "operations_expert_app_agent",
    ]
    weather = builder.build("weather_expert_app_agent")
    machinery = builder.build("machinery_expert_app_agent")

    assert weather.max_iterations == 60
    assert "Meta Agents Research Environments" in weather.system_prompt
    assert "provided function tools" in weather.system_prompt
    assert "weather and field-conditions expert" in weather.system_prompt
    assert machinery.max_iterations == 70
    assert "machinery and implement operations expert" in machinery.system_prompt


def test_a2a_typed_routing_and_wrapper_tool_exposure() -> None:
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    result = apply_a2a_to_apps(
        list(scenario.apps or []),
        llm_factory=lambda: _ScriptedLLM([_Message(content="done")]),
        app_agent_builder=AppAgentBuilder(),
        app_agent_config_builder=AppAgentConfigBuilder(),
        app_prop=1.0,
        policy="typed_experts",
        app_agent_name="default_app_agent",
        seed=scenario.seed,
    )

    wrappers = [app for app in result.apps if isinstance(app, AppAgent)]
    assert wrappers
    assert result.metadata["enabled"] is True
    assert result.metadata["transformed_apps"]
    assert all(app.name != "SystemAppExpert" for app in wrappers)
    assert all(app.max_tool_calls is not None for app in wrappers)
    assert resolve_a2a_agent_name_for_app(WeatherApp()) == "default_app_agent"
    assert resolve_a2a_agent_name_for_app(WeatherApp(), policy="typed_experts") == (
        "weather_expert_app_agent"
    )

    _, schemas, tools_map = __import__(
        "fairy.agents.agent.toolset_builder",
        fromlist=["build_toolset"],
    ).build_toolset(result.apps)
    schema_names = {schema["function"]["name"] for schema in schemas}
    assert "WeatherApp__expert_agent" in schema_names
    assert "WeatherAppExpert__expert_agent" not in schema_names
    assert "WeatherApp__get_current_weather" not in tools_map


def test_a2a_expert_agent_limit_can_be_capped_by_runner_budget() -> None:
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    result = apply_a2a_to_apps(
        list(scenario.apps or []),
        llm_factory=lambda: _ScriptedLLM([_Message(content="done")]),
        app_agent_builder=AppAgentBuilder(),
        app_agent_config_builder=AppAgentConfigBuilder(),
        app_prop=1.0,
        policy="typed_experts",
        app_agent_name="default_app_agent",
        seed=scenario.seed,
        max_tool_calls=3,
    )

    wrappers = [app for app in result.apps if isinstance(app, AppAgent)]
    assert wrappers
    assert all(app.max_tool_calls == 3 for app in wrappers)


def test_a2a_expert_agent_can_call_wrapped_app_tool() -> None:
    weather = WeatherApp()
    config = AppAgentConfigBuilder().build("weather_expert_app_agent")
    expert = AppAgentBuilder().build(
        config,
        llm=_ScriptedLLM(
            [
                _Message(tool_calls=[_ToolCall("WeatherApp__get_current_weather")]),
                _Message(content="weather checked", tool_calls=None),
            ]
        ),
        app=weather,
    )
    wrapper = AppAgent(
        wrapped_app=weather,
        app_agent=expert,
        app_agent_name="weather_expert_app_agent",
    )

    answer = wrapper.expert_agent("Check current weather.")

    assert answer == "weather checked"
    assert wrapper.last_tool_call_count == 1
    user_messages = [
        message
        for message in wrapper.app_agent.messages.messages
        if isinstance(message, dict) and message["role"] == "user"
    ]
    assert user_messages
    expected_time = datetime.fromtimestamp(wrapper.time_manager.time(), tz=CST).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    assert f"Received at: {expected_time}" in user_messages[0]["content"]
    assert "Sender: User" in user_messages[0]["content"]
    assert "Message: Check current weather." in user_messages[0]["content"]
    assert "Already read: True" in user_messages[0]["content"]
    assert f"Read at: {expected_time}" in user_messages[0]["content"]
    assert any(event["event_type"] == "tool_call_end" for event in wrapper.last_runtime_events)


def test_a2a_expert_agent_limit_returns_partial_result() -> None:
    weather = WeatherApp()
    config = AppAgentConfigBuilder().build("weather_expert_app_agent")
    expert = AppAgentBuilder().build(
        config,
        llm=_ScriptedLLM([_Message(tool_calls=[_ToolCall("WeatherApp__get_current_weather")])]),
        app=weather,
    )
    wrapper = AppAgent(
        wrapped_app=weather,
        app_agent=expert,
        app_agent_name="weather_expert_app_agent",
        max_tool_calls=0,
    )

    answer = wrapper.expert_agent("Check current weather.")

    assert "Expert agent stopped before completing the delegated task" in answer
    assert "max_tool_calls=0" in answer
    assert wrapper.last_answer == answer
    assert wrapper.last_tool_call_count == 0
    assert any(
        event["event_type"] == "agent_limit_exceeded"
        and event["status"] == "stopped"
        for event in wrapper.last_runtime_events
    )
    assert any(
        event["event_type"] == "agent_run_end"
        and event["status"] == "stopped"
        for event in wrapper.last_runtime_events
    )
    assert any(
        event["event_type"] == "a2a_expert_limit_returned"
        and event["status"] == "stopped"
        for event in wrapper.last_runtime_events
    )


def test_collect_a2a_traces_exports_expert_prompt_events_and_metrics() -> None:
    weather = WeatherApp()
    config = AppAgentConfigBuilder().build("weather_expert_app_agent")
    expert = AppAgentBuilder().build(
        config,
        llm=_ScriptedLLM(
            [
                _Message(tool_calls=[_ToolCall("WeatherApp__get_current_weather")]),
                _Message(content="weather checked", tool_calls=None),
            ]
        ),
        app=weather,
    )
    wrapper = AppAgent(
        wrapped_app=weather,
        app_agent=expert,
        app_agent_name="weather_expert_app_agent",
    )

    wrapper.expert_agent("Check current weather.")
    traces = collect_a2a_traces([wrapper])

    assert traces[0]["wrapper_app_name"] == "WeatherApp"
    assert traces[0]["app_agent"] == "weather_expert_app_agent"
    assert "weather and field-conditions expert" in traces[0]["messages"][0]["content"]
    assert "Message: Check current weather." in traces[0]["messages"][1]["content"]
    assert traces[0]["tool_call_count"] == 1
    assert traces[0]["runtime_metrics"][0]["tokens"]["total_tokens"] == 16
    assert any(event["event_type"] == "tool_call_end" for event in traces[0]["runtime_events"])
    assert "step1" in traces[0]["workflow"]


def test_engine_registers_wrapped_farm_world_for_system_time_advance() -> None:
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    result = apply_a2a_to_apps(
        list(scenario.apps or []),
        llm_factory=lambda: _ScriptedLLM([_Message(content="done")]),
        app_agent_builder=AppAgentBuilder(),
        app_agent_config_builder=AppAgentConfigBuilder(),
        app_prop=1.0,
        policy="typed_experts",
        app_agent_name="default_app_agent",
        seed=scenario.seed,
    )
    scenario.apps = result.apps

    Engine(agent=None, scenario=scenario)
    system_app = next(app for app in scenario.apps or [] if isinstance(app, SystemApp))

    assert getattr(system_app, "_farm_world_app", None).__class__.__name__ == "FarmWorldApp"
    assert system_app.advance_time(days=1)["status"] == "ok"


def test_iclr_runner_passes_a2a_cli_flags() -> None:
    from scripts.iclr_validation_runner import CellSpec, _build_cell_command

    cmd = _build_cell_command(
        CellSpec(family="farm_baseline_react", scenario="scenario_x", repeat=1),
        model="deepseek-chat",
        provider="deepseek",
        output_dir=Path("/tmp/fairy-cell"),
        a2a_enabled=True,
        a2a_app_prop=0.75,
        a2a_policy="typed_experts",
        a2a_app_agent="weather_expert_app_agent",
        a2a_model="qwen-plus",
        a2a_provider="qwen",
        a2a_endpoint="http://localhost:8000/v1",
        parallel_tool_calls=False,
        max_output_tokens=4096,
        system_prompt_mode="are",
    )

    joined = " ".join(cmd)
    assert "--a2a true" in joined
    assert "--a2a-app-prop 0.75" in joined
    assert "--a2a-policy typed_experts" in joined
    assert "--a2a-app-agent weather_expert_app_agent" in joined
    assert "--a2a-model qwen-plus" in joined
    assert "--a2a-provider qwen" in joined
    assert "--a2a-endpoint http://localhost:8000/v1" in joined
    assert "--parallel-tool-calls false" in joined
    assert "--max-output-tokens 4096" in joined
    assert "--system-prompt-mode are" in joined


def test_rewoo_strategy_builds_plan_context() -> None:
    profile = ResearchAgentProfileConfig.for_family("farm_rewoo_modular")
    telemetry = {"family_id": profile.family_id, "planning_mode": profile.planning_mode}
    strategy = ResearchStrategyCoordinator(profile)
    strategy.reset(telemetry)

    context = strategy.build_context("1. Check weather\n2. Read soil\n3. Irrigate")

    assert "ReWOO plan-work-solve" in context
    assert "Worker now executes: Check weather" in context
    assert telemetry["planned_steps"] == 3


@pytest.mark.parametrize(
    ("family_id", "planning_mode"),
    [
        ("farm_reflective_memory", "reflective"),
        ("farm_multi_specialist", "multi_specialist"),
        ("farm_adaptive_verifier", "adaptive_verifier"),
        ("farm_rewoo_modular", "rewoo_modular"),
        ("farm_tree_search", "tree_search"),
        ("farm_critic_refiner", "critic_refiner"),
        ("farm_graph_memory", "graph_memory"),
    ],
)
def test_agent_config_builder_matches_are_research_profiles(
    family_id: str, planning_mode: str
) -> None:
    config = AgentConfigBuilder().build(family_id)

    assert config.research_profile is not None
    assert config.research_profile.family_id == family_id
    assert config.research_profile.planning_mode == planning_mode
    if family_id in {"farm_adaptive_verifier", "farm_rewoo_modular"}:
        assert config.research_profile.replan_on_tool_error is True


def test_dynamic_skill_library_retrieves_migrated_skills() -> None:
    library = DynamicSkillLibrary("fairy/controllers/research_skills")

    results = library.retrieve("check weather forecast before harvest", top_k=2)

    assert results
    assert results[0][0].skill_id == "weather_window_assessment"


def test_skill_retrieval_oracle_workflow_is_canonical() -> None:
    from scripts.fullseason import run_l3_skill_retrieval_experiments as retrieval

    scenario_id = "scenario_full_season_hb_heihe43_early_density_weed_nutrient_recovery"
    workflow = retrieval._oracle_workflow(scenario_id)
    steps = list(workflow.values())

    assert len(steps) == 147
    timestamps = [step.get("time") for step in steps]
    assert all(isinstance(timestamp, (int, float)) for timestamp in timestamps)
    assert timestamps == sorted(timestamps)
    assert timestamps[-1] > timestamps[0]
    assert all(not str(step.get("tool_name") or "").startswith("AgentUserInterface__") for step in steps)
    assert not any(
        left.get("tool_name") == right.get("tool_name") == "SystemApp__advance_time"
        for left, right in zip(steps, steps[1:])
    )
    planting = next(step for step in steps if step.get("tool_name") == "TractorApp__plant_seeds")
    assert set(planting["tool_args"]) == {
        "start_ridge",
        "end_ridge",
        "depth_cm",
        "seed_spacing_cm",
    }
    assert retrieval._metric_score(workflow, workflow) == pytest.approx(1.0)


def test_all_pathsim_skill_builders_accept_fairy_workflows(monkeypatch) -> None:
    from scripts.fullseason import run_l3_skill_retrieval_experiments as retrieval

    target = "scenario_full_season_hb_heihe43_early_density_weed_nutrient_recovery"
    reference = "scenario_full_season_hb_coldspring_planting_window_heihe50"
    workflows = {
        scenario_id: retrieval._oracle_workflow(scenario_id)
        for scenario_id in (target, reference)
    }
    monkeypatch.setattr(
        retrieval,
        "_load_candidate_agent_workflow",
        lambda _root, scenario_id: workflows[scenario_id],
    )
    unused_root = Path("/tmp/fairy-pathsim-test")

    contexts = {
        "l2_pathsim_differ": retrieval._build_l2_pathsim_contexts(
            unused_root, [target], 4
        ),
        "l2_pathsim_grouped_differ": retrieval._build_l2_pathsim_grouped_contexts(
            unused_root, [target]
        ),
        "l3_pathsim_same": retrieval._build_l3_pathsim_contexts(
            unused_root, [target], [target, reference], 4, same=True
        ),
        "l3_pathsim_differ": retrieval._build_l3_pathsim_contexts(
            unused_root, [target], [target, reference], 4, same=False
        ),
    }

    for mode, context_map in contexts.items():
        assert target in context_map, mode
        assert context_map[target].strip(), mode


def test_skill_retrieval_runner_passes_parallel_tool_setting() -> None:
    from scripts.fullseason import run_l3_skill_retrieval_experiments as retrieval

    args = argparse.Namespace(
        families="farm_baseline_react",
        scenarios="scenario_x",
        repeats=1,
        model="deepseek-chat",
        provider="deepseek",
        cost_cap_dollars=9999.0,
        max_concurrent=1,
        cell_timeout_s=1800,
        cell_timeout_grace_s=120,
        agent_max_iterations=300,
        parallel_tool_calls=False,
        wait_for_user_input_timeout=5.0,
        log_level="INFO",
        endpoint=None,
    )
    command = retrieval.build_runner_command(
        args,
        group="detail_false",
        scenario_kwargs={"detailed_briefing": False},
        output_dir=Path("/tmp/fairy-skill-runner"),
    )

    assert "--parallel-tool-calls" in command
    assert command[command.index("--parallel-tool-calls") + 1] == "false"

    from scripts.fullseason import (
        run_deepseek_json_l3_20_retrieval_experiments as deepseek_retrieval,
    )

    wrapper_args = argparse.Namespace(
        families="farm_baseline_react",
        repeats=1,
        model="deepseek-chat",
        provider="deepseek",
        cost_cap_dollars=200.0,
        max_concurrent=1,
        cell_timeout_s=1200,
        cell_timeout_grace_s=60,
        agent_max_iterations=200,
        parallel_tool_calls="false",
        wait_for_user_input_timeout=5.0,
    )
    wrapper_command = deepseek_retrieval._base_runner_cmd(wrapper_args)

    assert "--parallel-tool-calls" in wrapper_command
    assert wrapper_command[wrapper_command.index("--parallel-tool-calls") + 1] == "false"


def test_controller_builder_creates_tool_enabled_agent() -> None:
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    agent = build_controller_agent(
        "farm_rewoo_modular",
        llm=_DummyLLM(),
        toolsets=scenario.apps,
    )

    assert agent.name == "farm_rewoo_modular"
    assert isinstance(agent, ResearchARESimulationAgent)
    assert "FarmWorldApp__get_inventory" in agent.tools_map
    assert agent.controller_profile.rewoo.enabled
    assert agent.controller_profile.planning_mode == "rewoo_modular"


def test_qwen_and_vllm_clients_use_function_call_path(monkeypatch) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "test-key")
    monkeypatch.setenv("VLLM_API_KEY", "EMPTY")

    qwen = BaseLLM.llm_builder(
        {"provider": "qwen", "model": "qwen3.6-flash-2026-04-16"}
    )
    qwen_legacy = BaseLLM.llm_builder(
        {"provider": "qwen-json", "model": "qwen3.6-flash-2026-04-16"}
    )
    vllm = BaseLLM.llm_builder(
        {
            "provider": "vllm",
            "model": "Qwen/Qwen3-1.7B",
            "base_url": "http://localhost:8000/v1",
        }
    )

    assert qwen.provider == "qwen"
    assert qwen_legacy.provider == "qwen"
    assert vllm.provider == "vllm"


def test_vllm_qwen_client_disables_thinking_in_chat_template(monkeypatch) -> None:
    monkeypatch.setenv("VLLM_API_KEY", "EMPTY")
    monkeypatch.delenv("FAIRY_VLLM_ENABLE_THINKING", raising=False)
    captured: dict = {}

    class _CaptureCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _Response(_Message(content="ok", tool_calls=None))

    class _CaptureChat:
        completions = _CaptureCompletions()

    class _CaptureClient:
        chat = _CaptureChat()

    vllm = BaseLLM.llm_builder(
        {
            "provider": "vllm",
            "model": "Qwen3.5-9B",
            "base_url": "http://localhost:8000/v1",
            "parallel_tool_calls": False,
        }
    )
    vllm.api_client = _CaptureClient()

    vllm.chat_completion([{"role": "user", "content": "Return ok"}], tools=[])

    assert captured["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
    assert captured["parallel_tool_calls"] is False
    assert captured["max_tokens"] == 2048


def test_deepseek_client_passes_parallel_tool_calls(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    captured: dict = {}

    class _CaptureCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _Response(_Message(content="ok", tool_calls=None))

    class _CaptureChat:
        completions = _CaptureCompletions()

    class _CaptureClient:
        chat = _CaptureChat()

    deepseek = BaseLLM.llm_builder(
        {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "parallel_tool_calls": False,
            "max_output_tokens": 4096,
        }
    )
    deepseek.api_client = _CaptureClient()

    deepseek.chat_completion([{"role": "user", "content": "Return ok"}], tools=[])

    assert captured["parallel_tool_calls"] is False
    assert captured["max_tokens"] == 4096


def test_llm_max_output_tokens_default_and_environment_override(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("FAIRY_LLM_MAX_OUTPUT_TOKENS", raising=False)

    default_client = BaseLLM.llm_builder(
        {"provider": "deepseek", "model": "deepseek-chat"}
    )
    assert default_client.max_output_tokens == 2048

    monkeypatch.setenv("FAIRY_LLM_MAX_OUTPUT_TOKENS", "3072")
    environment_client = BaseLLM.llm_builder(
        {"provider": "deepseek", "model": "deepseek-chat"}
    )
    assert environment_client.max_output_tokens == 3072

    with pytest.raises(ValueError, match="positive integer"):
        BaseLLM.llm_builder(
            {
                "provider": "deepseek",
                "model": "deepseek-chat",
                "max_output_tokens": 0,
            }
        )


def test_openai_compatible_clients_accept_request_timeout(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("FAIRY_LLM_REQUEST_TIMEOUT_S", "12.5")

    deepseek = BaseLLM.llm_builder(
        {"provider": "deepseek", "model": "deepseek-chat"}
    )
    qwen = BaseLLM.llm_builder(
        {"provider": "qwen", "model": "qwen-plus", "timeout": 7}
    )

    assert deepseek.request_timeout == 12.5
    assert qwen.request_timeout == 7.0


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
    assert agent.telemetry["tool_calls"] == 1
    assert agent.telemetry["llm_calls"] == 2
    assert len(workflow) == 2
    tool_step = next(step for step in workflow.dag.values() if step.op_type == "TOOL")
    assert isinstance(tool_step.time_before, float)
    assert isinstance(tool_step.time_after, float)
    assert tool_step.time_after >= tool_step.time_before
    assert agent.messages.runtime_metrics[0]["tokens"]["total_tokens"] == 16
    llm_starts = [event for event in agent.runtime_events if event["event_type"] == "llm_call_start"]
    llm_start = llm_starts[0]
    assert llm_start["max_output_tokens"] is None
    assert llm_start["messages"][0]["role"] == "system"
    assert llm_start["messages"][-1]["role"] == "user"
    assert "FarmWorldApp__get_inventory" in llm_start["tool_names"]
    assert all("time" not in message for event in llm_starts for message in event["messages"])
    llm_ends = [event for event in agent.runtime_events if event["event_type"] == "llm_call_end"]
    tool_call_end = llm_ends[0]
    final_end = llm_ends[1]
    assert tool_call_end["assistant_content"] is None
    assert tool_call_end["assistant_content_is_empty"] is True
    assert tool_call_end["rationale"] is None
    assert tool_call_end["rationale_source"] == "empty_assistant_content"
    assert tool_call_end["tool_calls"][0]["function"]["name"] == "FarmWorldApp__get_inventory"
    assert final_end["assistant_content"] == "done"
    assert final_end["assistant_content_is_empty"] is False
    assert final_end["rationale"] == "done"
    assert final_end["rationale_source"] == "assistant_content"


def test_agent_runtime_event_sink_receives_live_events() -> None:
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    agent = build_controller_agent(
        "farm_baseline_react",
        llm=_ScriptedLLM([_Message(content="done", tool_calls=None)]),
        toolsets=scenario.apps,
    )
    live_events = []
    agent.runtime_event_sink = live_events.append

    Engine(agent, scenario).run_scenario_agent(
        max_tool_calls=2,
        timeout_seconds=30,
        setup_scenario=False,
    )

    assert [event["event_type"] for event in live_events] == [
        event["event_type"] for event in agent.runtime_events
    ]
    assert live_events[-1]["event_type"] == "agent_run_end"


def test_iclr_runner_summarizes_live_progress(tmp_path: Path) -> None:
    from scripts.iclr_validation_runner import _runtime_progress_snapshot

    progress_path = tmp_path / "scenario.progress.jsonl"
    rows = [
        {"record_type": "agent_run_start", "wall_timestamp": "start"},
        {
            "record_type": "llm_call_end",
            "wall_timestamp": "llm",
            "tokens": {"prompt_tokens": 120, "completion_tokens": 8},
        },
        {
            "record_type": "tool_call_end",
            "wall_timestamp": "tool",
            "tool_name": "WeatherApp__get_current_weather",
        },
        {
            "record_type": "tool_call_error",
            "wall_timestamp": "error",
            "tool_name": "TractorApp__harvest",
        },
    ]
    progress_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    snapshot = _runtime_progress_snapshot(progress_path)

    assert snapshot["records"] == 4
    assert snapshot["llm_calls"] == 1
    assert snapshot["tool_calls"] == 1
    assert snapshot["tool_errors"] == 1
    assert snapshot["prompt_tokens"] == 120
    assert snapshot["completion_tokens"] == 8
    assert snapshot["last_type"] == "tool_call_error"
    assert snapshot["last_tool"] == "TractorApp__harvest"


def test_live_progress_omits_full_message_history(tmp_path: Path) -> None:
    from fairy.cli import _append_live_progress

    progress_path = tmp_path / "scenario.progress.jsonl"
    _append_live_progress(
        progress_path,
        {
            "event_index": 3,
            "event_type": "llm_call_start",
            "messages": [{"role": "user", "content": "large context"}],
            "message_count": 1,
        },
    )

    row = json.loads(progress_path.read_text(encoding="utf-8"))
    assert row["record_index"] == 3
    assert row["record_type"] == "llm_call_start"
    assert row["message_count"] == 1
    assert "messages" not in row


def test_iclr_runner_progress_poll_preserves_process_wait(
    tmp_path: Path, capsys
) -> None:
    from scripts.iclr_validation_runner import _wait_for_cell_process

    progress_path = tmp_path / "scenario.progress.jsonl"
    progress_path.write_text(
        json.dumps({"record_type": "agent_run_start"}) + "\n",
        encoding="utf-8",
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(0.12)"],
    )

    return_code, timed_out, force_killed = _wait_for_cell_process(
        proc,
        timeout_s=1,
        timeout_grace_s=0.1,
        stderr_h=io.StringIO(),
        cmd=[sys.executable, "-c", "sleep"],
        progress_path=progress_path,
        progress_label="test-cell",
        progress_interval_s=0.03,
    )

    assert return_code == 0
    assert timed_out is False
    assert force_killed is False
    assert "[progress] test-cell" in capsys.readouterr().out


def test_iclr_runner_checkpoints_results_csv(tmp_path: Path) -> None:
    from scripts.iclr_validation_runner import _write_results_csv

    csv_path = tmp_path / "results.csv"
    _write_results_csv(csv_path, [{"scenario": "one", "return_code": 0}])
    _write_results_csv(
        csv_path,
        [
            {"scenario": "one", "return_code": 0},
            {"scenario": "two", "return_code": -2, "timed_out": True},
        ],
    )

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert [row["scenario"] for row in rows] == ["one", "two"]
    assert rows[1]["timed_out"] == "True"
    assert not csv_path.with_suffix(".csv.tmp").exists()


def test_farm_agent_hides_user_message_injection_tool_but_replay_keeps_it() -> None:
    scenario_cls = get_scenario_class("scenario_full_season_hb_wetjune_short_spray_window")
    scenario = scenario_cls()
    scenario.setup()

    _, _, replay_tools_map = __import__(
        "fairy.agents.agent.toolset_builder",
        fromlist=["build_toolset"],
    ).build_toolset(list(scenario.apps or []))
    agent = build_controller_agent(
        "farm_baseline_react",
        llm=_ScriptedLLM([_Message(content="done", tool_calls=None)]),
        toolsets=scenario.apps,
    )

    assert "AgentUserInterface__send_message_to_agent" in replay_tools_map
    assert "AgentUserInterface__send_message_to_agent" not in agent.tools_map
    assert "AgentUserInterface__send_message_to_user" in agent.tools_map


def test_farm_agent_key_tool_descriptions_are_restored() -> None:
    scenario = ScenarioFarmWorldFieldPrepPhysicsActionTick()
    scenario.setup()
    agent = build_controller_agent(
        "farm_baseline_react",
        llm=_ScriptedLLM([_Message(content="done", tool_calls=None)]),
        toolsets=scenario.apps,
    )
    descriptions = {
        schema["function"]["name"]: schema["function"]["description"]
        for schema in agent.tool_schemas
    }

    expected_phrases = {
        "AgentUserInterface__send_message_to_user": "Send a message to the user",
        "SystemApp__advance_time": "Advance the simulation clock",
        "SystemApp__get_current_time": "Get the current time",
        "SystemApp__wait_for_notification": "Wait until the next notification",
    }
    for tool_name, phrase in expected_phrases.items():
        assert phrase in descriptions[tool_name]


def test_engine_appends_scenario_additional_system_prompt_for_agent_run() -> None:
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.additional_system_prompt = "SCENARIO-SPECIFIC-SYSTEM-HINT"
    scenario.setup()
    agent = build_controller_agent(
        "farm_baseline_react",
        llm=_ScriptedLLM([_Message(content="done", tool_calls=None)]),
        toolsets=scenario.apps,
    )

    Engine(agent, scenario).run_scenario_agent(
        max_tool_calls=2,
        timeout_seconds=30,
        setup_scenario=False,
    )

    llm_start = next(event for event in agent.runtime_events if event["event_type"] == "llm_call_start")
    assert "SCENARIO-SPECIFIC-SYSTEM-HINT" in llm_start["messages"][0]["content"]


def test_l3_agent_run_uses_event_briefing_as_controller_task() -> None:
    scenario_cls = get_scenario_class("scenario_full_season_hb_wetjune_short_spray_window")
    scenario = scenario_cls(detailed_briefing="kwoo")
    scenario.setup()
    assert scenario.scenario_input == ""

    agent = build_controller_agent(
        "farm_rewoo_modular",
        llm=_ScriptedLLM([_Message(content="done", tool_calls=None)]),
        toolsets=scenario.apps,
    )
    engine = Engine(agent, scenario)

    engine.run_scenario_agent(max_tool_calls=2, timeout_seconds=30, setup_scenario=False)

    task_source = next(
        event for event in agent.runtime_events if event["event_type"] == "agent_task_source"
    )
    assert task_source["source"] == "event_briefing"
    assert "湿六月" in task_source["content_preview"]

    llm_start = next(event for event in agent.runtime_events if event["event_type"] == "llm_call_start")
    assert "Today's date in 'YYYY-MM-DD HH' format is" in llm_start["messages"][0]["content"]
    user_message = next(message for message in llm_start["messages"] if message["role"] == "user")
    assert "湿六月" in user_message["content"]
    assert "Kwoo context" in user_message["content"]
    assert "ReWOO plan-work-solve" in user_message["content"]

    controller_context = next(
        event for event in agent.runtime_events if event["event_type"] == "controller_context"
    )
    assert "ReWOO plan-work-solve" in controller_context["content_preview"]
    assert "ReWOO plan fallback" not in controller_context["content_preview"]
    system_messages = [message["content"] for message in llm_start["messages"] if message["role"] == "system"]
    assert not any("ReWOO plan-work-solve" in content for content in system_messages)
    assert agent.telemetry["planned_steps"] > 0
    assert agent.telemetry["executed_steps"] == 1
    assert agent.telemetry["plan_parse_failures"] == 0


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
    assert any(
        event["event_type"] == "agent_run_end" and event["status"] == "stopped"
        for event in limited_agent.runtime_events
    )
    assert not any(
        event["event_type"] == "agent_run_error"
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

    parse_engine.run_scenario_agent(
        max_tool_calls=5,
        timeout_seconds=30,
        setup_scenario=False,
    )
    assert any(
        event["event_type"] == "tool_args_parse_error"
        for event in parse_agent.runtime_events
    )
    assert any(
        event["event_type"] == "tool_error_observation"
        and event["error_stage"] == "tool_args_parse"
        for event in parse_agent.runtime_events
    )
    assert any(
        message.get("role") == "tool"
        and "JSONDecodeError" in str(message.get("content"))
        and "Now retry with valid arguments" in str(message.get("content"))
        for message in parse_agent.messages.messages
        if isinstance(message, dict)
    )
    assert any(
        event["event_type"] == "agent_run_end" and event["status"] == "ok"
        for event in parse_agent.runtime_events
    )
    assert not any(
        event["event_type"] == "agent_run_error"
        for event in parse_agent.runtime_events
    )


def test_agent_runtime_events_capture_llm_call_errors() -> None:
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    agent = build_controller_agent(
        "farm_baseline_react",
        llm=_FailingLLM(RuntimeError("provider rejected number schema")),
        toolsets=scenario.apps,
    )
    engine = Engine(agent, scenario)

    with pytest.raises(RuntimeError, match="provider rejected number schema"):
        engine.run_scenario_agent(
            max_tool_calls=5,
            timeout_seconds=30,
            setup_scenario=False,
        )

    llm_errors = [
        event
        for event in agent.runtime_events
        if event["event_type"] == "llm_call_error"
    ]
    assert llm_errors
    assert llm_errors[0]["status"] == "error"
    assert llm_errors[0]["error_type"] == "RuntimeError"
    assert "provider rejected number schema" in llm_errors[0]["error_message"]
    assert any(
        event["event_type"] == "agent_run_error"
        and event["error_type"] == "RuntimeError"
        for event in agent.runtime_events
    )


def test_agent_runtime_events_capture_llm_call_retry_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAIRY_AGENT_RATE_LIMIT_SLEEP_S", "0")
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    llm = _FlakyLLM(
        RuntimeError("temporary rate limit"),
        _Message(content="done", tool_calls=None),
    )
    agent = build_controller_agent(
        "farm_baseline_react",
        llm=llm,
        toolsets=scenario.apps,
    )
    engine = Engine(agent, scenario)

    engine.run_scenario_agent(
        max_tool_calls=5,
        timeout_seconds=30,
        setup_scenario=False,
    )

    assert llm.calls == 2
    assert any(
        event["event_type"] == "llm_call_error"
        and "temporary rate limit" in event["error_message"]
        for event in agent.runtime_events
    )
    assert any(
        event["event_type"] == "llm_call_retry"
        and event["status"] == "retrying"
        and event["sleep_seconds"] == 0
        for event in agent.runtime_events
    )
    assert any(
        event["event_type"] == "agent_run_end" and event["status"] == "ok"
        for event in agent.runtime_events
    )
    assert not any(
        event["event_type"] == "agent_run_error"
        for event in agent.runtime_events
    )


def test_agent_llm_retry_defaults_wait_for_rate_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FAIRY_AGENT_LLM_CALL_RETRIES", raising=False)
    monkeypatch.delenv("FAIRY_AGENT_LLM_RETRY_SLEEP_S", raising=False)
    monkeypatch.delenv("FAIRY_AGENT_RATE_LIMIT_SLEEP_S", raising=False)

    agent = build_controller_agent(
        "farm_baseline_react",
        llm=_ScriptedLLM([_Message(content="done", tool_calls=None)]),
        toolsets=[],
    )

    assert agent.max_llm_call_retries == 5
    assert agent.llm_retry_sleep_seconds == 0
    assert agent.rate_limit_retry_sleep_seconds == 30
    assert agent._llm_retry_sleep_for_error(RuntimeError("error code: 429")) == 30
    assert agent._llm_retry_sleep_for_error(RuntimeError("connection reset")) == 0


def test_agent_runtime_events_capture_tool_call_errors() -> None:
    scenario = ScenarioFarmWorldFieldPrep()
    scenario.setup()
    agent = build_controller_agent(
        "farm_baseline_react",
        llm=_ScriptedLLM(
            [
                _Message(
                    tool_calls=[
                        _ToolCall(
                            "TractorApp__plant_seeds",
                            '{"start_ridge": 0, "end_ridge": 3, "bad_arg": 1}',
                        )
                    ]
                )
            ]
        ),
        toolsets=scenario.apps,
    )
    engine = Engine(agent, scenario)

    engine.run_scenario_agent(
        max_tool_calls=5,
        timeout_seconds=30,
        setup_scenario=False,
    )

    tool_errors = [
        event
        for event in agent.runtime_events
        if event["event_type"] == "tool_call_error"
    ]
    assert tool_errors
    assert tool_errors[0]["status"] == "error"
    assert tool_errors[0]["tool_name"] == "TractorApp__plant_seeds"
    assert tool_errors[0]["tool_args"] == {
        "start_ridge": 0,
        "end_ridge": 3,
        "bad_arg": 1,
    }
    assert tool_errors[0]["error_type"] == "TypeError"
    assert tool_errors[0]["error_message"]
    assert any(
        event["event_type"] == "tool_error_observation"
        and event["error_stage"] == "tool_call"
        for event in agent.runtime_events
    )
    assert any(
        message.get("role") == "tool"
        and "TypeError" in str(message.get("content"))
        and "Now retry with valid arguments" in str(message.get("content"))
        for message in agent.messages.messages
        if isinstance(message, dict)
    )
    assert any(
        event["event_type"] == "agent_run_end" and event["status"] == "ok"
        for event in agent.runtime_events
    )
    assert not any(
        event["event_type"] == "agent_run_error"
        for event in agent.runtime_events
    )


def test_rebatch_discovers_fairy_agent_workflow_bundles_only(tmp_path: Path) -> None:
    from scripts.rebatch_fos_from_traces import _discover_cells

    root = tmp_path / "matrix"
    fairy_cell = root / "farm_baseline_react__scenario_demo__r1"
    old_trace_cell = root / "farm_baseline_react__scenario_old__r1"
    nested_cell = root / "nested" / "farm_baseline_react__scenario_nested__r1"
    fairy_cell.mkdir(parents=True)
    old_trace_cell.mkdir(parents=True)
    nested_cell.mkdir(parents=True)

    (fairy_cell / "scenario_demo.agent_workflow.json").write_text("{}", encoding="utf-8")
    (old_trace_cell / "scenario_old.json").write_text("{}", encoding="utf-8")
    (nested_cell / "scenario_nested.agent_workflow.json").write_text("{}", encoding="utf-8")

    assert _discover_cells(root, recursive=False) == [fairy_cell]
    assert _discover_cells(root, recursive=True) == [fairy_cell, nested_cell]


def test_rebatch_uses_run_report_token_metrics() -> None:
    from scripts.rebatch_fos_from_traces import _llm_usage_from_run_report

    report = {
        "model": "deepseek-chat",
        "metrics": {
            "wall_time_seconds": 12.5,
            "llm_call_count": 2,
            "llm_wall_time_seconds": 10.0,
            "token_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "cached_tokens": 40,
                "total_tokens": 120,
            },
        },
    }

    assert _llm_usage_from_run_report(report) == {
        "model_type_size": "deepseek-chat",
        "runtime_s_per_scenario": "12.50",
        "llm_calls_with_usage": 2,
        "avg_total_tokens_per_agent_call": "60.00",
        "avg_input_tokens_per_agent_call": "50.00",
        "avg_output_tokens_per_agent_call": "10.00",
        "avg_cached_tokens_per_agent_call": "20.00",
        "total_tokens_per_scenario": "120.00",
        "avg_runtime_s_per_agent_call": "5.00",
    }


def test_rebatch_legacy_advance_time_uses_post_call_timestamp_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from fairy.time_manager import TimeManager
    from scripts import rebatch_fos_from_traces as rebatch

    class FarmWorldApp:
        name = "FarmWorldApp"

        def __init__(self, time_manager: TimeManager) -> None:
            self.time_manager = time_manager
            self.physics = SimpleNamespace(
                last_physics_sim_time=None,
                yield_recovery=SimpleNamespace(states={}),
            )

        def register_time_manager(self, time_manager: TimeManager) -> None:
            self.time_manager = time_manager

        def prepare_for_time_advance(self, current_sim_time: float) -> None:
            self.advance_physics_time(current_sim_time)

        def advance_physics_time(self, target_sim_time: float | None = None) -> None:
            target = float(
                self.time_manager.time() if target_sim_time is None else target_sim_time
            )
            previous = self.physics.last_physics_sim_time
            if previous is None or target > previous:
                self.physics.last_physics_sim_time = target

        def get_inventory(self) -> dict[str, float]:
            return {"harvest_grain_kg": 0.0, "warehouse_grain_kg": 0.0}

    time_manager = TimeManager()
    time_manager.reset(100.0)
    farm_world = FarmWorldApp(time_manager)
    system = SystemApp()
    system.register_time_manager(time_manager)
    system.attach_farm_world_app(farm_world)
    scenario = SimpleNamespace(
        scenario_id="scenario_test",
        start_time=100.0,
        apps=[farm_world, system],
    )
    monkeypatch.setattr(
        rebatch,
        "_instantiate_scenario_for_replay",
        lambda *_args, **_kwargs: scenario,
    )
    bundle = {
        "scenario_id": "scenario_test",
        "start_time": 100.0,
        "seed": 0,
        "run_report": {
            "outcome": {
                "inventory": {
                    "harvest_grain_kg": 0.0,
                    "warehouse_grain_kg": 0.0,
                }
            }
        },
        "workflow": {
            "step0": {"name": "step0", "op_type": "USER", "time": 100.0},
            "step1": {
                "name": "step1",
                "op_type": "TOOL",
                "tool_name": "SystemApp__advance_time",
                "tool_args": {"days": 1},
                "time": 86500.0,
                "content": {
                    "status": "ok",
                    "advanced_seconds": 86400,
                    "current_timestamp": 86500.0,
                    "current_datetime": "1970-01-02 00:01:40",
                },
            },
        },
    }

    replayed_scenario, _, info = rebatch._replay_fairy_run_bundle(bundle)

    assert info["legacy_timing_steps"] == 1
    assert info["exact_timing_steps"] == 0
    assert info["outcome_checkpoint_verified"] is True
    assert replayed_scenario.apps[0].physics.last_physics_sim_time == pytest.approx(
        86500.0, abs=0.01
    )
    assert replayed_scenario.apps[0].time_manager.time() == pytest.approx(
        86500.0, abs=0.01
    )

    exact_step = dict(bundle["workflow"]["step1"])
    exact_step.update(time=99999.0, time_before=100.0, time_after=86500.0)
    pre_time, post_time, exact = rebatch._workflow_step_times(
        exact_step, system.advance_time, None
    )
    assert (pre_time, post_time, exact) == (100.0, 86500.0, True)


def test_rebatch_rejects_mutating_tool_return_divergence() -> None:
    from scripts.rebatch_fos_from_traces import (
        ReplayDivergenceError,
        _assert_replay_outcome,
        _assert_replay_result,
    )

    step = {
        "name": "step7",
        "op_type": "TOOL",
        "tool_name": "TractorApp__harvest",
        "content": {"status": "ok", "harvested_ridges": [0, 1, 2, 3]},
    }

    with pytest.raises(ReplayDivergenceError, match="harvested_ridges"):
        _assert_replay_result(
            step,
            {"status": "ok", "harvested_ridges": []},
            None,
            strict_return=True,
        )

    with pytest.raises(ReplayDivergenceError, match="no outcome checkpoint"):
        _assert_replay_outcome(None, {})


def test_run_report_exposes_human_stop_reason_and_wall_time() -> None:
    from fairy.controllers.run_artifacts import build_run_report

    report = build_run_report(
        scenario_id="scenario_demo",
        controller_id="farm_baseline_react",
        provider="deepseek",
        model="deepseek-chat",
        temperature=0.1,
        system_prompt_mode="are",
        run_type="agent",
        stopped_reason="max_tool_calls",
        wall_time_seconds=12.3456789,
        max_tool_calls=3,
        timeout_seconds=30,
        parallel_tool_calls=False,
        max_output_tokens=2048,
        workflow_steps=4,
        tool_call_count=3,
        runtime_metrics=[],
        artifacts={},
    )

    assert report["status"] == "stopped"
    assert report["stopped_reason"] == "max_tool_calls"
    assert report["stop_reason"] == "max_tool_calls"
    assert report["wall_time_seconds"] == 12.345679
    assert report["system_prompt_mode"] == "are"
    assert report["limits"]["parallel_tool_calls"] is False
    assert report["limits"]["max_output_tokens"] == 2048
