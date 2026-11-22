# FAIRY 知识库构建与迭代计划

目标是打通场景材料整理、四类知识生成、结构化存储、发布和后续更正。实施按 **以场景为单位整理数据源 → 说明源字段及其用途 → 用 prompt 建立源字段与知识字段的联系 → 自动构建并校验初版知识库** 推进。先完整归集场景内各次运行，生成时再决定知识的主题和条数。

本文区分当前可读取的材料与拟实施的接口。下述场景材料包、数据库、生成和更新协议是建设规格。首轮以 70 个非 L3-mini 的 L3 场景验证流程，来源集合、作物、词表和版本均可扩展。检索与挖掘当前只确定 **待运行场景的纯基础任务描述 B 为 query**，算法与 G 载入接口留作 TODO。

## 一、FAIRY 知识库设计

### 1. 四类知识及其来源

| 类型 | 构建材料 | 输出目的 |
|---|---|---|
| Agronomic Skill | B＋Agent 工作流＋Yield 和 KTC | 可复用的农事操作指引，说明何时适用、怎样检查和操作、如何确认结果 |
| Agronomic Reflection | B＋Agent 工作流＋Yield 和 KTC | 对历史工作流中某种成功经验或错误的成因推断 |
| Agronomic Guidance | B＋Agent 工作流＋Yield 和 KTC | 从历史工作流提炼未来应采取、避免或按条件决定的行为 |
| Agronomic Observation | B＋Oracle 工作流＋Oracle 回放 Yield | 有适用约束的农事过程与结果记录，后续接入真实农场回流 |

当前 Oracle 材料的来源种类记为 `simulated_oracle_replay`。未来真实农场记录使用 `real_farm_record`，保留实际作业和收获资料。两种来源共用 Observation 内容结构，来源种类由材料包记录。

### 2. 公共标签与管理字段

| 字段 | 格式与含义 | 填写依据 |
|---|---|---|
| `release_id` | 全库发布版本，如 `structured_knowledge_v01` | 发布程序分配，导出每条知识时带入 |
| `source_scenario_id` | 一个来源场景 ID | 从场景材料包填写。同一条可以引用该场景的多次运行 |
| `crop` | 作物代码，当前为 `soybean` | B 中明确的作物或实际观测 |
| `cultivars` | 去重代码数组，证据不足为 `null` | B 中明示品种及目标田块实际播种、状态返回 |
| `growth_stages_before` | 操作或指引适用时的物候标签数组，证据不足为 `null` | 目标田块操作前的状态，按对应引擎版本映射 |
| `farming_group` | `establishment / management / harvest` | 知识主题所对应的主要农事阶段 |
| `task_types` | 非空、去重的任务代码数组 | 工具动作、任务目的与前后上下文共同判断 |

除版本外，上述场景和农学标签保留为后续可查询字段。首版一条知识归属一个来源场景，多场景材料按场景分别生成。多阶段过程可保留在正文中，物候标签表示该条知识开始适用的状态。存在多个不同的适用入口时，可分别成条。`null` 表示未知，跨品种或跨阶段通用可用 `["any"]` 表示，需有支持其适用范围的证据，且与具体代码互斥。

品种／种子类型的首版词表为 `EARLY_COLD、STANDARD、HIGH_DENSITY、STRESS_TOLERANT、HEIHE43、HEIHE50、HEINONG58、HEINONG60、HEINONG84、HEIKE71`。前四项是引擎内的通用种子类型。取值以涉及的田块为准，库存清单只能证明可用资源。[种子类型定义](../../fairy/apps/farm_world/models.py)

物候标签为 `FAIRY-Engine-` 加以下 14 个状态名，`NOT_PLANTED、PLANTED_PRE_EMERGENCE、VE、VC、V1、V2、V3、V4_PLUS、R1、R3、R5、R6、R7、R8`。适配器明确映射实际返回值，如 `R1_BEGINNING_BLOOM → R1`，并保留原值。旧显示值可能合并多个状态，只有结合对应版本及同一田块的其他证据能唯一确定时才填精确标签。后来的物候状态不能回填到先前操作。[物候定义](../../fairy/physics/phenology_engine.py) · [显示值兼容映射](../../fairy/apps/farm_world/physics_orchestrator.py)

