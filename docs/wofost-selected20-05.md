# 05｜花期凉湿与局部病害

已完成工程校准；不是田间验证或LLM Agent成绩。原考点：花期遇凉湿天气后，先确定局部病害而不是把长势异常都当缺水或全田病害；等待无雨风窗，地面确认后及时定向杀菌。

完整[独立场景](../fairy/scenarios/wofost/scenario_full_season_hb_coolwet_flowering_disease_risk_V2.py)声明全部初值、事件和正常工具步骤；旧文件SHA256 `9aae3b0a392c684026afa5504c5ae321ae8c740e69a8a8bf78690a08ce20d1f5` 保持。

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
  "warehouse_pesticide_l": 50.0,
  "warehouse_fuel_l": 1000.0,
  "tractor_fuel_l": 100.0,
  "irrigation_quota_mm": 60.0,
  "active_ingredient_cap_kg": 0.05,
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
    "event_id": "flowering_cool_wet_rain",
    "farm_id": "farm",
    "start": "2019-07-01",
    "end": "2019-07-05",
    "rain_mm": 8.0
  },
  {
    "type": "pressure",
    "event_id": "localized_flowering_disease",
    "farm_id": "farm",
    "start": "2019-07-01",
    "end": "2019-07-02",
    "ridge_start": 22,
    "ridge_end": 32,
    "kind": "disease",
    "value": 0.65,
    "mode": "set",
    "repeat": "once"
  },
  {
    "type": "weather",
    "event_id": "after_cool_wet_spray_window",
    "farm_id": "farm",
    "start": "2019-07-06",
    "end": "2019-07-08",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  }
]
```

- 官方Lille固定气象7月1–4日日均温17.9、17.4、16.8、16.9°C，保持原温度不改；只明确增加每日8mm雨，位于实际R1开花阶段。
- 7月4日雨中不飞不喷；7月6日传感器→全田无人机→20–35垄地面覆盖，7月7日确认后只处理22–32。

- 2019-05-23：等待出苗
- 2019-06-28：花期阶段与根水基线
- 2019-07-04：凉湿雨中巡查不飞不喷
- 2019-07-06：凉湿后局部异常诊断
- 2019-07-07：确认后仅局部病区杀菌窗口
- 2019-07-11：处理后复查
- 2019-07-20：关键期根水检查
- 2019-08-08：关键期根水检查
- 2019-09-20：成熟与收获窗口

所有作业通过正常工具耗时推进；机器人每次≤8垄且看真实覆盖，内部4垄一批，充电1h；全田无人机560秒。分趟不冒充多轮农事，dry_grain仍即时抽象；所有机趟及收储批次可在原始轨迹核对。

## 同输入三组对照

|组别|13%商品粮kg|原生平均kgDM/ha|毛水mm|化学活性kg|机械除草垄次|耗油L|调用数|
|---|---:|---:|---:|---:|---:|---:|---:|
|correct|8794.83|4207.95|60|0.0418|0|84.00|122|
|none|8480.92|4064.39|60|0|0|80.00|113|
|wrong|8480.92|4064.39|60|0.0418|0|84.00|122|

管理定义：correct处理22–32病区；none不杀菌；wrong在同一天把相同41.8L用在44–54健康区，其余管理相同。

正确方案比none的商品粮变化3.701%，比wrong变化3.701%。不把wrong可能存在的部分收益说成完全无效。原生TWSO是干物质，商品粮还需含水率及田间/机器回收损失，单位分开；有机等资源/窗口题按其实际证据解释，不能强称所有差异均为产量。

正确方案共7轮田间农事、122次工具调用（同类同日作业归并；有明示连续作业组时跨午夜仍为一轮，日期和每趟调用另列；失败尝试不计已完成农事轮次）。生产CLI构建、执行、回放、评价全部通过，参数/依赖/起止时间一致；正确对照与生产操作及时间亦一致。

```bash
PYTHONHASHSEED=0 .venv/bin/python -m fairy.cli -s scenario_full_season_hb_coolwet_flowering_disease_risk_V2 \
 --build-oracle --run-oracle-tools --replay --evaluate --output-dir /tmp/wofost-selected20-05
```

完整结果及控制定义保留在[证据目录](../validation_runs/wofost_selected20_20261027/05_calibration)（现有.gitignore忽略的本地验证材料）。[独立产物及三组核验](../validation_runs/wofost_selected20_20261027/05_calibration/static_artifact_audit.json)包含原生干物质、资源、作业范围及时间。
