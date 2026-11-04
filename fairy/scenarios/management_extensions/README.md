# 管理扩展场景：阅读入口

当前共31个场景，包含16个玉米／大豆管理场景和15个冬小麦场景。冬小麦的分块农场、现有工具复用及运行方法见 [WINTER_WHEAT.md](WINTER_WHEAT.md)；新增内容仍按L3、App、引擎和评估分别放在本目录。

## 美元核算与2025年中国价格

此前16个玉米／大豆场景的默认任务描述（`detail=true/false`）只提供价格查询入口，不重复列出单价表。基础价格分别通过 `OperatingAccounts.get_accounts`、`CropRotation.get_crop_options`、`SeasonCycle.get_season_ledger`、`SeasonPlanning.get_season_context` 或 `SeedMarket.get_budget` 查询；药剂及服务报价查 `CropProtection.get_products`，肥料供应合同报价和有效期查 `FertilizerMarket.get_offers`，种子采购方案查 `SeedMarket.list_offers`。任务保留经营目标、资源约束与管理指导，具体额度和预算数值从工具查询；实际价格、Oracle管理动作和评估口径不变。

此前16个玉米／大豆拓展场景使用 **USD**；新增冬小麦也使用USD，其独立价格表及自有农机成本核算见冬小麦说明。本目录以外的旧L1/L2/L3及通用农场工具不改价。所有单价、预算、现金、粮值和经营收益使用同一固定汇率：**1 USD = 7.1757 CNY**（中国人民银行公布的2025年6月美元兑人民币月均值）。这是实验固定口径，不重建2019/2024/2026年各自的历史价格或汇率。

- `china_market_prices.py`：人民币到美元换算及工具账本使用的固定基础价格。
- `data/china_market_2025.json`：每项人民币原价、资料日期、链接、计量单位；实测价格、类别代理和合同估价分别注明。
- `evaluation/oracle_comparison.py`：成本、粮值、净收益以及同作物/同年份产量的带符号对比。

| 项目 | 人民币基准 | USD单价 | 口径 |
| --- | ---: | ---: | --- |
| 46%N尿素产品 | 2.05元/kg | 0.285686/kg | 吉林2025年6月，按产品kg而不是纯氮kg |
| 0号柴油 | 6.63元/L | 0.923952/L | 吉林2025年6月零售监测 |
| 普通到田灌溉服务 | 0.20元/m³ | 0.027872/m³ | 明示供水+抽水服务合同估价 |
| 高水价田到田灌溉服务 | 0.80元/m³ | 0.111487/m³ | 更高抽水成本的合同估价，不是全省统一农业水价 |
| 玉米播种种子 | 采用80元/4200粒的计价假设 | 0.002654461/粒 | 东北2025年采购表为80元/亩、4200粒/袋；按一亩一袋折算，非直接零售袋价，更非WUR品种报价 |
| 大豆播种种子 | 7.60元/kg，按200g/千粒 | 0.000211826/粒 | 黑龙江2025年调研零售类别代理；千粒重为计价假设，不改作物参数 |
| 玉米入库粮 | 2.16元/kg | 0.301016/kg | 长春2025年末三等粮收购基准，按模型14%商品水分口径计值 |
| 大豆入库粮 | 4.32元/kg | 0.602032/kg | 蛟河2025年6月收购基准，按模型13%商品水分口径计值 |
| 实际干燥吞吐 | 40元/吨 | 0.005574/kg | 四平2025年走访成本量级，任务采用固定按吞吐结算的服务假设 |

吉林水价资料区分渠首供水费和实际抽水油/电费；本任务到田服务报价包含后者，不再作为拖拉机燃油重复收费。物理额度仍是上限，不强迫用满，也不虚构超额阶梯收费。干燥按实际处理量计费，安全粮跳过干燥不收费；固定40元/吨不是所有含水率通用的市场降水点报价。

采购题保留商业比较：大豆种子明示九折合同；玉米比较单价加运费的到货总价；跨年尿素提前合同1.95元/kg、春季2.05元/kg，均转USD。这些折扣/供货条款是以中国价格量级设定的任务合同，不能写成真实历史行情。购种现金上限与全季投入成本上限分别公布（玉米2000/6000 CNY，大豆1500/3500 CNY，均折USD）；采购现金支出与费用口径通过各自账本说明，剩余初始库存不重复收费。政策原文及`amount_yuan`保留CNY，凭证同时给`amount_usd`；实际领取的补贴仅转USD入账一次。

