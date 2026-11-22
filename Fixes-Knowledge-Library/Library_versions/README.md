# FAIRY 农业知识库构建计划

**目标**是让同一套流程可以反复接收实验或农场记录，生成 Agronomic Skill、Reflection、Guidance、Observation，按版本发布，供后续任务检索，并能根据新证据更正旧知识。本文是实施规格。下文的源目录和指标来自现有 FAIRY，其余数据库表、prompt、校验和发布接口为拟建内容。

首轮使用 70 个非 L3-mini 的 L3 场景，按 **20 / 20 / 20 / 10 个新场景**分批，累计覆盖 20 / 40 / 60 / 70 个来源。每批冻结一次知识库，再用同一组 mini20 验证。场景集合、批次、来源目录、指标定义和标签词表均由配置提供，后续更换作物、引擎或数据集时复用流程。

## 1. 整理数据源

### 1.1 首轮来源清单与可用性

以[正式 90 场景清单](../../scripts/fullseason/formal_90_scenario_ids.txt)减去 [mini20 清单](../../scripts/fullseason/l3_mini_20_scenario_ids.txt)，得到 70 个唯一 ID。按场景分批，同一场景的所有选中运行进入同一批。mini20 的运行与评估结果只用于验证。以下盘点以 2026-11-22 21:39（上海时间）的 DeepSeek B 进度为界。其 results.csv 当时已有 81 条数据行，最后一条为 `scenario_full_season_hb_dryer_breakdown_between_batches`，文件 SHA256 为 `20d307de0756355a77081b001849f9f4c90d7675b5d53c2ef5da0e4b5dbbdfdb`。正式导入时重新读取并冻结清单。

| Agent 来源目录 | 非 mini、`return_code=0` 运行数 | 本次可用的正式评分汇总 |
|---|---:|---|
| [DeepSeek Flash B](../../validation_runs/l3_formal90_deepseek_flash_B_nothink_El08gq/) | 62 | 核查时目录中尚无对应 rebatch 汇总，登记轨迹并等待同次运行的评分 |
| [DeepSeek Flash BP](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_OL0lel/) | 56 | [11-21 汇总](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_OL0lel/replay_analysis_20261121_34tfrwwj/rebatch_fos/summary_v2_rebatch_fos.csv)，固定这一份，避免与同目录另一轮评分重复计数 |
| [DeepSeek Flash BP rerun](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM/) | 14 | [rerun 汇总](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM/replay_analysis_20261121_qmown_yo/rebatch_fos/summary_v2_rebatch_fos.csv) |
| [Thor Qwen BP](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_lvxtsU/) | 50 | [Thor 汇总](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_lvxtsU/replay_analysis_20261120_3xx6dk_b/rebatch_fos/summary_v2_rebatch_fos.csv) |

此时共 **182 条符合 rc 条件的 Agent 运行**，均找到可解析的工作流和对应报告。其中三个 BP 目录的 **120 条**有同运行、两列均为有限数值的评分，合计覆盖 **70 个场景**。DeepSeek BP 主跑 56 个加 rerun 14 个，在本次筛选下恰好互补。Thor 的 50 条属于独立运行。DeepSeek B 的 62 条待补评分，纳入来源登记，待补齐后生成或更新知识。冻结批次时重扫正在增长的目录，以清单内的哈希和计数为准。

运行完整性单独记录。182 条的 `timed_out` 均为 False，其中 Thor 有一条 `stopped / max_tool_calls`。120 条已有评分中有 16 条报告 `replay_exec_errors > 0`，应检查具体出错动作及其对指标的影响，并在生成包中标注证据范围。这两类情况不会把 `rc=0` 自动改判为失败经验。四个目录的执行代码提交依次为 `1e71d132`、`838c7eef`、`838c7eef`、`8ff57bf`，提取 B 与复核回放时还应核对目录保存的工作区补丁和初始化配置。

**Oracle 来源**固定为 [oracle_140_verification_20261116](../../validation_runs/oracle_140_verification_20261116/)，再按同一 70 个 ID 筛选。`workflows/<id>.json` 是声明的参考流程，`execution_workflows/<id>.json` 保存实际执行的事件与返回，`baselines/<id>.json` 保存产量，`terminal_states/<id>.json` 可复核终态。四类文件共 280 份，与 manifest 哈希一致。70 个回收产量均大于零；5 个场景共 7 个 partial 事件应按实际完成范围记录。基线由生成器在相同配置下另行执行 oracle 得出，关联键是参考包版本与场景 ID，不能把配套基线写成事件日志内直接测得的值。[验证摘要](../../validation_runs/oracle_140_verification_20261116/verification_summary.json) · [参考包生成程序](../../scripts/fullseason/build_time_control_references.py)

