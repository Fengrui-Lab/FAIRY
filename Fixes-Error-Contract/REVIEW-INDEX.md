# Agent 工具内容错误与缺失校验审阅

审阅日期：2026-11-16。基于当前工作区源码；只生成审阅文档，未修改业务代码。原有 [README.md](README.md) 保持不变。

## 范围与方法

全量扫描生产 Python 源码中的 `@app_tool` / `@agent_tool`，逐个检查工具正文及其直接相关校验、资源扣减和物理动作路径。测试中自定义的模拟工具不作为产品工具。按脚本单独记录；无两类问题的入口也在对应报告覆盖清单中列出。

共覆盖 **11 个工具定义脚本、59 个装饰工具**，另有 3 份共享调用/校验报告；共 **14 份逐脚本报告、42 项记录**。共享根因与具体工具落点有交叉，记录数不是独立缺陷数。

## 判定边界

- 继续使用现有 `{"error":"非空原因"}`，不要求新增对外字段；消息应包含参数/状态、当前值、允许范围或需要/可用量，以及合理的恢复动作。
- `@app_tool()` 只做标记，`@type_check` 当前不做检查。Agent 层包装异常能保证错误外形，但不能补全业务原因或撤销副作用。
- 文档明确允许的 forecast clamp、途中返航、8 垄部分巡检、重复充电、待灌溉生效、未干燥入库警告、专家限额部分返回，不因没有 error 键自动列为缺陷。
- 不根据农业常识凭空增加阈值；顺序、农具、收获后操作等发现以本仓库工具说明和现有状态模型为依据。
- 没有将场景设置/加载状态函数当成 Agent 入口；辅助函数问题按调用它的入口或共享根因归属。未穷举全部场景/历史坏状态，报告是源码审阅加针对性复现，不等于所有输入状态的形式化证明。

## 报告索引

| 脚本 | 工具数 | 类型① | 类型② | 报告 |
|---|---:|---:|---:|---|
| `fairy/apps/farm_world/tractor_app.py` | 23 | 4 | 9 | [tractor_app](tractor_app.md) |
| `fairy/apps/farm_world/farm_world_app.py` | 8 | 2 | 4 | [farm_world_app](farm_world_app.md) |
| `fairy/apps/farm_world/field_ops_app.py` | 5 | 2 | 1 | [field_ops_app](field_ops_app.md) |
| `fairy/apps/farm_world/robot_app.py` | 6 | 1 | 3 | [robot_app](robot_app.md) |
| `fairy/apps/farm_world/drone_app.py` | 3 | 1 | 2 | [drone_app](drone_app.md) |
| `fairy/apps/farm_world/sensor_app.py` | 4 | 1 | 1 | [sensor_app](sensor_app.md) |
| `fairy/apps/farm_world/weather_app.py` | 2 | 0 | 1 | [weather_app](weather_app.md) |
| `fairy/apps/system.py` | 3 | 1 | 2 | [system](system.md) |
| `fairy/apps/agent_user_interface.py` | 2 | 0 | 1 | [agent_user_interface](agent_user_interface.md) |
| `fairy/controllers/app_agent.py` | 2 | 0 | 1 | [app_agent](app_agent.md) |
| `fairy/scenarios/farm_world_fullseason/scenario_full_season_baseline_balanced_season_v2.py` | 1 | 0 | 1 | [scenario_full_season_baseline_balanced_season_v2](scenario_full_season_baseline_balanced_season_v2.md) |
| `fairy/utils/type_utils.py` | 0 | 0 | 1 | [type_utils](type_utils.md) |
| `fairy/tool_utils.py` | 0 | 0 | 1 | [tool_utils](tool_utils.md) |
| `fairy/agents/agent/agent.py` | 0 | 1 | 1 | [agent](agent.md) |

## 验证证据

通过 `.venv/bin/python -B` 在全新内存实例上执行探针，没有调用 LLM、没有运行远端实验、没有修改持久业务状态：

| 触发 | 实际结果 |
|---|---|
| STANDARD 装 10 粒后 EARLY_COLD 装 0 粒 | 返回 count error，但品种变为 EARLY_COLD、料斗仍有 10 粒 |
| STANDARD 装 10 粒后 EARLY_COLD 装 10 粒 | 成功，20 粒全部标为 EARLY_COLD |
| load_fertilizer("NaN") | 返回 ok；仓库与机载肥料均为 nan |
| Robot.inspect_ridge(0.5) | TypeError；已扣 20% 电并推进约 700 秒 |
| apply_pesticide_manual(0.5) | TypeError；已扣 3 L 药剂 |
| advance_time(seconds=1.9) | 成功，只推进 1 秒 |
| advance_time(days=10**9) | 日期超界 ValueError；时钟已推进 86400000000000 秒 |
| 新拖拉机 form_ridges(1.2) | 无整地前置/农具仍成功 |
| 未种植未收获时 incorporate_residue(0,0) | 成功并扣油、推进时间 |
| 空库 dry_grain() / store_grain() | 均返回 ok；前者设 grain_dried 和湿度 |
| physics inactive 时 apply_fertigation(0,0,1,5) | 返回 ok，扣 30 kg 肥料、记水额度，无水肥效果路径 |
| 肥料配额为 0、有库存时 load_fertilizer(1) | 错报 Insufficient fertilizer in warehouse |
| 满足整地条件、VWC=0.36 时 plant_seeds | 提示上界 0.30，而源码判定上界为 0.35 |
| send_message_to_user(None) | 原样接收并返回 None |
| 无人机 20% 电量 fly_survey(0,0) | 零覆盖 partial，仍消耗起飞时间 30 秒 |

另运行 `.venv/bin/python -B tests/test_error_contract.py -q`：**41 项通过**。该测试验证现有错误反馈协议；不能据此认为工具内部内容校验已经完整。

## 建议处理顺序

先处理类型/有限数的共同入口、装种原子性以及时间超界等 P1；随后补齐能力与业务前置条件；最后统一错误文本。每条错误路径都应验证拒绝前后资源、作物、时钟不变，正常路径仍符合既有语义。
