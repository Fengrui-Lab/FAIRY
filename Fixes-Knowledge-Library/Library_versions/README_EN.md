# FAIRY Knowledge Base Design

The **goal** is to automatically build four types of agronomic knowledge from each scenario's base task description B, Agent/Oracle workflows, and their outcomes. SQLite stores the knowledge, while structured JSON supports generation, review, and exchange. Subsequent implementation will support creating, reading, updating, and deleting knowledge, as well as retrieving historical versions.

The **data flow** is: organize materials by scenario → read one L3 full-season record and identify L2 units → first table of initial knowledge → group each knowledge type by exact equality of all common fields → calibrate and consolidate → second table of consolidated knowledge. Each scenario has multiple Agent runs and one set of Oracle records. Initially, the user leads, reviews, and decides on the outputs of each stage. Responsibilities are gradually delegated to the Agent after prompts and processing rules have been calibrated. This document defines the knowledge, sources, and construction boundaries; specific prompts and read/write implementations remain TODOs in Part III.

## I. FAIRY Knowledge Base Design

### 1. Four Knowledge Types and Their Sources

| Type | Source materials | What one L2-level knowledge entry expresses |
|---|---|---|
| Agronomic Skill | B + one Agent workflow + recovered_yield_loss for that run | A reusable method for one agronomic objective, including conditions, checks, constraints, steps, and outcome verification |
| Agronomic Reflection | B + one Agent workflow + recovered_yield_loss for that run | A causal explanation of a local experience or error |
| Agronomic Guidance | B + one Agent workflow + recovered_yield_loss for that run | Advice for future actions addressing a local decision problem |
| Agronomic Observation | B + one Oracle execution record + its corresponding replay oracle_recovered_yield_kg | An identifiable agronomic process that actually occurred |

The current Oracle source is labeled `simulated_oracle_replay`. Future records from real farms will be labeled `real_farm_record`, using the same Observation content structure and preserving evidence of actual operations and harvests. Each Agent run supports extraction of the first three knowledge types; Oracle records support Observation. Each type may produce zero, one, or multiple initial entries, all retaining their respective sources.

### 2. Common Fields and Traceability Information

| Common field | Format and meaning | Basis for assignment |
|---|---|---|
| `knowledge_version` | Knowledge version string, such as `structured_knowledge_v01` | One target version is specified for the current build; both tables use the same identifier |
| `source_scenario_id` | Source scenario ID; each entry belongs to one scenario | Source material package |
| `crop` | Currently the enum value `soybean` | The task and target crop addressed by the entry |
| `cultivars` | Array of cultivar/general seed-type codes; null if unknown | The relevant B description and actual planting or state of the target field |
| `growth_stage_before` | One phenological state string; null if it cannot be established, with the gap reported | Phenological evidence for the target field before the entry's core decision or operation begins |
| `farming_group` | One farming phase: `establishment / management / harvest` | The entry's core agronomic objective |

**Identify L2 units first, then determine the phenological state and farming phase for each entry.** Both fields hold a single value per entry. The initial phenological state or overall task name of the full-season input must not be assigned uniformly to all outputs.

Cultivar/seed-type codes are `EARLY_COLD, STANDARD, HIGH_DENSITY, STRESS_TOLERANT, HEIHE43, HEIHE50, HEINONG58, HEINONG60, HEINONG84, HEIKE71`. The first four are general seed types. Inventory describes available resources; cultivar labels follow the actual task and field. For `cultivars`, null means unknown, and `["any"]` means evidence supports that cultivar is not a constraint. Arrays of specific codes must be nonempty, deduplicated, and normalized to vocabulary order. Do not mix any with specific codes. [Seed definitions](../../fairy/apps/farm_world/models.py)

Phenological labels use the `FAIRY-Engine-` prefix and one of 14 states: `NOT_PLANTED, PLANTED_PRE_EMERGENCE, VE, VC, V1, V2, V3, V4_PLUS, R1, R3, R5, R6, R7, R8`. Each entry selects only one state. Preserve the original observation and explicitly map engine values, for example, `R1_BEGINNING_BLOOM → FAIRY-Engine-R1`. When a legacy display value combines multiple states, use the corresponding version and evidence from the same field to determine the state; leave it null if it cannot be determined uniquely. Dates, farming phases, or post-operation phenological states cannot directly substitute for pre-operation evidence. [Phenology definitions](../../fairy/physics/phenology_engine.py) · [Compatibility mapping](../../fairy/apps/farm_world/physics_orchestrator.py)

