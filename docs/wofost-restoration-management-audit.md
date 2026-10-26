# WOFOST 恢复、多农场整合与管理审计

**2026-10-25 更新：** 当前交付是直接重写原90中的10个旧场景，保留ID和核心任务，原文件声明官方参数、公开天气、事件及预先写好的静态Workflow，见 [原场景列表和运行方法](wofost-integration.md)。此前另建12个reference场景方案已撤回；下文90例外部脚本运行和中国品种工程迁移仅是历史审查，不能作为“90个正式场景已迁入WOFOST”或“直接使用研究校准品种”的证据。

本页记录恢复整合及首轮90例审查。后续的正式90例逐场管理校准、六品种分配、剂量对照与最新结果，见[正式90例 Oracle 管理校准](formal90-oracle-recalibration.md)；本页五个代表流程属于首轮证据，不是后续覆盖范围。

## 恢复边界

工作目录为 `/Users/quao/.codex/worktrees/wofost-management-audit/FAIRY`，工作分支为 `codex/wofost-management-cultivars-oracle-audit`。

恢复来源是 `codex/wofost-integration-l3-migration` 的提交 `5d6bda72439a3f6fce30c79eb62ca636ed952efa`，随后用 `git stash apply --index a25682a53845c9de3f1143c3f660116acf95b3d7` 恢复未提交文件。没有 pop 或删除 stash。当前 `multi-farm` 工作目录没有重置。整合前源码备份为 `/tmp/fairy-wofost-restored-a25682a-before-integration.tar`，恢复清单位于 `validation_runs/wofost_management_20261024/restoration.json`。

正式 90 场景的原始审查使用独立冻结副本 `/tmp/fairy-wofost-original-a25682a`。这使“原来有什么问题”和“整合后有什么效果”有不同证据，不会将修改中的代码当作原始基线。

## 代码边界和所有权

| 层 | 负责 | 不应承担 |
|---|---|---|
| Scenario 文件 | 地块数量、几何、土壤、播期、初态、库存总额、设施、天气配置、完整参考事件流程 | 在工具外直接给管理行为补产量 |
| `FarmEnvironment` | 明确的农场目录、场景日历、公共时钟、共同天气逐日输入 | 作物生长公式、机器载荷 |
| 每场 `FarmWorldApp` / `FarmPhysicsState` | 本场土壤、作物、病虫草、管理额度和待提交动作 | 在多场中创建第二个种肥药油仓库 |
| `WofostBackend` | 每垄独立原生 PCSE 模型、水氮输入、原生碳同化与分配、生育阶段、状态投影和回放 | 自动猜测缺少的地方品种参数 |
| 固定 Sensor / Irrigation App | 绑定一场的探头、管网、记录；水额度属于该场 | 用参数切换到其他农场或载入其他农场快照 |
| Shared Tractor / Drone / Robot | 一台实物设备的电池、油箱、料箱、已装机具、作业日志 | 为每场复制一台机器或复制仓库 |
| `WarehouseApp` | 共有种肥药油和粮食批次，来源场、垄、品种、水分、干燥及入库 | 代替各场管理水量额度 |
| Engine / Agent | 注册真实工具、公共时钟推进、执行与记录、按记录时间回放 | 隐式决定当前目标农场或改写作物结果 |

新的多农场场景使用上述显式环境和共有仓库。恢复的旧 `FarmFleet` / services 接口保留为兼容入口，其历史快照和工具契约不能直接作为新共有仓库快照使用。

`FarmWorldApp.get_state()` 是田块的操作视图，不含原生模型历史。绑定共有环境时，加载此视图要求完整 `farm_config` 与场景配置完全一致，不能重新解释固定设施覆盖的地块几何。原生田块禁止用普通 `load_state()` 恢复该视图；单场原生续跑须使用 `export_farm_checkpoint_state` / `restore_farm_checkpoint_state` 的完整物理检查点。新 `FarmEnvironment` 的公共时钟、天气缓存、共有设备、仓库和全部田块整体原生检查点尚未实现，单独恢复一个田块视图不等于恢复多场场景。

装种、装肥、装药、加油、退料操作指向共有仓库，不接收 `farm_id`；田间移动作业必须指定实际 `farm_id`。固定设施的工具描述给出真实绑定农场。工具的参数枚举来自实例配置，执行时使用相同枚举校验。旧 services 使用已声明的普通方法，避免从后端反射动态伪造签名。

## 管理行为如何影响 WOFOST

