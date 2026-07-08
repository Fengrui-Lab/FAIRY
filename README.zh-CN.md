# FAIRY

[English README](README.md)

FAIRY 是一个农场智能体仿真运行时，用于执行 FARM 场景、通过 OpenAI-compatible function calling 暴露农场操作工具、推进天气/土壤/作物生长/产量恢复等物理过程，并生成紧凑的 run bundle，用于检查 workflow、重放轨迹和计算 FOS/yield loss。

## 系统定位

FAIRY 面向 FARM 场景的可执行实验运行。一次运行由以下输入决定：

| 输入 | 含义 |
|---|---|
| `scenario_id` | FARM 场景。定义初始农场状态、可用 app、任务目标和验证规则。 |
| `controller_id` | agent 控制器。定义 ReAct、ReWOO、planner、verifier、critic、memory、graph-memory 等运行策略。 |
| `provider` / `model` | OpenAI-compatible function calling 模型服务。 |
| `scenario_kwargs` | 场景构造参数，例如 full-season 的 detailed context 模式。 |
| `limits` | 运行边界，例如最大工具调用数和 wall-clock timeout。 |
| `output_dir` | 单次运行的完整产物目录。 |

主要输出是 run bundle。默认入口文件是：

```text
<output_dir>/<scenario_id>.run_report.json
```

`run_report.json` 是单次运行的索引文件，包含运行状态、停止原因、token/tool 统计、评估摘要、错误摘要以及所有产物路径。

## 运行模式

| 模式 | 命令参数 | 输入 | 输出 | 用途 |
|---|---|---|---|---|
| Agent run | `--agent` | 场景、控制器、模型 | `run_report.json`, `runtime_log.jsonl`, `agent_workflow.json` | 执行真实 function-calling agent。 |
| Oracle build | `--build-oracle` | 场景 | `oracle.json` | 导出场景内置 reference workflow。 |
| Workflow replay | `--replay --workflow <file>` | 任意 workflow JSON | `replay.json`, `runtime_log.jsonl`, `run_report.json` | 在全新场景状态中重放 workflow。 |
| Evaluation | `--replay --evaluate --workflow <file>` | 任意 workflow JSON | `run_report.json` | 对 replay 后的 workflow 和农场状态执行场景验证。 |
| Batch run | `scripts/iclr_validation_runner.py` | controller 集合、scenario 集合 | `results.csv` 和每个 cell 的 run bundle | 执行 controller × scenario 矩阵。 |
| FOS rebatch | `scripts/rebatch_fos_from_traces.py` | FAIRY agent run bundles、oracle baselines | `summary_v2.csv` | 从已有 `agent_workflow.json` run 重新计算 FOS、yield loss 和错误列。 |

## 安装和环境准备

FAIRY 是一个 Python 包。新 clone 下来的仓库需要先准备 Python 环境和依赖，不能假设裸环境直接运行。

要求：

- Python 3.10 或更高版本。
- 推荐使用 `uv` 管理本地环境。
- 只有真实 `--agent` run 需要模型 API key。oracle/replay/evaluate 不调用 LLM。

使用 `uv` 安装：

```bash
cd /path/to/FAIRY
uv sync
```

如果没有安装 `uv`：

```bash
python -m pip install uv
uv sync
```

不用 `uv` 的安装方式：

```bash
cd /path/to/FAIRY
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

配置真实 agent 所需模型 key：

```bash
export DEEPSEEK_API_KEY=<your_key>
# 或
export OPENAI_API_KEY=<your_key>
```

检查环境是否可用：

```bash
PYTHONPATH=. uv run python -m fairy.cli --list-controllers
PYTHONPATH=. uv run pytest -q tests/test_fairy_migration_smoke.py
```

## 快速开始

### 1. 执行真实 agent

该命令运行一个小型 FARM baseline 场景，使用 DeepSeek function calling，并把所有产物写入一个独立 run 目录。

```bash
PYTHONPATH=. uv run python -m fairy.cli \
  -s scenario_farm_world_field_prep \
  --agent \
  --controller farm_baseline_react \
  --provider deepseek \
  --model deepseek-chat \
  --temperature 0.1 \
  --max-tool-calls 20 \
  --timeout-seconds 300 \
  --output-dir validation_runs/quickstart/agent/farm_baseline_react__scenario_farm_world_field_prep__r1
```

运行完成后读取：

```text
validation_runs/quickstart/agent/farm_baseline_react__scenario_farm_world_field_prep__r1/scenario_farm_world_field_prep.run_report.json
```

关键字段：

| 字段 | 含义 |
|---|---|
| `status` | `completed`、`stopped` 或 `failed`。 |
| `stopped_reason` | 停止原因，例如 `completed`、`max_tool_calls`、`timeout`、`error`。 |
| `metrics.token_usage` | 模型 token 使用量。 |
| `metrics.tool_call_count` | 实际工具调用数。 |
| `evaluation` | 场景验证摘要。 |
| `artifacts` | 本次运行所有输出文件路径。 |

Agent run 的详细产物按以下顺序检查：

```text
1. <scenario>.run_report.json      # 总览：成功/失败、耗时、token、工具次数、评估、农场结果
2. <scenario>.runtime_log.jsonl    # 完整 prompt/messages、模型调用、工具调用、错误、超限
3. <scenario>.agent_workflow.json  # agent 实际做了哪些工具步骤
```

如果 `status=stopped` 且 `stopped_reason=max_tool_calls`，说明运行达到 `--max-tool-calls` 上限。需要更长轨迹时提高该参数。

### 2. 离线验证场景和 oracle/replay/evaluate 链路

该命令不调用 LLM。它导出 reference workflow，将该 workflow 在全新场景中重放，并执行场景验证。

```bash
PYTHONPATH=. uv run python -m fairy.cli \
  -s scenario_farm_world_field_prep_physics_action_tick \
  --build-oracle --replay --evaluate \
  --workflow validation_runs/quickstart/oracle/scenario_farm_world_field_prep_physics_action_tick.json \
  --output-dir validation_runs/quickstart/oracle_replay/scenario_farm_world_field_prep_physics_action_tick
```

运行完成后读取：

```text
validation_runs/quickstart/oracle_replay/scenario_farm_world_field_prep_physics_action_tick/scenario_farm_world_field_prep_physics_action_tick.run_report.json
```

关键字段：

- `status=completed`：这条 oracle/replay/evaluate 跑通了。
- `evaluation.validation.success=true`：场景验证通过。
- `artifacts.oracle_workflow`：标准答案 workflow 在哪里。
- `artifacts.replay_workflow`：重放后的 workflow 在哪里。
- `evaluation`：验证明细和农场结果摘要。

### 3. 执行 full-season 场景并切换 context 模式

full-season 的 detailed context 通过 `--scenario-kwargs` 传入场景构造器。

```bash
PYTHONPATH=. uv run python -m fairy.cli \
  -s scenario_full_season_hb_base_hn84_std_normal \
  --agent \
  --controller farm_baseline_react \
  --provider deepseek \
  --model deepseek-chat \
  --scenario-kwargs '{"detailed_briefing": false}' \
  --max-tool-calls 300 \
  --timeout-seconds 1200 \
  --output-dir validation_runs/quickstart/fullseason/detail_false
