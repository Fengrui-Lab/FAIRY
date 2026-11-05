# 20｜晚雨前有限时间内分区抢收

已完成工程校准；不是田间验证或LLM Agent成绩。原考点：根据各区真实成熟度、粮食含水率、2t粮箱和实际收割/卸粮耗时安排晚雨前抢收；不能等最湿区而错过已可收区，也不能把容量分趟冒充多轮农事。

完整[独立场景](../fairy/scenarios/wofost/scenario_full_season_hb_harvester_days_limit_laterain_V2.py)声明全部初值、事件和正常工具步骤；旧文件SHA256 `bb1eda7a0e76c06cab5f20d84205ac6c7d5443021199eff252aea69a9e5e4ee8` 保持。

## 初始世界与边界

```json
{
  "reference_id": "lille",
  "seed_type": "SOYBEAN_901",
  "timezone_name": "Europe/Paris",
  "sowing_date": "2019-04-27",
  "end_date": "2019-11-15",
  "farm_id": "farm",
  "num_ridges": 64,
  "field_length_m": 2000.0,
  "ridge_width_m": 1.1,
  "initial_vwc": 0.26,
  "initial_soil_temperature_c": 12.0,
  "soil_depth_m": 1.2,
  "wilting_point_vwc": 0.1,
  "field_capacity_vwc": 0.3,
  "saturation_vwc": 0.45,
  "infiltration_mm_day": 50.0,
  "initial_available_n_kg_ha": 50.0,
  "base_soil_n_kg_ha": 50.0,
  "base_fertilizer_kg": 0.0,
  "seed_stock": 7000000,
  "warehouse_fertilizer_kg": 0.0,
  "warehouse_pesticide_l": 0.0,
  "warehouse_fuel_l": 5000.0,
  "tractor_fuel_l": 100.0,
  "irrigation_quota_mm": 60.0,
  "active_ingredient_cap_kg": null,
  "max_machine_passes": null,
  "management_regime": "conventional",
  "max_insecticide_applications": null,
  "max_fungicide_applications": null,
  "max_mechanical_weed_ridges": null,
  "external_biotic_coupling": true,
  "grain_moisture_mode": "soybean_equilibrium",
  "planting_density_plants_m2": 45.0,
  "required_field_preparation_ops": [
    "level",
    "form_ridges"
  ]
}
```

官方地区参数及固定NASA POWER天气来源见[固定数据清单](../fairy/physics/data/wofost/research/official_soybean_nasa2019_v1/manifest.json)。官方作物参数无覆盖，TDWI仅沿既有实际密度/40初始化；不冒充商业黑农品种、不称官方最优密度。土壤、资源、局部外接病虫草与人工雨风事件为明确场景设定。病虫草非WOFOST原生病原模型；营养/表层观测有代理限制；不新增固氮机制。

## 事件与完整农事

```json
[
  {
    "type": "weather",
    "event_id": "spring_preparation_and_early_sowing",
    "farm_id": "farm",
    "start": "2019-04-27",
    "end": "2019-04-30",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  },
  {
    "type": "weather",
    "event_id": "late_sowing_window",
    "farm_id": "farm",
    "start": "2019-05-11",
    "end": "2019-05-12",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  },
  {
    "type": "weather",
    "event_id": "growth_baseline_scouting",
    "farm_id": "farm",
    "start": "2019-06-28",
    "end": "2019-06-29",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  },
  {
    "type": "weather",
    "event_id": "preharvest_wet_days",
    "farm_id": "farm",
    "start": "2019-09-12",
    "end": "2019-09-22",
    "rain_mm": 1.0,
    "wind_ms": 2.0
  },
  {
    "type": "weather",
    "event_id": "one_clear_harvest_day",
    "farm_id": "farm",
    "start": "2019-09-22",
    "end": "2019-09-23",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  },
  {
    "type": "weather",
    "event_id": "late_storm",
    "farm_id": "farm",
    "start": "2019-09-23",
    "end": "2019-09-27",
    "rain_mm": 15.0,
    "wind_ms": 2.0
  },
  {
    "type": "weather",
    "event_id": "post_storm_clear_spell",
    "farm_id": "farm",
    "start": "2019-09-27",
    "end": "2019-10-20",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  }
]
```

- 地块改为64×2000×1.1m=14.08ha，保持45株/m²、一垄两行、工具株距4.040404…cm；每垄99000粒，总6336000粒，库存700万。播种每趟最多3垄受30万粒种箱约束。
- 4/27开始正常平地/起垄，真实耗时跨日，期间按实测余油正常加油；4/28早区0–31、5/11迟区32–63实际播种。没有预先伪造整地完成，也没有跳过工具时间。
- 出苗各单垄样本；6/28传感器—4030秒全田无人机—两区各1垄5030秒地面基线检查；7/20与8/8各30mm常规补水。
- 秋季9/12–22人工1mm/day雨期，9/22无雨，9/23–27人工15mm/day雨期，9/27–10/20人工无雨。温湿辐射保留固定NASA原值。不是连续小时级实况；沿用工具每日雨天禁收判据。
- 9/18、9/21预查；9/22公开早区R8/15.98%、迟区R8/18.18%，迟区超过18%上限。先收早区，首垄正常收割后看实际粮箱重量与2t容量。
- 每垄收割1830秒、卸粮480秒，单垄粮箱批次；雨前从07:00到次日雨起仅17h，26垄60,060秒，余时不足下一趟1830秒，不尝试跨雨夜抢收。持续一轮26趟，不称26轮。
- 9/27、10/1复查雨后粮水与通行性，10/4两区均≤18%后续收余下38垄；该连续收储会跨午夜，仍是同一轮续收。dry_grain即时抽象，不借虚构干燥瓶颈限产。
- 全季max_machine_passes=None，未把旧40次机械额度当收割约束。对照不抢收及误等较湿区，完整收储并比较回收损失；WOFOST干物质单列，不直接扣产量。

