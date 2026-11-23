# FAIRY 知识库设计方案

**目标**是基于场景基础任务 B、Agent／Oracle 工作流及结果，自动构建四类农事知识。SQLite 保存知识，结构化 JSON 用于生成、审阅和交换，后续支持增删改查及版本回查。

**数据流**为“按场景整理材料 → 阅读单次 L3 全季记录并识别 L2 单元 → 第一张初始知识表 → 各知识类型按全部公共字段相同分组 → 校准与整合 → 第二张正式知识表”。一个场景有多次 Agent 运行和一套 Oracle 记录。前期各环节产物由用户审阅、主导和判断，prompt 与处理规则校准后再逐步托管给 Agent。本文集中定义知识、来源和构建边界，具体 prompt 与读写实现见第三部分 TODO。

## 一、FAIRY 知识库设计

### 1. 四类知识及其来源

| 类型 | 构建材料 | 一条 L2 级知识表达的内容 |
|---|---|---|
| Agronomic Skill | B＋单次 Agent 工作流＋该次 recovered_yield_loss | 围绕一个农事目标的可复用方法，含条件、检查、约束、步骤与结果确认 |
| Agronomic Reflection | B＋单次 Agent 工作流＋该次 recovered_yield_loss | 对一个局部经验或错误的成因解释 |
| Agronomic Guidance | B＋单次 Agent 工作流＋该次 recovered_yield_loss | 针对一个局部决策问题的未来行为建议 |
| Agronomic Observation | B＋一次 Oracle 执行记录＋配套回放 Yield | 一个可识别的实际农事过程 |

当前 Oracle 来源标为 `simulated_oracle_replay`。未来真实农场回流标为 `real_farm_record`，使用同一 Observation 内容结构，保留实际作业和收获证据。每次 Agent 运行分别支持前三类提炼，Oracle 记录支持 Observation。每类可以产出零条、一条或多条初始知识，所有条目保留各自来源。

### 2. 公共字段与追溯信息

| 公共字段 | 格式与含义 | 填写依据 |
|---|---|---|
| `knowledge_version` | 知识版本字符串，如 `structured_knowledge_v01` | 本轮构建统一指定目标版本，两张表使用相同标识 |
| `source_scenario_id` | 来源场景 ID，每条归属一个场景 | 来源材料包 |
| `crop` | 当前枚举为 `soybean` | 本条知识涉及的任务和目标作物 |
| `cultivars` | 品种／通用种子类型代码数组，未知为 null | 本条知识涉及的 B 描述及目标田块实际播种或状态 |
| `growth_stage_before` | 单个物候状态字符串，无法确认时为 null 并报告缺口 | 本条知识核心决策或操作开始前，目标田块的物候证据 |
| `farming_group` | 单个农事阶段，`establishment / management / harvest` | 本条知识的核心农事目标 |

**先识别 L2 单元，再逐条判断物候和农事阶段。** 每条知识的物候状态和农事阶段均为单值。全季输入的初始物候或总体任务名称不能统一赋给全部输出。

品种／种子类型使用 `EARLY_COLD、STANDARD、HIGH_DENSITY、STRESS_TOLERANT、HEIHE43、HEIHE50、HEINONG58、HEINONG60、HEINONG84、HEIKE71`。前四项属于通用种子类型。库存反映可用资源，品种标签依据实际任务和田块取值。`cultivars` 的 null 表示未知，`["any"]` 表示有依据认为品种不构成限制；具体代码数组非空、去重并按词表顺序规范化，禁止 any 与具体代码混填。[种子定义](../../fairy/apps/farm_world/models.py)

物候使用 `FAIRY-Engine-` 前缀及 14 个状态 `NOT_PLANTED、PLANTED_PRE_EMERGENCE、VE、VC、V1、V2、V3、V4_PLUS、R1、R3、R5、R6、R7、R8`，每条只选其中一个。保存原始观测，显式映射引擎值，如 `R1_BEGINNING_BLOOM → FAIRY-Engine-R1`。旧显示值合并了多个状态时，结合对应版本和同一田块的证据判断，无法唯一确定则留 null。日期、农事阶段或事后物候不能直接替代操作前的物候证据。[物候定义](../../fairy/physics/phenology_engine.py) · [兼容映射](../../fairy/apps/farm_world/physics_orchestrator.py)

