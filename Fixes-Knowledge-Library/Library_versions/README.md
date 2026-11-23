# FAIRY 知识库设计方案

**目标**是基于场景基础任务 B、Agent／Oracle 工作流及结果，自动构建四类农事知识。数据先按场景归集，再按单次运行提炼候选，最后在场景内整理形成正式知识，使用 SQLite 与结构化 JSON 支持增删改查和版本回查。

**数据流**为“场景材料包 → 单次运行提炼 → 第一张候选知识表 → 同场景同类型整理 → 第二张正式知识表 → 按发布版本查询／导出”。一个场景有多次 Agent 运行和一套 Oracle 记录。前期各环节产物由用户审阅、主导和判断，prompt 与处理规则校准后再逐步托管给 Agent。本文定义数据、字段和接口，任务词表仍需覆盖验收，具体程序为拟建内容。

## 一、FAIRY 知识库设计

### 1. 四类知识及其来源

| 类型 | 构建材料 | 一条知识表达的内容 |
|---|---|---|
| Agronomic Skill | B＋单次 Agent 工作流＋该次 recovered_yield_loss | 一个可复用的操作方法，含条件、检查、约束、步骤与结果确认 |
| Agronomic Reflection | B＋单次 Agent 工作流＋该次 recovered_yield_loss | 对一个历史经验或错误的成因解释 |
| Agronomic Guidance | B＋单次 Agent 工作流＋该次 recovered_yield_loss | 一个条件明确的未来行为建议 |
| Agronomic Observation | B＋一次 Oracle 执行记录＋配套回放 Yield | 一次可识别的事件或连续农事过程 |

当前 Oracle 来源标为 `simulated_oracle_replay`。未来真实农场回流标为 `real_farm_record`，使用同一 Observation 内容结构，保留实际作业和收获证据。每次 Agent 运行分别支持前三类提炼，Oracle 记录支持 Observation。每类可以产出零条、一条或多条候选，所有候选保留各自来源。

### 2. 公共标签与管理信息

| 标签 | 格式与含义 | 填写依据 |
|---|---|---|
| `source_scenario_id` | 来源场景 ID，每条归属一个场景 | 候选对应该场景的一次源记录，正式知识可关联该场景多次运行的候选 |
| `crop` | 当前枚举为 `soybean` | B 或实际记录中的作物 |
| `cultivars` | 品种／通用种子类型代码数组，未知为 null | B 中明示品种及目标田块实际播种或状态 |
| `growth_stages_before` | 该条知识开始适用时的物候标签数组，未知为 null | 对应田块操作前观测及引擎映射 |
| `farming_group` | 主要农事阶段，`establishment / management / harvest` | 知识的核心农事目标 |
| `task_types` | 非空、去重的任务代码数组 | 按第 3 节的目标与边界归类 |

品种和物候标签描述有证据支持的适用范围，Observation 对应记录实际发生时的条件。`null` 表示未知，`["any"]` 表示有依据认为该维度不构成限制。具体代码数组非空、去重，按词表顺序规范化，禁止 `[]` 及 any 与具体代码混填。知识内容中的步骤保留实际依赖顺序。

品种／种子类型使用 `EARLY_COLD、STANDARD、HIGH_DENSITY、STRESS_TOLERANT、HEIHE43、HEIHE50、HEINONG58、HEINONG60、HEINONG84、HEIKE71`。前四项属于通用种子类型。库存反映可用资源，品种标签依据实际任务和田块取值。[种子定义](../../fairy/apps/farm_world/models.py)

物候使用 `FAIRY-Engine-` 前缀及 14 个状态 `NOT_PLANTED、PLANTED_PRE_EMERGENCE、VE、VC、V1、V2、V3、V4_PLUS、R1、R3、R5、R6、R7、R8`。保存原始观测，显式映射引擎值，如 `R1_BEGINNING_BLOOM → R1`。旧显示值合并了多个状态时，结合对应版本和同一田块的证据判断，无法唯一确定则留 null。[物候定义](../../fairy/physics/phenology_engine.py) · [兼容映射](../../fairy/apps/farm_world/physics_orchestrator.py)

