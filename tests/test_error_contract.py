"""Regression checks for Agent error feedback, context, metrics, and replay.

Run from the repository root:
    .venv/bin/python -B tests/test_error_contract.py -v

The tests make no external LLM requests and keep artifact I/O in memory.
"""
from __future__ import annotations

import copy
import csv
import io
import json
import math
import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Support both direct script execution and unittest discovery.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fairy.agents.agent.agent import Agent, AgentRunLimitExceeded, RecoverableToolCallError
from fairy.agents.agent.base_agent import BaseAgent, RetryableLLMResponseError
from fairy.apps.app import App
from fairy.cli import _append_live_progress, _runtime_log_rows
from fairy.controllers.engine import Engine
from fairy.controllers.run_artifacts import (
    NEW_ERROR_METRIC_FIELDS,
    build_run_report,
    error_metric_totals,
    metric_totals,
    write_json,
    write_jsonl,
)
from fairy.scenarios.fos.spatiotemporal import compute_farm_fos, compute_farm_fos_v2
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.workflow import Workflow, WorkflowStep
from fairy.scenarios.workflow_validation import workflow_from_event_log
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered
from scripts import iclr_validation_runner as runner
from scripts import rebatch_fos_from_traces as rebatch
from scripts import summarize_runs


class MemoryFile(io.StringIO):
    """Keep mock export contents readable after exiting a file context."""

    def __exit__(self, *args):
        return False


# ----------------------------------------------------------------------------
# Tool classification, feedback, and message ordering
# ----------------------------------------------------------------------------


@dataclass
class ToolFunction:
    name: str
    arguments: str


@dataclass
class ToolCall:
    id: str
    function: ToolFunction
    type: str = "function"


@dataclass
class ToolReply:
    content: str | None = None
    tool_calls: list[ToolCall] | None = None


class ToolReplyClient:
    provider = "fake"
    model = "fake"

    def __init__(self, replies=()):
        self.replies = iter(replies)
        self.requests = []

    def chat_completion(self, messages, tools=None):
        self.requests.append(copy.deepcopy(messages))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=next(self.replies), finish_reason="stop")],
            usage=None,
        )


class TrackingAgent(Agent):
    def __init__(self, client):
        super().__init__("test", client, system_message="initial system")
        self.responses = []
        self.exceptions = []
        self.log = lambda _message: None
        self.clock = 10.0
        self.set_time_manager(SimpleNamespace(time=lambda: self.clock))
        self.tools_map = {}
        self.tool_schemas = []

    def after_tool_response(self, tool_call, tool_response):
        self.responses.append((tool_call.id, tool_response))

    def after_agent_error(self, exc):
        self.exceptions.append(exc)


def make_tool_call(identifier="c1", name="Demo__act", arguments="{}"):
    return ToolCall(identifier, ToolFunction(name, arguments))


