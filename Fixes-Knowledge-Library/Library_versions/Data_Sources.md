# FAIRY 数据来源清单与字段映射示例

核查日期为 2026-11-23。范围以用户指定的 [formal_70_scenario_ids.txt](../../scripts/fullseason/formal_70_scenario_ids.txt) 为准，共 70 个唯一场景 ID。知识字段沿用[知识库设计](README.md)。第一步登记文件和评分记录是否存在，第二步读取一个场景，说明哪些内容能够支撑四类知识。

## 一、来源是否存在与如何定位

### 1. Agent 来源

五个来源目录及各自的 `results.csv` 均存在。按 70 场景清单和 `return_code=0` 筛选，共 210 次运行，全部找到工作流、运行报告和运行日志。210 次运行均已找到配对评分及两项分数，本次补齐了 Thor BP rerun 的 20 次评分。

| 来源 | 根目录 | results.csv 存在 | rc=0 运行数 | 工作流 / 报告 / 日志存在数 | 配对评分行存在数与位置 |
|---|---|---|---:|---|---|
| DeepSeek B | [运行目录](../../validation_runs/l3_formal90_deepseek_flash_B_nothink_El08gq/) | 是 | 70 | 70 / 70 / 70 | 70，[评分汇总](../../validation_runs/l3_formal90_deepseek_flash_B_nothink_El08gq/replay_analysis_20261122_0x7es521/rebatch_fos/summary_v2_rebatch_fos.csv) |
| DeepSeek BP | [运行目录](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_OL0lel/) | 是 | 56 | 56 / 56 / 56 | 56，[评分汇总](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_OL0lel/replay_analysis_20261121_34tfrwwj/rebatch_fos/summary_v2_rebatch_fos.csv) |
| DeepSeek BP rerun | [运行目录](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM/) | 是 | 14 | 14 / 14 / 14 | 14，[评分汇总](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM/replay_analysis_20261121_qmown_yo/rebatch_fos/summary_v2_rebatch_fos.csv) |
| Thor BP | [运行目录](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_lvxtsU/) | 是 | 50 | 50 / 50 / 50 | 50，[评分汇总](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_lvxtsU/replay_analysis_20261123_ccsvhd_7/rebatch_fos/summary_v2_rebatch_fos.csv) |
| Thor BP rerun | [运行目录](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_rerun_BvciC0/) | 是 | 20 | 20 / 20 / 20 | 20，[评分汇总](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_rerun_BvciC0/replay_analysis_20261123_rxp1itc_/rebatch_fos/summary_v2_rebatch_fos.csv) |

本次纳入的运行均为 `farm_baseline_react`、`r1`。给定场景 ID，可按以下规则从对应根目录定位文件。

| 材料 | 根目录内的相对位置 | 用途 |
|---|---|---|
| 运行登记 | `results.csv` | 找到场景、cell、repeat 和 return_code |
| 工作流 | `farm_baseline_react__<scenario_id>__r1/<scenario_id>.agent_workflow.json` | 原始任务、调用、参数、返回和先后关系 |
| 运行报告 | 同一 cell 下 `<scenario_id>.run_report.json` | 场景、模型、运行配置和结束情况 |
| 运行日志 | 同一 cell 下 `<scenario_id>.runtime_log.jsonl` | 按需补查执行记录 |
| 评分 | 上表指定汇总中 `scenario=<scenario_id>` 且 `cell` 与该运行一致的行 | 读取 `recovered_yield_loss(%)` 和 `ktc(%)` |

五份选定汇总中，210 次纳入运行都能唯一找到对应行，两项分数均有值。DeepSeek BP 沿用已指定的 `20261121_34tfrwwj`。Thor BP 改用本次补充的 `20261123_ccsvhd_7`，其场景／cell 集合及两项分数与旧汇总一致。Thor BP rerun 使用新增的 `20261123_rxp1itc_`。逐场景分布见文末清单。“存在”在此表示文件或记录已找到。

### 2. 基础任务 B 与 Oracle 来源

**纯 B 已有直接来源。** DeepSeek B 的 70 份工作流均有非空 `step0` USER 正文，对应运行报告均为 `detailed_briefing="structured_true"`、`components=[]`。可以从这些实际运行记录读取基础任务。其他运行的 B 仍应依据各自配置和正文确认。

Oracle 根目录为 [oracle_140_verification_20261116](../../validation_runs/oracle_140_verification_20261116/)，存在情况如下。

