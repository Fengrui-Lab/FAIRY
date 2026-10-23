# 水稻场景与工具：WOFOST 8.1

水稻实现覆盖观测与设备作业、水肥与收后资源、病虫草害及水利维护，包含 **35 个水稻专用工具、28 个 L1/L2/L3 场景**。标准 FARM 控制器另暴露 6 个通用工具，共 41 个。大豆与水稻共用 PCSE 6.0.x / WOFOST 8.1 环境；本轮验证和包内固定产物使用 PCSE 6.0.13。

从已购入的成品秧苗开始，不实现育秧或购买交易。田埂、渠道已经建成，可以带有需维修的故障。土壤、天气、IR72 参数补全以及辅助模型均属于**未田间标定的工程基线**。

## 场景入口与阅读顺序

水稻场景保留在 `fairy/scenarios/rice/`，采用与 `farm_world_fullseason_v2/` 相同的显式场景文件和事件图组织方式。此次调整解决了两个结构问题：原来的单文件动态注册不便于按场景追踪代码；运行时参考策略把参考季生成、检查点派生与场景初始化混在一起。现在参考产物由脚本显式离线生成，运行时读取固定产物并构建事件图。**28 个场景 ID、物理模型和严格验收语义保持不变；不保留新旧两套注册或 oracle 执行路径。**

建议按以下顺序阅读：

1. [场景目录](../fairy/scenarios/rice/rice_scenario_catalog.py)：`RiceScenarioSpec` 描述任务、来源完整季及起始状态，`get_spec()` 查询既有场景 ID。
2. 一个顶层 `scenario_full_season_rice_<variant>.py`：8 个 L3 文件各自显式定义、注册场景。20 个 L1/L2 文件位于 `l2_l1_splits/rice_<sourcevariant>/scenario_rice_l*_*.py`，按来源完整季分组。文件名调整不会改变 `scenario_rice_l3_<variant>` 等对外 ID。
3. [公共场景基类](../fairy/scenarios/rice/rice_scenario.py) 与 [事件/应用辅助函数](../fairy/scenarios/rice/rice_scenario_helpers.py)：通过 `init_rice_apps()` 初始化应用，通过 `build_rice_events()` 构建标准事件图；各场景使用 `build_events_flow()`、`EventRegisterer`、`.oracle()` 和 `.depends_on()`。
4. [检查点读取](../fairy/scenarios/rice/farm_checkpoint_state.py) 与 [产物清单](../fairy/scenarios/rice/scenario_artifacts.json)：固定工具计划位于 `oracle_plans/<scenario_id>.json`，来源季检查点位于 `l2_l1_splits/rice_<variant>/checkpoints/<label>.json`。`setup()` 从磁盘恢复所需状态；它和 `build_oracle_workflow(run_oracle=False)` 都不执行完整参考季，后者只记录工具和参数。
5. [任务验收](../fairy/scenarios/rice/validation.py) 与 [水稻结果指标](../fairy/scenarios/rice/evaluation.py)：前者检查目标、错误和资源账本，后者计算 `rice_outcome`，职责分开。
6. [参考策略](../scripts/rice_reference_policy.py) 与 [产物构建脚本](../scripts/build_rice_scenario_artifacts.py)：需要重建参考计划或来源季检查点时才执行；随后再进入 [水田应用](../fairy/apps/paddy/)、[原生后端](../fairy/physics/rice_backend.py) 和 [水氮平衡](../fairy/physics/paddy_waterbalance.py) 查动作及模型实现。

旧 `scenarios.py` 和 `reference.py` 已移除。场景运行时不通过 `type()` 动态生成类，也不覆盖 `oracle_solution()` 来运行参考策略。参考策略仍能根据公开观测执行工具，但只用于显式产物构建和参考季验证；普通场景运行使用生成后的固定计划。

这次统一的是场景组织与执行协议。大豆仍通过 `FarmWorldApp` 和按垄的物理编排运行，水稻仍由 `PaddyWorldApp` 按田格驱动独立的 `RiceWofostBackend`，没有合并两套作物物理模型。水稻 `detailed_briefing` 目前只支持 `false` / `true`；`kwoo`、`library` 及各技能检索模式尚未接入，传入时明确报错。沿用事件协议也不代表水稻已接入大豆的统一 FOS 评分或跨作物比较。

