"""Maize challenges with scene-owned basic and expert briefing selection."""
from .runtime import CropChallengeScenario
from fairy.scenarios.registry import register_scenario


@register_scenario('scenario_maize_l1_targeted_fertilization')
class ScenarioMaizeL1TargetedFertilization(CropChallengeScenario):
    challenge_id = 'scenario_maize_l1_targeted_fertilization'
    BASIC_BRIEFING = (
        '田地共64垄（0–63），每垄长268米、垄宽0.75米；玉米品种Grain_maize_201，种子标识MAIZE_201。\n'
        '从当前检查点完成22–32垄的定向追肥并复查，仅完成本任务。'
    )

    def __post_init__(self):
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean: false or true")
        self._briefing_input_override = self.scenario_input
        super().__post_init__()

    def init_and_populate_apps(self):
        super().init_and_populate_apps()
        original_briefing = self.scenario_input
        if self._briefing_input_override:
            self.scenario_input = self._briefing_input_override
        elif not self.detailed_briefing:
            self.scenario_input = self.BASIC_BRIEFING
        if self.additional_system_prompt == original_briefing:
            self.additional_system_prompt = self.scenario_input


@register_scenario('scenario_maize_l1_targeted_irrigation')
class ScenarioMaizeL1TargetedIrrigation(CropChallengeScenario):
    challenge_id = 'scenario_maize_l1_targeted_irrigation'
    BASIC_BRIEFING = (
        '田地共64垄（0–63），每垄长268米、垄宽0.75米；玉米品种Grain_maize_201，种子标识MAIZE_201。\n'
        '从当前检查点完成0–10垄的定向灌溉并复查，仅完成本任务。'
    )

    def __post_init__(self):
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean: false or true")
        self._briefing_input_override = self.scenario_input
        super().__post_init__()

    def init_and_populate_apps(self):
        super().init_and_populate_apps()
        original_briefing = self.scenario_input
        if self._briefing_input_override:
            self.scenario_input = self._briefing_input_override
        elif not self.detailed_briefing:
            self.scenario_input = self.BASIC_BRIEFING
        if self.additional_system_prompt == original_briefing:
            self.additional_system_prompt = self.scenario_input


@register_scenario('scenario_maize_l2_compound_water_n_limit')
class ScenarioMaizeL2CompoundWaterNLimit(CropChallengeScenario):
    challenge_id = 'scenario_maize_l2_compound_water_n_limit'
    BASIC_BRIEFING = (
        '田地共64垄（0–63），每垄长268米、垄宽0.75米；玉米品种Grain_maize_201，种子标识MAIZE_201。\n'
        '田间存在不同水分和营养状况。辨别各区需求，分别管理并复查。仅完成当前管理窗口并复查，保留后续季节资源。'
    )

    def __post_init__(self):
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean: false or true")
        self._briefing_input_override = self.scenario_input
        super().__post_init__()

    def init_and_populate_apps(self):
        super().init_and_populate_apps()
        original_briefing = self.scenario_input
        if self._briefing_input_override:
            self.scenario_input = self._briefing_input_override
        elif not self.detailed_briefing:
            self.scenario_input = self.BASIC_BRIEFING
        if self.additional_system_prompt == original_briefing:
            self.additional_system_prompt = self.scenario_input


@register_scenario('scenario_maize_l2_rain_aware_irrigation')
class ScenarioMaizeL2RainAwareIrrigation(CropChallengeScenario):
    challenge_id = 'scenario_maize_l2_rain_aware_irrigation'
    BASIC_BRIEFING = (
        '田地共64垄（0–63），每垄长268米、垄宽0.75米；玉米品种Grain_maize_201，种子标识MAIZE_201。\n'
        '结合天气预报和田间状况安排水分管理，在保护作物的同时节约用水。仅完成当前管理窗口并复查，保留后续季节资源。'
    )

    def __post_init__(self):
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean: false or true")
        self._briefing_input_override = self.scenario_input
        super().__post_init__()

    def init_and_populate_apps(self):
        super().init_and_populate_apps()
        original_briefing = self.scenario_input
        if self._briefing_input_override:
            self.scenario_input = self._briefing_input_override
        elif not self.detailed_briefing:
            self.scenario_input = self.BASIC_BRIEFING
        if self.additional_system_prompt == original_briefing:
            self.additional_system_prompt = self.scenario_input


@register_scenario('scenario_maize_l2_rainy_harvest_window')
class ScenarioMaizeL2RainyHarvestWindow(CropChallengeScenario):
    challenge_id = 'scenario_maize_l2_rainy_harvest_window'
    BASIC_BRIEFING = (
        '田地共64垄（0–63），每垄长268米、垄宽0.75米；玉米品种Grain_maize_201，种子标识MAIZE_201。\n'
        '根据各区作物、粮食和天气状况选择收获时机，完成安全收储。仅完成当前管理窗口并复查，保留后续季节资源。'
    )

    def __post_init__(self):
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean: false or true")
        self._briefing_input_override = self.scenario_input
        super().__post_init__()

    def init_and_populate_apps(self):
        super().init_and_populate_apps()
        original_briefing = self.scenario_input
        if self._briefing_input_override:
            self.scenario_input = self._briefing_input_override
        elif not self.detailed_briefing:
            self.scenario_input = self.BASIC_BRIEFING
        if self.additional_system_prompt == original_briefing:
            self.additional_system_prompt = self.scenario_input


