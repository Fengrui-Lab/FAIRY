# 两农场差异化大豆全季场景

已实现一个完整场景：A场局部叶部病害管理，B场局部低持水土壤在灌浆期补水。两场同地区、同天气、同品种；差异来自各自的田块历史和土壤。真实工具执行完成286步，两场均收获、干燥并安全入库。

## 从哪里看

- [完整场景文件](/Users/quao/Desktop/Second-year/CWSN/FAIRY/fairy/scenarios/two_farm/scenario_two_farm_full_season_hn84_disease_water.py)：初态、设备、任务说明和整个`build_events_flow`均在本文件，不继承其他场景。
- [Agent任务说明 BRIEFING](/Users/quao/Desktop/Second-year/CWSN/FAIRY/fairy/scenarios/two_farm/scenario_two_farm_full_season_hn84_disease_water.py:60)。
- [设施与初态](/Users/quao/Desktop/Second-year/CWSN/FAIRY/fairy/scenarios/two_farm/scenario_two_farm_full_season_hn84_disease_water.py:127)。
- [完整 build_events_flow](/Users/quao/Desktop/Second-year/CWSN/FAIRY/fairy/scenarios/two_farm/scenario_two_farm_full_season_hn84_disease_water.py:240)。
- [实际执行的286步明细：每步日期、开始/结束时间、工具、参数](/Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/two_farm_differentiated_20261024/oracle_steps.md)。
- [两个重点区逐日状态CSV](/Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/two_farm_differentiated_20261024/daily_focus_state.csv)：每天每场一行，范围均为20–39垄，共280行。根层水分和病压属于内部审计真值，不能当作Agent读数。
- [本次829行增删的逐行原因](/Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/two_farm_differentiated_20261024/line_by_line.md)：旧/新行号、源码、AST作用域和修改理由；含新增场景512行、新测试298行及两处既有文件的最小差异。
- [只含本次4个源码/测试文件的补丁](/Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/two_farm_differentiated_20261024/this_task.patch)与[正向、反向、再次正向还原验证](/Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/two_farm_differentiated_20261024/patch_verification.json)：以本次开始前快照为基线，不混入工作区已有改动。

## 田块到底有什么差异

| 项目 | farm_a | farm_b |
|---|---|---|
| 地区、品种、播种起点 | 哈尔滨、黑农84、2026-05-05 07:00北京时间 | 相同 |
| 几何规模 | 64垄，本地编号0–63，每垄268m，垄距1.1m，每垄两行 | 相同 |
| 有效种植面积 | 64×268×1.1=18,867.2m²，即1.88672ha，约28.30亩 | 相同 |
| 普通土壤 | 深厚黑土 | 0–19、40–63垄与A相同 |
| 局部差异 | 20–39垄前茬重茬、有叶部病害记录 | 20–39垄土层较浅、持水量低 |
| 局部差异面积 | 20×268×1.1=5,896m²，即0.5896ha | 相同 |
| 需要重点判断 | 是否形成值得处理的叶部病害 | 结荚、鼓粒期是否持续缺水 |
| Oracle中的差异化管理 | 7月20日R3局部杀菌，7月27日复查 | 8月2日R5、8月9日R6各局部补水一次，次日复查 |

面积按实际种植的垄距覆盖计算。World外框71m×268m是1.9028ha，含未用于这些垄的边缘宽度，不能把它和有效种植面积混用。

A重点区初始潜在病原压力为0.20，其余为0.02。这是模型风险指数，不能翻译成“20%叶片已经染病”。场景没有在7月20日直接写入一次病害，也没有在8月2日直接写低B的水分。风险和水分都从初态随天气、作物与管理自然日推。

| 土壤参数 | 深厚黑土：A全部及B正常区 | B低持水区20–39 |
|---|---:|---:|
| 等效蓄水层厚度m | 1.45 | 0.80 |
| 田间持水量VWC | 0.37 | 0.29 |
| 表层排水率 | 0.22 | 0.22 |
| 根层排水率 | 0.03 | 0.30 |
| 降雨捕获效率 | 0.97 | 0.66 |
| 灌溉效率 | 0.92 | 0.80 |
| 日最大入渗mm | 85 | 72 |