两张表共用上述公共字段及四类 payload 定义。`knowledge_type` 单独标识为 `skill / reflection / guidance / observation`，四类知识分别处理。条目 ID、来源运行、步骤定位和生成请求属于追溯信息，具体边界见第 5 节。

### 3. L3 输入与 L2 知识单元

输入是一次完整的 L3 全季工作流，输出按 **L2 级农事目标或局部问题**组织。一个单元围绕一个可独立理解的目标展开，保留相关条件、观察与判断、操作或暂缓决定，以及结果证据。常规充电、补给、等待和装卸农具等辅助步骤随所属目标保留。农事目标在正文中表达。[现有 L2 划分原则](../../fairy/scenarios/farm_world_fullseason_v2/l2_l1_splits/l3-to-l2-l1-split-guide.zh.md)

先用 establishment、management、harvest 梳理整季过程，再在各阶段内识别独立单元。每个阶段可以包含多个单元，management 可包含不同时间、不同目标的多次管理。输出数量由材料支持的单元决定，各阶段不限定条数。同一单元可以支持不同类型的知识，各类按自身用途分别提炼。

- **独立目标分别成条。** 同一次巡查发现水分和营养问题，形成两个独立处置过程时，可分别形成知识。
- **同一过程的后续复查保留在原条目中。** 即使复查时物候已经变化，公共字段仍取核心决策或操作开始前的状态。
- **新的物候下发生独立决策时重新成条。** 例如，前期灌溉和后期重新判断是否灌溉，可以是两个单元。
- **目标田块的操作前物候不同，分别成条。** 每条使用对应田块的单个物候值。
- **跨农事阶段的独立目标分别成条。** 前后依赖保留在正文和证据中。
- **失败、遗漏和缺少复查照实保留。** 根据已有证据形成相应知识，说明限制，不补写未发生的过程或结果。

单元划分确定条目边界，生成时仍可回查本次来源的完整时间线。所需证据可以分布在多个步骤，相关单元也可引用共同的观测。

### 4. 四类私有字段

| 类型 | payload 格式 | 写作要求 |
|---|---|---|
| Skill | `applicable_when` 字符串，`pre_checks`、`constraints`、`operation_template`、`post_checks` 为字符串数组 | 写清触发条件、检查目的与依赖、参数如何取得、操作和验收。每个数组元素尽量表达一个检查或动作 |
| Reflection | `success` 布尔值，`applicable_when`、`content` 字符串 | true 表示肯定经验，false 表示指出错误。正文写历史行为、可见结果、原因推断和不确定处 |
| Guidance | `recommendation` 为 `recommend / avoid / conditional`，`applicable_when`、`content` 字符串 | 写清未来行为和触发条件；conditional 给出补充检查如何决定行动或暂缓 |
| Observation | `applicable_constraints` 字符串数组，`procedure` 为有序对象数组，每步含 `action` 字符串及 `observed_result` 字符串或 null | 按实际过程记录参数、覆盖范围、结果、失败或 partial，数值带单位 |

Reflection 的 success 描述经验方向，成功完成的运行也可产生指出局部错误的条目。四类正文可围绕同一主题分别表达方法、成因、建议和事实，按各自用途检查重复。

必要正文非空，检查、模板和流程为非空数组。约束暂缺可用空数组并报告缺口，未记录的结果为 null。无法形成有依据的知识时跳过。Observation 通过来源运行和步骤范围定位过程，使用 `episode_ref` 保留过程身份；同一过程补录沿用身份，独立事件分别记录。

### 5. 两张知识表的字段边界

**第一张表 `knowledge_candidates` 保存基于单次来源构建的初始知识。** 每行对应本次来源的一条 L2 级知识，第一阶段只依据本次输入新增条目。不同运行的内容允许相似、互补或冲突，均保留各自来源和证据。源材料或生成结果更正后保留旧记录，追加新的提炼结果。

