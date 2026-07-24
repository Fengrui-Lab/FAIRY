"""
Batch re-evaluation of FOS over FAIRY agent run bundles, without LLM cost.

For each cell directory under <root> (typical layout:
phase5_paper_matrix/<family>__<scenario>__rN/):

    1. Parse the FAIRY workflow bundle:
       ``<scenario>.agent_workflow.json`` + ``<scenario>.run_report.json``.
    2. Re-instantiate the scenario from the registry by `scenario_id`
       — this gets us a fresh, fully-wired set of apps including the
       physics orchestrator with its initial state.
    3. Replay the workflow's TOOL steps against the fresh scenario's apps.
       The agent's tool-mutating actions
       (plant_seeds, irrigate, advance_time, harvest, ...) re-drive
       the physics engines forward. Read-only actions are no-ops on
       state but still get logged so FOS Decision/Efficiency see the
       same agent history.
    4. Build a minimal env-stub holding the replayed event log.
    5. Call `evaluate_fos(...)` with the *current* FOS code (e.g.
       Scheme B + extrapolate_to_maturity) and emit a per-cell JSON
       under <out_root>/<rel_cell_dir>/fos/fos_<scenario>.json plus
       one row in a named summary CSV under <out_root>/ (v3 column schema,
       with agent_family,llm_model,run_level,detail_status,a2a_status plus
       pct_yield_loss and 100-scale metrics).

Why this matters:
    - Scheme B's `growing_loss / unharvested_mature` cannot be derived
      from the existing fos_*.json because they need physics state
      that's not in the trace. Replay reconstructs it.
    - `extrapolate_to_maturity` needs the post-replay physics state
      so the orchestrator can tick forward to R8.
    - Zero LLM dollars: we never re-call the agent. We only re-execute
      its already-recorded tool calls.

Usage:
    .venv312/bin/python scripts/rebatch_fos_from_traces.py \\
        --root validation_runs/iclr_sweep_qwen_l220260506T061339Z/phase5_paper_matrix \\
        --out-root validation_runs/iclr_sweep_qwen_reeval_v2 \\
        --extrapolate \\
        --workers 4

Caveats:
    - The replay assumes the scenario's `setup()` / `init_and_populate_apps()` is
      deterministic given (seed, start_time). All farm scenarios on this
      branch satisfy that.
    - Scenarios that aren't in the registry are skipped with status
      "scenario_not_in_registry".
    - Every replayed return value and the final FARM outcome checkpoint are
      checked against the trace. A mismatch fails that cell instead of
      emitting metrics from a divergent physics state.
    - Workflows written before exact pre/post timestamps were added use a
      backward-compatible timing reconstruction and are labelled with
      ``replay_legacy_timing_steps`` in the summary.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import os
import re
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

# Repo root to sys.path so FAIRY package imports work when this script is run
# directly.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_DEFAULT_EXCLUDED_SWEEP_DIRS: tuple[str, ...] = ()
_CST = timezone(timedelta(hours=8))


class ReplayDivergenceError(RuntimeError):
    """Raised when re-execution no longer represents the recorded run."""


# ---------------------------------------------------------------------------
# Replay primitives
# ---------------------------------------------------------------------------


def _operation_type_for_method(method: Any):
    from fairy.types import OperationType

    return getattr(method, "_event_operation_type", None) or OperationType.READ


def _build_completed_event_from_workflow_step(
    step: dict[str, Any],
    target_app: Any,
    method_name: str,
    args: dict[str, Any],
    event_time: float,
    return_value: Any,
    exception: Any,
):
    """Assemble a CompletedEvent from a FAIRY workflow step."""
    from fairy.types import (
        Action,
        CompletedEvent,
        EventMetadata,
        EventType,
    )

    method = getattr(target_app, method_name, None)
    if method is None:
        method = lambda **_kw: None  # noqa: E731

    action = Action(
        function=method,
        app=target_app,
        args={k: v for k, v in args.items() if k != "self"},
        operation_type=_operation_type_for_method(method),
        action_id=step.get("name"),
    )
    metadata = EventMetadata(
        return_value=return_value,
        exception=str(exception) if exception is not None else None,
        exception_stack_trace=None,
    )
    return CompletedEvent(
        event_type=EventType.AGENT,
        event_time=event_time,
        event_id=str(step.get("name") or ""),
        action=action,
        metadata=metadata,
        dependencies=step.get("depends_on") or [],
    )


def _instantiate_scenario_for_replay(scenario_id: str, start_time: float, seed: int):
    """Look up the scenario class in the registry and prepare it for
    replay (apps + physics initialised, but events flow not driven)."""
    from fairy.scenarios.registry import registry
    from fairy.time_manager import TimeManager

    cls = registry.get_scenario(scenario_id)
    scenario = cls()
    if start_time is not None:
        scenario.start_time = float(start_time)
    if seed is not None:
        scenario.seed = int(seed)
    # initialize() calls init_and_populate_apps() (apps + physics layers)
    # AND build_events_flow() (scenario events). The events are
    # benign here — we don't run them through the env, only call tools
    # directly via the agent's trace.
    scenario.initialize()
    if start_time is not None:
        # In a real run, Environment.register_apps() replaces every app's
        # constructor-created clock with one shared environment clock reset to
        # scenario.start_time. Replay calls tool methods directly, so it must
        # mirror that registration step or FARM full-season time jumps replay
        # from wall-clock app construction time.
        tm = TimeManager()
        tm.reset(float(start_time))
        for app in scenario.apps or []:
            app.register_time_manager(tm)
    return scenario


def _align_replay_time(scenario: Any, target_time: float | None) -> None:
    """Set replay clocks to *target_time* and advance physics monotonically."""
    if target_time is None:
        return
    try:
        target = float(target_time)
    except (TypeError, ValueError):
        return

    farm_world = next(
        (
            app
            for app in scenario.apps or []
            if app.__class__.__name__ == "FarmWorldApp"
        ),
        None,
    )
    physics = getattr(farm_world, "physics", None) if farm_world is not None else None
    physics_time = getattr(physics, "last_physics_sim_time", None)
    if physics_time is not None and target < float(physics_time) - 1.0:
        raise ReplayDivergenceError(
            "replay would move physics backwards: "
            f"target={target:.6f}, physics={float(physics_time):.6f}"
        )
    if physics_time is not None:
        target = max(target, float(physics_time))

    seen_time_managers: set[int] = set()
    for app in scenario.apps or []:
        tm = getattr(app, "time_manager", None)
        if tm is None:
            continue
        ident = id(tm)
        if ident in seen_time_managers:
            continue
        seen_time_managers.add(ident)
        tm.add_offset(target - float(tm.time()))

    if farm_world is not None:
        advance = getattr(farm_world, "advance_physics_time", None)
        if callable(advance):
            advance(target)


def _find_agent_workflow_path(cell_dir: Path) -> Path | None:
    matches = sorted(cell_dir.glob("*.agent_workflow.json"))
    return matches[0] if matches else None


def _find_run_report_path(cell_dir: Path, workflow_path: Path | None = None) -> Path | None:
    if workflow_path is not None:
        scenario_stem = workflow_path.name.removesuffix(".agent_workflow.json")
        candidate = cell_dir / f"{scenario_stem}.run_report.json"
        if candidate.is_file():
            return candidate
    matches = sorted(cell_dir.glob("*.run_report.json"))
    return matches[0] if matches else None


def _load_fairy_run_bundle(cell_dir: Path) -> dict[str, Any] | None:
    workflow_path = _find_agent_workflow_path(cell_dir)
    if workflow_path is None:
        return None
    report_path = _find_run_report_path(cell_dir, workflow_path)
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    run_report = (
        json.loads(report_path.read_text(encoding="utf-8"))
        if report_path is not None and report_path.is_file()
        else {}
    )
    scenario_id = (
        run_report.get("scenario_id")
        or workflow_path.name.removesuffix(".agent_workflow.json")
    )
    return {
        "cell_dir": cell_dir,
        "workflow_path": workflow_path,
        "report_path": report_path,
        "workflow": workflow,
        "run_report": run_report,
        "scenario_id": scenario_id,
        "start_time": run_report.get("start_time"),
        "seed": run_report.get("seed") or 0,
    }


def _iter_fairy_tool_steps(workflow: Any) -> list[dict[str, Any]]:
    raw_steps = workflow.values() if isinstance(workflow, dict) else workflow
    steps: list[dict[str, Any]] = []
    for raw_step in raw_steps or []:
        if not isinstance(raw_step, dict):
            continue
        if raw_step.get("op_type") == "USER":
            continue
        if not raw_step.get("tool_name"):
            continue
        steps.append(raw_step)
    return steps


def _tool_name_parts(tool_name: str) -> tuple[str, str]:
    if "__" not in tool_name:
        raise ValueError(f"FAIRY workflow tool_name must be App__method: {tool_name!r}")
    app_name, method_name = tool_name.split("__", 1)
    return app_name, method_name


def _parse_workflow_timestamp(raw: Any, fallback: float | None = None) -> float:
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str) and raw.strip():
        text = raw.strip().replace("T", " ")
        try:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_CST)
            return parsed.timestamp()
        except ValueError:
            pass
    return float(fallback or 0.0)


def _workflow_initial_timestamp(workflow: Any, fallback: float | None) -> float:
    raw_steps = workflow.values() if isinstance(workflow, dict) else workflow
    for step in raw_steps or []:
        if isinstance(step, dict) and step.get("op_type") == "USER":
            return _parse_workflow_timestamp(
                step.get("time_after", step.get("time")), fallback
            )
    return float(fallback or 0.0)


def _advance_time_seconds(args: dict[str, Any]) -> float:
    return float(
        int(args.get("seconds", 0) or 0)
        + int(args.get("minutes", 0) or 0) * 60
        + int(args.get("hours", 0) or 0) * 3600
        + int(args.get("days", 0) or 0) * 86400
    )


def _workflow_step_times(
    step: dict[str, Any],
    method: Any,
    previous_post_time: float | None,
) -> tuple[float, float, bool]:
    """Return (pre-call time, post-call time, exact timing available)."""
    post_time = _parse_workflow_timestamp(
        step.get("time_after", step.get("time")), previous_post_time
    )
    raw_pre_time = step.get("time_before")
    if raw_pre_time is not None:
        return _parse_workflow_timestamp(raw_pre_time, post_time), post_time, True

    tool_name = str(step.get("tool_name") or "")
    args = step.get("tool_args") if isinstance(step.get("tool_args"), dict) else {}
    if tool_name == "SystemApp__advance_time":
        return post_time - _advance_time_seconds(args), post_time, False

    from fairy.types import OperationType

    if _operation_type_for_method(method) == OperationType.READ:
        return post_time, post_time, False
    return float(previous_post_time or post_time), post_time, False


_VOLATILE_REPLAY_KEYS = {
    "action_id",
    "charge_complete_at",
    "current_datetime",
    "current_timestamp",
    "current_weekday",
    "elapsed_s",
    "effect_ready_at",
    "inspection_id",
    "last_physics_sim_time",
    "mission_id",
    "op_id",
}


def _parse_recorded_return(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{(\"'":
        return value
    try:
        return json.loads(stripped)
    except (TypeError, ValueError):
        try:
            return ast.literal_eval(stripped)
        except (ValueError, SyntaxError):
            return value


def _replay_value_mismatch(recorded: Any, actual: Any, path: str = "return") -> str | None:
    recorded = _parse_recorded_return(recorded)
    if isinstance(recorded, dict) and isinstance(actual, dict):
        recorded_by_key = {str(key): value for key, value in recorded.items()}
        actual_by_key = {str(key): value for key, value in actual.items()}
        recorded_keys = set(recorded_by_key).difference(_VOLATILE_REPLAY_KEYS)
        actual_keys = set(actual_by_key).difference(_VOLATILE_REPLAY_KEYS)
        if recorded_keys != actual_keys:
            return (
                f"{path} keys differ: recorded_only={sorted(recorded_keys - actual_keys)}, "
                f"actual_only={sorted(actual_keys - recorded_keys)}"
            )
        for key in sorted(recorded_keys):
            mismatch = _replay_value_mismatch(
                recorded_by_key[key], actual_by_key[key], f"{path}.{key}"
            )
            if mismatch is not None:
                return mismatch
        return None
    if isinstance(recorded, (list, tuple)) and isinstance(actual, (list, tuple)):
        if len(recorded) != len(actual):
            return f"{path} length differs: recorded={len(recorded)}, actual={len(actual)}"
        for index, (recorded_item, actual_item) in enumerate(zip(recorded, actual)):
            mismatch = _replay_value_mismatch(
                recorded_item, actual_item, f"{path}[{index}]"
            )
            if mismatch is not None:
                return mismatch
        return None
    if isinstance(recorded, (int, float)) and isinstance(actual, (int, float)):
        if math.isclose(float(recorded), float(actual), rel_tol=1e-9, abs_tol=2e-6):
            return None
    elif recorded == actual:
        return None
    return f"{path} differs: recorded={recorded!r}, actual={actual!r}"


def _assert_replay_result(
    step: dict[str, Any],
    actual_return: Any,
    actual_exception: Exception | None,
    *,
    strict_return: bool,
) -> str | None:
    step_name = str(step.get("name") or "<unnamed>")
    tool_name = str(step.get("tool_name") or "<unknown>")
    recorded_return = step.get("content")
    if step.get("op_type") == "TOOL_ERROR":
        if actual_exception is None:
            raise ReplayDivergenceError(
                f"{step_name} {tool_name}: trace recorded TOOL_ERROR but replay succeeded"
            )
        recorded_text = str(recorded_return)
        if type(actual_exception).__name__ not in recorded_text or str(actual_exception) not in recorded_text:
            raise ReplayDivergenceError(
                f"{step_name} {tool_name}: replay exception differs from recorded error: "
                f"{type(actual_exception).__name__}: {actual_exception}"
            )
        return None
    if actual_exception is not None:
        raise ReplayDivergenceError(
            f"{step_name} {tool_name}: replay raised "
            f"{type(actual_exception).__name__}: {actual_exception}"
        )
    recorded_parsed = _parse_recorded_return(recorded_return)
    recorded_error = (
        recorded_parsed.get("error") if isinstance(recorded_parsed, dict) else None
    )
    actual_error = actual_return.get("error") if isinstance(actual_return, dict) else None
    if bool(recorded_error) != bool(actual_error):
        raise ReplayDivergenceError(
            f"{step_name} {tool_name}: error outcome differs: "
            f"recorded={recorded_error!r}, actual={actual_error!r}"
        )
    if recorded_error and actual_error:
        return None

    mismatch = _replay_value_mismatch(recorded_parsed, actual_return)
    if mismatch is not None and strict_return:
        raise ReplayDivergenceError(f"{step_name} {tool_name}: {mismatch}")
    if mismatch is not None:
        return mismatch
    return None


def _assert_replay_outcome(scenario: Any, recorded_outcome: Any) -> None:
    if not isinstance(recorded_outcome, dict) or not recorded_outcome:
        raise ReplayDivergenceError("run report has no outcome checkpoint")
    farm_world = next(
        (
            app
            for app in scenario.apps or []
            if app.__class__.__name__ == "FarmWorldApp"
        ),
        None,
    )
    if farm_world is None:
        raise ReplayDivergenceError("recorded outcome exists but FarmWorldApp is missing")

    states = list(farm_world.physics.yield_recovery.states.values())
    harvested_states = [state for state in states if getattr(state, "harvested", False)]
    selected = harvested_states or states
    actual_outcome: dict[str, Any] = {"inventory": farm_world.get_inventory()}
    if states:
        denominator = len(selected)
        actual_outcome["yield_recovery"] = {
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
                sum(
                    float(getattr(state, "quality_discount_fraction", 0.0))
                    for state in selected
                )
                / denominator,
                6,
            ),
        }
    mismatch = _replay_value_mismatch(recorded_outcome, actual_outcome, "outcome")
    if mismatch is not None:
        raise ReplayDivergenceError(mismatch)


def _replay_fairy_run_bundle(bundle: dict[str, Any]) -> tuple[Any, Any, dict[str, Any]]:
    """Returns (scenario, env, info) where env has a populated EventLog."""
    from fairy.types import EventLog

    scenario_id = bundle.get("scenario_id")
    if not scenario_id:
        raise ValueError("FAIRY run bundle has no scenario_id")
    start_time = bundle.get("start_time")
    seed = bundle.get("seed") or 0

    scenario = _instantiate_scenario_for_replay(scenario_id, start_time, seed)
    apps_by_name = {a.name: a for a in scenario.apps or []}
    apps_by_class = {a.__class__.__name__: a for a in scenario.apps or []}

    tool_steps = _iter_fairy_tool_steps(bundle.get("workflow"))
    info = {
        "scenario_id": scenario_id,
        "start_time": start_time,
        "seed": seed,
        "n_completed_events": len(tool_steps),
        "n_replayed": 0,
        "n_skipped": 0,
        "skipped_reasons": {},
        "exec_errors": 0,
        "exact_timing_steps": 0,
        "legacy_timing_steps": 0,
        "observation_mismatches": 0,
        "observation_mismatch_examples": [],
        "outcome_checkpoint_verified": False,
    }

    rebound_events = []
    last_event_time: float | None = _workflow_initial_timestamp(
        bundle.get("workflow"), scenario.start_time
    )
    for step in tool_steps:
        tool_name = str(step.get("tool_name") or "")
        try:
            target_app_name, fn_name = _tool_name_parts(tool_name)
        except ValueError:
            info["n_skipped"] += 1
            info["skipped_reasons"]["bad_tool_name"] = (
                info["skipped_reasons"].get("bad_tool_name", 0) + 1
            )
            continue
        target_app = apps_by_name.get(target_app_name) or apps_by_class.get(
            target_app_name
        )
        if target_app is None:
            info["n_skipped"] += 1
            info["skipped_reasons"][f"unknown_app:{target_app_name}"] = (
                info["skipped_reasons"].get(f"unknown_app:{target_app_name}", 0) + 1
            )
            continue

        args = step.get("tool_args") or {}
        if not isinstance(args, dict):
            args = {}
        method = getattr(target_app, fn_name, None)
        if not callable(method):
            raise ReplayDivergenceError(
                f"{step.get('name')} {tool_name}: target method is missing"
            )
        pre_time, post_time, exact_timing = _workflow_step_times(
            step, method, last_event_time
        )
        timing_key = "exact_timing_steps" if exact_timing else "legacy_timing_steps"
        info[timing_key] += 1

        exception_obj = None
        actual_return = None
        try:
            _align_replay_time(scenario, pre_time)
            actual_return = method(**args)
        except ReplayDivergenceError:
            raise
        except Exception as exc:
            exception_obj = exc
            info["exec_errors"] += 1

        return_value = step.get("content")
        from fairy.types import OperationType

        strict_return = (
            tool_name == "SystemApp__advance_time"
            or _operation_type_for_method(method) == OperationType.WRITE
        )
        observation_mismatch = _assert_replay_result(
            step,
            actual_return,
            exception_obj,
            strict_return=strict_return,
        )
        if observation_mismatch is not None:
            info["observation_mismatches"] += 1
            if len(info["observation_mismatch_examples"]) < 5:
                info["observation_mismatch_examples"].append(
                    f"{step.get('name')} {tool_name}: {observation_mismatch}"
                )
        _align_replay_time(scenario, post_time)
        rebound_events.append(
            _build_completed_event_from_workflow_step(
                step,
                target_app,
                fn_name,
                args,
                post_time,
                return_value,
                exception_obj,
            )
        )
        info["n_replayed"] += 1
        last_event_time = post_time

    _assert_replay_outcome(scenario, (bundle.get("run_report") or {}).get("outcome"))
    info["outcome_checkpoint_verified"] = True

    env = SimpleNamespace(
        event_log=EventLog.from_list_view(rebound_events),
        dump_dir=None,
    )
    return scenario, env, info


# ---------------------------------------------------------------------------
# Per-cell driver
# ---------------------------------------------------------------------------


def _classify_level(scenario_id: str) -> str:
    if "fullseason" in scenario_id or "full_season" in scenario_id:
        return "level3_fullseason"
    if scenario_id.startswith("scenario_physics_") or scenario_id.startswith(
        "scenario_full_season_"
    ):
        return "level2_episode"
    if "_physics_action_tick" in scenario_id:
        return "level1_baseline"
    return "unknown"


def _gates_for_scenario(scenario: Any) -> list[Any]:
    """Look up the scenario's _gates() if present, else empty."""
    fn = getattr(scenario, "_gates", None)
    if not callable(fn):
        return []
    try:
        return list(fn())
    except Exception:
        return []