class ToolErrorContractTests(unittest.TestCase):
    def assert_failure(self, agent, identifier="c1", stage="tool_call", event_type="tool_call_error"):
        messages = [m for m in agent.messages.messages if isinstance(m, dict) and m.get("role") == "tool"]
        metrics = [m for m in agent.messages.runtime_metrics if m["role"] == "tool"]
        steps = [s for s in agent.workflow.dag.values() if s.tool_name]
        results = [e for e in agent.runtime_events if e["event_type"] in {
            "tool_call_end", "tool_call_error", "tool_args_parse_error",
        }]
        self.assertEqual((len(messages), len(metrics), len(steps), len(results)), (1, 1, 1, 1))
        message, metric, step, result = messages[0], metrics[0], steps[0], results[0]
        self.assertEqual(message["tool_call_id"], identifier)
        self.assertEqual(metric["tool_call_id"], identifier)
        self.assertEqual(result["tool_call_id"], identifier)
        self.assertEqual(result["event_type"], event_type)
        self.assertEqual((result["status"], metric["status"]), ("error", "error"))
        self.assertIs(result["is_error"], True)
        self.assertIs(metric["is_error"], True)
        self.assertEqual((step.op_type, step.error_stage), ("TOOL_ERROR", stage))
        self.assertEqual(json.loads(message["content"]), step.content)
        self.assertEqual(result["agent_feedback"], step.content)
        self.assertEqual(set(step.content), {"error"})
        self.assertEqual(agent.tool_call_count, 1)
        return step, result

    def test_business_error_retains_reason_return_value_and_side_effects(self):
        agent = TrackingAgent(ToolReplyClient())
        original = {"error": '原有原因 "quoted"\nsecond line'}
        invocations = []

        def reject():
            invocations.append("called")
            agent.clock += 7
            return original

        agent.tools_map["Demo__act"] = reject
        self.assertIs(agent.call_function(make_tool_call()), original)
        step, result = self.assert_failure(agent)
        self.assertEqual(step.content, original)
        self.assertEqual((step.time_before, step.time_after), (10, 17))
        self.assertEqual(invocations, ["called"])
        self.assertNotIn("error_type", result)
        self.assertEqual(result["error_source"], "returned_error")
        original["error"] = "later mutation"
        self.assertNotEqual(step.content, original)
        self.assertEqual(step.content, result["agent_feedback"])

    def test_success_outputs_keep_original_serialization(self):
        for response in ({"status": "ok"}, None, False, "contains error but is normal", [1, 2]):
            with self.subTest(response=response):
                agent = TrackingAgent(ToolReplyClient())
                agent.tools_map["Demo__act"] = lambda: response
                self.assertIs(agent.call_function(make_tool_call()), response)
                self.assertEqual(agent.messages.messages[-1]["content"], str(response))
                self.assertIs(agent.messages.runtime_metrics[-1]["is_error"], False)
                self.assertNotIn("status", agent.messages.runtime_metrics[-1])
                self.assertEqual(agent.runtime_events[-1]["event_type"], "tool_call_end")
                self.assertEqual(agent.workflow.dag["step0"].op_type, "TOOL")

    def test_execution_exception_wraps_the_existing_text_verbatim(self):
        agent = TrackingAgent(ToolReplyClient())

        def explode(value):
            agent.clock += 2
            raise ValueError("original reason")

        agent.tools_map["Demo__act"] = explode
        raw = '{"value":1}'
        with self.assertRaises(RecoverableToolCallError) as raised:
            agent.call_function(make_tool_call(arguments=raw))
        self.assertIsInstance(raised.exception.original, ValueError)
        step, result = self.assert_failure(agent)
        self.assertEqual(step.content["error"], (
            '[OUTPUT OF TOOL Demo__act] ERROR:\n***\nValueError: original reason\n'
            'Raw arguments: {"value":1}\n***\n\n'
            'Now retry with valid arguments or choose a different tool. '
            'Do not repeat the same invalid call.'
        ))
        self.assertEqual(result["error_type"], "ValueError")
        self.assertEqual((step.time_before, step.time_after), (10, 12))

    def test_parse_failure_is_recorded_without_executing_tool(self):
        agent = TrackingAgent(ToolReplyClient())
        invoked = []
        agent.tools_map["Demo__act"] = lambda: invoked.append(True)
        with self.assertRaises(RecoverableToolCallError):
            agent.call_function(make_tool_call(arguments="{"))
        step, result = self.assert_failure(agent, stage="tool_args_parse", event_type="tool_args_parse_error")
        self.assertEqual(invoked, [])
        self.assertEqual(step.tool_args, {})
        self.assertEqual(result["error_type"], "JSONDecodeError")

    def test_lookup_and_binding_failures_are_call_errors_without_invocation(self):
        cases = [("Missing__act", "{}", KeyError), ("Demo__act", '{"unexpected":1}', TypeError)]
        for name, arguments, expected in cases:
            with self.subTest(name=name):
                agent = TrackingAgent(ToolReplyClient())
                invoked = []
                agent.tools_map["Demo__act"] = lambda: invoked.append(True)
                with self.assertRaises(RecoverableToolCallError) as raised:
                    agent.call_function(make_tool_call(name=name, arguments=arguments))
                self.assertIsInstance(raised.exception.original, expected)
                self.assert_failure(agent)
                self.assertEqual(invoked, [])

    def test_valid_non_object_arguments_preserve_existing_failure_behavior(self):
        agent = TrackingAgent(ToolReplyClient())
        invoked = []
        agent.tools_map["Demo__act"] = lambda: invoked.append(True)
        with self.assertRaises(RecoverableToolCallError):
            agent.call_function(make_tool_call(arguments="[1]"))
        step, _ = self.assert_failure(agent)
        self.assertEqual(step.tool_args, [1])
        self.assertEqual(invoked, [])

    def test_internally_recovered_exception_is_not_a_failure(self):
        agent = TrackingAgent(ToolReplyClient())

        def recovered():
            try:
                raise ValueError("handled internally")
            except ValueError:
                return "done"

        agent.tools_map["Demo__act"] = recovered
        self.assertEqual(agent.call_function(make_tool_call()), "done")
        self.assertIs(agent.runtime_events[-1]["is_error"], False)

    def test_invalid_error_values_stay_failed_without_inventing_a_reason(self):
        for reason in (None, "", "  ", False, {"detail": "unknown schema"}):
            with self.subTest(reason=reason):
                agent = TrackingAgent(ToolReplyClient())
                original = {"error": reason}
                agent.tools_map["Demo__act"] = lambda: original
                self.assertIs(agent.call_function(make_tool_call()), original)
                result = agent.runtime_events[-1]
                self.assertEqual(result["event_type"], "tool_call_error")
                self.assertIs(result["is_error"], True)
                self.assertEqual(result["error_contract_issue"], "invalid_error_value")
                self.assertNotIn("agent_feedback", result)
                self.assertEqual(agent.workflow.dag["step0"].content, original)
                self.assertEqual(agent.messages.messages[-1]["content"], str(original))
                self.assertEqual(agent.messages.runtime_metrics[-1]["status"], "error")

    def test_direct_exception_reply_precedes_notifications(self):
        agent = TrackingAgent(ToolReplyClient())

        def notify_then_raise():
            agent.messages.system_notify("notification")
            raise RuntimeError("original reason")

        agent.tools_map["Demo__act"] = notify_then_raise
        with self.assertRaises(RecoverableToolCallError):
            agent.call_function(make_tool_call())
        self.assertEqual([m["role"] for m in agent.messages.messages], ["system", "tool", "system"])

    def test_batch_errors_reach_next_request_before_notifications_and_keep_callbacks(self):
        calls = [make_tool_call("business", "Demo__reject"), make_tool_call("exception", "Demo__raise"),
                 make_tool_call("parse", arguments="{"), make_tool_call("success", "Demo__ok")]
        client = ToolReplyClient([ToolReply(tool_calls=calls), ToolReply(content="done")])
        agent = TrackingAgent(client)
        invoked = []

        def notify(name):
            invoked.append(name)
            agent.messages.system_notify(name + " notification")
            agent.workflow.add_node(WorkflowStep(op_type="system", content=name + " notification"))

        def reject():
            notify("business")
            return {"error": "original business reason"}

        def explode():
            notify("exception")
            raise RuntimeError("original exception reason")

        def success():
            notify("success")
            return {"value": 7}

        agent.tools_map = {"Demo__reject": reject, "Demo__raise": explode, "Demo__ok": success}
        self.assertEqual(agent.run("task", max_tool_calls=10), "done")
        payload = client.requests[1]
        assistant_index = next(i for i, m in enumerate(payload) if m.get("tool_calls"))
        tail = payload[assistant_index + 1:]
        self.assertEqual([m["role"] for m in tail], ["tool"] * 4 + ["system"] * 3)
        self.assertEqual([m["tool_call_id"] for m in tail[:4]], [c.id for c in calls])
        self.assertEqual([identifier for identifier, _ in agent.responses], ["business", "success"])
        self.assertEqual([type(exc) for exc in agent.exceptions], [RuntimeError, json.JSONDecodeError])
        self.assertEqual(invoked, ["business", "exception", "success"])
        self.assertEqual([step.op_type for step in agent.workflow.dag.values()],
                         ["USER", "system", "TOOL_ERROR", "system", "TOOL_ERROR", "TOOL_ERROR", "system", "TOOL"])
        steps = [s for s in agent.workflow.dag.values() if s.tool_name]
        for index in range(3):
            self.assertEqual(json.loads(tail[index]["content"]), steps[index].content)
        metrics = metric_totals(agent.messages.runtime_metrics)
        self.assertEqual((metrics["new_tools"], metrics["new_tool_errors"]), (4, 3))
        self.assertEqual((metrics["new_llm"], metrics["new_llm_errors"]), (2, 0))
        # Successful tool content still uses its existing Python string form.
        self.assertEqual(tail[3]["content"], "{'value': 7}")

    def test_business_error_does_not_double_charge_budget_or_execute_remaining_calls(self):
        client = ToolReplyClient([ToolReply(tool_calls=[make_tool_call("first"), make_tool_call("second")])])
        agent = TrackingAgent(client)
        invoked = []

        def reject():
            invoked.append(True)
            return {"error": "original reason"}

        agent.tools_map["Demo__act"] = reject
        with self.assertRaises(AgentRunLimitExceeded):
            agent.run("task", max_tool_calls=1)
        self.assertEqual(invoked, [True])
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(agent.tool_call_count, 1)
        self.assertEqual(len(agent.responses), 1)
        self.assertEqual(agent.exceptions, [])
        self.assertEqual(agent.runtime_events[-1]["status"], "stopped")

    def test_tool_error_remains_in_later_history_requests(self):
        client = ToolReplyClient([ToolReply(content="first"), ToolReply(content="second")])
        agent = TrackingAgent(client)
        agent.tools_map["Demo__act"] = lambda: {"error": "original reason"}
        agent.call_function(make_tool_call())
        for _ in range(2):
            agent.chat_completion(agent.messages(), [])
        for request in client.requests:
            errors = [m for m in request if m.get("tool_call_id") == "c1"]
            self.assertEqual(len(errors), 1)
            self.assertEqual(json.loads(errors[0]["content"]), {"error": "original reason"})


# ----------------------------------------------------------------------------
# Single-use LLM correction feedback
# ----------------------------------------------------------------------------


@dataclass
class LLMFunction:
    name: str = "DoThing"
    arguments: str = "{}"


@dataclass
class LLMToolCall:
    id: str = "call_unexecuted"
    function: LLMFunction = field(default_factory=LLMFunction)
    type: str = "function"


@dataclass
class LLMMessage:
    content: str | None = "done"
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    role: str = "assistant"


@dataclass
class LLMChoice:
    message: LLMMessage
    finish_reason: str = "stop"


@dataclass
class LLMResponse:
    choices: list[LLMChoice]
    usage: object = None


def llm_response(content="done", *, finish_reason="stop", tool_calls=None):
    return LLMResponse([
        LLMChoice(LLMMessage(content, tool_calls or []), finish_reason),
    ])


class LLMResponseClient:
    provider = "mock"
    model = "mock-model"
    parallel_tool_calls = True

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def chat_completion(self, messages, tools=None):
        self.requests.append(copy.deepcopy(messages))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def llm_feedbacks(request):
    result = []
    for message in request:
        if message.get("role") != "system":
            continue
        try:
            content = json.loads(message["content"])
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(content, dict) and set(content) == {"error"}:
            result.append(content)
    return result


