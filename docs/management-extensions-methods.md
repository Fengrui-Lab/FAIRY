# 管理拓展基准：评价指标、经济核算与 WOFOST 参数化方法

核对日期：2026-11-06（Asia/Shanghai）。本文依据当前实现、已归档的 34 场 DeepSeek Thinking 运行及其离线回放产物编写，供论文 Methods 使用。**“软件实现已验证”“Oracle 参考策略已回放”“作物模型已田间校准”是三个不同命题；目前前两项有证据，小麦与甜菜的中国田间校准尚未完成。**

本文中的 `validation_runs/` 链接指向本地实验产物，该目录由 Git 忽略；需准备对应运行记录并执行回放脚本才能生成。这些链接用于审计本批数据，不是代码安装依赖。

## 1. 研究范围与实验单位

研究对象为 [SCENARIO_GROUPS.json](../fairy/scenarios/management_extensions/SCENARIO_GROUPS.json) 的推荐 34 场，不包含另列的 5 个备选小麦场景，也不包含独立交售窗口历史题。场景按下表互斥划分；每个场景在总表只计一次。

| 分组 | 数量 | 当前实际目标 |
| --- | ---: | --- |
| L3 小麦管理 | 10 | 约束下净运营收益；包含水氮、品种、巡查、病害、排水与分区配置 |
| L3 甜菜管理 | 6 | 5 场验收净鲜根产量；1 场高水价净运营收益 |
| L3 单季经营决策 | 10 | 6 场净运营收益；4 场产量门槛下的成本控制 |
| L4 多季／多作物管理 | 3 | 两年玉米累计安全入库量；两个小麦—甜菜按鲜根、小麦、收益顺序比较 |
| L4 跨季经营决策 | 5 | 两季累计净运营收益；政策题含实际到账补贴 |

L3 是一个受管理的作物季；冬小麦跨两个日历年仍为单季。L4 是实际连续管理多个作物季。两个旧 `multiseason_scn_*` 场景的前茬是给定历史，只推进当前一季，仍属于 L3。并行管理两块不同作物田的联合经营题仍按当前注册归 L3。多品种不等于多作物。

“多目标”不宜用于笼统描述全部经营题：最大化净运营收益是一个标量优化目标，水量、氮量、预算是约束。小麦—甜菜的顺序目标是 lexicographic comparison，不是把异质作物公斤数相加，也没有实施 Pareto 前沿优化。

本次结果使用已经保存的模型决策，配置为 DeepSeek Thinking、专家级提示、`parallel_tool_calls=false`、seed=0；来源为三个历史批次。没有重新调用模型。34 条记录均已完成，任务通过 29 条，未通过 5 条；34 条物理回放均有效。**这批数据不应写成“在最新统一源码版本下重新运行的 34 次模型实验”，也没有多随机种子的重复试验。** 原始配置与来源见 [manifest.json](../validation_runs/deepseek_thinking_recommended34_20261106/manifest.json)。

## 2. 指标字段与汇总规则

### 2.1 与既有结果表严格对齐

字段取自 [summary_20_19_18.md](../validation_runs/l3_mini_library_summary_tables_20261106/summary_20_19_18.md) 的“指标口径”，并由同一主回放链路导出。这里沿用原表的版本组合，不能在论文里把所有流程指标统称为 v2。

| 表头 | 唯一对应 CSV 列 | 单位／方向 | 定义与边界 |
| --- | --- | --- | --- |
| Tokens (M) | `total_tokens_per_scenario` ÷ 10⁶ | 百万 token，低为省 | 每次模型调用累计 usage；不是唯一文本长度，也不是扣除缓存后的计费 token |
| Δ Tokens | 由可比较组均值计算 | % | 相对指定参考条件，见下式；单一模型条件不报告 |
| Calls | `llm_calls_with_usage` | 次，低为省 | 保存有 usage 的模型调用次数；不另用循环步数代替 |
| Tools | `agent_tool_calls` | 次，低为省 | 评价器统计的 Agent 工具调用；包含读取、推进时间等，不等于农机作业次数 |
| YL | `yield_loss(%)` | %，低为优 | 相对匹配 Oracle 的生物产量缺口；负数保留 |
| RYL | `recovered_yield_loss(%)` | %，低为优 | 相对 Oracle 的实际回收产量缺口；本表新增 |
| KTC | `ktc(%)` | %，高为优 | **v1** 精确调用签名匹配后的顺序一致性 |
| Cov. | `coverage(%)` | %，高为优 | **v2** 数值比例容差 2 的参考签名覆盖 |
| BFCL Succ. | `bfcl_success(%)` | %，高为优 | 本仓库 BFCL-style 精确签名集合覆盖 |
| Core Path Corr. | `core_path_correctness(%)` | %，高为优 | **v1** 精确签名序列的归一化编辑距离分数 |
| ROCG | `relative_operating_cost_gap(%)` | %，通常低为优 | 相对运营成本差额；用于经营目标子集 |
| RNRG | `relative_net_operating_return_gap(%)` | %，Oracle 收益为正时高为优 | 相对净运营收益差额；用于经营目标子集 |

`path_correctness(%)`、`ktc_score(%)` 是 v2，不能替换原表的 Core、KTC；`coverage_v1(%)` 也不能替换原表的 Cov.。不以 `recovered_yield_loss_v2(%)` 代替 RYL：该旧列包含“成熟但未收获”的保底逻辑，语义不同。FARM/FARMv2 的原有大豆动作先验未针对原生小麦播种、甜菜起收重新标定，本次不作为论文主指标；通用 FOS 综合分在部分原生／闭合多季状态上也不适用。

### 2.2 等权统计、缺失与失败

对固定场景集合 \(S\)，每场先得到指标 \(m_s\)，再计算：

\[
\bar m_S=\frac{1}{|S|}\sum_{s\in S}m_s,
\qquad
\Delta T=100\left(\frac{\bar T_{\mathrm{condition}}}{\bar T_{\mathrm{reference}}}-1\right).
\]

本次 Markdown 平均的是回放 CSV 已导出的逐场数值；流程分／百分比列可能已经舍入到两位小数。Tokens 在场景内累加所有调用，再跨场景等权平均后除以 10⁶。Calls、Tools 同样按场景平均。34 场总均值不是五个分组均值的简单平均。

只有在场景 ID、模型、提示及实验设置可比时才计算 Δ Tokens；本次只有一个条件，因此省略该列。旧 20／19／18 是另一实验的场景集合定义，不能拿它们的任务数量替代本次 34 场。

任务未通过但运行完成且回放有效的样本继续进入均值，避免按结果筛选。运行中止、回放失败或分母为零的值不得填 0；须报告有效样本数及原因。不能对不同条件分别悄悄删除失败场景后比较“总体均值”。生成脚本在当前批次要求 34 个 ID 完整、唯一、关键指标有限且回放成功。相应核查见 [summary_audit.json](../validation_runs/deepseek_thinking_recommended34_20261106/summary_audit.json)。