def _parse_run_slug(cell_dir: Path, out_root: Path) -> dict[str, Any]:
    """Extract llm, level, detail, a2a from the run-slug directory.

    The run-slug sits one level above the cell in the ``phase5_paper_matrix/``
    layout, e.g.::

        validation_runs/iclr_<ts>/phase5_paper_matrix/deepseek_level1_detail_false_a2a_off/<cell>/

    When the cell_dir already lives under *out_root* (after a previous
    rebatch run), the run-slug info is not available from the path; we leave
    those fields empty so the caller can supply them via CLI override.
    """
    parts = Path(cell_dir).parts
    slug = ""
    for i, part in enumerate(parts):
        if part == "phase5_paper_matrix":
            if i + 1 < len(parts):
                slug = parts[i + 1]
            break
    if not slug:
        for part in reversed(parts[:-1]):
            part_lower = part.lower()
            if any(
                marker in part_lower
                for marker in (
                    "detail_true",
                    "detail_false",
                    "detail_kwoo",
                    "detail_library",
                )
            ):
                slug = part
                break
    if not slug:
        return {"llm_model": "", "run_level": "", "detail_status": "", "a2a_status": ""}

    # e.g. "deepseek_level1_detail_false_a2a_off"
    mapping = {
        "llm_model": "",
        "run_level": "",
        "detail_status": "",
        "a2a_status": "",
    }

    slug_lower = slug.lower()

    # Level
    for lvl in ("level4", "level3", "level2", "level1"):
        if lvl in slug_lower:
            mapping["run_level"] = lvl
            break

    # Model (ordered by specificity)
    if slug_lower.startswith("vllm") or "vllm" in slug_lower:
        mapping["llm_model"] = "vLLM"
    elif slug_lower.startswith("qwen"):
        mapping["llm_model"] = "Qwen"
    elif slug_lower.startswith("deepseek"):
        mapping["llm_model"] = "DeepSeek"
    elif slug_lower.startswith("gpt"):
        mapping["llm_model"] = "GPT"

    # Detail
    if "detail_true" in slug_lower:
        mapping["detail_status"] = "True"
    elif "detail_false" in slug_lower:
        mapping["detail_status"] = "False"
    elif "detail_kwoo" in slug_lower:
        mapping["detail_status"] = "Kwoo"
    elif "detail_library" in slug_lower:
        mapping["detail_status"] = "Library"
    else:
        mapping["detail_status"] = "unknown"

    # A2A
    if "a2a_on" in slug_lower or "a2a_true" in slug_lower:
        mapping["a2a_status"] = "on"
    elif "a2a_off" in slug_lower or "a2a_false" in slug_lower:
        mapping["a2a_status"] = "off"
    else:
        mapping["a2a_status"] = "unknown"

    return mapping


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _a2a_enabled_from_status(status: Any) -> bool | None:
    text = str(status or "").strip().lower()
    if text == "on":
        return True
    if text == "off":
        return False
    return None


