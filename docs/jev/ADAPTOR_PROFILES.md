# Jev 适配层对照版本

2026-11-04 起，`farm_jev` 使用 `enforced_tool_adaptor` 明确选择两条路径。默认 **false**，不再默认叠加近期强化；`detail` 仍只控制场景任务详略。

| 内容 | false：manos-compatible-v1 | true：enforced-v2 |
|---|---|---|
| Jev 工具选择、置信度、Hybrid full/REFLEX、重复检测 | 保留既有机制 | 同左 |
| 中文终止判断 | 共用 zh-en-done-v1 | 共用语言兼容，另有直接否定/全田未播等公开任务检查 |
| 单农场起点＋垄数 | 保留独立问题与预请求，按原公式映射终点 | 先选起点，随后限定可行垄数，再检查映射 |
| 种子数量 | 既有数值菜单，由 Jev 选择 | 先选品种；可根据显式任务、几何和可见回执推导需求；条件充分时直接填数，否则回到菜单 |
| 肥料用量 | 原菜单由Jev选择 | 明确配方自动换算、扣余量、按成功覆盖填参 |
| 长周期执行提示 | 无新增提示 | 旧guidance + 分轮进度/到期窗口/双时区/供水约束 |
| 提前done处理 | 原有限拒绝机制 | 未满足原完成事实时移除Jev的done候选 |
| 历史摘要队列 | 原 snapshot/history | 按实际回执归纳，保留最近五条、相邻重复压缩及原重复检测；不切换“最近有效动作”队列 |
| 自动推进时间、自动水肥计划 | 不启用 | 不启用 |

强化种子功能并非仅“扩展候选”：在可可靠推导时会承担数值计算和填参责任。比较时应如实说明这部分计算从模型转移到程序。enforced-v2 已实现明确施肥配方的剂量拆分和剩余资源计算，详见 [MANAGEMENT_V2.md](MANAGEMENT_V2.md)。水分是否需要、最优施肥时机等仍依据实际观测选择，不由适配层虚构。

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

管线冻结配置保留开关，协议/任务身份随配置变化；显式设置开关时要求 CLI capability `jev-adaptor-profiles-v1`；true 还要求 `jev-enforced-management-v2`，防止旧冻结 CLI 静默忽略或退到v1。未声明开关的旧冻结配置仍按其原运行时处理，不重写。新主版本默认 false；新对照应始终显式写出两种值。

telemetry 与 `jev_menu` 记录开关、profile、中文终止兼容版本，以及启用的 ridge/seed/guidance 版本与指导文本 SHA256。管线归一化结果保留这些字段，历史无标识数据为 `historical-unclassified`，不能用缺字段推断 false。运行报告与显式配置不符会使管线配置核对失败。

## 解释实验时的边界

两组差异属于“适配器约束＋确定性计算＋提示”的组合干预。若强化组改善，可支持“Jev 对这些适配层支持有依赖”的结论；不能单凭此对照证明 Jev 普遍缺乏推理能力。应固定模型/服务版本、语言、detail、预算、环境与评分，并同时报告原生任务完成、产量、错误、请求次数/费用。重复实验与分项消融才能进一步区分效果来源。

## 历史保护与验证

主工作区 `integration/jev-adaptor-profiles-20261104` 保存改前源代码、baseline 参考源、哈希清单、相关历史结果独立压缩备份、对照测试和版本说明。该目录只增加证据，不覆盖既有 attempt 或 score 指针。此前 latest 拼接展示不自动变成 baseline 数据集；normal 强化复测、H01 终止修补复测、历史摘要试验各自保留独立身份。

## 强化版本沿革

- enforced-v1：FAIRY@a9e4db6、管线@2054d11，包含范围、种量和旧执行指导。
- enforced-v2：本次增加明确施肥计算与持续管理支持；默认false及中文完成事实解析保留。新版本有独立profile与源码hash，不追改历史版本标签。

2026-11-04的enforced-v2覆盖加固还包含原生参数硬契约、固定参数、剩余装载容量、子类资源规则、真实覆盖回执、批次安全和公开前置条件。其程序辅助范围已超出“更详细prompt”；实验对照应报告这些机制及程序填参量。具体边界和未验证项见[MANAGEMENT_V2.md](MANAGEMENT_V2.md)末节。false的默认输入和动作协议不加入这些增强。

2026-11-04 enhanced-only follow-up: scoped-decision-context-v3 /
bounded-model-view-v2 add public-feasibility-v1, receipt-entity-v1 and
temporal-progress-v1. Native tools and scenarios are unchanged. See
`MANAGEMENT_V2.md` and the workspace audit
`integration/jev-tool-temporal-audit-20261104/REPORT.md` for coverage and limits.

