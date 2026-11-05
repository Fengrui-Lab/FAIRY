"""Recorded failures must replay as failures, without hiding divergence."""
from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from fairy.agents.agent.agent import Agent, RecoverableToolCallError
from fairy.apps.app import App
from fairy.controllers.engine import Engine, ReplayDivergenceError
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.workflow import Workflow, WorkflowStep
from fairy.tool_utils import app_tool


class FailureApp(App):
    def __init__(self, behavior="normal"):
        super().__init__()
        self.value = 0
        self.calls = 0
        self.behavior = behavior

    @app_tool()
    def update(self, amount: int = 1) -> int:
        self.calls += 1
        if amount < 0:
            if self.behavior == "succeed":
                return self.value
            if self.behavior == "mutate":
                self.value += 1
            if self.behavior == "advance":
                self.time_manager.add_offset(60)
            if self.behavior == "different_type":
                raise RuntimeError("amount must be nonnegative")
            if self.behavior == "different_message":
                raise ValueError("something else failed")
            raise ValueError("amount must be nonnegative")
        self.value += amount
        self.time_manager.add_offset(5)
        return self.value

    def get_state(self):
        return {"value": self.value}


def _agent(scenario):
    agent = Agent("replay-test", SimpleNamespace(provider="openai"), toolsets=scenario.apps)
    return agent, Engine(agent, scenario)


def _call(agent, name="FailureApp__update", arguments=None):
    return agent.call_function(SimpleNamespace(
        id=f"call-{agent.tool_call_count}",
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments or '{"amount": -1}'),
    ))


def _error_workflow(behavior="normal"):
    scenario = Scenario(start_time=1000, apps=[FailureApp(behavior)])
    agent, _ = _agent(scenario)
    with pytest.raises(RecoverableToolCallError):
        _call(agent)
    _call(agent, arguments='{"amount": 3}')
    return agent.workflow


def test_replay_preserves_recorded_errors_and_continues_after_correction(tmp_path):
    recorded = _error_workflow()
    path = tmp_path / "workflow.json"
    recorded.save_workflow(str(path))
    recorded = Workflow.load_workflow(str(path))
    first = next(iter(recorded.dag.values()))
    assert first.error_type == "ValueError"
    assert first.error_message == "amount must be nonnegative"
    assert json.loads(first.raw_arguments) == {"amount": -1}
    app = FailureApp()
    engine = Engine(None, Scenario(start_time=1000, apps=[app]))

    replayed = engine.replay_workflow(recorded)

    assert app.value == 3
    assert app.calls == 2
    assert engine.time_manager.offset == 5
    assert [s.op_type for s in replayed.dag.values()] == ["TOOL_ERROR", "TOOL"]
    assert replayed.dag["step0"].content == first.content
    assert replayed.dag["step0"].error_stage == "tool_call"
    assert replayed.dag["step0"].error_type == "ValueError"
    assert [entry["status"] for entry in engine.run_log] == ["expected_error", "ok"]


@pytest.mark.parametrize("wrapped", [True, False])
def test_legacy_string_error_observations_remain_replayable(wrapped):
    workflow = _error_workflow()
    error = workflow.dag["step0"]
    workflow.dag["step0"] = replace(
        error,
        error_type=None,
        error_message=None,
        raw_arguments=None,
        error_stage=None,
        content=error.content if wrapped else "ValueError: amount must be nonnegative",
    )
    app = FailureApp()
    replayed = Engine(None, Scenario(start_time=1000, apps=[app])).replay_workflow(workflow)
    assert app.value == 3
    assert replayed.dag["step0"].op_type == "TOOL_ERROR"


