"""Unfinished-work check before an agent's "done" is accepted (Part 2, Steps 3, 17, 19).

Simple rules on visible facts (farm snapshot facts and the task text), not
FAIRY's evaluator. Used by the Jev agent and its LLM helper, and optionally by
the LLM baseline (``--done-check``), so all agents get the same rule and limit.
"""

from __future__ import annotations

import re
from typing import Any

from fairy.agents.jev.snapshot import build_snapshot, ridge_ranges

REPORT_TOOL = "AgentUserInterface__send_message_to_user"
MAX_DONE_REFUSALS = 2


def done_problems(task: str, facts: dict[str, Any], tools_map: dict[str, Any] | None) -> list[str]:
    text = task.lower()
    ridges = facts.get("ridges", [])
    problems = [
        f"{p['from_action']} on ridges {p['ridges']} is not ready until {p['ready_at']}; "
        "wait, then check the result."
        for p in facts.get("pending", [])
        if p.get("ridges")
    ]
    if re.search(r"\bharvest", text):
        left = [r["ridge_id"] for r in ridges if r["planted"] and not r["harvested"]]
        if left:
            problems.append(f"ridges {ridge_ranges(left)} are planted but not harvested yet.")
    if re.search(r"\bplant ridges\b|\bplant\b", text):
        left = [r["ridge_id"] for r in ridges if not r["planted"] and not r["harvested"]]
        if left:
            problems.append(f"ridges {ridge_ranges(left)} are not planted yet.")
    for name, status in facts.get("machines", {}).items():
        if (status.get("grain_bin_kg") or 0) > 0:
            problems.append(f"the {name} grain bin still holds {status['grain_bin_kg']} kg; unload it.")
    unstored = (facts.get("inventory") or {}).get("harvest_grain_kg") or 0
    if unstored > 0 and re.search(r"\bstor", text):
        problems.append(f"{unstored} kg of harvested grain is not stored yet.")
    if re.search(r"\breport\b", text) and tools_map and REPORT_TOOL in tools_map:
        sent = any(s.tool_name == REPORT_TOOL and s.op_type == "TOOL" for s in facts.get("steps", []))
        if not sent:
            problems.append("the final report has not been sent to the user.")
    return problems


def refusal_note(problems: list[str]) -> list[str]:
    return [f'"done" was not accepted: {p}' for p in problems]


def current_problems(task: str, toolsets: list[Any], workflow: Any, now: float, tools_map: dict[str, Any] | None) -> list[str]:
    """The same check from scratch (reads stored farm values only; does not change the simulation)."""
    _, facts = build_snapshot(toolsets, workflow, now)
    return done_problems(task, facts, tools_map)
