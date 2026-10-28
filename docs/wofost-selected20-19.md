# 19｜杂草与病害造成的长势异常

已完成工程校准；不是田间验证或LLM Agent成绩。原考点：无人机的绿色覆盖和长势异常不能直接当病因；早期草害与后期病害分阶段地面确认，再分别机械除草和杀菌。两类操作不可互相替代。

完整[独立场景](../fairy/scenarios/wofost/scenario_full_season_hb_wetjune_weed_disease_diagnosis_V2.py)声明全部初值、事件和正常工具步骤；旧文件SHA256 `c1a139fb6bb4899de89a7d873f3f89e69527c161eeca933e88d23e4c2a4da907` 保持。

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
  "warehouse_pesticide_l": 61.0,
  "warehouse_fuel_l": 1000.0,
  "tractor_fuel_l": 100.0,
  "irrigation_quota_mm": 30.0,
  "active_ingredient_cap_kg": 0.061,
  "max_machine_passes": 2,
  "management_regime": "conventional",
  "max_insecticide_applications": null,
  "max_fungicide_applications": 1,
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
    "event_id": "early_green_weed_patch",
    "farm_id": "farm",
    "start": "2019-05-24",
    "end": "2019-05-25",
    "ridge_start": 6,
    "ridge_end": 21,
    "kind": "weed",
    "value": 0.8,
    "mode": "set",
    "repeat": "once"
  },
  {
    "type": "weather",
    "event_id": "seedling_diagnosis_and_work",
    "farm_id": "farm",
    "start": "2019-05-28",
    "end": "2019-05-30",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  },
  {
    "type": "weather",
    "event_id": "wet_canopy_spell",
    "farm_id": "farm",
    "start": "2019-06-18",
    "end": "2019-07-03",
    "rain_mm": 6.0
  },
  {
    "type": "pressure",
    "event_id": "later_canopy_disease_patch",
    "farm_id": "farm",
    "start": "2019-06-25",
    "end": "2019-06-26",
    "ridge_start": 34,
    "ridge_end": 49,
    "kind": "disease",
    "value": 0.65,
    "mode": "set",
    "repeat": "once"
  },
  {
    "type": "weather",
    "event_id": "disease_diagnosis_and_work",
    "farm_id": "farm",
    "start": "2019-07-04",
    "end": "2019-07-06",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  }
]
```

- 4/28统一建植，5/23仅0–3垄出苗样本，不称全田检查。苗期5/24一次外接草害，后期6/25另一区一次外接病害；两事件均世界自身注入。
- 5/28传感器—全田无人机定位异常—机器人覆盖4–23垄两端与54–57参照，确认6–21草区；5/29机械除草16垄，两趟同一轮。6/3复查。
- 6/18–7/3人工6mm/day湿期。7/4按同样层次定位新异常，再24垄地面覆盖32–55边界，确认34–49病区；7/5定向60.8L杀菌，一个施药日。7/10复查。
- 两种诊断不可交换：草区杀菌无除草作用，病区机械除草无杀菌作用；错误管理两类资源总量与正确相同。
- 8/8检查根水后30mm常规补水；9/20确认R8/粮水/天气，容量分趟收获、13%干燥和安全入库。

- 2019-05-23：等待出苗
- 2019-05-28：苗期绿色覆盖异常定位
- 2019-05-29：确认草区机械除草窗口
- 2019-06-03：苗期处理后复查
- 2019-07-04：湿季新异常定位鉴别
- 2019-07-05：确认病区局部杀菌窗口
- 2019-07-10：湿季处理后复查
- 2019-08-08：关键期根水检查
- 2019-09-20：成熟与收获窗口

所有作业通过正常工具耗时推进；机器人每次≤8垄且看真实覆盖，内部4垄一批，充电1h；全田无人机560秒。分趟不冒充多轮农事，dry_grain仍即时抽象；所有机趟及收储批次可在原始轨迹核对。

## 同输入三组对照

|组别|13%商品粮kg|原生平均kgDM/ha|毛水mm|化学活性kg|机械除草垄次|耗油L|调用数|
|---|---:|---:|---:|---:|---:|---:|---:|
|correct|8302.48|3980.54|30|0.0608|16|88.00|149|
|none|7174.21|3449.82|30|0|0|80.00|132|
|wrong|7174.21|3449.82|30|0.0608|16|88.00|149|

管理定义：correct苗期机械草区、湿季杀菌病区；none省略这两类关键干预；wrong把两种处理对象交换：5/29草区杀菌60.8L，7/5病区机械16垄。正确与错误的化学量、机械垄次/机趟和其他输入相同，不虚构错误药剂额外药害。

正确方案比none的商品粮变化15.727%，比wrong变化15.727%。不把wrong可能存在的部分收益说成完全无效。原生TWSO是干物质，商品粮还需含水率及田间/机器回收损失，单位分开；有机等资源/窗口题按其实际证据解释，不能强称所有差异均为产量。

正确方案共7轮田间农事、149次工具调用（同类同日作业归并；有明示连续作业组时跨午夜仍为一轮，日期和每趟调用另列；失败尝试不计已完成农事轮次）。生产CLI构建、执行、回放、评价全部通过，参数/依赖/起止时间一致；正确对照与生产操作及时间亦一致。

```bash
PYTHONHASHSEED=0 .venv/bin/python -m fairy.cli -s scenario_full_season_hb_wetjune_weed_disease_diagnosis_V2 \
 --build-oracle --run-oracle-tools --replay --evaluate --output-dir /tmp/wofost-selected20-19
```

完整结果及控制定义保留在[证据目录](../validation_runs/wofost_selected20_20261027/19_calibration)（现有.gitignore忽略的本地验证材料）。[独立产物及三组核验](../validation_runs/wofost_selected20_20261027/19_calibration/static_artifact_audit.json)包含原生干物质、资源、作业范围及时间。