| 字段 | 类型与约束 | 来源及边界 |
|---|---|---|
| `candidate_id` | 字符串主键 | 标识一条初始知识 |
| `knowledge_version` | 非空字符串 | 本轮目标知识版本 |
| `source_scenario_id` | 非空字符串 | 从可信材料包填写 |
| `source_ref` | 非空来源引用 | 唯一关联一次 Agent 运行或一次 Oracle 记录的材料，含对应 B 和结果 |
| `knowledge_type` | 四类枚举 | 本次构建的知识类型 |
| `crop` | 字符串 | 本条知识涉及的作物 |
| `cultivars` | JSON 数组或 null | 本条知识有证据支持的品种范围 |
| `growth_stage_before` | 单个状态字符串或 null | 本条知识核心决策或操作开始前的物候 |
| `farming_group` | 单个三值枚举 | 本条知识核心目标所属的农事阶段 |
| `payload` | JSON 对象 | 按知识类型使用第 4 节的完整字段 |
| `evidence` | 非空 JSON 数组 | 每项为 source_ref、原文定位 locators、对应知识字段 fields，均来自本次源记录 |
| `episode_ref` | 字符串或 null | Observation 对应的实际过程身份；其他类型为 null |
| `extraction_request_id` | 非空字符串 | 关联本次输入、生成配置、输出和审阅记录 |

**第二张表 `knowledge_revisions` 保存校准与整合后的正式知识。** 四类知识分别处理，同一类型内按全部公共字段完全一致分组，即 `knowledge_version`、`source_scenario_id`、`crop`、`cultivars`、`growth_stage_before`、`farming_group` 全部相等。每组可以形成零条、一条或多条正式知识，每行是一条正式知识的一个修订。

品种数组规范化后比较，null 仅与 null 相同，`["any"]` 仅与自身相同。来源运行、条目 ID、请求和证据不参与分组。公共字段相同只确定整理范围，未知值相同也不表示已确认适用范围；组内仍需比较具体目标、私有适用条件和正文。

| 字段 | 类型与约束 | 来源及边界 |
|---|---|---|
| `knowledge_id`、`revision` | 字符串＋正整数 | 正式知识身份及其修订号 |
| `knowledge_version` | 非空字符串 | 继承所在分组的目标知识版本 |
| `source_scenario_id` | 非空字符串 | 继承所在分组的场景 |
| `knowledge_type` | 四类枚举 | 与关联初始条目的类型一致 |
| `crop` | 字符串 | 继承所在分组的作物 |
| `cultivars` | JSON 数组或 null | 继承所在分组的品种值 |
| `growth_stage_before` | 单个状态字符串或 null | 继承所在分组的操作前物候值 |
| `farming_group` | 单个三值枚举 | 继承所在分组的农事阶段 |
| `payload` | JSON 对象 | 校准、合并或凝练后的完整内容，遵循相同类型规范 |
| `candidate_ids` | 非空、去重的 JSON 数组 | 支持该条正式知识的完整初始条目 ID 集合，均属于本组 |
| `evidence` | 非空 JSON 数组 | 正式字段到原始材料的证据，来源限于所关联初始条目的源记录 |
| `episode_ref` | 字符串或 null | Observation 保留对应过程身份，独立事件分别成条；其他类型为 null |
| `consolidation_request_id` | 非空字符串 | 关联本次分组输入、处理理由、输出和审阅记录 |

校准与整合遵循以下内容规则：

- 主张重叠且条件兼容时合并，保留支持内容的来源；影响决策的目标、方法或条件差异分别保留。
- 互补内容可以补充检查、限制或解释，但每项补充须有依据。不同运行的步骤保留各自归属，不能拼接为一次实际发生的过程。
- 冲突有充分证据可解决时，修正或删减相应内容；无法解决时，在整理报告中标记关联条目、争议及原因，留待审阅，不作为已确认结论使用。
- 未采纳的内容记录理由，第一张表保留原条目。发现公共字段误判时登记待更正，正式条目仍遵循分组字段一致的要求。
- 候选数量、模型数量及整季分数不能替代具体证据判断。来源分数及解释通过关联取得，合并知识不产生代表局部效果的“合并分数”。

一个初始条目可以支持多条正式知识，多条初始知识也可以支持同一正式条目。知识版本表示本轮构建版本，revision 表示单条正式知识的修订。跨版本沿用、发布及已有正式知识的撤回方式留到第三部分设计。

## 二、FAIRY 知识库数据来源

### 1. 来源集合与场景材料包