### 1.2 一份生成清单确定“用哪几次运行”

**增加生成迭代版本有效，前提是每个版本绑定明确的输入清单。** 例如给一次提炼编号 `gen_001`，同时保存下表中的信息。以后可精确回答“这次修订用了哪个模型的哪一次运行、哪版评分和哪份 prompt”。这些字段用于生成、查错和更正，农业检索只使用第 2 节的检索字段。

| 生成清单内容 | 首版规则 |
|---|---|
| 输入集合 | 记录允许的来源目录、70 个 ID 的批次归属、当批 ID、排除集合、来源类型和纳入条件。本轮纳入四个目录中所有符合条件的运行，保留 B/BP、模型、重复和重跑的区别 |
| 运行身份与评分 | 每个 Agent 输入以“来源目录标识＋目录内 cell 相对路径”定位，校对场景 ID 与 repeat。指标用同一来源目录的 cell 关联。旧绝对路径可映射到已登记根，但歧义须报错。记录 run report、workflow、评分行及文件哈希 |
| Oracle 身份 | oracle 参考版本＋场景 ID，保存执行流程和基线文件的哈希及终态引用。数据来源种类为 `simulated_oracle_replay`。未来真实农场回流沿用 Observation 结构，以 `real_farm_record` 标识并引用其实际作业与收获记录 |
| 生成设置 | 记录基础知识库版本、数据规范与词表版本、指标列、生成或修订 prompt 版本、模型和采样配置。保存原始候选与采纳结果。清单冻结后产生新证据或更换设置，建立下一次迭代 |

同一 cell 的两份评分属于同一次任务的不同评估。清单指定使用哪一份，重新评分通过新迭代更正。两次实际运行即使场景和 repeat 相同，只要来自不同实验根就分别登记。这样可以使用全部授权运行而不任意挑选第一份、最高分或最新一份。

首版建议的版本字段为 `generation_id`（此次提炼）、`source_manifest_sha256`（冻结的输入）、`schema_version`、`taxonomy_version`、`prompt_version`（按类型及生成/修订分别登记）和 `base_release_id`（从哪个库版本开始）。可另加一行 `change_note`，例如“补入上一批 DeepSeek B 的评分，并重审受影响的 Guidance”。同一发布可收录多个生成迭代，每条修订能追到实际迭代；这些管理字段不参与农业检索。

### 1.3 自动构造输入包和指标口径

| 材料 | 自动整理规则 |
|---|---|
| 基础任务 B | 从对应场景版本与初始化配置按 `detailed_briefing=false` 提取基础正文，能取得 `base_sha256` 时核对。BP 与 oracle 的首条 USER 可能包含当前场景计划。给生成器单独传 B，并从工作流输入剔除开场指令、P/G 和系统提示。原运行的 B/BP 条件留在清单中，便于解释其操作来源。[基础正文读取](../../fairy/scenarios/farm_world_fullseason_v2/harbin_l3_context_briefings.py) |
| Agent 工作流 | 读取同一 cell 的 `*.agent_workflow.json`、`*.run_report.json`，必要时查 `*.runtime_log.jsonl`。保留前后次序、时间、工具、参数、返回、错误及证据位置，长轨迹按农事决策切段。截断片段只能支持在截断点前有证据的结论。[运行产物定义](../../fairy/controllers/run_artifacts.py) |
| Agent 指标 | Yield **只取** `recovered_yield_loss(%)`，KTC **只取** `ktc(%)`。读取已锁定的汇总行，校验状态及有限数值。缺失填“待评分”，禁止填 0 或借用近似列。DeepSeek B 可用[现有 rebatch 入口](../../scripts/rebatch_fos_from_traces.py)按固定 oracle 基线、评分代码和回放设置补算，保存汇总后再绑定源清单 |
| Oracle 输入 | B＋执行流程＋同版回放的 `baselines/<id>.json`。绑定 `recovered_yield_kg_total` 作为该流程实际回收量（kg），并记录基线版本与外推情况。声明流程用于核对预期操作，描述发生了什么以执行返回为准 |