农事分组沿用当前三组。具体任务类型先采用下列候选词表，第一批生成时核查覆盖范围，遇到无法表达的任务登记新词及定义，再统一扩展词表。[现有农事分组](../../fairy/scenarios/farm_world_fullseason_v2/harbin_l3_context_briefings.py) · [现有动作类型](../../fairy/scenarios/farm_world_fullseason_v2/harbin_l3_batch_scenario.py)

`field_prep_planting、planting、planting_window、irrigation_planting_window、management_scouting、fertigation、irrigation、fungicide、herbicide、insecticide、mechanical_weed、replant、stand_recovery、harvest_postharvest`。

另保留最小的管理信息。`knowledge_id` 是稳定身份，`revision` 从 1 开始，`knowledge_type` 为 `skill / reflection / guidance / observation`。`generation_id` 关联本次生成或更新的输入清单、prompt、模型和规范版本。`evidence` 关联来源运行、文件及步骤，服务于生成、核查和更正。具体垄号和文件位置放在证据中，农业检索使用上表字段。

### 3. 私有字段与内容约束

以下字段组成每种知识的 `payload`。表中列出的键均须出现，额外键须先纳入 schema 版本。

| 类型 | 字段与 JSON 类型 | 内容规范 |
|---|---|---|
| Skill | `applicable_when` 字符串，`pre_checks` 字符串数组，`constraints` 字符串数组，`operation_template` 字符串数组，`post_checks` 字符串数组 | 适用条件可观察、可判断。检查及操作按依赖顺序排列，说明参数从何取得。区分执行返回与后续效果，只有关键前提有依据时才写“必须” |
| Reflection | `success` 布尔值，`applicable_when` 字符串，`content` 字符串 | true 表示总结可肯定的经验，false 表示明确一种错误。正文包含历史行为、可见结果和原因推断，说明推断的依据与不确定处 |
| Guidance | `recommendation` 三值枚举，`applicable_when` 字符串，`content` 字符串 | `recommend` 表示在适用条件下建议采取，`avoid` 表示应避免，`conditional` 表示要根据补充检查或条件分支决定是否采取。正文写明行为、触发条件及需要时的等待／检查规则 |
| Observation | `applicable_constraints` 字符串数组，`procedure` 对象数组 | 按实际发生顺序描述作业，每步包含 `action` 字符串及 `observed_result` 字符串或 null。实际参数、覆盖范围、失败和部分完成如实记录，数值带单位 |

Reflection 的 `success` 描述该条解释的方向，整季成功的运行也可以产生指出局部错误的 Reflection。Guidance 采用本版明确的 `recommendation` 三值。若内容是在建议“先检查”，可填 `recommend`，若内容包含“检查后满足 A 才做 X，否则暂缓”，可填 `conditional`。适用条件需要在三种取值下都写清。

必要正文为非空字符串，检查、模板和流程为有序非空数组。约束数组允许为空，表示来源尚未支持具体约束，生成报告记录这一缺口。缺失结果显式写 `null`，不以成功补齐。证据不足以形成有用内容时跳过并说明原因。整季指标保存在关联来源中，每条知识可读取其对应的指标，避免手工重复抄写数值。

## 二、FAIRY 知识库数据来源

### 1. 以场景为单位整理材料

首轮场景集合为[正式 90 场景](../../scripts/fullseason/formal_90_scenario_ids.txt)减去 [L3-mini 20](../../scripts/fullseason/l3_mini_20_scenario_ids.txt)，得到 70 个 ID。按场景归集以下来源中的 `return_code=0` 运行，每次运行分别保存身份、完成情况和评分。多个模型、B/BP 和重跑都保留来源区别。同一运行的多份评分按生成清单锁定一份。

