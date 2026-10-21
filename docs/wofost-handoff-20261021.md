# WOFOST 接入与 L3 迁移交接（2026-10-21）

分支：`codex/wofost-integration-l3-migration`，从 `origin/main` 的 `a7654d8` 创建。

当前交付是可切换的 WOFOST 世界引擎、黑农84工程参考参数、完整季运行器和 L3 迁移入口。**正式90个L3已完成盘点，尚未全部迁移；品种没有完成本地田间标定。** 默认后端仍是 `legacy`，需要显式选择 `wofost`。

## 1. 谁负责什么

采用 PCSE 6.0.x 的 `Wofost81_NWLP_CWB_CNB`，每个已播种垄建立独立原生模型，每天推进一次。没有依赖 WOFOSTGym；它只作为操作与作物模型边界的参考。

| 过程 | 当前负责方 | 接入后的变化 |
|---|---|---|
| 出苗、物候、根系、叶面积、同化、呼吸、器官分配、籽粒干物质 | WOFOST | 替代原简化物候与冠层生长公式 |
| 活跃作物的土壤水分、径流、排水、蒸发、蒸腾、氮平衡 | WOFOST | 使用原生水氮收支，灌溉和施氮进入原生事件 |
| 工具、农机、耗时、燃油、水肥库存、田块几何、共享时钟 | FAIRY | 保留原接口和资源约束 |
| 病虫草压力、药效及观测噪声 | FAIRY | 病虫草压力通过经验系数折减原生总同化量 |
| 土壤温度、地面通行判断 | FAIRY 辅助公式 | WOFOST 不提供本次所需的土壤热过程 |
| 成熟后粮水分、返潮、田间损失、机收损失、干燥与入库 | FAIRY | 以 WOFOST 籽粒干物质为起点计算实际回收量 |
| 品种、土壤、初始水氮、天气 | 配置与外部输入 | 模型不会自动识别本地品种和土壤剖面 |

操作路径：FAIRY 工具检查资源并执行 → 适配器记录动作与单位换算 → 下一日 WOFOST 消费灌溉/施氮事件并计算 → 结果映射到原有状态接口 → 传感器、代理和收获工具继续读取。

WOFOST 模式跳过旧的土壤水分、物候、冠层日更新，避免重复计算。旧状态对象保留作为兼容视图；表层水分目前复用根区平均水分，不能解释为独立的5 cm表土测量。未播种时仍有 FAIRY 辅助土壤过程。当前还没有补齐旧模型播种后逐日冷湿伤苗的等效机制。

主要入口：

- [原生后端与动作桥接](../fairy/physics/wofost_backend.py)、[物理推进分支](../fairy/apps/farm_world/physics_orchestrator.py)、[FarmPhysicsState](../fairy/apps/farm_world/farm_physics_state.py)。
- [品种档案加载与校验](../fairy/physics/wofost_profiles.py)、[检查点](../fairy/scenarios/farm_world_fullseason_v2/farm_checkpoint_state.py)。检查点保存原生输入和天气/动作日志，通过重放恢复；轻量状态快照不能替代完整检查点。
- [CLI](../fairy/cli.py)、[批量 runner](../scripts/iclr_validation_runner.py)、[独立评分来源校验](../fairy/scenarios/fos/provenance.py)、[oracle基线构建](../scripts/build_oracle_baselines.py)。
- [完整季场景类](../fairy/scenarios/farm_world_fullseason_v2/wofost_complete_scenario.py)、[运行器](../scripts/run_wofost_complete_season.py)。

## 2. 黑农84参数是什么来源

当前推荐审查的完整档案是 [`heilongjiang_heinong84_complete_v1.json`](../fairy/physics/data/wofost/profiles/heilongjiang_heinong84_complete_v1.json)，原生名称为 `Heinong84_PublicReference_v1`，只作用于 `HEINONG84`。78项数值完整锁定，缺项报错。**“完整”指可执行参数齐全，不代表78项均经过东北田间标定。**