Agent 的 `recovered_yield_loss(%) = 100 × (1 − Agent 回收产量 / Oracle 回收产量)`，越低越好，可为负数，分母缺失或不大于零时无定义。`ktc(%)` 是 v1 的原始顺序匹配分数经百分化后的列，取值 0–100，越高表示匹配动作的相对顺序越一致。它和覆盖率、`ktc_score(%)`、`ktc_adjusted(%)` 有不同含义。指标挂在整次运行上，局部操作与全季结果之间的因果判断需要额外证据。[回收损失计算](../../fairy/scenarios/fos/evaluation.py) · [KTC 计算](../../fairy/scenarios/workflow_validation.py) · [汇总列写入](../../scripts/rebatch_fos_from_traces.py)

Observation 的“Oracle 回放 Yield”在来源包中保留实际回收 kg，供过程与结果配对。Agent 的相对损失指标保持上述唯一口径。用同一 oracle 既作分子又作分母会恒为零，不能表达一次回放的产量，Observation 也无需填入 Agent KTC。

## 2. 定义数据库、标签和内容格式

### 2.1 SQLite 与 JSON 的分工

SQLite 保存可查询的条目、修订、证据关联和发布快照。四类正文用 JSON 表达，便于 prompt 输出、人工审阅和导出。大型原始 workflow 继续保存在来源目录，数据库保存可迁移的相对定位与哈希。下面是**拟实施的逻辑表**，表名不构成对现有 FAIRY 接口的声明。

| 表 | 主键与主要字段 | 用途 |
|---|---|---|
| 生成迭代 `generations` | `generation_id`，清单 JSON、清单哈希 | 固定输入、父快照、批次、prompt/词表/schema/模型版本，保留候选及处理报告的引用 |
| 来源包 `sources` | `source_ref`，场景 ID、来源种类、源运行键、B/轨迹/指标与哈希 | 每条运行或 oracle 参考独立登记。修正来源包产生新引用，同一运行的不同评分版不得计作多次运行 |
| 知识修订 `knowledge_revisions` | 联合主键 `(knowledge_id, revision)`，类型、场景、农学标签、极性、正文 JSON、生成迭代 | 稳定 ID 便于修改；增加修订号保留原文。枚举与布尔类型通过应用校验和数据库约束落实 |
| 修订证据 `evidence_refs` | 知识 ID＋修订号＋来源包＋证据定位 | 首版一条知识归属一个来源场景，可引用该场景一个或多个已选运行中的步骤／指标；文件和步骤仅用于生成、审阅、更正 |
| 发布版本 `releases` 与成员 `release_items` | 全库版本、父版本、批次清单与内容哈希；成员键 `(release_id, knowledge_id)` 指向确切修订 | 发布版本如 `structured_knowledge_v01`。每个快照中同一 ID 最多出现一次，导出知识时附上所选版本 |

启用外键，发布成员、修订及证据在一次事务内提交。并行生成候选允许，发布时校验父版本与预期修订。新增来源格式通过适配器转换成同一来源包，新作物／标签通过带版本词表扩展，新正文格式通过 schema 版本迁移。已发布快照仍用当时的解释规则读取。

### 2.2 公共字段

| 字段 | 首版格式与约束 | 使用环节 |
|---|---|---|
| `release_id` | `structured_knowledge_v01` 等，由程序分配给全库快照 | 选择检索版本、评估复现 |
| `knowledge_id`、`revision` | 稳定字符串 ID、从 1 起的修订号。一次内容或标签更正增加修订号 | 更新、复现 |
| `knowledge_type` | `skill / reflection / guidance / observation` | 生成、检索 |
| `source_scenario_id` | 已登记的场景 ID；首版按场景生成 | 来源筛选、排除目标、追溯 |
| `crop`、`cultivars` | 当前作物为 `soybean`；品种／种子类型用受控代码的去重数组。按涉及的田区和动作取值，不能依据仓库库存推断实际品种 | 生成、检索 |
| `growth_stages_before` | 去重数组，指该知识所述动作或决策**之前**的状态，如 `["FAIRY-Engine-R1"]`。多个值表示分别适用，不表示操作顺序 | 生成、检索 |
| `farming_group`、`task_types` | 一个主要农事阶段及一个或多个任务类型；跨阶段的长流程按有独立适用条件的决策片段拆分 | 生成、检索 |
| `source_ref` 和证据位置 | 引用来源包中的步骤、时间、工具返回或指标行。确切垄号、文件和运行身份保留在证据中 | 生成、审阅、更正，不作检索维度 |

