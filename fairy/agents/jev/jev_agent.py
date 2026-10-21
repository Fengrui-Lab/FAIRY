"""Jev agent: TypeSafe's Jev picks each next action from a menu.

Only the decision step differs from the LLM agent. FAIRY's own Agent.run loop
still executes the tool, enforces max_tool_calls / timeout, and records the
workflow and runtime log, so run_report.json and agent_workflow.json have the
same format as for the LLM agents.

Each action takes up to three Jev requests:
  1. one Choice over the scenario's tools plus "done";
  2. if the tool takes arguments, one Choice per argument, sent together;
  3. if the tool takes a ridge range, the end ridge is asked last, in its own
     request that states the start ridge already chosen (questions in one
     request cannot see each other's answers).
The action's confidence is the lowest confidence among its questions.

Part 2 (docs/jev/PROGRESS.md): Jev sees the task, a short farm snapshot built
by code (snapshot.py) and the last few actions, not the full history. Ridge and
waiting options are narrowed per turn from the snapshot, and "done" is checked
against simple rules before it is accepted.
"""

from __future__ import annotations

import json
import re
import time
from types import SimpleNamespace
from typing import Any

from fairy.agents.agent.agent import Agent
from fairy.agents.jev.menu import (
    DONE_DESCRIPTION,
    DONE_OPTION,
    DURATION_ARG,
    PASS_WIDTH,
    REPORT_OPTION,
    ToolMenu,
    build_tool_menus,
    task_numbers,
)
from fairy.agents.jev.snapshot import build_snapshot, ridge_ranges

TOOL_QUESTION_ID = "next_action"
TOOL_INSTRUCTIONS = "Which action should the farm agent take next?"

# End-of-range argument -> its start argument. The end is asked after the start.
RANGE_END_TO_START = {"end_ridge": "start_ridge", "end": "start"}
RANGE_STARTS = frozenset(RANGE_END_TO_START.values())

# Tools whose ridge options leave out ridges the farm overview shows as done.
RIDGE_FILTERS = {
    "TractorApp__harvest": lambda r: r["planted"] and not r["harvested"],
    "TractorApp__plant_seeds": lambda r: not r["planted"] and not r["harvested"],
}

REPORT_TOOL = "AgentUserInterface__send_message_to_user"
MAX_DONE_REFUSALS = 2


def _arg_question_id(arg_name: str) -> str:
    return f"arg__{arg_name}"


def _readable_seconds(seconds: int) -> str:
    if seconds >= 86400:
        return f"{seconds / 86400:.1f} days"
    if seconds >= 3600:
        return f"{seconds / 3600:.1f} hours"
    return f"{seconds / 60:.0f} minutes"


