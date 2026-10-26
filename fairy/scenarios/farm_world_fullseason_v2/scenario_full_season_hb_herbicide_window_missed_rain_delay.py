from __future__ import annotations

from typing import Any

from fairy.apps.farm_world import FarmWorldApp, SensorApp, WeatherApp
from fairy.apps.system import SystemApp
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.farm_world_fullseason_v2.harbin_l3_batch_catalog import (
    get_spec,
)
from fairy.scenarios.farm_world_fullseason_v2.harbin_l3_batch_scenario import (
    build_batch_events,
    init_batch_apps,
)
from fairy.scenarios.farm_world_fullseason_v2.harbin_l3_scenario_helpers import (
    harbin_start_time,
)
from fairy.scenarios.registry import register_scenario

SPEC = get_spec("hb_herbicide_window_missed_rain_delay")
SCENARIO_ID = SPEC.scenario_id
PROFILE_NAME = SPEC.profile_name
SCENARIO_DESCRIPTION = SPEC.description
BRIEFING_TEXT = SPEC.briefing_text


@register_scenario(SCENARIO_ID)
class ScenarioFullSeasonHBHerbicideWindowMissedRainDelay(Scenario):
    """{SCENARIO_DESCRIPTION}"""

    start_time: float | None = harbin_start_time()
    duration: float | None = 180 * 24 * 3600
    queue_based_loop: bool = True
    time_increment_in_seconds: int = 60
    detailed_briefing: bool = True
    nb_turns: int = 1

    def init_and_populate_apps(self, *args: Any, **kwargs: Any) -> None:
        init_batch_apps(self, SPEC)

    def _after_named_step(self, prev: Any, label: str) -> Any:
        if label != "before_whole_field_harvest_checks":
            return prev
        # Recorded original-world replay: the first dry, trafficable daily
        # harvest window is three days later. No weather or SPEC value changes.
        weather = self.get_typed_app(WeatherApp)
        sensor = self.get_typed_app(SensorApp)
        farm = self.get_typed_app(FarmWorldApp)
        system = self.get_typed_app(SystemApp)
        prev = (weather.get_current_weather().oracle()
                .with_id("o_compat_original_harvest_weather")
                .depends_on(prev, delay_seconds=1))
        prev = (sensor.read_soil_sensors().oracle()
                .with_id("o_compat_original_harvest_soil")
                .depends_on(prev, delay_seconds=1))
        prev = (farm.get_ridge_range_state(0, 63).oracle()
                .with_id("o_compat_original_harvest_grain_state")
                .depends_on(prev, delay_seconds=1))
        # Existing harvest checks repeat after this fixed, explicit wait.
        return (system.advance_time(days=3).oracle()
                .with_id("o_compat_wait_existing_dry_harvest_window")
                .depends_on(prev, delay_seconds=1))

    def build_events_flow(self) -> None:
        build_batch_events(self, SPEC)