## 运行与产物

```bash
uv sync --extra wofost

# 显式重建 28 个固定计划、来源季检查点及 SHA-256/PCSE 指纹清单。
# 省略 --output-dir 时写入 fairy/scenarios/rice/。
uv run --extra wofost python scripts/build_rice_scenario_artifacts.py

# 八种完整生长季：工具执行、独立重放、守恒审计与参数敏感性。
uv run --extra wofost python scripts/run_rice_reference.py \
  --variant all --sensitivity --output-dir validation_runs/rice_v2

# 标准 CLI；也可以通过 --agent 接入已有模型服务。
uv run --extra wofost python -m fairy.cli \
  -s scenario_rice_l3_equipment_limit --build-oracle --replay --evaluate \
  --output-dir validation_runs/rice_cli_v2

# 全部 28 个场景的 reference / do-nothing 基线。
uv run --extra wofost python scripts/build_oracle_baselines.py \
  --scenarios rice --crop-backend wofost --include-donothing \
  --output-dir validation_runs/rice_baselines_v2

# 全部离线回归，包含水稻及通用接口。
DEEPSEEK_API_KEY=unit-test-placeholder \
QWEN_API_KEY=unit-test-placeholder \
uv run --extra wofost --with pytest python -m pytest -q --disable-warnings tests

# 水稻物理、工具及接口/验收回归。
uv run --extra wofost --with pytest python -m pytest -q --disable-warnings \
  tests/test_rice_paddy.py tests/test_rice_toolset.py \
  tests/test_rice_scenario_structure.py \
  tests/test_tool_schema.py tests/test_rice_validation_regressions.py \
  tests/test_error_recovery_replay.py
```

全套测试中的模型客户端用例只构造 SDK 或使用替身，不访问真实模型；两个占位环境变量仅用于满足已有 SDK 的初始化要求，不需要有效凭据。测试使用包内参考产物或自行建立的临时状态和基线，不依赖项目外测试目录或预先生成的 `validation_runs`。

`build_rice_scenario_artifacts.py` 是参考产物的生成入口，默认写入 `fairy/scenarios/rice/`，可用 `--output-dir` 指定审查或实验用输出目录。脚本先生成临时产物，再由 `verify_event_plans(staging, specs)` 使用实际注册场景类和 Engine 对全部 28 个计划执行事件、独立重放，检查目标验收及最终状态哈希；此验证直接读取临时产物，不依赖此前已发布的文件。全部通过后，发布 **123 个受校验产物：28 个 oracle 计划和 95 个来源季检查点**，最后替换 `scenario_artifacts.json`。清单记录各产物的 SHA-256 和 PCSE 版本；每份计划另记录初始检查点哈希、配置指纹及 `expected_final_state_sha256`。

常规场景运行只读取包内固定产物。文件缺失、校验失败、版本或初始检查点/配置不匹配会明确报错并提示重建；不会在运行时退回参考策略、自动生成产物或继续使用不匹配的计划。修改参考策略、模型参数或来源季配置后，应显式重建并审查产物。参考季报告和评估基线分别由其余脚本生成。

包内固定产物绑定 **PCSE 6.0.13**，`uv.lock` 已锁定该版本。使用其他 PCSE 6.0.x 版本时，必须在该环境显式重建产物；依赖声明允许 6.0.x 不代表不同版本的检查点或计划可直接互换。测试命令中的 `--disable-warnings` 仅收起第三方 traitlets 等警告摘要，不改变测试判定。

水稻场景默认使用 `wofost`；明确选择 `legacy` 或传入大豆模型配置会报错。列出场景不要求安装 PCSE；缺少执行依赖会给出安装方法。控制器使用水稻提示词，完整季建议至少 `--max-tool-calls 2500`，具体调用量由策略决定。

输出目录中的 `summary.json` 汇总八个变体；各子目录包含报告、基线、工具工作流、操作日志、逐日原生状态、首尾和阶段检查点。检查点保存模型事件历史、观测缓存、资源、作业批次及配置指纹，恢复时重建原生引擎。

## 水田、模拟单位与时钟