### 2.3 流程指标的实际数学定义

令 \(O,A\) 分别为 Oracle 和 Agent 工具序列。v1 符号由工具名及规范化参数共同确定；相同工具、不同参数通常是不同符号，USER 消息排除。

**KTC。** 保留 Agent 首次出现且能匹配 Oracle 的不同符号，以其在 Oracle 的首次位置排序。若匹配数 \(n<2\)，实现返回 0；否则设一致序对数为 \(P\)，逆序对数为 \(Q\)：

\[
\tau=\frac{P-Q}{\binom n2},\qquad \mathrm{KTC}=100\frac{\tau+1}{2}.
\]

KTC 只评估成功匹配的子序列，因此“少做很多操作但顺序一致”仍可能高分，须与覆盖率和产量联合解释。

**Cov. v2。** 同工具、相同非数值参数、相同数值键集合的调用才可匹配；顶层数值按 \(\max(|a|,|o|)/\min(|a|,|o|)\le2\) 判断，双方接近零视为相同，仅一方为零则不匹配。字符串、列表、字典等按类别精确匹配。合格的多个 Oracle 候选按数值距离就近匹配，平局优先未占用符号。分数是匹配到的不同 Oracle 符号数占 Oracle 不同符号总数的比例。代码在匹配数不足 2 时继承 KTC 辅助函数的空匹配返回，因此该退化情形覆盖率也为 0。**容差 2 表示 0.5–2 倍窗口，不是 ±2%，也不是“农艺剂量等价”的证据；顶层数字 ID 同样进入这一规则。**

**BFCL-style。** 令 \(U_O,U_A\) 为精确的 `(tool_name, args)` 签名集合，则 \(100|U_O\cap U_A|/|U_O|\)；空 Oracle 返回 0。不考虑顺序或真实时间，重复调用折叠，不评估工具输出正确性。它不是官方 BFCL benchmark 的总成绩。

**Core Path Corr.。** 对 v1 符号序列使用插入、删除、替换代价均为 1 的 Levenshtein 距离 \(d\)：

\[
\mathrm{Core}=100\left(1-\frac{d(A,O)}{\max(|A|,|O|,1)}\right).
\]

实现依据：[workflow_validation.py](../fairy/scenarios/workflow_validation.py)、[path_correctness_v2.py](../fairy/scenarios/fos/path_correctness_v2.py)、[spatiotemporal.py](../fairy/scenarios/fos/spatiotemporal.py)、[主回放字段映射](../scripts/rebatch_fos_from_traces.py)。上述公式描述现有代码，不声称是农学界统一的过程质量指标。

静态 Oracle 与执行日志对连续时间推进的合并和缺省参数表示存在差异，此前自检版本曾观察到甜菜全季 Oracle 自回放 Cov./BFCL 为 90 而非 100；这一数字仅是已观测示例，不是当前 34 场的统一评分上限。把整日 Oracle 改写为 `days=N` 保持时长相同，却不能消除所有合并差异。论文须披露相同版本的 Oracle 控制分；不能把这部分失分完全归因于管理决策，也不能未经说明把 Agent 分数除以 0.9。产量／账目自回放的零差额检验与这些流程分是独立的。

## 3. 生物产量、回收产量及交售量

### 3.1 物理口径

用 \(b\) 表示地块、\(c\) 表示作物、\(t\) 表示作物季。原生模型的储藏器官干物质 \(TWSO_{bct}\) 单位为 kg DM/ha，地块面积 \(H_b\) 单位为 ha：

\[
Y^{bio}_{ct}=\sum_b TWSO_{bct}H_b.
\]

小麦为籽粒干物质，甜菜为块根储藏器官干物质。`TWRT` 是模型根系变量，不能因为块根位于地下就改用它；`TWSO` 也不能直接写成鲜甜菜、蔗糖或可回收白糖产量。普通玉米／大豆沿用原有作物适配器的生物籽粒量接口。

小麦原生收获转换使用固定回收系数 0.95；实际回收指标按配置的商品含水率质量，标准安全仓储含水率为 12.5%。在该口径下，已收获量对应 \(0.95Y^{bio}/(1-0.125)\)。20% 是收获批次的初始含水率设置，不能和 12.5% 的商品重混用。小麦销售价值取最终 `stored` 批次质量，存在批次取整；回收指标保留原生质量计算值，两者可有小额数值差异。玉米、大豆的商品含水率分别为 14%、13%，不是所有作物共用小麦系数。

甜菜采用 [RootContract / RootLedger](../fairy/scenarios/management_extensions/sugarbeet/contracts.py)：

\[
Y^{fresh}=Y^{bio}/f_{DM},\qquad
Y^{rec}=\eta_hY^{bio}/f_{DM},\qquad
M^{gross}=M^{del}/(1-\tau_{tare}).
\]

| 甜菜量／系数 | 当前值或定义 | 证据状态 |
| --- | --- | --- |
| \(f_{DM}\) 鲜根干物质率 | 0.20 | 固定工程假设，未测定／拟合 |
| \(\eta_h\) 机械起收回收率 | 0.95 | 固定假设，无场地实测收获损失校准 |
| \(\tau_{tare}\) 毛重中的扣杂比例 | 0.08 | 固定合同假设；仅用于净重与毛重转换 |
| `sucrose_fraction_fresh` | 0.16 | 声明的鲜重基蔗糖比例；不是 WOFOST 预测值，也不决定当前结算价 |
| \(Y^{rec}\) | 实际已起收批次 `recovered_net_kg` 之和 | RYL 的分子依据 |
| \(M^{del}\) | 糖厂实际接受的 `delivered_net_kg` | 收入及甜菜场景主目标依据 |

扣杂不能在净鲜根量上再扣一次。未起收根不能自动变成回收量，已起收但未交售根不产生当前糖厂收入。当前保存期限制拒绝超龄交售，没有另造连续失糖或腐烂曲线；固定含糖率不支持“管理提高含糖率”的实验结论。

### 3.2 YL 与 RYL

记 \(A\) 为 Agent，\(O\) 为配置匹配的 Oracle：

\[
\mathrm{YL}=100(1-Y^{bio}_A/Y^{bio}_O),\qquad
\mathrm{RYL}=100(1-Y^{rec}_A/Y^{rec}_O).
\]

推荐论文用语为 **Biological Yield Shortfall（生物产量缺口）** 与 **Recovered Yield Shortfall（回收产量缺口）**；表头仍保留 YL／RYL 兼容已有结果。“loss”在这里是相对参考策略的产量差，不是单独测量的生理损失通量。负数表示超过参考策略，不截断，也不证明模型超过了真实物理上限。