```

`detailed_briefing` 完整取值：

| 取值 | JSON 写法 | 含义 | 额外依赖 |
|---|---|---|---|
| `false` | `{"detailed_briefing": false}` | 只使用基础 L3 prompt，不注入额外 detail/context。 | 无 |
| `true` | `{"detailed_briefing": true}` | 使用场景自带的人工 detailed briefing。 | 场景内置 `detailed_briefing_text` |
| `kwoo` | `{"detailed_briefing": "kwoo"}` | 在基础 prompt 后追加 Kwoo 生成的 expert context。 | `FARM_FAIRY_KWOO_CONTEXT_PATH` 指向 Kwoo JSON/text |
| `library` | `{"detailed_briefing": "library"}` | 在基础 prompt 后追加同 L3 的结构化 L2 skill library。不是 Python 包；文件来自 `knowledge_library_pilot/<scenario_slug>/library_same_l3.md`。 | 该场景必须在 `knowledge_library_pilot` 下有 `library_same_l3.md` |
| `l2_human_same` | `{"detailed_briefing": "l2_human_same"}` | 注入同 source L3 的人工/结构化 L2 skill context。 | `knowledge_library_pilot` 中同 L3 skill JSON |
| `l2_human_differ` | `{"detailed_briefing": "l2_human_differ"}` | 注入其他 L3 source 转移来的人工/结构化 L2 skill context。 | `knowledge_library_pilot` cross-L3 skill JSON |
| `l2_textsim_differ` | `{"detailed_briefing": "l2_textsim_differ"}` | 注入文本相似度检索到的跨 L3 L2 skills。 | 已生成的 retrieval context |
| `l2_textsim_grouped_differ` | `{"detailed_briefing": "l2_textsim_grouped_differ"}` | 文本相似度检索跨 L3 L2 skills，并按 establishment/management/harvest 分组配额。 | 已生成的 retrieval context |
| `l2_pathsim_differ` | `{"detailed_briefing": "l2_pathsim_differ"}` | 注入 workflow/path 相似度检索到的跨 L3 L2 skills。 | `FARM_FAIRY_RETRIEVED_CONTEXT_PATH` 指向 retrieval JSON |
| `l2_pathsim_grouped_differ` | `{"detailed_briefing": "l2_pathsim_grouped_differ"}` | workflow/path 相似度检索跨 L3 L2 skills，并按农事阶段分组配额。 | `FARM_FAIRY_RETRIEVED_CONTEXT_PATH` |
| `l3_pathsim_same` | `{"detailed_briefing": "l3_pathsim_same"}` | 注入 workflow/path 相似度检索到的同 L3 reference context。 | `FARM_FAIRY_RETRIEVED_CONTEXT_PATH` |
| `l3_pathsim_differ` | `{"detailed_briefing": "l3_pathsim_differ"}` | 注入 workflow/path 相似度检索到的跨 L3 reference context。 | `FARM_FAIRY_RETRIEVED_CONTEXT_PATH` |
| `l3_textsim_differ` | `{"detailed_briefing": "l3_textsim_differ"}` | 注入文本相似度检索到的跨 L3 reference context。 | `FARM_FAIRY_RETRIEVED_CONTEXT_PATH` |
| `l3_textdiff_differ` | `{"detailed_briefing": "l3_textdiff_differ"}` | 兼容旧实验命名；运行时规范化为 `l3_textsim_differ`。 | `FARM_FAIRY_RETRIEVED_CONTEXT_PATH` |

`iclr_validation_runner.py --detail <value>` 会把同样的值自动合并进 `--scenario-kwargs` 的 `detailed_briefing` 字段。

### 4. 执行 controller × scenario 批量运行

批量实验使用 validation runner。每个 controller/scenario/repeat cell 会生成一个独立 run bundle。

```bash
PYTHONPATH=. uv run python scripts/iclr_validation_runner.py \
  --phase smoke \
  --output-root validation_runs/quickstart/batch/phase5_paper_matrix \
  --families farm_baseline_react,farm_rewoo_modular \
  --scenarios scenario_farm_world_field_prep,scenario_farm_world_planting \
  --repeats 1 \
  --provider deepseek \
  --model deepseek-chat \
  --max-concurrent 1 \
  --cell-timeout-s 600 \
  --agent-max-iterations 100 \
  --cost-cap-dollars 5
```

运行完成后读取：

```text
validation_runs/quickstart/batch/phase5_paper_matrix/results.csv
```

`results.csv` 完整列：

| 列 | 含义 |
|---|---|
| `family` | controller id。 |
| `scenario` | scenario id。 |
| `level` | runner 根据 scenario id 粗分的场景层级。 |
| `repeat` | repeat 序号，从 1 开始。 |
| `provider` | 用户传入的 provider。 |
| `command_provider` | 实际传给 `fairy.cli` 的 provider；某些 provider 会被规范化。 |
| `model` | 模型名。 |
| `model_family` | 报表模型族标签；未指定时由 provider/model 推断。 |
| `endpoint` | 实际使用的 endpoint override。 |
| `a2a_enabled` | 是否开启 A2A。 |
| `a2a_app_prop` | A2A app wrapper 比例；A2A off 时为 `0.0`。 |
| `a2a_policy` | A2A policy；A2A off 时为 `off`。 |
| `a2a_app_agent` | A2A fallback app-agent profile；A2A off 时为空。 |
| `detail_enabled` | `--detail` 规范化后的值；未设置为空。 |
| `parallel_tool_calls` | 本次运行是否允许模型在一个 assistant turn 里一次返回多个工具调用。 |
| `scenario_kwargs` | 实际透传给 `fairy.cli --scenario-kwargs` 的 JSON 字符串。 |
| `scenario_initialization_kwargs` | 实际透传给 `fairy.cli --init-kwargs` 的 JSON 字符串。 |
| `wall_s` | cell subprocess wall-clock 秒数。 |
| `return_code` | cell subprocess 退出码。`0` 表示进程成功退出。 |
| `timed_out` | 是否触发 `--cell-timeout-s`。 |
| `force_killed` | 超时后 graceful shutdown 未完成，是否被 terminate/kill。 |
| `timeout_grace_s` | 触发 timeout 后等待 graceful shutdown 的秒数；未 timeout 为空。 |
| `score` | 从 `run_report.evaluation.validation.success` 映射出的分数：成功为 `1.0`，失败为 `0.0`。 |
| `status` | `run_report.status`，例如 `completed`、`stopped`、`failed`。 |
| `workflow_combined` | 旧 `output.jsonl` rationale 中解析出的 workflow combined score；新 run_report 路径可能为空。最终 workflow/FOS 表请看 rebatch 输出。 |
| `fos` | 旧兼容 FOS 总分。论文/正式统计请看 `scripts/rebatch_fos_from_traces.py` 的输出。 |
| `outcome` | 旧兼容 FOS outcome。正式统计请看 rebatch 输出。 |
| `decision` | 旧兼容 FOS decision。正式统计请看 rebatch 输出。 |
| `efficiency` | 旧兼容 FOS efficiency。正式统计请看 rebatch 输出。 |
| `reasoning_steps` | LLM call 数；没有 LLM metrics 时退回旧 output.jsonl 估算。 |
| `llm_calls` | `run_report.metrics.llm_call_count`。 |
| `tool_calls` | `run_report.metrics.tool_call_count`。 |
| `planned_steps` | controller telemetry 中的 planned steps；无 telemetry 时退回 workflow steps。 |
| `executed_steps` | controller telemetry 中的 executed steps；无 telemetry 时退回 workflow steps。 |
| `skill_hits` | 兼容旧统计的 telemetry 列。FAIRY 内置 controller 不使用这一列，通常为 `0`，除非自定义 profile 重新启用 skills。 |
| `reflection_signals` | reflective controller telemetry。 |
| `replan_signals` | planner/ReWOO controller telemetry。 |
| `delegation_signals` | delegation/A2A/controller telemetry。 |
| `verification_signals` | verifier/critic controller telemetry。 |
| `error_count` | telemetry error count；run_report 有 error 时置为 `1`。 |
| `safety_violations` | FOS outcome breakdown 中的 safety violation 数。 |
| `crop_loss` | FOS crop loss count；若 run_report 有 `yield_recovery.avg_field_loss_fraction`，会用该值覆盖。 |
| `gates_matched` | FOS decision gates matched 数。 |
| `gates_total` | FOS decision gates 总数。 |
| `estimated_cost_dollars` | 按模型价格表估算的 cell 成本。 |
| `cell_dir` | cell run bundle 目录。 |
| `run_report_path` | cell 的 `<scenario>.run_report.json` 路径。 |
| `stdout_path` | cell stdout log 路径。 |
| `stderr_path` | cell stderr log 路径。 |
| `exception` | runner 层异常；只有 provider/env 准备失败或 future exception 时出现。 |

每个 cell 目录结构：

```text
<output-root>/<controller>__<scenario>__r1/
  stdout.log
  stderr.log
  <scenario>.run_report.json
  <scenario>.agent_workflow.json
  <scenario>.runtime_log.jsonl
