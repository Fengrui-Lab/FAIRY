# 正式90场景的大豆身份与原生参数映射

默认参数映射保留90个原场景实际使用的六种大豆身份，没有把黑农58偷偷改名为黑农44，也没有放宽参考档案的支持范围。配置入口是 `configs/wofost/formal90_cultivar_mapping_v1.json`；它直接包含 WofostConfig 参数，可供真实场景和Oracle回放加载。每个档案都保存78个完整原生参数、精确种子范围、来源和未验证状态。逐场运行后确需换品种的适应方案作为独立变体登记，见末尾“运行时品种适应例外”；不能把变体通过写成原品种已经通过。

## 依据及选参边界

新增五个档案以现有黑农84完整档案为共同生理背景，仅调整TSUM1和TSUM2的同一缩放比例。公开“出苗至成熟约多少天”只能约束总历时，不能分别识别开花前和开花后热量需求，因此固定原有5:11比例。其余76个原生参数均未按目标产量调整。黑农84原档案逐字节保持不变。

筛选独立使用哈尔滨2017年原始NASA POWER逐日气象，5月5日播种，一垄原生PCSE计算；候选共同系数为0.800至1.050、间隔0.005，共51个。仅按原生DOE至DOM与公开总成熟期近似值的差值选取，平局优先保留最接近共同背景的系数；2018、2019气象只作冻结后诊断。不使用正式90场景的产量、管理结果、干旱窗口或收割日期选参。该操作是公开资料约束的工程参数转移，不是地方品种田间校准。

