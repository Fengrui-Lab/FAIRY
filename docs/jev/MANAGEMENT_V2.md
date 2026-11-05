# enforced-v2：将明确的计算与管理记账移入适配层

2026-11-04。启用方式仍为 `enforced_tool_adaptor: true` / `--enforced-tool-adaptor true`；profile 从 enforced-v1 升为 **enforced-v2**，组件版本 `task-management-v2`。默认 false 的 manos-compatible-v1 路径保留。原 enforced-v1 可由 FAIRY 提交 a9e4db6 与管线提交2054d11复现；当前开发变更不追写旧冻结结果。

## 决策分工

| 内容 | 适配层承担 | Jev仍选择 |
|---|---|---|
| 明确施肥任务 | 产品单位换算、各轮实际投入、剩余剂量、机载余量/库存/配额、原生参数填入 | 是否执行施肥作业、目标田格/垄范围，结合实际观测判断时机 |
| 长周期管理 | 从成功回执记账，显式日期和巡查间隔换算成窗口，标记到期/未来、剩余区域与最近阻塞 | 进行检查、管理、恢复，或选择合适的等待 |
| 时间与供水约束 | UTC和UTC+08显式显示，渠道开放、流量、效率、配额与本窗口最大可供水深计算 | 目标田格及可行水量；关闭时选择等待/检查/修复 |
| 完成 | 沿用现有中文/英文完成事实判断，不满足时从Jev next_action中移除done | 完成条件允许后是否结束 |

这是一项明确的程序辅助干预，不只是把detail提示写长。既有 task、detail 开关、工具实现、仿真、Oracle和评分不改。新增管理state独立名为 `management_progress`，保留原始历史与重复检测；增强摘要按真实回执归纳。

## 已实现的计算范围

### 水稻

解析任务中 `p1三轮依次为300、300、300千克/公顷` 一类明确的分田尿素配方。结合快照公开面积及成功施肥回执，计算每轮剩余kg/ha，再转换成实际产品kg。

首轮两田需要30+45=75kg，直接装75kg。针对历史失败状态：80kg首次装载、已施75kg、机上余5kg、容量80kg、库存220kg时，再装 **70kg** 即可供应下一轮；不再让模型从任务数字中选80。缺货时按实际库存和容量分批供给，失败回执不计完成，部分剂量保留余量。

机上肥料不足以完成任一明确田格剂量时，暂不提供该施肥工具，先引导装肥。机上已够本轮用量或没有剩余处方时不重复装料。数量未知时保留模型选择，但load候选只在正数、剩余空间及库存范围内；不再把75000等任务数字直接当合法kg。

### 玉米

从公开任务的明确基肥量及“参考追肥安排为第25日300公斤、第50日300公斤”读取产品用量。300kg/64垄自动转换为 **4.6875kg/垄**。按成功回执记录实际覆盖，仅对当前轮剩余且可供料的区域提供候选；同一批次内只有剂量相同、连续的垄才可组合。失败和未实际覆盖区域不计完成。

TractorApp.load_fertilizer、base_fertilize、apply_fertilizer支持确定性填参。FarmWorldApp.apply_fertigation的等价路径也计入同一施肥账本；任务明确“不额外添加灌溉水”时，自动换算为0.15625倍剂量/垄、carrier water=0，不把同一施肥目标当两份预算。

没有明确配方时不发明剂量；重复矛盾处方、识别到否定施肥指令时不自动推导。当前解析器只承诺已覆盖的中文任务格式，未把任意自然语言理解包装成可靠计划。

## 持续管理引导

