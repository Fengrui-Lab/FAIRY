# 多农场共享工具与设备设计

实现说明：共享工具服务、独立设备资产、统一执行契约及场景迁移已经落到代码。本文说明实际责任边界、兼容方式与验收条件；不是待实现接口清单。最终全量测试和固定版本的回放结果以文末证据入口为准，不把局部验证写成全部通过。

当前同一套工具服务操作多个农场，同一项设备资产可以服务多个农场，Agent 获得与执行入口同源的工具信息。农场数量、服务数量和设备数量分别配置，不能由其中一个数量推导其他数量。

2026-10-23 再次重构公开 API：八类服务、51 个平台工具都改为普通 Python 类中的显式方法。`farm_id`、`asset_id`、业务参数、默认值及逐项说明写在真实源代码中；注册器不再扫描旧 App 生成新接口，也不再注入签名、改参数名或拼接旧说明。官方框架对照及取舍见 [工具框架研究](tool-framework-research.md)。

## 本次修改范围

本次修改共享工具入口、目标解析、设备状态归属、工具契约、运行环境接线，以及场景和轨迹的目标身份。

每场库存、拖车、粮仓、水肥额度继续独立。现有作物参数、面积设置、天气和物理公式不重新标定。共享仓储、跨场运粮、GIS、道路运输、劳动力和经济优化另行设计；本次不以工具共享为由加入这些模型。

设备可配置为专用或多场共用。八个默认全季场景各显式声明 `tractor_shared`、`robot_shared`、`drone_shared`，三项资产服务该场景全部农场；八个阶段任务则显式声明逐场专用资产，以保留局地降雨下其他设备不变等任务条件。两种配置使用同一套共享工具服务，不能把“工具入口共享”与“物理设备一定共用”混为一谈。

## 重构前的状态与当前归属

重构前，`FarmSite.from_spec()` 为每场装配七个 App，设备构造器绑定单场，工具通过 App 前缀定位目标。正式多场场景现在使用 `FarmSite.create(..., create_devices=False)` 和 `FarmFleet(..., shared_tools=True, assets=...)`，分别配置土地与资产。旧构造／旧 App 入口仍作为兼容路径保留，不代表新的领域边界。

| 状态或能力 | 新归属 | 不变量 |
| --- | --- | --- |
| 田块几何、作物、土壤、生长、成熟与收获历史 | 农场 | 各农场状态独立 |
| 平地、基肥、起垄完成情况 | 农场经营状态 | 换机器不丢失，换农场不继承 |
| 仓库、拖车、粮仓、水肥额度 | 农场 | 本次保持现有归属 |
| 天气与预报 | 天气站 | 同站可服务多场；不同站数据不混合 |
| 探头分区、读数、噪声流 | 传感器或观测后端 | 访问服务共享不会重建或混合探头状态 |
| 燃油、电量、机具、种箱、肥药箱、粮箱、充电进度 | 设备资产 | 一个 `asset_id` 只有一份状态 |
| 播种、灌溉、查询和巡检等公开入口 | 工具服务 | 每类服务注册一次，目标由参数指定 |
| 公共时间与运行记录 | 场景运行环境 | 所有农场使用同一时间线 |

这些字段的实际处理如下。

- `_completed_prep_ops` 访问目标农场的 `_field_preparation_ops`，换机器不丢失整地进度，换农场不继承另一场进度。
- 有效收割水分上限按目标作物与设备可选上限取较小值，不缓存首个农场的 profile。
- 新共享收割路径将粮食来源保存到 `AssetState.grain_lots`。旧 `FarmWorldApp._pending_bin_grain_*` 字段仍服务旧单场兼容路径；新路径不使用这个农场级待卸粮列表区分多台收割机。
- `_ScopedLog` 为设备操作追加明确的 `farm_id`、`asset_id` 和时间。结果汇总按 `grain_lots` 的来源归场，不用设备最近服务对象猜归属。

设备和服务字段按下表保存。`app_name` 是服务或旧适配器身份，不代替实体 ID。

| 当前字段组 | 保存位置 |
| --- | --- |
| Tractor 的 fuel_tank_l、pesticide_tank_l、fertilizer_spreader_kg、seed_type、seed_hopper、attached_implement | `AssetState(kind="tractor").data` 与 `payload_origin_farm_id` |
| Tractor 的 fungicide tank | `AssetState.data`，显式持久化，不依赖旧 `TractorApp.get_state()` 的字段覆盖 |
| Tractor 的 grain_bin_kg | 资产 grain_lots 的合计，不能与批次账分别随意修改 |
| Tractor 的 grain_bin_max_kg、available_implements | 能力查询读取现有设备容量常量与机具清单；不是全部可由 AssetSpec 任意配置 |
| Tractor 的 harvest_moisture_limit_pct | 资产可选额外上限；实际有效值按目标作物计算 |
| Tractor 的 completed_prep_ops | 农场经营状态 |
| Tractor 的 operation_log | 带 farm_id 和 asset_id 的操作账；资产视图按 asset_id 过滤 |
| Drone 的 description、config | 资产静态配置 |
| Drone 的 battery_pct、charging、charge_session | `AssetState(kind="drone")` |
| Drone 的 mission_log | 带双重身份的操作账 |
| Robot 的 description、battery_pct、charging、charge_session | `AssetSpec` 与 `AssetState(kind="robot")` |
| Robot 的 inspection_log | 带双重身份的操作账 |
| Sensor 的 soil_sensors、canopy_sensors、分区、观测 RNG | 对应探头／农场观测后端 |
| FieldOps 的 irrigation_log、manual_spray_log | 按 farm_id 归属的操作账 |
| App 的 time_manager 引用 | 运行环境统一绑定，不在每个实体中复制时钟 |

资产快照依据领域状态模型序列化，而不是直接拼接旧 App 的 get_state；否则旧接口遗漏的字段会在迁移中继续丢失。

## 实体与运行环境

`FarmRuntime` 管理农场、站点、观测后端、资产、静态关联和操作记录。它与公开 App 列表分离，内部状态载体不会因为 Engine 需要发现它而自动暴露给 Agent。

