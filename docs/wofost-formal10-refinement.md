# 原10场景的密度、限水与固定工作流精简

> 历史记录（2026-10-25）：下述小脉冲方案、正常季252次调用和全批2621次调用已被[本轮农事计划](wofost-farming-plans.md)部分替代。原试验与回放证据保留，不能当作当前9个新方案的农艺依据或最新成绩；03仍保留原题并标为未校准。

本轮继续修改原90名单中的同10个文件，保留原ID、单场64垄以及每垄268×1.1m的几何。目标是明确管理依据、删除重复步骤，并把必要说明直接保存在固定工作流的`name`中。每个场景仍在本文件内完整声明`WORLD`、事件与字面工具调用；构建不运行优化器、不读取回执决定下一步，也不读取运行结果JSON。

**状态：本轮10/10正式CLI鲜回放和独立产物审计全部通过，484项相关回归无失败、错误或跳过。固定步骤合计6783→2621，减少61.36%。** 下文的原生扫描、两区原型、预审64垄验证与正式CLI结果分别说明，不把它们混成一次完成验收。上一轮40株/m²、旧1.8/6mm额度下的[已归档结果](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_formal10_rewrite_20261025/results.json>)保持原样，不能当成本轮修改后的结果。

## 品种身份、密度与有效参数

