# scenario_full_season_baseline_balanced_season_v2.py 错误与校验审阅

源文件：[fairy/scenarios/farm_world_fullseason/scenario_full_season_baseline_balanced_season_v2.py](../fairy/scenarios/farm_world_fullseason/scenario_full_season_baseline_balanced_season_v2.py)

覆盖场景局部 DailyStateTraceApp.capture_daily_state；它同样有 @app_tool，不能在按 apps 目录扫描时漏掉。physics inactive 的显式返回不是错误。未发现类型①既有业务错误。

已审阅入口：`capture_daily_state`（L76）。

类型①：已有错误提示不清晰或不准确。类型②：缺少应在执行前完成的校验。P1：可能破坏状态；P2：影响行为或纠错；P3：提示可读性。

## 1. 【类型② / P2】快照开关和标签缺少类型校验

- 位置：[89-101, 148-149, 214-215](../fairy/scenarios/farm_world_fullseason/scenario_full_season_baseline_balanced_season_v2.py#L89)。
- 现状/触发：include_ridge_details="false" 为真值，仍输出全部垄明细；label 可接受非字符串。@type_check 不会阻止。
- 建议：推进物理前验证 include_ridge_details 为 bool、label 为 str，错误说明字段及收到类型。

## 验收重点

对上述触发输入确认返回非空字符串 `error`；拒绝发生在扣减资源、修改作物或推进时间之前。提示改动应与实际阈值一致，并覆盖修正后的合法调用。没有写明“实测”的项目为静态路径审阅结论。