这些是现有土壤引擎的等效参数，用于表达田块差异。`root_depth_m`在这里是模型蓄水参数，不表示刚出苗时根已长到1.45m。

## 为什么这样安排合理

两场共用一套区域天气。场景复制已有哈尔滨湿六月、八月少雨profile，再各自持有独立副本；清空源配置的强制病害事件。两份气候参数和天气事件相同，既不让B单独遇到旱天，也不污染全局profile。

局部雨事件设为6月14–17日每天18mm，四天72mm；固定气候种子1628的6月累计降水为140.33mm。源profile的72mm会被当前引擎每天应用，四天达到288mm事件雨，因此本场景明确降低为18mm/日。此处是合成气候场景，不是2026年哈尔滨实测天气。8月1–16日两场共同经历连续少雨，同样的天气使B低持水区较早出现水分压力。

叶部病害要综合田块风险、侦察证据、生育期和天气决定。R3–R4是部分大豆叶部病害常见的有效管理窗口，但不存在可以套给所有大豆叶病的统一阈值。本场景采用泛化叶部真菌病模型，安排7月20日R3确认后处理，并在7天后复查；不声称已模拟某个具体病原的全部流行病学。[Iowa State Extension](https://crops.extension.iastate.edu/cropnews/2018/08/frogeye-leaf-spot-making-appearance-across-iowa-soybeans)

大豆结荚到鼓粒阶段对缺水敏感，灌溉应结合生育期、土壤持水能力及墒情。B在R5/R6补水，符合这一管理逻辑；固定日期只是已验证种子下的参考窗口，其他运行应先确认实际阶段和缺水证据。[Michigan State Extension灌溉资料](https://www.canr.msu.edu/irrigation/upoads/files/Soybean%20Irrigation%20Management_AA.pdf)、[Nebraska Extension](https://extensionpubs.unl.edu/publication/g1367/na/html/view)

## 全季Oracle按什么顺序执行

以下为实际执行日期，均为北京时间；精确到秒的全部参数见286步明细。

| 日期 | 共同管理或A场动作 | B场动作 | 目的 |
|---|---|---|---|
| 5月5日 | 两场分别平地、施200kg底肥、起64垄；4垄一趟播种至全部完成 | 同左 | 完整从未播种状态开始 |
| 5月6日 | 两场一起完成一天结算 | 同步推进 | 同一公共时钟，不能每场再等一天 |
| 5月26日 | 两场多光谱全田巡查、4垄出苗抽查 | 同左 | 确认出苗和基础长势；多光谱作业在白天 |
| 6月18日 | 两场雨后墒情、冠层、多光谱和地面检查 | 同左 | 比较雨后状况，历史病害风险不等于立即需要施药 |
| 7月5日 | 两场复核初花状态，各全田轻量追肥：nutrient_amount=0.24，载水2mm | 同左 | 给相同营养管理，避免用缺肥制造场间差异 |
| 7月20日R3 | A20–39多光谱定位；28–31、32–35两次真实4垄地面抽查；局部两趟杀菌 | 28–31地面健康对照，无可靠证据不随A施药 | 先取得病害证据，再选择目标区域和药剂 |
| 7月27日 | A原8个样点复查，不重复施药 | 读取B墒情趋势 | 检查处理后的实际反应 |
| 8月2日R5 | A墒情作为同天气参照 | B土壤、冠层、地面鉴别、热像辅助；20–39垄补水4小时 | 正常区与风险区比较，确认鼓粒前期持续缺水 |
| 8月3日 | 公共时间推进一天 | 复查B土壤与作物 | 水先入表层，再看次日入渗 |
| 8月9日R6 | 同地区继续少雨 | 重新读取墒情、阶段与天气；B20–39再补水4小时 | 根据持续压力安排第二水 |
| 8月10日 | 公共时间推进一天 | 复查B墒情 | 不把灌后表层变湿等同于根层压力全部解除 |
| 9月11日 | A全64垄收获、必要时干燥、安全入库 | B正常44垄先收获、干燥、入库 | 已满足成熟与水分门槛的部分先收 |
| 9月21日 | 无需再收A | B20–39晚熟区单独收获、干燥、入库 | 不为等局部区拖延正常区，也不重复收已收垄 |
| 9月22日 | 分场检查最终库存与共享设备 | 同左 | 确认128垄全部完成 |

`build_events_flow`是固定的参考调用轨迹：包含观察节点和明确的处理节点，没有根据返回值运行`if`分支。它说明这个初态下存在一条合法可完成的管理路径。自主Agent应按BRIEFING用实际返回决定是否处理、何时等候；不能把Oracle里的日期当作无条件下令。

参考轨迹中的收割均已验证满足R8、所有目标垄籽粒水分≤18%、无雨和可通行条件。缺水控制组另有显式等待节点，继续使用相同门槛。干燥目标13%，入库安全上限13.5%。

## 工具信息和设备边界

| 层 | 本场景负责什么 | 运行时由谁执行 |
|---|---|---|
| 场景文件 | 两场初态、土壤/气候副本、库存、预算、App装配、BRIEFING和完整Oracle | 本文件 |
| Agent引擎 | 把可用工具及参数描述交给Agent，分发工具调用、记录时间与返回 | 复用现有Agent与Engine；本次未改 |
| 农场物理引擎 | 土壤、病害、物候、冠层、产量及作业效果随日结算 | 复用现有物理引擎；本次未改 |
| 固定App | 绑定一个农场，不能切换农场 | 每场各一套Sensor、Irrigation |
| 共享App | 管理同一台移动设备的电量、油量、挂具和物料来源；田间作业显式指定farm_id | Tractor、Mavic3M、Matrice4T、Robot0各一台；ManualOps也复用 |
| 时间 | 两场共用同一个北京时间时钟；一次等待推进所有场 | 复用FarmEnvironment与SimulationTimeManager；本次未改 |

Agent实际看到的例子：

```python
FarmA_Sensor__read_soil_sensors()       # 描述明确 Bound farm: farm_a
FarmB_Irrigation__irrigate(start=20, end=39, hours=4.0)
Tractor__apply_fungicide(farm_id="farm_a", start_ridge=20, end_ridge=29, liters_per_ridge=3.8)
Mavic3M__fly_survey(farm_id="farm_a", start_ridge=20, end_ridge=39)
Robot0__inspect_crop_health(farm_id="farm_b", start_ridge=28, end_ridge=31)
```

共享田间工具的`farm_id`为必填枚举，本场景只允许`farm_a`、`farm_b`；固定设施工具不需要另传`farm_id`。移动设备切场前先把剩余种药退回来源场，收割粮逐趟卸回来源场。无人机、机器人充电是异步动作，Oracle显式等待，避免把充电请求当作已经充满。

地面每次只请求4垄。现有底层观测每次实际处理前4垄，因此这里不请求8垄后声称已查8垄。热像有噪声，仅作辅助；土壤探头测表层，Agent不能直接获得根层精确水分。

本次另修正共享拖拉机4个工具描述中残留的跨行“both farms”，改为“all registered farms”，并修正对应测试扫描实际description，避免JSON转义换行导致漏检。没有改变这些工具的参数、业务逻辑或作业时间。

## 用药、用水怎么算

A只处理20–39共20垄，分20–29和30–39两趟。每垄3.8L工作液，总装载76L，实际扣A库存76L，B不扣。两趟同日，季预算计为1个施药日；现有工具的工作液单位不等于现实农药有效成分推荐剂量。

B两次都只处理20–39垄。固定系统名义强度5mm/h，一次4h即每目标垄20mm，选区并行供水。一次实际耗时4小时另加5分钟设置，不乘20垄。每次扣全田等效水量：

```text
20mm × 20垄 / 64垄 = 6.25mm
两次灌溉12.5mm + 全田追肥载水2mm = 14.5mm < 全季预算15mm
```

A只消耗追肥载水2mm。灌溉水先进入表层；内部审计显示B根层第一水约0.17384→0.17582，第二水约0.16210→0.16422，次日继续响应，不能写成“浇完立即恢复至0.18以上”。

CLI正式轨迹中，8月2日B低持水区公开S3表层VWC为0.2036，正常区S1为0.3200；8月9日分别为0.2096、0.2927。S3覆盖22–32垄，落在目标区内；S4跨33–43垄，混合了风险区和正常区，解释时不能当成纯风险区。决策依据是持续趋势、区间对比、生育期、天气与地面鉴别的组合。

## 实际管理效果，不只检查工具返回成功

四组都用真实工具完整收完，并以安全入库重量比较：

| 管理方式 | A入库kg | B入库kg | 完整步数 | 因收获门槛额外等候 |
|---|---:|---:|---:|---:|
| A杀菌+B两次补水 | 8,617.58 | 8,915.82 | 286 | 0天 |
| 省略A杀菌 | 8,458.27 | 8,915.82 | 286 | 0天 |
| 省略B补水 | 8,617.58 | 8,768.52 | 295 | 9天 |
| 两项均省略 | 8,458.27 | 8,768.52 | 295 | 9天 |

A处理增加安全入库159.31kg，B补水增加147.30kg。省略某场处理时，另一场入库重量精确不变。

省略动作通过公开`System.advance_time`补齐相同作业时长，保持管理阶段同时间、同天气。无B补水两组在9月21日仍因籽粒过湿无法合法收割，额外等待9天才收，因此全季收获日期不同；B的147.30kg收益包括对成熟、干燥和收获窗口的影响，不能称为固定同一收获日期下的纯生物学增益。这条参考流程也没有证明数学意义上的最高产量。

[四组完整验收报告](/Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/two_farm_differentiated_20261024/oracle_counterfactual_report.md)与[机器可读总表](/Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/two_farm_differentiated_20261024/oracle_counterfactual_summary.json)保留了逐日状态、观测、局部处理效果、合法延迟和全新场景回放证据。

## 怎么运行与复核

在仓库根目录执行：

```sh
python3 -m fairy.cli \
  -s scenario_two_farm_full_season_hn84_disease_water \
  --build-oracle --run-oracle-tools --replay \
  --output-dir /tmp/two-farm-disease-water
```

该命令实际执行参考工具，再在全新场景回放；不调用大模型。当前已保存的[执行报告](/Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/two_farm_differentiated_20261024/cli_executed/scenario_two_farm_full_season_hn84_disease_water.run_report.json)为completed，共286步，LLM调用0次。

验收情况：

- 全套测试280通过，其中本场景8个测试覆盖配置隔离、工具schema、全田播收、真实作业资源消耗、时间与终态。
- 真正通过`Agent.call_function`逐步执行参考工具，再交全新Engine回放：286步数值前后时间、显示时间、业务返回及完整最终物理/库存/设备状态一致。只排除4类随机操作ID；未调用LLM，不能表述成35B自主规划通过。[Agent与回放验收结果](/Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/two_farm_differentiated_20261024/agent_replay/summary.json)
- 四组各自保存workflow后，再分别交全新Engine回放，数值与显示时间逐项相同，安全入库重量精确相同。
- 多光谱巡查均在白天执行；共享设备无负电量、工具无error/partial；两场均64垄完整收获，粮箱和待入库粮清空，每批13%安全水分。
- `validate()`按要求暂空，返回None；上述完成性来自外部真实运行断言，当前没有实现场景评分。

现有`App.set_seed`用Python进程随机化的`hash()`派生噪声种子，所以不同Python进程的公开传感器读数会略有差异。本文精确公开读数引用`cli_executed`；反事实报告引用它自身的`managed/observations.json`，不能混用。物理初态、天气种子、真实时间及入库重量在这些运行中一致；本次验收的精确观测回放范围为同进程中的全新场景。独立命令间若要逐个噪声数值复现，可在每次启动Python前统一设置同一个`PYTHONHASHSEED=0`；当前保存的不同批次产物没有使用这一固定环境变量。
