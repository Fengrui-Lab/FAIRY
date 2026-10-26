# 正式90场景播种参数证据审查

本表只审查原始Oracle的播种配方、几何换算和主源密度依据，不修改已冻结品种参数、物理核心或源场景。机器可读文件是 [formal90_sowing_parameter_review_v1.json](../configs/oracles/formal90_sowing_parameter_review_v1.json)。90例均有独立决策和原工作流哈希：78例保留，12例包含候选，共13个分区候选；本审查没有自动应用候选。

## 几何与单位

实际大豆几何为一垄两行、垄距1.1m、垄长268m。名义密度为 `200/(1.1×株距cm)`，每垄种子数为 `round(268×2×100/株距cm)`。例如7.9cm约23.015粒/m²，而不是再乘一次双行系数。主源通常写的是最终保苗株数；本轮换算假设100%建植，不暗中拟合发芽率、缺苗率或补种率。

| 品种 | 主源面积保苗参考 | 源Oracle播距及名义密度 | 审查结果 |
|---|---|---|---|
| 黑农84 | 22–24株/m² | 7.9cm→23.015；11.8cm→15.408 | 标准密度保留；明确的低密度挑战保留 |
| 黑农60 | 25–30株/m² | 6.1cm→29.806；6.8cm→26.738 | 均在参考范围；保留高密度或梯度设定 |
| 黑农58 | 20–22株/m² | 7.9cm→23.015；8.4cm→21.645 | 8.4保留；7.9提出8.66cm→20.995候选 |
| 黑河50 | 30–35株/m²（主源垄三） | 8.2cm→22.173 | 提出5.59cm→32.526候选，区间中值不等于最优密度 |
| 黑河43 | 约30株/m²（主源垄三） | 实际8.1cm→22.447 | “推荐密度”标签依据不足；候选6.06cm→30.003 |
| 黑科71 | 大垄密植38株/m²；标准垄三32株/m² | 7.9cm→23.015；8.4cm→21.645 | 大垄模式候选4.78cm→38.037；晚播适用性另核验 |

主源及具体定位均保存在JSON的 `source_references`。其中黑科71来自育种者2022年原论文第4.4节。黑河50/43的主源垄三布局与项目双行不同，本轮仅转移单位面积密度，不能声称重现原行间光竞争或原栽培试验。

## 哪些值不能直接改

- `hb_density_gradient_wetdry` 的低/标准/高三梯度全部保留；`hb_lowdensity_weed_dry_competition` 的11.8cm明确作为挑战保留。不能用加密播种消除题目。
- 黑农84/58同密度分区比较，以及黑科71/黑农84早熟对照，原组必须保留。改成各品种推荐密度后，变化同时包含群体密度效应，不能单独归因于品种抗性或早熟基因。
- 三品种分区的0–20、21–42、43–63垄及错期播种顺序、等待和天气/土壤门槛保留；机械除草仅32垄、水量和化学额度等约束也保留。
- 黑河43的4.05cm只出现在未使用常量`HEIHE43_DENSITY_OPT_SPACING_CM`中，当前有效PlantingZone和冻结完整Oracle均用8.1cm。本报告不把4.05cm推导出的44.893株/m²假写成已经发生的播种。

所有原始播深均为4cm，处于当前工具允许的3–5cm范围，予以保留；这不等于独立识别了各品种最优播深。播种日期和跨区时间由Oracle的土壤/天气/分期约束另行校准。

## 候选如何使用

JSON每个 `planting_groups` 保存种子、受影响垄段、原stepID、原播距、来源、决策和候选。`candidate_options`给出主源范围下的边界/中值配方，默认候选采用区间中值或主源单点；并非根据原生初始TDWI偏好挑选最高密度。候选必须重新检查种子库存、料箱容量和装种次数，并与原配方配对全季回放。

当前原生适配只用密度缩放初始TDWI，没有经验证的密度竞争与最优密度曲线。因此，几何和来源审查可以说“保留/有依据的候选”，不能说“原生模型证明这个密度最高产”。各场的`native_density_optimum_inference`均明确标记不支持此类推断。

