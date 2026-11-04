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
"""

from __future__ import annotations

import json
from typing import Any

from fairy.agents.jev.jev_agent import DONE_OPTION, JevAgent
from fairy.agents.jev.menu import arg_descriptions, first_paragraph
from fairy.agents.jev.snapshot import _failed, _short, _tool_steps, step_history

REPORT_RESULT_CHARS = 8000
TOP_OPTIONS = 3
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


class ManagerEscalation:
    """Stands in for farm_jev's fallback LLM: here "fallback" ends the job (see _llm_decide)."""

    model = "manager"
    provider = None


class JevExpertAgent(JevAgent):
    tool_instructions = EXPERT_TOOL_INSTRUCTIONS

    def __init__(
        self,
        name: str,
        llm: Any,
        app: Any,
        all_apps: list[Any],
        scenario_task: str = "",
        min_confidence: float = 0.4,
    ) -> None:
        num_ridges = next(int(a.num_ridges) for a in all_apps if hasattr(a, "num_ridges"))
        super().__init__(
            name=name,
            llm=llm,
            toolsets=[app],
            fallback_llm=ManagerEscalation(),
            fallback_confidence=min_confidence,
            num_ridges=num_ridges,
        )
        self._toolsets = list(all_apps)  # the snapshot reads the whole farm
        self.app_name = getattr(app, "name", type(app).__name__)
        self.scenario_task = scenario_task
        self._job_start = 0
        self._job_text = ""
        self._handback: dict[str, Any] | None = None

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

    def run(self, input, **kwargs):
        self._job_text = str(input)
        return super().run(input, **kwargs)

    def _menu_task_text(self, task: str) -> str:
        return f"{task}\n{self.scenario_task}"

    def _done_problems(self, task: str) -> list[str]:
        return []  # "done" here ends one job; the season-level check stays on the main agent

    def _state(self) -> dict[str, Any]:
        state = super()._state()
        job_steps = self._facts["steps"][self._job_start:]
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
        }

    def _llm_decide(self, state, reason, fill_tool=None):
        """No LLM in the expert: an unsure or stuck Jev ends the job with what it did so far."""
        top = sorted(self._last_tool_probabilities.items(), key=lambda kv: -kv[1])[:TOP_OPTIONS]
        self._handback = {
            "reason": reason,
            "top_options": {name: round(float(p), 3) for name, p in top},
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
        return json.dumps(report, ensure_ascii=False, default=str)

    def job_summary(self) -> dict[str, Any]:
        confidences = self._action_confidences
        return {
            "status": self._status(None),
            "handback": self._handback,
            "tools": [s.tool_name for s in self._job_steps()],
            "jev_requests": self._jev_request_count,
            "jev_input_tokens": self._jev_tokens,
            "avg_confidence": round(sum(confidences) / len(confidences), 4) if confidences else None,
        }


class JevAppAgentBuilder:
    """Same interface as AppAgentBuilder, for apply_a2a_to_apps."""

    def __init__(self, all_apps: list[Any], scenario_task: str = "", min_confidence: float = 0.4) -> None:
        self.all_apps = list(all_apps)
        self.scenario_task = scenario_task
        self.min_confidence = min_confidence

    def build(self, app_agent_config: Any, llm: Any, app: Any) -> JevExpertAgent:
        return JevExpertAgent(
            name=f"jev_expert_{getattr(app, 'name', type(app).__name__)}",
            llm=llm,
            app=app,
            all_apps=self.all_apps,
            scenario_task=self.scenario_task,
            min_confidence=self.min_confidence,
        )