新共享路径的 `FarmSite` 保存农场身份、领域状态及站点和探头引用，不实例化每场专属的 Tractor、Drone、Robot。`site.tractor` 等内部兼容句柄由 runtime 根据资产与绑定提供无状态操作视图，不注册给 Agent。多个同类候选资产存在时，内部默认句柄要求明确绑定；公开工具始终明确传 `asset_id`。

| 注册项 | 必需信息 |
| --- | --- |
| farm | 唯一 `farm_id`、几何、作物、初态、窗口、额度、站点与探头引用 |
| station | 唯一 `station_id`、站点数据和天气安排 |
| sensor backend | 唯一 ID、所属田块、覆盖范围、观测配置和随机状态 |
| asset | 唯一 `asset_id`、类型、能力、初始设备状态、允许服务的农场集合 |
| service | 固定服务名、公开工具集合和契约 |

注册时检查农场、资产、站点和绑定引用，未知或冲突身份拒绝。共享站点的农场必须使用相同气象安排；在初始化完成后的 `freeze()` 比较规范 forcing 配置及初态，冲突拒绝，不能由最后写入者覆盖。

共享站点负责气象。旧 `WeatherApp` 的 `_avg_soil_vwc` 与通行判断仍保留兼容，但新设备操作使用 `FarmWeatherView(station, farm)`：气象来自站点，通行性取当前农场土壤，沿用已有阈值。同一站点服务一干一湿两场时，通行结论可以不同；一个农场不能把自己的土壤平均值写进共享气象。

同站 forcing 采用单一规范来源与按日期缓存的完整物理输入；`FarmWeatherView.daily_inputs(day)` 经 runtime 提供这些输入，受管理的物理编排路径优先消费它们。站点展示与预报也由同一气象来源更新，避免出现工具观测下雨而物理仍消费本场另一份干旱 generator。每日最小／最大温度等原生输入精度保留在规范输入中。forcing 配置、随机流和缓存属于站点状态与快照的一部分。

同站输入一致性与完整初态指纹是最终回归的独立验收项；本节说明已确认的实现约束，不据此提前声明其最终测试通过。

本次不加入设备空间位置与转场时间模型。允许服务的农场集合表示授权和兼容关系，不表示设备真实地理位置；跨场目标选择不能被描述为已经模拟了运输。执行仍串行，充电等跨时间状态按同一资产保存。

设备状态查询展示当前载荷、来源、剩余量、机具、充电情况和最近作业目标。最近作业目标仅是历史信息，不作为下一次调用的隐式目标。

## 操作上下文与领域实现复用

共享公开方法转交名称与参数，由 `ToolExecutor` 和 runtime resolver 检查身份、关联并构造冻结的 `OperationContext(farm, weather, asset, clock, recorder)`。目标引用在单次操作中固定；资产状态由上下文指向唯一 `AssetState`。

`operations.py` 明确定义 `EquipmentOperations`、`TractorOperations`、`DroneOperations` 和 `RobotOperations`。冻结的 `OperationContext` 标注农场、天气协议、资产、公共时钟和记录器类型。`operation_view(context)` 只按资产种类选择这三个已声明的类，不再创建动态类。

设备类通过普通、逐项可读的 property 把状态访问映射到资产或农场，没有 `__getattribute__`／`__setattr__` 通用拦截器。固定 dispatch 表明确列出复用的 `TractorApp.plant_seeds`、`DroneApp.fly_survey` 等原领域方法；`private_tool_execution()` 控制装饰器绕过内部重复 gate／capture，操作层不再使用 `inspect.unwrap()` 寻找方法体。这些类仍通过普通继承复用现有农业规则和内部辅助方法，尚未把所有农业算法重写成独立领域函数。

| 访问 | 视图实际解析 |
| --- | --- |
| `_farm_world_app` / `_weather_app` | 本次冻结上下文中的农场和 `FarmWeatherView` |
| 油箱、种箱、肥药箱、粮箱、电池、充电字段 | 唯一资产的 `data` |
| `_completed_prep_ops` | 目标农场的 `_field_preparation_ops` |
| `_harvest_moisture_limit_pct` | 目标作物上限与资产明确上限的较小值 |
| 设备操作日志 | 资产日志，并自动追加当前 farm／asset 身份 |
| `time_manager` | runtime 公共时钟 |

操作对象不运行旧设备构造器，不复制设备状态，不临时改写全局 `_farm_world_app`／`_weather_app` 再恢复。目标、身份、天气与时钟 property 不允许重新绑定。内部兼容句柄既不能被 capture，也不能通过 `get_tools()` 注册为 Agent 工具；这两个入口明确报错，要求使用共享公开服务。普通内部 Python 对象不是通用的不可变容器，不承诺禁止任意自定义属性。

资产状态查询的上下文没有农场，不自动补成最近作业农场。`return_supplies` 例外地从记录的载荷来源解析来源农场；卸粮则由显式 `farm_id` 校验来源。最近服务对象仅是历史信息。

旧单场兼容入口的 gate 位于 `fairy/utils/type_utils.py`。它以旧 App 已有绑定构造 `_LegacyContext`，经相同 `ToolExecutor` 基础设施做参数检查和回执记录，再调用原领域方法；它没有伪装成新的资产／农场注册表。兼容 gate 返回旧方法的原始 Python 返回值，包括原有警告与错误字典；原方法抛异常时重新抛出原异常及 traceback。不能宣称旧入口已统一返回新 envelope。

旧方法返回拒绝字典时，兼容回执保守记录 `stage="execution"`、`partial_effects="unknown"`，因为 gate 无法仅凭旧错误字典证明完全未修改状态。新共享私有 handler 调旧领域方法时，通过执行上下文标记避免再次进入兼容 gate 或重复 capture，领域方法体只执行一次。

## 共享设备的载荷规则

首版采用单一来源规则：田间载荷具有来源农场，有剩余种子、肥料、药剂或粮食时，不允许该设备对另一个农场执行目标操作。状态查询和充电不要求目标农场。

