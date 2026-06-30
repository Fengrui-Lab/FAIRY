from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMEngineConfig:
    model_name: str = "gpt-4o-mini"
    provider: str | None = "openai"
    endpoint: str | None = None
    temperature: float | None = 0.1


@dataclass
class ReactBaseAgentConfig:
    llm_engine_config: LLMEngineConfig = field(default_factory=LLMEngineConfig)
    system_prompt: str = ""
    max_iterations: int = 80
    use_custom_logger: bool = True


@dataclass
class ResearchSkillConfig:
    enabled: bool = False
    library_path: str | None = None
    top_k: int = 3
    min_score: float = 0.1


@dataclass
class ResearchMemoryConfig:
    enabled: bool = False
    max_items: int = 8
    injection_top_k: int = 3


@dataclass
class ResearchDelegationConfig:
    enabled: bool = False
    specialists: list[str] = field(default_factory=list)
    max_delegations_per_turn: int = 0


@dataclass
class ResearchVerificationConfig:
    enabled: bool = False
    uncertainty_keywords: list[str] = field(
        default_factory=lambda: ["maybe", "uncertain", "not sure", "risk", "verify"]
    )


@dataclass
class ResearchReWooConfig:
    enabled: bool = False
    max_plan_steps: int = 8
    max_replans: int = 1


@dataclass
class ResearchTreeSearchConfig:
    enabled: bool = False
    branch_factor: int = 3
    search_depth: int = 2
    max_expansions: int = 6


@dataclass
class ResearchCriticConfig:
    enabled: bool = False
    max_revision_cycles: int = 2
    enforce_precondition_checks: bool = True


@dataclass
class ResearchGraphMemoryConfig:
    enabled: bool = False
    max_nodes: int = 60
    retrieval_top_k: int = 5
    contradiction_check: bool = True


@dataclass
class ResearchTelemetryConfig:
    enabled: bool = True
    emit_to_result_metadata: bool = True


@dataclass
class ResearchAgentProfileConfig:
    family_id: str = "farm_baseline_react"
    planning_mode: str = "react"
    replan_on_tool_error: bool = False
    reflection: ResearchMemoryConfig = field(default_factory=ResearchMemoryConfig)
    skills: ResearchSkillConfig = field(default_factory=ResearchSkillConfig)
    delegation: ResearchDelegationConfig = field(default_factory=ResearchDelegationConfig)
    verification: ResearchVerificationConfig = field(default_factory=ResearchVerificationConfig)
    rewoo: ResearchReWooConfig = field(default_factory=ResearchReWooConfig)
    tree_search: ResearchTreeSearchConfig = field(default_factory=ResearchTreeSearchConfig)
    critic: ResearchCriticConfig = field(default_factory=ResearchCriticConfig)
    graph_memory: ResearchGraphMemoryConfig = field(default_factory=ResearchGraphMemoryConfig)
    telemetry: ResearchTelemetryConfig = field(default_factory=ResearchTelemetryConfig)

    @classmethod
    def for_family(cls, family_id: str) -> "ResearchAgentProfileConfig":
        profile = cls(family_id=family_id)
        match family_id:
            case "farm_baseline_react" | "farm_world" | "default":
                profile.planning_mode = "react"
            case "farm_planner_executor":
                profile.planning_mode = "planner_executor"
            case "farm_reflective_memory":
                profile.planning_mode = "react"
                profile.reflection.enabled = True
            case "farm_skill_rag":
                profile.planning_mode = "react"
                profile.skills.enabled = True
            case "farm_multi_specialist":
                profile.planning_mode = "react"
                profile.delegation.enabled = True
                profile.delegation.specialists = [
                    "weather",
                    "sensors",
                    "machinery",
                    "field_operations",
                ]
            case "farm_adaptive_verifier":
                profile.planning_mode = "react"
                profile.verification.enabled = True
            case "farm_rewoo_modular":
                profile.planning_mode = "rewoo"
                profile.rewoo.enabled = True
            case "farm_tree_search":
                profile.planning_mode = "tree_search"
                profile.tree_search.enabled = True
            case "farm_critic_refiner":
                profile.planning_mode = "critic_refiner"
                profile.critic.enabled = True
            case "farm_graph_memory":
                profile.planning_mode = "graph_memory"
                profile.graph_memory.enabled = True
            case _:
                raise ValueError(f"Unknown FAIRY controller family: {family_id}")
        return profile


@dataclass
class ControllerAgentConfig:
    agent_name: str = "farm_baseline_react"
    base_agent_config: ReactBaseAgentConfig = field(default_factory=ReactBaseAgentConfig)
    research_profile: ResearchAgentProfileConfig | None = None
    max_turns: int | None = None

    def get_agent_name(self) -> str:
        return self.agent_name

    def get_base_agent_config(self) -> ReactBaseAgentConfig:
        return self.base_agent_config

    def get_model_dump(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "base_agent_config": self.base_agent_config,
            "research_profile": self.research_profile,
            "max_turns": self.max_turns,
        }

