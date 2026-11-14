# weather_app.py

源文件：[fairy/apps/farm_world/weather_app.py](/Users/hanlinyuan/Documents/Codex_Projects/FAIRY/fairy/apps/farm_world/weather_app.py)。共 2 个工具；以下为审阅稿。

## WeatherApp.get_current_weather

能力边界：提供当前天气信息，辅助判断作业时机，返回气象站日期及气温、湿度、风速、降雨和太阳辐射，不直接批准作业。

```python
"""
Description:
    Provide current farm weather to assess field-work timing. Return the recorded
    simulation date, temperature, humidity, wind speed, rainfall, and solar radiation.
    This does not authorize an operation.
"""
```

## WeatherApp.get_forecast

能力边界：提供未来天气信息以辅助安排作业，返回现有预报中请求时段的数据；天数限制到 1—7，数据不足时返回更少，不保证届时可作业。

```python
"""
Description:
    Support field-work planning with available weather forecasts for the requested
    simulation period; forecasts do not guarantee operating conditions.

Args:
    days: Requested number of simulation days; clamped to 1-7, default 7. Fewer entries
        may be available.
"""
```
