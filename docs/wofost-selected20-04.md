# 04｜雨后机械除草窗口

已完成工程校准；不是田间验证或LLM Agent成绩。原考点：有机禁药；雨停不等于土壤能进机械。由真实土壤水量平衡使首个晴日仍超过0.40通行阈值，等待土壤回落再全田除草；不能把天晴当作唯一条件。

完整[独立场景](../fairy/scenarios/wofost/scenario_full_season_hb_mechanical_weed_control_soil_wetness_V2.py)声明全部初值、事件和正常工具步骤；旧文件SHA256 `9be0da9e9ff3bb46e285029c595a6cc59c22eb5c8fe5f85cc454be66e76c45c8` 保持。

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
  "warehouse_pesticide_l": 0.0,
  "warehouse_fuel_l": 1000.0,
  "tractor_fuel_l": 100.0,
  "irrigation_quota_mm": 60.0,
  "active_ingredient_cap_kg": null,
  "max_machine_passes": 7,
  "management_regime": "organic",
  "max_insecticide_applications": null,
  "max_fungicide_applications": null,
  "max_mechanical_weed_ridges": 64,
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
    "type": "pressure",
    "event_id": "post_rain_weeds",
    "farm_id": "farm",
    "start": "2019-05-25",
    "end": "2019-05-26",
    "ridge_start": 0,
    "ridge_end": 63,
    "kind": "weed",
    "value": 0.75,
    "mode": "set",
    "repeat": "once"
  },
  {
    "type": "weather",
    "event_id": "wet_spell",
    "farm_id": "farm",
    "start": "2019-05-27",
    "end": "2019-06-01",
    "rain_mm": 25.0,
    "wind_ms": 2.0
  },
  {
    "type": "weather",
    "event_id": "clear_operational_period",
    "farm_id": "farm",
    "start": "2019-06-01",
    "end": "2019-06-06",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  }
]
```

- 5月27日至31日人工每日25mm雨，共125mm；土壤FC0.36/饱和0.48/导水10mm/day是明确黏性土假设，不改作物参数。
- 6月1日全田粗查与地面样本后土壤仍湿，不进机械；6月2日复核；6月3日只在真实通行条件许可后全田一轮7趟机械除草。

- 2019-05-23：等待出苗
- 2019-06-01：雨已停但先核对土壤
- 2019-06-02：复核第二个晴日土壤
- 2019-06-03：等土水低于通行阈值后全田一轮除草窗口
- 2019-06-08：除草后复查
- 2019-06-28：花期水分复核
- 2019-07-20：R3根水检查而非例行灌水
- 2019-08-08：关键期根水检查
- 2019-09-20：成熟与收获窗口

所有作业通过正常工具耗时推进；机器人每次≤8垄且看真实覆盖，内部4垄一批，充电1h；全田无人机560秒。分趟不冒充多轮农事，dry_grain仍即时抽象；所有机趟及收储批次可在原始轨迹核对。

## 同输入三组对照

|组别|13%商品粮kg|原生平均kgDM/ha|毛水mm|化学活性kg|机械除草垄次|耗油L|调用数|
|---|---:|---:|---:|---:|---:|---:|---:|
|correct|8299.36|3957.21|30|0|64|94.00|123|
|none|5677.44|2707.04|30|0|0|80.00|110|
|wrong|5677.44|2707.04|30|0|0|80.00|112|

管理定义：correct等待土壤许可后除草；none不除草；wrong在首晴日强行进入，被真实工具拒绝后未有效除草，其完成性validate保留预期工具错误，不冒称合法作业成功。三组其余农事相同。

正确方案比none的商品粮变化46.181%，比wrong变化46.181%。不把wrong可能存在的部分收益说成完全无效。原生TWSO是干物质，商品粮还需含水率及田间/机器回收损失，单位分开；有机等资源/窗口题按其实际证据解释，不能强称所有差异均为产量。

正确方案共6轮田间农事、123次工具调用（同类同日作业归并；有明示连续作业组时跨午夜仍为一轮，日期和每趟调用另列；失败尝试不计已完成农事轮次）。生产CLI构建、执行、回放、评价全部通过，参数/依赖/起止时间一致；正确对照与生产操作及时间亦一致。

```bash
PYTHONHASHSEED=0 .venv/bin/python -m fairy.cli -s scenario_full_season_hb_mechanical_weed_trafficability_window_V2 \
 --build-oracle --run-oracle-tools --replay --evaluate --output-dir /tmp/wofost-selected20-04
```

完整结果及控制定义保留在[证据目录](../validation_runs/wofost_selected20_20261027/04_calibration)（现有.gitignore忽略的本地验证材料）。[独立产物及三组核验](../validation_runs/wofost_selected20_20261027/04_calibration/static_artifact_audit.json)包含原生干物质、资源、作业范围及时间。
