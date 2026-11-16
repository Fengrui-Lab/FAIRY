# drone_app.py 错误与校验审阅

源文件：[fairy/apps/farm_world/drone_app.py](../fairy/apps/farm_world/drone_app.py)

覆盖 fly_survey、check_status、charge 共 3 个工具。飞行中低电提前返航及 partial/warning 属于已说明的行为；重复充电和满电无需改成错误。

已审阅入口：`fly_survey`（L135）、`check_status`（L236）、`charge`（L255）。

类型①：已有错误提示不清晰或不准确。类型②：缺少应在执行前完成的校验。P1：可能破坏状态；P2：影响行为或纠错；P3：提示可读性。

## 1. 【类型① / P3】范围与飞行前置错误缺上下文

- 位置：[154-157, 302-310](../fairy/apps/farm_world/drone_app.py#L154)。
- 现状/触发：范围未给有效边界；充电错误未给 ETA；天气错误虽有 12 m/s 阈值，但未指出实际阻塞的是雨还是风。
- 建议：补充当前值、允许范围及 charge/check_status/天气查询和等待提示。

## 2. 【类型② / P2】飞行范围缺少整数校验

- 位置：[154-162](../fairy/apps/farm_world/drone_app.py#L154)。
- 现状/触发：0.5 等数值通过比较后在 range() 抛底层 TypeError；bool 被作为 0/1 接受。
- 建议：对两个端点做严格整数、顺序和上界校验，给参数名和输入值。

## 3. 【类型② / P2】无法完成任何一趟时缺少起飞前拒绝

- 位置：[158-186, 202-230, 304-305](../fairy/apps/farm_world/drone_app.py#L158)。
- 现状/触发：实测电量等于最低保留值 20% 时 fly_survey(0,0) 仍登记任务并消耗 30 秒，结果 partial 且 surveyed_ridges=[]。飞行前只比较 battery<minimum，未检查首趟成本。
- 建议：在起飞前校验首趟耗电加安全余量；零覆盖必然发生时返回所需电量/当前电量及充电建议。已有实际覆盖的途中返航继续使用 partial。

## 验收重点

对上述触发输入确认返回非空字符串 `error`；拒绝发生在扣减资源、修改作物或推进时间之前。提示改动应与实际阈值一致，并覆盖修正后的合法调用。没有写明“实测”的项目为静态路径审阅结论。
