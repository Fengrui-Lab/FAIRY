# 15｜晚雨后的局部虫害

已完成工程校准；不是田间验证或LLM Agent成绩。原考点：晚雨后仍在生殖形成产量的阶段识别局部虫害，选择无雨小风且可通行的施药窗口。不能把成熟后用药当保产，也不能雨中强喷；合法性指本模拟工具雨风/土壤/资源约束，不虚称真实药品标签或安全间隔已建模。

完整[独立场景](../fairy/scenarios/wofost/scenario_full_season_hb_laterain_insect_risk_V2.py)声明全部初值、事件和正常工具步骤；旧文件SHA256 `23fadb2e3193ced34b219eda3e637df3072f1cfe5e5e0c530ec6b5dbf5c9b72e` 保持。

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
    "event_id": "late_reproductive_rain",
    "farm_id": "farm",
    "start": "2019-08-09",
    "end": "2019-08-12",
    "rain_mm": 12.0
  },
  {
    "type": "pressure",
    "event_id": "late_local_insects",
    "farm_id": "farm",
    "start": "2019-08-09",
    "end": "2019-08-10",
    "ridge_start": 36,
    "ridge_end": 55,
    "kind": "insect",
    "value": 0.65,
    "mode": "set",
    "repeat": "once"
  },
  {
    "type": "weather",
    "event_id": "post_rain_spray_window",
    "farm_id": "farm",
    "start": "2019-08-12",
    "end": "2019-08-15",
    "rain_mm": 0.0,
    "wind_ms": 2.0
  }
]
```

- 8月9–11人工晚雨每日12mm，世界8月9日虫压一次施加于36–55，不在成熟后才造虫题。
- 8月8日预报强雨不例行灌水，8月10日雨中仅地面观察不飞；8月12日确认真实R5及虫区，8月13日正常160L一轮2趟杀虫。
- 当前工具未模拟真实药品PHI、产品标签或小时露水，明确只按现有天气/通行/资源规则判合法，不宣称田间实测。

- 2019-05-23：等待出苗
- 2019-06-28：花期根水
- 2019-07-20：关键期根水检查
- 2019-08-08：R5将来强雨不例行补水
- 2019-08-10：晚雨中地面虫情样本不飞
- 2019-08-12：雨后仍有保产价值的虫害确认
- 2019-08-13：R5合法窗口只处理虫区窗口
- 2019-08-18：药后虫情复查
- 2019-09-20：成熟与收获窗口

所有作业通过正常工具耗时推进；机器人每次≤8垄且看真实覆盖，内部4垄一批，充电1h；全田无人机560秒。分趟不冒充多轮农事，dry_grain仍即时抽象；所有机趟及收储批次可在原始轨迹核对。

## 同输入三组对照

|组别|13%商品粮kg|原生平均kgDM/ha|毛水mm|化学活性kg|机械除草垄次|耗油L|调用数|
|---|---:|---:|---:|---:|---:|---:|---:|
|correct|8919.28|4264.75|30|0.16|0|84.00|126|
|none|8664.58|4162.70|30|0|0|80.00|117|
|wrong|8664.58|4162.70|30|0|0|80.00|126|

管理定义：correct等待雨后且仍R5时处理；none不杀虫；wrong雨中尝试两趟均被真实工具拒绝，未有效施药，完成性validate保留预期错误；三组其余管理及收储相同。

正确方案比none的商品粮变化2.940%，比wrong变化2.940%。不把wrong可能存在的部分收益说成完全无效。原生TWSO是干物质，商品粮还需含水率及田间/机器回收损失，单位分开；有机等资源/窗口题按其实际证据解释，不能强称所有差异均为产量。

正确方案共6轮田间农事、126次工具调用（同类同日作业归并；有明示连续作业组时跨午夜仍为一轮，日期和每趟调用另列；失败尝试不计已完成农事轮次）。生产CLI构建、执行、回放、评价全部通过，参数/依赖/起止时间一致；正确对照与生产操作及时间亦一致。

```bash
PYTHONHASHSEED=0 .venv/bin/python -m fairy.cli -s scenario_full_season_hb_laterain_insect_risk_V2 \
 --build-oracle --run-oracle-tools --replay --evaluate --output-dir /tmp/wofost-selected20-15
```

完整结果及控制定义保留在[证据目录](../validation_runs/wofost_selected20_20261027/15_calibration)（现有.gitignore忽略的本地验证材料）。[独立产物及三组核验](../validation_runs/wofost_selected20_20261027/15_calibration/static_artifact_audit.json)包含原生干物质、资源、作业范围及时间。