最小模拟单位是 **田格（paddy_plot）**：田埂围闭、可独立控制进排水、内部按均匀状态近似的区域。一个田格对应一个 WOFOST 引擎、连续水量和氮量账本，不等于插秧行或穴。示例 p1 为 1,000 m²，p2 为 1,500 m²，共用渠道、农机、库存和仓库。

| 换算 | 公式 |
|---|---|
| 水量 m³ | 水深 mm × 面积 m² / 1000 |
| 干物质或肥料 kg | kg/ha × 面积 m² / 10000 |
| 14% 水分粮重 kg | 粮食干重 / 0.86 |

作业同步串行执行。灌排是有限计量任务，流量决定工时，跨午夜分段计量。没有持续开闸、并行设备调度或路径规划。生长和土壤以日步长在 UTC 午夜积分，根区含水率是最近一次日积分估计；前置条件在作业开始时检查。仅显式模拟时间推动生长，墙钟延迟不影响结果。

分批插秧是作业分批，**同一田格必须在同一 UTC 日完成**；完成后只建立一次原生作物，不拆分 WOFOST 群体。未完成时跨日操作会被拒绝。分批收获可以跨日，并持续结算未收部分的延迟损失。

## 工具清单与工作流

| App | 数量 | 公开工具 |
|---|---:|---|
| `PaddyWorldApp` | 4 | `get_farm_overview`、`get_plot_state`、`get_inventory`、`get_operation_log` |
| `PaddyObservationApp` | 5 | `read_water_sensors`、`inspect_crop`、`measure_grain_moisture`、`inspect_pests`、`inspect_establishment` |
| `PaddyMachineryApp` | 4 | `get_machine_status`、`refuel`、`attach_implement`、`detach_implement` |
| `PaddyOpsApp` | 16 | `irrigate`、`drain`、`soak`、`puddle_and_level`、`load_seedlings`、`transplant`、`harvest`、`unload_grain`、`dry_grain`、`store_grain`、`load_fertilizer`、`apply_fertilizer`、`apply_pesticide`、`apply_fungicide`、`control_weeds`、`replant_seedlings` |
| `PaddyInfrastructureApp` | 3 | `inspect_infrastructure`、`clear_channel`、`repair_bund` |
| `PaddyDroneApp` | 3 | `check_status`、`fly_survey`、`charge` |

标准控制器另提供天气查询 2 项、时间工具 3 项、向用户报告 1 项。App 原始注册数为 42，其中向 agent 注入消息的接口由现有控制器隐藏。旧 `dry_and_store` 仅保留为 Python 兼容方法，不再是 agent 工具。

台账只提供面积、已完成作业、库存及先前取得的观测。**Agent 工具不直接输出原生 DVS、LAI、TWSO、RFTRA 或氮池**；完整原生状态只用于内部模型、检查点和评估。现场工具输出确定性、取整的工程观测，带采样时间和来源；再次读取台账不会自动刷新观测。人工巡查消耗时间，水分传感器读取不额外耗时。观测不是已校准的传感器误差模型。

主要作业链：

1. 台账、天气及水利巡检 → 必要时疏渠、修埂 → 泡田 → 拖拉机挂耙 → 耙平 → 调浅水层、基肥。
2. 检查插秧机油箱与装载量 → 装成品苗 → 同日分批插秧 → 查苗 → 必要时补苗、延时复查。
3. 传感器/巡田/航拍 → 灌排、追肥、病虫草害处理 → 推进时间 → 复查；操作受共享库存和作业窗口约束。
4. 收前排水 → 查成熟、含水率与天气 → 分批收割、卸粮 → 每粮批测水分、干燥 → 单独入库。

### 设备、投入与收后约束

