from __future__ import annotations

from typing import Any

from fairy.agents.agent.agent import Agent
from fairy.controllers.agent_config import (
    ControllerAgentConfig,
    ResearchAgentProfileConfig,
)
from fairy.controllers.research_strategies import ResearchStrategyCoordinator


CONTROLLER_FAMILIES = [
    "default",
    "farm_world",
    "farm_baseline_react",
    "farm_planner_executor",
    "farm_reflective_memory",
    "farm_skill_rag",
    "farm_multi_specialist",
    "farm_adaptive_verifier",
    "farm_rewoo_modular",
    "farm_tree_search",
    "farm_critic_refiner",
    "farm_graph_memory",
]


DEFAULT_FARM_SYSTEM_MESSAGE = (
    "你是一个智能农场管理助手，负责协调农场的各种设备和操作。"
    "你需要根据天气、土壤状况等信息，合理安排农场作业。"
    "请按照农艺流程的正确顺序完成任务。"
)


class ControllerAgent(Agent):
    """Agent with a FAIRY controller family wrapper around the task prompt."""

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
        )
        self.controller_profile = controller_profile
        self.telemetry: dict[str, object] = {
            "family_id": controller_profile.family_id,
            "planning_mode": controller_profile.planning_mode,
        }
        self._strategy = ResearchStrategyCoordinator(controller_profile)
        self._strategy.reset(self.telemetry)

    def _controller_context(self, task: str) -> str:
        segments: list[str] = []
        if self.controller_profile.planning_mode == "planner_executor":
            segments.append(
                "Planning scaffold: define milestones, execute one milestone at a time, and replan after failed checks."
            )
        if self.controller_profile.reflection.enabled:
            segments.append(
                "Reflection memory protocol: after each observation, preserve lessons that prevent repeated farm-operation mistakes."
            )
        if self.controller_profile.skills.enabled:
            segments.append(
                "Skill-RAG protocol: retrieve relevant farming skills before irreversible actions when a skill library is configured."
            )
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

    def run(self, input, **kwargs):
        context = self._controller_context(str(input))
        task = f"{input}\n\n{context}" if context else input
        return super().run(task, **kwargs)


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
    ) -> ControllerAgent:
        family_id = agent_config.get_agent_name()
        profile = agent_config.research_profile or ResearchAgentProfileConfig.for_family(
            family_id
        )
        return ControllerAgent(
            name=family_id,
            llm=llm,
            controller_profile=profile,
            system_message=system_message or agent_config.base_agent_config.system_prompt or DEFAULT_FARM_SYSTEM_MESSAGE,
            toolsets=toolsets,
        )


def build_controller_agent(
    family_id: str,
    llm: Any,
    toolsets: list[Any] | None = None,
    system_message: str | None = None,
) -> ControllerAgent:
    config = ControllerAgentConfig(
        agent_name=family_id,
        research_profile=ResearchAgentProfileConfig.for_family(family_id),
    )
    return AgentBuilder().build(
        agent_config=config,
        llm=llm,
        toolsets=toolsets,
        system_message=system_message,
    )
