# FAIRY

[English README](README.md)

FAIRY 是一个独立的农场智能体仿真运行时，用于 FARM 场景执行、oracle
工作流生成、回放和评估。它把原先嵌在 ARE 里的 FARM 业务逻辑迁移成独立的
`fairy` Python 包，并保留 FarmAgent 风格的轻量控制器和 OpenAI-compatible
function calling 工具调用路径。

FAIRY 面向可复现实验：同一个场景可以初始化、生成 oracle workflow、在干净
场景状态上回放，再基于 workflow 和物理状态输出评估报告。

## 核心能力

- 独立 `fairy` Python 包，不再依赖 ARE runtime imports。
- Farm-world 应用：天气、传感器、无人机、机器人、拖拉机、田间作业、库存、
  时间控制和用户消息。
- FARM 物理引擎：土壤水分、天气、物候、冠层和生物量、管理措施效应、生物
  压力、观测模型和 recovered yield。
- FarmAgent baseline 场景、ARE action-tick 物理场景和 L3 full-season 场景。
- Oracle workflow 生成，保留稳定 JSON 结构：
  `name`、`content`、`op_type`、`tool_name`、`tool_args`、`depends_on`、`time`。
- 在全新场景状态上回放 workflow。
- 生成 oracle sequence matching 和场景 validate 的 evaluation report。
- 支持 DeepSeek、OpenAI 等 OpenAI-compatible chat completion provider 的
  function calling。
- 控制器家族包括 ReAct 风格、planner-executor、ReWOO 风格、reflective memory、
  verifier、tree-search、critic-refiner 和 graph-memory 等。

## 仓库结构

```text
fairy/
  agents/        LLM client、tool-calling loop、消息管理
  apps/          App 基类、SystemApp、FarmWorld apps
  controllers/   Engine、场景运行时、回放/评估、控制器家族
  physics/       FARM 物理引擎和 profiles
  scenarios/     Scenario 基类、registry、FARM 场景集
scripts/         CLI 入口
tests/           迁移、oracle、回放和控制器 smoke tests
docs/ai/         维护者笔记：执行路径和测试命令
```

## 安装

FAIRY 目前面向 Python 3.10 或更高版本。在仓库根目录执行：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

在原 FARM checkout 中做本地开发时，也可以直接使用现有 Python 3.12 环境：

```bash
PYTHONPATH=. /Users/quao/Desktop/Second-year/CWSN/FarmARE_physics/.venv312/bin/python scripts/run_scenario.py --list
```

## 快速开始

列出已迁移场景：

```bash
fairy-run --list
```

列出可用控制器家族：

```bash
fairy-run --list-controllers
```

生成 oracle workflow、在干净状态上回放，并输出评估：

```bash
fairy-run \
  -s scenario_farm_world_field_prep_physics_action_tick \
  --build-oracle --replay --evaluate \
  --workflow validation_runs/fairy_smoke/oracle_baselines/scenario_farm_world_field_prep_physics_action_tick.json \
  --output-dir validation_runs/fairy_smoke/oracle_replay/scenario_farm_world_field_prep_physics_action_tick
```

该命令会写出一个 run bundle。先打开 `*.run_report.json`，它会说明运行状态、
指标、评估、结果和每个产物文件的用途：

```text
validation_runs/fairy_smoke/oracle_baselines/scenario_farm_world_field_prep_physics_action_tick.json
validation_runs/fairy_smoke/oracle_replay/scenario_farm_world_field_prep_physics_action_tick/scenario_farm_world_field_prep_physics_action_tick.run_report.json
validation_runs/fairy_smoke/oracle_replay/scenario_farm_world_field_prep_physics_action_tick/scenario_farm_world_field_prep_physics_action_tick.events.jsonl
validation_runs/fairy_smoke/oracle_replay/scenario_farm_world_field_prep_physics_action_tick/scenario_farm_world_field_prep_physics_action_tick.replay.json
validation_runs/fairy_smoke/oracle_replay/scenario_farm_world_field_prep_physics_action_tick/scenario_farm_world_field_prep_physics_action_tick.evaluation.json
```

运行 L3 full-season 端到端 smoke：

```bash
fairy-run \
  -s scenario_full_season_balanced \
  --build-oracle --replay --evaluate \
  --workflow validation_runs/fairy_l3/oracle_baselines/scenario_full_season_balanced.json \
  --output-dir validation_runs/fairy_l3/oracle_replay/scenario_full_season_balanced
```

运行真实 DeepSeek function-calling agent，并设置真实耗时和工具调用上限：

```bash
fairy-run \
  -s scenario_full_season_balanced \
  --agent \
  --controller farm_baseline_react \
  --provider deepseek \
  --model deepseek-chat \
  --temperature 0.2 \
  --max-tool-calls 300 \
  --timeout-seconds 1200 \
  --output-dir validation_runs/fairy_l3/phase5_paper_matrix/farm_baseline_react__scenario_full_season_balanced__r1
```

## 运行模型

FAIRY 使用统一场景入口：

```python
scenario.setup()
```

迁移代码仍可使用兼容入口：

```python
scenario.initiate_scenario()
scenario.init_and_populate_apps()
```

核心执行链路是：

```text
Scenario.setup()
  -> Engine.build_oracle_workflow()
  -> Workflow.save_workflow()
  -> fresh Engine.replay_workflow()
  -> Engine.evaluation_report()
```

智能体运行路径采用 OpenAI-compatible function calling：

