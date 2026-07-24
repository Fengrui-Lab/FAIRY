# agents/agent/agent.py

import time
import json
import re
import os
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


class RecoverableToolCallError(RuntimeError):
    def __init__(self, original: Exception, tool_name: str, tool_call_id: str):
        self.original = original
        self.tool_name = tool_name
        self.tool_call_id = tool_call_id
        super().__init__(f"{type(original).__name__}: {original}")


def _is_rate_limit_error(error: Exception) -> bool:
    text = f"{type(error).__name__}: {error}".lower()
    return (
        "ratelimiterror" in text
        or "rate limit" in text
        or "too many requests" in text
        or "error code: 429" in text
        or "http/1.1 429" in text
        or "status code: 429" in text
    )


class Agent(BaseAgent):

    def __init__(
        self,
        name,
        llm,
        system_message="",
        messages=None,
        toolsets=None,
        hidden_tool_names: set[str] | frozenset[str] | None = None,
    ):
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
                build_toolset(toolsets, excluded_tool_names=hidden_tool_names)
        self.tool_call_count = 0
        self.llm_turn_count = 0
        self.stop_reason: str | None = None
        self.max_llm_call_retries = int(os.getenv("FAIRY_AGENT_LLM_CALL_RETRIES", "5"))
        self.llm_retry_sleep_seconds = float(os.getenv("FAIRY_AGENT_LLM_RETRY_SLEEP_S", "0"))
        self.rate_limit_retry_sleep_seconds = float(
            os.getenv("FAIRY_AGENT_RATE_LIMIT_SLEEP_S", "30")
        )

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
        tool_type = tool_call.type
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
            self.tool_call_count += 1
            self._append_tool_error_observation(
                tool_call=tool_call,
                tool_name=name,
                tool_type=tool_type,
                tool_args={},
                raw_arguments=raw_arguments,
                exc=exc,
                elapsed_time=0.0,
                error_stage="tool_args_parse",
            )
            raise RecoverableToolCallError(exc, name, tool_call_id) from exc

        # Record exact simulation time on both sides of the tool call.  The
        # human-readable ``time`` field remains the post-call timestamp for
        # backward compatibility with existing workflow consumers.
        env_time_before = self.time_manager.time()
        env_datetime = datetime.fromtimestamp(env_time_before, tz=CST).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        self.log(f"[Env Time: {env_datetime}] Calling tool: {name}({args})")

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
            self.tool_call_count += 1
            self._append_tool_error_observation(
                tool_call=tool_call,
                tool_name=name,
                tool_type=tool_type,
                tool_args=args,
                raw_arguments=raw_arguments,
                exc=exc,
                elapsed_time=elapsed_time,
                error_stage="tool_call",
                time_before=env_time_before,
            )
            raise RecoverableToolCallError(exc, name, tool_call_id) from exc
        elapsed_time = round(time.perf_counter() - start_time, 6)
        self.tool_call_count += 1

        # If the tool injected notifications into the conversation while it was
        # running, delay them until after the required tool response message.
        deferred_messages = self.messages.messages[message_count_before_tool:]
        if deferred_messages:
            del self.messages.messages[message_count_before_tool:]

        # Add time prefix to tool response
        env_time_after = self.time_manager.time()
        env_ts = datetime.fromtimestamp(env_time_after, tz=CST).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        self.messages.tool_call_response(tool_response, tool_call, elapsed_time, env_ts)
        if deferred_messages:
            self.messages.messages.extend(deferred_messages)
        self.workflow.add_node(WorkflowStep(
            op_type="TOOL",
            tool_name=name,
            tool_args=args,
            content=tool_response,
            time=env_ts,
            time_before=env_time_before,
            time_after=env_time_after,
        )
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

    def _append_tool_error_observation(
        self,
        *,
        tool_call: Any,
        tool_name: str,
        tool_type: str,
        tool_args: dict[str, Any],
        raw_arguments: str,
        exc: Exception,
        elapsed_time: float,
        error_stage: str,
        time_before: float | None = None,
    ) -> None:
        env_time_after = self.time_manager.time()
        env_ts = datetime.fromtimestamp(env_time_after, tz=CST).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        error_text = (
            f"[OUTPUT OF TOOL {tool_name}] ERROR:\n"
            "***\n"
            f"{type(exc).__name__}: {exc}\n"
            f"Raw arguments: {raw_arguments}\n"
            "***\n\n"
            "Now retry with valid arguments or choose a different tool. "
            "Do not repeat the same invalid call."
        )
        self.messages.messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": error_text,
                "time": env_ts,
            }
        )
        self.messages.runtime_metrics.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "time": elapsed_time,
                "status": "error",
            }
        )
        self.workflow.add_node(
            WorkflowStep(
                op_type="TOOL_ERROR",
                tool_name=tool_name,
                tool_args=tool_args,
                content=error_text,
                time=env_ts,
                time_before=(
                    float(time_before) if time_before is not None else env_time_after
                ),
                time_after=env_time_after,
            )
        )
        self.record_event(
            "tool_error_observation",
            status="ok",
            tool_name=tool_name,
            tool_call_id=tool_call.id,
            tool_type=tool_type,
            tool_args=tool_args,
            error_stage=error_stage,
            error_type=type(exc).__name__,
            error_message=str(exc),
            content_preview=error_text[:500],
        )

    def _chat_completion_with_retries(self, messages, tools=None):
        attempt = 0
        while True:
            try:
                return self.chat_completion(messages, tools=tools)
            except Exception as exc:
                if attempt >= self.max_llm_call_retries:
                    raise
                attempt += 1
                sleep_seconds = self._llm_retry_sleep_for_error(exc)
                self.record_event(
                    "llm_call_retry",
                    status="retrying",
                    attempt=attempt,
                    max_retries=self.max_llm_call_retries,
                    sleep_seconds=sleep_seconds,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)

    def _llm_retry_sleep_for_error(self, exc: Exception) -> float:
        if _is_rate_limit_error(exc):
            return max(0.0, self.rate_limit_retry_sleep_seconds)
        return max(0.0, self.llm_retry_sleep_seconds)

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
                message = self._chat_completion_with_retries(
                    self.messages(), tools=self.tool_schemas
                )
                self.llm_turn_count += 1
                self.after_llm_message(message)
                if not message.tool_calls:  # if finished handling tool calls, break
                    self.stop_reason = "agent_finished"
                    break

                # === handle tool calls ===
                for tool_call in message.tool_calls:
                    self._check_limits(max_tool_calls=max_tool_calls, timeout_seconds=timeout_seconds)
                    try:
                        tool_response = self.call_function(tool_call)
                    except RecoverableToolCallError as exc:
                        self.after_agent_error(exc.original)
                        continue
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