| 材料 | 根目录内的位置 | 存在情况 |
|---|---|---|
| 声明的 Oracle 流程 | `workflows/<scenario_id>.json` | 70 / 70 |
| Oracle 实际执行及返回 | `execution_workflows/<scenario_id>.json` | 70 / 70 |
| 配套回放产量 | `baselines/<scenario_id>.json` | 70 / 70 |
| 终态 | `terminal_states/<scenario_id>.json` | 70 / 70 |
| 来源清单与验证摘要 | `manifest.json`、`verification_summary.json` | 两份均存在 |

至此，70 个场景都有纯 B 来源和完整的 Oracle 文件集合，每个场景均有 3 次包含工作流、报告、日志和两项分数的 Agent 运行，分别来自 DeepSeek B、DeepSeek BP 主跑／重跑和 Thor BP 主跑／重跑。当前清单中的 210 次合资格运行均已配齐上述材料。

## 二、以一个场景说明字段映射

### 1. 选用材料及其可用内容

选用 `scenario_full_season_hb_storage_capacity_limit_batching`，它在正式 70 清单第 23 行。前三类知识以 **DeepSeek B、r1** 为例，Observation 使用同场景 Oracle。材料仍按完整场景组织，下面用“有限粮箱容量下的分批收获”说明字段如何形成。

| 材料 | 可核查位置 | 本例可用内容 |
|---|---|---|
| [Agent 工作流](../../validation_runs/l3_formal90_deepseek_flash_B_nothink_El08gq/farm_baseline_react__scenario_full_season_hb_storage_capacity_limit_batching__r1/scenario_full_season_hb_storage_capacity_limit_batching.agent_workflow.json) | `step0` | B 明示黑农84标准密度大豆、最多 64 垄、粮食处理容量有限，以及全季管理任务 |
| 同一工作流 | `step75`、`step82` | 前者查询 0–63 垄，目标 12–15 垄为 HEINONG84、R8；后者查询农机状态，粮箱上限 2,000 kg |
| 同一工作流 | `step117` → `step120` | 粮箱已有载荷 → 继续收获被容量检查拒绝 → 卸粮 → 同垄重试成功 |
| [Agent 运行报告](../../validation_runs/l3_formal90_deepseek_flash_B_nothink_El08gq/farm_baseline_react__scenario_full_season_hb_storage_capacity_limit_batching__r1/scenario_full_season_hb_storage_capacity_limit_batching.run_report.json) | `scenario_id`、`scenario_kwargs`、`status`、`stopped_reason` | 确认来源场景、B 配置及 `completed / agent_finished` |
| [Agent 评分汇总](../../validation_runs/l3_formal90_deepseek_flash_B_nothink_El08gq/replay_analysis_20261122_0x7es521/rebatch_fos/summary_v2_rebatch_fos.csv) | 第 74 行，同场景和 cell | `recovered_yield_loss(%)=13.58`，`ktc(%)=92.54` |
| [Oracle 执行流程](../../validation_runs/oracle_140_verification_20261116/execution_workflows/scenario_full_season_hb_storage_capacity_limit_batching.json) | `o_west_0_31_harvest_range_state`、`o_west_0_31_harvest_0_3`、`o_west_0_31_unload_after_3` | 操作前品种、阶段与水分，以及收获和卸粮的实际结果 |
| [Oracle 配套产量](../../validation_runs/oracle_140_verification_20261116/baselines/scenario_full_season_hb_storage_capacity_limit_batching.json) | 顶层 `recovered_yield_kg_total` | 全季回收 8,301.70 kg |

Agent 的局部证据链如下，各值来自工具返回。

| 步骤 | 实际请求或返回 |
|---|---|
| `step117` | 收获 8–11 垄后，`grain_bin_kg=1345.4`，`grain_bin_max_kg=2000` |
| `step118` | 请求收获 12–15 垄。工具按预计新增 980 kg 检查容量，返回 `Grain bin would overflow` 并要求先卸粮 |
| `step119` | `unload_grain` 返回卸出 1,345.36 kg，`grain_bin_kg=0` |
| `step120` | 重试收获 12–15 垄成功，`harvested_ridges=[12,13,14,15]`，`grain_kg_added=448.39` |

Oracle 的对应过程先确认 0–31 垄为 HEINONG84、R8，其中 0–3 垄籽粒水分为 17.23%，随后收获 0–3 垄得到 518.99 kg，再卸出 518.99 kg，粮箱归零。Agent 和 Oracle 各自的事件、参数和结果保留在各自来源下。

### 2. 公共字段从哪里来

