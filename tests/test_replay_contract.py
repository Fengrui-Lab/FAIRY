from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fairy.agents.agent.base_agent import BaseAgent
from fairy.apps.app import App
from fairy.controllers.engine import Engine
from fairy.controllers.run_artifacts import build_run_report
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.workflow import Workflow
from fairy.tool_utils import OperationType
from fairy.types import event_registered
from scripts import rebatch_fos_from_traces as rebatch


def _tool_call(call_id: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments="{}"),
    )


class _FakeLLM:
    provider = "deepseek"
    model = "deepseek-chat"
    max_output_tokens = 2048

    def __init__(self, *, parallel_tool_calls: bool, tool_calls: list[SimpleNamespace]):
        self.parallel_tool_calls = parallel_tool_calls
        self._tool_calls = tool_calls

    def chat_completion(self, messages, tools=None):
        message = SimpleNamespace(content=None, tool_calls=list(self._tool_calls))
        usage = SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=4,
            total_tokens=14,
            prompt_tokens_details=SimpleNamespace(cached_tokens=3),
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=usage,
        )


def test_parallel_tool_calls_false_keeps_one_call_in_agent_context() -> None:
    raw_calls = [
        _tool_call("call-1", "App__first"),
        _tool_call("call-2", "App__second"),
        _tool_call("call-3", "App__third"),
    ]
    agent = BaseAgent(
        "test-agent",
        _FakeLLM(parallel_tool_calls=False, tool_calls=raw_calls),
    )

    message = agent.chat_completion([], tools=[])

    assert [call.id for call in message.tool_calls] == ["call-1"]
    assert [call.id for call in agent.messages.messages[-1].tool_calls] == ["call-1"]
    violation = next(
        event
        for event in agent.runtime_events
        if event["event_type"] == "parallel_tool_call_violation"
    )
    assert violation["raw_tool_call_count"] == 3
    assert violation["effective_tool_call_count"] == 1
    assert [call["id"] for call in violation["dropped_tool_calls"]] == [
        "call-2",
        "call-3",
    ]
    llm_end = next(
        event for event in agent.runtime_events if event["event_type"] == "llm_call_end"
    )
    assert llm_end["raw_tool_call_count"] == 3
    assert llm_end["tool_call_count"] == 1
    assert llm_end["dropped_tool_call_count"] == 2


def test_parallel_tool_calls_true_preserves_all_calls() -> None:
    raw_calls = [_tool_call("call-1", "App__first"), _tool_call("call-2", "App__second")]
    agent = BaseAgent(
        "test-agent",
        _FakeLLM(parallel_tool_calls=True, tool_calls=raw_calls),
    )

    message = agent.chat_completion([], tools=[])

    assert [call.id for call in message.tool_calls] == ["call-1", "call-2"]
    assert not any(
        event["event_type"] == "parallel_tool_call_violation"
        for event in agent.runtime_events
    )


class ReplayApp(App):
    def __init__(self) -> None:
        super().__init__()
        self.read_calls = 0
        self.write_calls = 0

    @event_registered(OperationType.READ)
    def observe(self) -> dict[str, int]:
        self.read_calls += 1
        return {"value": 999}

    @event_registered(OperationType.WRITE)
    def mutate(self, amount: int) -> dict[str, int]:
        self.write_calls += 1
        return {"amount": amount}


class ReplayFarmWorldApp(App):
    def __init__(self) -> None:
        super().__init__(name="FarmWorldApp")
        self.advance_calls = 0

    def advance_physics_time(self, _target: float | None = None) -> None:
        self.advance_calls += 1


def _bundle(steps: list[dict]) -> dict:
    return {
        "scenario_id": "test_scenario",
        "start_time": 1000.0,
        "seed": 7,
        "scenario_kwargs": {},
        "init_kwargs": {},
        "workflow": {step["name"]: step for step in steps},
        "run_report": {"outcome": {"test": True}},
    }


def _step(
    name: str,
    tool_name: str,
    *,
    content,
    op_type: str = "TOOL",
    tool_args: dict | None = None,
    error_stage: str | None = None,
) -> dict:
    step = {
        "name": name,
        "op_type": op_type,
        "tool_name": tool_name,
        "tool_args": tool_args or {},
        "content": content,
        "depends_on": [],
        "time": 1000.0,
        "time_before": 1000.0,
        "time_after": 1000.0,
    }
    if error_stage is not None:
        step["error_stage"] = error_stage
    return step