植保目录仍保留原有美国商品与厂商说明，**未取得这些SKU的2025年东北成交价**；药品及75元/ha地面服务费为明确估价，以中国公开采购成本量级交叉检查。不能把这些价格或品种称为中国本地登记/成交验证，更没有改动模型药效。来源与限制见价格表及两个药品目录。

最终运行报告 `evaluation.validation.metadata.oracle_comparison` 给出：

```text
relative_difference     = (agent - oracle) / oracle
relative_difference_pct = 100 * (agent - oracle) / oracle
```

正数表示 Agent 的数值更高。Oracle 为零时比例为 `null`。Oracle 为负时保留原公式，报告同时给出差额和负分母标志。

拓展报告沿用回放表 `yield_loss(%)` 和 `recovered_yield_loss(%)` 的两套产量：

```text
yield_loss_pct           = 100 * (1 - agent_biological_kg / oracle_biological_kg)
recovered_yield_loss_pct = 100 * (1 - agent_recovered_kg / oracle_recovered_kg)
```

生物产量是模拟器的籽粒干物质。尚未成熟的作物在独立副本上逐日推进，最多 180 天且限于当季有效期限，取达到成熟或到达上限时的产量。收获产量取原轨迹中实际收获并折到市场含水率的公斤数，未收获的地块计零。两者均使用实际垄或地块面积，Agent 超过 Oracle 时为负，Oracle 为零或数据缺失时为 `null`。

单作物报告给出两项总比例，多作物分别看 `yield_loss_pct_by_crop` 和 `recovered_yield_loss_pct_by_crop`。跨年按同年同作物配对，同作物的年份集合一致时各自合计公斤数再比较。每季结果见 `oracle_comparison.seasons`，入库重量差异单列 `stored_yield_loss_pct_by_crop`。

改价会改变最优决策，因此当前Oracle需要匹配本美元价格表重新评估、执行和新实例回放。搜索证据与每场参考一起标识，不称为全局最优。以前的DeepSeek/OpenAI结果保持原价原样；若另作美元重估，必须标明旧决策是在旧价格下产生，不能当成新价格下重新调用模型的实验。

本次美元价格的16场Oracle指标、亩产、每亩每季成本和回放证据见 [USD_ORACLE_METRICS.txt](../../../validation_runs/management_usd_china_2025_20261103_220138/USD_ORACLE_METRICS.txt)，机器可读版本为同目录 `USD_ORACLE_METRICS.json`。16场Oracle均重新执行并通过回放，相关137项测试通过；此次没有重新调用模型，报告中的Oracle自回放比例为零。

## 任务描述的粒度

此前16个玉米／大豆场景的默认任务描述仅保留面积、垄距的具体数值。`detail=false`给出目标、必要情境与查询入口；`detail=true`增加观测、判断、处理、响应后复查的指导，保留每场的采购、选药、政策、跨季或产量目标，不预告Oracle日期、剂量、品种答案或未来收益。具体播种参数、额度、报价、年度日程与验收数值从现有工具读取。冠层和营养代理值不能当成独立养分化验；根区工具返回土壤氮模型估计时须核对来源、日期与覆盖。

为避免移走数字后信息不可查询，`OperatingAccounts.get_accounts`补充既有截止时间，`SeasonCycle.get_season_ledger`补充既有季节计划与总额度，原四场的`Field.get_crop_capabilities`统一提供既有验收目标。只是查询信息的补齐，价格、物理规则、Oracle管理动作及评估条件不变。当前Oracle仍是冻结的有限搜索参考，不因本次描述修改自动变为观测分支策略。

## 具体场景

- `L3/scenario_joint_maize_soybean_operating_margin.py`：玉米、大豆联合经营。
- `L4/scenario_two_year_maize_soil_carryover.py`：同田两年玉米，状态跨年延续。

