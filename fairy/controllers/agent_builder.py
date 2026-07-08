from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fairy.agents.agent.agent import Agent
from fairy.agents.agent.base_agent import CST
from fairy.controllers.app_agent import FinalAnswerApp
from fairy.controllers.agent_config import (
    AgentConfigBuilder as ControllerConfigBuilder,
    AppAgentConfig,
    AppAgentConfigBuilder,
    ControllerAgentConfig,
    FARM_WORLD_FUNCTION_CALL_SYSTEM_PROMPT,
    ResearchAgentProfileConfig,
)
from fairy.controllers.research_strategies import (
    ResearchStrategyCoordinator,
    StrategyLogSnapshot,
)
from fairy.controllers.skill_library import DynamicSkillLibrary


FARM_AGENT_HIDDEN_TOOL_NAMES = frozenset({"AgentUserInterface__send_message_to_agent"})


CONTROLLER_FAMILIES = [
    "default",
    "farm_world",
    "farm_baseline_react",
    "farm_planner_executor",
    "farm_reflective_memory",
    "farm_multi_specialist",
    "farm_adaptive_verifier",
    "farm_rewoo_modular",
    "farm_tree_search",
    "farm_critic_refiner",
    "farm_graph_memory",
]


DEFAULT_FARM_SYSTEM_MESSAGE = FARM_WORLD_FUNCTION_CALL_SYSTEM_PROMPT


