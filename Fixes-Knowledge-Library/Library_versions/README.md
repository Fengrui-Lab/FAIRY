# FAIRY 知识库构建与迭代计划

**目标**是基于场景基础任务 B、Agent／Oracle 工作流及结果，自动生成四类农事知识，通过结构化 JSON 与固定读写函数存入 SQLite，支持新增、修改、撤回、查询及版本回查。

**实施顺序**为按场景整理材料 → 明确源字段与知识字段 → 建立可读写四类知识的 SQLite → 小样本试验四类 prompt 并修订 → 按 20／20／20／10 个新场景分批循环验证。本文是建设规格，候选词表及 Agent 操作协议通过小样本和覆盖检查后定稿。面向任务的检索 query 暂定只使用纯 B，具体匹配和 G 装配留作后续接入。

## 一、FAIRY 知识库设计

### 1. 四类知识及其来源

| 类型 | 构建材料 | 一条知识表达的内容 |
|---|---|---|
| Agronomic Skill | B＋Agent 工作流＋Yield 和 KTC | 一个可复用的操作方法，含条件、检查、约束、步骤与结果确认 |
| Agronomic Reflection | B＋Agent 工作流＋Yield 和 KTC | 对一个历史经验或错误的成因解释 |
| Agronomic Guidance | B＋Agent 工作流＋Yield 和 KTC | 一个条件明确的未来行为建议 |
| Agronomic Observation | B＋Oracle 工作流＋配套回放 Yield | 一次可识别的事件或连续农事过程 |

当前 Oracle 来源标为 `simulated_oracle_replay`。未来真实农场回流标为 `real_farm_record`，使用同一 Observation 内容结构，保留实际作业和收获证据。先完整整理场景材料，再决定生成哪些主题和多少条知识，允许某一类没有足够证据产出。

### 2. 公共标签与管理信息

| 标签 | 格式与含义 | 填写依据 |
|---|---|---|
| `source_scenario_id` | 来源场景 ID，首版每条归属一个场景 | 材料包填写，同一条可关联该场景多次运行 |
| `crop` | 当前枚举为 `soybean` | B 或实际记录中的作物 |
| `cultivars` | 品种／通用种子类型代码数组，未知为 null | B 中明示品种及目标田块实际播种或状态 |
| `growth_stages_before` | 该条知识开始适用时的物候标签数组，未知为 null | 对应田块操作前观测及引擎映射 |
| `farming_group` | 主要农事阶段，`establishment / management / harvest` | 知识的核心农事目标 |
| `task_types` | 非空、去重的任务代码数组 | 按第 3 节的目标与边界归类 |

品种和物候标签描述有证据支持的适用范围，Observation 对应记录实际发生时的条件。`null` 表示未知，`["any"]` 表示有依据认为该维度不构成限制。具体代码数组非空、去重，按词表顺序规范化，禁止 `[]` 及 any 与具体代码混填。知识内容中的步骤保留实际依赖顺序。

品种／种子类型使用 `EARLY_COLD、STANDARD、HIGH_DENSITY、STRESS_TOLERANT、HEIHE43、HEIHE50、HEINONG58、HEINONG60、HEINONG84、HEIKE71`。前四项属于通用种子类型。库存反映可用资源，品种标签依据实际任务和田块取值。[种子定义](../../fairy/apps/farm_world/models.py)

物候使用 `FAIRY-Engine-` 前缀及 14 个状态 `NOT_PLANTED、PLANTED_PRE_EMERGENCE、VE、VC、V1、V2、V3、V4_PLUS、R1、R3、R5、R6、R7、R8`。保存原始观测，显式映射引擎值，如 `R1_BEGINNING_BLOOM → R1`。旧显示值合并了多个状态时，结合对应版本和同一田块的证据判断，无法唯一确定则留 null。[物候定义](../../fairy/physics/phenology_engine.py) · [兼容映射](../../fairy/apps/farm_world/physics_orchestrator.py)