| 行为 | 实际作用路径 | 结论和边界 |
|---|---|---|
| 杀虫、杀菌、化学除草 | 实际工作液剂量 → 当次降压与残效强度 → 病虫草综合胁迫 → 原生 `PGASS` → 呼吸、干物质分配、籽粒干物质 | 有原生因果路径，测试追踪原生变量；不是只改 UI 字段 |
| 机械除草 | 指定垄草压下降 → 同一原生同化胁迫接口 | 不消耗药液，仍消耗机器作业资源和时间 |
| 无人机、机器人巡查 | 生成有覆盖范围、置信度的观测 | 观测本身不增加原生产量；覆盖不足不能声称全田健康 |
| 灌溉、施肥 | 真实工具的水氮输入进入本垄原生平衡 | 装肥是库存转移；实际施用才扣本场施肥额度 |
| 收获 | 在当前状态上结算田间损失、机器损失和水分质量换算 | 不再次执行完整日更新；原生干物质转标准水分粮食质量 |
| 还田残茬 | 保留管理记录 | 尚无原生残茬碳氮分解耦合，不能声称提高原生氮库或下季产量 |
| 同地补种 / 第二个生命周期 | 需要新的原生作物生命周期及保留土壤水氮 | 目前不支持；工具在扣种、扣油和推进时间之前拒绝，不伪造成功 |

原生同化恢复不保证立即增产：严重缺水时，新增同化可能全部用于维持呼吸，`DMI` 仍为零。对照测试必须同时查看 `PGASS/GASS/MRES/ASRC/DMI/TWSO`，不能仅凭一个变量宣称产量改善。

## 本次修复的模型问题

1. `biotic_pressure_engine.py` 把“施药即时提交”和“每日演化”分开，同一日多次操作不再反复老化药效。残效有独立强度，微量补喷不能延长强剂量保护窗口。
2. 各真实施药入口按实际工作液量计算强度。模型参考量为喷杆杀虫/除草 8 L/垄、杀菌 3.8 L/垄、人工背负喷施 3 L/垄。它们是现有模拟器的设备工作液标尺，不是现实农药有效成分推荐量。超参考量不产生超过 1 的强度。
3. 种肥药油的存量和机上载荷保留计算精度，避免先取整导致微量作业免费；显示精度和实际库存不应混用。
4. `ManagementEffectEngine` 和 `YieldRecoveryEngine` 记录实际日推日期。同一时间戳提交的水肥、施药和收获队列仍会处理，但不会重复消耗生物天数。
5. 收割调用 `settle_harvest`，不再调用完整 `update_day`。原生干物质质量和标准水分质量保持不同口径；恢复的水稻兼容路径继续禁用大豆蒲式耳换算。
6. WOFOST 场景使用明确的 `Asia/Shanghai` 日历；物理日界、天气日期、System 读时一致。新共享场景一次作业或等待只推进一次场景时钟，同时结算闲置场。
7. 工作流记录真实 `time_before/time_after`，回放恢复这些边界，拒绝倒退时间。不能用宿主计算机运行速度决定模拟经过时间。
8. 固定设施快照验证农场身份；新共享田块快照禁止夹带旧库存或粮车暂存字段，共有仓库独立保存。
9. 无效原生土壤转换在创建任何垄模型前拒绝。历史 `rainfall_capture_efficiency > 1` 表示集水/径流假设，不能直接映射为负 `NOTINF`，也不应静默裁剪后声称同一水文模型。
10. 原生检查点恢复新增日推日期和品种参数指纹，避免日期字符串导致二次老化，或恢复成另一套品种参数。

原生场景的初始拖拉机油量另作容量校正：超过 100 L 的部分移回初始仓库，保留总燃油，并记录 `initial_state_adjustments`。旧默认场景的声明值保持兼容；冻结原始审计仍保留其 190 L/120 L 超容量证据。

## 四类大豆配置

详见 [文献、完整档案和原生对照](wofost-soybean-trait-references.md)。四类为绥农42耐低温、垦豆40低温敏感、黑农44耐旱、黑农65干旱敏感。每份档案保存全部 78 个原生参数和来源指纹。

`configs/wofost/soybean_trait_references_v1.json` 可同时显式配置四个档案和原有黑农84。场景仍须配置对应种子库存。论文支持耐性对照身份；从实验指标到 `TMNFTB/DEPNR` 的数值映射属于明确登记的工程假设，当前四份档案均未完成田间标定。不能用这四份新档案填补旧黑河43等其他品种缺参问题。

## Oracle 审核的含义

正式集合由 `scripts/fullseason/formal_90_scenario_ids.txt` 确定，每个 ID 分别保存原工作流哈希、真实工具结果、原生日状态和错误。`scripts/audit_wofost_oracle_management.py` 生成逐场 JSON/CSV。操作成功、按时成熟、观测覆盖充分、剂量有依据、管理必要、产量最优是不同判断。

`scripts/compile_wofost_observed_oracle.py` 保留原计划，依据公开生育阶段、土壤探头、天气、含水率和资源状态编译可执行参考工作流，再从新场景回放。私有 DVS、根层水分和病压仅用于事后审计，不得成为策略的隐藏输入。原剂量保留并登记复核项，不能把可执行性修复说成农艺最优。

缺少品种参数、原生补种生命周期、水文模型不支持的场景单列为模型阻塞；提前收割、超容量装载、低置信或局部巡查冒充全田的情况列为流程问题。“多余管理”需要删去该动作的对照实验，不能仅凭日期或剂量看起来较大下结论。

原始 90 场景已经全部实际运行并登记：[逐场报告及 90 个独立页面](/Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_90_management_audit_20261024/REPORT.md)。原完成检查通过 10，执行但未完成 54，旧品种参数阻塞 24，补种和土壤映射阻塞各 1。这不是修复后通过率。

