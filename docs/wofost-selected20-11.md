# 11｜先病后虫，共用施药预算

已完成工程校准；不是田间验证或LLM Agent成绩。原考点：中期杀菌与后期杀虫共用库存及活性额度。后期遇真实湿土、无雨小风时需改用人工背负点喷，保留原题湿土人工路径；不可通过时间开关免除人工耗时。

完整[独立场景](../fairy/scenarios/wofost/scenario_full_season_hb_insect_after_fungicide_budget_conflict_V2.py)声明全部初值、事件和正常工具步骤；旧文件SHA256 `f0bb9211cb2f554d751caa9e209e2230d216ab0cb82cb7e9159d76e56a742407` 保持。

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
  "soil_depth_m": 0.4,
  "wilting_point_vwc": 0.1,
  "field_capacity_vwc": 0.38,
  "saturation_vwc": 0.5,
  "infiltration_mm_day": 10.0,
  "initial_available_n_kg_ha": 50.0,
  "base_soil_n_kg_ha": 50.0,
  "base_fertilizer_kg": 0.0,
  "seed_stock": 1000000,
  "warehouse_fertilizer_kg": 0.0,
  "warehouse_pesticide_l": 110.0,
  "warehouse_fuel_l": 1000.0,
  "tractor_fuel_l": 100.0,
  "irrigation_quota_mm": 60.0,
  "active_ingredient_cap_kg": 0.11,
  "max_machine_passes": null,
  "management_regime": "conventional",
  "max_insecticide_applications": 1,
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
    "event_id": "flowering_wet_spell",
    "farm_id": "farm",
    "start": "2019-07-01",
    "end": "2019-07-05",
    "rain_mm": 6.0
  },
  {
    "type": "pressure",
    "event_id": "midseason_disease",
    "farm_id": "farm",
    "start": "2019-07-01",
    "end": "2019-07-02",
    "ridge_start": 20,
    "ridge_end": 35,
    "kind": "disease",
    "value": 0.6,
    "mode": "set",
    "repeat": "once"
  },
  {
    "type": "weather",
    "event_id": "fungicide_window",
    "farm_id": "farm",
    "start": "2019-07-06",
    "end": "2019-07-09",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  },
  {
    "type": "weather",
    "event_id": "late_wet_soil_spell",
    "farm_id": "farm",
    "start": "2019-08-02",
    "end": "2019-08-07",
    "rain_mm": 30.0
  },
  {
    "type": "pressure",
    "event_id": "later_insect",
    "farm_id": "farm",
    "start": "2019-08-05",
    "end": "2019-08-06",
    "ridge_start": 40,
    "ridge_end": 55,
    "kind": "insect",
    "value": 0.65,
    "mode": "set",
    "repeat": "once"
  },
  {
    "type": "weather",
    "event_id": "manual_spray_window",
    "farm_id": "farm",
    "start": "2019-08-07",
    "end": "2019-08-10",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  }
]
```

- 前期16垄×3.8L=60.8L；后期16垄×背负3L=48L，总108.8/110L、0.1088/0.11kg，余1.2L不追用。
- 后期5天人工雨共150mm及浅黏土参数共同通过真实原生水量平衡形成湿土；停雨后核对土水，正常人工背负8趟、每趟2垄且advance_time=True。
- 原题共享预算和湿土人工路线都保留，不把机喷8L/垄与背负3L/垄不同参考当真实浓度或零耗时优势；8月根区充足不额外灌水。

- 2019-05-23：等待出苗
- 2019-07-06：中期病害诊断
- 2019-07-07：只病区60点8升杀菌窗口
- 2019-07-20：关键期根水检查
- 2019-08-07：后期停雨但湿土虫情
- 2019-08-08：雨后根区充足不再例行灌水
- 2019-08-13：后期药后复核
- 2019-09-20：成熟与收获窗口

所有作业通过正常工具耗时推进；机器人每次≤8垄且看真实覆盖，内部4垄一批，充电1h；全田无人机560秒。分趟不冒充多轮农事，dry_grain仍即时抽象；所有机趟及收储批次可在原始轨迹核对。

## 同输入三组对照

|组别|13%商品粮kg|原生平均kgDM/ha|毛水mm|化学活性kg|机械除草垄次|耗油L|调用数|
|---|---:|---:|---:|---:|---:|---:|---:|
|correct|7893.08|3795.78|30|0.1088|0|84.00|141|
|none|7240.60|3506.72|30|0|0|80.00|124|
|wrong|7445.56|3601.52|30|0.1088|0|94.00|138|

管理定义：correct前期定向60.8L杀菌、后期湿土48L人工杀虫；none两类均不施药；wrong早期108.8L杀菌液均摊全田，余1.2L不足后期48L。正确/错误总药量相同，区别在全季时机、类别和分配；不追额度舍入边界。

正确方案比none的商品粮变化9.011%，比wrong变化6.011%。不把wrong可能存在的部分收益说成完全无效。原生TWSO是干物质，商品粮还需含水率及田间/机器回收损失，单位分开；有机等资源/窗口题按其实际证据解释，不能强称所有差异均为产量。

正确方案共7轮田间农事、141次工具调用（同类同日作业归并；有明示连续作业组时跨午夜仍为一轮，日期和每趟调用另列；失败尝试不计已完成农事轮次）。生产CLI构建、执行、回放、评价全部通过，参数/依赖/起止时间一致；正确对照与生产操作及时间亦一致。

```bash
PYTHONHASHSEED=0 .venv/bin/python -m fairy.cli -s scenario_full_season_hb_insect_after_fungicide_budget_conflict_V2 \
 --build-oracle --run-oracle-tools --replay --evaluate --output-dir /tmp/wofost-selected20-11
```

完整结果及控制定义保留在[证据目录](../validation_runs/wofost_selected20_20261027/11_calibration)（现有.gitignore忽略的本地验证材料）。[独立产物及三组核验](../validation_runs/wofost_selected20_20261027/11_calibration/static_artifact_audit.json)包含原生干物质、资源、作业范围及时间。
