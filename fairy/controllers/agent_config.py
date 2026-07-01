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
        config = AgentConfigBuilder().build(family_id)
        if config.research_profile is None:
            return cls(family_id=family_id, planning_mode="react")
        return config.research_profile


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


@dataclass
class AppAgentConfig:
    agent_name: str = "default_app_agent"
    llm_engine_config: LLMEngineConfig = field(default_factory=LLMEngineConfig)
    system_prompt: str = ""
    max_iterations: int = 80
    use_custom_logger: bool = True

    def get_agent_name(self) -> str:
        return self.agent_name


PLANNING_ADDENDUM = (
    "\n\n<research_family_instructions>\n"
    "Before calling tools, create a compact plan with explicit milestones.\n"
    "After each tool call, check whether the plan still holds; if not, replan before continuing.\n"
    "End by reporting completion status and unresolved risks.\n"
    "</research_family_instructions>"
)

REFLECTIVE_ADDENDUM = (
    "\n\n<research_family_instructions>\n"
    "Keep a short reflection loop: track mistakes, assumptions, and fixes across turns.\n"
    "Before deciding the next action, consult your memory notes and avoid repeated mistakes.\n"
    "</research_family_instructions>"
)

DELEGATION_ADDENDUM = (
    "\n\n<research_family_instructions>\n"
    "Use specialist reasoning modes (weather, soil, equipment, operations) before committing to action.\n"
    "Synthesize specialist viewpoints into one final executable action plan.\n"
    "</research_family_instructions>"
)

VERIFIER_ADDENDUM = (
    "\n\n<research_family_instructions>\n"
    "Use adaptive compute: short plan for straightforward cases, deeper verification for uncertain/high-risk actions.\n"
    "When uncertainty is high, verify preconditions before irreversible actions.\n"
    "</research_family_instructions>"
)

REWOO_ADDENDUM = (
    "\n\n<research_family_instructions>\n"
    "Follow a modular plan-work-solve pattern.\n"
    "First draft structured steps, then execute one step at a time with intermediate evidence, and finally synthesize results.\n"
    "</research_family_instructions>"
)

TREE_SEARCH_ADDENDUM = (
    "\n\n<research_family_instructions>\n"
    "Generate multiple candidate plans, score them with a risk-aware rubric, execute the top one, and backtrack once if it fails.\n"
    "</research_family_instructions>"
)

CRITIC_ADDENDUM = (
    "\n\n<research_family_instructions>\n"
    "Run an explicit actor-critic refinement cycle before high-impact actions.\n"
    "The critic must verify preconditions, safety constraints, and inventory/tool readiness.\n"
    "</research_family_instructions>"
)

GRAPH_MEMORY_ADDENDUM = (
    "\n\n<research_family_instructions>\n"
    "Maintain a compact graph memory of objectives, actions, outcomes, and dependencies.\n"
    "Retrieve relevant graph snippets before choosing the next action and check for contradictions.\n"
    "</research_family_instructions>"
)


DEFAULT_APP_AGENT_SYSTEM_MESSAGE = (
    "You are an expert sub-agent for one FAIRY app. Use only the app tools "
    "available to you, complete the delegated task, and return a concise final "
    "answer. If a final answer tool is available, call it when done."
)

WEATHER_APP_AGENT_ADDENDUM = (
    "\n\n<app_expert_instructions>\n"
    "You are the weather and field-conditions expert.\n"
    "Prioritize: current weather, short forecast, wind/rain risk, and go/no-go recommendations for field operations.\n"
    "If conditions are unsafe, explicitly block action and provide safe alternatives.\n"
    "</app_expert_instructions>"
)

SENSOR_APP_AGENT_ADDENDUM = (
    "\n\n<app_expert_instructions>\n"
    "You are the sensor interpretation expert.\n"
    "Prioritize: soil moisture/temperature, canopy indicators, anomalies, and confidence notes.\n"
    "Always report measured evidence before recommending actions.\n"
    "</app_expert_instructions>"
)

MACHINERY_APP_AGENT_ADDENDUM = (
    "\n\n<app_expert_instructions>\n"
    "You are the machinery and implement operations expert.\n"
    "Prioritize: equipment status, precondition checks, attachment compatibility, fuel/consumable readiness, and safe execution order.\n"
    "Do not execute irreversible actions unless readiness checks pass.\n"
    "</app_expert_instructions>"
)

