# 追加20个旧场景，逐场校正

本轮编号01—20仅指这次顺序，不与上一轮10场混算。当前已完成 **3/20**；已按要求暂停，剩余17场未继续。
每场完成机制对照、完整源文件、真实工具回放和独立核验后，才开始下一场。

主要考点保留，WOFOST版使用独立的 `_V2` 场景ID、文件和类；原名恢复经典版。世界、事件、中文农事说明和全部静态工具调用都写在各自新文件中。生产不加载校准脚本或外部轨迹JSON，不新增Agent引擎农事入口。版本映射见[新旧版本说明](wofost-scenario-versions.md)。

## 选题与验收

先验证问题确实影响原生生长或已实现的收储结果，再验证管理能改善，最后写题设和workflow。按正常农事调整事件时间、可作业窗口及资源额度；不把无效养分值、未实现的杂草耗水、瞬时烘干设备容量拿来充当考点。

沿用已核验的官方大豆参数及固定公开天气。土壤、人工灾害和药效耦合是显式模拟假设，不冒充田间实测。无依据的例行氮肥、频繁小水、补尾数和重复读取不写入计划。农事窗口数和工具调用数分开统计。

**异常排查保留三层：传感器发现异常 → 无人机粗查范围 → 机器人重点确诊 → 管理。** 无人机输出带噪声的NDVI与近似冠层温度，不能直接确诊病因；天气、电量、覆盖和飞行耗时按真实工具核验。普通出苗抽样不必例行起飞，雨天不强行飞行。

| 本轮编号 | 保留的主要考点与完整场景 | 状态 |
|---:|---|---|
| 01 | [识别20–31垄局部快失水干斑并定向补水](../fairy/scenarios/wofost/scenario_full_season_fastdraining_dry_patch_irrigation_V2.py) | 已校正并回放 |
| 02 | [两块干斑中按真实灌溉收益分配仅够一块的水](../fairy/scenarios/wofost/scenario_full_season_hb_two_dry_patches_one_irrigation_V2.py) | 已校正并回放 |
| 03 | [高密度田24–39垄更早缺水，分区补水](../fairy/scenarios/wofost/scenario_full_season_hb_hn60_high_fastdrain_dryr5r6_V2.py) | 已校正并回放 |
| 04 | [高密度群体在R5/R6的供水安排](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_hn60_high_dryr5r6_water_demand.py) | 待处理 |
| 05 | [有机禁药，机械能力仅够最高草压16垄](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_organic_weed_pressure_allowed_inputs.py) | 待处理 |
| 06 | [草害已出现，湿土阻碍机械作业，等待可通行窗口](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_mechanical_weed_control_soil_wetness.py) | 待处理 |
| 07 | [低投入、限水下同时控草与补水](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_lowinput_waterlimited_weed_pressure.py) | 待处理 |
| 08 | [低密度、草害与后期干旱的组合管理](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_lowdensity_weed_dry_competition.py) | 待处理 |
| 09 | [先诊断虫量，再分配有限杀虫机会](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_heinong84_threshold_insect_limited_spray.py) | 待处理 |
| 10 | [湿季病害下低化学投入管理](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_heinong84_low_chemical_wet_disease.py) | 待处理 |
| 11 | [轻病不耗尽后期杀菌预算](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_highdensity_wetjune_limited_fungicide.py) | 待处理 |
| 12 | [短无雨窗同时满足土壤通行性才作业](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_wetjune_shortwindow_trafficability.py) | 待处理 |
| 13 | [高密度田40–55垄湿土与病害管理](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_wetjune_highdensity_poordrainage_disease.py) | 待处理 |
| 14 | [连作病史、排水差田块的病害与复查](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_wetjune_soyhistory_poordrainage_disease.py) | 待处理 |
| 15 | [10–27垄缺水与30–47垄虫害需要不同处理](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_dryr5r6_insect_threshold_waterstress.py) | 待处理 |
| 16 | [33–43垄食叶虫与病斑信号的辨因处理](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_leaffeeder_vs_disease_spots_diagnosis.py) | 待处理 |
| 17 | [杀菌后复查，按残留与再发展决定是否再处理](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_wetjune_disease_recheck_after_fungicide.py) | 待处理 |
| 18 | [补水恢复后长势仍弱，避免误判病害](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_drought_recovery_false_disease_signal.py) | 待处理 |
| 19 | [花期凉湿后的22–32垄局部病害处理](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_coolwet_flowering_disease_risk.py) | 待处理 |
| 20 | [仍处于生长期的晚雨后36–55垄局部虫害](../fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_hb_laterain_insect_risk.py) | 待处理 |

## 逐场结果

### 01｜识别20–31垄局部快失水干斑并定向补水

