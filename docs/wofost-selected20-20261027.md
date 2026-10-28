# 2026-10-27 新选20场：逐场维护

本清单按本次用户给出的顺序执行，**已完成20/20，待改造0场、受模型阻塞0场**。它与此前暂停的追加20场清单不同；此前完成的3场灌溉题不重复计入本次20场。既有13对旧版/V2中仍是12个已校准、花期营养03未校准；加入本次已完成的20场后合计33对、32个已校准、1个未校准。没有声称全部旧场景迁移完成。

机器可读状态见[本次清单](../configs/oracles/wofost_selected20_20261027.json)。旧文件及旧ID保留经典引擎，新场景使用独立完整的 `_V2` 文件、类和注册ID。各场依次完成完整对照和回放后才更新清单；不修改Agent引擎或公共物理机制。

| 顺序 | 场景 | 状态 |
| --- | --- | --- |
| 01 | [虫害阈值与有限施药机会](../fairy/scenarios/wofost/scenario_full_season_heinong84_threshold_insect_limited_spray_V2.py) | 已校准，三组对照及CLI回放通过 |
| 02 | [湿季病害与低化学投入](../fairy/scenarios/wofost/scenario_full_season_heinong84_low_chemical_wet_disease_V2.py) | 已校准，三组对照及CLI回放通过 |
| 03 | [有机田局部草害与机械资源分配](../fairy/scenarios/wofost/scenario_full_season_hb_organic_weed_pressure_allowed_inputs_V2.py) | 已校准，[完整方案](wofost-selected20-03.md) |
| 04 | [雨后机械除草窗口](../fairy/scenarios/wofost/scenario_full_season_hb_mechanical_weed_control_soil_wetness_V2.py) | 已校准，[完整方案](wofost-selected20-04.md) |
| 05 | [花期凉湿与局部病害](../fairy/scenarios/wofost/scenario_full_season_hb_coolwet_flowering_disease_risk_V2.py) | 已校准，[完整方案](wofost-selected20-05.md) |
| 06 | [杀菌后的复查与再次用药](../fairy/scenarios/wofost/scenario_full_season_hb_wetjune_disease_recheck_after_fungicide_V2.py) | 已校准，[完整方案](wofost-selected20-06.md) |
| 07 | [食叶虫与病斑鉴别](../fairy/scenarios/wofost/scenario_full_season_hb_leaffeeder_vs_disease_spots_diagnosis_V2.py) | 已校准，[完整方案](wofost-selected20-07.md) |
| 08 | [旱后恢复慢，避免误诊病害](../fairy/scenarios/wofost/scenario_full_season_hb_drought_recovery_false_disease_signal_V2.py) | 已校准，[完整方案](wofost-selected20-08.md) |
| 09 | [缺水与虫害分区处理](../fairy/scenarios/wofost/scenario_full_season_hb_dryr5r6_insect_threshold_waterstress_V2.py) | 已校准，[完整方案](wofost-selected20-09.md) |
| 10 | [高密度田保留关键杀菌预算](../fairy/scenarios/wofost/scenario_full_season_hb_highdensity_wetjune_limited_fungicide_V2.py) | 已校准，[完整方案](wofost-selected20-10.md) |
| 11 | [先病后虫，共用施药预算](../fairy/scenarios/wofost/scenario_full_season_hb_insect_after_fungicide_budget_conflict_V2.py) | 已校准，[完整方案](wofost-selected20-11.md) |
| 12 | [短暂无雨窗与土壤通行性](../fairy/scenarios/wofost/scenario_full_season_hb_wetjune_shortwindow_trafficability_V2.py) | 已校准，[完整方案](wofost-selected20-12.md) |
| 13 | [高密度田局部湿区病害](../fairy/scenarios/wofost/scenario_full_season_hb_wetjune_highdensity_poordrainage_disease_V2.py) | 已校准，[完整方案](wofost-selected20-13.md) |
| 14 | [连作病史与局部湿区管理](../fairy/scenarios/wofost/scenario_full_season_hb_wetjune_soyhistory_poordrainage_disease_V2.py) | 已校准，[完整方案](wofost-selected20-14.md) |
| 15 | [晚雨后的局部虫害](../fairy/scenarios/wofost/scenario_full_season_hb_laterain_insect_risk_V2.py) | 已校准，[完整方案](wofost-selected20-15.md) |
| 16 | [同品种错期播种与分区收获](../fairy/scenarios/wofost/scenario_full_season_heinong84_staggered_planting_V2.py) | 已校准，[完整方案](wofost-selected20-16.md) |
| 17 | [错期播种遇到同一场干旱](../fairy/scenarios/wofost/scenario_full_season_hb_staggered_dryr5r6_stage_mismatch_V2.py) | 已校准，[完整方案](wofost-selected20-17.md) |
| 18 | [错期播种与分区病害管理](../fairy/scenarios/wofost/scenario_full_season_hb_staggered_wetjune_canopy_disease_V2.py) | 已校准，[完整方案](wofost-selected20-18.md) |
| 19 | [杂草与病害造成的长势异常](../fairy/scenarios/wofost/scenario_full_season_hb_wetjune_weed_disease_diagnosis_V2.py) | 已校准，[完整方案](wofost-selected20-19.md) |
| 20 | [晚雨前有限时间内分区抢收](../fairy/scenarios/wofost/scenario_full_season_hb_harvester_days_limit_laterain_V2.py) | 已校准，[完整方案](wofost-selected20-20.md) |