@pytest.mark.parametrize("behavior,match", [
    ("succeed", "but the call succeeded"),
    ("different_type", "got RuntimeError"),
    ("different_message", "something else failed"),
    ("advance", "explicit simulation time"),
])
def test_expected_errors_cannot_hide_replay_divergence(behavior, match):
    app = FailureApp(behavior)
    engine = Engine(None, Scenario(start_time=1000, apps=[app]))
    with pytest.raises(ReplayDivergenceError, match=match):
        engine.replay_workflow(_error_workflow())
    assert app.calls == 1  # The recovery operation must never run after divergence.
    assert engine.run_log[-1]["status"] == "error"


def test_exception_in_recorded_success_still_raises():
    workflow = Workflow()
    workflow.add_node(WorkflowStep(op_type="TOOL", tool_name="FailureApp__update",
                                   tool_args={"amount": -1}, content=1))
    engine = Engine(None, Scenario(start_time=1000, apps=[FailureApp()]))
    with pytest.raises(ValueError, match="nonnegative"):
        engine.replay_workflow(workflow)
    assert engine.run_log[-1]["status"] == "error"


@pytest.mark.parametrize("behavior,value,elapsed", [("mutate",4,5), ("advance",3,65)])
def test_recorded_failed_call_preserves_original_partial_effects(behavior,value,elapsed):
    workflow = _error_workflow(behavior)
    app = FailureApp(behavior)
    engine = Engine(None, Scenario(start_time=1000, apps=[app]))
    replayed = engine.replay_workflow(workflow)
    assert app.calls == 2
    assert app.value == value == replayed.dag["step1"].content
    assert engine.time_manager.offset == elapsed
    assert [x["status"] for x in engine.run_log] == ["expected_error","ok"]


class ReceiptApp(App):
    def __init__(self, envelope=False, stock=0, message="Insufficient fertilizer"):
        super().__init__()
        self.envelope, self.stock, self.message = envelope, stock, message
        self.attempts, self.refills = 0, 0

    @app_tool()
    def fertilize(self) -> dict:
        from fairy.tool_execution import ToolExecutionError, ToolResult
        self.attempts += 1
        before = self.time_manager.time()
        self.time_manager.add_offset(2)
        if self.stock == 0:
            if self.envelope:
                return ToolResult(ok=False, tool="ReceiptApp__fertilize",
                    time_before=before, time_after=self.time_manager.time(),
                    error=ToolExecutionError("STOCK_EMPTY",self.message))
            return {"error":self.message,"farm_id":"farm_a"}
        self.stock -= 1
        return {"status":"ok","stock":self.stock}

    @app_tool()
    def refill(self) -> dict:
        self.refills += 1
        self.stock += 1
        return {"stock":self.stock}


def _receipt_trace(envelope):
    app = ReceiptApp(envelope)
    agent,_ = _agent(Scenario(start_time=1000,apps=[app]))
    for method in ["fertilize","refill","fertilize"]:
        _call(agent,f"ReceiptApp__{method}","{}")
    return agent.workflow


@pytest.fixture(params=["cli","rebatch"])
def receipt_replay(request,monkeypatch):
    def run(workflow,app):
        engine = Engine(None,Scenario(start_time=1000,apps=[app]))
        if request.param == "cli":
            result = engine.replay_workflow(workflow)
            assert engine.run_log[0]["status"] == "expected_error"
            return result
        from scripts import rebatch_fos_from_traces as rebatch
        monkeypatch.setattr(rebatch,"_instantiate_scenario_for_replay",lambda *a,**k:engine.scenario)
        _,_,info = rebatch._replay_fairy_run_bundle({"scenario_id":"offline",
            "start_time":1000,"workflow":workflow.to_dict()})
        assert info["n_executed"] == 3 and info["n_skipped"] == 0
        assert info["expected_error_events"] == 1 and info["exec_errors"] == 0
        return workflow
    return run


@pytest.mark.parametrize("envelope",[False,True])
def test_returned_failure_is_reproduced_before_refill_and_retry(receipt_replay,envelope,tmp_path):
    workflow = _receipt_trace(envelope)
    path = tmp_path/"recorded.json"
    workflow.save_workflow(str(path))
    app = ReceiptApp(envelope)
    replayed = receipt_replay(Workflow.load_workflow(str(path)),app)
    assert app.attempts == 2 and app.refills == 1 and app.stock == 0
    assert app.time_manager.time() == 1004
    assert replayed.dag["step0"].content == workflow.dag["step0"].content