- 记录播种/插秧成功时间、已播/已收区域、每田下一施肥轮与剩余产品量；不以请求参数代替成功回执。
- 对任务明确的每7个UTC日水分巡查、每14天生育/植保检查、移栽后第18/38日施肥窗口以及第85日起每日成熟检查生成到期/未来提示。玉米从任务读取追肥和灌溉参考窗口。
- 水稻以实际成功插秧的UTC日为计日基准；玉米全田建植完成后，以最后一次成功播种时间计算参考经过天数。该基准写入state，不读取Oracle起点或隐藏生育阶段。
- 到期是“检查实际条件、执行或解释暂缓”，不代表无条件作业命令。等待候选不超过已解析的下个窗口，已到期任务仅给短期复查上限，并兼顾已有待生效效果和渠道开放时间。适配层不自动执行等待，也不自动施肥/灌水。
- `next_action` 对到期检查/管理工具增加明确说明。任务完成检查仍发现未播/未收/未入库等要求时，**不提供done**，而非baseline的最多两次拒绝后放行。完成事实满足后恢复done。
- 不重写服务返回的概率、置信度，也不承诺所有保留动作的模型概率排名。删除不合法结束选项是候选约束；带DUE说明是提示干预。它们都应如实计入实验机制。

## 供水与时区

仅使用公开渠道开闭时、效率、流量、阻塞率、剩余配额和田格面积。渠道关闭/堵塞/无配额时不提供即时灌溉；按UTC计算下一开放时刻。开放时对选定田格约束水量，使整项作业可以在当前窗口完成并满足取水额度。仍由原生工具最终校验，不调用隐蔽状态判断根区是否需要水。

## 版本与统计

telemetry/jev_menu记录profile、management_adapter_version、management_guidance_sha256。每个程序填写参数记录 `jev_derived_argument`，包含值、依据及版本；每次工具候选过滤记录 `jev_management_options`。`management_derived_arguments`单列程序填参数量，不能当Jev自行推理次数。

Action confidence仍只来自实际模型问题；移除数字问题可能改变最小置信度及Hybrid的fallback触发率，不能将其解释为模型本身更有把握。对照还应同时报告模型请求数、tokens/费用、程序填参量和实际任务验收。

管线显式true要求 `jev-enforced-management-v2` 能力，并核对报告为enforced-v2；不会静默以旧v1运行时执行新v2配置。false继续要求原profile能力。历史v1应继续使用其冻结运行时/管线，不能直接用新管线冒充v1。

## 验证与边界

离线测试覆盖真实原生“80+5越容量→再装70成功”、300kg全田64垄施肥、等价fertigation路径、部分/失败回执、缺货、未知/否定/矛盾任务、UTC窗口及供水量、等待截止、完成与未完成候选、输入构造不改仿真、实际CLI的两条SDK路由，以及baseline请求/回执一致性。

Pure-LLM snapshot通过继承曾获得旧版guidance，本次保留其原输入，不注入v2管理state。LLM主导咨询控制器不受影响。Hybrid full/REFLEX共享Jev分支的辅助，LLM完整接管/填参仍保留原生执行校验；新done候选约束直接作用于Jev决策，不能宣称完整接管LLM也获得同样强的终止屏蔽。

当前完成检查不是完整场景验证器；例如安全干燥、所有农艺窗口和否定句的全面理解仍不因done候选被约束而自动得到证明。未全面实现历史死局恢复、任意语言配方、共享多农场施肥调度，也没有自动决定最优水肥策略。是否提升全季成功率/产量需要使用独立实验身份做真实对照；本轮不改历史结果或启动规模实验。

## 40场景覆盖复核

覆盖评估曾确认继承工具、传感器语义、硬边界及partial摘要缺口，修复前证据保存在主工作区 [覆盖评估报告](../../../integration/jev-adaptor-opportunity-audit-20261104/REPORT.md)。下节记录随后落实的加固，不能把最初初始化通过当作这些问题从未存在。

## 覆盖复核后的增强（2026-11-04，独立 hardening 记录）

前节“已知遗漏”描述的是修复前审查状态，现已由本节取代。保留原报告作为时间点证据，修复和验收另存 `integration/jev-adaptor-hardening-20261104/`。