相对固定版本上游 `Soybean_901`，实际只有3项改变：

| 参数 | 上游 → 当前 | 依据 |
|---|---|---|
| `TBASEM` | 7 → 8 ℃ | 东北大豆研究的出苗基温先验 |
| `TSUM1` | 350 → 500 ℃·d | 哈尔滨2017天气下15组候选筛选 |
| `TSUM2` | 850 → 1100 ℃·d | 同上 |

其余75项沿用上游生理先验，包括光合、叶面积、器官分配、根系和固氮。上游901属于法国北部大豆参数，不能把保留值解释为黑农84实测。`IDSL=0`，尚未标定光周期响应。

[筛选脚本](../scripts/calibrate_wofost_complete_reference.py)以公开资料的出苗至成熟约119天为参考，工程筛选采用119–123天窗口、目标121天；另给“出苗至开花40天”较低权重，这个40天是工程设定，没有黑农84配对实测支持。**产量没有参与选参。** 2018/2019锁定参数复跑，只是跨年天气诊断，缺少配对田间观测，不能称为独立精度验证。

来源可从档案内追溯至[省农科院品种介绍](https://www.haas.cn/cgcyc/info/1231/2141.htm)、[Xu等东北大豆研究](https://essd.copernicus.org/articles/18/2413/2026/essd-18-2413-2026.html)和[固定版本上游参数](https://github.com/ajwdewit/WOFOST_crop_parameters/blob/1ca91d7dbb5aaf6b41462162de03a8254812d3a5/soybean.yaml)。农业≥10℃活动积温与原生 `TSUM1/TSUM2` 的有效温度口径不能直接互换。

已知元数据问题：档案 `parameter_groups.changed` 还列出了 `TEFFMX` 和 `TSUMEM`，但这两项与上游同值；实际数值变化是上述3项。本分支先保持档案指纹，后续版本化修正元数据并重建相关基线。

原有 `heilongjiang_heinong84_literature_v1` 是较早的480/1150跨研究组合，仍保留供比较，不要把它与当前完整档案或旧901结果混用。黑河43已有公开两年物候诊断，但留出年始花至成熟偏短18.1天，尚未发布为可靠的世界引擎品种档案。原L3其余5个品种没有独立完成的原生参数集。

## 3. 完整季现在跑到了哪里

独立完整季配置为 [`complete_harbin_heinong84_v1.json`](../configs/wofost/complete_harbin_heinong84_v1.json)：64垄、1.1 m大垄双行、28.3008亩，5月上旬择土温和墒情播种，深4 cm，株距7.9 cm，约23.02株/m²。假设100%初始成苗。

土壤是声明的120 cm均质壤土：初始VWC 0.28、萎蔫点0.14、田间持水量0.36、饱和0.48。**这是工程假设，不是黑土实测剖面。** 土层上限120 cm也不表示根系从第一天就占满120 cm。

逐日天气使用仓库自带的2017–2019年哈尔滨NASA POWER输入与来源记录。固定肥料配方为纯N 50、P₂O₅ 69、K₂O 36 kg/ha；N按70%回收进入原生模型，P/K目前只有操作和台账，没有原生生长限制反馈。

| 天气与管理 | 实际入库量，13%水分，kg/亩 | 灌溉总量 |
|---|---:|---:|
| 2017历史天气 | 235.23 | 0 mm |
| 2018历史天气 | 177.77 | 0 mm |
| 2019历史天气 | 208.78 | 0 mm |
| 2017每天雨量×0.25，不灌溉 | 117.08 | 0 mm |
| 同一缩雨试验，按需灌溉 | 201.61 | 100 mm |

共9组完整季（正常3年各 managed/rainfed，加缩雨3组）完成64垄播种、成熟、实际收割、干燥、安全入库。正常年管理策略未触发灌溉，因此与rainfed结果相同；提高缩雨组灌水额度也仍只触发100 mm。灌溉策略使用历史未来3日雨量，是回顾性管理试验。

独立审查覆盖84,672条垄日记录，最大日水量残差约1.39×10⁻¹³ mm，并检查真实施肥库存、粮重口径和逐日湿度。完整季设备允许最高25%粮水分收割；旧场景默认18%门槛保留。上述产量属于这套天气、土壤、管理及经验病虫草/回收层的模拟结果，不是本地品种产量预报精度证明。

## 4. 原L3迁移的完成与缺口

[`formal_90_scenario_ids.txt`](../scripts/fullseason/formal_90_scenario_ids.txt)是本轮范围；[盘点脚本](../scripts/audit_wofost_l3_migration.py)只初始化场景、读取oracle声明，不执行农事和日推进。

| 正式L3盘点 | 数量 |
|---|---:|
| 场景总数，均从播种前开始 | 90 |
| 只用黑农84 | 65 |
| 涉及其他品种 | 25 |
| 含混种 | 9 |
| 含补种 | 7 |

类别有重叠。黑农84且不含补种的58个是优先候选，**还需要压力机制审查，不是58个已通过。**

L3切换配置为 [`l3_heinong84_reference_v1.json`](../configs/wofost/l3_heinong84_reference_v1.json)，开启 `require_explicit_cultivar_parameters`：未覆盖品种报错，避免所有品种悄悄套用901。它只指定品种及后端选项，**保留原场景天气和土壤**；不能把独立完整季的120 cm土层和235 kg/亩套到原L3。

两个原L3用当前完整档案实际重放的结果：

| 原场景 | 原固定日历oracle | 只适配收获等待，在全新世界重放 |
|---|---|---|
| `scenario_full_season_hb_base_hn84_std_normal` | 尚未成熟，收获失败 | 增加10天；64垄全收、安全入库、0工具错误 |
| `scenario_full_season_hb_dryr5r6_hn84_water_limit` | 尚未成熟，收获失败 | 增加16天；64垄全收、安全入库、0工具错误 |

收获适配先用现有观测工具等待R8、粮水分≤18%、无雨及可通行，再把新增调用写入静态工作流，在全新世界重放。原调用参数及顺序保留。**前期播种、追肥、灌溉等时机没有随阶段适配；这里只证明收获适配可行。** 旧的901或480/1150实验可能有不同等待日数，不能当成本轮完整档案结果。

当前关键缺口：补种需新建原生作物生命周期并继承水氮；不同品种/混种需独立参数；低肥力和根瘤失败需映射到原生氮库/固氮；原排水修饰需映射到原生水力参数；磷钾、微量元素与冷湿伤苗需明确扩展。旧品种GDD/RUE/收获指数不会自动变成原生参数。

FOS必须使用相同后端、品种、土壤等配置指纹的新oracle/do-nothing基线，不能复用legacy产量分母。**当前未生成并验收全90个WOFOST基线。**

## 5. 密度目前能表达什么

实际密度进入 `TDWI = 120 × 实际密度 / 23 × 初始成苗率`，随后影响叶面积、光合、耗水、需氮及籽粒量。参考密度23应固定；改播种密度时不要同时改这个参考标尺。

[密度诊断脚本](../scripts/check_wofost_density_response.py)已跑9个密度×2种雨量，共18组；使用同一后端参数构造接口、单一均质垄和原生WOFOST，关闭外部病虫草，不计算FAIRY收获损失，无灌溉、固定纯N 50 kg/ha。

| 株/m² | 2017原雨量 | 每天雨量×0.25 |
|---|---:|---:|
| 20 | 290.42 | 135.38 |
| 21 | 290.36 | 134.43 |
| 22 | 290.26 | 133.52 |
| 23 | 290.11 | 132.63 |
| 25 | 289.73 | 130.94 |

单位是kg/亩、13%水分的**生物学籽粒量**，不等于上表实际入库产量。“×0.25”指每天降雨减少75%，其余天气不变，是人工缺水试验。当前模型20–23株在原雨量下基本处于同一平台，缺水时低密度略高；尚无标定过的分枝补偿、耐密性、行距几何和高密度倒伏，不能据此宣布20株或23株最优。

## 6. 安装与复现

以下命令从仓库根目录执行，不需要LLM/API密钥。PCSE需可写缓存；本机复现使用 `env -u USER` 规避已有用户缓存权限问题，这不是模型参数。

同伴已有仓库时，先获取分支：

```bash
git fetch origin
git switch --track origin/codex/wofost-integration-l3-migration
```

```bash
uv sync --locked --extra wofost

# 一组完整64垄2017管理季
env -u USER uv run --locked --extra wofost python \
  scripts/run_wofost_complete_season.py --cases managed \
  --output-dir validation_runs/wofost_reproduced/complete_2017

# 另外年份：同一品种参数，切换仓库自带天气
env -u USER uv run --locked --extra wofost python \
  scripts/run_wofost_complete_season.py --year 2018 --cases managed \
  --output-dir validation_runs/wofost_reproduced/complete_2018

# 合成缺水管理对照
env -u USER uv run --locked --extra wofost python \
  scripts/run_wofost_complete_season.py --rain-multiplier 0.25 \
  --cases managed,rainfed,high_quota \
  --output-dir validation_runs/wofost_reproduced/rain25pct

# 90场景静态盘点
env -u USER uv run --locked --extra wofost python \
  scripts/audit_wofost_l3_migration.py \
  --output validation_runs/wofost_reproduced/l3_inventory.json

# 两个原L3固定日历重放，预期记录成熟前收获失败并返回非零
env -u USER uv run --locked --extra wofost python \
  scripts/run_wofost_l3_comparison.py --backend wofost \
  --wofost-config configs/wofost/l3_heinong84_reference_v1.json \
  --output-dir validation_runs/wofost_reproduced/unchanged_oracle

# 上一步产物保存后，独立运行收获适配及全新世界重放
env -u USER uv run --locked --extra wofost python \
  scripts/run_wofost_profile_validation.py \
  --wofost-config configs/wofost/l3_heinong84_reference_v1.json \
  --source-root validation_runs/wofost_reproduced/unchanged_oracle \
  --output-dir validation_runs/wofost_reproduced/observed_harvest

# 18组密度敏感性诊断
env -u USER uv run --locked --extra wofost python \
  scripts/check_wofost_density_response.py \
  --output-dir validation_runs/wofost_reproduced/density
```

主CLI和批量runner均接受 `--crop-backend wofost --wofost-config configs/wofost/l3_heinong84_reference_v1.json`。直接对旧oracle执行 `--build-oracle --replay` 不会自动适配生育期。评分基线的生成、来源校验与检查点用法见[完整接口文档](wofost-integration.md)。

复现方式以克隆仓库后运行 `uv` 为准；wheel已经成功构建，并检查17项WOFOST参数、天气及观测数据均在包内。wheel不包含仓库级 `scripts/` 和 `configs/`，单独安装wheel不能直接执行以上源码脚本。两个历史运行器的默认天气路径已改为仓库自带2017输入，确认与旧本地产物天气的180天forcing逐项相同。

生成完整季图表/HTML需先准备脚本要求的全部9组 `seasons/` 和 `parameterization/` 目录；额外安装临时绘图库，默认 `wofost` extra不含Matplotlib：

```bash
env -u USER uv run --locked --extra wofost --with matplotlib python \
  scripts/plot_wofost_complete_season.py \
  --output-dir validation_runs/wofost_complete_20261021
```

## 7. 测试与交付范围

本分支提交前重新执行的相关回归：**251 passed**。同一命令又在待提交内容的干净导出副本中运行，仍为**251 passed**；该副本没有历史运行产物，也没有本次排除的本地LLM调试改动。

```bash
env -u USER uv run --locked --extra wofost --with pytest python -m pytest \
  -q --disable-warnings tests/test_wofost_*.py \
  tests/test_crop_backend_provenance.py tests/test_iclr_wofost_options.py \
  tests/test_weather_day_overrides.py tests/test_fairy_migration_smoke.py \
  tests/test_replay_contract.py
```

覆盖原生一致性、逐日桥接、动作与检查点、品种完整性/作用范围、缺参保护、天气覆盖、粮水分门槛、来源指纹、runner选项和legacy回归。此前完整季阶段186项、迁移选项/品种保护23项等是不同时间的分组结果，不与251相加。

干净副本还重新执行了2017年managed完整季：64垄全部成熟、收割、安全入库，仓库6657.10 kg，约235.23 kg/亩，运行器全部收支与状态检查通过。该次临时运行输出也未纳入提交。

此前本地扩展检查曾有 `tests/test_llm_runtime.py::test_a2a_trace_file_excludes_reasoning_without_mutating_sdk_history` 失败，属于A2A推理轨迹检查；该本地测试文件及相关LLM调试改动没有纳入本次提交。本次没有宣称全仓测试通过。

**约6.6 GB运行产物不随分支提交。** `validation_runs/`被Git忽略，里面的CSV、HTML、日志、检查点和报告只存在本机；`rebatch_outputs/`等运行输出也不交付。仓库自带的公开天气、参数、观测证据及其来源属于复现输入，随源码保留。

本机证据目录，可按上述命令重新生成对应结果；刚克隆分支时这些链接不可用：

- [完整季交付](../validation_runs/wofost_complete_20261021/delivery.html)及同目录 `verification.json`、`independent_audit_final.json`、逐垄日表和操作日志。
- [L3迁移报告](../validation_runs/wofost_l3_migration_20261021/migration.html)及同目录 `inventory.json`、`verification.json`、失败原序列与成功适配重放。
- [密度18组结果](../validation_runs/wofost_density_response_20261021/comparison.json)及每组输入、逐日CSV。

## 8. 后续工作优先级

1. 先审查58个黑农84且无补种候选的机制覆盖，逐个建立明确验收：成熟、实际收割、安全入库、资源收支、工具错误和压力方向；不能只看场景默认 `validate()` 成功。
2. 将固定天数农事改为根据实际出苗、DVS、胁迫和粮水分决策，覆盖前期管理。两个已通过的案例目前只适配收获。
3. 将每垄初始肥力、根瘤、排水和前茬影响映射到可审计的原生参数/状态；明确保留扩展的作用位置，补齐冷湿伤苗和补种生命周期。
4. 为其余5个品种建立独立档案，先收集配对物候，再标定叶面积、分配和产量，留独立站年验证。对密度用真实密度试验验证；不要用推荐密度或本次平台内小差异当最优值。
5. 锁定配置版本后批量验收90个场景，重建独立WOFOST oracle/do-nothing基线，再进行代理与FOS比较。公开资料参数、土壤假设和模型结构误差要分别记录。

## 可转发给同伴的短版

> 我把WOFOST接入整理到了 `codex/wofost-integration-l3-migration`。目前可选PCSE/WOFOST逐日计算物候、生物量和水氮，原FAIRY工具、病虫草、观测、收获损失与入库保留。黑农84已有完整78项工程参考参数，但75项沿用上游，尚未田间标定。完整64垄季节与相关251项回归已通过；正式90个L3完成盘点，两个案例通过观测等待完成收获适配（+10/+16天），90个尚未全部迁移。下一步重点是前期管理时机、压力映射、其他品种与补种，再重建WOFOST评分基线。约6.6 GB运行产物没有放入分支，代码、配置、复现输入和命令在，详见 `docs/wofost-handoff-20261021.md`。
