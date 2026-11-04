# 冬小麦模拟农场

这是可直接运行的模拟农场，不是田间观测导入或模型拟合项目。启动场景即可进行整地、装种、播种、水肥管理、越冬、收获与入库；不需要 Excel，也没有 Excel 导入、观测表映射或拟合精度评价接口。

## 管理单位与复用范围

默认一座 **10000 m² 农场，16 个平作管理块，每块 625 m²（100 m × 6.25 m）**。每块有独立的原生 WOFOST 实例、土壤水氮、生育进展、投入和收获状态。可只处理部分块；漏播、少投入和漏收会反映到对应块及农场结果中。小麦采用平作条播，没有大豆起垄步骤。

沿用现有 `FarmWorldApp` / `FarmEnvironment` 的田地、公共时钟和资源归属，以及：

- `SharedTractorApp` 的挂接、装种、装肥、补油、容量检查、收获拒绝检查、卸粮与批次来源。
- `SensorApp` 的根区水氮及冠层观测，`WeatherApp` 的当前天气和短期预报。
- `IrrigationApp` 的供水配额、输送时间和日志。
- `WarehouseApp` 的库存、粮食批次、干燥能力和安全入库。
- `SystemApp` 的时间推进，`OperatingAccounts` 的实际消耗及美元经营账本。

小麦专用子类调整管理块参数、作业覆盖宽度和原生输入，不修改通用工具或此前16个玉米／大豆场景。旧结构中的 `ridge_id`、`ridge_start/end`、粮食批次 `ridge_ids` 在这里指管理块编号，不代表实际起垄。新的田间操作参数使用 `start_block/end_block`，均为两端包含的本地编号。

连续处理相邻块时按其合计宽度计算真实机具路径、耗时和燃油；播种机3 m、撒肥机6 m、收获割台4.4 m。种箱沿用300000粒上限、粮仓沿用2000 kg上限，不能把全田当成一趟机器作业。

## 冬小麦场景

以下是当前推荐运行的场景。

| ID | 场景文件 | 经营情境 |
| --- | --- | --- |
| `scenario_l3_winter_wheat_full_season` | `L3/scenario_winter_wheat_full_season.py` | 普通水价，全季净经营收益 |
| `scenario_l3_winter_wheat_water_limit` | `L3/scenario_winter_wheat_water_limit.py` | 较少季节供水 |
| `scenario_l3_winter_wheat_nitrogen_limit` | `L3/scenario_winter_wheat_nitrogen_limit.py` | 较少尿素库存 |
| `scenario_l3_winter_wheat_block_scouting` | `L3/scenario_winter_wheat_block_scouting.py` | 春季巡查与分块管理 |
| `scenario_l3_winter_wheat_weak_growth_diagnosis` | `L3/scenario_winter_wheat_weak_growth_diagnosis.py` | 诊断缺水和缺氮造成的弱长势，分块处理和复查 |
| `scenario_l3_winter_wheat_stripe_rust` | `L3/scenario_winter_wheat_stripe_rust.py` | 识别条锈病灶，比较局部与全田防治 |
| `scenario_l3_winter_wheat_late_maturing` | `L3/scenario_winter_wheat_late_maturing.py` | 官方 Winter_wheat_101，按较长的灌浆期管理 |
| `scenario_l3_winter_wheat_two_varieties` | `L3/scenario_winter_wheat_two_varieties.py` | 同一农场各半种植 Winter_wheat_104 和 101，分开管理和入库 |
| `scenario_l3_winter_wheat_local_drainage` | `L3/scenario_winter_wheat_local_drainage.py` | 花前后局部积水，按块抽排并复查根区退湿 |
| `scenario_l3_winter_wheat_soil_water_priority` | `L3/scenario_winter_wheat_soil_water_priority.py` | 两种土壤共用配额，按可用水和生育期分水 |