| 对象 | 默认设置及行为 |
|---|---|
| 成品苗 | IR72，交付苗龄 20 天；20×20 cm、3 株/穴，即 75 株/m²；不支持密度响应或库存苗龄动态 |
| 整地 | 实际湿泡田 ≥24 小时、田面水 ≥5 mm、根区含水率 ≥0.45；需拖拉机与耙，耗油 0.004 L/m² |
| 插秧 | 已整平，田面水 ≤30 mm、根区含水率 ≥0.40；插秧机耗油 0.002 L/m²，默认装苗容量 150,000 株 |
| 农机 | 拖拉机、插秧机、收割机各有独立油箱；仓库燃油必须先加注，换农具先卸后挂 |
| 供水 | 默认 80 m³/h，输水效率 0.9，共享配额 12,000 m³；堵塞降低实际流量，配置可限制每日 UTC 开放时段 |
| 排水 | 默认 80 m³/h，只排田面水，不直接扣根区水 |
| 追肥 | 尿素产品含氮率 46%，剂量单位是 kg **产品**/ha；已耙田、未成熟且田面水 ≤50 mm，需装肥及挂撒肥器 |
| 收获 | 原生成熟、田面水 ≤0.1 mm、根区含水率 ≤0.42、当日雨量 ≤5 mm、粮食水分 14–28%；首选 20–25% |
| 粮箱 | 默认 1,500 湿 kg，所有田格共用；满箱须卸粮或缩小作业面积 |
| 干燥 | 按粮批处理至 14%；默认 10,000 湿 kg/日，蒸发 1 kg 水耗 0.06 kWh，干物质守恒；干燥不会自动入库 |
| 仓储 | 仅接收 ≤14% 水分粮批，默认容量 10,000 kg；不模拟长期仓储劣变 |
| 无人机 | 每 1,000 m² 耗电量 8%，巡查 10,000 m²/小时；雨量 >5 mm 或风速 >10 m/s 禁飞；满充耗时 1 小时、0.4 kWh |

成熟后，未收粮水分晴天每天减少 0.8 个百分点，雨量 >5 mm 时增加 1 个百分点，范围 12–28%。站秆延迟损失分别为剩余干重的 0.1%/日和 0.6%/日。机器损失以 3% 为基础；水分低于 20% 每低 1 个百分点增加 1 个百分点损失，高于 25% 每高 1 个百分点增加 0.5 个百分点损失。这些均是显式工程假设，非 WOFOST 原生输出。

### 病虫草害、缺苗与水利故障

病虫草害各维护 0–1 压力，按 Logistic 近似逐日增长。处理使用独立药剂库存、喷雾器和天气窗口；除草使用时间且要求浅水。压力和缺苗形成同化倍率：

```text
stand_fraction × max(0.2, 1 − 0.25×虫害 − 0.35×病害 − 0.30×杂草)
```

倍率作用于 WOFOST 8.1 原生同化计算结果，再由原生生长过程积分，因此会影响后续生物量和产量。它不是已验证的水稻病种、药剂或竞争生长模型，默认处理剂量不能当作生产施药建议。

补苗仅允许在移栽后 14 天内，消耗实苗、油和作业时间，两天后提高成活比例；保留原作物发育日历和生物量，不模拟新苗独立群体。无人机只提供田格平均覆盖和异常提示，诊断需落地巡查。

渠道堵塞增加同等水量的灌排工时；疏通恢复额定流量。田埂漏水进入独立水量损失项及经验氮迁移损失，修复消耗 10 kg 材料和两小时工时。

## 原生 WOFOST 8.1 与参数来源

作物为 `pcse.crop.wofost81.Wofost81`；以 `WOFOST81_Assimilation` 的轻量子类施加上述外部同化倍率，其余 8.1 原生计算保留。土壤由有限氮的 `N_Soil_Dynamics` 和两层 CWB 扩展组成，模型标识为 `Wofost81_NWLP_PADDY`。本版取代 v1 的无限土壤氮供应。

上游 [rice.yaml](../fairy/physics/data/wofost/rice/rice.yaml) 固定于提交 `1ca91d7dbb5aaf6b41462162de03a8254812d3a5`，校验和、URL 和许可见 [provenance.json](../fairy/physics/data/wofost/rice/provenance.json)。IR72 移栽起点采用上游 `DVSI=0.16`、`TDWI=50 kg/ha`、`RDI=10 cm`；原生 emergence 事件在此表示移栽建模起点，DOE 不是育秧出苗日。

上游 IR72 缺少两个 8.1 必需参数；[独立补全文件](../fairy/physics/data/wofost/rice/ir72_wofost81_completion_v1.json) 参与指纹：`AMAX_REF=40` 根据 IR72 恒定 AMAXTB 取值转换，未证明两版方程等价；`KN=0.4` 借用同文件 rice_eu，不是 IR72 本地标定。`AMAX_SLP=3.24` 和 `AMAX_LNB=0` 继承上游 GenericC3。

