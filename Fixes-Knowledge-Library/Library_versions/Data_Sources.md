# FAIRY 知识库数据源

本文记录原始数据的来源、数量、内容和使用边界，供用户审核。知识字段沿用[知识库设计](README.md)。后续验证范围为 [l3_skill_source_ids.txt](../../scripts/fullseason/l3_skill_source_ids.txt) 中的 20 个场景；具体整理方式与执行均待用户审核。

**2026-11-23 文本盘点：** 在 [formal_70_scenario_ids.txt](../../scripts/fullseason/formal_70_scenario_ids.txt) 的 70 个场景范围内，六个来源共有 **243 次 rc=0 Agent 运行**，其中 210 次评分齐备、33 次 Thor B 待评分；另有 70 套 Oracle。正式 70 清单与 formal90 排除 mini20 后的内容、顺序一致。运行目录仍可能新增结果，以下数量是本次盘点值，并非冻结材料包。

## 一、来源是否存在与如何定位

### 1. Agent 来源

六个来源目录及各自的 `results.csv` 均存在。按 70 场景清单和 `return_code=0` 筛选，243 次运行的工作流、运行报告和运行日志均存在；其中 210 次在下列显式选定的汇总中找到唯一配对评分。日志用于按需补查执行过程，基础提炼材料优先使用工作流、运行报告及评分。

| 来源 | 根目录 | results.csv 存在 | rc=0 运行数 | 工作流 / 报告 / 日志存在数 | 配对评分行存在数与位置 |
|---|---|---|---:|---|---|
| DeepSeek B | [运行目录](../../validation_runs/l3_formal90_deepseek_flash_B_nothink_El08gq/) | 是 | 70 | 70 / 70 / 70 | 70，[评分汇总](../../validation_runs/l3_formal90_deepseek_flash_B_nothink_El08gq/replay_analysis_20261122_0x7es521/rebatch_fos/summary_v2_rebatch_fos.csv) |
| DeepSeek BP | [运行目录](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_OL0lel/) | 是 | 56 | 56 / 56 / 56 | 56，[评分汇总](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_OL0lel/replay_analysis_20261121_34tfrwwj/rebatch_fos/summary_v2_rebatch_fos.csv) |
| DeepSeek BP rerun | [运行目录](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM/) | 是 | 14 | 14 / 14 / 14 | 14，[评分汇总](../../validation_runs/l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM/replay_analysis_20261121_qmown_yo/rebatch_fos/summary_v2_rebatch_fos.csv) |
| Thor B | [运行目录](../../validation_runs/l3_formal90_thor_qwen35b_B_nothink_vrNWR4/) | 是 | 33 | 33 / 33 / 33 | 尚未发现配套汇总，待补评分 |
| Thor BP | [运行目录](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_lvxtsU/) | 是 | 50 | 50 / 50 / 50 | 50，[评分汇总](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_lvxtsU/replay_analysis_20261123_ccsvhd_7/rebatch_fos/summary_v2_rebatch_fos.csv) |
| Thor BP rerun | [运行目录](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_rerun_BvciC0/) | 是 | 20 | 20 / 20 / 20 | 20，[评分汇总](../../validation_runs/l3_formal90_thor_qwen35b_BP_nothink_rerun_BvciC0/replay_analysis_20261123_rxp1itc_/rebatch_fos/summary_v2_rebatch_fos.csv) |

本次统计的运行均为 `farm_baseline_react`、`r1`。给定场景 ID，可按以下规则从对应根目录定位文件。

| 材料 | 根目录内的相对位置 | 用途 |
|---|---|---|
| 运行登记 | `results.csv` | 找到场景、cell、repeat 和 return_code |
| 工作流 | `farm_baseline_react__<scenario_id>__r1/<scenario_id>.agent_workflow.json` | 原始任务、调用、参数、返回和先后关系 |
| 运行报告 | 同一 cell 下 `<scenario_id>.run_report.json` | 场景、模型、运行配置和结束情况 |
| 运行日志 | 同一 cell 下 `<scenario_id>.runtime_log.jsonl` | 按需补查执行记录 |
| 评分 | 上表指定汇总中 `scenario=<scenario_id>` 且 `cell` 与该运行一致的行 | 读取 `recovered_yield_loss(%)` 和 `ktc(%)` |

