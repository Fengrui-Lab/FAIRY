# Thionville shared 2019 weather reference

This bundle pins six NASA POWER AG daily variables at **49.4 N, 6.2 E**, near
Thionville on the France–Luxembourg border. It contains **275 consecutive days,
1 March to 30 November 2019**, for two adjacent simulated farms using the same
weather. These are public gridded weather products, not measurements from the
original cultivar-calibration plots.

`raw/` contains the original API response, byte for byte. `weather.json` exposes
the existing FAIRY `daily` contract. Every normalized value is copied exactly;
there are no fills, rainfall shifts, multipliers or rounding. In particular,
AG solar radiation is already **MJ/m²/day**. The API version, products, response
metadata, units, request URL, byte counts and SHA-256 values are in `manifest.json`.

Daily **LST** labels remain unchanged. The scenario uses Europe/Paris to schedule
jobs and selects forcing by the same local date label; LST is not asserted to be
the same clock as civil time. Elevation 277.87 m is returned by the NASA product,
not a surveyed field elevation.

## Crop-selection rationale

The bundled, pinned official WOFOST YAML describes **Soybean_901** for Northern
France (28 April sowing) and **Grain_maize_201** for Luxembourg/Germany (1 May
sowing). Nearby parcels around the shared border point therefore provide a
reasonable geographical transfer example. The original parameter values remain
unchanged. These are regional model parameter identities, not named commercial
cultivars or a claim of field validation at this location. The official calendar
is a source reference; simulated maturity and actual workable weather determine
the authored management workflow. The exact pinned crop hashes are recorded in
the manifest. Soil, initial nitrogen, density and operations are separately
declared model assumptions, not reconstructed trial inputs.