默认初始可用氮 30 kg N/ha、土壤储备氮 40 kg N/ha、矿化比例 0.005/日、背景供应 0.05 kg N/ha/日。施肥氮回收率设为 0.7。排水、渗漏、溢流和漏埂的经验迁移比例为 `min(0.10, 外流水深mm×0.0005)`，作用于当前可用氮池。没有模拟铵硝形态、硝化或反硝化。

```text
初始水 + 降雨 + 到田灌溉
  = 当前田面/土壤水 + 蒸发 + 蒸腾 + 深层渗漏 + 溢流 + 主动排水 + 漏埂
初始可用/储备氮 + 施肥总氮 + 背景输入
  = 当前可用/储备氮 + 作物吸收 + 未回收施肥氮 + 迁移损失
```

移栽不重置土壤水氮。田埂默认 150 mm，土层 60 cm；耙田前 SOPE/KSUB 为 4/1 cm/日，之后为 1/0.2。该模型不等于地下水位、空间侧渗、深水淹没损伤或标准 AWD 水位管模型。

天气采用合成热带驱动：23–31°C、辐射 18 MJ/m²/日、位置 14.2°N/121.2°E，并按变体覆盖降雨。基础预报等于配置天气；水利变体另提供有标识的确定性降雨预报偏差。阶段观测是原生发育进度的管理代理，不声称模拟分蘖数、有效穗数或真实幼穗分化。

## 28 个场景

公共前缀为 `scenario_rice_`。L1 共 13 个，L2 共 7 个，L3 共 8 个。

| 层级 | ID 后缀 | 工作流重点 |
|---|---|---|
| L1 | `l1_irrigate`、`l1_drain` | p1 定量灌水 30 mm / 排出至多 20 mm |
| L1 | `l1_puddle`、`l1_transplant`、`l1_harvest` | 设备与现场条件检查 → 对应单田格作业 |
| L1 | `l1_observe_water` | 读取并保存新水分观测 |
| L1 | `l1_refuel` | 油箱/库存检查 → 拖拉机加油 10 L |
| L1 | `l1_dry`、`l1_store` | 测水分 → 分别干燥或入库 |
| L1 | `l1_fertilize` | 查水层 → 调水、挂撒肥器、装肥 → p1 追肥 |
| L1 | `l1_scout` | 航拍两田格 → 落地查病虫草害 |
| L1 | `l1_repair_bund` | 巡检 → 修复 p1 漏埂 |
| L1 | `l1_gap_fill` | 查缺苗 → 装苗、补苗 → 两天后复查 |
| L2 | `l2_establishment` | 初始田块 → 泡田、整地、基肥 → 插秧与查苗 |
| L2 | `l2_irrigation_management` | 生长期检查点 → 至少 10 天灌排管理，检查水分胁迫 |
| L2 | `l2_nutrition_management` | 生长期检查点 → 至少 25 天水肥管理 |
| L2 | `l2_harvest_storage` | 收前排水 → 成熟监测 → 收割、卸粮、干燥、入库 |
| L2 | `l2_crop_protection` | 航拍、巡查 → 虫/病处理、除草 → 危害下降 |
| L2 | `l2_infrastructure_recovery` | 巡检 → 修埂、疏通渠道 |
| L2 | `l2_harvest_batches` | 小粮箱条件下两田格分批收获和收后处理 |
| L3 | `l3_normal` | 常规完整季，日雨量 1 mm、取水配额 12,000 m³ |
| L3 | `l3_water_limit` | 无雨、取水配额 1,100 m³ |
| L3 | `l3_late_rain` | 常规季叠加 4 月 1–4 日每日 25 mm 降雨 |
| L3 | `l3_nitrogen_limit` | 较低初始土壤氮、仅 55 kg 尿素库存 |
| L3 | `l3_biotic` | 初始虫、病、草压力各 0.3，需巡查及干预 |
| L3 | `l3_infrastructure` | p1 漏埂 8 mm/日、进水渠堵塞 60%、06–20 时供水窗口 |
| L3 | `l3_equipment_limit` | 各机初始仅 1 L 油、75,000 株苗仓、600 kg 粮箱、2,000 kg/日干燥 |
| L3 | `l3_poor_stand` | p1 初始成活比例 0.75，需查苗补苗 |