Both tables share these common fields and the four payload definitions. `knowledge_type` is a separate identifier with values `skill / reflection / guidance / observation`; each type is processed separately. Entry IDs, source runs, step locators, and generation requests are traceability information. Their boundaries are defined in Section 5.

### 3. L3 Input and L2 Knowledge Units

The input is one complete L3 full-season workflow. Outputs are organized around **L2-level agronomic objectives or local problems**. Each unit addresses an independently understandable objective and retains the relevant conditions, observations and judgments, operations or decisions to defer action, and outcome evidence. Supporting steps such as routine charging, replenishment, waiting, and attaching or removing implements remain with the objective they serve. The agronomic objective is expressed in the content. [Existing L2 segmentation principles](../../fairy/scenarios/farm_world_fullseason_v2/l2_l1_splits/l3-to-l2-l1-split-guide.zh.md)

First organize the full-season process by establishment, management, and harvest, then identify independent units within each phase. Every phase may contain multiple units; management may contain multiple interventions at different times and for different objectives. The number of outputs depends on the units supported by the materials, with no fixed entry count per phase. The same unit may support different knowledge types, each extracted for its own purpose.

- **Create separate entries for independent objectives.** If one inspection identifies both water and nutrient problems that lead to two independent interventions, they may form separate knowledge entries.
- **Keep follow-up checks for the same process in the original entry.** Even if the phenological state has changed by the follow-up, the common field retains the state before the core decision or operation began.
- **Create a new entry when an independent decision occurs at a new phenological state.** For example, an early irrigation event and a later reassessment of whether to irrigate can be two units.
- **Create separate entries for target fields with different pre-operation phenological states.** Each entry uses the single state of its corresponding field.
- **Separate independent objectives across farming phases.** Preserve their dependencies in the content and evidence.
- **Retain failures, omissions, and missing follow-up checks as recorded.** Build knowledge from the available evidence, state its limitations, and do not invent processes or results that did not occur.

Segmentation defines entry boundaries; generation can still consult the complete timeline of the current source. Supporting evidence may span multiple steps, and related units may reference shared observations.

### 4. Type-Specific Fields

| Type | Payload format | Writing requirements |
|---|---|---|
| Skill | `applicable_when`: string; `pre_checks`, `constraints`, `operation_template`, `post_checks`: arrays of strings | Specify triggers, the purpose and dependencies of checks, how parameters are obtained, operations, and acceptance checks. Each array element should preferably express one check or action |
| Reflection | `success`: boolean; `applicable_when`, `content`: strings | true indicates a positive lesson; false identifies an error. Describe historical behavior, visible results, causal inferences, and uncertainties |
| Guidance | `recommendation`: `recommend / avoid / conditional`; `applicable_when`, `content`: strings | Specify future actions and their triggers; conditional explains how additional checks determine whether to act or defer |
| Observation | `applicable_constraints`: array of strings; `procedure`: ordered array of objects, each containing `action` as a string and `observed_result` as a string or null | Record parameters, coverage, results, failures, and partial completion according to the actual process; include units for numerical values |

Reflection's success indicates whether the entry affirms a lesson or identifies an error. A successfully completed run may also yield entries identifying local errors. The four types may address the same topic as methods, causes, recommendations, and facts, respectively; assess duplication according to each type's purpose.

Required text must be nonempty, and checks, templates, and procedures must be nonempty arrays. Constraints that are not yet available may use an empty array with the gap reported; unrecorded results are null. Skip entries that cannot be supported by evidence. Observation locates a process through its source run and step range, and uses `episode_ref` to preserve its identity. Supplementary records of the same process retain that identity; independent events are recorded separately.

### 5. Field Boundaries of the Two Knowledge Tables

