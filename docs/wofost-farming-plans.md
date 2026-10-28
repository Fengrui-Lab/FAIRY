# 先读农事计划，再看工具调用

本文说明最初选出的10套WOFOST方案，其中9套已完成农艺校准，03仍是花期营养题并明确未校准。**当前WOFOST的ID、文件名、类名都带`_V2`；无后缀的原名已恢复为经典`legacy`版。** 下文活跃源码链接均指向`_V2`文件；13套`_V2`已重新完成普通生产CLI的build→replay→evaluate，12套已校准方案的入库量与改名前参照完全一致。经典版另13套全部完成全季CLI回放、64垄全收安全入库，初始世界与原Git定义13/13一致。两版本对应关系及证据见[13对名称表](wofost-scenario-versions.md)。

本轮另完成[3个灌溉题](wofost-next20-farming-plans.md)，它们都加入真实SurveyDrone粗查与Robot定点检查，每场8窗口、101次调用。前9套此次只拆版本名称，没有全部补无人机。13套WOFOST共12套已校准、03未校准；扩展名单余下17场暂停。

每场都是单农场、64垄，每垄268×1.1m，共28.3008亩。下文日期均为2019年当地日历；入库量按13%商品水分质量计算。结果是这个模拟世界的实际工具回放，不是田间实测或大模型Agent成绩。

## 正常季应该怎样读

[正常季WOFOST源文件](../fairy/scenarios/wofost/scenario_full_season_hb_base_hn84_std_normal_V2.py)先写`FARMING_PLAN`，用7个管理窗口讲清一季；然后才在`build_events_flow()`中展开成89次真实工具调用：

1. **4月28日，整地播种。** 查播床与天气，整地、起垄，一次完成全田播种；不例行施氮肥。
2. **5月13日，查出苗。** 地面抽查4垄，出苗正常，不补播。
3. **5月28日，查杂草。** 看全田冠层和4垄地面样本，无草害，不除草。
4. **6月28日R1，查花期状态。** 水分和营养尚可，不灌水、不追氮。
5. **7月20日R3，第一次补水。** 根区亏水且近期少雨，全田一次30mm。
6. **8月8日R5，第二次补水。** 再次确认根区亏水，全田一次30mm。
7. **9月20日，成熟收储。** 核对成熟、含水率和通行性后，全田收割，合为6批收储。

七个管理窗口不等于七次工具调用。当前播种、收割工具每次最多4垄，因此各有16个机趟；装种受30万粒种箱限制，卸粮受2t粮箱限制。89次也包括观察和真实等待。这里没有把89次调用称为89次农事，或声称已经证明所有调用达到最少。

这一季实际灌水60mm、施氮肥产品0kg，安全入库**9134.24kg**。[当前`_V2`正式报告](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/wofost_replay/01/scenario_full_season_hb_base_hn84_std_normal_V2.run_report.json>)记录全部回执，入库量与[改名前WOFOST报告](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_agronomic_redesign_20261026/final/01/scenario_full_season_hb_base_hn84_std_normal.run_report.json>)相同；旧报告名无后缀不能当作今天同名经典版的成绩。旧小水方案252次调用、44次灌水和重复的水前读取只作为历史保留，不再代表当前正常季。

## 出题与管理使用同一套标准

- **原考点保留。** 机械控草仍不能用除草剂，限药仍要分配药剂，病后干旱仍要重新辨因；不因为难校准而换题。
- **设置必须支持合理处置。** 连雨题提供明确雨间窗口；预算够完成一轮正常剂量，而不是差几克迫使任意切剂量；允许余下水量不用。
- **正常豆作不例行施氮。** 已更新的9场取消原60kg例行氮肥。官方`NFIX_FR=0.8`保留，但这不是结瘤形成、失效或根瘤检查模型。03本轮不扩展新机制，保留为未校准。
- **灌水按有意义的轮次。** 根区亏缺、公开阶段和降雨预报支持时才安排整轮；使用20mm保苗或30—40mm阶段补水，不按每日计数补8—10mm，也不用小数尾水填额度。
- **诊断是抽样。** 地面4垄样本不冒充全田逐垄检查；置信度不当作虫害严重度。病、虫、草的注入与演化明确声明，处理不会自动清除全部压力。