首轮使用[正式 90 场景](../../scripts/fullseason/formal_90_scenario_ids.txt)排除 [L3-mini 20](../../scripts/fullseason/l3_mini_20_scenario_ids.txt)后的 70 个场景。六个 Agent 来源中，纳入这些场景的 `return_code=0` 运行，同场景不同模型、B/BP 和重跑分别保留。每次生成冻结具体文件及评分行，按“来源根＋cell 路径”配对工作流、报告和分数。

| 来源 | 允许目录 | 评分材料 |
|---|---|---|
| DeepSeek Flash B | [l3_formal90_deepseek_flash_B_nothink_El08gq](../../validation_runs/l3_formal90_deepseek_flash_B_nothink_El08gq/) | [20261122_0x7es521 汇总](../../validation_runs/l3_formal90_deepseek_flash_B_nothink_El08gq/replay_analysis_20261122_0x7es521/rebatch_fos/summary_v2_rebatch_fos.csv) |
| DeepSeek Flash BP | [l3_formal90_deepseek_flash_BP_nothink_OL0lel](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_OL0lel/) | [20261121_34tfrwwj 汇总](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_OL0lel/replay_analysis_20261121_34tfrwwj/rebatch_fos/summary_v2_rebatch_fos.csv) |
| DeepSeek Flash BP rerun | [l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM/) | [20261121_qmown_yo 汇总](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM/replay_analysis_20261121_qmown_yo/rebatch_fos/summary_v2_rebatch_fos.csv) |
| Thor Qwen B | [l3_formal90_thor_qwen35b_B_nothink_vrNWR4](../../validation_runs/l3_formal90_thor_qwen35b_B_nothink_vrNWR4/) | 2026-11-23 盘点时已有运行，配套评分汇总待补 |
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

原始材料完整归集，生成时可分页读取。BP 开场指令中包含的 P/G 与系统指令从生成视图剔除，纯 B 单独传入，原始运行条件保留。2026-11-23 材料盘点时，原五个来源已有 210 次配对评分，每个场景有 3 次评分齐备的运行。新增 Thor B 已有 26 次非 mini 的 rc=0 运行，工作流及报告可读取，暂缺评分汇总。该次盘点共 236 次原始运行，按场景实际可用数量装包，缺口单独报告。正式导入时重新扫描并冻结清单。[运行产物定义](../../fairy/controllers/run_artifacts.py)

### 2. 分数及解释

**前三类知识当前仅考虑 recovered_yield_loss，后续可扩展更多指标。** 每次 Agent 运行的 `scores` 当前保存下列一项指标及解释，来源身份和评分文件位置由运行记录提供。解释由程序按固定口径生成，数据缺口或回放问题据报告补充。

| scores 中的键 | 子字段 | 解释与校验 |
|---|---|---|
| `recovered_yield_loss_pct` | `value` 数值或 null，`explanation` 字符串 | `100 × (1 − Agent 回收量 / Oracle 回收量)`，越低越好。**负数表示 Agent 回收量高于 Oracle，是该指标上的好结果**，例如 −5% 表示高出 5%。允许负数，禁止截为 0；分母缺失或不大于零时无定义 |

存储沿用百分数口径。CSV 的 `recovered_yield_loss(%)` 直接映射为 `recovered_yield_loss_pct`，评分 JSON 中的 `recovered_yield_loss` 比例值乘以 100 后映射。两个回收 kg 保留在原始评分文件，整理时可复核公式。现有 JSON 和 CSV 均经过舍入，校验采用与保存精度一致的容差。Oracle 的配套 `recovered_yield_kg_total` 按 kg 保存在场景包内。整季评分通过来源关联到知识，局部成因和操作效果引用相应步骤。[指标公式](../../fairy/scenarios/fos/evaluation.py) · [报告精度](../../fairy/scenarios/fos/metrics.py)

`scores` 保留按指标名称扩展的对象结构。单次提炼和分组整理均按本版启用的指标提供输入及检查可用性，当前启用 `recovered_yield_loss_pct`。后续新增指标时明确名称、口径、单位、解释和校验规则，并记录相应规范及 prompt 版本。

### 3. 数据如何支持第一张表的字段

**本节仅用于构建第一张表。** 可直接提取或规范化转换的内容制定映射规则，需要归纳、解释或推断的内容制定判断和写作指引。四类知识分别定义输入与输出要求。