默认回放 `--extrapolate --extrapolation-max-days 365`。若模型停止时作物未结束，在独立状态副本上继续原有天气和生长，**不追加新的管理动作**；普通粮食投影到成熟，小麦受成熟及截止日限制，甜菜受收获窗口截止日限制，并受 365 天上限约束。因此 YL 可能是“停止追加管理后的终点产量”，不一定是模型最后一句回复时的在田量。已排队操作仍按原轨迹语义结算。回收量、成本、收入冻结在实际回放结束时。达到投影上限保留 `biological_projection_capped`，不能当作已正常成熟。

多季已经结束的作物从季账本／原生收获凭据读取，当前季使用对应引擎；避免只算最后一季。总表依既定兼容规则，先在一个 episode 内分别合计生物干物质与回收质量，再分别算 Agent/Oracle 比例。**小麦商品粮和甜菜鲜根之和不具有等营养或等经济意义**，必须配合 [逐作物明细](../validation_runs/deepseek_thinking_recommended34_20261106/metrics/management_yields_by_crop.csv)、[逐季明细](../validation_runs/deepseek_thinking_recommended34_20261106/metrics/management_yields_by_season.csv) 及 `crop_composition_changed` 使用。这里的年度键在原生场景可能是播种年，不能未经核对解释为销售年。

## 4. 运营成本与收益核算

### 4.1 成本的定义及经济学边界

定义 \(C\) 为任务期内**被当前场景建模并记账的投入与作业成本**。常规账本按实际消耗计量，购种题存在下面明确列出的现金支出例外。用 \(Q_k,p_k\) 表示第 \(k\) 类投入消耗和固定单位价格：

\[
C=C_{seed}+C_{fert}+C_{fuel}+C_{water}+C_{dry}
  +C_{protect}+C_{drain}+C_{transport}+\epsilon_{round}.
\]

仅启用对应模块时才有附加成本；没有模块的成本不是经过观测确认的真实零成本。

| 成本项 | 数量／实际算法 | 注意事项与实现 |
| --- | --- | --- |
| 种子 | 常规：期初库存＋购入−期末库存−料斗余额，按种子类型乘粒价 | 小麦 kg 以 45 g/千粒换粒数；甜菜按 20 g/千粒物流设定；两者均不是本地实测粒重 |
| 尿素 | 实际施用的肥料商品 kg × 商品 kg 单价 | 不把 kg 尿素当 kg 纯氮；水氮原生适配中纯氮比例为 0.46 |
| 农机燃料 | 期初仓库燃料＋期初油箱−期末仓库−期末油箱 | 包括模拟实际耗油作业；装入油箱本身不等于消耗 |
| 灌溉 | 账本累计施水体积 × 水服务单价；\(V=10\sum_b d_bH_b\)，d 为 mm | 按服务交付水量计费，效率系数不用于少付水费；已包含约定抽水服务，不再作为拖拉机燃油重复收取 |
| 干燥 | 仓库记录的实际处理吞吐 kg × 固定每 kg 服务费 | 不是“水分降低百分点×吨数”；安全粮跳过处理不收费，不能用是否有干燥标签替代吞吐账本 |
| 药剂 | 各配方实际用量 g／mL × 对应单位价格 | 配方商品量不是有效成分量，也不是喷液／载体水量 |
| 植保服务 | 每次实际处理面积 ha × 服务费，累加所有批次 | 药品费与服务费分开。服务含约定设备／用水／助剂等，不重复计入拖拉机作业费 |
| 排水 | 已接受排水作业的抽水体积 × 服务价 | 仅局部积水小麦；native 日结算量另列，账单按作业收据，不把该报价当实测能耗模型 |
| 甜菜运输 | 每次交售毛重 kg × 运费 | 净根按净重收入、运输按带杂毛重收费；不另计一份同义卡车燃料费 |
| 舍入 | 部分旧题总成本结算至美分的差额 | `accounting_rounding`，不是新增投入 |

常规实现：[OperatingAccounts](../fairy/scenarios/management_extensions/apps/operating_accounts_app.py)、[CropProtectionAccounts](../fairy/scenarios/management_extensions/apps/crop_protection_app.py)、[小麦药剂账本](../fairy/scenarios/management_extensions/apps/winter_wheat_rust_app.py)、[排水账本](../fairy/scenarios/management_extensions/apps/winter_wheat_drainage_app.py)、[甜菜账本](../fairy/scenarios/management_extensions/apps/sugarbeet_accounts_app.py)。多季依据 [SeasonCycle](../fairy/scenarios/management_extensions/apps/season_cycle_app.py) 与 [CropRotation](../fairy/scenarios/management_extensions/apps/crop_rotation_app.py)，累积所有季的实际消耗，季间不自动补满资源。

**成本范围不含**地租、普通人工／家庭劳动机会成本、机械购置折旧与维修、利息、保险、税费，以及未建模的磷钾肥、一般除草与其他未启用植保投入。巡查机器人存在电量和充电约束，但当前运营账本未单独计电费或折旧。外包植保／排水／运输等服务价格可以含其服务劳动，不能因此声称“所有人工已计入”。LLM token 成本也不在农场运营成本内；Tokens 是另一个计算资源指标。

