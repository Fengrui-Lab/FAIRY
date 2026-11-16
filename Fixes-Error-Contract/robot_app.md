# robot_app.py 错误与校验审阅

源文件：[fairy/apps/farm_world/robot_app.py](../fairy/apps/farm_world/robot_app.py)

覆盖 inspect_ridge、inspect_pests、inspect_crop_health、inspect_emergence、check_status、charge 共 6 个工具。最多覆盖 8 垄和 uncovered_ridges 已有明确返回，不将部分覆盖直接当成必须抛错。

已审阅入口：`inspect_ridge`（L116）、`inspect_pests`（L180）、`inspect_crop_health`（L202）、`inspect_emergence`（L224）、`check_status`（L244）、`charge`（L261）。

类型①：已有错误提示不清晰或不准确。类型②：缺少应在执行前完成的校验。P1：可能破坏状态；P2：影响行为或纠错；P3：提示可读性。

## 1. 【类型① / P3】范围及充电错误缺少恢复信息

- 位置：[129-134, 371-376](../fairy/apps/farm_world/robot_app.py#L129)。
- 现状/触发：范围错误不说明有效上界；charging 不给剩余时间；低电错误有阈值但没有充电入口。
- 建议：给动态垄范围、check_status/charge 指引和剩余充电时间，避免让 Agent 立即重复检查任务。

## 2. 【类型② / P1】垄号类型未在副作用前校验

- 位置：[129-142, 371-379](../fairy/apps/farm_world/robot_app.py#L129)。
- 现状/触发：实测 inspect_ridge(0.5) 通过范围检查，扣电 20% 并推进约 700 秒后 get_ridge 抛 TypeError。范围工具也未排除小数和 bool。
- 建议：严格整数验证并解析所有目标垄后才扣电/推进时间；非法输入返回具体参数 error，状态保持原值。

## 3. 【类型② / P1】缩减巡检范围后未复核保留电量

- 位置：[381-391](../fairy/apps/farm_world/robot_app.py#L381)。
- 现状/触发：分支判断要保留 10%，但缩减公式按全部电量计算可巡检垄数，没有减掉 10%。实测物理模式电量 15% 时 inspect_pests(0,7) 仍覆盖 3 垄，最后电量 0%，返回 ok。
- 建议：以 battery-10 计算可执行数量，并在扣电前再次验证成本；没有可执行垄时返回所需电量/当前电量 error，已有可执行垄则如实报告部分覆盖。

## 4. 【类型② / P1】legacy 巡检未验证观测字段可用性

- 位置：[389-391, 453-465](../fairy/apps/farm_world/robot_app.py#L389)。
- 现状/触发：全新默认 FarmWorldApp 的 RidgeState 没有 weed_pressure 字段。实测 inspect_pests(0,7) 在扣电和推进时间后抛 AttributeError；三个范围巡检共用此路径。
- 建议：在有副作用前解析可用观测能力；为 legacy 实现合法杂草观测来源，或明确拒绝该模式并返回能力不可用 error，不能把不存在字段当成可读状态。

## 验收重点

对上述触发输入确认返回非空字符串 `error`；拒绝发生在扣减资源、修改作物或推进时间之前。提示改动应与实际阈值一致，并覆盖修正后的合法调用。没有写明“实测”的项目为静态路径审阅结论。