- **世界：** lille2019固定天气，SOYBEAN_901官方参数组；单农场64垄，每垄268×1.1m，共28.3008亩。
- **怎么管理：** 4/28整地播种，5/13例行出苗、5/28雨天例行查草，6/28花期根水；7/20全田30mm；8/1根水冠层→检查可飞天气/电量→SurveyDrone真实560秒全田调查→Robot重点样本→目标20–31一次30mm；8/8全田30mm；9/20合法收割干燥入库，实际65.625/66mm。
- **机制对照：** 浅土层、低蓄水和较少捕雨使20–31垄更易缺水。保持同一官方901、土壤与旱期，目标区一次正常30mm使目标区原生TWSO比不补该区高29.95%，不是整场增幅；普通区额外补水也有收益。32mm/day是较低入渗上限，不解释成更快排水；不使用旧root_drainage_rate构造因果。此次真实UAV粗查只改变观测和作业时间，不改变生长/产量方程、世界、管理日期、剂量或水额。
- **真实回放：** 8个日期窗口，101次工具调用；13%商品水分入库 **7097.36kg**；用水65.625mm，额度66mm。
- **证据：** [原生对照及详细说明](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/01_fastdraining/analysis.md>)；[独立产物核验](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/01_fastdraining/static_artifact_audit.json>)。

### 02｜两块干斑中按真实灌溉收益分配仅够一块的水

- **世界：** lille2019固定天气，SOYBEAN_901官方参数组；单农场64垄，每垄268×1.1m，共28.3008亩。
- **怎么管理：** 4月28日整地起垄播种901，5月13日出苗样本、5月28日查草，6月28日花期根水复核；7月20日全田30mm，8月1日根水冠层→真实全田UAV560秒粗查→A/B重点样本后仅B42–53垄30mm，8月8日全田30mm；9月20日合法成熟收割并6批干燥入库。全季65.625/66mm，余0.375mm不用。
- **机制对照：** A、B两区一次正常30mm补水均有效：同输入对照A新增239.5971kg籽粒干物质、B新增263.2933kg，B等面积边际回收高9.89%，整场选择差距仅0.377%。A更干不自动等于最高回收收益，不把选A说成无效；B优先来自真实反事实产量×面积，非隐藏priority字段。
- **真实回放：** 8个日期窗口，101次工具调用；13%商品水分入库 **7005.65kg**；用水65.625mm，额度66mm。
- **证据：** [原生对照及详细说明](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/02_two_dry_patches/analysis.md>)；[独立产物核验](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/02_two_dry_patches/static_artifact_audit.json>)。

### 03｜高密度田24–39垄更早缺水，分区补水

- **世界：** lille2019固定天气，SOYBEAN_901官方参数组；单农场64垄，每垄268×1.1m，共28.3008亩。
- **怎么管理：** 4/28播前核对/整地起垄/D60播种；5/13出苗、5/28查草、6/28花期复核；7/20全田30mm、8/1根水冠层→真实全田UAV560秒→重点地面样本→24–39一次30mm、8/8全田30mm；9/20合法收割合批干燥入库。实用67.5/68mm，余.5不用。
- **机制对照：** 在固定D60高密任务背景下，目标24–39一次30mm使其TWSO2115.69→2804.77kgDM/ha（目标区+32.57%，不是整场增幅）；40mm参考总水70，超过68额度。普通16垄额外30mm也增加324.12kgDM，与目标325.03几乎相同，不夸大分配差。D45→D60同输入实际蒸腾仅约+1.8–2%，土壤蒸发下降后WTRAT+EVST至11月14日（含成熟后裸土蒸发）只约+.2%，成熟不变。D60固定供水产量更低；这是既定高密背景下浅土层、低蓄水、较少捕雨造成的易缺水区，不是密度越大季耗水同比增加，也不是商业HN60或官方最佳密度。
- **真实回放：** 8个日期窗口，101次工具调用；13%商品水分入库 **6649.92kg**；用水67.5mm，额度68mm。
- **证据：** [原生对照及详细说明](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/03_highdensity_fastdrain/analysis.md>)；[独立产物核验](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026/03_highdensity_fastdrain/static_artifact_audit.json>)。

## 状态和边界

逐场状态记录在[发布清单](../configs/oracles/wofost_next20_release_status.json)，只供文档和验收使用。原90个源文件的修改前快照、每场机制对照、日序列、真实工具轨迹及正式CLI回放保存在[验证目录](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_next20_20261026>)。版本拆分前无后缀的WOFOST报告是历史记录；当前请使用新构建的 `_V2` 产物，不能拿历史原生workflow回放今天的经典版旧ID。

原生籽粒干物质kg/ha与13%商品水分入库kg分别统计；机器、田间及仓储损失分开核验。病虫草仍为既有外接同化胁迫，dry_grain仍是即时工具抽象。这些结果不是田间实测、大模型Agent成绩或全球最优证明。上一轮03仍保留未校准，不计入本轮。
