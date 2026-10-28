# 经典版与 WOFOST 版：13对独立场景

本表13个任务各有两个独立命名的源文件。**无后缀原ID选择经典`legacy`；WOFOST的ID、文件名、类名均加`_V2`。** 经典版保留原来的类、继承和workflow组织；WOFOST版在自己的文件中声明`WORLD`、事件和字面工具workflow。WOFOST `_V2`源码统一位于[`fairy/scenarios/wofost/`](../fairy/scenarios/wofost/)，经典源码保留在`farm_world_fullseason_v2`；场景ID和运行命令不变。其他场景不因本次命名规则自动迁移。

准确映射保存在[版本清单](../configs/oracles/wofost_scenario_versions.json)。清单只是名称、来源与验收状态的索引，不是运行时别名、workflow加载器或优化策略。

## 13对名称与源码

下表名称是可直接传给CLI的完整`scenario_id`，点击名称打开对应源文件。经典版没有为追求形式统一而展开原有继承结构；`_V2`则保有独立世界设置和静态工具计划。原90名单保留原ID，不自动切到WOFOST。

| 任务 | 经典版ID／源码 | WOFOST版ID／源码 | WOFOST校准状态 |
|---|---|---|---|
| 01 正常季 | [`scenario_full_season_hb_base_hn84_std_normal`](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_base_hn84_std_normal.py) | [`scenario_full_season_hb_base_hn84_std_normal_V2`](../fairy/scenarios/wofost/scenario_full_season_hb_base_hn84_std_normal_V2.py) | 已校准 |
| 02 R5/R6限水干旱 | [`scenario_full_season_hb_dryr5r6_hn84_water_limit`](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_dryr5r6_hn84_water_limit.py) | [`scenario_full_season_hb_dryr5r6_hn84_water_limit_V2`](../fairy/scenarios/wofost/scenario_full_season_hb_dryr5r6_hn84_water_limit_V2.py) | 已校准 |
| 03 花期营养 | [`scenario_full_season_hb_low_nutrient_carryover_flowering_nutrition`](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_low_nutrient_carryover_flowering_nutrition.py) | [`scenario_full_season_hb_low_nutrient_carryover_flowering_nutrition_V2`](../fairy/scenarios/wofost/scenario_full_season_hb_low_nutrient_carryover_flowering_nutrition_V2.py) | 未校准 |
| 04 只准机械控草 | [`scenario_full_season_hb_high_weed_seedbank_mechanical_only_baseline`](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_high_weed_seedbank_early_control.py) | [`scenario_full_season_hb_high_weed_seedbank_mechanical_only_baseline_V2`](../fairy/scenarios/wofost/scenario_full_season_hb_high_weed_seedbank_early_control_V2.py) | 已校准 |
| 05 灌浆期食叶虫 | [`scenario_full_season_hb_r5_leaf_feeder_defoliation`](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_r5_leaf_feeder_defoliation.py) | [`scenario_full_season_hb_r5_leaf_feeder_defoliation_V2`](../fairy/scenarios/wofost/scenario_full_season_hb_r5_leaf_feeder_defoliation_V2.py) | 已校准 |
| 06 有限药剂预算 | [`scenario_full_season_hb_limited_spray_budget_season`](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_limited_spray_budget_season.py) | [`scenario_full_season_hb_limited_spray_budget_season_V2`](../fairy/scenarios/wofost/scenario_full_season_hb_limited_spray_budget_season_V2.py) | 已校准 |
| 07 雨间施药短窗 | [`scenario_full_season_hb_wetjune_short_spray_window`](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_wetjune_short_spray_window.py) | [`scenario_full_season_hb_wetjune_short_spray_window_V2`](../fairy/scenarios/wofost/scenario_full_season_hb_wetjune_short_spray_window_V2.py) | 已校准 |
| 08 病后干旱辨因 | [`scenario_full_season_hb_disease_then_drought_recovery_tradeoff`](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_disease_then_drought_recovery_tradeoff.py) | [`scenario_full_season_hb_disease_then_drought_recovery_tradeoff_V2`](../fairy/scenarios/wofost/scenario_full_season_hb_disease_then_drought_recovery_tradeoff_V2.py) | 已校准 |
| 09 草病冠层混淆 | [`scenario_full_season_hb_weed_then_disease_canopy_confusion`](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_weed_then_disease_canopy_confusion.py) | [`scenario_full_season_hb_weed_then_disease_canopy_confusion_V2`](../fairy/scenarios/wofost/scenario_full_season_hb_weed_then_disease_canopy_confusion_V2.py) | 已校准 |
| 10 降雨打断除草 | [`scenario_full_season_hb_herbicide_window_missed_rain_delay`](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_herbicide_window_missed_rain_delay.py) | [`scenario_full_season_hb_herbicide_window_missed_rain_delay_V2`](../fairy/scenarios/wofost/scenario_full_season_hb_herbicide_window_missed_rain_delay_V2.py) | 已校准 |
| 扩展01 局部快失水干斑 | [`scenario_full_season_fastdraining_dry_patch_irrigation`](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_fastdraining_dry_patch_irrigation.py) | [`scenario_full_season_fastdraining_dry_patch_irrigation_V2`](../fairy/scenarios/wofost/scenario_full_season_fastdraining_dry_patch_irrigation_V2.py) | 已校准 |
| 扩展02 两干斑分配有限水 | [`scenario_full_season_hb_two_dry_patches_one_irrigation`](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_two_dry_patches_one_irrigation.py) | [`scenario_full_season_hb_two_dry_patches_one_irrigation_V2`](../fairy/scenarios/wofost/scenario_full_season_hb_two_dry_patches_one_irrigation_V2.py) | 已校准 |
| 扩展03 高密度晚季干旱 | [`scenario_full_season_hb_hn60_high_fastdrain_dryr5r6`](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_hn60_high_fastdrain_dryr5r6.py) | [`scenario_full_season_hb_hn60_high_fastdrain_dryr5r6_V2`](../fairy/scenarios/wofost/scenario_full_season_hb_hn60_high_fastdrain_dryr5r6_V2.py) | 已校准 |