| 来源集合 | 明确允许的目录 | Agent 评分绑定 |
|---|---|---|
| DeepSeek Flash B | [l3_formal90_deepseek_flash_B_nothink_El08gq](../../validation_runs/l3_formal90_deepseek_flash_B_nothink_El08gq/) | 逐次核对对应评分，缺失项登记待评分，用固定版本的 rebatch 流程补齐 |
| DeepSeek Flash BP | [l3_formal90_deepseek_flash_BP_nothink_OL0lel](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_OL0lel/) | [20261121_34tfrwwj 汇总](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_OL0lel/replay_analysis_20261121_34tfrwwj/rebatch_fos/summary_v2_rebatch_fos.csv) |
| DeepSeek Flash BP rerun | [l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM/) | [20261121_qmown_yo 汇总](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM/replay_analysis_20261121_qmown_yo/rebatch_fos/summary_v2_rebatch_fos.csv) |
| Thor Qwen BP | [l3_formal90_thor_qwen35b_BP_nothink_lvxtsU](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_lvxtsU/) | [20261120_3xx6dk_b 汇总](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_lvxtsU/replay_analysis_20261120_3xx6dk_b/rebatch_fos/summary_v2_rebatch_fos.csv) |
| Oracle | [oracle_140_verification_20261116](../../validation_runs/oracle_140_verification_20261116/) | 同场景的 `execution_workflows/`、`baselines/`，结合参考包 manifest 配对 |

每次生成前扫描当前文件并冻结清单，记录纳入、待补和跳过的数量及原因，目录增长后再建立下一次生成迭代。按“来源目录＋cell 相对路径”识别一次 Agent 运行，并核对报告和评分行的场景 ID。同一场景可以同时拥有多份 B 版本，各运行引用其实际使用的版本。Oracle 通过“参考包版本＋场景 ID”关联执行资料和基线。

Agent 材料读取根目录的 `results.csv`、对应 cell 内的 `*.agent_workflow.json` 和 `*.run_report.json`，按需用 `*.runtime_log.jsonl` 补查。Oracle 材料读取 `execution_workflows/<id>.json` 与 `baselines/<id>.json`，`workflows/<id>.json` 和 `terminal_states/<id>.json` 辅助核对。评分行须 `status=ok`、两列均为有限数值，且 KTC 在 0–100 范围内。回放错误另行检查影响。不同运行的 B 仅在正文哈希一致时共用同一文本。

建议的场景材料包包括以下部分。原始文件保留，整理器输出可迁移的路径、哈希和内容视图。

| 材料包部分 | 内容 | 整理规则 |
|---|---|---|
| `scenario_id`、`base_tasks` | 场景编号，以及按 `base_ref` 标识的纯 B、代码版本和初始化参数 | 从对应版本按 `detailed_briefing=false` 提取 B，有 `base_sha256` 时核对。BP 或 Oracle 的首条 USER 可能带计划，需先还原纯 B |
| `agent_runs` | 每次运行的 `source_ref`、`base_ref`、运行元数据、完整有序工作流、对应 Yield/KTC、完成与回放状态 | 保留时间、步骤 ID、调用参数、返回、错误和重试。评分暂缺时保留材料并标待评分，补齐后用于前三类知识生成 |
| `oracle_runs` | `source_ref`、`base_ref`、实际执行流程、配套回收量、来源种类和参考包版本 | 声明 workflow 辅助检查预期操作，实际执行返回用于描述发生的过程。终态用于核对最终状态 |
| `source_manifest` | 各文件的来源根、相对路径、哈希，评分行键，运行代码与配置版本，缺口 | `source_ref` 唯一定位一份冻结的来源记录，更正材料产生新引用，原记录可追溯 |

整理器保留全场景材料和步骤关系，生成 Agent 可以按需分页读取长轨迹，并记录已读取的范围。生成阶段可按主题归纳，输入材料应足以回查其他步骤，避免初次整理就丢失远距离依赖。原始 USER／系统指令、P/G 文本在生成视图中剔除，原始文件仍可通过审计引用定位。B/BP 等运行条件保留在元数据中。[运行产物定义](../../fairy/controllers/run_artifacts.py) · [基础正文处理](../../fairy/scenarios/farm_world_fullseason_v2/harbin_l3_context_briefings.py)

### 2. 源字段及其与知识字段的对应

下表列出现有文件中的字段和可用内容。`base_tasks`、`source_ref` 等材料包字段由整理器产生。工具 `content` 的结构随工具而异，词典应保留实际 JSON 路径及单位，按工具逐项扩展。