| 知识字段 | 本例可填写的值 | 来源与抽象方式 |
|---|---|---|
| `source_scenario_id` | `scenario_full_season_hb_storage_capacity_limit_batching` | 清单、运行报告及 Oracle 文件身份 |
| `crop` | `soybean` | B 明示“大豆” |
| `cultivars` | `["HEINONG84"]` | B 明示黑农84，Agent `step75` 和 Oracle 田块返回再次确认 |
| `growth_stages_before` | `["FAIRY-Engine-R8"]` | Agent `step75` 的目标垄及 Oracle 收获前状态支持 R8，映射为规范标签 |
| `farming_group` | `harvest` | 本例聚焦连续收获和卸粮 |
| `task_types` | `["harvest"]` | 对照 README 候选词表，容量约束写入该操作的正文 |
| `release_id`、`knowledge_id`、`revision` | 入库／发布时分配 | 程序生成的管理信息 |
| 证据引用 | 来源运行＋步骤／字段位置 | 保留支撑各标签和主张的原始位置 |

`step75` 是目标垄此前的 R8 观测，距本例实际收获约 31 天，此后至 `step118` 没有补种或物候重置记录。引用时保留这一时点。较晚的 `step113` 只检查垄 0，其籽粒水分不能作为 12–15 垄的实测值。

### 3. 四类私有字段如何形成

以下内容用于说明“源内容能够支撑什么”，作为后续 prompt 的映射样例。

| 类型／字段 | 可用证据 | 可抽象出的内容 |
|---|---|---|
| Skill `applicable_when` | B 的容量限制，`step117` 已有载荷 | 连续分批收获，粮箱已有粮食且下一批作业受容量限制 |
| Skill `pre_checks` | `step82` 容量，`step117` 载荷，`step118` 拒绝原因 | 先读取已装量和上限，再核对计划收获批次的容量需求，决定是否先卸粮 |
| Skill `constraints` | `step118` 的容量检查 | 下一批作业须满足设备容量要求。2,000 kg 保留为本次设备实例值，模板读取当前设备上限 |
| Skill `operation_template` | `step119` 卸粮，`step120` 同垄重试 | 空间不足时先卸粮、确认粮箱释放容量，再执行目标批次收获 |
| Skill `post_checks` | `grain_bin_kg`、`harvested_ridges`、`grain_kg_added` | 核对卸粮后的载荷、实际收获垄和进粮量，确认本批完成 |
| Reflection `success` | `step118` 的错误与随后恢复 | `false`，该条解释指出一次容量安排错误 |
| Reflection `applicable_when`、`content` | `step117` 至 `step120` | 在连续收获已有载荷时，继续收获触发容量拒绝；卸粮后同垄操作成功，支持将此次中断归因于可用容量不足 |
| Guidance `recommendation` | 容量条件决定卸粮或继续收获 | `conditional` |
| Guidance `applicable_when`、`content` | B 的容量背景、错误及恢复过程 | 连续收获前核对当前余量与下一批需求；超过余量时先卸粮，再继续目标垄段 |
| Observation `applicable_constraints` | Oracle 收获前状态及收获返回 | HEINONG84、R8、目标 0–3 垄水分 17.23%、设备粮箱上限 2,000 kg |
| Observation `procedure` | Oracle 的三个有序事件 | 检查目标田块 → 收获 0–3 垄，得到 518.99 kg → 卸出 518.99 kg，粮箱归零；关联配套全季回收 8,301.70 kg |

前三类知识都关联这次 Agent 的两项分数及解释。13.58% 表示相对 Oracle 的整季回收损失率，92.54% 表示已匹配动作的相对顺序分数。损失率允许为负，负值表示 Agent 回收量超过 Oracle。局部容量错误的解释依据 `step117` 至 `step120`，整季 13.58% 无法据此分摊给该错误。

本例中的 980 kg 是工具拒绝操作时使用的预计值，448.39 kg 是重试的实际收获量。记录支持“容量检查拒绝并在卸粮后恢复”，实际溢粮损失没有在这段返回中发生。粮箱容量与 B 提到的粮食处理／仓储容量分别依实际字段描述。

四类内容所需的事实材料均有对应来源。Skill 的方法、Reflection 的原因和 Guidance 的未来建议需要 prompt 归纳和写作，Observation 根据实际事件整理。这些候选内容及其适用范围由用户在初版审阅中判断。

## 附录：70 个场景逐项存在清单

场景列省略统一前缀 `scenario_full_season_`，序号对应正式清单行号。**齐**表示存在该来源的 rc=0 运行，且工作流、报告、日志、配对评分行及两项分数都已找到。**无**表示该来源没有纳入范围的 rc=0 运行记录。全部 70 行的纯 B 及四类 Oracle 文件均存在。

