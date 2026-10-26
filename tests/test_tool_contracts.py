from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from types import SimpleNamespace
from typing import Annotated, Literal, Optional, TypedDict

import pytest

from fairy.agents.agent.toolset_builder import build_tool_schema, build_toolset
from fairy.apps.app import App
from fairy.scenarios.workflow import Workflow, WorkflowStep
from fairy.tool_execution import (
    TOOL_RESULT_SCHEMA, ToolExecutionError, ToolExecutor, ToolRegistry, ToolResult, WorkflowBundle,
)
from fairy.tool_utils import (
    OperationType, SchemaValidationError, ToolContract, ToolParameter, annotation_schema,
    app_tool, parameters_schema, validate_schema,
)
from fairy.types import EventRegisterer, event_registered
from fairy.utils.type_utils import type_check


class Crop(Enum):
    SOY = "soybean"
    RICE = "rice"


class Reading(TypedDict):
    sensor: str
    value: float


def _typed(
    farm_id: Annotated[str, ToolParameter(description="Target farm", entity_kind="farm")],
    count: Annotated[int, {"minimum": 1, "maximum": 4}],
    crop: Crop,
    mode: Literal["surface", "root"],
    readings: list[Reading],
    options: dict[str, bool],
    depth: Annotated[float, ToolParameter(unit="cm", exclusive_minimum=0)] = 4.0,
    note: Optional[str] = None,
) -> dict:
    """Exercise typed parameters.

    Args:
        count: Inclusive number of target ridges.
        mode: Probe depth selection.
    """
    return {}