**The first table, `knowledge_candidates`, stores initial knowledge built from a single source.** Each row is one L2-level entry from that source. The first stage only adds entries based on the current input. Content from different runs may be similar, complementary, or conflicting; each retains its own source and evidence. When source materials or generated results are corrected, preserve the old records and append new extraction results.

| Field | Type and constraints | Source and boundary |
|---|---|---|
| `candidate_id` | String primary key | Identifies one initial knowledge entry |
| `knowledge_version` | Nonempty string | Target knowledge version for this build |
| `source_scenario_id` | Nonempty string | Supplied by the trusted material package |
| `source_ref` | Nonempty source reference | Refers to exactly one Agent run or Oracle record, including its corresponding B and outcomes |
| `knowledge_type` | Enum of the four types | Knowledge type being constructed |
| `crop` | String | Crop addressed by this entry |
| `cultivars` | JSON array or null | Cultivar scope supported by evidence for this entry |
| `growth_stage_before` | One state string or null | Phenological state before the entry's core decision or operation begins |
| `farming_group` | One value from the three-phase enum | Farming phase of the entry's core objective |
| `payload` | JSON object | Complete fields for the knowledge type, as defined in Section 4 |
| `evidence` | Nonempty JSON array | Each item contains source_ref, original-material locators, and the supported knowledge fields; all come from the current source record |
| `episode_ref` | String or null | Identity of the actual process described by an Observation; null for the other types |
| `extraction_request_id` | Nonempty string | Links the current input, generation configuration, output, and review record |

**The second table, `knowledge_revisions`, stores calibrated and consolidated knowledge.** Process the four types separately. Within each type, group entries by exact equality of all common fields: `knowledge_version`, `source_scenario_id`, `crop`, `cultivars`, `growth_stage_before`, and `farming_group`. Each group may produce zero, one, or multiple consolidated entries; each row is one revision of a consolidated knowledge entry.

Compare cultivar arrays after normalization. null matches only null, and `["any"]` matches only itself. Source runs, entry IDs, requests, and evidence are not grouping fields. Equal common fields only define the consolidation scope. Matching unknown values do not establish applicability; the group's specific objectives, type-specific applicability conditions, and content still need to be compared.

| Field | Type and constraints | Source and boundary |
|---|---|---|
| `knowledge_id`, `revision` | String + positive integer | Consolidated knowledge identity and revision number |
| `knowledge_version` | Nonempty string | Inherits the group's target knowledge version |
| `source_scenario_id` | Nonempty string | Inherits the group's scenario |
| `knowledge_type` | Enum of the four types | Matches the type of the linked initial entries |
| `crop` | String | Inherits the group's crop |
| `cultivars` | JSON array or null | Inherits the group's cultivar value |
| `growth_stage_before` | One state string or null | Inherits the group's pre-operation phenological value |
| `farming_group` | One value from the three-phase enum | Inherits the group's farming phase |
| `payload` | JSON object | Complete content after calibration, merging, or condensation, following the same type specification |
| `candidate_ids` | Nonempty, deduplicated JSON array | Complete set of initial entry IDs supporting this consolidated entry; all belong to this group |
| `evidence` | Nonempty JSON array | Evidence linking consolidated fields to original materials; sources are limited to those of the linked initial entries |
| `episode_ref` | String or null | Observation retains the corresponding process identity, with independent events kept as separate entries; null for the other types |
| `consolidation_request_id` | Nonempty string | Links the current group's inputs, decision rationale, outputs, and review record |

Calibration and consolidation follow these content rules:

- Merge overlapping claims when their conditions are compatible, retaining supporting sources. Preserve separate entries when differences in objectives, methods, or conditions affect decisions.
- Complementary content may add checks, constraints, or explanations, but each addition requires evidence. Steps from different runs retain their source attribution and must not be spliced into a single process presented as having actually occurred.
- When sufficient evidence resolves a conflict, correct or remove the relevant content. Otherwise, flag the linked entries, disputed content, and reasons in the consolidation report for review; do not use them as established conclusions.
- Record reasons for content that is not adopted, retaining the original entries in the first table. Flag misassigned common fields for correction; consolidated entries must still comply with the group's field-equality requirement.
- The number of candidates, number of models, and full-season scores cannot replace judgment based on specific evidence. Retrieve source scores and explanations through their links. Consolidation does not produce a "combined score" representing a local effect.