| 行为 | 规则 |
| --- | --- |
| 装种、装肥、装药 | 扣来源场库存，登记物料种类、单位、实际数量和来源；不能混入另一来源 |
| 田间消耗 | 消耗本资产载荷，按实际目标登记操作和额度；目标必须满足来源约束 |
| 退回剩余种肥药 | `Tractor__return_supplies(asset_id)` 将实际剩余量退回记录的来源场；不退回已使用物料、额度或历史 |
| 收割 | 资产粮箱保存批次：来源场、作物、垄 ID、kg、含水率和收割时间 |
| 卸粮 | `Tractor__unload_grain(farm_id, asset_id)` 只能卸到来源场；只转移本资产批次，转移后移除对应批次 |
| 补油 | 从明确指定农场库存补给，记录来源；油量属于资产，可跨场继续消耗，不因换场重新扣一次库存 |
| 换目标 | 田间载荷满足切换条件后，显式指定新目标；油、电、机具和充电状态连续 |

返还工具是共享资产可用性的必要组成部分，不能让少量剩余肥药永久阻止换场。粮食不作为普通物资返还，必须走卸粮和后续收储链路。

运行记录按物料流核对守恒，不再把“仓库减少”等同于“全部已施用”。保存恢复保留来源、剩余载荷和粮食批次。

初始非空种、肥、药载荷必须声明来源，初始粮食还必须声明完整批次。载荷作为初始资产物料计入初始总账，不再从已声明的仓库库存重复扣除。来源缺失、不存在或数量与批次不符的配置及快照拒绝。返还成功后清除对应剩余载荷，重复返还不能增加库存。

补油也是指定来源农场的操作，服从非空田间载荷的跨场限制；它不构成隐含例外。初始油量作为资产初始禀赋计账，后续补油才扣明确来源的仓库。

新路径的有效收割水分上限取目标作物上限与设备明确上限的较小值；设备未设置额外上限时采用目标作物上限。不能初始化为首个农场上限后一直沿用。旧单场接口显式设置的历史覆盖规则在兼容契约中声明，不能悄悄带入新共享目录。

## 公开工具接口

共享名称不随农场数量增长。操作仍按明确方法拆分，不提供把任意字符串动作塞入字典的万能执行工具。

| 工具示例 | 目标参数 |
| --- | --- |
| `World__describe_environment()` | 无，返回公开结构 |
| `World__get_capabilities(farm_id, asset_id)` | 指定农场与可选资产，返回真实静态约束及关联 |
| `Farm__get_farm_overview(farm_id)` | 农场 |
| `Farm__get_ridge_range_state(farm_id, start, end)` | 农场与本地垄范围 |
| `Weather__get_current_weather(farm_id)` | 按农场关联查站点，结果包含站点 ID |
| `Sensor__read_root_zone_sensors(farm_id)` | 农场，结果包含探头与覆盖范围 |
| `Tractor__get_status(asset_id)` | 设备 |
| `Tractor__load_seeds(farm_id, asset_id, seed_type, count)` | 来源农场与设备 |
| `Tractor__plant_seeds(farm_id, asset_id, start_ridge, end_ridge, depth_cm, seed_spacing_cm)` | 目标农场与设备 |
| `Tractor__harvest(farm_id, asset_id, start_ridge, end_ridge)` | 目标农场与设备 |
| `Tractor__return_supplies(asset_id)` | 设备，来源由载荷记录确定 |
| `Tractor__unload_grain(farm_id, asset_id)` | 来源农场与设备 |
| `FieldOps__irrigate(farm_id, start, end, hours)` | 农场；保留现有灌溉模型与本场额度 |
| `Robot__inspect_crop_health(farm_id, asset_id, start_ridge, end_ridge)` | 目标农场与设备 |

上表冻结目标身份规则；全部现有公开方法的迁移表见文末。未在场景 allowlist 中的规范工具不会因为平台支持它而自动公开。

垄号始终是指定农场的本地编号，范围包含两端。播深和株距明确单位为 cm，保持必填，不在共享入口设置暗含大豆的默认值。

## 工具契约与 Agent 信息

`services/` 按 World、Farm、Weather、Sensor、FieldOps、Tractor、Drone、Robot 各写一个普通服务类。每个方法具备完整签名、`Args`、`Returns`，以及成功条件、耗时、资源变化和部分完成等必要说明。单位、数值下界和实体类别使用 `Annotated[..., ToolParameter(...)]` 声明；`@service_tool` 明确读写类型和 executor 消费的路由字段。

`shared_apps.py` 只实例化固定的服务类，按场景 allowlist 选择已声明方法，并把已经存在的实体字段枚举收窄到当前世界的 ID。它不能新增／重命名参数、修改默认值、修改说明或从旧 App 发现新的业务 API。参数 Schema 由这份真实声明编译，注册为 `ToolContract`。`SharedFarmService.get_tools()` 将注册契约投影为 `SharedAppTool`；`build_toolset()` 同时生成模型 Schema 与同名 callable map。

注册时会拒绝人工 `__signature__` 覆盖、公开变参、实际函数参数与声明不一致、缺失／残留的 Args 项、无类型参数及缺失 Returns。每个参数还必须有非空说明。此类检查保证结构不漂移，无法证明任意自然语言说明都真实；部分覆盖、电量、状态归属、返回字段仍需行为测试。

| 当前契约字段 | 实际内容与限制 |
| --- | --- |
| `name`、`description` | 固定工具名称和用途 |
| `parameters_schema` | 类型、必填、实际默认值、说明、单位、范围、枚举和未知参数拒绝 |
| `operation_type`、`routing_parameters` | 读写属性与 executor 消费的身份参数 |
| `metadata` | 服务、方法、单位和响应协议等扩展信息；没有独立完整的声明式前置条件／effects 规则库 |
| `result_schema`、`response_format` | 当前共享农业工具校验统一 envelope；`data` 是异构业务对象，没有逐工具完整的业务字段 schema |
| `semantic_version` | 当前显式语义版本；目录签名不自动分析 Python 源码变化，行为变化仍需维护契约版本 |
| registry 私有 handler | 对应服务的领域委托，不是公开入口本身 |

契约区分实体字段与路由消费字段：`farm_id`、`asset_id` 先构造上下文，再从 handler payload 移除。单探头的 `sensor_id` 既参与解析所属农场，又继续传给观测后端，因此它标注为 sensor 实体，但不放入被移除的 routing 列表。runtime 按服务分成具名的 farm、weather、sensor、field 和 device 适配方法；设备侧采用固定 dispatch 表。