```text
ControllerAgent.run()
  -> chat.completions.create(..., tools=[...])
  -> message.tool_calls
  -> AppName__method(**tool_args)
  -> 记录 workflow step
```

工具命名保持为：

```text
AppName__method_name
```

## 场景

FAIRY 包含三类已迁移 FARM 场景：

- Baseline farm-world 场景，例如整地、播种、灌溉、病虫害响应、无人机巡田和
  收获。
- Physics action-tick 场景，工具动作会推动农场物理和时间状态。
- L3 full-season 场景，包括 balanced season、adverse weather、aphid pressure、
  dry pod-fill、wet June disease pressure、resource-limited、nutrient differential
  和 Tangyan5 calibration 场景。

示例场景 ID：

```text
scenario_farm_world_field_prep
scenario_farm_world_field_prep_physics_action_tick
scenario_farm_world_harvest_physics_action_tick
scenario_full_season_balanced
scenario_full_season_dry_pod_fill
scenario_tangyan5_base_full_season
```

## 物理与产量恢复

FAIRY 保留了迁移 FARM 场景使用的物理模型。Full-season 链路包括：

- 每日土壤和天气更新，
- 物候和成熟期，
- 冠层、生物量和 biological yield potential，
- 播种、灌溉、施肥、施药、收获等管理措施效应，
- 生物压力，
- 籽粒水分，
- field loss，
- machine/header loss，
- recovered yield，
- 烘干和入库状态。

Recovered-yield 状态包含：

```text
biological_yield_g_m2
field_loss_fraction
machine_loss_fraction
recovered_yield_g_m2_at_market_moisture
recovered_yield_kg_ha_at_market_moisture
quality_discount_fraction
```

最终粮食库存通过 farm inventory 暴露：

```text
harvest_grain_kg
warehouse_grain_kg
grain_dried
```

## 评估

当前评估支持：

- physics action-tick 场景的 oracle sequence matching，
- 场景自带 `validate(env)` hook，
- replay report，包括 workflow step 数、matched tools、missing tools、score、
  threshold 和 environment metadata，
- L3 full-season 的回放和验证入口。

评估报告以 JSON 写出，可以直接接入实验流水线。

## 运行产物与日志

FAIRY 使用 FARM 原来的实验布局：

```text
validation_runs/<phase>/phase5_paper_matrix/<agent_family>__<scenario_id>__r<repeat>/
validation_runs/<phase>/oracle_baselines/<scenario_id>.json
validation_runs/<phase>/oracle_replay/<scenario_id>/
```

每个 cell 目录是一个 bundle。正常看实验时，只需要先看 cell 里的两个文件：

```text
*.run_report.json   首要入口：运行状态、停止原因、限制、wall time、token 汇总、
                    evaluation、outcome、错误和产物解释
*.events.jsonl      真正的运行时事件流：agent、LLM、tool、limit、error 事件，
                    按时间顺序逐行记录
```

深度调试文件单独保留：

```text
*.agent_workflow.json   可回放/审计的 workflow：工具名、参数、结果、依赖、
                        仿真时间
*.messages.json         原始 LLM 对话和 tool response
*.runtime_metrics.json  每次 LLM/tool 调用的耗时和 token 明细
*.evaluation.json       验证结果和 FARM outcome summary
*.run_summary.json      兼容旧脚本的机器摘要
*.run_log.jsonl         oracle/replay 的 tool-only 日志
```

如果 agent 因为 `--timeout-seconds` 或 `--max-tool-calls` 停止，仍然会写出
`run_report.json` 和 `events.jsonl`。报告中会有 `status`、`stopped_reason`、
`limits`、`metrics` 和 `error`；事件流中会有 `agent_limit_exceeded` 和最终
`agent_run_error`。LLM 接口错误会记录为 `llm_call_error`；function-call 参数
JSON 解析失败会记录为 `tool_args_parse_error`；工具执行异常会记录为
`tool_call_error`。

多个场景一起跑完后，用这个脚本生成总表：

```bash
PYTHONPATH=. python scripts/summarize_runs.py validation_runs/<phase> --csv validation_runs/<phase>/summary.csv
```

## LLM Provider

FAIRY 的 agent path 是 function-call based。DeepSeek 通过 OpenAI-compatible
client 支持：

```bash
export DEEPSEEK_API_KEY=...
```

之后可以直接用 `fairy-run --agent ...` 运行，也可以在用户代码中用 DeepSeek
client 和场景 apps 构造 controller agent。

## 测试

运行迁移 smoke suite：

```bash
PYTHONPATH=. python -m pytest tests/test_fairy_migration_smoke.py -q
```

检查 runtime 代码不再导入 ARE 或 rsare：

```bash
rg "from are\.|import are\.|from rsare\.|import rsare\." fairy tests
```

Smoke suite 覆盖：

- 模块导入检查，
- 场景 registry 检查，
- baseline oracle workflow 检查，
- physics action-tick oracle 检查，
- full-season oracle 检查，
- `SystemApp.advance_time()` 触发物理更新，
- 控制器家族构建，
- oracle build、workflow replay 和 evaluation。

## 发布状态

FAIRY v1 已经可以作为独立 FARM 场景运行时和评估基础设施使用。FARM 业务
逻辑、物理引擎、控制器、场景、oracle workflow 生成、回放和评估入口已经打包
进独立的 `fairy` runtime。

产品路线图包括：更严格的 L3 outcome metrics、更完整的 yield-loss 评估摘要、
packaging metadata、CI 和公开 API 文档。
