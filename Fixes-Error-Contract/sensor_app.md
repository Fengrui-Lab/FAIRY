# sensor_app.py 错误与校验审阅

源文件：[fairy/apps/farm_world/sensor_app.py](../fairy/apps/farm_world/sensor_app.py)

覆盖 read_soil_sensors、read_canopy_sensors、read_soil_sensor、read_canopy_sensor 共 4 个工具及 _sync_sensors。无参数聚合读取未发现需新增业务拒绝的确定问题。

已审阅入口：`read_soil_sensors`（L79）、`read_canopy_sensors`（L108）、`read_soil_sensor`（L135）、`read_canopy_sensor`（L158）。

类型①：已有错误提示不清晰或不准确。类型②：缺少应在执行前完成的校验。P1：可能破坏状态；P2：影响行为或纠错；P3：提示可读性。

## 1. 【类型① / P3】未知传感器提示没有区分传感器类型及可用 ID

- 位置：[145-148, 168-171](../fairy/apps/farm_world/sensor_app.py#L145)。
- 现状/触发：两个工具都只给 Unknown sensor_id，误用 S1/C1 时缺少直接纠正信息。
- 建议：返回土壤或冠层传感器类型及当前真实 ID 集合，指出 read_soil_sensors/read_canopy_sensors。

## 2. 【类型② / P2】传感器 ID 类型未在同步前校验

- 位置：[145-148, 168-171](../fairy/apps/farm_world/sensor_app.py#L145)。
- 现状/触发：sensor_id 为 null/数组等时也先执行 _sync_sensors，之后按 Unknown sensor_id 返回；没有清楚区分类型错误与不存在。物理同步不必为非法请求执行。
- 建议：入口先要求字符串、查找目标 ID，失败给预期类型/允许集合，再进行传感器同步。

## 验收重点

对上述触发输入确认返回非空字符串 `error`；拒绝发生在扣减资源、修改作物或推进时间之前。提示改动应与实际阈值一致，并覆盖修正后的合法调用。没有写明“实测”的项目为静态路径审阅结论。