```

### 5. 计算 yield loss / FOS

yield loss 需要 oracle yield baseline。当你要算 `crop_loss_pct`、`yield_loss(%)`、`fos(%)` 时，流程是两步。

第一步，生成 oracle baselines：

```bash
PYTHONPATH=. uv run python scripts/build_oracle_baselines.py \
  --scenarios formal90 \
  --output-dir validation_runs/quickstart/oracle_baselines_formal90 \
  --max-days 180 \
  --force \
  --include-donothing
```

第二步，对已经跑完的 agent traces 重放并重算 FOS：

```bash
PYTHONPATH=. uv run python scripts/rebatch_fos_from_traces.py \
  --root validation_runs/quickstart/batch/phase5_paper_matrix \
  --out-root validation_runs/quickstart/rebatch_fos \
  --oracle-baselines validation_runs/quickstart/oracle_baselines_formal90 \
  --extrapolate \
  --workers 4
```

运行完成后读取：

```text
validation_runs/quickstart/rebatch_fos/summary_v2.csv
```

正式看 FOS、yield loss、KTC/path matching 时，以这个 rebatch summary 为准，不要用 `iclr_validation_runner.py` 的 `results.csv` 里的旧兼容 FOS 列。`results.csv` 主要用来看 return code、timeout、费用、token/tool 次数和产物路径。

关键列：

- `fos(%)`：总 FOS 分。
- `outcome(%)` / `decision(%)` / `efficiency(%)`：FOS 分项。
- `agent_biological_kg`：agent replay 后的 biological yield。
- `oracle_biological_kg`：oracle baseline yield。
- `crop_loss_pct(%)` / `yield_loss(%)`：相对 oracle 的产量损失。
- `run_error_*` / `stderr_traceback_tail`：失败原因。

## 产物读取指南

按分析目标选择产物：

| 分析目标 | 产物 |
|---|---|
| 这次 run 成功了吗、为什么停、花了多久、用了多少 token？ | `run_report.json` |
| 模型最后看到的 prompt 是什么、模型怎么 function call？ | `runtime_log.jsonl` |
| agent 实际执行了哪些工具、参数和返回值是什么？ | `agent_workflow.json` |
| 哪一步报错、JSON 参数解析失败、接口失败、超时、超步数？ | `runtime_log.jsonl` |
| A2A 专家内部干了什么？ | `run_report.a2a` 和 `runtime_log.jsonl` |
| oracle 标准答案步骤是什么？ | `oracle.json` |
| oracle/agent workflow 在新场景里重放后是什么？ | `replay.json` |
| 场景最终验证和农场结果是什么？ | `run_report.json` |
| 一批实验的总表在哪里？ | `results.csv` 或 `summary_v2.csv` |

人工分析从 `run_report.json` 开始。逐轮 prompt、tool、错误和超限细节看 `runtime_log.jsonl`。

## 架构概览

FAIRY 的核心对象是一个 `Scenario`。每个场景会创建一组 farm apps，例如天气、传感器、无人机、机器人、拖拉机、田间作业、库存、物理引擎和系统时间。Agent 看到的是这些 app 暴露出的 function tools，工具名统一是：

```text
AppName__method_name
```

典型执行链路：

```text
Scenario.setup()
  -> apps + physics + initial farm state
  -> Engine
  -> oracle workflow 或 real agent function calls
  -> workflow/replay/evaluation/run_report artifacts
```

时间和物理链路：

```text
SystemApp.advance_time()
  -> FarmWorldApp.prepare_for_time_advance()
  -> FarmWorldApp.advance_physics_time()
  -> physics orchestrator daily ticks
  -> weather / soil / phenology / biomass / pest / yield state
```

## 仓库结构

```text
fairy/
  agents/        LLM client、function-calling agent loop、messages/runtime metrics
  apps/          App 基类、SystemApp、farm_world apps
  controllers/   Engine、控制器、A2A app-agent、run artifacts
  physics/       FARM 物理引擎和 profiles
  scenarios/     Scenario 基类、registry、baseline/action-tick/full-season 场景
  evaluation/    FARM evaluation/FOS helpers
scripts/
  build_oracle_baselines.py     生成 oracle yield baselines
  rebatch_fos_from_traces.py    对 FAIRY agent workflows 重放并重新算 FOS/yield loss
  iclr_validation_runner.py     批量跑 controller × scenario × repeat
  summarize_runs.py             汇总 run_report.json
tests/                          smoke、oracle、physics、controller、A2A 测试
docs/ai/                        维护笔记和已知坑
```

## 安装

推荐在仓库根目录安装为 editable package：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

如果不想安装 console script，也可以一直用：

```bash
PYTHONPATH=. uv run python -m fairy.cli --list
```

安装后可用：

```bash
fairy-run --list
```

## LLM Provider 环境变量

FAIRY 的 agent 路径使用 OpenAI-compatible chat completions + function calling。

支持的 provider：

- DeepSeek
  - `--provider deepseek`
  - 常用模型：`deepseek-chat`
  - 环境变量：`DEEPSEEK_API_KEY`，可选 `DEEPSEEK_API_BASE`
  - 默认 endpoint：`https://api.deepseek.com`

- OpenAI
  - `--provider openai`
  - 常用模型：`gpt-4o-mini`、`gpt-4o`
  - 环境变量：`OPENAI_API_KEY`
  - endpoint：OpenAI SDK 默认

- 通用 OpenAI-compatible 服务
  - `--provider llama-api` 或 `--provider openai-compatible`
  - 模型名：取决于你的服务
  - 环境变量：`LLAMA_API_KEY` 或 `OPENAI_API_KEY`
  - endpoint：用 `--endpoint` 或 `LLAMA_API_BASE` 指定