**词表初稿。** 作物品种／种子类型沿用 `EARLY_COLD、STANDARD、HIGH_DENSITY、STRESS_TOLERANT、HEIHE43、HEIHE50、HEINONG58、HEINONG60、HEINONG84、HEIKE71`，前四项是通用种子类型。物候标签统一加 `FAIRY-Engine-` 前缀，后接枚举名 `NOT_PLANTED、PLANTED_PRE_EMERGENCE、VE、VC、V1、V2、V3、V4_PLUS、R1、R3、R5、R6、R7、R8`。导入时显式映射实际值（如 `R1_BEGINNING_BLOOM → R1`），记录原始观测。旧显示值可能合并多个阶段，无法唯一还原时保留未知。品种和生长阶段都约定 `null` 为证据不足，`["any"]` 为经核实的跨品种／跨阶段适用，禁止与具体代码混填。[种子类型](../../fairy/apps/farm_world/models.py) · [物候枚举](../../fairy/physics/phenology_engine.py) · [兼容映射](../../fairy/apps/farm_world/physics_orchestrator.py)

农事阶段使用已有三组 `establishment / management / harvest`。具体任务类型先采用现有卡片出现过的 14 个代码，作为首版候选词表，并在第一批审阅覆盖情况：

`field_prep_planting、planting、planting_window、irrigation_planting_window、management_scouting、fertigation、irrigation、fungicide、herbicide、insecticide、mechanical_weed、replant、stand_recovery、harvest_postharvest`。

其中施药、灌溉、补种等可以由场景动作与工具调用辅助标注，复合任务需结合上下文判断。旧库在此仅提供分类词汇。发现词表不能表达的任务时，输出候选新词、含义和实例，审阅后更新词表。缺证据的标签留待核实，不用场景编号猜。观察类知识的流程可包含多个有序步骤；若要以不同阶段分别检索，则分别形成条目。[农事分组](../../fairy/scenarios/farm_world_fullseason_v2/harbin_l3_context_briefings.py) · [场景动作种类](../../fairy/scenarios/farm_world_fullseason_v2/harbin_l3_batch_scenario.py)

### 2.3 四类知识的私有字段

| 类型 | 结构化字段 | 内容验收 |
|---|---|---|
| **Agronomic Skill** | `applicable_when: string`，`pre_checks: string[]`，`constraints: string[]`，`operation_template: string[]`，`post_checks: string[]` | 描述一个可复用操作单元。检查及模板按实际依赖顺序排列，明确参数如何从当前观测取得；检查结果区分执行成功、失败、部分完成 |
| **Agronomic Reflection** | `success: boolean`（可检索），`applicable_when: string`，`content: string` | true 表示总结可肯定的经验，false 表示明确一种错误。正文写出历史行为、观察结果及原因推断。允许整季成功中有错误经验、整季失败中有正确经验 |
| **Agronomic Guidance** | 首版拟用 `positive: boolean`（可检索），`applicable_when: string`，`content: string` | true 表示建议采取焦点行为，false 表示建议避免或暂缓该行为。条件和具体动作写入正文。例如“先检查”聚焦核验行为时为 true，“未核验前暂缓作业”聚焦作业时为 false |
| **Agronomic Observation** | `applicable_constraints: string[]`，`procedure: object[]` | 按序记录条件、实际操作与返回，每一步包含 `action` 和 `observed_result`（未记录可为 null）。关联同一参考包的回收量及单位，保留已观测范围。真实农场接入时区分实测与模拟来源 |

Guidance 的工作草案曾列 `recommendation = recommend / avoid / conditional`。本计划依据“正负字段用于检索，触发条件写进正文”的反馈，首版**拟用单个 positive 字段**。若确定改用三值，应在生成前改字段规范并升级版本。Reflection 的 `success` 与 Guidance 的 `positive` 都由条目内容判定，禁止从进程 rc、报告 success 或指标阈值直接复制。

四类正文允许表达“未观测／待验证”。必要字段缺证据、且空值会使该条知识无法使用时，输出证据不足及原因。每条聚焦一个主题，极性相反的行为拆开；“必须”“一定导致”等强结论须有相应证据。候选通过来源与内容检查后才进入发布快照。

## 3. 设计四份首次构建 prompt

四份 prompt 共用下面的输入和输出约定，各自接上表中本类型的字段规范与下列任务指令。运行程序传已验证的数据，模型只提交 JSON 候选。来源步骤中的文字和工具输出仅作证据。