2026-11-04 状态语义修复：true 路径升级为 `bounded-model-view-v3`、
`public-state-semantics-v1`、`temporal-progress-v2`；false 路径不接入。
这是一次新的强化源码版本，既有冻结运行仍保留原版本。具体契约与边界见
[STATE_SEMANTICS_V1.md](STATE_SEMANTICS_V1.md)。不修改原生工具、场景或评分。

真实复测后主代码补充 `public-state-semantics-v1.1`，修复原生整数垄号键未进入列式
压缩的问题；仍保留失败运行的 v1 冻结源码，补丁尚未进行第二次真实复测。

按用户要求，强化模型视图进一步改为 `bounded-model-view-v4` /
`age-count-bytes-v1`：旧观测和历史失败回执允许按年龄、数量、字节淘汰，大回执使用
明确标注的预览。模型不再接收全部历史细节；原始工作流与程序账本保留。
这与此前“保护所有未确认解除的错误正文”的策略有明确区别。当前阻塞谓词仍独立保留。
false 的历史输入与默认行为不变，详见 [STATE_SEMANTICS_V1.md](STATE_SEMANTICS_V1.md)。

用户随后否定1500字节预览，主代码更新为 `bounded-model-view-v5` /
`whole-receipt-window-v1`：保留最近5个目标与年龄淘汰，取消单条裁切、8KB/4KB列表上限和32KB提前淘汰。
留下的回执保持完整，仅整体超过40KB时进一步按整条淘汰历史。v4真实运行不追改标签；v5尚未真实复测。

随后v5 normal真实复测已完成，出现81.60%生物损失（旧有界视图v1为7.79%）。
当前候选修补为 `bounded-model-view-v6` / `scoped-decision-context-v4` /
`temporal-progress-v3`：恢复明确播种年龄、区分未来与到期追肥、补充检查后的可行灌溉提示，
删除推导的全田未观察队列。只作用于true路径，不改变数值计算或工具实现。
v6仅完成离线机制验证，尚无真实产量结果；不能把它当成已恢复的成功版本。
完整回执、合法约束、剂量换算和原始日志保留。详见 [STATE_SEMANTICS_V1.md](STATE_SEMANTICS_V1.md)。

2026-11-04，针对Mini停滞进一步接入 `receipt-establishment-v1`：显式分区品种/地块/株距依赖、
实际补种重置账本、充电可用时间与截止区分、有效进展判据、剩余建植提示及报告去重。
对应 `task-management-v3` / `bounded-model-view-v7` / `scoped-decision-context-v5` /
`temporal-progress-v4` / `public-state-semantics-v1.2`，仍只接入true；false线协议回归保留。
已取得近Oracle产量的v6 normal冻结运行时继续保留，v7尚未真实复测。
范围和未知证据处理见 [ESTABLISHMENT_V1.md](ESTABLISHMENT_V1.md)。

2026-11-04，正式18项中土壤约束场景的v7真实复测暴露出苗前零观测被误作补种待办。
本次强化子版本更新为`receipt-establishment-v2`：区分出苗证据与成苗缺损，
按实际重置隔离作物周期，不用补种回执的成苗基数证明出苗，不把旧零值追认为新缺苗。
保留真实缺苗、品种/株距纠正；默认false、Pure-LLM、detail、原生工具和场景均不修改。
完整机制与验证边界见[ESTABLISHMENT_V1.md](ESTABLISHMENT_V1.md)的v2节。

同日启动前检查又确认补缺达到稳定成苗比例后仍可能被新观察反复触发，
子版本升为`receipt-establishment-v3`：以实际非重置回执记录无改善目标，
相同观测不自动重试，状态实际变化/处方错误/新周期仍可重开；不硬编码农艺上限。
见[ESTABLISHMENT_V1.md](ESTABLISHMENT_V1.md)的v3节。仅离线及隔离工具验证，
尚未启动v3真实模型复测；启动应使用新的冻结源码，不续跑v1/v2旧目录。

第二轮复查将子版本收紧为`receipt-establishment-v3.1`：明确未出苗或冲突观测的
数值变化不能清除无改善记录，只有有效出苗后的成苗变化才能重新评估。该边界缺陷
由合成观测序列复现，并非已确认的真实轨迹归因。false与原生工具不变；
新启动须使用v3.1冻结预览，v3预览保留作追溯，不视为已执行实验。
