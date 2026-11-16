# system.py 错误与校验审阅

源文件：[fairy/apps/system.py](../fairy/apps/system.py)

覆盖 get_current_time、advance_time、wait_for_notification 共 3 个工具。advance_time 文档只要求合计为正，因此混合正负分量不直接判缺陷。

已审阅入口：`get_current_time`（L38）、`advance_time`（L64）、`wait_for_notification`（L124）。

类型①：已有错误提示不清晰或不准确。类型②：缺少应在执行前完成的校验。P1：可能破坏状态；P2：影响行为或纠错；P3：提示可读性。

## 1. 【类型① / P3】时长错误缺输入和计算口径

- 位置：[95-96, 137-138](../fairy/apps/system.py#L95)。
- 现状/触发：advance_time amount must be >0 不说明四个分量合计后的秒数；Timeout must be non-negative 未给收到值。
- 建议：说明 seconds+60*minutes+3600*hours+86400*days 的总秒数及要求；timeout 给秒单位、非负整数约束和收到值。

## 2. 【类型② / P2】时长整数校验被强转和 assert 替代

- 位置：[92-94, 137-138](../fairy/apps/system.py#L92)。
- 现状/触发：实测 advance_time(seconds=1.9) 静默只前进 1 秒；timeout 也 int() 截断；assert 在 Python -O 下不执行。
- 建议：转换前执行严格整数检查，timeout 用显式条件返回 error；不要依赖 assert 维护 Agent 输入契约。

## 3. 【类型② / P1】缺少目标时间可表示性预检

- 位置：[97-119](../fairy/apps/system.py#L97)。
- 现状/触发：实测 advance_time(days=10**9) 先把时钟推进 86400000000000 秒，再在 datetime.fromtimestamp 报 year out of range。后续 Agent 格式化时间也可能失败。
- 建议：计算并验证目标时间和下游日期表示范围后再提交所有时钟/物理推进；错误说明最大可支持日期及本次目标，拒绝时不能改变时间。

## 验收重点

对上述触发输入确认返回非空字符串 `error`；拒绝发生在扣减资源、修改作物或推进时间之前。提示改动应与实际阈值一致，并覆盖修正后的合法调用。没有写明“实测”的项目为静态路径审阅结论。
