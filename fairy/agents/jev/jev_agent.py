"""Jev agent: TypeSafe's Jev picks each next action from a menu.

Only the decision step differs from the LLM agent. FAIRY's own Agent.run loop
still executes the tool, enforces max_tool_calls / timeout, and records the
workflow and runtime log, so run_report.json and agent_workflow.json have the
same format as for the LLM agents.

Independent arguments share Jev requests (fan-out; Jev bills the
state once per request, so questions that do not depend on each other share one):
  1. one Choice over the scenario's tools plus "done", together with the
     argument questions of the likely tools (Jev's top tools in the previous
     request and the last few actions); answers for tools not picked are ignored;
  2. only if the picked tool takes arguments and was not among the likely
     tools, one Choice per argument, sent together.
A ridge range is asked as start, then a dependent "how many ridges" question.
The latter uses the selected farm boundary and native pass limit; it is never
speculatively requested before the start is known (ridge-range-bounded-v1).
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

from fairy.agents.jev.constraints import family as tool_family, legal_options, action_blocker

import json
import math
import re
import time
from types import SimpleNamespace
from typing import Any

from fairy.agents.agent.agent import Agent
from fairy.agents.llm.decision_response import (
    DecisionBatch, DecisionProtocolError, normalize_response,
)
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
from fairy.agents.jev.baseline_parameters import BaselineParameters
from fairy.agents.jev import management, decision_context, model_view, establishment
from fairy.agents.jev.execution_guidance import (
    EXECUTION_GUIDANCE_VERSION, EXECUTION_GUIDANCE_SHA256, execution_guidance,
)
from fairy.agents.jev.done_check import MAX_DONE_REFUSALS, REPORT_TOOL, done_problems
from fairy.agents.jev.menu import dependent_menu, extended_scene_tool, scene_world, build_arg_menu, arg_descriptions, MAX_CHOICE_OPTIONS
from fairy.agents.jev.snapshot import RESULT_CHARS, _failed, _result_data, _short, build_snapshot, ridge_ranges

TOOL_QUESTION_ID = "next_action"
PART1_TOOL_INSTRUCTIONS = "Which action should the farm agent take next?"
BASELINE_TOOL_INSTRUCTIONS = (
    "Which action should the farm agent take next? Take the next step of the task that is not "
    "done yet; steps_so_far lists every action already taken. Do not repeat an action whose "
    "result is already shown unless the farm has changed since."
)

TOOL_INSTRUCTIONS = BASELINE_TOOL_INSTRUCTIONS + " Follow jev_execution_guidance in the state for task scope, failure recovery and waiting."

# End-of-range argument -> its start argument. The end is asked after the start.
RANGE_END_TO_START = {"end_ridge": "start_ridge", "end": "start"}
RANGE_STARTS = frozenset(RANGE_END_TO_START.values())
RIDGE_RANGE_ADAPTER_VERSION = "ridge-range-bounded-v1"

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
        confidence_source: str = "provider",
        qwen_context_policy: str = "bounded_history",
        hybrid_mode: str = "full",
        enforced_tool_adaptor: bool = False,
    ) -> None:
        if state_mode not in ("snapshot", "history"):
            raise ValueError(f"Unknown Jev state mode: {state_mode}")
        if qwen_context_policy not in ("bounded_history", "snapshot_only"):
            raise ValueError("Unknown Qwen context policy")
        if type(enforced_tool_adaptor) is not bool:
            raise ValueError("enforced_tool_adaptor must be boolean")
        self.enforced_tool_adaptor = enforced_tool_adaptor
        self.qwen_context_policy = qwen_context_policy
        self.fallback_llm = fallback_llm
        self.fallback_confidence = fallback_confidence
        self.state_mode = state_mode
        if confidence_source not in ("provider", "max_probability"):
            raise ValueError("Unknown decision confidence source")
        self.confidence_source = confidence_source
        if hybrid_mode not in HYBRID_MODES:
            raise ValueError(f"Unknown hybrid mode: {hybrid_mode}")
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
            from fairy.apps.farm_world.multi_farm import farm_world_apps
            self._num_ridges = max((f.num_ridges for f in farm_world_apps(self._toolsets)), default=None)
        if self._num_ridges is None and any(type(t).__name__ == "PaddyWorldApp" for t in self._toolsets):
            self._num_ridges = 0  # Paddy uses plots, never synthesized ridge IDs.
        if self._num_ridges is None:
            raise ValueError("JevAgent needs a farm app with num_ridges in its toolsets")
        self.tool_menus: dict[str, ToolMenu] = {}
        self._reset_telemetry()

    def _reset_telemetry(self) -> None:
        self._action_confidences: list[float] = []
        self._action_count = 0
        self._logical_turn = 0
        self._request_serial = 0
        self._active_request_id = None
        self._jev_request_count = 0
        self._decision_http_requests = 0
        self._decision_input_known = 0
        self._decision_usage_missing = False
        self._deterministic_questions = 0
        self._decision_model_actions = 0
        self._last_tool_deterministic = False
        self._done_refusals = 0
        self._llm_done_refusals = 0
        self._notes: list[str] = []
        self._management = None
        self._derived_management_arguments = 0
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
            "qwen_context_policy": self.qwen_context_policy,
            "decision_provider": getattr(self.llm, "provider", None),
            "decision_model": getattr(self.llm, "model", None),
            "decision_confidence_source": self.confidence_source,
            "fallback_provider": getattr(self.fallback_llm, "provider", None),
            "planning_mode": f"jev_menu_choice_{self.state_mode}",
            "fallback_model": getattr(self.fallback_llm, "model", None),
            "fallback_confidence": self.fallback_confidence if self.fallback_llm else None,
            "fallback_config": {
                "provider": getattr(self.fallback_llm, "provider", None),
                "model": getattr(self.fallback_llm, "model", None),
                "base_url": getattr(self.fallback_llm, "base_url", None),
                "max_output_tokens": getattr(self.fallback_llm, "max_output_tokens", None),
                "enable_thinking": getattr(self.fallback_llm, "enable_thinking", None),
            } if self.fallback_llm else None,
            "hybrid_mode": self.hybrid_mode,
            **self._adaptor_metadata(),
        }

    def _adaptor_metadata(self):
        enabled = self.enforced_tool_adaptor
        if self.name in {"farm_llm_snapshot", "farm_qwen_snapshot"}:
            return {"enforced_tool_adaptor": None, "tool_adaptor_profile": "not-applicable",
                    "completion_language_version": "zh-en-done-v1",
                    "execution_guidance_version": EXECUTION_GUIDANCE_VERSION,
                    "execution_guidance_sha256": EXECUTION_GUIDANCE_SHA256}
        return {
            "enforced_tool_adaptor": enabled,
            "tool_adaptor_profile": management.PROFILE if enabled else "manos-compatible-v1",
            "management_adapter_version": management.VERSION if enabled else None,
            "decision_context_version": decision_context.VERSION if enabled else None,
            "decision_context_sha256": decision_context.SHA256 if enabled else None,
            "model_view_version": model_view.VERSION if enabled else None,
            "model_view_contract_sha256": model_view.SHA256 if enabled else None,
            "history_retention_policy": {
                "version": model_view.HISTORY_POLICY,
                "max_age_sim_seconds": model_view.HISTORY_MAX_AGE_SECONDS,
                "observation_limit": model_view.OBSERVATION_LIMIT,
                "observation_bytes": model_view.OBSERVATION_BYTES,
                "failure_limit": model_view.FAILURE_LIMIT,
                "failure_bytes": model_view.FAILURE_BYTES,
                "result_preview_bytes": model_view.RESULT_PREVIEW_BYTES,
                "request_target_bytes": model_view.REQUEST_TARGET_BYTES,
            } if enabled else None,
            "tool_feasibility_version": "public-feasibility-v1" if enabled else None,
            "temporal_guidance_version": "temporal-progress-v4" if enabled else None,
            "state_semantics_version": "public-state-semantics-v1.2" if enabled else None,
            "establishment_adapter_version": establishment.VERSION if enabled else None,
            "entity_contract_version": "receipt-entity-v1" if enabled else None,
            "management_guidance_sha256": management.SHA256 if enabled else None,
            "completion_language_version": "zh-en-done-v1",
            "ridge_range_adapter_version": RIDGE_RANGE_ADAPTER_VERSION if enabled else "legacy-count-v1",
            "seed_amount_adapter_version": "task_seed_demand_v1" if enabled else None,
            "execution_guidance_version": EXECUTION_GUIDANCE_VERSION if enabled else None,
            "execution_guidance_sha256": EXECUTION_GUIDANCE_SHA256 if enabled else None,
        }

    def record_event(self, event_type: str, **payload: Any):
        payload.setdefault("logical_action_id", f"action_{getattr(self, '_logical_turn', 0)}")
        payload.setdefault("logical_request_id", getattr(self, "_active_request_id", None))
        for index, batch in enumerate(payload.get("batches", [])):
            batch.setdefault("batch_id", f"{payload['logical_request_id']}_batch_{index + 1}")
        return super().record_event(event_type, **payload)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self, input, **kwargs):
        self._reset_telemetry()
        self.tool_menus = build_tool_menus(
            self.tools_map, task_text=str(input), num_ridges=self._num_ridges,
            enforced_tool_adaptor=self.enforced_tool_adaptor
        )
        self.record_event(
            "jev_menu",
            status="ok",
            **self._adaptor_metadata(),
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
                "management_derived_arguments": self._derived_management_arguments,
                "llm_done_refusals": self._llm_done_refusals,
                "jev_input_tokens": self._jev_tokens,
                "decision_http_requests": self._decision_http_requests,
                "decision_input_tokens_known": self._decision_input_known,
                "decision_usage_complete": not self._decision_usage_missing,
                "deterministic_questions": self._deterministic_questions,
                "decision_model_actions": self._decision_model_actions,
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
        self._logical_turn += 1
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
        if source == "jev" and pick != DONE_OPTION and not self._last_tool_deterministic:
            self._decision_model_actions += 1
        self.record_event(
            "jev_action",
            status="ok",
            action=pick,
            arguments=arguments,
            action_confidence=action_confidence,
            tool_confidence=tool_confidence,
            question_confidences=confidences,
            source=source,
            deterministic=source == "jev" and self._last_tool_deterministic,
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

    def _management_enabled(self):
        # Pure-LLM snapshot inherits JevAgent; preserve its pre-v2 inputs.
        return self.enforced_tool_adaptor and not getattr(self, "strict_qwen", False)

    def _uses_managed_values(self, menu):
        if not self._management_enabled() or not self._management:
            return False
        native = self.tools_map[menu.tool_name]
        from fairy.agents.jev.entities import dependent
        if dependent(native):return True
        from fairy.agents.jev.establishment import supported
        if supported(native,getattr(self,'_snapshot_task',''),self._facts):return True
        cls, name = tool_family(native), native.name
        from fairy.agents.jev.ridge_irrigation import supported
        # Use dependent resolution where selectors affect resource arithmetic;
        # retain existing safe fan-out for unrelated read/range tools.
        return ((cls == 'TractorApp' and name in {'load_fertilizer','load_seeds','refuel','load_pesticide','load_fungicide','refill_pesticide_tank'}) or
                (cls == 'TractorApp' and name == 'apply_fertilizer') or
                (cls == 'TractorApp' and name == 'base_fertilize' and self._management['plan']['kind'] == 'ridge') or
                cls in {'PaddyOpsApp','PaddyMachineryApp'} or
                (cls == 'FarmWorldApp' and name == 'dry_grain') or
                (cls == 'FarmWorldApp' and name == 'apply_fertigation') or supported(native))

    def _management_criteria(self, criteria):
        if not self._management_enabled():
            return criteria
        criteria = dict(criteria)
        reasons = {}
        problems = self._done_problems(getattr(self, "_snapshot_task", ""))
        if problems and DONE_OPTION in criteria:
            criteria.pop(DONE_OPTION)
            reasons[DONE_OPTION] = problems
        context = self._management
        if context:
            plan, ledger = context['plan'], context['ledger']
            for name in list(criteria):
                if name not in self.tools_map:
                    continue
                native = self.tools_map[name]
                hard_blocker = action_blocker(native, self._facts, self._facts.get("now"))
                if not hard_blocker:
                    from fairy.agents.jev.ridge_irrigation import blocker
                    hard_blocker = blocker(native,self._facts,context)
                if hard_blocker:
                    if native.name in ('apply_fertilizer', 'apply_fertigation', 'base_fertilize'):
                        current = context['next_ridge_fertilizer_round']
                        if current and plan['kind'] == 'ridge' and native.name != 'base_fertilize':
                            hard_blocker = f'Fertilizer round {current["index"]} remains incomplete ({sum(current["remaining_by_ridge_kg"].values()):g} kg product). ' + hard_blocker
                    if native.name=='apply_fertilizer' and plan['kind']=='paddy':
                        remaining=[]
                        for plot in self._facts.get('plots',[]):
                            r=management.paddy_round(plan,ledger,plot['plot_id'])
                            if r and not plot.get('harvested'):remaining.append(dict(plot_id=plot['plot_id'],round=r['index'],required_product_kg=r['remaining_kg_ha']*plot['area_m2']/10000))
                        if remaining:hard_blocker=f'Plot fertilizer doses remain incomplete: {remaining}. '+hard_blocker+' For these incomplete plots, load the prescribed batch first if quota permits.'
                        else:hard_blocker='All explicit fertilizer doses are accounted for; this does not complete other seasonal work.'
                    criteria.pop(name)
                    reasons[name] = [hard_blocker]
                    continue
                from fairy.agents.jev.establishment import blocker as establishment_blocker
                reason=establishment_blocker(native,getattr(self,'_snapshot_task',''),self._facts)
                if reason:
                    criteria.pop(name);reasons[name]=[reason]
                    continue
                if tool_family(native) == 'PaddyOpsApp' and native.name == 'irrigate':
                    limits = context['canal_limits']
                    if limits and not any(c['is_open'] and any(v > management.EPS for v in c['max_delivery_mm_by_plot'].values()) for c in limits):
                        criteria.pop(name)
                        reasons[name] = ['Canal is closed, blocked or has no public quota; use the explicit UTC opening time or repair/inspection.']
                        continue
                resources = management.fertilizer_resources(native, self._facts)
                if not resources:
                    continue
                blocked = None
                if native.name == 'load_fertilizer':
                    if resources['load_limit_kg'] <= management.EPS:
                        blocked = ('Observed fertilizer stock is empty; loading cannot add supply.' if resources['stock_kg'] <= management.EPS else
                                   'The applicator has no free fertilizer capacity; use its carried supply before loading again.')
                    elif plan['kind'] in ('paddy', 'ridge'):
                        value = management.derive_fertilizer(native, 'kg', {}, plan, ledger, self._facts)
                        known = plan['kind'] == 'paddy' or plan.get('topdress') or ledger['basal_used_kg'] < plan.get('basal_kg', 0)
                        if known and value is None:
                            if plan['kind'] == 'ridge':
                                basal_left = max(0., plan['basal_kg']-ledger['basal_used_kg'])
                                current = context['next_ridge_fertilizer_round']
                                needed = basal_left if basal_left > management.EPS else sum(current['remaining_by_ridge_kg'].values()) if current else 0.
                            else:
                                remaining = [(p, management.paddy_round(plan, ledger, p['plot_id'])) for p in self._facts.get('plots', []) if not p.get('harvested')]
                                active = [r['index'] for p,r in remaining if r]
                                needed = sum(r['remaining_kg_ha']*p['area_m2']/10000 for p,r in remaining if r and r['index']==min(active)) if active else 0.
                            if needed <= management.EPS:
                                blocked = 'All explicit fertilizer doses are accounted for by successful receipts; this does not complete other seasonal work.'
                            elif resources['remaining_quota_kg'] is not None and resources['remaining_quota_kg'] <= management.EPS:
                                blocked = 'Fertilizer work remains, but the public quota is exhausted; loading does not restore quota.'
                            elif resources['carried_kg']+management.EPS >= needed:
                                blocked = f'The next prescribed batch ({needed:g} kg) is already carried; loading cannot add the same batch. Check its reference timing and actual need before field application.'
                            else:
                                blocked = 'The current batch cannot be derived from the observed resources; inspect the resource constraint, not assumed task completion.'
                elif native.name == 'base_fertilize' and plan['kind'] == 'ridge':
                    left = max(0., plan['basal_kg']-ledger['basal_used_kg'])
                    if left <= management.EPS or resources['carried_kg']+management.EPS < left:
                        blocked = ('Basal prescribed dose is complete.' if left <= management.EPS else
                                   f'Basal dose remains {left:g} kg; carried {resources["carried_kg"]:g} kg. Load fertilizer first; the dose is not complete.')
                elif native.name in ('apply_fertilizer', 'apply_fertigation'):
                    if plan['kind'] == 'paddy':
                        feasible = []
                        incomplete = []
                        for plot in self._facts.get('plots', []):
                            r = management.paddy_round(plan, ledger, plot['plot_id'])
                            if r and not plot.get('harvested'):
                                required = r['remaining_kg_ha']*plot['area_m2']/10000
                                incomplete.append(dict(plot_id=plot['plot_id'], round=r['index'], required_product_kg=required))
                                if required <= resources['carried_kg']+management.EPS:
                                    feasible.append(plot['plot_id'])
                        if not feasible:
                            blocked = (f'Plot fertilizer doses remain incomplete: {incomplete}. Carried fertilizer {resources["carried_kg"]:g} kg is insufficient; load the prescribed batch first.' if incomplete else
                                       'All explicit fertilizer doses for unharvested plots are accounted for; this does not complete other seasonal work.')
                    elif plan['kind'] == 'ridge' and plan.get('topdress'):
                        r = context['next_ridge_fertilizer_round']
                        quota = resources['remaining_quota_kg']
                        available = min(resources['available_kg'], quota) if quota is not None else resources['available_kg']
                        if not r:
                            blocked = 'All explicit fertilizer rounds are accounted for by successful product receipts; this does not complete other seasonal work.'
                        elif min(r['remaining_by_ridge_kg'].values()) > available+management.EPS:
                            need = min(r['remaining_by_ridge_kg'].values())
                            blocked = (f'Fertilizer round {r["index"]} remains incomplete; at least {need:g} kg is needed for one remaining ridge, '
                                       f'available to this tool {available:g} kg. ' +
                                       ('The remaining fertilizer quota is insufficient; inspect resources or defer.' if quota is not None and quota+management.EPS < need else
                                        'Load fertilizer first for this tool; prior-round coverage does not complete this round.'))
                if blocked:
                    criteria.pop(name)
                    reasons[name] = [blocked]
            due = {w['kind'] for w in context['windows'] if w['at'] <= self.time_manager.time()}
            due_tools = {w['tool'] for w in context['windows'] if w['at'] <= self.time_manager.time() and w.get('tool')}
            for name in list(criteria):
                if name in due_tools or ('fertilizer' in due and name.endswith(('__load_fertilizer', '__apply_fertilizer', '__apply_fertigation', '__inspect_crop'))) or ('water_check' in due and name.endswith(('__read_water_sensors', '__get_root_zone_water', '__read_soil_sensor', '__read_soil_sensors', '__read_root_zone_sensors', '__get_forecast'))):
                    criteria[name] = '[DUE management: inspect readiness and continue the listed task] ' + criteria[name]
                    if name.endswith(('__load_fertilizer', '__apply_fertilizer', '__apply_fertigation')):
                        r = context['next_ridge_fertilizer_round']
                        if r:
                            criteria[name] += f' Current fertilizer round {r["index"]}: {sum(r["remaining_by_ridge_kg"].values()):g} kg product still required across {len(r["remaining_by_ridge_kg"])} ridges; older-round coverage is not completion.'
                        if name.endswith('__load_fertilizer'):
                            criteria[name] += ' Loading supplies the applicator; it is a prerequisite, not a field application.'
                        if name.endswith('__apply_fertigation') and plan.get('fertigation_carrier_zero'):
                            criteria[name] += ' Explicit task: adapter sets carrier water to zero; this route applies fertilizer without extra irrigation.'
                if name.startswith('SystemApp__') and name.endswith(('__wait_for_notification', '__advance_time')) and due:
                    criteria[name] = '[DEFER due work only for a real blocker; waiting does not finish it] ' + criteria[name]
            from fairy.agents.jev.model_view import fertilizer_reference
            reference=fertilizer_reference(context,self.time_manager.time() if self.time_manager is not None else self._facts.get('now'))
            if reference and reference['timing_status']=='UPCOMING_REFERENCE':
                for name in criteria:
                    if name.endswith(('__apply_fertilizer','__apply_fertigation')):
                        criteria[name]='[UPCOMING fertilizer reference: remaining quantity is future planning, not an instruction to apply now; assess actual crop need before deviating] '+criteria[name]
            # Probe acquisition clears a water-check window. It must not erase
            # a still-feasible, undelivered reference from the decision menu.
            from fairy.agents.jev.ridge_irrigation import target as irrigation_target
            for name in criteria:
                native=self.tools_map.get(name)
                target=irrigation_target(native,self._facts,context) if native else None
                if target:
                    criteria[name]=f'[DUE irrigation reference {target["reference_index"]}: acquired fresh root-zone evidence permits a target with {target["target_mm_per_ridge"]:g} mm reference remaining; assess weather and crop need; a sensor read is not watering] '+criteria[name]
        if context is not None:
            from fairy.agents.jev import temporal
            context['temporal_guidance']=temporal.build(getattr(self,'_snapshot_task',''),self._facts,self.time_manager.time() if self.time_manager is not None else self._facts.get('now'))
            criteria=temporal.criteria(criteria,context['temporal_guidance'])
            context['blocked_actions'] = reasons
        from fairy.agents.jev.establishment import report_allowed
        report_farm=self._snapshot.get('farm_now',{})
        report_crop=report_farm.get('farms') or report_farm.get('plots') or report_farm.get('crop',[])
        if REPORT_TOOL in criteria and not report_allowed(getattr(self,'_snapshot_task',''),self._facts,report_crop):
            criteria.pop(REPORT_TOOL)
            reasons[REPORT_TOOL]=['A report was already sent for this material crop/work state. Queries, charging and repeated non-improving resets do not require another report.']
        from fairy.agents.jev.establishment import summary as establishment_summary
        pending=establishment_summary(getattr(self,'_snapshot_task',''),self._facts)
        if pending and pending['pending_planting_ridges']:
            for name in criteria:
                if name.endswith(('__plant_seeds','__load_seeds')):
                    criteria[name]='[ESTABLISHMENT INCOMPLETE: finish the remaining prescribed targets or their seed prerequisite before routine inspection of established areas] '+criteria[name]
        from fairy.agents.jev.receipts import grain_state
        if DONE_OPTION in criteria and grain_state(self._facts)['unsafe_stored_batches']:
            criteria[DONE_OPTION] = 'Stop with an unresolved recorded unsafe-storage warning; this is not successful task completion. Report the warning.'
        self.record_event('jev_management_options', status='ok', version=management.VERSION,
                          excluded=reasons, done_allowed=DONE_OPTION in criteria)
        return criteria

    def _decide(self, state, skip_args_below=None):
        if not self._management_enabled():
            return self._decide_once(state, skip_args_below)
        from fairy.agents.jev.feasibility import ToolNotReady
        excluded=set()
        for _ in range(len(self.tool_menus)+1):
            try:
                return self._decide_once(state, skip_args_below, excluded=excluded)
            except ToolNotReady as exc:
                excluded.add(exc.tool)
                self.record_event('jev_tool_not_ready',status='local_constraint',tool_name=exc.tool,
                                  argument=exc.argument,selected_arguments=exc.arguments,reason=str(exc))
                state={**state,'local_constraints':{'unavailable_tools_this_decision':sorted(excluded),
                       'last_blocker':str(exc),'instruction':'Choose another feasible prerequisite or wait/recheck. No tool was executed.'}}
        raise ValueError('No feasible tool could be resolved within bounded local checks')

    def _decide_once(
        self, state: dict[str, Any], skip_args_below: float | None = None, excluded=None
    ) -> tuple[str, dict[str, Any] | None, dict[str, float]]:
        """Jev's tool and arguments; arguments are None when skip_args_below skipped them."""
        tool_question = {
            "type": "choice",
            "instructions": (TOOL_INSTRUCTIONS if self.enforced_tool_adaptor else BASELINE_TOOL_INSTRUCTIONS) if self.state_mode == "snapshot" else PART1_TOOL_INSTRUCTIONS,
            "criteria": {
                **{
                    name: menu.description
                    for name, menu in self.tool_menus.items()
                    if not (name == REPORT_TOOL and self._last_was_report())
                },
                DONE_OPTION: DONE_DESCRIPTION,
            },
        }
        tool_question['criteria'] = self._management_criteria(tool_question['criteria'])
        for unavailable in excluded or ():
            tool_question['criteria'].pop(unavailable,None)
        if not tool_question['criteria']:
            raise ValueError('No legal next action remains after local feasibility checks')
        if self._management_enabled():
            from fairy.agents.jev.decision_context import INSTRUCTIONS
            tool_question['instructions'] = INSTRUCTIONS
        questions: dict[str, dict[str, Any]] = {TOOL_QUESTION_ID: tool_question}
        prepared: dict[str, dict[str, tuple[str, dict[str, Any]]]] = {}
        for name in ([] if self._management_enabled() else self._likely_tools(tool_question["criteria"])):
            arg_questions, candidate = self._value_questions(self.tool_menus[name], name)
            if self._management_enabled() and any(not q['criteria'] for q in arg_questions.values()):
                self.record_event('jev_speculative_arguments_skipped',status='empty_candidates',tool_name=name,
                    reason='No currently legal argument candidate; do not send an empty Choice for an unselected tool.')
                continue
            prepared[name] = candidate
            questions.update(arg_questions)
        if self._management_enabled() and self._state_chars:
            self._state_chars[-1] = len(json.dumps(state, default=str, ensure_ascii=False))
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
        if not self.enforced_tool_adaptor:
            return BaselineParameters._jev_arguments(self, state, pick, options, answers)
        menu = self.tool_menus[pick]
        if dependent_menu(self.tools_map[pick], enforced_tool_adaptor=self.enforced_tool_adaptor) or self._uses_managed_values(menu):
            arguments, confidences = self._dependent_values(menu, state)
            self._validate_ridge_ranges(menu, arguments)
            return arguments, confidences
        if options is not None:
            self._fanout["hits"] += 1
        else:
            self._fanout["misses"] += 1
            arg_questions, options = self._value_questions(menu)
            if self._management_enabled() and any(not q['criteria'] for q in arg_questions.values()):
                from fairy.agents.jev.feasibility import ToolNotReady
                raise ToolNotReady(menu.tool_name,'arguments',{})
            answers = self._ask("arguments", state, arg_questions)
        arguments, confidences = self._read_values(menu, options, answers)
        # Start and unrelated arguments may be pre-requested together. The end
        # depends on the selected start, so it must be a subsequent question.
        for arg in self._range_ends(menu):
            start_name = RANGE_END_TO_START[arg.name]
            opts = self._range_options(menu, arguments, start_name)
            if self._management_enabled() and not opts:
                from fairy.agents.jev.feasibility import ToolNotReady
                raise ToolNotReady(menu.tool_name,arg.name,arguments)
            qid = _arg_question_id(arg.name, None)
            question = {
                "type": "choice",
                "instructions": self._arg_instructions(menu, arg, count_from=start_name)
                    + " Selected arguments: " + json.dumps(arguments),
                "criteria": {k: None for k in opts},
            }
            answer = self._ask("arguments", state, {qid: question})[qid]
            arguments[arg.name] = opts[answer["choice"]]
            confidences[qid] = answer["confidence"]
        self._validate_ridge_ranges(menu, arguments)
        return arguments, confidences

    @staticmethod
    def _range_ends(menu: ToolMenu):
        names = {a.name for a in menu.args}
        return [a for a in menu.args if RANGE_END_TO_START.get(a.name) in names]

    def _range_options(self, menu: ToolMenu, arguments: dict[str, Any], start_name: str):
        """Public boundary/pass limits plus opt-in dose/battery arithmetic; no hidden maturity or weather reads."""
        native = self.tools_map[menu.tool_name]
        world = scene_world(native, arguments)
        size = getattr(world, "num_ridges", self._num_ridges)
        start = arguments[start_name]
        if type(start) is not int or not 0 <= start < size:
            raise ValueError(f"Invalid ridge start for {menu.tool_name}: {start!r} (size {size})")
        width = min(self._menu_width(menu, arguments), size - start)
        if self._management_enabled() and tool_family(native) == 'RobotApp' and native.name in ('inspect_emergence','inspect_pests','inspect_crop_health'):
            battery = self._facts.get('machines',{}).get(native.class_instance.name,{}).get('battery_pct')
            if management.number(battery) is not None:
                width = min(width,8,max(0,int((battery-10.)//5.)))
        if self._uses_managed_values(menu) and native.name in ('apply_fertilizer', 'apply_fertigation'):
            current = self._management['next_ridge_fertilizer_round']
            if current:
                needs = current['remaining_by_ridge_kg']
                dose = needs.get(start)
                if dose is not None:
                    resources = management.fertilizer_resources(native, self._facts)
                    if resources:
                        available = resources['available_kg']
                        if resources['remaining_quota_kg'] is not None:
                            available = min(available, resources['remaining_quota_kg'])
                        width = min(width, math.floor((available+management.EPS)/dose))
                    for offset in range(width):
                        if abs(needs.get(start+offset, -1.)-dose) > management.EPS:
                            width = offset
                            break
        if self._management_enabled():
            from fairy.agents.jev.establishment import range_width
            width=range_width(native,arguments,getattr(self,'_snapshot_task',''),self._facts,width)
        return {_count_key(n): start + n - 1 for n in range(1, width + 1)}

    def _validate_ridge_ranges(self, menu: ToolMenu, arguments: dict[str, Any]):
        """Fail closed on an adapter invariant violation; never clamp a choice."""
        for arg in self._range_ends(menu):
            valid = self._range_options(menu, arguments, RANGE_END_TO_START[arg.name])
            end = arguments.get(arg.name)
            if type(end) is not int or end not in valid.values():
                raise ValueError(f"Invalid adapted ridge range for {menu.tool_name}: {arguments!r}")

    def _likely_tools(self, offered: dict[str, Any]) -> list[str]:
        """Tools with arguments that Jev ranked high last time or used in the last few actions."""
        ranked = sorted(self._last_tool_probabilities.items(), key=lambda kv: -kv[1])
        likely = [n for n, p in ranked[:LIKELY_TOP_TOOLS] if p >= LIKELY_MIN_PROBABILITY]
        recent = [s.tool_name for s in self._facts.get("steps", [])[-LIKELY_RECENT_ACTIONS:]]
        out: list[str] = []
        for name in likely + recent[::-1]:
            if name in offered and name in self.tool_menus and self.tool_menus[name].args and name not in out and not dependent_menu(self.tools_map[name], enforced_tool_adaptor=self.enforced_tool_adaptor) and not self._uses_managed_values(self.tool_menus[name]):
                out.append(name)
        return out

    def _value_questions(
        self, menu: ToolMenu, tool_key: str | None = None
    ) -> tuple[dict[str, dict[str, Any]], dict[str, tuple[str, dict[str, Any]]]]:
        """One question per argument, none depending on another's answer.

        Range ends are omitted until the start has been selected. Returns the
        questions and, per independent argument, its question id and options.
        """
        if not self.enforced_tool_adaptor:
            return BaselineParameters._value_questions(self, menu, tool_key)
        names = {a.name for a in menu.args}
        questions: dict[str, dict[str, Any]] = {}
        options: dict[str, tuple[str, dict[str, Any]]] = {}
        for a in menu.args:
            qid = _arg_question_id(a.name, tool_key)
            count_from = RANGE_END_TO_START.get(a.name) if RANGE_END_TO_START.get(a.name) in names else None
            if count_from:
                continue
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

    def _menu_width(self, menu: ToolMenu, arguments: dict[str, Any] | None = None) -> int:
        if not self.enforced_tool_adaptor:
            return BaselineParameters._menu_width(self, menu)
        native = self.tools_map[menu.tool_name]
        if extended_scene_tool(native):
            if tool_family(native) == "ManualOpsApp":
                return 2
            from fairy.agents.jev.menu import canonical_tool
            if (canonical_tool(native).class_name if self._management_enabled() else native.class_name) in ("SharedTractorApp", "TractorService"):
                return PASS_WIDTH.get(("TractorApp", native.name), self._num_ridges)
            world = scene_world(native, arguments)
            return PASS_WIDTH.get((tool_family(native), native.name), getattr(world, "num_ridges", self._num_ridges))
        return PASS_WIDTH.get(tuple(menu.tool_name.split("__", 1))) or self._num_ridges

    def _dependent_values(self, menu: ToolMenu, state: dict[str, Any]):
        """Same Choice/value mapping, resolving entity selectors before dependants."""
        if not self.enforced_tool_adaptor:
            return BaselineParameters._dependent_values(self, menu, state)
        native = self.tools_map[menu.tool_name]
        arguments, confidences = {}, {}
        scope_order = {"farm_id": 0, "asset_id": 1, "plot_id": 2, "machine_id": 2, "seed_type": 2, "crop_id": 2, "offer_id": 2}
        if self._management_enabled() and native.name in ('plant_seeds','replant_seeds'):
            scope_order['start_ridge']=2
        ends = self._range_ends(menu)
        args = sorted(menu.args, key=lambda a: (scope_order.get(a.name, 4 if a in ends else 5 if a.name in {'kg', 'kg_per_ha', 'kg_per_ridge', 'total_kg', 'nutrient_amount', 'water_mm', 'hours', 'duration_hours'} else 3), a.name == "batch_id"))
        for arg in args:
            if self._management_enabled() and self._management:
                from fairy.agents.jev import ridge_irrigation
                irrigation_target = ridge_irrigation.target(native,self._facts,self._management)
                if irrigation_target and arg.name in irrigation_target['arguments']:
                    value=irrigation_target['arguments'][arg.name]
                    arguments[arg.name]=value
                    self._derived_management_arguments+=1
                    self.record_event('jev_derived_argument',status='ok',tool_name=menu.tool_name,
                        argument=arg.name,value=value,source=ridge_irrigation.VERSION,
                        reference_index=irrigation_target['reference_index'],reference_day=irrigation_target['reference_day'],
                        reason=irrigation_target['reason'])
                    continue
                derived = management.derive_fertilizer(native, arg.name, arguments,
                    self._management['plan'], self._management['ledger'], self._facts)
                if derived is None and native.name=='load_seeds' and arg.name=='count':
                    from fairy.agents.jev.establishment import load_amount
                    derived=load_amount(native,arguments.get('seed_type'),str(state.get('task','')),self._facts)
                if derived is None:
                    from fairy.agents.jev.constraints import derive_transfer
                    derived = derive_transfer(native,arg.name,arguments,self._facts)
                if derived is None and tool_family(native) == 'PaddyOpsApp':
                    from fairy.agents.jev.observations import derive_water
                    derived = derive_water(native,arg.name,arguments,str(state.get('task','')),self._facts,self._facts.get('now',0.))
                if derived is not None:
                    value, reason = derived
                    arguments[arg.name] = value
                    self._derived_management_arguments += 1
                    self.record_event('jev_derived_argument', status='ok', tool_name=menu.tool_name,
                        argument=arg.name, value=value, source=management.VERSION, reason=reason)
                    continue
            if tool_family(native) == "TractorApp" and native.name == "load_seeds" and arg.name == "count":
                from fairy.agents.jev.seed_candidates import seed_amount_hint
                from fairy.apps.farm_world import tractor_app as tractor_constants
                machine = self._facts.get("machines", {}).get(native.class_instance.name, {})
                amount, reason = seed_amount_hint(
                    scene_world(native), arguments.get("seed_type"), str(state.get("task", "")),
                    self._facts.get("steps", []), tractor_constants._SEED_HOPPER_MAX_PLANTS,
                    snapshot={"machine": machine, "inventory": self._facts.get("inventory", {}),
                              "ridges": self._facts.get("ridges", [])})
                if amount is not None:
                    arguments["count"] = amount
                    self.record_event("jev_derived_argument", tool_name=menu.tool_name,
                                      argument="count", value=amount, source="task_seed_demand_v1",
                                      reason=reason)
                    continue
            scoped = None
            opts = self._arg_options(menu, arg, arguments)
            from fairy.agents.jev.entities import dependent as entity_dependent
            if arg.name in ("water_mm", "quantity", "liters", "count", "kg") or (self._management_enabled() and entity_dependent(native)):
                raw_arg = next(a for a in native.args if a.name == arg.name)
                scoped = build_arg_menu(native, raw_arg,
                    descriptions=arg_descriptions(native.function_description),
                    numbers=task_numbers(str(state.get("task", ""))), num_ridges=self._num_ridges,
                    arguments=arguments, steps=self._facts.get("steps", []), task_text=str(state.get("task", "")),
                    enforced_tool_adaptor=self.enforced_tool_adaptor)
                opts = scoped.options
                if self._management_enabled() and self._management and tool_family(native) == 'PaddyOpsApp' and native.name == 'irrigate' and arg.name == 'water_mm':
                    pid = arguments.get('plot_id')
                    caps = [c['max_delivery_mm_by_plot'][pid] for c in self._management['canal_limits'] if pid in c['max_delivery_mm_by_plot']]
                    if caps:
                        cap = max(caps)
                        opts = {k:v for k,v in opts.items() if management.number(v) is not None and 0 < v <= cap+management.EPS}
                        if cap > management.EPS:
                            # Round down: a rounded-up volume can exceed the closing instant.
                            safe = math.floor(cap*1e6)/1e6
                            if safe > 0:
                                opts[f'{safe:g} mm fits current canal window'] = safe
                if self._management_enabled() and native.name == 'load_fertilizer' and arg.name == 'kg':
                    resources = management.fertilizer_resources(native, self._facts)
                    if resources:
                        opts = {k:v for k,v in opts.items() if management.number(v) is not None and 0 < v <= resources['load_limit_kg']+management.EPS}
                        if resources['load_limit_kg'] > management.EPS:
                            opts[f"{resources['load_limit_kg']:g} kg available load space"] = resources['load_limit_kg']
            if self._management_enabled():
                opts = legal_options(native, arg, opts, arguments, self._facts)
                from fairy.agents.jev.establishment import options as establishment_options
                opts=establishment_options(native,arg.name,opts,arguments,str(state.get('task','')),self._facts)
            count_from = RANGE_END_TO_START.get(arg.name)
            runtime = getattr(native.class_instance, "runtime", None)
            if runtime is not None and arg.name == "asset_id" and arguments.get("farm_id"):
                opts = {k: v for k, v in opts.items() if v is None or arguments["farm_id"] in runtime.assets[v].spec.allowed_farm_ids}
            if runtime is not None and arguments.get("farm_id"):
                from types import SimpleNamespace
                world = runtime.farms[arguments["farm_id"]].farm
                asset = runtime.assets.get(arguments.get("asset_id"))
                caps = runtime.capabilities(SimpleNamespace(farm=world, farm_id=arguments["farm_id"], asset=asset, asset_id=arguments.get("asset_id")))
                if arg.name == "seed_type":
                    opts = {k: v for k, v in opts.items() if v in caps["planting"]["compatible_seed_types"]}
                if arg.name == "depth_cm":
                    lo, hi = caps["planting"]["depth_cm_range"]
                    opts = {**{f"{round(lo+(hi-lo)*i/9,3):g}": round(lo+(hi-lo)*i/9,3) for i in range(10)}, **opts}
            if count_from in arguments:
                opts = self._range_options(menu, arguments, count_from)
            if native.name == "measure_grain_moisture":
                if arg.name == "plot_id":
                    batches = next(a for a in menu.args if a.name == "batch_id").options
                    if not any(v is not None for v in batches.values()):
                        opts = {k: v for k, v in opts.items() if v is not None}
                elif arg.name == "batch_id":
                    opts = {k: v for k, v in opts.items() if (v is None) == (arguments.get("plot_id") is not None)}
            if not opts and self._management_enabled():
                from fairy.agents.jev.feasibility import ToolNotReady
                raise ToolNotReady(menu.tool_name,arg.name,arguments)
            if not opts or len(opts) > MAX_CHOICE_OPTIONS:
                raise ValueError(f"Invalid dependent menu: {menu.tool_name}.{arg.name}")
            if self._uses_managed_values(menu) and len(opts) == 1:
                value = next(iter(opts.values()))
                arguments[arg.name] = value
                self._derived_management_arguments += 1
                self.record_event('jev_derived_argument', status='ok', tool_name=menu.tool_name,
                    argument=arg.name, value=value, source=management.VERSION,
                    reason='Only one value in the current explicit task/native schema scope; no model choice is needed.')
                continue
            qid = _arg_question_id(arg.name, None)
            question = {"type": "choice", "instructions": self._arg_instructions(menu, arg, count_from=count_from if count_from in arguments else None),
                        "criteria": {k: None for k in opts}}
            if self._management_enabled():
                from fairy.agents.jev.operation_clock import annotation
                for key,value in opts.items():
                    preview=annotation(native,{**arguments,arg.name:value},self._facts,self._management)
                    if preview: question['criteria'][key]=json.dumps(preview,ensure_ascii=False)

            if scoped is not None and scoped.description:
                question["instructions"] += " " + scoped.description
            # Include selected scope in the question, not hidden simulator facts.
            question["instructions"] += " Selected arguments: " + json.dumps(arguments)
            answer = self._ask("arguments", state, {qid: question})[qid]
            arguments[arg.name] = opts[answer["choice"]]
            confidences[qid] = answer["confidence"]
        return arguments, confidences

    def _read_values(
        self,
        menu: ToolMenu,
        options: dict[str, tuple[str, dict[str, Any]]],
        answers: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, float]]:
        if not self.enforced_tool_adaptor:
            return BaselineParameters._read_values(self, menu, options, answers)
        ends = self._range_ends(menu)
        arguments: dict[str, Any] = {}
        confidences: dict[str, float] = {}
        for a in [a for a in menu.args if a not in ends]:
            qid, opts = options[a.name]
            answer = answers[qid]
            value = opts[answer["choice"]]
            confidences[qid] = answer["confidence"]
            if a.name == DURATION_ARG:
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
        return all(_failed(s) for s in steps) or _result_data(steps[0].content) == _result_data(steps[1].content)

    def _llm_decide(
        self, state: dict[str, Any], reason: str, fill_tool: str | None = None
    ) -> tuple[str, dict[str, Any]] | None:
        """One decision by the fallback LLM; None keeps Jev's choice (LLM error or unknown tool).

        With fill_tool the LLM sees only that tool's schema and picks its arguments;
        any other answer (no call, another tool) is None.
        """
        self._request_serial += 1
        self._active_request_id = f"request_{self._request_serial}"
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
            provider=getattr(self.fallback_llm, "provider", None),
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
                wall_time_seconds=round(time.perf_counter() - started, 6),
                error_type=type(exc).__name__,
                error_message="Fallback request failed; inspect the service separately",
                status_code=getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None),
            )
            self.messages.runtime_metrics.append({"role": "assistant", "source": "llm_fallback",
                "accepted": False, "time": time.perf_counter() - started,
                "tokens": {k: None for k in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens")}})
            if getattr(self, "strict_qwen", False):
                raise RuntimeError("Qwen service request failed") from None
            return None
        latency = round(time.perf_counter() - started, 6)
        usage = getattr(response, "usage", None)
        details = getattr(usage, "prompt_tokens_details", None)
        tokens = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "cached_tokens": getattr(details, "cached_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
        }
        tokens["total_tokens"] = (tokens["prompt_tokens"] + tokens["completion_tokens"]
                                 if tokens["prompt_tokens"] is not None and tokens["completion_tokens"] is not None else None)
        for k in self._llm_tokens:
            self._llm_tokens[k] = (self._llm_tokens[k] + tokens[k]
                                   if self._llm_tokens[k] is not None and tokens[k] is not None else None)
        self.messages.runtime_metrics.append(
            {"role": "assistant", "time": latency, "accepted": True, "tokens": tokens, "source": "llm_fallback",
             "logical_action_id": f"action_{self._logical_turn}", "logical_request_id": self._active_request_id}
        )
        message = response.choices[0].message if response.choices else None
        calls = list(getattr(message, "tool_calls", None) or [])
        invalid_shape = getattr(self, "strict_qwen", False) and (len(response.choices) != 1 or len(calls) > 1)
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
        if getattr(self, "strict_qwen", False):
            invalid_done = not calls and str(getattr(message, "content", "") or "").strip().lower() != DONE_OPTION
            if invalid_shape or invalid_done or decided is None:
                self.messages.runtime_metrics[-1]["accepted"] = False
                self.record_event("llm_fallback_end", status="rejected", reason=reason,
                    wall_time_seconds=latency, tokens=tokens, model_version=getattr(response, "model", None),
                    error_type="InvalidQwenResponse")
                raise ValueError("Qwen must return exactly one valid tool call or explicit done")
        if decided is not None and self.state_mode == "snapshot" and self.qwen_context_policy == "bounded_history":
            self._remember_llm_turn(messages[-1]["content"], decided)
        self.record_event(
            "llm_fallback_end",
            status="ok" if decided else "rejected",
            reason=reason,
            fill_tool=fill_tool,
            wall_time_seconds=latency,
            provider=getattr(self.fallback_llm, "provider", None),
            model=getattr(self.fallback_llm, "model", None),
            model_version=getattr(response, "model", None),
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
        if self.qwen_context_policy == "snapshot_only":
            return [{"role": "system", "content": system},
                    {"role": "user", "content": FALLBACK_INSTRUCTIONS + fill + "\n\n" + json.dumps(state, ensure_ascii=False, default=str)}]
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
            if self._management_enabled():
                from fairy.agents.jev.observations import chinese_durations
                for unit,value in chinese_durations(getattr(self,'_snapshot_task','')):
                    seconds = value * {'days':86400,'hours':3600,'minutes':60,'seconds':1}[unit]
                    if seconds > 0:
                        options[f'{value:g} {unit} from explicit task'] = {'seconds':seconds} if arg.name == DURATION_ARG else seconds
            for p in self._facts.get("pending", []):
                secs = p["seconds_left"]
                key = f"until {p['from_action']} is ready ({_readable_seconds(secs)})"
                options[key] = {"seconds": secs} if arg.name == DURATION_ARG else secs
            if self._management_enabled() and self._management:
                limit = self._management['wait_limit_seconds']
                # A charged device may remain idle. Keep charge-ready as an
                # optional wake-up, not a mandatory farm-wide deadline.
                pending = [p['seconds_left'] for p in self._facts.get('pending', []) if p.get('seconds_left', 0) > 0
                           and p.get('from_action','').split('__')[-1]!='charge']
                if pending:
                    limit = min([limit, *pending]) if limit is not None else min(pending)
                if limit is not None and limit > 0:
                    def seconds(value):
                        return sum(management.number(v) * {'days':86400, 'hours':3600, 'minutes':60, 'seconds':1}.get(k,0) for k,v in value.items()) if isinstance(value,dict) else management.number(value)
                    options = {k:v for k,v in options.items() if seconds(v) is not None and 0 < seconds(v) <= limit+management.EPS}
                    has_due = any(w['at'] <= self.time_manager.time() for w in self._management['windows'])
                    label = 'defer blocked due work; recheck within ' if has_due else 'until next task check '
                    options[label + '(' + _readable_seconds(limit) + ')'] = {'seconds':limit} if arg.name == DURATION_ARG else limit
            if self._management_enabled():
                from fairy.agents.jev.temporal import wait_options
                options=wait_options(options,bool(self._management and self._management.get('temporal_guidance',{}).get('observation_loop_pressure')))
            return options
        native = self.tools_map[menu.tool_name]
        if self._management_enabled():
            options = legal_options(native, arg, options, arguments, self._facts)
            from fairy.agents.jev.establishment import options as establishment_options
            options=establishment_options(native,arg.name,options,arguments,getattr(self,'_snapshot_task',''),self._facts)
            resources = management.fertilizer_resources(native, self._facts)
            if resources and native.name == 'load_fertilizer' and arg.name == 'kg':
                options = {k:v for k,v in options.items() if management.number(v) is not None and 0 < v <= resources['load_limit_kg']+management.EPS}
                if resources['load_limit_kg'] > management.EPS:
                    options[f"{resources['load_limit_kg']:g} kg available load space"] = resources['load_limit_kg']
            if self._management:
                if tool_family(native) == 'PaddyOpsApp' and native.name == 'irrigate' and arg.name == 'plot_id' and self._management['canal_limits']:
                    feasible = {pid for c in self._management['canal_limits'] for pid,depth in c['max_delivery_mm_by_plot'].items() if depth > management.EPS}
                    options = {k:v for k,v in options.items() if v in feasible}
                if native.name == 'apply_fertilizer' and tool_family(native) == 'PaddyOpsApp' and arg.name == 'plot_id' and self._management['plan']['kind'] == 'paddy':
                    feasible = set()
                    for plot in self._facts.get('plots', []):
                        r = management.paddy_round(self._management['plan'], self._management['ledger'], plot['plot_id'])
                        if r and not plot.get('harvested') and resources and r['remaining_kg_ha']*plot['area_m2']/10000 <= resources['carried_kg']+management.EPS:
                            feasible.add(plot['plot_id'])
                    options = {k:v for k,v in options.items() if v in feasible}
                if self._uses_managed_values(menu) and native.name in ('apply_fertilizer', 'apply_fertigation') and arg.name == 'start_ridge':
                    current = self._management['next_ridge_fertilizer_round']
                    if current:
                        available = resources['available_kg'] if resources else float('inf')
                        if resources and resources['remaining_quota_kg'] is not None:
                            available = min(available, resources['remaining_quota_kg'])
                        options = {k:v for k,v in options.items() if current['remaining_by_ridge_kg'].get(v, float('inf')) <= available+management.EPS}
        if extended_scene_tool(native) and arg.name in ("ridge_id", "start", "end", "start_ridge", "end_ridge"):
            world = scene_world(native, arguments)
            if hasattr(world, "_ridges"):
                options = {k: v for k, v in options.items() if 0 <= v < world.num_ridges}
                keep = RIDGE_FILTERS.get("TractorApp__" + native.name)
                if keep:
                    eligible = {r.ridge_id for r in world._ridges if keep({"planted": r.planted, "harvested": r.harvested})}
                    narrowed = {k: v for k, v in options.items() if v in eligible}
                    options = narrowed or options
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
        if self._management_enabled():
            from fairy.agents.jev.completion import problems
            return problems(task,self._facts,self.tools_map)
        return done_problems(task, self._facts, self.tools_map)

    def _report_text(self) -> str:
        farm = self._snapshot.get("farm_now", {})
        lines = [
            f"Farm agent report ({farm.get('time')}).",
            "Actions this run: " + json.dumps(farm.get("actions_this_run", {}), ensure_ascii=False),
            "Crop now: " + json.dumps(farm.get("farms") or farm.get("plots") or farm.get("crop", []), ensure_ascii=False),
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
            self._toolsets, self.workflow, self.time_manager.time(), enhanced_tool_adaptor=self._management_enabled()
        )
        if self._management_enabled():
            from fairy.agents.jev.receipts import enhance_snapshot
            self._facts['now'] = self.time_manager.time()
            self._snapshot = enhance_snapshot(self._snapshot, self._facts)
        if any(extended_scene_tool(t) for t in self.tools_map.values()):
            # Dynamic entities (especially grain batches) can appear after a tool.
            self._menu_unavailable=[]
            self.tool_menus = build_tool_menus(self.tools_map, task_text=str(task), num_ridges=self._num_ridges,
                                              steps=self._facts.get("steps", []), enforced_tool_adaptor=self.enforced_tool_adaptor,
                                              diagnostics=self._menu_unavailable if self._management_enabled() else None)
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
        # Enhanced policy is opt-in and independent of scenario detail.
        # Keep the original task intact: it also feeds task-derived value menus.
        if self.enforced_tool_adaptor:
            state["jev_execution_guidance"] = execution_guidance()
        self._snapshot_task = str(task)
        if self._management_enabled():
            self._management = management.management_context(str(task), self._facts, self.time_manager.time(), self._num_ridges)
            from fairy.agents.jev.establishment import summary as establishment_summary
            establishment=establishment_summary(str(task),self._facts)
            if establishment:
                self._management['establishment']=establishment
                phase=establishment.get('next_planting_phase')
                if phase and phase.get('seconds_until') is not None and phase['seconds_until']>0:
                    self._management['windows'].append(dict(kind='planting',target='explicit next zone',at=phase['at'],status='UPCOMING',seconds_until=phase['seconds_until']))
                    self._management['windows'].sort(key=lambda w:w['at'])
                    old_limit=self._management['wait_limit_seconds']
                    self._management['wait_limit_seconds']=min(old_limit,phase['seconds_until']) if old_limit is not None else phase['seconds_until']
            from fairy.agents.jev import ridge_irrigation
            self._management['ridge_irrigation'] = ridge_irrigation.build(str(task),self._facts,self._management,self.time_manager.time())
            from fairy.agents.jev import temporal
            self._management['temporal_guidance']=temporal.build(str(task),self._facts,self.time_manager.time())
            self._management['tool_discovery_prerequisites']=[d for d in getattr(self,'_menu_unavailable',[]) if d['reason']=='requires_observation']
            self._management['completion_allowed'] = not bool(self._done_problems(str(task)))
            self._management['remaining_requirements'] = self._done_problems(str(task))
            from fairy.agents.jev.receipts import grain_state, paddy_batches
            self._management['grain_batches'] = paddy_batches(self._facts)
            if self._facts.get('plots'):
                self._management['shared_clock_note'] = 'Waiting and long operations advance every plot together. Use fresh preparation_wet_hours; do not repeat a separate full soak just because switching plots.'
            self._management['postharvest'] = grain_state(self._facts)
            from fairy.agents.jev.observations import water_targets, weather_evidence
            self._management['weather_evidence'] = weather_evidence(self._facts,self.time_manager.time())
            self._management['water_observations'] = water_targets(str(task),self._facts,self.time_manager.time())
            state['management_progress'] = self._management
            from fairy.agents.jev.decision_context import present
            state = present(state, self._facts, self._management, self.time_manager.time())
        if self._notes:
            state["notes"] = list(self._notes)
        self._state_chars.append(len(json.dumps(state, default=str, ensure_ascii=False)))
        return state

    def _ask(
        self, kind: str, state: dict[str, Any], questions: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        self._request_serial += 1
        self._active_request_id = f"request_{self._request_serial}"
        if self._management_enabled():
            from fairy.agents.jev.model_view import request_guard, compact, ContextBudgetError
            if self._management and 'management_progress' in state:
                state = {**state, 'management_progress': {**state['management_progress'],
                    'blocked_actions': compact(self._management.get('blocked_actions', {})),
                    'temporal_guidance': compact(self._management.get('temporal_guidance', {}))}}
            try:
                state, budget = request_guard(state, questions, getattr(self.llm, 'model', None))
            except ContextBudgetError as exc:
                self.record_event('jev_context_budget', status='blocked_before_network', **{k:v for k,v in exc.budget.items() if k!='status'})
                raise
            self.record_event('jev_context_budget', **budget)
            if self._state_chars:
                self._state_chars[-1] = len(json.dumps(state, default=str, ensure_ascii=False))
        option_counts = {qid: len(q["criteria"]) for qid, q in questions.items()}
        self.record_event(
            "jev_request_start",
            status="running",
            request_kind=kind,
            model=getattr(self.llm, "model", None),
            provider=getattr(self.llm, "provider", None),
            option_counts=option_counts,
            questions=questions,
            state=state,
        )
        started = time.perf_counter()
        try:
            raw = self.llm.system_one(state, questions)
            response = normalize_response(raw, questions)
            # SDK and legacy clients represent one request. The HTTP adapter already
            # carries physical batches (possibly zero for all-singleton questions).
            if not response.batches and not all(a.deterministic for a in response.choices.values()):
                response.batches = [DecisionBatch(
                    list(questions), response.usage, response.model, response.request_id,
                    round(time.perf_counter() - started, 6),
                )]
            self._record_decision_batches(response.batches)
            if self.confidence_source == "provider" and any(a.confidence is None for a in response.choices.values()):
                raise DecisionProtocolError("service omitted confidence; configure max_probability explicitly to use probabilities")
        except Exception as exc:
            error_batches = list(getattr(exc, "completed_batches", []))
            failed_batch = getattr(exc, "failed_batch", None)
            if failed_batch is not None:
                error_batches.append(failed_batch)
            self._record_decision_batches(error_batches)
            self.record_event(
                "jev_request_error",
                status="error",
                request_kind=kind,
                wall_time_seconds=round(time.perf_counter() - started, 6),
                error_type=type(exc).__name__,
                error_message=(str(exc) if isinstance(exc, DecisionProtocolError)
                               else "Decision request failed; inspect status_code and error_type"),
                status_code=getattr(exc, "status_code", None),
                completed_batches=len(getattr(exc, "completed_batches", [])),
                batches=[{"question_ids": b.question_ids, "status": b.status,
                          "model": b.model, "request_id": b.request_id,
                          "tokens": b.usage.tokens(), "wall_time_seconds": b.wall_time_seconds}
                         for b in error_batches],
            )
            raise
        latency = round(time.perf_counter() - started, 6)
        self._jev_request_count += 1

        answers: dict[str, dict[str, Any]] = {}
        for qid in questions:
            answer = response.choices[qid]
            routing_confidence = (answer.confidence if self.confidence_source == "provider"
                                  else max(answer.probabilities.values()))
            answers[qid] = {
                "choice": answer.choice,
                "confidence": routing_confidence,
                "provider_confidence": answer.confidence,
                "confidence_source": self.confidence_source,
                "probabilities": dict(answer.probabilities),
                "deterministic": answer.deterministic,
            }
        self._deterministic_questions += sum(a.deterministic for a in response.choices.values())
        if TOOL_QUESTION_ID in response.choices:
            self._last_tool_deterministic = response.choices[TOOL_QUESTION_ID].deterministic
        tokens = response.usage.tokens()
        self.record_event(
            "jev_request_end",
            status="ok",
            request_kind=kind,
            provider=getattr(self.llm, "provider", None),
            model=getattr(self.llm, "model", None),
            model_version=getattr(response, "model", None),
            request_id=getattr(response, "request_id", None),
            wall_time_seconds=latency,
            option_counts=option_counts,
            answers=answers,
            tokens=tokens,
            http_request_count=len(response.batches),
            batches=[{
                "question_ids": b.question_ids, "model": b.model, "request_id": b.request_id,
                "tokens": b.usage.tokens(), "wall_time_seconds": b.wall_time_seconds, "status": b.status,
            } for b in response.batches],
        )
        return answers

    def _record_decision_batches(self, batches: list[DecisionBatch]) -> None:
        for batch in batches:
            self._decision_http_requests += 1
            self._decision_input_known += batch.usage.input_tokens or 0
            if any(v is None for v in batch.usage.tokens().values()):
                self._decision_usage_missing = True
            if batch.usage.input_tokens is None or self._jev_tokens is None:
                self._jev_tokens = None
            else:
                self._jev_tokens = self._decision_input_known
            self.messages.runtime_metrics.append({
                "role": "assistant", "time": batch.wall_time_seconds, "accepted": batch.status == "ok",
                "tokens": batch.usage.tokens(), "source": "jev",
                "provider": getattr(self.llm, "provider", None),
                "model": batch.model, "request_id": batch.request_id,
                "logical_action_id": f"action_{self._logical_turn}", "logical_request_id": self._active_request_id,
            })