One initial entry may support multiple consolidated entries, and multiple initial entries may support the same consolidated entry. The knowledge version identifies the current build version; revision identifies a revision of an individual consolidated entry. Reuse across versions, publication, and withdrawal of existing consolidated knowledge remain to be designed in Part III.

## II. FAIRY Knowledge Base Data Sources

### 1. Source Collection and Scenario Material Packages

The first round uses the [formal 90 scenarios](../../scripts/fullseason/formal_90_scenario_ids.txt) with [L3-mini 20](../../scripts/fullseason/l3_mini_20_scenario_ids.txt) excluded, leaving 70 scenarios. Include runs with `return_code=0` for these scenarios from the six Agent sources, retaining different models, B/BP configurations, and reruns separately within each scenario. Freeze the specific files and score rows for each generation request, and pair workflows, reports, and scores by “source root + cell path.”

| Source | Allowed directory | Scoring material |
|---|---|---|
| DeepSeek Flash B | [l3_formal90_deepseek_flash_B_nothink_El08gq](../../validation_runs/l3_formal90_deepseek_flash_B_nothink_El08gq/) | [20261122_0x7es521 summary](../../validation_runs/l3_formal90_deepseek_flash_B_nothink_El08gq/replay_analysis_20261122_0x7es521/rebatch_fos/summary_v2_rebatch_fos.csv) |
| DeepSeek Flash BP | [l3_formal90_deepseek_flash_BP_nothink_OL0lel](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_OL0lel/) | [20261121_34tfrwwj summary](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_OL0lel/replay_analysis_20261121_34tfrwwj/rebatch_fos/summary_v2_rebatch_fos.csv) |
| DeepSeek Flash BP rerun | [l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM/) | [20261121_qmown_yo summary](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM/replay_analysis_20261121_qmown_yo/rebatch_fos/summary_v2_rebatch_fos.csv) |
| Thor Qwen B | [l3_formal90_thor_qwen35b_B_nothink_vrNWR4](../../validation_runs/l3_formal90_thor_qwen35b_B_nothink_vrNWR4/) | Runs were available in the 2026-11-23 inventory; the corresponding scoring summary was still pending |
| Thor Qwen BP | [l3_formal90_thor_qwen35b_BP_nothink_lvxtsU](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_lvxtsU/) | [20261123_ccsvhd_7 summary](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_lvxtsU/replay_analysis_20261123_ccsvhd_7/rebatch_fos/summary_v2_rebatch_fos.csv) |
| Thor Qwen BP rerun | [l3_formal90_thor_qwen35b_BP_nothink_rerun_BvciC0](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_rerun_BvciC0/) | [20261123_rxp1itc_ summary](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_rerun_BvciC0/replay_analysis_20261123_rxp1itc_/rebatch_fos/summary_v2_rebatch_fos.csv) |
| Oracle | [oracle_140_verification_20261116](../../validation_runs/oracle_140_verification_20261116/) | The execution workflow for the same scenario and the recovered yield in baselines |

**Each scenario is consistently associated with one Oracle record set.** Comparing the designated Oracle package with `oracle_time_control_20261116/advance_time_v2`, which was used for historical scoring, shows that all 70 scenarios have identical recovered yields, declared workflows, and ordered tool arguments, times, and agronomic results in actual execution. The execution records differ only in randomly generated inspection/task IDs. The two manifests contain identical hashes for all 430 source code files, and the relevant scenario, engine, and tool code was verified against the current workspace. The Oracle recovered yields in all 210 selected Agent score records also match the designated Oracle package. Therefore, for the first version, each scenario material package associates one Oracle record set and its corresponding Yield with a fixed scenario version. Historical file paths remain in the source records. [Designated Oracle manifest](../../validation_runs/oracle_140_verification_20261116/manifest.json) · [Historical reference manifest](../../validation_runs/oracle_time_control_20261116/advance_time_v2/manifest.json) · [Oracle construction entry point](../../fairy/scenarios/workflow_validation.py)