class ResearchARESimulationAgent(Agent):
    """FAIRY function-call port of ARE's FARM research controller wrapper."""

    def __init__(
        self,
        name: str,
        llm: Any,
        controller_profile: ResearchAgentProfileConfig,
        system_message: str = DEFAULT_FARM_SYSTEM_MESSAGE,
        messages: Any = None,
        toolsets: list[Any] | None = None,
    ) -> None:
        super().__init__(
            name=name,
            llm=llm,
            system_message=system_message,
            messages=messages,
            toolsets=toolsets,
            hidden_tool_names=FARM_AGENT_HIDDEN_TOOL_NAMES,
        )
        self.controller_profile = controller_profile
        self.reflection_memory: list[str] = []
        self.telemetry: dict[str, object] = {}
        self._strategy = ResearchStrategyCoordinator(controller_profile)
        self._skill_library: DynamicSkillLibrary | None = None
        self._initialize_skill_library()
        self._reset_research_state()

    def _initialize_skill_library(self) -> None:
        if not self.controller_profile.skills.enabled:
            return
        library_path = self.controller_profile.skills.library_path
        if not library_path:
            return
        path = Path(library_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        self._skill_library = DynamicSkillLibrary(path)

    def _reset_research_state(self) -> None:
        self.reflection_memory = []
        self.telemetry = {
            "family_id": self.controller_profile.family_id,
            "planning_mode": self.controller_profile.planning_mode,
            "tool_calls": 0,
            "llm_calls": 0,
            "replan_signals": 0,
            "reflection_signals": 0,
            "memory_writes": 0,
            "memory_reads": 0,
            "skill_hits": 0,
            "delegation_signals": 0,
            "verification_signals": 0,
            "error_count": 0,
            "retrieved_skill_ids": [],
        }
        self._strategy.reset(self.telemetry)

    def _append_reflection(self, text: str) -> None:
        if not self.controller_profile.reflection.enabled:
            return
        content = text.strip()
        if not content:
            return
        self.reflection_memory.append(content)
        max_items = max(1, self.controller_profile.reflection.max_items)
        self.reflection_memory = self.reflection_memory[-max_items:]
        self.telemetry["memory_writes"] = int(self.telemetry["memory_writes"]) + 1

    def _register_retrieved_skill(self, skill_id: str) -> None:
        current = list(self.telemetry["retrieved_skill_ids"])  # type: ignore[arg-type]
        if skill_id not in current:
            current.append(skill_id)
            self.telemetry["retrieved_skill_ids"] = current

    def _controller_context(self, task: str) -> str:
        segments: list[str] = []
        if self.controller_profile.planning_mode == "planner_executor":
            segments.append(
                "Planning scaffold: define milestones, execute one milestone at a time, and replan after failed checks."
            )
        if self.controller_profile.reflection.enabled and len(self.reflection_memory) > 0:
            top_k = max(1, self.controller_profile.reflection.injection_top_k)
            memory_items = self.reflection_memory[-top_k:]
            self.telemetry["memory_reads"] = int(self.telemetry["memory_reads"]) + 1
            rendered = "\n".join(f"- {item}" for item in memory_items)
            segments.append(f"Reflection memory:\n{rendered}")
        if self.controller_profile.skills.enabled and self._skill_library is not None:
            skill_results = self._skill_library.retrieve(
                task,
                top_k=self.controller_profile.skills.top_k,
                min_score=self.controller_profile.skills.min_score,
            )
            if skill_results:
                rendered_rows = []
                for skill, score in skill_results:
                    self._register_retrieved_skill(skill.skill_id)
                    rendered_rows.append(
                        f"- {skill.skill_id} (score={score:.2f}): {skill.title} - {skill.description}"
                    )
                self.telemetry["skill_hits"] = int(self.telemetry["skill_hits"]) + len(
                    skill_results
                )
                segments.append(f"Retrieved skills:\n" + "\n".join(rendered_rows))
        if self.controller_profile.delegation.enabled:
            specialists = ", ".join(self.controller_profile.delegation.specialists)
            segments.append(
                "Specialist protocol: reason as specialists before acting."
                f" Specialists: {specialists}. Keep one merged action plan."
            )
        if self.controller_profile.verification.enabled:
            keywords = ", ".join(self.controller_profile.verification.uncertainty_keywords)
            segments.append(
                "Adaptive verification: if uncertainty cues appear, run an explicit verification check before irreversible actions."
                f" Uncertainty cues: {keywords}."
            )
        strategy_context = self._strategy.build_context(task)
        if strategy_context.strip():
            segments.append(strategy_context)
        return "\n\n".join(segments)

    def before_llm_turn(self, task: str) -> str:
        return ""

    def after_llm_message(self, message: Any) -> None:
        self.telemetry["llm_calls"] = int(self.telemetry["llm_calls"]) + 1
        content = str(getattr(message, "content", "") or "")
        lowered = content.lower()
        if "replan" in lowered or "updated plan" in lowered:
            self.telemetry["replan_signals"] = int(self.telemetry["replan_signals"]) + 1
        if "reflect" in lowered or "lesson" in lowered or "mistake" in lowered:
            self.telemetry["reflection_signals"] = (
                int(self.telemetry["reflection_signals"]) + 1
            )
        if "specialist" in lowered or "delegate" in lowered:
            self.telemetry["delegation_signals"] = (
                int(self.telemetry["delegation_signals"]) + 1
            )
        if "verify" in lowered or "double-check" in lowered:
            self.telemetry["verification_signals"] = (
                int(self.telemetry["verification_signals"]) + 1
            )
        self._strategy.consume_snapshot(
            StrategyLogSnapshot(
                tool_calls=[],
                observations=[],
                llm_outputs=[content] if content else [],
                errors=[],
            )
        )

    def after_tool_response(self, tool_call: Any, tool_response: Any) -> None:
        tool_name = tool_call.function.name
        observation = str(tool_response)
        self.telemetry["tool_calls"] = int(self.telemetry["tool_calls"]) + 1
        self._append_reflection(
            f"After calling {tool_name}, verify outcome before continuing: {observation[:180]}"
        )
        self._strategy.consume_snapshot(
            StrategyLogSnapshot(
                tool_calls=[tool_name],
                observations=[observation[:300]],
                llm_outputs=[],
                errors=[],
            )
        )

    def after_agent_error(self, exc: Exception) -> None:
        self.telemetry["error_count"] = int(self.telemetry["error_count"]) + 1
        error_text = f"{type(exc).__name__}: {exc}"
        self._append_reflection(
            f"Error observed ({error_text}). Use stricter precondition checks and safer retry strategy."
        )
        self._strategy.consume_snapshot(
            StrategyLogSnapshot(
                tool_calls=[],
                observations=[],
                llm_outputs=[],
                errors=[error_text],
            )
        )

    def after_agent_run(self) -> None:
        self.telemetry["reflection_memory_size"] = len(self.reflection_memory)
        self.record_event(
            "controller_telemetry",
            status="ok",
            telemetry=dict(self.telemetry),
        )

    def _build_task_with_research_context(self, task: str) -> str:
        context = self._controller_context(task)
        if context.strip():
            self.record_event(
                "controller_context",
                status="ok",
                content_preview=context[:1000],
            )
        if not context.strip():
            return task
        if str(task).strip():
            return f"{task}\n\n{context}"
        return context

    def _ensure_current_time_system_prompt(self) -> None:
        if self.time_manager is None or not self.messages.messages:
            return
        first_message = self.messages.messages[0]
        if not isinstance(first_message, dict) or first_message.get("role") != "system":
            return
        content = str(first_message.get("content") or "")
        if "Today's date in 'YYYY-MM-DD HH' format is" in content:
            return
        date_str = datetime.fromtimestamp(
            self.time_manager.time(), tz=CST
        ).strftime("%Y-%m-%d %H")
        first_message["content"] = (
            f"{content}\n\nToday's date in 'YYYY-MM-DD HH' format is {date_str}"
        )

    def run(self, input, **kwargs):
        self._reset_research_state()
        self._ensure_current_time_system_prompt()
        task = self._build_task_with_research_context(str(input))
        return super().run(task, **kwargs)


ControllerAgent = ResearchARESimulationAgent


class AgentBuilder:
    """Build FAIRY farm controller agents by ARE-compatible family id."""

    def list_agents(self) -> list[str]:
        return list(CONTROLLER_FAMILIES)

    def build(
        self,
        agent_config: ControllerAgentConfig,
        llm: Any,
        toolsets: list[Any] | None = None,
        system_message: str | None = None,
    ) -> ResearchARESimulationAgent:
        if agent_config.research_profile is None:
            built_config = ControllerConfigBuilder(
                farm_system_prompt=agent_config.base_agent_config.system_prompt
                or DEFAULT_FARM_SYSTEM_MESSAGE
            ).build(agent_config.get_agent_name())
            agent_config = built_config
        family_id = agent_config.get_agent_name()
        profile = agent_config.research_profile or ResearchAgentProfileConfig.for_family(family_id)
        return ResearchARESimulationAgent(
            name=family_id,
            llm=llm,
            controller_profile=profile,
            system_message=system_message
            or agent_config.base_agent_config.system_prompt
            or DEFAULT_FARM_SYSTEM_MESSAGE,
            toolsets=toolsets,
        )


class AppAgentBuilder:
    def list_agents(self) -> list[str]:
        return AppAgentConfigBuilder().list_agents()

    def build(
        self,
        app_agent_config: AppAgentConfig,
        llm: Any,
        app: Any,
    ) -> Agent:
        return Agent(
            name=app_agent_config.agent_name,
            llm=llm,
            system_message=app_agent_config.system_prompt,
            toolsets=[app, FinalAnswerApp()],
        )


def build_controller_agent(
    family_id: str,
    llm: Any,
    toolsets: list[Any] | None = None,
    system_message: str | None = None,
) -> ResearchARESimulationAgent:
    config = ControllerConfigBuilder(
        farm_system_prompt=system_message or DEFAULT_FARM_SYSTEM_MESSAGE
    ).build(family_id)
    return AgentBuilder().build(
        agent_config=config,
        llm=llm,
        toolsets=toolsets,
        system_message=system_message,
    )