管理信息单列。`knowledge_id` 是稳定知识身份，`revision` 从 1 开始，`knowledge_type` 为 `skill / reflection / guidance / observation`。发布版本使用 `structured_knowledge_v01、v02…`，导出时附 `release_id`。来源运行、文件、步骤和生成设置用于核查与更正，农业检索使用上表标签。

### 3. task_types 的候选集合与覆盖要求

分类以 **L2 级农事目标**为单位，一个片段包含问题或条件、观察判断、操作或暂缓决定及结果检查。常规充电、补给、等待、装卸农具等步骤随所属任务保留。相同目标下的方法、用量、天气和设备限制写入正文。多个独立决策目标分别成条，紧密关联的目标可使用多个 task_types。[现有 L2 划分原则](../../fairy/scenarios/farm_world_fullseason_v2/l2_l1_splits/l3-to-l2-l1-split-guide.zh.md)

2026-11-23 对 70 个非 mini 场景的只读盘点覆盖了 17,862 条 Oracle 工具事件、42 种工具。现有原生 L2 文件仅覆盖其中 21 个来源场景的 75 个 L2，pilot 卡片覆盖 20 个来源场景的 72 个 L2。下面的 13 类据此作为首版候选，完整 L2 片段覆盖仍须逐项验收。[Oracle 执行资料](../../validation_runs/oracle_140_verification_20261116/execution_workflows/) · [已有 L2 拆分](../../fairy/scenarios/farm_world_fullseason_v2/l2_l1_splits/)

| 候选代码 | 目标与边界 |
|---|---|
| `field_preparation` | 播前土壤条件、整地、基肥、起垄及复查；播种执行归 planting |
| `planting` | 品种／密度、播种窗口、种床条件判断和播种；合并旧播种与播种窗口代码 |
| `crop_monitoring` | 独立的出苗、物候、长势巡查与复查，包括有依据的继续观察；治疗过程中的检查随治疗类型 |
| `stand_recovery` | 缺苗、断垄、板结等诊断及补种恢复，包含旧 replant 与 stand_recovery |
| `irrigation` | 水分诊断、灌溉时机／范围／用量和复查；为播种改善墒情时可同时标 planting |
| `nutrient_management` | 营养诊断、追肥／水肥恢复及复查；建植中的常规基肥随 field_preparation |
| `weed_management` | 杂草诊断、化学或机械控草决策和复查；具体方式写入模板与约束 |
| `disease_management` | 病害确认、杀菌窗口、处理与病情复查 |
| `insect_management` | 虫情判断、喷洒或人工点喷及复查 |
| `resource_scheduling` | 以有限资源、作业次数、设备或处理容量的分配为核心的决策；普通库存查询、补给随所属作业 |
| `harvest` | 成熟度、水分、天气与可作业性判断，分区收获及卸粮 |
| `grain_drying` | 收获粮食的水分、干燥能力和成本判断，批次安排及结果检查 |
| `grain_storage` | 入库水分、仓容与储藏条件确认，分批入库及存量复查 |

`farming_group` 表示该条的主要阶段，任务类型表示决策目标，两者分别填写。旧的 `harvest_postharvest` 在本版展开为收获、烘干和入库，连续过程可以关联多个类型。设备或预算限制根据实际影响的作业表达；只有资源分配本身构成独立决策时标 resource_scheduling。[储藏容量 L2 示例](../../fairy/scenarios/farm_world_fullseason_v2/l2_l1_splits/hb_storage_capacity_limit_batching/scenario_l2_harvest_capacity_batching.py) · [人工点喷 L2 示例](../../fairy/scenarios/farm_world_fullseason_v2/l2_l1_splits/hb_insect_after_fungicide_budget_conflict/scenario_l2_r5_insect_budget_manual_control.py)

**词表定稿前建立覆盖表。** 按 70 个场景列出 L2 级片段、来源步骤、独立目标、结果及 task_types，并检查选中 Agent 运行出现的额外操作。所有农事操作和独立巡查／暂缓决定均有归属，辅助步骤关联其服务的片段。不能归类时报告 `UNCLASSIFIED_TASK`，交叉过多或单类过长时调整边界。覆盖表通过后冻结 `taxonomy_version`，新增任务通过版本扩展。

