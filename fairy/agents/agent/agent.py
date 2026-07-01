# agents/agent/agent.py

import time
import json
import re
from pathlib import Path
from collections import deque, OrderedDict
from datetime import datetime, timezone, timedelta
from typing import Any

CST = timezone(timedelta(hours=8))

from fairy.agents.agent.base_agent import BaseAgent
from fairy.agents.agent.toolset_builder import build_toolset
from fairy.scenarios.workflow import WorkflowStep


class AgentRunLimitExceeded(RuntimeError):
    def __init__(self, limit_type: str, limit_value: float | int):
        self.limit_type = limit_type
        self.limit_value = limit_value
        super().__init__(f"Agent run stopped by {limit_type}: {limit_value}")


class Agent(BaseAgent):

    def __init__(self, name, llm, system_message="", messages=None, toolsets=None):
        """
        Agent extends BaseAgent with function-calling logic.
        
        Args:
            name (str): The agent's name.
            model_client: An instance of an LLM client.
            system_message (str, optional): A system instruction message.
            messages (optional): A Messages instance holding the conversation history.
            toolsets (list, optional): A list of Class objects (e.g., database API) from which agent tools are extracted.
        """
        super().__init__(name, llm, system_message, messages)
        self.tools = None
        self.tool_schemas = None
        self.tools_map = None
        if toolsets is not None:
            self.tools, self.tool_schemas, self.tools_map = \
                build_toolset(toolsets)
        self.tool_call_count = 0
        self.llm_turn_count = 0
        self.stop_reason: str | None = None

    def before_llm_turn(self, task: str) -> str:
        return ""

    def after_llm_message(self, message: Any) -> None:
        return None

    def after_tool_response(self, tool_call: Any, tool_response: Any) -> None:
        return None

    def after_agent_error(self, exc: Exception) -> None:
        return None

    def after_agent_run(self) -> None:
        return None

    def _check_limits(
        self,
        *,
        max_tool_calls: int | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        if max_tool_calls is not None and self.tool_call_count >= max_tool_calls:
            self.stop_reason = "max_tool_calls"
            self.record_event(
                "agent_limit_exceeded",
                status="stopped",
                limit_type="max_tool_calls",
                limit_value=max_tool_calls,
                tool_call_count=self.tool_call_count,
            )
            raise AgentRunLimitExceeded("max_tool_calls", max_tool_calls)
        if (
            timeout_seconds is not None
            and self.run_started_at_wall is not None
            and time.perf_counter() - self.run_started_at_wall >= timeout_seconds
        ):
            self.stop_reason = "timeout"
            self.record_event(
                "agent_limit_exceeded",
                status="stopped",
                limit_type="timeout_seconds",
                limit_value=timeout_seconds,
                elapsed_wall_seconds=round(time.perf_counter() - self.run_started_at_wall, 6),
                tool_call_count=self.tool_call_count,
            )
            raise AgentRunLimitExceeded("timeout_seconds", timeout_seconds)

    def call_function(self, tool_call):

        name = tool_call.function.name
        tool_call_id = tool_call.id
        raw_arguments = tool_call.function.arguments
        try:
            args = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError as exc:
            self.record_event(
                "tool_args_parse_error",
                status="error",
                tool_name=name,
                tool_call_id=tool_call_id,
                raw_arguments=raw_arguments,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise

        # Format environment time
        env_time = self.time_manager.time()
        env_datetime = datetime.fromtimestamp(env_time, tz=CST).strftime("%Y-%m-%d %H:%M:%S")

        self.log(f"[Env Time: {env_datetime}] Calling tool: {name}({args})")
        tool_type = tool_call.type

        # Call corresponding function with provided arguments
        start_time = time.perf_counter()
        message_count_before_tool = len(self.messages.messages)
        self.record_event(
            "tool_call_start",
            status="running",
            tool_name=name,
            tool_call_id=tool_call_id,
            tool_type=tool_type,
            tool_args=args,
        )
        try:
            tool_response = self.tools_map[name](**args)
        except Exception as exc:
            elapsed_time = round(time.perf_counter() - start_time, 6)
            self.record_event(
                "tool_call_error",
                status="error",
                tool_name=name,
                tool_call_id=tool_call_id,
                tool_type=tool_type,
                tool_args=args,
                wall_time_seconds=elapsed_time,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise
        elapsed_time = round(time.perf_counter() - start_time, 6)
        self.tool_call_count += 1

        # If the tool injected notifications into the conversation while it was
        # running, delay them until after the required tool response message.
        deferred_messages = self.messages.messages[message_count_before_tool:]
        if deferred_messages:
            del self.messages.messages[message_count_before_tool:]

        # Add time prefix to tool response
        env_ts = self.env_time_str()
        self.messages.tool_call_response(tool_response, tool_call, elapsed_time, env_ts)
        if deferred_messages:
            self.messages.messages.extend(deferred_messages)
        self.workflow.add_node(WorkflowStep(
            op_type="TOOL",
            tool_name=name,
            tool_args=args,
            content=tool_response,
            time=env_ts)
        )
        self.record_event(
            "tool_call_end",
            status="ok",
            tool_name=name,
            tool_call_id=tool_call_id,
            tool_type=tool_type,
            tool_args=args,
            wall_time_seconds=elapsed_time,
            content_type=type(tool_response).__name__,
            content_preview=str(tool_response)[:500],
        )
        return tool_response

    def run(
        self,
        input,
        *,
        max_tool_calls: int | None = None,
        timeout_seconds: float | None = None,
    ):
        """
        Add the user input to the conversation history, then call chat_completion()
        """
        self.run_started_at_wall = time.perf_counter()
        self.run_wall_timeout_seconds = timeout_seconds
        self.stop_reason = None
        env_ts = self.env_time_str()
        self.record_event(
            "agent_run_start",
            status="running",
            max_tool_calls=max_tool_calls,
            timeout_seconds=timeout_seconds,
        )
        self.messages.user_input(input, time=env_ts)
        self.workflow.add_node(WorkflowStep(op_type="USER", content=input, time=env_ts))

        try:
            while True:

                self._check_limits(max_tool_calls=max_tool_calls, timeout_seconds=timeout_seconds)
                turn_context = self.before_llm_turn(str(input))
                if turn_context.strip():
                    self.messages.system_notify(turn_context, time=self.env_time_str())
                    self.record_event(
                        "controller_context",
                        status="ok",
                        content_preview=turn_context[:1000],
                    )
                message = self.chat_completion(self.messages(), tools=self.tool_schemas)
                self.llm_turn_count += 1
                self.after_llm_message(message)
                if not message.tool_calls:  # if finished handling tool calls, break
                    self.stop_reason = "agent_finished"
                    break

                # === handle tool calls ===
                for tool_call in message.tool_calls:
                    self._check_limits(max_tool_calls=max_tool_calls, timeout_seconds=timeout_seconds)
                    tool_response = self.call_function(tool_call)
                    self.after_tool_response(tool_call, tool_response)
            wall_elapsed = round(time.perf_counter() - self.run_started_at_wall, 6)
            self.after_agent_run()
            self.record_event(
                "agent_run_end",
                status="ok",
                stopped_reason=self.stop_reason,
                wall_time_seconds=wall_elapsed,
                tool_call_count=self.tool_call_count,
                llm_turn_count=self.llm_turn_count,
            )
            return message.content
        except Exception as exc:
            wall_elapsed = round(time.perf_counter() - self.run_started_at_wall, 6)
            if (
                isinstance(exc, AgentRunLimitExceeded)
                and self.stop_reason in {"max_tool_calls", "timeout"}
            ):
                self.after_agent_run()
                self.record_event(
                    "agent_run_end",
                    status="stopped",
                    stopped_reason=self.stop_reason,
                    wall_time_seconds=wall_elapsed,
                    tool_call_count=self.tool_call_count,
                    llm_turn_count=self.llm_turn_count,
                    limit_type=exc.limit_type,
                    limit_value=exc.limit_value,
                )
                raise

            self.after_agent_error(exc)
            self.record_event(
                "agent_run_error",
                status="error",
                stopped_reason=self.stop_reason or "error",
                wall_time_seconds=wall_elapsed,
                tool_call_count=self.tool_call_count,
                llm_turn_count=self.llm_turn_count,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise
