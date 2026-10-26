# 多农场与作物扩展整合

整合目标是 `codex/wofost-management-cultivars-oracle-audit`，工作目录为
`/Users/quao/.codex/worktrees/wofost-management-audit/FAIRY`。
桌面 `multi-farm` 工作区保留原状；它的未提交修改也已经纳入整合。

## 三个来源

| 来源 | 输入版本 | 合入内容 |
| --- | --- | --- |
| 当前 WOFOST 工作区 | 原 HEAD `5d6bda7`；工作区检查点 `3a11f9f` | 官方大豆参数、13 对经典/V2 场景、日界与回放修复、病虫草外接胁迫、土壤氮事件、已有多场兼容 |
| Fengrui-Lab/FAIRY `extend_crops` | `238a203f54cc7da7fc156724333a521a46771a24` | 原生 WOFOST 玉米、独立水稻世界及 L1/L2/L3 场景、工具错误恢复 |
| 桌面 `multi-farm` | HEAD `e0a302c`；含全部未提交内容的快照 `f11d1d3` | 共仓与共享设备、作物/设备规则合同、独立玉米模型、双场大豆管理场景、旧引擎生长耗肥结算 |

恢复点在本地分支 `codex/integration-wofost-checkpoint-20261026` 和
`codex/integration-desktop-multifarm-20261026`。文件级 ZIP、补丁、逐文件 SHA256 和
实验命令保存于桌面 `validation_runs/wofost_three_way_integration_20261026/`。

## 如何选择作物与模型

| 构造/场景入口 | 实际生长模型 | 种子身份 |
| --- | --- | --- |
| 默认 `FarmWorldApp()`，`crop_backend="legacy"` | 经典大豆，经过 `SoybeanDynamics` 与环境引擎衔接 | 原有大豆种子 |
| `FarmWorldApp(crop_id="maize")` | 桌面分支的独立玉米模型，属于 legacy；不是 PCSE | `MAIZE_EARLY_2026` |
| 历史 `crop_type="maize"` / `crop_type="rice"` | 保留旧多作物代理模型及原公开生育期 | `MAIZE_STANDARD` / `RICE_STANDARD` |
| 大豆农场调用 `configure_crop_backend("wofost", ...)` | PCSE WOFOST 8.1，原生水分和氮平衡 | 显式映射的官方大豆或已声明的参数配置 |
| 玉米农场调用 `configure_crop_backend("wofost", crop_name="maize")` | PCSE WOFOST 8.1 玉米 | `MAIZE_201` → `Grain_maize_201` |
| `scenario_rice_*` | `PaddyWorldApp` + `RiceWofostBackend`，包含田面水层、插秧和水氮账 | `Rice_IR72` |

`crop_id` 是桌面新作物接口；`crop_type` 保留已有场景的兼容含义。因此三个玉米身份
保留各自的规则、机具要求和参数，不能互相替换。未知作物、错误种子或不匹配的后端会拒绝执行。

后端选择不改变农场面积，也不重建仓库。农场面积和行数由场景声明；物料由场景初始化。
水稻使用自己的完整田格世界。此次保留它的独立工具与库存边界，未把水田农机强行转成旱田
`FarmEnvironment` 的共享拖拉机。旧的非淹水水稻代理场景也仍独立存在。

## 多农场的归属

`FarmEnvironment` 管理同地区多个旱田农场的共同时间与天气。
每个 `FarmContext` 有独立土壤、作物、传感器和固定灌溉；移动设备各创建一次。
种子、油、药、肥及粮食在唯一 `WarehouseApp` 记账。各场水额度及施用额度仍归当地农场。

原生大豆与原生玉米可以通过同一 `SharedTractorApp` 作业：装料从共同仓库提取，
田间作业必须给 `farm_id`，播种前按目标农场重新检查种子与后端；拒绝操作不消耗时间或物料。
对应实际组合回归是 `tests/test_wofost_multicrop_shared_integration.py`。

工具参数仍来自真实 Python 签名。`CropDefinition` 与 `TractorEquipment` 提供作物和设备规则；
`OperationContract` 将这些规则用于 Agent 描述、参数范围与执行前校验。
构建 Oracle 只捕获调用；动态天气、库存和机具准入在真正执行时重新检查。

## 日推进与管理

`physics_orchestrator` 决定每天由哪个作物模型生长一次。
legacy 路径由 `CropDynamics` 执行作物阶段；环境统一更新土壤、管理残效及病虫草。
WOFOST 路径由 PCSE 负责生长、水分与氮，不再调用 legacy 的日生长或生长耗肥结算。
同日施药、补水和收割只提交操作，不再制造一个额外生物日。

桌面的增长耗肥修复作用于 legacy 综合肥力代理；它不是 N/P/K 质量平衡。
WOFOST 的 CNB 氮池保持原有责任范围，场景土壤氮事件仍写入真实氮池并保存事件游标。
大豆病虫草通过明确的外接同化胁迫作用于 WOFOST；原生玉米首版没有这套病虫草模型，
工具会明确拒绝相应植保操作，机器人不会生成大豆病虫害误报。

农场完整快照保存作物身份、几何、日游标、待提交操作及原生 journal。
传感器和固定设施保持原农场绑定；公共仓库独立保存，恢复单个农场不能恢复出第二套库存。

玉米分阶段任务已重新生成12个真实检查点，15个L1/L2任务分别通过执行与独立回放。
现代检查点内已包含完整原生状态，只恢复一次；旧格式才额外恢复其公开字段，避免重复推演64垄历史。

## 场景入口和运行

- 原有 13 对场景继续按 `configs/oracles/wofost_scenario_versions.json` 区分：原 ID 用经典引擎，`_V2` 用 WOFOST。03 的未校准标记保留。
- 原生玉米：`fairy/scenarios/maize/`，例如 `scenario_maize_l3_normal`。
- 水稻：`fairy/scenarios/rice/`，例如 `scenario_rice_l3_normal`。
- 桌面的两种单场玉米、玉米大豆双场及三个新增双场大豆文件保留各自的独立题设和 workflow。

在上面的整合工作目录运行，例如：

```bash
PYTHONHASHSEED=0 .venv/bin/python -m fairy.cli \
  -s scenario_maize_l3_normal \
  --build-oracle --run-oracle-tools --replay --evaluate \
  --output-dir /tmp/fairy-native-maize
```

把 `-s` 改为 `scenario_two_farm_maize_soybean_full_season` 可运行桌面的双场混种模型；
它使用 legacy 独立玉米与经典大豆。`scenario_rice_l3_normal` 运行原生水稻。
这些命令均执行真实工具、从新状态回放并评估，不调用 LLM。

## 已确认的上游校验问题

水稻有 13 项“最终状态必须等于发布 SHA256”的断言在本机原始 `238a203` 上同样失败。
已逐场确认：整合版与原分支的实际 SHA、产量、水氮和资源结果相同；每场执行与独立回放的
完整状态相同，任务与质量守恒检查通过。发布快照与本机重建的部分原生浮点值相差约
`1e-12`，严格字节哈希因此不同。本次没有改期望值或物理参数来掩盖该差异。
逐场证据位于整合验证目录的 `source_audits/extend/rice_golden_all13_comparison.json`。
