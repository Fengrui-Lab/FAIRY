# 一个场景统筹多个农场的全季管理

全季入口是 **`scenario_multi_crop_full_season_mixed`**，定义在独立文件 [scenario_multi_crop_full_season_mixed.py](../fairy/scenarios/farm_world_diverse/scenario_multi_crop_full_season_mixed.py)：同一个 agent、同一个场景、同一条仿真时间线，同时管理大豆、玉米和旱直播水稻三个农场，直到每个农场都完成收获入仓。

所有农场从未整地、未播种的土地开始。整地、装肥、施基肥、起垄、装种、播种、出苗、生长、干预、成熟、收割、卸粮、烘干和入库均通过真实工具和逐日物理引擎发生。场景运行期间没有设置成熟快照，也没有直接给粮仓写入参考产量。

## 先运行这个场景

无需 LLM 密钥即可导出策略并在全新初态中回放、验收：

```bash
PYTHONPATH=. uv run python -m fairy.cli \
  -s scenario_multi_crop_full_season_mixed \
  --build-oracle --replay --evaluate \
  --output-dir validation_runs/multi_farm_full_season_demo
```

检查输出目录的 `scenario_multi_crop_full_season_mixed.run_report.json`，必须同时看到：

- `status=completed`；
- `evaluation.validation.success=true`；
- `evaluation.validation.metadata.farms` 中，三个农场各自的出苗、成熟、收获垄数都等于本场总垄数；
- 每个农场有正的粮仓库存，且与按其实际面积计算的物理回收粮食一致。

实际 agent 可使用相同场景 ID：

```bash
PYTHONPATH=. uv run python -m fairy.cli \
  -s scenario_multi_crop_full_season_mixed \
  --agent --controller farm_baseline_react \
  --provider deepseek --model deepseek-chat \
  --max-tool-calls 1800 --timeout-seconds 7200 \
  --output-dir validation_runs/multi_farm_full_season_agent
```

这里验证的是离线参考策略和回放；没有据此声称真实 LLM 已达到相同成功率。全季操作步骤明显多于阶段任务，运行限制需容纳长期管理；工具入口不会按农场数复制。

## 一个场景里有哪些农场

默认混合作物配置的耕作面积如下。面积直接由几何参数计算，不是另填一个农场面积：

| farm_id / 显示名 | 作物 | 垄数 × 垄长 × 垄宽 | 耕作面积 | 公顷 / 亩 | 播种窗口（季节日） |
|---|---|---|---:|---|---|
| soy / Soy | 大豆 | 5 × 120 m × 1.1 m | 660 m² | 0.066 ha / 0.99 亩 | 0–5 |
| maize / Maize | 玉米 | 7 × 140 m × 0.75 m | 735 m² | 0.0735 ha / 1.1025 亩 | 7–12 |
| rice / Rice | 旱直播水稻 | 9 × 100 m × 1.0 m | 900 m² | 0.09 ha / 1.35 亩 | 14–19 |
| 合计 | 三种作物 | 21 垄 | 2295 m² | 0.2295 ha / 3.4425 亩 | — |

计算规则为 `耕作面积 m² = 垄数 × 每垄长度 m × 每垄宽度 m`，`1 ha = 10000 m²`，`1 亩 = 2000/3 m²`。例如大豆场总宽度是 `5 × 1.1 = 5.5 m`，整体耕作矩形为 `120 m × 5.5 m`。

**5 / 7 / 9 垄是此前为缩短集成回放、覆盖不同垄数和尾批作业而选的小型测试配置，没有真实农业经营规模的论证。** 它们对应三个小型试验田，不能据此称为大型农场。当前模型中，一个 farm 只有这一块耕作矩形；没有“农场下包含多块田”的层级，也没有把道路、沟渠、田埂或设施面积计入总面积。本次整理代码保留这些测试尺寸，面积随几何参数自动变化。

播种参数来自各作物的 profile：大豆 `STANDARD / 4 cm / 8 cm`，玉米 `MAIZE_STANDARD / 5 cm / 20 cm`，水稻 `RICE_STANDARD / 2 cm / 10 cm`，依次为种子、播深和株距。

