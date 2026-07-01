from __future__ import annotations

import importlib
import json
import pkgutil
import subprocess
import pytest
from pathlib import Path

import fairy
from fairy.agents.agent.agent import AgentRunLimitExceeded
from fairy.agents.llm.base_llm import BaseLLM
from fairy.apps.farm_world import FarmWorldApp, WeatherApp
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
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
)
from fairy.controllers.app_agent import (
    AppAgent,
    apply_a2a_to_apps,
    collect_a2a_traces,
    resolve_a2a_agent_name_for_app,
)
from fairy.controllers.research_strategies import ResearchStrategyCoordinator
from fairy.controllers.skill_library import DynamicSkillLibrary
from fairy.scenarios.farm_world_fullseason.scenario_full_season_baseline_balanced_season import (
    ScenarioFullSeasonBalanced,
)
from fairy.scenarios.farm_world_physics.scenario_field_prep_physics_action_tick import (
    ScenarioFarmWorldFieldPrepPhysicsActionTick,
)
from fairy.scenarios.farm_world_physics.scenario_irrigation_physics_action_tick import (
    ScenarioFarmWorldIrrigationPhysicsActionTick,
)
from fairy.scenarios.farm_world_fullseason_v2.scenario_full_season_hb_base_hn84_std_normal import (
    ScenarioFullSeasonHBBaseHN84StdNormal,
)
from fairy.scenarios.baseline_farm_world.scenario_field_prep import (
    ScenarioFarmWorldFieldPrep,
)
from fairy.scenarios.registry import list_scenarios
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


def test_controller_families_include_react_and_rewoo() -> None:
    families = AgentBuilder().list_agents()
    assert "farm_baseline_react" in families
    assert "farm_rewoo_modular" in families
    assert "farm_tree_search" in families
    assert "farm_critic_refiner" in families
    assert "farm_skill_rag" not in families
    with pytest.raises(ValueError):
        AgentConfigBuilder().build("farm_skill_rag")


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
    assert resolve_a2a_agent_name_for_app(WeatherApp(), policy="typed_experts") == (
        "weather_expert_app_agent"
    )

    _, schemas, tools_map = __import__(
        "fairy.agents.agent.toolset_builder",
        fromlist=["build_toolset"],
    ).build_toolset(result.apps)
    schema_names = {schema["function"]["name"] for schema in schemas}
    assert any(name.endswith("__expert_agent") for name in schema_names)
    assert "WeatherApp__get_current_weather" not in tools_map


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
    assert any(event["event_type"] == "tool_call_end" for event in wrapper.last_runtime_events)


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

    assert traces[0]["wrapper_app_name"] == "WeatherAppExpert"
    assert traces[0]["app_agent"] == "weather_expert_app_agent"
    assert "weather and field-conditions expert" in traces[0]["messages"][0]["content"]
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

    engine = Engine(agent=None, scenario=scenario)
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
    )

    joined = " ".join(cmd)
    assert "--a2a true" in joined
    assert "--a2a-app-prop 0.75" in joined
    assert "--a2a-policy typed_experts" in joined
    assert "--a2a-app-agent weather_expert_app_agent" in joined
    assert "--a2a-model qwen-plus" in joined
    assert "--a2a-provider qwen" in joined
    assert "--a2a-endpoint http://localhost:8000/v1" in joined


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