共享 handler 的传输入口仍是 `context, **arguments`；注册器能检查具名 handler 的字段，但这种通用传输函数不能独立证明业务参数完全相等。这里依靠显式公开方法、规范化校验、有限适配器和行为回归共同保证对应，不把注册器描述成形式化的业务正确性证明。

同一注册记录用于共享模型 schema、dispatch、静态参数检查与回放预检。类型转换支持整数、数值、布尔、枚举、Literal、数组、对象和可空类型；不支持的已声明公开类型会报错，不静默降为字符串。未知参数、布尔冒充整数、NaN 和 Infinity 会被拒绝。部分旧接口缺少精细标注的兼容行为不等于新 API 能自动推断全部业务约束。

Schema 包含实际实体 ID 枚举和 `additionalProperties: false`，不统一硬塞某供应商的 strict 标记。农场与资产组合、目标垄上界、播深、种子和成熟条件仍需按当前目标在执行时检查；schema 不把动态油量、天气和成熟状态写成永久成立的静态结论。

Agent 实际获得三类信息：

1. 真正发送给模型的 function schema，参数与实际 callable 同源。
2. briefing 中的实际目录摘要和始终直接可用的 `World__describe_environment`／`World__get_capabilities` 查询；分别给出农场、垄范围、站点、探头、资产及绑定，或目标作物与资产能力。
3. 当前库存、油电、载荷、天气和传感器结果，由状态工具和带执行时间的回执提供。

例如指定无人机巡哪块地，直接看 [DroneService.fly_survey](../fairy/apps/farm_world/services/drone.py)：`fly_survey(farm_id, asset_id, start_ridge, end_ridge)`。`farm_id` 指定当前实现中的田块，垄号只在该场有效；`asset_id` 指定哪台无人机，同一资产跨场时沿用电池和任务历史。说明明确 `data.status` 可能是 `partial`，必须检查 `data.surveyed_ridges`。不由设备最近巡过的农场猜下一次目标。

### 从一次巡田调用读懂边界

以混合场景的 `Drone__fly_survey(farm_id="rice", asset_id="drone_shared", start_ridge=0, end_ridge=5)` 为例：

1. Agent 根据实际 function Schema 生成四个参数。`SharedAppTool` 先检查 JSON 参数，再调用 `DroneService.fly_survey`；内部 Python 策略可以直接调用这个完整方法。
2. 公开方法只将这四个已具名参数交给 `_execute("fly_survey", ...)`。服务不取出水稻状态、不扣电、不猜测目标，也不调用 LLM。
3. `ToolExecutor` 检查类型、枚举、垄范围和资产关联；runtime resolver 找到 `rice` 农场、关联天气、唯一 `drone_shared` 资产与公共时钟，形成本次 `OperationContext`。路由 ID 不再作为普通业务参数传入领域方法。
4. `runtime._device_operation` 调用 `invoke_operation`。固定 dispatch 表选择原 `DroneApp.fly_survey` 规则，使用具名 `DroneOperations` 的显式 property 读取目标农场和资产电池。没有为 rice 新建无人机；天气、电量、充电等实时检查在领域操作中发生。
5. 飞行耗时推进公共时钟，runtime 推进所有农场的物理；只有本次任务把巡田观测写到 rice。资产日志记录双重身份，回执记录实际时间、目标与业务结果。
6. 即使回执 `ok=true`，`data.status` 仍可能是 `partial`；Agent 依据实际 `surveyed_ridges` 安排剩余任务。将下一次 `farm_id` 改为 soy 时，电池继续使用同一份资产状态。

场景负责声明 rice 的几何、作物、初态、站点和设备关联，以及该场景的管理目标与验收。它不重新定义无人机的电池规则。物理引擎负责随时间演化土壤与作物；它不解释 Agent 的 function Schema。

| 想修改的内容 | 首先修改的位置 |
| --- | --- |
| 工具名称、参数、默认值、说明 | 对应 `services/*.py` 的真实公开方法 |
| 参数单位、静态下界、实体类型 | 同一方法的 `Annotated` 声明；共用单位别名在 `services/base.py` |
| 模型 JSON 错误处理、注册规则 | `services/base.py`、`tool_utils.py`、`tool_execution.py` |
| 目标解析与合法关联 | `runtime.py` 的 resolver／静态检查 |
| 业务动作的资源消耗和实际结果 | 对应领域 App 的农业规则，资产归属适配在 `operations.py` |
| 作物特性与物理响应 | `crop_profiles.py` 及对应物理引擎 |
| 农场数量、尺寸、作物、设备及任务目标 | 要运行的完整场景文件 |
| 参考管理决策、事件图和验收 | 同一完整场景的 `_SeasonManager`、`build_events_flow()`、`validate()` |

修改公开契约或场景初态后，需要重新生成匹配的 Oracle 与 manifest；不能只改参考文件版本字段。

默认混合全季 FARM Agent 收到 47 个 function schema；含隐藏任务注入工具共注册 48 个。工具入口不按农场数复制；启用 A2A 后主 Agent 的部分入口变为专家委派工具，数量与内容按实际包装后的清单计算。

新共享 `Farm` handler 对普通 overview／垄状态结果递归移除 `nutrient_index`、`stand_fraction`、`ndvi_proxy` 等内部字段，保留公开观测与诊断入口。这个过滤发生在共享服务结果投影中，不是全仓库所有旧兼容返回都已统一重塑，也不等于所有工具的 `data` 都有完整字段白名单 schema。验收器继续可以读取领域真值，Agent 不因此获得验收器权限。

## 四条执行路径与事件捕获

共享公开方法保留现有事件装饰器，方法体只调用 `ToolExecutor.execute(name, arguments)`。Registry 注册私有领域 handler，不注册公开委托方法作为 handler。

| 路径 | 实际入口 |
| --- | --- |
| Agent | Schema 对应 callable 调公开方法，再进入 executor |
| 动态 Oracle | 调同一公开方法，再进入 executor |
| CapturedEvent | 执行捕获的公开方法体，再进入 executor |
| Replay | 名称查表调同一公开方法，再进入 executor |

executor 不能再回调公开方法，否则递归。捕获事件也不能直接指向私有 handler，否则绕过校验。