五份选定汇总中，210 次纳入运行的两项分数均为有限数值，`status=ok`，评分中的 Oracle 回收量与指定 Oracle 包逐项一致。评分应按 `(scenario, cell)` 配对，同场景不同来源或重跑分别保留，评分汇总须明确指定。33 次 Thor B 已有工作流和报告，但尚缺配对评分，补齐前不足以提供前三类知识要求的完整输入。`return_code=0` 只用于筛选运行，不等同于任务成功或知识方向为正向。

### 2. 基础任务 B 与 Oracle 来源

**纯 B 可从场景源码读取，并与实际运行交叉校验。** 已核查源码中的 `briefing_text` 字符串可通过 Python AST 读取，无需导入或运行场景：62 个来自 [harbin_l3_batch_catalog.py](../../fairy/scenarios/farm_world_fullseason_v2/harbin_l3_batch_catalog.py) 的 `ScenarioSpec`，8 个来自各自场景模块。涉及 9 个源码文件，哈希全部与 Oracle manifest 的对应记录一致。

前次核查的 241 次 Agent 运行均可从首条 USER 正文提取自己的 B：B 模式保留全文，BP 去掉独立 P/G 标签块；保留 B 的原始空白，核对报告中的 `briefing_text`、`briefing_sha256`、`base_sha256`，再与源码 B 比较。上述核查全部通过，同场景 B 一致。本次新增的 2 次 Thor B 仅计入文件完整性统计，正式使用前仍需完成相同核验。来源可定位到场景源码及实际工作流，后续整理时应保留这些位置。

Oracle 根目录为 [oracle_140_verification_20261116](../../validation_runs/oracle_140_verification_20261116/)，存在情况如下。

| 材料 | 根目录内的位置 | 存在情况 |
|---|---|---|
| 声明的 Oracle 流程 | `workflows/<scenario_id>.json` | 70 / 70 |
| Oracle 实际执行及返回 | `execution_workflows/<scenario_id>.json` | 70 / 70 |
| 配套回放产量 | `baselines/<scenario_id>.json` | 70 / 70 |
| 终态 | `terminal_states/<scenario_id>.json` | 70 / 70 |
| 来源清单与验证摘要 | `manifest.json`、`verification_summary.json` | 两份均存在 |

70 套 Oracle 的上述四类文件均通过 manifest 中的产物哈希校验。Observation 使用**实际执行及返回**与配套回放量，声明流程、终态和 manifest 留作核对。当前记录是 `simulated_oracle_replay`，不能称为真实农场实测。

Oracle 的首条 `briefing` 是详细计划，且 `op_type` 为 null，不能当作纯 B。后续整理时应将基础任务与通信／计划内容分开：单独提供纯 B，农事流程使用真实工具调用及返回，P/G 或开场详细计划不作为已执行的农事证据。保留原事件 ID、参数、返回、错误、partial、时间和依赖，原始文件留作核对。

## 二、后续小范围验证与审核边界

后续拟仅处理 [l3_skill_source_ids.txt](../../scripts/fullseason/l3_skill_source_ids.txt) 中的 **20 个场景**，该清单属于上述 70 场景集合，与 L3-mini 20 不重叠。70 场景统计用于说明原始数据覆盖范围，不代表本轮需要全量整理。

按当前原始登记，这 20 个场景共有 **68 次 rc=0 Agent 运行**：DeepSeek B 20 次、DeepSeek BP 14 次、其 rerun 6 次、Thor B 8 次、Thor BP 14 次、其 rerun 6 次。其中 60 次评分齐备，8 次 Thor B 待评分；另有 20 套 Oracle 文件。每个场景的不同运行分别保留。

待用户审核后，再决定小范围验证需要怎样的材料组织方式、是否编写整理代码或 skill，以及如何运行。当前不生成材料包、候选知识或正式知识，也不执行这 20 个场景的处理。