两张表共用上述标签及四类 payload 定义。`knowledge_type` 为 `skill / reflection / guidance / observation`。管理字段在第 5 节定义，来源运行、步骤和生成设置用于核查与更正。发布版本使用 `structured_knowledge_v01、v02…`，正式知识导出时附 release_id。

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

### 5. 两张知识表的字段边界

**第一张表 `knowledge_candidates` 保存逐次提炼结果。** 一行对应某次源运行的一条候选，内容可以与其他运行的候选相似。候选行固定后保留原文，源材料或 prompt 更正后生成新行，通过提炼请求关联前次结果。

| 字段 | 类型与约束 | 来源及边界 |
|---|---|---|
| `candidate_id` | 字符串主键 | 程序分配，同一提炼请求重试复用已有 ID |
| `source_scenario_id` | 非空字符串 | 从可信材料包填写 |
| `source_ref` | 非空来源引用 | 唯一指向一次 Agent 运行或一次 Oracle 记录的冻结材料，含对应 B 和结果 |
| `knowledge_type` | 四类枚举 | 与本次类型 prompt 一致 |
| `crop` | 字符串 | 按公共标签规范填写 |
| `cultivars` | JSON 数组或 null | 该次来源支持的适用范围 |
| `growth_stages_before` | JSON 数组或 null | 该次来源中的操作前物候证据 |
| `farming_group` | 三值枚举 | 候选主题所属的主要农事阶段 |
| `task_types` | 非空 JSON 数组 | 受本次词表版本约束 |
| `payload` | JSON 对象 | 按知识类型使用第 4 节的完整字段 |
| `evidence` | 非空 JSON 数组 | 每项为 source_ref、原文定位 locators、对应知识字段 fields，均来自本次源记录 |
| `episode_ref` | 字符串或 null | Observation 的稳定过程身份，由程序按源事件登记；其他类型为 null |
| `extraction_request_id` | 非空字符串 | 关联本次单运行提炼的输入、prompt／模型配置、原始输出和审阅记录 |

**第二张表 `knowledge_revisions` 保存整理后的正式知识及历史修订。** 一行是一条正式知识的一个修订，当前可用内容由发布成员关系确定。

| 字段 | 类型与约束 | 来源及边界 |
|---|---|---|
| `knowledge_id`、`revision` | 字符串＋正整数联合主键 | 稳定知识身份及修订号，首次为 1，修改追加新修订 |
| `source_scenario_id` | 非空字符串 | 与所有关联候选属于同一场景 |
| `knowledge_type` | 四类枚举 | 与所有关联候选类型一致 |
| `crop` | 字符串 | 整理后的适用作物，需有源证据 |
| `cultivars` | JSON 数组或 null | 整理后的适用范围，合并时核对条件兼容性 |
| `growth_stages_before` | JSON 数组或 null | 该正式条目开始适用的物候范围，无法确定时保留未知 |
| `farming_group` | 三值枚举 | 正式知识的主要农事阶段 |
| `task_types` | 非空 JSON 数组 | 凝练后主题对应的任务代码 |
| `payload` | JSON 对象 | 合并、凝练或修订后的完整正文，遵循相同类型 schema |
| `candidate_ids` | 非空、去重的 JSON 数组 | 支持该修订的完整候选 ID 集合，可包含历史候选与本轮新候选 |
| `evidence` | 非空 JSON 数组 | 正式字段到原始步骤的证据，来源限于所关联候选的源记录 |
| `episode_ref` | 字符串或 null | Observation 保留同一过程身份，独立事件分别成条；其他类型为 null |
| `consolidation_request_id` | 非空字符串 | 关联场景内整理的输入候选、处理决定、审阅及写入结果 |

来源分数及解释存于 source_ref 对应材料中，两张知识表通过关联取得。一个候选可以支持多条正式知识，多条候选也可以支持同一正式知识。正式修订保留完整 candidate_ids 和字段级 evidence，能够逐层追到原始运行。相同标签不会自动产生同一知识身份。

release_id 在发布成员表中绑定确切 `(knowledge_id, revision)`，导出时加入正式记录。候选审阅是否通过、候选在某次整理中是否采用分别记入对应请求的审阅报告，候选表本身保存不可变提炼结果。两张表共用 schema／词表版本，版本号通过各自请求及发布记录确定。

