from __future__ import annotations

import inspect
import copy
import re
import time
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from math import isfinite
from threading import Thread
from typing import Any

from fairy.agents.agent.toolset_builder import build_toolset
from fairy.agents.agent.tool_arguments import parse_tool_arguments
from fairy.apps.system import SystemApp
from fairy.apps.farm_world.multi_farm import farm_world_apps, iter_apps_of_type, unwrap_app
from fairy.apps.farm_world.tractor_app import TractorApp
from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.scenarios.workflow import Workflow, WorkflowStep
from fairy.time_manager import TimeManager, SimulationTimeManager
from fairy.tool_execution import ToolExecutionError, ToolResult, WorkflowBundle

CST = timezone(timedelta(hours=8))


class ReplayDivergenceError(RuntimeError):
    """A replayed tool no longer agrees with the recorded failure contract."""


def _recorded_tool_error(step: WorkflowStep) -> tuple[str, str, str | None]:
    """Read structured errors, or the error block emitted by older agents."""
    if step.error_type is not None and step.error_message is not None:
        return step.error_type, step.error_message, step.raw_arguments
    content = step.content
    if isinstance(content, dict):
        error_type = content.get("error_type")
        error_message = content.get("error_message")
        if error_type is not None and error_message is not None:
            return str(error_type), str(error_message), content.get("raw_arguments")
        content = content.get("error", "")
    text = str(content or "")
    raw_arguments = step.raw_arguments
    if text.startswith("[OUTPUT OF TOOL ") and " ERROR:\n***\n" in text:
        text = text.split(" ERROR:\n***\n", 1)[1]
        text, separator, arguments = text.partition("\nRaw arguments: ")
        if separator:
            raw_arguments = arguments.rsplit("\n***\n", 1)[0]
    match = re.fullmatch(r"([\w.]+): ?([\s\S]*)", text)
    if not match:
        raise ReplayDivergenceError(
            f"Workflow step {step.name!r} has no identifiable recorded exception"
        )
    return match.group(1), match.group(2), raw_arguments

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
        available_runtimes = list(getattr(scenario, "runtime_participants", []) or [])
        for app in scenario.apps or []:
            runtime = getattr(unwrap_app(app), "runtime", None)
            if runtime is not None and runtime not in available_runtimes:
                available_runtimes.append(runtime)
        restored = [runtime for runtime in available_runtimes if getattr(runtime, "restored_from_snapshot", False)]
        environment = getattr(scenario, "farm_environment", None)
        self.time_manager = (environment.time_manager if environment is not None else
                             restored[0].clock if restored else SimulationTimeManager())
        self.start_time = scenario.start_time if scenario.start_time is not None else 0.0
        if not restored and environment is None:
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
        self.farm_environment = getattr(self.scenario, "farm_environment", None)
        if self.farm_environment is not None:
            environment = self.farm_environment
            warehouse = environment.warehouse
            if warehouse is not None and sum(unwrap_app(app) is warehouse
                    for app in self.scenario.apps or []) != 1:
                raise ValueError("Register the common WarehouseApp exactly once")
            if environment.time_manager.start_time != self.start_time:
                raise ValueError("Scenario and farm environment must have the same start time")
            self.time_manager = environment.time_manager
            environment.register_time_manager(self.time_manager)
            if self.agent is not None:
                self.agent.set_time_manager(self.time_manager)
        farms = farm_world_apps(self.scenario.apps or [])
        other_worlds = [unwrap_app(app) for app in self.scenario.apps or []
                        if getattr(unwrap_app(app), "simulation_world", False)]
        participants = list(getattr(self.scenario, "runtime_participants", []) or [])
        for app in self.scenario.apps or []:
            runtime = getattr(unwrap_app(app), "runtime", None)
            if runtime is not None and runtime not in participants:
                participants.append(runtime)
        for key in getattr(self, "_runtime_observer_keys", []):
            self.time_manager.unregister_offset_observer(key)
        self._runtime_observer_keys = []
        for index, runtime in enumerate(participants):
            runtime.bind_clock(self.time_manager)
            key = f"runtime:{index}"
            self.time_manager.register_offset_observer(key, runtime.before_advance, runtime.advance_to)
            self._runtime_observer_keys.append(key)
        self.runtime_participants = participants
        if (other_worlds and self.farm_environment is None and not participants
                and not self.run_log and self.time_manager.offset == 0):
            # A paddy checkpoint can set its season timestamp during setup,
            # after Engine construction. Bind that restored epoch before tools.
            self.start_time = self.scenario.start_time
            self.time_manager.reset(start_time=self.start_time)
        names = [app.name for app in self.scenario.apps or []]
        if len(names) != len(set(names)):
            raise ValueError("Scenario app names must be unique; namespace each farm's apps.")
        farm_ids = [getattr(farm, "farm_id", farm.name) for farm in farms]
        if len(farm_ids) != len(set(farm_ids)):
            raise ValueError("Scenario farm IDs must be unique.")
        for app in self.scenario.apps or []:
            app.register_time_manager(self.time_manager)
            if hasattr(app, "register_event_scheduler"):
                app.register_event_scheduler("engine", self.schedule_dynamic_event)
            candidate = unwrap_app(app)
            if isinstance(candidate, SystemApp):
                candidate.wait_for_next_notification = self.wait_for_next_notification
                if self.farm_environment is not None:
                    candidate.attach_farm_environment(self.farm_environment)
                    candidate.attach_farm_world_apps([])
                else:
                    candidate.attach_farm_world_apps([] if participants else [*farms, *other_worlds])
        self.time_manager.unregister_offset_observer("farm_fleet")
        if len(farms) > 1 and not participants and self.farm_environment is None:
            def prepare_all(timestamp: float) -> None:
                for farm in farms:
                    farm.prepare_for_time_advance(timestamp)

            def advance_all(timestamp: float) -> None:
                for farm in farms:
                    farm.advance_physics_time(timestamp)

            self.time_manager.register_offset_observer("farm_fleet", prepare_all, advance_all)

    def schedule_dynamic_event(self, event: Any) -> None:
        self.scenario.dynamic_events.append(event)

    def _next_dynamic_event(self):
        pending = [e for e in self.scenario.dynamic_events or [] if not e.triggered]
        return min(pending, key=lambda e: e.time_start) if pending else None

    def _env_time_str(self) -> str:
        t = self.time_manager.time()
        return self._format_timestamp(t)

    def _format_timestamp(self, timestamp: float) -> str:
        calendar = getattr(self.scenario, "simulation_timezone", CST)
        return datetime.fromtimestamp(timestamp, tz=calendar).strftime("%Y-%m-%d %H:%M:%S")

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

    def _advance_clock(self, seconds: float) -> None:
        """Charge scene time once and settle all explicitly registered farms."""
        if self.farm_environment is not None:
            self.farm_environment.advance_time(seconds)
        else:
            self.time_manager.add_offset(seconds)

    def wait_for_next_notification(self) -> None:
        system_app = next(
            (unwrap_app(app) for app in self.scenario.apps or [] if isinstance(unwrap_app(app), SystemApp)), None
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
                self._advance_clock(jump_time)
            system_app.reset_wait_for_notification_timeout()
            return
        jump_time = next_event_time - self.time_manager.time()
        if jump_time > 0:
            self._advance_clock(jump_time)
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
                self._attach_workflow_manifest(self.scenario.workflow)
                if not run_oracle and self.run_manifest is not None:
                    self.workflow_bundle(self.scenario.workflow).validate(
                        self._shared_tool_registry(),
                        extra_tools=build_toolset(list(self.scenario.apps or []))[2],
                    )
                return self.scenario.workflow
            except NotImplementedError:
                pass
        self._run_captured_oracle_events(run_oracle=run_oracle)
        self._attach_workflow_manifest(self.scenario.workflow)
        return self.scenario.workflow

    def _shared_tool_registry(self):
        registries = []
        for runtime in getattr(self, "runtime_participants", []) or []:
            registry = getattr(runtime, "registry", None)
            if registry is not None and all(registry is not item for item in registries):
                if not registry.frozen:
                    runtime.freeze()
                registries.append(registry)
        if len(registries) > 1:
            raise ValueError("One shared tool catalog is required per scenario")
        return registries[0] if registries else None

    @property
    def run_manifest(self) -> dict[str, Any] | None:
        registry = self._shared_tool_registry()
        return None if registry is None else registry.manifest

    def _attach_workflow_manifest(self, workflow: Workflow) -> None:
        manifest = self.run_manifest
        if manifest is not None:
            workflow.manifest = deepcopy(manifest)
            self.scenario.workflow_manifest = deepcopy(manifest)

    def workflow_bundle(self, workflow: Workflow, manifest=None) -> WorkflowBundle:
        source_manifest = manifest if manifest is not None else getattr(workflow, "manifest", None)
        if source_manifest is None:
            raise ValueError("Shared-tool workflow requires its source manifest")
        return WorkflowBundle(workflow, source_manifest)

    def build_oracle_workflow(
        self, run_oracle: bool = False, **setup_kwargs: Any
    ) -> Workflow:
        return self.run_scenario_oracle(
            run_oracle=run_oracle, **setup_kwargs
        )

    def replay_workflow(
        self, workflow: Workflow | WorkflowBundle, *, manifest=None, **setup_kwargs: Any
    ) -> Workflow:
        if isinstance(workflow, WorkflowBundle):
            if manifest is not None and dict(manifest) != workflow.manifest:
                raise ValueError("Conflicting workflow manifests")
            manifest = deepcopy(workflow.manifest)
            workflow = workflow.workflow
        elif manifest is None:
            manifest = deepcopy(getattr(workflow, "manifest", None))
        self.scenario.setup(**setup_kwargs)
        self._register_scenario_apps()
        _, _, tools_map = build_toolset(list(self.scenario.apps or []))
        registry = self._shared_tool_registry()
        if registry is not None:
            self.workflow_bundle(workflow, manifest).validate(registry, extra_tools=tools_map)
        replayed = Workflow()
        for name, step in workflow.dag.items():
            if step.time_before is not None:
                self._align_replay_timestamp(step.time_before)
            wall_start = time.perf_counter()
            sim_time_before = self.time_manager.time()
            if step.time_after is not None and (not isfinite(step.time_after) or step.time_after < sim_time_before):
                raise ValueError(f"Workflow step {name!r} has an invalid end timestamp")
            if not step.tool_name:
                if step.op_type == "TOOL_ERROR":
                    raise ReplayDivergenceError(
                        f"Workflow step {name!r} records a tool error without a tool"
                    )
                if step.time_after is not None:
                    self._align_replay_timestamp(step.time_after)
                replayed.add_node(replace(
                    step, name=name, depends_on=list(step.depends_on),
                    time=self._env_time_str(), time_before=sim_time_before,
                    time_after=self.time_manager.time(),
                ))
                self._record_run_log(
                    step_name=name, phase="replay", tool_name=step.tool_name,
                    tool_args=step.tool_args, status="skipped_no_tool",
                    sim_time_before=sim_time_before,
                    sim_time_after=self.time_manager.time(),
                    wall_time_seconds=time.perf_counter() - wall_start,
                    content=step.content,
                )
                continue
            expected_error = step.op_type == "TOOL_ERROR"
            # Historical failed calls may have null/non-object arguments. Do
            # not turn them into a different executable call during replay.
            args = step.tool_args if expected_error or step.tool_args is not None else {}
            failure = None
            status, error = "ok", None
            try:
                if expected_error:
                    error = self._replay_tool_error(step, tools_map, args)
                    content = step.content
                    status = "expected_error"
                else:
                    if step.tool_name not in tools_map:
                        raise KeyError(f"Workflow step {name!r} references unknown tool {step.tool_name!r}")
                    content = tools_map[step.tool_name](**args)
                    if isinstance(content, ToolResult) and not content.ok:
                        detail = content.error
                        status = "error"
                        error = f"{detail['code']}: {detail['message']}"
                        failure = ToolExecutionError(detail["code"], detail["message"],
                            field=detail.get("field"), details=detail.get("details"),
                            stage=detail.get("stage", "execution"),
                            partial_effects=detail.get("partial_effects", "unknown"))
                    elif isinstance(content, dict) and (
                        bool(content.get("error")) or content.get("status") in {"error", "failed", "partial"}
                    ):
                        # Keep an actual returned failure and its partial
                        # effects, then stop. Expected Python exceptions above
                        # remain errors while allowing a recorded correction.
                        status = "error"
                        error = str(content.get("error") or content.get("reason")
                                    or f"Tool returned status {content.get('status')!r}")
                        failure = ToolExecutionError("LEGACY_TOOL_ERROR", error,
                            details={"tool": step.tool_name, "response": deepcopy(content)},
                            stage="execution", partial_effects="unknown")
            except Exception as exc:
                self._record_run_log(
                    step_name=name, phase="replay", tool_name=step.tool_name,
                    tool_args=args, status="error", sim_time_before=sim_time_before,
                    sim_time_after=self.time_manager.time(),
                    wall_time_seconds=time.perf_counter() - wall_start,
                    content={"error": str(exc)},
                    error=f"{type(exc).__name__}: {exc}",
                )
                raise
            if step.time_after is not None:
                self._align_replay_timestamp(step.time_after)
            sim_time_after = self.time_manager.time()
            replayed.add_node(replace(
                step, name=name, content=content, tool_args=args,
                depends_on=list(step.depends_on), time=self._env_time_str(),
                time_before=sim_time_before, time_after=sim_time_after,
            ))
            self._record_run_log(
                step_name=name, phase="replay", tool_name=step.tool_name,
                tool_args=args, status=status, sim_time_before=sim_time_before,
                sim_time_after=sim_time_after,
                wall_time_seconds=time.perf_counter() - wall_start,
                content=content, error=error,
            )
            if failure is not None:
                self.scenario.workflow = replayed
                self._attach_workflow_manifest(replayed)
                raise failure
        self.scenario.workflow = replayed
        if registry is not None:
            self._attach_workflow_manifest(replayed)
        return replayed

    def _replay_error_state(self) -> tuple[Any, ...]:
        # Compare explicit simulation time, not wall-clock time spent replaying.
        # Apps without snapshots cannot have their private state checked here.
        states = []
        for app in self.scenario.apps or []:
            get_state = getattr(app, "get_state", None)
            if callable(get_state):
                state = get_state()
                if state is not None:
                    states.append((app.name, copy.deepcopy(state)))
        return self.time_manager.start_time, self.time_manager.offset, states

    def _replay_tool_error(
        self, step: WorkflowStep, tools_map: dict[str, Any], args: Any
    ) -> str:
        error_type, error_message, raw_arguments = _recorded_tool_error(step)
        stage = step.error_stage
        # Older agent traces have the same error block but lack error_stage.
        if stage is None:
            stage = "tool_args_parse" if error_type == "JSONDecodeError" else "tool_call"
        if stage not in {"tool_args_parse", "tool_call"}:
            raise ReplayDivergenceError(
                f"Workflow step {step.name!r} has unsupported error stage {stage!r}"
            )
        if stage == "tool_args_parse" and raw_arguments is None:
            raise ReplayDivergenceError(
                f"Workflow step {step.name!r} cannot reproduce argument parsing without raw arguments"
            )
        if stage == "tool_call" and not isinstance(args, dict):
            # Old agents let non-object JSON reach Python's ** operator. Its
            # exception contains unstable callable reprs; reject safely instead
            # of guessing a match or executing a different argument set.
            raise ReplayDivergenceError(
                f"Workflow step {step.name!r} has legacy non-object tool arguments; "
                "cannot safely replay the recorded call"
            )
        before = self._replay_error_state()
        try:
            if stage == "tool_args_parse":
                # Neither invalid JSON nor a non-object value may reach a tool.
                parse_tool_arguments(raw_arguments)
            else:
                # Lookup remains inside the try: missing-tool KeyErrors are also
                # recoverable agent observations, but must match the old error.
                tools_map[step.tool_name](**args)
        except Exception as exc:
            if type(exc).__name__ != error_type or str(exc) != error_message:
                raise ReplayDivergenceError(
                    f"Workflow step {step.name!r}: expected {error_type}: {error_message}; "
                    f"got {type(exc).__name__}: {exc}"
                ) from exc
            if self._replay_error_state() != before:
                raise ReplayDivergenceError(
                    f"Workflow step {step.name!r}: failed tool changed application state "
                    "or explicit simulation time"
                ) from exc
            return f"{type(exc).__name__}: {exc}"
        raise ReplayDivergenceError(
            f"Workflow step {step.name!r}: expected {error_type}: {error_message}, "
            "but the call succeeded"
        )

    def _align_replay_timestamp(self, timestamp: float) -> None:
        """Replay recorded epochs without rewinding any farm's physical state."""
        if not isfinite(timestamp):
            raise ValueError("Replay timestamp must be finite")
        seconds = timestamp - self.time_manager.time()
        if seconds < -1e-6:
            raise ValueError("Replay timestamp precedes current state; use a fresh scenario")
        if seconds > 0:
            self._advance_clock(seconds)

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
            **({"tool_manifest": self.run_manifest} if self.run_manifest is not None else {}),
        }

    def outcome_summary(self) -> dict[str, Any]:
        if self.farm_environment is not None:
            self.farm_environment.sync()
            warehouse = self.farm_environment.warehouse
            return {
                "farms": {key: self._farm_outcome_summary(ctx.world)
                          for key, ctx in self.farm_environment.farms.items()},
                "warehouse": {"inventory": warehouse.get_inventory(),
                              "grain_batches": warehouse.get_grain_batches()["batches"]},
                "shared_equipment": {app.name: app.get_state()
                                     for app in getattr(self.scenario, "shared_equipment", [])},
            }
        for app in self.scenario.apps or []:
            candidate = unwrap_app(app)
            if getattr(candidate, "simulation_world", False):
                return candidate.outcome_summary()
        farms = farm_world_apps(self.scenario.apps or [])
        if not farms:
            return {}
        if len(farms) == 1 and not getattr(self, "runtime_participants", None):
            return self._farm_outcome_summary(farms[0])
        per_farm = {}
        tractors = iter_apps_of_type(self.scenario.apps or [], TractorApp)
        for farm in farms:
            farm_id = getattr(farm, "farm_id", farm.name)
            summary = self._farm_outcome_summary(farm)
            physics_active = bool(getattr(getattr(farm, "_physics", None), "engines_active", False))
            if not physics_active:
                summary.pop("yield_recovery", None)
            inventory = summary["inventory"]
            if getattr(self, "runtime_participants", None):
                bins_kg = sum(runtime.outcome().get(farm_id, {}).get("combine_bin_grain_kg", 0.0)
                              for runtime in self.runtime_participants)
            else:
                bins_kg = sum(float(getattr(tractor, "_grain_bin_kg", 0.0))
                              for tractor in tractors if tractor._farm_world_app is farm)
            grain_compartments = {
                "warehouse_grain_kg": float(inventory.get("warehouse_grain_kg", 0.0)),
                "trailer_grain_kg": float(inventory.get("harvest_grain_kg", 0.0)),
                "combine_bin_grain_kg": round(bins_kg, 4),
            }
            per_farm[farm_id] = {
                "farm_id": farm_id,
                "app_name": farm.name,
                "crop_type": getattr(farm, "crop_type", "soybean"),
                "num_ridges": farm.num_ridges,
                "ridge_area_m2": farm.field_length_m * farm.ridge_width_m,
                "physics_active": physics_active,
                "grain_compartments": grain_compartments,
                "recovered_grain_kg_total": round(sum(grain_compartments.values()), 4),
                "grain_accounting_source": "warehouse_plus_trailer_plus_combine_bins",
                "grain_mass_basis": "operational_inventory_kg",
                **summary,
            }
        inventory_totals: dict[str, Any] = {"seed_stock": {}}
        for summary in per_farm.values():
            for key, value in summary["inventory"].items():
                if key == "seed_stock":
                    for cultivar, count in value.items():
                        stock = inventory_totals["seed_stock"]
                        stock[cultivar] = stock.get(cultivar, 0) + count
                elif isinstance(value, (int, float)) and not isinstance(value, bool):
                    inventory_totals[key] = round(inventory_totals.get(key, 0) + value, 2)
        weighted_states = []
        physics_yield_available = all(summary["physics_active"] for summary in per_farm.values())
        for farm in farms:
            physics = getattr(farm, "_physics", None)
            if not getattr(physics, "engines_active", False):
                continue
            recovery = getattr(physics, "yield_recovery", None)
            area = farm.field_length_m * farm.ridge_width_m
            weighted_states.extend((state, area) for state in getattr(recovery, "states", {}).values())
        aggregate = {
            "farm_count": len(farms),
            "num_ridges": sum(farm.num_ridges for farm in farms),
            "field_area_m2": round(sum(farm.num_ridges * farm.field_length_m * farm.ridge_width_m for farm in farms), 4),
            "inventory": inventory_totals,
            "recovered_grain_kg_total": round(sum(summary["recovered_grain_kg_total"] for summary in per_farm.values()), 4),
            "grain_accounting_source": "warehouse_plus_trailer_plus_combine_bins",
            "grain_mass_basis": "operational_inventory_kg",
            "yield_accounting_source": "active_crop_physics" if physics_yield_available else "unavailable_without_active_physics_for_every_farm",
            "biological_yield_kg_total": round(sum(float(getattr(state, "biological_yield_g_m2", 0.0)) * area / 1000 for state, area in weighted_states), 4) if physics_yield_available else None,
            "recovered_yield_kg_total": round(sum(float(getattr(state, "recovered_yield_g_m2_at_market_moisture", 0.0)) * area / 1000 for state, area in weighted_states), 4) if physics_yield_available else None,
        }
        return {"farms": per_farm, "aggregate": aggregate}

    @staticmethod
    def _farm_outcome_summary(farm_world: Any) -> dict[str, Any]:
        if getattr(farm_world, "shared_warehouse", None) is not None:
            summary = {"warehouse_id": farm_world.shared_warehouse.warehouse_id,
                       "management_status": farm_world.get_management_status()}
        else:
            inventory = farm_world.get_inventory() if hasattr(farm_world, "get_inventory") else {}
            summary = {"inventory": inventory}
        # Reporting must not construct or activate a crop engine. Mature
        # operational snapshots can legitimately have no physics history.
        physics = getattr(farm_world, "_physics", None)
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
        registry = self._shared_tool_registry()
        if registry is not None:
            planned = Workflow()
            for index, event in enumerate(events):
                app_name = getattr(event.app, "name", event.app.__class__.__name__)
                planned.add_node(WorkflowStep(
                    name=event.event_id or f"step{index}",
                    tool_name=f"{app_name}__{event.function.__name__}",
                    tool_args=self._event_tool_args(event),
                    depends_on=[dependency.event_id for dependency in event.dependencies if dependency.event_id],
                ))
            source_manifest = getattr(self.scenario, "events_manifest", None)
            self.workflow_bundle(planned, source_manifest).validate(
                registry, extra_tools=build_toolset(list(self.scenario.apps or []))[2],
            )
        event_times = self._captured_event_times(events)
        for event in events:
            record_runtime_timing = run_oracle and bool(
                getattr(event, "record_runtime_timing", False) or self.farm_environment is not None
            )
            time_before = self.time_manager.time() if record_runtime_timing else None
            content = event.execute() if run_oracle else None
            if isinstance(content, ToolResult) and not content.ok:
                detail = content.error
                raise ToolExecutionError(detail["code"], detail["message"], field=detail.get("field"),
                                         details=detail.get("details"), stage=detail.get("stage", "execution"),
                                         partial_effects=detail.get("partial_effects", "unknown"))
            time_after = self.time_manager.time() if record_runtime_timing else None
            metadata = dict(getattr(event, "workflow_metadata", {}) or {})
            if metadata:
                if isinstance(content, dict):
                    content = dict(content)
                else:
                    content = {} if content is None else {"result": content}
                content.update(metadata)
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
                    time=self._format_timestamp(
                        time_after if record_runtime_timing else event_times[id(event)]
                    ),
                    time_before=time_before,
                    time_after=time_after,
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
            self._advance_clock(self.time_increment_in_seconds - 1)
