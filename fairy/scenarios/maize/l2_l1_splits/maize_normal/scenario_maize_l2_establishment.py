"""L2 maize task: establishment."""
from fairy.scenarios.registry import register_scenario
from fairy.scenarios.maize.maize_scenario_catalog import TASK_SPECS
from .._maize_split_common import MaizeSplitScenario, init_maize_split, build_maize_split_events

SCENARIO_ID = "scenario_maize_l2_establishment"


@register_scenario(SCENARIO_ID)
class ScenarioMaizeL2Establishment(MaizeSplitScenario):
    BASIC_BRIEFING = (
        '田地共64垄（0–63），每垄长268米、垄宽0.75米；玉米品种Grain_maize_201，种子标识MAIZE_201。\n'
        '从裸地开始完成全田玉米建植，播后观察并确认全田出苗。仅完成本任务，不继续后续全季作业。'
    )

    task_spec = TASK_SPECS[SCENARIO_ID]

    def init_and_populate_apps(self, *args, **kwargs):
        init_maize_split(self)
        original_briefing = self.scenario_input
        if self._briefing_input_override:
            self.scenario_input = self._briefing_input_override
        elif not self.detailed_briefing:
            self.scenario_input = self.BASIC_BRIEFING
        if self.additional_system_prompt == original_briefing:
            self.additional_system_prompt = self.scenario_input

    def build_events_flow(self):
        build_maize_split_events(self)

    def __post_init__(self):
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean: false or true")
        self._briefing_input_override = self.scenario_input
        super().__post_init__()