| 来源及真实字段／内容 | 可支持的知识字段 | 使用方法与边界 |
|---|---|---|
| 纯 B 文本中的作物、品种、田块规模、已知风险和任务要求 | `crop`、`cultivars`、适用条件／约束、任务主题 | 明示内容可提取。风险提示用于解释为何检查，具体受影响范围从工作流观测确定 |
| `run_report.scenario_id`、`seed`、`model`、`scenario_kwargs`、`init_kwargs`、`status`、`stopped_reason`，`results.csv` 的 `return_code`、`timed_out` | 场景关联、生成元数据、证据完整性 | 程序确定来源身份和完成边界，条目方向结合正文行为判定 |
| 工作流事件的 `name`、`time`、`time_before/time_after`（存在时）、`depends_on` | 检查与操作顺序、Reflection 历史经过、Observation 流程 | 保留原始顺序和步骤 ID，跨天或依赖关系应可回查 |
| 事件的 `op_type`、`tool_name`、`tool_args` | `farming_group`、`task_types`、操作模板和流程动作 | 参数证明请求了什么，执行完成范围仍需查返回。工具名辅助分类，任务目的结合上下文判断 |
| `content.ridges[]` 中的 `seed_type`、`growth_stage`、`planted`、`ridge_id` 等状态 | 品种、操作前物候、适用条件 | 取同一目标田块在操作前的可用观测。补种或重新播种后须注意物候重置 |
| 工具返回中的苗情、营养、水分、天气、病虫、库存、设备与容量信息 | 适用条件、前置检查、操作约束 | 使用相应工具真实字段、单位和观测范围。具体数值首先作为本次事实，普遍阈值需有额外支持 |
| 返回的 `status/error`、`covered_ridges/uncovered_ridges`、`replanted_ridges`、产量及其他结果 | 后检查、Reflection 原因依据、Guidance 条件、Observation 结果 | 按工具返回解释成功、失败和 partial。请求覆盖与实际覆盖分别记录，`status=ok` 时也核对完成范围 |
| 指定评分行的 `recovered_yield_loss(%)`、`ktc(%)`，以及 `status`、`replay_exec_errors` | 前三类知识的整季结果背景、证据可用范围 | 绑定同次运行。局部归因需要相应步骤和对照证据，评分变化本身不能定位原因 |
| Oracle 执行事件的同名字段，及 `baselines/<id>.json` 的 `recovered_yield_kg_total`、`extrapolation` | Observation 适用约束、实际流程和配套整季回收量 | 保留参考包版本及外推信息。全季产量与局部工具返回的收获量分别说明范围 |

私有字段由上述事实按以下方式形成，prompt 需要为每一项规定提取、归纳或写作方式。

| 知识字段 | 对应材料与形成方式 |
|---|---|
| Skill `applicable_when` | 结合 B 与操作前观测，把历史状态归纳为可判断的触发条件 |
| Skill `pre_checks` | 读取操作前查询及返回，整理有依赖关系的检查顺序，解释检查要确认什么 |
| Skill `constraints` | 提取明示限制、设备资源状态和有明确原因的错误，保留约束的适用范围 |
| Skill `operation_template` | 从工具与参数归纳步骤，将实例垄号、日期、用量改写为按当前任务取值的方法 |
| Skill `post_checks` | 从操作返回和后续复查提炼可执行的验收项，标清仅确认执行或已观察到效果 |
| Reflection `success/applicable_when/content` | 根据具体历史行为及结果确定经验方向，再写有证据的成因解释。工具错误与处理后重试可支持局部归因，多次运行的比较需核对条件差异 |
| Guidance `recommendation/applicable_when/content` | 将历史证据改写为面向未来的行为建议，写清触发条件、操作方向和必要的条件分支 |
| Observation `applicable_constraints/procedure` | 依据 B、Oracle 操作前状态、实际执行及返回形成有序过程，记录发生了什么和结果可见到什么程度 |

