# 管理拓展场景：推荐 34 场＋备选 5 场

默认推荐清单为 **34 场**，分成 **5 个互斥主类**。另有 **5 个小麦备选场景**，按注册表既有“待重做／待定”标记排除在默认推荐批次之外；它们仍保留注册，供历史回放。推荐与备选合计覆盖全部 39 个场景。

L4 多季单作物产量管理与多作物轮作合并为“L4 多季／多作物管理”；以跨季净运营收益为主目标的 5 场归入“L4 跨季经营决策”，避免重复计数。

## 默认推荐分类

| 主类 | 推荐数量 | 归类依据 |
| --- | ---: | --- |
| L3 小麦管理 | 10 | 推荐清单保留 10 场冬小麦管理；4 场待重做和高水价待定场景另列备选。 |
| L3 甜菜管理 | 6 | 单季甜菜按作物族归类；高水价场景的主目标为净运营收益，其余五场为验收净鲜根产量。 |
| L3 单季经营决策（玉米／大豆） | 10 | 承接除小麦、甜菜作物族以外的单季经营权衡；区分净收益最大化与产量约束下的成本最小化。 |
| L4 多季／多作物管理 | 3 | 以产量为主的跨季管理：两年玉米单作 1 场，小麦—甜菜轮作 2 场；多季与多作物合并列为一类。 |
| L4 跨季经营决策 | 5 | 实际连续经营两个作物季，以两季净运营收益为主目标；多作物选择作为交叉标签。 |
| **推荐合计** | **34** | **L3：26；L4：8。每场只计入一个主类。** |

## 备选小麦（5 场，不进入默认推荐批次）

| 场景 | ID／源码 | 原有状态 |
| --- | --- | --- |
| 高水价 | [`scenario_l3_winter_wheat_high_water_price`](L3/scenario_winter_wheat_high_water_price.py) | 待定／历史回放 |
| 灌溉轮次 | [`scenario_l3_winter_wheat_irrigation_turn`](L3/scenario_winter_wheat_irrigation_turn.py) | 待重做 |
| 错期播种 | [`scenario_l3_winter_wheat_staggered_sowing`](L3/scenario_winter_wheat_staggered_sowing.py) | 待重做 |
| 干燥窗口 | [`scenario_l3_winter_wheat_drying_window`](L3/scenario_winter_wheat_drying_window.py) | 待重做 |
| 交付合同 | [`scenario_l3_winter_wheat_delivery_contract`](L3/scenario_winter_wheat_delivery_contract.py) | 待重做 |

其中灌溉轮次、错期播种、干燥窗口、交付合同 4 场明确待重做；高水价小麦 1 场待定。因此默认排除 5 场，推荐小麦由 15 场减为 10 场。

## 推荐逐场清单

### L3 小麦管理（10）

| 场景 | ID／源码 | 实际主目标 | 说明 |
| --- | --- | --- | --- |
| 普通全季 | [`scenario_l3_winter_wheat_full_season`](L3/scenario_winter_wheat_full_season.py) | 净运营收益 | — |
| 限水 | [`scenario_l3_winter_wheat_water_limit`](L3/scenario_winter_wheat_water_limit.py) | 净运营收益 | — |
| 限氮 | [`scenario_l3_winter_wheat_nitrogen_limit`](L3/scenario_winter_wheat_nitrogen_limit.py) | 净运营收益 | — |
| 分块巡查 | [`scenario_l3_winter_wheat_block_scouting`](L3/scenario_winter_wheat_block_scouting.py) | 净运营收益 | — |
| 弱苗诊断 | [`scenario_l3_winter_wheat_weak_growth_diagnosis`](L3/scenario_winter_wheat_weak_growth_diagnosis.py) | 净运营收益 | — |
| 条锈病管理 | [`scenario_l3_winter_wheat_stripe_rust`](L3/scenario_winter_wheat_stripe_rust.py) | 净运营收益 | — |
| 晚熟品种 | [`scenario_l3_winter_wheat_late_maturing`](L3/scenario_winter_wheat_late_maturing.py) | 净运营收益 | — |
| 两个小麦品种分块管理 | [`scenario_l3_winter_wheat_two_varieties`](L3/scenario_winter_wheat_two_varieties.py) | 净运营收益 | 两个品种仍属于同一种作物。 |
| 局部排水 | [`scenario_l3_winter_wheat_local_drainage`](L3/scenario_winter_wheat_local_drainage.py) | 净运营收益 | — |
| 分区配水 | [`scenario_l3_winter_wheat_soil_water_priority`](L3/scenario_winter_wheat_soil_water_priority.py) | 净运营收益 | — |

