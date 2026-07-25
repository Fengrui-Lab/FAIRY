from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any

from fairy.agents.agent.agent import AgentRunLimitExceeded
from fairy.agents.llm.base_llm import BaseLLM
from fairy.controllers.agent_builder import (
    AgentBuilder,
    AppAgentBuilder,
    build_controller_agent,
)
from fairy.controllers.agent_config import (
    FARM_SYSTEM_PROMPT_MODES,
    AppAgentConfigBuilder,
    get_farm_world_system_prompt,
)
from fairy.controllers.app_agent import apply_a2a_to_apps, collect_a2a_traces
from fairy.controllers.engine import Engine
from fairy.controllers.run_artifacts import (
    build_run_report,
    metric_totals,
    write_json,
    write_jsonl,
)
from fairy.scenarios.registry import get_scenario_class, list_scenarios
from fairy.scenarios.workflow import Workflow

_LEGACY_ARTIFACT_SUFFIXES = (
    ".events.jsonl",
    ".messages.json",
    ".runtime_metrics.json",
    ".evaluation.json",
    ".run_summary.json",
    ".run_log.jsonl",
    ".a2a_traces.json",
)


def _cleanup_legacy_artifacts(output_dir: Path, scenario_id: str) -> None:
    for suffix in _LEGACY_ARTIFACT_SUFFIXES:
        path = output_dir / f"{scenario_id}{suffix}"
        if path.exists():
            path.unlink()


def _cleanup_repo_side_exports() -> None:
    for dirname in ("fos_exports", "workflow_exports"):
        path = Path.cwd() / dirname
        if path.exists():
            shutil.rmtree(path)


def _runtime_log_rows(runtime_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_runtime_log_row(event, i) for i, event in enumerate(runtime_events)]


def _runtime_log_row(event: dict[str, Any], fallback_index: int) -> dict[str, Any]:
    row = dict(event)
    record_type = row.pop("event_type", None)
    record_index = row.pop("event_index", fallback_index)
    return {
        "record_index": record_index,
        "record_type": record_type,
        **row,
    }