## 逐场结论

`keep`表示保留当前配方或明确挑战；`candidate`表示存在值得配对重跑的证据约束替代；`unsupported`表示无法给出主源支持的配方。本轮六种种子均找到面积密度资料，故参数审查没有unsupported案例；原生最优密度推断则在全部案例中均不受支持。

| 场景ID | 决策 | 原播距→候选（cm；未改变的分区写保留） |
|---|---|---|
| `scenario_full_season_heinong60_high_density_baseline` | keep | HEINONG60[0–63] 6.1→保留 |
| `scenario_full_season_wet_june_ab_zoned_disease` | keep | HEINONG84[0–31] 7.9→保留；HEINONG60[32–63] 6.1→保留 |
| `scenario_full_season_heinong84_edge_low_fertility` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_fastdraining_dry_patch_irrigation` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_heinong84_staggered_planting` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_heinong84_threshold_insect_limited_spray` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_heinong84_low_chemical_wet_disease` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_early_vs_standard_late_rain_harvest` | candidate | HEIKE71[0–31] 7.9→4.78；HEINONG84[32–63] 7.9→保留 |
| `scenario_full_season_hb_base_hn84_std_normal` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_dryr5r6_hn58_std_waterlimit` | candidate | HEINONG58[0–63] 7.9→8.66 |
| `scenario_full_season_hb_poordrainage_wetjune_disease_trafficability` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_soy_after_soy_wetjune_disease` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_coldspring_planting_window_heihe50` | candidate | HEIHE50[0–63] 8.2→5.59 |
| `scenario_full_season_hb_low_nutrient_carryover_flowering_nutrition` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_high_weed_seedbank_mechanical_only_baseline` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_wetjune_short_spray_window` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_r5_leaf_feeder_defoliation` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_limited_spray_budget_season` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_dryr5r6_hn84_water_limit` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_hn60_high_dryr5r6_water_demand` | keep | HEINONG60[0–63] 6.8→保留 |
| `scenario_full_season_hb_two_dry_patches_one_irrigation` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_staggered_dryr5r6_stage_mismatch` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_staggered_wetjune_canopy_disease` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_hn60_high_late_grain_moisture` | keep | HEINONG60[0–63] 6.8→保留 |
| `scenario_full_season_hb_harvester_days_limit_laterain` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_adversarial_multi_event_light` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_wetcold_high_residue_establishment` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_compacted_headland_stand_recovery` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_storage_capacity_limit_batching` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_low_carbon_min_machinery_passes` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_organic_patch_weed_mechanical_capacity` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_coldspring_lateplanting_laterain_hn50` | candidate | HEIHE50[0–63] 8.2→5.59 |
| `scenario_full_season_hb_wetjune_highdensity_poordrainage_disease` | keep | HEINONG60[0–63] 6.8→保留 |
| `scenario_full_season_hb_wetjune_soyhistory_poordrainage_disease` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_wetjune_weed_disease_diagnosis` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_highdensity_wetjune_limited_fungicide` | keep | HEINONG60[0–63] 6.8→保留 |
| `scenario_full_season_hb_wetjune_shortwindow_trafficability` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_hn84_hn58_dry_patch_waterlimit` | candidate | HEINONG84[0–31] 7.9→保留；HEINONG58[32–63] 7.9→8.66 |
| `scenario_full_season_hb_hn60_high_fastdrain_dryr5r6` | keep | HEINONG60[0–63] 6.8→保留 |
| `scenario_full_season_hb_dryr5r6_insect_threshold_waterstress` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_heatdry_aphid_limitedspray_waterlimit` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_lowdensity_weed_dry_competition` | keep | HEINONG84[0–63] 11.8→保留 |
| `scenario_full_season_hb_hn84_hn58_weed_mechanical_allocation` | candidate | HEINONG84[0–31] 7.9→保留；HEINONG58[32–63] 7.9→8.66 |
| `scenario_full_season_hb_organic_residue_weed_establishment` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_lowcarbon_batch_operations_wetdisease` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_dryer_capacity_batch_harvest_storage` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_laterain_shattering_drying_tradeoff` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_cool_august_lategrain_laterain` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_hn50_hn84_hn58_mixed_stress` | candidate | HEIHE50[0–20] 8.2→5.59；HEINONG84[21–42] 7.9→保留；HEINONG58[43–63] 7.9→8.66 |
| `scenario_full_season_hb_density_gradient_wetdry` | keep | HEINONG84[0–20] 11.8→保留；HEINONG84[21–42] 7.9→保留；HEINONG60[43–63] 6.8→保留 |
| `scenario_full_season_hb_fertilizer_quota_edge_lowfertility` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_insect_after_fungicide_budget_conflict` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_disease_then_drought_recovery_tradeoff` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_weed_then_disease_canopy_confusion` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_lowinput_waterlimited_weed_pressure` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_planter_skip_rows_stand_gap` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_replant_after_crusting_short_season` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_fertilizer_misapplication_strip_recovery` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_nutrient_vs_disease_leafcolor_diagnosis` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_weed_green_ndvi_masked_drought` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_herbicide_window_missed_rain_delay` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_mechanical_weed_trafficability_window` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_leaffeeder_vs_disease_spots_diagnosis` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_wetjune_disease_recheck_after_fungicide` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_drought_recovery_false_disease_signal` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_r5_heat_stress_without_soil_drought` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_cloudy_wet_low_radiation_biomass` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_split_irrigation_schedule_power_limit` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_fuel_limit_irrigation_harvest_ops` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_market_discount_high_moisture_delivery` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_split_quality_batches_late_disease` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_rhizobia_nodulation_failure_nutrition` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_local_soil_constraint_nutrition_patch` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_micronutrient_deficiency_flowering_patch` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_potassium_deficit_dry_podfill_interaction` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_overfertilized_dense_canopy_disease_risk` | keep | HEINONG60[0–63] 6.8→保留 |
| `scenario_full_season_hb_laterain_insect_risk` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_coolwet_flowering_disease_risk` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_grain_moisture_sensor_failure_harvest` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_storage_aeration_failure_after_harvest` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_dryer_breakdown_between_batches` | keep | HEINONG84[0–63] 7.9→保留 |
| `scenario_full_season_hb_heinong58_drought_insect_diagnosis_waterlimit` | candidate | HEINONG58[0–63] 7.9→8.66 |
| `scenario_full_season_hb_heinong60_highdensity_wetjune_weed_disease` | keep | HEINONG60[0–63] 6.8→保留 |
| `scenario_full_season_hb_heike71_lateplanting_laterain_highmoisture_quality` | candidate | HEIKE71[0–63] 8.4→4.78 |
| `scenario_full_season_hb_heihe43_early_density_weed_nutrient_recovery` | candidate | HEIHE43[0–63] 8.1→6.06 |
| `scenario_full_season_hb_heinong58_resistant_biotic_water_budget_priority` | keep | HEINONG84[0–31] 7.9→保留；HEINONG58[32–63] 8.4→保留 |
| `scenario_full_season_hb_three_cultivar_wet_disease_dry_harvest_sequence` | candidate | HEIHE50[0–20] 8.2→5.59；HEINONG84[21–42] 7.9→保留；HEINONG58[43–63] 8.4→保留 |
| `scenario_full_season_hb_heinong60_highdensity_fertigation_irrigation_water_budget` | keep | HEINONG60[0–63] 6.8→保留 |
| `scenario_full_season_hb_hn84_hn58_low_chemical_disease_insect_budget` | keep | HEINONG84[0–31] 7.9→保留；HEINONG58[32–63] 8.4→保留 |
| `scenario_full_season_hb_heinong58_water_chemical_priority_under_dual_stress` | candidate | HEINONG58[0–63] 7.9→8.66 |