### L3 甜菜管理（6）

| 场景 | ID／源码 | 实际主目标 | 说明 |
| --- | --- | --- | --- |
| 普通全季 | [`scenario_l3_sugarbeet_full_season`](L3/scenario_sugarbeet_full_season.py) | 验收净鲜根产量 | — |
| 限水 | [`scenario_l3_sugarbeet_water_limit`](L3/scenario_sugarbeet_water_limit.py) | 验收净鲜根产量 | — |
| 限氮 | [`scenario_l3_sugarbeet_nitrogen_limit`](L3/scenario_sugarbeet_nitrogen_limit.py) | 验收净鲜根产量 | — |
| 高水价经营 | [`scenario_l3_sugarbeet_high_water_price`](L3/scenario_sugarbeet_high_water_price.py) | 净运营收益 | — |
| 苗期缺水救援 | [`scenario_l3_sugarbeet_seedling_rescue`](L3/scenario_sugarbeet_seedling_rescue.py) | 验收净鲜根产量 | — |
| 分区配水 | [`scenario_l3_sugarbeet_soil_water_priority`](L3/scenario_sugarbeet_soil_water_priority.py) | 验收净鲜根产量 | — |

### L3 单季经营决策（玉米／大豆）（10）

| 场景 | ID／源码 | 实际主目标 | 说明 |
| --- | --- | --- | --- |
| 大豆种子折扣采购 | [`scenario_multiobjective_seed_discount`](scenario_multiobjective_seed_discount.py) | 产量门槛＋成本控制 | 达到参考产量门槛后控制运营成本，包含采购最优性校验。 |
| 玉米种子到货总价 | [`scenario_multiobjective_seed_total_cost`](scenario_multiobjective_seed_total_cost.py) | 产量门槛＋成本控制 | 达到参考产量门槛后控制运营成本，包含到货总价校验。 |
| SCN 历史下的本季作物选择（一） | [`scenario_multiseason_scn_switch_to_maize`](scenario_multiseason_scn_switch_to_maize.py) | 产量门槛＋成本控制 | 前季为给定历史；实际只推进本季，不属于连续两季 L4。 |
| SCN 历史下的本季作物选择（二） | [`scenario_multiseason_scn_continue_maize`](scenario_multiseason_scn_continue_maize.py) | 产量门槛＋成本控制 | 前季为给定历史；实际只推进本季，不属于连续两季 L4。 |
| 大豆高水价 | [`scenario_l3_soybean_high_water_price`](L3/scenario_soybean_high_water_price.py) | 净运营收益 | — |
| 大豆杀虫剂选择 | [`scenario_l3_soybean_pesticide_choice`](L3/scenario_soybean_pesticide_choice.py) | 净运营收益 | — |
| 玉米肥料预算权衡 | [`scenario_l3_maize_fertilizer_budget_tradeoff`](L3/scenario_maize_fertilizer_budget_tradeoff.py) | 净运营收益 | — |
| 大豆杀菌剂选择 | [`scenario_l3_soybean_fungicide_choice`](L3/scenario_soybean_fungicide_choice.py) | 净运营收益 | — |
| 大豆品种选择与高水价 | [`scenario_l3_soybean_variety_high_water_price`](L3/scenario_soybean_variety_high_water_price.py) | 净运营收益 | 多个大豆品种不算多个作物。 |
| 玉米与大豆双地块联合经营 | [`scenario_l3_joint_maize_soybean_operating_margin`](L3/scenario_joint_maize_soybean_operating_margin.py) | 净运营收益 | 两种作物在同一季的不同地块同时经营；当前注册级别为 L3。 |

### L4 多季／多作物管理（3）

| 场景 | ID／源码 | 实际主目标 | 说明 |
| --- | --- | --- | --- |
| 两年玉米与土壤延续 | [`scenario_l4_two_year_maize_soil_carryover`](L4/scenario_two_year_maize_soil_carryover.py) | 两季累计安全入库量 | 成本和收益有记录，但不是该场景的主优化目标。 |
| 同地小麦—甜菜轮作 | [`scenario_l4_wheat_sugarbeet_rotation`](L4/scenario_wheat_sugarbeet_rotation.py) | 鲜根→小麦→收益（顺序比较） | 多个目标按顺序比较；不是直接把不同作物公斤数相加。 |
| 小麦—甜菜跨季共享水氮 | [`scenario_l4_wheat_sugarbeet_shared_resources`](L4/scenario_wheat_sugarbeet_shared_resources.py) | 鲜根→小麦→收益（顺序比较） | 共享有限水氮，小麦须达到公开产量下限。 |

