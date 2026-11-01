from __future__ import annotations

from typing import Any

from fairy.scenarios.registry import register_scenario
from .maize_scenario_catalog import build_reference_events, configure_reference_briefing, get_spec
from .maize_scenario_helpers import MaizeScenario, init_maize_apps

SPEC = get_spec("normal")
SCENARIO_ID = SPEC.scenario_id


@register_scenario(SCENARIO_ID)
class ScenarioFullSeasonMaizeNormal(MaizeScenario):
    spec = SPEC

    def init_and_populate_apps(self, *args: Any, **kwargs: Any) -> None:
        init_maize_apps(self, SPEC)
        configure_reference_briefing(self, SPEC)

    def build_events_flow(self) -> None:
        build_reference_events(self, SPEC)