@register_scenario('scenario_maize_l2_staggered_water_priority')
class ScenarioMaizeL2StaggeredWaterPriority(CropChallengeScenario):
    challenge_id = 'scenario_maize_l2_staggered_water_priority'
    BASIC_BRIEFING = (
        '田地共64垄（0–63），每垄长268米、垄宽0.75米；玉米品种Grain_maize_201，种子标识MAIZE_201。\n'
        '田间玉米分期播种。根据各区生育与水分状况安排管理并复查。仅完成当前管理窗口并复查，保留后续季节资源。'
    )

    def __post_init__(self):
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean: false or true")
        self._briefing_input_override = self.scenario_input
        super().__post_init__()

    def init_and_populate_apps(self):
        super().init_and_populate_apps()
        original_briefing = self.scenario_input
        if self._briefing_input_override:
            self.scenario_input = self._briefing_input_override
        elif not self.detailed_briefing:
            self.scenario_input = self.BASIC_BRIEFING
        if self.additional_system_prompt == original_briefing:
            self.additional_system_prompt = self.scenario_input


@register_scenario('scenario_maize_l2_zonal_nitrogen_recovery')
class ScenarioMaizeL2ZonalNitrogenRecovery(CropChallengeScenario):
    challenge_id = 'scenario_maize_l2_zonal_nitrogen_recovery'
    BASIC_BRIEFING = (
        '田地共64垄（0–63），每垄长268米、垄宽0.75米；玉米品种Grain_maize_201，种子标识MAIZE_201。\n'
        '辨别需要营养恢复的区域，完成针对性管理并复查，保护正常区域。仅完成当前管理窗口并复查，保留后续季节资源。'
    )

    def __post_init__(self):
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean: false or true")
        self._briefing_input_override = self.scenario_input
        super().__post_init__()

    def init_and_populate_apps(self):
        super().init_and_populate_apps()
        original_briefing = self.scenario_input
        if self._briefing_input_override:
            self.scenario_input = self._briefing_input_override
        elif not self.detailed_briefing:
            self.scenario_input = self.BASIC_BRIEFING
        if self.additional_system_prompt == original_briefing:
            self.additional_system_prompt = self.scenario_input


@register_scenario('scenario_maize_l2_zonal_water_priority')
class ScenarioMaizeL2ZonalWaterPriority(CropChallengeScenario):
    challenge_id = 'scenario_maize_l2_zonal_water_priority'
    BASIC_BRIEFING = (
        '田地共64垄（0–63），每垄长268米、垄宽0.75米；玉米品种Grain_maize_201，种子标识MAIZE_201。\n'
        '根据不同分区的实际水分状况安排灌溉，合理使用有限供水并保护正常区域。仅完成当前管理窗口并复查，保留后续季节资源。'
    )

    def __post_init__(self):
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean: false or true")
        self._briefing_input_override = self.scenario_input
        super().__post_init__()

    def init_and_populate_apps(self):
        super().init_and_populate_apps()
        original_briefing = self.scenario_input
        if self._briefing_input_override:
            self.scenario_input = self._briefing_input_override
        elif not self.detailed_briefing:
            self.scenario_input = self.BASIC_BRIEFING
        if self.additional_system_prompt == original_briefing:
            self.additional_system_prompt = self.scenario_input


@register_scenario('scenario_maize_l3_compound_water_n_limit')
class ScenarioMaizeL3CompoundWaterNLimit(CropChallengeScenario):
    challenge_id = 'scenario_maize_l3_compound_water_n_limit'
    BASIC_BRIEFING = (
        '田地共64垄（0–63），每垄长268米、垄宽0.75米；玉米品种Grain_maize_201，种子标识MAIZE_201。\n'
        '田间存在不同水分和营养状况。辨别各区需求，分别管理并复查。完成全季管理及安全入库，报告实际产量和投入。'
    )

    def __post_init__(self):
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean: false or true")
        self._briefing_input_override = self.scenario_input
        super().__post_init__()

    def init_and_populate_apps(self):
        super().init_and_populate_apps()
        original_briefing = self.scenario_input
        if self._briefing_input_override:
            self.scenario_input = self._briefing_input_override
        elif not self.detailed_briefing:
            self.scenario_input = self.BASIC_BRIEFING
        if self.additional_system_prompt == original_briefing:
            self.additional_system_prompt = self.scenario_input


