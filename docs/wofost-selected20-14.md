# 14｜连作病史与局部湿区管理

已完成工程校准；不是田间验证或LLM Agent成绩。原考点：交接病史与局部偏湿是重点巡查线索而非确诊。根据当季地面证据处理后仍需跟踪再发展；病史通过明确背景和独立压力事件承载，不宣称原生轮作/病原残留模型。

完整[独立场景](../fairy/scenarios/wofost/scenario_full_season_hb_wetjune_soyhistory_poordrainage_disease_V2.py)声明全部初值、事件和正常工具步骤；旧文件SHA256 `3af37462fc397dde15ceccd83026cccec09f7e3527c4305057fa25e8ba37b8cd` 保持。

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
  "warehouse_pesticide_l": 200.0,
  "warehouse_fuel_l": 1000.0,
  "tractor_fuel_l": 100.0,
  "irrigation_quota_mm": 60.0,
  "active_ingredient_cap_kg": 0.2,
  "max_machine_passes": null,
  "management_regime": "conventional",
  "max_insecticide_applications": null,
  "max_fungicide_applications": 2,
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
    "event_id": "first_wet_period",
    "farm_id": "farm",
    "start": "2019-06-25",
    "end": "2019-07-04",
    "rain_mm": 6.0
  },
  {
    "type": "pressure",
    "event_id": "history_zone_first_disease",
    "farm_id": "farm",
    "start": "2019-06-25",
    "end": "2019-06-26",
    "ridge_start": 20,
    "ridge_end": 35,
    "kind": "disease",
    "value": 0.5,
    "mode": "set",
    "repeat": "once"
  },
  {
    "type": "weather",
    "event_id": "first_spray_window",
    "farm_id": "farm",
    "start": "2019-07-04",
    "end": "2019-07-07",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  },
  {
    "type": "weather",
    "event_id": "later_wet_period",
    "farm_id": "farm",
    "start": "2019-07-22",
    "end": "2019-07-25",
    "rain_mm": 8.0
  },
  {
    "type": "pressure",
    "event_id": "history_zone_new_infection",
    "farm_id": "farm",
    "start": "2019-07-24",
    "end": "2019-07-25",
    "ridge_start": 20,
    "ridge_end": 35,
    "kind": "disease",
    "value": 0.5,
    "mode": "add",
    "repeat": "once"
  },
  {
    "type": "weather",
    "event_id": "second_spray_window",
    "farm_id": "farm",
    "start": "2019-07-25",
    "end": "2019-07-28",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  }
]
```

- 公开病史与20–35较湿土壤作为巡查先验；当季病害由世界一次set0.5及后来一次add0.5明确注入，不靠oracle触发。
- 7月5日60.8L首轮后7月10日复查；14日残效后7月24日独立新感染，7月25日确认后7月26日第二轮60.8L。
- 两轮共121.6L/0.1216kg，始终留有余额，不为用完药量加喷；湿期后不例行7月补水，8月一次30mm。

- 2019-05-23：等待出苗
- 2019-06-28：病史区雨中重点巡视
- 2019-07-04：首次证据确认
- 2019-07-05：首次确诊后正常剂量杀菌窗口
- 2019-07-10：首次处理后必须跟踪
- 2019-07-25：病史湿区新发展核查
- 2019-07-26：复查证实再发展后二轮处理窗口
- 2019-08-01：第二轮后继续跟踪
- 2019-08-08：关键期根水检查
- 2019-09-20：成熟与收获窗口

所有作业通过正常工具耗时推进；机器人每次≤8垄且看真实覆盖，内部4垄一批，充电1h；全田无人机560秒。分趟不冒充多轮农事，dry_grain仍即时抽象；所有机趟及收储批次可在原始轨迹核对。

## 同输入三组对照

|组别|13%商品粮kg|原生平均kgDM/ha|毛水mm|化学活性kg|机械除草垄次|耗油L|调用数|
|---|---:|---:|---:|---:|---:|---:|---:|
|correct|8571.24|4108.33|30|0.1216|0|88.00|145|
|none|7887.04|3793.61|30|0|0|80.00|127|
|wrong|8161.68|3924.94|30|0.0608|0|84.00|136|

管理定义：correct根据病史重点巡查并在再发展后第二轮处理；none不杀菌；wrong仅第一次处理，虽复查仍忽略后续新发展。其余世界、土壤、资源、作业和收储相同。

正确方案比none的商品粮变化8.675%，比wrong变化5.018%。不把wrong可能存在的部分收益说成完全无效。原生TWSO是干物质，商品粮还需含水率及田间/机器回收损失，单位分开；有机等资源/窗口题按其实际证据解释，不能强称所有差异均为产量。

正确方案共7轮田间农事、145次工具调用（同类同日作业归并；有明示连续作业组时跨午夜仍为一轮，日期和每趟调用另列；失败尝试不计已完成农事轮次）。生产CLI构建、执行、回放、评价全部通过，参数/依赖/起止时间一致；正确对照与生产操作及时间亦一致。

```bash
PYTHONHASHSEED=0 .venv/bin/python -m fairy.cli -s scenario_full_season_hb_wetjune_soyhistory_poordrainage_disease_V2 \
 --build-oracle --run-oracle-tools --replay --evaluate --output-dir /tmp/wofost-selected20-14
```

完整结果及控制定义保留在[证据目录](../validation_runs/wofost_selected20_20261027/14_calibration)（现有.gitignore忽略的本地验证材料）。[独立产物及三组核验](../validation_runs/wofost_selected20_20261027/14_calibration/static_artifact_audit.json)包含原生干物质、资源、作业范围及时间。
