# 管理扩展场景：阅读入口

论文方法与统计口径见 [management-extensions-methods.md](../../../docs/management-extensions-methods.md)：包含与既有汇总表一致的指标、成本与收入公式、逐项价格证据，以及小麦／甜菜官方参考参数和未完成本地校准的边界。当前 DeepSeek 推荐 34 场表见 [summary.md](../../../validation_runs/deepseek_thinking_recommended34_20261106/summary.md)。

当前共39个场景，包含16个玉米／大豆管理场景、15个冬小麦场景和8个甜菜管理场景。冬小麦的分块农场及运行方法见 [WINTER_WHEAT.md](WINTER_WHEAT.md)。

按层级、作物结构和经营目标整理的清单见 [SCENARIO_GROUPS.md](SCENARIO_GROUPS.md)，批次筛选可读取 [SCENARIO_GROUPS.json](SCENARIO_GROUPS.json)。默认推荐34场、分成五个互斥主类，另列5个小麦备选（4场待重做、1场待定）；L4多季与多作物管理合并一类。默认运行读取 `recommended_scenario_ids`，注册表保留全部39场供历史回放。

## 甜菜与小麦轮作

| 场景 ID | 任务与优化目标 |
| --- | --- |
| `scenario_l3_sugarbeet_full_season` | 完成春播、管理、起收和交售，最大化验收净鲜根重量 |
| `scenario_l3_sugarbeet_water_limit` | 在共享灌溉额度内最大化验收净鲜根重量 |
| `scenario_l3_sugarbeet_nitrogen_limit` | 在尿素库存限制内最大化验收净鲜根重量 |
| `scenario_l3_sugarbeet_high_water_price` | 按较高灌溉单价最大化净经营收益 |
| `scenario_l4_wheat_sugarbeet_rotation` | 同地冬小麦、休耕、次年春播甜菜。两季达到产量下限后，按验收鲜根、小麦入库量、净经营收益依次排序 |
| `scenario_l3_sugarbeet_seedling_rescue` | 接管已播种、已施基氮但未灌溉的苗期地块，观测缺水并安排救援 |
| `scenario_l3_sugarbeet_soil_water_priority` | 在浅层粗质土与较深土壤分区间分配共享水量，优化验收净鲜根产量 |
| `scenario_l4_wheat_sugarbeet_shared_resources` | 两季共享有限水氮，小麦达到公开最低产出后，按甜菜净鲜根、小麦入库量、收益依次排序 |