`SharedAppTool` 是模型 JSON 调用的薄适配层：先做相同静态参数校验，错误参数通过 executor 返回失败回执，合法参数调用真实公开方法。直接 Python 调用缺参数／多参数仍遵循普通 Python `TypeError`；不会为了接住任意错误调用而把公开函数退回 `*args, **kwargs`。合法调用在适配层和 executor 会重复静态检查，但领域动作仅执行一次。

capture 只记录未来调用，不执行成熟、天气、库存等动态检查，也不执行领域操作。导出前校验名称、参数、合法 ID 和静态关联；实际运行时重新检查全部条件，不能因为 Oracle 曾成功而跳过。

executor 先规范参数、解析目标并检查静态关联与能力，再进入私有 handler、领域方法和结果记录。参数、目标解析，以及操作入口显式检查的载荷来源等拒绝发生在相应经营动作之前。天气、成熟和库存等检查仍有一部分保留在原领域方法体中，不能声称所有动态前置条件都已抽成执行前的独立规则。领域方法返回错误和运行中的内部故障都记录实际阶段与部分副作用是否确定，不能一律伪装成无副作用的参数错误；当前不承诺自动回滚。

共享农业结果的错误对象包含代码、字段、原因、阶段和 `partial_effects`；可附合法选项或解除条件。业务 `data` 的字段随工具不同，来源、覆盖和单位由对应工具数据及契约说明表达。

私有领域操作目前返回原领域字典；runtime 将其中明确的错误转换为 `ToolExecutionError`，executor 生成 `ToolResult` envelope。八个全季管理器对共享结果先检查 `ok`，从 `data` 读取观测，轨迹保留整个回执。System 和任务接口保持原协议，不包装成新农业 envelope；管理器按这两类入口的已知协议处理。

统一 envelope 包含 `ok`、`tool`、执行前后时间、适用的目标 ID、`data` 与 `error`。成功时 `error=null`。参数／解析阶段拒绝可标明无经营副作用；已进入 handler、结果校验或记录阶段的内部异常使用 `partial_effects="unknown"`，没有通用事务回滚或完整部分变更明细。原操作返回警告可能表示动作已完成，不等同于未执行。Replay 遇失败回执保留失败步骤并停止，Agent 可以得到失败观察后继续决策。

## 初始化、版本与保存恢复

正式场景先创建农场和资产、建立关联、生成共享服务，完成土壤、天气、窗口和额度配置，设置 `definition_metadata`，然后在 briefing／首次工具发现前 `freeze()`。之后才构建参考事件图或启动 Agent。不能在场景初态尚未配置完成时提前冻结指纹。

一次运行中固定农场、资产、站点和公开工具结构。动态状态通过查询变化；恢复不同结构的快照要创建匹配的新 runtime，并重建 schema 与 dispatch。

`catalog_version` 根据工具契约、schema、公开静态能力与实体关联生成，不包含对象地址、当前油电等动态值。`scenario_config_fingerprint` 单独绑定完整初态、天气 forcing、物理与观测参数／随机状态、实际资产初态、绑定和 seed；正式场景还登记 ID、后端选项、季节期限和巡检要求。目录相同不代表场景条件相同。完整 forcing、初态和 RNG 的指纹覆盖按最终回归校验，不把仅 hash 几何或 profile 名称当作完整覆盖。

Workflow 仍是原来的纯步骤字典。文件保存通过 `WorkflowBundle.save()` 写配套 `.manifest.json` sidecar，包含格式版本、`catalog_version`、`scenario_config_fingerprint` 和保存内容的 `workflow_fingerprint`。文件读取验证内容指纹；执行目标工具前再预检整个图的名称、参数、合法 ID、静态组合与依赖。未知工具、缺失 sidecar、版本或配置不匹配会明确拒绝。

内存路径使用 `WorkflowBundle(workflow, manifest)`，或带生产方 manifest 的 Workflow；验收仍可读取 workflow 视图。捕获图保存 `events_manifest`。执行方不能临时拿目标 runtime 的当前版本替代缺失的生产方清单；CapturedEvent 执行也检查构图时版本。

快照实现位于 `runtime_state.py`，使用版本化、显式允许的类型与字段编码，不使用 pickle 或按载荷任意导入类。保存农场完整物理状态及队列、农场内 sensor／FieldOps 状态、共享 stations、assets、bindings、初始定义、manifest 和工具历史。每项资产仅保存一次，并保存 RNG、载荷来源、粮食批次与绝对充电会话时间。

快照在工具调用边界捕获仿真时刻，不额外推进物理或刷新观测；各引擎自己的最后推进时间和待执行队列一并保存，不伪装成所有引擎已恰好推进到捕获时刻。恢复创建独立新 runtime，保留原季节 `start_time`，以等效 offset 对齐捕获时刻，重新建立墙钟起点和推进回调；后续正常推进补齐应演化的时间。来源、批次数量、设备容量、引用及版本不匹配会拒绝，失败不替换当前运行世界。

## Engine 与物理引擎边界

正式九个场景实现文件显式声明 `runtime_participants=[fleet.runtime]`。`FarmRuntime` 提供 `bind_clock`、`before_advance`、`advance_to`、`snapshot`、`load_snapshot` 和 `outcome`。Engine 通过这些生命周期接口推进新共享运行时。为保留旧接线方式，Engine 仍能从共享服务／A2A wrapper 的 `.runtime` 发现参与者，并保留无 runtime 的旧农场扫描兜底；不能宣称这些兼容分支已完全移除。

FarmRuntime 将时钟绑定给唯一实体，推进全部农场并处理各自天气。共享工具不改变物理公式，也不能只推进当前目标。沿用当前 TimeManager 的时间语义，本次不顺带改成新的离散事件时钟。

粮食统计按资产携带批次的来源归场。物理产量、设备粮箱、拖车和仓库分别计算，避免重复或因设备换目标而改变归属。

## 场景与兼容迁移

八个全季场景继续各自包含配置、初始化、完整 Oracle、build_events_flow 和验收，不以公共场景基类隐藏这些实现。共享的是平台实体、工具服务、契约和物理能力。