@pytest.mark.parametrize("envelope",[False,True])
@pytest.mark.parametrize("change",["success","different_error"])
def test_returned_failure_must_match_record_before_recovery(receipt_replay,envelope,change):
    app = ReceiptApp(envelope,stock=1) if change=="success" else ReceiptApp(envelope,message="Wrong implement")
    with pytest.raises(ReplayDivergenceError,match="recorded failure"):
        receipt_replay(_receipt_trace(envelope),app)
    assert app.attempts == 1 and app.refills == 0


@pytest.mark.parametrize("envelope",[False,True])
def test_new_returned_failure_in_recorded_success_is_divergence(receipt_replay,envelope):
    source = _receipt_trace(envelope).dag["step2"]
    workflow = Workflow()
    workflow.add_node(replace(source,name="step0",time_before=1000,time_after=1002))
    app = ReceiptApp(envelope)
    with pytest.raises(ReplayDivergenceError,match="new failure"):
        receipt_replay(workflow,app)
    assert app.attempts == 1 and app.refills == 0


def test_recorded_partial_write_continues_with_its_actual_effects():
    class PartialApp(App):
        def __init__(self):
            super().__init__(); self.value=0
        @app_tool()
        def work(self):
            self.value+=1; self.time_manager.add_offset(3)
            return {"status":"partial","completed":self.value,"remaining":1}
        @app_tool()
        def inspect(self):
            return {"value":self.value}
    app=PartialApp(); agent,_=_agent(Scenario(start_time=1000,apps=[app]))
    _call(agent,"PartialApp__work","{}");_call(agent,"PartialApp__inspect","{}")
    target=PartialApp(); engine=Engine(None,Scenario(start_time=1000,apps=[target]))
    result=engine.replay_workflow(agent.workflow)
    assert target.value==1 and engine.time_manager.offset==3
    assert result.dag["step1"].content=={"value":1}
    assert engine.run_log[0]["status"]=="expected_error"


@pytest.mark.parametrize("legacy", [False, True])
def test_argument_parse_error_is_reproduced_without_executing_tool(legacy):
    app = FailureApp()
    scenario = Scenario(start_time=1000, apps=[app])
    agent, _ = _agent(scenario)
    with pytest.raises(RecoverableToolCallError):
        _call(agent, arguments="{bad json")
    _call(agent, arguments='{"amount": 3}')
    if legacy:
        error = agent.workflow.dag["step0"]
        agent.workflow.dag["step0"] = replace(
            error, error_type=None, error_message=None, raw_arguments=None, error_stage=None,
        )
    replay_app = FailureApp()
    replayed = Engine(None, Scenario(start_time=1000, apps=[replay_app])).replay_workflow(agent.workflow)
    assert replay_app.calls == 1
    assert replay_app.value == 3
    assert replayed.dag["step0"].op_type == "TOOL_ERROR"


def test_valid_json_cannot_replay_a_recorded_parse_error():
    agent, _ = _agent(Scenario(start_time=1000, apps=[FailureApp()]))
    with pytest.raises(RecoverableToolCallError):
        _call(agent, arguments="{bad json")
    agent.workflow.dag["step0"].raw_arguments = "{}"
    app = FailureApp()
    with pytest.raises(ReplayDivergenceError, match="but the call succeeded"):
        Engine(None, Scenario(start_time=1000, apps=[app])).replay_workflow(agent.workflow)
    assert app.calls == 0