def llm_events(agent, event_type):
    return [event for event in agent.runtime_events if event["event_type"] == event_type]


def base_agent(client):
    agent = BaseAgent("test", client, system_message="Follow the task.")
    agent.messages.user_input("Complete the task.")
    return agent


def running_agent(client, retries=2):
    agent = Agent("test", client, toolsets=[])
    agent.max_llm_call_retries = retries
    agent.llm_retry_sleep_seconds = 0
    agent.rate_limit_retry_sleep_seconds = 0
    return agent


class LLMErrorContextTests(unittest.TestCase):
    def test_truncated_tools_never_execute_and_feedback_is_send_only(self):
        client = LLMResponseClient(
            llm_response("INVALID_OUTPUT_SENTINEL", finish_reason="length", tool_calls=[LLMToolCall()]),
            llm_response("accepted"),
            llm_response("later"),
        )
        agent = running_agent(client)
        tool_calls = []
        agent.tools_map["DoThing"] = lambda: tool_calls.append("executed")

        self.assertEqual(agent.run("Complete the task."), "accepted")
        sent_log_snapshot = copy.deepcopy(llm_events(agent, "llm_call_start")[1])
        agent.chat_completion(agent.messages())

        self.assertEqual(tool_calls, [])
        self.assertEqual(agent.tool_call_count, 0)
        self.assertEqual([step.op_type for step in agent.workflow.dag.values()], ["USER"])
        self.assertEqual([len(llm_feedbacks(request)) for request in client.requests], [0, 1, 0])
        self.assertNotIn("INVALID_OUTPUT_SENTINEL", json.dumps(client.requests))
        self.assertEqual(llm_feedbacks(agent._llm_compatible_messages(agent.messages())), [])
        self.assertNotIn("INVALID_OUTPUT_SENTINEL", str(agent.messages.messages))

        starts = llm_events(agent, "llm_call_start")
        ends = llm_events(agent, "llm_call_end")
        self.assertEqual(starts[1], sent_log_snapshot)
        self.assertEqual(starts[1]["messages"], client.requests[1])
        self.assertEqual(starts[1]["feedback_for_llm_call_id"], ends[0]["llm_call_id"])
        self.assertEqual(llm_feedbacks(client.requests[1]), [ends[0]["agent_feedback"]])
        self.assertEqual(ends[0]["rejection_reason"], "output_truncated")
        self.assertEqual(ends[0]["assistant_content"], "INVALID_OUTPUT_SENTINEL")
        self.assertNotIn("feedback_for_llm_call_id", starts[2])
        self.assertEqual([event["accepted"] for event in ends], [False, True, True])
        self.assertEqual(len(agent.messages.runtime_metrics), 3)
        self.assertEqual(
            [metric["llm_call_id"] for metric in agent.messages.runtime_metrics],
            [event["llm_call_id"] for event in ends],
        )
        self.assertEqual(agent.messages.runtime_metrics[0]["rejection_reason"], "output_truncated")

    def test_network_failure_consumes_feedback_and_does_not_create_another(self):
        client = LLMResponseClient(llm_response("", finish_reason="length"), OSError("network unavailable"), llm_response())
        agent = running_agent(client, retries=2)
        self.assertEqual(agent.run("Complete the task."), "done")

        self.assertEqual([len(llm_feedbacks(request)) for request in client.requests], [0, 1, 0])
        starts = llm_events(agent, "llm_call_start")
        ends = llm_events(agent, "llm_call_end")
        self.assertEqual(llm_events(agent, "llm_call_error")[0]["llm_call_id"], starts[1]["llm_call_id"])
        self.assertEqual(starts[1]["feedback_for_llm_call_id"], ends[0]["llm_call_id"])
        self.assertNotIn("feedback_for_llm_call_id", starts[2])
        self.assertEqual(len(ends), 2)
        self.assertEqual(len(agent.messages.runtime_metrics), 2)
        self.assertEqual(sum(not event["accepted"] for event in ends), 1)
        self.assertEqual(len(llm_events(agent, "llm_call_retry")), 2)
        self.assertEqual([step.op_type for step in agent.workflow.dag.values()], ["USER"])

    def test_each_consecutive_rejection_has_its_own_single_use_feedback(self):
        client = LLMResponseClient(llm_response(""), llm_response("", finish_reason="length"), llm_response())
        agent = running_agent(client, retries=2)
        self.assertEqual(agent.run("Complete the task."), "done")

        starts = llm_events(agent, "llm_call_start")
        ends = llm_events(agent, "llm_call_end")
        self.assertEqual([len(llm_feedbacks(request)) for request in client.requests], [0, 1, 1])
        self.assertEqual(ends[0]["rejection_reason"], "empty_response")
        self.assertEqual(ends[1]["rejection_reason"], "output_truncated")
        for index in (1, 2):
            self.assertEqual(starts[index]["feedback_for_llm_call_id"], ends[index - 1]["llm_call_id"])
            self.assertEqual(llm_feedbacks(client.requests[index]), [ends[index - 1]["agent_feedback"]])
        self.assertNotEqual(llm_feedbacks(client.requests[1]), llm_feedbacks(client.requests[2]))
        self.assertEqual(len(llm_events(agent, "llm_call_retry")), 2)
        self.assertEqual(len(ends), 3)
        self.assertEqual(len(agent.messages.runtime_metrics), 3)
        self.assertEqual(agent.llm_turn_count, 1)

    def test_local_preparation_failure_does_not_consume_feedback(self):
        client = LLMResponseClient(llm_response(""), llm_response())
        agent = base_agent(client)
        with self.assertRaises(RetryableLLMResponseError):
            agent.chat_completion(agent.messages())
        original_feedback = llm_events(agent, "llm_call_end")[0]["agent_feedback"]

        for method_name in ("_llm_compatible_messages", "llm_config"):
            with self.subTest(method=method_name):
                with patch.object(agent, method_name, side_effect=ValueError("local preparation failed")):
                    with self.assertRaises(ValueError):
                        agent.chat_completion(agent.messages())
                self.assertEqual(len(client.requests), 1)
                self.assertEqual(len(llm_events(agent, "llm_call_start")), 1)

        agent.chat_completion(agent.messages())
        self.assertEqual(llm_feedbacks(client.requests[1]), [original_feedback])

    def test_final_rejection_stops_without_extra_call_and_new_run_resets_feedback(self):
        client = LLMResponseClient(llm_response(""), llm_response("next run"))
        agent = running_agent(client, retries=0)
        with self.assertRaises(RetryableLLMResponseError) as caught:
            agent.run("First task.")

        self.assertEqual(len(client.requests), 1)
        rejected = llm_events(agent, "llm_call_end")[0]
        self.assertFalse(rejected["accepted"])
        self.assertEqual(caught.exception.llm_call_id, rejected["llm_call_id"])
        self.assertEqual(llm_events(agent, "llm_call_retry"), [])
        self.assertEqual([step.op_type for step in agent.workflow.dag.values()], ["USER"])

        self.assertEqual(agent.run("Second task."), "next run")
        self.assertEqual(llm_feedbacks(client.requests[1]), [])
        self.assertNotIn("feedback_for_llm_call_id", llm_events(agent, "llm_call_start")[1])
        self.assertNotEqual(llm_events(agent, "llm_call_end")[1]["llm_call_id"], rejected["llm_call_id"])

    def test_infrastructure_only_failure_does_not_generate_feedback(self):
        client = LLMResponseClient(OSError("network unavailable"), llm_response())
        agent = base_agent(client)
        with self.assertRaises(OSError):
            agent.chat_completion(agent.messages())
        agent.chat_completion(agent.messages())

        self.assertEqual([llm_feedbacks(request) for request in client.requests], [[], []])
        self.assertEqual(len(llm_events(agent, "llm_call_end")), 1)
        self.assertTrue(llm_events(agent, "llm_call_end")[0]["accepted"])
        self.assertNotIn("agent_feedback", llm_events(agent, "llm_call_end")[0])

    def test_empty_content_with_tool_call_keeps_existing_acceptance_rule(self):
        client = LLMResponseClient(llm_response(None, tool_calls=[LLMToolCall()]))
        agent = base_agent(client)
        message = agent.chat_completion(agent.messages())

        self.assertEqual(message.tool_calls[0].id, "call_unexecuted")
        self.assertTrue(llm_events(agent, "llm_call_end")[0]["accepted"])
        self.assertNotIn("agent_feedback", llm_events(agent, "llm_call_end")[0])

    def test_explicit_reset_clears_feedback_without_erasing_rejection_record(self):
        client = LLMResponseClient(llm_response(""), llm_response())
        agent = base_agent(client)
        with self.assertRaises(RetryableLLMResponseError):
            agent.chat_completion(agent.messages())
        rejected = copy.deepcopy(llm_events(agent, "llm_call_end")[0])

        agent.reset_llm_feedback()
        agent.chat_completion(agent.messages())

        self.assertEqual(llm_feedbacks(client.requests[1]), [])
        self.assertEqual(llm_events(agent, "llm_call_end")[0], rejected)