- Qwen / DashScope
  - `--provider qwen`
  - 常用模型：`qwen-plus`、`qwen-max`
  - 环境变量：`QWEN_API_KEY` 或 `DASHSCOPE_API_KEY`，可选 `QWEN_API_BASE`
  - 默认 endpoint：`https://dashscope.aliyuncs.com/compatible-mode/v1`

- vLLM
  - `--provider vllm`
  - 模型名：本地 vLLM 服务暴露的模型名
  - 环境变量：可选 `VLLM_API_KEY`，可选 `VLLM_API_BASE`
  - 默认 endpoint：`http://localhost:8000/v1`

`deepseek-json` 和 `qwen-json` 是兼容别名；在 FAIRY 里仍然走 function calling，不再走 JSON-only agent。

## 端到端示例命令

生成 oracle、回放、评估：

```bash
fairy-run \
  -s scenario_farm_world_field_prep_physics_action_tick \
  --build-oracle --replay --evaluate \
  --workflow validation_runs/example/oracle_baselines/scenario_farm_world_field_prep_physics_action_tick.json \
  --output-dir validation_runs/example/oracle_replay/scenario_farm_world_field_prep_physics_action_tick
```

先打开：

```text
validation_runs/example/oracle_replay/scenario_farm_world_field_prep_physics_action_tick/scenario_farm_world_field_prep_physics_action_tick.run_report.json
```

`run_report.json` 是入口文件。它会告诉你本次 run 的状态、耗时、token、tool calls、评估结果、错误、产量状态，以及其他文件分别在哪里。

## 主命令：`fairy-run`

等价入口：

```bash
uv run fairy-run ...
PYTHONPATH=. uv run python -m fairy.cli ...
PYTHONPATH=. uv run python scripts/run_scenario.py ...   # 兼容入口，内部调用 fairy.cli
```

### 1. 查看可用对象

列出场景：

```bash
fairy-run --list
```

列出控制器：

```bash
fairy-run --list-controllers
```

当前控制器包括：

```text
default
farm_world
farm_baseline_react
farm_planner_executor
farm_reflective_memory
farm_multi_specialist
farm_adaptive_verifier
farm_rewoo_modular
farm_tree_search
farm_critic_refiner
farm_graph_memory
```

### 2. Oracle / Replay / Evaluate 模式

```bash
fairy-run \
  -s <scenario_id> \
  --build-oracle \
  --replay \
  --evaluate \
  --workflow <path/to/oracle.json> \
  --output-dir <path/to/run_dir>
```

参数说明：

| 参数 | 类型/取值 | 默认值 | 含义 |
|---|---|---|---|
| `-s`, `--scenario` | scenario id | 必填 | 要运行的场景。用 `--list` 查看。 |
| `--build-oracle` | flag | false | 调用场景内置 oracle，生成 workflow JSON。 |
| `--run-oracle-tools` | flag | false | 生成 oracle 时也实际执行工具。通常构建 workflow baseline 不需要开；需要同时推动物理状态时才开。 |
| `--replay` | flag | false | 读取 `--workflow` 指向的 workflow，在新的场景实例上重放工具调用。 |
| `--evaluate` | flag | false | 对 replay 后的 workflow 和 farm state 做评估，结果写入 `run_report.evaluation`。 |
| `--workflow` | path | `<output-dir>/<scenario>.oracle.json` | `--build-oracle` 时的输出路径；`--replay/--evaluate` 时的输入路径。 |
| `--output-dir` | path | `runs` | 本次 run bundle 的输出目录。 |
| `--scenario-kwargs` | JSON object string | `{}` | 创建 scenario 对象时传入的参数。detail/context 例如 `'{\"detailed_briefing\":\"kwoo\"}'` 放这里。 |
| `--init-kwargs` | JSON object string | `{}` | 调用 `scenario.setup(**init_kwargs)` 时传入的参数。普通 FARM 场景一般不用。 |

常见组合：

只生成 oracle workflow：

```bash
fairy-run -s scenario_full_season_balanced \
  --build-oracle \
  --workflow validation_runs/oracle/scenario_full_season_balanced.json \
  --output-dir validation_runs/oracle_build/scenario_full_season_balanced
```

只回放和评估已有 workflow：

```bash
fairy-run -s scenario_full_season_balanced \
  --replay --evaluate \
  --workflow validation_runs/oracle/scenario_full_season_balanced.json \
  --output-dir validation_runs/oracle_replay/scenario_full_season_balanced
```

兼容的直接 oracle 打印模式：

```bash
fairy-run -s scenario_farm_world_field_prep --oracle
```

`--oracle` / `-o` 会运行 `Engine.run_scenario_oracle(run_oracle=True)` 并把 workflow 打印到 stdout。它主要用于快速调试，不会自动写完整 run bundle；正式实验建议用 `--build-oracle --replay --evaluate`。

### 3. Agent 模式

```bash
fairy-run \
  -s <scenario_id> \
  --agent \
  --controller <controller_id> \
  --provider <provider> \
  --model <model> \
  --temperature 0.1 \
  --max-tool-calls 300 \
  --timeout-seconds 1200 \
  --output-dir <path/to/run_dir>
```

参数说明：

| 参数 | 类型/取值 | 默认值 | 含义 |
|---|---|---|---|
| `--agent` | flag | false | 运行真实 function-calling agent。 |
| `--controller` | controller id | `farm_baseline_react` | 控制器家族。用 `--list-controllers` 查看。 |
| `--provider` | `deepseek`, `openai`, `llama-api`, `openai-compatible`, `qwen`, `vllm` | `deepseek` | LLM client 类型。 |
| `--model` | string | `deepseek-chat` | provider 下的模型名。 |
| `--temperature` | float | `0.1` | 采样温度。reasoning/openAI 某些模型可能忽略该值。 |
| `--endpoint` | URL | provider 默认 | 覆盖 OpenAI-compatible base URL。会传成 client 的 `base_url`。 |
| `--max-tool-calls` | int | `300` | 主 agent 最多允许多少次工具调用。到达后 `run_report.status=stopped`，`stopped_reason=max_tool_calls`。 |
| `--timeout-seconds` | float | `1200.0` | 主 agent 最大 wall time。到达后 `stopped_reason=timeout`。 |
| `--scenario-kwargs` | JSON object string | `{}` | 创建 scenario 对象时传入的参数。`detailed_briefing` / detail-context 模式就放这里。 |
| `--init-kwargs` | JSON object string | `{}` | 调用 `scenario.setup(**init_kwargs)` 时传入的参数。普通 FARM 场景一般不用；只有某个场景的 `setup()` 明确需要额外初始化参数时才用。 |

`--scenario-kwargs` 和 `--init-kwargs` 的区别：

- `--scenario-kwargs`：控制“这个场景对象怎么创建”。例如 full-season 场景的 `detailed_briefing` 是 dataclass/constructor 字段，所以必须放这里。
- `--init-kwargs`：控制“创建后 setup 怎么初始化”。目前大多数 FARM 场景不需要它，保持 `{}` 即可。

detail true/false/kwoo 这些都走 `--scenario-kwargs`：

