# field_ops_app.py 错误与校验审阅

源文件：[fairy/apps/farm_world/field_ops_app.py](../fairy/apps/farm_world/field_ops_app.py)

覆盖 5 个工具。灌溉待生效返回 irrigation_pending 已明确说明等待，不因缺少 error 键单独判为缺陷。

已审阅入口：`irrigate_ridge`（L82）、`irrigate`（L105）、`irrigate_range`（L135）、`apply_pesticide_manual`（L173）、`get_irrigation_log`（L257）。

类型①：已有错误提示不清晰或不准确。类型②：缺少应在执行前完成的校验。P1：可能破坏状态；P2：影响行为或纠错；P3：提示可读性。

## 1. 【类型① / P3】垄号/范围错误缺有效边界

- 位置：[91-94, 120-123, 147-150, 193-203](../fairy/apps/farm_world/field_ops_app.py#L91)。
- 现状/触发：Invalid ridge_id/ridge range 不给 num_ridges、闭区间和起止顺序。
- 建议：说明 0<=ridge_id<num_ridges 或 0<=start<=end<num_ridges；数量必须为整数 1 或 2。

## 2. 【类型① / P2】喷药天气及库存错误缺少关键上下文

- 位置：[205-219](../fairy/apps/farm_world/field_ops_app.py#L205)。
- 现状/触发：天气只写 above spray limit，未给阈值和当前值；库存错误仅报 need，无 have。
- 建议：给出当前雨量、风速和严格阈值；库存给需要/剩余升数，并指向 get_inventory。

## 3. 【类型② / P1】缺少类型、有限数及提前验证

- 位置：[91-100, 120-130, 147-159, 193-224, 280-290](../fairy/apps/farm_world/field_ops_app.py#L91)。
- 现状/触发：duration_hours/hours 的 NaN 在 int() 才异常；ridge_count=1.9 会截断；advance_time="false" 仍推进时间。实测 apply_pesticide_manual(0.5) 先扣 3 L 再在 range() 抛 TypeError。
- 建议：先验证所有索引和计数为严格整数，布尔开关为 bool，时长/药量为有限正数，构造合法 ridge_ids 后再扣药及推进时间。

## 验收重点

对上述触发输入确认返回非空字符串 `error`；拒绝发生在扣减资源、修改作物或推进时间之前。提示改动应与实际阈值一致，并覆盖修正后的合法调用。没有写明“实测”的项目为静态路径审阅结论。