def test_complete_type_metadata_defaults_are_advertised_and_enforced():
    schema = parameters_schema(_typed)
    properties = schema["properties"]
    assert properties["farm_id"]["description"] == "Target farm"
    assert properties["farm_id"]["x-entity-kind"] == "farm"
    assert properties["count"] == {"type": "integer", "minimum": 1, "maximum": 4,
                                    "description": "Inclusive number of target ridges."}
    assert properties["crop"]["enum"] == ["soybean", "rice"]
    assert properties["readings"]["items"]["properties"]["value"]["type"] == "number"
    assert properties["options"]["additionalProperties"] == {"type": "boolean"}
    assert properties["depth"]["default"] == 4.0
    assert properties["depth"]["x-unit"] == "cm"
    assert properties["note"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    values = {"farm_id": "north", "count": 2, "crop": "rice", "mode": "root",
              "readings": [{"sensor": "r1", "value": 0.3}], "options": {"active": True}}
    normalized = validate_schema(schema, values, apply_defaults=True)
    assert normalized["depth"] == 4.0 and normalized["note"] is None
    assert "depth" not in values
    for field, value in [("count", True), ("count", 5), ("depth", 0), ("depth", float("nan")),
                         ("crop", "maize"), ("mode", "other"), ("options", {"active": 1}),
                         ("readings", [{"sensor": "r1", "value": "0.3"}])]:
        with pytest.raises(SchemaValidationError):
            validate_schema(schema, {**values, field: value}, apply_defaults=True)


def test_plain_callable_and_app_use_same_schema_compiler():
    assert build_tool_schema(_typed)["function"]["parameters"] == parameters_schema(_typed)

    class Example(App):
        @app_tool(parameters={"depth": ToolParameter(unit="cm", minimum=1)},
                  metadata={"scope": "farm"})
        def inspect(self, farm_id: str, depth: float = 5.0) -> dict:
            return {"farm_id": farm_id, "depth": depth}

    app = Example()
    tools, schemas, callables = build_toolset([app])
    assert schemas[0]["function"]["parameters"]["properties"]["depth"] == {
        "type": "number", "x-unit": "cm", "minimum": 1, "default": 5.0}
    assert tools[0].metadata["scope"] == "farm"
    # Enhancing metadata does not wrap legacy calls into a new result format.
    assert callables["Example__inspect"](farm_id="north") == {"farm_id": "north", "depth": 5.0}


def test_unsupported_types_and_bad_defaults_fail_registration():
    with pytest.raises(TypeError, match="Unsupported"):
        annotation_schema(complex)
    with pytest.raises(TypeError, match="string keys"):
        annotation_schema(dict[int, float])

    def invalid(depth: Annotated[float, {"minimum": 1}] = 0.0):
        pass

    with pytest.raises(SchemaValidationError):
        parameters_schema(invalid)
    with pytest.raises(ValueError, match="Unsupported tool schema"):
        ToolContract("Test__run", "test", {"type": "object", "properties": {},
                                            "additionalProperties": False, "not": {}})


class Clock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def add_offset(self, seconds):
        self.now += seconds


class SharedService(App):
    def __init__(self):
        super().__init__(name="Shared")
        self.clock = Clock()
        self.calls = []
        self.allow = True
        self.registry = ToolRegistry()
        contract = ToolContract.from_callable(
            type(self).apply, name="Shared__apply", operation_type=OperationType.WRITE,
            routing_parameters=("farm_id", "asset_id"),
            parameter_metadata={"farm_id": {"enum": ["north", "south"]},
                                "asset_id": {"enum": ["pump1"]},
                                "liters": {"minimum": 0.1, "unit": "L"}},
        )
        self.registry.register(contract, self._apply)
        self.registry.freeze({"farms": ["north", "south"], "assets": ["pump1"]},
                             scenario_config_fingerprint="initial-state")
        self.executor = ToolExecutor(self.registry, self._resolve, clock=self.clock)

    def _resolve(self, contract, arguments):
        if not self.allow:
            raise ToolExecutionError("ASSET_BUSY", "Pump is busy", field="asset_id")
        return SimpleNamespace(farm_id=arguments["farm_id"], asset_id=arguments["asset_id"],
                               clock=self.clock, recorder=None)

    def _apply(self, context, liters):
        self.calls.append((context.farm_id, context.asset_id, liters))
        self.clock.add_offset(5)
        return {"applied_liters": liters}

    def get_tools(self):
        tools = super().get_tools()
        for tool in tools:
            tool.parameters_schema = self.registry.contract(f"{self.name}__{tool.name}").parameters_schema
        return tools

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def apply(self, farm_id: str, asset_id: str, liters: float = 2.0) -> dict:
        """Apply water using a shared device with explicit target identity."""
        return self.executor.execute("Shared__apply", {"farm_id": farm_id, "asset_id": asset_id, "liters": liters})


def test_registry_freezes_detached_contracts_and_manifest():
    first, clone = SharedService(), SharedService()
    assert first.registry.catalog_version == clone.registry.catalog_version
    schema = first.registry.contract("Shared__apply").parameters_schema
    schema["properties"]["farm_id"]["enum"].append("wrong")
    assert "wrong" not in first.registry.contract("Shared__apply").parameters_schema["properties"]["farm_id"]["enum"]
    with pytest.raises(RuntimeError, match="after"):
        first.registry.register(first.registry.contract("Shared__apply"), first._apply)
    with pytest.raises(RuntimeError, match="refreeze"):
        first.registry.freeze({"farms": ["changed"]})


@pytest.mark.parametrize("arguments", [
    {"farm_id": "missing", "asset_id": "pump1"},
    {"farm_id": "north", "asset_id": "missing"},
    {"farm_id": "north", "asset_id": "pump1", "liters": True},
    {"farm_id": "north", "asset_id": "pump1", "liters": float("inf")},
    {"farm_id": "north", "asset_id": "pump1", "unexpected": 1},
    {"asset_id": "pump1"},
])
def test_invalid_call_rejected_before_domain_or_clock(arguments):
    app = SharedService()
    result = app.executor.execute("Shared__apply", arguments)
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_ARGUMENT"
    assert result["error"]["partial_effects"] is False
    assert app.calls == [] and app.clock.now == 1000


def test_domain_rejection_and_unknown_failure_have_different_effect_claims():
    app = SharedService()
    app.allow = False
    rejected = app.apply("north", "pump1")
    assert rejected["error"]["code"] == "ASSET_BUSY"
    assert rejected["error"]["partial_effects"] is False
    assert app.calls == []

    registry = ToolRegistry()
    contract = ToolContract("Broken__apply", "broken", {"type": "object", "properties": {}, "additionalProperties": False})
    changes = []
    def broken(context):
        changes.append("changed")
        raise RuntimeError("after effect")
    registry.register(contract, broken)
    registry.freeze({})
    result = ToolExecutor(registry, lambda contract, arguments: None).execute("Broken__apply", {})
    assert changes == ["changed"]
    assert result["error"]["stage"] == "execution"
    assert result["error"]["partial_effects"] == "unknown"


def test_capture_and_all_public_call_paths_execute_once():
    app = SharedService()
    _, _, tools_map = build_toolset([app])
    # Agent callable and live Oracle call the public method.
    assert tools_map["Shared__apply"](farm_id="north", asset_id="pump1")["ok"]
    assert app.apply("south", "pump1", 3.0)["ok"]
    with EventRegisterer.capture_mode() as events:
        event = app.apply("north", "pump1", 4.0)
        assert len(app.calls) == 2
        # CapturedEvent executes the delegating body, not the capture wrapper.
        assert event.execute()["ok"]
        assert events == [event]
    workflow = Workflow()
    workflow.add_node(WorkflowStep(tool_name="Shared__apply", tool_args={"farm_id": "south", "asset_id": "pump1"}))
    bundle = WorkflowBundle(workflow, app.registry.manifest)
    bundle.validate(app.registry)
    for step in workflow.dag.values():
        assert tools_map[step.tool_name](**step.tool_args)["ok"]
    assert len(app.calls) == len(app.executor.history) == 4
    assert app.clock.now == 1020


def test_capture_defers_dynamic_check_until_execution():
    app = SharedService()
    app.allow = False
    with EventRegisterer.capture_mode() as events:
        event = app.apply("north", "pump1")
    assert len(events) == 1 and app.executor.history == []
    result = event.execute()
    assert result["error"]["code"] == "ASSET_BUSY"
    assert app.calls == []


def test_actual_agent_receives_contract_schema_and_calls_same_gate():
    from fairy.agents.agent.agent import Agent
    app = SharedService()
    agent = Agent("contract-test", SimpleNamespace(provider="openai"), toolsets=[app])
    agent.set_time_manager(app.clock)
    assert agent.tool_schemas[0]["function"]["parameters"]["properties"]["liters"]["type"] == "number"
    assert agent.tool_schemas[0]["function"]["parameters"]["properties"]["farm_id"]["enum"] == ["north", "south"]
    call = SimpleNamespace(id="call_1", type="function", function=SimpleNamespace(
        name="Shared__apply", arguments=json.dumps({"farm_id": "north", "asset_id": "pump1"})))
    result = agent.call_function(call)
    assert result["ok"] and app.calls == [("north", "pump1", 2.0)]
    assert len(app.executor.history) == 1


def test_workflow_manifest_roundtrip_and_preflight_rejects_all_before_execution(tmp_path):
    app = SharedService()
    workflow = Workflow()
    workflow.add_node(WorkflowStep(name="good", tool_name="Shared__apply", tool_args={"farm_id": "north", "asset_id": "pump1"}))
    bundle = WorkflowBundle(workflow, app.registry.manifest)
    path = tmp_path / "oracle.json"
    bundle.save(path)
    assert (tmp_path / "oracle.manifest.json").is_file()
    restored = WorkflowBundle.load(path)
    restored.validate(app.registry)
    bad = deepcopy(restored.manifest)
    bad["catalog_version"] = "different"
    with pytest.raises(ValueError, match="catalog_version"):
        WorkflowBundle(workflow, bad).validate(app.registry)
    workflow.add_node(WorkflowStep(name="invalid", tool_name="Shared__apply", tool_args={"farm_id": "absent", "asset_id": "pump1"}))
    with pytest.raises(ToolExecutionError, match="one of"):
        WorkflowBundle(workflow, app.registry.manifest).validate(app.registry)
    assert app.calls == [] and app.clock.now == 1000
    path.write_text("{}")
    with pytest.raises(ValueError, match="fingerprint"):
        WorkflowBundle.load(path)


def test_missing_sidecar_unknown_tool_and_forward_dependencies_rejected(tmp_path):
    path = tmp_path / "missing.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="Missing"):
        WorkflowBundle.load(path)
    app = SharedService()
    workflow = Workflow()
    workflow.add_node(WorkflowStep(tool_name="Missing__action", tool_args={}))
    with pytest.raises(ValueError, match="Unknown"):
        WorkflowBundle(workflow, app.registry.manifest).validate(app.registry)
    workflow.dag["step0"].tool_name = None
    workflow.dag["step0"].depends_on = ["step1"]
    with pytest.raises(ValueError, match="dependencies"):
        WorkflowBundle(workflow, app.registry.manifest).validate(app.registry)


def test_handler_registration_compares_only_business_payload():
    app = SharedService()
    contract = app.registry.contract("Shared__apply")
    with pytest.raises(ValueError, match="payload"):
        ToolRegistry().register(contract, lambda context, farm_id, asset_id, liters: None)
    with pytest.raises(ValueError, match="private"):
        ToolRegistry().register(contract, app.apply)
    with pytest.raises(ValueError, match="Duplicate"):
        registry = ToolRegistry()
        registry.register(contract, app._apply)
        registry.register(contract, app._apply)


def test_response_compatibility_and_result_validation():
    app = SharedService()
    assert app.executor.execute("Shared__apply", {"farm_id": "north", "asset_id": "pump1"},
                                response_format="legacy") == {"applied_liters": 2.0}
    registry = ToolRegistry()
    contract = ToolContract("Bad__result", "bad result", {"type": "object", "properties": {}, "additionalProperties": False},
                            result_schema={"type": "integer"})
    registry.register(contract, lambda context: "wrong")
    registry.freeze({})
    result = ToolExecutor(registry, lambda contract, arguments: None).execute("Bad__result", {})
    assert result["error"]["stage"] == "result"
    assert result["error"]["partial_effects"] == "unknown"
    assert isinstance(result, ToolResult)


def test_envelope_contract_and_recording_failure_keep_effect_claim_explicit():
    app = SharedService()
    contract = app.registry.contract("Shared__apply")
    contract = ToolContract(contract.name, contract.description, contract.parameters_schema,
                            routing_parameters=contract.routing_parameters,
                            response_format="envelope", result_schema=TOOL_RESULT_SCHEMA)
    registry = ToolRegistry()
    registry.register(contract, app._apply)
    registry.freeze({})
    receipts = []
    executor = ToolExecutor(registry, app._resolve, clock=app.clock, recorder=receipts.append)
    assert executor.execute("Shared__apply", {"farm_id": "north", "asset_id": "pump1"})["ok"]
    assert receipts[0]["data"] == {"applied_liters": 2.0}

    def broken_recorder(result):
        raise RuntimeError("disk failed")
    executor.recorder = broken_recorder
    result = executor.execute("Shared__apply", {"farm_id": "north", "asset_id": "pump1"})
    assert not result.ok and result.error["stage"] == "recording"
    assert result.error["partial_effects"] == "unknown"
    assert result.data == {"applied_liters": 2.0} and len(app.calls) == 2


class _Runtime:
    def __init__(self, app):
        self.app = app
        self.registry = app.registry

    def bind_clock(self, clock):
        self.app.clock = clock
        self.app.executor.clock = clock

    def before_advance(self, timestamp):
        pass

    def advance_to(self, timestamp):
        pass


class _Scenario:
    start_time = 1000.0
    time_increment_in_seconds = 1
    scenario_id = "tool_contract_toy"

    def __init__(self, *, captured=False):
        self.apps = []
        self.workflow = Workflow()
        self.captured = captured

    def setup(self):
        if self.apps:
            return
        self.app = SharedService()
        self.apps = [self.app]
        self.runtime_participants = [_Runtime(self.app)]
        if self.captured:
            self.events_manifest = self.app.registry.manifest
            with EventRegisterer.capture_mode() as events:
                self.app.apply("north", "pump1").with_id("apply").oracle()
            self.events = events

    def oracle_solution(self, run_oracle=False):
        if self.captured:
            raise NotImplementedError
        self.workflow = Workflow()
        result = self.app.apply("north", "pump1") if run_oracle else None
        self.workflow.add_node(WorkflowStep(name="apply", tool_name="Shared__apply",
                                            tool_args={"farm_id": "north", "asset_id": "pump1"}, content=result))


def test_engine_preserves_source_manifest_and_prechecks_entire_replay():
    from fairy.controllers.engine import Engine
    source = Engine(None, _Scenario())
    workflow = source.build_oracle_workflow(run_oracle=False)
    assert workflow.manifest == source.run_manifest
    assert source.scenario.app.calls == []
    workflow.add_node(WorkflowStep(name="bad", tool_name="Shared__apply", tool_args={"farm_id": "absent", "asset_id": "pump1"}))
    target = Engine(None, _Scenario())
    with pytest.raises(ToolExecutionError, match="one of"):
        target.replay_workflow(workflow)
    assert target.scenario.app.calls == []

    fresh = source.build_oracle_workflow(run_oracle=False)
    replayed = target.replay_workflow(WorkflowBundle(fresh, fresh.manifest))
    assert len(replayed) == 1 and len(target.scenario.app.calls) == 1
    assert replayed.manifest == source.run_manifest
    unversioned = Workflow()
    unversioned.add_node(next(iter(fresh.dag.values())))
    other = Engine(None, _Scenario())
    with pytest.raises(ValueError, match="source manifest"):
        other.replay_workflow(unversioned)
    assert other.scenario.app.calls == []


def test_engine_captured_graph_requires_its_own_manifest_before_execution():
    from fairy.controllers.engine import Engine
    source = Engine(None, _Scenario(captured=True))
    workflow = source.run_scenario_oracle(run_oracle=True)
    assert len(workflow) == 1 and len(source.scenario.app.calls) == 1
    other = Engine(None, _Scenario(captured=True))
    other.scenario.setup()
    other.scenario.events_manifest = {**other.scenario.events_manifest, "catalog_version": "wrong"}
    with pytest.raises(ValueError, match="catalog_version"):
        other.run_scenario_oracle(run_oracle=True)
    assert other.scenario.app.calls == []


def test_cli_writes_and_requires_shared_workflow_sidecar(tmp_path, monkeypatch, capsys):
    from fairy import cli
    instances = []

    class Scenario(_Scenario):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            instances.append(self)

    monkeypatch.setattr(cli, "get_scenario_class", lambda name: Scenario)
    monkeypatch.setattr(cli, "_cleanup_repo_side_exports", lambda: None)
    monkeypatch.setattr("sys.argv", ["fairy", "-s", "toy", "--build-oracle", "--output-dir", str(tmp_path)])
    cli.main()
    oracle = tmp_path / "toy.oracle.json"
    sidecar = tmp_path / "toy.oracle.manifest.json"
    assert oracle.is_file() and sidecar.is_file()
    assert instances[-1].app.calls == []
    report = json.loads((tmp_path / "toy.run_report.json").read_text())
    assert report["tool_manifest"]["catalog_version"]
    monkeypatch.setattr("sys.argv", ["fairy", "-s", "toy", "--replay", "--evaluate",
                                     "--workflow", str(oracle), "--output-dir", str(tmp_path / "replayed")])
    cli.main()
    assert len(instances[-1].app.calls) == 1
    sidecar.unlink()
    monkeypatch.setattr("sys.argv", ["fairy", "-s", "toy", "--replay", "--workflow", str(oracle),
                                     "--output-dir", str(tmp_path / "missing")])
    with pytest.raises(ValueError, match="source manifest"):
        cli.main()
    assert instances[-1].app.calls == []
    capsys.readouterr()


def test_static_association_hook_is_shared_by_preflight_and_execution():
    app = SharedService()
    seen = []

    def check(contract, arguments):
        seen.append(arguments.copy())
        assert arguments["liters"] == 2.0
        if arguments["farm_id"] == "south":
            raise ToolExecutionError("ASSET_NOT_ASSIGNED", "pump1 cannot serve south")
        arguments["liters"] = 999  # Validation cannot modify the normalized call.

    registry = ToolRegistry(static_validator=check)
    registry.register(app.registry.contract("Shared__apply"), app._apply)
    registry.freeze({})
    workflow = Workflow()
    for farm in ("north", "south"):
        workflow.add_node(WorkflowStep(tool_name="Shared__apply", tool_args={"farm_id": farm, "asset_id": "pump1"}))
    with pytest.raises(ToolExecutionError, match="cannot serve"):
        WorkflowBundle(workflow, registry.manifest).validate(registry)
    assert app.calls == []
    executor = ToolExecutor(registry, app._resolve, clock=app.clock)
    assert executor.execute("Shared__apply", {"farm_id": "north", "asset_id": "pump1"}).ok
    rejected = executor.execute("Shared__apply", {"farm_id": "south", "asset_id": "pump1"})
    assert rejected.error["code"] == "ASSET_NOT_ASSIGNED"
    assert app.calls == [("north", "pump1", 2.0)]
    with pytest.raises(RuntimeError, match="after freezing"):
        registry.static_validator = lambda contract, arguments: None


class LegacyService(App):
    def __init__(self):
        super().__init__("Legacy")
        self.clock = Clock()
        self.register_time_manager(self.clock)
        self.calls = []

    @event_registered(operation_type=OperationType.READ)
    def internal_notice(self):
        return "notice"

    @type_check
    @app_tool(parameters={"count": ToolParameter(minimum=1, maximum=4)})
    @event_registered(operation_type=OperationType.WRITE)
    def apply(self, count: int, rate: float = 2.0) -> dict:
        self.internal_notice()
        self.calls.append((count, rate))
        self.time_manager.add_offset(5)
        return {"status": "ok", "range": (0, count - 1), "rate": rate}

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def alias(self, count: int) -> dict:
        return self.apply(count)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def reject(self) -> dict:
        return {"error": "Legacy refusal", "specific_detail": "retained"}

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def broken(self) -> dict:
        self.calls.append("before failure")
        raise RuntimeError("legacy original failure")


def test_legacy_gate_keeps_return_shape_and_checks_actual_schema_before_effects():
    app = LegacyService()
    _, schemas, tools = build_toolset([app])
    schema = next(item["function"]["parameters"] for item in schemas if item["function"]["name"] == "Legacy__apply")
    assert schema["properties"]["count"]["minimum"] == 1
    result = tools["Legacy__apply"](count=2)
    assert result == {"status": "ok", "range": (0, 1), "rate": 2.0}
    assert app._legacy_tool_receipts[-1].data["range"] == [0, 1]
    assert app.calls == [(2, 2.0)]
    before = app.clock.time()
    invalid = tools["Legacy__apply"](count=True)
    assert invalid["error_code"] == "INVALID_ARGUMENT"
    assert len(app.calls) == 1 and app.clock.time() == before
    assert app._legacy_tool_receipts[-1].error["partial_effects"] is False


def test_legacy_capture_checks_static_only_and_execution_never_recaptures():
    app = LegacyService()
    with EventRegisterer.capture_mode() as events:
        event = app.alias(2)
        assert len(events) == 1 and app.calls == []
        assert not hasattr(app, "_legacy_tool_receipts")
        assert event.execute()["status"] == "ok"
        assert len(events) == 1  # No alias, internal notice, or backend recapture.
    assert app.calls == [(2, 2.0)] and len(app._legacy_tool_receipts) == 1
    with EventRegisterer.capture_mode() as invalid_events:
        with pytest.raises(ToolExecutionError, match="integer"):
            app.apply(True)
    assert invalid_events == []
    event.kwargs["count"] = "invalid"
    event.args = ()
    assert event.execute()["error_code"] == "INVALID_ARGUMENT"
    assert len(app.calls) == 1


def test_legacy_guard_and_original_exception_semantics_are_preserved():
    app = LegacyService()
    assert app.reject() == {"error": "Legacy refusal", "specific_detail": "retained"}
    assert app._legacy_tool_receipts[-1].ok is False
    with pytest.raises(RuntimeError, match="legacy original failure"):
        app.broken()
    assert app.calls == ["before failure"]
    assert app._legacy_tool_receipts[-1].error["partial_effects"] == "unknown"


def test_legacy_private_unwrap_and_shared_handler_do_not_open_another_gate():
    import inspect
    app = LegacyService()
    raw = inspect.unwrap(type(app).apply)
    assert raw(app, 2)["status"] == "ok"
    assert not hasattr(app, "_legacy_tool_receipts")
    registry = ToolRegistry()
    contract = ToolContract("Shared__legacy_backend", "private legacy reuse",
                            {"type": "object", "properties": {"count": {"type": "integer"}},
                             "required": ["count"], "additionalProperties": False})
    registry.register(contract, lambda context, count: app.apply(count))
    registry.freeze({})
    executor = ToolExecutor(registry, lambda contract, arguments: SimpleNamespace(clock=app.clock))
    with EventRegisterer.capture_mode() as events:
        result = executor.execute("Shared__legacy_backend", {"count": 3})
    assert result.ok and events == []
    assert not hasattr(app, "_legacy_tool_receipts")
    assert len(executor.history) == 1 and app.calls == [(2, 2.0), (3, 2.0)]


def test_legacy_gate_uses_rebound_clock_and_live_agent_same_entry():
    from fairy.agents.agent.agent import Agent
    app = LegacyService()
    app.apply(1)
    next_clock = Clock()
    next_clock.now = 5000
    app.register_time_manager(next_clock)
    agent = Agent("legacy-contract-test", SimpleNamespace(provider="openai"), toolsets=[app])
    agent.set_time_manager(next_clock)
    call = SimpleNamespace(id="call_legacy", type="function", function=SimpleNamespace(
        name="Legacy__apply", arguments='{"count": 2}'))
    result = agent.call_function(call)
    assert result["range"] == (0, 1)
    assert app._legacy_tool_receipts[-1]["time_before"] == 5000
    assert app._legacy_tool_receipts[-1]["time_after"] == 5005
    assert len(app._legacy_tool_receipts) == 2