# ----------------------------------------------------------------------------
# New metrics and unchanged legacy calculations
# ----------------------------------------------------------------------------


def progress_path(rows):
    path = MagicMock(spec=Path)
    path.exists.return_value = True
    data = "".join(json.dumps(row) + "\n" for row in rows)
    path.open.side_effect = lambda **kwargs: MemoryFile(data)
    path.stat.return_value = SimpleNamespace(st_mtime=90.0)
    return path


def result_rows():
    tools = [
        {"role": "tool", "is_error": value, "time": 0.5}
        for value in [False] * 5 + [True] * 4
    ]
    responses = [
        {"role": "assistant", "accepted": accepted, "time": 1.5,
         "tokens": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}
        for accepted in [True, False, False]
    ]
    return tools + responses


def main_events():
    return [
        *[{"record_type": "tool_call_end", "is_error": False} for _ in range(5)],
        *[{"record_type": "tool_call_error", "is_error": True} for _ in range(3)],
        {"record_type": "tool_args_parse_error", "is_error": True},
        *[{"record_type": "llm_call_end", "accepted": accepted,
           "tokens": {"prompt_tokens": 10, "completion_tokens": 2}}
          for accepted in [True, False, False]],
        {"record_type": "llm_call_retry"},
        {"record_type": "tool_error_observation"},
        {"record_type": "llm_call_error"},
        {"record_type": "agent_run_end", "wall_timestamp": "end"},
    ]


