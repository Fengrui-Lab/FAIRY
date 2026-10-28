# 07｜食叶虫与病斑鉴别

已完成工程校准；不是田间验证或LLM Agent成绩。原考点：叶片或冠层异常不能直接判为病害；地面区分虫害与病害后选择对应药剂。当前模型用外接虫压影响同化，不直接移除叶面积或生成叶孔，具体虫种标签只是工具简化诊断，不能冒称真实食叶虫图像识别。

完整[独立场景](../fairy/scenarios/wofost/scenario_full_season_hb_leaffeeder_vs_disease_spots_diagnosis_V2.py)声明全部初值、事件和正常工具步骤；旧文件SHA256 `3f3edf4358c5a21e2309ca432b62d12503c74886f0ab7ea64ed6bdd4b3b9cc36` 保持。

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
    "type": "pressure",
    "event_id": "leaf_feeding_category_insect",
    "farm_id": "farm",
    "start": "2019-07-15",
    "end": "2019-07-16",
    "ridge_start": 33,
    "ridge_end": 43,
    "kind": "insect",
    "value": 0.65,
    "mode": "set",
    "repeat": "once"
  },
  {
    "type": "pressure",
    "event_id": "minor_spot_reference",
    "farm_id": "farm",
    "start": "2019-07-15",
    "end": "2019-07-16",
    "ridge_start": 44,
    "ridge_end": 55,
    "kind": "disease",
    "value": 0.08,
    "mode": "set",
    "repeat": "once"
  },
  {
    "type": "weather",
    "event_id": "diagnosis_and_treatment_window",
    "farm_id": "farm",
    "start": "2019-07-20",
    "end": "2019-07-23",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  }
]
```

- 7月20日根水及冠层→全田无人机→健康/虫区/轻病参考的32垄分段地面检查；不凭NDVI猜病。
- 7月21日确认后只给33–43垄正常8L/垄杀虫剂，非真叶孔或虫种复现；错误组同区使用正常3.8L/垄杀菌剂，不能压低虫害。
- 实际根区亏水和虫害同时存在，分开正常补水与对症施药，不用杀菌剂替代补水或杀虫。

- 2019-05-23：等待出苗
- 2019-06-28：花期根水基线
- 2019-07-20：冠层异常先辨因
- 2019-07-20：关键期根水检查
- 2019-07-21：地面确认虫害后用杀虫剂窗口
- 2019-07-26：对症用药后复查
- 2019-08-08：关键期根水检查
- 2019-09-20：成熟与收获窗口

所有作业通过正常工具耗时推进；机器人每次≤8垄且看真实覆盖，内部4垄一批，充电1h；全田无人机560秒。分趟不冒充多轮农事，dry_grain仍即时抽象；所有机趟及收储批次可在原始轨迹核对。

## 同输入三组对照

|组别|13%商品粮kg|原生平均kgDM/ha|毛水mm|化学活性kg|机械除草垄次|耗油L|调用数|
|---|---:|---:|---:|---:|---:|---:|---:|
|correct|8854.91|4234.13|60|0.088|0|84.00|121|
|none|8592.40|4118.45|60|0|0|80.00|112|
|wrong|8592.40|4118.45|60|0.0418|0|84.00|121|

管理定义：correct在33–43虫区用88L杀虫工作液；none不施药；wrong给同区41.8L正常参考杀菌工作液。两种类别各按其既有参考剂量，不虚称同体积或同现实有效成分；其余管理相同。

正确方案比none的商品粮变化3.055%，比wrong变化3.055%。不把wrong可能存在的部分收益说成完全无效。原生TWSO是干物质，商品粮还需含水率及田间/机器回收损失，单位分开；有机等资源/窗口题按其实际证据解释，不能强称所有差异均为产量。

正确方案共7轮田间农事、121次工具调用（同类同日作业归并；有明示连续作业组时跨午夜仍为一轮，日期和每趟调用另列；失败尝试不计已完成农事轮次）。生产CLI构建、执行、回放、评价全部通过，参数/依赖/起止时间一致；正确对照与生产操作及时间亦一致。

```bash
PYTHONHASHSEED=0 .venv/bin/python -m fairy.cli -s scenario_full_season_hb_leaffeeder_vs_disease_spots_diagnosis_V2 \
 --build-oracle --run-oracle-tools --replay --evaluate --output-dir /tmp/wofost-selected20-07
```

完整结果及控制定义保留在[证据目录](../validation_runs/wofost_selected20_20261027/07_calibration)（现有.gitignore忽略的本地验证材料）。[独立产物及三组核验](../validation_runs/wofost_selected20_20261027/07_calibration/static_artifact_audit.json)包含原生干物质、资源、作业范围及时间。