def test_replay_executes_reads_and_writes_and_restores_pre_execution_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = ReplayApp()
    scenario = SimpleNamespace(apps=[app], start_time=1000.0)
    monkeypatch.setattr(rebatch, "_instantiate_scenario_for_replay", lambda *a, **k: scenario)
    steps = [
        _step("step0", "ReplayApp__observe", content={"value": 1}),
        _step(
            "step1",
            "ReplayApp__mutate",
            content={"amount": 4},
            tool_args={"amount": 4},
        ),
        _step(
            "step2",
            "ReplayApp__missing_tool",
            content="KeyError: 'ReplayApp__missing_tool'",
            op_type="TOOL_ERROR",
        ),
    ]

    _, env, info = rebatch._replay_fairy_run_bundle(_bundle(steps))

    assert app.read_calls == 1
    assert app.write_calls == 1
    assert info["n_executed"] == 2
    assert info["n_restored_error_events"] == 1
    assert info["n_skipped"] == 0
    events = env.event_log.list_view()
    assert [event.function_name() for event in events] == [
        "observe",
        "mutate",
        "missing_tool",
    ]
    assert events[0].metadata.return_value == {"value": 1}
    assert events[2].failed()
    assert events[2].metadata.exception == "KeyError: 'ReplayApp__missing_tool'"


def test_replay_rejects_missing_method_on_recorded_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = SimpleNamespace(apps=[ReplayApp()], start_time=1000.0)
    monkeypatch.setattr(rebatch, "_instantiate_scenario_for_replay", lambda *a, **k: scenario)

    with pytest.raises(rebatch.ReplayDivergenceError, match="target method is missing"):
        rebatch._replay_fairy_run_bundle(
            _bundle([_step("step0", "ReplayApp__missing_tool", content="ok")])
        )


def test_replay_does_not_execute_tool_after_argument_parse_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = ReplayApp()
    scenario = SimpleNamespace(apps=[app], start_time=1000.0)
    monkeypatch.setattr(rebatch, "_instantiate_scenario_for_replay", lambda *a, **k: scenario)
    parse_error = _step(
        "step0",
        "ReplayApp__mutate",
        content=("JSONDecodeError: Expecting property name enclosed in double quotes: "
                 "line 1 column 2 (char 1)\nRaw arguments: {\n***"),
        op_type="TOOL_ERROR",
        error_stage="tool_args_parse",
    )
    parse_error.update(error_type="JSONDecodeError", raw_arguments="{",
        error_message="Expecting property name enclosed in double quotes: line 1 column 2 (char 1)")

    _, env, info = rebatch._replay_fairy_run_bundle(_bundle([parse_error]))

    assert app.write_calls == 0
    assert info["n_executed"] == 0
    assert info["n_restored_error_events"] == 1
    assert env.event_log.list_view()[0].failed()


def test_replay_uses_recorded_return_and_pre_call_event_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = ReplayApp()
    scenario = SimpleNamespace(apps=[app], start_time=1000.0)
    monkeypatch.setattr(rebatch, "_instantiate_scenario_for_replay", lambda *a, **k: scenario)
    step = _step("step0", "ReplayApp__observe", content={"value": 1})
    step.update(time_before=1000.0, time_after=2000.0, time=2000.0)

    _, env, info = rebatch._replay_fairy_run_bundle(_bundle([step]))

    event = env.event_log.list_view()[0]
    assert app.read_calls == 1
    assert info["n_executed"] == 1
    assert event.metadata.return_value == {"value": 1}
    assert event.event_time == 1000.0


def test_replay_time_alignment_does_not_tick_physics() -> None:
    farm_world = ReplayFarmWorldApp()
    scenario = SimpleNamespace(apps=[farm_world])
    before = farm_world.time_manager.time()

    rebatch._align_replay_time(scenario, before + 3600.0)

    assert farm_world.time_manager.time() == pytest.approx(before + 3600.0, abs=0.01)
    assert farm_world.advance_calls == 0