季节第 0 日为 2026-05-01。各农场的土地、作物、天气数据、仓库物资、水肥额度、拖车与粮仓独立。八个全季场景都显式声明三个可跨场服务的设备资产：`tractor_shared`、`robot_shared`、`drone_shared`，每项资产只有一份油箱、电池、载荷或充电状态。公共时钟下，在 Maize 灌溉三小时，Soy 与 Rice 也经历三小时的土壤与作物演化。Soy 完成入库后，场景继续管理尚未收获的 Maize 和 Rice。

初始营养指数为 0.68，使全季追肥有实际作用。每场默认灌溉额度为全场等效 300 mm、肥料额度 500 kg。播种窗口包含起止日期，由工具约束和验收器共同检查。

默认肥料额度、100000 kg 仓容和 20000 kg/日烘干能力是测试用的宽松资源上限，没有随这些小田块的面积按比例标定。调整田块规模时，应同时审查该农场的 `resources`，不能把这些值当作每公顷推荐量。

这些是确定性的测试天气：日均温约 26°C、辐射 15 MJ/m²/日、平时降雨 2 mm/日，每七天安排一个干燥作业日；播种窗口附近、局地干旱事件、局地降雨事件及季末干燥期另行覆盖。它们用于验证管理行为，并非真实地区气候或农业生产建议。

## 共享工具、农场状态与设备资产

`FarmSite` 保存土地状态和关联关系，不规定每个农场独占七套 App。场景分别声明农场、资产及其可服务范围；`FarmRuntime` 连接公开服务和内部状态，通过 `runtime_participants` 显式接入 Engine 的时间推进。公开服务是 `World`、`Farm`、`Weather`、`Sensor`、`FieldOps`、`Tractor`、`Drone`、`Robot`，另有场景级任务接口和 `SystemApp`。

| 目标 | 参数与归属 | 调用示例 |
|---|---|---|
| 农场观测、天气和操作 | `farm_id`；垄号只在该场内部有效 | `Farm__get_farm_overview(farm_id="maize")` |
| 农机田间作业 | `farm_id` + `asset_id` | `Tractor__plant_seeds(farm_id="maize", asset_id="tractor_shared", start_ridge=0, end_ridge=3, depth_cm=5, seed_spacing_cm=20)` |
| 设备自身状态、充电、挂载 | `asset_id`；不虚构设备属于某个农场 | `Robot__check_status(asset_id="robot_shared")` |
| 单个探头 | 目录给出的全局 `sensor_id` | 先从目录取得实际探头 ID，再调用单探头读取工具 |
| 载荷返还 | `asset_id`；按已记录来源返还 | `Tractor__return_supplies(asset_id="tractor_shared")` |

Agent 先通过 `World__describe_environment()` 取得实际农场、垄范围、资产、站点、探头和绑定关系，再用 `World__get_capabilities(farm_id="maize", asset_id="tractor_shared")` 查询该作物的播种／收获约束和设备容量。实时油量、电量、充电情况仍从设备状态工具读取；天气和土壤从对应公开观测工具读取。

发给模型的 function schema 与实际执行来自同一个工具契约和注册表，包含参数类型、必填项、默认值、说明、单位和合法目标 ID。静态 schema 不能代替目标组合和实时作业条件检查：无效 ID、越界垄、不适配设备或载荷来源冲突会由同一执行入口拒绝。Agent、动态 Oracle、捕获事件和 Replay 都调用这一入口。返回结果统一提供 `ok`、`tool`、目标标识、执行前后时间、`data` 和 `error`；策略读取 `data`，轨迹保留原始结果。

默认混合全季场景实际向 FARM Agent 提供 **47 个 function schema**；包含仅供环境注入任务的 `AgentUserInterface__send_message_to_agent` 时共注册 48 个工具。增加农场扩大目标目录与 ID 选择范围，不复制一套工具。这个计数对应默认直接工具模式；启用 A2A 后专家入口会改变主 Agent 的目录，World 发现入口仍直接可用。