**指标口径**固定如下。Agent Yield 取 `recovered_yield_loss(%)`，即 `100 × (1 − Agent 回收量 / Oracle 回收量)`，越低越好，可为负数，分母缺失或不大于零时无定义。KTC 取 `ktc(%)`，是 v1 的 `ktc_raw` 百分化，范围 0–100。保存评分版本及其 Oracle 基线，同一运行重评建立新评分记录。[Yield 计算](../../fairy/scenarios/fos/evaluation.py) · [KTC 计算](../../fairy/scenarios/workflow_validation.py) · [汇总列写入](../../scripts/rebatch_fos_from_traces.py)

Oracle 的 Yield 使用 `recovered_yield_kg_total`，单位 kg。当前参考包的 baseline 由生成器按相同配置另行执行 Oracle 得出，执行日志与配套 baseline 按参考包关联，局部事件结果另从执行返回读取。[参考包构建程序](../../scripts/fullseason/build_time_control_references.py) · [Oracle 验证摘要](../../validation_runs/oracle_140_verification_20261116/verification_summary.json)

### 3. 四类首次构建的 Agentic 流程

**输入组合**由程序装配为“共享指令＋本类型生成指令＋字段 schema／词表＋场景材料视图”。每次调用明确知识类型。Skill、Reflection、Guidance 接收该场景的纯 B、已选 Agent 运行、各自指标与完成边界。Observation 接收纯 B、Oracle 实际执行和配套回收量。各运行的 B、参数、时间线和评分分别关联，跨运行的比较在正文中注明来源和条件差异。

共享指令要求 Agent 先检查材料是否读全、运行与评分能否配对，再阅读全场景的任务与过程，最后提出有证据的知识候选。零条、一条和多条均可。长轨迹分页读取或分次归纳后，要汇合证据并检查遗漏、重复和矛盾。模型可以调用只读材料查询和结构校验工具，提交结构化候选，入库由程序执行。

四份首次构建 prompt 使用下表中的类型指令，与共享规则和材料一起组成可版本化的完整输入。

| Prompt | 类型任务与写作指引 |
|---|---|
| `skill_generate` | 阅读本场景 Agent 的任务、过程和两项指标。找出有证据支持的可复用农事操作，按 Skill 五个字段输出。模板写出当前任务如何确定范围和参数，前后检查说明要确认的结果。错误和重试可以作为补足检查与约束的依据 |
| `reflection_generate` | 阅读历史行为、直接返回、后续状态和整季指标。围绕某一成功经验或错误先陈述事实，再写原因推断。证据只能支持可能解释时使用限定表达，若存在实质不同解释则说明。按所解释经验填写 success |
| `guidance_generate` | 从实际工作流和结果提炼未来行为，写成“何种条件下建议做什么／避免什么／还需检查什么”。按正文语义填写 recommendation。建议限于证据可支持的情境，实例数值外推需说明依据 |
| `observation_generate` | 按实际执行顺序整理 Oracle 作业及返回，填写适用约束和流程。保留操作参数、实际范围、部分完成和未观测结果，关联配套回收 kg。只写来源中发生或明确记录的过程 |

**结构化输出**采用统一 JSON 外壳，首次生成的 `operation` 为 `add`。下例为结构模板，尖括号内容在实际输出时由具体值替换。`tags` 包含全部五个农学字段，`payload` 依类型使用第一节的规范。`reason` 简述形成此候选的依据。

```json
{
  "proposals": [
    {
      "operation": "add",
      "knowledge_type": "skill",
      "tags": {
        "crop": "soybean",
        "cultivars": null,
        "growth_stages_before": null,
        "farming_group": "establishment",
        "task_types": ["planting_window"]
      },
      "payload": {
        "applicable_when": "<可判断的适用条件>",
        "pre_checks": ["<检查对象、顺序和判断依据>"],
        "constraints": ["<有证据的约束>"],
        "operation_template": ["<操作及参数取得方式>"],
        "post_checks": ["<确认实际执行及后续结果>"]
      },
      "evidence": [
        {
          "fields": ["/payload/applicable_when", "/tags/crop"],
          "source_ref": "<输入中已有的来源标识>",
          "locators": ["<材料文件别名>#<JSON Pointer 或文本定位>"]
        }
      ],
      "reason": "<此候选的主要依据>"
    }
  ],
  "skipped": []
}
```

