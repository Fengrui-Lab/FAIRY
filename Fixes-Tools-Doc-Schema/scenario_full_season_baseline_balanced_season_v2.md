# scenario_full_season_baseline_balanced_season_v2.py

源文件：[fairy/scenarios/farm_world_fullseason/scenario_full_season_baseline_balanced_season_v2.py](/Users/hanlinyuan/Documents/Codex_Projects/FAIRY/fairy/scenarios/farm_world_fullseason/scenario_full_season_baseline_balanced_season_v2.py)。共 1 个工具；以下为审阅稿。

## DailyStateTraceApp.capture_daily_state

能力边界：用于场景内参考流程（oracle）的内部状态追踪与评估，返回带标签的天气和当前仿真时间，不推进时间；启用土壤作物计算时另返回全田汇总及可选逐垄详情，信息范围大于普通监测。

```python
"""
Description:
    Capture internal farm state for scenario reference-workflow tracing and evaluation.
    Return labeled weather and current UTC simulation time without advancing it. Field
    summary and optional ridge details require physics_active to be true (soil/crop
    calculations enabled).

    VE/VC = emergence/cotyledon; V4_PLUS = fourth vegetative stage onward; ndvi_proxy =
    canopy greenness; stand_fraction = established plant fraction. days_after_planting
    counts simulation days.

Args:
    label: Your label for this snapshot; it does not select a date or saved record.
    include_ridge_details: Include individual ridge states as well as the field summary;
        default True.
"""
```