| 原实际种子 | 主源近似成熟期 | 2017原生历时 | TSUM1 / TSUM2 | 来源 |
|---|---:|---:|---|---|
| HEINONG84（黑农84） | 119–123天 | 121天 | 500.0 / 1100.0 | [HAAS Heinong84 cultivar description:119days,22–24plants/m2,regional yields](https://www.haas.cn/cgcyc/info/1231/2141.htm) |
| HEINONG58（黑农58） | 约118天 | 119天 | 492.5 / 1083.5 | [黑龙江省农业科学院：大豆所专家、品种简介（黑农58）](https://www.haas.cn/info/1051/80431.htm) |
| HEINONG60（黑农60） | 约119天 | 119天 | 492.5 / 1083.5 | [黑龙江省农业科学院：大豆所专家、品种简介（国审豆黑农60）](https://www.haas.cn/info/1051/80431.htm) |
| HEIHE50（黑河50） | 约110天 | 111天 | 472.5 / 1039.5 | [黑龙江省农业科学院：黑河分院专家、品种简介（黑河50号）](https://www.haas.cn/info/1051/79851.htm) |
| HEIHE43（黑河43） | 约115天 | 116天 | 485.0 / 1067.0 | [黑龙江省农业科学院成果产业处：黑河43（黑审豆2007011）](https://www.haas.cn/cgcyc/info/1231/8621.htm) |
| HEIKE71（黑科71） | 约108天 | 108天 | 462.5 / 1017.5 | [鹿文成等（2022）：极早熟高产高油大豆新品种黑科71的选育及栽培技术](https://www.aeeisp.com/ddkx/article/id/fccbd5ae-c8a3-40b0-abc8-f938972d8c33) |

黑科71采用育种者2022年论文适应区约108天的描述；2023年国审材料另有114天的跨区域均值，保留为来源差异，不能把两者拼成同一地点试验。黑河43另有Jia2025多点两年物候阶段资料，仓库保留原始证据包；本轮没有把R7强行改作收获日期，也没有将缺失值补成观测。

## 不能由这组资料推出的结论

- 黑农58的公开抗旱描述有主源依据，但没有识别其原生DEPNR。它和黑农84均沿用DEPNR=5，因此本轮不能声称原生模型已经体现黑农58比黑农84更抗旱。
- 黑农58与黑农60因近似目标和离散日步筛选选择同样的两个热量参数，没有为制造品种差异而随意改变系数。其种子身份、来源、现有FAIRY生物压力响应仍分别保存；这不是两套独立拟合的原生生理参数。
- 黑河50/黑科71的早熟背景不等于原生低温萌发或冻害存活模型。原生温度响应表保持共同背景；不能靠“耐寒”标签把不适宜播种条件改成安全。
- 主源推荐密度：黑农58约20–22株/m²，黑农60约25–30，黑河50约30–35，黑河43约30。这些是管理参数参考。原生适配当前仅按密度线性缩放初始TDWI，未验证密度竞争或最优密度。
- NASA POWER是网格气象代理；2017年哈尔滨天气并不是各品种审定试验的原地点和原年份。原生DOM与公开成熟描述的对应也是明确近似。

## 冻结后的跨年度诊断

| 种子 | 2017选参年 | 2018未选参年 | 2019未选参年 |
|---|---:|---:|---:|
| HEINONG84 | 121天 | 115天 | 132天 |
| HEINONG58 | 119天 | 113天 | 125天 |
| HEINONG60 | 119天 | 113天 | 125天 |
| HEIHE50 | 111天 | 107天 | 116天 |
| HEIHE43 | 116天 | 111天 | 121天 |
| HEIKE71 | 108天 | 105天 | 114天 |

各年的气象不同，成熟历时应自然变化；未把成熟日锁死为119天等常量。随后使用真实六种seed和各自已发布profile、不加运行时热量覆盖，再独立运行18个原生完整季，确认身份、参数指纹和物候结果。

## 复现与证据

```bash
env -u USER .venv/bin/python scripts/audit_formal90_cultivar_phenology.py \
  --output /tmp/formal90-cultivar-screen.json
env -u USER .venv/bin/python scripts/audit_formal90_cultivar_phenology.py \
  --verify-published --output /tmp/formal90-cultivar-published.json
```

[51点筛选与选择准则](/Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/formal90_oracle_recalibration_20261024/cultivars/phenology_screen.json)、[18个实际品种原生季核验](/Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/formal90_oracle_recalibration_20261024/cultivars/published_native_verification.json)、[90例逐ID身份和参数指纹清单](/Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/formal90_oracle_recalibration_20261024/cultivars/formal90_mapping_manifest.json)。本轮这组品种选参在Oracle校准前冻结；Oracle产生的产量不会回流修改这些参数。

## 90例逐场分配

以下原seed来自冻结的原始完整Oracle，逐场精确清单保留原workflow哈希。全部映射为各自同名公开参考档案；不是把六种种子统一套成同一个身份。

| 场景ID | 实际种子 → 参数档案 |
|---|---|
| `scenario_full_season_heinong60_high_density_baseline` | HEINONG60 → `heilongjiang_heinong60_public_reference_v1` |
| `scenario_full_season_wet_june_ab_zoned_disease` | HEINONG60 → `heilongjiang_heinong60_public_reference_v1`；HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_heinong84_edge_low_fertility` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_fastdraining_dry_patch_irrigation` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_heinong84_staggered_planting` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_heinong84_threshold_insect_limited_spray` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_heinong84_low_chemical_wet_disease` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_early_vs_standard_late_rain_harvest` | HEIKE71 → `heilongjiang_heike71_public_reference_v1`；HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_base_hn84_std_normal` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_dryr5r6_hn58_std_waterlimit` | HEINONG58 → `heilongjiang_heinong58_public_reference_v1` |
| `scenario_full_season_hb_poordrainage_wetjune_disease_trafficability` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_soy_after_soy_wetjune_disease` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_coldspring_planting_window_heihe50` | HEIHE50 → `heilongjiang_heihe50_public_reference_v1` |
| `scenario_full_season_hb_low_nutrient_carryover_flowering_nutrition` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_high_weed_seedbank_mechanical_only_baseline` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_wetjune_short_spray_window` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_r5_leaf_feeder_defoliation` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_limited_spray_budget_season` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_dryr5r6_hn84_water_limit` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_hn60_high_dryr5r6_water_demand` | HEINONG60 → `heilongjiang_heinong60_public_reference_v1` |
| `scenario_full_season_hb_two_dry_patches_one_irrigation` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_staggered_dryr5r6_stage_mismatch` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_staggered_wetjune_canopy_disease` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_hn60_high_late_grain_moisture` | HEINONG60 → `heilongjiang_heinong60_public_reference_v1` |
| `scenario_full_season_hb_harvester_days_limit_laterain` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_adversarial_multi_event_light` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_wetcold_high_residue_establishment` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_compacted_headland_stand_recovery` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_storage_capacity_limit_batching` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_low_carbon_min_machinery_passes` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_organic_patch_weed_mechanical_capacity` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_coldspring_lateplanting_laterain_hn50` | HEIHE50 → `heilongjiang_heihe50_public_reference_v1` |
| `scenario_full_season_hb_wetjune_highdensity_poordrainage_disease` | HEINONG60 → `heilongjiang_heinong60_public_reference_v1` |
| `scenario_full_season_hb_wetjune_soyhistory_poordrainage_disease` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_wetjune_weed_disease_diagnosis` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_highdensity_wetjune_limited_fungicide` | HEINONG60 → `heilongjiang_heinong60_public_reference_v1` |
| `scenario_full_season_hb_wetjune_shortwindow_trafficability` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_hn84_hn58_dry_patch_waterlimit` | HEINONG58 → `heilongjiang_heinong58_public_reference_v1`；HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_hn60_high_fastdrain_dryr5r6` | HEINONG60 → `heilongjiang_heinong60_public_reference_v1` |
| `scenario_full_season_hb_dryr5r6_insect_threshold_waterstress` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_heatdry_aphid_limitedspray_waterlimit` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_lowdensity_weed_dry_competition` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_hn84_hn58_weed_mechanical_allocation` | HEINONG58 → `heilongjiang_heinong58_public_reference_v1`；HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_organic_residue_weed_establishment` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_lowcarbon_batch_operations_wetdisease` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_dryer_capacity_batch_harvest_storage` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_laterain_shattering_drying_tradeoff` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_cool_august_lategrain_laterain` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_hn50_hn84_hn58_mixed_stress` | HEIHE50 → `heilongjiang_heihe50_public_reference_v1`；HEINONG58 → `heilongjiang_heinong58_public_reference_v1`；HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_density_gradient_wetdry` | HEINONG60 → `heilongjiang_heinong60_public_reference_v1`；HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_fertilizer_quota_edge_lowfertility` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_insect_after_fungicide_budget_conflict` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_disease_then_drought_recovery_tradeoff` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_weed_then_disease_canopy_confusion` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_lowinput_waterlimited_weed_pressure` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_planter_skip_rows_stand_gap` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_replant_after_crusting_short_season` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_fertilizer_misapplication_strip_recovery` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_nutrient_vs_disease_leafcolor_diagnosis` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_weed_green_ndvi_masked_drought` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_herbicide_window_missed_rain_delay` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_mechanical_weed_trafficability_window` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_leaffeeder_vs_disease_spots_diagnosis` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_wetjune_disease_recheck_after_fungicide` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_drought_recovery_false_disease_signal` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_r5_heat_stress_without_soil_drought` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_cloudy_wet_low_radiation_biomass` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_split_irrigation_schedule_power_limit` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_fuel_limit_irrigation_harvest_ops` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_market_discount_high_moisture_delivery` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_split_quality_batches_late_disease` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_rhizobia_nodulation_failure_nutrition` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_local_soil_constraint_nutrition_patch` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_micronutrient_deficiency_flowering_patch` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_potassium_deficit_dry_podfill_interaction` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_overfertilized_dense_canopy_disease_risk` | HEINONG60 → `heilongjiang_heinong60_public_reference_v1` |
| `scenario_full_season_hb_laterain_insect_risk` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_coolwet_flowering_disease_risk` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_grain_moisture_sensor_failure_harvest` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_storage_aeration_failure_after_harvest` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_dryer_breakdown_between_batches` | HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_heinong58_drought_insect_diagnosis_waterlimit` | HEINONG58 → `heilongjiang_heinong58_public_reference_v1` |
| `scenario_full_season_hb_heinong60_highdensity_wetjune_weed_disease` | HEINONG60 → `heilongjiang_heinong60_public_reference_v1` |
| `scenario_full_season_hb_heike71_lateplanting_laterain_highmoisture_quality` | HEIKE71 → `heilongjiang_heike71_public_reference_v1` |
| `scenario_full_season_hb_heihe43_early_density_weed_nutrient_recovery` | HEIHE43 → `heilongjiang_heihe43_public_reference_v1` |
| `scenario_full_season_hb_heinong58_resistant_biotic_water_budget_priority` | HEINONG58 → `heilongjiang_heinong58_public_reference_v1`；HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_three_cultivar_wet_disease_dry_harvest_sequence` | HEIHE50 → `heilongjiang_heihe50_public_reference_v1`；HEINONG58 → `heilongjiang_heinong58_public_reference_v1`；HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_heinong60_highdensity_fertigation_irrigation_water_budget` | HEINONG60 → `heilongjiang_heinong60_public_reference_v1` |
| `scenario_full_season_hb_hn84_hn58_low_chemical_disease_insect_budget` | HEINONG58 → `heilongjiang_heinong58_public_reference_v1`；HEINONG84 → `heilongjiang_heinong84_complete_v1` |
| `scenario_full_season_hb_heinong58_water_chemical_priority_under_dual_stress` | HEINONG58 → `heilongjiang_heinong58_public_reference_v1` |

## 播种参数的独立逐场审查

六个品种的参数档案冻结后，另对90例Oracle的实际一垄两行、1.1m垄距进行密度换算及一手来源复核。结果为78例保留、12例有候选（共13个分区），明确保留密度梯度/低密挑战，不依据原生TDWI随密度的增益选择最高密度。候选尚未由本审查应用；见[播种参数审查与90例清单](oracle-sowing-parameter-review.md)。

## 运行时品种适应例外

`scenario_full_season_hb_cool_august_lategrain_laterain` 的原黑农84配方在固定期限内未成熟，故另登记播种前选用黑农58的适应候选，完整边界见 [formal90_runtime_adaptations_v1.json](../configs/oracles/formal90_runtime_adaptations_v1.json)。原黑农84对照失败证据保留；该候选改变了“固定黑农84”的问题，不能算原品种通过。

选择黑农58的公开依据是[省农科院资料](https://www.haas.cn/info/1051/80431.htm)给出约118天、2400℃活动积温以及第二积温带/第三积温带上限适应区，与[原黑农84](https://www.haas.cn/cgcyc/info/1231/2141.htm)约119天、2400℃、第二积温带较接近。资料只能支持优先试验这个候选，不保证本模拟凉八月季节能够成熟，也没有确认虚拟田块的实际积温带。

候选使用已冻结的黑农58档案，不调热量系数、不改天气、不延180天期限、不强制DVS。第一组品种对照保留原7.9cm播距；若再试黑农58约21株/m²对应8.66cm，应单列品种和密度同时变化的方案。更早的黑河43约115天、2150℃可以作为下一候选，但主源适应区为第四积温带，与原区域目标不同，适地性与全季完成仍需独立检查，不能直接承诺更合适。

同一运行时适应登记还为poor-drainage场景单独启用明确的外来边界水解释：源44–53垄`rainfall_capture_efficiency=1.02`中的超额2%日雨量单列为外来水，不能转成负`NOTINF`或静默混入实灌水。外来贡献区面积未识别，故仍是有来源标签的经验场景假设，不是经校准的真实集水区模型；默认配置继续拒绝这种未声明的超额入水。品种档案与当地天气雨量均保持原样，外来水、工具灌水与原生水量守恒须分别登记核验。