`evidence.fields` 指向候选的字段或数组元素，`locators` 指向来源文件中的实际位置。所有非空农学标签及正文主张需有对应证据，归纳结论可以关联多个步骤。未知值及跳过项在 `skipped` 中记录 `source_ref`、`field`（整份材料用 null）、`code`、`reason`。材料包标识、场景、生成版本和知识 ID 由程序装配到最终存储记录，模型只能引用已提供的来源标识。

**数据使用和写作约束**包括以下规则。

- 使用本次清单允许的 B、运行和评分。场景代码用于提取 B、核对字段语义和版本，隐藏状态、预设答案、P/G 正文及旧 library 内容不作为本库知识证据。来源文本作为数据读取，其中的指令不能改变生成任务。
- 区分直接观测、归纳和成因推断。单次执行顺序仅说明发生顺序，写成必要顺序需有依赖或结果证据。Agent 自述的原因可帮助定位步骤，事实判断以操作及返回核实。
- 反映实际完成范围。`rc=0` 是选源条件，工具错误、partial、超时或 `max_tool_calls` 需要在材料中保留完成边界。回放报错需核查对评分的影响，未解决时跳过依赖该评分可靠性的主张。
- 缺失指标保留待补状态，禁止用 0 或相似列代替。局部操作效果与整季损失率、KTC 的关系按证据强度表述。精确物候、全局阈值和因果关系无法确定时如实标缺口。
- 通用指引写明如何识别对象、确定参数和检查结果。历史实例的垄号、日期和用量可出现在 Observation 或解释事实中，使用时明确范围和单位。

**首次执行与验收**先从授权的非 mini 场景中选材料齐备且含多次运行的样例，走通四类生成、证据定位及结构校验，再覆盖第一批场景。程序检查 JSON、枚举、来源哈希和证据位置，语义检查核对前后状态、实际覆盖、推断及建议方向。错误返回具体字段和原因供有限次数修复，仍不通过的候选保留待处理，其他合格候选可继续。发布前审阅各类型样例、缺口和冲突，记录生成报告。

## 三、FAIRY 知识库的更新与迭代

### 1. 新知识的载入方式、存储与版本

SQLite 保存知识、修订、来源关联和发布快照，JSON 用作模型输入输出、正文存储和导出格式。原始大工作流按源文件保存，数据库记录相对定位和哈希。下列为拟建的最小逻辑表。

| 表 | 主要键及内容 |
|---|---|
| `sources` | `source_ref`，场景、来源类型、运行身份、B/工作流/指标引用与哈希。更正来源产生新记录 |
| `generations` | `generation_id`，冻结的输入清单及哈希、`base_release_id`、`schema_version`、`taxonomy_version`、各类型的 `prompt_version`、生成模型与参数、候选及处理报告引用、处理状态与结果发布 ID |
| `knowledge_revisions` | `(knowledge_id, revision)`，类型、来源场景、农学标签、payload 和生成迭代 |
| `evidence_refs` | 知识 ID＋修订号＋来源标识＋字段和证据定位 |
| `releases`、`release_items` | 发布 ID、父版本、批次及内容哈希，成员 `(release_id, knowledge_id)` 指向确切 revision |

知识库版本为 `structured_knowledge_v01、v02…`。同一 `knowledge_id` 的内容、标签或证据发生更正时 `revision` 加 1。`generation_id` 记录一次提炼，多个生成迭代可汇入同一发布。schema 和词表单独版本化，未来换作物、物候引擎或来源格式时通过适配器和显式迁移扩展，旧快照仍按当时规则解释。

新数据到达后，先更新对应场景材料包，再按下表提出操作。

| 操作 | 使用条件 | 存储效果 |
|---|---|---|
| `add` 新增 | 新的知识主题、实质不同的适用情境，或独立发生的新 Observation | 程序分配新 knowledge_id，revision=1 |
| `revise` 修订 | 同一知识的事实、适用条件、解释、建议、标签或证据需要补足／更正 | 保持 ID，写入完整的新修订，保留旧修订 |
| `keep` 保留 | 当前条目内容与证据已经足够，此次材料无需改变它 | 记录本次比较结论，沿用已有修订 |
| `retire` 撤回 | 已有知识证实无效，或其内容由其他条目完整替代 | 从新快照的有效成员中撤下，登记原因及替代 ID，保留历史 |