#### 3.1 先识别单元，再逐条填写公共字段

Agent 先阅读完整 L3 材料，理解全季任务、执行顺序和结果；按三个农事阶段梳理局部目标，再依第一部分第 3 节的边界识别 L2 单元。阶段中的每个单元分别生成知识，并判断自己的物候和农事阶段。划分后仍可回查本次来源的完整材料。

| 公共字段 | 原始内容与填写方法 |
|---|---|
| `knowledge_version`、`source_scenario_id` | 分别由本轮构建设置和来源材料包提供 |
| `crop`、`cultivars` | 依据 B 及该单元目标田块的实际作物、品种和已播状态；库存中的品种仅表示可用资源 |
| `growth_stage_before` | 定位核心决策或操作，读取此前目标田块的物候证据，如 `content.ridges[]` 中的状态，并按引擎映射填写单个状态 |
| `farming_group` | 根据该单元要完成的主要农事目标，选择 establishment、management 或 harvest |

工作流的 `name/time/depends_on` 及时间扩展字段用于保留顺序与依赖，`tool_name/tool_args` 和返回内容用于理解动作、目标范围与结果。工具名称辅助识别农事目标，物候和农事阶段在单元确定后分别判断。

例如，假设材料支持以下过程，一次 Skill 构建可以产生多条知识。以下仅为尺度示例，实际条目和状态以材料为准。

| Skill 围绕的内容 | farming_group | growth_stage_before |
|---|---|---|
| 播种准备与执行 | establishment | FAIRY-Engine-NOT_PLANTED |
| 苗期水分判断与灌溉 | management | FAIRY-Engine-V2 |
| 苗期营养问题处置 | management | FAIRY-Engine-V2 |
| 后期虫情判断与处理 | management | FAIRY-Engine-R3 |
| 成熟度确认与收获 | harvest | FAIRY-Engine-R8 |

输出数量取决于材料支持的 L2 单元数量，每个农事阶段可以对应多条同类型知识。示例中的 V2 灌溉和 V2 营养处置，在其余公共字段一致时会进入第二阶段同一组；二者解决不同问题，可以分别保留。

#### 3.2 Agronomic Skill

**输入：B＋单次 Agent 工作流＋该次 recovered_yield_loss 及解释。** 公共字段按对应 L2 单元填写，私有内容形成可复用的方法。

| 输出字段 | 构建依据与内容指引 |
|---|---|
| `applicable_when` | 从 B 的任务限制、操作前观测及资源状态中归纳触发条件和适用范围 |
| `pre_checks` | 结合实际检查及检查不足暴露的问题，提炼必要检查、目的与依赖顺序 |
| `constraints` | 从明示规则、工具限制、资源条件及失败返回中提炼操作限制，数值和阈值须有依据 |
| `operation_template` | 将相关工具调用、参数、返回及调整整理为围绕一个目标的方法，说明参数如何确定、何时执行或暂缓 |
| `post_checks` | 根据完成状态、实际覆盖和后续观测，说明怎样确认结果，并保留未完成验证的证据限制 |

例如，该次材料确有“库存不足失败 → 补给 → 重试成功”时，可以提炼作业前核对资源需求和库存、必要时补给、执行后检查结果的方法。

#### 3.3 Agronomic Reflection

**输入：B＋单次 Agent 工作流＋该次 recovered_yield_loss 及解释。** 公共字段定位被分析的局部决策或操作，私有内容解释历史经验或错误。

| 输出字段 | 构建依据与内容指引 |
|---|---|
| `success` | 根据本条内容是在肯定经验还是指出错误确定，分别为 true 或 false |
| `applicable_when` | 根据相关任务、操作前状态及限制，说明该解释成立的条件和范围 |
| `content` | 联系行为前观测、具体动作、返回及后续变化，区分已观察事实和原因推断，说明证据与不确定处 |

例如，有相应步骤证据时，可以解释“该次作业因库存不足失败，补给后重试成功，支持将资源检查不足视为此次失败的一项原因”，该条 success 为 false。

#### 3.4 Agronomic Guidance

**输入：B＋单次 Agent 工作流＋该次 recovered_yield_loss 及解释。** 公共字段定位建议对应的局部决策情境，私有内容表达未来行动。

