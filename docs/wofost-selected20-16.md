# 16｜同品种错期播种与分区收获

已完成工程校准；不是田间验证或LLM Agent成绩。原考点：同一官方地区大豆分三播期建植，按各区真实出苗、生育、成熟、粮水和天气分别收获，不把早区成熟当全田成熟。

完整[独立场景](../fairy/scenarios/wofost/scenario_full_season_heinong84_staggered_planting_V2.py)声明全部初值、事件和正常工具步骤；旧文件SHA256 `1c8281b574f400ea6055876c8fb1eeb776b74379b900a3599fbea4405c11888f` 保持。

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
    "event_id": "middle_sowing_window",
    "farm_id": "farm",
    "start": "2019-05-11",
    "end": "2019-05-12",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  },
  {
    "type": "weather",
    "event_id": "late_sowing_window",
    "farm_id": "farm",
    "start": "2019-05-28",
    "end": "2019-05-29",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  },
  {
    "type": "weather",
    "event_id": "harvest_clear_spells",
    "farm_id": "farm",
    "start": "2019-09-20",
    "end": "2019-10-09",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  },
  {
    "type": "weather",
    "event_id": "cohort_comparison_flight",
    "farm_id": "farm",
    "start": "2019-06-28",
    "end": "2019-06-29",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  }
]
```

- 三区同一官方Soybean_901，按4/28、5/11、5/28实际播种；已有播期窗口约束。5/8土温不足的试验已否决，不能靠覆写土温强播。
- 出苗仅各4垄样本；6/28传感器—全田无人机—三区各4垄地面确认，解释冠层差异先考虑播期。
- 7/20、8/8各30mm常规关键期补水；无例行化学投入。9/17开始分别查阶段/粮水。
- 9/20收早区、9/22收中区、10/7收迟区；这是公开逐日校准后固定的合法窗口，收前仍实际查各区。
- 9/20–10/9人工无雨、风2m/s，温湿度辐射保留NASA原值；迟区即使9/26已R8，仍须等粮水≤18%。
- 对照统一等迟区再收，量化早中区在田损失；错误收未熟迟区应被工具拒绝，随后完成合法补救收储。

- 2019-05-11：中播区独立播床检查
- 2019-05-23：早播区出苗样本
- 2019-05-28：迟播区独立播床检查
- 2019-06-15：两后播区分别出苗样本
- 2019-06-28：三区阶段差异
- 2019-07-20：关键期根水检查
- 2019-08-08：关键期根水检查
- 2019-09-17：临近成熟各区分别检查
- 2019-09-20：成熟与收获窗口
- 2019-09-22：成熟与收获窗口
- 2019-10-07：成熟与收获窗口

所有作业通过正常工具耗时推进；机器人每次≤8垄且看真实覆盖，内部4垄一批，充电1h；全田无人机560秒。分趟不冒充多轮农事，dry_grain仍即时抽象；所有机趟及收储批次可在原始轨迹核对。

## 同输入三组对照

|组别|13%商品粮kg|原生平均kgDM/ha|毛水mm|化学活性kg|机械除草垄次|耗油L|调用数|
|---|---:|---:|---:|---:|---:|---:|---:|
|correct|8898.56|4250.61|60|0|0|88.00|136|
|none|8505.36|4250.61|60|0|0|84.00|119|
|wrong|8505.36|4250.61|60|0|0|84.00|123|

管理定义：none不做分区收获，10/7全田统一收；wrong在9/20把早区成熟误当全田成熟，尝试43–46垄被原工具拒绝，再与none一样10/7合法收全部。correct分区及时收。所有组播期、输入、天气和最终完整收储相同；wrong的失败验收为预期拒绝记录，不冒称成功。

正确方案比none的商品粮变化4.623%，比wrong变化4.623%。不把wrong可能存在的部分收益说成完全无效。原生TWSO是干物质，商品粮还需含水率及田间/机器回收损失，单位分开；有机等资源/窗口题按其实际证据解释，不能强称所有差异均为产量。

正确方案共10轮田间农事、136次工具调用（同类同日作业归并；有明示连续作业组时跨午夜仍为一轮，日期和每趟调用另列；失败尝试不计已完成农事轮次）。生产CLI构建、执行、回放、评价全部通过，参数/依赖/起止时间一致；正确对照与生产操作及时间亦一致。

```bash
PYTHONHASHSEED=0 .venv/bin/python -m fairy.cli -s scenario_full_season_heinong84_staggered_planting_V2 \
 --build-oracle --run-oracle-tools --replay --evaluate --output-dir /tmp/wofost-selected20-16
```

完整结果及控制定义保留在[证据目录](../validation_runs/wofost_selected20_20261027/16_calibration)（现有.gitignore忽略的本地验证材料）。[独立产物及三组核验](../validation_runs/wofost_selected20_20261027/16_calibration/static_artifact_audit.json)包含原生干物质、资源、作业范围及时间。
