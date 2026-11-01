# 当前水稻 Oracle 与任务描述（2026-11-01）

当前注册 38 个水稻场景：15 个 L1、11 个 L2、12 个 L3。8 个常规 L3 与其 20 个子任务保留显式场景入口，4 个挑战 L3 与其 6 个子任务沿用挑战场景注册。物理模型、工具上限和品种参数不因本次 Oracle 或 prompt 安装而改变。

## 运行时资产与提交范围

- 常规固定计划：`fairy/scenarios/rice/oracle_plans/`。
- L3 挑战固定计划：`fairy/scenarios/rice/l3_defaults/challenge_plans/`。
- 12 个 L3 的详细任务：`fairy/scenarios/rice/l3_defaults/detailed_briefings.json`，结构为任务、已知条件、管理重点、九步操作、总体约束；水分巡查为第 4 步，分蘖追肥、幼穗追肥为第 5、6 步。
- L1/L2 描述：`l3_defaults/split_briefings.json`；常规检查点在 `l2_l1_splits/`，挑战切片和检查点在 `l3_defaults/split_challenges/`。
- `split_lineage.json` 记录每个子任务对应的父计划哈希、半开步骤范围及起止状态。加载器校验父计划身份与步骤内容；评估基线也必须匹配该身份。
- `scenario_artifacts.json` 和 `l3_defaults/manifest.json` 必须随所属计划、检查点和描述一起提交；只提交描述或 Python 加载器不能构成完整安装。

构图和初始化只加载固定资产，不执行参考季或离线策略。`scripts/build_rice_scenario_artifacts.py` 从当前固定 L3 计划派生 L1/L2，先在临时目录验证后发布；它不会搜索新管理方案或修改 L3。历史候选与扫参脚本已从 `scripts/` 移至本地实验归档，运行时不依赖它们。

## 场景差异

| 场景 | 保留的主要管理差异 |
| --- | --- |
| normal | 每 7 天查水，第 18/38 天阶段追肥，植保每 14 天、阈值 0.25 |
| water_limit | 无日常降雨、取水 1100 m³、首轮泡田 80 mm，每 5 天查水 |
| nitrogen_limit | 尿素总量 55 kg；每公顷三轮 24.444444、97.777777、97.777777 kg 产品；底肥前表水约 29.9 mm |
| biotic | 插秧后尽早地面确诊，每 7 天植保检查、阈值 0.1 |
| infrastructure | 疏渠、修 p1 漏埂并复核，UTC06—20 时供水 |
| equipment_limit | 初始低油量、载苗 75000 株、600 kg 粮箱、2000 kg 湿粮/日干燥能力 |
| poor_stand | p1 缺苗，按实际缺口补苗，2 天后复查及约第 7 天核对 |
| late_rain | 4 月初连续降雨，结合含水与天气窗口收割，雨后核对根区通行性 |
| zonal_water_n_allocation | 水额 1900 m³、尿素 75 kg；p1/p2 不同分肥，第 14/35 天追肥，每 5 天查水 |
| infrastructure_water_priority | 水额 1800 m³、UTC06—10 时供水；疏渠后 p2 过干先预湿，再修 p1 漏埂 |
| zonal_crop_protection | 先航拍定位、再逐田地面确诊，每 3 天植保检查、阈值 0.1 |
| rainy_harvest_capacity | 晚期周期降雨、600 kg 粮箱、1800 kg 湿粮/日干燥能力、400 kWh 电量 |

施肥量均按尿素产品质量，不是纯氮。详细描述保留逐田施肥轮次和各自日期。巡水与植保是贯穿生长期的重复管理，等待其他农事节点时也不能漏掉；每个场景的间隔和阈值取其自身描述。

## 复现

从仓库根目录用现有虚拟环境执行。CLI 使用单独工作目录，避免其清理兼容导出目录时影响仓库根目录的旧产物：

```bash
REPO="$(pwd)"
PYTHON="$REPO/.venv/bin/python"
RUN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/fairy-rice.XXXXXX")"
cd "$RUN_DIR"

env -u USER PYTHONPATH="$REPO" "$PYTHON" -m fairy.cli \
  --scenario scenario_rice_l3_normal --build-oracle --replay --evaluate \
  --scenario-kwargs '{"seed":0,"detailed_briefing":true}' \
  --output-dir "$RUN_DIR/oracle"

# OPENAI_API_KEY 通过环境提供，不写入命令、源码或结果文件。
env -u USER PYTHONPATH="$REPO" "$PYTHON" -m fairy.cli \
  --scenario scenario_rice_l3_normal --agent \
  --provider openai --model gpt-6-luna \
  --controller farm_baseline_react --system-prompt-mode fairy \
  --max-output-tokens 8192 --parallel-tool-calls false \
  --max-tool-calls 500 --timeout-seconds 1800 \
  --scenario-kwargs '{"seed":0,"detailed_briefing":true}' \
  --output-dir "$RUN_DIR/agent"
```

`gpt-6-luna` 由现有 OpenAI 适配器走 Responses，默认推理强度 medium；该路由不传 temperature。运行报告中的名义 temperature 不代表 Responses 实际使用了该参数。

在仓库根目录校验当前切片与固定资产：

```bash
env -u USER PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
  scripts/build_rice_scenario_artifacts.py --verify-only

env -u USER PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q --disable-warnings \
  tests/test_rice_l3_defaults.py tests/test_rice_split_lineage.py \
  tests/test_rice_paddy.py tests/test_rice_scenario_structure.py \
  tests/test_rice_toolset.py tests/test_rice_validation_regressions.py
```

## 结果口径与证据边界

2026-11-01 seed 0、当前详细描述的 GPT-6-luna normal 运行正常结束：204 次工具调用、205 次模型调用、无工具错误。独立 Engine 回放的 outcome 与原报告完全一致。成熟籽粒为 8.308789 t/ha，固定 Oracle 为 8.335921 t/ha，相对产量损失 0.325488%；0.25 ha 实际入库 2014.881346 kg；未出现水分胁迫。成熟籽粒按 14% 含水换算、未扣收获损失，实际入库量已经历收获与收储。该结果是一条运行记录，不是跨种子或模型的成功率估计。

`zonal_water_n_allocation` 和 `infrastructure_water_priority` 的 L3，以及对应的两个 L2 diagnosis，仍保留 experimental 校准状态。Oracle 能执行和回放，不代表通过匹配对照校准。不得为提交而改成已通过。路径相似度、任务验收、成熟产量和实际入库量需分别报告。

稻作结果使用 `fairy/scenarios/rice/evaluation.py` 的田格面积及 `rice_outcome` 口径；通用 FOS 的按垄/R8 口径不能直接用于水稻。运行日志、旧版备份、搜索候选和批次比较保留在被 Git 忽略的 `validation_runs/`；运行和测试只依赖提交的固定资产，不读取这些本地证据目录。