def _set_a2a_fields(row: dict[str, Any], enabled: bool | None) -> None:
    if enabled is None:
        return
    row["a2a_enabled"] = "true" if enabled else "false"
    row["a2a_status"] = "on" if enabled else "off"


def _normalize_model_family_label(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    lowered = text.lower()
    if lowered == "vllm":
        return "vLLM"
    if lowered == "qwen":
        return "Qwen"
    if lowered == "deepseek":
        return "DeepSeek"
    if lowered == "gpt":
        return "GPT"
    return text


def _normalize_detailed_briefing_value(value: Any) -> str:
    """Return a stable CSV label for scenario_kwargs.detailed_briefing."""
    if value is None or value == "":
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        stripped = value.strip()
        lowered = stripped.lower()
        if lowered in {"true", "false"}:
            return lowered
        if lowered in {"none", "null"}:
            return ""
        return stripped
    return str(value)


def _parse_detailed_briefing_from_kwargs(raw: Any) -> str:
    """Extract detailed_briefing from a results.csv scenario_kwargs cell."""
    if raw is None or raw == "":
        return ""
    if isinstance(raw, dict):
        payload = raw
    else:
        try:
            payload = json.loads(str(raw))
        except json.JSONDecodeError:
            return ""
    if not isinstance(payload, dict):
        return ""
    return _normalize_detailed_briefing_value(payload.get("detailed_briefing"))


def _result_cell_matches(cell_dir: Path, raw_cell_dir: str, results_path: Path) -> bool:
    """Match a results.csv row to an absolute trace cell directory.

    Runner outputs often store cell_dir relative to the runner repo, while
    rebatch may be run from this repo checkout against a sibling validation
    directory.  Exact absolute paths are ideal, but suffix matching is needed
    for the common "validation_runs/.../<cell>" relative form.
    """
    if not raw_cell_dir:
        return False

    target = cell_dir.resolve()
    raw_path = Path(raw_cell_dir)
    if raw_path.is_absolute():
        try:
            return raw_path.resolve() == target
        except OSError:
            return raw_path == target

    raw_posix = raw_path.as_posix().rstrip("/")
    target_posix = target.as_posix().rstrip("/")
    if target_posix.endswith(raw_posix):
        return True

    candidates = [
        (results_path.parent / raw_path),
        (results_path.parent.parent / raw_path),
        (_REPO_ROOT / raw_path),
    ]
    for candidate in candidates:
        try:
            if candidate.resolve() == target:
                return True
        except OSError:
            continue

    return raw_path.name == target.name


def _detailed_briefing_from_results_csv(cell_dir: Path) -> str:
    """Look up the real detailed_briefing value from the run results.csv."""
    for parent in (cell_dir, *cell_dir.parents):
        results_path = parent / "results.csv"
        if not results_path.is_file():
            continue
        try:
            with results_path.open(newline="", encoding="utf-8") as handle:
                for result_row in csv.DictReader(handle):
                    raw_cell_dir = result_row.get("cell_dir") or ""
                    if not _result_cell_matches(cell_dir, raw_cell_dir, results_path):
                        continue
                    detailed = _parse_detailed_briefing_from_kwargs(
                        result_row.get("scenario_kwargs")
                    )
                    if detailed:
                        return detailed
                    return _normalize_detailed_briefing_value(
                        result_row.get("detail_enabled")
                    )
        except OSError:
            continue
    return ""


def _model_family_from_results_csv(cell_dir: Path) -> str:
    """Look up the runner's explicit model_family value from results.csv."""
    for parent in (cell_dir, *cell_dir.parents):
        results_path = parent / "results.csv"
        if not results_path.is_file():
            continue
        try:
            with results_path.open(newline="", encoding="utf-8") as handle:
                for result_row in csv.DictReader(handle):
                    raw_cell_dir = result_row.get("cell_dir") or ""
                    if not _result_cell_matches(cell_dir, raw_cell_dir, results_path):
                        continue
                    return _normalize_model_family_label(
                        result_row.get("model_family")
                        or result_row.get("llm_model")
                        or ""
                    )
        except OSError:
            continue
    return ""


def _model_type_size_from_results_csv(cell_dir: Path) -> str:
    """Look up the exact model id/name from the runner results.csv."""
    for parent in (cell_dir, *cell_dir.parents):
        results_path = parent / "results.csv"
        if not results_path.is_file():
            continue
        try:
            with results_path.open(newline="", encoding="utf-8") as handle:
                for result_row in csv.DictReader(handle):
                    raw_cell_dir = result_row.get("cell_dir") or ""
                    if not _result_cell_matches(cell_dir, raw_cell_dir, results_path):
                        continue
                    return str(result_row.get("model") or "").strip()
        except OSError:
            continue
    return ""


def _number_or_zero(value: Any) -> float:
    if value in (None, "") or value is True or value is False:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _format_metric_number(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


_LOG_TIMESTAMP_RE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})")
_LOG_MODEL_RE = re.compile(r"\b(?:LLM usage|LLM request): model=([^\s]+)")
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
_PY_ERROR_LINE_RE = re.compile(
    r"^(?P<type>(?:[A-Za-z_][\w]*\.)*[A-Za-z_][\w]*(?:Error|Exception)|"
    r"AssertionError|KeyboardInterrupt|TimeoutError|CancelledError)"
    r"(?::\s*(?P<message>.*))?$"
)


def _log_span_s_from_cell_logs(cell_dir: Path) -> float | None:
    """Return wall-clock span covered by stdout/stderr timestamps."""
    first: datetime | None = None
    last: datetime | None = None
    for log_name in ("stdout.log", "stderr.log"):
        log_path = cell_dir / log_name
        if not log_path.is_file():
            continue
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            match = _LOG_TIMESTAMP_RE.search(line)
            if not match:
                continue
            timestamp = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S,%f")
            if first is None or timestamp < first:
                first = timestamp
            if last is None or timestamp > last:
                last = timestamp
    if first is None or last is None:
        return None
    return max(0.0, (last - first).total_seconds())


def _model_type_size_from_cell_logs(cell_dir: Path) -> str:
    for log_name in ("stderr.log", "stdout.log"):
        log_path = cell_dir / log_name
        if not log_path.is_file():
            continue
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = _LOG_MODEL_RE.search(text)
        if match:
            return match.group(1).strip()
    return ""


def _stderr_failure_from_cell_logs(cell_dir: Path) -> dict[str, str]:
    """Extract a compact failure summary from stderr.log for no-trace cells."""
    log_path = cell_dir / "stderr.log"
    if not log_path.is_file():
        return {}
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    text = _ANSI_ESCAPE_RE.sub("", text)
    lines = [line.rstrip() for line in text.splitlines()]
    nonempty = [line for line in lines if line.strip()]
    if not nonempty:
        return {"run_error_source": "stderr.log"}

    traceback_start = None
    for idx, line in enumerate(lines):
        if "Traceback (most recent call last):" in line:
            traceback_start = idx
    tail_lines = lines[-80:] if traceback_start is None else lines[traceback_start:]
    if len(tail_lines) > 80:
        tail_lines = tail_lines[-80:]
    tail = "\n".join(tail_lines).strip()

    error_type = ""
    error_message = ""
    for line in reversed(nonempty):
        match = _PY_ERROR_LINE_RE.match(line.strip())
        if match:
            error_type = match.group("type")
            error_message = match.group("message") or ""
            break
    if not error_type:
        for marker in ("429", "timed out", "timeout", "404 Not Found", "AssertionError"):
            for line in reversed(nonempty):
                if marker.lower() in line.lower():
                    error_type = marker
                    error_message = line.strip()
                    break
            if error_type:
                break

    return {
        "run_error_source": "stderr.log",
        "run_error_type": error_type,
        "run_error_message": error_message,
        "stderr_traceback_tail": tail,
    }