每个场景显式列出资产及服务关系。oracle_clone 保留初始资产数量、状态和关联；构图副本与原场景无可变对象共享。build_events_flow 保留原初态不变的完整参考推演方式，事件记录显式目标。初始化与参考策略的既有计算耦合在本次保留，不同时重写场景生命周期。

管理策略使用公开工具查询共享设备状态，根据已知配置选择允许的资产，并在切场前处理剩余载荷。验收按明确目标和动作账核对，不要求照抄 Oracle，也不再按 App 前缀分场。

旧单场接口经兼容 gate 复用原领域实现，新多场 Agent 不同时看到旧前缀别名。显式转换器是 `fairy/scenarios/legacy_workflow_migration.py` 的 `migrate_legacy_workflow(source, runtime, app_bindings, platform_apps=...)`，绑定采用 `LegacyAppBinding(service, farm_id, asset_id)`。

转换器逐项检查旧 App 名、旧参数、目标身份、别名适配和新契约，返回带迁移记录的 `WorkflowBundle`，不执行操作，也不修改源轨迹。未映射、错误种类、未知目标、已有共享前缀以及多个旧设备映到同一新资产均拒绝，避免把原来独立设备的载荷历史静默合并。它不向共享旧轨迹重新签名，也不默认选第一个农场或设备。

转换成功只证明静态可迁移，manifest 明确记录 `dynamic_success_verified=False`。几何、天气、作物或设备配置不同仍可能使参考策略失败，必须再在目标新初态 fresh replay 并验收。需要真正共享载荷的新参考策略应重新构建，不能靠结构转换自动补出返还／卸粮策略。

保留旧证据，新参考流程生成到新目录。只替换验收通过的基线，不覆盖用户已有工作区改动。

## A2A 工具可见性

`World` 环境目录属于基础服务，不参与随机专家包装。主 Agent 始终可以查询环境；专家获得相同来源的只读目录，并只获得分配给自己的实际工具。

专家包装工具的说明包含真实能力和目标摘要，新服务有明确专家映射。包装前后的工具清单应可追溯；不能让主 Agent 看到一个通用 task 字符串后就失去设备和农场信息。

`expert_agent` 可能调用写工具，因此标为 WRITE，返回格式标为 text，说明部分完成与重试前检查状态。World 的农业回执协议列出准确的原子工具名称，不能把 `Drone__expert_agent` 的文本误报成农业 envelope；专家内部调用仍使用原子工具回执。

## 实装索引与验收入口

以下是已落地代码的职责索引。已有 App 原领域方法和物理模型保留在原路径，新共享服务通过上下文复用这些行为。

| 模块 | 职责 |
| --- | --- |
| [runtime.py](../fairy/apps/farm_world/runtime.py) | 实体注册、关联校验、公共生命周期、快照与 outcome |
| [assets.py](../fairy/apps/farm_world/assets.py) | 资产配置、设备状态、载荷来源和粮箱批次 |
| [operations.py](../fairy/apps/farm_world/operations.py) | 类型明确的 OperationContext、具名设备操作类、显式资产属性、固定方法派发与载荷规则 |
| [services/](../fairy/apps/farm_world/services/) | 八个普通服务类、51 个完整公开方法；直接阅读目标参数、单位、默认值和行为说明 |
| [services/base.py](../fairy/apps/farm_world/services/base.py) | 声明校验、事件标记、基础参数元数据与 JSON 调用适配 |
| [shared_apps.py](../fairy/apps/farm_world/shared_apps.py) | 固定类列表注册、allowlist 选择和已有实体枚举收窄；旧轨迹兼容名称映射 |
| [tool_utils.py](../fairy/tool_utils.py) | 扩展 AppTool 契约、参数元数据与类型 Schema 转换 |
| [tool_execution.py](../fairy/tool_execution.py) | registry、executor、统一 envelope、失败回执和 WorkflowBundle／manifest |
| [runtime_state.py](../fairy/apps/farm_world/runtime_state.py) | 允许类型／字段的完整快照编码与独立恢复 |
| [type_utils.py](../fairy/utils/type_utils.py) | 旧单场 gate、原返回／异常兼容和回执 |
| [legacy_workflow_migration.py](../fairy/scenarios/legacy_workflow_migration.py) | 显式旧 App 到实体的静态转换，拒绝歧义与错误重新签名 |
| [toolset_builder.py](../fairy/agents/agent/toolset_builder.py) | 将已注册公开契约投影为模型 Schema 与 callable map |
| [engine.py](../fairy/controllers/engine.py) | 通用 runtime 接线、四路径执行和 bundle 校验 |
| [app_agent.py](../fairy/controllers/app_agent.py) | A2A 目录保留和专家能力可见性 |
| 各独立场景文件 | 本场景实体声明、完整初始化、Oracle、事件图与验收 |

物理算法模块不依赖 Agent 或工具 Schema；领域动作不调用 LLM；共享 App 不直接修改设备或农场状态；场景不另写一套工具语义。

| 层级 | 已落地内容 | 验收检查点 |
| --- | --- | --- |
| 1 | 依据本文工具表与状态表登记参数元数据及领域状态 | 无未归属状态、无隐式目标、无双重 handler |
| 2 | 农场经营状态、资产载荷批次、注册表与快照 | 单资产单状态，恢复不复制，来源可追溯、守恒可核对 |
| 3 | 显式上下文和统一领域操作，旧单场适配 | 准备状态、作物约束、载荷退回与卸粮均正确 |
| 4 | 工具契约、executor、共享服务、目录 | 四条调用路径只执行一次，参数／路由拒绝无经营副作用，handler 故障如实回执 |
| 5 | Engine lifecycle、Agent Schema、A2A 目录 | 全部农场时间推进，模型收到的接口与 dispatch 一致 |
| 6 | 八个独立全季文件及旧阶段任务迁移 | Oracle、事件和验收均用明确目标，完整文件边界保持 |
| 7 | 新参考流程与回归证据 | 八个全季逐一从全新初态导出、回放和验收，并核对负例 |

这张表保留实现依赖顺序，作为代码审查和回归定位索引，不表示这些模块仍停留在计划阶段。平台已覆盖下文迁移表的入口；各场景实际公开集合仍由 allowlist 确定。

最低验收矩阵如下。

