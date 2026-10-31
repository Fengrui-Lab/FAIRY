# Jev 新场景工具适配

沿用 manos `a667e6ff3c00a517015f1c708defe44dfdebcb3c` 的 Choice 菜单、类型化参数映射及快照机制。基于 HSCC `c42527358ae69bd38f2e53aa44ff8895d1a6ac2e` 的工作树快照；未提交的客户端适配也保留于来源校验清单。没有增加控制器或管线工具协议。

## 必要差异及来源

| 扩展 | 依据与边界 |
|---|---|
| 多农场标识、设备标识、传感器标识 | 原生工具 schema / FarmEnvironment / runtime 公开的目录与设备适用范围；选农场后再选关联参数，关联问题不参加旧的推测请求 |
| 原生 Annotated 参数 | 从原生 JSON schema 读取标量类型和枚举，继续使用 ArgMenu；不改工具签名 |
| 动态粮食批次 | Warehouse.get_grain_batches、PaddyWorld.get_inventory 的公开字段；没有批次则暂不提供处理工具，下一步重新读取候选 |
| 新卸粮批次名称 | `jev-batch-000001` 起取首个未使用名称，单个确定性选项；只命名，不决定何时卸粮 |
| Rice 地块列表 | 公开地块 ID 的所有非空子集，映射为原生 list；超过 255 项直接报错 |
| Rice 互斥参数 | measure_grain_moisture 的原生 exactly-one 约束；plot_id 与 batch_id 不能同时为空或同时填写 |
| 新数值范围 | 原生 OperationContract、设备容量、PaddyOps 肥料 300 kg/ha 上限；沿用等距候选 + 任务数字 + 默认值 |
| 共享服务返回 | 原生 receipt 的 `ok` 判成功/失败，`data` 供已有结果比较及等待字段读取；TOOL_ERROR 优先，旧返回规则不变，日志不改写 |
| 共享机械容量 | `FarmRuntime.capabilities().asset_capacities`；选定农场/设备后构造燃油、种箱、肥箱、药箱候选，不按不同设备混用上限 |
| 原生 schema 范围 | `ToolParameter` 的 minimum/maximum；包括 Farm.dry_grain 的 11–16；Rice soak 的 1–72 来自原生工具源码 |
| Rice 灌溉 | 公开流量 × (1−堵塞比例) × 输水效率 × 1000 / 地块面积得到 mm/h；按已有 WAIT_STEPS 及任务时长分别生成10个等距水量。剩余额度、有限开放时段只裁剪候选；加入范围内任务数字。不新增时长决策，不预判最优灌溉量 |
| Rice 排水／补苗 | 从 workflow 中取对应地块最后一次成功 read_water_sensors／inspect_establishment 返回；不调用查询。排水按观测水深，补苗按观测缺株比例 × 面积 × 原生密度75株/m²，受已装载苗数约束；取等距正数，补苗向下取整 |
| Rice 农具 | PaddyMachinery.attach_implement/detach_implement 仅接受 tractor；不替 agent 自动装卸农具或检查完整作业前置条件 |
| 多农场／Rice 快照 | 仅公开农场概览、库存及设备字段；不调用带物理刷新副作用的读工具；不包含新传感器观测、WOFOST 内部状态或 oracle |
| 完成检查 | 对各农场／地块与共享粮食执行现有规则；语言匹配及最多两次拒绝保持原样 |

原有单农场大豆菜单、选项顺序和快照保持不变。新实体关联问题必须分阶段发送，因此新场景的物理请求数可能增加；不将其描述为请求级完全等同。原有决策路由、fallback、重复检测和单动作执行保持不变。

## 已知支持边界

- 初始化与菜单检查不等于完整场景通过；模拟 HTTP 仅验证原生 CLI、实际客户端和单动作执行。
- Rice 的缺观测、资源为空、未实现规则分别记录；排水/补苗未取得相应观测前不提供候选，正常查询后逐步更新。观测保留时间来源，可能过期或有舍入误差，原生工具仍可拒绝不满足前置条件的操作。
- 原“剩余额度等距”规则已由用户确认的流量/时间候选替代。当前 Rice normal：p1最小3.6mm、p2最小2.4mm，分别62个候选；该值由设备与地块计算，不是固定推荐水量。候选更多可能影响token和置信度，须单独真实验证，不能声称方法性能不变。
- 没有粮食批次属于临时不可用，与未知参数类型不同。覆盖清单分别记录。
- 原生 Maize checkpoint 一致性失败保持阻塞，不修改初始化、仿真或审计判据。
- 不自动启用新场景，不改变旧批次配置、执行版本及产物。

## 离线复验

在 FAIRY 根目录执行：

```sh
.venv/bin/python -m pytest tests/test_jev_new_tools.py tests/test_jev_new_tools_http.py tests/test_jev_agent.py tests/test_jev_tool_receipts_and_candidates.py -q
PYTHONPATH=. .venv/bin/python scripts/jev_tool_coverage.py --output /tmp/jev-tool-coverage.json
```

工具覆盖命令不创建模型客户端，也不调用模型。HTTP 测试只启动 127.0.0.1 模拟服务。旧实现的菜单／快照测试夹具保留于 tests/fixtures/jev_before_new_tools，不能随实现一起刷新。

## 验收记录（2026-10-30）

原169项回归、新20项回归及18项复核通过。补入 farm_world_diverse 后检查204个场景：197可初始化，7个原生 checkpoint 阻塞不变；没有未实现参数规则，等待观测/资源为空仍单列。70个旧场景基准夹具未更新。

真实短测及来源、完整性记录见 HSCC `integration/jev-tool-fix-20261030-170215/REPORT.md`。同一4场景 × 两方法，每次10工具调用/180秒；保持原任务、原日志，追加执行版本及 attempt。短测不构成完整季节验收，不自动扩大场景实验。

后续流量候选修正的离线验收见 `integration/jev-rice-flow-menu-20261030-173249/REPORT.md`。本轮未调用真实模型，先前短测仍代表旧候选版本，不改写其结果。原生 irrigate、场景、时钟、完成检查、阈值及日志格式不变。