具体场景直接继承项目现有的 `Scenario`，没有新增场景基类、配置框架或组装层。
每个文件依次包含：具体资源和环境参数、实测参考、初始化、题设、App 创建和连接、评估入口、输入指纹、完整 `build_events_flow()`。
Oracle 的动作、参数、依赖和步骤说明直接写在场景文件中；当前步数见每个文件的 `ORACLE_REFERENCE.workflow_steps`。
输入指纹序列化中的 `plan` 键保留历史格式以兼容已验证参考，不再对应任何 Plan 类。

## 独立文件为什么保留

| 文件 | 独立职责 |
| --- | --- |
| `apps/season_cycle_app.py` | `SeasonCycle` 提供结季、开季、账本工具；`AnnualCropSeason` 定义这些工具需要检查的日期与额度 |
| `apps/operating_accounts_app.py` | `OperatingAccounts` 提供成本与收益查询；`OperatingPrices` 是其计价输入 |
| `apps/shared_irrigation_app.py` | 在现有灌溉操作前检查共同供水额度 |
| `engines/continuous_wofost.py` | 保持原生 WOFOST 模型、土壤、逐日状态与跨季检查点 |
| `evaluation/operating_profit.py` | 经营任务的可行性、消耗平衡和收益差距 |
| `evaluation/multi_season_yield.py` | 季节账本、资源守恒和带符号 YieldLoss |

普通农场工具仍从 `fairy/apps/` 复用。此前四个管理场景及其依赖保留原入口。
新场景放进对应的 `L3/` 或 `L4/`，直接声明自己的任务、初始化和 Oracle；仅在需要业务机制时使用这些 App。
本目录 `__init__.py` 的 `SCENARIO_MODULES` 负责注册。

## 运行与证据

继续使用现成入口：

```bash
.venv/bin/python -m fairy.cli \
  --scenario scenario_l3_joint_maize_soybean_operating_margin \
  --build-oracle --replay --evaluate \
  --output-dir validation_runs/joint_crop_check
```

`ORACLE_REFERENCE` 保存运行评分需要的实测参考和搜索范围，不声称全局最优。
完整搜索记录保存在 `validation_runs/management_v2_development_20261102/`；
搬迁后的原始参考保存在 `validation_runs/management_layout_20261103/*_search_reference.json`。
本次简化的前后状态与工作流对照保存在 `validation_runs/management_flatten_20261103/`。

`management_oracles.py` 和 `oracle_management_plans.py` 只用于离线探索与验证，复用现有 Engine；
实际运行执行场景文件里的冻结 Oracle。它们不承担场景初始化。
`continuous_wofost.py` 保留同作物年度周期；新 `crop_rotation_wofost.py` 在同一原生土壤上切换官方玉米/大豆参数，并逐季记录作物身份用于检查点重建。目前不包含稻田切换、雪/冻土、残茬分解或人为固氮奖励。


## 新增五个官方参数场景

| 层级 | 场景 ID / 文件 | 实际考察的管理 |
| --- | --- | --- |
| L3 | `scenario_l3_soybean_high_water_price` / `L3/scenario_soybean_high_water_price.py` | 高水价下灌水的增产与费用；更多水不一定更赚钱 |
| L3 | `scenario_l3_maize_fertilizer_budget_tradeoff` / `L3/scenario_maize_fertilizer_budget_tradeoff.py` | 有限肥料产品的基施/追施时机与实际成本 |
| L4 | `scenario_l4_maize_fertilizer_procurement` / `L4/scenario_maize_fertilizer_procurement.py` | 两个日历年的采购现金、有效报价、库存和施肥配置 |
| L4 | `scenario_l4_soybean_predecessor_maize_nutrition` / `L4/scenario_soybean_predecessor_maize_nutrition.py` | 固定大豆前茬后，次年作物与营养投入的经营比较 |
| L4 | `scenario_l4_maize_soybean_policy_choice` / `L4/scenario_maize_soybean_policy_choice.py` | 接手已在生长的首季玉米，完成收储，检索次年政策并实际申领补贴 |

五个场景使用未修改的 WUR `Soybean_901` / `Grain_maize_201`。官方作物数据与自行声明的天气、土壤、经济条件是不同来源；这些场景不声称已经过东北田间标定，不使用“黑农”自定义品种，也不把同一官方大豆文件里的不同生育期品种说成已经标定的不同抗旱品种。

