# 多农场、多作物重构与 Oracle

**同一个场景管理多个农场全季**请使用 [全季场景与 Oracle](multi-farm-full-season.md)，推荐入口 `scenario_multi_crop_full_season_mixed`。本页保留阶段任务及其操作回归说明。

这里新增 **4 个多农场场景 + 4 个多作物场景**。`maize` 表示籽粒玉米，`rice` 表示旱直播、非淹水水稻；大豆原有品种继续可用。这批是可执行的农事操作基准，oracle 是满足任务约束的参考策略，不声称求得全局最优产量。

| 类别 | 场景 | Oracle 步数 | 完整工具与参数 |
|---|---|---:|---|
| 多农场 M1 | 三场不同垄数播种 | 35 | [workflow JSON](../configs/oracles/diverse/scenario_multi_farm_uneven_planting.json) |
| 多农场 M2 | 分场定向灌溉与额度 | 16 | [workflow JSON](../configs/oracles/diverse/scenario_multi_farm_targeted_irrigation.json) |
| 多农场 M3 | 分批收获与独立粮仓 | 29 | [workflow JSON](../configs/oracles/diverse/scenario_multi_farm_harvest_storage.json) |
| 多农场 M4 | 局地降雨与作业隔离 | 21 | [workflow JSON](../configs/oracles/diverse/scenario_multi_farm_weather_isolation.json) |
| 多作物 C1 | 玉米建植 | 13 | [workflow JSON](../configs/oracles/diverse/scenario_multi_crop_maize_planting.json) |
| 多作物 C2 | 旱直播水稻建植 | 15 | [workflow JSON](../configs/oracles/diverse/scenario_multi_crop_rice_planting.json) |
| 多作物 C3 | 三作物协同建植 | 37 | [workflow JSON](../configs/oracles/diverse/scenario_multi_crop_mixed_planting.json) |
| 多作物 C4 | 玉米／水稻分场收储 | 33 | [workflow JSON](../configs/oracles/diverse/scenario_multi_crop_harvest_storage.json) |

## 从固定农场到组合模型

| 层 | 新约定 | 解决的问题 |
|---|---|---|
| 土地 | `FarmWorldApp(farm_id, num_ridges, field_length_m, ridge_width_m, crop_type)` | 每个农场独立定义垄数、长度、垄宽及作物；默认仍为原大豆场 |
| 作物 | 冻结的 `CropProfile` | 种子、行数、播深、株距、阶段、成熟标记、收获水分、产量代理和灌溉阈值集中定义 |
| 农场 | `FarmSite` | 保存土地、天气关联和本场观测／操作状态，不决定独占七套 App |
| 设备资产 | `AssetSpec` / `AssetState` | 单独声明设备 ID、种类、可服务农场和一份油量／电量／载荷状态 |
| 多场装配 | `FarmFleet(..., shared_tools=True)` / `FarmRuntime` | 将农场、设备与绑定组合起来，通过显式 runtime 参与者接入 Engine |
| 共享服务 | `Farm`、`Weather`、`Sensor`、`FieldOps`、`Tractor`、`Drone`、`Robot` | 相同方法使用同一工具入口，数量不按农场数复制 |
| 路由 | `Tractor__plant_seeds(farm_id=..., asset_id=...)` | 同号垄按 farm ID 区分；设备按 asset ID 区分，不能默认选第一个目标 |
| 时间 | 一个 `Engine` 时钟，所有场站同步推进 | 等待和设备作业耗时都作用于所有农场，闲置农场继续演化 |
| 观测 | 按实际垄数划分最多六个连续传感器分区 | 1 垄、小于 64 垄、大于 64 垄都能完整覆盖，无越界；64 垄保留旧分区 |
| 核算 | 每场 outcome + 资产状态 + 总计 | 仓库物资和额度按场核算；设备状态按资产核算；粮食按来源场归属，面积使用实际尺寸 |

例如新增一个 13 垄玉米场，不需要复制农机或传感器实现：