```bash
# detail false：不加额外 detailed context
--scenario-kwargs '{"detailed_briefing": false}'

# detail true：使用场景自带 detailed briefing
--scenario-kwargs '{"detailed_briefing": true}'

# Kwoo context
--scenario-kwargs '{"detailed_briefing": "kwoo"}'

# knowledge library context
--scenario-kwargs '{"detailed_briefing": "library"}'

# L2/L3 retrieval context
--scenario-kwargs '{"detailed_briefing": "l2_textsim_differ"}'
--scenario-kwargs '{"detailed_briefing": "l3_pathsim_differ"}'
```

注意 JSON 里布尔值是小写 `true` / `false`，字符串模式要加双引号，例如 `"kwoo"`。

DeepSeek 示例：

```bash
fairy-run \
  -s scenario_full_season_balanced \
  --agent \
  --controller farm_baseline_react \
  --provider deepseek \
  --model deepseek-chat \
  --temperature 0.1 \
  --max-tool-calls 300 \
  --timeout-seconds 1200 \
  --output-dir validation_runs/manual/farm_baseline_react__scenario_full_season_balanced__r1
```

Qwen 示例：

```bash
fairy-run \
  -s scenario_full_season_balanced \
  --agent \
  --controller farm_baseline_react \
  --provider qwen \
  --model qwen-plus \
  --output-dir validation_runs/manual/qwen__farm_baseline_react__scenario_full_season_balanced__r1
```

vLLM 示例：

```bash
fairy-run \
  -s scenario_full_season_balanced \
  --agent \
  --controller farm_baseline_react \
  --provider vllm \
  --model Qwen/Qwen3-1.7B \
  --endpoint http://localhost:8000/v1 \
  --output-dir validation_runs/manual/vllm__farm_baseline_react__scenario_full_season_balanced__r1
```

## A2A：Agent2Agent App Experts

A2A 打开后，主 agent 不再直接看到所有 app tools。部分 app 会被替换成 expert wrapper，只暴露一个工具：

```text
<AppName>Expert__expert_agent(task)
```

专家 agent 收到 task 后，只能调用被包装 app 的工具和 `FinalAnswerTool__final_answer`。专家摘要、metrics 和 trace 写在：

```text
<scenario>.run_report.json
```

命令：

```bash
fairy-run \
  -s scenario_farm_world_drone_survey \
  --agent \
  --controller farm_multi_specialist \
  --provider deepseek \
  --model deepseek-chat \
  --a2a true \
  --a2a-app-prop 1.0 \
  --a2a-policy typed_experts \
  --output-dir validation_runs/manual/farm_multi_specialist__scenario_farm_world_drone_survey__a2a_on
```

A2A 参数：

| 参数 | 类型/取值 | 默认值 | 含义 |
|---|---|---|---|
| `--a2a` | bool: `true/false`, `1/0`, `yes/no`, `on/off` | `false` | 是否启用 app-agent wrapper。 |
| `--a2a-app-prop` | float, `0.0` 到 `1.0` | `0.5` | eligible apps 中被包装的比例。`1.0` 表示全部 eligible apps。 |
| `--a2a-policy` | `typed_experts` 或 `generic` | `typed_experts` | `typed_experts` 按 app 类型分配专家；`generic` 全部用 fallback profile。 |
| `--a2a-app-agent` | app-agent profile | `default_app_agent` | fallback profile。`generic` policy 时所有 wrapped apps 用它。 |
| `--a2a-model` | model string | 主 agent model | 专家 agent 使用的模型。 |
| `--a2a-provider` | provider string | 主 agent provider | 专家 agent 使用的 provider。 |
| `--a2a-endpoint` | URL | 主 agent endpoint | 专家 agent 使用的 endpoint。 |

App-agent profiles：

```text
default_app_agent
weather_expert_app_agent
sensor_expert_app_agent
machinery_expert_app_agent
operations_expert_app_agent
```

`typed_experts` 映射：

| App class | Expert |
|---|---|
| `WeatherApp` | `weather_expert_app_agent` |
| `SensorApp` | `sensor_expert_app_agent` |
| `TractorApp`, `FieldOpsApp` | `machinery_expert_app_agent` |
| `FarmWorldApp`, `DroneApp`, `RobotApp` | `operations_expert_app_agent` |
| `SystemApp`, `AgentUserInterface` | 不包装 |

已知注意点：如果主 agent 把过大的任务一次性委托给单个专家，专家可能在自己的 `max_tool_calls` 内循环。遇到 A2A 慢或失败，先看 `run_report.a2a.expert_metrics` 和 `runtime_log.jsonl`。

## 输出文件怎么读

所有 `fairy-run` 都会在 `--output-dir` 下写 run bundle。文件名前缀通常是 `<scenario_id>`。

### Agent run 文件按排查路径看

Agent run 指真正调用模型的运行：模型读 prompt，发 function call，FAIRY 执行工具，再把结果喂回模型。一次 agent run 最少要回答五个问题。

第 1 个问题：这次到底跑成了吗？

```text
<scenario>.run_report.json
```

先打开它。这里有 `status`、`stop_reason`、`limits`、`wall_time_seconds`、token、tool/LLM 次数、controller telemetry、A2A summary、evaluation、outcome 和 error。它是人看的总入口。

第 2 个问题：prompt 对不对？token、接口错误、JSON 解析错误、超时、超步数去哪看？

```text
<scenario>.runtime_log.jsonl
```

这是按时间顺序写的运行日志。每条 `record_type=llm_call_start` 里，`messages` 就是实际发给模型的完整 messages，`tool_names` 是这一轮可用的 function tools。模型 token、工具参数、工具返回、API 报错、JSON 解析失败、超时、超步数也都在这个文件里。

第 3 个问题：模型实际调用了哪些工具？

```text
<scenario>.agent_workflow.json
```

这里是语义 workflow：USER/TOOL 节点、工具名、参数、返回值、依赖和环境时间。做路径比较、人工审计、后续 replay，主要看它。

第 4 个问题：最后验证和农场结果是什么？

看 `run_report.json` 里的 `evaluation` 和 `outcome` 字段。

### Oracle / Replay / Evaluate 文件按步骤看

Oracle/replay/evaluate 不是一堆平级文件，而是三步。

第 1 步：`--build-oracle`

```text
<scenario>.oracle.json
```

这是“标准答案步骤表”。它记录场景 oracle 认为应该执行的工具、参数、依赖和环境时间。用途是当 baseline、当 replay 输入、和 agent workflow 做路径对照。

第 2 步：`--replay`

```text
<scenario>.replay.json
<scenario>.runtime_log.jsonl
```

`replay.json` 是把 workflow 放进一个全新场景状态后重新执行出来的步骤表。它证明这套 workflow 不是只写在纸上，而是真的能驱动 FARM apps。

`runtime_log.jsonl` 是 replay 的运行日志，一行一个工具 replay 记录。排查 replay 哪一步执行了、返回了什么、是否出错，看它。

第 3 步：`--evaluate`

```text
<scenario>.run_report.json
```

验证结果在 `run_report.evaluation` 里。看场景 validate 是否通过、库存/产量/物理状态是否合理。

最后总览：

```text
<scenario>.run_report.json
```

`run_report.json` 是入口。先看它，它会把上面所有文件路径和评估结果汇总起来。

### `run_report.json` 字段