class ErrorMetricsTests(unittest.TestCase):
    def test_report_metrics_preserve_fixed_legacy_values(self):
        result = metric_totals(result_rows())
        legacy = {key: value for key, value in result.items() if key not in NEW_ERROR_METRIC_FIELDS}
        self.assertEqual(legacy, {
            "llm_call_count": 3,
            "tool_metric_count": 9,
            "llm_wall_time_seconds": 4.5,
            "tool_wall_time_seconds": 4.5,
            "token_usage": {
                "prompt_tokens": 30, "completion_tokens": 6,
                "total_tokens": 36, "cached_tokens": 0,
                "source": "llm_runtime_metrics",
            },
        })
        self.assertEqual({key: result[key] for key in NEW_ERROR_METRIC_FIELDS}, {
            "new_tools": 9, "new_tool_errors": 4, "new_llm": 3, "new_llm_errors": 2,
            "new_llm_call_errors": None,
        })

    def report(self, rows, tool_count=0, *, runtime_events=None):
        return build_run_report(
            scenario_id="sample", controller_id="react", provider="fake",
            model="fake", temperature=0.0, run_type="agent",
            stopped_reason="agent_finished", wall_time_seconds=1.0,
            max_tool_calls=None, timeout_seconds=None, parallel_tool_calls=True,
            max_output_tokens=100, workflow_steps=tool_count + 1,
            tool_call_count=tool_count, runtime_metrics=rows, artifacts={},
            runtime_events=runtime_events,
            evaluation={"validation": {"success": False}},
            controller_telemetry={"error_count": 77, "tool_calls": 5},
        )

    def test_run_report_only_adds_metrics_and_does_not_replace_outcomes(self):
        report = self.report(result_rows(), 9)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["evaluation"], {"validation": {"success": False}})
        self.assertEqual(report["controller_telemetry"], {"error_count": 77, "tool_calls": 5})
        self.assertEqual(report["metrics"]["tool_call_count"], 9)
        self.assertEqual(report["metrics"]["new_tool_errors"], 4)
        self.assertEqual(report["metrics"]["new_llm_errors"], 2)

    def test_legacy_classification_is_unknown_without_losing_known_totals(self):
        result = error_metric_totals([
            {"role": "tool", "status": "ok", "content_preview": "{'error': 'denied'}"},
            {"role": "tool", "is_error": True},
            {"role": "assistant", "status": "rejected"},
        ])
        self.assertEqual(result, {
            "new_tools": 2, "new_tool_errors": None,
            "new_llm": 1, "new_llm_errors": None,
            "new_llm_call_errors": None,
        })
        invalid = error_metric_totals([
            {"role": "tool", "is_error": 0},
            {"role": "assistant", "accepted": "false"},
        ])
        self.assertIsNone(invalid["new_tool_errors"])
        self.assertIsNone(invalid["new_llm_errors"])

    def test_empty_metrics_and_missing_tool_records_are_distinct(self):
        empty = self.report([], 0, runtime_events=[])["metrics"]
        self.assertEqual({key: empty[key] for key in NEW_ERROR_METRIC_FIELDS},
                         dict.fromkeys(NEW_ERROR_METRIC_FIELDS, 0))
        missing = self.report([], 2)["metrics"]
        self.assertIsNone(missing["new_tools"])
        self.assertIsNone(missing["new_tool_errors"])
        self.assertEqual(missing["tool_call_count"], 2)
        self.assertEqual(missing["tool_metric_count"], 0)
        self.assertEqual(missing["new_llm"], 0)

    def test_independent_runs_are_not_combined(self):
        parent = self.report([{"role": "tool", "is_error": False}], 1)["metrics"]
        child = self.report([{"role": "tool", "is_error": True}], 1)["metrics"]
        self.assertEqual((parent["new_tools"], parent["new_tool_errors"]), (1, 0))
        self.assertEqual((child["new_tools"], child["new_tool_errors"]), (1, 1))

    def test_progress_keeps_old_counts_and_ignores_auxiliary_events(self):
        path = progress_path(main_events())
        with patch.object(runner.time, "time", return_value=100.0):
            result = runner._runtime_progress_snapshot(path)
            text = runner._format_cell_progress(path, "sample", 12.0)
        self.assertEqual({key: value for key, value in result.items()
                          if key not in NEW_ERROR_METRIC_FIELDS}, {
            "records": 16, "llm_calls": 3, "tool_calls": 5, "tool_errors": 4,
            "prompt_tokens": 30, "completion_tokens": 6,
            "last_type": "agent_run_end", "last_tool": None,
            "last_timestamp": "end", "idle_seconds": 10.0,
        })
        expected_old_display = (
            "  [progress] sample elapsed=12s llm=3 tools=5 tool_errors=4 "
            "tokens_in=30 tokens_out=6 last=agent_run_end idle=10s"
        )
        self.assertEqual(text, expected_old_display +
                         " new_tools=9 new_tool_errors=4 new_llm=3 new_llm_errors=2"
                         " new_llm_call_errors=1")
        self.assertEqual({key: result[key] for key in NEW_ERROR_METRIC_FIELDS},
                         error_metric_totals(result_rows(), llm_call_errors=1))

    def test_old_progress_does_not_infer_business_failures_from_preview(self):
        rows = [
            *[{"record_type": "tool_call_end", "status": "ok"} for _ in range(5)],
            *[{"record_type": "tool_call_end", "content_preview": "{'error': 'denied'}"}
              for _ in range(2)],
            {"record_type": "tool_call_error"},
            {"record_type": "tool_args_parse_error"},
            {"record_type": "llm_call_end", "accepted": False},
        ]
        path = progress_path(rows)
        result = runner._runtime_progress_snapshot(path)
        self.assertEqual((result["tool_calls"], result["tool_errors"]), (7, 2))
        self.assertEqual(result["new_tools"], 9)
        self.assertIsNone(result["new_tool_errors"])
        self.assertEqual((result["new_llm"], result["new_llm_errors"]), (1, 1))
        self.assertIn("new_tool_errors=unknown", runner._format_cell_progress(path, "sample", 1))

    def test_waiting_unknown_and_started_zero_results_are_distinct(self):
        for path in (None, progress_path([])):
            result = runner._runtime_progress_snapshot(path)
            self.assertEqual({key: result[key] for key in NEW_ERROR_METRIC_FIELDS},
                             dict.fromkeys(NEW_ERROR_METRIC_FIELDS))
            self.assertEqual(runner._format_cell_progress(path, "sample", 1),
                             "  [progress] sample elapsed=1s waiting_for_first_event")
        result = runner._runtime_progress_snapshot(progress_path([
            {"record_type": "agent_run_start"},
            {"record_type": "llm_call_error"},
            {"record_type": "agent_run_end", "status": "stopped"},
        ]))
        self.assertEqual({key: result[key] for key in NEW_ERROR_METRIC_FIELDS},
                         {**dict.fromkeys(NEW_ERROR_METRIC_FIELDS, 0), "new_llm_call_errors": 1})

    def test_csv_new_fields_append_after_old_columns_and_missing_values_stay_blank(self):
        path = MagicMock(spec=Path)
        file = MemoryFile()
        path.with_suffix.return_value.open.return_value = file
        runner._write_results_csv(path, [
            {"scenario": "new", "error_count": 77,
             "new_tools": 9, "new_tool_errors": 4, "new_llm": 3, "new_llm_errors": 2,
             "new_llm_call_errors": 1},
            {"scenario": "old", "error_count": 5},
        ])
        reader = csv.DictReader(io.StringIO(file.getvalue()))
        self.assertEqual(reader.fieldnames, ["error_count", "scenario", *NEW_ERROR_METRIC_FIELDS])
        rows = list(reader)
        self.assertEqual(rows[0]["error_count"], "77")
        self.assertEqual(rows[1]["error_count"], "5")
        self.assertEqual([rows[0][key] for key in NEW_ERROR_METRIC_FIELDS], ["9", "4", "3", "2", "1"])
        self.assertEqual([rows[1][key] for key in NEW_ERROR_METRIC_FIELDS], [""] * 5)
        path.with_suffix.return_value.replace.assert_called_once_with(path)

    def test_csv_uses_only_new_report_fields_not_old_telemetry(self):
        for report in (None, {"metrics": {"tool_call_count": 9}, "controller_telemetry": {"error_count": 4}}):
            self.assertEqual(runner._new_error_metrics_from_report(report),
                             dict.fromkeys(NEW_ERROR_METRIC_FIELDS))
        report = self.report(result_rows(), 9)
        self.assertEqual(runner._new_error_metrics_from_report(report), {
            "new_tools": 9, "new_tool_errors": 4, "new_llm": 3, "new_llm_errors": 2,
            "new_llm_call_errors": None,
        })

    def test_call_error_count_requires_events_and_preserves_existing_metrics(self):
        original = metric_totals(result_rows())
        self.assertIsNone(original["new_llm_call_errors"])
        self.assertIsNone(self.report(result_rows(), 9)["metrics"]["new_llm_call_errors"])
        for events, expected in (
            ([], 0),
            ([{"event_type": "llm_call_retry"},
              {"event_type": "llm_call_end", "accepted": False}], 0),
            ([{"event_type": "llm_call_error"},
              {"event_type": "llm_call_retry"},
              {"event_type": "llm_call_error"},
              {"event_type": "agent_run_error"}], 2),
        ):
            with self.subTest(events=events):
                totals = metric_totals(result_rows(), runtime_events=events)
                self.assertEqual(totals, {**original, "new_llm_call_errors": expected})
                report = self.report(result_rows(), 9, runtime_events=events)
                self.assertEqual(report["metrics"]["new_llm_call_errors"], expected)

    def test_real_call_errors_and_response_rejections_are_counted_separately(self):
        cases = (
            ("retry_success", [OSError("network unavailable"), llm_response()],
             1, 1, 0, 1, 1, [0, 0], False),
            ("rejection_then_call_error", [llm_response(""), OSError("network unavailable"), llm_response()],
             2, 2, 1, 1, 2, [0, 1, 0], False),
            ("final_failure", [OSError("network unavailable")],
             0, 0, 0, 1, 0, [0], True),
        )
        for name, outcomes, retries, llm_count, rejections, call_errors, retry_count, feedback_counts, fails in cases:
            with self.subTest(name=name):
                client = LLMResponseClient(*outcomes)
                agent = running_agent(client, retries=retries)
                with patch.object(agent, "log"):
                    if fails:
                        with self.assertRaisesRegex(OSError, "network unavailable"):
                            agent.run("Complete the task.")
                    else:
                        self.assertEqual(agent.run("Complete the task."), "done")
                messages_before = copy.deepcopy(agent.messages.messages)
                workflow_before = copy.deepcopy(agent.workflow.to_dict())
                metrics_before = copy.deepcopy(agent.messages.runtime_metrics)
                report = self.report(metrics_before, runtime_events=agent.runtime_events)
                progress = runner._runtime_progress_snapshot(
                    progress_path(_runtime_log_rows(agent.runtime_events))
                )
                expected = {
                    "new_tools": 0, "new_tool_errors": 0, "new_llm": llm_count,
                    "new_llm_errors": rejections, "new_llm_call_errors": call_errors,
                }
                self.assertEqual({key: report["metrics"][key] for key in NEW_ERROR_METRIC_FIELDS}, expected)
                self.assertEqual({key: progress[key] for key in NEW_ERROR_METRIC_FIELDS}, expected)
                self.assertEqual(len(llm_events(agent, "llm_call_retry")), retry_count)
                self.assertEqual(report["metrics"]["llm_call_count"], llm_count)
                self.assertEqual(progress["llm_calls"], llm_count)
                self.assertEqual(report["metrics"]["token_usage"]["total_tokens"], 0)
                self.assertEqual([len(llm_feedbacks(request)) for request in client.requests], feedback_counts)
                self.assertEqual([step.op_type for step in agent.workflow.dag.values()], ["USER"])
                self.assertEqual(agent.messages.messages, messages_before)
                self.assertEqual(agent.messages.runtime_metrics, metrics_before)
                self.assertEqual(agent.workflow.to_dict(), workflow_before)


# ----------------------------------------------------------------------------
# CSV and TSV summary exports
# ----------------------------------------------------------------------------


LEGACY_SUMMARY_FIELDS = [
    "run_dir", "run_type", "scenario_id", "controller_id", "system_prompt_mode",
    "model", "status", "stopped_reason", "success", "wall_time_seconds",
    "workflow_steps", "tool_call_count", "total_tokens", "cached_tokens",
    "warehouse_grain_kg", "harvested_ridges", "yield_g_m2",
]