FAO 农场经营预算使用总收入减可变成本的 gross margin 框架，固定成本不在该差额内。本实现的成本项目还受到模拟范围限制，因此论文更准确的名称是 **return over modeled operating costs（扣除已建模运营成本后的收益）**，可说明其为 gross-margin-style 评价；不应直接称 fully costed net profit。外部定义只支持核算结构，不验证本项目具体价格或费用完整性。[FAO：企业与活动预算，第 4 章](https://www.fao.org/4/W7365E/w7365e07.htm)、[Ontario Ministry of Agriculture：生产成本预算指南](https://www.ontario.ca/page/guide-cost-production-budgeting)。

### 4.2 三种特殊核算规则

1. **购种折扣／到货总价两题。** `scenario_multiobjective_seed_discount`、`scenario_multiobjective_seed_total_cost` 的种子成本取 `episode.spent / 100`，即实际购种订单美元付款，包含订单规则中的折扣和运费；未用完种子不在这一列自动冲回。其他投入按实际消耗。不能在描述这两题时声称“所有未用库存都不计成本”。两个 SCN 历史题进入 `rotation` 分支，种子按实际消耗计价。四个旧题最终总成本只结算到美分一次。[common.production_accounts](../fairy/scenarios/management_extensions/common.py)
2. **跨年肥料采购。** 采购扣现金、增加库存；实际施用按期初批次和购入批次 FIFO 计成本。未施肥料保留库存账面价值，采购付款与生产消耗不得再加总一次。提前采购 1.95 CNY/kg、春季 2.05 CNY/kg 是声明的供应合同设定，不能当成实测的跨年价格上涨。[FertilizerMarket](../fairy/scenarios/management_extensions/apps/fertilizer_market_app.py)
3. **接管历史。** 苗期甜菜救援、政策接管等保留已经发生的操作和资源消耗；指标是完整配置账本期的结果，没有统一扣除所有接管前成本。Agent 与 Oracle 使用相同初始化历史，但含共同沉没投入的分母会影响相对成本差。若论文另报告“接管后的增量收益”，须新增有明确起点的增量账本，不能把现有列重命名代替。

### 4.3 作物收入与收益公式

粮食按最终安全入库批次计固定价格价值，甜菜按实际验收净根计销售收入：

\[
R_{grain}=\sum_c p_c M^{stored}_c,\qquad
R_{beet}=p_{root}\sum_j M^{del}_j,
\qquad N=R_{grain}+R_{beet}+B_{paid}-C.
\]

这里 \(N\) 对应代码 `net_operating_margin` 和 CSV `agent/oracle_net_operating_return_usd`，是 USD 金额，**不是**利润率 \(N/R\)。粮食入库价值不要求真实发生现金销售，故 \(N\) 也不是纯现金流。未收粮、未入库粮和未交售甜菜不按“潜在可卖”补记收入。没有秸秆、甜菜叶等副产品收入，也没有残余土壤水氮的终值收益。甜菜暂存净根没有期末存货价值抵补，这也是其与粮食价值确认不同的地方。

政策题 \(B_{paid}\) 只包括通过工具实际领取的补贴；查询、申报、符合理论资格都不等于已经到账。当前留存政策对注册榆树市的大豆采用 550 CNY/亩，对玉米采用 48.95 CNY/亩，按有效面积及固定汇率折算。文件的发布时间影响工具可获取的信息，办理窗口是另行声明的模拟条件；不额外叠加没有实现资格核验的补贴。[吉林 2025 大豆区域政策](https://agri.jl.gov.cn/xczx/lssc/202503/t20250324_3419686.html)、[吉林 2025 最终玉米补贴通知](https://xxgk.jl.gov.cn/zcbm/fgw_98047/xxgkmlqy/202509/t20250910_9318768.html)、[本地政策表](../fairy/scenarios/management_extensions/data/jilin_2025_policy/notices.json)。

L4 的收入、成本及补贴按完整任务期累加，使用固定价，不贴现、不年化。这支持同一场景内 A/O 配对比较，不直接支持不同面积、时长的农场绝对收益排名。若另报单位面积收益，USD/亩 = USD/(ha×15)；跨季年化需另明确占地时间和休耕时间分母，不能只除以作物季数并称“每年”。

### 4.4 两项新增经济评价指标

\[
\mathrm{ROCG}=100\frac{C_A-C_O}{C_O},\qquad
\mathrm{RNRG}=100\frac{N_A-N_O}{N_O}.
\]

- **ROCG：Relative Operating Cost Gap，相对运营成本差额。** 正值比参考更贵；负值更便宜。成本减少须同时满足任务和产量条件，少种或漏收导致的低支出不是成本效率改善。
- **RNRG：Relative Net Operating Return Gap，相对净运营收益差额。** Oracle 收益为正时，正值为收益提高，负值为收益减少。本批 34 个 Oracle 的收益均为正。它不是利润率差、投资回报率或相对最优 regret。
- 分母为零时未定义；CSV 留空，JSON 为 null 并附原因。保留原来的有符号分母；若未来 Oracle 收益为负，方向需查看 USD 绝对差，不能继续简单标“越大越好”。没有加 epsilon 或偷偷取绝对值。
- 分组结果取逐场比值的平均，不是先跨场景合计金额再算比例。所有成本与收益的双方金额、绝对差额也保留供复核。

这两个英文名称是本基准对明确数学量的命名，不声称来自某篇既有指标论文。经济表覆盖 10 场 L3 经营和 5 场 L4 经营，并额外报告实际以净收益为目标的 10 场小麦、1 场甜菜高水价，共 26 场；不会把其余产量题改成利润题。

## 5. 价格表：数值、单位、来源和证据强度

### 5.1 固定 CNY→USD 基准

玉米、大豆及原生 L3 小麦采用 \(1\ \mathrm{USD}=7.1757\ \mathrm{CNY}\)，USD = CNY / 7.1757。该值为人民银行表中的 2025 年 6 月平均数，非月底数、实时汇率或所有生长年份的实际汇率。单位价格保留小数，必要现金结算再四舍五入到美分。[人民银行汇率表](https://www.pbc.gov.cn/diaochatongjisi/attachDir/2025/12/2025121517172677839.pdf)。

价格以 2025 年不同日期、地区的观测、政策和合同设定构成固定实验价格向量；**不是同一农场、同一时点完整调查得到的成本预算**。尤其 2019—2020 小麦天气配 2025 价格，只能描述为固定价格情景下估值，不能写成重现 2020 年实际利润。当前没有 CPI 平减或价格时间序列模型。

| 项目 | 冻结的 CNY 价格 | 对应 USD（约） | 来源及适用边界 |
| --- | ---: | ---: | --- |
| 玉米商品粮 | 2.16/kg | 0.301016/kg | 2025-12-30 长春深加工企业三等玉米收购 2160 元/t；加工企业收购基准，不是农户净到手价 [价格原页](https://grain.jl.gov.cn/ywpd/xqzx/ymsc/202512/t20251231_9386324.html) |
| 大豆商品粮 | 4.32/kg | 0.602032/kg | 2025-06-30 吉林蛟河收购 4320 元/t；不套用进口压榨豆价格 [价格原页](https://grain.jl.gov.cn/ywpd/xqzx/ddsc/202507/t20250704_9273234.html) |
| L3 小麦商品粮 | 2.38/kg | 0.331675/kg | 2025—2026 三等小麦最低收购价 119 元/50 kg；作为估值基准，不推定所有批次符合政策收购资格 [发改价格〔2024〕1405号](https://zfxxgk.ndrc.gov.cn/web/iteminfo.jsp?id=20439) |
| 46% N 尿素 | 2.05/kg 商品 | 0.285686/kg | 2025-06 吉林零售监测；不是 2.05 元/kg N [监测附表15](https://www.chinaprice.cn/zgscjgjcbg/56767.jhtml) |
| 柴油 | 6.63/L | 0.923952/L | 同期吉林 0 号车用柴油零售，单位 L，不是批发吨价 [监测附表13](https://www.chinaprice.cn/zgscjgjcbg/56767.jhtml) |
| 正常灌溉服务 | 0.20/m³ | 0.027872/m³ | **假设报价**；不是统一农业水价或已核验到田报价 |
| 高价灌溉服务（非甜菜） | 0.80/m³ | 0.111487/m³ | **假设报价**；用于高抽水／输送成本压力测试 |
| 干燥服务 | 0.04/kg 处理量 | 0.005574/kg | 取 40 元/t 的成本量级作固定服务设定；不是通用湿度阶梯计价 |
| 小麦种子 | 4.00/kg | 0.557437/kg | **实验报价假设**；45 g/千粒为计数换算，单粒约 0.0000250847 USD |
| 玉米种子 | 80/4200 粒 | 0.00265446/粒 | 政采表的 80 元/亩＋4200 粒/袋，经“一袋/亩”假设换算；不是直接观察到的零售袋价 |
| 大豆种子 | 7.60/kg；0.00152/粒 | 0.000211826/粒 | 公开调研转载的类别代理；200 g/千粒是假设，各 WOFOST 品种使用同一计价代理 |

其中商品含水率、无额外蛋白／品质溢价为模拟估值规则；价格网页不为这些规则背书。除甜菜显式运输外，粮食从田间到加工企业的市场物流费用没有完整建模，不能把加工企业收购基准直接解释为已扣运输的农户价格。

完整机器可读出处见 [china_market_2025.json](../fairy/scenarios/management_extensions/data/china_market_2025.json) 和 [winter_wheat_prices_2025.json](../fairy/scenarios/management_extensions/data/winter_wheat_prices_2025.json)。水服务拆分为 0.056 元/m³ 水源费参照＋0.144 或 0.744 元/m³ 泵送服务假设；保存的 [吉林市水价规则链接](https://xxgk.jlcity.gov.cn/gzbm/fgw_2/xbgkml/202201/t20220120_1014956.html) 本次访问重定向失败，因此不能声称已重新核验原文。0.20/0.80 本来就是合同假设，并非该通知直接报价。

玉米种子来源为 [政府采购报价 PDF](https://www.ccgp-neimenggu.gov.cn/gpx-bid-file/ZF_JGBM_000001/150522/2025/4/7/402881e195a444f001960dd017584af7/gpx-bidconfirm/402881ef967ef7330196858b0099153e.pdf?accessCode=9ac41e475e07bb8eb249a58429c8361f)，本次未重新逐页核查；大豆种子与干燥基准在本地价格表中分别关联 [广发期货调研转载](https://www.7hcn.com/article/471091-1.html)、[永安期货调研转载](https://www.7hcn.com/article/467746-1.html)。这些是已有实现的价格线索，证据等级低于直接价格监测／已核验合同；本次没有把转载升级成原始实测证据。采购折扣 10%、廉价玉米种子 0.018 CNY/粒及 100 CNY 运费同属实验合同条款。

### 5.2 药品和专项服务

| 项目 | 现用价格 | 证据边界 |
| --- | --- | --- |
| Transform WG | 1 CNY/g 配方商品，折合约 0.139359 USD/g | 未核验中国具体商品报价；美国标签提供用量信息，不提供本地价格与真实药效标定 |
| Sefina | 0.5 CNY/mL，约 0.069680 USD/mL | 同上 |
| TebuStar 3.6L | 0.06 CNY/mL，约 0.008362 USD/mL | 同上，不用液体 mL 与固体 g 的单价直接比较 |
| Proline 480SC | 0.30 CNY/mL，约 0.041808 USD/mL | 同上 |
| 大豆植保服务 | 75 CNY/ha，约 10.451942 USD/ha/次 | 地面服务合同假设；不是把无人机报价原样套入 |
| 小麦条锈病戊唑醇商品 | 0.024 USD/mL | 独立固定美元假设；登记标签链接不证明这一市场价格 |
| 小麦条锈病喷施服务 | 32 USD/ha/次 | 独立固定美元假设 |
| 小麦局部排水 | 0.10 USD/m³；泵流量 30 m³/h | 工程服务假设，不是现场标定 |

药剂单位、施用约束、服务成本分别记录于 [蚜虫目录](../fairy/scenarios/management_extensions/data/soybean_aphid_products/catalog.json)、[病害目录](../fairy/scenarios/management_extensions/data/soybean_fungicide_products/catalog.json)、[小麦条锈病配置](../fairy/scenarios/management_extensions/apps/winter_wheat_rust_app.py)。现有美国标签的剂量／安全间隔来源与中国价格代理并存，**不能称为已核验的中国注册用药方案**；本 Methods 不提供现实处方。产品间使用相同的简化药效系数是模拟假设，不能据此推导不同真实商品等效。小麦病害模块也有自己的假设参数，不属于原版 WOFOST 的自动疾病预测。

### 5.3 甜菜及小麦—甜菜轮作：独立假设价格

甜菜使用 `beet_synthetic_economic_assumptions_v1`，**没有 CNY→USD 换算，不能引用前面的汇率或中国价格表作为其价格依据**。两个小麦—甜菜 L4 的前茬小麦也使用该表，不能套 L3 小麦价格。

| 项目 | USD 单价 | 当前来源 |
| --- | ---: | --- |
| 糖厂验收净鲜根 | 0.05/kg | RootContract 固定假设，无市场合同证据 |
| 运输 | 0.004/kg 毛重 | 固定假设，无距离／路线成本模型 |
| 甜菜种子 | 0.002/粒 | 固定假设 |
| 轮作小麦种子 | 0.000025/粒 | 固定假设 |
| 轮作小麦入库粮 | 0.30/kg | 固定假设，不是 L3 小麦的 0.331675 |
| 尿素 | 0.40/kg 商品 | 固定假设 |
| 农机燃料 | 1.10/L | 固定假设 |
| 正常水服务 | 0.08/m³ | 固定假设 |
| 高水价甜菜水服务 | 0.35/m³ | 固定压力测试设定 |
| 轮作粮食干燥 | 0.015/kg 处理量 | 固定假设；单季甜菜没有根部干燥收费 |

依据：[BeetResources](../fairy/scenarios/management_extensions/sugarbeet/resources.py)、[场景价格覆盖](../fairy/scenarios/management_extensions/sugarbeet/scenario.py)、[RootContract](../fairy/scenarios/management_extensions/sugarbeet/contracts.py)。`crop_per_kg['sugarbeet']=0` 不表示甜菜不卖钱：甜菜收入由独立 RootLedger 的交售收据计入，防止与粮食收入重复计算。

**可复算的单位例子（仅解释公式，非实测结果）：** 若 1 ha 甜菜有 10,000 kg 块根干物质，则按当前固定系数得到 50,000 kg 理论鲜根、47,500 kg 实际回收净根。若全部验收，毛重为 47,500/0.92=51,630.435 kg，收入为 2,375 USD，运输成本为 206.522 USD。其余种子、水氮、燃料费用还须继续扣除；不能把 2,375−206.522 称为该田的完整净利润。0.16 含糖比例不进入该收入公式。

## 6. 原生 WOFOST 小麦与甜菜：模型、参数和“校准”证据

### 6.1 实际使用的模型

两者使用 PCSE 6.0.13 中的 `Wofost81_NWLP_CWB_CNB`（运行接口带同日管理合并的 deferred-rate 包装），即水分和氮限制、经典土壤水量平衡、经典氮平衡的 WOFOST 8.1 实现。不是仅温度物候模型，也不是 SNOMIN 多层有机碳氮版本。没有输入时不退回手工产量公式。[PCSE 官方模型清单](https://pcse.readthedocs.io/en/stable/available_models.html)、[原生运行封装](../fairy/physics/wofost_backend.py)。

一块田默认 16 个 100 m × 6.25 m 管理单元，共 1 ha。每个管理单元有独立原生作物／土壤状态，共享气象、时钟、机械和资源账本。小麦成熟由原生状态决定，成熟后保留相应作物状态供收获记账；甜菜使用 harvest 结束机制，由实际起收动作结束作物，不把 DVS=2 当成与小麦相同的自动经济收获目标。[小麦后端](../fairy/scenarios/management_extensions/engines/winter_wheat_wofost.py)、[甜菜／轮作后端](../fairy/scenarios/management_extensions/engines/sugarbeet_wofost.py)。

### 6.2 上游参数来源，不等于本研究本地校准

两种作物参数均固定在 WUR 官方参数库提交 `1ca91d7dbb5aaf6b41462162de03a8254812d3a5`，每次加载核对文件 SHA-256。未修改的基础参数直接继承该文件；场景级土壤／胁迫覆盖另行声明。

| 品种键 | 使用场景 | 上游适用范围 | 物候及初始参数（来自固定 YAML） |
| --- | --- | --- | --- |
| `Winter_wheat_104` | 基础小麦与轮作前茬 | 德国中部、法国北部 | IDSL=2；TSUMEM=120、TSUM1=706、TSUM2=950 °C·d；VERNBASE=8、VERNSAT=41 d；TDWI=50 kg/ha |
| `Winter_wheat_101` | 晚熟与分品种小麦 | 北爱尔兰、苏格兰、英国北部、丹麦 | IDSL=2；TSUMEM=120、TSUM1=543、TSUM2=1194 °C·d；VERNBASE=10、VERNSAT=49 d；TDWI=50 kg/ha |
| `Sugarbeet_601` | 全部甜菜 | 欧洲多个国家，含德国、法北／中部、荷比卢、英爱、丹麦 | IDSL=0；TSUMEM=90、TSUM1=650、TSUM2=1400 °C·d；TDWI=0.51 kg/ha；DVSEND=2 |

`IDSL=2` 表示小麦花前发育含温度、光周期与春化响应；`IDSL=0` 的甜菜仅用温度推进该物候路径。甜菜文件通用变量说明中的“anthesis”不能直接转述为本生产系统第一年收糖块根必须开花；模型阶段名称与实际商品收获阶段要区分。选择 101 形成不同物候，是采用另一上游参数集，不是本研究拟合了一个中国“晚熟品种”。[固定 wheat.yaml](https://raw.githubusercontent.com/ajwdewit/WOFOST_crop_parameters/1ca91d7dbb5aaf6b41462162de03a8254812d3a5/wheat.yaml)、[固定 sugarbeet.yaml](https://raw.githubusercontent.com/ajwdewit/WOFOST_crop_parameters/1ca91d7dbb5aaf6b41462162de03a8254812d3a5/sugarbeet.yaml)。

上游小麦文件关联 Ceglar et al. (2019), *Improving WOFOST model to simulate winter wheat phenology in Europe: Evaluation and effects on yield*, Agricultural Systems 168:168–180，DOI **10.1016/j.agsy.2018.05.002**。该研究在欧洲物候观测与农时基础上校准温度需求；它是参数背景文献，**不是本项目石家庄站点的校准报告**。[WUR 作者机构出版记录](https://research.wur.nl/en/publications/improving-wofost-model-to-simulate-winter-wheat-phenology-in-euro/)。

小麦与甜菜文件还关联 Boons-Prins, de Koning & van Diepen (1993), *Crop-specific simulation parameters for yield forecasting across the European Community*, CABO-TT Simulation Report 32。甜菜 601 的文件元数据说明其欧洲参考播收历，但没有给出本项目中国点位的产量或含糖率拟合误差。本次已核对 WUR 出版记录，报告 PDF 直链访问受限，未声称重新核读完整试验附表。[WUR 报告记录](https://research.wur.nl/en/publications/crop-specific-simulation-parameters-for-yield-forecasting-across-/)。

**当前准确结论：** 原生小麦、甜菜和轮作输入均为 `parameter_status='uncalibrated_reference'`；没有可用于本地独立验证的观测数据集、拟合目标、最优参数文件及 RMSE/NRMSE 报告。不能写“我们根据中国田间试验校准了 WOFOST”，也不能把“官方参数在欧洲有校准背景”改写成“本研究已完成校准”。

### 6.3 气象、地点和土壤

| 输入 | 当前值／来源 | 解释 |
| --- | --- | --- |
| 气象点 | 38.05°N，114.50°E，80 m | 石家庄区域 NASA POWER 网格；不是东北甜菜实测站，也不是田间气象站 |
| 单季小麦 | 2019-10-01 起；播期窗口 10-05 至 10-25 | 基础截止 2020-07-15；本批全部小麦 `late_harvest=true`，实际截止扩至 2020-08-30 |
| 单季甜菜 | 2021-03-20 起；播期 04-01 至 04-20；收获 09-25 至 10-31；任务截止 11-05 | 场景农时，不是站点观测的逐日记录 |
| 轮作 | 2019 秋播小麦→2020 收获→休耕→2021 春播甜菜 | 不重叠的两季，非同年夏收小麦立即播春甜菜 |
| 逐日气象 | Tmin/Tmax/Tmean、降雨、短波辐射、2 m 风速、相对湿度 | 固定 NASA POWER 日序列，下载参数、日期和 SHA 在 manifest |
| 时间 | POWER 日界采用 LST；工具时钟 Asia/Shanghai | 用 LST 日期作为模型日，未声称逐小时转换为中国民用时间；不含小时叶面湿润观测 |

NASA 的 Daily API 明确区分 LST 与 UTC，提供网格日值；使用历史天气驱动不等于田间校准。[NASA POWER Daily API](https://power.larc.nasa.gov/docs/services/api/temporal/daily/)。历史天气“预报”接口使用固定真实序列，是完美信息的参考条件，不能宣称包含真实天气预报误差。小麦晚收扩展是为该参考品种在给定环境中的运行窗口设置，不是当地推荐收获期的实证结果。

本地 manifest：[小麦](../fairy/scenarios/management_extensions/data/winter_wheat_ncp_2019_2020/manifest.json)、[甜菜](../fairy/scenarios/management_extensions/data/sugarbeet_demo/manifest.json)、[轮作](../fairy/scenarios/management_extensions/data/wheat_beet_rotation_demo/manifest.json)。基础土壤和初始条件如下，三套输入沿用同类工程设定，**非该站点土壤剖面实测**：

| 参数 | 数值 | 单位／含义 |
| --- | ---: | --- |
| SMW / SMFCF / SM0 | 0.12 / 0.30 / 0.45 | m³/m³，萎蔫点／田间持水量／饱和含水量 |
| CRAIRC | 0.06 | m³/m³，临界空气含量 |
| SOPE / KSUB / K0 | 10 / 1 / 10 | cm/day，经典水量模型渗透／导水参数 |
| RDMSOL | 120 | cm，土壤允许最大根深 |
| WAV | 20 | cm，初始可用土壤水量；不是 20% 含水率 |
| NAVAILI / NSOILBASE | 40 / 40 | kg N/ha，初始有效氮与基础土壤供氮参数 |
| NSOILBASE_FR | 0.01 | day⁻¹，基础供氮释放比例参数 |
| SMLIM | 0.30 | m³/m³，初始化水分限制参数 |
| CO₂ | 410 | ppm，固定设置 |
| NOTINF / SSI / SSMAX / IFUNRN | 0 / 0 / 0 / 0 | 基础非入渗、地表贮水及相应开关设定；SSI/SSMAX 为 cm |
| 灌溉效率 | 0.85 | 原生灌溉信号的有效入水比例，固定假设 |
| 施氮回收比例 | 0.70 | 管理信号的氮回收参数，固定假设，不等于实测全年氮利用效率 |

原生接口将辐射 MJ/m²/day 转 J/m²/day、降雨 mm 转 cm，按温度和 RH 估计水汽压，并调用 PCSE Penman–Monteith 参考蒸散接口；ET0 等再转 cm/day。肥料实际 kg 按 0.46 转 kg N，再除地块 ha 转成 kg N/ha 传入，模型另应用 0.70 回收设定。水量、纯氮量与价格计量应保持区分。

### 6.4 场景扰动与农艺规则的证据边界

| 扩展 | 当前实现 | 可以支持的结论／不能支持的结论 |
| --- | --- | --- |
| 小麦弱苗与分区水分 | 分块初始氮、水分、土层等人工差异 | 评估识别与分配任务；不代表调查确认的农田异质性 |
| 小麦局部积水 | 指定低洼块改土壤剖面、启用 IOX；2020-05-07 和 05-08 各增加 60 mm 压力测试降雨 | 合成胁迫条件下的排水决策；该场景天气不能称未经修改的 NASA 实况 |
| 小麦条锈病 | 简化潜伏、邻块传播与气象适宜度，影响同化；保护期 13 d，潜伏尺度 8 d 等为固定假设 | 原生生长模型与外加病害代理耦合；无本地病情曲线校准、无产品药效拟合 |
| 甜菜苗期救援 | 初始 WAV=16 cm，公开工具建立播种和 72 kg N/ha 历史，17 天后接管 | 任务历史可追溯；不是观测到的真实干旱试验 |
| 甜菜分区配水 | 一半地块 SMW=0.10、SMFCF=0.24、SM0=0.41、RDMSOL=60 cm、WAV=10 cm | 设定浅层粗质地对照；不是测土数据 |
| 甜菜晚期水氮与收获 | 固定晚氮截止、收前 20 天禁灌、秋收窗口 | 有技术指导的定性支持；具体日期和氮上限仍为场景设计 |

2024 年农业农村部门甜菜后期指导提出收前 20 天停止灌水、后期限制氮肥及秋季适时收获；2026 年春季指导给出华北／东北一般春播时段、2–3 cm 播深等。这些支撑规则的农艺方向，**不能当作 2021 年石家庄田间数据，也不能校准产量、干物质率或糖分响应**。[2024 后期指导](https://www.agri.cn/zx/nyyw/202408/t20240827_8665579.htm)、[2026 春季指导](https://nmj.tongliao.gov.cn/xwzx/jftx/202604/t20260403_1041668.html)。

小麦—甜菜轮作每块地保留同一个原生土壤对象，休耕期继续水氮演化；切换作物不重置土壤。`residue_policy='no_unmodelled_residue_n_credit'`，不凭空增加前茬残体氮收益。当前不能据此宣称已模拟完整残体分解、有机碳氮、病虫轮作效应或现实土壤长期肥力。

### 6.5 哪些系数随管理变，哪些不会

灌溉、施氮、播种和收获时点改变原生土壤水氮、物候、叶面积、同化和最终 TWSO；分块管理通过不同状态产生不同产量。输入品种参数、灌溉效率 0.85、施氮回收 0.70、甜菜干物质率 0.20、固定含糖率 0.16、机械回收率 0.95、扣杂 0.08 **不会因管理策略自动重新拟合或动态变化**。价格也不随天气和产量内生变动，只有预设高水价或供应合同选择造成报价差异。

因此当前甜菜实验可以研究设定条件下水氮管理对块根干物质和固定质量换算产出的影响；不能研究真实管理诱发的含糖率、杂质率、可提取糖或品质价差。若论文要声称“增糖增收”，需要外部质量模型／化验数据及糖厂质量结算规则，目前没有这些证据。

## 7. Oracle baseline 与可复现评价

每个场景、seed、开始时间、构造参数、初始化参数、输入指纹、评价代码摘要和投影配置共同确定 Oracle 缓存。Oracle 通过与 Agent 相同的公开工具执行、资源限制和账本结算；保存执行轨迹及实际数值，再用于逐场配对比较。不能只用静态工作流文件中的手填产量作为数值基线。

甜菜 reference 声明 `best_in_declared_finite_grid`、`global_optimum_proven=false`；其他场景也有固定／有限候选参考流程。准确名称为 **verified reference policy**，或在有候选搜索记录时称 **best policy within the declared candidate set**。Oracle 优化、工作流校正、函数名中的 `calibrating` 不代表 WOFOST 作物参数田间校准。参考策略不是严格可证全局最优，Agent 有小幅更好表现是允许的。

本批基线目录见 [oracle_baseline_catalog.json](../validation_runs/deepseek_thinking_recommended34_20261106/oracle_baseline_catalog.json)。已有 [39 场全精度 Oracle 自回放检查](../validation_runs/management_replay_metrics_20261106/oracle_full_precision_check.json) 验证同策略执行／回放的生物产量、回收产量、成本与收益相对差在 1e-10 容差内为零。此检验说明执行与记账可复现，不验证与真实田间产量一致，也不证明 Oracle 全局最优。

历史轨迹使用当前可匹配代码离线重放，保留参数、时间和错误响应检查；当前批次小麦巡查的随机 UUID 标签只在响应比较时规范化，观测、覆盖范围、时间、电量和状态仍校验。修复说明见 [replay_contract_fix.json](../validation_runs/deepseek_thinking_recommended34_20261106/replay_contract_fix.json)。输入或管理语义发生不兼容变更时须用原实验快照重放，不能为获取分数放宽物理校验。

原始模型记录生成指标的命令：

```bash
env -u USER TMPDIR=/tmp/fairy_management_qwen3_pcse PYTHONPATH="$PWD" \
  .venv/bin/python scripts/replay_management_metrics.py \
  --root validation_runs/deepseek_thinking_recommended34_20261106/runs \
  --out-root validation_runs/deepseek_thinking_recommended34_20261106/metrics \
  --summary-name summary.csv --workers 3
```

上述输出为回放指标层；本批根目录 CSV 在其上合并分组及原始运行元数据，并保留已实际重放验证的巡查修复结果。本次仅从已整理的 CSV 生成 Markdown：

```bash
.venv/bin/python scripts/summarize_management_results.py \
  --summary validation_runs/deepseek_thinking_recommended34_20261106/summary.csv
```

生成器检查 34 个推荐 ID、字段有效性及 68 份 A/O 账本的恒等式；不执行模型、不重新回放、不修改 CSV。结果为 [summary.md](../validation_runs/deepseek_thinking_recommended34_20261106/summary.md)，证据为 [summary_audit.json](../validation_runs/deepseek_thinking_recommended34_20261106/summary_audit.json)。

## 8. 可以写入论文的 Methods 段落

> 本研究构建了包含 34 个管理任务的仿真基准，覆盖单季小麦、单季甜菜、单季经营决策、多季／多作物管理及跨季经营决策。原生小麦与甜菜由 PCSE 6.0.13 的 WOFOST 8.1 水分和氮限制模型驱动。作物参数采用固定提交的 WUR 参考品种数据，配以指定网格的 NASA POWER 逐日气象和显式土壤设定。品种参数未使用本研究中国点位的田间观测重新校准；因此实验评估的是给定仿真机制下的决策表现，而非本地实际产量预测精度。场景级土壤异质性、病害代理及压力测试扰动独立声明。

> 我们对保存的工具轨迹进行离线物理回放，并与相同配置下可执行且通过约束校验的参考策略配对。生物产量使用储藏器官干物质，甜菜由 TWSO 表示；实际回收量由收获账本确定，交售量单独用于甜菜收入。生物产量缺口和回收产量缺口分别定义为 100×(1−Agent/Oracle)。对停止时尚未结束的作物，按固定规则在独立副本中推进生长，不追加管理；回收量及经济账目保留实际执行结束状态。所有指标先逐场计算，再在固定场景集合内等权平均，运行完成且回放有效的任务失败样本仍纳入统计。

> 经济评价以已建模投入与作业成本为边界，计入种子、肥料、燃料、灌溉和干燥，以及场景启用的药剂、植保服务、排水与甜菜运输。常规投入按实际消耗计价，购种题按订单付款核算种子费用，跨年肥料采购按 FIFO 计实际施用成本。粮食按安全入库价值、甜菜按验收净根收入计值；政策题只计实际到账补贴。净运营收益定义为这些收入与补贴之和减运营成本，不含地租、普通人工、折旧及其他未建模费用。我们分别报告相对运营成本差额与相对净运营收益差额，并保留双方绝对金额。玉米、大豆和单季小麦采用冻结的观测／政策价格基准及显式合同假设；甜菜和小麦—甜菜轮作采用独立的假设美元价格。该评价不等同于真实农场完整净利润估计。

以上为项目实现的概述；论文正式版本应在相应句旁引用本章第 5–6 节列出的原始来源，并用补充材料给出完整参数、价目和文件版本。流程指标应另按第 2 节明确 v1/v2 字段与表示差异，不能只写“采用标准 BFCL”。

## 9. 若要提出田间真实性或经济外推结论，仍需补足的证据

下列事项**尚未完成**，是下一阶段验证设计，不能以完成时写进当前 Methods：

| 拟提出的论文结论 | 需要的数据／验证 |
| --- | --- |
| 小麦本地校准与准确预测 | 确定站点与品种；实测播种、出苗、抽穗／开花、成熟、产量、LAI、土壤水氮；用独立年份／处理做验证，报告 n、RMSE、偏差与观测不确定性 |
| 甜菜本地产量及糖产量 | 同站点品种试验、块根干鲜重、干物质率、糖分与杂质化验；独立检验质量模型，不能把 0.20/0.16 固定值当观测 |
| 管理反应可信 | 多水氮处理及管理时间梯度；检验响应曲线和排序，而不只校准一个高产终点；冻结参数后评估新处理 |
| 真实盈利性 | 同地区同年份种子与药品报价、运输路线、糖厂合同、机械／劳动／地租等完整预算；区分现金流、存货价值与经济利润 |
| 参数假设下结果稳健 | 对价格、干物质率、收获率、土壤初始水氮等做预先声明的敏感性分析；每种条件重新建立匹配 Oracle，报告排名与差额变化 |
| 模型比较有统计把握 | 固定版本和场景清单，多次独立运行；按场景配对，报告不确定性。仅对 34 个异质场景 bootstrap 不能替代模型随机重复 |

WUR 的参数选择指南可作为未来物候与生长参数校准顺序的依据，但不能补充并不存在的本项目实测结果。[WUR：A gentle introduction to WOFOST，参数选择与校准附录](https://backend.wur.nl/sites/default/files/2025-10/Gentle-WOFOST-2024.pdf)。

## 10. 证据导航与版本留存

| 证据 | 文件 |
| --- | --- |
| 本批逐场指标与原始报告路径 | [summary.csv](../validation_runs/deepseek_thinking_recommended34_20261106/summary.csv) |
| 按原表字段生成的分组与逐场 Markdown | [summary.md](../validation_runs/deepseek_thinking_recommended34_20261106/summary.md) |
| 表格生成、68 份账本恒等式核验及文件 SHA | [summary_audit.json](../validation_runs/deepseek_thinking_recommended34_20261106/summary_audit.json) |
| 原始文件 SHA 与复制来源 | [manifest.json](../validation_runs/deepseek_thinking_recommended34_20261106/manifest.json)、[original_files_verification.json](../validation_runs/deepseek_thinking_recommended34_20261106/original_files_verification.json) |
| 参数与方法证据快照 | [management-methods-evidence.json](../validation_runs/deepseek_thinking_recommended34_20261106/management-methods-evidence.json) |
| 回放实现与一般使用说明 | [management_replay_metrics.py](../scripts/management_replay_metrics.py)、[management-replay-metrics.md](management-replay-metrics.md) |

当前工作区含未提交的实验实现，单独记录 Git commit 不足以完整复现；应同时保存使用源码、配置与输入的文件摘要及运行快照。本次只增加报告与报告生成工具，没有更改场景、Oracle、价格、作物参数或历史原始记录。