| 清单行 | 场景后缀 | DeepSeek B | DeepSeek BP | DeepSeek BP rerun | Thor BP | Thor BP rerun |
|---:|---|---|---|---|---|---|
| 1 | `heinong60_high_density_baseline` | 齐 | 齐 | 无 | 齐 | 无 |
| 2 | `wet_june_ab_zoned_disease` | 齐 | 齐 | 无 | 齐 | 无 |
| 3 | `fastdraining_dry_patch_irrigation` | 齐 | 齐 | 无 | 齐 | 无 |
| 4 | `heinong84_staggered_planting` | 齐 | 齐 | 无 | 齐 | 无 |
| 5 | `heinong84_threshold_insect_limited_spray` | 齐 | 齐 | 无 | 齐 | 无 |
| 6 | `heinong84_low_chemical_wet_disease` | 齐 | 齐 | 无 | 齐 | 无 |
| 7 | `early_vs_standard_late_rain_harvest` | 齐 | 齐 | 无 | 齐 | 无 |
| 8 | `hb_base_hn84_std_normal` | 齐 | 齐 | 无 | 齐 | 无 |
| 9 | `hb_coldspring_planting_window_heihe50` | 齐 | 齐 | 无 | 齐 | 无 |
| 10 | `hb_low_nutrient_carryover_flowering_nutrition` | 齐 | 齐 | 无 | 齐 | 无 |
| 11 | `hb_high_weed_seedbank_mechanical_only_baseline` | 齐 | 齐 | 无 | 齐 | 无 |
| 12 | `hb_wetjune_short_spray_window` | 齐 | 齐 | 无 | 齐 | 无 |
| 13 | `hb_r5_leaf_feeder_defoliation` | 齐 | 齐 | 无 | 齐 | 无 |
| 14 | `hb_limited_spray_budget_season` | 齐 | 齐 | 无 | 齐 | 无 |
| 15 | `hb_dryr5r6_hn84_water_limit` | 齐 | 齐 | 无 | 齐 | 无 |
| 16 | `hb_hn60_high_dryr5r6_water_demand` | 齐 | 齐 | 无 | 齐 | 无 |
| 17 | `hb_two_dry_patches_one_irrigation` | 齐 | 齐 | 无 | 齐 | 无 |
| 18 | `hb_staggered_dryr5r6_stage_mismatch` | 齐 | 齐 | 无 | 齐 | 无 |
| 19 | `hb_hn60_high_late_grain_moisture` | 齐 | 齐 | 无 | 齐 | 无 |
| 20 | `hb_harvester_days_limit_laterain` | 齐 | 齐 | 无 | 齐 | 无 |
| 21 | `hb_adversarial_multi_event_light` | 齐 | 齐 | 无 | 齐 | 无 |
| 22 | `hb_wetcold_high_residue_establishment` | 齐 | 齐 | 无 | 齐 | 无 |
| 23 | `hb_storage_capacity_limit_batching` | 齐 | 齐 | 无 | 齐 | 无 |
| 24 | `hb_low_carbon_min_machinery_passes` | 齐 | 齐 | 无 | 齐 | 无 |
| 25 | `hb_coldspring_lateplanting_laterain_hn50` | 齐 | 齐 | 无 | 齐 | 无 |
| 26 | `hb_wetjune_highdensity_poordrainage_disease` | 齐 | 齐 | 无 | 齐 | 无 |
| 27 | `hb_wetjune_soyhistory_poordrainage_disease` | 齐 | 齐 | 无 | 齐 | 无 |
| 28 | `hb_wetjune_weed_disease_diagnosis` | 齐 | 齐 | 无 | 齐 | 无 |
| 29 | `hb_highdensity_wetjune_limited_fungicide` | 齐 | 齐 | 无 | 齐 | 无 |
| 30 | `hb_wetjune_shortwindow_trafficability` | 齐 | 齐 | 无 | 齐 | 无 |
| 31 | `hb_hn84_hn58_dry_patch_waterlimit` | 齐 | 齐 | 无 | 齐 | 无 |
| 32 | `hb_heatdry_aphid_limitedspray_waterlimit` | 齐 | 齐 | 无 | 齐 | 无 |
| 33 | `hb_lowdensity_weed_dry_competition` | 齐 | 齐 | 无 | 齐 | 无 |
| 34 | `hb_hn84_hn58_weed_mechanical_allocation` | 齐 | 齐 | 无 | 齐 | 无 |
| 35 | `hb_lowcarbon_batch_operations_wetdisease` | 齐 | 齐 | 无 | 齐 | 无 |
| 36 | `hb_density_gradient_wetdry` | 齐 | 齐 | 无 | 齐 | 无 |
| 37 | `hb_fertilizer_quota_edge_lowfertility` | 齐 | 齐 | 无 | 齐 | 无 |
| 38 | `hb_insect_after_fungicide_budget_conflict` | 齐 | 齐 | 无 | 齐 | 无 |
| 39 | `hb_disease_then_drought_recovery_tradeoff` | 齐 | 齐 | 无 | 齐 | 无 |
| 40 | `hb_weed_then_disease_canopy_confusion` | 齐 | 齐 | 无 | 齐 | 无 |
| 41 | `hb_lowinput_waterlimited_weed_pressure` | 齐 | 齐 | 无 | 齐 | 无 |
| 42 | `hb_planter_skip_rows_stand_gap` | 齐 | 齐 | 无 | 齐 | 无 |
| 43 | `hb_replant_after_crusting_short_season` | 齐 | 齐 | 无 | 齐 | 无 |
| 44 | `hb_fertilizer_misapplication_strip_recovery` | 齐 | 齐 | 无 | 齐 | 无 |
| 45 | `hb_nutrient_vs_disease_leafcolor_diagnosis` | 齐 | 齐 | 无 | 齐 | 无 |
| 46 | `hb_weed_green_ndvi_masked_drought` | 齐 | 齐 | 无 | 齐 | 无 |
| 47 | `hb_herbicide_window_missed_rain_delay` | 齐 | 齐 | 无 | 齐 | 无 |
| 48 | `hb_mechanical_weed_trafficability_window` | 齐 | 齐 | 无 | 齐 | 无 |
| 49 | `hb_leaffeeder_vs_disease_spots_diagnosis` | 齐 | 齐 | 无 | 齐 | 无 |
| 50 | `hb_wetjune_disease_recheck_after_fungicide` | 齐 | 齐 | 无 | 齐 | 无 |
| 51 | `hb_r5_heat_stress_without_soil_drought` | 齐 | 齐 | 无 | 无 | 齐 |
| 52 | `hb_split_irrigation_schedule_power_limit` | 齐 | 齐 | 无 | 无 | 齐 |
| 53 | `hb_fuel_limit_irrigation_harvest_ops` | 齐 | 齐 | 无 | 无 | 齐 |
| 54 | `hb_market_discount_high_moisture_delivery` | 齐 | 齐 | 无 | 无 | 齐 |
| 55 | `hb_split_quality_batches_late_disease` | 齐 | 齐 | 无 | 无 | 齐 |
| 56 | `hb_rhizobia_nodulation_failure_nutrition` | 齐 | 齐 | 无 | 无 | 齐 |
| 57 | `hb_potassium_deficit_dry_podfill_interaction` | 齐 | 无 | 齐 | 无 | 齐 |
| 58 | `hb_overfertilized_dense_canopy_disease_risk` | 齐 | 无 | 齐 | 无 | 齐 |
| 59 | `hb_laterain_insect_risk` | 齐 | 无 | 齐 | 无 | 齐 |
| 60 | `hb_coolwet_flowering_disease_risk` | 齐 | 无 | 齐 | 无 | 齐 |
| 61 | `hb_storage_aeration_failure_after_harvest` | 齐 | 无 | 齐 | 无 | 齐 |
| 62 | `hb_dryer_breakdown_between_batches` | 齐 | 无 | 齐 | 无 | 齐 |
| 63 | `hb_heinong58_drought_insect_diagnosis_waterlimit` | 齐 | 无 | 齐 | 无 | 齐 |
| 64 | `hb_heinong60_highdensity_wetjune_weed_disease` | 齐 | 无 | 齐 | 无 | 齐 |
| 65 | `hb_heike71_lateplanting_laterain_highmoisture_quality` | 齐 | 无 | 齐 | 无 | 齐 |
| 66 | `hb_heihe43_early_density_weed_nutrient_recovery` | 齐 | 无 | 齐 | 无 | 齐 |
| 67 | `hb_three_cultivar_wet_disease_dry_harvest_sequence` | 齐 | 无 | 齐 | 无 | 齐 |
| 68 | `hb_heinong60_highdensity_fertigation_irrigation_water_budget` | 齐 | 无 | 齐 | 无 | 齐 |
| 69 | `hb_hn84_hn58_low_chemical_disease_insect_budget` | 齐 | 无 | 齐 | 无 | 齐 |
| 70 | `hb_heinong58_water_chemical_priority_under_dual_stress` | 齐 | 无 | 齐 | 无 | 齐 |
