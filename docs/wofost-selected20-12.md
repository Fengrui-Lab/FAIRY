# 12｜短暂无雨窗与土壤通行性

已完成工程校准；不是田间验证或LLM Agent成绩。原考点：天晴不等于机械能进地。在短暂无雨窗同时核对天气和土壤通行性；首晴日土壤仍湿，等真实土水回落并在再来雨之前完成定向作业。

完整[独立场景](../fairy/scenarios/wofost/scenario_full_season_hb_wetjune_shortwindow_trafficability_V2.py)声明全部初值、事件和正常工具步骤；旧文件SHA256 `cc76efc8728bff502044ef4c75d498328959544f4b8483ecf19dcc19684f3de9` 保持。

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
  "soil_depth_m": 0.8,
  "wilting_point_vwc": 0.1,
  "field_capacity_vwc": 0.36,
  "saturation_vwc": 0.48,
  "infiltration_mm_day": 10.0,
  "initial_available_n_kg_ha": 50.0,
  "base_soil_n_kg_ha": 50.0,
  "base_fertilizer_kg": 0.0,
  "seed_stock": 1000000,
  "warehouse_fertilizer_kg": 0.0,
  "warehouse_pesticide_l": 100.0,
  "warehouse_fuel_l": 1000.0,
  "tractor_fuel_l": 100.0,
  "irrigation_quota_mm": 60.0,
  "active_ingredient_cap_kg": 0.1,
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
    "event_id": "wet_soil_build_up",
    "farm_id": "farm",
    "start": "2019-05-27",
    "end": "2019-06-01",
    "rain_mm": 25.0
  },
  {
    "type": "pressure",
    "event_id": "wet_period_disease",
    "farm_id": "farm",
    "start": "2019-05-25",
    "end": "2019-05-26",
    "ridge_start": 22,
    "ridge_end": 43,
    "kind": "disease",
    "value": 0.65,
    "mode": "set",
    "repeat": "once"
  },
  {
    "type": "weather",
    "event_id": "short_clear_period",
    "farm_id": "farm",
    "start": "2019-06-01",
    "end": "2019-06-04",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  },
  {
    "type": "weather",
    "event_id": "returning_rain",
    "farm_id": "farm",
    "start": "2019-06-04",
    "end": "2019-06-08",
    "rain_mm": 8.0
  }
]
```

- 5日人工25mm雨与明确浅黏土参数形成真实湿土；无雨窗只有6月1–3日，6月4日重新降雨。
- 6月1日晴但平均土水仍高于0.4，6月2日复查；6月3日确认土水已可通行，完成22–43垄一轮83.6L杀菌，3趟不算3轮。
- 窗口来自真实日历、土水和工具耗时，未修改通行门槛或创建隐藏天气开关。

- 2019-05-23：等待出苗
- 2019-06-01：首晴日先看土水
- 2019-06-02：无雨窗第二日复核土水及余窗
- 2019-06-03：土水及雨风均许可的最后窗口窗口
- 2019-06-08：处理后复查
- 2019-07-20：R3根水与预报检查
- 2019-08-08：关键期根水检查
- 2019-09-20：成熟与收获窗口

所有作业通过正常工具耗时推进；机器人每次≤8垄且看真实覆盖，内部4垄一批，充电1h；全田无人机560秒。分趟不冒充多轮农事，dry_grain仍即时抽象；所有机趟及收储批次可在原始轨迹核对。

## 同输入三组对照

|组别|13%商品粮kg|原生平均kgDM/ha|毛水mm|化学活性kg|机械除草垄次|耗油L|调用数|
|---|---:|---:|---:|---:|---:|---:|---:|
|correct|7980.09|3839.38|30|0.0836|0|86.00|121|
|none|7107.07|3419.10|30|0|0|80.00|111|
|wrong|7107.07|3419.10|30|0|0|80.00|121|

管理定义：correct在土水和天气均许可的6月3日作业；none不杀菌；wrong6月1日已装药但每次进地均被真实湿土检查拒绝，未产生有效处理，完成性validate保留预期工具错误。

正确方案比none的商品粮变化12.284%，比wrong变化12.284%。不把wrong可能存在的部分收益说成完全无效。原生TWSO是干物质，商品粮还需含水率及田间/机器回收损失，单位分开；有机等资源/窗口题按其实际证据解释，不能强称所有差异均为产量。

正确方案共6轮田间农事、121次工具调用（同类同日作业归并；有明示连续作业组时跨午夜仍为一轮，日期和每趟调用另列；失败尝试不计已完成农事轮次）。生产CLI构建、执行、回放、评价全部通过，参数/依赖/起止时间一致；正确对照与生产操作及时间亦一致。

```bash
PYTHONHASHSEED=0 .venv/bin/python -m fairy.cli -s scenario_full_season_hb_wetjune_shortwindow_trafficability_V2 \
 --build-oracle --run-oracle-tools --replay --evaluate --output-dir /tmp/wofost-selected20-12
```

完整结果及控制定义保留在[证据目录](../validation_runs/wofost_selected20_20261027/12_calibration)（现有.gitignore忽略的本地验证材料）。[独立产物及三组核验](../validation_runs/wofost_selected20_20261027/12_calibration/static_artifact_audit.json)包含原生干物质、资源、作业范围及时间。