共享 Tractor 的剩余种子、肥料和药剂必须先通过 `return_supplies` 退回记录的来源仓库，才能给另一场装料作业；粮食不能用该工具退还，须先在来源场 `unload_grain`。切换目标不会重置油量、料斗、电池、挂载或充电进度。当前作业仍串行，不模拟跨场道路、运输耗时或成本。

设计说明见 [共享工具与资产设计](multi-farm-shared-tools-design.md)，公开函数定义见 [services/](../fairy/apps/farm_world/services/)，平台接线见 [runtime.py](../fairy/apps/farm_world/runtime.py)、[shared_apps.py](../fairy/apps/farm_world/shared_apps.py) 和 [工具执行契约](../fairy/tool_execution.py)。八类服务的51个完整方法直接声明目标、业务参数、类型、默认值及说明；注册器不加工旧 App 的业务签名。框架依据见 [官方研究](tool-framework-research.md)。

## 全季 Oracle 如何决策

实现直接位于各场景自己的文件。主混合场景在 [scenario_multi_crop_full_season_mixed.py](../fairy/scenarios/farm_world_diverse/scenario_multi_crop_full_season_mixed.py) 中，先读 `build_events_flow()` 如何形成完整事件图，再读 `oracle_solution()` 的两种模式。动态管理判断在本文件的 `_SeasonManager.run()` 及其 `prepare()`、`sow()`、`inspect()`、`care()`、`ready_to_harvest()`、`harvest()` 中。

实际生命周期如下：

1. `setup()` 先调用 `init_and_populate_apps()`，创建未整地、未播种的原场景及其所有农场，再自动调用本地 `build_events_flow()`。
2. `build_events_flow()` 先 capture `season_briefing`，把完整任务交给 agent。随后创建独立的 `oracle_clone()`，让本地 `_SeasonManager` 根据公开工具观测动态推演完整季节。
3. 将副本实际产生的每个规范工具步骤及 `farm_id`／`asset_id` 参数，重新 capture 为绑定原场景共享服务的事件。图包含整地、播种、全季观测、照管、载荷返还和收储，保留依赖关系、`phase`、`oracle_reason` 及作业耗时延迟。
4. 构建完成后缓存事件图。构图只推进独立副本，原场景的时钟、库存和作物保持初态；内部推演副本有私有标记避免递归构图，普通公开 clone 仍会构建完整图。构建结束还会恢复事件注册器的全局兜底列表，避免污染其他场景。

自定义条件下若参考策略无法走完整季，`event_flow_error` 会记录原因，事件图仅保留真实推演前缀。场景仍能初始化供 agent 接管；`oracle_solution(False)` 会明确拒绝导出该不完整图。八个默认场景均可构建完整事件图。

`oracle_solution(run_oracle=False)` 从这份事件图导出 `Workflow`，供保存和新初态回放；它不在原场景执行田间操作。`oracle_solution(run_oracle=True)` 则直接在当前场景运行本地 `_SeasonManager`，根据实时观测持续决策并记录实际结果。CLI 的 `--build-oracle --replay --evaluate` 对应先导出、再在新初态回放和验收。运行 `--agent` 时，模型读取 briefing 后自行管理，事件图中的参考操作不会替模型执行。