Sources: [NASA POWER Daily API](https://power.larc.nasa.gov/docs/services/api/temporal/daily/),
[official soybean parameters](https://github.com/ajwdewit/WOFOST_crop_parameters/blob/wofost81/soybean.yaml),
[official maize parameters](https://github.com/ajwdewit/WOFOST_crop_parameters/blob/wofost81/maize.yaml),
[original source report](https://edepot.wur.nl/308997).

## 双农场全季设置与小场先验验证

两块相邻的模拟农场共用上述 Thionville 点天气，使用原始 `Soybean_901`
（法国北部参数组）和 `Grain_maize_201`（德国、卢森堡参数组）。两者的官方
名义播期分别为 4 月 28 日和 5 月 1 日。这里把两场开始及播种安排在
**2019-05-01，Europe/Paris，07:00 起依次作业**，初始播床温度 12°C、
土壤体积含水率 0.26 为公开的场景初值。当天原始天气无雨；不修改原天气来
制造播种窗口。4 月 28 日实际降雨 1.56 mm，5 月 5–6 日最低气温约 −0.6°C，
因此不把官方历日直接解释为当年的最优播期。小场模拟中两种作物均在冷春后
于 5 月下旬出苗；这也不构成真实田间抗霜或成苗率验证。

先验使用每种作物 **1 垄、268 m 长**的小场，经现有整地、播种、水肥工具和
原生 WOFOST 日推进检查管理窗口。大豆垄宽 1.1 m、两行、40 株/m²；玉米垄宽
0.75 m、一行、约 6.67 株/m²。两者都保持官方作物参数及对应的密度归一化
基准，不另拟合品种参数。土壤假设为 WP=0.10、FC=0.30、饱和含水率 0.45、
最大深度 1.2 m、最大入渗 50 mm/day。大豆初始有效氮/储备氮均为 50 kgN/ha，
沿用 0.025 矿化分数；玉米分别为 30/50 kgN/ha，矿化分数为 0.002。
大豆不例行施氮。玉米基肥和 6 月 10 日追肥各按正式 64 垄、1.2864 ha
农场的 200 kg 产品量等比缩放；产品采用 46%N 尿素和 70%N 回收的明确模型
假设。这些土壤、肥料与管理设置不是原校准试验的实测输入。

### 七轮整量补水的依据

每轮补水均为 **30 mm**。大豆使用 90 mm、额度 120 mm；玉米使用 120 mm、
额度 150 mm，参考管理保留余量，不追满额度。去掉了 6 月中旬土壤仍较湿时
不必要的日历补水。下表为小场作业日 07:00、完成前一日结算后的原生真值；
7 天预报合计取随后 1–7 日相同的固定天气。根区缺水量按原生实际根深 RD
计算为 `(FC − SM) × RD_cm × 10`，不把整段 1.2 m 剖面都当成已经扎根。

| 作物 | 日期 | DVS | 根区 SM | RFTRA | 实际根深 cm | 距 FC 的根区缺水 mm | 后 7 日雨 mm |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 大豆 | 07-05 | 1.119 | 0.2076 | 1.000 | 60.4 | 55.8 | 13.76 |
| 大豆 | 07-20 | 1.330 | 0.2024 | 1.000 | 78.4 | 76.5 | 6.44 |
| 大豆 | 08-05 | 1.635 | 0.1667 | 1.000 | 88.0 | 117.3 | 24.73 |
| 玉米 | 07-01 | 0.670 | 0.2115 | 1.000 | 98.0 | 86.7 | 0.80 |
| 玉米 | 07-15 | 0.932 | 0.1907 | 1.000 | 100.0 | 109.3 | 2.43 |
| 玉米 | 08-01 | 1.285 | 0.1581 | 0.816 | 100.0 | 141.9 | 12.88 |
| 玉米 | 08-15 | 1.531 | 0.1604 | 1.000 | 100.0 | 139.6 | 13.72 |

这些补水主要是在开花、结荚/结实和灌浆前后，依据已有亏水和近期降雨防止
亏缺继续扩大；**RFTRA=1 的轮次不能描述为已经发生生理水分胁迫**。
8 月 1 日玉米 RFTRA≈0.816 是已经存在胁迫的明确补救点。8 月 5 日大豆虽然
未来一周有约 24.7 mm 雨，但当时实际根区距 FC 仍缺约 117 mm；30 mm 整轮
补水不会把根区灌到 FC。这里没有搜索零碎小水，也不声称这些日期是数学最优。

### 成熟和自然干燥窗口

| 作物 | 小场读到出苗 | 读到开花 | 首次读到成熟 | 首个满足收割候选条件的日期 | 当时籽粒水分 | 当时根区 SM |
| --- | --- | --- | --- | --- | ---: | ---: |
| 大豆 | 05-24 | 06-28 | 08-30 | 09-09 | 17.00% | 0.2332 |
| 玉米 | 05-22 | 07-19 | 09-15 | 09-20 | 23.57% | 0.1197 |

日期是场景当地读数日。例如 8 月 30 日早上完成 8 月 29 日的 forcing 结算；
PCSE 的 DOM 边界标签为 8 月 30 日，FAIRY 的完成日字段为 8 月 29 日，
不能把它们当成两个不同成熟事件。玉米 9 月 15 日同理。收割候选条件为成熟、
当天无雨、地面可通行，以及大豆不高于 18%/玉米不高于 25% 水分。大豆 9 月
10 日也是候选日，玉米 9 月 21 日也是候选日；秋雨随后会再增湿，不能仅按
生理成熟日期无限延后收获。安全入库仍需检查独立粮批的实际水分和容量。

小场原生 TWSO 参考值约为大豆 **3915 kg 干物质/ha**、玉米 **9836 kg
干物质/ha**。它们仅用于确认这组气象、参数和管理能走完生育期；不是收割后
商品粮、实测产量或任务验收阈值。该先验没有执行全部收割、卸粮、烘干、入库
流程，表中的窗口也不等于已经完成收割。

### 与 128 垄正式运行的边界

正式双农场为每场 64 垄，共 128 垄，并且共用拖拉机、仓库和时钟。单垄预跑
只提供生长和管理日期先验，**不证明正式整季工作流已通过**。真实规模还必须
通过公开工具验证机趟耗时、跨日天气、燃油补给、种箱/肥箱/粮箱容量、共享
物资转移、每垄收获覆盖、粮批干燥入库，以及回放的一致性。较长的真实作业
可能改变后续操作时刻及田间状态，应以正式 128 垄运行的回执和验证结果为准。
天气和官方作物数据无需为这些设备约束而改写。
