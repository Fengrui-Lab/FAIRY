# agents/agent/base_agent.py

import dataclasses
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Any
from fairy.agents.agent.messages import Messages
from fairy.scenarios.workflow import Workflow, WorkflowStep

# Beijing timezone (UTC+8)
CST = timezone(timedelta(hours=8))

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
        self.run_started_at_wall: float | None = None
        self.run_wall_timeout_seconds: float | None = None

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
        return event

    def chat_completion(self, messages, tools=None):
        """
        Given a conversation history (messages) and an optional list of tools,
        return a response from the language model.

        Args:
            messages (list): A list of message dictionaries representing the conversation history.
            tools (list, optional): A list of tool specifications available for function calling.

        Returns:
            dict: A dictionary containing the model's response, input tokens, output tokens, etc.
        """
        start_time = time.perf_counter()
        normalized_tools = self._jsonable(tools or [])
        tool_names = []
        for tool in normalized_tools:
            function = tool.get("function", {}) if isinstance(tool, dict) else {}
            name = function.get("name")
            if name:
                tool_names.append(name)
        self.record_event(
            "llm_call_start",
            model=getattr(self.llm, "model", None),
            provider=getattr(self.llm, "provider", None),
            message_count=len(messages),
            tool_schema_count=len(tools or []),
            messages=self._jsonable(messages),
            tool_names=tool_names,
        )
        try:
            response = self.llm.chat_completion(messages, tools)
        except Exception as exc:
            elapsed_time = round(time.perf_counter() - start_time, 6)
            self.record_event(
                "llm_call_error",
                status="error",
                wall_time_seconds=elapsed_time,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise
        elapsed_time = round(time.perf_counter() - start_time, 6)
        self.messages.llm_response(response, elapsed_time)
        message = response.choices[0].message
        usage = getattr(response, "usage", None)
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        self.record_event(
            "llm_call_end",
            status="ok",
            wall_time_seconds=elapsed_time,
            tool_call_count=len(getattr(message, "tool_calls", None) or []),
            tokens={
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
                "cached_tokens": getattr(prompt_details, "cached_tokens", 0) if prompt_details else 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
                "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
            },
        )
        return message

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