同一 Observation 事件的补录或更正采用 revise，独立的新作业实例采用 add。只有标签相同不足以合并知识。证据尚有冲突时保留候选和冲突原因，待查证后决定修订。拆分可用“旧条 retire＋新条 add”，合并可用“保留条 revise＋其他条 retire”，同批候选通过输出数组索引关联，程序最终写入实际 ID。

指标按来源运行及评分版本保留。未来可据此检查某类知识引用的实验结果、筛选比较材料和核查反例，阈值与评分聚合方法待设计。重算指标触发受影响条目的复审，不自动翻转 Reflection 的 success 或 Guidance 的 recommendation。检索／挖掘的 query 固定为纯 B，检索算法、结果排序和 G 装配留作 TODO。

### 2. 自动更新的 Agentic 输入、输出与约束

**更新输入**沿用场景材料包、schema、词表和四类写作规则，增加基础发布版本、旧条目的 ID／修订／正文／原证据、新材料以及变更说明。程序按来源关联找出受影响条目，并提供同一场景、同一类型的已有知识供比较。旧资料和新资料都应可查，评分重算或源文件修正要明确替换了哪个来源版本。

四份更新 prompt 分别在首次生成指令上增加以下任务。

| Prompt | 比较任务 |
|---|---|
| `skill_update` | 比较触发条件、检查依赖、操作参数来源和结果验证。补充同一方法采用 revise，新方法或不同适用情境采用 add，失效方法可 retire |
| `reflection_update` | 检查新事实如何支持、削弱或推翻旧成因解释，说明事实与推断分别改了什么。根据条目经验方向核对 success |
| `guidance_update` | 检查原建议的适用条件和行为方向。局部反例可促使收窄条件或拆分，充分证据支持方向改变时同步修改正文和 recommendation |
| `observation_update` | 判断是同一事件的更正还是新的独立作业，核对动作、实际范围、返回和配套产量，保留来源版本及未解冲突 |

**更新输出**沿用 `proposals/skipped` 外壳，所有操作均有 `knowledge_type` 和 `reason`。add 使用首次生成结构，revise 额外提供 `knowledge_id` 和 `expected_revision`，并提交完整 tags、payload、evidence。keep／retire 提供 ID、预期修订、证据及原因，正文省略。拆分／合并时 retire 另带 `replaced_by`，引用已有 ID 或本批 add 的数组索引。未决冲突写入 skipped，code 为 `EVIDENCE_CONFLICT`。

keep／retire 的 `evidence.fields` 使用 `["/reason"]`，证据用于核查本次决定并存入操作记录。若要补充知识自身的证据集合，使用 revise。`replaced_by` 为对象数组，每项使用 `{"knowledge_id": "已有ID"}` 或 `{"proposal_index": 0}`，后者为原始 proposals 数组的零基索引且只能指向 add。替代目标必须在新快照有效，关联新增或修订未通过时，相关撤回也暂缓提交。

下面示意一次 Guidance 修订。实际 evidence 需覆盖所有新正文和标签，保留仍有效的旧证据并补充新证据。

```json
{
  "proposals": [
    {
      "operation": "revise",
      "knowledge_type": "guidance",
      "knowledge_id": "<输入中已有的知识 ID>",
      "expected_revision": 1,
      "tags": {
        "crop": "soybean",
        "cultivars": null,
        "growth_stages_before": null,
        "farming_group": "management",
        "task_types": ["replant"]
      },
      "payload": {
        "recommendation": "conditional",
        "applicable_when": "<修订后的适用条件>",
        "content": "<检查结果满足哪些条件才行动，否则如何处理>"
      },
      "evidence": [
        {
          "fields": ["/payload/content", "/payload/recommendation"],
          "source_ref": "<已登记的新证据标识>",
          "locators": ["workflow#/<原步骤 ID>/content"]
        }
      ],
      "reason": "<新证据如何影响原有建议>"
    }
  ],
  "skipped": []
}
```