另有必须区分的模型能力：当前原生模型使用氮限制版本；钾、微量元素、根瘤失效不能仅凭通用营养指数得到对应的专属生理机制。残茬分解没有进入原生碳氮循环；叶部病虫害使用显式标注的经验同化折减，没有原生叶面积移除机制；低温萌发和生育延迟不等于冻害死亡模型。场景完成检查即使通过，也不能用来证明这些具体机制已实现。

原 `apply_fertigation` 仍是即时的抽象全田接口，尚未统一到固定设施的流量、管网和作业耗时约束。本轮确认它向原生模型提交真实肥料质量和载水量；这不等于完成水肥设施建模。64 垄 `.24` 的实际含义为 460.8 kg 肥料产品，加指定载水，不应把“light”标签当作实际轻量或认定其必要。删除该动作的对照同时删去肥和载水，不能单独归因于氮。

可执行参考工作流编译和新场景回放命令（在本工作目录运行）：

```bash
env -u USER .venv/bin/python scripts/compile_wofost_observed_oracle.py \
  --scenario scenario_two_farm_full_season_hn84_normal \
  --wofost-config configs/wofost/l3_heinong84_reference_v1.json \
  --output-dir /tmp/wofost-two-farm-observed
```

原始的固定日期 Oracle 保留用于追溯，不会将未检查的旧流程直接重命名为“最高产 Oracle”。原生补种、缺少显式品种档案以及不支持的水文情况仍须先解决对应能力边界。

## 核验入口

- [原始 90 例逐场审计](/Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_90_management_audit_20261024/REPORT.md)：冻结源码实际运行、各动作参数和实际阶段、问题与能力边界。
- [当前修订参考流程与覆盖范围](/Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_90_management_audit_20261024/CURRENT_RESULTS.md)：区分原始完成、当前初始化检查及实际修订回放，不能把少数样例外推为全部 90 例修复。
- [157 项物理与真实工具回归](../validation_runs/wofost_management_20261024/physics_validation.json)：精确命令、版本、源码指纹和原生因果检查。
- [实际 Agent 的 84 个工具契约](../validation_runs/wofost_management_20261024/agent_tool_contract_audit.json)：真实目录、参数、固定绑定和无效调用无副作用。
- [四类新大豆通过真实工具准入](../validation_runs/wofost_management_20261024/trait_tool_admission.json)：共有仓库装种、整地播种、两日原生运行及档案匹配。
- [全库回归及修复后复测](../validation_runs/wofost_management_20261024/regression_summary.json)：全库 846 项先通过 841 项；5 项失败均来自场景把 8 垄写成一次地面任务。修复三个场景文件后，受影响的三个测试模块 29 项全部通过，无遗留失败。一项测试随行为修复改名，按同一用例计数，不重复计算；这不是一次全绿命令的结果。
- [相对于恢复 stash 的完整整合补丁](../validation_runs/wofost_management_20261024/integration.patch)：用于区分“恢复的旧代码”与“本轮整合修改”，逐文件指纹见同目录 `implementation-change-ledger.json`。

这些测试分组存在重叠，不应相加成一个通过总数。工具契约检查、公开工具 Oracle 和外部 LLM Agent 运行是不同证据；本轮没有宣称调用服务器模型完成全季。

最终冻结源码的五个参考流程全部完成真实工具调用及从新场景开始的回放：普通季 3756.60 kg、干旱季 2705.53 kg、病害季 4450.72 kg、双场合计 7605.34 kg、三场合计 11427.35 kg。各场均收割并安全入库 64 垄。工具响应、参数、绝对时钟、六个物理引擎及原生后端公开快照一致；快照核验不等于序列化了所有 PCSE 内部 Python 对象。结果和原始轨迹见上面的“当前修订参考流程与覆盖范围”。

## 普通季中已实证可删的管理动作

普通季的 R1 `.24` 营养量及 2 mm 载水操作经配对删除试验后，安全入库由 3756.60 kg 变为 3761.94 kg，增加 5.34 kg（约 0.142%），并少用 460.8 kg 肥料产品及 2 mm 载水。两组初态、其余 617 次操作的参数和绝对时刻完全相同，都有 64 垄安全入库，成熟日和收割日相同。

因此，在这个普通季、这组模型参数下，该整次水肥操作没有增产收益，可以删去。它不是单独的氮效应试验，不说明其他场景不需要施肥或灌水，也没有证明全局最高产。

[执行过的候选完整工作流](/Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_90_management_audit_20261024/nitrogen_ablation/recommended_normal_workflow.json)和[对照证据](/Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_90_management_audit_20261024/nitrogen_ablation/recommendation.json)可直接核查。复现命令：

```bash
env -u USER .venv/bin/python -m fairy.cli \
  -s scenario_full_season_hb_base_hn84_std_normal \
  --wofost-config configs/wofost/l3_heinong84_reference_v1.json \
  --replay \
  --workflow /Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_90_management_audit_20261024/nitrogen_ablation/recommended_normal_workflow.json \
  --output-dir /tmp/wofost-normal-reviewed
```
