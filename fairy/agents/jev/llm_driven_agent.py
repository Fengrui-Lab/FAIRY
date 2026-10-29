"""LLM-driven agent with Jev as a tool (farm_llm_jev).

The LLM baseline (farm_baseline_react) runs the farm as usual, with the normal
FAIRY task, system prompt and tools, plus one extra tool, ``ask_jev``. The LLM
writes a farm state itself and a question with options; Jev returns its pick,
the probability of each option and its confidence. The LLM decides when to ask
and what to do with the answer; no rule makes it ask. Optionally (``--jev-prompt-note``,
off by default) a short neutral note about Jev is added to the system prompt.

ask_jev is not a farm action: it is not in the workflow (so scoring and replay
see only farm tools) and does not count toward max_tool_calls. Each call is
logged as an ``ask_jev`` runtime event and counted in the controller telemetry.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from fairy.agents.agent.base_agent import CST
from fairy.agents.jev.menu import MAX_CHOICE_OPTIONS
from fairy.controllers.agent_builder import ResearchARESimulationAgent
from fairy.controllers.agent_config import ResearchAgentProfileConfig

ASK_JEV_TOOL = "ask_jev"
ASK_JEV_QUESTION_ID = "question"
# Jev input price used in the docs/jev cost tables ($ per input token).
JEV_PRICE_PER_INPUT_TOKEN = 0.042e-6
# Guard against a loop of asks: ask_jev does not count toward max_tool_calls.
MAX_ASK_JEV_CALLS = 300

# Optional system-prompt note (--jev-prompt-note): what Jev is and returns, no rule on when to ask.
JEV_PROMPT_NOTE = (
    "You also have the tool ask_jev. Jev is a decision model: you give it a farm state that you "
    "write, a question and a list of options, and it returns its pick, the probability of each "
    "option and its confidence (0 to 1). Jev sees only what you pass. Use it when it helps; "
    "the decision stays yours."
)

ASK_JEV_SCHEMA = {
    "type": "function",
    "function": {
        "name": ASK_JEV_TOOL,
        "description": (
            "Ask Jev, a decision model, to choose one option for a decision. Jev sees only the "
            "state and question you pass here: not this conversation, not the task and not the "
            "farm. Write in the state the facts that matter for the decision. Jev returns its "
            "pick, the probability of each option and its confidence (0 to 1). It does not act "
            "on the farm; you decide what to do with its answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "state": {
                    "type": "object",
                    "description": (
                        "The farm state you write for Jev, as a JSON object (for example date, "
                        "crop stage per ridge range, weather, sensor readings, inventory, machines, "
                        "what is already done)."
                    ),
                },
                "question": {"type": "string", "description": "The question Jev should answer."},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "description": "The options Jev chooses from (at least 2, distinct).",
                },
            },
            "required": ["state", "question", "options"],
        },
    },
}


class LLMDrivenJevAgent(ResearchARESimulationAgent):
    def __init__(
        self,
        name: str,
        llm: Any,
        jev_llm: Any,
        system_message: str,
        toolsets: list[Any] | None = None,
    ) -> None:
        self.jev_llm = jev_llm  # before super().__init__, which resets the telemetry
        super().__init__(
            name=name,
            llm=llm,
            controller_profile=ResearchAgentProfileConfig.for_family("farm_baseline_react"),
            system_message=system_message,
            toolsets=toolsets,
        )
        self.tool_schemas = list(self.tool_schemas or []) + [ASK_JEV_SCHEMA]
        self._reset_jev_counts()

    def _reset_jev_counts(self) -> None:
        self._ask_jev_calls = 0
        self._ask_jev_errors = 0
        self._jev_input_tokens = 0
        self._jev_output_tokens = 0
        self._jev_confidences: list[float] = []
        self._jev_state_chars: list[int] = []
        # Farm actions taken right after an ask (the next farm call after one or more asks).
        self._asked_since_action = False
        self._actions_after_ask = 0

    def _reset_research_state(self) -> None:
        super()._reset_research_state()
        self.telemetry["planning_mode"] = "react_llm_with_jev_tool"
        self.telemetry["jev_model"] = getattr(self.jev_llm, "model", None)
        self.telemetry["jev_prompt_note"] = any(
            isinstance(m, dict) and m.get("role") == "system" and JEV_PROMPT_NOTE in str(m.get("content"))
            for m in self.messages.messages
        )
        self._reset_jev_counts()

    # ------------------------------------------------------------------
    # Tool calls
    # ------------------------------------------------------------------

    def call_function(self, tool_call):
        if tool_call.function.name != ASK_JEV_TOOL:
            if self._asked_since_action:
                self._actions_after_ask += 1
                self._asked_since_action = False
            return super().call_function(tool_call)
        started = time.perf_counter()
        result = self._ask_jev(tool_call.id, tool_call.function.arguments)
        env_ts = datetime.fromtimestamp(self.time_manager.time(), tz=CST).strftime("%Y-%m-%d %H:%M:%S")
        self.messages.tool_call_response(
            json.dumps(result, ensure_ascii=False), tool_call, round(time.perf_counter() - started, 6), env_ts
        )
        return result

    def after_tool_response(self, tool_call: Any, tool_response: Any) -> None:
        # The baseline's telemetry counts farm tools only.
        if tool_call.function.name != ASK_JEV_TOOL:
            super().after_tool_response(tool_call, tool_response)

    def _ask_jev(self, call_id: str, raw_arguments: str | None) -> dict[str, Any]:
        """One Jev request; problems go back to the LLM as an error, the run goes on."""
        try:
            args = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError as exc:
            return self._ask_jev_error(call_id, f"arguments are not valid JSON: {exc}")
        if not isinstance(args, dict):
            return self._ask_jev_error(call_id, "arguments must be a JSON object")
        state = args.get("state")
        if isinstance(state, str):
            state = {"farm_state": state}
        question = str(args.get("question") or "").strip()
        options = list(dict.fromkeys(str(o).strip() for o in args.get("options") or [] if str(o).strip()))
        if not isinstance(state, dict) or not state:
            return self._ask_jev_error(call_id, "state must be a non-empty JSON object")
        if not question:
            return self._ask_jev_error(call_id, "question is empty")
        if not 2 <= len(options) <= MAX_CHOICE_OPTIONS:
            return self._ask_jev_error(call_id, f"give between 2 and {MAX_CHOICE_OPTIONS} distinct options")
        if self._ask_jev_calls >= MAX_ASK_JEV_CALLS:
            return self._ask_jev_error(call_id, f"limit of {MAX_ASK_JEV_CALLS} Jev requests per run reached")

        state_chars = len(json.dumps(state, ensure_ascii=False, default=str))
        questions = {
            ASK_JEV_QUESTION_ID: {
                "type": "choice",
                "instructions": question,
                "criteria": {o: None for o in options},
            }
        }
        started = time.perf_counter()
        try:
            response = self.jev_llm.system_one(state, questions)
        except Exception as exc:
            return self._ask_jev_error(call_id, f"Jev request failed: {type(exc).__name__}: {exc}")
        latency = round(time.perf_counter() - started, 6)
        answer = response.choices[ASK_JEV_QUESTION_ID]
        input_tokens = int(getattr(response.usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(response.usage, "output_tokens", 0) or 0)
        cost = input_tokens * JEV_PRICE_PER_INPUT_TOKEN

        self._ask_jev_calls += 1
        self._asked_since_action = True
        self._jev_input_tokens += input_tokens
        self._jev_output_tokens += output_tokens
        self._jev_confidences.append(float(answer.confidence))
        self._jev_state_chars.append(state_chars)
        tokens = {
            "prompt_tokens": input_tokens,
            "cached_tokens": 0,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        # Same metric shape as the LLM's, so run_report token totals include Jev.
        self.messages.runtime_metrics.append(
            {"role": "assistant", "time": latency, "accepted": True, "tokens": tokens, "source": "jev"}
        )
        result = {
            "pick": answer.choice,
            "probabilities": {k: round(float(v), 4) for k, v in dict(answer.probabilities).items()},
            "confidence": round(float(answer.confidence), 4),
        }
        self.record_event(
            "ask_jev",
            status="ok",
            tool_call_id=call_id,
            ask_index=self._ask_jev_calls,
            farm_actions_before=self.tool_call_count,
            model=getattr(self.jev_llm, "model", None),
            model_version=getattr(response, "model", None),
            request_id=getattr(response, "request_id", None),
            state_chars=state_chars,
            state_keys=list(state),
            state=state,
            question=question,
            options=options,
            option_count=len(options),
            pick=result["pick"],
            confidence=result["confidence"],
            probabilities=result["probabilities"],
            tokens=tokens,
            cost_usd=round(cost, 8),
            wall_time_seconds=latency,
        )
        return result

    def _ask_jev_error(self, call_id: str, message: str) -> dict[str, Any]:
        self._ask_jev_errors += 1
        self.record_event("ask_jev_error", status="error", tool_call_id=call_id, error_message=message)
        return {"error": message}

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------

    def after_agent_run(self) -> None:
        calls, actions = self._ask_jev_calls, self.tool_call_count
        confidences, chars = self._jev_confidences, self._jev_state_chars
        llm_tokens = {"prompt_tokens": 0, "cached_tokens": 0, "completion_tokens": 0}
        for metric in self.messages.runtime_metrics:
            if metric.get("role") == "assistant" and metric.get("source") != "jev":
                for k in llm_tokens:
                    llm_tokens[k] += int((metric.get("tokens") or {}).get(k) or 0)
        self.telemetry.update(
            {
                "ask_jev_calls": calls,
                "ask_jev_errors": self._ask_jev_errors,
                "farm_actions": actions,
                "ask_jev_per_action": round(calls / actions, 3) if actions else None,
                "actions_after_ask": self._actions_after_ask,
                "actions_after_ask_share": round(self._actions_after_ask / actions, 3) if actions else None,
                "avg_jev_confidence": round(sum(confidences) / len(confidences), 4) if confidences else None,
                "avg_jev_state_chars": round(sum(chars) / len(chars)) if chars else None,
                "max_jev_state_chars": max(chars) if chars else None,
                "jev_input_tokens": self._jev_input_tokens,
                "jev_output_tokens": self._jev_output_tokens,
                "jev_cost_usd": round(self._jev_input_tokens * JEV_PRICE_PER_INPUT_TOKEN, 6),
                "llm_tokens": llm_tokens,
            }
        )
        super().after_agent_run()


def build_llm_driven_jev_agent(
    family_id: str,
    llm: Any,
    jev_llm: Any,
    toolsets: list[Any] | None,
    system_message: str,
    prompt_note: bool = False,
) -> LLMDrivenJevAgent:
    if jev_llm is None or getattr(jev_llm, "provider", None) != "typesafe":
        raise ValueError("farm_llm_jev needs a Jev client (--jev-model, provider typesafe)")
    return LLMDrivenJevAgent(
        name=family_id,
        llm=llm,
        jev_llm=jev_llm,
        system_message=f"{system_message}\n\n{JEV_PROMPT_NOTE}" if prompt_note else system_message,
        toolsets=toolsets,
    )
