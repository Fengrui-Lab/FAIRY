from __future__ import annotations

import inspect
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from threading import Thread
from typing import Any

from fairy.agents.agent.toolset_builder import build_toolset
from fairy.apps.system import SystemApp
from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.scenarios.workflow import Workflow, WorkflowStep
from fairy.time_manager import TimeManager

CST = timezone(timedelta(hours=8))


@dataclass
class EngineEnvironment:
    scenario: Any
    workflow: Workflow
    apps: list[Any]
    time_manager: TimeManager
    engine: "Engine"

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": getattr(self.scenario, "scenario_id", ""),
            "workflow_steps": len(self.workflow),
            "apps": [getattr(app, "name", app.__class__.__name__) for app in self.apps],
            "current_time": self.time_manager.time(),
        }


class Engine:
    engine_name: str = "fairy_engine"

    def __init__(self, agent: Any | None, scenario: Any):
        self.time_manager = TimeManager()
        self.start_time = scenario.start_time if scenario.start_time is not None else 0.0
        self.time_manager.reset(start_time=self.start_time)
        self.current_time = self.time_manager.time()
        self.agent = agent
        self.run_log: list[dict[str, Any]] = []
        self.token_usage: dict[str, Any] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "source": "not_applicable_without_llm",
        }
        if self.agent is not None:
            self.agent.set_time_manager(self.time_manager)
        self.scenario = scenario
        self._ensure_scenario_state()
        self._register_scenario_apps()
        self.time_increment_in_seconds = (
            scenario.time_increment_in_seconds
            if scenario.time_increment_in_seconds is not None
            else 1
        )

    def _ensure_scenario_state(self) -> None:
        if self.scenario.apps is None:
            self.scenario.apps = []
        if getattr(self.scenario, "dynamic_events", None) is None:
            self.scenario.dynamic_events = []
        if getattr(self.scenario, "workflow", None) is None:
            self.scenario.workflow = Workflow()

    def _register_scenario_apps(self) -> None:
        farm_world = None
        for app in self.scenario.apps or []:
            candidate = getattr(app, "wrapped_app", app)
            if candidate.__class__.__name__ == "FarmWorldApp":
                farm_world = candidate
                break
        for app in self.scenario.apps or []:
            app.register_time_manager(self.time_manager)
            if hasattr(app, "register_event_scheduler"):
                app.register_event_scheduler("engine", self.schedule_dynamic_event)
            if isinstance(app, SystemApp):
                app.wait_for_next_notification = self.wait_for_next_notification
                if farm_world is not None:
                    app.attach_farm_world_app(farm_world)

    def schedule_dynamic_event(self, event: Any) -> None:
        self.scenario.dynamic_events.append(event)

    def _next_dynamic_event(self):
        pending = [e for e in self.scenario.dynamic_events or [] if not e.triggered]
        return min(pending, key=lambda e: e.time_start) if pending else None

    def _env_time_str(self) -> str:
        t = self.time_manager.time()
        return self._format_timestamp(t)

    def _format_timestamp(self, timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, tz=CST).strftime("%Y-%m-%d %H:%M:%S")

    def environment(self, workflow: Workflow | None = None) -> EngineEnvironment:
        return EngineEnvironment(
            scenario=self.scenario,
            workflow=workflow or self.scenario.workflow or Workflow(),
            apps=list(self.scenario.apps or []),
            time_manager=self.time_manager,
            engine=self,
        )

    def _trigger_dynamic_event(self, event: Any) -> None:
        self.current_time = self.time_manager.time()
        event.start(self.current_time)
        message = event.step()
        time_str = self._env_time_str()
        if self.agent is not None:
            self.agent.messages.system_notify(message, time=time_str)
            self.agent.workflow.add_node(
                WorkflowStep(op_type="system", content=message, time=time_str)
            )
        event.triggered = True

    def wait_for_next_notification(self) -> None:
        system_app = next(
            (app for app in self.scenario.apps or [] if isinstance(app, SystemApp)), None
        )
        assert system_app is not None, "System app not found"
        wait_timeout = system_app.wait_for_notification_timeout
        assert wait_timeout is not None, "Wait for notification timeout not set"
        timeout_timestamp = wait_timeout.timeout_timestamp
        next_event = self._next_dynamic_event()
        next_event_time = next_event.time_start if next_event is not None else None
        if next_event_time is None or next_event_time > timeout_timestamp:
            jump_time = timeout_timestamp - self.time_manager.time()
            if jump_time > 0:
                self.time_manager.add_offset(jump_time)
            system_app.reset_wait_for_notification_timeout()
            return
        jump_time = next_event_time - self.time_manager.time()
        if jump_time > 0:
            self.time_manager.add_offset(jump_time)
        self._trigger_dynamic_event(next_event)
        system_app.reset_wait_for_notification_timeout()

    def run_scenario_agent(
        self,
        *,
        max_tool_calls: int | None = None,
        timeout_seconds: float | None = None,
        setup_scenario: bool = True,
    ):
        if setup_scenario:
            self.scenario.setup()
            self._register_scenario_apps()
        assert self.agent is not None, "Agent run requires an agent"
        self._apply_scenario_system_prompt()
        agent_task = self._resolve_agent_task()
        self.agent.run(
            input=agent_task,
            max_tool_calls=max_tool_calls,
            timeout_seconds=timeout_seconds,
        )
        return self.agent.workflow

    def _apply_scenario_system_prompt(self) -> None:
        additional_system_prompt = getattr(self.scenario, "additional_system_prompt", None)
        if not additional_system_prompt or self.agent is None:
            return
        messages = getattr(getattr(self.agent, "messages", None), "messages", [])
        if not messages:
            return
        first_message = messages[0]
        if not isinstance(first_message, dict) or first_message.get("role") != "system":
            return
        content = str(first_message.get("content") or "")
        if additional_system_prompt in content:
            return
        first_message["content"] = f"{content}\n\n{additional_system_prompt}"

    def _resolve_agent_task(self) -> str:
        event_task = self._agent_briefing_from_events()
        if event_task:
            if self.agent is not None and hasattr(self.agent, "record_event"):
                self.agent.record_event(
                    "agent_task_source",
                    status="ok",
                    source="event_briefing",
                    content_preview=event_task[:1000],
                )
            return event_task
        scenario_input = str(getattr(self.scenario, "scenario_input", "") or "")
        if self.agent is not None and hasattr(self.agent, "record_event"):
            self.agent.record_event(
                "agent_task_source",
                status="ok",
                source="scenario_input",
                content_preview=scenario_input[:1000],
            )
        return scenario_input

    def _agent_briefing_from_events(self) -> str:
        for event in getattr(self.scenario, "events", []) or []:
            app = getattr(event, "app", None)
            function = getattr(event, "function", None)
            app_name = getattr(app, "name", app.__class__.__name__ if app is not None else "")
            function_name = getattr(function, "__name__", "")
            if app_name != "AgentUserInterface" or function_name != "send_message_to_agent":
                continue
            kwargs = getattr(event, "kwargs", {}) or {}
            content = kwargs.get("content")
            if content is None:
                args = getattr(event, "args", ()) or ()
                content = args[0] if args else None
            text = str(content or "").strip()
            if text:
                return text
        return ""

    def run_scenario_oracle(self, run_oracle: bool = True, **setup_kwargs: Any):
        self.scenario.setup(**setup_kwargs)
        self._register_scenario_apps()
        if type(self.scenario).oracle_solution is not object and hasattr(
            self.scenario, "oracle_solution"
        ):
            try:
                self.scenario.oracle_solution(run_oracle=run_oracle)
                return self.scenario.workflow
            except NotImplementedError:
                pass
        self._run_captured_oracle_events(run_oracle=run_oracle)
        return self.scenario.workflow

    def build_oracle_workflow(
        self, run_oracle: bool = False, **setup_kwargs: Any
    ) -> Workflow:
        return self.run_scenario_oracle(
            run_oracle=run_oracle, **setup_kwargs
        )

    def replay_workflow(self, workflow: Workflow) -> Workflow:
        self.scenario.setup()
        self._register_scenario_apps()
        _, _, tools_map = build_toolset(list(self.scenario.apps or []))
        replayed = Workflow()
        for name, step in workflow.dag.items():
            wall_start = time.perf_counter()
            sim_time_before = self.time_manager.time()
            if not step.tool_name:
                wall_elapsed = time.perf_counter() - wall_start
                replayed.add_node(
                    WorkflowStep(
                        name=name,
                        content=step.content,
                        op_type=step.op_type,
                        tool_name=step.tool_name,
                        tool_args=step.tool_args,
                        depends_on=list(step.depends_on),
                        time=self._env_time_str(),
                    )
                )
                self._record_run_log(
                    step_name=name,
                    phase="replay",
                    tool_name=step.tool_name,
                    tool_args=step.tool_args,
                    status="skipped_no_tool",
                    sim_time_before=sim_time_before,
                    sim_time_after=self.time_manager.time(),
                    wall_time_seconds=wall_elapsed,
                    content=step.content,
                )
                continue
            if step.tool_name not in tools_map:
                raise KeyError(f"Workflow step {name!r} references unknown tool {step.tool_name!r}")
            args = dict(step.tool_args or {})
            try:
                content = tools_map[step.tool_name](**args)
                status = "ok"
                error = None
            except Exception as exc:
                content = {"error": str(exc)}
                status = "error"
                error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                wall_elapsed = time.perf_counter() - wall_start
            replayed.add_node(
                WorkflowStep(
                    name=name,
                    content=content,
                    op_type=step.op_type,
                    tool_name=step.tool_name,
                    tool_args=args,
                    depends_on=list(step.depends_on),
                    time=self._env_time_str(),
                )
            )
            self._record_run_log(
                step_name=name,
                phase="replay",
                tool_name=step.tool_name,
                tool_args=args,
                status=status,
                sim_time_before=sim_time_before,
                sim_time_after=self.time_manager.time(),
                wall_time_seconds=wall_elapsed,
                content=content,
                error=error,
            )
        self.scenario.workflow = replayed
        return replayed

    def evaluate(self, workflow: Workflow | None = None) -> ScenarioValidationResult:
        workflow = workflow or self.scenario.workflow or Workflow()
        validate = getattr(self.scenario, "validate", None)
        if validate is None:
            return ScenarioValidationResult(
                success=True,
                message="Scenario has no validate() hook.",
                metadata={"workflow_steps": len(workflow)},
            )
        env = self.environment(workflow)
        signature = inspect.signature(validate)
        if len(signature.parameters) == 0:
            raw_result = validate()
        else:
            raw_result = validate(env)
        if isinstance(raw_result, ScenarioValidationResult):
            result = raw_result
        elif isinstance(raw_result, bool):
            result = ScenarioValidationResult(success=raw_result)
        elif raw_result is None:
            result = ScenarioValidationResult(
                success=True,
                message="Scenario validate() returned no result.",
            )
        else:
            result = ScenarioValidationResult(
                success=bool(raw_result),
                message=str(raw_result),
            )
        result.metadata.setdefault("workflow_steps", len(workflow))
        result.metadata.setdefault("environment", env.to_dict())
        return result

    def evaluation_report(self, workflow: Workflow | None = None) -> dict[str, Any]:
        result = self.evaluate(workflow)
        if hasattr(result, "to_dict"):
            validation = result.to_dict()
        else:
            validation = asdict(result)
        return {
            "scenario_id": getattr(self.scenario, "scenario_id", ""),
            "validation": validation,
            "outcome": self.outcome_summary(),
        }

    def outcome_summary(self) -> dict[str, Any]:
        farm_world = next(
            (
                app
                for app in self.scenario.apps or []
                if app.__class__.__name__ == "FarmWorldApp"
            ),
            None,
        )
        if farm_world is None:
            return {}
        inventory = farm_world.get_inventory() if hasattr(farm_world, "get_inventory") else {}
        summary: dict[str, Any] = {"inventory": inventory}
        physics = getattr(farm_world, "physics", None)
        yield_recovery = getattr(physics, "yield_recovery", None)
        states = list(getattr(yield_recovery, "states", {}).values()) if yield_recovery else []
        if states:
            harvested_states = [state for state in states if getattr(state, "harvested", False)]
            denominator = len(harvested_states) or len(states)
            selected = harvested_states or states
            summary["yield_recovery"] = {
                "ridges": len(states),
                "harvested_ridges": len(harvested_states),
                "avg_field_loss_fraction": round(
                    sum(float(getattr(state, "field_loss_fraction", 0.0)) for state in selected)
                    / denominator,
                    6,
                ),
                "avg_machine_loss_fraction": round(
                    sum(float(getattr(state, "machine_loss_fraction", 0.0)) for state in selected)
                    / denominator,
                    6,
                ),
                "avg_recovered_yield_g_m2_at_market_moisture": round(
                    sum(
                        float(
                            getattr(
                                state,
                                "recovered_yield_g_m2_at_market_moisture",
                                0.0,
                            )
                        )
                        for state in selected
                    )
                    / denominator,
                    6,
                ),
                "avg_quality_discount_fraction": round(
                    sum(float(getattr(state, "quality_discount_fraction", 0.0)) for state in selected)
                    / denominator,
                    6,
                ),
            }
        return summary

    def _run_captured_oracle_events(self, run_oracle: bool = True) -> None:
        captured_events = list(getattr(self.scenario, "events", []) or [])
        events = self._oracle_event_dependency_closure(captured_events)
        event_times = self._captured_event_times(events)
        for event in events:
            content = event.execute() if run_oracle else None
            name = event.event_id
            app_name = getattr(event.app, "name", event.app.__class__.__name__)
            tool_name = f"{app_name}__{event.function.__name__}"
            tool_args = self._event_tool_args(event)
            deps = [
                getattr(dep, "event_id", None)
                for dep in getattr(event, "dependencies", [])
                if getattr(dep, "event_id", None)
            ]
            self.scenario.workflow.add_node(
                WorkflowStep(
                    name=name,
                    content=content,
                    op_type=getattr(getattr(event, "operation_type", None), "name", None),
                    tool_name=tool_name,
                    tool_args=tool_args,
                    depends_on=deps,
                    time=self._format_timestamp(event_times[id(event)]),
                )
            )

    def _oracle_event_dependency_closure(self, captured_events: list[Any]) -> list[Any]:
        included: set[int] = set()
        ordered: list[Any] = []

        def include_with_dependencies(event: Any) -> None:
            event_key = id(event)
            if event_key in included:
                return
            for dependency in getattr(event, "dependencies", []) or []:
                include_with_dependencies(dependency)
            included.add(event_key)
            ordered.append(event)

        for event in captured_events:
            if getattr(event, "is_oracle", False):
                include_with_dependencies(event)
        return ordered

    def _captured_event_times(self, events: list[Any]) -> dict[int, float]:
        event_times: dict[int, float] = {}
        visiting: set[int] = set()

        def scheduled_time(event: Any) -> float:
            event_key = id(event)
            if event_key in event_times:
                return event_times[event_key]
            if event_key in visiting:
                raise ValueError("Cycle detected in captured oracle event graph.")
            visiting.add(event_key)
            app_name = getattr(event.app, "name", event.app.__class__.__name__)
            tool_name = f"{app_name}__{event.function.__name__}"
            tool_args = self._event_tool_args(event)
            dependencies = list(getattr(event, "dependencies", []) or [])
            delay = float(getattr(event, "delay_seconds", 0.0) or 0.0)
            if dependencies:
                base_time = max(scheduled_time(dep) for dep in dependencies)
            else:
                base_time = float(self.start_time)
            event_times[event_key] = base_time + delay + self._explicit_time_advance_seconds(tool_name, tool_args)
            visiting.remove(event_key)
            return event_times[event_key]

        for event in events:
            scheduled_time(event)
        return event_times

    def _event_tool_args(self, event: Any) -> dict[str, Any]:
        signature = inspect.signature(event.function)
        parameters = [
            name for name in signature.parameters
            if name != "self"
        ]
        args = {
            name: value
            for name, value in zip(parameters, getattr(event, "args", ()))
        }
        args.update(dict(getattr(event, "kwargs", {}) or {}))
        return args

    def _explicit_time_advance_seconds(self, tool_name: str, tool_args: dict[str, Any]) -> float:
        if tool_name == "SystemApp__advance_time":
            return (
                float(tool_args.get("seconds", 0) or 0)
                + float(tool_args.get("minutes", 0) or 0) * 60
                + float(tool_args.get("hours", 0) or 0) * 3600
                + float(tool_args.get("days", 0) or 0) * 86400
            )
        if tool_name == "SystemApp__wait_for_notification":
            return float(tool_args.get("timeout", 0) or 0)
        return 0.0

    def _record_run_log(
        self,
        *,
        step_name: str,
        phase: str,
        tool_name: str | None,
        tool_args: dict[str, Any] | None,
        status: str,
        sim_time_before: float,
        sim_time_after: float,
        wall_time_seconds: float,
        content: Any,
        error: str | None = None,
    ) -> None:
        self.run_log.append(
            {
                "index": len(self.run_log),
                "phase": phase,
                "step_name": step_name,
                "tool_name": tool_name,
                "tool_args": tool_args or {},
                "status": status,
                "error": error,
                "sim_time_before": self._format_timestamp(sim_time_before),
                "sim_timestamp_before": sim_time_before,
                "sim_time_after": self._format_timestamp(sim_time_after),
                "sim_timestamp_after": sim_time_after,
                "sim_elapsed_seconds": round(sim_time_after - sim_time_before, 6),
                "wall_time_seconds": round(wall_time_seconds, 6),
                "content_type": type(content).__name__,
                "content_preview": str(content)[:500],
            }
        )

    def run_scenario_dynamic(self):
        self.scenario.setup()
        self._register_scenario_apps()
        assert self.agent is not None, "Dynamic run requires an agent"
        self._apply_scenario_system_prompt()
        agent_task = self._resolve_agent_task()

        def run_agent():
            self.agent.run(input=agent_task)

        agent_thread = Thread(target=run_agent, name="Agent", daemon=True)
        agent_thread.start()

        while agent_thread.is_alive():
            self.current_time = self.time_manager.time()
            for event in self.scenario.dynamic_events or []:
                if not event.triggered and self.current_time >= event.time_start:
                    self._trigger_dynamic_event(event)
            time.sleep(1)
            self.time_manager.add_offset(self.time_increment_in_seconds - 1)
