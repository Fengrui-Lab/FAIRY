"""Crop operation metadata and the existing executor share one public gate."""
import json
from types import SimpleNamespace

import pytest

from fairy.apps.app import App
from fairy.crops.rules import ScalarRange
from fairy.scenarios.scenario import Scenario
from fairy.time_manager import SimulationTimeManager
from fairy.tool_contracts import OperationContract, ParameterContract
from fairy.tool_utils import ToolArgumentRejection, app_tool
from fairy.types import EventRegisterer, event_registered
from fairy.utils.type_utils import type_check


class ContractProbe(App):
    require_explicit_tool_docs = True
    validate_tool_arguments = True

    def __init__(self):
        super().__init__()
        clock = SimulationTimeManager()
        clock.reset(1000.0)
        self.register_time_manager(clock)
        self.maximum = 5.0
        self.calls = []

    def get_tool_contract(self, method):
        if method != "apply":
            return None
        return OperationContract(
            "Apply an amount to the explicitly selected target.",
            {"target": ParameterContract("Registered target.", choices=("small", "large")),
             "amount": ParameterContract("Amount in model units.", numeric=ScalarRange(0, self.maximum))},
            lambda args: "small target is limited to 2 units"
            if args["target"] == "small" and args["amount"] > 2 else None,
        )

    @type_check
    @app_tool()
    @event_registered()
    def apply(self, target: str, amount: float = 1.0) -> dict:
        """Apply one operation.

        Args:
            target: Selected target.
            amount: Requested amount.
        """
        self.calls.append((target, amount))
        self.time_manager.add_offset(1)
        return {"status": "ok", "target": target, "amount": amount}

    def get_state(self):
        return {"calls": list(self.calls), "maximum": self.maximum}


def public_tool(app):
    return next(tool for tool in app.get_tools() if tool.name == "apply")


def test_operation_constraints_augment_real_type_default_and_target_metadata():
    app = ContractProbe()
    tool = public_tool(app)
    function = tool.to_open_ai()["function"]
    assert function["description"] == app.get_tool_contract("apply").description
    parameters = function["parameters"]
    assert parameters["properties"]["target"]["enum"] == ["small", "large"]
    assert parameters["properties"]["amount"] == {
        "type": "number", "description": "Amount in model units.",
        "default": 1.0, "minimum": 0, "maximum": 5.0,
    }
    assert parameters["required"] == ["target"]
    assert parameters["additionalProperties"] is False


@pytest.mark.parametrize("arguments", [
    {"target": "missing", "amount": 1},
    {"target": "large", "amount": float("nan")},
    {"target": "large", "amount": "1"},
    {"target": "large", "amount": 6},
    {"target": "small", "amount": 3},
])
def test_direct_and_model_tool_preflight_reject_before_any_effect(arguments):
    app = ContractProbe()
    for call in (app.apply, public_tool(app)):
        result = call(**arguments)
        assert isinstance(result, ToolArgumentRejection)
        assert result == {"error": str(result.exception)}
        assert app.calls == []
        assert app.time_manager.time() == 1000.0
    assert public_tool(app)(target="large", amount=3)["status"] == "ok"
    assert app.calls == [("large", 3)]
    assert app.time_manager.time() == 1001.0


def test_captured_operation_rechecks_changed_rules_without_executing_at_build():
    app = ContractProbe()
    with EventRegisterer.capture_mode() as events:
        event = app.apply("large", 3)
    assert len(events) == 1 and app.calls == []
    assert app.time_manager.time() == 1000.0
    app.maximum = 2
    result = event.execute()
    assert isinstance(result, ToolArgumentRejection)
    assert app.calls == [] and app.time_manager.time() == 1000.0


def test_capture_defers_state_dependent_operation_checks_until_execution():
    app = ContractProbe()
    with EventRegisterer.capture_mode() as events:
        event = app.apply("small", 3)
    assert len(events) == 1
    assert app.calls == [] and app.time_manager.time() == 1000.0
    result = event.execute()
    assert isinstance(result, ToolArgumentRejection)
    assert "small target" in result["error"]
    assert app.calls == [] and app.time_manager.time() == 1000.0


def test_typed_operation_refusal_survives_agent_recording_and_fresh_replay():
    from fairy.agents.agent.agent import Agent, RecoverableToolCallError
    from fairy.controllers.engine import Engine

    app = ContractProbe()
    scene = Scenario(start_time=1000.0, apps=[app])
    agent = Agent("offline-contract", SimpleNamespace(provider="openai"), toolsets=scene.apps)
    Engine(agent, scene)

    def call(raw):
        return agent.call_function(SimpleNamespace(
            id=f"call-{agent.tool_call_count}", type="function",
            function=SimpleNamespace(name="ContractProbe__apply", arguments=raw),
        ))

    with pytest.raises(RecoverableToolCallError, match="small target"):
        call('{"target":"small","amount":3}')
    call('{"target":"large","amount":3}')
    fresh = ContractProbe()
    replay = Engine(None, Scenario(start_time=1000.0, apps=[fresh]))
    workflow = replay.replay_workflow(agent.workflow)
    assert fresh.get_state() == app.get_state()
    assert replay.time_manager.time() == agent.time_manager.time() == 1001.0
    assert [step.op_type for step in workflow.dag.values()] == ["TOOL_ERROR", "TOOL"]
    assert [item["status"] for item in replay.run_log] == ["expected_error", "ok"]


@pytest.mark.parametrize("crop", ["soybean", "maize", "rice"])
def test_public_crop_profile_has_the_same_shape_after_workflow_json(crop):
    from fairy.apps.farm_world.crop_profiles import get_crop_profile

    public = get_crop_profile(crop).to_dict()
    assert json.loads(json.dumps(public, allow_nan=False)) == public