| 阶段 | 每个农场的观测与行动 | 回到其他农场的规则 |
|---|---|---|
| 初始巡场 | 读本场 overview、本站天气和预报、地表与根区水分、冠层，以及所选共享农机的状态 | 先确认全部农场的空白初态、物资和设备资产 |
| 整地与播种 | 到本场播种窗口后，挂平地机→平整→装基肥→施基肥→换起垄机→起垄；按作物装种并分最多四垄一趟播种，尾趟自动收窄 | 尚未开放播种窗口的场继续等待，但其土壤继续演化 |
| 出苗检查 | 复查每垄阶段、土温与水分、冠层；地面机器人检查出苗与群体状况 | 每个仍在生长的农场有自己的下一次巡检时间 |
| 营养与水分 | 低根区水分才定向灌溉；地面叶色营养诊断显示缺乏且未确认病虫害时，检查本场额度并追肥 | 已灌溉后等待响应，不在交付尚未完成时重复灌水 |
| 病虫草监测 | 综合冠层与地面检测，按目标、置信度、天气及上次处理时间决定是否施药或机械除草 | 不把其他农场的诊断、雨情或物资当成本场证据 |
| 成熟与收获窗口 | 本场所有待收垄达到该作物成熟阶段后，检查实际籽粒水分、本站降雨及土壤作业条件；等待时改为按日复查 | 某场等待收获不强迫其他生长期农场重复每日全套巡检；它们仍按各自周期管理 |
| 分批收储 | 挂收割机→四垄以内收割→本场卸粮→当前批次烘干至 13%→入本场粮仓 | 每场独立关账；已完成场不再重复执行田间管理 |
| 切换资产目标 | Tractor 为另一场作业前，显式将残留供料退回记录的来源；粮食先卸回来源场 | 设备状态持续保留，不能因切场恢复油量或电量 |
| 结束 | 最后逐场检查垄、粮箱、拖车、粮仓与物料账 | 只有所有农场均完成才报告整个场景成功 |

这里新增了明确命名的 `Sensor__read_root_zone_sensors`：它模拟独立的根区探头，给出分区平均值并加入 ±0.005 VWC 噪声。原有 5 cm 地表探头保持其原本含义。`Robot__inspect_crop_health` 的叶色营养诊断是带噪声的分类观测；未出苗时返回 `unavailable`，不会把隐藏的营养指数直接交给策略。

参考策略只读取 agent 也能获取的工具结果来判断状态。田块几何、作物配置及播种窗口是公开任务输入。下一次访问时间取所有未完成农场的最早到期日，公共时钟推进会同时更新所有场站。

每个版本化 oracle JSON 步骤包含 `tool_name`、`tool_args`、`depends_on`、`content.phase` 和 `content.oracle_reason`；真实工具返回值及执行时间保存在 replay/runtime log。oracle 是满足任务和物理约束的参考管理策略，不声称是数学上的产量最优解。

共享工具轨迹与同名 manifest sidecar 一起保存：例如 `oracle.json` 配套 `oracle.manifest.json`。sidecar 记录格式版本、工具目录版本、场景配置指纹与 workflow 内容指纹；场景指纹包含农场初态、资产、绑定、后端、期限和巡检要求。Replay 在执行目标工具前检查版本、配置、参数及依赖。复制或提交参考答案时必须同时保留两份文件；旧前缀轨迹需要显式迁移，不能把它默认为当前共享工具轨迹。

## 4 个多农场全季 + 4 个多作物全季

以下每一行本身都是一个管理多个农场、覆盖完整季节的场景。**一个场景对应一个 `.py` 文件，文件名与 scenario ID 相同。**

