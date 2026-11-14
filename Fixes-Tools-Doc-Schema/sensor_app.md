# sensor_app.py

源文件：[fairy/apps/farm_world/sensor_app.py](/Users/hanlinyuan/Documents/Codex_Projects/FAIRY/fairy/apps/farm_world/sensor_app.py)。共 4 个工具；以下为审阅稿。

## SensorApp.read_soil_sensors

能力边界：监测全田各固定传感器区域的土壤水分和温度，返回带测量误差的区域平均读数，不代表逐垄精确状态；传感器数量和覆盖范围以实际部署为准。

```python
"""
Description:
    Monitor soil conditions across field zones using fixed sensors. Return vwc
    (volumetric water fraction) and temp_c (Celsius) as zone averages, with possible
    measurement error. Current readings represent 5 cm depth.

    Default deployment: S1-S6 cover ridges 0-10, 11-21, 22-32, 33-43, 44-53, and 54-63
    respectively. Returned IDs and coverage reflect the active deployment.
"""
```

## SensorApp.read_canopy_sensors

能力边界：监测全田各固定传感器区域的冠层绿度，返回带测量误差的区域平均读数，不代表逐垄精确状态；传感器数量和覆盖范围以实际部署为准。

```python
"""
Description:
    Monitor canopy conditions across field zones using fixed sensors. Return ndvi_proxy
    (canopy greenness, 0-1; -1 = unavailable) as zone averages, with possible
    measurement error.

    Default deployment: C1-C6 cover ridges 0-10, 11-21, 22-32, 33-43, 44-53, and 54-63
    respectively. Returned IDs and coverage reflect the active deployment.
"""
```

## SensorApp.read_soil_sensor

能力边界：监测指定固定传感器区域的土壤水分和温度，返回带测量误差的区域平均读数，不代表逐垄精确状态；传感器数量和覆盖范围以实际部署为准。

```python
"""
Description:
    Monitor soil conditions across one sensor zone using fixed sensors. Return vwc
    (volumetric water fraction) and temp_c (Celsius) as zone averages, with possible
    measurement error. Current readings represent 5 cm depth.

Args:
    sensor_id: Existing sensor ID, case-sensitive; default IDs S1-S6. Get active IDs and
        coverage from read_soil_sensors.
"""
```

## SensorApp.read_canopy_sensor

能力边界：监测指定固定传感器区域的冠层绿度，返回带测量误差的区域平均读数，不代表逐垄精确状态；传感器数量和覆盖范围以实际部署为准。

```python
"""
Description:
    Monitor canopy conditions across one sensor zone using fixed sensors. Return
    ndvi_proxy (canopy greenness, 0-1; -1 = unavailable) as zone averages, with possible
    measurement error.

Args:
    sensor_id: Existing sensor ID, case-sensitive; default IDs C1-C6. Get active IDs and
        coverage from read_canopy_sensors.
"""
```