```python
from fairy.apps.farm_world.multi_farm import AssetSpec, FarmSite, FarmFleet
from fairy.apps.system import SystemApp

north = FarmSite.create("north", "North", num_ridges=13,
                        field_length_m=160, ridge_width_m=0.75,
                        crop_type="maize", create_devices=False)
rice = FarmSite.create("rice", "Rice", num_ridges=21,
                       field_length_m=100, ridge_width_m=1.0,
                       crop_type="rice", create_devices=False)
assets = [AssetSpec("tractor_shared", "tractor", ("north", "rice")),
          AssetSpec("robot_shared", "robot", ("north", "rice")),
          AssetSpec("drone_shared", "drone", ("north", "rice"))]
fleet = FarmFleet([north, rice], assets=assets, shared_tools=True, seed=0)
apps = [*fleet.apps, SystemApp()]
runtime_participants = [fleet.runtime]  # 在 Scenario 上显式声明给 Engine
```

这个示例与八个全季场景一样共享三项设备资产。**本页八个阶段任务则显式为每场配置专用设备**，以保留局地降雨下“另一场设备不动”等操作测试条件；工具入口仍只注册一套。是否共享设备由场景资产清单决定，不由 `FarmSite` 隐式创建。旧 `tool_prefix` 仅保留显示名与内部兼容句柄，公开工具不再命名为 `NorthTractor__...`。

Agent 使用 `World__describe_environment()` 读取实际农场、垄范围、站点、探头、资产与绑定，使用 `World__get_capabilities(farm_id=..., asset_id=...)` 读取目标作物约束和设备容量。模型收到的 function schema 和实际 dispatch 由同一工具契约生成，提供参数类型、默认值、单位与合法 ID；实时天气、土壤、油量、电量和充电状态由相应查询工具读取。工具返回统一 envelope，`ok` 表示是否成功，`data` 保存观测或结果，`error` 保存结构化拒绝原因。

设备自身状态、充电和挂载只接收 `asset_id`；播种、收获等田间动作同时接收 `farm_id` 与 `asset_id`。一台设备跨场使用时保持同一油箱、电池、挂载和充电状态。Tractor 携带的种子、肥料、药剂和粮食有来源：换场前用 `Tractor__return_supplies(asset_id=...)` 将残余供料退回来源仓；粮食须先在来源场卸粮，不能借切换目标跨场混粮。当前不模拟道路、运输时间或经营成本。

完整边界见 [共享工具与资产设计](multi-farm-shared-tools-design.md)，完整公开方法见 [services/](../fairy/apps/farm_world/services/)，平台接线见 [runtime.py](../fairy/apps/farm_world/runtime.py)、[shared_apps.py](../fairy/apps/farm_world/shared_apps.py) 和 [tool_execution.py](../fairy/tool_execution.py)。

播种量公式为 `round(垄长 m × 每垄种植行数 × 100 / 株距 cm)`；面积为 `垄数 × 垄长 × 垄宽`。最后一趟取 `min(start + 3, num_ridges - 1)`，不能继续假设 16 趟或 0–63。

## 作物配置与模型边界

| 作物 | 默认种子 | 每垄行数 | Oracle 播深 / 株距 | 成熟标记 | 最大收获水分 |
|---|---|---:|---|---|---:|
| 大豆 | STANDARD（原有大豆品种也可用） | 2 | 4 cm / 8 cm | R8 | 18% |
| 玉米 | MAIZE_STANDARD | 1 | 5 cm / 20 cm | R6 | 25% |
| 水稻 | RICE_STANDARD | 4 | 2 cm / 10 cm | maturity | 24% |

玉米、水稻的播种约束、生育阶段、密度及收获规则不同，不能把大豆种子改名后沿用大豆 R8。物理路径按作物配置热量、生物量及成熟后的水分代理，并向外输出对应作物阶段。内部通用引擎使用阶段锚点进行映射；这些玉米／水稻参数是透明的仿真假设，尚未进行当地品种标定。