| 组别 | scenario_id | 全季配置 | 场景源码 | 完整 Oracle |
|---|---|---|---|---|
| 多农场 1 | `scenario_multi_farm_full_season` | 两个大豆场，错开一周播种 | [Python](../fairy/scenarios/farm_world_diverse/scenario_multi_farm_full_season.py) | [JSON](../configs/oracles/full_season/scenario_multi_farm_full_season.json) |
| 多农场 2 | `scenario_multi_farm_full_season_drought_priority` | 两个大豆场，其中一场第 40–68 天干旱 | [Python](../fairy/scenarios/farm_world_diverse/scenario_multi_farm_full_season_drought_priority.py) | [JSON](../configs/oracles/full_season/scenario_multi_farm_full_season_drought_priority.json) |
| 多农场 3 | `scenario_multi_farm_full_season_staggered_windows` | 三个大豆场，垄数与播种日期不同 | [Python](../fairy/scenarios/farm_world_diverse/scenario_multi_farm_full_season_staggered_windows.py) | [JSON](../configs/oracles/full_season/scenario_multi_farm_full_season_staggered_windows.json) |
| 多农场 4 | `scenario_multi_farm_full_season_weather_risk` | 两场独立收获判断，其中一场第 92–108 天连雨 | [Python](../fairy/scenarios/farm_world_diverse/scenario_multi_farm_full_season_weather_risk.py) | [JSON](../configs/oracles/full_season/scenario_multi_farm_full_season_weather_risk.json) |
| 多作物 1 | `scenario_multi_crop_full_season_maize` | 两个玉米场，错期播种、局地干旱 | [Python](../fairy/scenarios/farm_world_diverse/scenario_multi_crop_full_season_maize.py) | [JSON](../configs/oracles/full_season/scenario_multi_crop_full_season_maize.json) |
| 多作物 2 | `scenario_multi_crop_full_season_rice` | 两个旱直播水稻场，独立水肥管理 | [Python](../fairy/scenarios/farm_world_diverse/scenario_multi_crop_full_season_rice.py) | [JSON](../configs/oracles/full_season/scenario_multi_crop_full_season_rice.json) |
| 多作物 3 | `scenario_multi_crop_full_season_mixed` | 一个大豆场、一个玉米场、一个水稻场 | [Python](../fairy/scenarios/farm_world_diverse/scenario_multi_crop_full_season_mixed.py) | [JSON](../configs/oracles/full_season/scenario_multi_crop_full_season_mixed.json) |
| 多作物 4 | `scenario_multi_crop_full_season_staggered` | 三作物错期，叠加分场干旱与收获降雨 | [Python](../fairy/scenarios/farm_world_diverse/scenario_multi_crop_full_season_staggered.py) | [JSON](../configs/oracles/full_season/scenario_multi_crop_full_season_staggered.json) |

上一批 [阶段任务](multi-farm-multi-crop-oracles.md) 继续用于检查单项操作；本页的八个全季场景有单独的 ID、oracle 和验证规则。

批量生成并验收本页八个全季场景：

```bash
PYTHONPATH=. uv run python scripts/validate_diverse_oracles.py \
  --suite full-season \
  --references-dir configs/oracles/full_season
```

汇总在 [summary.json](../validation_runs/full_season_oracles/summary.json)，其中给出各场真实播种、出苗、成熟、收获日期、入仓量、水肥消耗、巡检日期和最长巡检间隔。步骤数会随带噪声诊断而有少量变化。

## 场景文件怎么读、怎么改

主混合场景入口是 [scenario_multi_crop_full_season_mixed.py](../fairy/scenarios/farm_world_diverse/scenario_multi_crop_full_season_mixed.py)，文件里定义 `ScenarioMultiCropFullSeasonMixed` 及其本地配置类型、初始化、`build_events_flow()`、Oracle 和验收实现。**打开这一个文件，就能从输入读到事件图、运行与验收。** 其他七个场景分别在上表链接的独立文件中修改。

推荐按以下顺序阅读同一个场景文件：

1. 本地配置类型与解析：`FieldLayout`、`SeasonSettings`、`SeasonFarmPlan` 等定义字段、单位和校验，`parse_farm_config()` 处理 CLI 输入。
2. 场景类参数：`season_settings` 声明开始日期、期限和巡检间隔；`management_objectives` 列出完成目标；`farm_plans` 逐场展开几何、作物、播种窗口，以及各自的 `SoilInitialState(...)`、`WeatherSchedule(...)`、`FarmResources(...)`。
3. 初始化和天气：`__post_init__()` 解析参数与公共时钟起点；`_create_fleet()` 分别创建农场、显式 `AssetSpec`、共享服务和 runtime 参与者；`_configure_soil()`、`_configure_limits()`、`_configure_weather()`、`_daily_rain_mm()` 展开每场初态和逐日天气，完成后再冻结目录和配置指纹。
4. 事件图：`build_events_flow()` capture 任务 briefing，在独立副本推演全季，再 capture 为绑定本场景共享服务的完整工具 DAG；查看显式目标 ID、依赖、操作延迟和步骤说明。
5. Oracle：`oracle_solution(False)` 导出事件图，`oracle_solution(True)` 运行本地 `_SeasonManager.run()`；完整动态管理循环和动作判断均在这个本地管理器中。
6. 验收：从 `validate()` 看如何逐场检查播种、生长、巡检、照管、收获与物料账。

