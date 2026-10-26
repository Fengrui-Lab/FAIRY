"""全季场景的兼容导出和 ID 清单；本文件不定义场景。

每个场景的真实定义在同目录下与其 scenario_id 同名的 .py 文件中。
例如三作物混合场景：scenario_multi_crop_full_season_mixed.py。
每个场景文件包含本地配置类型、初始化、Oracle 和验收的完整实现。
保留这些导出，使已有 Python import、CLI 与 Oracle 脚本继续可用。
"""
from __future__ import annotations

from .full_season_config import (
    FarmResources,
    FieldLayout,
    SeasonFarmPlan,
    SeasonSettings,
    SoilInitialState,
    WeatherSchedule,
)
from .full_season_runtime import FullSeasonMultiFarmScenario
from .scenario_multi_farm_full_season import ScenarioMultiFarmFullSeason
from .scenario_multi_farm_full_season_drought_priority import ScenarioMultiFarmFullSeasonDroughtPriority
from .scenario_multi_farm_full_season_staggered_windows import ScenarioMultiFarmFullSeasonStaggeredWindows
from .scenario_multi_farm_full_season_weather_risk import ScenarioMultiFarmFullSeasonWeatherRisk
from .scenario_multi_crop_full_season_maize import ScenarioMultiCropFullSeasonMaize
from .scenario_multi_crop_full_season_rice import ScenarioMultiCropFullSeasonRice
from .scenario_multi_crop_full_season_mixed import ScenarioMultiCropFullSeasonMixed
from .scenario_multi_crop_full_season_staggered import ScenarioMultiCropFullSeasonStaggered


FULL_SEASON_SCENARIO_IDS = (
    "scenario_multi_farm_full_season",
    "scenario_multi_farm_full_season_drought_priority",
    "scenario_multi_farm_full_season_staggered_windows",
    "scenario_multi_farm_full_season_weather_risk",
    "scenario_multi_crop_full_season_maize",
    "scenario_multi_crop_full_season_rice",
    "scenario_multi_crop_full_season_mixed",
    "scenario_multi_crop_full_season_staggered",
)


__all__ = [
    "FULL_SEASON_SCENARIO_IDS",
    "FullSeasonMultiFarmScenario",
    "FarmResources",
    "FieldLayout",
    "SeasonFarmPlan",
    "SeasonSettings",
    "SoilInitialState",
    "WeatherSchedule",
    "ScenarioMultiFarmFullSeason",
    "ScenarioMultiFarmFullSeasonDroughtPriority",
    "ScenarioMultiFarmFullSeasonStaggeredWindows",
    "ScenarioMultiFarmFullSeasonWeatherRisk",
    "ScenarioMultiCropFullSeasonMaize",
    "ScenarioMultiCropFullSeasonRice",
    "ScenarioMultiCropFullSeasonMixed",
    "ScenarioMultiCropFullSeasonStaggered",
]
