"""A2A with a global LLM and local Jev experts (--a2a true --a2a-provider typesafe).

The main agent is a normal LLM controller. Every field app is hidden behind
`<App>__expert_agent(task)`; the LLM writes a job in plain text and that app's
Jev expert carries it out. Clock and user message stay with the LLM.

Jev cannot write, so one expert job works like this:
  - the expert sees the job, a code-built farm snapshot and its actions in this job;
  - it picks actions and arguments from menus over this app's tools only, the
    same menus as farm_jev; numbers in the job text become menu options;
  - it ends the job with "done", or hands it back to the LLM when unsure (confidence
    under the threshold) or stuck (same action, no change);
  - the reply to the LLM is written by code: status, each action with its result,
    and, when unsure, Jev's top options with their probabilities.
There is no LLM inside an expert: the LLM decides what to do with a handed-back job.

Hybrid experts (--a2a-expert-hybrid true, off by default): each expert runs the new
hybrid (lean memory, plan note, budget note, reasoning "medium"; docs/jev/better_hybrid.md).
When Jev is unsure or stuck, a local LLM takes that decision inside the expert and writes
its next steps, which Jev follows until the next hand-off in the same job. The job does not
go back to the manager. The local LLM's memory and plan last one job; the budget counts
the run's actions, not the job's.
"""

from __future__ import annotations

import json
import re
from typing import Any

from fairy.agents.jev.jev_agent import DONE_OPTION, RANGE_END_TO_START, RANGE_STARTS, JevAgent
from fairy.agents.jev.menu import PASS_WIDTH, arg_descriptions, first_paragraph
from fairy.agents.jev.snapshot import _failed, _short, _tool_steps, step_history

REPORT_RESULT_CHARS = 8000
TOP_OPTIONS = 3
_RIDGE_RANGE_RES = (
    re.compile(r"ridges?\s*(\d+)\s*(?:-|\u2013|to|through)\s*(\d+)", re.IGNORECASE),
    re.compile(r"start(?:_ridge)?\s*[=:]\s*(\d+)\D+end(?:_ridge)?\s*[=:]\s*(\d+)", re.IGNORECASE),
)
EXPERT_TOOL_INSTRUCTIONS = (
    "You are the expert for one farm app. `task` is the job the farm manager gave you, and "
    "steps_in_this_job lists what you did for it so far. Which action comes next for this job? "
    'Choose "done" as soon as the job is complete, or if no action here can do it. Do not do '
    "more than the job asks and do not repeat an action whose result is already shown."
)
MANAGER_NOTE = (
    "Field work goes through expert agents. Each `<App>__expert_agent(task)` tool hands one job "
    "to the expert for that app; you cannot call the app's tools yourself. The tool description "
    "lists what each expert can do. The experts are decision models: they cannot write text and "
    "only pick actions and argument values from fixed lists. Numbers you write in the job are "
    "added to those lists, so write every amount, ridge range, sensor id and setting the job "
    "needs. An expert sees the job and the current farm state, not the season task and not this "
    "conversation. Give one small job at a time. The reply lists every action with its result "
    "and a status: `finished`, or `unsure`, `stuck`, `no_action` or `action_limit` when the job "
    "may not be complete; then check the actions, and rewrite the job more exactly or split it. "
    "You call the clock tools and the message to the user directly."
)


def job_ridge_range(job: str) -> tuple[int, int] | None:
    """The ridge range a job names, if it names exactly one."""
    found = {
        (int(a), int(b))
        for pattern in _RIDGE_RANGE_RES
        for a, b in pattern.findall(job or "")
        if int(a) <= int(b)
    }
    return found.pop() if len(found) == 1 else None


# Added to the farm system prompt of the local LLM in a hybrid expert.
LOCAL_LLM_NOTE = (
    "You are the local expert for one farm app. Jev, a decision model, does the routine steps of "
    "a job and you are asked only when Jev is unsure or stuck. The task is one job from the farm "
    "manager, not the whole season. You have this app's tools only; the manager has the clock "
    "and the other apps. If the job is complete, or the next step needs waiting or another app, "
    'reply "done" without calling a tool and say why in one line.'
)
# The expert has no clock, so "when the plan says to wait, advance time" does not apply.
EXPERT_PLAN_INSTRUCTIONS = (
    " If the state has a plan_from_advisor, follow its next step that is not done yet, unless "
    'the farm has changed so that it no longer fits. If what is left of the plan is waiting or '
    'needs another app, choose "done".'
)