def test_replay_wall_time_does_not_advance_farm_physics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import fairy.time_manager as clocks
    from fairy.apps.farm_world import FarmWorldApp

    scenario = rebatch._instantiate_scenario_for_replay(
        "scenario_full_season_hb_base_hn84_std_normal_V2", None, 0
    )
    farm = scenario.get_typed_app(FarmWorldApp)
    farm.get_farm_overview()
    start = scenario.start_time
    assert farm.physics.last_physics_sim_time == start

    # Model computation and I/O may take arbitrary real time. They must not
    # change the recorded simulation timestamp or integrate another day.
    wall = clocks.time.time()
    monkeypatch.setattr(clocks.time, "time", lambda: wall + 86400.0)
    assert all(app.time_manager.time() == start for app in scenario.apps)
    result = farm.advance_physics_time()
    assert result["status"] == "noop"
    assert farm.physics.last_physics_sim_time == start


def test_replay_repeated_same_epoch_reads_do_not_move_physics_backwards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import fairy.time_manager as clocks
    from fairy.apps.farm_world import FarmWorldApp

    wall = clocks.time.time()

    def elapsed_wall_time() -> float:
        nonlocal wall
        wall += 0.01
        return wall

    monkeypatch.setattr(clocks.time, "time", elapsed_wall_time)
    scenario_id = "scenario_full_season_hb_base_hn84_std_normal_V2"
    from fairy.scenarios.registry import registry

    start = registry.get_scenario(scenario_id)().start_time
    steps = [
        _step(f"step{index}", "FarmWorldApp__get_farm_overview", content={})
        for index in range(3)
    ]
    for step in steps:
        step.update(time=start, time_before=start, time_after=start)
    bundle = _bundle(steps)
    bundle.update(scenario_id=scenario_id, start_time=start, seed=0)

    scenario, _, info = rebatch._replay_fairy_run_bundle(bundle)

    farm = scenario.get_typed_app(FarmWorldApp)
    assert info["n_executed"] == 3
    assert info["exec_errors"] == 0
    assert farm.time_manager.time() == start
    assert farm.physics.last_physics_sim_time == start


def test_run_report_persists_replay_initialization_metadata() -> None:
    report = build_run_report(
        scenario_id="scenario_x",
        controller_id="react",
        provider="deepseek",
        model="deepseek-chat",
        temperature=0.1,
        run_type="agent",
        stopped_reason="agent_finished",
        wall_time_seconds=1.0,
        max_tool_calls=10,
        timeout_seconds=20.0,
        parallel_tool_calls=False,
        max_output_tokens=2048,
        workflow_steps=2,
        tool_call_count=1,
        runtime_metrics=[],
        artifacts={},
        start_time=123.0,
        seed=9,
        scenario_kwargs={"detailed_briefing": True},
        init_kwargs={"sensor_count": 2},
    )

    assert report["start_time"] == 123.0
    assert report["seed"] == 9
    assert report["scenario_kwargs"] == {"detailed_briefing": True}
    assert report["init_kwargs"] == {"sensor_count": 2}


def test_engine_replay_forwards_setup_kwargs() -> None:
    class SetupScenario(Scenario):
        def setup(self, *args, **kwargs) -> None:
            self.received_setup_kwargs = kwargs

    scenario = SetupScenario(start_time=123.0)
    engine = Engine(agent=None, scenario=scenario)

    engine.replay_workflow(Workflow(), sensor_count=2)

    assert scenario.received_setup_kwargs == {"sensor_count": 2}


def test_old_bundle_recovers_scenario_kwargs_from_results_csv(tmp_path: Path) -> None:
    cell = tmp_path / "phase5_paper_matrix" / "family__scenario_x__r1"
    cell.mkdir(parents=True)
    (cell / "scenario_x.agent_workflow.json").write_text("{}", encoding="utf-8")
    (cell / "scenario_x.run_report.json").write_text(
        json.dumps({"scenario_id": "scenario_x"}), encoding="utf-8"
    )
    results_path = cell.parent / "results.csv"
    results_path.write_text(
        "cell_dir,scenario_kwargs,init_kwargs\n"
        f'"{cell}","{{""detailed_briefing"": true}}","{{""sensor_count"": 2}}"\n',
        encoding="utf-8",
    )

    bundle = rebatch._load_fairy_run_bundle(cell)

    assert bundle is not None
    assert bundle["scenario_kwargs"] == {"detailed_briefing": True}
    assert bundle["init_kwargs"] == {"sensor_count": 2}
