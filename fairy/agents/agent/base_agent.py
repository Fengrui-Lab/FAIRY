# agents/agent/base_agent.py

import copy
import dataclasses
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fairy.agents.agent.messages import Messages
from fairy.scenarios.workflow import Workflow, WorkflowStep

# Beijing timezone (UTC+8)
CST = timezone(timedelta(hours=8))


class RetryableLLMResponseError(RuntimeError):
    def __init__(
        self,
        reason: str,
        finish_reason: str | None,
        *,
        llm_call_id: str | None = None,
    ):
        self.reason = reason
        self.finish_reason = finish_reason
        self.llm_call_id = llm_call_id
        super().__init__(f"LLM response rejected: {reason} (finish_reason={finish_reason!r})")


class BaseAgent:
    def __init__(self, name, llm, system_message=None, messages=None):
        """
        Minimal BaseAgent which holds basic parameters.
        
        Args:
            name (str): The agent's name.
            llm: An LLM client instance.
            tools (list, optional): List of tool functions available.
            system_message (str, optional): Instructional system message.
        """
        self.name = name
        self.llm = llm
        self.system_message = system_message
        self.messages = messages if messages is not None else Messages(provider=llm.provider, system_message=system_message)
        self.time_manager = None
        self.workflow = Workflow()
        self.runtime_events: list[dict[str, Any]] = []
        self.runtime_event_sink = None
        self.run_started_at_wall: float | None = None
        self.run_wall_timeout_seconds: float | None = None
        self._llm_request_count = 0
        self._pending_llm_feedback: tuple[str, dict[str, str]] | None = None

    def reset_llm_feedback(self) -> None:
        """Prevent feedback from an earlier run from reaching a new run."""
        self._pending_llm_feedback = None

    def log(self, message):
        print(f"[{self.name}] {message}")

    def record_event(self, event_type: str, **payload: Any) -> dict[str, Any]:
        event = {
            "event_index": len(self.runtime_events),
            "event_type": event_type,
            "agent": self.name,
            "wall_timestamp": datetime.now(tz=CST).isoformat(),
            "sim_time": self.env_time_str(),
            **payload,
        }
        self.runtime_events.append(event)
        sink = self.runtime_event_sink
        if sink is not None:
            try:
                sink(dict(event))
            except Exception as exc:
                # Observability must never change agent execution semantics.
                self.runtime_event_sink = None
                self.log(
                    "WARNING: live runtime event sink disabled after "
                    f"{type(exc).__name__}: {exc}"
                )
        return event

    def llm_config(self) -> dict[str, Any]:
        # Allowlist effective client settings; never serialize credentials/params.
        sdk_client = getattr(self.llm, "api_client", None)
        return {
            "provider": getattr(self.llm, "provider", None),
            "model": getattr(self.llm, "model", None),
            "temperature": getattr(self.llm, "temperature", None),
            "base_url": str(self.llm.base_url) if getattr(self.llm, "base_url", None) else None,
            "request_timeout_seconds": getattr(self.llm, "request_timeout", None),
            "max_output_tokens": getattr(self.llm, "max_output_tokens", None),
            "parallel_tool_calls": getattr(self.llm, "parallel_tool_calls", None),
            "enable_thinking_override": getattr(self.llm, "enable_thinking", None),
            **({"thinking": self.llm.thinking}
               if getattr(self.llm, "provider", None) == "deepseek"
               and hasattr(self.llm, "thinking") else {}),
            **({"preserve_thinking": self.llm.preserve_thinking}
               if getattr(self.llm, "provider", None) == "qwen"
               and getattr(self.llm, "preserve_thinking", None) is not None else {}),
            "sdk_max_retries": getattr(sdk_client, "max_retries", None),
            "reasoning_history_policy": "preserve" if self._preserve_reasoning_history() else "exclude",
        }

    def _preserve_reasoning_history(self) -> bool:
        if getattr(self.llm, "provider", None) == "deepseek":
            return getattr(self.llm, "thinking", "disabled") == "enabled"
        return (
            getattr(self.llm, "provider", None) == "qwen"
            and getattr(self.llm, "preserve_thinking", False) is True
        )

    def chat_completion(self, messages, tools=None):
        """Log and account for a reply, accepting only usable, untruncated messages."""
        start_time = time.perf_counter()
        llm_messages = self._llm_compatible_messages(messages)
        normalized_tools = self._jsonable(tools or [])
        tool_names = []
        for tool in normalized_tools:
            function = tool.get("function", {}) if isinstance(tool, dict) else {}
            name = function.get("name")
            if name:
                tool_names.append(name)
        # Construct a send-only view. Rejected replies and their feedback never
        # become conversation history or workflow steps.
        pending_feedback = self._pending_llm_feedback
        feedback_metadata: dict[str, Any] = {}
        if pending_feedback is not None:
            source_call_id, feedback = pending_feedback
            llm_messages.append({
                "role": "system",
                "content": json.dumps(feedback, ensure_ascii=False),
            })
            feedback_metadata["feedback_for_llm_call_id"] = source_call_id
        client_completion = self.llm.chat_completion
        self._llm_request_count += 1
        llm_call_id = f"llm_call_{self._llm_request_count}"
        self.record_event(
            "llm_call_start",
            llm_call_id=llm_call_id,
            model=getattr(self.llm, "model", None),
            provider=getattr(self.llm, "provider", None),
            max_output_tokens=getattr(self.llm, "max_output_tokens", None),
            parallel_tool_calls=getattr(self.llm, "parallel_tool_calls", None),
            enable_thinking_override=getattr(self.llm, "enable_thinking", None),
            reasoning_history_policy="preserve" if self._preserve_reasoning_history() else "exclude",
            llm_config=self.llm_config(),
            message_count=len(llm_messages),
            tool_schema_count=len(tools or []),
            messages=self._jsonable(llm_messages),
            tool_names=tool_names,
            **feedback_metadata,
        )
        # Consume at the actual client boundary, not on a successful response.
        # Preparation/logging failures above leave the pending feedback intact;
        # a network failure below must not resend it on the following attempt.
        self._pending_llm_feedback = None
        try:
            response = client_completion(llm_messages, tools)
        except Exception as exc:
            elapsed_time = round(time.perf_counter() - start_time, 6)
            self.record_event(
                "llm_call_error",
                llm_call_id=llm_call_id,
                status="error",
                wall_time_seconds=elapsed_time,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise
        elapsed_time = round(time.perf_counter() - start_time, 6)
        choice = response.choices[0] if response.choices else None
        raw_message = getattr(choice, "message", None)
        raw_tool_calls = list(getattr(raw_message, "tool_calls", None) or [])
        finish_reason = getattr(choice, "finish_reason", None)
        rejection_reason = self._response_rejection_reason(raw_message, finish_reason)
        agent_feedback = (
            self._response_error_feedback(rejection_reason) if rejection_reason else None
        )
        # Rejected replies are logged/accounted for but never become history
        # or executable tool calls, including partially generated tool calls.
        message = (
            raw_message if rejection_reason
            else self._enforce_tool_call_policy(raw_message, raw_tool_calls)
        )
        self.messages.llm_response(
            response, elapsed_time, message=message,
            add_to_history=rejection_reason is None,
            llm_call_id=llm_call_id,
            rejection_reason=rejection_reason,
        )
        self._record_llm_response(
            response, message, elapsed_time, rejection_reason,
            llm_call_id=llm_call_id, agent_feedback=agent_feedback,
        )
        if rejection_reason:
            self._pending_llm_feedback = (llm_call_id, agent_feedback)
            raise RetryableLLMResponseError(
                rejection_reason, finish_reason, llm_call_id=llm_call_id,
            )
        return message

    @staticmethod
    def _response_rejection_reason(message: Any, finish_reason: str | None) -> str | None:
        if finish_reason == "length":
            return "output_truncated"
        has_content = bool(str(getattr(message, "content", None) or "").strip())
        if not has_content and not getattr(message, "tool_calls", None):
            return "empty_response"
        return None

    @staticmethod
    def _response_error_feedback(reason: str) -> dict[str, str]:
        descriptions = {
            "empty_response": (
                "Previous response was empty: no usable text or tool calls were returned. "
                "Generate a complete response or valid tool call."
            ),
            "output_truncated": (
                "Previous response was truncated at the output token limit. "
                "No tool calls from that response were executed. "
                "Generate a shorter, complete response."
            ),
        }
        return {"error": descriptions.get(reason, f"Previous response was rejected: {reason}.")}

    def _record_llm_response(
        self, response: Any, message: Any, elapsed_time: float, rejection_reason: str | None,
        *, llm_call_id: str | None = None, agent_feedback: dict[str, str] | None = None,
    ) -> None:
        choice = response.choices[0] if response.choices else None
        raw_message = getattr(choice, "message", None)
        finish_reason = getattr(choice, "finish_reason", None)
        assistant_content = getattr(message, "content", None)
        tool_calls = self._tool_call_details(getattr(message, "tool_calls", None) or [])
        raw_tool_call_details = self._tool_call_details(getattr(raw_message, "tool_calls", None) or [])
        usage = getattr(response, "usage", None)
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        self.record_event(
            "llm_call_end",
            llm_call_id=llm_call_id,
            status="rejected" if rejection_reason else "ok",
            accepted=rejection_reason is None,
            rejection_reason=rejection_reason,
            wall_time_seconds=elapsed_time,
            finish_reason=finish_reason,
            usage=self._jsonable(usage),
            assistant_content=assistant_content,
            assistant_content_is_empty=not bool(str(assistant_content or "").strip()),
            rationale=assistant_content,  # Legacy alias for content, not reasoning.
            rationale_source="assistant_content" if assistant_content else "empty_assistant_content",
            tool_call_count=len(tool_calls),
            tool_calls=tool_calls,
            raw_tool_call_count=len(raw_tool_call_details),
            raw_tool_calls=raw_tool_call_details,
            dropped_tool_call_count=len(raw_tool_call_details) - len(tool_calls),
            tokens={
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
                "cached_tokens": getattr(prompt_details, "cached_tokens", 0) if prompt_details else 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
                "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
            },
            **({"agent_feedback": dict(agent_feedback)} if agent_feedback is not None else {}),
        )

    def _enforce_tool_call_policy(self, message: Any, tool_calls: list[Any]) -> Any:
        parallel_allowed = bool(getattr(self.llm, "parallel_tool_calls", True))
        if parallel_allowed or len(tool_calls) <= 1:
            return message

        effective_tool_calls = tool_calls[:1]
        if hasattr(message, "model_copy"):
            normalized = message.model_copy(update={"tool_calls": effective_tool_calls})
        elif dataclasses.is_dataclass(message):
            normalized = dataclasses.replace(message, tool_calls=effective_tool_calls)
        elif isinstance(message, dict):
            normalized = {**message, "tool_calls": effective_tool_calls}
        else:
            normalized = copy.copy(message)
            setattr(normalized, "tool_calls", effective_tool_calls)

        self.record_event(
            "parallel_tool_call_violation",
            status="normalized",
            policy="keep_first",
            raw_tool_call_count=len(tool_calls),
            effective_tool_call_count=1,
            kept_tool_call=self._tool_call_details(effective_tool_calls)[0],
            dropped_tool_calls=self._tool_call_details(tool_calls[1:]),
        )
        return normalized

    def _tool_call_details(self, tool_calls: list[Any]) -> list[dict[str, Any]]:
        details: list[dict[str, Any]] = []
        for tool_call in tool_calls:
            function = getattr(tool_call, "function", None)
            details.append(
                {
                    "id": getattr(tool_call, "id", None),
                    "type": getattr(tool_call, "type", None),
                    "function": {
                        "name": getattr(function, "name", None),
                        "arguments": getattr(function, "arguments", None),
                    },
                }
            )
        return self._jsonable(details)

    def _llm_compatible_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        allowed_keys = {
            "role",
            "content",
            "name",
            "tool_call_id",
            "tool_calls",
            "function_call",
        }
        compatible_messages: list[dict[str, Any]] = []
        preserve_reasoning = self._preserve_reasoning_history()
        for message in messages:
            jsonable_message = self._jsonable(message)
            if isinstance(jsonable_message, dict):
                compatible = {
                    key: value
                    for key, value in jsonable_message.items()
                    if key in allowed_keys and value is not None
                }
                if (
                    preserve_reasoning
                    and jsonable_message.get("role") == "assistant"
                    and jsonable_message.get("reasoning_content") is not None
                ):
                    compatible["reasoning_content"] = jsonable_message["reasoning_content"]
                if compatible:
                    compatible_messages.append(compatible)
                continue
            compatible_messages.append({"role": "assistant", "content": str(jsonable_message)})
        return compatible_messages

    def _jsonable(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(k): self._jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._jsonable(v) for v in value]
        if dataclasses.is_dataclass(value):
            return self._jsonable(dataclasses.asdict(value))
        if hasattr(value, "model_dump"):
            try:
                return self._jsonable(value.model_dump())
            except Exception:
                pass
        if hasattr(value, "dict"):
            try:
                return self._jsonable(value.dict())
            except Exception:
                pass
        try:
            return self._jsonable(json.loads(json.dumps(value)))
        except Exception:
            return str(value)

    def env_time_str(self):
        if self.time_manager:
            t = self.time_manager.time()
            return datetime.fromtimestamp(t, tz=CST).strftime("%Y-%m-%d %H:%M:%S")
        return None

    def set_time_manager(self, time_manager):
        self.time_manager = time_manager