文件名与类名也成对存在。例如正常季：

| 身份 | 经典版 | WOFOST版 |
|---|---|---|
| 文件 | `scenario_full_season_hb_base_hn84_std_normal.py` | `scenario_full_season_hb_base_hn84_std_normal_V2.py` |
| 类 | `ScenarioFullSeasonHBBaseHN84StdNormal` | `ScenarioFullSeasonHBBaseHN84StdNormal_V2` |

其余12对同样在经典文件名与类名末尾分别增加`_V2`。注意04的注册ID为`high_weed_seedbank_mechanical_only_baseline`，文件名却是`high_weed_seedbank_early_control`；不能只根据ID猜文件名。清单逐项保存完整路径和类名。

## 如何运行两个版本

在包含这些改动的仓库根目录执行。每个版本先捕获自己的静态Oracle，再用自己的场景重放；不要共享同一产物目录。

经典正常季：

```bash
uv run python -m fairy.cli \
  --scenario scenario_full_season_hb_base_hn84_std_normal \
  --build-oracle --replay --evaluate \
  --output-dir validation_runs/classic_normal
```

WOFOST正常季：

```bash
uv run --extra wofost python -m fairy.cli \
  --scenario scenario_full_season_hb_base_hn84_std_normal_V2 \
  --build-oracle --replay --evaluate \
  --output-dir validation_runs/wofost_normal_V2
```

`_V2`场景自行声明WOFOST后端，不需要再加`--crop-backend wofost`。运行其他表中任务时，把`--scenario`与产物目录一起替换。`--build-oracle`捕获文件里写好的工具图；`--replay`执行真实工具及其耗时、库存和物理结算。这些命令不调用LLM。

经典版detail/context和原90名单示例继续使用原ID。它们属于经典版实验入口，不能机械地加`_V2`后沿用旧资料库或旧workflow。

## 原代码保存在哪里，兼容修改允许做到哪里

经典源码恢复来源为Git提交`e0a302c3d3de9cf532ea5fd01bc79ebb3e9bb864`。13份原始文件另完整保存在[原始经典源码备份](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/legacy_sources>)，可与Git对照。活跃经典文件的兼容修复只涉及两类workflow变化：把原来会被截断的16／64垄检查改为明确的4垄代表性抽样，不再把样本冒充全田检查；另3场在原天气下分别多等3/1/1天，满足原收获与储藏门槛后再采收。

