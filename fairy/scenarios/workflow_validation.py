from __future__ import annotations

import inspect
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.types import Action, CompletedEvent, EventType


def _make_serializable(value: Any) -> Any:
    if is_dataclass(value):
        return _make_serializable(asdict(value))
    if isinstance(value, dict):
        return {str(k): _make_serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_make_serializable(v) for v in value]
    if hasattr(value, "value"):
        return value.value
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _normalize_value(value: Any) -> Any:
    if isinstance(value, float) and value == int(value):
        return int(value)
    if isinstance(value, list):
        return tuple(_normalize_value(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((k, _normalize_value(v)) for k, v in value.items()))
    return value


def _make_key(tool_name: str, tool_args: dict[str, Any] | None) -> tuple[Any, ...]:
    if not tool_args:
        return (tool_name,)
    normalized = tuple(sorted((k, _normalize_value(v)) for k, v in tool_args.items()))
    return (tool_name, normalized)


def _extract_tool_steps(
    workflow: dict[str, dict[str, Any]] | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    steps = workflow.values() if isinstance(workflow, dict) else workflow
    return [
        step
        for step in steps
        if step.get("tool_name") and step.get("op_type") != "USER"
    ]


def _levenshtein_distance(
    s1: list[str], s2: list[str], k_ins: int = 1, k_del: int = 1, k_sub: int = 1
) -> int:
    m, n = len(s1), len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i * k_del
    for j in range(n + 1):
        dp[0][j] = j * k_ins
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else k_sub
            dp[i][j] = min(
                dp[i - 1][j] + k_del,
                dp[i][j - 1] + k_ins,
                dp[i - 1][j - 1] + cost,
            )
    return dp[m][n]


def _ktc(predicted: list[str], gold: list[str]) -> tuple[float, list[str]]:
    from itertools import combinations

    seen: set[str] = set()
    matched: list[str] = []
    for symbol in predicted:
        if symbol in gold and symbol not in seen:
            seen.add(symbol)
            matched.append(symbol)

    n = len(matched)
    if n < 2:
        return 0.0, []

    rank: dict[str, int] = {}
    for idx, symbol in enumerate(gold):
        if symbol in seen and symbol not in rank:
            rank[symbol] = idx
    ranks = [rank[symbol] for symbol in matched]

    concordant = 0
    discordant = 0
    for i, j in combinations(range(n), 2):
        if (ranks[i] - ranks[j]) * (i - j) > 0:
            concordant += 1
        else:
            discordant += 1

    tau = (concordant - discordant) / (0.5 * n * (n - 1))
    return (tau + 1) / 2.0, matched


def evaluate_workflows(
    oracle_workflow: dict[str, dict[str, Any]] | list[dict[str, Any]],
    agent_workflow: dict[str, dict[str, Any]] | list[dict[str, Any]],
) -> dict[str, float]:
    oracle_steps = _extract_tool_steps(oracle_workflow)
    agent_steps = _extract_tool_steps(agent_workflow)

    alphabet: dict[tuple[Any, ...], str] = {}

    def get_symbol(tool_name: str, tool_args: dict[str, Any] | None) -> str:
        key = _make_key(tool_name, tool_args)
        if key not in alphabet:
            idx = len(alphabet)
            alphabet[key] = chr(ord("A") + idx) if idx < 26 else f"A{idx - 25}"
        return alphabet[key]

    oracle_symbols = [
        get_symbol(step["tool_name"], step.get("tool_args")) for step in oracle_steps
    ]
    agent_symbols = [
        get_symbol(step["tool_name"], step.get("tool_args")) for step in agent_steps
    ]

    ld = _levenshtein_distance(agent_symbols, oracle_symbols)
    max_len = max(len(agent_symbols), len(oracle_symbols), 1)
    path_correctness = 1.0 - ld / max_len

    oracle_set = set(oracle_symbols)
    ktc_raw, matched = _ktc(agent_symbols, oracle_symbols)
    coverage = len(matched) / len(oracle_set) if oracle_set else 0.0
    ktc_adjusted = ktc_raw * coverage
    combined = 0.5 * path_correctness + 0.5 * ktc_adjusted

    return {
        "path_correctness": round(path_correctness, 4),
        "ktc_raw": round(ktc_raw, 4),
        "coverage": round(coverage, 4),
        "ktc_adjusted": round(ktc_adjusted, 4),
        "combined": round(combined, 4),
    }


def _resolve_tool_name(action: Action) -> str:
    app_name = action.app_name
    if action.class_name in {"DroneApp", "RobotApp"} and app_name:
        return f"{app_name}__{action.function_name}"
    return f"{action.class_name}__{action.function_name}"


def _resolve_op_type(action: Action) -> str | None:
    operation_type = action.operation_type
    if operation_type is None:
        return None
    return str(getattr(operation_type, "value", operation_type)).upper()


def _is_system_advance_time_action(action: Action) -> bool:
    return action.class_name == "SystemApp" and action.function_name == "advance_time"


def _advance_time_seconds_from_args(tool_args: dict[str, Any]) -> int:
    try:
        return max(
            0,
            int(tool_args.get("seconds", 0) or 0)
            + int(tool_args.get("minutes", 0) or 0) * 60
            + int(tool_args.get("hours", 0) or 0) * 3600
            + int(tool_args.get("days", 0) or 0) * 86400,
        )
    except (TypeError, ValueError):
        return 0


def _advance_time_args_from_seconds(total_seconds: int) -> dict[str, int]:
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    args: dict[str, int] = {}
    if days:
        args["days"] = days
    if hours:
        args["hours"] = hours
    if minutes:
        args["minutes"] = minutes
    if seconds or not args:
        args["seconds"] = seconds
    return args


def _extract_action_args(
    action: Action, completed_event: CompletedEvent | None = None
) -> dict[str, Any]:
    if completed_event is not None:
        args = completed_event.get_args()
    else:
        args = action.resolved_args or action.args
    return {k: _make_serializable(v) for k, v in (args or {}).items() if k != "self"}


def workflow_from_event_log(
    event_log: list[CompletedEvent],
) -> dict[str, dict[str, Any]]:
    workflow: dict[str, dict[str, Any]] = {}
    previous_step_name: str | None = None
    previous_advance_step_name: str | None = None
    step_index = 0

    for event in event_log:
        if getattr(event, "event_type", None) != EventType.AGENT:
            continue
        if not isinstance(event.action, Action):
            continue
        if event.action.class_name == "AgentUserInterface":
            continue

        tool_args = _extract_action_args(event.action, event)
        is_advance_time = _is_system_advance_time_action(event.action)
        if is_advance_time and previous_advance_step_name is not None:
            previous_args = workflow[previous_advance_step_name].get("tool_args") or {}
            total_seconds = _advance_time_seconds_from_args(
                dict(previous_args)
            ) + _advance_time_seconds_from_args(tool_args)
            workflow[previous_advance_step_name]["tool_args"] = _make_serializable(
                _advance_time_args_from_seconds(total_seconds)
            )
            continue

        step_name = f"step{step_index}"
        workflow[step_name] = {
            "name": step_name,
            "content": _make_serializable(
                event.metadata.return_value if event.metadata else None
            ),
            "op_type": _resolve_op_type(event.action),
            "tool_name": _resolve_tool_name(event.action),
            "tool_args": tool_args,
            "depends_on": [previous_step_name] if previous_step_name else [],
            "time": event.event_time,
        }
        previous_step_name = step_name
        previous_advance_step_name = step_name if is_advance_time else None
        step_index += 1

    return workflow


def workflow_from_oracle_events(scenario: Any) -> dict[str, dict[str, Any]]:
    workflow: dict[str, dict[str, Any]] = {}
    event_name_map: dict[str, str] = {}
    previous_advance_step_name: str | None = None
    step_index = 0

    for event in getattr(scenario, "events", []) or []:
        if not bool(getattr(event, "is_oracle", False)):
            continue
        app = getattr(event, "app", None)
        function = getattr(event, "function", None)
        if app is None or function is None:
            continue
        cls = app.__class__.__name__
        if cls == "AgentUserInterface":
            continue
        fn = getattr(function, "__name__", function.__class__.__name__)
        app_name = getattr(app, "name", cls)
        tool_name = f"{app_name}__{fn}" if cls in {"DroneApp", "RobotApp"} else f"{cls}__{fn}"
        tool_args = dict(getattr(event, "kwargs", {}) or {})
        args = list(getattr(event, "args", ()) or ())
        try:
            signature = inspect.signature(function)
            parameters = list(signature.parameters)
            call_args = [app, *args] if parameters and parameters[0] == "self" else args
            bound = signature.bind_partial(*call_args, **tool_args)
            bound.apply_defaults()
            tool_args = {
                name: value
                for name, value in bound.arguments.items()
                if name != "self"
            }
        except (TypeError, ValueError):
            if args:
                tool_args.update({f"arg{i}": value for i, value in enumerate(args)})
        is_advance_time = cls == "SystemApp" and fn == "advance_time"
        event_id = getattr(event, "event_id", None) or f"oracle_{step_index}"

        if is_advance_time and previous_advance_step_name is not None:
            previous_args = workflow[previous_advance_step_name].get("tool_args") or {}
            total_seconds = _advance_time_seconds_from_args(
                dict(previous_args)
            ) + _advance_time_seconds_from_args(tool_args)
            workflow[previous_advance_step_name]["tool_args"] = _make_serializable(
                _advance_time_args_from_seconds(total_seconds)
            )
            event_name_map[event_id] = previous_advance_step_name
            continue

        step_name = f"step{step_index}"
        depends_on = [
            event_name_map[dependency.event_id]
            for dependency in getattr(event, "dependencies", []) or []
            if getattr(dependency, "event_id", None) in event_name_map
            and event_name_map[dependency.event_id] != step_name
        ]
        workflow[step_name] = {
            "name": step_name,
            "content": None,
            "op_type": str(getattr(getattr(event, "operation_type", None), "value", "")).upper()
            or None,
            "tool_name": tool_name,
            "tool_args": _make_serializable(tool_args),
            "depends_on": depends_on,
            "time": None,
        }
        event_name_map[event_id] = step_name
        previous_advance_step_name = step_name if is_advance_time else None
        step_index += 1

    return workflow


def ensure_oracle_workflow(scenario: Any) -> dict[str, dict[str, Any]]:
    cached = getattr(scenario, "_cached_oracle_workflow", None)
    if cached is not None:
        return cached

    from fairy.controllers.engine import Engine

    oracle_scenario = scenario.__class__()
    for attr in ("start_time", "seed", "detailed_briefing"):
        if hasattr(scenario, attr):
            setattr(oracle_scenario, attr, getattr(scenario, attr))
    engine = Engine(agent=None, scenario=oracle_scenario)
    workflow = engine.run_scenario_oracle(run_oracle=True).to_dict()
    _normalize_workflow_times(workflow)
    scenario._cached_oracle_workflow = workflow
    return workflow


def _normalize_workflow_times(workflow: dict[str, dict[str, Any]]) -> None:
    for step in workflow.values():
        value = step.get("time")
        if not isinstance(value, str):
            continue
        try:
            step["time"] = datetime.fromisoformat(value).timestamp()
        except ValueError:
            try:
                step["time"] = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp()
            except ValueError:
                step["time"] = None


def _default_workflow_dir(scenario: Any, env: Any) -> Path:
    env_dump_dir = getattr(env, "dump_dir", None)
    if env_dump_dir:
        return Path(env_dump_dir)
    working_dir = getattr(scenario, "working_dir", None)
    if working_dir:
        return Path(working_dir)
    return Path.cwd() / "workflow_exports"


def save_workflow_json(
    workflow: dict[str, dict[str, Any]],
    output_dir: str | Path,
    filename: str,
) -> str:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    file_path = output_path / filename
    file_path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(file_path)


def append_workflow_evaluation(
    scenario: Any,
    env: Any,
    result: ScenarioValidationResult,
    workflow_subdir: str = "workflows",
) -> ScenarioValidationResult:
    oracle_workflow = ensure_oracle_workflow(scenario)
    event_log = getattr(env, "event_log", None)
    if event_log is not None and hasattr(event_log, "list_view"):
        agent_workflow = workflow_from_event_log(event_log.list_view())
    else:
        env_workflow = getattr(env, "workflow", None)
        agent_workflow = env_workflow.to_dict() if hasattr(env_workflow, "to_dict") else {}
    metrics = evaluate_workflows(oracle_workflow, agent_workflow)

    workflow_dir = _default_workflow_dir(scenario, env) / workflow_subdir
    oracle_path = save_workflow_json(
        oracle_workflow,
        workflow_dir,
        f"workflow_oracle_{scenario.scenario_id}.json",
    )
    agent_path = save_workflow_json(
        agent_workflow,
        workflow_dir,
        f"workflow_agent_{scenario.scenario_id}.json",
    )

    metric_text = ", ".join(f"{key}={value:.4f}" for key, value in metrics.items())
    workflow_text = f"workflow_oracle={oracle_path}, workflow_agent={agent_path}"
    parts = [result.rationale] if result.rationale else []
    parts.append(f"workflow_eval: {metric_text}")
    parts.append(workflow_text)
    result.rationale = "\n".join(parts)
    return result