| 字段 | 含义 |
|---|---|
| `schema_version` | report schema 版本。 |
| `run_type` | `agent` 或 `oracle_replay_evaluate`。 |
| `scenario_id` | 场景 ID。 |
| `controller_id` | agent controller；oracle/replay 模式为 `null`。 |
| `provider`, `model`, `temperature` | LLM 配置。 |
| `status` | `completed`、`stopped` 或 `failed`。 |
| `stopped_reason` | `agent_finished`、`completed`、`max_tool_calls`、`timeout`、`error` 等。 |
| `limits` | 本次设置的 `max_tool_calls` 和 `timeout_seconds`。 |
| `metrics.wall_time_seconds` | 真实运行耗时，来自 Python `time.perf_counter()`。 |
| `metrics.workflow_steps` | workflow 节点数。 |
| `metrics.tool_call_count` | 主 agent 或 replay 的工具调用数。 |
| `metrics.llm_call_count` | 主 agent LLM 调用数。 |
| `metrics.token_usage` | 主 agent token 汇总：prompt、completion、cached、total。 |
| `controller_telemetry` | planner/skill/rewoo/tree/critic/graph 等控制器内部计数。 |
| `a2a` | A2A 配置、wrapped apps、专家层 tool/LLM/token 汇总。 |
| `evaluation` | 场景 validate 和 outcome。 |
| `outcome` | farm state 摘要，例如库存、yield recovery、物理状态。 |
| `error` | fatal error 的类型和消息；正常超步数/超时不算 fatal error。 |
| `artifacts` | 其他输出文件路径。 |
| `artifact_guide` | 每个 artifact 的用途说明。 |
| `created_at` | 报告写入时间，CST/UTC+8。 |

## 推荐目录规范

单条手动 run：

```text
validation_runs/manual/<controller>__<scenario>__r1/
```

A2A：

```text
validation_runs/manual/<controller>__<scenario>__a2a_on__r1/
```

批量实验：

```text
validation_runs/<experiment_name>/phase5_paper_matrix/<controller>__<scenario>__r<repeat>/
```

推荐将 oracle baseline、agent run 和 rebatch FOS 输出隔离到不同目录：

```text
validation_runs/<experiment>/
  oracle_baselines/
    <scenario>.json
  phase5_paper_matrix/
    <controller>__<scenario>__r1/
      <scenario>.run_report.json
      ...
  rebatch_fos/
    summary_v2.csv
    <controller>__<scenario>__r1/
      fos/
      workflows/
```

## 场景池

列出全部：

```bash
fairy-run --list
```

常用示例：

```text
scenario_farm_world_field_prep
scenario_farm_world_planting
scenario_farm_world_irrigation
scenario_farm_world_pesticide
scenario_farm_world_drone_survey
scenario_farm_world_harvest
scenario_farm_world_field_prep_physics_action_tick
scenario_farm_world_planting_physics_action_tick
scenario_farm_world_irrigation_physics_action_tick
scenario_farm_world_pesticide_physics_action_tick
scenario_full_season_balanced
scenario_full_season_balanced_v2
```

`scripts/build_oracle_baselines.py --scenarios` 支持这些组名：

| 组名 | 含义 |
|---|---|
| `all` | 默认 FARM baseline 组，包含 round12、round3、round4、Tangyan5。 |
| `round12` | 8 个 action-tick baseline physics 场景。 |
| `round3` | 8 个 mid-season physics/FOS 场景。 |
| `round4` | full-season 旧 round4 组。 |
| `full`, `formal90`, `l3_fullseason` | `scripts/fullseason/formal_90_scenario_ids.txt` 里的 90 个 formal L3 场景。 |
| `selected_l2_l1_20_30`, `l2_l1_20_30` | 选定 L2/L1 split 场景池。 |
| `l2_skill_72`, `l2_skills`, `l2_skill` | 72 个 L2 skill scenarios。 |
| 逗号分隔 scenario IDs | 只跑指定场景。 |

## Full-season detail/context 模式

通过 `--scenario-kwargs '{"detailed_briefing": ...}'` 或 `iclr_validation_runner.py --detail` 设置。

`fairy-run` 示例：

```bash
fairy-run \
  -s scenario_full_season_hb_base_hn84_std_normal \
  --agent \
  --controller farm_baseline_react \
  --provider deepseek \
  --model deepseek-chat \
  --scenario-kwargs '{"detailed_briefing":"kwoo"}' \
  --output-dir validation_runs/manual/kwoo_example
```

等价批跑写法：

```bash
PYTHONPATH=. uv run python scripts/iclr_validation_runner.py \
  --phase l3_context \
  --output-root validation_runs/l3_context/phase5_paper_matrix \
  --families farm_baseline_react \
  --scenarios scenario_full_season_hb_base_hn84_std_normal \
  --detail kwoo \
  --provider deepseek \
  --model deepseek-chat
```

`iclr_validation_runner.py --detail kwoo` 会自动合并成：

```text
--scenario-kwargs '{"detailed_briefing":"kwoo"}'
```

可用值：

| 值 | 含义 |
|---|---|
| `false` | 不注入额外 L3 detail/context。 |
| `true` | 使用原始 detailed L3 briefing。 |
| `kwoo` | 使用 Kwoo 生成的 expert context。 |
| `library` | 使用同 L3 的 `knowledge_library_pilot` context。 |
| `l2_human_same` | 同 source L3 内的人工/结构化 L2 skills。 |
| `l2_human_differ` | 其他 L3 source 转移来的人工/结构化 L2 skills。 |
| `l2_textsim_differ` | 文本相似度检索的跨 L3 L2 skills。 |
| `l2_textsim_grouped_differ` | 按 establishment、management、harvest 分组的文本相似跨 L3 L2 skills。 |
| `l2_pathsim_differ` | workflow/path 相似度检索的跨 L3 L2 skills。 |
| `l2_pathsim_grouped_differ` | 按农事阶段分组的 path 相似跨 L3 L2 skills。 |
| `l3_pathsim_same` | L3 workflow/path 相似度检索的同 L3 context。 |
| `l3_pathsim_differ` | L3 workflow/path 相似度检索的跨 L3 context。 |
| `l3_textsim_differ` | L3 文本相似度检索的跨 L3 context。 |
| `l3_textdiff_differ` | 旧实验配置兼容别名。 |

相关资产：

```text
scripts/fullseason/formal_90_scenario_ids.txt
scripts/fullseason/selected_l2_l1_20_30_scenario_ids.txt
scripts/fullseason/l2_skill_scenario_ids.txt
scripts/fullseason/l3_skill_source_ids.txt
scripts/kwoo_expansion_result.json
scripts/kwoo_l1l2_expansion_result.json
```

如果要跑 `selected_l2_l1_20_30` 这 50 个 L1/L2 场景，不要把 `selected_l2_l1_20_30` 当成单个 scenario id 直接传给 batch runner。先从 manifest 里取出真实 scenario id，再传给 `--scenarios`：

```bash
SCENARIOS=$(awk -F, 'NF>=3 && $1 !~ /^#/ {print $3}' \
  scripts/fullseason/selected_l2_l1_20_30_scenario_ids.txt | paste -sd, -)

PYTHONPATH=. uv run python scripts/iclr_validation_runner.py \
  --phase selected_l2_l1_20_30_detail_false \
  --output-root validation_runs/selected_l2_l1_20_30_detail_false/phase5_paper_matrix \
  --families farm_baseline_react \
  --scenarios "$SCENARIOS" \
  --repeats 1 \
  --provider deepseek \
  --model deepseek-chat \
  --detail false \
  --a2a false \
  --parallel-tool-calls false \
  --max-concurrent 1 \
  --agent-max-iterations 200 \
  --cell-timeout-s 1200
```