这项兼容修复不改变经典初始题设、天气、品种、作物物理或管理目标；没有改动App、Engine或TimeManager，也不会把旧版套上WOFOST模型。[最终初始世界对照](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/legacy_compatibility/original_vs_current_initial_world.json>)确认13/13与原Git定义一致：比较在同一当前legacy运行时、既有helper与固定初始时钟下进行，不声称整个运行库恢复成e0。修复后的活跃经典文件不能再声称与原始备份字节相同。WOFOST文件的ID、文件名、类名已重命名，农艺配置是否变化与源码哈希是否变化应分别核对。

[6个文件的逐项修改说明](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/legacy_compatibility/code_change_notes.md>)列出5个叶文件和1个batch helper的实际变更；[workflow兼容审计](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/legacy_compatibility/workflow_compatibility_audit.json>)核对原步骤ID、采样范围、等待节点与真实收储，[活跃源码哈希](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/legacy_compatibility/active_source_hashes.json>)区分原备份和当前兼容文件。

## 当前完成与核验边界

- **WOFOST农艺校准：12套完成，03未校准。** 前10套中9套完成，另完成本轮3个灌溉题。03即使能全季运行，也不能算“花期追肥有效”的校准通过；土壤氮事件支持与考点成立是两项不同结论。
- **本轮3个灌溉题：** 各8个管理窗口、101次实际调用，均有Sensor根水与冠层→SurveyDrone全田粗查→Robot定点样本。按13%水分入库分别7097.36、7005.65、6649.92kg；全田等效用水分别65.625/66、65.625/66、67.5/68mm（实际/额度）。它们已完成版本拆分前真实CLI回放和原生对照。
- **无人机范围：** 前9套已校准方案此次只做版本命名拆分，没有全部追加UAV；不能说13套都完成了无人机链路。
- **新命名空间验收：** [13套`_V2`新鲜生产CLI回放](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/wofost_replay_summary.json>)全部通过build→replay→evaluate。12套已校准方案的入库量与改名前参照完全一致；03为233次调用、8229.50kg，仍未校准。新增3场还通过源码→纯构建→新命名CLI Oracle／replay→原试跑工具与时序的核查。
- **经典版验收：** [13套普通生产CLI最终全季回放](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/legacy_compatibility/summary.json>)均通过，每场64垄全部收割、安全入库大于0。不是只检查`validate()`未报错，而是另查实际收割覆盖和仓库结果。
- **暂停范围：** 新增20名单中的第4—20共17场暂停，不继续校准或发布，不计完成。
- **Agent范围：** 当前结果来自静态Oracle的真实工具回放，尚未运行35B Agent，不能当作模型的自主决策成绩。

[前10套农事计划](wofost-farming-plans.md)、[新增3套农事计划](wofost-next20-farming-plans.md)、[前10套发布状态](../configs/oracles/wofost_formal10_release_status.json)与[扩展名单状态](../configs/oracles/wofost_next20_release_status.json)分别保存管理与范围。测试数量以对应批次的独立证据为准；早期507／529项回归记录不能代替本次13对版本的最终验收。

本次最终[相关广泛回归JSON](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/related_regression.json>)记录**644项通过、0失败、0错误、0跳过，50.95秒**，另保留[完整日志](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/related_regression.log>)与[JUnit](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/related_regression.xml>)。范围包括原生模型、版本与源码契约、经典workflow兼容及App／共享运行时，**不是全仓库测试声明**。独立27项版本隔离检查和经典正常季2项smoke也通过，不把可能重叠的测试数相加。

其中一个天气smoke原断言把“连续4天事件合计82mm”固化成“单日大于80mm”。本轮只修测试，以配对背景天气核验4天增量合计82mm；没有改生产天气或物理。[修正说明](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/weather_smoke_correction.md>)保存原失败原因、控制组和逐日公开天气／物理输入一致性检查，早期529项命令未包含这项完整smoke，不能倒推其当时已验证。

## 怎样读历史报告

版本拆分前，一些无后缀ID曾直接运行WOFOST。已有报告、Oracle和研究记录保留当时名称及来源，不批量改写这些历史证据。**同一段旧ID文字今天选择经典版，不代表该历史结果来自经典模型。** 查报告时同时看生成日期、后端、参数来源、源码哈希和版本清单。

旧无后缀WOFOST轨迹不能直接交给今天同名经典版重放；应使用对应`_V2`源文件重新构建Oracle。原90名单、论文实验与context资料库的ID也不因这次拆分自动改变。
