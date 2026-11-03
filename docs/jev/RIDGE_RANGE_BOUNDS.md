# Jev 区间参数边界修复：ridge-range-bounded-v1

> 2026-11-04 版本管理更新：下述强化现仅在 `enforced_tool_adaptor=true` 时启用；默认 false 保留本地 manos 兼容基线。见 [ADAPTOR_PROFILES.md](ADAPTOR_PROFILES.md)。本文原测试数对应首次实现。

2026-11-04，直接应用于主工作区。该版本改变 Jev 区间参数的提问依赖关系；与历史适配器的请求次数和候选集合不同，不能当作相同执行版本。

## 原因与修复

历史适配器独立询问起始垄与垄数，再计算 `end = start + count - 1`。因此即使两项都从候选列表合法选取，也会组合成 `62–65`，超过 64 垄农场的 `0–63` 边界。这个组合错误来自适配器，不能归因于模型未遵守候选列表。

现在先确定农场、设备等作用域及起始垄，再询问垄数：

- 64 垄农场，起点 62：只提供 1、2 垄，映射到终点 62、63。
- 起点 63：只提供 1 垄。
- 拖拉机播种等有明确单次范围上限的工具，同时遵守既有原生限制。
- 多农场使用所选农场的边界；参数在 schema 中的排列顺序不应破坏起点先于终点的依赖。
- 起点和其他独立参数仍可随工具选择一起预请求；依赖起点的垄数不预请求。一般单农场区间动作增加一次参数请求。
- 映射完成后再次检查区间与单次范围上限。适配器不变量失效时抛出错误，不发送越界原生调用，也不静默截断或替换模型选择。

运行 telemetry 和 `jev_menu` 事件记录 `ridge_range_adapter_version`。历史冻结源码、轨迹与评分不追改。

## 范围

用于 `farm_jev` 中 Jev 选择参数的路径，包括 Pure-Jev、Hybrid full 和 REFLEX 的 Jev 填参。LLM 自行生成参数的原生调用路径不在本修复范围。

没有修改历史摘要、完成检查、场景、Oracle、评分或实验配置。下雨、未成熟、充电等动态前置条件仍由原生工具反馈；本修复不替智能体推进时间或选择农事操作。机器人一次最多实际访问八垄属于部分覆盖语义，不额外误当作“请求范围超过八垄必然非法”的硬限制。

## 验证

`tests/test_jev_ridge_range_bounds.py` 覆盖起点 0/62/63、真实工具调用、重复动作预请求、越界选择拒绝、原生 pass width、多农场及反序 schema。原有 Jev 测试更新了两个依赖旧越界行为的断言。

`tests/test_jev_new_tools_http.py::test_real_cli_robot_range_is_bounded_on_the_wire` 使用本地模拟 HTTP，通过 `system-one-compatible` 与 `typesafe` 两条实际 CLI/SDK 路径核验请求与执行参数。所有测试均无需真实模型服务。

这能消除已定位的越界循环来源，不代表已证明 normal 的全季管理或产量问题解决；需要后续独立复测。

本次最终验证：170 项通过（包含 Pure-Jev、Hybrid full/REFLEX、LLM 主导策略、水稻与多农场回归）。日志见主工作区 `integration/jev-ridge-range-bounded-20261104/tests.log`。未启动真实实验。
