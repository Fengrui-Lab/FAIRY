"""L2 maize task: harvest_storage."""
from fairy.scenarios.registry import register_scenario
from fairy.scenarios.maize.maize_scenario_catalog import TASK_SPECS
from .._maize_split_common import MaizeSplitScenario, init_maize_split, build_maize_split_events

SCENARIO_ID = "scenario_maize_l2_harvest_storage"


@register_scenario(SCENARIO_ID)
class ScenarioMaizeL2HarvestStorage(MaizeSplitScenario):
    task_spec = TASK_SPECS[SCENARIO_ID]

    def init_and_populate_apps(self, *args, **kwargs):
        init_maize_split(self)

    def build_events_flow(self):
        build_maize_split_events(self)
