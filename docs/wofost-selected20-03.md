# 03｜有机田局部草害与机械资源分配

已完成工程校准；不是田间验证或LLM Agent成绩。原考点：有机管理禁止化学除草及其他化学药剂；机械能力只够16垄。根据实际草压分档和冠层/地面检查，优先保护最高草压区；中低草压继续观察，不平均分配机械资源。

完整[独立场景](../fairy/scenarios/wofost/scenario_full_season_hb_organic_weed_pressure_allowed_inputs_V2.py)声明全部初值、事件和正常工具步骤；旧文件SHA256 `6b7fe6a33eabf0884121b2b488823ac6e3100bbb5f08259fcb6f3c9e8dcde2ec` 保持。

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
  "warehouse_pesticide_l": 0.0,
  "warehouse_fuel_l": 1000.0,
  "tractor_fuel_l": 100.0,
  "irrigation_quota_mm": 60.0,
  "active_ingredient_cap_kg": null,
  "max_machine_passes": 2,
  "management_regime": "organic",
  "max_insecticide_applications": null,
  "max_fungicide_applications": null,
  "max_mechanical_weed_ridges": 16,
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
    "event_id": "high_weed_patch",
    "farm_id": "farm",
    "start": "2019-05-24",
    "end": "2019-05-25",
    "ridge_start": 0,
    "ridge_end": 15,
    "kind": "weed",
    "value": 0.8,
    "mode": "set",
    "repeat": "once"
  },
  {
    "type": "pressure",
    "event_id": "medium_weed_patch",
    "farm_id": "farm",
    "start": "2019-05-24",
    "end": "2019-05-25",
    "ridge_start": 16,
    "ridge_end": 31,
    "kind": "weed",
    "value": 0.4,
    "mode": "set",
    "repeat": "once"
  },
  {
    "type": "pressure",
    "event_id": "low_weed_reference",
    "farm_id": "farm",
    "start": "2019-05-24",
    "end": "2019-05-25",
    "ridge_start": 32,
    "ridge_end": 63,
    "kind": "weed",
    "value": 0.08,
    "mode": "set",
    "repeat": "once"
  },
  {
    "type": "weather",
    "event_id": "early_scout_work_window",
    "farm_id": "farm",
    "start": "2019-06-01",
    "end": "2019-06-03",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  }
]
```

- 5月24日三档杂草一次注入，不直接扣产量。
- 6月1日传感器→无人机→三档地面样本；6月2日只对高草压16垄机械除草，2趟为一轮，化学投入0。
- 6月7日复查样本，不声称逐垄全田检查；7月和8月各正常30mm关键期补水。

- 2019-05-23：等待出苗
- 2019-06-01：苗期高低草压分区诊断
- 2019-06-02：高草压16垄一轮机械除草窗口
- 2019-06-07：处理后草压与长势复查
- 2019-06-28：花期阶段根水非缺氮确诊
- 2019-07-20：关键期根水检查
- 2019-08-08：关键期根水检查
- 2019-09-20：成熟与收获窗口

所有作业通过正常工具耗时推进；机器人每次≤8垄且看真实覆盖，内部4垄一批，充电1h；全田无人机560秒。分趟不冒充多轮农事，dry_grain仍即时抽象；所有机趟及收储批次可在原始轨迹核对。

## 同输入三组对照

|组别|13%商品粮kg|原生平均kgDM/ha|毛水mm|化学活性kg|机械除草垄次|耗油L|调用数|
|---|---:|---:|---:|---:|---:|---:|---:|
|correct|7880.60|3757.56|60|0|16|84.00|123|
|none|7208.64|3437.16|60|0|0|80.00|115|
|wrong|7709.12|3675.78|60|0|16|84.00|123|

管理定义：correct为上文正确管理；none仅省略本题关键干预，其他管理/收储相同；wrong为同额度错误分配或错误时机，详情见原始recipe和工具轨迹。

正确方案比none的商品粮变化9.322%，比wrong变化2.224%。不把wrong可能存在的部分收益说成完全无效。原生TWSO是干物质，商品粮还需含水率及田间/机器回收损失，单位分开；有机等资源/窗口题按其实际证据解释，不能强称所有差异均为产量。

正确方案共7轮田间农事、123次工具调用（同类同日作业归并；有明示连续作业组时跨午夜仍为一轮，日期和每趟调用另列；失败尝试不计已完成农事轮次）。生产CLI构建、执行、回放、评价全部通过，参数/依赖/起止时间一致；正确对照与生产操作及时间亦一致。

```bash
PYTHONHASHSEED=0 .venv/bin/python -m fairy.cli -s scenario_full_season_hb_organic_patch_weed_mechanical_capacity_V2 \
 --build-oracle --run-oracle-tools --replay --evaluate --output-dir /tmp/wofost-selected20-03
```

完整结果及控制定义保留在[证据目录](../validation_runs/wofost_selected20_20261027/03_calibration)（现有.gitignore忽略的本地验证材料）。[独立产物及三组核验](../validation_runs/wofost_selected20_20261027/03_calibration/static_artifact_audit.json)包含原生干物质、资源、作业范围及时间。