除起始任务外，L1/L2 从对应 L3 参考季的真实工具检查点派生，不直接赋值 DVS 或生物量。来源季在离线产物构建时执行，运行时从磁盘恢复检查点。参考策略只通过公开观测与工具行动，完整状态仅用于保存检查点；它不保证最优。限水和限氮变体各同时改变多个条件，不可当作单因素因果试验。

## 评估与兼容性

使用 `schema_version=4 / rice_outcome_v2`，世界和原生适配器检查点 schema 为 2，管理配置为 `paddy_operations_v2`。新增字段及模型变化会改变指纹，**必须重建 v1 基线和检查点**。

`validation.py` 检查目标、工具错误、水氮守恒、苗/肥/油/药/电/维修材料账本、收获干物质与粮批容量，公共场景基类调用这些验收逻辑。`evaluation.py` 保留水稻指标计算：产量按实际田格面积换算，分别报告生物籽粒干重、已收获干重、14% 水分入库量、站秆/机收损失及资源消耗。

完整季、收获入库和分批收获任务要求所有粮批均已入库、含水率不超过 14%，粮箱和接粮区无剩余干粮，且每个田格的入库干重与已收获干重一致。仅部分粮批入库，即使资源守恒审计通过，也不满足任务目标。

`metadata.goal_met` 单独表示目标是否达成；`metadata.tool_errors` 同时识别标准 `TOOL_ERROR` 记录和旧式 `content.error` 记录，每步只计一次。整体 `success` 仍要求目标达成、零工具错误且守恒审计通过，因此成功纠错不会抹掉此前的错误。

工具 JSON Schema 按 Python 类型注解递归生成：地块列表是字符串数组，作业面积接受数值或 `null`；有默认值的参数可省略。整个工具参数必须是 JSON 对象，传入 `null`、列表等值会在解析阶段被拒绝，不执行工具，并记录可重放的稳定错误。

标准 `Engine.replay_workflow` 会重新验证轨迹中明确记录的工具错误，匹配异常类型、消息以及可检查的应用状态和显式仿真时钟，再继续后续动作；意外异常、预期失败变成成功、错误不匹配或失败造成状态变化均会终止重放。旧字符串错误记录仍兼容，新记录另保存结构化错误与原始参数；缺少原始参数的解析错误，以及历史非对象参数产生的不稳定调用异常，会明确拒绝重放。未提供 `get_state()` 的应用无法通用核对其私有状态。

生物量评估在私有检查点副本中无后续管理地推进已种植田格至原生成熟，未种植田格不自动种植，未完成分批插秧不允许投影。收获/入库只统计实际取得结果。reference 和 do-nothing 从同一初始检查点独立运行。

比较前检查 PCSE、参数、模型、水田、天气、场景、初始检查点和目标田格指纹。相对收益 `(agent − do-nothing)/(reference − do-nothing)` 不截断；分母无差异时返回 `null`。观测、加油、维修类任务还必须看任务验证和资源状态，不能只看产量。

指定 `FOS_ORACLE_BASELINE_DIR` 可将比较写入标准评估的 `metadata.rice_outcome`；缺失或不兼容基线会明确报错。旧的按大豆垄计算的 FOS rebatch/export 不适用于水稻。批量 runner 已能识别水稻层级并记录任务验证结果，但尚未把 `rice_outcome` 接入大豆的统一 FOS 汇总；水稻尚无相同口径的决策、效率和综合评分，不能直接用现有 FOS 分数做跨作物比较。

## 本轮场景组织迁移核对

本轮使用 **PCSE 6.0.13**，全套 **427 项测试通过**，包括原有 354 项回归和新增 73 项场景结构、产物与运行路径用例。测试入口包含 `tests/test_rice_scenario_structure.py`。

- 重新生成的 28 份计划中，`expected_final_state_sha256` 与迁移前保存的 28 个场景最终状态哈希逐项一致。
- 在独立目录重新生成 123 个产物及清单，与包内版本逐字节一致；增强后的构建脚本已实际完成全部 28 个计划的发布前事件执行、独立重放、任务验收和最终哈希校验。
- 八种完整参考季及参数敏感性运行通过；每个参考季的工具执行与独立重放最终完整状态一致。
- 标准 CLI 的设备受限完整季构图、重放与评估通过；全部 28 个场景的 reference / do-nothing 基线完成构建。

