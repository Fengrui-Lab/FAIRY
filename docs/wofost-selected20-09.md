# 09｜缺水与虫害分区处理

已完成工程校准；不是田间验证或LLM Agent成绩。原考点：一块区域缺水，另一块有虫害；先由根区与冠层定位，再地面确认。分别灌溉和杀虫，不能把同量资源全田均摊或用一种处理替代另一种。

完整[独立场景](../fairy/scenarios/wofost/scenario_full_season_hb_dryr5r6_insect_threshold_waterstress_V2.py)声明全部初值、事件和正常工具步骤；旧文件SHA256 `369884d9d31e9aca313d3213fbe84d1173a65dd3fbacd0dcab576eebdbb99bcc` 保持。

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
  "warehouse_pesticide_l": 150.0,
  "warehouse_fuel_l": 1000.0,
  "tractor_fuel_l": 100.0,
  "irrigation_quota_mm": 69.0,
  "active_ingredient_cap_kg": 0.15,
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
    "type": "drought",
    "event_id": "r3_r5_dry_period",
    "farm_id": "farm",
    "start": "2019-07-10",
    "end": "2019-08-16",
    "rain_multiplier": 0.0
  },
  {
    "type": "pressure",
    "event_id": "separate_insect_patch",
    "farm_id": "farm",
    "start": "2019-07-24",
    "end": "2019-07-25",
    "ridge_start": 30,
    "ridge_end": 47,
    "kind": "insect",
    "value": 0.65,
    "mode": "set",
    "repeat": "once"
  },
  {
    "type": "weather",
    "event_id": "diagnostic_and_treatment_wind",
    "farm_id": "farm",
    "start": "2019-07-26",
    "end": "2019-07-30",
    "wind_ms": 2.0
  }
]
```

- 10–27垄为公开浅土低捕雨分区，干旱作用于真实水量平衡；30–47为世界一次虫压注入。
- 7月26日传感器→无人机→8–47分段40垄，正常充电并区分虫害与缺水。7月27日仅10–27一次30mm，7月28日仅30–47以8L/垄杀虫。
- 正确和错误额外水都相当全田8.4375mm、药液都144L，错误把水与药均摊全田；非每天小水。总水68.4375/69mm。

- 2019-05-23：等待出苗
- 2019-06-28：花期根水
- 2019-07-20：关键期根水检查
- 2019-07-26：两类空间异常诊断
- 2019-07-27：关键期根水检查
- 2019-07-28：仅虫区正常剂量杀虫窗口
- 2019-08-01：两区分别复查
- 2019-08-08：关键期根水检查
- 2019-09-20：成熟与收获窗口

所有作业通过正常工具耗时推进；机器人每次≤8垄且看真实覆盖，内部4垄一批，充电1h；全田无人机560秒。分趟不冒充多轮农事，dry_grain仍即时抽象；所有机趟及收储批次可在原始轨迹核对。

## 同输入三组对照

|组别|13%商品粮kg|原生平均kgDM/ha|毛水mm|化学活性kg|机械除草垄次|耗油L|调用数|
|---|---:|---:|---:|---:|---:|---:|---:|
|correct|6857.01|3278.30|68.44|0.144|0|84.00|130|
|none|6072.11|2919.11|60|0|0|80.00|116|
|wrong|6533.04|3136.52|68.44|0.144|0|94.00|135|

管理定义：correct局部水30mm+另一区8L/垄杀虫；none仅省略这两项定向干预、保留普通两次全田水；wrong额外水与药总量完全相同，但分别均摊全田8.4375mm与2.25L/垄。

正确方案比none的商品粮变化12.926%，比wrong变化4.959%。不把wrong可能存在的部分收益说成完全无效。原生TWSO是干物质，商品粮还需含水率及田间/机器回收损失，单位分开；有机等资源/窗口题按其实际证据解释，不能强称所有差异均为产量。

正确方案共8轮田间农事、130次工具调用（同类同日作业归并；有明示连续作业组时跨午夜仍为一轮，日期和每趟调用另列；失败尝试不计已完成农事轮次）。生产CLI构建、执行、回放、评价全部通过，参数/依赖/起止时间一致；正确对照与生产操作及时间亦一致。

```bash
PYTHONHASHSEED=0 .venv/bin/python -m fairy.cli -s scenario_full_season_hb_dryr5r6_insect_threshold_waterstress_V2 \
 --build-oracle --run-oracle-tools --replay --evaluate --output-dir /tmp/wofost-selected20-09
```

完整结果及控制定义保留在[证据目录](../validation_runs/wofost_selected20_20261027/09_calibration)（现有.gitignore忽略的本地验证材料）。[独立产物及三组核验](../validation_runs/wofost_selected20_20261027/09_calibration/static_artifact_audit.json)包含原生干物质、资源、作业范围及时间。