## 二、FAIRY 知识库数据来源

### 1. 来源集合与场景材料包

首轮使用[正式 90 场景](../../scripts/fullseason/formal_90_scenario_ids.txt)排除 [L3-mini 20](../../scripts/fullseason/l3_mini_20_scenario_ids.txt)后的 70 个场景。六个 Agent 来源中，纳入这些场景的 `return_code=0` 运行，同场景不同模型、B/BP 和重跑分别保留。每次生成冻结具体文件及评分行，按“来源根＋cell 路径”配对工作流、报告和分数。

| 来源 | 允许目录 | 评分材料 |
|---|---|---|
| DeepSeek Flash B | [l3_formal90_deepseek_flash_B_nothink_El08gq](../../validation_runs/l3_formal90_deepseek_flash_B_nothink_El08gq/) | [20261122_0x7es521 汇总](../../validation_runs/l3_formal90_deepseek_flash_B_nothink_El08gq/replay_analysis_20261122_0x7es521/rebatch_fos/summary_v2_rebatch_fos.csv) |
| DeepSeek Flash BP | [l3_formal90_deepseek_flash_BP_nothink_OL0lel](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_OL0lel/) | [20261121_34tfrwwj 汇总](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_OL0lel/replay_analysis_20261121_34tfrwwj/rebatch_fos/summary_v2_rebatch_fos.csv) |
| DeepSeek Flash BP rerun | [l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM/) | [20261121_qmown_yo 汇总](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM/replay_analysis_20261121_qmown_yo/rebatch_fos/summary_v2_rebatch_fos.csv) |
| Thor Qwen B | [l3_formal90_thor_qwen35b_B_nothink_vrNWR4](../../validation_runs/l3_formal90_thor_qwen35b_B_nothink_vrNWR4/) | 本轮核查已有运行，尚未发现配套评分汇总，登记后待补 |
| Thor Qwen BP | [l3_formal90_thor_qwen35b_BP_nothink_lvxtsU](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_lvxtsU/) | [20261123_ccsvhd_7 汇总](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_lvxtsU/replay_analysis_20261123_ccsvhd_7/rebatch_fos/summary_v2_rebatch_fos.csv) |
| Thor Qwen BP rerun | [l3_formal90_thor_qwen35b_BP_nothink_rerun_BvciC0](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_rerun_BvciC0/) | [20261123_rxp1itc_ 汇总](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_rerun_BvciC0/replay_analysis_20261123_rxp1itc_/rebatch_fos/summary_v2_rebatch_fos.csv) |
| Oracle | [oracle_140_verification_20261116](../../validation_runs/oracle_140_verification_20261116/) | 同场景执行工作流及 baselines 中的回收量 |

**Oracle 按场景统一绑定。** 对比上述 Oracle 包与历史评分使用的 `oracle_time_control_20261116/advance_time_v2`，70 个场景的回收量、声明流程，以及实际执行中的有序工具参数、时间和农事结果全部一致，执行记录仅有随机巡查／任务 ID 差异。两个 manifest 的 430 个来源代码哈希相同，相关场景、引擎和工具代码与当前工作区核对一致。已选定的 210 条 Agent 评分，其 Oracle 回收量也全部与指定 Oracle 包一致。因此首版在固定场景版本下，每个场景材料包绑定一套 Oracle 与配套 Yield，历史文件路径保留在来源记录中。[指定 Oracle manifest](../../validation_runs/oracle_140_verification_20261116/manifest.json) · [历史参考 manifest](../../validation_runs/oracle_time_control_20261116/advance_time_v2/manifest.json) · [Oracle 构建入口](../../fairy/scenarios/workflow_validation.py)