## 01：虫害阈值与有限施药机会

完整[场景源文件](../fairy/scenarios/wofost/scenario_full_season_heinong84_threshold_insect_limited_spray_V2.py)直接声明世界、事件、任务说明和140次静态工具调用。旧文件SHA256保持为 `49468f8b265cd84b58572036fc67bce2699f2ae714a3bb0c5d7afc01dc9b248a`。

**保留考点：** 轻虫情先观察，不因单点阳性提前用完药量；确认生殖期虫情加重后定向处理。正确管理与错误管理用相同160L药量、相同作业范围，只有用药日期不同；不施药组只省略杀虫操作，仍播种、灌溉、收获和入库，不能称作全季放任不管。

### 世界、官方值与场景假设

- 法国Lille，50.63°N、3.06°E，海拔41.86m；2019-04-28 07:00至11-15 07:00，Europe/Paris。
- `farm`，64垄，每垄268×1.1m，一垄两行，总面积18867.2m²（1.88672ha）。45株/m²换算株距 `100×2/(45×1.1)=4.040404…cm`，播深4cm，每垄13266粒、全田849024粒。
- 使用官方地区参数组 `Soybean_901` / `SOYBEAN_901`。历史文件名里的Heinong84不是实际品种映射。官方78项原始参数无人工覆盖；现有适配器按实际密度45/40把TDWI从120初始化为135。这是既有密度适配，不是官方最优密度或商业品种试验复现；未扩展固氮限制。
- 参数来源：[官方固定提交](https://github.com/ajwdewit/WOFOST_crop_parameters/blob/1ca91d7dbb5aaf6b41462162de03a8254812d3a5/soybean.yaml)，[原始报告](https://edepot.wur.nl/308997)。天气使用仓库已有[固定数据清单](../fairy/physics/data/wofost/research/official_soybean_nasa2019_v1/manifest.json)内NASA POWER Lille 2019数据，天气SHA256为 `b0322825ef8140d714a9724b3933f18954d51541877459d3f9dd48cf7c80a675`，作物YAML为 `b65cf37a478542d74564094dc0760c69bd3cda99452eb6e7d327e457f87ba9a9`。地点天气是公开网格产品，土壤不是原试验实测。
- 土层1.2m，初始VWC0.26、温度12°C，萎蔫点0.10、持水量0.30、饱和0.45、入渗上限50mm/day；初始有效氮及储备氮模型设定均50kgN/ha。这些是场景初值，P/K未构成生长限制题。
- 库存：种子100万粒、肥料0kg、杀虫工作液160L、仓库燃油1000L；拖拉机初始燃油100L。全季毛灌溉额60mm，设施5mm/h；原生土壤实际接收55.2mm，沿用既有92%效率。
- 杀虫最多1个施药日，活性成分上限0.16kg；现有工具以1g/L工作液记账。8L/垄为模拟参考剂量，20垄需160L；同日两趟是1个施药日。相较旧题2日/0.18kg，调整成只够一轮正常处理，使“提前耗尽机会”可被明确检验，不把分趟误算成农事轮次。这不是现实农药标签推荐。
- 设备：种箱30万粒、粮箱2t；播种/收割每次最多4垄，喷药每趟最多10垄。机器人范围任务最多8垄、内部4垄一批，本方案只抽查明确的4垄样本；单垄详细检查另计。无人机全田粗查560秒，电量100%→36%，随后实际充电。

### 世界事件与可见依据

全部事件通过 `install_scenario_events` 安装，Agent、oracle及回放相同；没有在施药步骤中注入虫情。

| 事件 | 范围与时间 | 机制 |
|---|---|---|
| 早期轻虫情 | 18–37垄，6/14一次 | insect=0.08，once/set |
| 后期新虫情 | 18–37垄，7/24一次 | insect=0.65，once/set；距早期施药超过10日残效窗 |
| 早期巡查窗 | 6/15全天 | 人工设定无雨、2m/s风 |
| 后期巡查与施药窗 | 7/25–27 | 人工设定无雨、2m/s风 |

其余天气字段沿用固定数据；7/28不在人工天气窗内，复查允许出现地湿提示，机器人照常消耗步行时间。病虫草为FAIRY外接同化胁迫，非WOFOST原生虫种、叶面积移除或田间药效模型。once/set不是每日重设，药后下降不会被下一日无条件覆盖。

公开交接信息将18–37垄列为重点巡查区；这是风险线索，不能代替当季诊断。无人机7/25目标区平均NDVI约0.835、其余区约0.848，差异较弱且有噪声，**不据此声称精确定位20条虫害垄**。传感器与全田无人机作参考，两端18–21、34–37垄的地面样本及18、34垄详细分档作主要确认；只覆盖这些样本，不声称逐垄确诊。

6/15两个详细点均为 `low`、未检出虫害；7/25两个点均为 `medium`，多个范围样本有高置信虫情，公开阶段R3。7/28药后两组样本虫情均下降；低置信度病害假阳性不能作为改用杀菌剂依据。这里的low/medium/high是模型内管理判据，不是经过田间验证的虫种经济阈值。

### 完整计划与真实耗时

4/28检查土壤/天气/库存/设备→整地→起垄→全田播种；5/13播后状态样本尚未出苗（原生DOE为5/20），不能因此盲目补播；5/28用冠层及地面样本复核苗情和杂草。6/15按传感器→无人机→地面分点→详细虫量分档观察并保留药量；6/28花期复核不例行追氮。7/20 R3根层VWC约0.174–0.176且预报不足时全田30mm；7/25按同样诊断层次确认后，18–27及28–37各喷8L/垄。7/28复查；8/8 R5根层VWC约0.150–0.155、预报不足时全田30mm。9/20确认全田R8、水分17.33%、无雨且可通行，完成收获、卸粮、必要干燥和安全入库。

全程10个检查/管理日期窗口、**7轮田间农事、140次工具调用**。7轮为整地1、起垄1、播种1、灌溉2、杀虫1、收获1；播种16趟，喷药2趟，收割16趟，卸粮/干燥/入库8批。每趟喷药190秒、收割271秒、卸粮480秒；6h灌溉加启动共21900秒。`dry_grain`沿用即时零耗时抽象，不伪造设备耗时或干燥产能约束。9/20当地09:16:16完成；正式构建与回放逐项核对实际起止时间。

### 三组同输入对照

| 管理 | 虫区TWSO kgDM/ha | 全田平均TWSO kgDM/ha | 原生总干物质kg | 13%商品粮入库kg | 工作液L/施药日 | 耗油L |
|---|---:|---:|---:|---:|---:|---:|
| 正确：7/25处理 | 3904.45 | 4118.33 | 7770.14 | 8612.98 | 160/1 | 84 |
| 不施杀虫剂 | 3295.67 | 3928.09 | 7411.20 | 8176.12 | 0/0 | 80 |
| 错误：6/15提前用完 | 3294.48 | 3927.72 | 7410.50 | 8175.38 | 160/1 | 84 |

三组均毛水60mm（1132.032m³）、肥料0kg、同面积同播种密度，作物/土壤/气象/事件声明一致，非虫区TWSO完全相同，均64垄安全收储。正确处理的虫区原生产量比不施药高18.47%，整场商品粮高5.34%。提前用药与不施药只差0.74kg，不能说提前喷药本身造成明显额外减产；后果是药量与施药日额度耗尽，后期失去可获得的保护收益。

原生TWSO是干物质。除以0.87只是损失前13%含水率理论重量，入库量还经过现有田间/机器回收损失；不能直接混比kgDM/ha和整田入库kg。三组 `validate` 都通过表示成熟与合法收储完成，不代表三种管理质量相同；管理考点由独立反事实比较核验，不由产量硬编码评分。

### 复现及验收

```bash
cd /Users/quao/.codex/worktrees/wofost-management-audit/FAIRY
PYTHONHASHSEED=0 .venv/bin/python -m fairy.cli \
  -s scenario_full_season_heinong84_threshold_insect_limited_spray_V2 \
  --build-oracle --run-oracle-tools --replay --evaluate \
  --output-dir /tmp/fairy-threshold-v2-check

# 独立实验代码使用生产场景的世界/事件/设备；不被生产oracle导入。
PYTHONHASHSEED=0 .venv/bin/python tests/wofost_threshold_insect_experiment.py correct /tmp/fairy-threshold-controls
PYTHONHASHSEED=0 .venv/bin/python tests/wofost_threshold_insect_experiment.py none /tmp/fairy-threshold-controls
PYTHONHASHSEED=0 .venv/bin/python tests/wofost_threshold_insect_experiment.py early /tmp/fairy-threshold-controls
.venv/bin/python tests/wofost_threshold_insect_experiment.py verify /tmp/fairy-threshold-controls
```

正式CLI build→真实工具→replay→evaluate通过；140条参数/依赖/操作类别/时间全部一致。最终静态源码计划另与已执行CLI逐项核对；最后公开文字澄清与状态标记不改变世界、事件或调用。三组对照通过独立断言；场景、旧版保留、版本隔离、事件及任务说明相关回归共73项通过，非全仓库测试声明。

完整证据存于本worktree的 `validation_runs/wofost_selected20_20261027/01_threshold_insect/`（按现有.gitignore保留在本地）：三个完整原生状态/工具轨迹、CLI构建与回放、run_report、summary、比较审计及测试日志。可核对[结果摘要](../validation_runs/wofost_selected20_20261027/01_threshold_insect/summary.json)、[三组核验](../validation_runs/wofost_selected20_20261027/01_threshold_insect/comparison_audit.json)、[最终源码计划核验](../validation_runs/wofost_selected20_20261027/01_threshold_insect/static_artifact_audit.json)。这些是工程校准和oracle工具结果，不是LLM Agent实验成绩或田间实测。

本次20场已按上表顺序完成工程校准。第20场只允许真实收割耗时和雨窗形成约束，不能把未限制收割的 `max_machine_passes` 写成收割次数/天数限制。花期营养03保持未校准，不扩展固氮限制机制。

## 02：湿季病害与低化学投入

已完成[独立完整场景](../fairy/scenarios/wofost/scenario_full_season_heinong84_low_chemical_wet_disease_V2.py)与[逐项方案、参数边界和复现命令](wofost-wet-disease-v2.md)。Lille 2019官方Soybean_901，明确人工连雨期与一次性局部病害事件。传感器→全田无人机→机器人分四次检查18–45垄、充电后补齐覆盖，再只对22–43垄用83.6L工作液。湿期土水充足，取消普通季7月灌溉，8月一次30mm，余水不用。

正确定向、不施杀菌剂、同量全田均摊三组分别入库8232.27、7552.47、7802.06kg（13%商品水分）。正确方案比不施药高9.00%，比均摊高5.51%；均摊仍有部分收益，不能称完全无效。6轮田间农事、132次调用，生产CLI及实际时间回放一致，相关76项回归通过；第01场源码与全部旧文件保留。证据见[结果汇总](../validation_runs/wofost_selected20_20261027/02_wet_disease/summary.json)与[独立产物核验](../validation_runs/wofost_selected20_20261027/02_wet_disease/static_artifact_audit.json)。

### 03 完成记录

有机田局部草害与机械资源分配：correct/none/wrong入库分别7880.60/7208.64/7709.12kg（13%）。123次调用，7轮田间农事，CLI及独立时间/范围核验通过。[本场完整说明](wofost-selected20-03.md)。

### 04 完成记录

雨后机械除草窗口：correct/none/wrong入库分别8299.36/5677.44/5677.44kg（13%）。123次调用，6轮田间农事，CLI及独立时间/范围核验通过。[本场完整说明](wofost-selected20-04.md)。

### 05 完成记录

花期凉湿与局部病害：correct/none/wrong入库分别8794.83/8480.92/8480.92kg（13%）。122次调用，7轮田间农事，CLI及独立时间/范围核验通过。[本场完整说明](wofost-selected20-05.md)。

### 06 完成记录

杀菌后的复查与再次用药：correct/none/wrong入库分别8292.38/7258.10/7676.96kg（13%）。153次调用，7轮田间农事，CLI及独立时间/范围核验通过。[本场完整说明](wofost-selected20-06.md)。

### 07 完成记录

食叶虫与病斑鉴别：correct/none/wrong入库分别8854.91/8592.40/8592.40kg（13%）。121次调用，7轮田间农事，CLI及独立时间/范围核验通过。[本场完整说明](wofost-selected20-07.md)。

### 08 完成记录

旱后恢复慢，避免误诊病害：correct/none/wrong入库分别7005.30/6587.08/7005.30kg（13%）。122次调用，7轮田间农事，CLI及独立时间/范围核验通过。[本场完整说明](wofost-selected20-08.md)。

### 09 完成记录

缺水与虫害分区处理：correct/none/wrong入库分别6857.01/6072.11/6533.04kg（13%）。130次调用，8轮田间农事，CLI及独立时间/范围核验通过。[本场完整说明](wofost-selected20-09.md)。

### 10 完成记录

高密度田保留关键杀菌预算：correct/none/wrong入库分别8423.47/7797.92/7875.87kg（13%）。133次调用，7轮田间农事，CLI及独立时间/范围核验通过。[本场完整说明](wofost-selected20-10.md)。

### 11 完成记录

先病后虫，共用施药预算：correct/none/wrong入库分别7893.08/7240.60/7445.56kg（13%）。141次调用，7轮田间农事，CLI及独立时间/范围核验通过。[本场完整说明](wofost-selected20-11.md)。

### 12 完成记录

短暂无雨窗与土壤通行性：correct/none/wrong入库分别7980.09/7107.07/7107.07kg（13%）。121次调用，6轮田间农事，CLI及独立时间/范围核验通过。[本场完整说明](wofost-selected20-12.md)。

### 13 完成记录

高密度田局部湿区病害：correct/none/wrong入库分别8492.88/8030.84/8492.88kg（13%）。122次调用，6轮田间农事，CLI及独立时间/范围核验通过。[本场完整说明](wofost-selected20-13.md)。

### 14 完成记录

连作病史与局部湿区管理：correct/none/wrong入库分别8571.24/7887.04/8161.68kg（13%）。145次调用，7轮田间农事，CLI及独立时间/范围核验通过。[本场完整说明](wofost-selected20-14.md)。

### 15 完成记录

晚雨后的局部虫害：correct/none/wrong入库分别8919.28/8664.58/8664.58kg（13%）。126次调用，6轮田间农事，CLI及独立时间/范围核验通过。[本场完整说明](wofost-selected20-15.md)。

### 16 完成记录

同品种错期播种与分区收获：correct/none/wrong入库分别8898.56/8505.36/8505.36kg（13%）。136次调用，10轮田间农事，CLI及独立时间/范围核验通过。[本场完整说明](wofost-selected20-16.md)。

### 17 完成记录

错期播种遇到同一场干旱：correct/none/wrong入库分别6252.80/5469.20/6130.72kg（13%）。127次调用，7轮田间农事，CLI及独立时间/范围核验通过。[本场完整说明](wofost-selected20-17.md)。

### 18 完成记录

错期播种与分区病害管理：correct/none/wrong入库分别7637.92/6673.76/6673.76kg（13%）。137次调用，8轮田间农事，CLI及独立时间/范围核验通过。[本场完整说明](wofost-selected20-18.md)。

### 19 完成记录

杂草与病害造成的长势异常：correct/none/wrong入库分别8302.48/7174.21/7174.21kg（13%）。149次调用，7轮田间农事，CLI及独立时间/范围核验通过。[本场完整说明](wofost-selected20-19.md)。

### 20 完成记录

晚雨前有限时间内分区抢收：correct/none/wrong入库分别65919.34/64671.04/64671.04kg（13%）。412次调用，8轮田间农事，CLI及独立时间/范围核验通过。[本场完整说明](wofost-selected20-20.md)。

## 全批次结果与复现

下表均为**13%商品粮kg**，已包含田间/机器回收损失；各场分别比较，20号面积为14.08ha，其他场为1.88672ha，不能直接以整田重量跨场排名。原生干物质及水肥药油统计在[机器结果汇总](../configs/oracles/wofost_selected20_results_20261027.json)与各场完整说明中单列。

| 顺序 | 正确kg | 不做关键干预kg | 错误kg | 正确工具调用 | 正确农事轮次 | 核验重点 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 01 | 8612.98 | 8176.12 | 8175.38 | 140 | 7 | 虫情分档与用药时机 |
| 02 | 8232.27 | 7552.47 | 7802.06 | 132 | 6 | 药量有限、定向杀菌 |
| 03 | 7880.60 | 7208.64 | 7709.12 | 123 | 7 | 有机机械资源优先区 |
| 04 | 8299.36 | 5677.44 | 5677.44 | 123 | 6 | 湿土进地被拒绝 |
| 05 | 8794.83 | 8480.92 | 8480.92 | 122 | 7 | 凉湿花期局部病害 |
| 06 | 8292.38 | 7258.10 | 7676.96 | 153 | 7 | 药后复查、新病情再处理 |
| 07 | 8854.91 | 8592.40 | 8592.40 | 121 | 7 | 杀虫与杀菌类别鉴别 |
| 08 | 7005.30 | 6587.08 | 7005.30 | 122 | 7 | 错误施药浪费，未虚构药害 |
| 09 | 6857.01 | 6072.11 | 6533.04 | 130 | 8 | 水与虫害分别分区 |
| 10 | 8423.47 | 7797.92 | 7875.87 | 133 | 7 | 保留晚期杀菌机会 |
| 11 | 7893.08 | 7240.60 | 7445.56 | 141 | 7 | 杀菌与背负杀虫共用额度 |
| 12 | 7980.09 | 7107.07 | 7107.07 | 121 | 6 | 无雨仍须等土壤通行 |
| 13 | 8492.88 | 8030.84 | 8492.88 | 122 | 6 | 同产量，错误全田用药4倍 |
| 14 | 8571.24 | 7887.04 | 8161.68 | 145 | 7 | 有病史区处理后继续复查 |
| 15 | 8919.28 | 8664.58 | 8664.58 | 126 | 6 | R5仍有保产价值、雨天禁喷 |
| 16 | 8898.56 | 8505.36 | 8505.36 | 136 | 10 | 同干物质，分区收获减损 |
| 17 | 6252.80 | 5469.20 | 6130.72 | 127 | 7 | 等水量实测：晚区优先 |
| 18 | 7637.92 | 6673.76 | 6673.76 | 137 | 8 | 播期长势差异不等于病害 |
| 19 | 8302.48 | 7174.21 | 7174.21 | 149 | 7 | 同资源、除草与杀菌对象鉴别 |
| 20 | 65919.34 | 64671.04 | 64671.04 | 412 | 8 | 真实26趟雨窗与容量约束 |

none只省略各题关键干预，保留建植、其他共同管理和最终完整收储。错误管理允许有部分收益；08错误杀菌和13全田杀菌主要体现资源浪费，不捏造药害。04/12/15/16/20的wrong包含预期非法尝试，原工具拒绝且资源/时间未被虚构扣罚；其最终完整收储仍单独核对，`validate=False`来自预期拒绝记录，不能当成正确Oracle失败。

03–20使用可提交的[固定配方](../tests/data/wofost_selected20)和[独立对照复现器](../tests/wofost_selected20_experiments.py)，生产场景不导入它们。01和02的复现命令见各自上文。例：

```bash
PYTHONHASHSEED=0 .venv/bin/python tests/wofost_selected20_experiments.py 20 correct /tmp/wofost-selected-controls
PYTHONHASHSEED=0 .venv/bin/python tests/wofost_selected20_experiments.py 20 none /tmp/wofost-selected-controls
PYTHONHASHSEED=0 .venv/bin/python tests/wofost_selected20_experiments.py 20 wrong /tmp/wofost-selected-controls
.venv/bin/python tests/wofost_selected20_experiments.py 20 verify /tmp/wofost-selected-controls
```

[独立产物核验器](../tests/wofost_selected20_artifact_audit.py)按各场WORLD核对真实面积、原始时区时间戳、传感器—无人机—地面顺序、真实覆盖/电量、粮箱、批次及安全收储；第20场不再套用旧审计固定1.88672ha的假设，公共物理与旧审计文件均未改动。农事轮次与工具调用分列；同轮容量分趟及跨午夜连续收储仍只计一轮，失败尝试不算已完成农事轮次。

全部旧文件SHA和场景身份保留；已有未提交双农场大豆＋玉米、天气、测试、文档及farm_environment改动保留。当前共有33对旧版/V2、32个已校准、原花期营养03仍未校准；本批完成不代表全部旧场景迁移完成。这是工程校准，不是田间实测验证或LLM Agent实验。

## 最终回归与文件保留

2026-10-28最终相关回归 **147项通过（277.60秒）**，覆盖20场新旧身份、完整静态workflow与配方一致性、既有13场任务说明/事件、原生同化与管理因果，以及保留的双农场共享天气和两作物完整收储；不是全仓库测试声明。[测试日志](../validation_runs/wofost_selected20_20261027/regression-final.log)与[最终核验](../validation_runs/wofost_selected20_20261027/final_verification.json)保留完整范围。

18场通用对照复现器的结果断言全部通过，01/02分别保留专用对照与原有验收。20个旧文件和20个新源码SHA、18份固定配方、逐场文档本地链接、33对/32校准/1未校准口径均核对一致。已有双农场大豆＋玉米场景、Thionville天气、相关测试/文档与原有farm_environment.py未提交改动经哈希复核保持；公共引擎未修改，未重置工作区，未提交或推送。