每个场景文件直接继承基础 `Scenario`，本地包含场景实现，不引用其他全季场景或 `full_season_*` 共享实现。所有输入都使用具名字段原地展开，包括与其他农场相同的值；配置对象不可变，资源额度逐场创建和扣减。作物生理、农机及工具行为仍使用底层仿真组件。

| 想改什么 | 改哪个字段 | 单位与含义 |
|---|---|---|
| 有几个农场 | `farm_plans` 的项数 | 一项就是一个独立农场 |
| 农场标识与显示名 | `farm_id`、`tool_prefix` | `farm_id="soy"` 是公开目标；`tool_prefix="Soy"` 仅保留显示与旧内部句柄兼容，不生成公开工具前缀 |
| 设备数量与服务范围 | `_create_fleet()` 中的 `AssetSpec(...)` | 显式资产 ID、种类与允许服务的 farm IDs；八个默认全季场景均共享三项资产 |
| 作物 | `crop_type` | `soybean`、`maize` 或 `rice` |
| 面积 | `layout.ridge_count`、`ridge_length_m`、`ridge_width_m` | 垄数、每垄长度 m、每垄宽度 m；面积自动计算 |
| 播种时间 | `planting_start_day`、`planting_window_days` | 从公共第 0 天开始；开始日 7、窗口 6 天表示第 7–12 天 |
| 初始土壤 | `initial_soil` | 含水率、土温、营养及病虫压力 |
| 当地天气与事件 | `weather` | 温度、正常日雨量、当地干旱与收获降雨时段 |
| 本场额度和容量 | `resources` | 全场等效灌溉 mm、肥料 kg、烘干 kg/日、仓储 kg |
| 公共起点、期限与巡检要求 | `season_settings` | 起始日期、UTC 小时、最多模拟天数、巡检间隔天数 |

字段、装配、Oracle 和验收的阅读入口都是相应场景文件。[full_season.py](../fairy/scenarios/farm_world_diverse/full_season.py) 只用于旧导入路径的兼容导出和场景 ID 清单。修改某个场景的条件、目标、初始化、管理策略或验收规则，都在该场景自己的文件中完成。

CLI 支持 `farm_configs`、`season_length_days`、`monitor_interval_days`。以下 JSON 使用同样的具名嵌套字段，替换为两个农场；为了演示配置格式，仍沿用小型测试田的尺寸：

```json
{
  "season_length_days": 190,
  "monitor_interval_days": 7,
  "farm_configs": [
    {
      "farm_id": "east",
      "tool_prefix": "East",
      "crop_type": "maize",
      "layout": {
        "ridge_count": 5,
        "ridge_length_m": 120,
        "ridge_width_m": 0.75
      },
      "planting_start_day": 0,
      "planting_window_days": 6
    },
    {
      "farm_id": "west",
      "tool_prefix": "West",
      "crop_type": "rice",
      "layout": {
        "ridge_count": 9,
        "ridge_length_m": 100,
        "ridge_width_m": 1.0
      },
      "planting_start_day": 14,
      "planting_window_days": 6,
      "weather": {"drought_days": [45, 65]},
      "resources": {
        "irrigation_budget_mm": 300,
        "fertilizer_budget_kg": 500
      }
    }
  ]
}
```

将上面的 JSON 保存为 `custom-season.json` 后运行：

```bash
PYTHONPATH=. uv run python -m fairy.cli \
  -s scenario_multi_crop_full_season_mixed \
  --scenario-kwargs "$(cat custom-season.json)" \
  --build-oracle --replay --evaluate \
  --output-dir validation_runs/custom_full_season
```

最少两个农场，farm ID 与兼容显示名前缀必须唯一。旧 CLI 配置中的 `prefix`、`num_ridges`、`length_m`、`width_m`、`crop`、`plant_day` 等扁平字段继续兼容；新配置建议用上面的嵌套写法。同时填写新旧同义字段但数值冲突时会报错。无需为每种组合复制工具入口；默认共享资产的可服务农场集合按解析后的 `farm_plans` 建立。调整几何、天气、资源、期限或后端后，必须重新生成对应配置的 Oracle 与 manifest。

