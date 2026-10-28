# 08｜旱后恢复慢，避免误诊病害

已完成工程校准；不是田间验证或LLM Agent成绩。原考点：冠层扩展期的缺水已造成累计生物量差距；补水后根水上升不意味着冠层马上追平。根据根水、旱情历史和地面病害证据辨因，不能因长势仍弱盲喷杀菌剂；不虚构额外药害或恢复迟滞机制。

完整[独立场景](../fairy/scenarios/wofost/scenario_full_season_hb_drought_recovery_false_disease_signal_V2.py)声明全部初值、事件和正常工具步骤；旧文件SHA256 `6d3a0eacf36d1dfa23383e8506d56f7039c8396fa6bfdf49225bfdcc1c43e9bd` 保持。

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
  "irrigation_quota_mm": 71.0,
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
    "type": "drought",
    "event_id": "canopy_expansion_drought",
    "farm_id": "farm",
    "start": "2019-06-01",
    "end": "2019-07-06",
    "rain_multiplier": 0.0
  },
  {
    "type": "weather",
    "event_id": "diagnosis_and_false_spray_window",
    "farm_id": "farm",
    "start": "2019-06-27",
    "end": "2019-07-05",
    "wind_ms": 2.0
  }
]
```

- 避免R5闭合冠层NDVI饱和掩盖差异，把缺水与复查安排在冠层扩展期。土壤限制来自真实原生水量平衡，不新增恢复迟滞机制。
- 6月27日先诊断，6月29日18–39一次30mm，7月1日核对根水升高及冠层仍弱、病害证据不足；不施无效杀菌剂。
- 两次正常全田30mm加一次局部30mm，共70.3125/71mm，不追余量。

- 2019-05-23：等待出苗
- 2019-06-27：冠层扩展期缺水异常
- 2019-06-29：关键期根水检查
- 2019-07-01：补水后先看水与冠层而非认病
- 2019-07-10：开花期继续跟踪
- 2019-07-20：关键期根水检查
- 2019-08-08：关键期根水检查
- 2019-09-20：成熟与收获窗口

所有作业通过正常工具耗时推进；机器人每次≤8垄且看真实覆盖，内部4垄一批，充电1h；全田无人机560秒。分趟不冒充多轮农事，dry_grain仍即时抽象；所有机趟及收储批次可在原始轨迹核对。

## 同输入三组对照

|组别|13%商品粮kg|原生平均kgDM/ha|毛水mm|化学活性kg|机械除草垄次|耗油L|调用数|
|---|---:|---:|---:|---:|---:|---:|---:|
|correct|7005.30|3340.21|70.31|0|0|80.00|122|
|none|6587.08|3140.81|60|0|0|80.00|117|
|wrong|7005.30|3340.21|70.31|0.0836|0|86.00|132|

管理定义：correct两次正常全田水加6月29日局部30mm，无杀菌；none仅省略局部补水；wrong同样补水却7月3日误施83.6L杀菌剂，产量应与correct相同但资源消耗增加。

正确方案比none的商品粮变化6.349%，比wrong变化0.000%。不把wrong可能存在的部分收益说成完全无效。原生TWSO是干物质，商品粮还需含水率及田间/机器回收损失，单位分开；有机等资源/窗口题按其实际证据解释，不能强称所有差异均为产量。

正确方案共7轮田间农事、122次工具调用（同类同日作业归并；有明示连续作业组时跨午夜仍为一轮，日期和每趟调用另列；失败尝试不计已完成农事轮次）。生产CLI构建、执行、回放、评价全部通过，参数/依赖/起止时间一致；正确对照与生产操作及时间亦一致。

```bash
PYTHONHASHSEED=0 .venv/bin/python -m fairy.cli -s scenario_full_season_hb_drought_recovery_false_disease_signal_V2 \
 --build-oracle --run-oracle-tools --replay --evaluate --output-dir /tmp/wofost-selected20-08
```

完整结果及控制定义保留在[证据目录](../validation_runs/wofost_selected20_20261027/08_calibration)（现有.gitignore忽略的本地验证材料）。[独立产物及三组核验](../validation_runs/wofost_selected20_20261027/08_calibration/static_artifact_audit.json)包含原生干物质、资源、作业范围及时间。
