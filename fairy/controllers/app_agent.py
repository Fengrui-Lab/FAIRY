from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fairy.agents.agent.agent import Agent, AgentRunLimitExceeded
from fairy.agents.agent.base_agent import CST
from fairy.agents.agent.messages import Messages
from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.app import App
from fairy.apps.system import SystemApp
from fairy.scenarios.workflow import Workflow
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered


@dataclass
class A2AResult:
    apps: list[Any]
    metadata: dict[str, Any]


class FinalAnswerApp(App):
    def __init__(self) -> None:
        super().__init__(name="FinalAnswerTool")

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def final_answer(self, answer: str) -> str:
        """Return the final answer for an app-agent delegated task."""
        return str(answer)


class AppAgent(App):
    """A FAIRY app wrapper that delegates one app's tools to an expert agent."""

    def __init__(
        self,
        *,
        wrapped_app: App,
        app_agent: Agent,
        app_agent_name: str,
        max_tool_calls: int | None = None,
    ) -> None:
        super().__init__(name=wrapped_app.name)
        self.wrapped_app = wrapped_app
        self.app_agent = app_agent
        self.app_agent_name = app_agent_name
        self.max_tool_calls = max_tool_calls
        self.last_answer: str | None = None
        self.last_tool_call_count: int = 0
        self.last_runtime_events: list[dict[str, Any]] = []

    def register_time_manager(self, time_manager) -> None:
        super().register_time_manager(time_manager)
        self.wrapped_app.register_time_manager(time_manager)
        self.app_agent.set_time_manager(time_manager)

    def register_to_env(self, key: str, add_event) -> None:
        super().register_to_env(key, add_event)
        self.wrapped_app.register_to_env(key, add_event)

    def register_event_scheduler(self, key: str, schedule_event) -> None:
        super().register_event_scheduler(key, schedule_event)
        self.wrapped_app.register_event_scheduler(key, schedule_event)

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def expert_agent(self, task: str) -> str:
        """
        Ask the expert agent for this app to complete a specific task.

        The expert can call the wrapped app's tools and should answer with a
        concise completion summary or call `FinalAnswerTool__final_answer`.
        """
        self.app_agent.set_time_manager(self.time_manager)
        self.app_agent.messages = Messages(
            provider=getattr(self.app_agent.llm, "provider", "openai"),
            system_message=self.app_agent.system_message,
        )
        self.app_agent.workflow = Workflow()
        self.app_agent.runtime_events = []
        self.app_agent.tool_call_count = 0
        self.app_agent.llm_turn_count = 0
        timestamp = self.time_manager.time()
        delegated_task = self._format_delegated_user_message(str(task), timestamp)
        try:
            answer = self.app_agent.run(delegated_task, max_tool_calls=self.max_tool_calls)
        except AgentRunLimitExceeded as exc:
            answer = (
                "Expert agent stopped before completing the delegated task "
                f"because it reached {exc.limit_type}={exc.limit_value}. "
                "Treat this result as partial and verify completion before continuing."
            )
            self.app_agent.record_event(
                "a2a_expert_limit_returned",
                status="stopped",
                limit_type=exc.limit_type,
                limit_value=exc.limit_value,
                answer=answer,
            )
        finally:
            self.last_tool_call_count = int(getattr(self.app_agent, "tool_call_count", 0))
            self.last_runtime_events = list(getattr(self.app_agent, "runtime_events", []))
        self.last_answer = str(answer)
        return self.last_answer

    def _format_delegated_user_message(self, task: str, timestamp: float) -> str:
        timestamp_str = datetime.fromtimestamp(timestamp, tz=CST).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        return (
            f"Received at: {timestamp_str}\n"
            "Sender: User\n"
            f"Message: {task}\n"
            "Already read: True\n"
            f"Read at: {timestamp_str}"
        )


