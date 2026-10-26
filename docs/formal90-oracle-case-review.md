# 正式90场景 Oracle 逐场复核契约

本文件记录源码与原始完整工作流的逐场复核，不把旧流程可执行、当前模型可表达、管理参数已校准三个判断合并。运行结果应由本轮新映射后的实际全季回放及配对试验补充。机器可读明细见 `configs/oracles/formal90_review_v1.json`。

## 必须先分开的校准边界

- 品种身份和参数代理分别保存；映射不等于原地方品种已完成田间标定。
- 施肥归一化值必须换算实际产品质量及氮质量；默认含氮比例0.46。全64垄 `.24` 是460.8kg产品和211.968kg N，另带指定水。
- 灌溉按5mm/h/目标垄的模拟设施映射；`.65h` 是3.25mm，不是0.65mm。
- 杀菌/杀虫/除草参考量为3.8/8/8L工作液每垄，这是模拟剂量标尺，不是药剂标签或有效成分推荐量。
- 删去水肥整动作同时删去氮和载水，不能单独归因为氮。处理的因果收益必须以匹配其他操作和绝对时刻的对照验证。
- 混合品种及错期场景需逐种植区门控；现有编译器保留固定日程并不等于完成物候校准。

## 发现的能力缺口

| 缺口 | 场景数 |
|---|---:|
| `aeration_failure_is_static_safety_proxy` | 1 |
| `dryer_failure_is_static_capacity_proxy` | 1 |
| `legacy_canopy_override_ignored_by_native` | 1 |
| `moisture_sensor_fault_not_injected` | 1 |
| `native_replant_lifecycle_missing` | 7 |
| `no_explicit_native_leaf_removal` | 2 |
| `no_residue_native_C_N_decomposition` | 2 |
| `nodulation_failure_not_native_Nfix_intervention` | 1 |
| `non_N_element_not_in_selected_NWLP_model` | 2 |
| `nutrient_proxy_not_explicit_local_native_N_stock` | 12 |
| `rainfall_capture_1_02_not_native_fraction` | 1 |
| `weed_NDVI_masking_not_in_UAV_projection` | 1 |

补种不能通过删去动作或接受no-op声称解决；K/微量元素/根瘤故障不能靠输入氮肥声称纠正。传感器故障、通风故障和批间烘干机故障的场景名也不等于存在对应动态故障模型。本轮新结果必须保留这些原目标能力标签。

## 每场必须核对的决策

