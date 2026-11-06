# 管理拓展场景回放与论文指标

入口是 `scripts/replay_management_metrics.py`，适配当前注册的 39 个管理拓展场景。它调用主回放脚本 `scripts/rebatch_fos_from_traces.py` 的严格工具回放、KTC、COV、BFCL、效率及旧 FARM 指标函数；不调用语言模型，不修改 Agent 的管理决策，也不为其补播、补肥或补收获。

## 运行

在仓库根目录执行。`--root` 可给多个实验目录，递归发现其中的 `*.agent_workflow.json`，保留模型、提示模式及重试目录层级。同一物理目录被重复指定时仅处理一次。建议显式指定独立的输出目录。

```bash
env -u USER TMPDIR=/tmp/fairy_management_qwen3_pcse PYTHONPATH="$PWD" \
  .venv/bin/python scripts/replay_management_metrics.py \
  --root validation_runs/management_missing20_qwen3_20261106_004839 \
         validation_runs/sugarbeet_final_briefings_two_models_20261105_231450 \
  --out-root validation_runs/management_replay_results --workers 3
```

`TMPDIR` 应为已存在、可写的目录。入口先串行导入 PCSE，再开进程，避免首次创建共享缓存时竞争。以上两个示例输入目录不包含全部 39 个场景，覆盖缺口见输出的 `management_coverage.json`。可继续添加历史实验目录或新跑的 39 场景实验根目录。

入口默认 `--recursive --management-only --extrapolate --extrapolation-max-days 365`。365 天用于覆盖越冬小麦；主脚本的原有默认值仍为 180 天。完全复现旧命令的投影上限请指定 `--extrapolation-max-days 180`；仅统计实际结束状态用 `--no-extrapolate`。投影在副本上进行，沿用停止管理后的生长过程；恢复量、账目和成本冻结在实际回放结束时。

验证所有注册 Oracle 的执行与回放一致性：

```bash
env -u USER TMPDIR=/tmp/fairy_management_qwen3_pcse PYTHONPATH="$PWD" \
  .venv/bin/python scripts/replay_management_metrics.py --verify-oracles \
  --out-root validation_runs/management_oracle_selftest --workers 3
```

此模式逐场景运行 Oracle、保存轨迹并严格回放，检查两项产量损失和两项经济差额为零。产物标记为 `oracle_replay_selftest`，不属于模型实验；`oracle_verification.json` 记录完整结果。`--list-scenarios` 列出当前注册 ID。

## 建议论文名称与公式

记 Agent 为 A，Oracle 为 O。百分比列等于下列比例乘 100。保留旧字段以兼容已有总表，新名称是本文建议的报告用语，不声称为某篇文献的既有标准。

| 论文名称 | 缩写 | CSV 字段 | 比例公式 |
| --- | --- | --- | --- |
| 生物产量缺口 / Biological Yield Shortfall | BYS | `yield_loss(%)`，别名 `biological_yield_shortfall(%)` | `1 − Ybio_A / Ybio_O` |
| 回收产量缺口 / Recovered Yield Shortfall | RYS | `recovered_yield_loss(%)`，别名 `recovered_yield_shortfall(%)` | `1 − Yrec_A / Yrec_O` |
| 相对运营成本差额 / Relative Operating Cost Gap | ROCG | `relative_operating_cost_gap(%)` | `(C_A − C_O) / C_O` |
| 相对净运营收益差额 / Relative Net Operating Return Gap | RNRG | `relative_net_operating_return_gap(%)` | `(N_A − N_O) / N_O` |

经济字段同时导出无百分号的原比例、双方 USD 数值、USD 绝对差额、未定义原因及 Oracle 分母为负标记。成本来自场景实际消耗投入和已启用作业；净运营收益采用场景 `net_operating_margin`，政策场景包含实际到账补贴。未包含地租、普通人工、折旧和税费，故不命名为完整净利润。

Oracle 分母为零时 CSV 留空、JSON 为 null，并记录原因；不添加 epsilon、不改成绝对值分母。Oracle 收益为负时保留用户指定的有符号公式，应结合 `net_operating_return_gap_usd` 判断收益是否改善。负产量缺口表示超过参考 Oracle，不截断。Oracle 是通过场景校验的参考工作流，未证明全局最优，因此不把这些指标称为 optimality regret。

## 作物与轮作口径

* 生物产量：粮食储藏器官干物质；甜菜使用 WOFOST `TWSO` 的块根干物质，乘实际地块面积，绝不使用 `TWRT` 或把 TWSO 直接当作鲜根/糖产量。
* 回收产量：粮食使用场景商品含水率的实际收获质量；甜菜使用 RootLedger 中实际起收的净鲜根质量 `recovered_net_kg`，并非糖厂验收量或仓储量。干鲜换算和收获损失沿用场景执行时的批次账本。
* 多季：已结束季使用季账本或原生收获凭据，当前季使用对应引擎；不会只取最后一季覆盖之前的产量。
* 投影停止条件：普通粮食保留旧脚本的成熟投影；原生小麦受成熟/季截止日约束，甜菜受收获窗口截止日约束，并共同受 `extrapolation-max-days` 限制。达到天数上限时保留 `biological_projection_capped` 标记。原生周期的明细年份采用播种窗口年份，轮作季账本沿用其季年份。
* 跨作物总表：按用户确认，沿用主回放“先合计质量、再算 A/O 比例”的公式。干物质与回收量分别汇总。鲜根与粮食商品重的总和只作为兼容性总表指标，解释作物间差异时必须同时报告分作物、分季结果及 `crop_composition_changed`，不能视为等营养、等价值的总产出。
* `recovered_yield_loss_v2(%)` 是旧脚本的成熟未收获保底口径，独立于实际回收量。普通粮食沿用原函数；原生作物未收获时该项留空并标明原因，不套用大豆成熟或粮食含水率假设。

