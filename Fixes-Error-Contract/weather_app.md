# weather_app.py 错误与校验审阅

源文件：[fairy/apps/farm_world/weather_app.py](../fairy/apps/farm_world/weather_app.py)

覆盖 get_current_weather、get_forecast 共 2 个工具。get_forecast 的 1–7 截断及少于请求天数的结果已明确写入文档，不应据此增加越界错误。未发现类型①的独立业务提示问题。

已审阅入口：`get_current_weather`（L71）、`get_forecast`（L82）。

类型①：已有错误提示不清晰或不准确。类型②：缺少应在执行前完成的校验。P1：可能破坏状态；P2：影响行为或纠错；P3：提示可读性。

## 1. 【类型② / P2】days 的整数契约未执行

- 位置：[82-93](../fairy/apps/farm_world/weather_app.py#L82)。
- 现状/触发：int(days) 静默把 1.9 截为 1，也接受 true 和数值字符串；null/不可转字符串只产生底层转换异常。
- 建议：先验证 days 为整数且排除 bool，再保留文档规定的 1–7 clamp；错误写 days must be an integer，并回显值。

## 验收重点

对上述触发输入确认返回非空字符串 `error`；拒绝发生在扣减资源、修改作物或推进时间之前。提示改动应与实际阈值一致，并覆盖修正后的合法调用。没有写明“实测”的项目为静态路径审阅结论。