def _llm_usage_from_run_report(run_report: dict[str, Any]) -> dict[str, Any]:
    """Aggregate token/runtime metrics from FAIRY run_report.json."""
    metrics = run_report.get("metrics") or {}
    usage = metrics.get("token_usage") or {}
    calls = int(_number_or_zero(metrics.get("llm_call_count")))
    total_tokens = _number_or_zero(usage.get("total_tokens"))
    input_tokens = _number_or_zero(usage.get("prompt_tokens"))
    output_tokens = _number_or_zero(usage.get("completion_tokens"))
    cached_tokens_total = _number_or_zero(usage.get("cached_tokens"))
    total_runtime_s = _number_or_zero(metrics.get("llm_wall_time_seconds"))
    model_name = str(run_report.get("model") or "").strip()

    out: dict[str, Any] = {}
    if model_name:
        out["model_type_size"] = model_name
    if metrics.get("wall_time_seconds") is not None:
        out["runtime_s_per_scenario"] = _format_metric_number(
            _number_or_zero(metrics.get("wall_time_seconds"))
        )
    if calls <= 0:
        return out
    out.update(
        {
            "llm_calls_with_usage": calls,
            "avg_total_tokens_per_agent_call": _format_metric_number(
                total_tokens / calls
            ),
            "avg_input_tokens_per_agent_call": _format_metric_number(
                input_tokens / calls
            ),
            "avg_output_tokens_per_agent_call": _format_metric_number(
                output_tokens / calls
            ),
            "avg_cached_tokens_per_agent_call": _format_metric_number(
                cached_tokens_total / calls
            ),
            "total_tokens_per_scenario": _format_metric_number(total_tokens),
            "avg_runtime_s_per_agent_call": _format_metric_number(
                total_runtime_s / calls
            ),
        }
    )
    return out


def _detailed_briefing_from_detail_status(detail_status: Any) -> str:
    """Fallback for older runs that have no results.csv nearby."""
    status = str(detail_status or "").strip().lower()
    if status in {"true", "false", "kwoo", "library"}:
        return status
    return ""


_SELECTED_L3_20_SCENARIOS: frozenset[str] = frozenset(
    {
        "scenario_full_season_hb_heihe43_early_density_weed_nutrient_recovery",
        "scenario_full_season_hb_coldspring_planting_window_heihe50",
        "scenario_full_season_hb_wetcold_high_residue_establishment",
        "scenario_full_season_heinong84_staggered_planting",
        "scenario_full_season_hb_fertilizer_quota_edge_lowfertility",
        "scenario_full_season_hb_insect_after_fungicide_budget_conflict",
        "scenario_full_season_hb_two_dry_patches_one_irrigation",
        "scenario_full_season_hb_wetjune_shortwindow_trafficability",
        "scenario_full_season_hb_storage_capacity_limit_batching",
        "scenario_full_season_hb_three_cultivar_wet_disease_dry_harvest_sequence",
        "scenario_full_season_hb_heinong58_water_chemical_priority_under_dual_stress",
        "scenario_full_season_hb_r5_leaf_feeder_defoliation",
        "scenario_full_season_hb_heinong60_highdensity_fertigation_irrigation_water_budget",
        "scenario_full_season_hb_lowcarbon_batch_operations_wetdisease",
        "scenario_full_season_hb_laterain_insect_risk",
        "scenario_full_season_hb_planter_skip_rows_stand_gap",
        "scenario_full_season_hb_high_weed_seedbank_mechanical_only_baseline",
        "scenario_full_season_hb_wetjune_disease_recheck_after_fungicide",
        "scenario_full_season_hb_potassium_deficit_dry_podfill_interaction",
        "scenario_full_season_hb_disease_then_drought_recovery_tradeoff",
    }
)


def _scenario_id_from_cell_name(cell_name: str) -> str:
    parts = cell_name.split("__")
    return parts[1] if len(parts) >= 2 else ""


def _l3_pool_for_scenario(scenario_id: str) -> str:
    if scenario_id in _SELECTED_L3_20_SCENARIOS:
        return "20"
    if scenario_id.startswith("scenario_full_season"):
        return "70"
    return "unknown"


def _pct(v: Any) -> str:
    """Convert a 0-1 decimal to 100-scale with 2 decimal places.

    Returns a string like ``97.88`` (no % suffix). Non-numeric or out-of-range
    values pass through as empty string.
    """
    if v is None or v == "" or v is True or v is False:
        return ""
    try:
        fv = float(v)
    except (ValueError, TypeError):
        return ""
    return f"{fv * 100:.2f}"


def _agent_family_from_cell(cell_name: str) -> str:
    """Extract the agent family name from the cell directory name.

    E.g. ``farm_adaptive_verifier__scenario_xxx__r1`` → ``adaptive_verifier``.
    """
    if "__" not in cell_name:
        return ""
    return cell_name.split("__", 1)[0].removeprefix("farm_")


