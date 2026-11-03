# 玉米 L3 扩增：阶段0仓库审计

检查日期：2026-11-03（Asia/Shanghai）。本阶段只审计；未新增生产场景、未修改生产逻辑/参数、未运行模型请求或全季矩阵。本报告不是10个场景的验收报告。

## 结论与建议

当前具备复用的单田 WOFOST 玉米、合法播前合同、真实水氮输入、收储链和 checkpoint 框架，可进入规格阶段；不足以直接承诺10个独立且有效的场景。优先 MZ-W01、MZ-N01 两个最小配对。不要为了凑足10个而把天气变体包装成独立决策。

三个必须先记录的差异：

1. 当前 HEAD **就是交接包锚点 cc00de0**，不是需要回退的其他源码版本；工作树另有已有评分/回放修改，必须保留。
2. 当前 Python **3.12.15**、PCSE **6.0.13**；交接包历史证据使用 **6.0.7**。不能将历史产量与 checkpoint 续跑结果自动视作当前依赖环境验收；不在本阶段降级依赖。
3. 现有核心 maize 场景通过 `configure_reference_briefing()` 提供参考水肥日程及收获日。可以复用工具/初始化，不能直接复用这份 briefing 来测新场景的自主决策。

## 1. 仓库与已有修改保护

- 路径：`/Users/ouyangkun/PHD/Project/HSCC/FAIRY`。
- 分支：`jev`，跟踪 `origin/jev`。
- HEAD：`cc00de087c4ed73ddedd8023f4796891971a0db5`。
- 提交标题：`Integrate Hybrid modes, native scoring adapters and request diagnostics`。
- 本审计未 fetch、checkout、reset、安装依赖或操作运行中的实验。
- 未发现项目及其祖先路径的 AGENTS.md。
- 完整 dirty 清单、原有变更文件 SHA256、环境及实际工具清单见 `audit_evidence.json`。

开始时已有修改（均保留）：

- `fairy/contracts/cli.py`、`fairy/controllers/engine.py`、`scripts/rebatch_fos_from_traces.py`、`tests/test_replay_contract.py`。
- `fairy/scenarios/crop_challenges/runtime.py`、`artifacts/manifest.json`、6个玉米和4个水稻 `.json.gz` 工件。
- 已删除 `scripts/fullseason/selected_l2_l1_20_30_scenario_ids1.txt`。
- 未跟踪的 `fairy/contracts/score_batch.py`、`fairy/parallel.py`、`tests/test_crop_challenge_calibration_policy.py`、`tests/test_score_batch.py`。

相对历史 cc00de0，本地差异主要在评分、原生回放、并行评分和 crop challenge 校准诊断。没有发现本次之前对玉米 WOFOST backend、核心场景目录、工具门槛或品种文件的未提交修改。HEAD 相同不代表运行环境或 dirty 工作树相同。

## 2. 路径核对与可复用实现

| 内容 | 当前入口 | 结论 |
|---|---|---|
| V2全季约定 | `fairy/scenarios/farm_world_fullseason_v2/FarmARE_L3_scenario_CN.md`、`full_season_scenarios.md` | 存在，作为流程与职责参考 |
| WOFOST大豆参考 | `fairy/scenarios/wofost/scenario_full_season_hb_base_hn84_std_normal_V2.py` | 存在；不能直接移植大豆病虫系数 |
| 玉米原生L3 | `fairy/scenarios/maize/scenario_full_season_maize_{normal,water_limit,nitrogen_limit}.py` | 注册为 `scenario_maize_l3_*`，三项均已初始化核验 |
| 玉米初始化/流程 | `maize_scenario_helpers.py`、`maize_scenario_catalog.py`（同目录） | backend强制WOFOST/Grain_maize_201，显式水肥库存/预算/天气 |
| 原生模型绑定 | `fairy/physics/wofost_backend.py` | PCSE `Wofost81_NWLP_CWB_CNB`，DeferredRateModel逐日积分 |
| 参数溯源 | `fairy/physics/data/wofost/maize.yaml`、`maize.provenance.json` | 上游参数提交和SHA已声明，欧洲未本地校准参考品种 |
| 注册 | `fairy/scenarios/registry.py` | 扫描maize等包；新规格必须核对唯一ID |
| 玉米验收 | `fairy/scenarios/maize/validation.py` | 成熟、全垄收获、≤14%水分、实际入库、缓冲区清空等原生判定 |
| 证据构建runner | `scripts/build_maize_scenario_artifacts.py` | 用Engine执行公开Oracle并在真实事件边界导出checkpoint；与生产scenario分离 |
| 通用原生重放 | `scripts/rebatch_fos_from_traces.py`；`fairy/contracts/cli.py` | 后续管线应继续调用CLI，不再复制重放实现 |
| 观察驱动WOFOST参考 | `scripts/compile_wofost_observed_oracle.py`、`scripts/audit_wofost_oracle_management.py` | 现有机制审计/编译入口，不等于交接包的30条玉米留出产物 |
| 玉米checkpoint | `fairy/scenarios/maize/farm_checkpoint_state.py` | schema1、校验和/源码指纹、设备精确状态与RNG恢复 |
| 通用checkpoint | `fairy/scenarios/farm_world_fullseason_v2/farm_checkpoint_state.py` | 原生backend状态、天气发生器/缓存、时钟等导出恢复 |
| 玉米L1/L2 | `fairy/scenarios/maize/l2_l1_splits/_maize_split_common.py` | 真实母轨迹checkpoint恢复，禁止换配置和起始时间 |
| 大豆切分参考 | `fairy/scenarios/farm_world_fullseason_v2/l2_l1_splits/_batch_generated_split_common.py` | 存在；新玉米优先复用玉米专用checkpoint适配 |

