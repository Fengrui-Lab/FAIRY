"""Acceptance regressions from the external rice agent trials."""
from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

pytest.importorskip("pcse")

from fairy.apps.paddy.world import PaddyWorldApp
from fairy.apps.paddy.operations import PaddyOpsApp
from fairy.controllers.agent_builder import build_controller_agent
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.workflow import Workflow, WorkflowStep


def test_storage_goals_reject_partial_batches_until_every_batch_is_stored():
    cls = get_scenario_class("scenario_rice_l3_equipment_limit")
    complete = Engine(None, cls())
    complete_workflow = complete.run_scenario_oracle(run_oracle=True)
    batch_plots = {batch.batch_id: batch.plot_id
                   for batch in complete.scenario.get_typed_app(PaddyWorldApp).field.grain_batches}
    stored_plots = set()
    skipped_batches = []
    partial_workflow = Workflow()
    previous = None
    for step in complete_workflow.dag.values():
        if step.tool_name == "PaddyOpsApp__store_grain":
            plot_id = batch_plots[step.tool_args["batch_id"]]
            if plot_id in stored_plots:
                skipped_batches.append(step.tool_args["batch_id"])
                continue
            stored_plots.add(plot_id)
        # Reconnect the sequential history when a storage operation is omitted.
        partial_workflow.add_node(replace(step, depends_on=[previous] if previous else []))
        previous = step.name

    scenario = cls()
    engine = Engine(None, scenario)
    workflow = engine.replay_workflow(partial_workflow)
    world = scenario.get_typed_app(PaddyWorldApp)
    assert len(skipped_batches) > 0
    assert all(p.harvested and p.stored_dry_kg > 0 for p in world.field.plots)
    assert sum(b.dry_kg for b in world.field.grain_batches if b.location == "reception") > 0

    # The same complete-season history must satisfy all three storage goal
    # variants; changing the goal does not alter the physically executed history.
    for task in ("season", "harvest_storage", "harvest_batches"):
        scenario.task = task
        result = engine.evaluate(workflow)
        assert result.metadata["audit"]["success"], result.metadata["audit"]
        assert result.metadata["tool_errors"] == 0
        assert not result.metadata["goal_met"], task
        assert not result.success, task

    ops = scenario.get_typed_app(PaddyOpsApp)
    for batch_id in skipped_batches:
        result = ops.store_grain(batch_id)
        step = WorkflowStep(name=f"complete_storage_{batch_id}", content=result, op_type="WRITE",
                            tool_name="PaddyOpsApp__store_grain", tool_args={"batch_id": batch_id},
                            depends_on=[previous] if previous else [])
        workflow.add_node(step)
        previous = step.name

    assert all(b.location == "stored" for b in world.field.grain_batches)
    for task in ("season", "harvest_storage", "harvest_batches"):
        scenario.task = task
        result = engine.evaluate(workflow)
        assert result.metadata["goal_met"], task
        assert result.success, result.metadata


class RefuelRecoveryLLM:
    provider = "openai"
    model = "deterministic-validation-test"
    parallel_tool_calls = False

    def __init__(self):
        self.calls = 0

    def chat_completion(self, messages, tools=None):
        self.calls += 1
        if self.calls <= 2:
            arguments = {"machine_id": "tractor", "liters": 100 if self.calls == 1 else 10}
            call = SimpleNamespace(
                id=f"call{self.calls}", type="function",
                function=SimpleNamespace(name="PaddyMachineryApp__refuel", arguments=json.dumps(arguments)),
            )
            message = SimpleNamespace(role="assistant", content=None, tool_calls=[call])
        else:
            message = SimpleNamespace(role="assistant", content="done", tool_calls=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="tool_calls" if self.calls <= 2 else "stop")],
            usage=None,
        )


def test_real_agent_error_is_counted_even_after_successful_correction():
    scenario = get_scenario_class("scenario_rice_l1_refuel")()
    scenario.setup()
    agent = build_controller_agent("farm_baseline_react", llm=RefuelRecoveryLLM(), toolsets=scenario.apps)
    engine = Engine(agent, scenario)
    engine.run_scenario_agent(max_tool_calls=10, timeout_seconds=30, setup_scenario=False)

    errors = [step for step in agent.workflow.dag.values() if step.op_type == "TOOL_ERROR"]
    assert len(errors) == 1
    assert agent.tool_call_count == 2
    result = engine.evaluate(agent.workflow)
    assert result.metadata["goal_met"]
    assert result.metadata["audit"]["success"]
    assert result.metadata["tool_errors"] == 1
    # Existing benchmark semantics require error-free success, while goal_met
    # separately makes the successful recovery visible.
    assert not result.success


def test_error_count_accepts_legacy_dict_errors_without_double_counting():
    scenario = get_scenario_class("scenario_rice_l1_refuel")()
    engine = Engine(None, scenario)
    workflow = engine.run_scenario_oracle(run_oracle=True)
    workflow.add_node(WorkflowStep(op_type="TOOL_ERROR", content={"error": "both markers"}))
    workflow.add_node(WorkflowStep(content={"error": "legacy result"}))
    workflow.add_node(WorkflowStep(content={"error": ""}))

    result = engine.evaluate(workflow)
    assert result.metadata["goal_met"]
    assert result.metadata["tool_errors"] == 2
    assert not result.success