| 材料包部分 | 原始文件与整理内容 |
|---|---|
| 基础任务 `base_tasks` | 从对应版本按 `detailed_briefing=false` 提取纯 B，保存正文和哈希。各次运行引用实际 B，正文一致时共用 |
| Agent 运行 `agent_runs` | 根目录 `results.csv`，cell 内 `*.agent_workflow.json`、`*.run_report.json`，按需查 `*.runtime_log.jsonl`。保存完整顺序、调用、返回、错误、运行条件及评分 |
| 场景 Oracle `oracle` | `execution_workflows/<id>.json` 与 `baselines/<id>.json`；声明 `workflows/<id>.json` 和 `terminal_states/<id>.json` 用于核对 |
| 来源清单 | 来源身份、文件／评分行定位、哈希、版本、缺失项。原始内容保存不可变副本或引用可恢复的归档 |

原始材料完整归集，生成时可分页读取。BP 开场指令中包含的 P/G 与系统指令从生成视图剔除，纯 B 单独传入，原始运行条件保留。本轮核查时，原五个来源已有 210 次配对评分，每个场景有 3 次评分齐备的运行。新增 Thor B 已有 26 次非 mini 的 rc=0 运行，工作流及报告可读取，暂缺评分汇总。当前共 236 次原始运行，按场景实际可用数量装包，缺口单独报告。正式导入时重新扫描并冻结清单。[运行产物定义](../../fairy/controllers/run_artifacts.py)

### 2. 分数及解释

**前三类知识当前仅考虑 recovered_yield_loss，后续可扩展更多指标。** 每次 Agent 运行的 `scores` 当前保存下列一项指标及解释，来源身份和评分文件位置由运行记录提供。解释由程序按固定口径生成，数据缺口或回放问题据报告补充。

| scores 中的键 | 子字段 | 解释与校验 |
|---|---|---|
| `recovered_yield_loss_pct` | `value` 数值或 null，`explanation` 字符串 | `100 × (1 − Agent 回收量 / Oracle 回收量)`，越低越好。**负数表示 Agent 回收量高于 Oracle，是该指标上的好结果**，例如 −5% 表示高出 5%。允许负数，禁止截为 0；分母缺失或不大于零时无定义 |

存储沿用百分数口径。CSV 的 `recovered_yield_loss(%)` 直接映射为 `recovered_yield_loss_pct`，评分 JSON 中的 `recovered_yield_loss` 比例值乘以 100 后映射。两个回收 kg 保留在原始评分文件，整理时可复核公式。现有 JSON 和 CSV 均经过舍入，校验采用与保存精度一致的容差。Oracle 的配套 `recovered_yield_kg_total` 按 kg 保存在场景包内。整季评分通过来源关联到知识，局部成因和操作效果引用相应步骤。[指标公式](../../fairy/scenarios/fos/evaluation.py) · [报告精度](../../fairy/scenarios/fos/metrics.py)

`scores` 保留按指标名称扩展的对象结构。单次提炼和场景内整理均按本版启用的指标提供输入及检查可用性，当前启用 `recovered_yield_loss_pct`。后续新增指标时明确名称、口径、单位、解释和校验规则，并记录相应规范及 prompt 版本。

### 3. 源字段与知识字段的对应

| 原始内容 | 对应知识字段 | 使用方法 |
|---|---|---|
| B 中的作物、品种、明示条件、风险和任务 | crop、cultivars、适用条件、任务主题 | 明示内容直接提取，风险涉及的具体田区由观测核实 |
| 工作流 `name/time/depends_on`，可选时间扩展字段 | 检查、操作及流程顺序 | 保留原步骤和时间关联，允许跨步骤回查 |
| `tool_name/tool_args` | task_types、操作模板、流程动作 | 结合任务目的归类，参数说明请求内容 |
| `content.ridges[]` 中的品种、物候、已播状态 | cultivars、growth_stages_before、适用条件 | 使用目标田块操作前的实际观测 |
| 苗情、营养、水分、天气、病虫、库存与设备返回 | 适用条件、pre_checks、constraints | 保留单位、时点和覆盖范围，归纳为可判断条件 |
| `status/error`、实际覆盖、完成垄、后续复查 | post_checks、Reflection、Guidance、Observation 结果 | 结合行为与返回解释结果，部分完成和错误照实记录 |
| Agent 的 recovered_yield_loss 及解释 | 前三类知识的整季结果背景 | 支持比较历史运行，具体经验方向由正文与步骤证据判定 |
| Oracle 实际执行及配套回收量 | applicable_constraints、procedure | 描述发生的过程，局部收获量和全季回收量注明各自范围 |

