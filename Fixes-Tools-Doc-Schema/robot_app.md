# robot_app.py

源文件：[fairy/apps/farm_world/robot_app.py](/Users/hanlinyuan/Documents/Codex_Projects/FAIRY/fairy/apps/farm_world/robot_app.py)。共 6 个工具；以下为审阅稿。

## RobotApp.inspect_ridge

能力边界：对单垄进行地面病虫害复核，沿垄往返并返回检出结果及剩余电量，消耗电量和仿真时间；虫量是等级而非实际计数。

```python
"""
Description:
    Check a suspect ridge on the ground for aphids and leaf spot by walking its length
    and back. Requires >= 15% battery and no charging. Consume battery and simulation
    time; return detections and remaining battery. pest_count_estimate is a
    low/medium/high abundance band.

Relation:
    Use drone survey results to select a suspect ridge.

Args:
    ridge_id: Zero-based ID of an existing ridge.
"""
```

## RobotApp.inspect_pests

能力边界：对疑似虫害区域进行局部地面复核，同时返回病害、杂草和成苗情况。消耗电量和仿真时间，每次最多巡查前 8 垄；巡查不保证获得有效病虫草观测，零置信度检出不能视为确认无害；此限制不用于否定成苗比例。

```python
"""
Description:
    Check suspected pest problems locally on the ground. Requires >= 15% battery and no
    charging. Use battery and simulation time; return pest/disease/weed findings,
    confidence, stand_fraction (established plant fraction), visited ridges, and
    remaining battery.

    Visiting a ridge does not guarantee valid pest/disease/weed observations;
    zero-confidence detections are unconfirmed.

Relation:
    Use drone survey results to select a suspect range.

Args:
    start_ridge: Zero-based ID of the first existing ridge.
    end_ridge: Last existing ridge ID, inclusive; >= start_ridge. Requests may exceed 8
        ridges, but only the first 8 can be visited (fewer with low battery).
"""
```

## RobotApp.inspect_crop_health

能力边界：对局部作物健康问题进行地面复核，返回病虫草和成苗情况，不直接诊断缺水或缺肥。消耗电量和仿真时间，每次最多巡查前 8 垄；巡查不保证获得有效病虫草观测，零置信度检出不能视为确认无害；此限制不用于否定成苗比例。

```python
"""
Description:
    Check local crop-health concerns on the ground. Requires >= 15% battery and no
    charging. Use battery and simulation time; return pest/disease/weed findings,
    confidence, stand_fraction (established plant fraction), visited ridges, and
    remaining battery.

    Visiting a ridge does not guarantee valid pest/disease/weed observations;
    zero-confidence detections are unconfirmed. This does not diagnose water or nutrient
    stress.

Relation:
    Use drone survey results to select a suspect range.

Args:
    start_ridge: Zero-based ID of the first existing ridge.
    end_ridge: Last existing ridge ID, inclusive; >= start_ridge. Requests may exceed 8
        ridges, but only the first 8 can be visited (fewer with low battery).
"""
```

## RobotApp.inspect_emergence

能力边界：检查局部成苗情况，为缺苗补救提供依据，同时返回病虫草观测，不自动补种。消耗电量和仿真时间，每次最多巡查前 8 垄；巡查不保证获得有效病虫草观测，零置信度检出不能视为确认无害；此限制不用于否定成苗比例。

```python
"""
Description:
    Assess crop establishment on the ground to support replanting decisions. Requires >=
    15% battery and no charging. Use battery and simulation time; return
    pest/disease/weed findings, confidence, stand_fraction (established plant fraction),
    visited ridges, and remaining battery.

    Visiting a ridge does not guarantee valid pest/disease/weed observations;
    zero-confidence detections are unconfirmed.

Args:
    start_ridge: Zero-based ID of the first existing ridge.
    end_ridge: Last existing ridge ID, inclusive; >= start_ridge. Requests may exceed 8
        ridges, but only the first 8 can be visited (fewer with low battery).
"""
```

## RobotApp.check_status

能力边界：查看当前机器人电量、充电状态和设备信息，不推进仿真时间。

```python
"""
Description:
    Return this robot's battery, charging status, and identity. eta_minutes_to_full is
    the remaining simulation minutes to full charge, or null when not charging.
"""
```

## RobotApp.charge

能力边界：为机器人恢复后续作业所需电量，启动充电后立即返回状态和预计完成时间；当前充电周期为 60 个仿真分钟，调用本身不推进时间。

```python
"""
Description:
    Start recharging this robot for future inspections. Return charging status and
    estimated completion simulation time immediately, without advancing simulation time.
    Current charging duration: 60 simulation minutes.
"""
```
