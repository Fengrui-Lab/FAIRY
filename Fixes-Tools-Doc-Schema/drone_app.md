# drone_app.py

源文件：[fairy/apps/farm_world/drone_app.py](/Users/hanlinyuan/Documents/Codex_Projects/FAIRY/fairy/apps/farm_world/drone_app.py)。共 3 个工具；以下为审阅稿。

## DroneApp.fly_survey

能力边界：对目标垄进行空中筛查，返回冠层绿度、温度、覆盖垄和电量，不直接诊断原因。当前要求未充电、无雨、风速 <12 m/s，且达到本机最低电量；该门槛因实例而异，check_status 未返回。消耗电量及仿真时间，覆盖可能不完整，ndvi=-1 表示不可用。

```python
"""
Description:
    Screen target ridges from the air for canopy variation. Currently requires no
    charging, no rain, wind < 12 m/s, and battery at or above this drone's configured
    minimum. This instance-specific minimum is not exposed by check_status. Consume
    battery and simulation time; return surveyed ridges, NDVI (canopy greenness; -1 =
    unavailable), canopy temperature, and remaining battery. Low battery may limit
    coverage; readings do not diagnose causes.

Relation:
    Use check_status to assess the drone battery before flight.

Args:
    start_ridge: Zero-based ID of the first existing ridge.
    end_ridge: Last existing ridge ID, inclusive; must be >= start_ridge.
"""
```

## DroneApp.check_status

能力边界：查看当前无人机电量、充电状态和设备信息，不推进仿真时间。

```python
"""
Description:
    Return this drone's battery, charging status, and flight speed and ridge coverage
    per pass. eta_minutes_to_full is the remaining simulation minutes to full charge, or
    null when not charging.
"""
```

## DroneApp.charge

能力边界：为无人机恢复后续作业所需电量，启动充电后立即返回状态和预计完成时间；当前充电周期为 30 个仿真分钟，调用本身不推进时间。

```python
"""
Description:
    Start recharging this drone for future flights. Return charging status and estimated
    completion simulation time immediately, without advancing simulation time. Current
    charging duration: 30 simulation minutes.
"""
```
