"""Compose the initial L3 briefing from independently selected local G/P records."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from fairy.scenarios.farm_world_fullseason_v2 import harbin_l3_context_briefings as legacy

_KNOWLEDGE_ROOT = Path(__file__).parent / "structured_knowledge"
GUIDELINES = "reusable_operational_guidelines"
PLAN = "scenario_specific_plan"
_COMPONENTS = (GUIDELINES, PLAN)
_MAP_MODES = {
    "l2_pathsim_differ",
    "l2_pathsim_grouped_differ",
    "l3_pathsim_differ",
    "l3_textsim_differ",
}
_CARD_MODES = {"l2_human_differ", "l2_textsim_differ", "l2_textsim_grouped_differ"}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class BriefingText(str):
    """Keep strategy input and audit data alongside an ordinary user string.

    Event capture preserves this object; model serialization still sees a string.
    Only structured_true uses this carrier, so legacy task handling is unchanged.
    """

    strategy_task: str
    metadata: dict[str, Any]

    def __new__(
        cls, text: str, *, strategy_task: str, metadata: dict[str, Any]
    ) -> BriefingText:
        value = super().__new__(cls, text)
        value.strategy_task = strategy_task
        value.metadata = {
            **metadata,
            "briefing_text": text,
            "briefing_sha256": _sha256(text),
        }
        return value


def _read_json(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload, hashlib.sha256(raw).hexdigest()


def supports_structured_scenario(scenario_id: str) -> bool:
    manifest, _ = _read_json(_KNOWLEDGE_ROOT / "manifest.json")
    return scenario_id in manifest["scenario_ids"]


def validate_structured_config(config: Any) -> dict[str, Any]:
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ValueError("structured_briefing must be an object")
    unknown = set(config) - {"components", "guidelines"}
    if unknown:
        raise ValueError(f"Unknown structured_briefing fields: {sorted(unknown)}")
    components = config.get("components", [])
    if not isinstance(components, list) or any(
        not isinstance(item, str) or item not in _COMPONENTS for item in components
    ):
        raise ValueError(f"components must be a list containing only {list(_COMPONENTS)}")
    normalized: dict[str, Any] = {
        "components": [item for item in _COMPONENTS if item in components]
    }
    if GUIDELINES not in components:
        return normalized
    options = config.get("guidelines", {})
    if not isinstance(options, dict):
        raise ValueError("guidelines must be an object")
    source = options.get("source", "cross_scenario_detailed")
    if source == "cross_scenario_detailed":
        allowed = {"source"}
        options = {**options, "source": source}
    elif source == "library":
        mode = legacy.normalize_briefing_mode(options.get("mode"))
        if mode not in _CARD_MODES | _MAP_MODES:
            raise ValueError("G requires a cross-scenario library mode ending in 'differ'")
        allowed = {"source", "mode"}
        if mode == "l2_textsim_differ":
            allowed.add("top_k")
            top_k = options.get("top_k")
            if top_k is not None and (type(top_k) is not int or top_k < 1):
                raise ValueError("guidelines.top_k must be a positive integer")
        if mode in _MAP_MODES:
            allowed.add("context_path")
            if "context_path" in options and (
                not isinstance(options["context_path"], str) or not options["context_path"].strip()
            ):
                raise ValueError("guidelines.context_path must be a nonempty path string")
        options = {**options, "mode": mode}
    else:
        raise ValueError(f"Unknown guidelines.source: {source!r}")
    unknown = set(options) - allowed
    if unknown:
        raise ValueError(f"Unsupported guidelines fields for this source/mode: {sorted(unknown)}")
    normalized["guidelines"] = options
    return normalized


def _read_resource(name: str) -> tuple[dict[str, Any], dict[str, str]]:
    manifest, _ = _read_json(_KNOWLEDGE_ROOT / "manifest.json")
    payload, digest = _read_json(_KNOWLEDGE_ROOT / name)
    if digest != manifest["files"][name]:
        raise ValueError(f"Structured knowledge hash mismatch: {name}; rebuild local records")
    return payload, {"file": name, "sha256": digest}


def _check_external_sources(scenario_id: str, sources: list[dict[str, Any]]) -> None:
    if not sources or any(
        not isinstance(source, dict)
        or not isinstance(source.get("scenario_id"), str)
        or not source["scenario_id"].strip()
        or source["scenario_id"].strip() == scenario_id
        for source in sources
    ):
        raise ValueError(f"Guidelines for {scenario_id!r} require explicit non-target sources")


def _load_local_guidelines(scenario_id: str) -> tuple[str, dict[str, Any]]:
    mapping, mapping_version = _read_resource("scenario_guidelines.json")
    library, library_version = _read_resource("guides.json")
    selected = mapping["scenarios"][scenario_id]["selected_guides"]
    if not selected:
        raise ValueError(f"No reusable guidelines for {scenario_id!r}")
    parts = [
        "以下方法归纳自其他场景；按适用条件使用，具体日期、垄号、剂量和资源限制以当前任务为准。"
    ]
    for item in selected:
        guide = library["guides"][item["guide_id"]]
        sources = item["source_evidence"]
        _check_external_sources(scenario_id, sources)
        if len({source["scenario_id"] for source in sources}) < 2:
            raise ValueError(f"Guide {item['guide_id']!r} requires two distinct external sources")
        if any(source not in guide["source_evidence"] for source in sources):
            raise ValueError(f"Unverified evidence for guide {item['guide_id']!r}")
        parts.extend([
            f"### {guide['title']}",
            f"适用条件：{guide['applicable_when']}",
            "\n".join(f"- {rule}" for rule in guide["guidance"]),
        ])
    return "\n\n".join(parts), {
        "source": "cross_scenario_detailed",
        "selection_method": "explicit_theme_rules",
        "resources": [mapping_version, library_version],
        "selected_guides": selected,
    }


def _load_plan(scenario_id: str) -> tuple[str, dict[str, Any]]:
    payload, version = _read_resource("plans.json")
    plan = payload["plans"][scenario_id]
    requirements = plan["scenario_requirements"]
    if not plan["steps"]:
        raise ValueError(f"No scenario-specific plan steps for {scenario_id!r}")
    lines = ["任务条件与限制：", *[f"- {item}" for item in requirements], "", "执行步骤："]
    for step in plan["steps"]:
        instruction = step["instruction"]
        details = []
        for label, key in (("时间/阶段", "timing"), ("范围/数量", "quantities")):
            remaining = [value for value in step[key] if value not in instruction]
            if remaining:
                details.append(f"{label}：{'；'.join(remaining)}")
        suffix = "（" + "；".join(details) + "）" if details else ""
        lines.append(f"{step['order']}) {instruction}{suffix}")
    return "\n".join(lines), {
        "source": "target_detailed",
        "resource": version,
        "provenance": plan["source"],
        "additional_sources": plan.get("additional_sources", []),
    }


def _load_map_guidelines(scenario_id: str, options: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    path = options.get("context_path") or legacy._get_env_with_legacy(
        legacy.RETRIEVED_CONTEXT_ENV_VAR, legacy.LEGACY_RETRIEVED_CONTEXT_ENV_VAR
    )
    if not path:
        raise ValueError(
            "Library map requires guidelines.context_path or FARM_FAIRY_RETRIEVED_CONTEXT_PATH"
        )
    fp = Path(path).expanduser().resolve()
    payload, digest = _read_json(fp)
    if payload.get("mode") != options["mode"]:
        raise ValueError("Library map mode must match guidelines.mode")
    text = (payload.get("contexts") or {}).get(scenario_id)
    if not isinstance(text, str) or not text.strip():
        raise KeyError(f"Library map has no context for {scenario_id!r}: {fp}")
    sources = (payload.get("sources") or {}).get(scenario_id)
    if not isinstance(sources, list):
        raise ValueError("structured_true library maps require sources[target_id] metadata")
    _check_external_sources(scenario_id, sources)
    for source in sources:
        score = source.get("score")
        if type(score) not in (int, float) or not math.isfinite(score):
            raise ValueError("Library map sources must record their finite retrieval score")
    return text.strip(), {
        "source": "library",
        "mode": options["mode"],
        "selection_method": options["mode"],
        "resource": {"file": str(fp), "sha256": digest},
        "sources": sources,
    }


def _load_library_guidelines(spec: Any, options: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    scenario_id = str(spec.scenario_id)
    mode = options["mode"]
    if mode in _MAP_MODES:
        return _load_map_guidelines(scenario_id, options)
    metadata: dict[str, Any] = {"source": "library", "mode": mode, "selection_method": mode}
    if mode == "l2_human_differ":
        cards = legacy._select_manual_differ_cards(scenario_id)
        selected = [(None, card) for card in cards]
    elif mode == "l2_textsim_differ":
        top_k = options.get("top_k")
        if top_k is None:
            top_k = int(legacy._get_env_with_legacy(
                legacy.TEXTSIM_TOP_K_ENV_VAR, legacy.LEGACY_TEXTSIM_TOP_K_ENV_VAR, "6"
            ) or "6")
        if top_k < 1:
            raise ValueError("Text similarity top_k must be positive")
        selected = legacy._select_textsim_differ_cards(spec, top_k=top_k)
        metadata["top_k"] = top_k
    else:
        selected = [
            (score, card)
            for score, card, _ in legacy._select_textsim_grouped_differ_cards(spec)
        ]
        metadata["group_quotas"] = dict(legacy._GROUPED_RETRIEVAL_QUOTAS)
    sources = [{
        "scenario_id": card.get("source_l3_scenario_id"),
        "source_library": card["source_slug"],
        "skill_id": card["skill"]["skill_id"],
        **({"score": score} if score is not None else {}),
    } for score, card in selected]
    _check_external_sources(scenario_id, sources)
    resources = []
    for slug in sorted({card["source_slug"] for _, card in selected}):
        path = legacy._CONTEXT_ROOT / slug / "library_same_l3.json"
        resources.append({
            "file": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    metadata.update(sources=sources, resources=resources)
    scored = {
        (card["source_slug"], card["skill"]["skill_id"]): score
        for score, card in selected if score is not None
    }
    text = legacy._render_skill_context(
        f"{mode.upper()} atomic skill context",
        [card for _, card in selected],
        same_l3=False,
        scored=scored if scored else None,
    )
    return text, metadata


def _guidelines_for_model(text: str) -> str:
    """Omit provenance labels from G while retaining knowledge and code blocks."""
    lines = []
    fence = ""
    for line in text.splitlines():
        stripped = line.lstrip()
        if fence:
            if stripped.startswith(fence):
                fence = ""
            lines.append(line)
            continue
        fence_match = re.match(r"(`{3,}|~{3,})", stripped)
        if fence_match:
            fence = fence_match.group(1)
            lines.append(line)
            continue
        if re.match(r"^(?:-\s*)?(?:来源|source_l3|source_l2|source_library)\s*[:：]", stripped):
            continue
        line = re.sub(r"^(#{1,6})\s+Retrieved L3:.*$", r"\1 Reference workflow", line)
        lines.append(line)
    return "\n".join(lines)


def build_structured_briefing(spec: Any, config: Any = None) -> BriefingText:
    config = validate_structured_config(config)
    scenario_id = str(getattr(spec, "scenario_id", "") or "")
    if not supports_structured_scenario(scenario_id):
        raise ValueError(
            f"structured_true is not supported for scenario {scenario_id!r}; formal90 only"
        )
    base = str(getattr(spec, "briefing_text", "") or "")
    parts = [base]
    strategy_task = base
    metadata: dict[str, Any] = {
        "mode": "structured_true",
        "scenario_id": scenario_id,
        "components": config["components"],
        "base_sha256": _sha256(base),
    }
    if GUIDELINES in config["components"]:
        options = config["guidelines"]
        if options["source"] == "cross_scenario_detailed":
            text, provenance = _load_local_guidelines(scenario_id)
        else:
            text, provenance = _load_library_guidelines(spec, options)
        text = _guidelines_for_model(text)
        parts.append(
            f"<reusable_operational_guidelines>\n{text}\n</reusable_operational_guidelines>"
        )
        metadata["guidelines"] = {**provenance, "text_sha256": _sha256(text)}
    if PLAN in config["components"]:
        text, provenance = _load_plan(scenario_id)
        parts.append(f"<scenario_specific_plan>\n{text}\n</scenario_specific_plan>")
        strategy_task = text
        metadata["plan"] = {**provenance, "text_sha256": _sha256(text)}
    return BriefingText("\n\n".join(parts), strategy_task=strategy_task, metadata=metadata)
