# field_ops_app.py

源文件：[fairy/apps/farm_world/field_ops_app.py](/Users/hanlinyuan/Documents/Codex_Projects/FAIRY/fairy/apps/farm_world/field_ops_app.py)。共 5 个工具；以下为审阅稿。

## FieldOpsApp.irrigate_ridge

能力边界：灌溉一垄，消耗灌溉配额并推进作业所需仿真时间，返回用水量和效果复查时间；目标垄土壤体积含水率须低于 0.30。请求通过前置检查后，若目标垄有待生效灌溉，则返回已有 pending 状态，不启动新一轮灌溉。

```python
"""
Description:
    Irrigate one ridge within the water quota; every target ridge must have soil
    volumetric water fraction < 0.30. Advance simulation time for setup and irrigation;
    return water use and effect_ready_at (simulation timestamp for rechecking). For an
    otherwise valid request, pending irrigation on any target ridge returns
    irrigation_pending (existing irrigation awaiting its effect), without starting
    another irrigation run.

Relation:
    Check soil sensor readings before deciding to irrigate.

Args:
    ridge_id: Zero-based ID of an existing ridge.
    duration_hours: Irrigation duration in simulation hours; must be positive.
"""
```

## FieldOpsApp.irrigate

能力边界：同时灌溉连续垄，消耗灌溉配额并推进作业所需仿真时间，返回用水量和效果复查时间；目标垄土壤体积含水率须低于 0.30。作业时长不逐垄累加。请求通过前置检查后，若目标垄有待生效灌溉，则返回已有 pending 状态，不启动新一轮灌溉。

```python
"""
Description:
    Irrigate a contiguous ridge range together within the water quota; every target
    ridge must have soil volumetric water fraction < 0.30. Advance simulation time for
    setup and irrigation; return water use and effect_ready_at (simulation timestamp for
    rechecking). Equivalent to irrigate_range. For an otherwise valid request, pending
    irrigation on any target ridge returns irrigation_pending (existing irrigation
    awaiting its effect), without starting another irrigation run.

Relation:
    Check soil sensor readings before deciding to irrigate.

Args:
    start: Zero-based ID of the first existing ridge.
    end: Last existing ridge ID, inclusive; must be >= start.
    hours: Irrigation duration in simulation hours; must be positive. The same period
        applies to all target ridges, not a sum across them.
"""
```

## FieldOpsApp.irrigate_range

能力边界：同时灌溉连续垄，消耗灌溉配额并推进作业所需仿真时间，返回用水量和效果复查时间；目标垄土壤体积含水率须低于 0.30。作业时长不逐垄累加。请求通过前置检查后，若目标垄有待生效灌溉，则返回已有 pending 状态，不启动新一轮灌溉。

```python
"""
Description:
    Irrigate a contiguous ridge range together within the water quota; every target
    ridge must have soil volumetric water fraction < 0.30. Advance simulation time for
    setup and irrigation; return water use and effect_ready_at (simulation timestamp for
    rechecking). For an otherwise valid request, pending irrigation on any target ridge
    returns irrigation_pending (existing irrigation awaiting its effect), without
    starting another irrigation run.

Relation:
    Check soil sensor readings before deciding to irrigate.

Args:
    start: Zero-based ID of the first existing ridge.
    end: Last existing ridge ID, inclusive; must be >= start.
    duration_hours: Irrigation duration in simulation hours; must be positive. The same
        period applies to all target ridges, not a sum across them.
"""
```

## FieldOpsApp.apply_pesticide_manual

能力边界：用背负式喷雾器处理 1—2 条连续垄，直接消耗仓库农药，受喷洒天气和管理限制约束，可选择是否推进仿真时间。

```python
"""
Description:
    Spray insecticide with a backpack sprayer when weather and management rules allow.
    Use warehouse pesticide and optionally advance simulation time; return treated
    ridges and chemical use.

Relation:
    Use RobotApp.inspect_pests to assess a localized infestation before spraying.

Args:
    ridge_id: Zero-based ID of the first existing ridge to spray.
    liters_per_ridge: Insecticide volume per ridge in litres; positive, default 3.0.
    advance_time: Whether to advance simulation time for spraying; default True. False
        still applies and consumes pesticide.
    ridge_count: Number of adjacent ridges, 1 or 2; default 1. All must exist.
"""
```

## FieldOpsApp.get_irrigation_log

能力边界：查看该灌溉工具记录的历史，不提供当前土壤水分，也不包含其他工具的全部施水记录。

```python
"""
Description:
    Return this irrigation service's operation history, including treated ridges,
    simulation dates, and durations in simulation hours or seconds.
"""
```