### 4. 四类私有字段

| 类型 | payload 格式 | 写作要求 |
|---|---|---|
| Skill | `applicable_when` 字符串，`pre_checks`、`constraints`、`operation_template`、`post_checks` 为字符串数组 | 写清触发条件、检查目的与依赖、参数如何取得、操作和验收。每个数组元素尽量表达一个检查或动作 |
| Reflection | `success` 布尔值，`applicable_when`、`content` 字符串 | true 表示肯定经验，false 表示指出错误。正文写历史行为、可见结果、原因推断和不确定处 |
| Guidance | `recommendation` 为 `recommend / avoid / conditional`，`applicable_when`、`content` 字符串 | 写清未来行为和触发条件；conditional 给出补充检查如何决定行动或暂缓 |
| Observation | `applicable_constraints` 字符串数组，`procedure` 为有序对象数组，每步含 `action` 字符串及 `observed_result` 字符串或 null | 按实际过程记录参数、覆盖范围、结果、失败或 partial，数值带单位 |

Reflection 的 success 描述经验方向，成功完成的运行也可产生指出局部错误的条目。四类正文可围绕同一主题分别表达方法、成因、建议和事实，按各自用途检查重复。

必要正文非空，检查、模板和流程为非空数组。约束暂缺可用空数组并报告缺口，未记录的结果为 null。无法形成有依据的知识时跳过。Observation 通过来源运行和步骤范围定位过程，首次接受后登记稳定 `episode_ref`；同一过程补录沿用身份，新运行的实例另行登记。

## 二、FAIRY 知识库数据来源

### 1. 来源集合与场景材料包

首轮使用[正式 90 场景](../../scripts/fullseason/formal_90_scenario_ids.txt)排除 [L3-mini 20](../../scripts/fullseason/l3_mini_20_scenario_ids.txt)后的 70 个场景。五个 Agent 来源中，纳入这些场景的 `return_code=0` 运行，同场景不同模型、B/BP 和重跑分别保留。每次生成冻结具体文件及评分行，按“来源根＋cell 路径”配对工作流、报告和分数。

| 来源 | 允许目录 | 评分材料 |
|---|---|---|
| DeepSeek Flash B | [l3_formal90_deepseek_flash_B_nothink_El08gq](../../validation_runs/l3_formal90_deepseek_flash_B_nothink_El08gq/) | [20261122_0x7es521 汇总](../../validation_runs/l3_formal90_deepseek_flash_B_nothink_El08gq/replay_analysis_20261122_0x7es521/rebatch_fos/summary_v2_rebatch_fos.csv) |
| DeepSeek Flash BP | [l3_formal90_deepseek_flash_BP_nothink_OL0lel](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_OL0lel/) | [20261121_34tfrwwj 汇总](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_OL0lel/replay_analysis_20261121_34tfrwwj/rebatch_fos/summary_v2_rebatch_fos.csv) |
| DeepSeek Flash BP rerun | [l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM/) | [20261121_qmown_yo 汇总](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM/replay_analysis_20261121_qmown_yo/rebatch_fos/summary_v2_rebatch_fos.csv) |
| Thor Qwen BP | [l3_formal90_thor_qwen35b_BP_nothink_lvxtsU](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_lvxtsU/) | [20261123_ccsvhd_7 汇总](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_lvxtsU/replay_analysis_20261123_ccsvhd_7/rebatch_fos/summary_v2_rebatch_fos.csv) |
| Thor Qwen BP rerun | [l3_formal90_thor_qwen35b_BP_nothink_rerun_BvciC0](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_rerun_BvciC0/) | [20261123_rxp1itc_ 汇总](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_rerun_BvciC0/replay_analysis_20261123_rxp1itc_/rebatch_fos/summary_v2_rebatch_fos.csv) |
| Oracle | [oracle_140_verification_20261116](../../validation_runs/oracle_140_verification_20261116/) | 同场景执行工作流及 baselines 中的回收量 |

