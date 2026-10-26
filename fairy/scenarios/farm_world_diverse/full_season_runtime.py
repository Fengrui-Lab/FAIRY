"""旧自定义场景入口的兼容适配；八个正式场景均直接继承 Scenario。"""
from typing import ClassVar

from .scenario_multi_crop_full_season_mixed import (
    ScenarioMultiCropFullSeasonMixed, SeasonFarmPlan, SeasonSettings,
)


class FullSeasonMultiFarmScenario(ScenarioMultiCropFullSeasonMixed):
    """保留旧 Python 自定义农场入口，不作为正式场景的父类。"""

    scenario_id = ""
    farm_plans: ClassVar[tuple[SeasonFarmPlan, ...]] = ()
    season_settings = SeasonSettings()
    purpose = "Manage all farms for their entire crop season."
    management_objectives: ClassVar[tuple[str, ...]] = ()


__all__ = ["FullSeasonMultiFarmScenario"]