| 检查 | 必须证明的行为 |
| --- | --- |
| 工具信息 | 捕获真正发给模型的请求，Schema、目录、allowlist、dispatch 一致 |
| 类型与目标 | 错类型、未知 ID、错误组合、越界垄、错作物参数在副作用前拒绝 |
| 资产连续性 | 同一无人机跨场后电量连续；不同资产不共用电池 |
| 农场准备 | 同一机器不能把 A 场的整地进度带到 B 场 |
| 载荷 | 剩余载荷跨场拒绝；退回后可以换场；不会重复返还已消耗物资 |
| 多机收粮 | 同场两机分别收割和卸粮，批次来源各自完整，无重复或丢失 |
| 作物规则 | 同一共享入口正确使用三作物参数，不沿用首场的种子或水分阈值 |
| 天气观测 | 同站关联可复用；同站干湿两场的通行性不同；异站天气和各场探头覆盖不混合 |
| 公共时间 | 操作推进全部农场，非目标场无该经营动作和扣库，但物理继续演化 |
| 捕获执行 | capture 不运行动态检查；执行会检查；不会再捕获或递归扣资源 |
| 保存恢复 | 资产数量、身份、油电、载荷、来源、RNG 和充电剩余时间保留；坏快照不半恢复 |
| 四路径一致 | Agent、动态 Oracle、CapturedEvent、Replay 使用同一校验与 handler |
| 版本 | clone 同条件版本一致；错误版本或映射在第一步前拒绝 |
| A2A | 主 Agent 和专家都能获取准确目录，不被包装隐藏 |
| 全季 | 八场分别 fresh export、replay、evaluate；当前八个默认全季均真实共享三项资产 |
| 兼容 | 旧单场场景继续可运行，旧轨迹显式转换，无静默默认目标 |

验收比较流程完整性、守恒、阶段与操作历史及合理容差，不以固定步骤数或浮点逐位一致作为成功条件。

### 证据与复核入口

- [共享运行时测试](../tests/test_shared_tools_runtime.py)：模型实际请求中的 schema、目录、目标校验、共享工具和 A2A 可见性。
- [显式公开接口测试](../tests/test_explicit_tool_services.py)：51 个工具的真实源码签名、参数文档、默认值、单位、旧 App 变更隔离、签名伪造拒绝、部分覆盖与未启用物理时的诊断。
- [工具契约测试](../tests/test_tool_contracts.py)：类型、默认值、注册、executor、结果协议、manifest 和回放预检。
- [资产测试](../tests/test_shared_assets.py)：共享状态、目标准备状态、载荷来源、返还和多机粮食批次。
- [Engine 接线测试](../tests/test_shared_runtime_engine.py)：公共时间、runtime 参与者、执行和统计。
- [快照测试](../tests/test_shared_runtime_snapshot.py)：JSON 保存恢复、共享资产身份、随机流、充电及坏快照拒绝。
- [共享天气测试](../tests/test_shared_weather_contract.py) 与 [运行配置测试](../tests/test_full_season_runtime_config.py)：同站规范 forcing、跨场通行判断和完整配置指纹的专项复核入口。
- [旧轨迹转换测试](../tests/test_legacy_workflow_migration.py)：显式映射、错误类型、别名、共享资产歧义、源轨迹不变与转换后的回放要求。
- [全季事件测试](../tests/test_season_event_flows.py) 与 [全季业务测试](../tests/test_multi_farm_full_season.py)：独立文件、原初态不变、四条执行路径、过程与物料账及漏管负例。
- [阶段任务测试](../tests/test_diverse_scenarios.py)：八个阶段任务及同场证据、局地天气、缺失动作反例。
- [全季共享工具回放目录](../validation_runs/explicit_tools_full_season/summary.json)：八个全季场景的保存、加载与 fresh replay 结果；目录／配置版本变化后应重新生成，不能把旧清单当当前版本证据。

2026-10-23 验证覆盖 635 项独立测试：全量 633 项通过；采集后新增的两个签名拒绝负例在 13 项显式接口专项中通过。不是单次全量运行 635 项。PCSE 官方 `user_settings` 从测试开始就将日志与缓存放到临时目录，并传给真实 CLI 子进程；未更换物理引擎、跳过用例或修改 HOME。见 [全量日志](../validation_runs/explicit_tools_validation/pytest.log)、[专项日志](../validation_runs/explicit_tools_validation/pytest-explicit.log)、[当前635项采集清单](../validation_runs/explicit_tools_validation/collection.log) 和 [验证汇总](../validation_runs/explicit_tools_validation/summary.json)。首次全量发现的私有句柄与验收接线问题已修复，原始失败日志另行保留。

当前 8 个全季导出及验收、8 个阶段导出及验收均通过。16 份保存的 JSON 与 manifest 还全部通过独立 Python 进程加载、回放及验收，见 [独立文件回放汇总](../validation_runs/explicit_tools_file_replay/summary.json)。默认混合全季覆盖三作物 21 垄，约 145.015 个模拟日完成，八个全季合计覆盖 19 个农场。

[实际 FARM Agent 的 47 个 schema](../validation_runs/explicit_tools_validation/mixed.agent_tool_schemas.json) 与 [同版本公开环境目录](../validation_runs/explicit_tools_validation/mixed.public_environment.json) 已保存，并核对与参考文件 manifest 一致。测试使用 Mock LLM 验证真正发给模型的工具 schema 和实际调用；离线参考策略回放不等于真实 LLM 或真实农业生产成功率。

## 全部现有工具迁移表

重构前七类农业 App 共 52 个 `app_tool` 方法；下表保留逐项迁移对应关系。旧类仍保留兼容入口，当前共享目录去掉别名和内部同步工具，并增加 World 与返还入口。System 和任务接口不增加农场或设备目标。

“农场”表示新增必填 `farm_id`；“资产”表示新增必填 `asset_id`；“两者”表示均必填。未注明变化的业务参数名称、单位和默认值沿用现有实现，并显式进入契约。只移除确属别名的重复入口，不合并不同业务动作。

