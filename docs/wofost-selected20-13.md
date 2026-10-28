# 13｜高密度田局部湿区病害

已完成工程校准；不是田间验证或LLM Agent成绩。原考点：高密度背景下识别局部更湿区的病害，结合雨风和土水在可作业窗口处理。不能因全田平均条件可作业就跳过目标湿区复核；不把高密度本身当成自动病害或官方增产推荐。

完整[独立场景](../fairy/scenarios/wofost/scenario_full_season_hb_wetjune_highdensity_poordrainage_disease_V2.py)声明全部初值、事件和正常工具步骤；旧文件SHA256 `363b8a99499f0841d3c790f6900cea3b819a066d309b9a444e0d29cc60e7095f` 保持。

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
  "warehouse_pesticide_l": 300.0,
  "warehouse_fuel_l": 1000.0,
  "tractor_fuel_l": 100.0,
  "irrigation_quota_mm": 60.0,
  "active_ingredient_cap_kg": 0.3,
  "max_machine_passes": null,
  "management_regime": "conventional",
  "max_insecticide_applications": null,
  "max_fungicide_applications": null,
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
    "type": "weather",
    "event_id": "wet_period",
    "farm_id": "farm",
    "start": "2019-06-18",
    "end": "2019-07-03",
    "rain_mm": 8.0
  },
  {
    "type": "pressure",
    "event_id": "wet_patch_disease",
    "farm_id": "farm",
    "start": "2019-06-22",
    "end": "2019-06-23",
    "ridge_start": 40,
    "ridge_end": 55,
    "kind": "disease",
    "value": 0.65,
    "mode": "set",
    "repeat": "once"
  },
  {
    "type": "weather",
    "event_id": "scout_spray_window",
    "farm_id": "farm",
    "start": "2019-07-08",
    "end": "2019-07-11",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  }
]
```

- 高密度60株/m²、株距3.030303cm、1132032粒，库存130万；同官方901参数仅既有TDWI密度适配。
- 40–55公开较高持水量/较低导水分区，原生水量平衡形成更湿背景；病害仍由独立一次事件声明，不宣称原生病原或自动密度致病。
- 7月8日传感器→无人机→32–63含目标及参考的32垄逐段检查，7月9日真实无雨风窗内只给16病区60.8L；错误组全田也使用3.8L/垄正常剂量，不人为压低剂量制造减产。
- 当前拖拉机门槛是农场平均土水，不冒称原生工具逐湿区禁入；oracle额外检查目标区土水以保持合理操作。

- 2019-05-23：等待出苗
- 2019-06-28：连雨中的根区冠层对照
- 2019-07-08：局部湿区异常确认
- 2019-07-09：只确认湿病区正常剂量杀菌窗口
- 2019-07-14：湿区处理后复查
- 2019-07-20：雨后根水仍较足不例行灌溉
- 2019-08-08：关键期根水检查
- 2019-09-20：成熟与收获窗口

所有作业通过正常工具耗时推进；机器人每次≤8垄且看真实覆盖，内部4垄一批，充电1h；全田无人机560秒。分趟不冒充多轮农事，dry_grain仍即时抽象；所有机趟及收储批次可在原始轨迹核对。

## 同输入三组对照

|组别|13%商品粮kg|原生平均kgDM/ha|毛水mm|化学活性kg|机械除草垄次|耗油L|调用数|
|---|---:|---:|---:|---:|---:|---:|---:|
|correct|8492.88|4072.60|30|0.0608|0|84.00|122|
|none|8030.84|3858.98|30|0|0|80.00|113|
|wrong|8492.88|4072.60|30|0.2432|0|94.00|127|

管理定义：correct只对40–55病区16垄正常3.8L/垄，共60.8L；none不杀菌；wrong全田64垄正常3.8L/垄，共243.2L。药量足以支持两种选择，预期产量相同，错误主要是药耗、油耗和额外机趟，不虚构过度施药减产。

正确方案比none的商品粮变化5.753%，比wrong变化0.000%。不把wrong可能存在的部分收益说成完全无效。原生TWSO是干物质，商品粮还需含水率及田间/机器回收损失，单位分开；有机等资源/窗口题按其实际证据解释，不能强称所有差异均为产量。

正确方案共6轮田间农事、122次工具调用（同类同日作业归并；有明示连续作业组时跨午夜仍为一轮，日期和每趟调用另列；失败尝试不计已完成农事轮次）。生产CLI构建、执行、回放、评价全部通过，参数/依赖/起止时间一致；正确对照与生产操作及时间亦一致。

```bash
PYTHONHASHSEED=0 .venv/bin/python -m fairy.cli -s scenario_full_season_hb_wetjune_highdensity_poordrainage_disease_V2 \
 --build-oracle --run-oracle-tools --replay --evaluate --output-dir /tmp/wofost-selected20-13
```

完整结果及控制定义保留在[证据目录](../validation_runs/wofost_selected20_20261027/13_calibration)（现有.gitignore忽略的本地验证材料）。[独立产物及三组核验](../validation_runs/wofost_selected20_20261027/13_calibration/static_artifact_audit.json)包含原生干物质、资源、作业范围及时间。
