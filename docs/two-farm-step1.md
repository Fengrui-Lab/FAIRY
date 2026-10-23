# 两农场、固定设施与一个共享仓库

场景文件为 `fairy/scenarios/two_farm/scenario_two_farm_shared_equipment.py`。这个场景从未整地、未播种开始，完成两个农场各64垄的准备、播种及巡查；不要求收获。配置、参考动作、`build_events_flow()` 和验收全部位于这个文件。

## 归属边界

| 对象 | 归属 | 保存什么 |
|---|---|---|
| FarmA / FarmB | 各自农场 | 本地0–63垄、土壤、作物、整地进度、用水与施药管理额度 |
| FarmA_Sensor / FarmB_Sensor | 各自农场的固定探头 | 探头位置与本场观测 |
| FarmA_Irrigation / FarmB_Irrigation | 各自农场的固定设施 | 灌溉任务、作业记录；扣本场水量额度 |
| Warehouse | 整个场景唯一一个 | 种子、肥料、农药、燃油，以及带来源的粮食批次 |
| Tractor / Mavic3M / Robot0 | 跨场共用 | 同一台机器的油箱、电池、挂具、载荷及作业日志 |
| FarmEnvironment | 整个场景 | 农场目录、仓库绑定、公共时钟、共同天气和同步推进 |

`InventoryState` 保留给原单场兼容路径。多场景不再用每个 FarmWorld 的旧库存做业务账，也不把同一份库存复制成两个独立仓库。共享资源只声明在 `WarehouseStock`，通过一个 `WarehouseApp` 管理。

本场景明确配置十种现有大豆种子各2,000,000粒、农药4,000L、肥料4,000kg、燃油2,000L；这是修改前两个场库存的总和。机器初始油箱及机上载荷是机器自己的状态，不再次计入仓库。

## Agent 能看到什么

```python
Warehouse__get_inventory()             # 全场唯一的种、肥、药、油库存及粮食总量
Warehouse__get_grain_batches()         # batch_id、来源场、作物、垄范围、水分与状态
FarmA__get_management_status()         # A的用水额度、已用量及施药限制
FarmB__get_management_status()         # B的用水额度、已用量及施药限制
FarmA_Sensor__read_soil_sensors()       # 固定绑定A，不需要farm_id
FarmB_Irrigation__irrigate(start=0, end=3, hours=0.2)
Tractor__load_seeds(seed_type="STANDARD", count=42880)
Tractor__load_fertilizer(kg=200)
Tractor__refuel(liters=100)
Tractor__plant_seeds(farm_id="farm_a", start_ridge=0, end_ridge=3,
                    depth_cm=4, seed_spacing_cm=5)
Tractor__return_supplies()              # 剩余种、肥、药退回唯一仓库
Mavic3M__fly_survey(farm_id="farm_b", start_ridge=0, end_ridge=6)
Tractor__get_status()                   # 同一台机器的油量与载荷
```

共享场景不向 Agent 注册 `FarmA/FarmB__get_inventory`、`dry_grain`、`store_grain`，避免把共享仓库伪装成各场库存。田间作业仍要求真实的 `farm_id` 枚举；装料、加油、退料没有这个参数，因为它们操作同一个仓库。工具 Schema 来自实际公开签名与参数说明，固定设施的说明包含实际绑定农场。

## 装料、使用、退料

从仓库装100kg肥料后，仓库减少100kg、机器增加100kg；在A用40kg、再到B用60kg是合法的。扣目标农场管理额度和记录应用效果发生在实际作业时，而不是装料时。相同仓库来源不再成为切场限制；不同种子品种仍不能混装，机器容量、燃油及田间作业门槛继续生效。

收获时，粮箱保留来源场和垄范围，不能把其他场的粮食混进尚未卸空的粮箱。`Tractor__unload_grain(batch_id="farm_a_0_3")` 将这一趟转入共享仓库，`batch_id` 必须唯一；来源来自真实粮箱，不允许参数伪造。随后通过 `Warehouse__dry_grain(batch_id=...)`、`Warehouse__store_grain(batch_id=...)` 处理该批。来源用于追踪和按场统计产量，不表示存在各场独立仓库。这个播种场景本身不执行收获。

## 物理、时间与场景

设备 Operations 显式接收目标 FarmContext，读取该场土壤和作物，扣同一台机器的资源，把效果写回目标场。没有通过改写设备“当前农场”来转场。农场物理引擎继续只计算田块；仓库不参与作物生长，也不拥有灌溉水量额度。

`FarmEnvironment.advance_time()` 同步两场、公共时钟只推进一次，再把两场推进到同一时间戳。移动作业、固定灌溉和 System 等待均走这个入口。这个场景使用北京时间；每天的区域天气只生成一次，两场土壤和作物独立演化。

## 运行与验收

```bash
PYTHONHASHSEED=0 python3 -m fairy.cli -s scenario_two_farm_shared_equipment \
  --build-oracle --run-oracle-tools --replay --evaluate \
  --output-dir /tmp/fairy-two-farm
```

当前Oracle共88个执行步骤（事件图另含一条briefing），先读共享库存，再读两场探头，分别固定灌溉0–3垄0.2小时，逐场完成平地、基肥、起垄和全部播种，再用共享无人机与机器人检查指定范围，最后核对共享库存。`_reference_actions()` 完整列出动作，构图不执行业务。

验收按场检查准备、覆盖范围、播深、株距、品种、探头与巡查证据，再用共享仓库的总种子消耗对照两场已播种总数和机上余种。少管B场、遗漏B探头、缩短灌溉或巡查、改错播深都不能通过。结果按农场列出田块任务，仓库和公共设备各列一次。

相关测试为 `tests/test_two_farm_scene.py`、`test_two_farm_fixed_systems.py`、`test_two_farm_tractor.py` 和全季两场/三场测试。真实模型规划能力不由离线 Oracle 或脚本式 LLM 测试证明。

本轮针对四个多农场场景的37项集成断言已通过，包含三个全季的真实工具运行/新初态回放、唯一批次的来源与覆盖、共享库存守恒及各场水量/应用记录。