原五个场景的 `detail=true` 给出水深、每块尿素产品重量和关键阶段的参考范围。水肥实际用量仍结合墒情、天气、苗情、可用氮和剩余资源决定。

弱长势诊断、条锈病、晚熟品种、双品种、局部排涝和新版土壤分水的固定 Oracle 位于 `data/winter_wheat_oracles/`，场景文件记录构造和任务描述。Oracle 候选使用公开工具完成全季作业，对照用量、产量和净收益随参考结果保存。品种比较采用同一份官方 WOFOST 参数文件和相同的面积、天气及资源口径。双品种地块分别计算干粮、开花和成熟日期，仓储批次保留品种来源。

### 待定

| ID | 场景文件 | 经营情境 |
| --- | --- | --- |
| `scenario_l3_winter_wheat_high_water_price` | `L3/scenario_winter_wheat_high_water_price.py` | 更高供水价格 |

保留原场景 ID 供历史回放，暂不纳入推荐运行批次。

### 待重做

以下四个保留原场景 ID，供查看和回放历史实验。暂不列入推荐运行批次。

| ID | 场景文件 | 经营情境 |
| --- | --- | --- |
| `scenario_l3_winter_wheat_irrigation_turn` | `L3/scenario_winter_wheat_irrigation_turn.py` | 核对泵站轮次和并行能力，安排两批花前补水 |
| `scenario_l3_winter_wheat_staggered_sowing` | `L3/scenario_winter_wheat_staggered_sowing.py` | 地块分期交接，分别利用合适的播种时段 |
| `scenario_l3_winter_wheat_drying_window` | `L3/scenario_winter_wheat_drying_window.py` | 在短收获窗口和日烘干容量下按期交付 |
| `scenario_l3_winter_wheat_delivery_contract` | `L3/scenario_winter_wheat_delivery_contract.py` | 满足交付量门槛后，尽量降低实际生产成本 |

这些场景从秋播到次年收获，属于L3。各场景文件包含题设、资源配置、参考结果和固定的 `build_events_flow()`。

## 地块巡查

巡查场景使用六个固定观测区和十六个管理块。固定传感器读区域根区水氮和冠层，无人机按块报告 NDVI 和冠层温度代理，机器人到块内读取生育状态和叶片 SPAD 代理。飞行和步巡沿用原设备的天气、电量、时间与覆盖规则。记录各次巡查的时间和覆盖块，报告可用的测量误差。

局部初始土壤氮供应差异由原生 WOFOST 结算。Agent 通过多种观测定位，再决定处理。地块状态查询发布播种与收获所需的状态，氮供应和冠层诊断证据由巡查工具提供。机器人叶片值来自已有 SPAD 观测模型和小麦的原生叶氮状态。这两个巡查场景的病虫草字段为未模拟。条锈病场景使用单独的病程与地面抽样。

运行下文的 CLI 命令时，将场景 ID 换成 `scenario_l3_winter_wheat_block_scouting` 即可执行巡查 Oracle 和回放。油菜可沿用地块编号、设备作业和观测入口，生育和观测值由油菜模型提供。

## 土壤水量优先

浅土区和深土区各 8 块，接受同一份天气并共用季节供水。两区的土壤是模拟参数。逐块查询同时给出根区含水率、原生根深、可用水深及其比例、到田间持水量的净补水缺口。按区比较含水量时，应结合各区的田间持水量、萎蔫点、根深和降雨趋势。灌水完成后按日结算，再复查墒情。

新版季节配额为 950 m³。147 步 Oracle 从 16 条已执行方案中按净收益选出。前两轮先补浅土区，开花后同时补深土区。相同播期、施氮、灌溉日期和每轮水量下，分区方案干籽粒 6,454.99 kg，均分为 6,130.31 kg，全给浅土区为 6,131.13 kg。另行调整日期的均分候选最好为 6,301.66 kg。