class SharedTraceAppAgent(AppAgent):
    """AppAgent whose expert writes into the main agent's run.

    The plain AppAgent gives every delegation a new workflow and drops it, so
    the real farm actions are lost and the run cannot be replayed or scored.
    Here the expert's tool calls land in the main workflow, its events in the
    main runtime log, and its actions count toward the main action limit (a
    delegation itself costs nothing). Works for LLM and Jev experts.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.main_agent: Agent | None = None
        self.jobs: list[dict[str, Any]] = []
        self.all_runtime_metrics: list[dict[str, Any]] = []

    def get_tools(self):
        tools = super().get_tools()
        describe = getattr(self.app_agent, "describe_tools", None)
        if describe is not None:
            for tool in tools:
                tool.function_description = f"{tool.function_description}\n\n{describe()}"
        return tools

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def expert_agent(self, task: str) -> str:
        """
        Hand one job to the expert for this app.

        The expert acts on the farm with this app's tools and returns what it did.
        """
        main = self.main_agent
        if main is None:
            raise RuntimeError("SharedTraceAppAgent needs main_agent; see attach_main_agent")
        expert = self.app_agent
        expert.set_time_manager(self.time_manager)
        expert.messages = Messages(
            provider=getattr(expert.llm, "provider", "openai"),
            system_message=expert.system_message,
        )
        expert.workflow = main.workflow
        expert.runtime_events = main.runtime_events
        expert.runtime_event_sink = main.runtime_event_sink
        expert.tool_call_count = 0
        expert.llm_turn_count = 0
        if hasattr(expert, "start_job"):
            expert.start_job()
        else:
            task = self._format_delegated_user_message(str(task), self.time_manager.time())
        timeout = None
        if main.run_wall_timeout_seconds is not None and main.run_started_at_wall is not None:
            timeout = main.run_wall_timeout_seconds - (time.perf_counter() - main.run_started_at_wall)
        limit = None
        try:
            answer = expert.run(str(task), max_tool_calls=self.max_tool_calls, timeout_seconds=timeout)
        except AgentRunLimitExceeded as exc:
            limit = exc.limit_type
            answer = (
                f"Expert agent stopped because it reached {exc.limit_type}={exc.limit_value}. "
                "Treat this result as partial and verify completion before continuing."
            )
        finally:
            main.tool_call_count += max(0, expert.tool_call_count - 1)
            self.all_runtime_metrics.extend(expert.messages.runtime_metrics)
        result = expert.job_report(limit) if hasattr(expert, "job_report") else str(answer)
        self.last_answer = result
        self.last_tool_call_count = expert.tool_call_count
        self.jobs.append(
            {
                "task": str(task),
                "actions": expert.tool_call_count,
                "limit": limit,
                **(expert.job_summary() if hasattr(expert, "job_summary") else {}),
            }
        )
        return result

    def trace(self) -> dict[str, Any]:
        return {
            "wrapper_app_name": self.name,
            "wrapped_app_name": getattr(self.wrapped_app, "name", self.wrapped_app.__class__.__name__),
            "wrapped_app_class": self.wrapped_app.__class__.__name__,
            "app_agent": self.app_agent_name,
            "max_tool_calls": self.max_tool_calls,
            "last_answer": self.last_answer,
            "job_count": len(self.jobs),
            "tool_call_count": sum(j["actions"] for j in self.jobs),
            "llm_turn_count": 0,
            "jobs": self.jobs,
            "runtime_metrics": self.all_runtime_metrics,
        }


def attach_main_agent(apps: list[Any], agent: Agent) -> None:
    """Link shared-trace wrappers to the main agent, once it exists."""
    for app in apps:
        if isinstance(app, SharedTraceAppAgent):
            app.main_agent = agent


def collect_a2a_traces(apps: list[Any]) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    for app in apps:
        if not isinstance(app, AppAgent):
            continue
        if isinstance(app, SharedTraceAppAgent) and app.main_agent is not None:
            traces.append(app.trace())
            continue
        traces.append(
            {
                "wrapper_app_name": app.name,
                "wrapped_app_name": getattr(app.wrapped_app, "name", app.wrapped_app.__class__.__name__),
                "wrapped_app_class": app.wrapped_app.__class__.__name__,
                "app_agent": app.app_agent_name,
                "max_tool_calls": app.max_tool_calls,
                "last_answer": app.last_answer,
                "tool_call_count": int(getattr(app.app_agent, "tool_call_count", 0)),
                "llm_turn_count": int(getattr(app.app_agent, "llm_turn_count", 0)),
                "runtime_events": list(getattr(app.app_agent, "runtime_events", [])),
                "messages": list(getattr(app.app_agent.messages, "messages", [])),
                "runtime_metrics": list(getattr(app.app_agent.messages, "runtime_metrics", [])),
                "workflow": app.app_agent.workflow.to_dict(),
            }
        )
    return traces


_A2A_TYPED_APP_AGENT_BY_CLASS: dict[str, str] = {
    "WeatherApp": "weather_expert_app_agent",
    "SensorApp": "sensor_expert_app_agent",
    "TractorApp": "machinery_expert_app_agent",
    "FieldOpsApp": "machinery_expert_app_agent",
    "FarmWorldApp": "operations_expert_app_agent",
    "DroneApp": "operations_expert_app_agent",
    "RobotApp": "operations_expert_app_agent",
}


def resolve_a2a_agent_name_for_app(
    app: Any,
    *,
    policy: str = "generic",
    fallback_app_agent: str = "default_app_agent",
) -> str:
    if policy == "typed_experts":
        return _A2A_TYPED_APP_AGENT_BY_CLASS.get(
            app.__class__.__name__,
            fallback_app_agent,
        )
    return fallback_app_agent


def apply_a2a_to_apps(
    apps: list[Any],
    *,
    llm_factory,
    app_agent_builder,
    app_agent_config_builder,
    app_prop: float,
    policy: str = "generic",
    app_agent_name: str = "default_app_agent",
    seed: int = 0,
    max_tool_calls: int | None = None,
    wrapper_class: type[AppAgent] = AppAgent,
) -> A2AResult:
    if app_prop <= 0:
        return A2AResult(
            apps=list(apps),
            metadata={
                "enabled": False,
                "app_prop": float(app_prop),
                "policy": policy,
                "app_agent": app_agent_name,
                "transformed_apps": [],
            },
        )

    filtered_apps = [
        app
        for app in apps
        if getattr(app, "name", "") not in {"InternalContacts", "AgentUserInterface", "SystemApp"}
        and not isinstance(app, (AgentUserInterface, SystemApp))
    ]
    if not filtered_apps:
        raise ValueError("No valid apps available for A2A after filtering.")

    bounded_prop = max(0.0, min(1.0, float(app_prop)))
    num_apps_to_transform = int(len(filtered_apps) * bounded_prop)
    if num_apps_to_transform <= 0:
        return A2AResult(
            apps=list(apps),
            metadata={
                "enabled": False,
                "app_prop": bounded_prop,
                "policy": policy,
                "app_agent": app_agent_name,
                "transformed_apps": [],
            },
        )

    rng = random.Random(seed)
    apps_to_transform = rng.sample(filtered_apps, num_apps_to_transform)
    transformed_set = set(apps_to_transform)
    new_apps = [app for app in apps if app not in transformed_set]
    transformed_metadata: list[dict[str, Any]] = []

    for app in apps_to_transform:
        resolved_app_agent_name = resolve_a2a_agent_name_for_app(
            app,
            policy=policy,
            fallback_app_agent=app_agent_name,
        )
        config = app_agent_config_builder.build(resolved_app_agent_name)
        expert_agent = app_agent_builder.build(
            config,
            llm=llm_factory(),
            app=app,
        )
        wrapper_max_tool_calls = config.max_iterations
        if max_tool_calls is not None:
            wrapper_max_tool_calls = min(config.max_iterations, max_tool_calls)
        wrapper = wrapper_class(
            wrapped_app=app,
            app_agent=expert_agent,
            app_agent_name=resolved_app_agent_name,
            max_tool_calls=wrapper_max_tool_calls,
        )
        new_apps.append(wrapper)
        transformed_metadata.append(
            {
                "app_name": getattr(app, "name", app.__class__.__name__),
                "app_class": app.__class__.__name__,
                "wrapper_app_name": wrapper.name,
                "app_agent": resolved_app_agent_name,
            }
        )

    return A2AResult(
        apps=new_apps,
        metadata={
            "enabled": True,
            "app_prop": bounded_prop,
            "policy": policy,
            "app_agent": app_agent_name,
            "transformed_apps": transformed_metadata,
        },
    )
