from __future__ import annotations

from typing import Any

from fairy.scenarios.registry import register_scenario
from .maize_scenario_catalog import get_spec
from .maize_scenario_helpers import MaizeScenario, build_maize_events, init_maize_apps

SPEC = get_spec("water_limit")
SCENARIO_ID = SPEC.scenario_id


@register_scenario(SCENARIO_ID)
class ScenarioFullSeasonMaizeWaterLimit(MaizeScenario):
    spec = SPEC

    def init_and_populate_apps(self, *args: Any, **kwargs: Any) -> None:
        init_maize_apps(self, SPEC)

    def build_events_flow(self) -> None:
        build_maize_events(self, SPEC)