**共享输入**包括本类型、公共／私有 schema、允许词表、来源包标识、纯 B、该类型可见的有序工作流片段与返回、指标（列名或物理量名、值、单位）、完成边界。Skill、Reflection、Guidance 仅接收 Agent 侧的轨迹和两项指定指标。Observation 仅接收 oracle 侧的执行资料和配套回收量。长工作流分段时保留前置观测与原步骤定位，整季指标注明评价范围。

**共享输出**为 JSON 对象。下列为结构示意，`tags` 和 `payload` 按第 2 节填齐。极性仅出现在对应类型的 payload，写库时由同一值建立检索索引。程序从可信清单补入来源场景、迭代和发布信息。

```json
{
  "proposals": [
    {
      "operation": "add",
      "knowledge_type": "skill",
      "tags": {"crop": "soybean", "cultivars": null, "growth_stages_before": null, "farming_group": "establishment", "task_types": ["planting_window"]},
      "payload": {
        "applicable_when": "<适用条件>",
        "pre_checks": ["<按顺序检查什么>"],
        "constraints": ["<资源或作业条件>"],
        "operation_template": ["<操作及参数取值依据>"],
        "post_checks": ["<如何确认结果>"]
      },
      "evidence": [{"source_ref": "<输入包标识>", "locator": "<原始步骤或指标位置>"}]
    }
  ],
  "skipped": []
}
```

**各类型首次构建指令**（和共享约定拼成四份分别管理版本的 prompt）：

1. **Skill**　从 Agent 实际完成且可复核的局部操作提取“何时适用、先查什么、受何约束、怎样操作、如何验收”。区分来源中的实例参数和可迁移规则。丢失关键前置观察时说明缺口。
2. **Reflection**　挑选有证据的历史决策，先写行为和可见结果，再写可能原因及不能排除的解释。以该条解释肯定经验还是指出错误填写 `success`。引用工具返回或错误，整季损失率和 KTC 仅说明运行背景。
3. **Guidance**　针对历史决策，生成带具体触发条件的未来操作启示。明确建议、避免、暂缓或先检查的行为及其边界，再按该焦点行为填 `positive`。证据仅支持特定土壤、阶段或资源条件时，保留该条件。
4. **Observation**　按发生顺序整理指定 oracle 执行片段，描述作业条件、动作、实参和可观测结果，关联配套回收 kg。对漏测、部分完成或无返回的步骤照实表述。只在来源明确记录时填写效果或现场状态。

**验收**按类型各取一组有证据样例和一组缺证据样例。有效样例能追到源步骤；证据不足时 `proposals` 可为空，`skipped` 应给出对应来源及原因。一个场景可生成零条、一条或多条，生成数量不作为质量指标。

## 4. 检索、挖掘与上下文载入（TODO）

预留独立的知识库来源。接口边界为“输入冻结版本、允许来源、目标场景与检索参数，返回选中条目 ID 和修订号、正文及选择记录”。只在 `detailed_briefing="structured_true"` 的首条 briefing 中加载 G，沿用 B→G→P。默认 `cross_scenario_detailed` 与旧 library 保持独立模式，均不作为本库知识来源。排名算法和渲染细节留待专项设计。[现有来源校验与 G 装配](../../fairy/scenarios/farm_world_fullseason_v2/harbin_l3_structured_briefings.py)

每批可以先完成来源、生成和数据库验收；实际验证**新库对 mini20 的效果**依赖最小读取与 G 载入接口。接口可用后，固定验证清单、模型、种子策略、P 开关与检索配置，记录快照和实际装入的修订。mini20 作为分批开发验证集，相关轨迹和指标隔离于知识生成及修正输入。

## 5. 新数据、修正与迭代

新的运行、重算的指标、修正后的观测都经第 1 节建立新来源包。程序按“同一来源场景＋知识类型”提供上一已发布版本中的候选旧条目，让模型比较适用条件、主题与证据。运行来源本身可以扩充。批次迭代、证据替换和条目身份分别管理。

**四份更新 prompt 的共享约定。** 输入增加旧条目 ID、修订号、正文、原证据、新证据和待更正事项。每份都可提出 `add / revise / keep / retire`。沿用首次构建的 JSON 外壳：`add` 给完整候选；`revise` 给 `knowledge_id`、`expected_revision`、完整新内容、证据和 `reason`；`keep / retire` 给 ID、预期修订、证据和原因。证据不足用 `skipped`。待人工判定的冲突不自动覆盖。模型仅可引用输入中已有的 ID 和证据定位。