def sample_report():
    return {
        "run_type": "agent", "scenario_id": "sample", "controller_id": "react",
        "system_prompt_mode": "fairy", "model": "fake", "status": "completed",
        "stopped_reason": "agent_finished",
        "evaluation": {"validation": {"success": False}},
        "metrics": {
            "wall_time_seconds": 3.5, "workflow_steps": 10, "tool_call_count": 9,
            "token_usage": {"total_tokens": 120, "cached_tokens": 4},
            "new_tools": 9, "new_tool_errors": 4, "new_llm": 3, "new_llm_errors": 0,
            "new_llm_call_errors": 2,
        },
        "outcome": {
            "inventory": {"warehouse_grain_kg": 8},
            "yield_recovery": {
                "harvested_ridges": 2,
                "avg_recovered_yield_g_m2_at_market_moisture": 11.5,
            },
        },
    }


class ErrorSummaryExportTests(unittest.TestCase):
    def test_new_columns_append_and_legacy_values_do_not_change(self):
        self.assertEqual(summarize_runs.FIELDS, LEGACY_SUMMARY_FIELDS + list(NEW_ERROR_METRIC_FIELDS))
        path = Path("/synthetic/new.run_report.json")
        with patch.object(Path, "read_text", return_value=json.dumps(sample_report())):
            row = summarize_runs.row_from_report(path)
        self.assertEqual({key: row[key] for key in LEGACY_SUMMARY_FIELDS}, {
            "run_dir": "/synthetic", "run_type": "agent", "scenario_id": "sample",
            "controller_id": "react", "system_prompt_mode": "fairy", "model": "fake",
            "status": "completed", "stopped_reason": "agent_finished", "success": False,
            "wall_time_seconds": 3.5, "workflow_steps": 10, "tool_call_count": 9,
            "total_tokens": 120, "cached_tokens": 4, "warehouse_grain_kg": 8,
            "harvested_ridges": 2, "yield_g_m2": 11.5,
        })
        self.assertEqual([row[key] for key in NEW_ERROR_METRIC_FIELDS], [9, 4, 3, 0, 2])

    def test_missing_or_unknown_metrics_are_not_inferred_from_old_fields(self):
        for metrics in ({"tool_call_count": 9}, None, {key: None for key in NEW_ERROR_METRIC_FIELDS}):
            report = {"metrics": metrics, "controller_telemetry": {"error_count": 4}}
            with self.subTest(metrics=metrics):
                with patch.object(Path, "read_text", return_value=json.dumps(report)):
                    row = summarize_runs.row_from_report(Path("/synthetic/old.run_report.json"))
                self.assertEqual([row[key] for key in NEW_ERROR_METRIC_FIELDS], [None] * 5)

    def test_report_with_previous_four_metrics_leaves_only_new_column_blank(self):
        report = sample_report()
        report["metrics"].pop("new_llm_call_errors")
        with patch.object(Path, "read_text", return_value=json.dumps(report)):
            row = summarize_runs.row_from_report(Path("/synthetic/previous.run_report.json"))
        self.assertEqual([row[key] for key in NEW_ERROR_METRIC_FIELDS], [9, 4, 3, 0, None])
        self.assertEqual(runner._new_error_metrics_from_report(report), {
            "new_tools": 9, "new_tool_errors": 4, "new_llm": 3, "new_llm_errors": 0,
            "new_llm_call_errors": None,
        })
        path = MagicMock(spec=Path)
        output = MemoryFile()
        path.with_suffix.return_value.open.return_value = output
        runner._write_results_csv(path, [row])
        exported = next(csv.DictReader(io.StringIO(output.getvalue())))
        self.assertEqual([exported[key] for key in NEW_ERROR_METRIC_FIELDS], ["9", "4", "3", "0", ""])

    def test_csv_and_tsv_export_match_report_values_and_keep_unknown_blank(self):
        paths = [Path("/synthetic/new.run_report.json"), Path("/synthetic/old.run_report.json")]
        old_report = sample_report()
        for key in NEW_ERROR_METRIC_FIELDS:
            old_report["metrics"].pop(key)
        reports = dict(zip(paths, [sample_report(), old_report]))
        csv_output = MemoryFile()
        stdout = io.StringIO()

        def read_report(path, **kwargs):
            return json.dumps(reports[path])

        with (
            patch("sys.argv", ["summarize_runs", "/synthetic", "--csv", "/synthetic/export.csv"]),
            patch.object(Path, "glob", return_value=paths),
            patch.object(Path, "read_text", autospec=True, side_effect=read_report),
            patch.object(Path, "mkdir"),
            patch("builtins.open", return_value=csv_output),
            patch("sys.stdout", stdout),
        ):
            summarize_runs.main()

        csv_reader = csv.DictReader(io.StringIO(csv_output.getvalue()))
        tsv_reader = csv.DictReader(io.StringIO(stdout.getvalue()), delimiter="\t")
        self.assertEqual(csv_reader.fieldnames, LEGACY_SUMMARY_FIELDS + list(NEW_ERROR_METRIC_FIELDS))
        self.assertEqual(tsv_reader.fieldnames, csv_reader.fieldnames)
        csv_rows, tsv_rows = list(csv_reader), list(tsv_reader)
        self.assertEqual(csv_rows, tsv_rows)
        self.assertEqual([csv_rows[0][key] for key in NEW_ERROR_METRIC_FIELDS], ["9", "4", "3", "0", "2"])
        self.assertEqual([csv_rows[1][key] for key in NEW_ERROR_METRIC_FIELDS], [""] * 5)
        self.assertEqual(csv_rows[0]["tool_call_count"], csv_rows[1]["tool_call_count"])


# ----------------------------------------------------------------------------
# Agent-to-artifact integration
# ----------------------------------------------------------------------------


@dataclass
class ArtifactToolFunction:
    name: str
    arguments: str = "{}"


@dataclass
class ArtifactToolCall:
    id: str
    function: ArtifactToolFunction
    type: str = "function"


@dataclass
class ArtifactMessage:
    content: str | None = None
    tool_calls: list[ArtifactToolCall] = field(default_factory=list)
    role: str = "assistant"


def artifact_tool_call(identifier, method, arguments="{}"):
    return ArtifactToolCall(identifier, ArtifactToolFunction(f"ArtifactApp__{method}", arguments))


def artifact_response(message, finish_reason="stop"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        usage=SimpleNamespace(
            prompt_tokens=10, completion_tokens=3, total_tokens=13,
            prompt_tokens_details=SimpleNamespace(cached_tokens=1),
        ),
    )


class ArtifactClient:
    provider = "fake"
    model = "artifact-test"
    parallel_tool_calls = True

    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def chat_completion(self, messages, tools=None):
        self.requests.append(copy.deepcopy(messages))
        return next(self.responses)


class ArtifactApp(App):
    def __init__(self):
        super().__init__()
        self.calls = []

    @app_tool()
    def reject(self):
        self.calls.append("reject")
        return {"error": "need 2 units; have 1"}

    @app_tool()
    def explode(self):
        self.calls.append("explode")
        raise ValueError("original execution reason")

    @app_tool()
    def succeed(self):
        self.calls.append("succeed")
        return {"completed": True}