**Oracle 按场景统一绑定。** 对比上述 Oracle 包与历史评分使用的 `oracle_time_control_20261116/advance_time_v2`，70 个场景的回收量、声明流程，以及实际执行中的有序工具参数、时间和农事结果全部一致，执行记录仅有随机巡查／任务 ID 差异。两个 manifest 的 430 个来源代码哈希相同，相关场景、引擎和工具代码与当前工作区核对一致。五个 Agent 来源中选定的 210 条评分，其 Oracle 回收量也全部与指定 Oracle 包一致。因此首版在固定场景版本下，每个场景材料包绑定一套 Oracle 与配套 Yield，历史文件路径保留在来源记录中。[指定 Oracle manifest](../../validation_runs/oracle_140_verification_20261116/manifest.json) · [历史参考 manifest](../../validation_runs/oracle_time_control_20261116/advance_time_v2/manifest.json) · [Oracle 构建入口](../../fairy/scenarios/workflow_validation.py)

| 材料包部分 | 原始文件与整理内容 |
|---|---|
| 基础任务 `base_tasks` | 从对应版本按 `detailed_briefing=false` 提取纯 B，保存正文和哈希。各次运行引用实际 B，正文一致时共用 |
| Agent 运行 `agent_runs` | 根目录 `results.csv`，cell 内 `*.agent_workflow.json`、`*.run_report.json`，按需查 `*.runtime_log.jsonl`。保存完整顺序、调用、返回、错误、运行条件及评分 |
| 场景 Oracle `oracle` | `execution_workflows/<id>.json` 与 `baselines/<id>.json`；声明 `workflows/<id>.json` 和 `terminal_states/<id>.json` 用于核对 |
| 来源清单 | 来源身份、文件／评分行定位、哈希、版本、缺失项。原始内容保存不可变副本或引用可恢复的归档 |

原始材料完整归集，生成时可分页读取。BP 开场指令中包含的 P/G 与系统指令从生成视图剔除，纯 B 单独传入，原始运行条件保留。当前五个 Agent 根目录分别有 70／56／14／50／20 个非 mini 的 rc=0 运行，合计 210 次。五个来源的 210 次运行均已有配对评分和两项分数，第五来源的 20 次与 Thor 主跑的 50 次恰好互补，每个场景共有 3 次材料齐备的运行。正式导入时重新扫描并冻结清单。[运行产物定义](../../fairy/controllers/run_artifacts.py)

### 2. 分数及解释

每次 Agent 运行的 `scores` 只保存以下两项分数及解释，来源身份和评分文件位置由运行记录提供。解释由程序按固定口径生成，数据缺口或回放问题据报告补充。

| scores 中的键 | 子字段 | 解释与校验 |
|---|---|---|
| `recovered_yield_loss_pct` | `value` 数值或 null，`explanation` 字符串 | `100 × (1 − Agent 回收量 / Oracle 回收量)`，越低越好。**负数表示 Agent 回收量高于 Oracle，是该指标上的好结果**，例如 −5% 表示高出 5%。允许负数，禁止截为 0；分母缺失或不大于零时无定义 |
| `ktc_pct` | `value` 数值或 null，`explanation` 字符串 | 对应 `ktc(%)`，v1 已匹配动作的相对顺序分数，范围 0–100。高分需结合实际完成范围和 Yield 理解 |

两个回收 kg 保留在原始评分文件，整理时可复核公式。现有 JSON 和 CSV 均经过舍入，校验采用与保存精度一致的容差。Oracle 的配套 `recovered_yield_kg_total` 按 kg 保存在场景包内。整季评分通过来源关联到知识，局部成因和操作效果引用相应步骤。[指标公式](../../fairy/scenarios/fos/evaluation.py) · [KTC 计算](../../fairy/scenarios/workflow_validation.py) · [报告精度](../../fairy/scenarios/fos/metrics.py)

