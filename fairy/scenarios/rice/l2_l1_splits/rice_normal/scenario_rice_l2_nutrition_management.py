"""L2 rice task: nutrition management."""
from __future__ import annotations

from typing import Any

from fairy.scenarios.registry import register_scenario
from fairy.scenarios.rice.rice_scenario import RiceScenario
from fairy.scenarios.rice.rice_scenario_catalog import get_spec
from fairy.scenarios.rice.rice_scenario_helpers import build_rice_events, init_rice_apps

SCENARIO_ID = "scenario_rice_l2_nutrition_management"
SPEC = get_spec(SCENARIO_ID)


@register_scenario(SCENARIO_ID)
class ScenarioRiceL2NutritionManagement(RiceScenario):
    spec = SPEC

    def init_and_populate_apps(self, *args: Any, **kwargs: Any) -> None:
        init_rice_apps(self, SPEC)

    def build_events_flow(self) -> None:
        build_rice_events(self, SPEC)