更新 Agent 只能引用输入中的旧 ID 和来源。source_scenario_id 和 knowledge_type 构成条目身份边界，变更归属时采用新条目并说明替代关系。每个旧 ID 在同批中最多有一个操作，keep 也计入。新增证据即使没有改变正文，也通过 revise 固定新的证据集合。模型产生建议，写入器核对基础版本和 expected_revision 后提交。

### 3. 自动提交、检测与分批闭环

1. **登记输入并生成候选。** 每次任务固定 generation_id、输入清单、来源哈希、规范、prompt、生成模型配置及基础版本，据此计算处理键并保存原始输出。相同 generation_id 的重试复用已成功处理的结果，失败任务从已保存状态继续。主动重新提炼分配新 generation_id 并产生新处理键。
2. **校验和比较。** 检查结构、来源、证据和内容，完全相同的内容及证据记录为 keep。疑似重复或矛盾交回更新流程比较。相同标签下的不同经验允许并存，未决条目列为待处理。
3. **事务提交并发布。** 启用外键，对处理键和修订建立唯一约束，校验预期父版本及修订号。在一次事务内提交本次修订、证据、变更记录、新快照成员以及 committed 状态和结果发布 ID。新快照从父版本有效成员出发应用 add／revise／retire，keep 沿用原成员。重复提交 committed 任务返回原发布结果，pending／failed 任务从保存状态恢复。失败则回滚本次写入，冲突需基于新版本重新比较，成功后发布号绑定固定内容。
4. **分批验证。** 首轮按 formal90 原顺序排除 mini20，冻结 20／20／20／10 个新场景的批次清单，累计覆盖 20／40／60／70。后续批次可以新增来源并更正早期知识。每批记录新增、修订、撤回、保留及待补数量，版本号与批次分别记录。
5. **回流修正。** 新运行、补评分、源数据更正进入对应场景材料包，受影响知识走更新流程。mini20 每批验证绑定具体知识版本，其结果用于发现问题，修订内容回到建库来源查证。mini20 轨迹及评分隔离于知识生成输入。

每批先完成材料、生成和数据库校验。mini20 对新库效果的验证需要后续完成读取与 G 载入接口，届时固定模型、种子策略、P 开关和知识版本，记录实际使用的知识 ID 与修订。首轮数据库建设阶段将该依赖列为待接入项。

| 检测点 | 错误信息及处理 |
|---|---|
| 来源范围和身份 | `SOURCE_OUT_OF_SCOPE` 指出未登记来源或 mini20 混入，阻止冻结。`RUN_ID_MISMATCH` 指出无法配对的运行／评分，隔离该包 |
| 材料完整性 | `TRACE_MISMATCH` 指出文件、哈希或 B 版本不符，停止使用该包。`METRIC_MISSING` 指明缺少的指标及运行，登记待补 |
| 字段和证据 | `INVALID_PAYLOAD` 返回字段路径和类型／枚举错误。`UNSUPPORTED_CLAIM` 返回无法支持的主张和所引证据，退回修复。语义检查结论及审阅记录保留 |
| 冲突和并发 | `EVIDENCE_CONFLICT` 保留待查证项。`STALE_REVISION` 指出目标修订已变化。`RELEASE_CONFLICT` 指出基础版本或成员冲突，取消本次事务 |
| 生成失败 | `GENERATION_FAILED` 保留请求、已读范围及错误。修复次数达到配置上限时退出该任务，允许后续按相同处理键恢复 |

首版实施产物依次为场景材料包及清单、源字段字典、知识 schema 与词表、四份生成 prompt、SQLite 存储及写入器、四份更新 prompt、生成和变更报告。验收至少走通多运行材料配对、四类候选生成、缺证据跳过、重复提交不重复入库、单条更正与撤回、并发修订冲突，以及新旧发布各自读取对应正文。

## Original Library Modes

默认 G、`reusable_operational_guidelines` 和旧 library 各自独立管理。四类新知识的来源与版本按本文清单和生成协议维护。旧模式的数据源、参数和 map 兼容说明见[现有 library 替换 G 的说明](../README.md#3-用现有library知识替换g)。