### 3. 源字段与知识字段的对应

| 原始内容 | 对应知识字段 | 使用方法 |
|---|---|---|
| B 中的作物、品种、明示条件、风险和任务 | crop、cultivars、适用条件、任务主题 | 明示内容直接提取，风险涉及的具体田区由观测核实 |
| 工作流 `name/time/depends_on`，可选时间扩展字段 | 检查、操作及流程顺序 | 保留原步骤和时间关联，允许跨步骤回查 |
| `tool_name/tool_args` | task_types、操作模板、流程动作 | 结合任务目的归类，参数说明请求内容 |
| `content.ridges[]` 中的品种、物候、已播状态 | cultivars、growth_stages_before、适用条件 | 使用目标田块操作前的实际观测 |
| 苗情、营养、水分、天气、病虫、库存与设备返回 | 适用条件、pre_checks、constraints | 保留单位、时点和覆盖范围，归纳为可判断条件 |
| `status/error`、实际覆盖、完成垄、后续复查 | post_checks、Reflection、Guidance、Observation 结果 | 结合行为与返回解释结果，部分完成和错误照实记录 |
| 两项 Agent 分数及解释 | 前三类知识的整季结果背景 | 支持比较历史运行，具体经验方向由正文与步骤证据判定 |
| Oracle 实际执行及配套回收量 | applicable_constraints、procedure | 描述发生的过程，局部收获量和全季回收量注明各自范围 |

Skill 将事实整理为方法，Reflection 解释历史成因，Guidance 转为未来决策，Observation 记录过程。字段与证据的对应关系由四类 prompt 明确，并在输出中保存具体来源定位。

## 三、FAIRY 知识库的更新与迭代

### 1. 四类 Agent 共用的生成与比较流程

**本版建议统一首次和后续调用。** 每类知识维护一套 prompt，输入均为“共享规则＋类型字段与写作规范＋场景材料＋已有相关知识＋本批待写候选”。空库时已有知识为空；已有库时先读出相关条目。后续都经过比较和去重。bootstrap／maintain 可作为调用状态描述，共用这一流程。

仅允许首次 add 无法避免内容重叠。提交前需比较“新候选与已有库”和“同批候选之间”的核心主张、适用条件及证据。同场景多次运行先归集，完全重复候选归并，语义相近候选由 Agent 判断补充、修订或分别保留；并行生成后统一检查再写入。

首版 source_scenario_id 为单值，同场景、同类型的等价知识可以合并证据。跨场景相似内容保留各自来源身份，登记为相似候选，供后续明确合并规则。若要求跨场景只存一条知识，需同时定义多场景来源与排除目标场景的语义，此项待商议。同主题的不同知识类型按各自用途检查冗余。

| 类型 prompt | 归纳与更新指令 |
|---|---|
| Skill | 提炼适用条件、观察顺序、约束、操作方法和后检查；新证据补足同一方法时修订，独立方法新增 |
| Reflection | 先写历史行为和可见结果，再写原因推断与不确定性；新事实影响旧解释时说明修改依据 |
| Guidance | 写将来采取、避免或按检查结果选择的行为；反例涉及部分条件时收窄条件或拆开建议 |
| Observation | 按实际执行整理过程；相同 episode 的补录或纠错采用修订，独立实例采用新增 |

共享规则要求来源和时点可核查，实际覆盖取返回，事实、归纳与推断表达清楚。原始 Agent 轨迹用于解释历史观察，评分用于说明其评估结果。单次高分或行为先后不足以证明局部因果或必要顺序。具体数值作为实例保留，通用阈值和方法约束须有证据。

### 2. 中间 JSON 与增删改的暂定语义

以下协议用于小样本试验，重点核验重复内容、keep 与 retire 的边界。

