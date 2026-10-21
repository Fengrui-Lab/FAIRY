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

Optional LLM fallback: when Jev's action confidence is below a threshold, when
Jev repeats an action that changed nothing, or when "done" was refused twice,
an LLM gets the same state and FAIRY's normal tool schemas and calls one action
itself (it can write values that are not on Jev's menu).
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
PART1_TOOL_INSTRUCTIONS = "Which action should the farm agent take next?"
TOOL_INSTRUCTIONS = (
    "Which action should the farm agent take next? Take the next step of the task that is not "
    "done yet; steps_so_far lists every action already taken. Do not repeat an action whose "
    "result is already shown unless the farm has changed since."
)

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

FALLBACK_INSTRUCTIONS = (
    "Decide the next single step of a farm agent. Below are the task, a snapshot of the farm "
    "built from the farm's own tools, the last actions with their results, and notes. "
    "The snapshot is current: it already shows the crop stage of every ridge, the inventory "
    "and the machines, so do not call a tool only to read those again; read tools are for "
    "values the snapshot does not show (weather, sensors, ridge details, inspections). "
    "Call exactly one tool for the next action. If the whole task is complete, reply "
    '"done" without calling a tool.'
)


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
        fallback_llm: Any = None,
        fallback_confidence: float = 0.6,
        state_mode: str = "snapshot",
    ) -> None:
        if state_mode not in ("snapshot", "history"):
            raise ValueError(f"Unknown Jev state mode: {state_mode}")
        self.fallback_llm = fallback_llm
        self.fallback_confidence = fallback_confidence
        self.state_mode = state_mode
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
        self._jev_tokens = 0
        self._llm_tokens = {"prompt_tokens": 0, "cached_tokens": 0, "completion_tokens": 0}
        self._fallbacks: dict[str, int] = {}
        self._llm_decisions = 0
        self.telemetry: dict[str, Any] = {
            "family_id": self.name,
            "planning_mode": f"jev_menu_choice_{self.state_mode}",
            "fallback_model": getattr(self.fallback_llm, "model", None),
            "fallback_confidence": self.fallback_confidence if self.fallback_llm else None,
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
                "jev_input_tokens": self._jev_tokens,
                "llm_fallback_triggers": dict(self._fallbacks),
                "llm_decisions": self._llm_decisions,
                "llm_tokens": dict(self._llm_tokens),
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
            action_confidence = min(confidences.values())
            reason = None
            if pick == DONE_OPTION:
                problems = self._done_problems(state["task"])
                if problems and self._done_refusals < MAX_DONE_REFUSALS:
                    # "done" refused: the reasons go into the next state, and Jev is asked again.
                    self._done_refusals += 1
                    self._notes = [f'"done" was not accepted: {p}' for p in problems]
                    self.record_event("jev_done_refused", status="ok", reasons=problems)
                    continue
                if problems:
                    reason = "done_refused_twice"
            elif action_confidence < self.fallback_confidence:
                reason = "low_confidence"
            elif self._is_stuck(pick, arguments):
                reason = "repeat_without_change"
            break

        self._action_confidences.append(action_confidence)
        self._action_count += 1
        source = "jev"
        if reason and self.fallback_llm is not None:
            self._fallbacks[reason] = self._fallbacks.get(reason, 0) + 1
            decided = self._llm_decide(state, reason)
            if decided is not None:
                pick, arguments = decided
                source = "llm"
                self._llm_decisions += 1
        self.record_event(
            "jev_action",
            status="ok",
            action=pick,
            arguments=arguments,
            action_confidence=action_confidence,
            question_confidences=confidences,
            source=source,
            fallback_reason=reason,
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
            "instructions": TOOL_INSTRUCTIONS if self.state_mode == "snapshot" else PART1_TOOL_INSTRUCTIONS,
            "criteria": {
                **{
                    name: menu.description
                    for name, menu in self.tool_menus.items()
                    if not (name == REPORT_TOOL and self._last_was_report())
                },
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

    # ------------------------------------------------------------------
    # LLM fallback
    # ------------------------------------------------------------------

    def _is_stuck(self, pick: str, arguments: dict[str, Any]) -> bool:
        """The same call twice in a row already, with the same result or two failures."""
        steps = self._facts.get("steps", [])[-2:]
        if len(steps) < 2:
            return False
        key = json.dumps(arguments, sort_keys=True, default=str)
        if any(
            s.tool_name != pick or json.dumps(s.tool_args or {}, sort_keys=True, default=str) != key
            for s in steps
        ):
            return False
        failed = [s.op_type == "TOOL_ERROR" or (isinstance(s.content, dict) and "error" in s.content) for s in steps]
        return all(failed) or steps[0].content == steps[1].content

    def _llm_decide(self, state: dict[str, Any], reason: str) -> tuple[str, dict[str, Any]] | None:
        """One decision by the fallback LLM; None keeps Jev's choice (LLM error or unknown tool)."""
        system = next(
            (m["content"] for m in self.messages.messages if isinstance(m, dict) and m.get("role") == "system"),
            "",
        )
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": FALLBACK_INSTRUCTIONS
                + "\n\n"
                + json.dumps(state, ensure_ascii=False, default=str),
            },
        ]
        self.record_event(
            "llm_fallback_start",
            status="running",
            reason=reason,
            model=getattr(self.fallback_llm, "model", None),
            messages=messages,
        )
        started = time.perf_counter()
        try:
            response = self.fallback_llm.chat_completion(messages, tools=self.tool_schemas)
        except Exception as exc:
            self.record_event(
                "llm_fallback_error",
                status="error",
                reason=reason,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            return None
        latency = round(time.perf_counter() - started, 6)
        usage = getattr(response, "usage", None)
        details = getattr(usage, "prompt_tokens_details", None)
        tokens = {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "cached_tokens": int(getattr(details, "cached_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        }
        tokens["total_tokens"] = tokens["prompt_tokens"] + tokens["completion_tokens"]
        for k in self._llm_tokens:
            self._llm_tokens[k] += tokens[k]
        self.messages.runtime_metrics.append(
            {"role": "assistant", "time": latency, "accepted": True, "tokens": tokens, "source": "llm_fallback"}
        )
        message = response.choices[0].message if response.choices else None
        calls = list(getattr(message, "tool_calls", None) or [])
        if not calls:
            decided: tuple[str, dict[str, Any]] | None = (DONE_OPTION, {})
        else:
            name = calls[0].function.name
            try:
                args = json.loads(calls[0].function.arguments or "{}")
            except json.JSONDecodeError:
                args = None
            decided = (name, args) if name in self.tools_map and isinstance(args, dict) else None
        self.record_event(
            "llm_fallback_end",
            status="ok" if decided else "rejected",
            reason=reason,
            wall_time_seconds=latency,
            tokens=tokens,
            decision=list(decided) if decided else None,
            content=getattr(message, "content", None),
        )
        return decided

    def _last_was_report(self) -> bool:
        """No report straight after a report: Jev sent up to 5 in a row (Part 2, Step 6)."""
        steps = self._facts.get("steps", [])
        return bool(steps) and steps[-1].tool_name == REPORT_TOOL

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
        if re.search(r"\breport\b", text) and REPORT_TOOL in self.tools_map:
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

    def _arg_instructions(
        self, menu: ToolMenu, arg: Any, picked_keys: dict[str, str] | None = None
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
        if self.state_mode == "snapshot":
            # Without this, Jev repeated the task's first values for this action
            # (e.g. ridges 44-55 again instead of 24-35): single-question test, Part 2 Step 5.
            earlier = self._earlier_calls(menu.tool_name)
            if earlier:
                text += f" Earlier calls of this action in this run: {earlier}."
            text += " Choose the value for the next step of the task that is not done yet."
        return text

    def _earlier_calls(self, tool_name: str, limit: int = 5) -> str:
        seen: list[str] = []
        for s in self._facts.get("steps", []):
            if s.tool_name != tool_name:
                continue
            args = ", ".join(f"{k}={v}" for k, v in (s.tool_args or {}).items() if k != "content")
            call = f"({args})"
            if call in seen:
                seen.remove(call)
            seen.append(call)
        return "; ".join(seen[-limit:])

    def _state(self) -> dict[str, Any]:
        """Task, farm snapshot and last few actions (Jev has no memory)."""
        task = next(
            (step.content for step in self.workflow.dag.values() if step.op_type == "USER"), ""
        )
        self._snapshot, self._facts = build_snapshot(
            self._toolsets, self.workflow, self.time_manager.time()
        )
        if self.state_mode == "history":
            # Part 1 input (diagnostic): every action with its full result, no snapshot.
            # The snapshot is still built for the menus and the done check.
            state = {
                "task": task,
                "actions_so_far": [
                    {"action": s.tool_name, "arguments": s.tool_args or {}, "result": s.content}
                    for s in self._facts["steps"]
                ],
            }
        else:
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
        self._jev_tokens += input_tokens
        tokens = {
            "prompt_tokens": input_tokens,
            "cached_tokens": 0,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        # Same metric shape as Messages.llm_response, so run_report token totals work.
        self.messages.runtime_metrics.append(
            {"role": "assistant", "time": latency, "accepted": True, "tokens": tokens, "source": "jev"}
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