- **硬契约与固定值**：在选择前过滤非有限值、类型错误、原生schema范围/枚举及明确拒绝范围；把水稻20cm×20cm、每穴3苗、干燥14%等原生固定值直接填入。作物自身播深规则优先于原黄豆菜单；fertigation的“典型0.5–1.5”不是硬限制，合法0.15625保留。
- **资源与批次**：装苗、种子、油、肥和药液候选受实际库存及机载剩余容量约束；加油和已知密度下装苗可直接计算。施肥先确定范围再约束总产品量。插秧还受余苗、燃油、剩余面积及严格UTC午夜规则约束；收获面积只按公开剩余面积、燃油和满箱状态约束，不能从隐藏产量预知绝对安全批量。没有明确药剂处方时，不擅自耗尽共享药液库存。
- **继承与语义覆盖**：通过MRO识别HeaderMaintenanceTractorApp继承的公开规则和机器状态；识别真实SensorApp根区读数，按回执覆盖范围记账。浅层5cm读数、单点读数、冠层观测不冒充全田根区检查。
- **回执摘要**：仅增强模式把请求范围与实际覆盖、partial、未覆盖、warning及待生效区分。原始workflow、回执、最近动作名额和重复检测不改；没有“失败动作移出最近五条”的另一项干预。未知覆盖明确标未知。
- **批次安全**：本地玉米新卸粮使上批干燥证据失效；空批干燥不计新批安全。水稻按batch_id关联实际含水观测/干燥回执，只有安全批次且有仓容才提供入库。已经发生的不安全入库警告继续保留；允许明确带失败说明的终止，不承诺通过后续空操作修复。
- **前置与恢复**：充电、电量不足、满箱/空箱、错误机具、公开整地前置、无可补油机器、无堵塞渠道等约束进入候选过滤，原因写入blocked_actions及事件。仍是逐个原生动作执行，不新增隐藏宏动作或免费操作。
- **观测与时钟**：水位/缺苗率的数值推导要求相应目标的有效观测；跨UTC日或同目标相关作业后要求复核。仅对无歧义的明确田格目标水位计算“补到/排到”的增量。中文时长候选加入等待菜单；长作业参数附共享时钟、预计时长及跨过检查窗口的提示。已经观测到湿泡24小时的另一田不会再被要求重复完整浸田。巡查时间表不再依赖肥料配方是否解析成功。
- **完成分层**：增强模式识别直接否定动作短语，补充“要求全田收获但尚未播种”的公开缺项检查；不把自然停止、可见作业完成、独立原生验证成功混为一谈。它仍不是任意自然语言的完备终止合约。

这些增强均是可公开审计的程序辅助，不能据此直接证明Jev缺乏推理能力，也不能把干预后提升全归因于模型。新profile需要独立真实对照；历史baseline、旧复测和评分保持各自身份。初始化覆盖与离线原生用例通过不等于完成40个全季真实实验。

## 玉米灌溉单位与覆盖修补（ridge-irrigation-reference-v1）

2026-11-04，在normal真实复测发现五次1小时仅用24.6875mm、水深没有换算成时长、零小时仍进入候选和末垄漏灌。新增`ridge_irrigation.py`，仅增强模式接入，历史冻结副本不改。

- 对标准原生IrrigationApp/FieldOpsApp的灌溉时长，按有限正数和当前剩余全田等效配额过滤，三种范围/单垄别名一致处理；不把水深数字直接当小时。
- 对明确的单农场玉米全田参考安排，在当前已到期窗口、取得当天有效根区观测后，程序将参考水深除以原生5mm/h得到小时数，同时生成尚需覆盖且观测可作业的连续范围。50mm正常情况下填写`start=0,end=63,hours=10`；不再向Jev分别询问这三个确定参数。Jev仍决定是否选择灌溉。
- 只按实际`irrigation_started`及正载水施肥回执记账；失败、重复`irrigation_pending`不追加水量。已启动但未结算的水量记为已预留，不称为已确认土壤响应。按轮次和每垄保留余量，部分覆盖后第63垄仍为明确待办。
- 配额按`每垄水深 × 覆盖垄数 / 全田垄数`换算；供水不足时程序填写合法部分量，并保留未满足余量。不会扩展配额。
- 已有待生效灌溉、过期/缺失观测、观测湿区会阻止相应自动批次，引导等待或复查。观测是带噪声的分区平均，原生工具仍负责最终条件校验，不能宣称保证全部实际田垄永不拒绝。
- 多农场、分区/定向、配方歧义或没有明确到期参考窗口时，不编造全田灌溉处方；只保留适用的参数合法性/配额保护。旧漏掉的参考窗口独立显示，不把所有历史欠水一次性累加灌入。