## Oracle Baselines：yield loss 的分母从这里来

`scripts/build_oracle_baselines.py` 会跑每个场景的 oracle，必要时把物理推进到 R8 成熟期，然后写出每个场景的 oracle yield baseline。FOS 里的核心 yield loss 使用它作为分母：

```text
crop_loss_pct = 1 - agent_biological_kg / oracle_biological_kg
```

命令：

```bash
PYTHONPATH=. uv run python scripts/build_oracle_baselines.py \
  --scenarios formal90 \
  --output-dir validation_runs/oracle_baselines_formal90 \
  --max-days 180 \
  --force \
  --include-donothing
```

参数：

| 参数 | 类型/取值 | 默认值 | 含义 |
|---|---|---|---|
| `--scenarios` | 组名或逗号分隔 IDs | `all` | 要构建 baseline 的场景。支持 `all`, `round12`, `round3`, `round4`, `formal90`, `selected_l2_l1_20_30`, `l2_skill_72`。 |
| `--output-dir` | path | `oracle_baselines_full` | 写 `<scenario_id>.json` 的目录。 |
| `--max-days` | int | `180` | oracle 后最多额外推进多少天到 R8。 |
| `--force` | flag | false | 已存在 baseline 时是否重建。不开则 skip。 |
| `--continue-on-error` | flag | false | 单个场景失败时继续构建其他场景。 |
| `--include-donothing` | flag | false | 同时构建 do-nothing baseline，供 normalized yield score 使用。 |

每个 baseline JSON 主要字段：

| 字段 | 含义 |
|---|---|
| `scenario_id` | 场景 ID。 |
| `schema_version` | baseline schema 版本。 |
| `ridge_area_m2` | 单垄面积。 |
| `ridges_total`, `ridges_planted`, `ridges_r8`, `ridges_harvested` | 总垄数、已播种、到 R8、已收获数量。 |
| `biological_yield_g_m2_per_ridge` | 每垄 biological yield。 |
| `biological_yield_kg_total` | oracle biological yield 总 kg。FOS yield loss 主要用它。 |
| `recovered_yield_g_m2_per_ridge` | 每垄 recovered/market moisture yield。 |
| `recovered_yield_kg_total` | recovered yield 总 kg。 |
| `extrapolation` | 额外推进到成熟期的状态。 |
| `donothing` | 可选，do-nothing yield baseline。 |
| `tool_errors` | oracle 中保留下来的工具 error 返回；不一定代表 baseline 失败。 |

## Rebatch FOS：从 FAIRY runs 重算 FOS/yield loss

当你已经有一批 FAIRY agent run bundles，不想重新花 LLM 钱，只想用最新 FOS/yield loss 逻辑重新评估，用：

```bash
PYTHONPATH=. uv run python scripts/rebatch_fos_from_traces.py \
  --root validation_runs/<experiment>/phase5_paper_matrix \
  --out-root validation_runs/<experiment>/rebatch_fos \
  --oracle-baselines validation_runs/oracle_baselines_formal90 \
  --extrapolate \
  --workers 4
```

它会：

1. 找到每个 cell 目录里的 trace/run artifacts。
2. 重新实例化同一个 scenario。
3. 按已记录的工具调用重放 agent 行为。
4. 推进物理到 R8。
5. 读取 oracle baseline。
6. 写 per-cell FOS JSON 和 `summary_v2*.csv`。

Rebatch 输出结构：

```text
<out-root>/
  summary_v2_<out-root-name>.csv      # 主 CSV，除非 --summary-name 覆盖
  summary_v2.csv                      # 兼容副本
  <cell>/
    fos/
      fos_<scenario>.json             # per-cell FOS 明细
    workflows/
      workflow_agent_<scenario>.json  # replay 后 agent workflow
      workflow_oracle_<scenario>.json # oracle workflow/path 对照
    path_corr_v2_<scenario>.json      # 开启 path-correctness-v2 时的路径匹配明细
```

这些文件的用途：

| 文件 | 用途 |
|---|---|
| `summary_v2*.csv` | 论文表格/统计入口。一行一个 cell。 |
| `fos/fos_<scenario>.json` | 单个 cell 的 FOS 分项、decision gates、outcome breakdown。 |
| `workflows/workflow_agent_<scenario>.json` | 由 trace 重放出来的 agent 工具序列。用于人工看 agent 做了什么。 |
| `workflows/workflow_oracle_<scenario>.json` | 同一场景 oracle 工具序列。用于 path correctness / KTC 对照。 |
| `path_corr_v2_<scenario>.json` | v2 relaxed numeric path matching 的匹配细节。 |

参数：

| 参数 | 类型/取值 | 默认值 | 含义 |
|---|---|---|---|
| `--root` | path，可多次传 | 必填 | sweep/cell 根目录。默认只看直接子目录；配 `--recursive` 可递归找。 |
| `--out-root` | path | 必填 | rebatch 输出目录。 |
| `--summary-name` | filename | `summary_v2_<out-root-name>.csv` | 主 summary CSV 文件名。总会另写兼容副本 `summary_v2.csv`。 |
| `--extrapolate` | flag | false | replay 后推进物理到 R8。full-season 和 mid-season 推荐打开。 |
| `--extrapolation-max-days` | int | `180` | 最多推进天数。 |
| `--oracle-baselines` | path | none | oracle baseline JSON 目录。提供后才能算 oracle-relative yield loss。 |
| `--workers` | int | CPU 一半 | 并行 cell 数。 |
| `--limit` | int | none | 只处理前 N 个 cell，debug 用。 |
| `--cells` | cell dir names | none | 只处理指定 cell，debug 用。 |
| `--recursive` | flag | false | 在 `--root` 全子树里找 cell。 |
| `--donothing-inline` | flag | false | replay 时额外算 do-nothing baseline。需要 `--extrapolate`。 |
| `--path-correctness-v2` / `--no-path-correctness-v2` | bool | on | 是否计算 relaxed numeric path correctness v2。 |
| `--pc2-tol` | float | `2.0` | v2 数值参数匹配容忍比例。 |
| `--focus-ridges-config` | JSON path | none | 指定场景的 focus ridges，用于局部 yield 指标。 |
| `--exclude-dir` | path，可多次传 | none | 排除某些目录。 |

`summary_v2.csv` 重要列：

| 列 | 含义 |
|---|---|
| `status` | cell 是否成功重评估。 |
| `cell`, `cell_dir`, `cell_output_rel` | cell 名和路径。 |
| `agent_family`, `scenario`, `level` | controller、场景、场景层级。 |
| `llm_model`, `model_type_size` | 模型标签。 |
| `run_level`, `detail_status`, `detailed_briefing`, `a2a_status`, `a2a_enabled` | 实验条件。 |
| `llm_calls_with_usage`, `total_tokens_per_scenario`, `runtime_s_per_scenario` | token/runtime 汇总。 |
| `fos(%)`, `outcome(%)`, `decision(%)`, `efficiency(%)` | FOS 总分和分项，100 分制。 |
| `agent_biological_kg`, `oracle_biological_kg`, `donothing_biological_kg` | agent/oracle/do-nothing biological yield。 |
| `yield_preserved_ratio(%)` | agent preserved yield ratio。 |
| `yield_loss(%)`, `crop_loss_pct(%)` | yield loss 指标。 |
| `normalized_yield_score(%)` | 用 do-nothing floor 归一化后的 yield score。 |
| `growing_loss`, `harvest_loss`, `unharvested_mature`, `safety_violations` | loss bucket 和安全违规。 |
| `path_correctness(%)`, `coverage(%)`, `ktc_score(%)`, `combined(%)` | workflow path 指标。 |
| `farm_fos(%)`, `farm_fos_v2_*` | FARM-FOS 农业动作级指标。 |
| `run_error_*`, `stderr_traceback_tail`, `error`, `traceback` | 失败诊断。 |