| Material package component | Original files and organized content |
|---|---|
| Base tasks `base_tasks` | Extract pure B from the corresponding version with `detailed_briefing=false`, preserving the text and its hash. Each run references its actual B; identical text may be shared |
| Agent runs `agent_runs` | Root-level `results.csv`, `*.agent_workflow.json` and `*.run_report.json` within each cell, and `*.runtime_log.jsonl` when needed. Preserve the complete sequence, calls, returns, errors, run conditions, and scores |
| Scenario Oracle `oracle` | `execution_workflows/<id>.json` and `baselines/<id>.json`; the declared `workflows/<id>.json` and `terminal_states/<id>.json` are used for cross-checking |
| Source manifest | Source identities, file/score-row locations, hashes, versions, and missing items. Preserve original content as immutable copies or references to recoverable archives |

Collect the original material in full; generation may read it in pages. Exclude P/G content in the BP opening instructions and system instructions from the generation view, pass pure B separately, and retain the original run conditions. In the 2026-11-23 material inventory, the original five sources provided 210 runs with paired scores, with 3 fully scored runs per scenario. The newly added Thor B source provided 26 non-mini runs with rc=0 and readable workflows and reports, while its scoring summary was still missing. The inventory contained 236 original runs in total. Package the actual available runs for each scenario and report gaps separately. Rescan and freeze the manifest at formal import. [Run artifact definitions](../../fairy/controllers/run_artifacts.py)

### 2. Scores and Explanations

**The first three knowledge types currently consider only recovered_yield_loss; additional metrics may be added later.** For each Agent run, `scores` currently stores the following single metric and its explanation. The run record provides the source identity and score-file location. The program generates the explanation using a fixed metric definition, supplemented with data gaps or replay issues from the reports.

| Key in scores | Subfields | Interpretation and validation |
|---|---|---|
| `recovered_yield_loss_pct` | `value`: number or null; `explanation`: string | `100 × (1 − Agent recovered yield / Oracle recovered yield)`, where lower is better. **A negative value means the Agent recovered more yield than the Oracle, which is a good result for this metric.** For example, −5% means 5% more recovered yield. Negative values are allowed and must not be clipped to 0. The metric is undefined if the denominator is missing or not greater than zero |

Store this metric as a percentage. The CSV field `recovered_yield_loss(%)` maps directly to `recovered_yield_loss_pct`; multiply the ratio in the scoring JSON field `recovered_yield_loss` by 100 before mapping it. Both recovered-yield values in kg remain in the original scoring files so that the formula can be checked during preparation. Existing JSON and CSV values are rounded, so validation uses a tolerance consistent with the stored precision. The Oracle's corresponding `recovered_yield_kg_total` is stored in kg in the scenario package. Full-season scores are associated with knowledge through source references; explanations of local causes and operational effects cite the relevant steps. [Metric formula](../../fairy/scenarios/fos/evaluation.py) · [Report precision](../../fairy/scenarios/fos/metrics.py)

`scores` remains an object extensible by metric name. Both single-run extraction and grouped consolidation receive the metrics enabled for the current version and check their availability; the currently enabled metric is `recovered_yield_loss_pct`. When adding a metric, specify its name, definition, unit, interpretation, and validation rules, and record the corresponding specification and prompt versions.

### 3. How the Data Supports the Fields in the First Table

**This section applies only to construction of the first table.** Define mapping rules for content that can be extracted directly or normalized, and judgment and writing guidelines for content requiring synthesis, explanation, or inference. Define input and output requirements separately for the four knowledge types.

#### 3.1 Identify Units First, Then Populate Common Fields for Each Entry

The Agent first reads the complete L3 material to understand the full-season task, execution order, and results. It organizes local objectives under the three farming phases, then identifies L2 units using the boundaries in Part I, Section 3. Generate knowledge separately for each unit within a phase and determine its own phenological state and farming phase. The complete material for the current source remains available for reference after the units have been identified.

