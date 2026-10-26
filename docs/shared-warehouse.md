# 多农场共用仓库

种子、肥料、燃油、农药和收获粮食归整个经营场景的一个 `WarehouseApp`。农场数量增加，不会自动创建仓库或复制库存；场景文件必须显式声明一次物资总预算。固定灌溉设施及水额仍绑定各自农场。

## 归属与职责

| 对象 | 拥有什么 | 不负责什么 |
|---|---|---|
| `FarmWorldApp` | 土地、垄、作物、土壤、田间操作记录、水额和本场实际施用额度 | 多场共有物资余额、粮食仓储余额 |
| `SensorApp` / `IrrigationApp` | 固定绑定的农场、探头或固定灌溉设施状态 | 其他农场和共有物资 |
| `WarehouseApp` | 唯一物资余额、粮食批次、共同仓容、按日累计的烘干处理额度 | 选择施药地块、作物生长计算 |
| `SharedTractorApp` | 油箱、种箱、肥箱、药箱、粮箱及粮箱来源 | 独立仓库或农场库存归属锁 |
| `FarmEnvironment` | 农场目录、唯一仓库绑定、公共时间和同步 | 库存默认值、各场粮食预算分配 |
| 场景文件 | 物资总量、农场初态、设施装配、任务说明、完整 `build_events_flow` | App 内部业务实现 |
| Agent / Engine | 真实工具注册、调度和回放；Engine 检查仓库恰好注册一次 | 推断私有仓库、自动补充物资 |

`fertilizer_quota_kg`、用药次数等仍可作为某块田的施用上限。它们表示农艺约束，不表示该田有一份私有库存。例如 A 场施肥上限 200 kg，不能靠换一台拖拉机规避；但从仓库装 400 kg 不会预先占用 A 或 B 的额度。

## Agent 如何查看与操作

| 目的 | 实际工具 |
|---|---|
| 查所有农场共用的物资 | `Warehouse__get_inventory()` |
| 查某场水额、实际施用次数与用量 | `FarmA__get_management_status()` / `FarmB__get_management_status()` |
| 查固定探头、固定灌溉 | `FarmA_Sensor__…` / `FarmA_Irrigation__…`，B/C 同理 |
| 装种、肥、药、加油 | `Tractor__load_seeds(seed_type,count)`、`load_fertilizer(kg)`、`load_pesticide(liters)`、`load_fungicide(liters)`、`refuel(liters)` |
| 对田作业 | `Tractor__plant_seeds(farm_id,…)`、`apply_fertilizer(farm_id,…)`、`spray_pesticide(farm_id,…)` 等 |
| 退回余料 | `Tractor__return_supplies()` |
| 卸粮 | `Tractor__unload_grain(batch_id)`，来源取真实粮箱记录 |
| 查粮食批次 | `Warehouse__get_grain_batches()` |
| 烘干、入库 | `Warehouse__dry_grain(batch_id,target_moisture_pct)`、`store_grain(batch_id)` |

共享场景不注册各场的旧 `get_inventory` / `dry_grain` / `store_grain`，避免 Agent 误以为每块田各有一份库存。参数来自实际 Python 工具签名：装料没有 `farm_id`，田间作业有真实农场 ID 枚举，烘干和入库必须提供 `batch_id`。

## 装料、施用和退料如何记账

以共同仓库初有 1,000 kg 肥料为例：

1. 装车 400 kg：仓库剩 600 kg，机上 400 kg，A/B 实际施肥均为 0。
2. 给 A 施入 200 kg：仓库仍为 600 kg，机上剩 200 kg，A 实际施肥为 200 kg。
3. 给 B 施入 100 kg：仓库仍为 600 kg，机上剩 100 kg，B 实际施肥为 100 kg。
4. 退回 100 kg：仓库变为 700 kg，机上清空，田间实际施肥记录不变。

直接水肥施用没有装车步骤：直接扣共同仓库，同时记录目标场实际施用。手工施药也从同一仓库扣药，药效与施用次数写入目标场。固定灌溉只记本场水额，不从共同仓库扣一个虚构的“水库存”。

种箱不能混品种，但同一箱兼容种子可跨场使用。药箱和杀菌剂箱仍是不同机上容器；当前物资模型将两者记入同一个 `pesticide_liters` 化学品池，尚未按商品或有效成分拆分仓储物料。这次更正的是共有关系，不改变现有药剂效力模型。

共有余额和机上物料在内部保留计算精度，不能因显示取整让小额装料或退料凭空增加库存。仓库不足、品种混装、目标场额度不足等请求在转移或施用前拒绝。

## 收获粮食为什么还需要批次

共同仓库只有一个，但 A 的粮食可能为 16% 水分，B 为 13%。一个全局 `grain_dried` 布尔值无法表达这种情况。每趟卸粮建立独立 `GrainBatch`，保存批次 ID、来源农场、作物、实际品种记录、垄范围、重量、水分和 `pending` / `stored` 状态。

粮食先从田里进入机器粮箱，再由 `unload_grain` 经 480 秒卸入共有仓库的待处理批次。粮箱未卸空时不允许继续收另一个农场，防止丢失来源；同一台机器的其他田间操作仍可切换目标场。物资归属没有“来源场锁”。

