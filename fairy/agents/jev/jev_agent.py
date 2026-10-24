"""Jev agent: TypeSafe's Jev picks each next action from a menu.

Only the decision step differs from the LLM agent. FAIRY's own Agent.run loop
still executes the tool, enforces max_tool_calls / timeout, and records the
workflow and runtime log, so run_report.json and agent_workflow.json have the
same format as for the LLM agents.

Each action takes one Jev request, sometimes two (fan-out; Jev bills the
state once per request, so questions that do not depend on each other share one):
  1. one Choice over the scenario's tools plus "done", together with the
     argument questions of the likely tools (Jev's top tools in the previous
     request and the last few actions); answers for tools not picked are ignored;
  2. only if the picked tool takes arguments and was not among the likely
     tools, one Choice per argument, sent together.
A ridge range is asked as start + "how many ridges" (independent questions);
the code turns the count into the end ridge within the allowed ridges.
The action's confidence is the lowest confidence among the picked tool's questions.

Part 2 (docs/jev/PROGRESS.md): Jev sees the task, a short farm snapshot built
by code (snapshot.py) and the last few actions, not the full history. Ridge and
waiting options are narrowed per turn from the snapshot, and "done" is checked
against simple rules before it is accepted.

Optional LLM fallback: when Jev's action confidence is below a threshold, when
Jev repeats an action that changed nothing, or when "done" was refused twice,
an LLM gets the same state and FAIRY's normal tool schemas and calls one action
itself (it can write values that are not on Jev's menu).

Reflex mode (--hybrid-mode reflex, after REFLEX, arXiv 2609.26532): Jev always
picks the tool. Only Jev's confidence on the tool counts: at or above the
threshold Jev also picks the arguments; below it the LLM gets only Jev's tool
and fills in its arguments. Repeats and "done" refused twice still go to the
LLM as in the default mode.
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
from fairy.agents.jev.done_check import MAX_DONE_REFUSALS, REPORT_TOOL, done_problems
from fairy.agents.jev.snapshot import RESULT_CHARS, _failed, _short, build_snapshot, ridge_ranges

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


FALLBACK_INSTRUCTIONS = (
    "Decide the next single step of a farm agent. Below are the task, a snapshot of the farm "
    "built from the farm's own tools, the last actions with their results, and notes. "
    "The snapshot is current: it already shows the crop stage of every ridge, the inventory "
    "and the machines, so do not call a tool only to read those again; read tools are for "
    "values the snapshot does not show (weather, sensors, ridge details, inspections). "
    "Call exactly one tool for the next action. If the whole task is complete, reply "
    '"done" without calling a tool.'
)
FALLBACK_MEMORY_INSTRUCTIONS = (
    "You are asked only for some steps; Jev, another agent, takes the others. Your earlier "
    "decisions in this run and their results are in this conversation, with the actions Jev "
    "took in between. Do not repeat a read whose result above is still current."
)
FILL_INSTRUCTIONS = (
    "Jev has already chosen the next action: `{tool}`. Call exactly that tool; you only "
    "choose its arguments."
)
HYBRID_MODES = ("full", "reflex")

# Fallback memory (Part 2, Step 11): earlier fallback requests and the LLM's calls
# stay in its input, append-only, so each request is the previous one plus new
# messages. gpt-6-luna's cache only hits on a whole earlier request; a request
# that shares just its start gets nothing cached (tested). Past MAX turns the
# oldest are cut back to KEEP, so the cache restarts once every MAX - KEEP calls.
FALLBACK_MEMORY_MAX_TURNS = 20
FALLBACK_MEMORY_KEEP_TURNS = 10
FALLBACK_SINCE_LINES = 30
FALLBACK_SINCE_RESULT_CHARS = 300


# Fan-out: argument questions of these tools ride along with the tool question.
# Jev's next tool was in this set 91% of the time in the Step 11-12 L3 logs.
LIKELY_TOP_TOOLS = 5
LIKELY_MIN_PROBABILITY = 0.05
LIKELY_RECENT_ACTIONS = 3


def _arg_question_id(arg_name: str, tool_name: str | None = None) -> str:
    return f"arg__{tool_name}__{arg_name}" if tool_name else f"arg__{arg_name}"


def _count_key(n: int) -> str:
    return f"{n} ridge" if n == 1 else f"{n} ridges"


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
        hybrid_mode: str = "full",
    ) -> None:
        if state_mode not in ("snapshot", "history"):
            raise ValueError(f"Unknown Jev state mode: {state_mode}")
        if hybrid_mode not in HYBRID_MODES:
            raise ValueError(f"Unknown hybrid mode: {hybrid_mode}")
        self.fallback_llm = fallback_llm
        self.fallback_confidence = fallback_confidence
        self.state_mode = state_mode
        self.hybrid_mode = hybrid_mode
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
        self._llm_done_refusals = 0
        self._notes: list[str] = []
        self._facts: dict[str, Any] = {}
        self._snapshot: dict[str, Any] = {}
        self._state_chars: list[int] = []
        self._jev_tokens = 0
        self._llm_tokens = {"prompt_tokens": 0, "cached_tokens": 0, "completion_tokens": 0}
        self._fallbacks: dict[str, int] = {}
        self._llm_decisions = 0
        self._llm_argument_fills = 0
        self._llm_turns: list[dict[str, Any]] = []
        self._llm_seen_steps = 0
        self._last_tool_probabilities: dict[str, float] = {}
        self._fanout = {"hits": 0, "misses": 0}
        self.telemetry: dict[str, Any] = {
            "family_id": self.name,
            "planning_mode": f"jev_menu_choice_{self.state_mode}",
            "fallback_model": getattr(self.fallback_llm, "model", None),
            "fallback_confidence": self.fallback_confidence if self.fallback_llm else None,
            "hybrid_mode": self.hybrid_mode,
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
                "jev_requests_per_action": (
                    round(self._jev_request_count / self._action_count, 3) if self._action_count else None
                ),
                "fanout_hits": self._fanout["hits"],
                "fanout_misses": self._fanout["misses"],
                "avg_action_confidence": (
                    round(sum(confidences) / len(confidences), 4) if confidences else None
                ),
                "min_action_confidence": min(confidences) if confidences else None,
                "done_refusals": self._done_refusals,
                "llm_done_refusals": self._llm_done_refusals,
                "jev_input_tokens": self._jev_tokens,
                "llm_fallback_triggers": dict(self._fallbacks),
                "llm_decisions": self._llm_decisions,
                "llm_argument_fills": self._llm_argument_fills,
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
        reflex = self.hybrid_mode == "reflex" and self.fallback_llm is not None
        while True:
            while True:
                state = self._state()
                # Reflex: Jev is not asked for arguments the LLM will fill in.
                pick, arguments, confidences = self._decide(
                    state, skip_args_below=self.fallback_confidence if reflex else None
                )
                action_confidence = min(confidences.values())
                tool_confidence = confidences[TOOL_QUESTION_ID]
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
                elif reflex and tool_confidence < self.fallback_confidence:
                    reason = "low_tool_confidence"
                elif not reflex and action_confidence < self.fallback_confidence:
                    reason = "low_confidence"
                elif self._is_stuck(pick, arguments):
                    reason = "repeat_without_change"
                break

            source = "jev"
            if reason == "low_tool_confidence":
                # Reflex: Jev's tool stays; the LLM only fills in its arguments.
                if self.tool_menus[pick].args:
                    self._fallbacks[reason] = self._fallbacks.get(reason, 0) + 1
                    decided = self._llm_decide(state, reason, fill_tool=pick)
                    if decided is not None:
                        arguments = decided[1]
                        source = "llm_arguments"
                        self._llm_argument_fills += 1
                    elif arguments is None:
                        # LLM error or another tool: Jev picks the arguments after all.
                        arguments, arg_confidences = self._jev_arguments(state, pick)
                        confidences.update(arg_confidences)
                        action_confidence = min(confidences.values())
            elif reason and self.fallback_llm is not None:
                self._fallbacks[reason] = self._fallbacks.get(reason, 0) + 1
                decided = self._llm_decide(state, reason)
                if decided is not None and decided[0] == DONE_OPTION:
                    # The LLM's "done" gets the same check as Jev's, with its own limit
                    # (it ended a wetjune run on 23 June with the crop still growing; Step 17).
                    problems = self._done_problems(state["task"])
                    if problems and self._llm_done_refusals < MAX_DONE_REFUSALS:
                        self._llm_done_refusals += 1
                        self._notes = [f'"done" was not accepted: {p}' for p in problems]
                        self.record_event("llm_done_refused", status="ok", reasons=problems)
                        continue
                if decided is not None:
                    pick, arguments = decided
                    source = "llm"
                    self._llm_decisions += 1
            break

        self._action_confidences.append(action_confidence)
        self._action_count += 1
        self.record_event(
            "jev_action",
            status="ok",
            action=pick,
            arguments=arguments,
            action_confidence=action_confidence,
            tool_confidence=tool_confidence,
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

    def _decide(
        self, state: dict[str, Any], skip_args_below: float | None = None
    ) -> tuple[str, dict[str, Any] | None, dict[str, float]]:
        """Jev's tool and arguments; arguments are None when skip_args_below skipped them."""
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
        questions: dict[str, dict[str, Any]] = {TOOL_QUESTION_ID: tool_question}
        prepared: dict[str, dict[str, tuple[str, dict[str, Any]]]] = {}
        for name in self._likely_tools(tool_question["criteria"]):
            arg_questions, prepared[name] = self._value_questions(self.tool_menus[name], name)
            questions.update(arg_questions)
        answers = self._ask("tool", state, questions)
        tool_answer = answers[TOOL_QUESTION_ID]
        self._last_tool_probabilities = tool_answer["probabilities"]
        pick = tool_answer["choice"]
        confidences = {TOOL_QUESTION_ID: tool_answer["confidence"]}
        if pick == DONE_OPTION or not self.tool_menus[pick].args:
            return pick, {}, confidences
        if pick not in prepared and skip_args_below is not None and confidences[TOOL_QUESTION_ID] < skip_args_below:
            return pick, None, confidences
        arguments, arg_confidences = self._jev_arguments(state, pick, prepared.get(pick), answers)
        confidences.update(arg_confidences)
        return pick, arguments, confidences

    def _jev_arguments(
        self,
        state: dict[str, Any],
        pick: str,
        options: dict[str, tuple[str, dict[str, Any]]] | None = None,
        answers: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], dict[str, float]]:
        """Jev's arguments for pick: from the fan-out answers, or one more request."""
        menu = self.tool_menus[pick]
        if options is not None:
            self._fanout["hits"] += 1
        else:
            self._fanout["misses"] += 1
            arg_questions, options = self._value_questions(menu)
            answers = self._ask("arguments", state, arg_questions)
        return self._read_values(menu, options, answers)

    def _likely_tools(self, offered: dict[str, Any]) -> list[str]:
        """Tools with arguments that Jev ranked high last time or used in the last few actions."""
        ranked = sorted(self._last_tool_probabilities.items(), key=lambda kv: -kv[1])
        likely = [n for n, p in ranked[:LIKELY_TOP_TOOLS] if p >= LIKELY_MIN_PROBABILITY]
        recent = [s.tool_name for s in self._facts.get("steps", [])[-LIKELY_RECENT_ACTIONS:]]
        out: list[str] = []
        for name in likely + recent[::-1]:
            if name in offered and name in self.tool_menus and self.tool_menus[name].args and name not in out:
                out.append(name)
        return out

    def _value_questions(
        self, menu: ToolMenu, tool_key: str | None = None
    ) -> tuple[dict[str, dict[str, Any]], dict[str, tuple[str, dict[str, Any]]]]:
        """One question per argument, none depending on another's answer.

        A range end is asked as "how many ridges" from the start; _read_values turns
        it into the end ridge. Returns the questions and, per argument, its
        question id and options.
        """
        names = {a.name for a in menu.args}
        questions: dict[str, dict[str, Any]] = {}
        options: dict[str, tuple[str, dict[str, Any]]] = {}
        for a in menu.args:
            qid = _arg_question_id(a.name, tool_key)
            count_from = RANGE_END_TO_START.get(a.name) if RANGE_END_TO_START.get(a.name) in names else None
            if count_from:
                width = PASS_WIDTH.get(tuple(menu.tool_name.split("__", 1))) or self._num_ridges
                opts: dict[str, Any] = {_count_key(n): n for n in range(1, width + 1)}
            else:
                opts = self._arg_options(menu, a, {})
            questions[qid] = {
                "type": "choice",
                "instructions": self._arg_instructions(
                    menu, a, speculative=tool_key is not None, count_from=count_from
                ),
                "criteria": {key: None for key in opts},
            }
            options[a.name] = (qid, opts)
        return questions, options

    def _read_values(
        self,
        menu: ToolMenu,
        options: dict[str, tuple[str, dict[str, Any]]],
        answers: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, float]]:
        names = {a.name for a in menu.args}
        ends = [a for a in menu.args if RANGE_END_TO_START.get(a.name) in names]
        arguments: dict[str, Any] = {}
        confidences: dict[str, float] = {}
        for a in [a for a in menu.args if a not in ends] + ends:
            qid, opts = options[a.name]
            answer = answers[qid]
            value = opts[answer["choice"]]
            confidences[qid] = answer["confidence"]
            if a in ends:
                # Count -> end ridge, unchanged even if it does not fit: the farm
                # refuses it, as for the LLM agent (Part 2, Step 15).
                arguments[a.name] = arguments[RANGE_END_TO_START[a.name]] + value - 1
            elif a.name == DURATION_ARG:
                arguments.update(value)
            else:
                arguments[a.name] = value
        return arguments, confidences

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

    def _llm_decide(
        self, state: dict[str, Any], reason: str, fill_tool: str | None = None
    ) -> tuple[str, dict[str, Any]] | None:
        """One decision by the fallback LLM; None keeps Jev's choice (LLM error or unknown tool).

        With fill_tool the LLM sees only that tool's schema and picks its arguments;
        any other answer (no call, another tool) is None.
        """
        messages = self._fallback_messages(state, reason, fill_tool)
        tools = (
            [t for t in self.tool_schemas if t["function"]["name"] == fill_tool]
            if fill_tool else self.tool_schemas
        )
        self.record_event(
            "llm_fallback_start",
            status="running",
            reason=reason,
            fill_tool=fill_tool,
            model=getattr(self.fallback_llm, "model", None),
            messages=messages,
        )
        started = time.perf_counter()
        try:
            response = self.fallback_llm.chat_completion(messages, tools=tools)
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
            decided: tuple[str, dict[str, Any]] | None = None if fill_tool else (DONE_OPTION, {})
        else:
            name = calls[0].function.name
            try:
                args = json.loads(calls[0].function.arguments or "{}")
            except json.JSONDecodeError:
                args = None
            decided = (name, args) if name in self.tools_map and isinstance(args, dict) else None
        if fill_tool and decided is not None and decided[0] != fill_tool:
            decided = None
        if decided is not None and self.state_mode == "snapshot":
            self._remember_llm_turn(messages[-1]["content"], decided)
        self.record_event(
            "llm_fallback_end",
            status="ok" if decided else "rejected",
            reason=reason,
            fill_tool=fill_tool,
            wall_time_seconds=latency,
            tokens=tokens,
            decision=list(decided) if decided else None,
            content=getattr(message, "content", None),
        )
        return decided

    def _fallback_messages(
        self, state: dict[str, Any], reason: str, fill_tool: str | None = None
    ) -> list[dict[str, Any]]:
        """Fixed rules and task, then the LLM's earlier turns, then the current state."""
        fill = "\n" + FILL_INSTRUCTIONS.format(tool=fill_tool) if fill_tool else ""
        system = next(
            (m["content"] for m in self.messages.messages if isinstance(m, dict) and m.get("role") == "system"),
            "",
        )
        if self.state_mode != "snapshot":
            # Part 1 input: no memory (the full history is already in the state).
            return [
                {"role": "system", "content": system},
                {"role": "user", "content": FALLBACK_INSTRUCTIONS + fill + "\n\n" + json.dumps(state, ensure_ascii=False, default=str)},
            ]
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": FALLBACK_INSTRUCTIONS + " " + FALLBACK_MEMORY_INSTRUCTIONS + "\n\nTask:\n" + state["task"],
            },
        ]
        steps = self._facts.get("steps", [])
        for turn in self._llm_turns:
            messages.append({"role": "user", "content": turn["asked"]})
            if turn["call"] is None:
                messages.append({"role": "assistant", "content": DONE_OPTION})
                continue
            name, args = turn["call"]
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": turn["id"],
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
                }],
            })
            step = steps[turn["step"]] if turn["step"] < len(steps) else None
            result = (
                f"[{step.time}] " + ("failed: " if _failed(step) else "") + _short(step.content)
                if step is not None and step.tool_name == name
                else "(no result recorded)"
            )
            messages.append({"role": "tool", "tool_call_id": turn["id"], "content": result})
        # recent_actions left out: the LLM's own results and the actions since cover them.
        current = {k: v for k, v in state.items() if k not in ("task", "recent_actions")}
        messages.append({
            "role": "user",
            "content": self._since_last_llm_turn(steps)
            + f"\nYou are asked now because: {reason.replace('_', ' ')}."
            + fill
            + "\n\nCurrent state:\n"
            + json.dumps(current, ensure_ascii=False, default=str),
        })
        return messages

    def _since_last_llm_turn(self, steps: list[Any]) -> str:
        """Jev's actions since the LLM's last call, with time and a short result."""
        since = steps[self._llm_seen_steps:]
        if not since:
            return "No actions since your last decision."
        lines = [
            f"[{st.time}] {st.tool_name}({', '.join(f'{k}={v}' for k, v in (st.tool_args or {}).items() if k != 'content')})"
            f" -> {'failed: ' if _failed(st) else ''}{_short(st.content, FALLBACK_SINCE_RESULT_CHARS)}"
            for st in since[-FALLBACK_SINCE_LINES:]
        ]
        head = "Actions since your last decision" if self._llm_turns else "Actions so far"
        if len(since) > len(lines):
            head += f" ({len(since) - len(lines)} earlier ones not shown)"
        return head + ":\n" + "\n".join(lines)

    def _remember_llm_turn(self, current_message: str, decided: tuple[str, dict[str, Any]]) -> None:
        """Keep the request's last message as sent, so the next request starts with this one."""
        steps = self._facts.get("steps", [])
        name, args = decided
        self._llm_turns.append({
            "asked": current_message,
            "call": None if name == DONE_OPTION else (name, args),
            "id": f"fallback_call_{self._action_count}",
            "step": len(steps),
        })
        self._llm_seen_steps = len(steps) + (0 if name == DONE_OPTION else 1)
        if len(self._llm_turns) > FALLBACK_MEMORY_MAX_TURNS:
            self._llm_turns = self._llm_turns[-FALLBACK_MEMORY_KEEP_TURNS:]

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
        return done_problems(task, self._facts, self.tools_map)

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
        self, menu: ToolMenu, arg: Any, *, speculative: bool = False, count_from: str | None = None
    ) -> str:
        lead = (
            f"If the farm agent calls `{menu.tool_name}` next: {menu.description} "
            if speculative
            else f"The farm agent has decided to call `{menu.tool_name}`: {menu.description} "
        )
        if count_from:
            text = lead + (
                f"How many ridges should the call cover, counting from the ridge chosen for "
                f"`{count_from}`?"
            )
        else:
            text = lead + f"Which value should its argument `{arg.name}` take?"
        if arg.description:
            text += f" `{arg.name}`: {arg.description}"
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
            tool_args = {k: v for k, v in (s.tool_args or {}).items() if k != "content"}
            parts = []
            for end_name, start_name in RANGE_END_TO_START.items():
                if end_name in tool_args and start_name in tool_args:
                    # Same terms as the "how many ridges" question: "ridges 12-15 (4 ridges)".
                    start, end = tool_args.pop(start_name), tool_args.pop(end_name)
                    parts.append(f"ridges {start}-{end} ({_count_key(end - start + 1)})")
            parts += [f"{k}={v}" for k, v in tool_args.items()]
            call = f"({', '.join(parts)})"
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