| Common fields | Original content and population rules |
|---|---|
| `knowledge_version`, `source_scenario_id` | Supplied by the current construction settings and the source material package, respectively |
| `crop`, `cultivars` | Based on B and the actual crop, cultivar, and planting status of the target fields in this unit; cultivars in inventory indicate available resources only |
| `growth_stage_before` | Locate the core decision or operation, read preceding phenological evidence for the target fields, such as the state in `content.ridges[]`, and populate one state using the engine mapping |
| `farming_group` | Select establishment, management, or harvest according to the unit's primary agronomic objective |

The workflow's `name/time/depends_on` and time extension fields preserve order and dependencies. `tool_name/tool_args` and returned content help identify actions, target scope, and results. Tool names help identify agronomic objectives; determine the phenological state and farming phase separately after identifying the unit.

For example, if the material supports the following processes, one Skill generation request may produce several entries. This example illustrates granularity only; actual entries and states depend on the material.

| Focus of the Skill | farming_group | growth_stage_before |
|---|---|---|
| Sowing preparation and execution | establishment | FAIRY-Engine-NOT_PLANTED |
| Seedling-stage water assessment and irrigation | management | FAIRY-Engine-V2 |
| Addressing seedling-stage nutrient issues | management | FAIRY-Engine-V2 |
| Later-stage insect assessment and treatment | management | FAIRY-Engine-R3 |
| Maturity confirmation and harvest | harvest | FAIRY-Engine-R8 |

The number of outputs depends on the L2 units supported by the material. Each farming phase may produce several entries of the same knowledge type. In this example, V2 irrigation and V2 nutrient treatment enter the same second-stage group if all their other common fields match. They address different problems and may remain separate.

#### 3.2 Agronomic Skill

**Input: B + a single Agent workflow + that run's recovered_yield_loss and explanation.** Populate common fields for the corresponding L2 unit; the type-specific content forms a reusable method.

| Output field | Construction basis and content guidelines |
|---|---|
| `applicable_when` | Derive triggering conditions and applicability from task constraints in B, observations before the operation, and resource status |
| `pre_checks` | Use actual checks and problems exposed by insufficient checking to identify necessary checks, their purposes, and their dependency order |
| `constraints` | Derive operational constraints from explicit rules, tool limitations, resource conditions, and failure returns; values and thresholds require supporting evidence |
| `operation_template` | Organize relevant tool calls, arguments, returns, and adjustments into a method centered on one objective, explaining how parameters are determined and when to act or defer |
| `post_checks` | Explain how to verify results using completion status, actual coverage, and subsequent observations, while preserving evidence limitations where verification was incomplete |

For example, if the current material actually records “failure due to insufficient stock → replenishment → successful retry,” it may support a method that checks resource requirements and stock before an operation, replenishes when necessary, and checks the result afterward.

#### 3.3 Agronomic Reflection

**Input: B + a single Agent workflow + that run's recovered_yield_loss and explanation.** Common fields identify the local decision or operation being analyzed; the type-specific content explains a historical lesson or error.

| Output field | Construction basis and content guidelines |
|---|---|
| `success` | Set to true when the entry presents a positive lesson, or false when it identifies an error |
| `applicable_when` | State the conditions and scope under which the explanation holds, based on the relevant task, state before the operation, and constraints |
| `content` | Connect observations before the action, specific actions, returns, and subsequent changes; distinguish observed facts from causal inferences and explain the evidence and uncertainty |

For example, given supporting step-level evidence, an entry may explain: “The operation failed because stock was insufficient, and the retry succeeded after replenishment. This supports inadequate resource checking as one cause of this failure.” The entry's success is false.

#### 3.4 Agronomic Guidance

**Input: B + a single Agent workflow + that run's recovered_yield_loss and explanation.** Common fields identify the local decision context addressed by the advice; the type-specific content describes future action.

| Output field | Construction basis and content guidelines |
|---|---|
| `recommendation` | Select recommend, avoid, or conditional according to the direction of future action supported by the historical experience, consistently with the content |
| `applicable_when` | Derive the conditions required to apply the advice from the relevant task, observations, and constraints |
| `content` | Turn historical decisions and results into actions to take, avoid, or defer in the future, specifying what to check first and which conditions permit action |