注册清单中包含41个带 maize 的ID，含旧简化模型、切片、挑战和多田，**不是41个符合本批目标的独立单田L3**。完整列表见JSON证据。

需明确区分两条作物链：`scenario_single_farm_maize_full_season` 等使用独立简化玉米 `MAIZE_EARLY_2026`（0.65m垄宽），而本批目标的核心 WOFOST 使用 `MAIZE_201/Grain_maize_201`（0.75m垄宽）。不能因名称相近就混用产量、oracle、成熟规则或面积。后者64×268×0.75m = 1.2864ha。

## 3. 实际公开工具与初态

对三个核心原生L3执行 `scenario.setup()` 后检查各App的 `get_tools()`，未推进全季：

- 三者均为64垄、**0垄已播种**；默认准备合同均为 `level, base_fertilize, form_ridges`。
- `FarmWorldApp`：overview、ridge/range state、inventory、crop capabilities、fertigation、dry_grain、store_grain等。
- `SensorApp`：本次三个**单田绑定**实际暴露 `read_root_zone_sensors`、soil/canopy整体和单探头接口。
- `WeatherApp`：current weather、forecast。
- `TractorApp`：实际工具全集见JSON；准备、装载、播种、收获、卸粮工具可复用。
- `FieldOpsApp`：irrigate及旧别名、灌溉日志和手工施药入口；公开不代表适用于玉米，原生玉米不支持的植保动作会拒绝。

不能推广为所有环境都暴露root-zone工具：SensorApp在绑定 `farm_environment` 的共享环境会隐藏该方法，必须每个候选重新查 `get_tools()`。FieldOpsApp实际也不是独立IrrigationApp两项工具过滤后的同一菜单。

当前根区工具返回 root_vwc 和不确定度；源码还允许返回计算的土壤 available/reserve N 估计及覆盖/日期状态。这不是实验室土壤N检测。未播种且原生土壤run未开始时可能是 `not_started`，不能填零。交接规则禁止直接用隐藏NAVAIL/DVS/RFTRA决策，因此新策略不得偷读backend；即便公开估计存在，也应在规格中明确是否允许使用、如何处理播前不可用，而不能默认MZ-N02已具备播前可辨识性。

## 4. 原生模型通路和执行边界

- 品种：仅 `Grain_maize_201`；provenance明确为未本地校准欧洲参考。哈尔滨合成天气不等于东北校准。
- 氧胁迫：maize.yaml的 `IOX=0`；不能声明真实渍涝恢复收益。
- 水分：公开FieldOps灌溉按5mm/垄/小时换算，核对配额和VWC门槛，管理动作排队进入原生日积分；配置灌溉效率默认0.92。毛水、有效水、原生日、根区最终存水不能混为一项。
- `effect_ready_at` 在原生路径指向下一日界，并不意味着作物已恢复。IrrigationApp对重复pending有检查，但源码原生分支明确没有调用旧 `set_irrigation_pending()`；因此不能仅见此检查就宣布原生重复请求问题已经消失。阶段2必须用共用执行器验证回执、实际日结算、重复抑制、部分/拒绝结果。
- 氮：肥料产品经含氮率（默认0.46）、面积换算和native `apply_n`，回收系数默认0.7。播前肥料进入首个原生日，不应再次写NAVAILI重复施氮。fertigation允许 `water_mm=0`，可避免氮对照夹带灌水。
- 当前CNB结构不是完整淋失/挥发/反硝化模型；不得预设分施优于一次早施。
- 土层：RDMSOL来自实际root_depth，初始WAV由VWC与可用土层推导；40/100cm改变容量也改变初始水量，不能称纯阈值消融。
- 出苗：原生积温机制；公共播种合法门槛与生理机制应分开。合法不等于有缺水不出苗/湿冷烂种模型。
- 后处理：实际成熟、收获、卸粮、必要干燥和入库可以闭环；固定回收损失不能宣传为干燥时机的动态数量损失。
- 三项产量应分存：成熟TWSO kg DM/ha、回收干物质、全田14%标准入库kg。原生验证结果不能替代这些独立结算值；拒绝投入记0。

## 5. 十个候选逐项判断和去重预审