四个种子保留官方原名：`SOYBEAN_901/902/903/905`分别使用北法、中法、北西班牙、意大利的区域参数组。固定[官方YAML](https://github.com/ajwdewit/WOFOST_crop_parameters/blob/1ca91d7dbb5aaf6b41462162de03a8254812d3a5/soybean.yaml)和本地SHA不变；没有把欧洲参数改名为中国商业品种。旧ID中的HN84等只是兼容标识。

| 官方组/固定2019地点 | 本轮目标株数/m² | 双行株距cm | 每垄实际整数粒数 | 64垄用种 | 有效TDWI kg干物质/ha |
|---|---:|---:|---:|---:|---:|
| 901 / Lille | 45 | 4.040404… | 13266 | 849024 | 135 |
| 902 / Clermont-Ferrand | 60 | 3.030303… | 17688 | 1132032 | 180 |
| 903 / Valladolid | 40 | 4.545454… | 11792 | 754688 | 120 |
| 905 / Bologna | 45 | 4.040404… | 13266 | 849024 | 135 |

902场景将种子库存明确改为120万粒，才能供给1132032粒的实际需求；播后仓库应余67968粒。其他三组仍可由100万粒供给。这里的株数按当前名义成苗率1计算，不把实际田间发芽损失或缺苗补播能力假装成已验证机制。

换算关系为：

```text
株距cm = 200 / (1.1 × 目标株数/m²)
每垄粒数 = round(268 × 2 × 100 / 株距cm)
实际密度 = 每垄整数粒数 / 294.8m²
有效TDWI = 官方120 × 实际密度/40 × 初始成苗率1
```

**原文件的78项基准未改，不等于每次运行的78项有效输入均未改。** 45和60密度分别将TDWI改为135和180，其余77项保留官方值；903在40密度下仍全部78项相同。`reference_density_plants_m2=40`是FAIRY适配器的初始生物量归一化，不是原研究已证实的最佳株数。TDWI120本身是初始干物质量，不是40株/m²的田间密度证明。当前密度作用仅通过TDWI初始化，未模拟单株竞争、分枝补偿、倒伏随密度变化或田间经济最优。

## 密度选择的实际证据和边界

[完整扫描](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/density_sweep.json>)使用PCSE6.0.13的`Wofost81_NWLP_CWB_CNB`，共82个原生运行：四组各测15、20、25、30、35、40、45、50、55、60株/m²，两种水分条件共80组，另对902/903充分供水组测试80株/m²作边界诊断。

同一品种、水分组内，除有效TDWI外输入保持一致：同一固定NASA POWER2019日天气，1.2m土层，初始VWC0.26，萎蔫/田容/饱和0.10/0.30/0.45，初始和基础土壤N各50kg/ha，CO₂420ppm，底肥31.8012kg产品/ha，N比例0.46、回收率0.7；没有外加病虫草耦合。每个代表垄面积294.8m²。

两种条件分别是雨养，以及播后第0—146天每两天固定12mm的供水对照，合计毛水888mm、有效816.96mm。后者只用于稳定水分条件下的模型比较，实际报告RFTRA最低值为1、土壤最大含水率约0.4379；它不是给正式场景推荐的灌溉计划。官方`IOX=0`也意味着该对照不能证明这些供水量在田间不存在缺氧风险。

| 固定供水核心网格 | 网格内最高产密度 | 原生TWSO kg干物质/ha | 结论限度 |
|---|---:|---:|---|
| 901 | 45 | 4367.399 | 所测离散网格的内部最高值 |
| 902 | 60 | 4126.499 | 核心网格上边界；80诊断组仍升至4140.358，不能称全域最优 |
| 903 | 60 | 3904.444 | 充分供水扫描结果；正式限水场另做密度×时机对照，选40 |
| 905 | 45 | 3540.493 | 所测离散网格的内部最高值 |

这四个TWSO是模型籽粒干物质，不是正式64垄的入库kg。四组雨养扫描都在所测下边界15株/m²取得最高值，说明结果依赖水分条件；不能把固定供水的45/60直接推广为无灌溉田块最优值。99%平台的最低密度与最大产量密度也是两列不同指标，见[完整选择表](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/density_candidate_selection.csv>)。

903在320mm限水条件下，又比较了25、35、40、45、55、60密度与已执行的多种管理时机组合；40密度、`observed_t24`原型的面积加权TWSO为3582.949kg干物质/ha，是该已测邻域的最高记录。它不等于连续密度或所有可能水时机的全局搜索。

[输入与复跑检查](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/density_repeatability.json>)覆盖八个水分×品种组，并对八个选择点作鲜原生复跑，结果及逐日CSV字节完全一致。[真实工具确认](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/density_tool_confirmation.json>)另有14次实际整地、装种、播种及雨养全季运行，实际整数密度、有效TDWI和其余77项一致，所测TWSO与相同输入原生对照差为0。它验证密度映射，不把888mm科学对照当生产Oracle。

[密度响应图PNG](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/density_response.png>) / [PDF](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/density_response.pdf>)展示上述受控扫描；横轴是当前适配器实现的密度处理，不能当作田间密度试验图。

现有[文献证据审查](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/density_evidence.json>)没有找到能把官方901等区域组唯一对应到商业品种、当前熟期组及其田间最优密度的资料。因此本轮选择属于明确的模型对照结果，不声称来自这些具体品种的田间密度标定。

## 两个限水场的参考量和新额度

旧1.8mm和6mm额度在本轮重新校准，没有把它们偷偷保留为当前值。新额度低于已测近平台参考，仍要求按阶段和区域分配资源。

| 场景 | 代表区与面积权重 | 当前密度 | 已测99%近平台参考 | 本轮正式额度 | 额度/参考 |
|---|---|---:|---:|---:|---:|
| 02 干旱限水 | 普通42/64，优先快排22—43垄占22/64 | 40 | 360mm | 320mm | 88.89% |
| 08 病后干旱 | 20—43垄占24/64，其他垄不补水 | 45 | 13mm | 11.5mm | 88.46% |

以上均为**全田面积等效毛灌水mm**，不是目标垄局部水深。管理灌水进入原生时统一使用全局`irrigation_efficiency=0.92`，不是优先区工程modifier中的0.86；该0.86与`root_drainage_rate=0.26`都未映射为各区独立的WOFOST原生参数。目标区实际进入原生的水文区别来自FC0.31、降水集水比例0.82（对应NOTINF0.18）及入渗85mm/d。02按`(普通区局部水深×42+优先区局部水深×22)/64`记账；08按`局部水深×24/64`记账。例如08局部合计30⅔mm对应全田11.5mm，不能把两者混为一项剂量。

参考点来自同一既定天气、土壤、事件和密度下的有限原型搜索。02所测最高TWSO3802.223，360mm的`observed_t26_reserve`为3765.749，达到99.041%；350mm的同策略为98.328%。08所测最高3549.693，13mm的`observed_t24/t28`为3514.405，达到99.006%；12.8mm为98.932%。因此360和13是各自已测候选集合中的99%参考点，不是理论最小充分灌溉量，也不是现实灌区定额。

本轮320/11.5mm日历已写入各场本地静态源码，并完成正式64垄CLI鲜回放。其[02输入与日历](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/irrigation/plans/case02_good/plan_metadata.json>)、[08输入与日历](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/irrigation/plans/case08_good/plan_metadata.json>)保留选择阶段的原型、面积权重、目标区和文件SHA，最终依据另见文末正式表。02预审曾暴露水账逐笔取整导致末笔误拒，失败记录保留；水账窄修后已通过真实64垄复测。

02也完成了同预算的真实64垄对照：两组都用320mm，好安排TWSO3582.949、较差安排3152.259kg干物质/ha；安全入库分别7537.03与6631.08kg，较差安排下降12.02%。[对照记录](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/irrigation/plans/case02_moderate_bad/plan_metadata.json>)同时改变分区总量、频次和日期，属于同预算的分区安排比较，不是纯日期对照。

08另做了严格的日期对照：保持20—43垄、4次局部毛水10/10/10/⅔mm、全田11.5mm及其他管理不变，将整套水脉冲整体后移32天至R7。[原型与64垄验证记录](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/irrigation/plans/case08_late_same_pulses/plan_metadata.json>)显示，原时机TWSO3493.519、后移3405.785kg干物质/ha，下降2.51%；64垄对应入库7267.70与7087.82kg，下降179.88kg（2.48%）。这可称当前模型内、同脉冲只改日期的对照。02的好坏计划还改变了同预算下的分区和阶段分配，不能称纯日期效应。

## 保留哪些步骤，为什么不能继续只按总量计步

播种与收割工具每趟最多4垄，因此64垄各需要16趟。这个硬限制与装种、卸粮、储藏的次数是不同问题。

- **种箱批装。** 45密度每4垄需要53064粒，本计划保留最少16个4垄整趟；30万粒种箱最多支持5个完整播种趟次。尽管`ceil(849024/300000)=3`，三个装料区间最多完成15趟，仍差最后一趟，因此需要4次装料。若为少装一次而改成更多小趟，会增加播种次数、时间与油耗。批装可以保留余种，例如300000、265320、265320、18384粒，总计849024，不再每4垄单独装一次。60密度每趟70752粒，一箱最多4趟，也需4次装料；40密度一箱可6趟，3次即可，最终实际次数以本场固定计划和回放为准。
- **油按作业预算。** 268m几何下，整地三项共24L，播种和收割共64L，基准总耗88L，初油100L足够。追加7趟追肥或机械作业的两场总耗102L，需要补足缺口和明确的安全余量；其余场不能仅因旧helper剩油20L门槛而补满。每次补油仍是仓库到机上真实转移。
- **灌溉合并。** FieldOps没有11垄硬上限。同日、同水深、同土壤区的相邻范围可合并；不同土区、不同水深或中间有不灌垄时分开。逐垄水量和全田额度必须守恒。合并会改变泵作业持续时间及2小时效果等待，必须重算真实等待并鲜回放，不能只删节点后沿用旧完成时刻。
- **粮箱与8批收储。** 固定计划可采用两趟收割、8垄一批的保守分组，共8批。它不是接口规定所有场必须8次；真正限制是2t粮箱、工具的保守收前容量检查，以及额外湿重安全核对。低产场若想进一步合批，仍需实际工具证明，不能只看全田最终入库kg就声称可行。
- **标准质量与湿重。** 当前`grain_kg_added/grain_bin_kg`为13%商品水分质量，不是实收湿重。额外安全核对用收前公开的批内最高籽粒水分及舍入裕度，按`湿重=标准13%质量×0.87/(1−水分率)`保守换算。不能用标准质量小于2t掩盖湿粮已超2t，也不能读私有原生状态拼出答案。
- **干燥边界。** 已安全的批次直接入库；高于13.5%的批次先处理。当前`dry_grain`是零耗时、无能源结算的即时模型操作；可选容量只是现有拒绝边界，没有真实连续烘干排队。不得把它写成已验证的真实烘干设备耗时。最终批次仍要有真实卸粮、必要干燥、全部来源垄和安全入库回执。
- **诊断证据。** 病、虫、草处理前保留对应区域的地面诊断、类型与置信度，机器人所需电量、充电和等待不删。全局NDVI或单次范围状态不能代替病虫草鉴别。机器喷药/除草/追肥每趟最多10垄，药剂与机械额度继续保留。

只保留同一时刻一份可复用的观测与设备状态。作业跨日、天气窗口变化、进入其他土区或灌溉效果尚未到达时，要保留真正必要的复查。删除零耗时重复读取与改变有耗时农事不是同一类改动，后者必须重新生成并执行固定计划。

## 工作流内可见的必要说明

步骤ID/`name`采用`序号_当地日期_操作目的_目标和剂量`，例如：

```text
00001_2019-04-28_播种前核验_全田土壤天气库存
00020_2019-04-28_批量装种_本批300000粒
00150_2019-07-07_限水补水_22至43垄_全田等效剂量见参数
00200_2019-09-20_卸粮_两趟8垄批次_核对2t容量
```

普通作业的名称日期表示开始日，等待节点的名称日期表示目标日；`time`及回放`time_after`记录完成时刻。跨日时，两者日期可以不同，这不是时钟回退或UTC错位。

事件按农场当地日历使用`[start,end)`区间，垄号包含两端。`daily/set`在每个有效日重新注入目标压力，`daily/add`逐日累加；到结束日只停止注入，**不会自动清除病虫草压力**。

名称随现有Workflow序列化、加载及回放保留，不增加解释用的虚假工具调用。完整剂量仍由`tool_args`给出，解释不混进工具参数。源码日期块注释补充人读的农事顺序；`MIGRATION_NOTES`记录设定与能力边界。计划`content`仍为null，真实工具回执只在replay中产生，不能把`purpose`塞进会被回放替换的响应字段。Engine/Workflow没有为本轮加新注释协议。

## 三项App精度窄修及其回归证据

整批91.2L分38+38+15.2L使用时，二进制尾数可能使末次库存比需求低约1e−14，旧严格比较误报缺药。修复仅覆盖单场与共享的可变剂量喷虫剂、杀菌剂、除草剂路径：`current>=required or math.isclose(current,required,rel_tol=1e-12,abs_tol=0.0)`，扣减为`max(0,current-required)`。未四舍五入库存或剂量，也未用绝对epsilon让零库存获得正微量药效。

[药剂修复证据](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/chemical_tank_float_fix/evidence.json>)对应当时114项相关回归。随后76.8kg整批追肥、6×12+4.8kg末趟暴露同类问题；仅对单场/共享`apply_fertilizer`的料箱守卫和扣减作相同修复，不改变肥效或原生N路径。[追加施肥后的相关回归](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/fertilizer_spreader_float_fix/evidence.json>)共124项通过，包含此前药剂测试，不能与114相加。真不足、零库存的1e−12/1e−300正剂量都拒绝，时间、库存和物理状态保持不变。

水额度还有独立的记账问题：旧`record_irrigation_use`每次累计后取6位小数，检查点视图再取4位，数学上恰好320mm的分次灌溉会累计成320.000033mm并在末笔误拒。修复只保留累计和检查点的完整浮点精度，不增加额度、不放宽现有1e−9比较容差，也不改水物理。[水账精度证据](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/irrigation_accounting_precision/evidence.json>)记录5项新增回归及40项相关测试通过。它与药箱、肥箱相对比较修复解决的是不同问题；这些相关测试存在重叠，不相加当作独立总数。

## 本轮正式64垄结果

下表全部来自新的静态`--build-oracle --replay --evaluate`正式产物，10/10完成64垄成熟、合法收获及安全入库。亩产按实际28.3008亩及13%商品水分质量计算；没有把科学扫描或候选预审数值填入正式表。

| 原场景 | 密度株/m² | 全田限水mm | 步骤（前→后） | 安全入库kg | kg/亩 |
|---|---:|---:|---:|---:|---:|
| [01 正常季](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/final/01/scenario_full_season_hb_base_hn84_std_normal.run_report.json>) | 45 | 无硬额度 | 818→252 | 9159.68 | 323.65 |
| [02 干旱限水](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/final/02/scenario_full_season_hb_dryr5r6_hn84_water_limit.run_report.json>) | 40 | 320 | 305→407 | 7537.03 | 266.32 |
| [03 低氮追肥](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/final/03/scenario_full_season_hb_low_nutrient_carryover_flowering_nutrition.run_report.json>) | 60 | 无硬额度 | 719→233 | 8229.50 | 290.79 |
| [04 机械控草](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/final/04/scenario_full_season_hb_high_weed_seedbank_mechanical_only_baseline.run_report.json>) | 45 | 无硬额度 | 852→304 | 8139.36 | 287.60 |
| [05 R5食叶虫](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/final/05/scenario_full_season_hb_r5_leaf_feeder_defoliation.run_report.json>) | 45 | 无硬额度 | 646→165 | 6402.64 | 226.24 |
| [06 有限药预算](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/final/06/scenario_full_season_hb_limited_spray_budget_season.run_report.json>) | 45 | 无硬额度 | 880→312 | 8314.43 | 293.79 |
| [07 短施药窗口](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/final/07/scenario_full_season_hb_wetjune_short_spray_window.run_report.json>) | 45 | 无硬额度 | 656→246 | 8214.68 | 290.26 |
| [08 病后干旱](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/final/08/scenario_full_season_hb_disease_then_drought_recovery_tradeoff.run_report.json>) | 45 | 11.5 | 361→131 | 7267.70 | 256.80 |
| [09 草病鉴别](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/final/09/scenario_full_season_hb_weed_then_disease_canopy_confusion.run_report.json>) | 45 | 无硬额度 | 761→306 | 8409.33 | 297.14 |
| [10 雨延除草](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/final/10/scenario_full_season_hb_herbicide_window_missed_rain_delay.run_report.json>) | 45 | 无硬额度 | 785→265 | 8489.45 | 299.97 |

[结果JSON](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/results.json>) / [CSV](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/results.csv>)保存全部源码SHA和工具用量。本轮合计6783→2621步，减少4162步（61.36%）。**02单场305→407步，增长102步**：额度从历史1.8mm明确改为本轮320mm，实际97次定向灌溉，增加的是有剂量与实际耗时的农事，没有为压计数而删掉。跨轮同时改变密度、水额度和管理时机，产量差不能单独归因于步骤精简。

[独立产物审计](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/independent_static_artifact_audit.json>)10/10通过：源码纯构建无农事执行、计划`content`为空；工具、参数、依赖、类型、中文名称和完成时间与回放一致；实际时钟、64垄收储覆盖、标准质量和公开水分换算的湿重安全、剩余粮食及额度使用全部通过。所有场景的校准入库量与正式回放一致。

[最终相关回归](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_refinement_20261025/regression.json>)为**484项通过，0失败、0错误、0跳过**，包括原生对照、10个静态场景、资源精度、共享工具及兼容运行时。这是该列明范围的相关回归，不声称全仓库测试；先前114、124、40等阶段性分组存在重叠，不相加。

这些地点/年份/管理组合仍缺少配套田间观测，因此没有田间预测误差或全局最优证明。正式产物证明的是给定世界与有限搜索范围中的可执行、可复现管理流程。
