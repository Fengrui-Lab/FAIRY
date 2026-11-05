"""Frozen H01 engineering pilot, derived from the accepted N01 environment.

Only the candidate's tractor exposes header maintenance. The native crop,
weather, input, harvest and storage rules are inherited without retuning.
The event graph delivers the task; the separately frozen dynamic controller
is the reference. No unexecuted static harvest policy is represented as an
accepted H01 oracle.
"""
from pathlib import Path

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world import FarmWorldApp, TractorApp, WeatherApp
from fairy.scenarios.farm_world_fullseason_v2.harbin_l3_scenario_helpers import collect_event_graph
from fairy.scenarios.registry import register_scenario
from fairy.types import EventRegisterer

from .basic_management import BasicManagementScenario, candidate_spec
from .header_maintenance import HeaderMaintenanceTractorApp
from .h01_evaluation import augment_h01_evaluation

DATA = Path(__file__).with_name("basic_h01_v0")
SCENARIO_ID = "scenario_maize_l3_basic_h01_v0"


@register_scenario(SCENARIO_ID)
class BasicH01Scenario(BasicManagementScenario):
    candidate = "N01"
    spec = candidate_spec("N01")
    scenario_version = "basic-h01-v0.1"
    event_graph_policy = "briefing_only; no validated H01 static oracle"

    def __init__(self, **kwargs):
        kwargs.setdefault("scenario_id", SCENARIO_ID)
        super().__init__(**kwargs)

    def init_and_populate_apps(self, *args, **kwargs):
        super().init_and_populate_apps(*args, **kwargs)
        old = self.get_typed_app(TractorApp)
        replacement = HeaderMaintenanceTractorApp(
            self.get_typed_app(FarmWorldApp),
            self.get_typed_app(WeatherApp),
            name=old.name,
            equipment=old.equipment,
        )
        # Preserve the accepted parent's actual fuel, moisture capability,
        # initial device inventory and deterministic RNG.
        replacement.seed = old.seed
        parent_state = old.get_state()
        parent_state["h01_header"] = replacement.get_state()["h01_header"]
        replacement.load_state(parent_state)
        self.apps[self.apps.index(old)] = replacement
        self.scenario_input = (DATA / "agent_task.zh.txt").read_text(encoding="utf-8")

    def build_events_flow(self):
        with EventRegisterer.capture_mode():
            briefing = self.get_typed_app(AgentUserInterface).send_message_to_agent(
                content=self.scenario_input
            ).with_id("briefing")
            self.events = collect_event_graph(briefing)

    def validate(self, env=None):
        return augment_h01_evaluation(
            super().validate(env),
            farm=self.get_typed_app(FarmWorldApp),
            tractor=self.get_typed_app(HeaderMaintenanceTractorApp),
            scenario_version=self.scenario_version,
        )