上述氮肥例外条件和灌溉量级可参照[Terres Inovia大豆氮管理](https://www.terresinovia.fr/-/pas-d-engrais-azote-sur-soja-sauf-en-cas-de-defaut-de-nodulation)、[按土层与生育阶段安排灌溉](https://www.terresinovia.fr/en/technical-information/soja/irrigate-stabilize-yield-and-maintain-high-protein-content)。这些资料用于约束候选管理的常识范围，不把某地区推荐直接冒充Lille2019的田间标定。

## 01｜正常季

- **原考点：** 无额外灾害时，完成正常全季管理。
- **设定变化：** 保留Lille2019天气、原土壤及901参数组；去掉例行氮底肥和频繁小水规则。
- **合理操作：** 上述7个窗口；4月28日播种，7月20日和8月8日各补30mm，9月20日收储。
- **正式结果：** **9134.24kg，89次工具调用。**

## 02｜R5/R6干旱与限水

[完整WOFOST场景](../fairy/scenarios/wofost/scenario_full_season_hb_dryr5r6_hn84_water_limit_V2.py)

- **原考点：** 干旱期分配有限水量，照顾22—43垄优先区。
- **设定变化：** 保留Valladolid2019天气、干旱事件及分区土壤；额度改为全田等效240mm。完整正常轮灌参考为260mm，不再沿用小脉冲搜索的360mm/320mm。
- **合理操作：** 4月30日播种；5月10日全田20mm保苗；6月19、27日和7月5、13、21日各全田40mm；7月29日只给22—43垄40mm。共7轮，用233.75mm，余6.25mm不用；8月12日收割并分4批入库。
- **正式结果：** **6588.87kg，104次工具调用。**[当前`_V2`正式报告](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/wofost_replay/02/scenario_full_season_hb_dryr5r6_hn84_water_limit_V2.run_report.json>)

这里的40mm是受水区域的局部水深。最后22垄占全田22/64，因此末轮计入全田额度`40×22/64=13.75mm`，不是全田又灌40mm。参考260mm是20mm保苗加6轮全田40mm的量级对照，不是全球最优或99%平台证明。

## 03｜低氮供给与花期营养

[未校准的WOFOST场景文件](../fairy/scenarios/wofost/scenario_full_season_hb_low_nutrient_carryover_flowering_nutrition_V2.py)

- **原考点保留：** 前期氮供给偏低，花期根据营养状况决定管理。
- **核查结果：** 固定作物、天气、土壤及水量的5组对照中，花期施氮最大增产约0.072%，不能支持“识别花期缺氮并追肥救产”的有效题设。旧公开营养值使用的`RFRGRL`是特定幼苗阶段的叶面积增长限制因子，不能当成一般花期缺氮诊断。
- **处理方式：** 保留已有未校准农艺配置；本轮不扩展新结瘤或花期氮胁迫机制，不直接修改公开营养数值制造效果，也不把题换成灌溉或跳肥题。新增土壤氮事件接口的对照也没有使原考点成立，详见[氮事件与固定对照](wofost-soil-nitrogen-events.md)。
- **当前结果：** **未校准，不计校准完成。** 活跃文件已改为`_V2`，ID、类名及校准状态元数据相应变化，不能称源码逐字不变。[当前新鲜回放](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/wofost_replay/03/scenario_full_season_hb_low_nutrient_carryover_flowering_nutrition_V2.run_report.json>)可全季执行，仍为233次调用、8229.50kg；这不是追肥考点有效的证据，不混入9场校准成绩，也不当作经典版的结果。[诊断核验](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_agronomic_redesign_20261026/flowering_nitrogen_diagnostics/verification.json>)、[发布状态清单](../configs/oracles/wofost_formal10_release_status.json)分别保存模型原因和版本状态。

## 04｜高草库、只准机械除草

[完整WOFOST场景](../fairy/scenarios/wofost/scenario_full_season_hb_high_weed_seedbank_early_control_V2.py)

- **原考点：** 全田草害，化学额度为0，最多7趟机械作业、累计64垄。
- **设定变化：** 保留种子库和分批出草，取消例行氮肥；将处置放在草害出现后的可通行窗口。
- **合理操作：** 4月28日播种；5月25日看冠层与代表性地面样本，5月26日完成一轮全田机械除草，分7个机趟；7月20日和8月8日各补30mm，9月20日收储。
- **正式结果：** **8068.64kg，101次工具调用。**

## 05｜灌浆期食叶虫

[完整WOFOST场景](../fairy/scenarios/wofost/scenario_full_season_hb_r5_leaf_feeder_defoliation_V2.py)

- **原考点：** 16—39垄在灌浆阶段遭遇虫害，及时确认并处理。
- **设定变化：** 保留905/Bologna及虫害目标区；7月17日注入一次虫压力，之后按现有模型演化，不再连续重置压力抵消早处理；保留7月18日起的无雨低风窗口。
- **合理操作：** 4月30日播种；7月18日样本诊断后，用8L/垄工作液处理24垄，共192L、3趟；7月5、20、30日分别按R3/R5/R6实际缺水补30mm，9月4日收储。
- **正式结果：** **6400.70kg，96次工具调用。**

虫害仍通过FAIRY外接总同化胁迫影响WOFOST，尚未直接模拟原生叶面积被虫啃掉。

## 06｜先轻虫、后重虫，药量有限

[完整WOFOST场景](../fairy/scenarios/wofost/scenario_full_season_hb_limited_spray_budget_season_V2.py)

- **原考点：** 不能把药剂在早期虫情出现时就用尽，需分配到后续问题。
- **设定变化：** 有效成分额度由0.22改为0.24kg。早期20垄完整施药需0.160kg，后期28垄需0.224kg，两轮合计0.384kg；因此够一轮重虫处理，不够两轮都做。虫情由公开虫量档位和样本解释，置信度不是严重度。
- **合理操作：** 4月28日播种；6月27日在第20垄检查到低档位虫情，先观察；7月21日确认后期虫害，对18—45垄完整施药8L/垄，共224L、3个机趟，计1个施药日；7月20日和8月8日各补30mm，9月20日收储。
- **正式结果：** **8660.16kg，107次工具调用。** 用药0.224kg，剩余0.016kg。

## 07｜连续降雨中的短施药窗口

[完整WOFOST场景](../fairy/scenarios/wofost/scenario_full_season_hb_wetjune_short_spray_window_V2.py)

- **原考点：** 病害已出现，在连雨之间识别并利用可作业短窗。
- **设定变化：** 在两段降雨之间明确保留6月22—24日无雨、低风窗口；后面6月25日起再次降雨。7月初只是错过后的恢复窗口，不再设计成整段时间都绝对无法喷药。
- **合理操作：** 4月28日播种；6月23日在短窗中对18—45垄杀菌，3.8L/垄，共106.4L；7月20日水分尚可不灌，8月8日补30mm，8月21日复核后不追加，9月20日收储。
- **正式结果：** **8213.34kg，101次工具调用。**

## 08｜病害管理后再遇干旱

[完整WOFOST场景](../fairy/scenarios/wofost/scenario_full_season_hb_disease_then_drought_recovery_tradeoff_V2.py)

- **原考点：** 先处理20—43垄病害，后续长势异常时重新辨因，不能只重复上一种管理。
- **设定变化：** 病压力在6月19日一次注入，保留8月1—16日干旱。额度为全田等效11.25mm，刚好支持目标24垄一次30mm；不用隔日小水或0.667mm尾水。
- **合理操作：** 4月28日播种；6月22日杀菌3.8L/垄；8月1日复核根水、冠层与代表性地面样本后，对20—43垄一次补30mm；9月20日收储。
- **正式结果：** **7258.34kg，99次工具调用。**[当前`_V2`正式报告](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/wofost_replay/08/scenario_full_season_hb_disease_then_drought_recovery_tradeoff_V2.run_report.json>)

公开诊断仍可能显示残病，不能写成“病已完全清除”或“再杀菌无效”。同日对照的全田原生产量为：不处理3302.88、再杀菌3386.79、补水3489.18kg干物质/ha；这轮补水的收益更大。35mm局部单轮参考折合全田13.125mm，属于正常轮灌量级对照，不是99%平台或田间最优证明。[对照与真实输入核验](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_agronomic_redesign_20261026/water_candidates/selection_report.json>)

## 09｜先草害、后病害，冠层信号混淆

[完整WOFOST场景](../fairy/scenarios/wofost/scenario_full_season_hb_weed_then_disease_canopy_confusion_V2.py)

- **原考点：** 相似冠层异常可能来自不同原因，处理类型和区域不能混淆。
- **设定变化：** 保留4—23垄草害、32—51垄后期病害及原处理类型；病压力改为一次注入后演化，不反复重置；取消例行氮肥和每日轮询。
- **合理操作：** 4月28日播种；5月31日对草区机械除草20垄、2趟；6月28日对病区杀菌3.8L/垄，共76L；7月20日暂不灌，8月8日和21日各补30mm，9月20日收储。
- **正式结果：** **8401.71kg，107次工具调用。**

## 10｜降雨打断除草，雨后恢复

[完整WOFOST场景](../fairy/scenarios/wofost/scenario_full_season_hb_herbicide_window_missed_rain_delay_V2.py)

- **原考点：** 计划除草遇到降雨，判断暂缓，并在雨后恢复管理。
- **设定变化：** 让12—45垄在5月24—26日分批出草，5月24—29日连续降雨；保留总雨量64mm，调整日期使5月27日确有草害和被雨阻断的决策。
- **合理操作：** 4月28日播种；5月27日查雨情和冠层后暂缓施药，不耗药；6月1日对34垄恢复除草，8L/垄，共272L、4趟；8月8日和21日各补30mm，9月20日收储。
- **正式结果：** **8416.50kg，104次工具调用。**

## 代码、结果与能力边界

前9个已校准`_V2`文件完整声明`WORLD`、事件、`FARMING_PLAN`及字面工具调用；03的`_V2`保留已有未校准农艺配置。`FARMING_PLAN`供人审阅，不是运行时优化器；`--build-oracle`只捕获已经写好的计划，不推进农场。真实工具在`--replay`时结算作业、库存、时间和约束。运行命令见[接入说明](wofost-integration.md#如何运行写好的workflow)。经典版来源、版本名、独立文件和兼容边界见[版本说明](wofost-scenario-versions.md)。

9个已校准方案的正式产物保存在[版本拆分前final目录](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_agronomic_redesign_20261026/final>)。[该批独立产物核验](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_agronomic_redesign_20261026/independent_static_artifact_audit.json>)9/9通过：源码纯构建、计划空响应、工具参数与依赖、名称及时间、实际收储和额度分别检查。它记录当时无后缀ID下的WOFOST执行，不是恢复经典版后的验收。

当前13套`_V2`的[新鲜CLI回放汇总](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/wofost_replay_summary.json>)均通过普通生产CLI的build→replay→evaluate；12套已校准方案产量与改名前参照完全一致，03可运行而未校准。经典版的[最终全季回放汇总](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/legacy_compatibility/summary.json>)与[最终初态对照](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/legacy_compatibility/original_vs_current_initial_world.json>)分别确认13场全收安全入库、13/13原题设在同一当前legacy运行时下初始世界一致；兼容修复涉及明确的4垄代表性采样与3场多等3/1/1天采收，不是保持源码逐字不变。[6文件逐项修改说明](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/legacy_compatibility/code_change_notes.md>)列出具体原因和边界。

[历史结果JSON](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_agronomic_redesign_20261026/results.json>)、[CSV](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_agronomic_redesign_20261026/results.csv>)保存该批9场结果及03未校准状态。同9场的工具调用合计由2388变为908，03不计；不能把不同入选范围的总数混着比较。[该批相关回归](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_agronomic_redesign_20261026/regression.json>)为507项通过、0失败、0错误、0跳过。它早于土壤氮事件529项记录和当前版本拆分，不能替代当前13对版本的回放核验，也不是全仓库测试声明。

当前版本拆分和经典workflow兼容的[相关广泛回归](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/related_regression.json>)已**644项通过，0失败、0错误、0跳过，50.95秒**，覆盖原生模型、版本／源码契约、经典workflow与App／共享运行时，仍不等于全仓库测试。另有一个旧天气smoke断言更正，验证4天事件增量合计82mm，而非每天82mm；[依据](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/version_split/weather_smoke_correction.md>)保留初次失败和修正过程，生产天气未修改。

四组官方参数与固定2019公开天气继续使用，密度候选仍为901/905每平方米45株、903每平方米40株；03原902配置为60株。它们不是商业品种名称或官方推荐密度。原YAML未改，45/60密度通过既有适配器将有效TDWI改为135/180，其余77项保留官方值。

本轮没有新增Engine农艺入口，也没有把全部作业封成一个假工具来降低计数。施底肥是否必做由每场显式声明；旧场景默认仍要求整地、底肥、起垄，新的正常豆作场景可明确只要求整地、起垄，不伪造已施肥标记。当前`dry_grain`仍是零耗时、无能源结算的即时抽象，不能称为真实连续烘干机。

[上一轮密度与小脉冲方案](wofost-formal10-refinement.md)保留历史证据；其2621次调用、正常季252次调用以及320/11.5mm额度，不再代表当前方案。新增3场另见[扩展计划](wofost-next20-farming-plans.md)，余下17个扩展任务暂停；不把暂停项算完成。当前没有35B Agent的这13场成绩。