For example, when supported by evidence, an entry may advise: “Check the resource requirements for this operation against available stock beforehand; replenish first if stock is insufficient.” It may be classified as conditional when the conditional branches are explicit.

The first three types currently consider only recovered_yield_loss, with additional metrics possible later. It provides full-season result context; local operational effects, the direction of lessons, and causal judgments depend on evidence from the relevant steps.

#### 3.5 Agronomic Observation

**Input: B + one actual Oracle execution record + the corresponding replay Yield.** Common fields describe the target crop's state before the recorded process and its agronomic objective; the type-specific content records what occurred.

| Output field | Construction basis and content guidelines |
|---|---|
| `applicable_constraints` | Use B, the actual state before the operation, and equipment and resource limitations; distinguish conditions present during the process from necessary constraints supported by evidence |
| `procedure[].action` | Record actions according to execution order, tool arguments, and target scope, retaining necessary times, parameters, and units |
| `procedure[].observed_result` | Faithfully record tool returns, actual completion scope, errors, partial outcomes, and subsequent records; use null when the result was not recorded |

For example, if the execution record contains “check stock → replenish → execute the operation,” record the corresponding actions and returns in order, without adding unrecorded checks. State the respective scopes of local operational results and full-season recovered yield.

## III. Stepwise Database Construction: Inputs, Outputs, Prompts, Content Guidance, and Constraints

**TODO: Design specific prompts and read/write implementations after the source materials, fields of both tables, and content specifications for the four types have been confirmed.** The input/output boundaries of the following two steps are currently established.

| Step | Input | Processing and content constraints | Output |
|---|---|---|---|
| Step 1: Build initial knowledge | Materials from one Agent or Oracle source, plus the field specification for the corresponding type | Read the complete L3 record, identify L2 units, determine common fields for each entry, and generate its type-specific content; add entries based on the current source | New entries in the first table, source evidence, and descriptions of material gaps |
| Step 2: Calibrate and consolidate | A group of entries from the first table with the same knowledge type and exactly equal common fields, together with their linked evidence | Inherit the group's common fields; use specific objectives, type-specific conditions, and content to decide whether to merge, retain separately, or handle conflicts | Consolidated knowledge in the second table, with explanations of merges, conflicts, and content removal |

Input examples, output examples, and content guidance will be designed separately for the four types. The number of distinct prompts will be determined during calibration. Priorities are:

1. How to identify L2 units in L3 materials and determine pre-operation phenological states and farming phases for individual entries.
2. Complete input packages, structured outputs, prompts, evidence requirements, and missing-information handling for each type.
3. Rules for merging, retaining separate entries, resolving conflicts, and removing content within a group, and for correcting misassigned common fields.
4. JSON validation and fixed SQLite read/write functions; rules for addition, revision, withdrawal, version inheritance, and publication; and necessary checks and error reporting.

SQLite and JSON retain their agreed roles: the Agent produces structured JSON, and fixed functions write it to the database after review and validation. Specific operation enums, function signatures, transactions, and version protocols remain to be designed. Task retrieval and loading into G remain TODOs; the agreed task query uses only the scenario's base task description B.

Initially, the user reviews materials, fields, initial knowledge, and consolidation results, focusing on source pairing, L2 unit boundaries, single-value labels, evidence, and conflict handling. Responsibilities are gradually delegated to the Agent after small-sample calibration succeeds. Subsequent batches retain the original formal90 order with mini20 excluded: freeze batches of 20/20/20/10 new scenarios, reaching cumulative coverage of 20/40/60/70. Each batch may add sources and correct earlier knowledge. Record initial-entry counts and consolidated additions, revisions, withdrawals, retained entries, and items awaiting completion separately. Knowledge versions and batches are recorded separately. Effectiveness on mini20 will be evaluated once retrieval using B alone and loading into G are available.

### Original Library Modes

Default G, `reusable_operational_guidelines`, and legacy library modes are managed independently. The four new knowledge types are built from the sources and generation flow defined here. For the data sources, parameters, and map compatibility of legacy modes, see [the existing instructions for replacing G with library content](../README.md).