## 流程指标与有效性

旧列完整保留：`ktc(%)`、`coverage_v1(%)`、`core_path_correctness(%)`，以及默认开启、数值容差为 2 的 v2 `ktc_score(%)`、`coverage(%)`、`path_correctness(%)`、`ktc_adjusted(%)`、`combined(%)`，还有 `bfcl_success(%)`。`cov(%)` / `cov_v1(%)` 只是对应 coverage 的别名。报告 KTC/COV 时应声明使用 v1 还是 v2，不能混用。

BFCL 是本仓库原有的参考工具调用匹配分数，不能当成官方 BFCL 榜单成绩。Oracle 流程的构造方式、参数归一化和评分公式沿用主回放；完整执行轨迹另外保存在 Oracle 参考 JSON 的 `executed_workflow`，供状态回放审计。

兼容旧口径也保留了一个已观测限制：静态 Oracle 与执行日志对连续 `SystemApp.advance_time` 的合并、缺省时间参数的表示不同，因此 Oracle 自身回放的 COV/BFCL 也可能小于 100（甜菜全季自检为 90），不能直接把这一部分差异归因于模型决策。自检总表给出各场景的 Oracle 控制分；论文应同时报告或说明这一参照上限。这里没有静默重标定旧流程分。

FARM/FARMv2 原列仍调用旧函数输出，但其大豆先验没有对原生小麦播种、甜菜起收等动作重新标定；`farm_fos_calibration_scope` 明示此限制。通用 FOS outcome 尚不能表达原生块根与闭合多季账本，这些场景的该综合分留空并给出 `generic_fos_status`。这不影响这里的作物适配产量、经济指标或 KTC/COV/BFCL。

严格回放保留原有时间、参数、拒绝响应与异常契约检查。失败轨迹不生成虚构产量或经济结果；可从原始日志恢复的流程分单独标记 `workflow_metrics_source=recorded_trace_only` 和 `physical_replay_verified=false`。缺少 run_report 时尝试读取匹配的批次 cells 配置；若实际物理回放完成、仅最终 validate 报错，可从账本提取指标，并保留 `validation_error_metrics_recovered`。任务成功、回放成功和产量水平是不同字段。

Oracle 缓存按场景、seed、起始时刻、构造/初始化参数、输入指纹、评价代码摘要和投影配置隔离；并行使用文件锁与原子写入。历史模型轨迹仍由当前代码重放；输入发生变化而导致严格校验失败时，应使用原实验代码快照重放，不能通过放宽检查获得数值。

## 输出

已有三模型采集目录可用以下命令合并和核验：

```bash
.venv/bin/python scripts/assemble_management_comparison.py --root <collection-dir>
.venv/bin/python scripts/verify_management_comparison.py --root <collection-dir>
```

目录包含 `deepseek_thinking/`、`qwen_nothinking/`、`gpt6_luna/`，以及
`provenance/SCENARIO_GROUPS.json`。DeepSeek 子目录保留已整理的 `summary.csv`；
Qwen、GPT 子目录包含采集的 `runs/`、记录来源与原始文件哈希的 `manifest.json`
（`records[].scenario/collected_cell_dir/source_cell_dir/files`）和回放脚本生成的
`metrics/summary.csv`。每份 CSV 均须完整覆盖推荐 34 场。缺最终报告时还需原始
`progress.jsonl` 及 `cells/<scenario>.json` 初始化配置。

合并器仅连接原运行元数据与回放指标，检查账本恒等式、逐场比值和配置；对于模型已正常
结束而最终评价报错的轨迹，用原始 `llm_call_end.tokens` 恢复 usage，并明确标记原始报告缺失。
它保留任务失败，不调用模型或重新模拟作物。输出每模型 34 行、合并 102 行、逐场宽表及
分类均值；原始 CSV 数值不由手工报表替代。核验器另检查原始文件 SHA 和全部核心指标。
实验原始文件位于 Git 忽略的 `validation_runs/`，不随源码提交。

* `summary_v2.csv` 和带输出目录名的同内容 CSV：兼容旧汇总表，追加产量、经济指标和状态列。
* `management_yields_by_season.csv`：每个 episode × 农场 × 年份 × 作物的 A/O 质量及缺口。
* `management_yields_by_crop.csv`：每个 episode × 作物的跨季合计。
* `management_coverage.json`：注册场景覆盖缺口、轨迹数和各类有效指标数。
* `management_metric_definitions.json`：机器可读名称、公式和有效范围。
* 每轨迹 `management_metrics.json`：投影状态、质量口径、实际账目、分项比较及 Oracle 参考路径；`management_oracles/*.json` 保存配置对应的参考值及两类流程。
