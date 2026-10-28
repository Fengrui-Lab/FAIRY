# 17｜错期播种遇到同一场干旱

已完成工程校准；不是田间验证或LLM Agent成绩。原考点：同一大豆品种的早晚播区遇到同一场干旱。全季水量仅够半田一次正常30mm灌溉；依据各区阶段、根水和实际保产对照选择优先区，不能默认某阶段一定收益最高。

完整[独立场景](../fairy/scenarios/wofost/scenario_full_season_hb_staggered_dryr5r6_stage_mismatch_V2.py)声明全部初值、事件和正常工具步骤；旧文件SHA256 `cf6206396997ca0ba55be371d094c02dd69a6fca21c4011131129e2919cdfcdf` 保持。

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
  "initial_vwc": 0.3,
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
  "irrigation_quota_mm": 15.5,
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
    "event_id": "late_sowing_window",
    "farm_id": "farm",
    "start": "2019-05-28",
    "end": "2019-05-29",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  },
  {
    "type": "weather",
    "event_id": "cohort_comparison",
    "farm_id": "farm",
    "start": "2019-07-01",
    "end": "2019-07-02",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  },
  {
    "type": "drought",
    "event_id": "shared_reproductive_drought",
    "farm_id": "farm",
    "start": "2019-07-15",
    "end": "2019-08-20",
    "rain_multiplier": 0.0
  },
  {
    "type": "weather",
    "event_id": "limited_water_diagnosis",
    "farm_id": "farm",
    "start": "2019-08-04",
    "end": "2019-08-06",
    "wind_ms": 2.0
  },
  {
    "type": "weather",
    "event_id": "harvest_clear_spell",
    "farm_id": "farm",
    "start": "2019-09-20",
    "end": "2019-10-09",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  }
]
```

- 先按公开播期建植两块等面积区域，分别检查出苗；不强改土温。
- 7/1建立阶段/冠层基线，8/4传感器—全田无人机—两区各4垄地面检查，再决定有限水量。
- 干旱7/15–8/20仅减雨，不直接扣产量；一次半田30mm扣全田15mm，没有日常小水搜索。
- 校准确认8/4早区R5、晚区R3（DVS阶段近似）。8/5把一次30mm给晚区，8/9复查；等水量早区对照同样有收益，但全田商品粮比晚区方案少122.08kg。
- 早区/晚区30mm与不浇三组完整跑到分区成熟收储；按实际商品粮、原生干物质及等水量比较确定oracle。
- 分区9/20与10/7收获；人工无雨窗9/20–10/9，只改雨风，不改温湿辐射。

- 2019-05-23：早区出苗样本
- 2019-05-28：迟区独立播床检查
- 2019-06-15：迟区出苗样本
- 2019-07-01：错期冠层基线
- 2019-08-04：同一干旱下的阶段和根水
- 2019-08-05：关键期根水检查
- 2019-08-09：一次正常灌水后复查
- 2019-09-20：成熟与收获窗口
- 2019-10-07：成熟与收获窗口

所有作业通过正常工具耗时推进；机器人每次≤8垄且看真实覆盖，内部4垄一批，充电1h；全田无人机560秒。分趟不冒充多轮农事，dry_grain仍即时抽象；所有机趟及收储批次可在原始轨迹核对。

## 同输入三组对照

|组别|13%商品粮kg|原生平均kgDM/ha|毛水mm|化学活性kg|机械除草垄次|耗油L|调用数|
|---|---:|---:|---:|---:|---:|---:|---:|
|correct|6252.80|2996.38|15|0|0|80.00|127|
|none|5469.20|2619.38|0|0|0|80.00|122|
|wrong|6130.72|2934.79|15|0|0|80.00|127|

管理定义：correct：8/5晚播32–63垄30mm；wrong：同日早播0–31垄30mm；none不灌水。两管理组均全田等效15mm、半田实际30mm。8/4公开阶段早R5/晚R3，早区根水更低，但本固定情境晚区保留更长同化期，实际水量边际收益更高；不把“最缺水”或R5名称直接当最优判据。两种灌水均比不灌水有收益，不能称早区浇水无效。对照后仅重命名等水量处理的correct/wrong标签，没有改变任何一次轨迹、世界或物理参数。

正确方案比none的商品粮变化14.328%，比wrong变化1.991%。不把wrong可能存在的部分收益说成完全无效。原生TWSO是干物质，商品粮还需含水率及田间/机器回收损失，单位分开；有机等资源/窗口题按其实际证据解释，不能强称所有差异均为产量。

正确方案共7轮田间农事、127次工具调用（同类同日作业归并；有明示连续作业组时跨午夜仍为一轮，日期和每趟调用另列；失败尝试不计已完成农事轮次）。生产CLI构建、执行、回放、评价全部通过，参数/依赖/起止时间一致；正确对照与生产操作及时间亦一致。

```bash
PYTHONHASHSEED=0 .venv/bin/python -m fairy.cli -s scenario_full_season_hb_staggered_dryr5r6_stage_mismatch_V2 \
 --build-oracle --run-oracle-tools --replay --evaluate --output-dir /tmp/wofost-selected20-17
```

完整结果及控制定义保留在[证据目录](../validation_runs/wofost_selected20_20261027/17_calibration)（现有.gitignore忽略的本地验证材料）。[独立产物及三组核验](../validation_runs/wofost_selected20_20261027/17_calibration/static_artifact_audit.json)包含原生干物质、资源、作业范围及时间。