## 批量跑真实 agent：`iclr_validation_runner.py`

用于 controller × scenario × repeat 的批量真实 LLM run。每个 cell 是一个独立 subprocess，并写自己的 stdout/stderr 和 run_report。

```bash
PYTHONPATH=. uv run python scripts/iclr_validation_runner.py \
  --phase smoke \
  --output-root validation_runs/smoke/phase5_paper_matrix \
  --families farm_baseline_react,farm_rewoo_modular \
  --scenarios scenario_farm_world_field_prep,scenario_farm_world_planting \
  --repeats 1 \
  --provider deepseek \
  --model deepseek-chat \
  --cost-cap-dollars 5 \
  --max-concurrent 1 \
  --cell-timeout-s 600 \
  --agent-max-iterations 100
```

参数：

| 参数 | 类型/取值 | 默认值 | 含义 |
|---|---|---|---|
| `--config` | JSON path | none | 从 JSON 配置读取默认值；CLI 会覆盖 config。 |
| `--phase` | string | 必填 | 实验阶段标签，只用于日志/组织。 |
| `--output-root` | path | 必填 | 写 cell 目录和 `results.csv` 的根目录。 |
| `--families` | 逗号分隔或 config list | 必填 | controller 列表。 |
| `--scenarios` | 逗号分隔或 config list | 必填 | scenario 列表。 |
| `--repeats` | int | `1` | 每个 family × scenario 跑几次。 |
| `--model`, `--provider`, `--endpoint` | string | `gpt-4o-mini`, `llama-api`, none | LLM 配置。 |
| `--model-family` | string | 自动推断 | CSV 里的模型族标签。 |
| `--cost-cap-dollars` | float | `10.0` | 估算费用上限；达到 80% 时取消剩余 cells。 |
| `--max-concurrent` | int | `1` | 并行 cell 数。 |
| `--cell-timeout-s` | int | `300` | 单 cell subprocess 超时。 |
| `--cell-timeout-grace-s` | int | `60` | 超时后先 SIGINT 等待多久，再 terminate/kill。 |
| `--agent-max-iterations` | int | `200` | 传给 `fairy-run --max-tool-calls`。 |
| `--parallel-tool-calls` | `true` / `false` | `true` | 传给 `fairy-run`。如果要严格一轮只出一个工具调用的 ReAct trace，设成 `false`。 |
| `--wait-for-user-input-timeout` | float | `5.0` | 兼容旧 runner 字段；当前 FAIRY CLI 不直接使用。 |
| `--scenario-kwargs`, `--init-kwargs` | JSON object string | none | 透传给 FAIRY CLI。 |
| `--detail` | detail mode | none | 自动合并进 `--scenario-kwargs` 的 `detailed_briefing`。 |
| `--a2a`, `--a2a-*` | 同 FAIRY CLI | off | 批量 A2A 配置。 |

跑 `selected_l2_l1_20_30` 这类场景池时，先按上面“场景池”一节的命令生成 `SCENARIOS`，这里传 `--scenarios "$SCENARIOS"`。

输出：

| 文件 | 用途 |
|---|---|
| `<output-root>/results.csv` | 每个 cell 一行：return code、status、cost、tool/LLM calls、telemetry、run_report 路径。 |
| `<output-root>/<family>__<scenario>__rN/stdout.log` | 该 cell 的 stdout。 |
| `<output-root>/<family>__<scenario>__rN/stderr.log` | 该 cell 的 stderr、timeout/traceback。 |
| `<output-root>/<family>__<scenario>__rN/<scenario>.run_report.json` | cell 的主报告。 |
| 其他 `<scenario>.*` artifacts | 同普通 agent run。 |

## 汇总 run_report：`summarize_runs.py`

快速扫描一个目录下所有 `*.run_report.json`：

```bash
PYTHONPATH=. uv run python scripts/summarize_runs.py validation_runs/manual \
  --csv validation_runs/manual/summary.csv
```

输出列：

```text
run_dir, run_type, scenario_id, controller_id, model, status,
stopped_reason, success, wall_time_seconds, workflow_steps,
tool_call_count, total_tokens, cached_tokens, warehouse_grain_kg,
harvested_ridges, yield_g_m2
```

## 状态、错误、超时怎么看

先看 `run_report.json`：

- `status=completed`：正常完成。
- `status=stopped`：达到限制，例如 `max_tool_calls` 或 `timeout`。这不是 fatal error。
- `status=failed`：发生 fatal error，看 `error.type` 和 `error.message`。

再看 `runtime_log.jsonl`：

- `record_type=llm_call_start` / `llm_call_end`：每次 LLM 调用。`llm_call_start.messages` 就是实际发给模型的完整 prompt/messages。
- `record_type=tool_call_start` / `tool_call_end`：每次工具调用。
- `record_type=tool_args_parse_error`：模型返回的 function arguments 不是合法 JSON。
- `record_type=tool_call_error`：工具执行抛异常，或 A2A 专家内部失败。
- `record_type=agent_limit_exceeded`：主 agent 到达 max tool calls 或 timeout。
- `record_type=agent_run_end` 且 `status=stopped`：正常限制停止。
- `record_type=agent_run_error`：真正异常。

接口错误通常在：

```text
<run_dir>/<scenario>.runtime_log.jsonl
<run_dir>/stderr.log              # iclr_validation_runner.py 批跑
<run_dir>/command_stderr.log      # 手写 subprocess smoke
<run_dir>/<scenario>.run_report.json error 字段
```

Prompt 是否符合预期：

```text
<scenario>.runtime_log.jsonl      # record_type=llm_call_start 里有完整 messages
```

Token 和 runtime：

```text
run_report.metrics.token_usage
run_report.metrics.llm_wall_time_seconds
run_report.metrics.tool_wall_time_seconds
run_report.a2a.expert_metrics     # A2A on 时专家层 token/runtime
runtime_log.jsonl                 # 每次调用细节
```

## 测试

```bash
PYTHONPATH=. pytest -q tests/test_fairy_migration_smoke.py -q
python -m py_compile fairy/cli.py fairy/controllers/app_agent.py fairy/controllers/run_artifacts.py
rg "from are\\.|import are\\.|from rsare\\.|import rsare\\." fairy tests scripts
```

import guard 没输出且返回码为 1 表示没有匹配到外部框架 runtime imports。

## 已知限制

- `farm_rewoo_modular` 当前可能进入 fallback：`ReWOO plan fallback`。这说明还不是完整 paper-run 级 ReWOO planner。
- A2A on 会显著增加 wall time 和专家 token。比较 A2A on/off 时必须同时看主 agent token 和 `a2a.expert_metrics`。
- Oracle baseline 中的 `tool_errors` 可能是场景设计的一部分，不一定代表 baseline 构建失败。