def test_unknown_tool_error_matches_lookup_and_can_be_corrected():
    agent, _ = _agent(Scenario(start_time=1000, apps=[FailureApp()]))
    with pytest.raises(RecoverableToolCallError):
        _call(agent, name="FailureApp__typo")
    _call(agent, arguments='{"amount": 2}')
    app = FailureApp()
    replayed = Engine(None, Scenario(start_time=1000, apps=[app])).replay_workflow(agent.workflow)
    assert app.value == 2
    assert replayed.dag["step0"].error_type == "KeyError"


def test_real_rice_refuel_error_replay_has_identical_final_state():
    pytest.importorskip("pcse")
    from fairy.apps.paddy.world import PaddyWorldApp
    from fairy.scenarios.registry import get_scenario_class

    cls = get_scenario_class("scenario_rice_l1_refuel")
    scenario = cls()
    scenario.setup()
    agent, engine = _agent(scenario)
    world = scenario.get_typed_app(PaddyWorldApp)
    initial = world.get_state()
    with pytest.raises(RecoverableToolCallError):
        _call(agent, "PaddyMachineryApp__refuel", '{"machine_id":"tractor","liters":100}')
    assert world.get_state() == initial
    assert engine.time_manager.offset == 0
    _call(agent, "PaddyMachineryApp__refuel", '{"machine_id":"tractor","liters":10}')
    final = world.get_state()
    # Simulate old, real-agent traces that have no structured error metadata.
    step = agent.workflow.dag["step0"]
    agent.workflow.dag["step0"] = replace(step, error_type=None, error_message=None, raw_arguments=None)
    replay_engine = Engine(None, cls())
    replayed = replay_engine.replay_workflow(agent.workflow)
    assert replay_engine.scenario.get_typed_app(PaddyWorldApp).get_state() == final
    assert [s.op_type for s in replayed.dag.values()] == ["TOOL_ERROR", "TOOL"]
    assert replay_engine.time_manager.offset == engine.time_manager.offset == 300


@pytest.mark.parametrize("raw_arguments", ["null", "[]", '[{"amount": 3}]', '"text"', "42", "true", "false"])
def test_non_object_json_is_rejected_before_execution_and_replays(raw_arguments):
    app = FailureApp()
    agent, original_engine = _agent(Scenario(start_time=1000, apps=[app]))
    with pytest.raises(RecoverableToolCallError, match="must decode to a JSON object"):
        _call(agent, arguments=raw_arguments)
    assert app.calls == 0
    assert app.value == 0
    assert original_engine.time_manager.offset == 0
    recorded_error = agent.workflow.dag["step0"]
    assert recorded_error.op_type == "TOOL_ERROR"
    assert recorded_error.error_stage == "tool_args_parse"
    assert recorded_error.error_type == "TypeError"
    assert recorded_error.error_message == "Tool arguments must decode to a JSON object"
    assert recorded_error.tool_args == {}
    assert recorded_error.raw_arguments == raw_arguments
    assert agent.tool_call_count == 1
    _call(agent, arguments='{"amount": 3}')

    replay_app = FailureApp()
    replay_engine = Engine(None, Scenario(start_time=1000, apps=[replay_app]))
    replayed = replay_engine.replay_workflow(agent.workflow)

    assert replay_app.calls == 1
    assert replay_app.value == app.value == 3
    assert replay_engine.time_manager.offset == original_engine.time_manager.offset == 5
    assert replayed.dag["step0"].op_type == "TOOL_ERROR"
    assert replayed.dag["step0"].error_message == recorded_error.error_message
    assert [entry["status"] for entry in replay_engine.run_log] == ["expected_error", "ok"]


@pytest.mark.parametrize("arguments", [None, [], [1], "text", 42, False])
def test_legacy_non_object_arguments_are_rejected_without_calling_tool(arguments):
    workflow = Workflow()
    workflow.add_node(WorkflowStep(
        op_type="TOOL_ERROR",
        tool_name="FailureApp__update",
        tool_args=arguments,
        content="TypeError: AppTool(class_instance=<FailureApp object at 0x1234>) argument after ** must be a mapping",
        error_stage="tool_call",
        raw_arguments=json.dumps(arguments),
    ))
    workflow.add_node(WorkflowStep(
        op_type="TOOL", tool_name="FailureApp__update", tool_args={"amount": 3}, content=3,
    ))
    app = FailureApp()
    engine = Engine(None, Scenario(start_time=1000, apps=[app]))

    with pytest.raises(ReplayDivergenceError, match="legacy non-object tool arguments"):
        engine.replay_workflow(workflow)

    assert app.calls == 0
    assert app.value == 0
    assert engine.time_manager.offset == 0
    assert engine.run_log[-1]["status"] == "error"