每个程序填写参数的事件记录独立组件版本与参考轮次。当前施肥到期概率分析仅提取实际请求；未修改该轮施肥提示、候选概率或历史选择，也未发起上下文消融模型请求。完整概率与证据在主工作区`integration/jev-due-probability-irrigation-fix-20261104/`。

## Scoped decision presentation revision (2026-11-04)

`decision_context_version=scoped-decision-context-v1` is recorded separately from
`task-management-v2`; its instruction SHA256 is included in adaptor telemetry.
This is an opt-in bundled improvement, not a single-variable ablation.

For all enhanced Jev scenes, operation selection asks only `next_action`.
Unselected tools no longer send speculative parameter questions. Once an
operation is selected, the existing dependent selectors, legal candidate
filters and task-derived quantities resolve that operation's arguments. This
adds a separate argument request when needed; native execution remains one
operation, and ordinary request budget/timeout/retry accounting still applies.
REFLEX confidence routing and full takeover precedence remain unchanged.

Recent actions keep all existing slots and raw receipt excerpts. They now carry
simulation timestamps, UTC and UTC+08 strings, age and action index. Historical
fertilizer receipts identify the earliest incomplete round before/after their
product contribution, using the same public quantity ledger; these are not
claims that later-round readiness or agronomic success was established.
Every history line carries time and age. `actions_this_run` is explicitly a
cumulative union, never a current-round completion marker. The current round,
per-target remainder, due checkpoints and irrigation reference appear before
history in `current_decision`. Unknown times remain null.

Blocker text distinguishes an empty applicator, exhausted quota, carried supply,
and completed prescriptions. Equivalent zero-carrier fertilizer tools disclose
that no extra water is added. Repeating an operation for a new required round is
explicitly allowed; repeating an unchanged failed call or pending effect is not.
Waiting remains selectable but is labelled deferral when work is already due,
not a future prerequisite. Due reference dates still do not establish physical
readiness, and no action is automatically executed or forced by this revision.

No scenario-name conditions, oracle access, hidden simulator reads, default
`detail` changes, workflow rewrites or baseline (`false`) behavior changes are
introduced. Previous frozen pilots keep their original source and reports.
Full-season improvement needs a subsequent run; offline tests verify contracts,
not yield improvement.

## Bounded model view (2026-11-04)

Enhanced mode now uses `scoped-decision-context-v2` with
`model_view_version=bounded-model-view-v1`; its presentation/budget contract hash
is recorded in controller telemetry. The precise `_facts`, `_management`, native
workflow and repeat detector remain internal and unchanged by the projection.
No task text or model choices are truncated.

The model receives current remaining work and resources, exact range-grouped
product balances, a cumulative operation summary, the latest observation per
tool/target (at most 12 targets), up to 8 recent distinct events, and all unique
unresolved failures. Old successful actions are aggregated instead of sending
an unbounded `steps_so_far`. Earlier observation targets omitted from the view
are counted explicitly; full evidence remains in the workflow. Failed calls
are never silently dropped to meet a budget. They clear only when a confirmed
successful receipt with exactly matching tool and arguments supersedes them.

