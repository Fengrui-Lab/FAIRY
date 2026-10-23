# 遗留问题

## TIME-001：旧单场的业务日期、天气日期与 Agent 显示时区不一致

- 状态：已确认，暂缓修复。2026-10-24 用户要求将其保留为遗留问题。
- 范围：当前注册的 310 个旧单场场景沿用公共旧路径；4 个新增多农场场景已显式配置 `Asia/Shanghai`，不属于本项的未迁移范围。
- 本次处理：登记问题，保留现有运行行为，没有修改天气或物理日界。
- 后续新增单场玉米场景显式配置 `Asia/Shanghai`；它不使用旧单场回退路径，也不属于本项的 310 个旧单场。

### 当前行为

旧单场 `FarmWorldApp`、`WeatherApp` 默认使用 UTC。没有 `FarmEnvironment` 时，`SystemApp` 也使用 UTC；Engine/Agent 的默认时间文本则使用北京时间。`WeatherApp` 返回的 `date` 只有日期，没有时区标记。

例如同一个时间戳，北京时间 `2026-05-08T07:00:00+08:00` 等于 UTC `2026-05-07T23:00:00+00:00`。两种时间表达本身正确；问题在于这些按北京时间定义的场景，仍按 UTC 的 5 月 7 日选择当天天气、执行物理日更新。天气切日要等到北京时间 08:00。

这并不意味着 310 个场景都会失败。影响取决于运行时刻、物理是否激活，以及播种、病虫、灌溉、收获等规则是否处在日期边界附近。

### 已确认的影响

`scenario_full_season_adversarial_weather` 在北京时间 5 月 8 日 07:00 播种时，物理日期仍为 5 月 7 日，使用寒潮最后一天的天气；目标 0–3 垄平均土温约 6.426°C，低于 `EARLY_COLD` 的 8°C 作业门槛，播种被拒绝。通过正常工具再推进 1 小时，跨过 UTC 日界后，物理进入 5 月 8 日，土温约 9.876°C，相同参数的播种成功。这是每日模型切换导致的结果，不能解释为现实土壤一小时自然升温约 3.5°C。

### 代码入口

- `fairy/apps/farm_world/farm_world_app.py`：默认时区、`simulation_date()`。
- `fairy/apps/farm_world/weather_app.py`：默认时区、`advance_to_timestamp()`。
- `fairy/apps/farm_world/physics_orchestrator.py`：日界、天气与每日模型推进。
- `fairy/apps/system.py`：没有 `FarmEnvironment` 时的时区回退。
- `fairy/controllers/engine.py`、`fairy/agents/agent/base_agent.py`：时间格式化与 Agent 时区。
- `fairy/apps/farm_world/farm_environment.py`：已迁移多农场的时区传播入口。

### 后续修复与验收要求

1. 用场景显式声明的业务时区统一天气、物理、System、Agent、回放；时区不能由农场数量决定。
2. 保持 Unix 时间戳的同一时刻语义，审查旧快照的日期、日更新游标和物理时间；不能仅重写显示文本或给旧状态补一个时区标签。
3. 覆盖北京时间 00:00、07:59、08:00、跨日作业、同日重复读取，以及保存后在新实例中回放。
4. 对全部旧单场重新执行兼容性审查。天气、物理和产量变化可能是修复的预期结果，应与新增执行失败分开解释。
5. 重新生成受此影响的 Oracle 与优化搜索结果，不能继续把旧时区结果认作修复后的基准。

### 本地审计证据

- `validation_runs/planting_failure_audit_20261024/adversarial_prefix_result.json`：真实公开工具前缀与推进 1 小时的复现。
- `validation_runs/all_single_farm_compat_20261024/REPORT.md`：310 个旧单场的营养字段修复前后兼容性审查；这不是时区修复后的验收。

`validation_runs/` 被仓库忽略，上述运行产物保留在本机，不随 Git 提交。问题本身、复现条件与验收要求由本文件保存。