默认输入使用石家庄附近的 NASA POWER 历史天气，L3 模拟 2021 年甜菜季，L4 从 2019 年秋播冬小麦持续到 2021 年甜菜交售。两个输入目录各有清单，记录原始来源、文件哈希和农艺假设。WOFOST 使用固定版本的欧洲参考品种 `Sugarbeet_601`。土壤、品质和价格采用试算假设，产量和收益的适用范围为该模拟场景。 [官方品种参数](https://raw.githubusercontent.com/ajwdewit/WOFOST_crop_parameters/1ca91d7dbb5aaf6b41462162de03a8254812d3a5/sugarbeet.yaml)

小麦与甜菜共用分块、天气、时钟、农机、仓库和资源账本。轮作中各分块的原生土壤持续推进并保留水氮状态，入库小麦继续计入账本。甜菜通过 `harvest_roots` 起收，用模型块根干重和固定干物质率计算鲜根，并按扣杂、运力和交售结果结算。晚期施氮、收获前停灌和交售时效由工具检查。

交售完成按每批 0.01 kg 的称重精度检查尾差，任一批超出该范围即验收失败。评估仍记录实际验收量和 `undelivered_root_kg`，并在 `delivery_weighing_tolerance_kg_per_batch` 中公开判定精度。

交售申报量因舍入超出批次余量不超过 0.01 kg 时，工具按实际余量裁剪，并在回执记录 `weighing_adjustment_kg`。收入、运输费和库存均按实际重量结算；超过该精度的超售仍被拒绝。历史失败调用可能因此变为成功，旧轨迹的成功／失败及时间戳契约应按原版本保留，不能视作新版本的严格回放。

```bash
.venv/bin/python -m fairy.cli \
  --scenario scenario_l4_wheat_sugarbeet_rotation \
  --build-oracle --replay --evaluate \
  --output-dir validation_runs/sugarbeet_rotation
```

默认输入和种子 `0` 自动加载指纹匹配的 [Oracle 参考](data/sugarbeet_oracles/)。原四个 L3 场景各比较 24 个策略，原 L4 比较 48 个策略。新增苗期救援、分区水分、跨季资源场景的当前参考分别比较 12、40、16 个策略。分区搜索从初始 12 条扩到 40 条，补查配水份额中间值和边界，最佳净鲜根产量由 2273.72 提升到 2338.36 kg/亩。参考工作流记录有效作业和时钟推进，经过新建场景回放后冻结。产量、收益和投入的比较范围是各场景声明的策略网格。

八场默认 Oracle 的完整工具调用序列直接写在各自 `L3/scenario_sugarbeet_*.py`、`L4/scenario_wheat_sugarbeet_*.py` 的 `build_events_flow()` 中，与冬小麦场景采用相同的 `EventRegisterer.capture_mode`、`capture_step`、`finish_capture` 写法。JSON 保留参考指标、搜索范围和已验证工作流作为核验依据；默认场景的步骤由本文件逐条捕获。显式传入 `reference_file` 时，继续支持加载该自定义参考的公开工具工作流。

`ArableField.get_field_info` 公开每块的萎蔫点、田间持水量、饱和含水量、可扎根深度及土壤假设来源。`inspect_blocks` 返回模型水分、相对可利用水、本季累计纯氮、灌水和播种日期。相对可利用水为 `(SM−SMW)/(SMFCF−SMW)`，截到零至一；它是当前根区含水量的模型参照，不能代替实测总剖面可用水储量。

新增场景沿用原生水氮与作物过程，设定如下：

- 苗期救援使用初始有效水层 16 cm 的工程土壤假设，公开工具完成播种和每公顷 72 kg 纯氮基施，17 天后交给 Agent。先前投入已扣库存并计成本，原时钟继续推进。策略比较响应延迟、灌水触发点和单次水量。
- 分区场景前八块为浅层粗质土（可扎根深度 60 cm），后八块为较深土（120 cm），共享 1000 m³ 灌溉水。策略比较分区水量份额、触发点和单次水量。土壤差异通过各分块独立原生后端产生，不附加手工减产系数。
- 新 L4 共享 300 kg 纯氮对应的尿素产品与 4200 m³ 水；小麦每块原生干物质产量下限 6500 kg/ha。该有效门槛在 `management_objective`、当前 `cycle` 及 `cycles` 日历中一致公开，验收条件保持不变。各季单独氮上限继续有效，休耕和换茬保留土壤状态与未用库存。参考策略比较季间氮和水分配。

这些土壤、资源和验收门槛是可复现的试题假设，尚未田间标定。甜菜干物质率、含糖率和回收率仍是公开的固定外部假设；水氮管理影响原生块根干物质，当前没有声称管理会预测这些品质系数。

验收的 `success` / `operational_success` 表示作业、资源和产量门槛达标；管理表现另列在 `management_performance`。产量分为实际净鲜根量除以可比参考量，允许超过一；收益分为 `1+(实际收益−参考收益)/max(abs(参考收益),1 USD)`，避免负收益参考反转排序。L4 给出按目标顺序排列的三个分数，不合计不同作物公斤数。作业失败或缺少可比参考时不提供目标分数。

甜菜提示分为两档，使用相同目标、约束和公开查询接口：`detailed_briefing=false` 给正常任务情境与交付要求；`true` 在此基础上增加按生育阶段观测、判断水氮需求、安排管理和复查的专家指导。任务文本中不混入评分说明，专家文本不提供 Oracle 的具体日期、剂量、触发阈值、配水比例或预期产量。

专家指导采用[FAO 灌溉调度](https://www.fao.org/4/T7202E/t7202e06.htm)和[明尼苏达大学甜菜养分指南](https://extension.umn.edu/agriculture/crop-production/nutrient-management-for-minnesota-crops/sugarbeet-fertilizer-guidelines)的一般原则，结合本场景可观察的墒情、生育阶段与供氮记录；具体管理按本地场景条件判断。模型未实现的品质变化不被写成可利用的增产机制。

场景与 Oracle 的合理性按农艺过程、信息和约束一致性、资源与质量守恒及公开工具可执行性检查。Oracle 是有限候选中的有效参照；Agent 距离 Oracle 的差距用于观察模型能力和任务难度，不能用来反向修改任务门槛或提供答案。完整两档提示及审查依据见 `validation_runs/sugarbeet_thinking_review_20261105_213642/briefing_review/PROMPTS.md`。此前 13 次 DeepSeek 调用保留其原始提示版本；整理后两档提示的实际模型运行另行记录如下。

新增场景的有限搜索、管理对照与原生公开工具回放见 `validation_runs/sugarbeet_yield_extensions_20261105/`。搜索和复现入口继续使用 `scripts/sugarbeet_oracle.py`、`scripts/run_sugarbeet_suite.py` 及上面的 FAIRY CLI。

只复验全部八场冻结参考，可运行：

```bash
PYTHONPATH=. .venv/bin/python scripts/verify_sugarbeet_references.py \
  --output validation_runs/sugarbeet_reference_check
```

2026-11-05 验证：八场正式 CLI 自回放均通过，目标评分均为一。当前新增三场的参考网格共覆盖 68 条策略；分区新增候选的完整运行、新实例回放和有限范围见 `validation_runs/sugarbeet_thinking_review_20261105_213642/soil_oracle_expanded_search/`。本轮甜菜与工具文档回归 130 项通过。DeepSeek Flash Thinking 的八场首跑、发现的问题及修正后复跑记录在同一审查目录，均设置 `parallel_tool_calls=false`；首跑和修正后的结果分别保留，不能混作同一版本的重复实验。

2026-11-06 整理后提示实跑：8 场 × 任务级／专家级 × DeepSeek Flash Thinking／Qwen3.6-35B-A3B-FP8 NoThinking，共 32 次，每项一次、环境种子 0，均设置 `parallel_tool_calls=false`。DeepSeek 两档各 7/8 通过；Qwen 任务级 4/8、专家级 6/8 通过。7 次任务校验失败及 1 次越期评价异常原样保留，没有重跑挑选成绩，也没有按模型产量调整场景或 Oracle。完整产量、水氮、收益、两档提示、源码／输入快照和原始日志见 `validation_runs/sugarbeet_final_briefings_two_models_20261105_231450/REPORT.md`。

Qwen 初始使用 `http://100.115.106.71:8000/v1`；用户补充的 `http://172.21.1.101:20344/v1`、`http://172.21.1.101:20345/v1` 均确认提供同名模型并支持关闭 Thinking。仅将未启动的 8 场分到新端口，逐场保存实际端点，总次数不变。本轮暴露的评价边界是：模型将时钟推进到季节截止之外后，最终同步抛出异常，未生成结构化 run_report；该场产量保持空值，stderr、工作流和返回码保留，未将其冒充普通任务失败或成功。

独立的交售窗口场景已移出正式列表与默认实验批次。历史场景源码、参考和实验记录可用于追溯此前结果。

场景接受 `input_dir` 和 `reference_file` 构造参数。可用 `python -m scripts.prepare_sugarbeet_inputs --help` 准备自定义输入，使用 `python -m scripts.sugarbeet_oracle --help` 搜索和回放相同输入下的策略。自定义配置可独立验收生产与交售，提供匹配指纹的参考后可比较 Oracle 差额。

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

## 玉米与大豆场景

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

## 39 场景统一回放指标

使用 `scripts/replay_management_metrics.py` 复用主回放的 KTC/COV/BFCL，输出生物产量缺口、实际回收产量缺口、相对运营成本差额及相对净运营收益差额。旧总表字段保留，并增加逐作物、逐季明细；甜菜分别统计 TWSO 块根干物质与实际起收鲜根。命令、公式、Oracle 自检及指标适用范围见 [管理回放指标说明](../../../docs/management-replay-metrics.md)。
