# 第一步：两个农场、固定设施独立、移动设备共用

运行场景为 `scenario_two_farm_shared_equipment`。完整定义在
[scenario_two_farm_shared_equipment.py](../fairy/scenarios/two_farm/scenario_two_farm_shared_equipment.py)，包含配置、初始化、参考策略、`build_events_flow()`、Oracle 和验收。

本步沿用 main 的大豆和物理参数。A、B 各64垄，每垄268米长、1.1米宽，每场面积18,867.2平方米，约1.887公顷。场景任务为整地、播种和检查两个农场；全季管理与其他作物留给后续步骤。

## 对象和状态归属

| 对象 | 实例 | 状态 |
| --- | --- | --- |
| `FarmWorldApp` | FarmA、FarmB | 各自的田垄、土壤、作物、库存、额度、整地进度和物理引擎 |
| `SensorApp` | FarmA_Sensor、FarmB_Sensor | 各自6个土壤探头和6个冠层探头、覆盖区和观测随机流 |
| `IrrigationApp` | FarmA_Irrigation、FarmB_Irrigation | 各自灌溉日志；待生效水分和额度保存在所属农场 |
| `SharedTractorApp` | Tractor | 一份油箱、机具、种子肥药、粮箱及来源记录 |
| `SharedDroneApp` | Mavic3M | 一份电池、充电会话、飞行配置和任务记录 |
| `SharedRobotApp` | Robot0 | 一份电池、充电会话和检查记录 |
| `ManualOpsApp` | ManualOps | 人工作业记录，指定农场提供化学品 |
| `WeatherApp` | WeatherApp | 同地区公共天气输入，不保存某个农场的通行判断 |
| `TimeManager` | 场景公共时钟 | 原实现保持原样 |

`FarmContext` 明确关联一个农场的 world、weather、sensors、irrigation。
`FarmEnvironment` 保存农场映射和公共时间／天气协调，不暴露为 Agent 工具，不保存第二份设备状态。

## Agent 看到的工具

固定设施通过 App 名绑定农场，局部探头ID或垄号可以在两场重复：

```python
FarmA_Sensor__read_soil_sensor(sensor_id="S1")
FarmB_Sensor__read_soil_sensor(sensor_id="S1")
FarmA_Irrigation__irrigate(start=0, end=3, hours=0.2)
FarmB_Irrigation__irrigate(start=0, end=3, hours=0.2)
```

移动设备名称选择实际机器，每次田间操作显式指定农场：

```python
Tractor__plant_seeds(farm_id="farm_a", start_ridge=0, end_ridge=3,
                    depth_cm=4, seed_spacing_cm=5)
Mavic3M__fly_survey(farm_id="farm_b", start_ridge=0, end_ridge=6)
Robot0__inspect_crop_health(farm_id="farm_b", start_ridge=0, end_ridge=7)
Tractor__get_status()
```

这些是普通 Python 方法的真实签名。Schema 读取签名、类型、默认值和 Args 说明；场景只收窄已经声明的 `farm_id` 枚举。新接口注册会检查参数说明、显式类型和签名覆盖，工具重名会报错。新接口的直接调用与 JSON 调用都拒绝非有限数及错类型；JSON 调用还提前拒绝未知枚举、缺失和多余参数。

固定设施说明包含实际绑定的农场。控制器通用提示词使用场景配置，场景另提供准确的两个农场、设备和任务范围说明，避免继续告诉 Agent 只有一个固定规模农场。

## 一次共享设备作业如何执行

以 `Mavic3M.fly_survey("farm_b", 0, 6)` 为例：公开方法查找 `farm_b`，同步两场当前状态，把明确的 `FarmContext` 传给普通 `DroneOperations`；它读取 B 的作物和公共天气，扣除这台无人机的电量，写入 B 的观测和带 `farm_id` 的任务日志。

设备没有“当前农场”切换开关，也不通过改写 `_farm_world_app` 实现跨场。每个设备 Operations helper 都显式接收所需农场上下文。单场旧 App 保留原公开签名，并调用同一份业务算法；新场景只注册共享入口，不混入旧工具。

`TractorOperations` 的整地进度写入目标农场的 `completed_prep_ops`。共享油箱、挂具和电量保持连续。种肥药按来源场扣库；机上有剩余物料时先通过 `return_supplies(farm_id=来源)` 退回原场，再切场。粮箱只允许一个来源，必须卸回该场。未引入混仓批次、设备转场路网或运输时间模型。

## 时间和天气

`FarmEnvironment.advance_time()` 先同步两场，公共时钟只推进一次，再把两场物理推进到同一个时间戳。移动作业、灌溉、人工操作、System 时间推进、通知等待、动态循环和单场日推进都接入此入口。TimeManager 类没有修改。

每天的公共天气输入只生成／推进一次并缓存供两场使用；土壤和作物继续独立计算。拖拉机按目标农场的土壤判断通行，不向共享天气写入该场的平均湿度。

灌溉保留 main 的两种执行语义：激活物理后，在运行结束时向土壤引擎施加水分，回执生效时间为结束时；未激活物理的旧路径保留额外两小时延迟。回执按实际路径报告时间。没有根据旧文案虚构自动完成通知。

## 运行和验证

无需模型密钥，导出参考计划并在新初态中回放：

```bash
uv run python -m fairy.cli -s scenario_two_farm_shared_equipment \
  --build-oracle --replay --evaluate \
  --workflow /tmp/fairy-two-farm/oracle.json \
  --output-dir /tmp/fairy-two-farm
```

只运行已有文件：

```bash
uv run python -m fairy.cli -s scenario_two_farm_shared_equipment \
  --replay --evaluate --workflow /tmp/fairy-two-farm/oracle.json \
  --output-dir /tmp/fairy-two-farm-replay
```

Oracle 共86步：读取两场固定探头，各自固定灌溉0–3垄0.2小时，逐场完成整地／基肥／起垄和64垄播种，再用同一台无人机巡查0–6垄、同一机器人检查0–7垄。源码的参考管理步骤完整列在 `_reference_actions()`。`build_events_flow()` 捕获同一套公开调用，构图不执行经营动作。

验收读取真实农场状态、资源账和实际作业日志，逐场检查覆盖范围、播深、株距、种类和任务完成情况。少管B场、缺B场探头证据、缩短灌溉／巡检范围或改错播深均不能通过。结果分别列两个农场，公共设备只列一次。

测试入口为 `tests/test_two_farm_*.py`，包含固定设施隔离、设备连续性、载荷来源、天气单次推进、真实物理观测、Agent 实际请求 Schema、捕获执行、保存回放和验收反例。验证产物见 `validation_runs/two_farm_step1/`。Mock LLM 用于检查实际接口链路，未测真实模型任务成功率。