class JevAgent(Agent):
    def __init__(
        self,
        name: str,
        llm: Any,
        system_message: str = "",
        toolsets: list[Any] | None = None,
        hidden_tool_names: set[str] | frozenset[str] | None = None,
    ) -> None:
        super().__init__(
            name=name,
            llm=llm,
            system_message=system_message,
            toolsets=toolsets,
            hidden_tool_names=hidden_tool_names,
        )
        self._toolsets = list(toolsets or [])
        self._num_ridges = next(
            (int(t.num_ridges) for t in self._toolsets if hasattr(t, "num_ridges")),
            None,
        )
        if self._num_ridges is None:
            raise ValueError("JevAgent needs a farm app with num_ridges in its toolsets")
        self.tool_menus: dict[str, ToolMenu] = {}
        self._reset_telemetry()

    def _reset_telemetry(self) -> None:
        self._action_confidences: list[float] = []
        self._action_count = 0
        self._jev_request_count = 0
        self._done_refusals = 0
        self._notes: list[str] = []
        self._facts: dict[str, Any] = {}
        self._snapshot: dict[str, Any] = {}
        self._state_chars: list[int] = []
        self.telemetry: dict[str, Any] = {
            "family_id": self.name,
            "planning_mode": "jev_menu_choice_snapshot",
        }

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self, input, **kwargs):
        self._reset_telemetry()
        self.tool_menus = build_tool_menus(
            self.tools_map, task_text=str(input), num_ridges=self._num_ridges
        )
        self.record_event(
            "jev_menu",
            status="ok",
            task_numbers=task_numbers(str(input)),
            tool_option_count=len(self.tool_menus) + 1,
            tools={
                name: {
                    "description": menu.description,
                    "args": {
                        a.name: {
                            "type": a.arg_type,
                            "description": a.description,
                            "source": a.source,
                            "option_count": len(a.options),
                            "options": list(a.options),
                        }
                        for a in menu.args
                    },
                }
                for name, menu in self.tool_menus.items()
            },
        )
        return super().run(input, **kwargs)

    def after_agent_run(self) -> None:
        confidences = self._action_confidences
        chars = self._state_chars
        self.telemetry.update(
            {
                "tool_calls": self.tool_call_count,
                "llm_calls": self._jev_request_count,
                "jev_requests": self._jev_request_count,
                "jev_decisions": self._action_count,
                "avg_action_confidence": (
                    round(sum(confidences) / len(confidences), 4) if confidences else None
                ),
                "min_action_confidence": min(confidences) if confidences else None,
                "done_refusals": self._done_refusals,
                "max_state_chars": max(chars) if chars else None,
                "avg_state_chars": round(sum(chars) / len(chars)) if chars else None,
            }
        )
        self.record_event("controller_telemetry", status="ok", telemetry=dict(self.telemetry))

    # ------------------------------------------------------------------
    # Decision step (replaces the LLM call)
    # ------------------------------------------------------------------

    def chat_completion(self, messages, tools=None):
        while True:
            state = self._state()
            pick, arguments, confidences = self._decide(state)
            if pick != DONE_OPTION:
                break
            problems = self._done_problems(state["task"])
            if not problems or self._done_refusals >= MAX_DONE_REFUSALS:
                break
            # "done" refused: the reasons go into the next state, and Jev is asked again.
            self._done_refusals += 1
            self._notes = [f'"done" was not accepted: {p}' for p in problems]
            self.record_event("jev_done_refused", status="ok", reasons=problems)

        action_confidence = min(confidences.values())
        self._action_confidences.append(action_confidence)
        self._action_count += 1
        self.record_event(
            "jev_action",
            status="ok",
            action=pick,
            arguments=arguments,
            action_confidence=action_confidence,
            question_confidences=confidences,
        )

        if pick == DONE_OPTION:
            return SimpleNamespace(role="assistant", content=DONE_OPTION, tool_calls=[])

        self._notes = []
        if arguments.get("content") == REPORT_OPTION:
            arguments["content"] = self._report_text()
        tool_call = SimpleNamespace(
            id=f"jev_call_{self._action_count}",
            type="function",
            function=SimpleNamespace(name=pick, arguments=json.dumps(arguments)),
        )
        self.messages.messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {"name": pick, "arguments": tool_call.function.arguments},
                    }
                ],
            }
        )
        return SimpleNamespace(role="assistant", content=None, tool_calls=[tool_call])

    def _decide(self, state: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, float]]:
        tool_question = {
            "type": "choice",
            "instructions": TOOL_INSTRUCTIONS,
            "criteria": {
                **{name: menu.description for name, menu in self.tool_menus.items()},
                DONE_OPTION: DONE_DESCRIPTION,
            },
        }
        tool_answer = self._ask("tool", state, {TOOL_QUESTION_ID: tool_question})[TOOL_QUESTION_ID]
        pick = tool_answer["choice"]
        confidences = {TOOL_QUESTION_ID: tool_answer["confidence"]}
        arguments: dict[str, Any] = {}
        if pick == DONE_OPTION:
            return pick, arguments, confidences

        menu = self.tool_menus[pick]
        names = {a.name for a in menu.args}
        later = [
            a for a in menu.args
            if a.name in RANGE_END_TO_START and RANGE_END_TO_START[a.name] in names
        ]
        first = [a for a in menu.args if a not in later]
        picked_keys: dict[str, str] = {}
        for kind, group in (("arguments", first), ("end_ridge", later)):
            if not group:
                continue
            options = {a.name: self._arg_options(menu, a, arguments) for a in group}
            questions = {
                _arg_question_id(a.name): {
                    "type": "choice",
                    "instructions": self._arg_instructions(menu, a, picked_keys),
                    "criteria": {key: None for key in options[a.name]},
                }
                for a in group
            }
            answers = self._ask(kind, state, questions)
            for a in group:
                answer = answers[_arg_question_id(a.name)]
                value = options[a.name][answer["choice"]]
                picked_keys[a.name] = answer["choice"]
                if a.name == DURATION_ARG:
                    arguments.update(value)
                else:
                    arguments[a.name] = value
                confidences[_arg_question_id(a.name)] = answer["confidence"]
        return pick, arguments, confidences

    # ------------------------------------------------------------------
    # Per-turn options, done check, report
    # ------------------------------------------------------------------

    def _allowed_ridges(self, tool_name: str) -> set[int] | None:
        keep = RIDGE_FILTERS.get(tool_name)
        if keep is None:
            return None
        return {r["ridge_id"] for r in self._facts.get("ridges", []) if keep(r)}

    def _arg_options(self, menu: ToolMenu, arg: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        options = dict(arg.options)
        if arg.name in (DURATION_ARG, "timeout") and menu.tool_name.startswith("SystemApp__"):
            for p in self._facts.get("pending", []):
                secs = p["seconds_left"]
                key = f"until {p['from_action']} is ready ({_readable_seconds(secs)})"
                options[key] = {"seconds": secs} if arg.name == DURATION_ARG else secs
            return options
        allowed = self._allowed_ridges(menu.tool_name)
        if arg.name in RANGE_STARTS or arg.name == "ridge_id":
            if allowed:
                narrowed = {k: v for k, v in options.items() if v in allowed}
                return narrowed or options
            return options
        start_name = RANGE_END_TO_START.get(arg.name)
        if start_name is None or start_name not in arguments:
            return options
        start = arguments[start_name]
        width = PASS_WIDTH.get(tuple(menu.tool_name.split("__", 1)))
        narrowed = {}
        for key, end in options.items():
            if end < start or (width and end > start + width - 1):
                continue
            if allowed is not None and any(r not in allowed for r in range(start, end + 1)):
                continue
            narrowed[key] = end
        return narrowed or {k: v for k, v in options.items() if v >= start} or options

    def _done_problems(self, task: str) -> list[str]:
        """Simple checks on visible facts before "done" is accepted (not the evaluator)."""
        text = task.lower()
        ridges = self._facts.get("ridges", [])
        problems = [
            f"{p['from_action']} on ridges {p['ridges']} is not ready until {p['ready_at']}; "
            "wait, then check the result."
            for p in self._facts.get("pending", [])
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
        for name, status in self._facts.get("machines", {}).items():
            if (status.get("grain_bin_kg") or 0) > 0:
                problems.append(f"the {name} grain bin still holds {status['grain_bin_kg']} kg; unload it.")
        unstored = (self._facts.get("inventory") or {}).get("harvest_grain_kg") or 0
        if unstored > 0 and re.search(r"\bstor", text):
            problems.append(f"{unstored} kg of harvested grain is not stored yet.")
        if re.search(r"\breport\b", text):
            sent = any(
                s.tool_name == REPORT_TOOL and s.op_type == "TOOL"
                for s in self._facts.get("steps", [])
            )
            if not sent:
                problems.append("the final report has not been sent to the user.")
        return problems

    def _report_text(self) -> str:
        farm = self._snapshot.get("farm_now", {})
        lines = [
            f"Farm agent report ({farm.get('time')}).",
            "Actions this run: " + json.dumps(farm.get("actions_this_run", {}), ensure_ascii=False),
            "Crop now: " + json.dumps(farm.get("crop", []), ensure_ascii=False),
            "Inventory now: " + json.dumps(farm.get("inventory", {}), ensure_ascii=False),
        ]
        return "\n".join(lines)

    @staticmethod
    def _arg_instructions(
        menu: ToolMenu, arg: Any, picked_keys: dict[str, str] | None = None
    ) -> str:
        text = (
            f"The farm agent has decided to call `{menu.tool_name}`: {menu.description} "
            f"Which value should its argument `{arg.name}` take?"
        )
        if arg.description:
            text += f" `{arg.name}`: {arg.description}"
        start = RANGE_END_TO_START.get(arg.name)
        if start and picked_keys and start in picked_keys:
            text += f" The agent has already chosen `{start}` = {picked_keys[start]}."
        return text

    def _state(self) -> dict[str, Any]:
        """Task, farm snapshot and last few actions (Jev has no memory)."""
        task = next(
            (step.content for step in self.workflow.dag.values() if step.op_type == "USER"), ""
        )
        self._snapshot, self._facts = build_snapshot(
            self._toolsets, self.workflow, self.time_manager.time()
        )
        state = {"task": task, **self._snapshot}
        if self._notes:
            state["notes"] = list(self._notes)
        self._state_chars.append(len(json.dumps(state, default=str, ensure_ascii=False)))
        return state

    def _ask(
        self, kind: str, state: dict[str, Any], questions: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        option_counts = {qid: len(q["criteria"]) for qid, q in questions.items()}
        self.record_event(
            "jev_request_start",
            status="running",
            request_kind=kind,
            model=getattr(self.llm, "model", None),
            option_counts=option_counts,
            questions=questions,
            state=state,
        )
        started = time.perf_counter()
        try:
            response = self.llm.system_one(state, questions)
        except Exception as exc:
            self.record_event(
                "jev_request_error",
                status="error",
                request_kind=kind,
                wall_time_seconds=round(time.perf_counter() - started, 6),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise
        latency = round(time.perf_counter() - started, 6)
        self._jev_request_count += 1

        answers: dict[str, dict[str, Any]] = {}
        for qid in questions:
            answer = response.choices[qid]
            answers[qid] = {
                "choice": answer.choice,
                "confidence": answer.confidence,
                "probabilities": dict(answer.probabilities),
            }
        input_tokens = int(getattr(response.usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(response.usage, "output_tokens", 0) or 0)
        tokens = {
            "prompt_tokens": input_tokens,
            "cached_tokens": 0,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        # Same metric shape as Messages.llm_response, so run_report token totals work.
        self.messages.runtime_metrics.append(
            {"role": "assistant", "time": latency, "accepted": True, "tokens": tokens}
        )
        self.record_event(
            "jev_request_end",
            status="ok",
            request_kind=kind,
            model_version=getattr(response, "model", None),
            request_id=getattr(response, "request_id", None),
            wall_time_seconds=latency,
            option_counts=option_counts,
            answers=answers,
            tokens=tokens,
        )
        return answers
