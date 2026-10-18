"""Jev agent: TypeSafe's Jev picks each next action from a menu.

Only the decision step differs from the LLM agent. FAIRY's own Agent.run loop
still executes the tool, enforces max_tool_calls / timeout, and records the
workflow and runtime log, so run_report.json and agent_workflow.json have the
same format as for the LLM agents.

Each action takes up to two Jev requests:
  1. one Choice over the scenario's tools plus "done";
  2. if the tool takes arguments, one Choice per argument, sent together.
The action's confidence is the lowest confidence among its questions.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any

from fairy.agents.agent.agent import Agent
from fairy.agents.jev.menu import (
    DONE_DESCRIPTION,
    DONE_OPTION,
    ToolMenu,
    build_tool_menus,
    task_numbers,
)

TOOL_QUESTION_ID = "next_action"
TOOL_INSTRUCTIONS = "Which action should the farm agent take next?"


def _arg_question_id(arg_name: str) -> str:
    return f"arg__{arg_name}"


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
        self._num_ridges = next(
            (int(t.num_ridges) for t in (toolsets or []) if hasattr(t, "num_ridges")),
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
        self.telemetry: dict[str, Any] = {
            "family_id": self.name,
            "planning_mode": "jev_menu_choice",
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
            }
        )
        self.record_event("controller_telemetry", status="ok", telemetry=dict(self.telemetry))

    # ------------------------------------------------------------------
    # Decision step (replaces the LLM call)
    # ------------------------------------------------------------------

    def chat_completion(self, messages, tools=None):
        state = self._state()
        tool_question = {
            "type": "choice",
            "instructions": TOOL_INSTRUCTIONS,
            "criteria": {
                **{name: menu.description for name, menu in self.tool_menus.items()},
                DONE_OPTION: DONE_DESCRIPTION,
            },
        }
        tool_answers = self._ask("tool", state, {TOOL_QUESTION_ID: tool_question})
        tool_answer = tool_answers[TOOL_QUESTION_ID]
        pick = tool_answer["choice"]
        confidences = {TOOL_QUESTION_ID: tool_answer["confidence"]}
        arguments: dict[str, Any] = {}

        if pick != DONE_OPTION:
            menu = self.tool_menus[pick]
            if menu.args:
                arg_questions = {
                    _arg_question_id(a.name): {
                        "type": "choice",
                        "instructions": self._arg_instructions(menu, a),
                        "criteria": {key: None for key in a.options},
                    }
                    for a in menu.args
                }
                arg_answers = self._ask("arguments", state, arg_questions)
                for a in menu.args:
                    answer = arg_answers[_arg_question_id(a.name)]
                    arguments[a.name] = a.options[answer["choice"]]
                    confidences[_arg_question_id(a.name)] = answer["confidence"]

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

    @staticmethod
    def _arg_instructions(menu: ToolMenu, arg: Any) -> str:
        text = (
            f"The farm agent has decided to call `{menu.tool_name}`: {menu.description} "
            f"Which value should its argument `{arg.name}` take?"
        )
        if arg.description:
            text += f" `{arg.name}`: {arg.description}"
        return text

    def _state(self) -> dict[str, Any]:
        """Task text plus every action so far with its result (Jev has no memory)."""
        task = ""
        actions: list[dict[str, Any]] = []
        for step in self.workflow.dag.values():
            if step.op_type == "USER":
                task = step.content
            elif step.op_type in ("TOOL", "TOOL_ERROR"):
                actions.append(
                    {
                        "action": step.tool_name,
                        "arguments": step.tool_args or {},
                        "result": step.content,
                    }
                )
        return {"task": task, "actions_so_far": actions}

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