## 验收要求与失败反例

验收实现就在各场景文件中。主混合场景从 [scenario_multi_crop_full_season_mixed.py](../fairy/scenarios/farm_world_diverse/scenario_multi_crop_full_season_mixed.py) 的 `validate()` 阅读；它逐场检查真实物理历史、工具历史与最终物料账，允许等效管理策略：

- 每个农场初始未整地、未播种；实际执行整地、起垄与覆盖全部本地垄的播种；种子类型和扣库数量正确。
- 每垄都有真实的播种、出苗、成熟、收获日期，正的积温、生物产量和物理回收粮食。
- 在出苗、营养生长、生殖生长、成熟阶段分别有本场观测；生长至收获期间最长巡检间隔不超过设定值加一天的作业容差。
- 出苗后、实际收割前有真实的田间管理；干旱窗口覆盖需要管理的本场垄；水肥使用不超过本场额度。
- 播种、田间干预和收割前有本场近期天气与水分证据；`op_type=TOOL` 不会绕过校验。
- 所有本场垄均已收获；仓储批次来源完整；粮箱与拖车清空；按实际面积计算的回收 kg 与本场粮仓增量相符；入仓水分安全。

测试覆盖空轨迹、只收获、漏管整个农场、跳过整地／田间管理／时间推进／本场观测／烘干／入仓，以及两场总粮食不变但跨场挪粮。即使最终状态正确，删去全季观测过程或只保留稀疏的四个日期，也不能通过。

```bash
PYTHONPATH=. uv run --with pytest python -m pytest -q \
  tests/test_multi_farm_full_season.py \
  tests/test_full_season_physics.py \
  tests/test_season_observations.py
```

## 模型边界

玉米和水稻使用确定性的作物代理参数；水稻为旱直播非淹水模型。WOFOST 仍只支持已有大豆参数。这里验证完整管理链路、长期并行演化和质量守恒，不把未标定的产量解释为实际地区产量预测。

当前每场保留自己的物资与粮仓，三个设备资产共享；供料和粮食保存来源，禁止将带有另一场载荷的 Tractor 直接用于新场作业。实现了未使用供料返还与原场卸粮，没有库存跨场调拨、道路移动、运输时间或经营成本模型。旧单农场 FOS baseline 缓存不适用这批多场全季任务，本页使用按场核算的专用验收器和实际物理结果。

## 显式工具重构后的验收（2026-10-23）

八个全季场景均通过规范工具导出 → 保存 JSON 与 manifest → 从磁盘重新加载 → fresh replay → 逐场验收，见 [共享工具全季汇总](../validation_runs/explicit_tools_full_season/summary.json)。每个场景使用三项共享资产，合计覆盖 19 个农场，模拟时长约 119–152 天。主混合场景的动态 Oracle 也通过同样的全季验收。工具、资产、状态恢复和 manifest 的契约验证见 [共享运行时测试](../tests/test_shared_tools_runtime.py)；这不等于真实 LLM 或真实农业生产的成功率证据。

固定版本参考文件另在全新 Python 进程中逐一加载、回放与验收，**16/16 通过**（8 个全季、8 个阶段任务），见 [独立进程文件回放汇总](../validation_runs/explicit_tools_file_replay/summary.json)。该次验证使用不同的 `PYTHONHASHSEED`，仍与导出时的工具版本和初始配置指纹匹配；每份参考 JSON 都有同名 manifest。

默认混合场景用 1118 个参考步骤完成约 145.015 个模拟日，21 垄全部真实出苗、成熟、收获并入仓。当前保存文件的独立回放结果如下，完整过程和资源账见 [运行报告](../validation_runs/explicit_tools_file_replay/scenario_multi_crop_full_season_mixed/scenario_multi_crop_full_season_mixed.run_report.json)。