| 场景 ID | 原管理调用数 | 分区时机 | 本场复核重点 |
|---|---:|---|---|
| `scenario_full_season_heinong60_high_density_baseline` | 3 | 本区物候 | 高密HN60的两次全田营养支持与全田轻灌均需独立删去对照；高密度并不能作为追肥/补水的公开证据。 |
| `scenario_full_season_wet_june_ab_zoned_disease` | 6 | 逐区 | A/B品种切换必须精确耗尽料斗；B区两次5 L/垄杀菌剂超过模型3.8 L参考量，超量部分没有更高即时防效，需限量和二喷删除对照。 |
| `scenario_full_season_heinong84_edge_low_fertility` | 4 | 本区物候 | 0–11垄营养恢复、0–3垄重播、后续全田支持应分开判定；局部低肥不能推出全田R5追肥必要。原生重播及本场N库差异须先落实。 |
| `scenario_full_season_fastdraining_dry_patch_irrigation` | 2 | 本区物候 | 20–31垄3h灌溉实际15mm；应按该区土壤/阶段安排，不把前置全田轻追肥当作默认必要。 |
| `scenario_full_season_heinong84_staggered_planting` | 1 | 逐区 | 三播区分别检查播床和成熟，晚区1.2h灌水为6mm；晚区原低水分播种失败须补足并复测，不允许未种成功仍收割。 |
| `scenario_full_season_heinong84_threshold_insect_limited_spray` | 2 | 本区物候 | 18–37垄6 L/垄杀虫量为参考量75%；施药前确认害虫检出和资源预算，阈值映射是模拟指标，不能称实测虫口经济阈值。 |
| `scenario_full_season_heinong84_low_chemical_wet_disease` | 3 | 本区物候 | 22–43垄3 L/垄杀菌强度约0.789，不能按完整药效假设；限药下比较目标区半量/原量及不喷。 |
| `scenario_full_season_early_vs_standard_late_rain_harvest` | 0 | 逐区 | 早熟与标准品种必须保持可解释的物候差异，分区成熟独立收割；映射为完全同参数会破坏主要任务。 |
| `scenario_full_season_hb_base_hn84_std_normal` | 1 | 本区物候 | 全田R1 .24+2mm捆绑水肥已有局部删除实证，当前应把省去候选纳入新映射版本复核，不无条件沿用。 |
| `scenario_full_season_hb_dryr5r6_hn58_std_waterlimit` | 2 | 本区物候 | 22–43垄2h为10mm定向补水，优先依据当地水分与R5/R6；前置全田 .22 肥需删除对照并保留载水混杂说明。 |
| `scenario_full_season_hb_poordrainage_wetjune_disease_trafficability` | 2 | 本区物候 | 先解决集水效率1.02不能映射NOTINF的水文语义；只裁成1会改变原场景。44–53病区喷药需同时确认可通行，不应以全田水肥缓解积水。 |
| `scenario_full_season_hb_soy_after_soy_wetjune_disease` | 4 | 本区物候 | 连作是风险背景，实际施药针对22–43症状区；全田 .22 营养支持不能由连作病害风险推出。 |
| `scenario_full_season_hb_coldspring_planting_window_heihe50` | 0 | 逐区 | 11天播前等待只可作最早计划参考；须在公开土温/水分达标后播种，并验证映射品种在180天截止前成熟。 |
| `scenario_full_season_hb_low_nutrient_carryover_flowering_nutrition` | 1 | 本区物候 | 全田R1 .34+1.5mm约652.8kg产品；先建立真实低N初值，否则只能观察generic营养代理，不可把此大剂量标成必要。 |
| `scenario_full_season_hb_high_weed_seedbank_mechanical_only_baseline` | 7 | 本区物候 | 全田机械除草遵守禁化学规则；观察草检出并在冠层尚未封行、地面可通行时安排，逐通行次数比较。 |
| `scenario_full_season_hb_wetjune_short_spray_window` | 3 | 本区物候 | 18–45垄4.2 L杀菌超过3.8 L参考量；比较3.8和原量，明确时间等待是否错过症状窗口。 |
| `scenario_full_season_hb_r5_leaf_feeder_defoliation` | 3 | 本区物候 | 16–39垄3.8 L杀虫仅0.475模型强度；当前不移除原生叶片，不能用同化代理宣称验证食叶损伤修复。 |
| `scenario_full_season_hb_limited_spray_budget_season` | 3 | 本区物候 | 18–45垄3.6 L杀虫需预算约束下比较覆盖与剂量，不根据风险名称强制喷药。 |
| `scenario_full_season_hb_dryr5r6_hn84_water_limit` | 1 | 本区物候 | 22–43垄 .9h=4.5mm；R5/R6期需检查灌后实际缺水恢复及以后复发，不能只核查水已扣除。 |
| `scenario_full_season_hb_hn60_high_dryr5r6_water_demand` | 1 | 本区物候 | 全田 .75h=3.75mm；高密“需水更大”当前只TDWI代理，需用实际native水分胁迫与产量对照验证全田灌水范围。 |
| `scenario_full_season_hb_two_dry_patches_one_irrigation` | 1 | 本区物候 | 只给42–53垄1.25h=6.25mm的选择必须与另一缺水区分配候选比较，保留总水预算。 |
| `scenario_full_season_hb_staggered_dryr5r6_stage_mismatch` | 1 | 逐区 | 0–31垄 .85h=4.25mm必须按该区阶段安排；全田统一R5等待会抹掉错期考点。 |
| `scenario_full_season_hb_staggered_wetjune_canopy_disease` | 4 | 逐区 | 先播区0–31喷杀菌需按其冠层/病检出时间；晚播区不应被统一全田时钟强制当作同阶段。 |
| `scenario_full_season_hb_hn60_high_late_grain_moisture` | 0 | 本区物候 | 成熟与籽粒安全水分分开门控，比较田间等待和干燥；替代品种不能未经说明消除晚熟高水分任务。 |
| `scenario_full_season_hb_harvester_days_limit_laterain` | 0 | 本区物候 | 按真实可收天气和收割日配额安排所有64垄，不可只延迟到全田干燥且越过配额或截止。 |
| `scenario_full_season_hb_adversarial_multi_event_light` | 3 | 本区物候 | 24–43病区与20–43旱区依次诊断；杀菌不能代替灌水，.65h仅3.25mm，逐项删除及组合对照。 |
| `scenario_full_season_hb_wetcold_high_residue_establishment` | 4 | 逐区 | 0–15重播及残茬冷湿建植是原任务核心；当前无原生重播/残茬C-N循环，换早熟品种不能补上能力。 |
| `scenario_full_season_hb_compacted_headland_stand_recovery` | 3 | 本区物候 | 0–7重播与0–11营养动作需依据缺苗和真实N分别判断；土壤压实代理只在已映射的水文参数范围解释。 |
| `scenario_full_season_hb_storage_capacity_limit_batching` | 0 | 本区物候 | 分批收获必须每批有来源、质量、卸粮和入库闭环；仓库总容量不足不能靠拆批制造额外容量。 |
| `scenario_full_season_hb_low_carbon_min_machinery_passes` | 1 | 本区物候 | 减少机械通行是目标；全田R1 .22 肥必须删除比较，不能用“保产”默认增加一趟。 |
| `scenario_full_season_hb_organic_patch_weed_mechanical_capacity` | 2 | 本区物候 | 0–15机械除草覆盖与设备可用性优先；禁止用杀草剂填补机械容量缺口。 |
| `scenario_full_season_hb_coldspring_lateplanting_laterain_hn50` | 0 | 本区物候 | 冷春等待、替代品种早熟性和晚雨收获窗口联动；逐区确认成熟，不直接用固定“早熟”标签提前收割。 |
| `scenario_full_season_hb_wetjune_highdensity_poordrainage_disease` | 2 | 本区物候 | 40–55垄4.1 L超参考；需确认病害与过湿并存，杀菌不能改善土壤通行性。 |
| `scenario_full_season_hb_wetjune_soyhistory_poordrainage_disease` | 6 | 本区物候 | 22–43垄4.0后二喷2.8需要复查残效与病检出；持续outbreak重置可能压过防治，不可当作田间反弹证据。 |
| `scenario_full_season_hb_wetjune_weed_disease_diagnosis` | 4 | 本区物候 | 6–21草与34–49病应分别地面确认；保留不同对象和范围，不能只因低NDVI统一施药。 |
| `scenario_full_season_hb_highdensity_wetjune_limited_fungicide` | 3 | 本区物候 | 36–59垄3.6 L约0.947参考强度；药预算下比较较少覆盖与剂量，防止把强度阈值当作物种防效。 |
| `scenario_full_season_hb_wetjune_shortwindow_trafficability` | 3 | 本区物候 | 22–45喷药需交集窗口：症状、无雨低风、地面可通行；无条件等到可喷可能错过有产量收益阶段。 |
| `scenario_full_season_hb_hn84_hn58_dry_patch_waterlimit` | 1 | 逐区 | 22–31垄 .8h=4mm；保留原两品种分区和局部灌水，不将代理品种同参数结果解释成原HN84/HN58差异。 |
| `scenario_full_season_hb_hn60_high_fastdrain_dryr5r6` | 1 | 本区物候 | 24–39垄 .9h=4.5mm；快排水需验证原生水分持续时间，单次补水并不证明R5/R6全程缓解。 |
| `scenario_full_season_hb_dryr5r6_insect_threshold_waterstress` | 3 | 本区物候 | 30–47虫与10–27旱分开处置，杀虫3.5 L为0.4375参考强度；优先级需共享预算对照。 |
| `scenario_full_season_hb_heatdry_aphid_limitedspray_waterlimit` | 4 | 本区物候 | 0–31灌水与12–35杀虫空间重叠但原因不同；高温自然抑虫和缺水须先分辨，比较省去低收益喷药。 |
| `scenario_full_season_hb_lowdensity_weed_dry_competition` | 6 | 本区物候 | 低密种子growth override不影响原生参数；机械8–55与灌水16–47可校准经验压力和水限制，不能验证完整杂草水氮竞争。 |
| `scenario_full_season_hb_hn84_hn58_weed_mechanical_allocation` | 4 | 逐区 | 0–31机械投入需在两品种区间比较边际收益；高草种子库是初始压力而非持续真杂草种群。 |
| `scenario_full_season_hb_organic_residue_weed_establishment` | 9 | 本区物候 | 全田机械草控可校准，但0–7重播和残茬效应不支持，须保留原任务语义未完成标签。 |
| `scenario_full_season_hb_lowcarbon_batch_operations_wetdisease` | 3 | 本区物候 | 24–47垄3.6 L杀菌与少通行目标联动；量化通行/油料，不能仅按kg产量选最优。 |
| `scenario_full_season_hb_dryer_capacity_batch_harvest_storage` | 0 | 本区物候 | 逐批干燥量不得超过日处理上限；等待和田间损失纳入净实收，不得一次dry调用视为全田完成。 |
| `scenario_full_season_hb_laterain_shattering_drying_tradeoff` | 0 | 本区物候 | 比较成熟后不同可收日期、田间脱水与机器干燥；目标需包含收割损失与干燥后的标准水分质量。 |
| `scenario_full_season_hb_cool_august_lategrain_laterain` | 0 | 本区物候 | 冷八月改变原生发育与同化，固定秋收日要重排；低温不能以追肥/杀菌替代，保留晚雨风险。 |
| `scenario_full_season_hb_hn50_hn84_hn58_mixed_stress` | 1 | 逐区 | 三品种各有播种、R5及成熟节奏；21–42补水 .7h=3.5mm，不能用全田R5门槛延迟早区管理。 |
| `scenario_full_season_hb_density_gradient_wetdry` | 6 | 逐区 | 0–20机械、43–63杀菌分区证据保留；密度梯度仅TDWI代理，必须分清其物理表达边界。 |
| `scenario_full_season_hb_fertilizer_quota_edge_lowfertility` | 3 | 本区物候 | 0–7 .32、8–15 .16两次肥及0–3重播需分别对照；严格按产品总kg额度，不按归一化amount相加。 |
| `scenario_full_season_hb_insect_after_fungicide_budget_conflict` | 15 | 本区物候 | 18–39杀菌与24–47杀虫共用资源，需阶段/剂量组合比较，后发虫风险不能提前无证据占用预算。 |
| `scenario_full_season_hb_disease_then_drought_recovery_tradeoff` | 4 | 本区物候 | 20–43先病后旱需两次独立诊断，防治收益可能被后续水限制盖住；比较两动作及组合。 |
| `scenario_full_season_hb_weed_then_disease_canopy_confusion` | 4 | 本区物候 | 4–23机械、32–51杀菌，保留草/病地面检测区分；观测相似不能代替因果诊断。 |
| `scenario_full_season_hb_lowinput_waterlimited_weed_pressure` | 8 | 本区物候 | 全田机械及16–47 1.2h=6mm在低投入预算下比较；不得为补充管理无限增加水或机械燃油。 |
| `scenario_full_season_hb_planter_skip_rows_stand_gap` | 2 | 本区物候 | 12–15及28–31两区补种是任务中心；原生生命周期未实现，不可把补种调用no-op当成恢复缺苗。 |
| `scenario_full_season_hb_replant_after_crusting_short_season` | 2 | 本区物候 | 0–7补种与短季成熟均须真实新作物季；替代早熟品种只能缓解物候，不能修复补种能力缺口。 |
| `scenario_full_season_hb_fertilizer_misapplication_strip_recovery` | 1 | 本区物候 | 24–39 .30+1.2mm先建立分区原生N缺口，否则“误施恢复”仅generic营养代理，不应强制补肥。 |
| `scenario_full_season_hb_nutrient_vs_disease_leafcolor_diagnosis` | 2 | 本区物候 | 8–23营养与44–53病斑分别确认；原生N初态与病压是不同状态，不可因叶色差就对两区同施肥。 |
| `scenario_full_season_hb_weed_green_ndvi_masked_drought` | 5 | 本区物候 | 杂草遮蔽NDVI为观测语义任务，但当前UAV只读取作物冠层NDVI；不得把未显式实现的遮蔽机制当检测成功。 |
| `scenario_full_season_hb_herbicide_window_missed_rain_delay` | 4 | 本区物候 | 12–45垄2 L仅0.25参考强度；需核查晚窗口后允许施药范围与实际效果，不能把“成功返回”当足量除草。 |
| `scenario_full_season_hb_mechanical_weed_trafficability_window` | 7 | 本区物候 | 全田机械时间由草检出和真实地面可通行交集决定；湿土等待可能错过早期杂草控制，应比较窗口候选。 |
| `scenario_full_season_hb_leaffeeder_vs_disease_spots_diagnosis` | 2 | 本区物候 | 33–43杀虫前必须明确虫检出且排除病斑；食叶实物损伤未接原生叶量，结论限经验同化代理。 |
| `scenario_full_season_hb_wetjune_disease_recheck_after_fungicide` | 6 | 本区物候 | 20–43两次3.6/2.8 L间需真实复查，二喷整动作必须删去比较；14d残效不是自动二喷理由。 |
| `scenario_full_season_hb_drought_recovery_false_disease_signal` | 1 | 本区物候 | 18–39补水后先等候并复测，不因NDVI未立即恢复而加杀菌剂；水胁迫恢复与病害分别判定。 |
| `scenario_full_season_hb_r5_heat_stress_without_soil_drought` | 0 | 本区物候 | 无干旱证据不得补水；高温响应由原生温度生理驱动，不可给无关药肥“治疗热害”。 |
| `scenario_full_season_hb_cloudy_wet_low_radiation_biomass` | 0 | 本区物候 | 低辐射低生物量不能靠水肥自动恢复；保留无额外投入的候选，仅做病/水真实观察。 |
| `scenario_full_season_hb_split_irrigation_schedule_power_limit` | 2 | 本区物候 | 8–23 .65h与40–55 .55h必须分别在其R5/R6和电力窗口内进行，原旧样本有一次晚至R7，需重排。 |
| `scenario_full_season_hb_fuel_limit_irrigation_harvest_ops` | 1 | 本区物候 | 20–43 .65h补水与收获共用燃油/设备约束，不能因compiler自动补油绕过原仓库总油预算。 |
| `scenario_full_season_hb_market_discount_high_moisture_delivery` | 0 | 本区物候 | 目标应为安全标准水分实收/质量折价，湿粮kg高不等于更高产；比较干燥时机。 |
| `scenario_full_season_hb_split_quality_batches_late_disease` | 3 | 本区物候 | 32–55晚病区单独批次来源和质量；晚喷不可恢复已经造成的籽粒损伤，当前损失是即时压力代理。 |
| `scenario_full_season_hb_rhizobia_nodulation_failure_nutrition` | 1 | 本区物候 | 18–45 .26肥不能证明补偿根瘤失效；需原生固氮参数/状态干预，否则仅保留generic营养实验。 |
| `scenario_full_season_hb_local_soil_constraint_nutrition_patch` | 1 | 本区物候 | 48–59 .18+1mm只有nutrient_index下降代理，尚未显式土壤化学或局部N库机制，补肥必要性先做删除比较。 |
| `scenario_full_season_hb_micronutrient_deficiency_flowering_patch` | 1 | 本区物候 | 28–43 .16+0.8mm实际进入N而非微量元素；原任务机制不支持，不能称微量元素校准完成。 |
| `scenario_full_season_hb_potassium_deficit_dry_podfill_interaction` | 2 | 本区物候 | 20–39 .20水肥输入是N，不是K；只能校准灌水/N子任务，不能验证补钾与抗旱交互。 |
| `scenario_full_season_hb_overfertilized_dense_canopy_disease_risk` | 3 | 本区物候 | 22–43杀菌需依据症状；“过肥→密冠→病”因果链目前不能仅以初始proxy证明，不应增加施肥。 |
| `scenario_full_season_hb_laterain_insect_risk` | 2 | 本区物候 | 36–55晚期杀虫前确认仍有原生生长/籽粒保护收益；若已成熟，不能宣称增加原生TWSO。 |
| `scenario_full_season_hb_coolwet_flowering_disease_risk` | 2 | 本区物候 | 22–32垄3 L杀菌须按实际花期而非mid标签；冷湿改变发育速度，不可固定日期喷施。 |
| `scenario_full_season_hb_grain_moisture_sensor_failure_harvest` | 0 | 本区物候 | 当前只有分区交叉检查和湿粮折价，没有传感器故障注入或独立替代测量；可验证质量闭环，不能验证故障识别。 |
| `scenario_full_season_hb_storage_aeration_failure_after_harvest` | 0 | 本区物候 | 当前静态9500kg容量及13%安全水分为通风不足代理，没有通风故障动态；校准应报告代理约束。 |
| `scenario_full_season_hb_dryer_breakdown_between_batches` | 0 | 本区物候 | 当前静态5200kg/day烘干容量，没有第一批后失效事件；可校准容量调度，不能宣称处置真实批间故障。 |
| `scenario_full_season_hb_heinong58_drought_insect_diagnosis_waterlimit` | 3 | 本区物候 | 8–23灌水和40–55杀虫严格分区，HN58耐旱耐虫标签须由映射证据分别支持，不得复制一个耐旱参数即保留耐虫宣称。 |
| `scenario_full_season_hb_heinong60_highdensity_wetjune_weed_disease` | 4 | 本区物候 | 4–23草控与40–55病控分开证据，高密参数代理不能替代多物种竞争或病害流行机制。 |
| `scenario_full_season_hb_heike71_lateplanting_laterain_highmoisture_quality` | 0 | 本区物候 | 晚播黑科71映射必须明确成熟期代理，收获/干燥独立门控且批次保留原种子标签与实际profile来源。 |
| `scenario_full_season_hb_heihe43_early_density_weed_nutrient_recovery` | 3 | 本区物候 | 8–19营养恢复与44–55除草各自诊断；HEIHE43高密标签如映射无依据，应保留未知，不虚构早熟/密度耐性。 |
| `scenario_full_season_hb_heinong58_resistant_biotic_water_budget_priority` | 5 | 逐区 | 0–31杀菌与补水优先级要组合对照，抗性标签须分开看原biotic resistance和新native作物profile。 |
| `scenario_full_season_hb_three_cultivar_wet_disease_dry_harvest_sequence` | 4 | 逐区 | 保留三区种子切换、分期管理和分批收获顺序，21–42病区与43–63旱区分别门控；不可全田统一等待。 |
| `scenario_full_season_hb_heinong60_highdensity_fertigation_irrigation_water_budget` | 2 | 本区物候 | 8–19 .24水肥载水2mm必须计入水预算，40–55 .55h灌水2.75mm；二者总水和N质量分别核算。 |
| `scenario_full_season_hb_hn84_hn58_low_chemical_disease_insect_budget` | 6 | 逐区 | 0–31杀菌与8–23杀虫共享低药量，比较先后、剂量及省去组合；两品种标签不可解释为已标定抗病抗虫。 |
| `scenario_full_season_hb_heinong58_water_chemical_priority_under_dual_stress` | 3 | 本区物候 | 8–23补水、40–55杀菌在预算内比较收益；避免高NDVI/耐旱标签先验决定优先级。 |

## 运行结果应附带的最小证据

每个ID应保存：原始完整工作流、映射配置与原参数指纹、修订工作流、各管理节点公开观察、修改理由及实际剂量、配对省去/半量对照、资源总量、原生逐日TWSO/水氮/PGASS、成熟和入库证明、鲜场景重放一致性、原任务能力仍未覆盖的条目。

若某动作在公开证据不支持时被省去，应记录“无证据且已省略”；若配对试验不能显示增产，应记录“本候选集合未显示收益”。两者均不可泛化为真实农艺上的无用操作。