“支持”仅指实现通路存在，不代表本次已取得E2。以下均需规格与配对准入。

| ID | 当前判断 | 阶段1/2核查与淘汰条件 |
|---|---|---|
| MZ-S01 | 需小实验；可表达播期/季节变化 | 用公开土温/VWC/天气选两个合法播期，全季比较成熟/TWSO；不以工具拒绝代替农艺损失 |
| MZ-S02 | 重复风险高，暂不独立计数 | 必须有与S01不同的准备延迟/剩余季长决策；仅换播种日期则并入S01环境变体 |
| MZ-W01 | 优先；水输入通路支持 | 阈值补灌vs不补灌，同初态预算/观测，完整收储。历史收益需在当前PCSE重新确认 |
| MZ-W02 | 条件支持 | 同毛水、面积、效率；各次都须被工具接受；比较的是完整时序策略，不能单独归因预报/诊断 |
| MZ-W03 | 需小实验，强保产标签不支持 | 同一真实checkpoint分叉、次日允许补救、后续同控制器；历史0.111%不能写显著保产 |
| MZ-W04 | 条件支持；可能只是W01环境变体 | 土层公开证据/初始水量语义明确；每层内独立配对后再判是否有独立阈值适配决策 |
| MZ-W05 | 需小实验；信息价值未证明 | 同环境预测可用/不可用或冻结策略；若结果无差异，保留负结论，不能强立新能力标签 |
| MZ-N01 | 优先；原生施N输入支持 | N60/N120统一基肥/总N口径、同水/预算；不能把默认200kg产品基肥漏出总N账。N0另需显式取消基肥合同 |
| MZ-N02 | 条件候选；播前信息可辨识性待查 | 不泄露隐藏N池；nutrient_index不是N检测，根区估计播前可能不可用。缺少合法公开区分依据时改题/淘汰 |
| MZ-N03 | 条件支持 | 水策略×N量2×2；完整同初态对照确认交互，不能把单因素重复算独立决策 |

阶段0没有足够依据把十项都判为独立通过。S01/S02、W01/W04、W02/W05尤其需去重；W03可能只能保留弱效应/多合理答案。若不足10项，应明确缺口，而不是引入本轮排除的病虫草、多田或自定义损失系数。

## 6. 历史证据可核实范围

交接包ZIP只有11份说明/模板文件，没有历史5条2017公共工具轨迹、30条留出轨迹、2011田间重建、checkpoint续跑原始结果或逐项哈希。上述数量、0–4.75%、0.111%、18.18%均为交接台账中的历史报告值，**本次没有独立复算确认**。现有通用审计/参考脚本不能自动当作那些历史运行的证明。

后续获得原始产物后，核对：源码/PCSE版本、初态天气哈希、参数、公开工具菜单、实际接受水N、原生日、成熟TWSO、回收/入库量、留出是否用于改规则。无法确认的继续列“历史报告、未独立复核”。本阶段不查外部文献，不新增E3农艺声明；规格阶段需补候选适用条件与农艺来源。

## 7. 本次验证与未验证项目

已执行：

- 环境/工作树、引用路径和注册检查。
- 三个核心L3 setup后实际工具菜单、准备合同和未播种初态检查；详见 `audit_evidence.json`。
- `.venv/bin/python -m pytest -q tests/test_field_preparation_contract.py tests/test_native_maize_tools.py`：**40 passed，81条既有依赖warning，0.86秒**；完整日志 `audit_tests.log`。
- 测试覆盖显式无基肥合同、旧默认基肥要求、原生玉米合法种子/设备、水日界回执、成熟收获/干物质14%转换、无效植保拒绝等。它们不是十候选完整季配对验收。

未执行：新候选规格实现、MZ-W01/N01完整配对、全季成熟产量重算、待生效动作checkpoint跨进程续跑、PCSE版本差异定量复现、历史轨迹原始证据复核。既有测试文件中有checkpoint/同输入native parity测试，但本次未运行其全季用例，不能写成本次通过。

## 8. 下一阶段交付顺序

1. 十份候选规格和去重结果；明确不支持/待验证项，冻结开发环境和未接触的留出分组。
2. 先W01/N01，所有策略共用公开工具执行器；记录准备、实际N/水、pending/重复、成熟与收储。先证明完整流程和公平输入，再讨论赢家。
3. PCSE版本写入运行manifest；历史6.0.7与当前6.0.13不混写。现有checkpoint source_fingerprint主要覆盖spec和两个玉米源码文件，不能单靠它推断PCSE版本兼容。
4. 通过后再逐项筛选其他候选；正式生产scenario与trace runner分离，不将捕获或内部变量读取塞进Agent策略。
5. 母轨迹跨进程恢复（包括pending、天气、PCSE历史、库存设备及RNG）通过后才派生L1/L2。

按START_HERE_CODEX.md的阶段0停止点，本报告完成后先汇报，不自动批量写场景或启动长矩阵。