### L4 跨季经营决策（5）

| 场景 | ID／源码 | 实际主目标 | 说明 |
| --- | --- | --- | --- |
| 玉米跨年肥料采购 | [`scenario_l4_maize_fertilizer_procurement`](L4/scenario_maize_fertilizer_procurement.py) | 净运营收益 | 单作物两季；重点为合同、采购现金与库存。 |
| 大豆前茬与后茬作物选择 | [`scenario_l4_soybean_predecessor_maize_nutrition`](L4/scenario_soybean_predecessor_maize_nutrition.py) | 净运营收益 | 首季固定大豆，次季可选择玉米或大豆。 |
| 玉米／大豆种植与补贴政策 | [`scenario_l4_maize_soybean_policy_choice`](L4/scenario_maize_soybean_policy_choice.py) | 净运营收益 | 接管首季在田玉米，次季选作物；收益包含实际到账补贴。 |
| 两季作物与氮资源配置 | [`scenario_l4_two_year_crop_nitrogen_allocation`](L4/scenario_two_year_crop_nitrogen_allocation.py) | 净运营收益 | 每季均可选作物，不强制两季种不同作物。 |
| 两季 SCN 种群与轮作经营 | [`scenario_l4_two_year_soybean_cyst_rotation`](L4/scenario_two_year_soybean_cyst_rotation.py) | 净运营收益 | 实际模拟两季种群与土壤状态，区别于仅给定前茬历史的旧场景。 |

## 命名与统计建议

- “经营决策／经济权衡”比笼统的“多目标”更准确：净运营收益最大化是一个标量目标，水、氮和预算上限属于约束；记录多项指标不等于实施 Pareto 多目标优化。
- 两个小麦—甜菜 L4 按鲜根、小麦、收益顺序比较；两年玉米以累计安全入库量为主目标。合并分类保留这些目标差异。
- 多作物使用交叉标签：多个小麦或大豆品种仍属于同一作物。
- 冬小麦跨两个日历年仍只有一个作物季，归 L3。两个名字带 multiseason_scn 的旧题只模拟当前一季，前茬为历史资料，也归 L3。
- 推荐小麦 10 场、甜菜高水价 1 场、玉米／大豆经营 6 场，共 17 场 L3 以净运营收益为主目标。用标签筛选这些场景，避免在作物主类和经营主类重复计数。

## 推荐清单的交叉筛选（可重叠）

| 视图 | 数量 | 解释 |
| --- | ---: | --- |
| L4 全部多季任务 | 8 | 3 场多季／多作物管理＋5 场跨季经营。 |
| L4 固定多作物轮作 | 2 | 两个小麦—甜菜场景，两种作物都实际进入任务。 |
| L4 可选作物／轮作 | 4 | 前茬营养、政策、跨季氮分配、SCN；实际轨迹未必包含两种作物。 |
| L3 同季多作物 | 1 | 玉米—大豆双地块联合经营，当前注册为 L3。 |
| L3 净运营收益主目标 | 17 | 推荐小麦 10＋甜菜高水价 1＋玉米／大豆经营 6。 |
| L4 净运营收益主目标 | 5 | 5 场跨季经营。 |
| 产量门槛下控制成本 | 4 | 两个购种题和两个 SCN 历史题。小麦交付合同列入备选。 |

机器可读清单见 [SCENARIO_GROUPS.json](SCENARIO_GROUPS.json)：

- 默认运行列表：`recommended_scenario_ids`（34 个 ID）。
- 按类运行：`groups[].scenarios[].id`（只含推荐 34 场）。
- 备选列表：`reserve_scenario_ids`／`reserve_scenarios`（5 场）。
- 交叉筛选：`overlapping_views`（只含推荐场景）；备选状态见 `reserve_views`。

源文件、场景 ID、注册级别、任务和 Oracle 保持原样；注册表仍为 39 场。独立交售窗口历史场景不在这 39 场之内。