播深的量级参考：[明尼苏达大学玉米播种说明](https://extension.umn.edu/agriculture/crop-production/corn/strategies-successful-corn-planting)（通常约 2 英寸）、[IRRI 旱直播水稻说明](https://www.ricetoday.irri.org/deep-sowing-of-dry-direct-seeded-rice-cultivar-differences-in-seedling-establishment-and-grain-yield/)（常见钻播 1–2 cm）。行数、株距、产量代理及本基准的水分阈值为场景配置，不是上述来源给出的地区农艺推荐。

当前水稻场景不模拟移栽、淹水层、田埂蓄水和排水。WOFOST 后端仍只支持已有大豆参数，给玉米／水稻选择 WOFOST 会明确报错；不能无声地调用大豆模型。收获场景从明确的成熟快照开始，验证收获与收储操作；播种场景启用物理代理并推进七天，验证实际播种与时间推进。

## 场景与标准答案

以下 ridge 范围均包含两端。每场先执行：`Farm__get_farm_overview(farm_id=...)` → `Weather__get_current_weather(farm_id=...)` → `Sensor__read_soil_sensors(farm_id=...)`，并读取所选 `Tractor__get_status(asset_id=...)`。天气、土壤与库存证据必须属于目标场；设备状态证据必须属于所选资产。

### M1：三场不同垄数播种

ID：`scenario_multi_farm_uneven_planting`

| 农场 | 布局 | 每垄种子 | 分趟范围 | 总种子 |
|---|---|---:|---|---:|
| North | 5 × 120 m × 1.1 m，大豆 | 3,000 | 0–3；4–4 | 15,000 |
| East | 9 × 180 m × 1.1 m，大豆 | 4,500 | 0–3；4–7；8–8 | 40,500 |
| West | 3 × 90 m × 1.1 m，大豆 | 2,250 | 0–2 | 6,750 |

每趟先从本场仓库装载恰好足够的 STANDARD 种子，再以 4 cm / 8 cm 播种。先读本场七天预报；所有播种场景都设置为当日无雨，随后七天日均温 26°C、降雨 2 mm/天、辐射 15 MJ/m²/天，支持雨养出苗。三个场全部完成后统一推进七天，再分别读传感器和 overview。

验收：17 垄全部种上本场大豆且实际出苗，三场各自库存减少恰好对应总种子数，料斗清空，无收获；所有场的物理时间均达到七天检查点。漏掉尾趟、使用 268 m 计算耗种、把 East 的种子扣到 North 均失败。

### M2：分场定向灌溉与独立额度

ID：`scenario_multi_farm_targeted_irrigation`

| 农场 | 垄数 | 缺水垄 / 初始 VWC | 操作 | 本场额度 | 交付后目标 VWC |
|---|---:|---|---|---:|---:|
| North | 7 | 2–4 / 0.18 | `FieldOps__irrigate(farm_id="north", start=2, end=4, hours=2)` | 30/7 ≈ 4.285714 mm | 0.280 |
| South | 11 | 7–10 / 0.18 | `FieldOps__irrigate(farm_id="south", start=7, end=10, hours=1.5)` | 30/11 ≈ 2.727273 mm | 0.255 |

其他垄初始 VWC 均为 0.31，不灌溉。额度是全场等效水深：`5 mm/h × 小时 × 目标垄数 / 本场总垄数`。两场操作完成后 `SystemApp__advance_time(hours=2)`，再分场复查。这里使用显式的传统水分交付模型：每小时增加 0.05 VWC，操作完成后有两小时交付延迟。

验收：日志目标集合与任务一致、每垄只执行一次；七个缺水垄达到各自目标，其他垄保持 0.31；无待交付灌溉；各场消耗不超过自己的额度。向健康垄泛灌、等待前重复灌溉、漏等交付均失败。

### M3：两场分批收获、烘干、入仓

ID：`scenario_multi_farm_harvest_storage`

| 农场 | 布局 | 初始阶段 / 水分 | 收获范围 |
|---|---|---|---|
| North | 5 × 120 m × 1.1 m | R8 / 16% | 0–3；4–4 |
| South | 7 × 180 m × 1.1 m | R8 / 17% | 0–3；4–6 |

每趟执行本场 `harvest` → `unload_grain` → `Farm__dry_grain(target_moisture_pct=13)` → `Farm__store_grain`。仓储上限设为 13.5%，不能直接把田间收获水分当作安全入仓水分。

验收：12 垄全部收获，按实际垄面积计算的粮食全部进入原属农场粮仓；联合收割机粮箱和拖车都清空；每批安全收储。只收割不卸粮、卸粮后不入仓、湿粮入仓，均失败。

### M4：局地天气隔离

ID：`scenario_multi_farm_weather_isolation`

Dry：5 垄、120 m，成熟大豆，16% 水分，本站无雨。Rainy：9 垄、180 m，成熟大豆，16% 水分，本站降雨 12 mm。

标准答案只在 Dry 执行两趟收获、卸粮、烘干、入仓。在 Rainy 完成观测并保留作物、库存和农机状态；Dry 的天气不能替代 Rainy 的天气检查。

验收：Dry 全部收储；Rainy 零收获、零物资变化、农机和料斗未变、没有写操作。对 Rainy 的收获尝试即使被工具阻止，也计作任务失败。

### C1：玉米建植

ID：`scenario_multi_crop_maize_planting`

Maize：7 垄 × 140 m × 0.75 m；MAIZE_STANDARD，每垄一行，5 cm 播深、20 cm 株距，每垄 700 粒。分趟 0–3、4–6，对应装载 2,800、2,100 粒，共 4,900 粒；随后推进七天并复查。

验收：7 垄玉米均已出苗，正确种子、播深、密度和本场扣库；料斗空、零收获、物理时间到达建植检查点。错误大豆种子或水稻浅播参数会被拒绝。

### C2：旱直播水稻建植

ID：`scenario_multi_crop_rice_planting`

Rice：9 垄 × 100 m × 1.0 m；RICE_STANDARD，每垄四行，2 cm 播深、10 cm 株距，每垄 4,000 粒。分趟 0–3、4–7、8–8，装载 16,000、16,000、4,000 粒，共 36,000 粒；随后推进七天并复查。

验收同 C1，但使用水稻自己的建植约束和阶段名称。此场初始土壤 VWC 0.26，土温 20°C；不会使用大豆播深默认值或假设田内已有淹水层。

### C3：三作物统一调度

ID：`scenario_multi_crop_mixed_planting`

Soy：5 垄 × 120 m × 1.1 m，15,000 粒大豆。Maize 与 C1 相同，4,900 粒。Rice 与 C2 相同，36,000 粒。

逐场完成本场观测、按作物装种及播种，再统一推进七天。三场共 21 垄、7 趟。验收逐场检查 crop/seed/geometry 和物料守恒，禁止用一个全局 seed_type 或 64 垄循环覆盖全部场站。

### C4：玉米、水稻各自成熟与收储

ID：`scenario_multi_crop_harvest_storage`

| 农场 | 布局 | 初始阶段 / 水分 | 最大收获水分 | 参考产量 |
|---|---|---|---:|---:|
| Maize | 7 × 140 m × 0.75 m | R6 / 22% | 25% | 735 kg |
| Rice | 9 × 100 m × 1.0 m | maturity / 23% | 24% | 675 kg |

Maize 分两趟、Rice 分三趟。每趟收获后卸粮、烘干至 13%、入原场粮仓。无需把玉米／水稻错误地改成大豆 R8，也不应沿用大豆 18% 收获限制。

验收：16 垄收获，Maize 仓 735 kg、Rice 仓 675 kg；两个粮箱和拖车清空、均为安全储存水分。提前用非成熟阶段收获、跨场混粮、只按“大豆每垄 245 kg”累计均失败。

## 如何检查详细 Oracle

版本化的八个 workflow 位于 `configs/oracles/diverse/`。每个步骤含：

- `tool_name`：规范共享服务名称，例如 `Tractor__plant_seeds`。
- `tool_args`：显式目标 `farm_id`／`asset_id` 以及尾趟范围、种子数量、播深和株距；资产自身操作不附虚构的农场参数。
- `depends_on`：前置步骤依赖，保证可顺序 replay。
- `content.oracle_reason`：这一步的决策理由。replay 文件的 `content` 则保存真实工具结果。

每份 JSON 配套同名 manifest sidecar，例如 `scenario_multi_crop_mixed_planting.json` 与 `scenario_multi_crop_mixed_planting.manifest.json`。sidecar 保存工具目录版本、场景配置指纹和 workflow 内容指纹；复制与重放时需同时保留。参数、依赖、版本或配置不匹配时，在执行目标工具前拒绝；运行时农业条件不满足时，记录失败步骤并停止 Replay。旧前缀轨迹需要显式迁移，不能无清单地猜测农场或资产。

验证器同时检查最终农场状态与本场观测前置条件，不把“和 oracle 文本完全一样”当作任务成功。它按工具真实的写属性识别操作，因此真实 agent 的 `op_type=TOOL` 也不能绕过检查。空轨迹必须失败。

这批场景使用专用的分场 outcome/safety 验证器；没有把旧单场 FOS 直接套到多场结果。原 `build_oracle_baselines.py` 的缓存以单个 ridge ID 为键，遇到多农场会明确拒绝。以下脚本才是这八个场景的统一 oracle 验证入口。

```bash
PYTHONPATH=. uv run python scripts/validate_diverse_oracles.py \
  --output-dir validation_runs/diverse_oracles \
  --references-dir configs/oracles/diverse

PYTHONPATH=. uv run --with pytest python -m pytest -q \
  tests/test_diverse_scenarios.py tests/test_multi_farm_runtime.py \
  tests/test_farm_crop_geometry.py tests/test_crop_physics.py
```

每场原生运行包包含 oracle、replay、evaluation、runtime log 和 `*.run_report.json`。先看 `validation_runs/diverse_oracles/summary.json`，然后查失败场景的 `validation_message` 与详细报告；不能只看命令退出码或 `status=completed`，还必须满足 `evaluation.validation.success=true`。

单场也可通过现有 CLI 运行，例如：

```bash
PYTHONPATH=. uv run python -m fairy.cli \
  -s scenario_multi_crop_mixed_planting \
  --build-oracle --replay --evaluate \
  --workflow /tmp/fairy-mixed/oracle.json \
  --output-dir /tmp/fairy-mixed
```

真实 agent 使用同一 `scenario_id` 和 `--agent` 即可。共享服务不会随农场数重复工具；准确 ID 和目标范围从实际目录和 function schema 获取。这里的离线验收无需模型密钥，也没有声称已验证真实 LLM 的任务成功率。

共享工具迁移后，八个阶段任务均已通过规范工具导出与新初态回放，见 [当前阶段任务汇总](../validation_runs/explicit_tools_episodes/summary.json)。8 个阶段与 8 个全季保存文件还通过了独立 Python 进程加载、回放及验收，见 [16/16 独立文件回放汇总](../validation_runs/explicit_tools_file_replay/summary.json)。全季共享资产证据见 [全季共享工具汇总](../validation_runs/explicit_tools_full_season/summary.json)，对应 8 个全季场景和 19 个农场。下面保留迁移前的历史统计，不将其当作当前版本的完整测试结果。

## 本次验收记录（2026-10-21）

- 8/8 场景通过原生 CLI 的 build-oracle → fresh replay → evaluate，共 199 个参考步骤。
- 新增的作物、布局、物理、多场运行及场景反例测试：66/66 通过。
- 含可选 WOFOST 的完整测试：364 通过、1 个既有失败。失败为 `tests/test_llm_runtime.py::test_a2a_trace_file_excludes_reasoning_without_mutating_sdk_history`，涉及 A2A SDK 消息序列化；用改动前 HEAD `5d6bda72439a3f6fce30c79eb62ca636ed952efa` 的源码与相同测试也能复现。本次未修改用户原有的 runtime 改动或该测试。
- [8 场景验收汇总](../validation_runs/diverse_oracles/summary.json)；[完整测试日志](../validation_runs/diverse_oracles/pytest-full.log)。这些本地运行产物不纳入版本化 oracle。
- 玉米／水稻收储参考结果为 735 kg + 675 kg = 1410 kg。报告的 `recovered_grain_kg_total` 统计本场粮仓、拖车和收割机粮箱，口径为操作库存 kg；快照任务没有完整生物产量历史时，物理产量字段为 `null`，不能将其解释成零产量。