第一阶段中，Skill 将单次运行事实整理为方法，Reflection 解释该次历史成因，Guidance 转为未来决策，Observation 记录 Oracle 过程。第二阶段在同场景同类型候选之间比较和凝练，分数仍保留各运行的原有含义。

## 三、两阶段 prompt、写入及更新设计

### 1. 两组、八个逻辑 prompt

共两组功能，每组四个类型 prompt，使用共享规则和类型规范装配。第一组负责单次提炼，第二组负责场景内整理。首次建库和后续更新共用这两组，第二阶段通过已有正式知识是否为空适配调用。

| 类型 | 第一组，单次运行提炼 | 第二组，场景内整理 |
|---|---|---|
| Skill | `skill_extract`，从一次 Agent 运行提取条件、检查、约束、操作和验收 | `skill_consolidate`，比较方法及适用条件，合并等价内容，保留必要差异 |
| Reflection | `reflection_extract`，解释该次运行中有证据的经验或错误 | `reflection_consolidate`，核对多次运行的成因解释，补充条件、收窄或修订推断 |
| Guidance | `guidance_extract`，提出该次历史经验支持的未来行为 | `guidance_consolidate`，比较建议方向与触发条件，处理重复和反例 |
| Observation | `observation_extract`，按一次 Oracle 记录提炼实际过程 | `observation_consolidate`，核对同一过程的描述、范围和结果，整理重复与补录 |

**第一组输入**为共享来源规则、对应类型 schema／词表、纯 B，以及一次源记录。前三类每次读取一份 Agent 工作流和该运行的 recovered_yield_loss 及解释，Observation 读取一份 Oracle 执行记录和配套回收量。第一阶段可回查该源记录的完整时间线，生成视图限定在本次来源内。当前启用的指标或关键证据缺失时报告待补，其他完备运行可独立处理。

**第二组输入**为同一场景、同一类型的显式 selected_candidate_ids、候选内容及原证据、对应 B 和场景约束、已有正式条目及其修订。完整候选集可以分页读取，整理报告记录处理范围。允许回查这些候选关联的原始材料。单份 Oracle 也经过这一步，核对重复描述、事件身份和流程完整性。

同一源运行、同一类型可能因 prompt 修订而多次提炼。来源清单指定采用哪次提炼结果，重复提炼保留历史，不按多次独立运行计证。整理时可引用已有正式条目关联的历史候选，并明确保留或替换的证据。

### 2. 场景内合并、凝练和删减规则

- 同场景、同类型中，主张及适用条件一致时合并，保留有效候选与原始证据。方法或条件差异会影响决策时分别成条。
- 跨运行比较保留各自的观测、动作、结果和分数，因果解释中的前后证据须来自同一运行或明确说明比较条件。不同运行的步骤不能拼接成一次实际发生的过程。
- 多次运行支持相近结论时，核对共同条件后再凝练。标签数组的并集不自动成为更广泛的适用范围，未知信息不能推导为 any。
- 解释或建议冲突时回查事实，可补充条件、收窄范围或登记待处理。候选数量、模型数量及整季分数不能代替具体证据判断。
- 精简重复表述时保留触发条件、操作限制和结果边界。未采纳的候选在报告中写明重复、证据不足等原因，原始候选仍可读取。
- 新内容接受了额外来源证据时，即使正文相同，也通过正式修订固定新 candidate_ids 和 evidence。
- Observation 的独立事件分别保留，同一事件补录或纠错沿用 episode_ref。Skill、Reflection、Guidance 和 Observation 各按自身用途整理。

候选未被采纳只表示本次整理的选择。撤回已有正式知识需要明确的目标 ID、理由和证据。跨场景材料保持各自来源身份，首版整理范围为场景内部。

### 3. 两阶段结构化输出

**第一阶段输出**为 `candidates` 和 `issues`。每个候选包含类型、五个农学标签、完整 payload 和 evidence。程序从可信 context 填入候选 ID、场景、唯一 source_ref、提炼请求及 Observation 过程身份。下面是格式模板。