OPERATIONS_APP_AGENT_ADDENDUM = (
    "\n\n<app_expert_instructions>\n"
    "You are the farm operations coordination expert.\n"
    "Prioritize: operational sequencing, ridge-level targeting, inventory consistency, and completion evidence.\n"
    "Return a concise completion summary with unresolved risks if any remain.\n"
    "</app_expert_instructions>"
)


class AgentConfigBuilder:
    """Build FAIRY controller configs with ARE-compatible family semantics."""

    def __init__(self, farm_system_prompt: str = "") -> None:
        self.farm_system_prompt = farm_system_prompt

    def build(self, agent_name: str) -> ControllerAgentConfig:
        base_prompt = self.farm_system_prompt
        match agent_name:
            case "default" | "farm_world":
                return ControllerAgentConfig(
                    agent_name=agent_name,
                    base_agent_config=ReactBaseAgentConfig(
                        system_prompt=base_prompt,
                        max_iterations=80,
                    ),
                )
            case "farm_baseline_react":
                return ControllerAgentConfig(
                    agent_name=agent_name,
                    base_agent_config=ReactBaseAgentConfig(
                        system_prompt=base_prompt,
                        max_iterations=80,
                    ),
                    research_profile=ResearchAgentProfileConfig(
                        family_id=agent_name,
                        planning_mode="react",
                        telemetry=ResearchTelemetryConfig(enabled=True),
                    ),
                )
            case "farm_planner_executor":
                return ControllerAgentConfig(
                    agent_name=agent_name,
                    base_agent_config=ReactBaseAgentConfig(
                        system_prompt=base_prompt + PLANNING_ADDENDUM,
                        max_iterations=100,
                    ),
                    research_profile=ResearchAgentProfileConfig(
                        family_id=agent_name,
                        planning_mode="planner_executor",
                        replan_on_tool_error=True,
                        telemetry=ResearchTelemetryConfig(enabled=True),
                    ),
                )
            case "farm_reflective_memory":
                return ControllerAgentConfig(
                    agent_name=agent_name,
                    base_agent_config=ReactBaseAgentConfig(
                        system_prompt=base_prompt + REFLECTIVE_ADDENDUM,
                        max_iterations=100,
                    ),
                    research_profile=ResearchAgentProfileConfig(
                        family_id=agent_name,
                        planning_mode="reflective",
                        reflection=ResearchMemoryConfig(
                            enabled=True, max_items=12, injection_top_k=4
                        ),
                        telemetry=ResearchTelemetryConfig(enabled=True),
                    ),
                )
            case "farm_multi_specialist":
                return ControllerAgentConfig(
                    agent_name=agent_name,
                    base_agent_config=ReactBaseAgentConfig(
                        system_prompt=base_prompt + DELEGATION_ADDENDUM,
                        max_iterations=110,
                    ),
                    research_profile=ResearchAgentProfileConfig(
                        family_id=agent_name,
                        planning_mode="multi_specialist",
                        delegation=ResearchDelegationConfig(
                            enabled=True,
                            specialists=[
                                "weather_specialist",
                                "soil_specialist",
                                "equipment_specialist",
                                "operations_specialist",
                            ],
                            max_delegations_per_turn=4,
                        ),
                        telemetry=ResearchTelemetryConfig(enabled=True),
                    ),
                )
            case "farm_adaptive_verifier":
                return ControllerAgentConfig(
                    agent_name=agent_name,
                    base_agent_config=ReactBaseAgentConfig(
                        system_prompt=base_prompt + VERIFIER_ADDENDUM,
                        max_iterations=110,
                    ),
                    research_profile=ResearchAgentProfileConfig(
                        family_id=agent_name,
                        planning_mode="adaptive_verifier",
                        replan_on_tool_error=True,
                        verification=ResearchVerificationConfig(enabled=True),
                        telemetry=ResearchTelemetryConfig(enabled=True),
                    ),
                )
            case "farm_rewoo_modular":
                return ControllerAgentConfig(
                    agent_name=agent_name,
                    base_agent_config=ReactBaseAgentConfig(
                        system_prompt=base_prompt + REWOO_ADDENDUM,
                        max_iterations=110,
                    ),
                    research_profile=ResearchAgentProfileConfig(
                        family_id=agent_name,
                        planning_mode="rewoo_modular",
                        replan_on_tool_error=True,
                        rewoo=ResearchReWooConfig(
                            enabled=True,
                            max_plan_steps=8,
                            max_replans=1,
                        ),
                        telemetry=ResearchTelemetryConfig(enabled=True),
                    ),
                )
            case "farm_tree_search":
                return ControllerAgentConfig(
                    agent_name=agent_name,
                    base_agent_config=ReactBaseAgentConfig(
                        system_prompt=base_prompt + TREE_SEARCH_ADDENDUM,
                        max_iterations=110,
                    ),
                    research_profile=ResearchAgentProfileConfig(
                        family_id=agent_name,
                        planning_mode="tree_search",
                        tree_search=ResearchTreeSearchConfig(
                            enabled=True,
                            branch_factor=3,
                            search_depth=2,
                            max_expansions=6,
                        ),
                        telemetry=ResearchTelemetryConfig(enabled=True),
                    ),
                )
            case "farm_critic_refiner":
                return ControllerAgentConfig(
                    agent_name=agent_name,
                    base_agent_config=ReactBaseAgentConfig(
                        system_prompt=base_prompt + CRITIC_ADDENDUM,
                        max_iterations=110,
                    ),
                    research_profile=ResearchAgentProfileConfig(
                        family_id=agent_name,
                        planning_mode="critic_refiner",
                        critic=ResearchCriticConfig(
                            enabled=True,
                            max_revision_cycles=2,
                            enforce_precondition_checks=True,
                        ),
                        verification=ResearchVerificationConfig(enabled=True),
                        telemetry=ResearchTelemetryConfig(enabled=True),
                    ),
                )
            case "farm_graph_memory":
                return ControllerAgentConfig(
                    agent_name=agent_name,
                    base_agent_config=ReactBaseAgentConfig(
                        system_prompt=base_prompt + GRAPH_MEMORY_ADDENDUM,
                        max_iterations=110,
                    ),
                    research_profile=ResearchAgentProfileConfig(
                        family_id=agent_name,
                        planning_mode="graph_memory",
                        graph_memory=ResearchGraphMemoryConfig(
                            enabled=True,
                            max_nodes=60,
                            retrieval_top_k=5,
                            contradiction_check=True,
                        ),
                        telemetry=ResearchTelemetryConfig(enabled=True),
                    ),
                )
            case _:
                raise ValueError(f"Agent {agent_name} not found")