class ManagerEscalation:
    """Stands in for farm_jev's fallback LLM: here "fallback" ends the job (see _llm_decide)."""

    model = "manager"
    provider = None


class JevExpertAgent(JevAgent):
    tool_instructions = EXPERT_TOOL_INSTRUCTIONS
    plan_instructions = EXPERT_PLAN_INSTRUCTIONS

    def __init__(
        self,
        name: str,
        llm: Any,
        app: Any,
        all_apps: list[Any],
        scenario_task: str = "",
        min_confidence: float = 0.4,
        local_llm: Any = None,
        system_message: str = "",
        run_max_tool_calls: int | None = None,
    ) -> None:
        num_ridges = next(int(a.num_ridges) for a in all_apps if hasattr(a, "num_ridges"))
        self.local_llm = local_llm
        self.run_max_tool_calls = run_max_tool_calls
        self._job_start = 0
        hybrid = local_llm is not None
        super().__init__(
            name=name,
            llm=llm,
            system_message=system_message,
            toolsets=[app],
            fallback_llm=local_llm if hybrid else ManagerEscalation(),
            fallback_confidence=min_confidence,
            num_ridges=num_ridges,
            fallback_memory="lean" if hybrid else "full",
            plan_note=hybrid,
            budget_note=hybrid,
        )
        self._toolsets = list(all_apps)  # the snapshot reads the whole farm
        self.app_name = getattr(app, "name", type(app).__name__)
        self.scenario_task = scenario_task
        self._job_text = ""
        self._handback: dict[str, Any] | None = None
        self._local_note: str | None = None
        self._last_decision: tuple[str, Any, dict[str, float]] | None = None

    def describe_tools(self) -> str:
        lines = [f"This expert can do ({self.app_name}):"]
        for tool in self.tools_map.values():
            docs = arg_descriptions(tool.function_description)
            args = ", ".join(a.name for a in tool.args)
            line = f"- {tool.name}({args}): {first_paragraph(tool.function_description)}"
            details = "; ".join(f"{k}: {v}" for k, v in docs.items())
            lines.append(f"{line} [{details}]" if details else line)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # One job
    # ------------------------------------------------------------------

    def start_job(self) -> None:
        self._job_start = len(_tool_steps(self.workflow))
        self._handback = None
        self._local_note = None

    def _reset_telemetry(self) -> None:
        super()._reset_telemetry()
        self._llm_seen_steps = self._job_start  # the local LLM hears about this job only

    def _budget(self) -> dict[str, Any] | None:
        self._max_tool_calls = self.run_max_tool_calls  # the run's limit, not the job's
        return super()._budget()

    def run(self, input, **kwargs):
        self._job_text = str(input)
        return super().run(input, **kwargs)

    def _menu_task_text(self, task: str) -> str:
        return f"{task}\n{self.scenario_task}"

    def _offer_done(self) -> bool:
        # With "done" offered at once, Jev skipped read jobs whose answer it believed it had.
        return bool(self._job_steps())

    def _value_questions(self, menu, tool_key=None):
        """When the job names a ridge range, only ridges inside it are offered."""
        questions, options = super()._value_questions(menu, tool_key)
        job_range = job_ridge_range(self._job_text)
        if job_range is None:
            return questions, options
        low, high = job_range
        width = PASS_WIDTH.get(tuple(menu.tool_name.split("__", 1))) or self._num_ridges
        for name, (qid, opts) in options.items():
            if name in RANGE_STARTS or name == "ridge_id":
                narrowed = {k: v for k, v in opts.items() if low <= v <= high}
            elif name in RANGE_END_TO_START and qid in questions and any(
                k.endswith(("ridge", "ridges")) for k in opts
            ):
                narrowed = {k: v for k, v in opts.items() if v <= min(width, high - low + 1)}
            else:
                continue
            if narrowed:
                options[name] = (qid, narrowed)
                questions[qid]["criteria"] = {key: None for key in narrowed}
        return questions, options

    def _decide(self, state, skip_args_below=None):
        decision = super()._decide(state, skip_args_below)
        self._last_decision = decision
        return decision

    def _done_problems(self, task: str) -> list[str]:
        return []  # "done" here ends one job; the season-level check stays on the main agent

    def _state(self) -> dict[str, Any]:
        state = super()._state()
        job_steps = self._facts["steps"][self._job_start:]
        extra = {k: state[k] for k in ("plan_from_advisor", "action_budget", "notes") if k in state}
        return {
            "task": self._job_text,
            "app": self.app_name,
            "farm_now": state["farm_now"],
            "steps_in_this_job": step_history(job_steps),
            "recent_actions": [
                {
                    "action": s.tool_name,
                    "arguments": s.tool_args or {},
                    "failed": _failed(s),
                    "result": _short(s.content),
                }
                for s in job_steps[-3:]
            ],
            **extra,
        }

    def _llm_decide(self, state, reason, fill_tool=None):
        """Without a local LLM, an unsure or stuck Jev ends the job with what it did so far."""
        if self.local_llm is not None:
            decided = super()._llm_decide(state, reason, fill_tool)
            if decided is not None and decided[0] == DONE_OPTION:
                self._local_note = self.runtime_events[-1].get("content")
            return decided
        top = sorted(self._last_tool_probabilities.items(), key=lambda kv: -kv[1])[:TOP_OPTIONS]
        pick, arguments, confidences = self._last_decision
        self._handback = {
            "reason": reason,
            "top_options": {name: round(float(p), 3) for name, p in top},
            "wanted": {"action": pick.split("__", 1)[-1], "arguments": arguments},
            "least_sure_about": min(confidences, key=confidences.get).split("__")[-1],
        }
        self.record_event("jev_expert_handback", status="ok", app=self.app_name, **self._handback)
        return DONE_OPTION, {}

    # ------------------------------------------------------------------
    # Reply to the main agent (written by code)
    # ------------------------------------------------------------------

    def _job_steps(self) -> list[Any]:
        return _tool_steps(self.workflow)[self._job_start:]

    def _status(self, limit: str | None) -> str:
        if limit:
            return "action_limit"
        if self._handback:
            return "stuck" if self._handback["reason"] == "repeat_without_change" else "unsure"
        return "finished" if self._job_steps() else "no_action"

    def job_report(self, limit: str | None = None) -> str:
        report: dict[str, Any] = {
            "status": self._status(limit),
            "actions": [
                {
                    "action": s.tool_name.split("__", 1)[-1],
                    "arguments": s.tool_args or {},
                    "failed": _failed(s),
                    "result": _short(s.content, REPORT_RESULT_CHARS),
                }
                for s in self._job_steps()
            ],
        }
        if self._handback:
            report["expert_top_options"] = self._handback["top_options"]
            report["expert_wanted_not_done"] = self._handback["wanted"]
            report["expert_least_sure_about"] = self._handback["least_sure_about"]
        if self._local_note:
            report["expert_note"] = self._local_note
        return json.dumps(report, ensure_ascii=False, default=str)

    def job_summary(self) -> dict[str, Any]:
        confidences = self._action_confidences
        return {
            "status": self._status(None),
            "handback": self._handback,
            "tools": [s.tool_name for s in self._job_steps()],
            "jev_requests": self._jev_request_count,
            "jev_input_tokens": self._jev_tokens,
            "llm_handoffs": dict(self._fallbacks),
            "plans_written": self._plans_written,
            "avg_confidence": round(sum(confidences) / len(confidences), 4) if confidences else None,
        }


class JevAppAgentBuilder:
    """Same interface as AppAgentBuilder, for apply_a2a_to_apps."""

    def __init__(
        self,
        all_apps: list[Any],
        scenario_task: str = "",
        min_confidence: float = 0.4,
        local_llm_factory: Any = None,
        system_message: str = "",
        run_max_tool_calls: int | None = None,
    ) -> None:
        self.all_apps = list(all_apps)
        self.scenario_task = scenario_task
        self.min_confidence = min_confidence
        self.local_llm_factory = local_llm_factory
        self.system_message = system_message
        self.run_max_tool_calls = run_max_tool_calls

    def build(self, app_agent_config: Any, llm: Any, app: Any) -> JevExpertAgent:
        return JevExpertAgent(
            name=f"jev_expert_{getattr(app, 'name', type(app).__name__)}",
            llm=llm,
            app=app,
            all_apps=self.all_apps,
            scenario_task=self.scenario_task,
            min_confidence=self.min_confidence,
            local_llm=self.local_llm_factory() if self.local_llm_factory else None,
            system_message=self.system_message,
            run_max_tool_calls=self.run_max_tool_calls,
        )