| 农场 | 播种日期 | 成熟日期 | 收获日期 | 入仓粮食 |
| --- | --- | --- | --- | ---: |
| soy | 2026-05-01 | 2026-07-11 | 2026-08-21 | 94.76 kg |
| maize | 2026-05-08 | 2026-08-26–27 | 2026-09-23 | 349.22 kg |
| rice | 2026-05-15 | 2026-08-13 | 2026-09-20 | 290.54 kg |

[实际 FARM Agent 工具 schema](../validation_runs/explicit_tools_validation/mixed.agent_tool_schemas.json) 保存当前 47 个接口；[公开环境目录](../validation_runs/explicit_tools_validation/mixed.public_environment.json) 保存对应的农场、几何、资产、站点、探头、版本及响应协议。两者来自真实 Agent 构造与运行时注册表，没有另写工具清单。

测试覆盖 635 项独立用例：全量 633 项通过，采集后新增的两个签名拒绝负例在 13 项接口专项中通过。通过 PCSE 官方 `user_settings` 为真实 CLI 子进程配置临时日志／缓存，没有替换引擎、跳过测试或修改 HOME。见 [全量日志](../validation_runs/explicit_tools_validation/pytest.log)、[专项日志](../validation_runs/explicit_tools_validation/pytest-explicit.log) 和 [本次验证汇总](../validation_runs/explicit_tools_validation/summary.json)。这次还验证了低电量部分覆盖、内部句柄禁止发布工具目录，以及非物理模式的 Robot 杂草信息明确不可用。

## 保存的全季运行样例（2026-10-21）

本节及下一节是共享工具迁移前的历史记录，用于保留当时的模型与事件流证据；当前规范工具轨迹和版本应以上面的共享工具汇总为准。

[保存的混合场景 oracle 再次独立回放报告](../validation_runs/full_season_oracles/saved_mixed_replay/scenario_multi_crop_full_season_mixed.run_report.json) 显示约 145.015 个模拟日完成，21 垄全部真实出苗、成熟、收获并入仓：

| 农场 | 播种日期 | 实际成熟日期 | 实际收获日期 | 入仓粮食 |
|---|---|---|---|---:|
| Soy | 2026-05-01 | 2026-07-11 | 2026-08-21 | 94.76 kg |
| Maize | 2026-05-08 | 2026-08-26–27 | 2026-09-23 | 346.37 kg |
| Rice | 2026-05-15 | 2026-08-13 | 2026-09-20 | 291.27 kg |

Soy 入仓之后，Maize 和 Rice 继续在同一场景中生长和等待本场收获窗口。这些数量来自本次代理模型的实际回放，不是要求其他策略必须精确复现的固定产量目标。

## 完整场景与事件流验收（2026-10-21）

八个场景各自直接继承 `Scenario`。每个文件本地包含配置类型与解析器、全部输入、农场初始化与逐日天气、`build_events_flow()`、完整 Oracle 管理器、完整 `validate()` 及辅助函数。正式场景没有导入其他场景或旧公共全季实现；旧模块只保留兼容入口。

- 八个场景通过事件图导出 → fresh replay → evaluate，**8/8 通过**，见 [事件流回放汇总](../validation_runs/season_event_flows/summary.json)。
- [24 项完整文件边界测试](../tests/test_complete_season_files.py) 验证独立加载与配置兼容；禁止其他场景与旧公共全季模块后，目标文件仍可初始化、克隆，混合场景能完成全季。
- [12 项全季事件流测试](../tests/test_season_event_flows.py) 覆盖八个场景的完整 DAG、幂等与状态隔离，以及混合场景事件直接执行、事件图导出回放、转换器导出回放的完整验收。90 天短季也能初始化，但不完整 Oracle 会明确拒绝导出。
- [8 项通用事件测试](../tests/test_captured_event_workflow.py) 覆盖农场工具前缀、原因元数据及真实执行时钟，保留旧事件行为。
- 完整回归 **505 通过、1 个既有 A2A 日志失败**，见 [完整测试日志](../validation_runs/full_season_oracles/season-event-flows-full-tests.log)。失败为 `tests/test_llm_runtime.py::test_a2a_trace_file_excludes_reasoning_without_mutating_sdk_history`，此前已在原 HEAD 复现。