| 重构前 App 与方法 | 当前规范入口 | 目标或参数变化 |
| --- | --- | --- |
| FarmWorld.get_farm_overview | Farm.get_farm_overview | 农场 |
| FarmWorld.get_ridge_state | Farm.get_ridge_state | 农场，保留 ridge_id，使用公开字段投影 |
| FarmWorld.get_ridge_range_state | Farm.get_ridge_range_state | 农场，保留 start/end，使用公开字段投影 |
| FarmWorld.get_inventory | Farm.get_inventory | 农场 |
| FarmWorld.commit_daily_physics | 新共享目录移除 | 新路径由 runtime 随公共时间同步；旧单场保留原先增加一天 offset 再推进物理的行为 |
| FarmWorld.apply_fertigation | Farm.apply_fertigation | 农场 |
| FarmWorld.dry_grain | Farm.dry_grain | 农场 |
| FarmWorld.store_grain | Farm.store_grain | 农场 |
| Weather.get_current_weather | Weather.get_current_weather | 农场，解析所关联站点 |
| Weather.get_forecast | Weather.get_forecast | 农场，保留 days |
| Sensor.read_root_zone_sensors | Sensor.read_root_zone_sensors | 农场 |
| Sensor.read_soil_sensors | Sensor.read_soil_sensors | 农场 |
| Sensor.read_canopy_sensors | Sensor.read_canopy_sensors | 农场 |
| Sensor.read_soil_sensor | Sensor.read_soil_sensor | 使用全局唯一 sensor_id，由注册表定位所属农场 |
| Sensor.read_canopy_sensor | Sensor.read_canopy_sensor | 使用全局唯一 sensor_id，由注册表定位所属农场 |
| FieldOps.irrigate_ridge | FieldOps.irrigate | 兼容映射为 start=end=ridge_id，duration_hours 转 hours |
| FieldOps.irrigate | FieldOps.irrigate | 农场，保留 start/end/hours |
| FieldOps.irrigate_range | FieldOps.irrigate | 兼容映射 duration_hours 转 hours |
| FieldOps.apply_pesticide_manual | FieldOps.apply_pesticide_manual | 农场，规范范围为 start_ridge/end_ridge，保留 liters_per_ridge，范围最多两垄；新接口不接受 advance_time 开关 |
| FieldOps.get_irrigation_log | FieldOps.get_irrigation_log | 农场，按目标过滤记录 |
| Tractor.attach_implement | Tractor.attach_implement | 资产，保留 implement |
| Tractor.detach_implement | Tractor.detach_implement | 资产 |
| Tractor.refuel | Tractor.refuel | 两者，farm_id 表示燃油来源 |
| Tractor.refill_pesticide_tank | Tractor.load_pesticide | 旧名称为兼容映射，不同时公开两个同义入口 |
| Tractor.load_fertilizer | Tractor.load_fertilizer | 两者，farm_id 表示物料来源 |
| Tractor.load_seeds | Tractor.load_seeds | 两者，保留 seed_type/count |
| Tractor.get_status | Tractor.get_status | 资产 |
| Tractor.level | Tractor.level | 两者，完成状态写目标农场 |
| Tractor.base_fertilize | Tractor.base_fertilize | 两者，完成状态写目标农场 |
| Tractor.form_ridges | Tractor.form_ridges | 两者，新多场路径按场景声明的 ridge_width_m 起垄，传入不同宽度拒绝 |
| Tractor.apply_fertilizer | Tractor.apply_fertilizer | 两者 |
| Tractor.plant_seeds | Tractor.plant_seeds | 两者，深度与株距保持必填 |
| Tractor.apply_pesticide | Tractor.apply_pesticide | 两者，保留固定剂量行为，与可选剂量版本分别说明 |
| Tractor.load_pesticide | Tractor.load_pesticide | 两者，farm_id 表示物料来源 |
| Tractor.spray_pesticide | Tractor.spray_pesticide | 两者，保留 liters_per_ridge |
| Tractor.load_fungicide | Tractor.load_fungicide | 两者，farm_id 表示物料来源 |
| Tractor.apply_fungicide | Tractor.apply_fungicide | 两者 |
| Tractor.apply_herbicide | Tractor.apply_herbicide | 两者，沿用当前物料渠道，契约明示，不引入新的药品模型 |
| Tractor.mechanical_weed_control | Tractor.mechanical_weed_control | 两者 |
| Tractor.replant_seeds | Tractor.replant_seeds | 两者，规范 spacing_cm 为 seed_spacing_cm，保留 full_replant |
| Tractor.incorporate_residue | Tractor.incorporate_residue | 两者 |
| Tractor.harvest | Tractor.harvest | 两者，按目标作物检查，批次进入本资产 |
| Tractor.unload_grain | Tractor.unload_grain | 两者，farm_id 必须与本资产粮食来源匹配 |
| Drone.fly_survey | Drone.fly_survey | 两者 |
| Drone.check_status | Drone.check_status | 资产 |
| Drone.charge | Drone.charge | 资产 |
| Robot.inspect_ridge | Robot.inspect_ridge | 两者，保留 ridge_id |
| Robot.inspect_pests | Robot.inspect_pests | 两者 |
| Robot.inspect_crop_health | Robot.inspect_crop_health | 两者 |
| Robot.inspect_emergence | Robot.inspect_emergence | 两者 |
| Robot.check_status | Robot.check_status | 资产 |
| Robot.charge | Robot.charge | 资产 |

新增 `World.describe_environment`、`World.get_capabilities` 和 `Tractor.return_supplies`。不新增 Agent 可任意修改场景、设置真值、重置设备或跳过作业耗时的工具。

单探头 ID 使用农场前缀与本地探头 ID 组成全局唯一值；旧局部 ID 仅通过旧单场适配器解析。设备 ID 与农场 ID 不共用命名空间，必须连同类型校验，不能因为字符串相同就认为是同一对象。

新多场路径在创建后固定作物身份和几何；`form_ridges` 执行按已声明尺寸起垄的操作，不改写面积。这样工具能力、面积与版本不会在一季中互相失配。旧单场接口需要的历史宽度修改行为仅由兼容契约保留，不进入新共享路径。

人工喷药的旧 `advance_time=False` 仅保留为内部组合操作／旧接口兼容选项，新 Agent 入口始终按操作规则计时。旧接口的 ridge_id/ridge_count 显式转换为规范范围。此类兼容选项不出现在新多场目录中。