默认截止日为 2020 年 8 月 30 日。历史工作流沿用原场景 ID，回放时增加 `"legacy": true` 或 `"late_harvest": false`，即可使用原土壤、1,000 m³ 配额、7 月 15 日截止日和 155 步 Oracle。新版的参数、候选和观测保存在 [Oracle 参考与工作流](data/winter_wheat_oracles/scenario_l3_winter_wheat_soil_water_priority.json)。

## 局部排涝

16 个管理块中，6–9 号块使用独立的浅土层、低渗排和地表蓄水参数，并启用 WOFOST 原生根区缺氧响应。各块接受同一场雨。为使涝害在事前节制灌溉的情况下也能出现，场景在原 NASA POWER 序列的 2020 年 5 月 7 日和 8 日各叠加 60 mm 模拟降雨，合计日雨量为 78.70 和 78.25 mm。这是严重降雨压力测试，土壤和排水价格也是实验设定。

`Drainage.inspect_blocks` 可查逐块积水、根区含水率、连续过湿天数和抽排能力。`Drainage.drain` 按实际地表积水量计费并占用作业时间，次日复查原生结算。根区仍按原生渗排逐日退湿。独立管理块之间没有横向来水。

Oracle 从 14 条候选中选出净收益最高的方案，共 184 步。5 月 9 日抽排 27.23 m³，复查退湿后再分区补水。同水肥下及时排水收获 7251.23 kg 干籽粒，不排为 6964.77 kg，全场 YieldLoss 为 3.95%。相同水肥的排水对照和逐日观测保存在 [Oracle 参考与工作流](data/winter_wheat_oracles/scenario_l3_winter_wheat_local_drainage.json)。

## 代码位置

| 文件 | 职责 |
| --- | --- |
| `apps/winter_wheat_farm_app.py` | 管理块、原生状态到现有设备的投影、简洁的分块查看及状态恢复 |
| `apps/winter_wheat_tractor_app.py` | 复用共享农机操作，补充小麦播种、水肥及收获接口 |
| `apps/winter_wheat_irrigation_app.py` | 灌溉的管理块／mm参数与原生入水 |
| `apps/winter_wheat_accounts_app.py` | 小麦资源配置、价格查询及现成消耗账本 |
| `apps/winter_wheat_scouting_apps.py` | 在地块上复用无人机和机器人作业及原有观测模型 |
| `winter_wheat_setup.py` | 小麦农场、设备和公共时钟接线 |
| `engines/winter_wheat_wofost.py` | 原生PCSE日尺度模型、同日输入合并、原生历史恢复 |
| `engines/winter_wheat_inputs.py` | 本地输入校验、日期和单位 |
| `evaluation/winter_wheat.py` | 全块完成、物资／粮食守恒及带符号Oracle比较 |
| `winter_wheat_oracles.py` | 离线候选执行、有限搜索与现有Engine回放验证 |

## 原生生长与单位