| 结果 | 判定 | 写入行为 |
|---|---|---|
| `add` | 新的有效主题或适用情境，且比较后无等价条目 | 新 knowledge_id，revision=1 |
| `revise` | 同一知识的内容、标签或证据需补足／更正 | 保持 ID，增加修订号，提交完整新记录 |
| `no_change`（原 keep） | 比较后已有内容和证据足够 | 写入比较报告，沿用旧修订；未提到的旧条目也沿用 |
| `retire` | 有证据确认错误、失效，或已被其他条目完整替代 | 从新版本有效成员中撤回，历史版本保留 |
| `pending` | 缺证据、归属不明或冲突未解决 | 保存原因，待补材料或复核 |

keep 作为“比较后无变更”的报告结果。正文相同但需要增加已接受证据时使用 revise。retire 是有明确对象和理由的撤回提案，证据冲突或暂缺材料先进入 pending。替代条目与关联撤回一起核验和提交。这些语义须在小样本评审中确认。

中间 JSON 使用 `changes` 数组提交 add／revise／retire，`notes` 数组记录 no_change／pending。下例为格式模板，实际值由材料和现有知识提供。

```json
{
  "changes": [
    {
      "operation": "revise",
      "knowledge_id": "<现有 ID>",
      "expected_revision": 1,
      "knowledge_type": "guidance",
      "tags": {
        "crop": "soybean",
        "cultivars": null,
        "growth_stages_before": null,
        "farming_group": "management",
        "task_types": ["stand_recovery"]
      },
      "payload": {
        "recommendation": "conditional",
        "applicable_when": "<修订后的适用条件>",
        "content": "<检查后满足哪些条件才行动，否则如何处理>"
      },
      "evidence": [
        {
          "source_ref": "<材料标识>",
          "locators": ["workflow#/<步骤 ID>/content"],
          "fields": ["/payload/content"]
        }
      ],
      "reason": "<新证据及修改理由>"
    }
  ],
  "notes": []
}
```

add 省略旧 ID 和 expected_revision，由程序分配身份。revise 提交完整 tags、payload 和证据，retire 提交旧 ID、预期修订、理由和证据。因替代而撤回时另带 replaced_by 数组，每项使用 `{"knowledge_id": "已有ID"}` 或 `{"change_index": 0}`，后者指向本批 changes 中 add 的零基索引。替代目标须在新版本有效，关联候选未通过时撤回也暂缓提交。

全部非空标签和正文主张需要证据对应，示例仅展示一项。场景身份、输入版本和生成配置由调用端的可信 context 提供。notes 每项包含 status、来源或旧知识 ID 及 reason。模型输出只允许引用已提供的 ID 与来源。

### 3. SQLite 与固定读写函数

第一步建立能存入并读回四类知识的 SQLite。标量标签存普通列，数组、各类型 payload 和 evidence 存 JSON，写入函数按类型 schema 校验。查询通过固定函数内的参数化 SQL 实现，结果序列化为 JSON。相同函数可在后续封装为 Agent 工具。

| 首版逻辑表 | 内容 |
|---|---|
| `sources` | 场景包及来源运行的身份、材料定位、归档哈希、分数与解释；更正材料创建新来源版本 |
| `knowledge_revisions` | `(knowledge_id, revision)`，类型、来源场景、农学标签、payload、evidence 及对应写入批次 |
| `releases`、`release_items` | 发布版本、父版本、规范与词表版本、提交记录；每个发布中知识 ID 对应确切 revision |
| `change_batches` | request_id、基础版本、输入清单、prompt／模型配置、原始 JSON、检查结果及最终发布 ID |

| 固定函数接口草案 | 职责 |
|---|---|
| `init_db()` | 创建表与约束，支持四类 schema 及版本 |
| `validate_changes(context, proposal)` | 检查字段、枚举、来源、重复候选和目标修订，返回错误位置与原因；语义检查结果附在批次记录中 |
| `apply_changes(request_id, base_release_id, context, proposal)` | 从可信 context 填入场景及来源信息，原子应用 add／revise／retire，保存 notes、修订及新快照；重复请求返回原结果 |
| `get_knowledge(release_id, knowledge_id)` | 读取指定发布绑定的完整条目 |
| `query_knowledge(release_id, filters, pagination)` | 按类型、场景、标签和私有方向字段筛选，确定性排序并返回 JSON |
| `get_history(knowledge_id)`、`export_release(release_id)` | 回查修订与证据，导出指定版本 |

