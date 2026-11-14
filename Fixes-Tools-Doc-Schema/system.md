# system.py

源文件：[fairy/apps/system.py](/Users/hanlinyuan/Documents/Codex_Projects/FAIRY/fairy/apps/system.py)。共 3 个工具；以下为审阅稿。

## SystemApp.get_current_time

能力边界：查询当前仿真时间，返回 UTC 日期时间、时间戳和星期，不推进时间。

```python
"""
Description:
    Return the current UTC simulation time as an epoch timestamp, a datetime (YYYY-MM-DD
    HH:MM:SS), and a weekday.
"""
```

## SystemApp.advance_time

能力边界：按给定总时长推进仿真时间，更新随时间变化的农场状态，返回推进时长和新的 UTC 时间。

```python
"""
Description:
    Advance simulation time and update time-dependent farm conditions. Return the
    elapsed simulation seconds and new UTC simulation time. The four duration components
    are added; their total must be positive.

Relation:
    Use get_current_time to calculate the duration needed to reach a target simulation
    time.

Args:
    seconds: Simulation seconds to add; default 0.
    minutes: Simulation minutes to add; default 0.
    hours: Simulation hours to add; default 0.
    days: Simulation days to add; default 0.
"""
```

## SystemApp.wait_for_notification

能力边界：等待下一条已安排的通知或超时，期间可推进仿真时间；工具返回空值，通知另行进入对话。默认不等待未来通知。

```python
"""
Description:
    Wait for the next scheduled notification, advancing simulation time up to the
    timeout. Return no value; any notification is delivered separately.

Args:
    timeout: Maximum simulation seconds to wait, >= 0; default 0 checks only for an
        already-due notification.
"""
```