烘干和入库只处理给定批次，不修改其他批次的水分。入库要求该批水分已知且满足共同设施与作物的储存上限；所有来源共享仓容。每日烘干额度也在共同仓库按场景日期累计，不能分成多个小批规避。当前烘干/入库沿用逻辑即时结算，不增加模拟时间；粮食重量沿用作物模型的市场标准水分口径，不再次换算扣重。

`harvest_grain_kg` 是共有仓库内尚待入库批次的合计，`warehouse_grain_kg` 是已入库批次的合计；机器粮箱尚未卸出的部分另查 `Tractor__get_status()`。来源场只用于追溯和按场统计，不意味着存在多个仓库。

## 场景如何声明

```python
warehouse = WarehouseApp(stock=WarehouseStock(
    seed_stock={"HEINONG84": 2_000_000},
    pesticide_liters=320.0,
    fertilizer_kg=5_000.0,
    fuel_liters=2_400.0,
))
environment = FarmEnvironment(
    [farm_a_context, farm_b_context], weather,
    warehouse=warehouse, start_time=start_time,
    timezone_name="Asia/Shanghai",
)
apps = [warehouse, farm_a, farm_b, sensor_a, sensor_b,
        irrigation_a, irrigation_b, shared_tractor, ...]
```

这是接口示例。现有四个多场场景保留此前各场物资之和，10 个大豆品种均保留，没有另改物资难度：

| 场景 | 每个品种种子 / 粒 | 药 / L | 肥 / kg | 油 / L |
|---|---:|---:|---:|---:|
| 双场整地播种 | 2,000,000 | 4,000 | 4,000 | 2,000 |
| 双场正常全季 | 2,000,000 | 2,400 | 5,000 | 2,400 |
| 双场病虫与补水全季 | 2,000,000 | 320 | 5,000 | 2,400 |
| 三场正常全季 | 3,000,000 | 3,600 | 7,500 | 3,600 |

增加第四块田时，是否增购物资、增加多少应由场景作者明确决定。

## 保存、恢复及兼容范围

共有仓库在 `scenario.apps` 中恰好出现一次，独立保存余额和批次。各场快照只存 `warehouse_id` 和本场状态，不重复保存共有余额；机器快照保存机上余料和粮箱来源。恢复或重置一块田不会退还已用物资，也不会清空仓库。共同仓库的 `reset()` 仅在明确重置该仓库时恢复场景初始物资。

`InventoryState` 保留为已有单农场场景的兼容类型。未配置共同仓库的单农场大豆、单农场玉米仍使用原有 API 和状态格式。绑定共同仓库后直接访问 `farm._inventory` 会明确报错，避免留下第二份可用库存。

此前多农场版本的快照和工作流含有按场装料、退料、卸粮的旧参数，需重新从场景生成；新代码拒绝把旧库存快照无声覆盖到共有仓库。

## 本次修改位置与原因

| 文件 | 修改原因 |
|---|---|
| `warehouse_app.py` | 建立唯一物资账本及独立粮批，避免整个旧 `InventoryState` 简单别名共享造成水分和状态串批 |
| `farm_environment.py` | 绑定一个显式仓库，拒绝多场却未声明共有物资的配置 |
| `farm_world_app.py` | 直接施用改扣共同库存；田间额度独立；共享库存工具和粮食工具从各场移出；场快照/重置不再改仓库 |
| `shared_tractor_app.py` | 删除装料的农场选择和物料来源锁；真实田间目标保留；余料跨场用；粮箱按真实来源卸批 |
| `tractor_operations.py` | 在目标场实际施肥时检查和记录额度；共同物料计算保留精度；单场分支沿用旧行为 |
| `manual_ops_app.py` | 说明实际扣药对象为共同仓库；施用效果仍归目标场 |
| `controllers/engine.py` | 检查仓库只注册一次，结果报告中只汇总一次共有库存，各场报告本场管理与产量 |
| 四个多场场景文件 | 显式声明一次总库存，更新任务说明与完整 Oracle 到新接口 |

针对性测试覆盖跨场装料使用、共同库存耗尽、退料守恒、实际施肥额度、固定水额独立、粮批隔离、共同仓容/日烘干额度、快照及重置、实际 Agent 工具 Schema 和全季 Oracle 回放。

2026-10-24 最终验证：完整测试 **393 passed**；四个多场场景及单场玉米均完成 CLI Oracle 导出、实际执行、全新状态回放，工具错误与部分完成回包均为 0。三条多场全季路径的 `validate` 按此前要求仍为空，完成情况由测试另查全垄收获、粮批安全入库和物资守恒，不能将空 validator 视为任务评分。

与本轮修改前的完整工作区逐一对照全部 311 个单场：282 个原生 Oracle 执行结束、29 个原有异常，前后数量和路径一致；可取得的物理状态、工具轨迹和时间线无差异。原有异常是 11 个物理时间倒退、18 个缺外部 Excel 文件，本次没有修复，也不能称所有旧单场都成功。

运行记录：`validation_runs/shared_warehouse_20261024/summary.json`、`pytest.log`、`oracles/`；详细单场对照见该目录下 `compat/REPORT.md`。实际 Agent 注册了 84 个工具，其中共有仓库工具 4 个且各出现一次，11 次真实工具分发检查了装料/退料守恒与旧参数拒绝；相关记录在 `tool_information/`。上述验证未调用大模型，不代表服务器模型已自主运行。