release_id 使用 `structured_knowledge_v01` 等。变更在事务外生成并检查，事务内校验基础版本和 expected_revision，再一起写入操作记录、知识修订及发布成员。相同 request_id 必须对应相同输入，重试已经成功的请求返回原发布，冲突返回明确错误。并行候选合并时，同一旧 ID 的互斥操作先解决冲突。旧快照始终引用原有修订。

未修改的条目沿用父版本，撤回只改变新版本成员。JSON 导出来自指定数据库快照，拟修改内容通过中间 JSON 和写入函数进入新版本。来源、规范或 prompt 发生变化时，写入批次保留其版本与设置，以便复核。

查询层先确定基本合同。跨字段条件使用 AND，数组字段显式选择 ANY／ALL；有字段筛选时未知值默认不匹配，可通过参数纳入。类型私有条件只适用于相应知识类型。分数按来源返回，指标条件如后续接入，应在同次运行内同时满足。待运行场景以纯 B 提供任务输入，B 如何转成筛选／匹配条件及结果如何装入 G，后续再接入。

## 四、实施方案与验收

| 阶段 | 交付物 | 验收 |
|---|---|---|
| 1. 整理场景材料 | 五个 Agent 来源和 Oracle 的冻结清单、材料包、源字段说明、缺失报告 | 运行与评分正确配对，Oracle 按场景绑定，来源可回读 |
| 2. 明确字段并建库 | JSON Schema、任务词表及 70 场景片段覆盖表、SQLite、固定读写函数 | 四类完整写入与读回；合法负损失率被保留，非法字段有明确报错 |
| 3. 小样本 prompt 试验 | 四套共享流程的类型 prompt、中间 JSON、检查与比较报告 | 首次生成和追加都检查重复，能判断新增、修订、无变更、撤回及待处理 |
| 4. 验证修订和查询 | 固定增删改查案例、版本回查与导出结果 | 重试不重复新增，旧版本可恢复，更新冲突可定位，撤回及替代成组完成 |
| 5. 分批循环 | 按 formal90 顺序排除 mini20，冻结 20／20／20／10 个新场景，累计 20／40／60／70 | 每批记录新增、修订、撤回、无变更和待补项，查询与固定更新案例回归通过 |

小样本建议从首批非 mini 场景中选 3–5 个，覆盖成功运行里的局部错误、partial、多次运行差异、缺分数或缺证据、同事件补录及独立新事件。必要异常可用明确标记的测试夹具验证。样例通过后计入首批，利用相同写入身份避免重复导入。

每批库版本准备后运行 mini20 的 Agent 效果验证，依赖后续完成 B 查询和 G 载入接口。此前先完成数据库与生成流程的验收。mini20 结果绑定知识版本、模型、种子及载入配置，作为开发验证反馈；生成和更正内容从建库来源取证。

必要错误包括 `SOURCE_OUT_OF_SCOPE`、`RUN_ID_MISMATCH`、`METRIC_MISSING`、`UNCLASSIFIED_TASK`、`INVALID_PAYLOAD`、`UNSUPPORTED_CLAIM`、`STALE_REVISION`、`RELEASE_CONFLICT`。报告返回具体场景、运行、字段或知识 ID 与原因，来源缺失和未决候选保留待处理，其他完备材料可继续。

**当前待定项**为 13 类任务词表的逐片段覆盖验收、跨场景相似知识的合并策略、no_change／retire 的小样本判定规则，以及纯 B 的匹配与 G 载入。首版可以先完成四类知识存储和固定函数，再逐项用真实材料校准。

## Original Library Modes

默认 G、`reusable_operational_guidelines` 和旧 library 各自独立管理。四类新知识按本文来源和生成流程建设。旧模式的数据源、参数及 map 兼容说明见[现有 library 替换 G 的说明](../README.md)。