class ErrorRuntimeArtifactTests(unittest.TestCase):
    def test_run_feedback_workflow_report_and_progress_agree(self):
        app = ArtifactApp()
        calls = [
            artifact_tool_call("business", "reject"),
            artifact_tool_call("exception", "explode"),
            artifact_tool_call("parse", "succeed", "{"),
            artifact_tool_call("success", "succeed"),
        ]
        client = ArtifactClient([
            artifact_response(ArtifactMessage("REJECTED_SENTINEL", [artifact_tool_call("discarded", "succeed")]), "length"),
            artifact_response(ArtifactMessage(tool_calls=calls)),
            artifact_response(ArtifactMessage("finished")),
        ])
        agent = Agent("artifact-test", client, system_message="Perform the task.", toolsets=[app])
        agent.max_llm_call_retries = 1
        agent.llm_retry_sleep_seconds = 0
        scenario = Scenario(scenario_id="artifact_test", scenario_input="Run all operations.",
                            start_time=1000, apps=[app])
        engine = Engine(agent, scenario)

        # Exercise the real live exporter; all path operations use memory mocks.
        live = MemoryFile()
        progress_path = MagicMock(spec=Path)
        progress_path.exists.return_value = True
        progress_path.stat.return_value = SimpleNamespace(st_mtime=100.0)
        progress_path.open.side_effect = lambda mode="r", **kwargs: (
            live if mode == "a" else MemoryFile(live.getvalue())
        )
        agent.runtime_event_sink = lambda event: _append_live_progress(progress_path, event)
        with patch.object(agent, "log"):
            workflow = engine.run_scenario_agent()

        self.assertEqual(app.calls, ["reject", "explode", "succeed"])
        self.assertEqual((agent.tool_call_count, agent.llm_turn_count), (4, 2))
        self.assertEqual(len(client.requests), 3)

        # Exercise the complete runtime exporter, including JSON serialization.
        log_path = MagicMock(spec=Path)
        log_path.suffix = ".jsonl"
        complete = MemoryFile()
        with patch("builtins.open", return_value=complete):
            write_jsonl(log_path, _runtime_log_rows(agent.runtime_events))
        log_path.with_suffix.return_value.replace.assert_called_once_with(log_path)
        rows = [json.loads(line) for line in complete.getvalue().splitlines()]
        starts = [row for row in rows if row["record_type"] == "llm_call_start"]
        ends = [row for row in rows if row["record_type"] == "llm_call_end"]
        self.assertEqual([row["record_index"] for row in rows], list(range(len(rows))))
        self.assertEqual([row["accepted"] for row in ends], [False, True, True])
        rejected = ends[0]
        self.assertEqual(rejected["rejection_reason"], "output_truncated")
        self.assertEqual(rejected["assistant_content"], "REJECTED_SENTINEL")
        self.assertEqual(starts[1]["feedback_for_llm_call_id"], rejected["llm_call_id"])
        self.assertEqual(starts[1]["messages"], client.requests[1])
        feedback_message = {"role": "system", "content": json.dumps(rejected["agent_feedback"])}
        self.assertIn(feedback_message, starts[1]["messages"])
        for index in (0, 2):
            self.assertNotIn("feedback_for_llm_call_id", starts[index])
            self.assertNotIn(feedback_message, starts[index]["messages"])
        self.assertNotIn("REJECTED_SENTINEL", json.dumps(client.requests))
        self.assertNotIn(feedback_message, agent._llm_compatible_messages(agent.messages()))
        self.assertTrue(all("messages" not in row for row in map(json.loads, live.getvalue().splitlines())))

        steps = list(workflow.dag.values())
        self.assertEqual([step.op_type for step in steps], ["USER", "TOOL_ERROR", "TOOL_ERROR", "TOOL_ERROR", "TOOL"])
        self.assertEqual([step.error_stage for step in steps[1:]], ["tool_call", "tool_call", "tool_args_parse", None])
        self.assertNotIn(rejected["agent_feedback"]["error"], json.dumps(workflow.to_dict()))
        self.assertEqual([step.tool_name for step in steps[1:]], [call.function.name for call in calls])
        tool_replies = [message for message in client.requests[2] if message.get("role") == "tool"]
        self.assertEqual([message["tool_call_id"] for message in tool_replies], [call.id for call in calls])
        results = [row for row in rows if row["record_type"] in {
            "tool_call_end", "tool_call_error", "tool_args_parse_error",
        }]
        self.assertEqual([row["tool_call_id"] for row in results], [call.id for call in calls])
        self.assertEqual([row["record_type"] for row in results], [
            "tool_call_error", "tool_call_error", "tool_args_parse_error", "tool_call_end",
        ])
        for step, reply, result in zip(steps[1:4], tool_replies[:3], results[:3]):
            self.assertIsInstance(step.content, dict)
            self.assertEqual(json.loads(reply["content"]), step.content)
            self.assertEqual(result["agent_feedback"], step.content)

        report = build_run_report(
            scenario_id=scenario.scenario_id, controller_id="simple", provider=client.provider,
            model=client.model, temperature=0.0, run_type="agent", stopped_reason=agent.stop_reason,
            wall_time_seconds=1.0, max_tool_calls=None, timeout_seconds=None,
            parallel_tool_calls=True, max_output_tokens=None, workflow_steps=len(workflow),
            tool_call_count=agent.tool_call_count, runtime_metrics=agent.messages.runtime_metrics,
            runtime_events=agent.runtime_events,
            artifacts={}, evaluation=engine.evaluation_report(workflow),
            llm_config=agent.llm_config(), response_policy=agent.response_policy(),
        )
        serialized_report = MemoryFile()
        with patch("builtins.open", return_value=serialized_report):
            write_json(MagicMock(spec=Path), report)
        report = json.loads(serialized_report.getvalue())
        with patch.object(runner.time, "time", return_value=100.0):
            progress = runner._runtime_progress_snapshot(progress_path)
            display = runner._format_cell_progress(progress_path, "integration", 12)

        expected = {"new_tools": 4, "new_tool_errors": 3, "new_llm": 3, "new_llm_errors": 1,
                    "new_llm_call_errors": 0}
        self.assertEqual({key: report["metrics"][key] for key in NEW_ERROR_METRIC_FIELDS}, expected)
        self.assertEqual({key: progress[key] for key in NEW_ERROR_METRIC_FIELDS}, expected)
        self.assertEqual(runner._new_error_metrics_from_report(report), expected)
        # Fixed legacy expectations deliberately differ from the new total tools.
        self.assertEqual((progress["llm_calls"], progress["tool_calls"], progress["tool_errors"]), (3, 1, 3))
        self.assertEqual((progress["prompt_tokens"], progress["completion_tokens"]), (30, 9))
        self.assertEqual(display, "  [progress] integration elapsed=12s llm=3 tools=1 tool_errors=3 "
                         "tokens_in=30 tokens_out=9 last=agent_run_end idle=0s "
                         "new_tools=4 new_tool_errors=3 new_llm=3 new_llm_errors=1 new_llm_call_errors=0")
        metrics = report["metrics"]
        self.assertEqual((metrics["llm_call_count"], metrics["tool_metric_count"], metrics["tool_call_count"]), (3, 4, 4))
        self.assertEqual(metrics["workflow_steps"], 5)
        self.assertEqual(metrics["token_usage"], {
            "prompt_tokens": 30, "completion_tokens": 9, "total_tokens": 39,
            "cached_tokens": 3, "source": "llm_runtime_metrics",
        })
        for role, field_name in (("assistant", "llm_wall_time_seconds"), ("tool", "tool_wall_time_seconds")):
            self.assertEqual(metrics[field_name], round(sum(
                row["time"] for row in agent.messages.runtime_metrics if row["role"] == role
            ), 6))
        self.assertEqual(report["status"], "completed")


# ----------------------------------------------------------------------------
# Unchanged workflow conversion and replay behavior
# ----------------------------------------------------------------------------