```json
{
  "candidates": [
    {
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
        "applicable_when": "<该次运行支持的条件>",
        "content": "<检查结果满足何种条件才行动>"
      },
      "evidence": [
        {
          "source_ref": "<本次唯一源记录>",
          "locators": ["workflow#/<步骤 ID>/content"],
          "fields": ["/payload/content"]
        }
      ]
    }
  ],
  "issues": []
}
```

实际输出须补全所有非空标签和正文的证据，示例仅展示一项。locators 和 fields 均为非空字符串数组，分别定位原材料内容和被支持的知识字段。issues 每项说明 field、code 和 reason。tags 展平为知识表的标签列，payload 与 evidence 按 JSON 保存。第一阶段的候选输出由 `write_candidates` 校验并保存，再进入用户的候选审阅。

**第二阶段输出**为 `changes` 和 `notes`。changes 每项包含 operation、knowledge_type、reason，以及下表中的类型专属内容。

| 操作／报告结果 | 必需内容 | 效果 |
|---|---|---|
| `add` | 完整 tags、payload、candidate_ids、evidence、Observation 的 episode_ref | 分配正式 knowledge_id，revision=1 |
| `revise` | 旧 knowledge_id、expected_revision，以及完整的新 tags、payload、candidate_ids、evidence、episode_ref | 追加正式修订，历史版本保留 |
| `retire` | 旧 ID、expected_revision、撤回依据的 candidate_ids 与 evidence | 从新版本有效成员中撤回 |
| `no_change` | notes 中记录旧 ID、相关 candidate_ids 和原因 | 正式内容与证据沿用原修订 |
| `not_selected` | notes 中记录未采用的 candidate_ids 和原因，可指向等价正式条目 | 保留候选及本次选择理由 |
| `pending` | notes 中记录候选或旧 ID、冲突／缺口和原因 | 留待补充材料或复核 |

notes 项使用 status、candidate_ids、knowledge_id（无关联时为 null）、reason。全部输入候选须在 changes 或 notes 中有处理说明，一个候选可以支撑多条正式知识。candidate_ids 限于 context 冻结的 selected_candidate_ids 及本次提供的旧正式修订关联候选，类型和场景须一致。正式字段证据必须来自关联候选的源记录，Observation 的候选还须指向同一 episode_ref。已有正式条目未被列入变更时沿用原修订。

revise 的 candidate_ids 是新修订的完整关联集合。替代关系使用可选 replaced_by 数组，每项为 `{"knowledge_id": "已有ID"}` 或 `{"change_index": 0}`，后者指向本批 changes 中的 add。替代目标须在新版本有效，替代与撤回成组校验和提交。以上操作的判定规则在小样本中由用户审阅确认。

retire 的 evidence.fields 指向 `/reason`，理由及证据保存在整理请求和操作记录中，撤回通过新发布成员关系生效。

### 4. SQLite 与固定读写函数

两张业务表分别承担候选积累和正式知识使用。结构校验通过的候选先入第一表，经过用户审阅和场景内整理后，再将审阅通过的变更写入第二表。SQLite 保存正式状态，JSON 用于两阶段交换、审阅和导出。

| 表 | 职责 |
|---|---|
| `sources` | 场景材料及单次源记录、归档定位、哈希、分数与解释 |
| `knowledge_candidates` | 第一次提炼的不可变候选，字段见第一节 |
| `knowledge_revisions` | 第二次整理的正式修订，含确切 candidate_ids 和原始证据 |
| `releases`、`release_items` | 发布版本、父版本及有效知识的确切修订 |
| `change_batches` | request_id、阶段 extract／consolidate、输入清单、规范／prompt／模型配置、原始输出、用户审阅结论及写入结果 |

candidate_ids 用 JSON 数组保存，固定写入函数核验所有引用、同场景同类型约束和证据来源。标量标签存普通列，数组、payload、evidence 存 JSON。所有业务读写经过参数化 SQL 函数，后续可将同一函数封装为 Agent 工具。

