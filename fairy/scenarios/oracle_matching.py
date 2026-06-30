from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fairy.scenarios.validation_result import ScenarioValidationResult


@dataclass
class OracleStepSpec:
    function_name: str | None = None
    class_name: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    penalty_if_repeated: float = 0.0


def oracle_validate(
    *,
    scenario,
    env,
    step_specs: list[OracleStepSpec],
    success_threshold: float = 1.0,
    harmless_extra_penalty: float = 0.0,
    **_: Any,
) -> ScenarioValidationResult:
    workflow_steps = list(env.workflow.dag.values())
    app_classes = {
        getattr(app, "name", app.__class__.__name__): app.__class__.__name__
        for app in getattr(env, "apps", [])
    }
    matched: list[str] = []
    missing: list[str] = []
    search_start = 0

    for spec in step_specs:
        found_index = None
        for index in range(search_start, len(workflow_steps)):
            step = workflow_steps[index]
            if _step_matches_spec(step, spec, app_classes):
                found_index = index
                break
        if found_index is None:
            missing.append(_spec_label(spec))
            continue
        matched.append(workflow_steps[found_index].tool_name or workflow_steps[found_index].name or "")
        search_start = found_index + 1

    expected_labels = {_spec_label(spec) for spec in step_specs}
    extra_steps = [
        step.tool_name or step.name or ""
        for step in workflow_steps
        if (
            step.tool_name
            and not _is_briefing_step(step.tool_name, app_classes)
            and _tool_label(step.tool_name, app_classes) not in expected_labels
        )
    ]
    match_score = len(matched) / len(step_specs) if step_specs else 1.0
    extra_penalty = harmless_extra_penalty * len(extra_steps)
    score = max(0.0, match_score - extra_penalty)

    return ScenarioValidationResult(
        success=score >= success_threshold,
        rationale=(
            f"Matched {len(matched)}/{len(step_specs)} oracle steps; "
            f"score={score:.3f}, threshold={success_threshold:.3f}."
        ),
        metadata={
            "score": score,
            "success_threshold": success_threshold,
            "matched_steps": matched,
            "missing_steps": missing,
            "extra_steps": extra_steps,
            "workflow_steps": len(workflow_steps),
            "scenario_id": getattr(scenario, "scenario_id", ""),
        },
    )


def _step_matches_spec(step: Any, spec: OracleStepSpec, app_classes: dict[str, str]) -> bool:
    if not step.tool_name:
        return False
    if spec.tool_name and step.tool_name != spec.tool_name:
        return False
    if spec.function_name or spec.class_name:
        app_name, function_name = _split_tool_name(step.tool_name)
        class_name = app_classes.get(app_name, app_name)
        if spec.function_name and function_name != spec.function_name:
            return False
        if spec.class_name and spec.class_name not in {app_name, class_name}:
            return False
    if spec.tool_args is not None and dict(step.tool_args or {}) != spec.tool_args:
        return False
    return True


def _spec_label(spec: OracleStepSpec) -> str:
    if spec.tool_name:
        return _tool_label(spec.tool_name, {})
    return f"{spec.class_name or '*'}__{spec.function_name or '*'}"


def _tool_label(tool_name: str, app_classes: dict[str, str]) -> str:
    app_name, function_name = _split_tool_name(tool_name)
    class_name = app_classes.get(app_name, app_name)
    return f"{class_name}__{function_name}"


def _split_tool_name(tool_name: str) -> tuple[str, str]:
    app_name, _, function_name = tool_name.partition("__")
    return app_name, function_name


def _is_briefing_step(tool_name: str, app_classes: dict[str, str]) -> bool:
    app_name, function_name = _split_tool_name(tool_name)
    class_name = app_classes.get(app_name, app_name)
    return class_name == "AgentUserInterface" and function_name == "send_message_to_agent"