def replay_one_cell(
    cell_dir: Path,
    out_root: Path,
    extrapolate: bool,
    extrapolation_max_days: int,
    oracle_baseline_dir: Path | None = None,
    donothing_inline: bool = False,
    path_correctness_v2: bool = True,
    pc2_tol: float = 2.0,
    focus_ridges_config: dict[str, list[int]] | None = None,
    output_rel: Path | None = None,
) -> dict[str, Any]:
    """Replay one cell + re-eval. Returns a CSV-ready row dict."""
    rel = output_rel if output_rel is not None else Path(cell_dir.name)
    slug_info = _parse_run_slug(cell_dir, out_root)
    row: dict[str, Any] = {
        "cell": cell_dir.name,
        "cell_output_rel": rel.as_posix(),
        "cell_dir": str(cell_dir),
        "agent_family": _agent_family_from_cell(cell_dir.name),
        "status": "ok",
    }
    row.update(slug_info)
    _set_a2a_fields(row, _a2a_enabled_from_status(row.get("a2a_status")))
    model_family = _model_family_from_results_csv(cell_dir)
    if model_family:
        row["llm_model"] = model_family
    model_type_size = _model_type_size_from_results_csv(cell_dir)
    if model_type_size:
        row["model_type_size"] = model_type_size
    else:
        model_type_size = _model_type_size_from_cell_logs(cell_dir)
        if model_type_size:
            row["model_type_size"] = model_type_size
    log_span_s = _log_span_s_from_cell_logs(cell_dir)
    if log_span_s is not None:
        row["runtime_s_per_scenario"] = _format_metric_number(log_span_s)
    bundle = _load_fairy_run_bundle(cell_dir)
    if bundle is None:
        row.update(_stderr_failure_from_cell_logs(cell_dir))
        scenario_id = _scenario_id_from_cell_name(cell_dir.name)
        if scenario_id:
            row["scenario"] = scenario_id
            row["l3_pool"] = _l3_pool_for_scenario(scenario_id)
        row["detailed_briefing"] = (
            _detailed_briefing_from_results_csv(cell_dir)
            or _detailed_briefing_from_detail_status(row.get("detail_status"))
        )
        row["status"] = "no_agent_workflow"
        return row
    run_report = bundle.get("run_report") or {}
    scenario_id = str(bundle.get("scenario_id") or "")
    if scenario_id:
        row["scenario"] = scenario_id
        row["l3_pool"] = _l3_pool_for_scenario(scenario_id)
    if run_report.get("controller_id"):
        row["agent_family"] = str(run_report.get("controller_id")).removeprefix("farm_")
    if run_report.get("provider") and not row.get("llm_model"):
        row["llm_model"] = _normalize_model_family_label(run_report.get("provider"))
    if run_report.get("model") and not row.get("model_type_size"):
        row["model_type_size"] = str(run_report.get("model"))
    report_a2a = (run_report.get("a2a") or {}).get("enabled")
    _set_a2a_fields(row, _coerce_bool(report_a2a))
    usage_metrics = _llm_usage_from_run_report(run_report)
    report_model_type_size = usage_metrics.pop("model_type_size", "")
    if not row.get("model_type_size") and report_model_type_size:
        row["model_type_size"] = report_model_type_size
    row.update(usage_metrics)
    row["detailed_briefing"] = (
        _detailed_briefing_from_results_csv(cell_dir)
        or _detailed_briefing_from_detail_status(row.get("detail_status"))
    )

    # ---- Inline do-nothing baseline (optional, no pre-built JSON needed) ----
    # Computed BEFORE the agent replay from a fresh scenario instance that
    # shares the same (scenario_id, start_time, seed) so the physics seed
    # is identical.
    inline_donothing_kg: float | None = None
    inline_donothing_per_ridge: list[float] | None = None
    if donothing_inline and extrapolate:
        try:
            _dn_scenario_id = bundle.get("scenario_id")
            _dn_start_time = bundle.get("start_time")
            _dn_seed = int(bundle.get("seed") or 0)
            if _dn_scenario_id:
                # Use the per-ridge variant so we get both the total kg AND
                # the per-ridge yield array — needed to score focus subsets
                # without a pre-built baseline JSON.
                from fairy.scenarios.fos.evaluation import (
                    compute_donothing_per_ridge_yields,
                )

                total, per_ridge = compute_donothing_per_ridge_yields(
                    _dn_scenario_id,
                    start_time=_dn_start_time,
                    seed=_dn_seed,
                    extrapolation_max_days=extrapolation_max_days,
                )
                inline_donothing_kg = total
                inline_donothing_per_ridge = per_ridge
        except Exception:
            inline_donothing_kg = None
            inline_donothing_per_ridge = None

    try:
        scenario, env, info = _replay_fairy_run_bundle(bundle)
    except KeyError as exc:
        row["status"] = "scenario_not_in_registry"
        row["error"] = str(exc)
        return row
    except Exception as exc:
        row["status"] = "replay_failed"
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["traceback"] = traceback.format_exc(limit=3)
        return row

    row["scenario"] = info["scenario_id"]
    row["l3_pool"] = _l3_pool_for_scenario(info["scenario_id"])
    row["level"] = _classify_level(info["scenario_id"])
    row["replayed_events"] = info["n_replayed"]
    row["replay_skipped"] = info["n_skipped"]
    row["replay_exec_errors"] = info["exec_errors"]
    row["replay_exact_timing_steps"] = info["exact_timing_steps"]
    row["replay_legacy_timing_steps"] = info["legacy_timing_steps"]
    row["replay_observation_mismatches"] = info["observation_mismatches"]
    row["replay_observation_mismatch_examples"] = json.dumps(
        info["observation_mismatch_examples"], ensure_ascii=False
    )
    row["replay_outcome_checkpoint_verified"] = info[
        "outcome_checkpoint_verified"
    ]
    if inline_donothing_kg is not None:
        row["donothing_biological_kg_inline"] = round(inline_donothing_kg, 2)

    # Per-cell FOS export dir to avoid cross-process write collisions.
    cell_out = out_root / rel
    fos_dir = cell_out / "fos"
    fos_dir.mkdir(parents=True, exist_ok=True)
    os.environ["FOS_EXPORT_DIR"] = str(fos_dir.parent)

    gates = _gates_for_scenario(scenario)

    # Resolve focus ridge ids from the per-scenario JSON config (if provided).
    # Looked up by scenario_id; missing keys mean "no focus subset for this cell".
    cell_focus_ridge_ids: list[int] | None = None
    if focus_ridges_config:
        sid = info["scenario_id"]
        raw_ids = focus_ridges_config.get(sid)
        if isinstance(raw_ids, list):
            try:
                cell_focus_ridge_ids = [int(x) for x in raw_ids]
            except (TypeError, ValueError):
                cell_focus_ridge_ids = None

    try:
        from fairy.scenarios.fos.evaluation import evaluate_fos

        report = evaluate_fos(
            scenario,
            env,
            gates=gates,
            extrapolate_to_maturity=extrapolate,
            extrapolation_max_days=extrapolation_max_days,
            oracle_baseline_dir=oracle_baseline_dir,
            donothing_biological_kg=inline_donothing_kg,
            donothing_per_ridge_g_m2=inline_donothing_per_ridge,
            focus_ridge_ids=cell_focus_ridge_ids,
        )
    except Exception as exc:
        row["status"] = "eval_failed"
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["traceback"] = traceback.format_exc(limit=3)
        return row

    # Persist the structured report.
    fos_path = fos_dir / f"fos_{info['scenario_id']}.json"
    fos_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    row["fos_path"] = str(fos_path)

    comp = report.components
    ob = report.outcome_breakdown
    eb = report.efficiency_breakdown

    # Extract yield-preserved ratio as raw decimal (for pct_yield_loss calc)
    ypr_raw = ob.yield_preserved_ratio

    row.update(
        {
            "outcome(%)": _pct(comp.outcome),
            "decision(%)": _pct(comp.decision),
            "efficiency(%)": _pct(comp.efficiency),
            "fos(%)": _pct(comp.fos),
            "yield_ratio(%)": _pct(ob.yield_ratio),
            "yield_loss(%)": (
                _pct(1.0 - ypr_raw) if ypr_raw is not None and ypr_raw != "" else ""
            ),
            "recovered_yield_loss(%)": (
                _pct(ob.recovered_yield_loss)
                if ob.recovered_yield_loss is not None
                else ""
            ),
            "recovered_yield_loss_v2(%)": (
                _pct(ob.recovered_yield_loss_v2)
                if ob.recovered_yield_loss_v2 is not None
                else ""
            ),
            "agent_recovered_yield_kg": round(ob.agent_recovered_yield_kg, 2),
            "oracle_recovered_yield_kg": (
                round(ob.oracle_recovered_yield_kg, 2)
                if ob.oracle_recovered_yield_kg is not None
                else ""
            ),
            "scenario_potential_kg": round(ob.scenario_potential_kg, 2),
            "agent_biological_kg": round(ob.agent_biological_kg, 2),
            "oracle_biological_kg": (
                round(ob.oracle_biological_kg, 2)
                if ob.oracle_biological_kg is not None
                else ""
            ),
            "donothing_biological_kg": (
                round(ob.donothing_biological_kg, 2)
                if ob.donothing_biological_kg is not None
                else ""
            ),
            "normalized_yield_score(%)": (
                _pct(ob.normalized_yield_score)
                if ob.normalized_yield_score is not None
                else ""
            ),
            "yield_preserved_ratio(%)": (
                _pct(ypr_raw) if ypr_raw is not None and ypr_raw != "" else ""
            ),
            "crop_loss_pct(%)": (
                _pct(ob.crop_loss_pct) if ob.crop_loss_pct is not None else ""
            ),
            "expects_agent_harvest": ob.expects_agent_harvest,
            "growing_loss": ob.growing_loss_count,
            "harvest_loss": ob.harvest_loss_count,
            "unharvested_mature": ob.unharvested_mature_count,
            "crop_loss": ob.crop_loss_count,
            "crop_loss_fraction(%)": (
                _pct(ob.crop_loss_fraction) if ob.crop_loss_fraction is not None else ""
            ),
            "safety_violations": ob.safety_violations,
            "tool_inflation": round(eb.tool_inflation, 4),
            "redundant_reads": eb.redundant_reads,
            "agent_tool_calls": eb.agent_tool_calls,
            "oracle_tool_calls": eb.oracle_tool_calls,
            "gates_matched": sum(1 for g in report.decision_breakdown if g.matched),
            "gates_total": len(report.decision_breakdown),
            "extrapolation_status": (
                ob.extrapolation.get("status") if ob.extrapolation else ""
            ),
            "extrapolation_days": (
                ob.extrapolation.get("days_ticked") if ob.extrapolation else ""
            ),
            "focus_ridge_ids": (
                ",".join(str(i) for i in ob.focus_ridge_ids)
                if ob.focus_ridge_ids
                else ""
            ),
            "focus_agent_biological_kg": (
                round(ob.focus_agent_biological_kg, 2)
                if ob.focus_agent_biological_kg is not None
                else ""
            ),
            "focus_oracle_biological_kg": (
                round(ob.focus_oracle_biological_kg, 2)
                if ob.focus_oracle_biological_kg is not None
                else ""
            ),
            "focus_donothing_biological_kg": (
                round(ob.focus_donothing_biological_kg, 2)
                if ob.focus_donothing_biological_kg is not None
                else ""
            ),
            "focus_yield_preserved_ratio(%)": (
                _pct(ob.focus_yield_preserved_ratio)
                if ob.focus_yield_preserved_ratio is not None
                else ""
            ),
            "focus_normalized_yield_score(%)": (
                _pct(ob.focus_normalized_yield_score)
                if ob.focus_normalized_yield_score is not None
                else ""
            ),
            "extrapolation_reached_r8": (
                ob.extrapolation.get("reached_maturity") if ob.extrapolation else ""
            ),
        }
    )

    # ---- Optional: legacy v1 + relaxed-numeric v2 path_correctness -------
    # When --path-correctness-v2 is set, we emit BOTH:
    #   * v1 (legacy): path_correctness / coverage / ktc_raw / ktc_adjusted /
    #     combined — produced by workflow_validation.evaluate_workflows
    #     (byte-identical args alphabet).
    #   * v2: path_correctness_v2 / coverage_v2 / ktc_raw_v2 /
    #     ktc_adjusted_v2 / combined_v2 — same formulas, but the alphabet
    #     treats numeric args within the tol-ratio window as one symbol,
    #     and same-tool oracle anchors are matched closest-first.
    # The pair is written together so v1 vs v2 can be diff'd per cell.
    if path_correctness_v2:
        try:
            from fairy.scenarios.fos.path_correctness_v2 import (
                evaluate_path_correctness_v2,
            )
            from fairy.scenarios.workflow_validation import (
                evaluate_workflows,
                workflow_from_event_log,
                workflow_from_oracle_events,
            )

            oracle_wf = workflow_from_oracle_events(scenario)
            agent_wf = workflow_from_event_log(list(env.event_log.list_view()))

            evaluate_workflows(oracle_wf, agent_wf)
            # Convert v1 workflow metrics (0-1) to 100-scale.
            # for k in ("path_correctness", "coverage", "ktc_raw", "ktc_adjusted", "combined"):
            #     row[k] = _pct(v1_metrics.get(k))

            pc2 = evaluate_path_correctness_v2(oracle_wf, agent_wf, tol_ratio=pc2_tol)

            row["path_correctness(%)"] = _pct(pc2.get("path_correctness_v2"))
            row["coverage(%)"] = _pct(pc2.get("coverage_v2"))
            row["ktc_score(%)"] = _pct(pc2.get("ktc_raw_v2"))
            row["ktc_adjusted(%)"] = _pct(pc2.get("ktc_adjusted_v2"))
            row["combined(%)"] = _pct(pc2.get("combined_v2"))
            # row["pc2_n_oracle_steps"] = pc2["n_oracle_steps"]
            # row["pc2_n_agent_steps"] = pc2["n_agent_steps"]
            # row["pc2_levenshtein"] = pc2["levenshtein_distance"]
            # row["pc2_tol_ratio"] = pc2["tol_ratio"]
            # row["pc2_n_agent_reused"] = pc2["n_agent_reused"]
            # row["pc2_n_agent_fresh"] = pc2["n_agent_fresh"]
            # row["pc2_path"] = str(pc2_detail_path)
        except Exception as exc:
            row["path_correctness_v2_error"] = f"{type(exc).__name__}: {exc}"

    # ---- FARM-FOS (ours) + BFCL + v1 CORE/KTC baselines -------------------
    # Standalone block (independent of the optional path_correctness_v2 module,
    # which may be absent on some branches). All four metrics are computed from
    # the SAME (oracle, agent) workflows so the comparison is apples-to-apples.
    # FARM-FOS needs real per-action timestamps: the static
    # workflow_from_oracle_events(...) leaves time=None until oracle mode runs,
    # so we use ensure_oracle_workflow (runs+caches oracle mode) for the oracle
    # side, giving absolute sim-times comparable to the agent trace.
    try:
        from fairy.scenarios.fos.spatiotemporal import (
            baseline_bfcl,
            compute_farm_fos,
            compute_farm_fos_v2,
        )
        from fairy.scenarios.workflow_validation import (
            ensure_oracle_workflow,
            evaluate_workflows,
            workflow_from_event_log,
        )

        oracle_wf_timed = ensure_oracle_workflow(scenario)
        agent_wf_ff = workflow_from_event_log(list(env.event_log.list_view()))

        base_v1 = evaluate_workflows(oracle_wf_timed, agent_wf_ff)
        row["core_path_correctness(%)"] = _pct(base_v1.get("path_correctness"))
        row["ktc(%)"] = _pct(base_v1.get("ktc_raw"))
        row["coverage_v1(%)"] = _pct(base_v1.get("coverage"))

        ff = compute_farm_fos(oracle_wf_timed, agent_wf_ff)
        row["farm_fos(%)"] = _pct(ff.farm_fos) if ff.farm_fos is not None else ""
        row["farm_fos_n_decisions"] = ff.n_oracle_decisions
        row["farm_fos_n_matched"] = ff.n_matched
        ff2 = compute_farm_fos_v2(oracle_wf_timed, agent_wf_ff)
        row["farm_fos_v2_total(%)"] = (
            _pct(ff2.farm_fos_v2_total)
            if ff2.farm_fos_v2_total is not None
            else ""
        )
        row["farm_fos_v2_path(%)"] = (
            _pct(ff2.farm_fos_v2_path)
            if ff2.farm_fos_v2_path is not None
            else ""
        )
        row["farm_fos_v2_param(%)"] = _pct(ff2.farm_fos_v2_param)
        row["farm_fos_v2_terminal(%)"] = _pct(ff2.farm_fos_v2_terminal)
        v2_diag = ff2.diagnosis
        row["farm_fos_v2_missing_plant_ridges"] = v2_diag.missing_plant_ridges
        row["farm_fos_v2_density_error_pct"] = (
            round(v2_diag.density_error_pct, 3)
            if v2_diag.density_error_pct is not None
            else ""
        )
        row["farm_fos_v2_depth_error_cm"] = (
            round(v2_diag.depth_error_cm, 3)
            if v2_diag.depth_error_cm is not None
            else ""
        )
        row["farm_fos_v2_missing_management_actions"] = (
            v2_diag.missing_management_actions
        )
        row["farm_fos_v2_missing_harvest_ridges"] = v2_diag.missing_harvest_ridges
        row["farm_fos_v2_postharvest_incomplete"] = v2_diag.postharvest_incomplete
        row["farm_fos_v2_postharvest_warning"] = v2_diag.postharvest_warning
        row["farm_fos_v2_early_or_late_action_days"] = (
            round(v2_diag.early_or_late_action_days, 3)
            if v2_diag.early_or_late_action_days is not None
            else ""
        )
        row["farm_fos_v2_tool_error_returns"] = v2_diag.tool_error_returns
        row["farm_fos_v2_primary_issue"] = v2_diag.primary_issue
        row["bfcl_success(%)"] = _pct(baseline_bfcl(oracle_wf_timed, agent_wf_ff))
        try:
            fos_payload = json.loads(fos_path.read_text(encoding="utf-8"))
            fos_payload["farm_fos_spatiotemporal"] = ff.to_dict()
            fos_payload["farm_fos_v2"] = ff2.to_dict()
            fos_path.write_text(
                json.dumps(fos_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass
    except Exception as exc:
        import traceback as _tb
        row["farm_fos_error"] = f"{type(exc).__name__}: {exc}"
        row["farm_fos_traceback"] = _tb.format_exc(limit=3)

    return row


def _replay_one_cell_safe(*args, **kwargs) -> dict[str, Any]:
    """ProcessPool entrypoint: never raises, always returns a row."""
    try:
        return replay_one_cell(*args, **kwargs)
    except Exception as exc:
        return {
            "status": "uncaught_exception",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=4),
            "cell_dir": str(args[0]) if args else "",
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


# Column order for summary_v2.csv: human-readable groups left-to-right,
# then any per-row extras (sorted) appended for forward compatibility.
# v3 adds: agent_family / llm_model / run_level / detail_status / a2a_status
#          at the front, plus pct_yield_loss near yield_preserved_ratio,
#          and converts all 0-1 metrics to 100-scale (string "97.88").
_SUMMARY_COLUMN_ORDER: list[str] = [
    # Identity / scenario
    "status",
    "cell",
    "agent_family",
    "scenario",
    "l3_pool",
    "level",
    "llm_model",
    "model_type_size",
    "run_level",
    "detail_status",
    "detailed_briefing",
    "a2a_status",
    "a2a_enabled",
    "cell_dir",
    "cell_output_rel",
    # LLM usage from saved agent logs
    "llm_calls_with_usage",
    "avg_total_tokens_per_agent_call",
    "avg_input_tokens_per_agent_call",
    "avg_output_tokens_per_agent_call",
    "avg_cached_tokens_per_agent_call",
    "total_tokens_per_scenario",
    "avg_runtime_s_per_agent_call",
    "runtime_s_per_scenario",
    # FOS summary (100-scale)
    "fos(%)",
    "outcome(%)",
    "decision(%)",
    "efficiency(%)",
    # Yield — biology / oracle / baseline / recovery
    "agent_biological_kg",
    "oracle_biological_kg",
    "donothing_biological_kg",
    "donothing_biological_kg_inline",
    "scenario_potential_kg",
    "agent_recovered_yield_kg",
    "oracle_recovered_yield_kg",
    "yield_preserved_ratio(%)",
    "yield_loss(%)",
    "recovered_yield_loss(%)",
    "recovered_yield_loss_v2(%)",
    "crop_loss_pct(%)",
    "normalized_yield_score(%)",
    "yield_ratio(%)",
    # Loss buckets & mandate
    "expects_agent_harvest",
    "growing_loss",
    "harvest_loss",
    "unharvested_mature",
    "crop_loss",
    "crop_loss_fraction(%)",
    "safety_violations",
    # Physics extrapolation (post-replay maturity)
    "extrapolation_status",
    "extrapolation_days",
    "extrapolation_reached_r8",
    # Efficiency / gates
    "agent_tool_calls",
    "oracle_tool_calls",
    "tool_inflation",
    "redundant_reads",
    "gates_matched",
    "gates_total",
    # Workflow path: v1 (exact-args) then v2 (numeric window)
    "path_correctness(%)",
    "coverage(%)",
    "ktc_score(%)",
    "ktc_adjusted(%)",
    "combined(%)",
    # FARM-FOS (ours) + BFCL baseline + v1 CORE/KTC (branch-independent)
    "farm_fos(%)",
    "farm_fos_n_decisions",
    "farm_fos_n_matched",
    "farm_fos_v2_total(%)",
    "farm_fos_v2_path(%)",
    "farm_fos_v2_param(%)",
    "farm_fos_v2_terminal(%)",
    "farm_fos_v2_missing_plant_ridges",
    "farm_fos_v2_density_error_pct",
    "farm_fos_v2_depth_error_cm",
    "farm_fos_v2_missing_management_actions",
    "farm_fos_v2_missing_harvest_ridges",
    "farm_fos_v2_postharvest_incomplete",
    "farm_fos_v2_postharvest_warning",
    "farm_fos_v2_early_or_late_action_days",
    "farm_fos_v2_tool_error_returns",
    "farm_fos_v2_primary_issue",
    "bfcl_success(%)",
    "core_path_correctness(%)",
    "ktc(%)",
    "coverage_v1(%)",
    # Artefact paths & replay bookkeeping
    "fos_path",
    "replayed_events",
    "replay_skipped",
    "replay_exec_errors",
    "replay_exact_timing_steps",
    "replay_legacy_timing_steps",
    "replay_observation_mismatches",
    "replay_observation_mismatch_examples",
    "replay_outcome_checkpoint_verified",
    # Failure columns
    "path_correctness_v2_error",
    "run_error_source",
    "run_error_type",
    "run_error_message",
    "stderr_traceback_tail",
    "error",
    "traceback",
]


def _summary_csv_fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    union = {k for r in rows for k in r.keys()}
    ordered = [k for k in _SUMMARY_COLUMN_ORDER if k in union]
    rest = sorted(union.difference(ordered))
    return ordered + rest


def _safe_summary_stem(raw: str) -> str:
    """Return a filesystem-safe stem for generated summary CSV names."""
    import re

    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw.strip())
    stem = stem.strip("._-")
    return stem or "rebatch"


def _summary_csv_path(out_root: Path, summary_name: str | None) -> Path:
    """Choose the primary summary CSV path.

    By default, include the output directory name in the CSV filename so
    multiple rebatch outputs are not all called just ``summary_v2.csv`` when
    copied or opened side by side.  A compatibility copy is still written to
    ``summary_v2.csv`` by ``main()``.
    """
    if summary_name:
        name = summary_name if summary_name.endswith(".csv") else f"{summary_name}.csv"
        return out_root / name
    return out_root / f"summary_v2_{_safe_summary_stem(out_root.name)}.csv"


def _root_output_prefix(root: Path) -> Path:
    """Return the output subdir prefix for a root in multi-root mode."""
    return Path(_safe_summary_stem(root.name))


def _discover_cells(root: Path, recursive: bool = False) -> list[Path]:
    """Find cell directories under *root*.

    A cell directory is any directory that contains at least one
    FAIRY ``*.agent_workflow.json`` file.

    When ``recursive=False`` (default), only the immediate children of
    *root* are checked — this is the fast path for a well-structured sweep
    output like ``phase5_paper_matrix/``.

    When ``recursive=True``, the entire subtree under *root* is walked so
    you can point at a top-level ``validation_runs/`` directory and the
    script will find all cells regardless of how many nesting levels the
    sweep runner added (e.g.
    ``validation_runs/iclr_sweep_<ts>/phase5_paper_matrix/<cell>/``).
    """
    cells = []
    if recursive:
        # rglob "*.agent_workflow.json" then take parent dirs, de-dup, sort.
        seen: set[Path] = set()
        for match in sorted(root.rglob("*.agent_workflow.json")):
            parent = match.parent
            if parent not in seen:
                seen.add(parent)
                cells.append(parent)
        cells.sort()
    else:
        for p in sorted(root.iterdir()):
            if not p.is_dir():
                continue
            if any(p.glob("*.agent_workflow.json")):
                cells.append(p)
    return cells


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _normalize_excluded_dirs(excluded_dirs: list[str]) -> list[Path]:
    normalized: list[Path] = []
    for raw in excluded_dirs:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = (_REPO_ROOT / p).resolve()
        else:
            p = p.resolve()
        normalized.append(p)
    return normalized


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Re-evaluate FOS over FAIRY agent run bundles."
    )
    ap.add_argument(
        "--root",
        required=True,
        type=Path,
        action="append",
        nargs="+",
        help="Sweep dir (e.g. .../phase5_paper_matrix/<grouping>/) "
        "containing one subdir per cell with a *.agent_workflow.json bundle. "
        "Pass multiple roots to combine several sweeps into one summary.",
    )
    ap.add_argument(
        "--out-root",
        required=True,
        type=Path,
        help=(
            "Where to write per-cell fos_*.json plus the summary CSV. "
            "By default the primary CSV is named "
            "summary_v2_<out-root-name>.csv, with summary_v2.csv also "
            "written as a compatibility copy."
        ),
    )
    ap.add_argument(
        "--summary-name",
        default=None,
        help=(
            "Optional primary summary CSV filename under --out-root. "
            "If omitted, uses summary_v2_<out-root-name>.csv. "
            "The compatibility copy summary_v2.csv is still written."
        ),
    )
    ap.add_argument(
        "--extrapolate",
        action="store_true",
        help="If set, ticks physics forward to R8 before computing Outcome. "
        "Recommended for mid-season episodes (round-3) and full-season "
        "scenarios; for round-1+2 baselines this is mostly a no-op.",
    )
    ap.add_argument(
        "--extrapolation-max-days",
        type=int,
        default=180,
        help="Hard cap on post-replay tick days (default: 180).",
    )
    ap.add_argument(
        "--oracle-baselines",
        type=Path,
        default=None,
        help=(
            "Directory holding cached oracle baselines "
            "(<scenario_id>.json from scripts/build_oracle_baselines.py). "
            "When provided, FOS Outcome reports the headline metric "
            "crop_loss_pct = 1 - agent_biological / oracle_biological, "
            "and yield_preserved_ratio replaces yield_ratio as the main "
            "Outcome term. Without it we fall back to yield_ratio."
        ),
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=max(1, (os.cpu_count() or 4) // 2),
        help="Parallel cell workers (default: half of CPU count).",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N cells (debug).",
    )
    ap.add_argument(
        "--cells",
        nargs="*",
        default=None,
        help="Process only these specific cell dirnames (debug).",
    )
    ap.add_argument(
        "--recursive",
        action="store_true",
        default=False,
        help=(
            "Walk the entire subtree under --root to find cell directories "
            "(any dir containing a *.agent_workflow.json file). Use this when "
            "--root points to a top-level directory such as validation_runs/ "
            "that contains multiple sweep subdirectories. Without this flag "
            "only the immediate children of --root are checked."
        ),
    )
    ap.add_argument(
        "--donothing-inline",
        action="store_true",
        default=False,
        help=(
            "Compute the 'do-nothing' biological yield baseline inline "
            "during replay, without a pre-built oracle baseline JSON. "
            "For each cell, a second fresh scenario instance is created "
            "and physics is extrapolated to R8 with no agent events — the "
            "resulting yield is the do-nothing floor. Requires --extrapolate. "
            "Adds donothing_biological_kg and normalized_yield_score columns."
        ),
    )
    ap.add_argument(
        "--path-correctness-v2",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Compute the path-correctness pair: legacy v1 (path_correctness, "
            "coverage, ktc_raw, ktc_adjusted, combined — exact-args alphabet) "
            "AND the relaxed-numeric v2 (path_correctness_v2, coverage_v2, "
            "ktc_raw_v2, ktc_adjusted_v2, combined_v2 — numeric args within "
            "the --pc2-tol ratio window share an alphabet symbol; non-numeric "
            "args still require exact equality; same-tool oracle anchors are "
            "matched closest-first to repeated agent calls). Both sets are "
            "written together to the summary CSV and per-cell "
            "path_corr_v2_<scenario>.json. v1 is untouched, v2 is additive. "
            "Default is on. Pass --no-path-correctness-v2 to skip."
        ),
    )
    ap.add_argument(
        "--pc2-tol",
        type=float,
        default=2.0,
        help=(
            "Tolerance ratio for path_correctness_v2 numeric matching "
            "(default 2.0). max(|o|,|a|)/min(|o|,|a|) <= tol counts as a "
            "match. tol=2.0 corresponds to the user's '200%% relaxation': "
            "oracle=1 accepts agent in [0.5, 2.0]."
        ),
    )
    ap.add_argument(
        "--focus-ridges-config",
        type=Path,
        default=None,
        help=(
            "JSON file mapping scenario_id -> [ridge_ids] for per-scenario "
            "focus subsets. Example contents: "
            '{"scenario_physics_pod_fill_drought_irrigation": [10,11,12,13]}. '
            "When a cell's scenario matches a key, focus_agent_biological_kg "
            "is computed from the agent replay's per-ridge biological yield "
            "summed over those ridges. focus_oracle_biological_kg requires "
            "either an oracle baseline JSON (--oracle-baselines) or is left "
            "blank. focus_donothing_biological_kg uses the inline per-ridge "
            "do-nothing yields when --donothing-inline is on, otherwise "
            "falls back to the oracle baseline JSON. Cells whose scenario_id "
            "is not in the config are scored without a focus subset (existing "
            "behaviour). Outputs 5 new CSV columns: focus_ridge_ids, "
            "focus_agent_biological_kg, focus_oracle_biological_kg, "
            "focus_donothing_biological_kg, focus_yield_preserved_ratio, "
            "focus_normalized_yield_score."
        ),
    )
    ap.add_argument(
        "--exclude-dir",
        action="append",
        default=None,
        help=(
            "Directory to exclude from replay discovery. "
            "Can be passed multiple times. "
            "Relative paths are resolved from repo root. "
            "Defaults already exclude specific deepseek sweeps."
        ),
    )
    args = ap.parse_args()

    roots = [root.expanduser() for group in args.root for root in group]
    missing_roots = [root for root in roots if not root.is_dir()]
    if missing_roots:
        for root in missing_roots:
            print(f"ERROR: --root {root} is not a directory", file=sys.stderr)
        return 2

    multi_root = len(roots) > 1
    cell_items: list[tuple[Path, Path]] = []
    for root in roots:
        root_cells = _discover_cells(root, recursive=args.recursive)
        root_prefix = _root_output_prefix(root) if multi_root else Path()
        cell_items.extend((cell, root_prefix / cell.name) for cell in root_cells)
    excluded_raw = list(_DEFAULT_EXCLUDED_SWEEP_DIRS)
    if args.exclude_dir:
        excluded_raw.extend(args.exclude_dir)
    excluded_dirs = _normalize_excluded_dirs(excluded_raw)
    if excluded_dirs:
        cells_before_exclude = len(cell_items)
        cell_items = [
            (c, rel)
            for c, rel in cell_items
            if not any(_is_relative_to(c.resolve(), ex) for ex in excluded_dirs)
        ]
        excluded_count = cells_before_exclude - len(cell_items)
        if excluded_count > 0:
            print(
                f"Excluded {excluded_count} cell(s) from {len(excluded_dirs)} "
                "excluded dir(s)."
            )
    if args.cells:
        wanted = set(args.cells)
        cell_items = [(c, rel) for c, rel in cell_items if c.name in wanted]
    if args.limit:
        cell_items = cell_items[: args.limit]
    if not cell_items:
        print("No cells found.", file=sys.stderr)
        return 0

    args.out_root.mkdir(parents=True, exist_ok=True)
    oracle_dir = (
        args.oracle_baselines.expanduser().resolve()
        if args.oracle_baselines is not None
        else None
    )
    if oracle_dir is not None and not oracle_dir.is_dir():
        print(
            f"  [warn] --oracle-baselines={oracle_dir} is not a directory; "
            f"running without baselines (fallback to yield_ratio).",
            file=sys.stderr,
        )
        oracle_dir = None
    # Load focus ridges config (optional). Validated up-front so a typo'd
    # path or malformed JSON aborts before we start the per-cell sweep.
    focus_ridges_config: dict[str, list[int]] | None = None
    if args.focus_ridges_config is not None:
        cfg_path = args.focus_ridges_config.expanduser().resolve()
        if not cfg_path.is_file():
            print(
                f"ERROR: --focus-ridges-config {cfg_path} is not a file",
                file=sys.stderr,
            )
            return 2
        try:
            raw_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"ERROR: cannot parse --focus-ridges-config {cfg_path}: {exc}",
                file=sys.stderr,
            )
            return 2
        if not isinstance(raw_cfg, dict):
            print(
                f"ERROR: --focus-ridges-config {cfg_path} must be a JSON object "
                "mapping scenario_id -> list[int]",
                file=sys.stderr,
            )
            return 2
        focus_ridges_config = {
            str(k): [int(x) for x in (v or [])]
            for k, v in raw_cfg.items()
            if isinstance(v, list)
        }
        print(
            f"  Loaded focus-ridges config from {cfg_path}: "
            f"{len(focus_ridges_config)} scenario(s)"
        )

    print(
        f"Re-evaluating {len(cell_items)} cells from {len(roots)} root(s) "
        f"with {args.workers} worker(s) "
        f"(extrapolate={args.extrapolate}, max_days={args.extrapolation_max_days}, "
        f"oracle_baselines={oracle_dir}, "
        f"donothing_inline={args.donothing_inline}, "
        f"path_correctness_v2={args.path_correctness_v2}, "
        f"pc2_tol={args.pc2_tol}, "
        f"focus_ridges_config={'on' if focus_ridges_config else 'off'})"
    )

    rows: list[dict[str, Any]] = []
    if args.workers <= 1:
        for c, output_rel in cell_items:
            row = _replay_one_cell_safe(
                c,
                args.out_root,
                args.extrapolate,
                args.extrapolation_max_days,
                oracle_dir,
                args.donothing_inline,
                args.path_correctness_v2,
                args.pc2_tol,
                focus_ridges_config,
                output_rel,
            )
            rows.append(row)
            dn_part = (
                f"  dn_kg={row.get('donothing_biological_kg_inline', '-')}"
                f"  norm_yield={row.get('normalized_yield_score(%)', '-')}"
                if args.donothing_inline
                else ""
            )
            pc2_part = (
                f"  pc={row.get('path_correctness(%)', '-')} "
                f"comb={row.get('combined(%)', '-')} "
                if args.path_correctness_v2
                else ""
            )
            focus_part = (
                f"  focus_kg={row.get('focus_agent_biological_kg', '-')}"
                f"  focus_dn={row.get('focus_donothing_biological_kg', '-')}"
                f"  focus_nys={row.get('focus_normalized_yield_score(%)', '-')}"
                if focus_ridges_config and row.get("focus_ridge_ids")
                else ""
            )
            print(
                f"  [{row.get('status', '?'):24s}] {c.name}  "
                f"fos={row.get('fos(%)', '-')} "
                f"unharv_mature={row.get('unharvested_mature', '-')}"
                f"{dn_part}{pc2_part}{focus_part}"
            )
    else:
        # ProcessPool first (true parallelism). Fall back to ThreadPool
        # if the runtime denies semaphore allocation (e.g. sandboxed
        # environments). The replay path holds the GIL most of the
        # time during _orch_advance, so threading still helps for the
        # I/O-bound JSON parse / FOS export portions.
        try:
            executor = ProcessPoolExecutor(max_workers=args.workers)
        except (PermissionError, OSError) as exc:
            from concurrent.futures import ThreadPoolExecutor

            print(
                f"  [warn] ProcessPoolExecutor unavailable ({exc!r}); "
                f"falling back to ThreadPoolExecutor"
            )
            executor = ThreadPoolExecutor(max_workers=args.workers)
        with executor as ex:
            fut_to_cell = {
                ex.submit(
                    _replay_one_cell_safe,
                    c,
                    args.out_root,
                    args.extrapolate,
                    args.extrapolation_max_days,
                    oracle_dir,
                    args.donothing_inline,
                    args.path_correctness_v2,
                    args.pc2_tol,
                    focus_ridges_config,
                    output_rel,
                ): (c, output_rel)
                for c, output_rel in cell_items
            }
            for fut in as_completed(fut_to_cell):
                row = fut.result()
                rows.append(row)
                cell, _output_rel = fut_to_cell[fut]
                dn_part = (
                    f"  dn_kg={row.get('donothing_biological_kg_inline', '-')}"
                    f"  norm_yield={row.get('normalized_yield_score(%)', '-')}"
                    if args.donothing_inline
                    else ""
                )
                pc2_part = (
                    f"  pc={row.get('path_correctness(%)', '-')} "
                    f"comb={row.get('combined(%)', '-')} "
                    if args.path_correctness_v2
                    else ""
                )
                focus_part = (
                    f"  focus_kg={row.get('focus_agent_biological_kg', '-')}"
                    f"  focus_dn={row.get('focus_donothing_biological_kg', '-')}"
                    f"  focus_nys={row.get('focus_normalized_yield_score(%)', '-')}"
                    if focus_ridges_config and row.get("focus_ridge_ids")
                    else ""
                )
                print(
                    f"  [{row.get('status', '?'):24s}] {cell.name}  "
                    f"fos={row.get('fos(%)', '-')} "
                    f"unharv_mature={row.get('unharvested_mature', '-')}"
                    f"{dn_part}{pc2_part}{focus_part}"
                )

    # Emit the primary named summary CSV. Primary columns follow a fixed
    # semantic order; any unexpected keys fall back to sorted suffix
    # (forward-compatible). Also emit summary_v2.csv as a compatibility copy
    # for existing notebooks/scripts.
    csv_path = _summary_csv_path(args.out_root, args.summary_name)
    fieldnames = _summary_csv_fieldnames(rows)
    with csv_path.open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nWrote {csv_path} ({len(rows)} rows)")
    compat_csv_path = args.out_root / "summary_v2.csv"
    if compat_csv_path != csv_path:
        with compat_csv_path.open("w", newline="", encoding="utf-8") as h:
            w = csv.DictWriter(h, fieldnames=fieldnames)
            w.writeheader()
            for r in rows:
                w.writerow(r)
        print(f"Wrote {compat_csv_path} ({len(rows)} rows, compatibility copy)")

    # Print a quick aggregate summary.
    ok = [r for r in rows if r.get("status") == "ok"]
    if ok:

        def _f(key: str, r: dict) -> float:
            v = r.get(key, 0)
            if isinstance(v, str) and v != "":
                try:
                    return float(v)
                except (ValueError, TypeError):
                    return 0.0
            return float(v) if isinstance(v, (int, float)) else 0.0

        avg_fos = sum(_f("fos(%)", r) for r in ok) / len(ok)
        with_extrap = [r for r in ok if r.get("extrapolation_days") not in ("", None)]
        avg_extrap_days = (
            sum(_f("extrapolation_days", r) for r in with_extrap) / len(with_extrap)
            if with_extrap
            else 0.0
        )
        n_unharv = sum(int(r.get("unharvested_mature") or 0) for r in ok)
        n_growing = sum(int(r.get("growing_loss") or 0) for r in ok)
        n_harvest = sum(int(r.get("harvest_loss") or 0) for r in ok)
        print(
            f"\nAggregate: n_ok={len(ok)}  avg_fos={avg_fos:.4f}  "
            f"avg_extrap_days={avg_extrap_days:.1f}  "
            f"sum(growing/harvest/unharv_mature)={n_growing}/{n_harvest}/{n_unharv}"
        )
        detail_groups = sorted(
            {
                str(r.get("detailed_briefing") or r.get("detail_status") or "unknown")
                for r in ok
            }
        )
        for detail_status in detail_groups:
            group_rows = [
                r
                for r in ok
                if str(
                    r.get("detailed_briefing") or r.get("detail_status") or "unknown"
                )
                == detail_status
            ]
            if not group_rows:
                continue
            group_avg_fos = sum(_f("fos(%)", r) for r in group_rows) / len(
                group_rows
            )
            group_avg_outcome = sum(_f("outcome(%)", r) for r in group_rows) / len(
                group_rows
            )
            group_avg_decision = sum(_f("decision(%)", r) for r in group_rows) / len(
                group_rows
            )
            group_avg_efficiency = sum(
                _f("efficiency(%)", r) for r in group_rows
            ) / len(group_rows)
            print(
                f"Detail[{detail_status}]: n={len(group_rows)}  "
                f"avg_fos={group_avg_fos:.4f}  "
                f"avg_outcome={group_avg_outcome:.4f}  "
                f"avg_decision={group_avg_decision:.4f}  "
                f"avg_efficiency={group_avg_efficiency:.4f}"
            )
        if focus_ridges_config:
            focus_ok = [r for r in ok if r.get("focus_ridge_ids")]
            if focus_ok:
                n = len(focus_ok)

                def _focus_avg(key: str) -> float | None:
                    vs = [
                        r[key]
                        for r in focus_ok
                        if isinstance(r.get(key), (int, float)) and r.get(key) != ""
                    ]
                    return sum(vs) / len(vs) if vs else None

                avg_agent = _focus_avg("focus_agent_biological_kg")
                avg_dn = _focus_avg("focus_donothing_biological_kg")
                avg_oracle = _focus_avg("focus_oracle_biological_kg")
                avg_ypr = _focus_avg("focus_yield_preserved_ratio(%)")
                avg_nys = _focus_avg("focus_normalized_yield_score(%)")

                def fmt(v):
                    return f"{v:.2f}" if isinstance(v, (int, float)) else "-"

                def fmt4(v):
                    return f"{v:.4f}" if isinstance(v, (int, float)) else "-"

                print(
                    f"Focus:     n={n}  "
                    f"avg_focus_agent_kg={fmt(avg_agent)}  "
                    f"avg_focus_donothing_kg={fmt(avg_dn)}  "
                    f"avg_focus_oracle_kg={fmt(avg_oracle)}  "
                    f"avg_focus_ypr={fmt4(avg_ypr)}  "
                    f"avg_focus_nys={fmt4(avg_nys)}"
                )

        if args.path_correctness_v2:
            pc2_ok = [r for r in ok if "path_correctness(%)" in r]
            if pc2_ok:
                n = len(pc2_ok)

                def _avg(key: str) -> float:
                    def _to_float(v: Any) -> float:
                        if isinstance(v, (int, float)):
                            return float(v)
                        if isinstance(v, str) and v.strip():
                            try:
                                return float(v.strip())
                            except ValueError:
                                return 0.0
                        return 0.0

                    return sum(_to_float(r.get(key, 0.0)) for r in pc2_ok) / n

                avg_pc1 = _avg("path_correctness(%)")
                avg_cov1 = _avg("coverage(%)")
                avg_comb1 = _avg("combined(%)")
                avg_pc2 = _avg("path_correctness_v2")
                avg_cov2 = _avg("coverage_v2")
                avg_comb2 = _avg("combined_v2")
                avg_reused = _avg("pc2_n_agent_reused")
                avg_fresh = _avg("pc2_n_agent_fresh")
                print(
                    f"V1 (exact-args):  n={n}  "
                    f"avg_path_correctness={avg_pc1:.4f}  "
                    f"avg_coverage={avg_cov1:.4f}  "
                    f"avg_combined={avg_comb1:.4f}"
                )
                print(
                    f"V2 (tol={args.pc2_tol}):    n={n}  "
                    f"avg_path_correctness_v2={avg_pc2:.4f}  "
                    f"avg_coverage_v2={avg_cov2:.4f}  "
                    f"avg_combined_v2={avg_comb2:.4f}  "
                    f"(lift vs v1: pc {avg_pc2 - avg_pc1:+.4f}, "
                    f"comb {avg_comb2 - avg_comb1:+.4f})  "
                    f"avg_agent_reused={avg_reused:.2f}  "
                    f"avg_agent_fresh={avg_fresh:.2f}"
                )

    return 0


if __name__ == "__main__":
    sys.exit(main())