使用真实 PCSE `Wofost81_NWLP_CWB_CNB`（本次验证6.0.13），保留官方 `Winter_wheat_104` 的春化和光周期。原始参数固定在 [WUR官方提交](https://raw.githubusercontent.com/ajwdewit/WOFOST_crop_parameters/1ca91d7dbb5aaf6b41462162de03a8254812d3a5/wheat.yaml)，不是中国品种标定结果。

本目录已包含连续的2019年秋至2020年夏石家庄附近NASA POWER天气和官方参数；日常运行不联网。越冬不重建作物，不跳过闰日。等待可跨多周，仍逐日结算，中途不施加7天等待上限。

普通全季、限水、限氮、高水价和地块巡查默认运行至 **2020 年 8 月 30 日 23:59:59（北京时间）**。补充天气使用同一格点、同一日尺度数据到 8 月 31 日。按原截止日回放历史轨迹时，在场景参数中传入 `"late_harvest": false`。

- `Tractor.fertilize` 接收 **每块kg尿素产品**；纯N/ha = 产品kg × 0.46 ÷ 块面积ha。回收率只用于原生投入，不减少商品消耗。
- `Irrigation.irrigate` 接收 **各选中块的mm毛水深**；m³ = mm × 选中面积m² ÷ 1000。耗时按现有5 mm/h设备计算。
- 当日同类原生信号先合并，不让后一次施用覆盖前一次。跨午夜作业按完成日期登记投入。
- `SM`为模型根区体积含水率，`NAVAIL`为kg N/ha估计；冠层指数由原生LAI投影。这些不是实测化验。土温仅有明确标记的日均气温代理，没有伪造5 cm土温探头。
- 播种率固定为参考用种量；模型没有密度响应，不能声称少播种自动获得相同产量。种子质量／粒数换算为显式物流假设。
- 只能收获原生成熟块。`TWSO`是kg干籽粒/ha，按真实块面积换算一次，再采用明确的95%机械回收率和标准水分换算。沿用仓库的**标准水分质量口径**，干燥不重复增减这份标准质量。

当前不模拟冻死、雪被、倒伏、横向块间水氮流动或成熟后延迟收获损失。条锈病和局部涝害仅在对应场景启用，其他病虫草害未模拟。粮食含水率是物流假设，不是WOFOST动态预测。

## 价格、任务与评价

通过 `OperatingAccounts.get_accounts` 查价格、库存和消耗。`detail=false` 给任务目标和查询入口。`detail=true` 是给 Agent 的人工专家指导。原有五场把提示融入各生育期，说明先观察什么、何时作业或等待调整、作业后复查什么，以及最后如何确认收获入库。具体作业日期、剂量和范围由 Agent 根据观测决定。

延续固定汇率 `1 USD = 7.1757 CNY`。小麦专用价格表为 `data/winter_wheat_prices_2025.json`，复用现有实际消耗账本：种子、尿素、燃油、供水与实际干燥量。自有农机不再另收外包服务费，避免重复收费；不含地租、折旧及普通人工。粮价为固定政策计值基准，种子报价为实验假设，不能当成田间成本调查。

场景通常以净经营收益为目标，最低交付量场景在达标的策略中比较生产成本。水、肥、燃油、预算与仓容为可行性条件。全部块收获、全部粮食安全入库才算完成；一次可补救的工具拒绝不自动判失败。报告保留 YieldLoss 负值，成本和净收益比例为 `(Agent−Oracle)/Oracle`。

Oracle按实际共享设备执行的有限候选比较选出，包含播期、水氮减量、缺投入及分次管理对照，不宣称全局最优。采用真实块、实际机具及库存规则后，旧版全田服务Oracle与轨迹不适用于新版小麦；原有玉米／大豆接口保持原状。

## 运行

在仓库根目录使用安装了项目WOFOST依赖的Python：

```bash
PYTHONPATH=. .venv/bin/python -m fairy.cli \
  --scenario scenario_l3_winter_wheat_full_season \
  --build-oracle --replay --evaluate \
  --scenario-kwargs '{"seed":0,"detailed_briefing":true}' \
  --output-dir validation_runs/winter_wheat_full_season

# 原有四个全季经营场景执行并从JSON轨迹在新农场回放。
PYTHONPATH=. .venv/bin/python -m fairy.scenarios.management_extensions.winter_wheat_oracles \
  verify --output validation_runs/winter_wheat_blocks_verify

# 每场11条候选，输出目录须为新目录。
PYTHONPATH=. .venv/bin/python -m fairy.scenarios.management_extensions.winter_wheat_oracles \
  search --workers 3 --output validation_runs/winter_wheat_blocks_search

PYTHONPATH=. .venv/bin/python -m pytest -q fairy/scenarios/management_extensions/tests
```

实际结果、失败候选及验证记录在 `validation_runs/winter_wheat_blocks_20261104/`；最终以 `release_search/` 和 `release_verify/` 为准，不复用早先全田服务版的成绩。