本轮报告分别写入 `validation_runs/rice_structure_alignment`、`validation_runs/rice_structure_cli` 和 `validation_runs/rice_structure_baselines`，这些运行目录不随仓库提交。以上验证未使用真实 LLM 服务，也不表示水稻已接入大豆统一 FOS 评分或完成跨作物评价。

## 2026-10-23 模型服务测试

使用 `http://100.89.223.79:8000/v1` 返回的 `Qwen3.8-27B-FP8`，通过标准 `fairy.cli --agent` 和 `farm_baseline_react` 控制器执行真实函数调用。正式批次覆盖全部 28 个场景、每场景一次：温度 0.1、详细 briefing、允许同轮多个工具调用、关闭 A2A、输出上限 2048 token、不覆盖服务端思考设置，8 个场景并发。每场景上限为 1200 次工具调用和 900 秒；HTTP 请求等待为 600 秒。这是受限预算的端到端测试，不等于无时间限制的完整季能力评估。

| 层级 | 场景数 | 严格通过 | 目标达成 |
|---|---:|---:|---:|
| L1 | 13 | 11 | 11 |
| L2 | 7 | 1 | 2 |
| L3 | 8 | 0 | 0 |
| 合计 | 28 | 12 | 13 |

28 份原始报告和工作流均完整保存；全部资源审计通过，独立重放的任务验收与实际 `outcome` 均和原运行一致。12 个场景正常结束，16 个达到 900 秒后被批量监督器中断；因此 L3 的零通过表示本预算内未完成，不是无约束能力结论。L2 病虫防治虽已达成目标，但发生过一次工具错误，按既有严格规则仍不通过。

正式批次共返回 211 次模型响应、执行 361 次工具调用。记录到 4 次输出截断和 6 次工具错误，已返回响应的耗时中位数约 43.6 秒。工具错误涉及未成熟时测量籽粒水分、施药剂量、联合收割机燃油与粮箱容量、供水 UTC 时窗。复核未发现这些拒绝源于执行器异常，但确认施药上限未写入工具说明/Schema，供水窗口及不同时间显示的时区标注也不统一；本次保留原接口执行测试，没有在批次中更改约束或验收。

单场景复现示例：

```bash
FAIRY_LLM_REQUEST_TIMEOUT_S=600 .venv/bin/python -m fairy.cli \
  --scenario scenario_rice_l1_irrigate --agent \
  --controller farm_baseline_react --provider vllm \
  --model Qwen3.8-27B-FP8 --endpoint http://100.89.223.79:8000/v1 \
  --temperature 0.1 --max-output-tokens 2048 --parallel-tool-calls true \
  --max-tool-calls 1200 --timeout-seconds 900 --crop-backend wofost \
  --scenario-kwargs '{"detailed_briefing":true}' \
  --output-dir validation_runs/rice_model_single
```

全量配置和报告保存在本地 `validation_runs/rice_qwen38_20261023/`：设置 `FAIRY_LLM_REQUEST_TIMEOUT_S=600` 后，将 `config.json` 传给已有 `scripts/iclr_validation_runner.py --config` 即可使用正式批次参数。单独 CLI 的超时在调用边界检查，批量 runner 另提供进程级硬墙钟上限。`summary.md`/`summary.json` 汇总严格验收，`findings.md` 记录操作错误及接口说明问题，`replay_checks/` 保存独立重放核对和离线基线比较。这些目录不随仓库提交。正式运行不注入可选的 `FOS_ORACLE_BASELINE_DIR`，避免未完成状态的投影异常掩盖任务验收；基线比较在离线重放后单独执行。

早期 `smoke` 使用不同输出预算；`preflight_http120` 使用 120 秒请求等待并出现 SDK 超时重试。两者均单独保留，不计入正式结果。Token 统计仅包含服务已返回的 usage，中断请求和 SDK 内部重试可能没有 usage，不能将其当作全部服务端消耗；现有批量 runner 的美元估价也不是本地模型的真实账单。