| 更新 prompt | 给模型的类型专属指令 |
|---|---|
| Skill | 比较新旧操作的触发条件、顺序、参数来源及验收结果。同一方法出现可复核的补充或错误，修订原条；新增方法或适用条件实质不同则提新增。相似操作名称不足以合并 |
| Reflection | 检查新证据是否支持、削弱或推翻原成因解释。修订时交代变更的事实与推断。若正反经验针对不同决策，保留各自的证据并拆条。单次总分变化不足以翻转 `success` |
| Guidance | 检查原建议在相同触发条件下是否仍成立。反例只涉及一部分条件时，收窄条件或拆分建议；充分证据表明方向错误时，修订内容与极性并说明理由。纯文字重述可保留原条 |
| Observation | 核对新资料对应的观测事件和数据来源。修正同一事件的漏记、结果或配套基线时修订原条；独立的新作业实例保留为新的观察。冲突记录保留可追溯引用，补录结果不得静默改写历史快照 |

**提交与发布规则**

1. 程序以输入清单、来源包哈希、prompt/模型配置及基础版本产生处理键，持久保存本次候选。相同请求重试复用已处理结果。主动重新提炼需新迭代 ID。模型的随机输出不能自行作为去重键。
2. 程序校验候选、来源与证据。完全重复的候选记录为 `keep`；相同标签但含义或证据不同的条目允许并存。证据变化应可修订，即使正文没有变。
3. `revise` 必须命中预期的 ID 和修订。撤回只影响新快照的成员关系，并登记原因。发布事务失败时旧快照仍可用；已验证的快照不可原地改写。
4. 首轮在开始前冻结四组场景 ID。可复算的默认分批方案为按 formal90 原顺序去掉 mini20，依次取 20、20、20、10；若采用主题均衡分批，应先冻结替代清单。第 2 至 4 批分别基于前一发布版本新增来源，可同时更正先前知识。每个快照记录累计来源数、当批新增及更正的条目数和待补项。
5. 发布版本按顺序分配，批次与版本号分别记录。若单独发布更正版本，下次验证绑定新编号。验证发现的问题登记为修订请求，回到授权来源查证后再修订。

### 必要检查和验收口径

| 环节 | 触发条件与处理 |
|---|---|
| 选源 | `SOURCE_OUT_OF_SCOPE`：目录未登记、mini20 被选入来源，或场景重复跨批，阻止冻结。`RUN_ID_MISMATCH`：run、指标行和来源目录不能唯一配对，隔离该包 |
| 评分与轨迹 | `METRIC_MISSING`：列缺失、空或非有限值，登记待评分，其他完备包可继续。`TRACE_MISMATCH`：哈希、基础正文或文件身份不符，停止使用该包。工具错误、partial、max_tool_calls 单独标出可解释范围，不能转成条目极性 |
| 生成 | `INVALID_PAYLOAD`：类型、布尔、字段或词表不合法，返回字段位置。`UNSUPPORTED_CLAIM`：证据定位无效、时间或范围不符、结论超出观测，退回修订。JSON 格式由程序全检，因果解释、方向和可迁移性需要逐批审阅样例及冲突条目 |
| 更正与发布 | `STALE_REVISION`：待修订条目已变化，重新与当前修订比对。`RELEASE_CONFLICT`：清单与快照成员不一致或存在未解决的写冲突，取消本次发布，保留草稿 |
| 验证 | 按场景、运行分别输出“选入、可生成、待补、跳过及原因”。每个 mini20 验证结果都能追到使用的发布版本；来源不足时如实列为缺口。是否发布含已知缺口的快照由发布清单明确，不能用“覆盖 70 个场景”代替运行完整性检查 |

实施顺序为**来源适配与冻结清单 → 建表、词表及 schema → 四类首次生成和样例审阅 → 发布首个快照 → mini20 接入验证 → 后续批次新增和更正**。最小验收可用一个有多次运行的场景及一条已更正知识走通：同场景的 B/BP 轨迹正确配对，重复执行不会重复写入，修订后新旧版本各自能读取原定正文，旧快照的 mini20 输入能够重现。

## Original Library Modes

现有默认 G 和旧 library 的模式、数据源及 map 兼容边界见[现有 library 替换 G 的说明](../README.md#3-用现有library知识替换g)。本设计中的批次和发布版本只统计经上述流程生成的四类知识。