## 附录：70 个场景逐项存在清单

场景列省略统一前缀 `scenario_full_season_`，序号对应正式清单行号。**齐**表示存在该来源的 rc=0 运行，且工作流、报告、日志、配对评分行及两项分数都已找到。**待**表示工作流、报告和日志存在，但尚缺配对评分。**无**表示该来源没有纳入范围的 rc=0 运行记录。全部 70 行的纯 B 及四类 Oracle 文件均存在。

| 清单行 | 场景后缀 | DeepSeek B | DeepSeek BP | DeepSeek BP rerun | Thor B | Thor BP | Thor BP rerun |
|---:|---|---|---|---|---|---|---|
| 1 | `heinong60_high_density_baseline` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 2 | `wet_june_ab_zoned_disease` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 3 | `fastdraining_dry_patch_irrigation` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 4 | `heinong84_staggered_planting` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 5 | `heinong84_threshold_insect_limited_spray` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 6 | `heinong84_low_chemical_wet_disease` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 7 | `early_vs_standard_late_rain_harvest` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 8 | `hb_base_hn84_std_normal` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 9 | `hb_coldspring_planting_window_heihe50` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 10 | `hb_low_nutrient_carryover_flowering_nutrition` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 11 | `hb_high_weed_seedbank_mechanical_only_baseline` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 12 | `hb_wetjune_short_spray_window` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 13 | `hb_r5_leaf_feeder_defoliation` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 14 | `hb_limited_spray_budget_season` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 15 | `hb_dryr5r6_hn84_water_limit` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 16 | `hb_hn60_high_dryr5r6_water_demand` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 17 | `hb_two_dry_patches_one_irrigation` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 18 | `hb_staggered_dryr5r6_stage_mismatch` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 19 | `hb_hn60_high_late_grain_moisture` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 20 | `hb_harvester_days_limit_laterain` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 21 | `hb_adversarial_multi_event_light` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 22 | `hb_wetcold_high_residue_establishment` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 23 | `hb_storage_capacity_limit_batching` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 24 | `hb_low_carbon_min_machinery_passes` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 25 | `hb_coldspring_lateplanting_laterain_hn50` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 26 | `hb_wetjune_highdensity_poordrainage_disease` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 27 | `hb_wetjune_soyhistory_poordrainage_disease` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 28 | `hb_wetjune_weed_disease_diagnosis` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 29 | `hb_highdensity_wetjune_limited_fungicide` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 30 | `hb_wetjune_shortwindow_trafficability` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 31 | `hb_hn84_hn58_dry_patch_waterlimit` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 32 | `hb_heatdry_aphid_limitedspray_waterlimit` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 33 | `hb_lowdensity_weed_dry_competition` | 齐 | 齐 | 无 | 待 | 齐 | 无 |
| 34 | `hb_hn84_hn58_weed_mechanical_allocation` | 齐 | 齐 | 无 | 无 | 齐 | 无 |
| 35 | `hb_lowcarbon_batch_operations_wetdisease` | 齐 | 齐 | 无 | 无 | 齐 | 无 |
| 36 | `hb_density_gradient_wetdry` | 齐 | 齐 | 无 | 无 | 齐 | 无 |
| 37 | `hb_fertilizer_quota_edge_lowfertility` | 齐 | 齐 | 无 | 无 | 齐 | 无 |
| 38 | `hb_insect_after_fungicide_budget_conflict` | 齐 | 齐 | 无 | 无 | 齐 | 无 |
| 39 | `hb_disease_then_drought_recovery_tradeoff` | 齐 | 齐 | 无 | 无 | 齐 | 无 |
| 40 | `hb_weed_then_disease_canopy_confusion` | 齐 | 齐 | 无 | 无 | 齐 | 无 |
| 41 | `hb_lowinput_waterlimited_weed_pressure` | 齐 | 齐 | 无 | 无 | 齐 | 无 |
| 42 | `hb_planter_skip_rows_stand_gap` | 齐 | 齐 | 无 | 无 | 齐 | 无 |
| 43 | `hb_replant_after_crusting_short_season` | 齐 | 齐 | 无 | 无 | 齐 | 无 |
| 44 | `hb_fertilizer_misapplication_strip_recovery` | 齐 | 齐 | 无 | 无 | 齐 | 无 |
| 45 | `hb_nutrient_vs_disease_leafcolor_diagnosis` | 齐 | 齐 | 无 | 无 | 齐 | 无 |
| 46 | `hb_weed_green_ndvi_masked_drought` | 齐 | 齐 | 无 | 无 | 齐 | 无 |
| 47 | `hb_herbicide_window_missed_rain_delay` | 齐 | 齐 | 无 | 无 | 齐 | 无 |
| 48 | `hb_mechanical_weed_trafficability_window` | 齐 | 齐 | 无 | 无 | 齐 | 无 |
| 49 | `hb_leaffeeder_vs_disease_spots_diagnosis` | 齐 | 齐 | 无 | 无 | 齐 | 无 |
| 50 | `hb_wetjune_disease_recheck_after_fungicide` | 齐 | 齐 | 无 | 无 | 齐 | 无 |
| 51 | `hb_r5_heat_stress_without_soil_drought` | 齐 | 齐 | 无 | 无 | 无 | 齐 |
| 52 | `hb_split_irrigation_schedule_power_limit` | 齐 | 齐 | 无 | 无 | 无 | 齐 |
| 53 | `hb_fuel_limit_irrigation_harvest_ops` | 齐 | 齐 | 无 | 无 | 无 | 齐 |
| 54 | `hb_market_discount_high_moisture_delivery` | 齐 | 齐 | 无 | 无 | 无 | 齐 |
| 55 | `hb_split_quality_batches_late_disease` | 齐 | 齐 | 无 | 无 | 无 | 齐 |
| 56 | `hb_rhizobia_nodulation_failure_nutrition` | 齐 | 齐 | 无 | 无 | 无 | 齐 |
| 57 | `hb_potassium_deficit_dry_podfill_interaction` | 齐 | 无 | 齐 | 无 | 无 | 齐 |
| 58 | `hb_overfertilized_dense_canopy_disease_risk` | 齐 | 无 | 齐 | 无 | 无 | 齐 |
| 59 | `hb_laterain_insect_risk` | 齐 | 无 | 齐 | 无 | 无 | 齐 |
| 60 | `hb_coolwet_flowering_disease_risk` | 齐 | 无 | 齐 | 无 | 无 | 齐 |
| 61 | `hb_storage_aeration_failure_after_harvest` | 齐 | 无 | 齐 | 无 | 无 | 齐 |
| 62 | `hb_dryer_breakdown_between_batches` | 齐 | 无 | 齐 | 无 | 无 | 齐 |
| 63 | `hb_heinong58_drought_insect_diagnosis_waterlimit` | 齐 | 无 | 齐 | 无 | 无 | 齐 |
| 64 | `hb_heinong60_highdensity_wetjune_weed_disease` | 齐 | 无 | 齐 | 无 | 无 | 齐 |
| 65 | `hb_heike71_lateplanting_laterain_highmoisture_quality` | 齐 | 无 | 齐 | 无 | 无 | 齐 |
| 66 | `hb_heihe43_early_density_weed_nutrient_recovery` | 齐 | 无 | 齐 | 无 | 无 | 齐 |
| 67 | `hb_three_cultivar_wet_disease_dry_harvest_sequence` | 齐 | 无 | 齐 | 无 | 无 | 齐 |
| 68 | `hb_heinong60_highdensity_fertigation_irrigation_water_budget` | 齐 | 无 | 齐 | 无 | 无 | 齐 |
| 69 | `hb_hn84_hn58_low_chemical_disease_insect_budget` | 齐 | 无 | 齐 | 无 | 无 | 齐 |
| 70 | `hb_heinong58_water_chemical_priority_under_dual_stress` | 齐 | 无 | 齐 | 无 | 无 | 齐 |
