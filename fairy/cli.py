from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from fairy.agents.llm.base_llm import BaseLLM
from fairy.controllers.engine import Engine
from fairy.controllers.agent_builder import AgentBuilder
from fairy.controllers.agent_builder import build_controller_agent
from fairy.controllers.run_artifacts import build_run_report, write_json, write_jsonl
from fairy.scenarios.registry import get_scenario_class, list_scenarios
from fairy.scenarios.workflow import Workflow


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FAIRY farm scenarios")
    parser.add_argument("-s", "--scenario", help="Scenario id")
    parser.add_argument("-o", "--oracle", action="store_true", help="Run oracle only")
    parser.add_argument("--agent", action="store_true", help="Run a real function-calling agent")
    parser.add_argument("--controller", default="farm_baseline_react", help="Controller family for --agent")
    parser.add_argument("--provider", default="deepseek", help="LLM provider for --agent")
    parser.add_argument("--model", default="deepseek-chat", help="LLM model for --agent")
    parser.add_argument("--temperature", type=float, default=0.2, help="LLM temperature for --agent")
    parser.add_argument("--max-tool-calls", type=int, default=300, help="Maximum tool calls for --agent")
    parser.add_argument("--timeout-seconds", type=float, default=1200.0, help="Wall-time limit for --agent")
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
            evaluation_path = output_dir / f"{args.scenario}.evaluation.json"
            write_json(evaluation_path, report)
            artifacts["evaluation"] = str(evaluation_path)
            print(f"evaluation={evaluation_path}")
            print(json.dumps(report, ensure_ascii=False, indent=2))

        log_engine = active_engine if active_engine is not None else build_engine
        run_log_path = output_dir / f"{args.scenario}.run_log.jsonl"
        write_jsonl(run_log_path, log_engine.run_log)
        artifacts["run_log"] = str(run_log_path)
        events_path = output_dir / f"{args.scenario}.events.jsonl"
        write_jsonl(
            events_path,
            [
                {"event_type": "tool_replay", **entry}
                for entry in log_engine.run_log
            ],
        )
        artifacts["events"] = str(events_path)

        run_summary = {
            "scenario_id": args.scenario,
            "wall_time_seconds": round(time.perf_counter() - run_wall_start, 6),
            "oracle_workflow_steps": len(source_workflow) if source_workflow is not None else 0,
            "replay_workflow_steps": len(active_workflow) if active_workflow is not None else 0,
            "run_log_entries": len(log_engine.run_log),
            "token_usage": log_engine.token_usage,
            "artifacts": artifacts,
            "evaluation": report,
            "outcome": log_engine.outcome_summary(),
        }
        run_summary_path = output_dir / f"{args.scenario}.run_summary.json"
        artifacts["run_summary"] = str(run_summary_path)
        report_path = output_dir / f"{args.scenario}.run_report.json"
        artifacts["run_report"] = str(report_path)
        run_report = build_run_report(
            scenario_id=args.scenario,
            controller_id=None,
            provider=None,
            model=None,
            temperature=None,
            run_type="oracle_replay_evaluate",
            stopped_reason="completed",
            wall_time_seconds=time.perf_counter() - run_wall_start,
            max_tool_calls=None,
            timeout_seconds=None,
            workflow_steps=len(active_workflow or source_workflow or Workflow()),
            tool_call_count=len(log_engine.run_log),
            runtime_metrics=[],
            artifacts=artifacts,
            evaluation=report,
            outcome=log_engine.outcome_summary(),
        )
        write_json(run_summary_path, run_summary)
        write_json(report_path, run_report)
        print(f"run_log={run_log_path}")
        print(f"events={events_path}")
        print(f"run_report={report_path}")
        print(f"run_summary={run_summary_path}")
        return

    scenario = scenario_class(**scenario_kwargs)
    if args.agent:
        run_wall_start = time.perf_counter()
        output_dir.mkdir(parents=True, exist_ok=True)
        llm = BaseLLM.llm_builder(
            {
                "provider": args.provider,
                "model": args.model,
                "temperature": args.temperature,
            }
        )
        scenario.setup(**init_kwargs)
        agent = build_controller_agent(
            args.controller,
            llm=llm,
            toolsets=scenario.apps,
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
            error = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
            workflow = agent.workflow
        wall_time_seconds = round(time.perf_counter() - run_wall_start, 6)
        runtime_metrics = list(agent.messages.runtime_metrics)
        artifacts: dict[str, str] = {}

        workflow_path = output_dir / f"{args.scenario}.agent_workflow.json"
        workflow.save_workflow(str(workflow_path))
        artifacts["agent_workflow"] = str(workflow_path)

        messages_path = output_dir / f"{args.scenario}.messages.json"
        write_json(messages_path, agent.messages.messages)
        artifacts["messages"] = str(messages_path)

        metrics_path = output_dir / f"{args.scenario}.runtime_metrics.json"
        write_json(metrics_path, runtime_metrics)
        artifacts["runtime_metrics"] = str(metrics_path)

        events_path = output_dir / f"{args.scenario}.events.jsonl"
        write_jsonl(events_path, agent.runtime_events)
        artifacts["events"] = str(events_path)

        evaluation = engine.evaluation_report(workflow)
        evaluation_path = output_dir / f"{args.scenario}.evaluation.json"
        write_json(evaluation_path, evaluation)
        artifacts["evaluation"] = str(evaluation_path)

        run_summary_path = output_dir / f"{args.scenario}.run_summary.json"
        artifacts["run_summary"] = str(run_summary_path)
        report_path = output_dir / f"{args.scenario}.run_report.json"
        artifacts["run_report"] = str(report_path)
        run_report = build_run_report(
            scenario_id=args.scenario,
            controller_id=args.controller,
            provider=args.provider,
            model=args.model,
            temperature=args.temperature,
            run_type="agent",
            stopped_reason=stopped_reason,
            wall_time_seconds=wall_time_seconds,
            max_tool_calls=args.max_tool_calls,
            timeout_seconds=args.timeout_seconds,
            workflow_steps=len(workflow),
            tool_call_count=agent.tool_call_count,
            runtime_metrics=runtime_metrics,
            artifacts=artifacts,
            evaluation=evaluation,
            outcome=engine.outcome_summary(),
            error=error,
        )
        run_summary = {
            "scenario_id": args.scenario,
            "controller_id": args.controller,
            "provider": args.provider,
            "model": args.model,
            "temperature": args.temperature,
            "max_tool_calls": args.max_tool_calls,
            "timeout_seconds": args.timeout_seconds,
            "stopped_reason": stopped_reason,
            "final_message": final_message,
            "tool_call_count": agent.tool_call_count,
            "workflow_steps": len(workflow),
            "wall_time_seconds": wall_time_seconds,
            "token_usage": run_report["metrics"]["token_usage"],
            "artifacts": artifacts,
            "evaluation": evaluation,
            "outcome": engine.outcome_summary(),
            "error": error,
        }
        write_json(run_summary_path, run_summary)
        write_json(report_path, run_report)
        print(f"agent_workflow={workflow_path}")
        print(f"events={events_path}")
        print(f"run_report={report_path}")
        print(f"run_summary={run_summary_path}")
        if error is not None:
            raise RuntimeError(f"Agent run failed: {error['type']}: {error['message']}")
        return

    engine = Engine(agent=None, scenario=scenario)
    if args.oracle:
        workflow = engine.run_scenario_oracle(run_oracle=True, **init_kwargs)
        print(workflow)
    else:
        parser.error("agent mode requires constructing an Agent in user code")