Identical full observation results at the exact same simulated timestamp are
merged, including interleaved repeats; different results or times remain
separate. Read results are labelled `observation_received`, rather than unknown
field-work coverage. A single event time uses UTC+08, while explicitly named
UTC canal fields keep their original clock. Repeated timestamp explanations,
ISO variants and age fields are eliminated. Ridge rows and quantity maps are
compressed by exact contiguous equality, preserving tail differences, units,
pending status and actual coverage; requested/skipped ridges are not credited.
Completed irrigation references are labelled `REFERENCE_AMOUNT_ACCOUNTED`, or
`AMOUNT_ACCOUNTED_PENDING_EFFECT` while queued effects remain, not `DUE`.
Accounting a reference amount is not a claim of optimal irrigation or successful
crop response. Irrigation reference component version is now v2.

Before every enhanced SDK request, budget the serialized state, full question
set and model together. The local envelope is 48,000 UTF-8 JSON bytes, with an
8,000-byte response allowance and a 40,000-byte input ceiling. These are
conservative engineering guards, not a hosted-token limit, tokenizer estimate,
or change to configured model output/action/timeout budgets. If necessary,
remove optional recent events and old completion summaries first; retain the
task, current constraints, questions, latest observations and unresolved errors.
If protected content still cannot fit, emit `jev_context_budget` and stop with
`ContextBudgetError` before any service call. Never send an arbitrarily truncated
request or loop against a failing service. Each actual request logs its measured
size and compression decision. Baseline and Pure-LLM snapshot modes bypass this
projection and guard.

## Feasibility and temporal revision (2026-11-04)

Enhanced mode now records scoped-decision-context-v3, bounded-model-view-v2,
public-feasibility-v1, receipt-entity-v1 and temporal-progress-v1. These revisions
change agent adaptation/presentation only. Native tools, scenes, simulation,
oracles and scores are not modified; previously frozen runs remain untouched.

Paddy transplantation uses one capacity calculation for action readiness, plot
selection and area candidates: actual remaining area, onboard seedlings at the
native 75/m2, machine fuel and strict UTC-midnight work limit. Successful partial
job receipts establish their same-UTC-day deadline; an expired partial job is
not described as repairable by waiting. Empty seedlings require loading, not a
zero-area or empty-choice model request. Fertilizer stock/carried/quota guards
also apply consistently to ridge, paddy and direct-inventory tools.

An empty selected dependency branch raises ToolNotReady. Enhanced selection logs
that local constraint, excludes the tool for that decision and asks for another
feasible action; no native action or fabricated successful receipt is emitted.
Retries are bounded by the finite tool menu, and real request use is counted.
Service failures are not caught as feasibility constraints or retried here.
Baseline selection preserves its old behavior.

Inherited app methods may share their trusted native-base parameter contract
only when method identity matches. Overrides retain their own contract. Missing
entity choices use previously acquired successful public receipts, scoped to
selected farm/plot/asset. Known catalog tools keep crop/cultivar and offer/lot
quantity dependencies; caller-supplied order labels are explicit adapter values.
Unseen catalog IDs are not invented or read from private tool fields; tools wait
for public discovery, with that prerequisite exposed in management_progress.

Observation coverage is separate from the bounded latest-result cache. It uses
actual returned ridge IDs, with a current-day/post-crop-change cycle; unknown
coverage remains unknown. Read coverage is evidence, not a new obligation to
inspect every ridge. Zonal/sample tasks should not become exhaustive inspections;
adjacent requested checks can use native-supported batches. Crop lifecycle goals
are detected from task intent (plant/grow/mature/harvest), without requiring the
literal phrase “full season”. Observation-heavy activity with little simulated
progress raises a soft seasonal-recheck priority; due care, pending effects and
actual crop/resource readiness still take precedence. No wait is auto-executed,
no maturation date is invented, and no legal observation is forcibly removed.

Offline scope: 456 registered, non-quarantined initial scenarios; 409 initialized
with first/last argument paths checked. Initialization failures from missing
external data, invalid checkpoints and missing scenario attributes are reported
separately. This is menu/contract coverage, not full-season validation of every
scene or proof of yield improvement. Additional historical Rice failure and mini
loop reproductions use public logged evidence without network/model calls.