上游：[WOFOST_crop_parameters](https://github.com/ajwdewit/WOFOST_crop_parameters)，固定提交 `1ca91d7dbb5aaf6b41462162de03a8254812d3a5`。本地文件逐字节 SHA256 与该提交一致：

- `fairy/physics/data/wofost/soybean.yaml`：`b65cf37a478542d74564094dc0760c69bd3cda99452eb6e7d327e457f87ba9a9`
- `fairy/physics/data/wofost/maize.yaml`：`f1bf8e3202418f294873bb3236727e07a10cd2b91c297b3660d46341a84f469d`

新业务工具分别在 `apps/fertilizer_market_app.py`、`apps/crop_rotation_app.py`、`apps/crop_subsidy_app.py`；`apps/crop_rotation_farm_app.py` 仅为这些新场景记录真实粮批及干燥处理量，普通 FarmWorldApp/TractorApp 不改动。

政策事实来自冻结的吉林省官方公告：2025-03-24 已公布分区大豆补贴，2025-09-10 才公布最终玉米补贴。公告按模拟时钟可见，未检索/未申请/未实际领取均不能提前记收入。农场登记身份与申领办理日期是明确写出的模拟条件，不能冒充公告规定。该场景不是“有补贴就必须换大豆”：比较的是给定历史实现下实际净收益，冻结 Oracle 是有限候选中的事后收益参照，不能当成春播时已知道未来补贴的在线策略。

每个场景的 `ORACLE_REFERENCE.scope` 列出实际搜索范围；完整动作直接看同一文件的 `build_events_flow()`。`detailed_briefing=True` 给分阶段作业建议与核查条件，不预告未来产量/最终收益。对照必须是真实可执行、完成收储的管理方案；报错中断不作为“农业损失”的证据。

开发搜索与被否决的假设保留在 `validation_runs/official_five_scenarios_20261103/`；独立审查、修正记录和重新回放在 `validation_runs/official_scenario_audit_20261103/`。只有逐场验收通过后才加入本目录 `SCENARIO_MODULES`。

验证单个已注册场景（使用现有 Engine，包含构图无副作用、原生执行、保存后新实例回放及状态/评分比对）：

```bash
PYTHONPATH=. .venv/bin/python -m fairy.scenarios.management_extensions.management_oracles verify \
  --scenario scenario_l3_soybean_high_water_price \
  --output validation_runs/soybean_high_water_price_verify
```


## 单场大豆虫害选药（新增L3）

`L3/scenario_soybean_pesticide_choice.py`，ID：`scenario_l3_soybean_pesticide_choice`。
一个大豆地块正常种植后出现虫害，Agent需要查询两种真实产品、购买商品制剂、选择合规处理与轮换窗口，并完成成熟收储。已有政策场景不重复计为新增。

- 官方品种Soybean_901；真实产品为Transform WG与Sefina Inscalis，保留的厂商资料和单位换算在`data/soybean_aphid_products/`。
- `apps/crop_protection_app.py`负责具名产品库存、实际费用及施用限制；其中成本和拖拉机适配仅用于新增植保场景（虫害及病害）。虫害事件及生长耦合直接复用现有接口，未新建作物引擎或评分框架。
- 完整Oracle直接在场景文件内；当前美元参考、实际步数及有限候选范围看同文件的 `ORACLE_REFERENCE`。改价前的47条最终候选和DEMO结果仅保留为历史证据。
- 场景报价是明确的模拟报价，两药采用同一经验防治效果，不宣称其真实药效相同；官方数据、药品资料和模拟假设分别记录。2019用于气象驱动历法，不复原当年产品信息可见时间线。
- 验证和错误管理损失记录：`validation_runs/soybean_pesticide_choice_20261103/REVIEW.md`。原生与新实例回放、施药中途JSON检查点及61项相关回归通过。

使用现有入口：

```bash
.venv/bin/python -m fairy.cli \
  --scenario scenario_l3_soybean_pesticide_choice \
  --build-oracle --replay --evaluate \
  --output-dir validation_runs/soybean_pesticide_choice_check
```


## 本批继续补齐的四个场景

已有政策场景保留，本批不重复计数。加上此前虫害选药，本轮共新增五个；本次补齐下面四个。

| 层级 | 场景 ID / 明确文件名 | 改价前历史有限候选策略（当前参考以场景文件为准） | 历史工具步骤 | 改价前历史入库粮 / 净经营收益DEMO |
| --- | --- | --- | ---: | --- |
| L3 | `scenario_l3_soybean_fungicide_choice` / `L3/scenario_soybean_fungicide_choice.py` | 病后足量TebuStar，按实际天气与最少10天间隔复查、共三次；90mm水计划 | 202 | 大豆1842.88kg / 584.137201 |
| L3 | `scenario_l3_soybean_variety_high_water_price` / `L3/scenario_soybean_variety_high_water_price.py` | 官方Soybean_903，总水30mm分三次 | 82 | 大豆1672.32kg / 502.569600 |
| L4 | `scenario_l4_two_year_crop_nitrogen_allocation` / `L4/scenario_two_year_crop_nitrogen_allocation.py` | 2024大豆0kg肥 → 2025玉米90kg肥；两年都可自由选作物 | 197 | 大豆1109.36kg + 玉米3293.08kg / 1089.142327 |
| L4 | `scenario_l4_two_year_soybean_cyst_rotation` / `L4/scenario_two_year_soybean_cyst_rotation.py` | 2024玉米非寄主 → 2025大豆寄主；真实跨年种群 | 164 | 玉米3372.44kg + 大豆875.92kg / 1084.095927 |

收益依据实际安全入库粮和消耗计价，跨作物产量分别列出。Oracle是有限实测候选中的最好方案：选种41条，病害16条中15条完成，氮肥17条，SCN6条；不是全局最优承诺。所有`detail=true`说明与完整字面`build_events_flow()`就在对应场景文件里，不依赖隐藏的工作流配置或新场景基类。

新增职责：

- `apps/variety_selection_app.py`：播前官方品种选择及其共享农场恢复适配，选择后不能以换种重置作物。
- `apps/crop_protection_app.py`：既有具名植保工具增加目录指定的杀菌剂分支；虫害默认接口和结果不变。两药资料在`data/soybean_fungicide_products/`。
- `apps/scn_monitoring_app.py`：当前模拟土样及SCN农场检查点适配。
- `engines/soybean_cyst_nematode.py`：仅此新SCN题启用的实验种群和每日同化因子，官方WOFOST作物文件不变。寄主/非寄主方向有农学来源，数值繁殖、存活和损失参数未田间校准，不能称为官方SCN模型。
- `engines/crop_rotation_wofost.py`：修正已开次季但尚未播种时的配置恢复；先重建上一季历史，再恢复当前已选作物。`apps/crop_rotation_farm_app.py`只增加实际使用的后端恢复钩子，默认后端不变。

以上数值表是美元改价前的历史记录，不是当前USD参考。

SCN题的最优选择依赖公开的模拟系数及粮价：强损伤斜率敏感性试验中，两季玉米优于玉米后大豆，不能把基准题的轮作Oracle泛化为任何感染田的普遍经济最优。水贵题的三个品种只存在官方生育参数差异，不称为已标定的抗旱品种。杀菌剂TebuStar与Proline同属FRAC3，换商品不是更换作用机制；药价和统一通用药效均明确标为模拟假设。

验收、管理损失对照、检查点修复和逐文件保持证据：`validation_runs/management_remaining_20261103/REVIEW.md`、`SUMMARY.json`。四题均通过原生执行、保存后新实例回放、全部App/RNG比对和JSON检查点；相关管理回归71项通过。两类L4另外分别检查了开季待播和第二季已生长的恢复与下一日。没有改旧场景文件、通用农场/拖拉机、Engine或核心WOFOST方程。

继续使用现成入口，不需要另装项目或修改调用方：

```bash
.venv/bin/python -m fairy.cli \
  --scenario scenario_l4_two_year_soybean_cyst_rotation \
  --build-oracle --replay --evaluate \
  --output-dir validation_runs/scn_rotation_check
```