| 输出字段 | 构建依据与内容指引 |
|---|---|
| `recommendation` | 根据历史经验支持的未来行为方向，选择 recommend、avoid 或 conditional，与正文一致 |
| `applicable_when` | 从相关任务、观测及限制中提炼采用建议所需的条件 |
| `content` | 将历史决策和结果转为未来应采取、避免或暂缓的行为，说明先检查什么、满足何种条件再行动 |

例如，有相应证据时，可建议“作业前核对本次资源需求与可用库存，不足时先补给”，条件分支明确时可归为 conditional。

前三类当前仅考虑 recovered_yield_loss，后续可扩展更多指标。它提供整季结果背景，局部操作效果、经验方向及成因判断依赖相应步骤证据。

#### 3.5 Agronomic Observation

**输入：B＋一次 Oracle 实际执行记录＋对应回放 Yield。** 公共字段对应实际过程开始前的目标作物状态及农事目标，私有内容记录发生的过程。

| 输出字段 | 构建依据与内容指引 |
|---|---|
| `applicable_constraints` | 根据 B、实际作业前状态及设备和资源限制填写，区分过程发生时的条件与有证据支持的必要约束 |
| `procedure[].action` | 按执行顺序、工具参数和目标范围记录动作，保留必要的时间、参数及单位 |
| `procedure[].observed_result` | 根据工具返回、实际完成范围、错误、partial 和后续记录如实填写；缺少记录时为 null |

例如，执行记录包含“检查库存 → 补给 → 执行作业”时，按顺序记录对应动作和返回，未记录的检查不补写。局部操作结果与整季回收量分别注明范围。

## 三、分步数据库构建：输入、输出、prompt、内容指引与约束

**TODO：在来源材料、两张表的字段及四类内容规范确认后，设计具体 prompt 和读写实现。** 当前固定以下两步的输入输出边界。

| 步骤 | 输入 | 处理与内容约束 | 输出 |
|---|---|---|---|
| 第一步：构建初始知识 | 单次 Agent 或 Oracle 来源材料，以及对应类型的字段规范 | 阅读完整 L3 记录，识别 L2 单元，逐条判断公共字段并生成对应私有内容；依据本次来源新增 | 第一张表的新增条目、来源证据和材料缺口说明 |
| 第二步：校准与整合 | 第一张表中，同一知识类型且全部公共字段完全一致的一组条目及其关联证据 | 继承分组公共字段，根据具体目标、私有条件及正文判断合并、分别保留或处理冲突 | 第二张表的正式知识，以及合并、冲突和删减说明 |

后续分别为四类知识设计输入示例、输出示例和内容指引，具体拆成多少份 prompt 在校准时确定。优先明确以下内容：

1. L3 材料如何识别为 L2 单元，操作前物候和农事阶段如何逐条判定。
2. 各类型的完整输入包、结构化输出、prompt、证据要求及缺失信息处理。
3. 同组内的合并、分别保留、冲突和删减判定，以及公共字段误判后的更正方式。
4. JSON 校验及 SQLite 固定读写函数，新增、修订、撤回和版本继承／发布规则，必要的检测与错误报告。

SQLite 与 JSON 的配合方式沿用既定方向：Agent 输出结构化 JSON，审阅和校验通过后，由固定函数写入数据库。具体操作枚举、函数签名、事务和版本协议留待设计。任务检索与 G 载入暂为 TODO，已确认任务 query 只使用场景的纯 B。

前期由用户审阅材料、字段、初始知识和整合结果，重点检查来源配对、L2 单元边界、单值标签、证据及冲突处理。小样本校准通过后再逐步托管给 Agent。后续仍按 formal90 原顺序排除 mini20，冻结 20／20／20／10 个新场景批次，累计覆盖 20／40／60／70；每批可新增来源并更正早期知识，分别记录候选产出与正式新增、修订、撤回、保留及待补数量。知识版本与批次分别记录。mini20 效果验证在纯 B 查询和 G 载入可用后进行。

### Original Library Modes

默认 G、`reusable_operational_guidelines` 和旧 library 各自独立管理。四类新知识按本文来源和生成流程建设。旧模式的数据源、参数及 map 兼容说明见[现有 library 替换 G 的说明](../README.md)。