| 固定函数接口草案 | 职责 |
|---|---|
| `init_db()` | 创建两张业务表及来源、请求、发布辅助表 |
| `write_candidates(request_id, context, output)` | 校验单次来源及类型，保存候选、issues 和生成上下文，返回 candidate_ids |
| `get_candidates(scenario_id, knowledge_type, candidate_ids)` | 读取冻结的候选集合及原证据，供审阅和场景整理 |
| `validate_changes(context, proposal)` | 检查正式字段、候选引用及允许集合、处理覆盖、证据和目标修订，返回错误位置与原因 |
| `apply_changes(request_id, base_release_id, context, proposal)` | 核验已登记的正式审阅结论，原子提交修订、notes 和新快照 |
| `get_knowledge(release_id, knowledge_id)`、`query_knowledge(release_id, filters, pagination)` | 读取正式发布，按类型、场景、标签及私有方向字段筛选，确定性排序并返回 JSON |
| `get_history(knowledge_id)`、`export_release(release_id)` | 回查正式修订到候选及源步骤，导出指定版本 |

同一 request_id 绑定同一阶段、输入及输出，重试复用已写入的候选 ID 或发布结果。新材料、prompt 调整或主动重提炼使用新请求，保留旧候选。正式写入在短事务中校验基础版本、expected_revision 和依赖，一起提交知识修订、操作记录与发布成员。并发冲突返回明确错误，回到最新版本重新比较。

### 5. 新数据与持续更新

新运行先进入相应场景包，第一组 prompt 为该次输入产生新候选。候选审阅后，第二组读取本轮选定的新旧候选和当前正式知识，提出增删改及未采纳理由。源数据更正或评分补齐也走此流程，原候选与旧发布可回查。

同场景的独立运行分别保存分数，正式知识根据 candidate_ids 取得其来源结果。查询历史发布时使用当时绑定的材料，重新评分通过新候选和正式修订接入。知识内容与来源补充分别在整理报告中说明。

查询层先约定跨字段 AND、数组字段显式 ANY／ALL，有条件筛选时未知值默认不匹配，可由参数纳入。面向待运行任务的 query 只使用纯 B。B 到匹配条件的转换及正式结果到 G 的载入留作后续接入，实际任务使用第二张表的已发布内容。

## 四、审阅边界与设计验收

前期由用户审阅并决定各环节产物。材料包审阅检查来源及评分配对，字段／词表审阅检查含义和覆盖。第一张表审阅检查单次提炼是否准确、充分、有证据，第二阶段审阅检查凝练后是否保留必要条件、如何处理冲突及删减，正式写入以通过审阅的变更为依据。审阅结论和修正要求随请求保存，自动化校准后再逐步交给 Agent。

正式审阅结论绑定 request_id、基础发布、选中候选集合及 proposal 内容哈希，提交时核对一致。审阅后修改内容须重新登记对该产物的审阅结论。

设计验收包括单运行输入隔离、四类字段合法、同场景多运行整理、同源重复提炼去重计证、正式字段追到候选与原步骤、候选未采纳不误撤回正式知识，以及重复提交、修订、撤回和历史导出正确。冲突或证据不足可保留待处理，其他完备材料独立推进。

首次分批仍按 formal90 顺序排除 mini20，冻结 20／20／20／10 个新场景，累计覆盖 20／40／60／70。每批分别记录候选产出与正式新增、修订、撤回及待处理项。小样本包含在首批范围中。mini20 验证绑定正式发布版本，待纯 B 查询和 G 载入接口可用后检验 Agent 效果。

必要错误包括 `SOURCE_OUT_OF_SCOPE`、`RUN_ID_MISMATCH`、`METRIC_MISSING`、`UNCLASSIFIED_TASK`、`INVALID_PAYLOAD`、`CANDIDATE_SCOPE_MISMATCH`、`UNSUPPORTED_CLAIM`、`STALE_REVISION`、`RELEASE_CONFLICT`。报告定位到具体来源、候选或正式知识字段。

待校准项为 13 类 task_types 的逐片段覆盖、同场景候选的合并／删减和正式撤回边界、纯 B 的匹配及 G 载入。用户审阅通过后固化为 schema、词表和 prompt 版本。

## Original Library Modes

默认 G、`reusable_operational_guidelines` 和旧 library 各自独立管理。四类新知识按本文来源和生成流程建设。旧模式的数据源、参数及 map 兼容说明见[现有 library 替换 G 的说明](../README.md)。