- 2019-04-28：早区播床需实测
- 2019-05-11：迟区播床需实测
- 2019-05-23：早区出苗单垄样本
- 2019-06-01：迟区出苗单垄样本
- 2019-06-28：生长期独立基线巡查
- 2019-07-20：关键期根水检查
- 2019-08-08：关键期根水检查
- 2019-09-18：收获前分区阶段粮水和雨窗
- 2019-09-21：收获前分区阶段粮水和雨窗
- 2019-09-22：唯一雨前无雨窗
- 2019-09-27：暴雨后重新检查可收条件
- 2019-10-01：暴雨后重新检查可收条件
- 2019-10-04：雨后两区均达到可收粮水

所有作业通过正常工具耗时推进；机器人每次≤8垄且看真实覆盖，内部4垄一批，充电1h；全田无人机4030秒。分趟不冒充多轮农事，dry_grain仍即时抽象；所有机趟及收储批次可在原始轨迹核对。

## 同输入三组对照

|组别|13%商品粮kg|原生平均kgDM/ha|毛水mm|化学活性kg|机械除草垄次|耗油L|调用数|
|---|---:|---:|---:|---:|---:|---:|---:|
|correct|65919.34|4321.93|60|0|0|1402.99|412|
|none|64671.04|4321.93|60|0|0|1402.99|406|
|wrong|64671.04|4321.93|60|0|0|1402.99|411|

管理定义：correct在9/22合法窗口先收已达粮水要求的早区26垄，10/4续收余38垄；none完全错过雨前窗口，10/4才开始全田收获；wrong在9/22把尚18.18%的迟区列首位，32垄单垄尝试被原工具拒绝，随后误等两区一起收，亦10/4才全田收。拒绝不虚构时间或燃油惩罚；损失来自错过实际可收窗口与后续留田/风雨回收损失。3组世界、生长期水肥及每垄最终收储相同；wrong的validate失败记录仅为预期非法尝试。

正确方案比none的商品粮变化1.930%，比wrong变化1.930%。不把wrong可能存在的部分收益说成完全无效。原生TWSO是干物质，商品粮还需含水率及田间/机器回收损失，单位分开；有机等资源/窗口题按其实际证据解释，不能强称所有差异均为产量。

正确方案共8轮田间农事、412次工具调用（同类同日作业归并；有明示连续作业组时跨午夜仍为一轮，日期和每趟调用另列；失败尝试不计已完成农事轮次）。生产CLI构建、执行、回放、评价全部通过，参数/依赖/起止时间一致；正确对照与生产操作及时间亦一致。

```bash
PYTHONHASHSEED=0 .venv/bin/python -m fairy.cli -s scenario_full_season_hb_harvester_days_limit_laterain_V2 \
 --build-oracle --run-oracle-tools --replay --evaluate --output-dir /tmp/wofost-selected20-20
```

完整结果及控制定义保留在[证据目录](../validation_runs/wofost_selected20_20261027/20_calibration)（现有.gitignore忽略的本地验证材料）。[独立产物及三组核验](../validation_runs/wofost_selected20_20261027/20_calibration/static_artifact_audit.json)包含原生干物质、资源、作业范围及时间。

## 真实容量、时间和回收差异

雨前首垄公共粮箱读数为1058.15kg（工具按13%标准重量记账），两个同类垄已超过2t；雨后仍遵守工具的保守装箱上界，使用单垄批次。9/22从07:00到23:41正常完成26趟收割和26次卸粮，共60,060秒；距次日15mm/day降雨只有1140秒，小于下一趟收割1830秒。收割允许夜间进行，没有另加每日工作小时上限，也没有把max_machine_passes当收割约束。

10/4续收38垄，10/5 07:23完成；对照从10/4才全田收，于10/6 00:04完成。正确方案8轮农事、412次工具调用，64趟收割和64批卸粮/干燥/入库；雨后跨午夜是同一轮续收。全季耗油1402.9851L、毛水60mm=8448m³、肥药0。加油按实际转移量统计，“油箱已满”不算又加了100L。

三组原生平均4321.9289kgDM/ha、原生总60852.7589kgDM相同，商品粮65919.34/64671.04/64671.04kg；正确方案少损失1248.30kg（1.9302%）。差异来自收获/风雨后回收，不是直接改WOFOST产量。场景人工雨风逐段声明，温湿度和辐射保留固定NASA原值；每日雨天禁收与即时干燥均为现有工具边界。