@register_scenario('scenario_maize_l3_rain_aware_irrigation')
class ScenarioMaizeL3RainAwareIrrigation(CropChallengeScenario):
    challenge_id = 'scenario_maize_l3_rain_aware_irrigation'
    BASIC_BRIEFING = (
        '田地共64垄（0–63），每垄长268米、垄宽0.75米；玉米品种Grain_maize_201，种子标识MAIZE_201。\n'
        '结合天气预报和田间状况安排水分管理，在保护作物的同时节约用水。完成全季管理及安全入库，报告实际产量和投入。'
    )

    def __post_init__(self):
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean: false or true")
        self._briefing_input_override = self.scenario_input
        super().__post_init__()

    def init_and_populate_apps(self):
        super().init_and_populate_apps()
        original_briefing = self.scenario_input
        if self._briefing_input_override:
            self.scenario_input = self._briefing_input_override
        elif not self.detailed_briefing:
            self.scenario_input = self.BASIC_BRIEFING
        if self.additional_system_prompt == original_briefing:
            self.additional_system_prompt = self.scenario_input


@register_scenario('scenario_maize_l3_rainy_harvest_window')
class ScenarioMaizeL3RainyHarvestWindow(CropChallengeScenario):
    challenge_id = 'scenario_maize_l3_rainy_harvest_window'
    BASIC_BRIEFING = (
        '田地共64垄（0–63），每垄长268米、垄宽0.75米；玉米品种Grain_maize_201，种子标识MAIZE_201。\n'
        '根据各区作物、粮食和天气状况选择收获时机，完成安全收储。完成全季管理及安全入库，报告实际产量和投入。'
    )

    def __post_init__(self):
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean: false or true")
        self._briefing_input_override = self.scenario_input
        super().__post_init__()

    def init_and_populate_apps(self):
        super().init_and_populate_apps()
        original_briefing = self.scenario_input
        if self._briefing_input_override:
            self.scenario_input = self._briefing_input_override
        elif not self.detailed_briefing:
            self.scenario_input = self.BASIC_BRIEFING
        if self.additional_system_prompt == original_briefing:
            self.additional_system_prompt = self.scenario_input


@register_scenario('scenario_maize_l3_staggered_water_priority')
class ScenarioMaizeL3StaggeredWaterPriority(CropChallengeScenario):
    challenge_id = 'scenario_maize_l3_staggered_water_priority'
    BASIC_BRIEFING = (
        '田地共64垄（0–63），每垄长268米、垄宽0.75米；玉米品种Grain_maize_201，种子标识MAIZE_201。\n'
        '田间玉米分期播种。根据各区生育与水分状况安排管理并复查。完成全季管理及安全入库，报告实际产量和投入。'
    )

    def __post_init__(self):
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean: false or true")
        self._briefing_input_override = self.scenario_input
        super().__post_init__()

    def init_and_populate_apps(self):
        super().init_and_populate_apps()
        original_briefing = self.scenario_input
        if self._briefing_input_override:
            self.scenario_input = self._briefing_input_override
        elif not self.detailed_briefing:
            self.scenario_input = self.BASIC_BRIEFING
        if self.additional_system_prompt == original_briefing:
            self.additional_system_prompt = self.scenario_input


@register_scenario('scenario_maize_l3_zonal_nitrogen_recovery')
class ScenarioMaizeL3ZonalNitrogenRecovery(CropChallengeScenario):
    challenge_id = 'scenario_maize_l3_zonal_nitrogen_recovery'
    BASIC_BRIEFING = (
        '田地共64垄（0–63），每垄长268米、垄宽0.75米；玉米品种Grain_maize_201，种子标识MAIZE_201。\n'
        '辨别需要营养恢复的区域，完成针对性管理并复查，保护正常区域。完成全季管理及安全入库，报告实际产量和投入。'
    )

    def __post_init__(self):
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean: false or true")
        self._briefing_input_override = self.scenario_input
        super().__post_init__()

    def init_and_populate_apps(self):
        super().init_and_populate_apps()
        original_briefing = self.scenario_input
        if self._briefing_input_override:
            self.scenario_input = self._briefing_input_override
        elif not self.detailed_briefing:
            self.scenario_input = self.BASIC_BRIEFING
        if self.additional_system_prompt == original_briefing:
            self.additional_system_prompt = self.scenario_input


@register_scenario('scenario_maize_l3_zonal_water_priority')
class ScenarioMaizeL3ZonalWaterPriority(CropChallengeScenario):
    challenge_id = 'scenario_maize_l3_zonal_water_priority'
    BASIC_BRIEFING = (
        '田地共64垄（0–63），每垄长268米、垄宽0.75米；玉米品种Grain_maize_201，种子标识MAIZE_201。\n'
        '根据不同分区的实际水分状况安排灌溉，合理使用有限供水并保护正常区域。完成全季管理及安全入库，报告实际产量和投入。'
    )

    def __post_init__(self):
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean: false or true")
        self._briefing_input_override = self.scenario_input
        super().__post_init__()

    def init_and_populate_apps(self):
        super().init_and_populate_apps()
        original_briefing = self.scenario_input
        if self._briefing_input_override:
            self.scenario_input = self._briefing_input_override
        elif not self.detailed_briefing:
            self.scenario_input = self.BASIC_BRIEFING
        if self.additional_system_prompt == original_briefing:
            self.additional_system_prompt = self.scenario_input