def _append_live_progress(path: Path, event: dict[str, Any]) -> None:
    row = _runtime_log_row(event, int(event.get("event_index", 0)))
    # Full message histories remain in runtime_log.jsonl.  Keeping them out of
    # the live stream makes heartbeat I/O independent of context-window size.
    row.pop("messages", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _tool_replay_log_rows(run_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, entry in enumerate(run_log):
        row = dict(entry)
        row.pop("index", None)
        rows.append(
            {
                "record_index": i,
                "record_type": "tool_replay",
                **row,
            }
        )
    return rows


def _json_object_arg(raw: str | None, name: str) -> dict[str, Any]:
    if raw in (None, ""):
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{name} must be a JSON object: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{name} must be a JSON object.")
    return payload


def _str_to_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected boolean value, got {value!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FAIRY farm scenarios")
    parser.add_argument("-s", "--scenario", help="Scenario id")
    parser.add_argument("-o", "--oracle", action="store_true", help="Run oracle only")
    parser.add_argument("--agent", action="store_true", help="Run a real function-calling agent")
    parser.add_argument("--controller", default="farm_baseline_react", help="Controller family for --agent")
    parser.add_argument(
        "--system-prompt-mode",
        choices=FARM_SYSTEM_PROMPT_MODES,
        default="fairy",
        help=(
            "FARM controller system prompt: 'fairy' keeps the current prompt; "
            "'are' ports compatible legacy ARE behavior rules"
        ),
    )
    parser.add_argument("--provider", default="deepseek", help="LLM provider for --agent")
    parser.add_argument("--model", default="deepseek-chat", help="LLM model for --agent")
    parser.add_argument("--temperature", type=float, default=0.1, help="LLM temperature for --agent")
    parser.add_argument(
        "--max-output-tokens",
        "--max-tokens",
        dest="max_output_tokens",
        type=int,
        default=2048,
        help="Maximum completion tokens per LLM call",
    )
    parser.add_argument("--endpoint", default=None, help="OpenAI-compatible base URL for --agent provider")
    parser.add_argument("--parallel-tool-calls", type=_str_to_bool, default=True, help="Allow the model to return multiple tool calls in one LLM turn")
    parser.add_argument("--max-tool-calls", type=int, default=300, help="Maximum tool calls for --agent")
    parser.add_argument("--timeout-seconds", type=float, default=1200.0, help="Wall-time limit for --agent")
    parser.add_argument("--a2a", type=_str_to_bool, default=False, help="Enable Agent2Agent app wrappers")
    parser.add_argument("--a2a-app-prop", type=float, default=0.5, help="Fraction of eligible apps to wrap for A2A")
    parser.add_argument("--a2a-policy", default="generic", choices=["generic", "typed_experts"], help="A2A app-agent selection policy")
    parser.add_argument("--a2a-app-agent", default="default_app_agent", help="Fallback app-agent profile")
    parser.add_argument("--a2a-model", default=None, help="A2A app-agent model; defaults to main model")
    parser.add_argument("--a2a-provider", default=None, help="A2A app-agent provider; defaults to main provider")
    parser.add_argument("--a2a-endpoint", default=None, help="A2A app-agent endpoint; defaults to main endpoint")
    parser.add_argument("--a2a-max-tool-calls", type=int, default=None, help="Maximum tool calls per A2A expert agent; defaults to --max-tool-calls")
    parser.add_argument("--build-oracle", action="store_true", help="Build and save oracle workflow")
    parser.add_argument("--run-oracle-tools", action="store_true", help="Execute tools while building oracle")
    parser.add_argument("--replay", action="store_true", help="Replay a workflow against fresh scenario state")
    parser.add_argument("--evaluate", action="store_true", help="Evaluate the replayed workflow")
    parser.add_argument("--workflow", help="Workflow JSON path for build output or replay input")
    parser.add_argument("--output-dir", default="runs", help="Directory for generated workflow/evaluation files")
    parser.add_argument("--scenario-kwargs", default=None, help="JSON object passed to the scenario constructor")
    parser.add_argument("--init-kwargs", default=None, help="JSON object passed to scenario setup/initialize")
    parser.add_argument("--list", action="store_true", help="List scenarios")
    parser.add_argument("--list-controllers", action="store_true", help="List controller families")
    args = parser.parse_args()
    if args.list_controllers:
        for controller_id in AgentBuilder().list_agents():
            print(controller_id)
        return
    if args.list:
        for scenario_id in list_scenarios():
            print(scenario_id)
        return
    if args.max_output_tokens <= 0:
        parser.error("--max-output-tokens must be a positive integer")
    if not args.scenario:
        parser.error("--scenario is required unless --list is used")
    scenario_class = get_scenario_class(args.scenario)
    scenario_kwargs = _json_object_arg(args.scenario_kwargs, "--scenario-kwargs")
    init_kwargs = _json_object_arg(args.init_kwargs, "--init-kwargs")
    output_dir = Path(args.output_dir)
    workflow_path = Path(args.workflow) if args.workflow else output_dir / f"{args.scenario}.oracle.json"

    if args.build_oracle or args.replay or args.evaluate:
        run_wall_start = time.perf_counter()
        output_dir.mkdir(parents=True, exist_ok=True)
        _cleanup_legacy_artifacts(output_dir, args.scenario)
        source_workflow: Workflow | None = None
        active_engine: Engine | None = None
        active_workflow: Workflow | None = None
        artifacts: dict[str, str] = {}

        if args.build_oracle:
            build_engine = Engine(agent=None, scenario=scenario_class(**scenario_kwargs))
            source_workflow = build_engine.build_oracle_workflow(
                run_oracle=args.run_oracle_tools,
                **init_kwargs,
            )
            source_workflow.save_workflow(str(workflow_path))
            artifacts["oracle_workflow"] = str(workflow_path)
            print(f"oracle_workflow={workflow_path}")

        if args.replay or args.evaluate:
            if source_workflow is None:
                source_workflow = Workflow.load_workflow(str(workflow_path))
            active_engine = Engine(agent=None, scenario=scenario_class(**scenario_kwargs))
            active_workflow = active_engine.replay_workflow(source_workflow)
            replay_path = output_dir / f"{args.scenario}.replay.json"
            active_workflow.save_workflow(str(replay_path))
            artifacts["replay_workflow"] = str(replay_path)
            print(f"replay_workflow={replay_path}")

        report = None
        if args.evaluate:
            assert active_engine is not None
            report = active_engine.evaluation_report(active_workflow)
            print(json.dumps(report, ensure_ascii=False, indent=2))

        log_engine = active_engine if active_engine is not None else build_engine
        runtime_log_path = output_dir / f"{args.scenario}.runtime_log.jsonl"
        write_jsonl(
            runtime_log_path,
            _tool_replay_log_rows(log_engine.run_log),
        )
        artifacts["runtime_log"] = str(runtime_log_path)

        report_path = output_dir / f"{args.scenario}.run_report.json"
        artifacts["run_report"] = str(report_path)
        run_report = build_run_report(
            scenario_id=args.scenario,
            controller_id=None,
            provider=None,
            model=None,
            temperature=None,
            system_prompt_mode=None,
            run_type="oracle_replay_evaluate",
            stopped_reason="completed",
            wall_time_seconds=time.perf_counter() - run_wall_start,
            max_tool_calls=None,
            timeout_seconds=None,
            parallel_tool_calls=None,
            max_output_tokens=None,
            workflow_steps=len(active_workflow or source_workflow or Workflow()),
            tool_call_count=len(log_engine.run_log),
            runtime_metrics=[],
            artifacts=artifacts,
            evaluation=report,
            outcome=log_engine.outcome_summary(),
        )
        write_json(report_path, run_report)
        _cleanup_repo_side_exports()
        print(f"runtime_log={runtime_log_path}")
        print(f"run_report={report_path}")
        return

    scenario = scenario_class(**scenario_kwargs)
    if args.agent:
        run_wall_start = time.perf_counter()
        output_dir.mkdir(parents=True, exist_ok=True)
        _cleanup_legacy_artifacts(output_dir, args.scenario)
        progress_log_path = output_dir / f"{args.scenario}.progress.jsonl"
        if progress_log_path.exists():
            progress_log_path.unlink()
        llm = BaseLLM.llm_builder(
            {
                "provider": args.provider,
                "model": args.model,
                "temperature": args.temperature,
                "max_output_tokens": args.max_output_tokens,
                "parallel_tool_calls": args.parallel_tool_calls,
                **({"base_url": args.endpoint} if args.endpoint else {}),
            }
        )
        scenario.setup(**init_kwargs)
        a2a_metadata = {"enabled": False}
        if args.a2a:
            app_provider = args.a2a_provider or args.provider
            app_model = args.a2a_model or args.model
            app_endpoint = args.a2a_endpoint or args.endpoint

            def _build_app_llm():
                return BaseLLM.llm_builder(
                    {
                        "provider": app_provider,
                        "model": app_model,
                        "temperature": args.temperature,
                        "max_output_tokens": args.max_output_tokens,
                        "parallel_tool_calls": args.parallel_tool_calls,
                        **({"base_url": app_endpoint} if app_endpoint else {}),
                    }
                )

            a2a_result = apply_a2a_to_apps(
                list(scenario.apps or []),
                llm_factory=_build_app_llm,
                app_agent_builder=AppAgentBuilder(),
                app_agent_config_builder=AppAgentConfigBuilder(),
                app_prop=args.a2a_app_prop,
                policy=args.a2a_policy,
                app_agent_name=args.a2a_app_agent,
                seed=int(getattr(scenario, "seed", 0) or 0),
                max_tool_calls=(
                    args.a2a_max_tool_calls
                    if args.a2a_max_tool_calls is not None
                    else args.max_tool_calls
                ),
            )
            scenario.apps = a2a_result.apps
            a2a_metadata = {
                **a2a_result.metadata,
                "model": app_model,
                "provider": app_provider,
                "endpoint": app_endpoint,
            }
        agent = build_controller_agent(
            args.controller,
            llm=llm,
            toolsets=scenario.apps,
            system_message=get_farm_world_system_prompt(args.system_prompt_mode),
        )
        agent.runtime_event_sink = lambda event: _append_live_progress(
            progress_log_path, event
        )
        engine = Engine(agent=agent, scenario=scenario)
        workflow = None
        final_message = None
        error = None
        stopped_reason = "agent_finished"
        try:
            workflow = engine.run_scenario_agent(
                max_tool_calls=args.max_tool_calls,
                timeout_seconds=args.timeout_seconds,
                setup_scenario=False,
            )
            final_message = agent.messages.messages[-1] if agent.messages.messages else None
            stopped_reason = agent.stop_reason or "agent_finished"
        except Exception as exc:
            stopped_reason = agent.stop_reason or "error"
            if not (
                isinstance(exc, AgentRunLimitExceeded)
                and stopped_reason in {"max_tool_calls", "timeout"}
            ):
                error = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            workflow = agent.workflow
        wall_time_seconds = round(time.perf_counter() - run_wall_start, 6)
        runtime_metrics = list(agent.messages.runtime_metrics)
        controller_telemetry = dict(getattr(agent, "telemetry", {}) or {})
        artifacts: dict[str, str] = {}
        artifacts["progress_log"] = str(progress_log_path)

        workflow_path = output_dir / f"{args.scenario}.agent_workflow.json"
        workflow.save_workflow(str(workflow_path))
        artifacts["agent_workflow"] = str(workflow_path)

        runtime_log_path = output_dir / f"{args.scenario}.runtime_log.jsonl"
        write_jsonl(runtime_log_path, _runtime_log_rows(agent.runtime_events))
        artifacts["runtime_log"] = str(runtime_log_path)

        if a2a_metadata.get("enabled"):
            a2a_traces = collect_a2a_traces(list(scenario.apps or []))
            a2a_trace_metrics = [
                metric
                for trace in a2a_traces
                for metric in trace.get("runtime_metrics", [])
            ]
            a2a_metadata = {
                **a2a_metadata,
                "expert_trace_count": len(a2a_traces),
                "expert_tool_call_count": sum(
                    int(trace.get("tool_call_count") or 0) for trace in a2a_traces
                ),
                "expert_llm_turn_count": sum(
                    int(trace.get("llm_turn_count") or 0) for trace in a2a_traces
                ),
                "expert_metrics": metric_totals(a2a_trace_metrics),
            }
            a2a_metadata["expert_traces"] = a2a_traces

        evaluation = engine.evaluation_report(workflow)
        report_path = output_dir / f"{args.scenario}.run_report.json"
        artifacts["run_report"] = str(report_path)
        run_report = build_run_report(
            scenario_id=args.scenario,
            controller_id=args.controller,
            provider=args.provider,
            model=args.model,
            temperature=args.temperature,
            system_prompt_mode=args.system_prompt_mode,
            run_type="agent",
            stopped_reason=stopped_reason,
            wall_time_seconds=wall_time_seconds,
            max_tool_calls=args.max_tool_calls,
            timeout_seconds=args.timeout_seconds,
            parallel_tool_calls=args.parallel_tool_calls,
            max_output_tokens=args.max_output_tokens,
            workflow_steps=len(workflow),
            tool_call_count=agent.tool_call_count,
            runtime_metrics=runtime_metrics,
            artifacts=artifacts,
            evaluation=evaluation,
            outcome=engine.outcome_summary(),
            error=error,
            controller_telemetry=controller_telemetry,
            a2a=a2a_metadata,
        )
        write_json(report_path, run_report)
        _cleanup_repo_side_exports()
        print(f"agent_workflow={workflow_path}")
        print(f"runtime_log={runtime_log_path}")
        print(f"run_report={report_path}")
        if error is not None:
            raise RuntimeError(f"Agent run failed: {error['type']}: {error['message']}")
        return

    engine = Engine(agent=None, scenario=scenario)
    if args.oracle:
        workflow = engine.run_scenario_oracle(run_oracle=True, **init_kwargs)
        print(workflow)
    else:
        parser.error("agent mode requires constructing an Agent in user code")


if __name__ == "__main__":
    main()
