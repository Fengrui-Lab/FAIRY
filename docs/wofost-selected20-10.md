# 10｜高密度田保留关键杀菌预算

已完成工程校准；不是田间验证或LLM Agent成绩。原考点：既定高密度背景下，早期轻微信号先复查，把有限杀菌药量留给需要干预的阶段。密度不是官方推荐值，不声称高密度提高产量或自动导致病害；病害事件独立声明。

完整[独立场景](../fairy/scenarios/wofost/scenario_full_season_hb_highdensity_wetjune_limited_fungicide_V2.py)声明全部初值、事件和正常工具步骤；旧文件SHA256 `89fce5d40c310aafafaef92c902cffeedbf018da4e80dc6e36c49353a38e6469` 保持。

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
  "seed_stock": 1300000,
  "warehouse_fertilizer_kg": 0.0,
  "warehouse_pesticide_l": 76.0,
  "warehouse_fuel_l": 1000.0,
  "tractor_fuel_l": 100.0,
  "irrigation_quota_mm": 60.0,
  "active_ingredient_cap_kg": 0.076,
  "max_machine_passes": null,
  "management_regime": "conventional",
  "max_insecticide_applications": null,
  "max_fungicide_applications": 1,
  "max_mechanical_weed_ridges": null,
  "external_biotic_coupling": true,
  "grain_moisture_mode": "soybean_equilibrium",
  "planting_density_plants_m2": 60.0,
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
    "event_id": "early_minor_disease_signal",
    "farm_id": "farm",
    "start": "2019-06-10",
    "end": "2019-06-11",
    "ridge_start": 24,
    "ridge_end": 43,
    "kind": "disease",
    "value": 0.08,
    "mode": "set",
    "repeat": "once"
  },
  {
    "type": "weather",
    "event_id": "early_assessment_window",
    "farm_id": "farm",
    "start": "2019-06-16",
    "end": "2019-06-19",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  },
  {
    "type": "weather",
    "event_id": "later_wet_spell",
    "farm_id": "farm",
    "start": "2019-07-01",
    "end": "2019-07-05",
    "rain_mm": 6.0
  },
  {
    "type": "pressure",
    "event_id": "later_disease_development",
    "farm_id": "farm",
    "start": "2019-07-03",
    "end": "2019-07-04",
    "ridge_start": 24,
    "ridge_end": 43,
    "kind": "disease",
    "value": 0.65,
    "mode": "add",
    "repeat": "once"
  },
  {
    "type": "weather",
    "event_id": "critical_spray_window",
    "farm_id": "farm",
    "start": "2019-07-08",
    "end": "2019-07-11",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  }
]
```

- 60株/m²一垄两行，对应株距3.030303cm，需1132032粒，种子库存130万；仅按既有TDWI/40适配，不把高密度当官方最优。
- 早期0.08轻信号先观察；后期一次add0.65表示独立新的压力输入，不每日set覆盖药效。两次同样层次诊断后只在明确需要时处理。
- 杀菌最多1个施药日、76L恰够20垄一轮3.8L/垄；错误提前用完后不能在后期再次施药。

- 2019-05-23：等待出苗
- 2019-06-16：早期轻微信号辨别
- 2019-07-08：后期病情复查
- 2019-07-09：保留预算至真正需干预阶段窗口
- 2019-07-13：关键处理后复查
- 2019-07-20：关键期根水检查
- 2019-08-08：关键期根水检查
- 2019-09-20：成熟与收获窗口

所有作业通过正常工具耗时推进；机器人每次≤8垄且看真实覆盖，内部4垄一批，充电1h；全田无人机560秒。分趟不冒充多轮农事，dry_grain仍即时抽象；所有机趟及收储批次可在原始轨迹核对。

## 同输入三组对照

|组别|13%商品粮kg|原生平均kgDM/ha|毛水mm|化学活性kg|机械除草垄次|耗油L|调用数|
|---|---:|---:|---:|---:|---:|---:|---:|
|correct|8423.47|4044.76|60|0.076|0|84.00|133|
|none|7797.92|3756.85|60|0|0|80.00|124|
|wrong|7875.87|3793.77|60|0.076|0|84.00|133|

管理定义：correct7月9日正常76L；none不杀菌；wrong6月17日同范围同剂量提前用完，后续无额度。湿期及后期加压独立于oracle，所有策略相同。

正确方案比none的商品粮变化8.022%，比wrong变化6.953%。不把wrong可能存在的部分收益说成完全无效。原生TWSO是干物质，商品粮还需含水率及田间/机器回收损失，单位分开；有机等资源/窗口题按其实际证据解释，不能强称所有差异均为产量。

正确方案共7轮田间农事、133次工具调用（同类同日作业归并；有明示连续作业组时跨午夜仍为一轮，日期和每趟调用另列；失败尝试不计已完成农事轮次）。生产CLI构建、执行、回放、评价全部通过，参数/依赖/起止时间一致；正确对照与生产操作及时间亦一致。

```bash
PYTHONHASHSEED=0 .venv/bin/python -m fairy.cli -s scenario_full_season_hb_highdensity_wetjune_limited_fungicide_V2 \
 --build-oracle --run-oracle-tools --replay --evaluate --output-dir /tmp/wofost-selected20-10
```

完整结果及控制定义保留在[证据目录](../validation_runs/wofost_selected20_20261027/10_calibration)（现有.gitignore忽略的本地验证材料）。[独立产物及三组核验](../validation_runs/wofost_selected20_20261027/10_calibration/static_artifact_audit.json)包含原生干物质、资源、作业范围及时间。