def test_replay_continues_after_partial_robot_inspection():
    from fairy.apps.farm_world import FarmWorldApp, RobotApp, WeatherApp

    farm = FarmWorldApp()
    weather = WeatherApp()
    robot = RobotApp(farm_world_app=farm, weather_app=weather, name="Robot0")
    engine = Engine(None, Scenario(start_time=1000, apps=[farm, weather, robot]))
    workflow = Workflow()
    workflow.add_node(WorkflowStep(
        name="inspect", tool_name="Robot0__inspect_emergence",
        tool_args={"start_ridge": 0, "end_ridge": 63},
    ))
    workflow.add_node(WorkflowStep(
        name="status", tool_name="Robot0__check_status", tool_args={},
        depends_on=["inspect"],
    ))

    replayed = engine.replay_workflow(workflow)

    content = replayed.dag["inspect"].content
    assert content["status"] == "partial"
    assert content["covered_ridges"] == list(range(8))
    assert content["uncovered_ridges"] == list(range(8, 64))
    assert len(content["observations"]) == 8
    assert "status" in replayed.dag
    assert [entry["status"] for entry in engine.run_log] == ["ok", "ok"]


def test_replay_still_rejects_partial_write_with_coverage():
    from fairy.tool_utils import OperationType
    from fairy.types import event_registered
    from fairy.tool_execution import ToolExecutionError

    class PartialWriteApp(App):
        @app_tool()
        @event_registered(operation_type=OperationType.WRITE)
        def apply(self) -> dict:
            return {
                "status": "partial", "covered_ridges": [0],
                "uncovered_ridges": [1], "observations": {"0": {"vwc": 0.3}},
            }

    app = PartialWriteApp()
    engine = Engine(None, Scenario(start_time=1000, apps=[app]))
    workflow = Workflow()
    workflow.add_node(WorkflowStep(
        name="apply", tool_name="PartialWriteApp__apply", tool_args={},
    ))

    with pytest.raises(ToolExecutionError, match="partial"):
        engine.replay_workflow(workflow)
    assert engine.run_log[-1]["status"] == "error"


def test_recorded_partial_drone_survey_replays_coverage_battery_and_time():
    from fairy.apps.farm_world import FarmWorldApp, DroneApp, WeatherApp
    def scene():
        farm,weather=FarmWorldApp(),WeatherApp()
        weather.set_weather("2026-05-12",20,55,2,0,350)
        drone=DroneApp(farm_world_app=farm,weather_app=weather,name="Mavic3M")
        drone._battery_pct=36.0
        return Scenario(start_time=1778544000,apps=[farm,weather,drone]),drone
    source,drone=scene();agent,original=_agent(source)
    _call(agent,"Mavic3M__fly_survey",'{"start_ridge":0,"end_ridge":63}')
    _call(agent,"Mavic3M__check_status","{}")
    recorded=agent.workflow.dag["step0"].content
    assert recorded["status"]=="partial" and recorded["surveyed_ridges"]
    target,replay_drone=scene();engine=Engine(None,target)
    result=engine.replay_workflow(agent.workflow)
    actual=result.dag["step0"].content
    assert actual["surveyed_ridges"]==recorded["surveyed_ridges"]
    assert replay_drone._battery_pct==drone._battery_pct
    assert engine.time_manager.time()==original.time_manager.time()
    assert [x["status"] for x in engine.run_log]==["ok","ok"]