class RecordApp(App):
    def __init__(self):
        super().__init__("CustomAppName")
        self.calls = 0

    @event_registered(OperationType.READ)
    def observe(self, z: int = 1, a: int = 2):
        self.calls += 1
        return {"value": 999}

    @app_tool()
    @event_registered(OperationType.WRITE)
    def reject(self, amount: int = 1):
        self.calls += 1
        return {"error": "operation rejected"}

    @event_registered(OperationType.WRITE)
    def harvest(self, start_ridge: int, end_ridge: int):
        self.calls += 1
        return {"ok": True}


class SystemApp(App):
    def __init__(self):
        super().__init__()
        self.calls = 0

    @event_registered(OperationType.WRITE)
    def advance_time(self, **kwargs):
        self.calls += 1
        return {"ok": True}


def _step(name="source_name", tool_name="CustomAppName__reject", **changes):
    result = {
        "name": name, "op_type": "TOOL_ERROR", "tool_name": tool_name,
        "tool_args": {"amount": 2}, "content": {"error": "original reason"},
        "error_stage": "tool_call", "time": "1970-01-01 08:16:50",
        "time_before": 1000.25, "time_after": 1010.5,
    }
    result.update(changes)
    return result


def _replay(app, steps):
    scenario = SimpleNamespace(apps=[app], start_time=1000.0)
    bundle = {
        "scenario_id": "synthetic_record_conversion", "start_time": 1000.0,
        "workflow": {step["name"]: step for step in steps},
    }
    with patch.object(rebatch, "_instantiate_scenario_for_replay", return_value=scenario):
        _, env, info = rebatch._replay_fairy_run_bundle(bundle)
    return env.event_log.list_view(), info


class ErrorRecordConversionTests(unittest.TestCase):
    def test_converter_keeps_legacy_numeric_time_read_type_and_class_name(self):
        app = RecordApp()
        source = _step(tool_name="CustomAppName__observe", op_type="TOOL",
                       tool_args={"z": 7, "a": 3}, content={"value": 1})
        events, info = _replay(app, [source])
        converted = next(iter(workflow_from_event_log(events).values()))
        self.assertEqual((app.calls, info["n_executed"]), (1, 1))
        self.assertEqual(converted["time"], 1000.25)
        self.assertIsInstance(converted["time"], float)
        self.assertEqual(converted["op_type"], "READ")
        self.assertEqual(converted["tool_name"], "RecordApp__observe")
        self.assertEqual(converted["tool_args"], source["tool_args"])
        self.assertEqual(list(converted["tool_args"]), ["z", "a"])
        self.assertEqual(converted["content"], {"value": 1})
        self.assertNotIn("time_before", converted)
        self.assertNotIn("time_after", converted)

    def test_rebatch_keeps_recorded_error_even_when_replayed_method_succeeds(self):
        app = RecordApp()
        source = _step(tool_name="CustomAppName__harvest",
                       tool_args={"start_ridge": 0, "end_ridge": 3})
        events, info = _replay(app, [source])
        self.assertEqual((app.calls, info["n_executed"], info["exec_errors"]), (1, 1, 0))
        self.assertEqual(events[0].metadata.return_value, source["content"])
        # This legacy replay representation is intentionally not redesigned.
        self.assertEqual(events[0].metadata.exception, str(source["content"]))
        self.assertTrue(events[0].failed())
        converted = next(iter(workflow_from_event_log(events).values()))
        self.assertEqual(converted["content"], source["content"])
        self.assertEqual(converted["op_type"], "WRITE")
        self.assertNotIn("error_stage", converted)

    def test_parse_error_skips_rebatch_execution_but_converter_loses_old_label(self):
        app = RecordApp()
        source = _step(error_stage="tool_args_parse", tool_args={})
        events, info = _replay(app, [source])
        self.assertEqual((app.calls, info["n_executed"]), (0, 0))
        self.assertTrue(events[0].failed())
        converted = next(iter(workflow_from_event_log(events).values()))
        self.assertEqual(converted["content"], source["content"])
        self.assertEqual(converted["op_type"], "WRITE")
        self.assertNotIn("error_stage", converted)

    def test_legacy_advance_time_merge_includes_failed_step(self):
        app = SystemApp()
        steps = [
            _step("a", "SystemApp__advance_time", op_type="TOOL", tool_args={"seconds": 10},
                  content={"ok": True}, time_before=1000, time_after=1010),
            _step("b", "SystemApp__advance_time", tool_args={"seconds": 5},
                  time_before=1010, time_after=1010),
            _step("c", "SystemApp__advance_time", op_type="TOOL", tool_args={"seconds": 20},
                  content={"ok": True}, time_before=1010, time_after=1030),
        ]
        events, info = _replay(app, steps)
        self.assertTrue(events[1].failed())
        converted = list(workflow_from_event_log(events).values())
        self.assertEqual((app.calls, info["n_executed"], len(converted)), (3, 3, 1))
        self.assertEqual(converted[0]["tool_args"], {"seconds": 35})
        self.assertEqual(converted[0]["content"], {"ok": True})
        self.assertEqual(converted[0]["time"], 1000.0)
        self.assertNotIn("time_after", converted[0])

    def test_source_string_time_replays_and_scores_with_numeric_converted_time(self):
        args = {"start_ridge": 0, "end_ridge": 3}
        oracle = {"step0": {
            "tool_name": "RecordApp__harvest", "tool_args": args,
            "op_type": "WRITE", "time": 1000.25, "content": {"ok": True},
        }}
        for is_error in (False, True):
            with self.subTest(is_error=is_error):
                app = RecordApp()
                source = _step(tool_name="CustomAppName__harvest", tool_args=args,
                               op_type="TOOL_ERROR" if is_error else "TOOL",
                               content={"error": "original reason"} if is_error else {"ok": True})
                self.assertIsInstance(source["time"], str)
                events, _ = _replay(app, [source])
                agent_workflow = workflow_from_event_log(events)
                self.assertIsInstance(agent_workflow["step0"]["time"], float)
                score = compute_farm_fos(oracle, agent_workflow)
                score_v2 = compute_farm_fos_v2(oracle, agent_workflow)
                self.assertEqual(score.farm_fos, 1.0)
                self.assertEqual(score_v2.farm_fos_v2_path, 1.0)
                self.assertTrue(math.isfinite(score_v2.farm_fos_v2_total))
                self.assertEqual(score_v2.diagnosis.tool_error_returns, int(is_error))
                self.assertEqual(app.calls, 1)

    def test_missing_tools_keep_existing_restore_or_reject_policy(self):
        app = RecordApp()
        for tool_name in ("CustomAppName__missing", "MissingApp__missing"):
            with self.subTest(tool_name=tool_name):
                source = _step(tool_name=tool_name)
                events, info = _replay(app, [source])
                self.assertEqual((app.calls, info["n_restored_error_events"]), (0, 1))
                self.assertTrue(events[0].failed())
                with self.assertRaises(rebatch.ReplayDivergenceError):
                    _replay(app, [_step(tool_name=tool_name, op_type="TOOL", content="ok")])

    def test_engine_keeps_old_execution_status_and_drops_stage_on_rebuild(self):
        app = RecordApp()
        engine = Engine(None, Scenario(apps=[app], start_time=1000))
        workflow = Workflow()
        workflow.add_node(WorkflowStep(**_step(error_stage="tool_args_parse")))
        replayed = engine.replay_workflow(workflow)
        result = replayed.dag["source_name"]
        self.assertEqual(app.calls, 1)
        self.assertEqual(result.op_type, "TOOL_ERROR")
        self.assertIsNone(result.error_stage)
        self.assertIsNone(result.time_before)
        self.assertIsNone(result.time_after)
        self.assertEqual(result.content, {"error": "operation rejected"})
        self.assertEqual(engine.run_log[0]["status"], "ok")
        self.assertIsNone(engine.run_log[0]["error"])


if __name__ == "__main__":
    unittest.main()
