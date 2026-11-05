# 18｜错期播种与分区病害管理

已完成工程校准；不是田间验证或LLM Agent成绩。原考点：同品种早晚两播区长势不同，湿季先比较各区阶段与同播区参照，再用地面检查确认病害；只对确认病区施药，并各区分别收获。不能把迟播冠层未封行或低NDVI直接当病害。

完整[独立场景](../fairy/scenarios/wofost/scenario_full_season_hb_staggered_wetjune_canopy_disease_V2.py)声明全部初值、事件和正常工具步骤；旧文件SHA256 `ff668c5034763b2abec1e2914be6e30982fa727cf2af2d6105cd2883e0081d39` 保持。

## 初始世界与边界

```json
{
  "reference_id": "lille",
  "seed_type": "SOYBEAN_901",
  "timezone_name": "Europe/Paris",
  "sowing_date": "2019-04-28",
  "end_date": "2019-11-15",
  "farm_id": "farm",
  "num_ridges": 64,
  "field_length_m": 268.0,
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
  "seed_stock": 1000000,
  "warehouse_fertilizer_kg": 0.0,
  "warehouse_pesticide_l": 122.0,
  "warehouse_fuel_l": 1000.0,
  "tractor_fuel_l": 100.0,
  "irrigation_quota_mm": 30.0,
  "active_ingredient_cap_kg": 0.122,
  "max_machine_passes": null,
  "management_regime": "conventional",
  "max_insecticide_applications": null,
  "max_fungicide_applications": 1,
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
    "event_id": "late_sowing_window",
    "farm_id": "farm",
    "start": "2019-05-28",
    "end": "2019-05-29",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  },
  {
    "type": "weather",
    "event_id": "wet_canopy_spell",
    "farm_id": "farm",
    "start": "2019-06-18",
    "end": "2019-07-03",
    "rain_mm": 6.0
  },
  {
    "type": "pressure",
    "event_id": "early_closed_canopy_disease",
    "farm_id": "farm",
    "start": "2019-06-25",
    "end": "2019-06-26",
    "ridge_start": 0,
    "ridge_end": 31,
    "kind": "disease",
    "value": 0.65,
    "mode": "set",
    "repeat": "once"
  },
  {
    "type": "weather",
    "event_id": "split_diagnosis_and_spray",
    "farm_id": "farm",
    "start": "2019-07-07",
    "end": "2019-07-09",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  },
  {
    "type": "weather",
    "event_id": "harvest_clear_spell",
    "farm_id": "farm",
    "start": "2019-09-20",
    "end": "2019-10-09",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  }
]
```

- 同一官方地区品种按4/28与5/28真实建植，分别确认出苗；旧题6天延后调整为本固定天气下的合法30天。
- 6/18–7/3人工6mm/day湿期；6/25早区一次施加外接病害，非原生闭合冠层病原传播。
- 7/7先看两播区公开阶段/根水/冠层，再全田无人机；机器人四个8垄任务覆盖早区32垄，另8垄迟区参照。单次≤8，累计16垄后实际充电。
- 7/8只给地面确认早区0–31垄正常3.8L/垄，121.6L、一个施药日；7/12复查两端样本，不把迟播长势当疾病。
- 湿季不例行7月补水，8/8根水核对后全田30mm；两播区分别9/20、10/7收储，人工无雨窗口只改雨风。

- 2019-05-23：早区出苗样本
- 2019-05-28：迟区独立播床检查
- 2019-06-15：迟区出苗样本
- 2019-07-07：两播区阶段与病情鉴别
- 2019-07-08：确认早区杀菌窗口
- 2019-07-12：处理后分区复查
- 2019-08-08：关键期根水检查
- 2019-09-20：成熟与收获窗口
- 2019-10-07：成熟与收获窗口

所有作业通过正常工具耗时推进；机器人每次≤8垄且看真实覆盖，内部4垄一批，充电1h；全田无人机560秒。分趟不冒充多轮农事，dry_grain仍即时抽象；所有机趟及收储批次可在原始轨迹核对。

## 同输入三组对照

|组别|13%商品粮kg|原生平均kgDM/ha|毛水mm|化学活性kg|机械除草垄次|耗油L|调用数|
|---|---:|---:|---:|---:|---:|---:|---:|
|correct|7637.92|3702.53|30|0.1216|0|88.00|137|
|none|6673.76|3258.80|30|0|0|80.00|126|
|wrong|6673.76|3258.80|30|0.1216|0|88.00|137|

管理定义：correct只给确认病害的早区32垄121.6L；none省略杀菌；wrong同日把同量121.6L用于较迟的健康32垄。所有组实际播期、事件、灌水与分区收储相同；错误用药不虚构额外药害。

正确方案比none的商品粮变化14.447%，比wrong变化14.447%。不把wrong可能存在的部分收益说成完全无效。原生TWSO是干物质，商品粮还需含水率及田间/机器回收损失，单位分开；有机等资源/窗口题按其实际证据解释，不能强称所有差异均为产量。

正确方案共8轮田间农事、137次工具调用（同类同日作业归并；有明示连续作业组时跨午夜仍为一轮，日期和每趟调用另列；失败尝试不计已完成农事轮次）。生产CLI构建、执行、回放、评价全部通过，参数/依赖/起止时间一致；正确对照与生产操作及时间亦一致。

```bash
PYTHONHASHSEED=0 .venv/bin/python -m fairy.cli -s scenario_full_season_hb_staggered_wetjune_canopy_disease_V2 \
 --build-oracle --run-oracle-tools --replay --evaluate --output-dir /tmp/wofost-selected20-18
```

完整结果及控制定义保留在[证据目录](../validation_runs/wofost_selected20_20261027/18_calibration)（现有.gitignore忽略的本地验证材料）。[独立产物及三组核验](../validation_runs/wofost_selected20_20261027/18_calibration/static_artifact_audit.json)包含原生干物质、资源、作业范围及时间。
