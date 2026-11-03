# Jev 适配层对照版本

2026-11-04 起，`farm_jev` 使用 `enforced_tool_adaptor` 明确选择两条路径。默认 **false**，不再默认叠加近期强化；`detail` 仍只控制场景任务详略。

| 内容 | false：manos-compatible-v1 | true：enforced-v1 |
|---|---|---|
| Jev 工具选择、置信度、Hybrid full/REFLEX、重复检测 | 保留既有机制 | 同左 |
| 中文终止判断 | 共用 zh-en-done-v1 | 同左 |
| 单农场起点＋垄数 | 保留独立问题与预请求，按原公式映射终点 | 先选起点，随后限定可行垄数，再检查映射 |
| 种子数量 | 既有数值菜单，由 Jev 选择 | 先选品种；可根据显式任务、几何和可见回执推导需求；条件充分时直接填数，否则回到菜单 |
| 长周期执行提示 | 无新增提示 | state 中加入 jev-execution-guidance-v1 |
| 历史摘要队列 | 原 snapshot/history | 同左，不启用实验性压缩队列 |
| 自动推进时间、自动水肥计划 | 不启用 | 不启用 |

强化种子功能并非仅“扩展候选”：在可可靠推导时会承担数值计算和填参责任。比较时应如实说明这部分计算从模型转移到程序。强化版目前**没有**实现 normal 的追肥剂量拆分或灌溉单位换算新功能。

## baseline 的准确含义

`manos-compatible-v1` 指保留 manos 决策机制的**本地兼容基线**，不是未经修改的上游原版。它保留当前统一 TypeSafe SDK、已有新场景菜单/实体依赖、回执处理以及本地可观测状态支持。参数选择基准取自 `typesafe-maize10-harvest-feedback-20261104` 冻结源码；五个方法逐项保存在 `baseline_parameters.py`，AST 与冻结源相同。该冻结版本也包含本地新场景兼容代码。

共用的中文终止兼容识别播种/种植/移栽、收获/收割、入库/储藏/储存，以及明确“提交报告/汇报结果”；它不将任意“报告部件状态”都当作提交最终报告。这是相同完成要求的语言接入，不作为强化组独有优势。旧历史运行没有此修补的，仍记录其原始版本，不能事后声称使用过它。终止检查也不等于原生终态验收，更不以收满田垄替代全部验收。

原生玉米收获反馈等环境修改**不由该开关切换**。它们属于工具/场景环境版本；对照组必须固定相同环境、任务、Oracle、评分版本。不要将旧环境结果与新环境结果冒充仅开关不同的对照。

## 使用与版本记录

CLI：

```sh
# 其余已有场景、服务、预算参数保持相同
fairy-cli ... --controller farm_jev --enforced-tool-adaptor false
fairy-cli ... --controller farm_jev --enforced-tool-adaptor true
```

管线在每个 group 上设置真实 JSON boolean，建议独立 group ID：

```json
[
  {"id":"typesafe-manos-zh","method":"pure_decision","controller":"farm_jev","llm":null,"decision":"jev","enforced_tool_adaptor":false},
  {"id":"typesafe-enforced-zh","method":"pure_decision","controller":"farm_jev","llm":null,"decision":"jev","enforced_tool_adaptor":true}
]
```

上面是 group 片段；`decision` 改成既有 d3 服务 ID 即可比较 d3。完整实验仍需已有 suite、服务、预算和资源锁。`farm_jev` 的 Pure-Jev、Hybrid full、REFLEX 均可用；`farm_llm_jev` 与纯 LLM 不支持启用该开关。纯 LLM snapshot 此前通过继承已经得到执行指导；本次保留它的改前输入，并记录为 `not-applicable`，不会因 Jev 默认 false 而静默撤掉它的提示。

管线冻结配置保留开关，协议/任务身份随配置变化；显式设置开关时要求 CLI capability `jev-adaptor-profiles-v1`，防止旧冻结 CLI 静默忽略。未声明开关的旧冻结配置仍按其原运行时处理，不重写。新主版本默认 false；新对照应始终显式写出两种值。

telemetry 与 `jev_menu` 记录开关、profile、中文终止兼容版本，以及启用的 ridge/seed/guidance 版本与指导文本 SHA256。管线归一化结果保留这些字段，历史无标识数据为 `historical-unclassified`，不能用缺字段推断 false。运行报告与显式配置不符会使管线配置核对失败。

## 解释实验时的边界

两组差异属于“适配器约束＋确定性计算＋提示”的组合干预。若强化组改善，可支持“Jev 对这些适配层支持有依赖”的结论；不能单凭此对照证明 Jev 普遍缺乏推理能力。应固定模型/服务版本、语言、detail、预算、环境与评分，并同时报告原生任务完成、产量、错误、请求次数/费用。重复实验与分项消融才能进一步区分效果来源。

## 历史保护与验证

主工作区 `integration/jev-adaptor-profiles-20261104` 保存改前源代码、baseline 参考源、哈希清单、相关历史结果独立压缩备份、对照测试和版本说明。该目录只增加证据，不覆盖既有 attempt 或 score 指针。此前 latest 拼接展示不自动变成 baseline 数据集；normal 强化复测、H01 终止修补复测、历史摘要试验各自保留独立身份。