本次补充了 CLI 的中断保存：批处理达到墙钟上限发送 SIGINT 后，保留工作流、运行日志和验收报告，状态记为 `interrupted`。相关 6 项测试通过，包括新增 `tests/test_cli_interrupt.py`；中断不意味着任务成功，仍需读取 `goal_met`、`tool_errors`、`audit` 和严格 `success`。

## 此前工具扩展的验证记录

本节保留场景组织重构前的结果，不能作为本轮重构的测试结论。本轮验证应以重新执行的命令输出和报告为准。

此前使用 PCSE 6.0.13、无 LLM，八个变体工具执行与独立重放最终状态完全一致。当时 **354 项测试通过**：66 项水稻测试、251 项既有回归、37 项接口与验收回归。28 个场景均生成了验证成功的 reference / do-nothing 基线，标准 CLI 的设备受限完整季执行、重放和评估通过。覆盖原生氮/同化产量响应、资源与水氮守恒、非法操作不扣资源、观测缓存、分批作业及跨日拒绝、工具检查点恢复、全部场景重放、参数 Schema、完整入库验收、工具错误计数、纠错轨迹重放及非对象 JSON 参数保护。

项目外的智能体探索测试另保存了覆盖 28 个场景的 30 份轨迹；修复后由标准重放器重放，30 份最终完整水田状态均与原记录一致。这些轨迹与生成日志是辅助评审材料，不随仓库提交；对应缺陷的自动回归已包含在仓库中。探索时使用当前会话智能体通过本地接口调用真实工具，完整季允许自编观测驱动脚本；独立 Codex CLI 因 401 认证失败未完成模型端到端测试。历史轨迹重放和上述无 LLM 的标准 CLI 验证不能替代真实模型服务测试。

合作者评审建议先运行全套回归、八种参考季和全部 28 个基线，再使用配置正常的模型服务至少运行一个 L1、L2、L3 场景，检查参数声明、纠错行为、完整收储及 `goal_met`/`tool_errors`/`success` 的区分。模型结果需同时注明 IR72 工程补全、合成热带天气和辅助压力模型等边界；本版定位为可复现的工程基线，未证明田间预测精度。

| 变体 | 生物籽粒干重 kg | 14% 入库 kg | 渠道取水 m³ |
|---|---:|---:|---:|
| normal | 1310.20 | 1477.78 | 1766.67 |
| water_limit | 823.27 | 928.57 | 1098.16 |
| late_rain | 1310.20 | 1465.98 | 1766.67 |
| nitrogen_limit | 817.52 | 922.09 | 1766.67 |
| biotic | 1229.69 | 1385.59 | 1766.67 |
| infrastructure | 1310.17 | 1477.76 | 1766.67 |
| equipment_limit | 1310.20 | 1477.13 | 1766.67 |
| poor_stand | 1310.66 | 1478.30 | 1766.67 |

收前降雨在生物产量相同的情况下减少实际入库量；设备分批增加作业历时并产生差异。未标定非线性模型中，补苗后的生物产量可能略高于正常变体，不应解释成真实增产结论。逐日最大水氮平衡残差均小于 `1e-9`（分别为 mm 和 kg N/ha）。

后续实地校准应选定目标稻区/品种、实测天气与水土参数，以移栽—抽穗—成熟日期、覆盖/LAI、产量、田面水、氮肥响应和病虫调查验证。当前未包括地下水 AWD、磷钾、育秧及苗龄响应、真实多群体补苗、药剂药效标定或长期仓储。

主要实现：[显式场景入口](../fairy/scenarios/rice/)、[参考产物构建](../scripts/build_rice_scenario_artifacts.py)、[参考策略](../scripts/rice_reference_policy.py)、[水田工具](../fairy/apps/paddy/)、[原生适配器](../fairy/physics/rice_backend.py)、[水氮平衡](../fairy/physics/paddy_waterbalance.py)、[参考季报告脚本](../scripts/run_rice_reference.py)、[基础测试](../tests/test_rice_paddy.py)、[扩展测试](../tests/test_rice_toolset.py)。

接口与验收回归：[参数 Schema](../tests/test_tool_schema.py)、[完整入库与错误统计](../tests/test_rice_validation_regressions.py)、[错误恢复轨迹重放](../tests/test_error_recovery_replay.py)。