class AppAgentConfigBuilder:
    def __init__(self, app_system_prompt: str = DEFAULT_APP_AGENT_SYSTEM_MESSAGE) -> None:
        self.app_system_prompt = app_system_prompt

    def list_agents(self) -> list[str]:
        return [
            "default_app_agent",
            "weather_expert_app_agent",
            "sensor_expert_app_agent",
            "machinery_expert_app_agent",
            "operations_expert_app_agent",
        ]

    def build(self, agent_name: str) -> AppAgentConfig:
        base_prompt = self.app_system_prompt
        match agent_name:
            case "default_app_agent":
                return AppAgentConfig(
                    agent_name=agent_name,
                    system_prompt=base_prompt,
                    max_iterations=80,
                )
            case "weather_expert_app_agent":
                return AppAgentConfig(
                    agent_name=agent_name,
                    system_prompt=base_prompt + WEATHER_APP_AGENT_ADDENDUM,
                    max_iterations=60,
                )
            case "sensor_expert_app_agent":
                return AppAgentConfig(
                    agent_name=agent_name,
                    system_prompt=base_prompt + SENSOR_APP_AGENT_ADDENDUM,
                    max_iterations=60,
                )
            case "machinery_expert_app_agent":
                return AppAgentConfig(
                    agent_name=agent_name,
                    system_prompt=base_prompt + MACHINERY_APP_AGENT_ADDENDUM,
                    max_iterations=70,
                )
            case "operations_expert_app_agent":
                return AppAgentConfig(
                    agent_name=agent_name,
                    system_prompt=base_prompt + OPERATIONS_APP_AGENT_ADDENDUM,
                    max_iterations=70,
                )
            case _:
                raise ValueError(f"Sub agent {agent_name} not found")
