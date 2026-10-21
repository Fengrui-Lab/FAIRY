# WOFOST crop backend

FAIRY can use the optional Python [PCSE](https://github.com/ajwdewit/pcse) implementation of WOFOST while keeping its existing agent tools, farm operations, observation layer, and FOS evaluation. The default backend remains `legacy`; selecting `wofost` never silently falls back when PCSE is unavailable.

The selected native model is `Wofost81_NWLP_CWB_CNB`, with daily crop growth, water limitation, nitrogen limitation, a classic water balance, and a classic nitrogen balance. One independent native simulation runs per planted ridge. [WOFOSTGym](https://github.com/Intelligent-Reliable-Autonomous-Systems/WOFOSTGym) is a useful reference for the action/environment boundary; FAIRY integrates PCSE directly and does not require Gym or an RL agent.

## What changes

| Part of FAIRY | With the WOFOST backend |
|---|---|
| Phenology | Native emergence, thermal time, and development stage (`DVS`), mapped to the existing soybean stage labels. |
| Canopy and biomass | Native leaf area, assimilation, respiration, organ partitioning, biomass, and storage-organ dry matter replace the reduced growth model. |
| Soil water and nitrogen | Native CWB/CNB balances provide root-zone water and nitrogen availability for active crops. Auxiliary bare-soil/temperature behavior remains where the native model does not supply it. |
| Biological yield | Native `TWSO` supplies biological storage-organ dry matter. |
| Harvest recovery | FAIRY retains field losses, grain drying, machine losses, market-moisture conversion, harvest tools, and inventory transfers. |
| Agent and tools | Controllers, tool schemas, operation duration, equipment, resource checks, and action history remain FAIRY responsibilities. |
| Observations and biotic pressure | FAIRY retains noisy/sparse sensors, drone/robot observations, weeds, insects, disease, and treatment effects. |

The integration boundary is `FarmWorldApp.configure_crop_backend()` and the existing physics orchestrator. Action tools queue physical inputs; the next daily native step consumes them once. The adapter mirrors selected outputs into existing physics state views so tools and evaluators can keep their interfaces.

## Install and run the complete demo

From the repository root:

```bash
uv sync --extra wofost
uv run --extra wofost python scripts/run_wofost_demo.py
```

Alternatively, install into an existing environment with `python -m pip install -e '.[wofost]'`. The optional dependency is PCSE 6.0.x. The soybean parameter file is bundled with a pinned upstream commit, SHA-256 checksum, and preserved EUPL attribution in [its provenance file](../fairy/physics/data/wofost/provenance.json); no crop-parameter download is needed during a run. PCSE initializes its normal user cache on first import, so the user's cache location must be writable.

The demo needs no API key or LLM. It starts with an explicitly prepared, unplanted field on 2026-05-01, uses the actual `TractorApp` seed-loading and planting tools, applies irrigation through `FieldOpsApp`, applies fertilizer through `TractorApp`, advances the shared `Engine` clock through `SystemApp`, and harvests/unloads through `TractorApp` after maturity and drydown. Irrigation also responds to a scripted root-water threshold. Initial soil and nitrogen are prescribed scenario inputs; historical preparation operations are not reconstructed.

Weather is a complete synthetic constant forecast: mean 22 °C, 20 MJ/m²/day radiation, 55% humidity, 2 m/s wind, and no rain. The static weather bridge derives minimum/maximum temperatures as mean ±5 °C. This demonstrates software integration; its irrigation schedule and yields are not field recommendations or validation evidence.

Outputs:

- `validation_runs/wofost_integration_demo/daily.csv`: native DVS, LAI, biomass, storage-organ dry matter, root water, nitrogen, and FAIRY recovery diagnostics.
- `validation_runs/wofost_integration_demo/summary.json`: success, operation results, native model/configuration provenance, per-ridge native outputs, and recovered yield.

Use `--ridges 4` for a four-ridge run, `--output-dir <directory>` to keep separate results, or `--wofost-config <JSON-file>` to supply backend settings. A successful exit requires actual harvest plus the scheduled irrigation and fertilizer operations. If maturity/harvest is not reached before `--max-days` (default 220), the summary is saved and the script fails.

## Select the backend in existing scenarios

The main CLI accepts `--crop-backend legacy|wofost` and a JSON configuration file:

```bash
uv run --extra wofost python -m fairy.cli \
  -s scenario_full_season_balanced \
  --crop-backend wofost \
  --build-oracle --replay \
  --output-dir validation_runs/wofost_balanced
```

That example starts from bare soil and replays the existing full-season management sequence with its generated weather profile. The original reference workflow was designed for the reduced model; selecting WOFOST does not establish that those timings are optimal under the new model. Existing scenarios that initialize an emerged crop cannot be switched into WOFOST by assigning a stage or LAI: start at sowing, replay the historical forcing/actions, or restore a full WOFOST checkpoint. An unsupported midseason start raises an error.

Example configuration, saved as `wofost-config.json`:

```json
{
  "variety_name": "Soybean_901",
  "latitude_deg": 45.7,
  "longitude_deg": 126.6,
  "elevation_m": 150.0,
  "fertilizer_n_fraction": 0.46,
  "fertilizer_n_recovery": 0.7,
  "irrigation_efficiency": 0.92,
  "initial_available_n_kg_ha": 50.0,
  "external_biotic_coupling": true
}
```

Add `--wofost-config wofost-config.json` to the CLI command. Supplying that file implies `wofost`; explicitly combining it with `legacy` is an error. Scenario constructors also accept `crop_backend="wofost"` and `crop_backend_options={...}`. Direct app users must call `farm.configure_crop_backend("wofost", **options)` before planting or advancing the season.

The full settings are defined in [`WofostConfig`](../fairy/physics/wofost_backend.py). `cultivar_map` maps FAIRY seed labels to bundled native varieties. `cultivar_profile` selects an explicitly scoped, versioned literature transfer (see the Chinese section below). `parameter_overrides` accepts native PCSE crop parameters keyed by FAIRY seed label, or `"*"` for all labels. `soil_overrides` and `site_overrides` accept the corresponding native parameters. Existing legacy GDD, RUE, and harvest-index calibration settings are not automatically converted into WOFOST parameters.

## Use separate FOS oracle baselines

A legacy oracle yield is not a valid reference for a WOFOST run. Build a separate directory using the same backend and JSON configuration as the evaluated run:

```bash
uv run --extra wofost python scripts/build_oracle_baselines.py \
  --scenarios scenario_full_season_balanced \
  --crop-backend wofost \
  --wofost-config wofost-config.json \
  --include-donothing --force \
  --output-dir oracle_baselines_wofost

export FOS_ORACLE_BASELINE_DIR="$PWD/oracle_baselines_wofost"

uv run --extra wofost python -m fairy.cli \
  -s scenario_full_season_balanced \
  --crop-backend wofost --wofost-config wofost-config.json \
  --build-oracle --replay --evaluate \
  --output-dir validation_runs/wofost_balanced_evaluated
```

Then run/evaluate with the same `--crop-backend wofost --wofost-config wofost-config.json` settings. Only scenarios compatible with a sowing start or restored native checkpoint can build WOFOST baselines. The builder applies the same settings to the oracle and the do-nothing run and refuses to publish a WOFOST baseline if native extrapolation fails or a planted ridge has not matured at the cap. Legacy static-weather scenarios may contain radiation inputs outside PCSE's accepted daily range; correct the forcing and its units rather than silently clipping it.

New baseline files, FOS reports, and run reports record `crop_backend_provenance`, including the native model, PCSE version, parameter-file checksum, backend options, static soil assumptions, and a configuration fingerprint. Cached WOFOST comparisons reject missing metadata, a different backend, or a different fingerprint and request baseline regeneration. Untagged historical baseline files remain valid for the legacy backend. If no baseline exists, the existing FOS fallback remains available; that fallback is not an oracle yield comparison.

The rebatch option `--donothing-inline` creates a fresh do-nothing scenario with the replayed backend, options, seed, and scenario/init settings, and validates its provenance before injecting any yields. Direct `evaluate_fos()` callers supplying WOFOST inline do-nothing numbers must also supply matching `donothing_provenance`; untagged inline values are rejected.

## Save and restore a live native crop

Use the full farm checkpoint helpers, rather than treating lightweight `get_state()`/`load_state()` snapshots as a resumable simulation:

```python
from fairy.scenarios.farm_world_fullseason_v2.farm_checkpoint_state import (
    export_farm_checkpoint_state,
    restore_farm_checkpoint_state,
)

checkpoint = export_farm_checkpoint_state(
    farm_world=farm,
    weather_app=weather,
    scenario_id="my_sowing_scenario",
    checkpoint_label="day_30",
)

# Initialize a matching fresh farm/app bundle and its shared Engine clock.
# The clock must start at checkpoint["sim_time"].
restore_farm_checkpoint_state(
    farm_world=fresh_farm,
    weather_app=fresh_weather,
    checkpoint_state=checkpoint,
)
```

The checkpoint is JSON-safe. Its native backend section stores configuration, initial per-ridge specifications, pending native inputs, and the daily weather/action journal. Restoration reconstructs independent native models by replaying that journal. Preserve tractor and other operational-app state separately when resuming a complete operation sequence; the farm checkpoint helper takes only the farm and weather apps. Do not shift a native checkpoint to an unrelated date without the intervening daily forcing.

## 原有 L3 场景的原样切换验证

2026-10-20 对两个现有 formal L3 场景完成了旧模型 / WOFOST 对照：

- `scenario_full_season_hb_base_hn84_std_normal`：黑农84标准密度正常年，242 次工具调用。
- `scenario_full_season_hb_dryr5r6_hn84_water_limit`：黑农84 R5/R6 缺水与水量限制，245 次工具调用。

每个场景只生成一次原 oracle 工具序列，再分别在全新 `legacy` / `wofost` 世界中重放。同一场景的两次重放具有相同工具名称、参数、顺序和依赖指纹。没有修改原场景、增加等待、进行成熟外推，或为了通过而调整品种参数。

四次重放均完成 64 垄播种、成熟、收获和安全入库，工具错误为 0；两次 WOFOST 重放各有 64 个原生模型实例。另通过主 CLI 实际执行了两个 WOFOST oracle，结果一致。这里的通过标准是实际工具返回、作物状态和入库覆盖；两个场景继承的 `validate()` 没有实质检查，不能用其默认 `success=true` 代替这些证据。

| 场景 | 旧模型回收量（kg） | WOFOST 回收量（kg） | 旧模型成熟日期 | WOFOST 成熟日期 |
|---|---:|---:|---|---|
| 正常年 | 8478.85 | 2495.76 | 08-25 至 08-26 | 08-09 |
| 缺水 / 水量限制 | 9053.82 | 3293.45 | 08-24 至 08-25 | 08-09 |

回收量均为各模型输出的商品含水率口径；这些数值是软件验证结果，尚未证明田间准确性。旧模型的生物产量代理和 WOFOST 的干物质产量另有不同质量基础，不能混用。

接口可以原样切换，专家时机仍需审计：正常年 07-05 的原“R1 追肥”在 WOFOST 中已是约 DVS 1.351（近似 R3）；缺水场景 07-29 的原“R5 灌溉”已是约 DVS 1.801（近似 R6）。原定收获仍在 09-10 / 09-01，WOFOST 分别已成熟 32 / 23 天。默认 `Soybean_901` 并未标定为黑农84，旧模型的熟期、产量标定和评分基准不能直接沿用。

可复现整个对照，无需 LLM：

```bash
uv run --extra wofost python scripts/run_wofost_l3_comparison.py \
  --output-dir validation_runs/wofost_l3_comparison
```

[对照脚本](../scripts/run_wofost_l3_comparison.py)默认运行上述两个场景和两个后端；支持 `--scenario <ID>`、`--backend legacy|wofost|both`、`--wofost-config <JSON>`。输出包括 `comparison_summary.json`，以及每次运行的逐日 `daily.csv`、完整 `runtime_log.jsonl`、`errors.json`、`final_state.json` 和严格完成检查。任一严格检查失败时返回非零状态。

实际迁移时：主 CLI 添加 `--crop-backend wofost`；`iclr_validation_runner.py` 可通过 `--scenario-kwargs '{"crop_backend":"wofost"}'` 透传。保留现有其他构造参数，并安装 WOFOST extra。按前文重建独立且配置一致的 oracle / do-nothing 基准；后续先标定本地品种，再审查固定天数对应的生育阶段，逐步改为根据观测阶段、籽粒水分和天气作出操作决策。

## 黑龙江大豆文献候选档案

已提供可选择的 `heilongjiang_heinong84_literature_v1`，配置文件为 [`configs/wofost/harbin_heinong84_literature.json`](../configs/wofost/harbin_heinong84_literature.json)：

```json
{
  "cultivar_profile": "heilongjiang_heinong84_literature_v1"
}
```

可由主 CLI 的 `--wofost-config` 加载，也可在播种前调用 `farm.configure_crop_backend("wofost", cultivar_profile="heilongjiang_heinong84_literature_v1")`。该档案只作用于 `HEINONG84` 标签；其他品种不继承这套参数。默认后端及未选择档案时的原生默认值不变。

这是**面向黑农84继续验证的跨研究候选，不是已率定的黑农84品种文件**。它以固定版本的 `Soybean_901` 提供原生通用参数，按有出处的生育期先验覆盖：

| 参数 | 候选值 | 依据与边界 |
|---|---:|---|
| `TBASEM` / `TEFFMX` | 8 / 22 ℃ | Xu 等（2026）正式版 Table A1 |
| `TSUMEM` | 70 ℃·d | 同上；表中单位简写为 ℃，迁入原生时使用积温语义 |
| `TSUM1` | 480 ℃·d | 同上“中早熟”组；农业农村部把黑农84列为北方春大豆中早熟品种 |
| `TSUM2` | 1150 ℃·d | 孙锡鹏等（2022）海伦研究 Table 2；原表印为 `TMUS2`，按开花至成熟的定义映射 |
| `DTSMTB` / `IDSL` | 保留原生温度响应 / 0 | 明示继承假设，尚无黑农84的温度与光周期率定 |

来源：

- [Xu 等（2026）东北大豆研究](https://essd.copernicus.org/articles/18/2413/2026/)，正式版[全文 XML](https://essd.copernicus.org/articles/18/2413/2026/essd-18-2413-2026.xml)及 [Table A1](https://essd.copernicus.org/articles/18/2413/2026/essd-18-2413-2026-t06.xlsx)。论文采用 PCSE 5.5 / `Wofost72_WLP_CWB`；中早熟组原值为 **480 / 770**。本候选采用海伦的 1150 替代其 770，因此不能声称复现了这篇论文或使用了作者公布的单一品种配置。论文最终精度来自 WOFOST、GRU 和遥感的组合，也不等于单独原生引擎的验证精度。
- [孙锡鹏等（2022）海伦研究](https://www.casb.org.cn/CN/10.11924/j.issn.1000-6850.casb2021-0788)。可核对到 1150 这个事实参数，但可用表格没有完整的原生 `TSUM1`、`DTSMTB` 和具体品种证据。其 `SLATB1=0.014` 与东北论文的 `0.0014` 存在十倍歧义，没有直接导入或擅自修正。
- [省农科院黑农84介绍](https://www.haas.cn/cgcyc/info/1231/2141.htm)给出出苗到成熟约119天；[农业农村部2025年品种目录](https://zys.moa.gov.cn/gzdt/202507/P020251016602773218443.pdf)印刷页185给出平均123天。两者是不同资料中的外部合理性参考，程序不会强制在这些天数成熟。

迁移仅覆盖上述生育期参数，未把7.2的 `AMAXTB` 套入8.1的叶氮相关同化模块，也没有改产量系数、情景土层、密度映射、水肥资源或收获门槛。东北论文的 Table A1 未给出原生 `DTSMTB`；其第3.3.1节的8/37 ℃响应用于另外生成的物候图。验证中将该公式转为原生查表的版本单独标为“推断口径敏感性”，不会隐瞒为论文完整配置。

[`SoybeanCultivarProfile`](../fairy/physics/wofost_profiles.py)保存版本、种子作用范围、参数与研究来源。选择顺序为：原生基底 → 作用于该品种的档案 → 显式 `*` 覆盖 → 显式品种覆盖。文件内容与 SHA-256 进入配置指纹、每垄原生记录和检查点；更换文献来源或参数后，旧档案检查点不能继续使用，oracle基准也应重新生成。所有状态保留 `literature_transfer`、`unvalidated` 和 `uncalibrated` 标记。

原L3的固定日期收获可能早于新候选的自然成熟。此时原工具应拒绝收获，必须按真实观测阶段调整等待和农事时机，不能修改DVS、强制R8或绕过收获门槛。情景生成天气下接近119–123天仅表示初步合理，后续仍需本地多年、多播期的物候、叶面积、土壤和产量观测作独立验证。

### 2026-10-20 实际验证结果

在同一批原始工具序列、天气和土壤下，先比较预先定义的三个候选，没有按目标产量拟合：

| 配置 / 收获策略 | 正常年亩产（kg） | 缺水场景亩产（kg） | 出苗到成熟（正常 / 缺水） |
|---|---:|---:|---|
| 原默认901，原收获日期 | 88.19 | 116.37 | 88 / 88天 |
| 东北中早熟480/770，原生温度表 | 96.28 | 111.32 | 91 / 91天 |
| 东北中早熟480/770，另行推断的8/37 ℃温度表 | 113.39 | 103.86 | 97 / 98天 |
| 本文献组合480/1150，按观测等待可收 | 139.37 | 105.14 | 124 / 121天 |

田块面积按实际64垄计算，为18867.2 m²（28.3008亩）；回收产量均为13%商品含水率。最后一行同时更换了生育期参数和收获时机，不能把与第一行的产量差全部归因于品种参数。另有干物质证据：正常年成熟籽粒干重从1371.23提高至1925.24 kg DM/ha；缺水场景从1708.61降至1423.72 kg DM/ha，并非两个场景统一增加产量。

组合候选的**原样固定日期流程两例均失败**：正常年原09-10、缺水场景原09-01的作物尚未成熟。只等到R8仍失败，正常年初次R8时籽粒约28.02%，超过原工具18%的收割上限。两个失败实验均保留，没有作为成功季产量报告。

[`run_wofost_profile_validation.py`](../scripts/run_wofost_profile_validation.py)增加独立的观测等待验证：先在探索世界完整重放原收割前流程，通过现有的垄状态、天气、土壤和每日时间推进工具，等待全田R8、籽粒≤18%、无雨、土壤可通行。把所有额外调用写成普通静态工作流，再在**全新世界**重放，继续由原收割、干燥和储藏工具检查真实门槛。原有工具名称、参数和先后顺序全部保留；仅首个收割步骤增加对额外观测的依赖，前期农事时间未调整。

- 正常年09-15自然成熟，09-24以16.57%籽粒水分收割；相对旧收割日增加14个真实等待日，最终回收3944.42 kg。
- 缺水场景09-12自然成熟，09-18以17.38%籽粒水分收割；增加17个真实等待日，最终回收2975.64 kg。
- 两例均64垄成熟、收割、干燥至13%并安全入库，64个真实原生实例，工具错误为0。83项品种档案、原生引擎、检查点、同源模型一致性和基准来源检查通过；主CLI也分别实际重放了两个新工作流。

正常年139.37 kg/亩仍低于前述黑农84试验参考；即使去掉全部收获损失，其成熟籽粒也仅对应147.53 kg/亩。因此这是更接近已知熟期的**实验候选**，尚未完成产量率定。正常场景原有土层上限40 cm、密度到初始干物质的近似、8.1同化/氮参数和前期农事时机仍需实测检验。两个场景本来具有不同天气和土壤，产量之差也不等于受控干旱效应。这里未评估FOS，旧901基准不能作为新档案的评分分母。

使用已生成的原工具序列复现两例：

```bash
uv run --extra wofost python scripts/run_wofost_profile_validation.py \
  --wofost-config configs/wofost/harbin_heinong84_literature.json \
  --source-root validation_runs/wofost_l3_switch_20261020/replay_comparison \
  --output-dir validation_runs/wofost_heinong84_profile_check
```

`--source-root`中每个场景的 `canonical_workflow.json` 可由前述 `run_wofost_l3_comparison.py` 生成。结果记录在 `validation_runs/wofost_soybean_research_20261020/`：固定日期的成功/失败对照位于 `screening/`，只等成熟的失败位于 `adaptive_harvest/`，完整可收等待及全新重放位于 `adaptive_harvest_ready/`，另有独立核验、逐日数据和验证报告。

## 独立原生模型与历史天气诊断（2026-10-20）

新增 [`run_wofost_standalone.py`](../scripts/run_wofost_standalone.py)。该脚本不导入 FAIRY，直接运行原生 WOFOST 7.2 水分限制模型；没有农事工具、FAIRY 土壤映射、氮限制、外部病虫草耦合及收获损失。它用于先检查文献参数与气象输入，再检查适配层。

基础配置为 [`standalone_xu2026_hailun.json`](../configs/wofost/standalone_xu2026_hailun.json)，采用 Xu 等正式版 Table A1 的中早熟 **480/770**，以及 Table 2 的中壤土。缺失的通用作物参数由固定提交的官方 `wofost72` 大豆文件补全；没有使用8.1的作物文件冒充7.2。原始文件、扁平参数和逐项出处保存在 [`standalone/`](../fairy/physics/data/wofost/standalone/)。

**这属于公开参数重建，并非完整复现作者实验。** 论文没有提供足以还原整个原生输入的 `DTSMTB`、`IDSL`、`RDMSOL`、`SOPE`、`KSUB`、初始水分等设置。本次显式假设土层120 cm、`SOPE=10`、`KSUB=1` cm/day、初始田间持水量，以及CO₂ 400 ppm；这些不是论文给出的本地实测值。土壤 `K0` 不能代替经典水量平衡所需的 `SOPE/KSUB`。

天气使用海伦、哈尔滨两地点的2017年 NASA POWER 历史逐日数据，包含184个连续日期，原始JSON、请求地址、单位和校验和均有保存。它是**再分析气象和卫星辐射格点数据，不是中国气象站实测序列**。辐射按API实际返回的MJ/m²/day转换为J/m²/day；降水mm转cm。水汽压由日均温和相对湿度近似推导，参考蒸散使用PCSE自身计算。这些输入也不等同于作者的51站天气。

```bash
# 当前项目的PCSE 6环境可直接运行；无FAIRY引擎参与。
uv run --extra wofost python scripts/run_wofost_standalone.py \
  --config configs/wofost/standalone_xu2026_hailun.json \
  --weather validation_runs/wofost_reference_diagnostics_20261020/weather/hailun_2017_pcse.csv \
  --output-dir validation_runs/wofost_standalone_hailun
```

若需按论文标注的PCSE5.5核对，在独立环境安装 `pcse==5.5.6`、`numpy<2` 后运行同一脚本。5.5.6的原生类实际叫 `Wofost72_WLP_FD`，6.0.13叫 `Wofost72_WLP_CWB`；脚本记录实际类、作物/土壤组件和原生配置校验和。没有改模型方程。

海伦2017、5月10日播种、上述120 cm中壤土输入的实际结果：

| 运行时 | 出苗 / 开花 / 成熟 | 出苗到成熟 | 籽粒干重（kg DM/ha） | 折13%水分、损失前（kg/亩） |
|---|---|---:|---:|---:|
| PCSE5.5.6 / 原生7.2 | 05-19 / 07-05 / 08-22 | 95天 | 2473.02 | 189.50 |
| PCSE6.0.13 / 原生7.2 | 05-19 / 07-05 / 08-22 | 95天 | 2476.97 | 189.81 |

两个版本的产量相差约0.16%，不能宣称逐值相同。这里的亩产只是 `TWSO / 0.87 / 15`，不是已收获、干燥并入库的产量；没有配对田间观测，不能据此声称精度合格或已经标定黑农84。未自然成熟的运行会保留末期干物质，但成熟产量换算设为 `null`。

每次运行保存 `daily.csv`、`weather_with_et.csv`、`summary.json`、完整解析输入、管理日历和来源校验和。脚本拒绝缺日、重复日期、无效数值和单位不一致的天气，不补天气、不强制成熟、不乘产量修正系数。

另有两组用于定位问题的受控检查：

1. [`check_wofost_real_weather_parity.py`](../scripts/check_wofost_real_weather_parity.py)把完全相同的海伦历史天气、原生参数交给 FAIRY 适配器和未修改的8.1水氮模型。原默认901及480/1150候选分别在40/120 cm土层对照，共四对；逐日 `DVS/LAI/TAGP/TWSO/SM/NAVAIL` 最大差均为0，成熟状态与时钟检查通过。这说明受测条件下数值桥接一致，不能证明土壤参数映射符合实地。
2. 原生8.1水分版与水氮版使用同一套8.1基底、Xu兼容覆盖、120 cm土层及历史天气，成熟籽粒干重均为3195.76 kg DM/ha；`NFIX_FR=0.8`、初始可用氮50 kg/ha等本次条件下没有出现氮胁迫。因此“打开氮限制必然导致此前低产”不成立。该组保留8.1的原生叶氮同化参数，不能把它与7.2的产量差单独解释成氮效应。

**480/1150跨研究候选在这段真实历史气候下截至10月30日仍未成熟，`DVS≈1.91779`。** 此前合成L3天气中接近119–123天的结果不能作为黑农84适用性证据；候选继续仅供实验，不升级为默认或已率定品种。两个深度的末期籽粒干重也不能当成熟产量报告。

当前诊断材料位于 `validation_runs/wofost_reference_diagnostics_20261020/`：`pcse55_medium_default/`、`pcse60_medium_default/`、`adapter_parity/`、`adapter_parity_901/`、`nitrogen_control/` 和 `sensitivity/`。敏感性矩阵分别改变地点、土层、土类和温度响应；其中8/37 ℃响应是从论文另一物候制图步骤推断的实验口径，**不是作者公开的原生 `DTSMTB`**。深度比较保持相同初始体积含水率，因此初始可用水总量也随土层变化。

32组预先指定的组合均由PCSE5.5.6实际完成（两地点×两深度×两温度响应×四土类）。中壤土结果如下，全部采用480/770，亩产均为13%水分的损失前换算：

| 地点 | 土层 | 原生7 ℃响应：成熟日 / kg/亩 | 推断8/37 ℃响应：成熟日 / kg/亩 |
|---|---:|---|---|
| 海伦 | 40 cm | 08-22 / 114.99 | 09-02 / 134.59 |
| 海伦 | 120 cm | 08-22 / 189.50 | 09-02 / 197.73 |
| 哈尔滨 | 40 cm | 08-17 / 173.25 | 08-24 / 186.52 |
| 哈尔滨 | 120 cm | 08-17 / 184.59 | 08-24 / 195.20 |

矩阵范围为106.38–198.45 kg/亩。受控深度变化没有改变成熟日期，但其产量效应从0到80.34 kg/亩，不能视为通用修正倍率。温度响应变化把成熟推迟7–11天。海伦中壤土的水分胁迫天数（`RFTRA<0.95`）从40 cm的20天减至120 cm的2天；哈尔滨对应5天减至0天。该结果支持优先核实有效土层和初始水分，尚不能直接判定旧L3低产的实际成因。

本次100项WOFOST接口、原生一致性、档案、产量归因、来源与独立运行检查通过；其中17项独立运行检查也在PCSE5.5.6单独通过。

后续率定需要同地点、同品种、同年份的实测出苗/开花/成熟日期，随后才是LAI、生物量及产量，并留出独立年份或站点验证。Xu的20 m产品包含WOFOST、GRU和遥感推断，可以作区域对照，不能当独立田间真值来证明本模型准确。

## 公开观测整理与自动物候率定（2026-10-20）

新增 [`calibrate_wofost_phenology.py`](../scripts/calibrate_wofost_phenology.py)，在前述独立原生运行器上进行显式网格搜索，无需新增依赖。只搜索 `TSUM1/TSUM2`；出苗、温度响应、光周期、土壤和生长参数保持固定。默认 `inspect` 只检查证据，`fit` 使用训练集的物候误差选参数，锁定后才计算验证集；同一站点、年份、品种不能跨训练/验证分组。

### 黑农84：16条真实产量记录，尚无可用于物候拟合的配对记录

[`heinong84_public_evidence_v1.json`](../fairy/physics/data/wofost/observations/heinong84_public_evidence_v1.json)保存两篇论文的16条逐处理观测，区别于品种介绍中的119/123天等聚合参考：

- [Qiao等（2023）哈尔滨黑农84分期播种试验](https://www.aeeisp.com/ddkx/cn/article/pdf/preview/55667413-2ed0-4fff-87ec-a7b452087ab4.pdf)：2021年10个播期，保留Table 3原始产量、籽粒含水率、收获成株数及其±值。产量原口径为12%含水率，干物质换算乘0.88；再除0.87才是13%水分质量。10月5日是统一收割日，不能代替自然成熟日；正文还指出5月24日播种处理未完全成熟。每米成株数是每垄两行合计的收获存留数，不能再次乘2，也不能直接当播种密度。地点文字与印刷坐标、播期间隔正文与表格存在冲突，均保留原值和标记。
- [Yan等（2024）密度与烯效唑试验](https://www.mdpi.com/2073-4395/14/4/754)：2021/2023年各取20、30、40株/m²的清水对照，共6条。两年原表均显示30株/m²产量高于40株/m²，可用于审查密度响应。但论文未给明确的籽粒水分基准、完整播种物候和水肥日程，因此没有擅自转成干物质或13%产量，也没有把7月13日施药事件补成逐年开花日期。

运行已整理的观测清单：

```bash
uv run --extra wofost python scripts/calibrate_wofost_phenology.py \
  --dataset configs/wofost/calibration/heinong84_public_v1.json \
  --output-dir validation_runs/wofost_calibration_20261020/heinong84_inventory
```

实际输出为16条田间产量记录加2条聚合参考，**0条具备当前物候率定所需的完整证据**。`gaps_report.json`逐条列出缺失和地点歧义。若加 `--mode fit`，程序返回非零并保留缺口报告；不会用平均119天补造逐站日期。

[NESDC海伦生育动态旧数据包](https://www.nesdc.org.cn/sdo/detail?id=5fc70e2c042ebb415eebe6f6&subjectCode=5fc727fd042ebb415eebe705)的公开说明书明确包含大豆品种和播种至收获各期，实际覆盖2004–2008；匿名取得了说明书及元数据，原始XLS/ZIP下载要求登录，尚未取得具体观测。较新的海伦2004–2023数据和[CERN AA065](https://www.cnern.org.cn/data/meta?id=16968)为协议共享。这些目录条目不是已取得的黑农84记录，也不能按年份数直接算成大豆站年数。

### 黑河43：真实两年物候持续时间基准

[Jia等（2025）](https://www.mdpi.com/1422-0067/26/7/3362)的公开附表S2含黑河43（Heihe 43，ID303）逐站、逐年阶段持续时间；没有黑农84。[选取的原始记录](../fairy/physics/data/wofost/observations/heihe43_jia2025_v1.json)保留小数天数、单元格定位和NA。方法明确2020/2021均于5月9日播种，黑河站为50°15′N、127°28′E、154 m。

该表没有实际出苗、开花、成熟日历日期。因此使用 `objective="stage_durations"`，直接比较原生 `DOA−DOE`、`DOM−DOA`，不会拿预测DOE加观测持续时间来伪造观测日期。VE/R1/R7映射必须显式说明；R7是主茎至少一个正常豆荚达到成熟荚色，和原生通用成熟状态的比较仍是结构假设，更不等于FAIRY的可收获R8。原表总时长仅作参考，避免两个阶段加总后重复计入目标；NA不自动变成霜前未成熟约束。

实际实验预先固定629组候选（`TSUM1=300..700`、`TSUM2=500..1400`，步长25），只用HH2020选参，HH2021留出。两个年份均用各自NASA POWER历史格点天气；土壤和其他作物参数仍是明确的背景假设。原生7.2 / PCSE6.0.13得到训练集最优网格点 **400/850**，非边界点：

| 年份 / 用途 | 实测VE→R1 | 模拟VE→R1 | 实测R1→R7 | 模拟R1→成熟 |
|---|---:|---:|---:|---:|
| 2020 / 训练 | 41.3天 | 42天 | 75.7天 | 74天 |
| 2021 / 留出 | 30.7天 | 35天 | 81.1天 | 63天 |

原480/770背景参数在两年分别模拟47/71天与41/58天。400/850改善了两个阶段的误差，但留出年的后一个阶段仍偏短18.1天，**不足以发布为已经适配的黑河43档案**，更不能迁给黑农84。仅一个训练年、一个留出年，且实际出苗日、站点气象和R7映射仍有假设，不能把残差直接断言为WOFOST结构错误。看到留出误差后没有再调参追这个年份。

复现实验（使用本次已下载并保存的天气与输入）：

```bash
uv run --extra wofost python scripts/calibrate_wofost_phenology.py \
  --dataset validation_runs/wofost_calibration_20261020/heihe43/dataset.json \
  --output-dir validation_runs/wofost_calibration_20261020/heihe43/reproduced_fit \
  --mode fit
```

结果包含所有候选训练得分、等价最优集合、边界诊断、固定物候口径、来源校验和及分开的训练/验证预测。实际材料集中于 `validation_runs/wofost_calibration_20261020/`；`calibration_assessment.json`为汇总，`heihe43/stage_duration_comparison.csv`为阶段对照，原始论文、附表和数据访问说明在 `sources/`。`heihe43/fetch_weather.py`可按固定站点和年份重新请求公开天气。

当前仍保持实验档案状态。要形成可接入世界引擎的品种新版本，需要在一致温度与阶段口径下解释留出误差，并取得更多独立站年；产量、密度、土壤和氮参数再使用相应观测单独约束。原生7.2与8.1共用 `DVS_Phenology`；其中 `IDSL=1`、`DLO<DLC`允许简单短日照响应，但只影响开花前，不能只打开开关就声称实现完整大豆物候。现有两年数据也不足以同时辨识温度与光周期参数。

本次125项WOFOST检查通过；其中25项率定入口测试也在PCSE5.5.6独立通过。原生合成数据回收参数的测试仅验证软件流程，与上述真实田间留出结果分开记录。

## Scientific and interface limits

- **Cultivars are uncalibrated.** The default `Soybean_901` parameter set is an upstream transfer. All FAIRY seed labels use that default unless explicitly mapped, overridden, or covered by a selected literature profile. A literature profile is still an unvalidated transfer. Local labels such as HEIHE43/HEINONG60 do not establish local cultivar validity. No field accuracy is claimed by this integration.
- **Stage and density mappings are approximations.** DVS thresholds map to FAIRY's soybean V/R labels. Density currently scales initial `TDWI` relative to 40 plants/m² and establishment fraction; it does not implement a validated spacing, canopy-architecture, or density-response model.
- **Surface water is a proxy.** Classic WOFOST `SM` is root-zone moisture. The compatibility view uses it for both root and top water; it is not a simulated 5 cm sensor measurement. Soil temperature and trafficability use auxiliary FAIRY behavior. NDVI, canopy cover/temperature, and nutrient index also remain observation/compatibility proxies.
- **Fertilizer needs actual composition.** Tool metadata preserves fertilizer kg/ridge; the adapter converts `kg × N fraction × 10000 / ridge area` to kg N/ha. Defaults assume 46% nitrogen (urea-equivalent), with 70% recovery. Set the actual fraction/recovery for other products. A normalized legacy fertilizer `amount` is not kg N/ha; a fertilizer-only action does not implicitly add water.
- **Native growth is daily.** Subdaily irrigation/nitrogen is queued for the next native day, rather than immediately running another full crop day. Operations and their resource/time effects still execute through FAIRY tools. Native forcing must be consecutive; rotations and replanting require an explicitly new native season.
- **Biotic coupling is empirical.** FAIRY's weed/insect/disease states optionally multiply native gross assimilation (`PGASS`) before respiration/partitioning. They are not native WOFOST pest population or disease models. Disable this coupling explicitly with `external_biotic_coupling=false` when an experiment requires it.
- **Keep units and yield bases distinct.** The bridge converts daily mean W/m² to MJ/m²/day (`×0.0864`), then to PCSE J/m²/day (`×10⁶`); water mm to cm (`÷10`); and biomass kg/ha to g/m² (`÷10`). Native `TSUM`/`TSUME` follow native temperature-response parameters and are not interchangeable with legacy GDD10. Biological yield is dry matter, whereas recovered yield is reported at market moisture (13% by default), so recovered wet mass can exceed biological dry mass despite harvest losses.

Relevant implementation files: [`wofost_backend.py`](../fairy/physics/wofost_backend.py), [`physics_orchestrator.py`](../fairy/apps/farm_world/physics_orchestrator.py), [`provenance.py`](../fairy/scenarios/fos/provenance.py), and the [native integration tests](../tests/test_wofost_backend.py).

## 黑农84完整工程参考场景 v1

`configs/wofost/complete_harbin_heinong84_v1.json` 是可直接执行的完整场景定义；
`WofostCompleteScenario` 位于
`fairy/scenarios/farm_world_fullseason_v2/wofost_complete_scenario.py`，供普通 Engine
和外部脚本复用。默认从随仓库保存的 NASA POWER 哈尔滨2017年逐日天气运行，不需要
LLM、API key 或运行时下载天气。

```bash
env -u USER uv run --locked --extra wofost python scripts/run_wofost_complete_season.py \
  --output-dir validation_runs/heinong84_complete
```

PCSE 的 `USER` 未设置时使用其临时缓存位置；在已有可写 `~/.pcse` 的普通环境中也可以
直接用 `uv run`。默认同时执行状态管理组与雨养组。`--year 2018`、`--year 2019` 使用
随仓库保存的另外两年天气；`--weather <NASA JSON>` 显式替换天气。
`--rain-multiplier 0.25 --cases managed,rainfed,high_quota` 是明确标注的合成缩雨压力
试验，不代表某年实测旱情。`high_quota` 仅放宽同一管理策略的配额，并不强制无限供水。

### 完整参数与品种身份

- 品种档案：`fairy/physics/data/wofost/profiles/heilongjiang_heinong84_complete_v1.json`。
- 原生身份：`Heinong84_PublicReference_v1`；仅作用于 `HEINONG84`。
- 78项原生参数全部显式保存；缺失任意一项即失败，不静默用901补齐。
  上游通用生理参数的来源仍保留为 `upstream_base_variety=Soybean_901`，便于审计。
- `TBASEM=8`、`TEFFMX=22`、`TSUMEM=70`、`TSUM1=500`、`TSUM2=1100`；两段发育
  使用同一原生7℃有效温度表。仅根据官方119–123天的聚合熟期参照筛选15组物候参数，
  不以产量选择参数。`IDSL=0`，未声称完成本地光周期标定。
- `TDWI=120 kg/ha` 对应明确的23株/m²工程参考密度；实际7.9cm株距约23.0156株/m²。
  SLA、同化、呼吸、分配、固氮等其余生理参数保留原生值。密度响应仅是初始生物量
  缩放，不是最优密度、分枝补偿或倒伏机理。
- 档案为公开资料约束的工程参考，`field_observation_validation=false`。
  2018/2019固定参数天气外推不是独立田间观测验证。

### 场景和操作闭环

64垄、1.1m大垄双行、全田28.3008亩。5月上旬按土壤观测择日播种，假设100%成苗。
土壤为声明的均质壤土假设：120cm、SMW/SMFCF/SM0为0.14/0.36/0.48，初始SM=0.28；
不是实测黑土剖面，也没有把作物最大根深当成土层观测。

全田混合肥产品490.5472kg（260kg/ha）通过真实 `base_fertilize` 的200kg加
`apply_fertilizer` 的剩余量播前投入，合计纯N50kg/ha，70%回收率对应有效N35kg/ha。
产品账保留DAP150、尿素50、氯化钾60kg/ha的N/P₂O₅/K₂O50/69/36组成；当前原生8.1
只有N反馈，P/K及肥料化学形态、侧深施位置仍是账本信息。没有在总配方外重复加200kg。

管理根据实际观测巡检。灌溉要求R1后、RFTRA低于0.9持续两天、未来三天少雨、合适
作业条件及配额，正常湿润年可完全不浇水。使用未来天气的是回顾性政策试验，不是预报
能力验证。未发生氮限制时不自动追肥。除草和施药需巡检触发。

新场景通过 `TractorApp.configure_harvest(max_grain_moisture_pct=25)` 声明湿收设备
能力；旧场景默认18%不变。成熟、无雨、可通行门槛及>18%的额外机器损失仍有效。
所有收割批次卸粮后，全田一次 `dry_grain(13)`、一次 `store_grain`，干燥能力10000kg、
仓储容量20000kg按当前标准水分库存口径检查。干燥耗能、湿粮实际吞吐和小时级过程
未建模。原生籽粒干物质只转换一次到13%标准质量。

实际湿度现作为强制天气输入传到原生模型；UI仍可四舍五入显示，日表的`used_rh_pct`
来自原生天气日志，并用原生VAP独立核对，避免拿源RH与自身比较。

### 固定参数的已执行结果

结果位于 `validation_runs/wofost_complete_20261021/`，亩产按实际仓库量计算，均为13%
标准水分。三年使用同一个品种、密度、土壤、施肥和管理策略，未针对年份重调参数。

| 天气 | 成熟 | 收割 | 入库kg/亩 | 全田入库kg |
|---|---|---|---:|---:|
| 哈尔滨2017 | 9月17日 | 9月29日 | 235.23 | 6657.10 |
| 哈尔滨2018 | 9月7日 | 9月18日 | 177.77 | 5031.04 |
| 哈尔滨2019 | 9月24日 | 9月28日 | 208.78 | 5908.55 |

三年均值207.26kg/亩是本组仿真的结果，不是事先写入的产量目标。2017缩雨至25%的
同环境压力试验：雨养117.08kg/亩；状态管理补灌100mm后201.61kg/亩。高配额组仍只
需100mm，结果与管理组相同，不能声称其被120mm配额卡住。

每个case保存逐垄日表、全田日均与中文日表、真实工具日志、管理决策、实际解析原生
参数、天气和配置来源以及最终收储状态。`scripts/audit_wofost_complete_season.py`
从原始记录独立检查逐垄覆盖、成熟后冻结、水量平衡、RH/VAP、N/灌水、一次13%转换
和收割/卸粮/入库对账，不依赖runner自身的success字段。

## 正式90个L3场景的迁移范围与入口

正式池以 `scripts/fullseason/formal_90_scenario_ids.txt` 为准。全部90个场景均从
64垄未播种状态开始，可以从播种当天建立原生模拟；不需要伪造一个已开花作物的
WOFOST历史。迁移应保留原场景ID、分区、天气事件、资源和工具约束，同时单独审查
原挑战是否仍能影响新的内核。初始化成功不代表全季运行或挑战保留已经通过。

只读盘点命令：

```bash
uv run --locked python scripts/audit_wofost_l3_migration.py \
  --output validation_runs/wofost_l3_migration_20261021/inventory.json
```

此检查捕获原oracle工具计划，不执行农事、不推进WOFOST、不调用LLM。
逐场清单和初始状态保存在 `inventory.json`。它不授予场景“已迁移”的状态。

`configs/wofost/l3_heinong84_reference_v1.json` 是黑农84候选迁移配置，采用完整的
`heilongjiang_heinong84_complete_v1`公开参考参数和23株/m²参考密度。
它没有全局覆盖土层、田间持水量或入渗参数，避免把L3原有分区差异覆盖成完整演示
场景的均质土壤。原L3土壤本身仍须按新水量模型检查，不能据此视为实测黑土参数。

候选配置启用 `require_explicit_cultivar_parameters=true`：真实播种的品种必须有
作用范围匹配的档案、明确的`cultivar_map`或该种子非空`parameter_overrides`；
否则在解析种子时报错。通用`*`覆盖不能冒充每个品种都已适配。此开关默认false，
保留旧配置行为；显式映射或少量覆盖仅说明调用者明确选择了参数，并不证明本地标定。
当前候选配置仅覆盖HEINONG84，不能直接用于整套90场景。

主CLI与ICLR批量runner均可使用：

```text
--crop-backend wofost --wofost-config configs/wofost/l3_heinong84_reference_v1.json
```

批量runner会在调度前将配置内容合并到`scenario_kwargs`，保留seed、detail等字段，
并传给各子进程。原有runner JSON也支持`crop_backend`、`wofost_config`。
原L3 context/retrieval包装脚本仍可通过其现有`scenario_kwargs`透传。

### 保留原题义需要完成的工作

| 原L3内容 | 原生模式现状 | 迁移工作 |
|---|---|---|
| 六个品种与混种 | 仅黑农84有完整原生参考档案 | 为另外五个品种显式建档；重新验证物候与产量差异 |
| 低肥力/漏施肥分区 | `nutrient_index_delta`不进入原生氮库 | 增加每垄可用氮/可矿化氮初值，重新定义施肥恢复路径 |
| 根瘤固氮不足 | 原场景只降低养分指数 | 增加每垄固氮参数入口，使故障进入原生固氮过程 |
| 钾/微量元素不足 | 当前原生模型只有氮限制 | 明确实现FAIRY外部扩展，或改写场景挑战并记录版本 |
| 土壤分区 | 根深、FC、入渗等部分映射 | 重设原生SOPE/KSUB等；旧排水率和分区灌溉效率不能直接照搬 |
| 密度、冷湿伤苗、水涝、高温 | 部分过程为近似或尚缺失 | 保留明确来源的FAIRY扩展，验证挑战效应；不能只靠名称声明生效 |
| 七个补种场景 | 已启动的原生垄不支持再次PLANTING | 设计旧作物结束、新作物启动和土壤水氮连续继承的生命周期 |
| 固定等待天数的oracle | 新物候不会与旧阶段日历相同 | 按观测到的出苗/DVS、粮水分和可作业性生成新oracle |

应在场景语义和动态oracle通过后，用同一套后端及参数另建WOFOST oracle/do-nothing
基线，保留原legacy基线。严格完成检查应覆盖全部64垄、工具错误、成熟、收割、干燥、
卸粮和安全入库；`Scenario.validate()`返回None或仅外推到R8均不足以证明迁移完成。

### 已执行的两个原L3收获迁移探针

使用上述候选配置、原场景2026合成天气和原土壤分区，先重放原oracle，再通过现有
观测工具等待成熟、粮水分≤18%、无雨、土壤可作业，生成增强工具序列并在全新世界
重放。没有改收割门槛、天气、场景状态或品种参数。

| 原场景 | 原固定oracle | 观测等待后全新重放 |
|---|---|---|
| `hb_base_hn84_std_normal` | 64个原生模拟启动；0垄成熟/收割 | 加等10天；64垄成熟、收割、安全入库；0工具错误 |
| `hb_dryr5r6_hn84_water_limit` | 64个原生模拟启动；0垄成熟/收割 | 加等16天；64垄成熟、收割、安全入库；0工具错误 |

原工具日历结果在 `validation_runs/wofost_l3_migration_20261021/unchanged_oracle_probe/`，
观测等待后的完整日志、规划观测、增强序列和全新重放结果在同目录的
`observed_harvest_probe/`。增强序列保留原工具、参数、相对顺序，增加收割前等待。
这两个探针证明收获流程可以适配；前期管理仍沿用原日历，尚不能据此宣布全季管理
时机或所有挑战语义都已迁移。它们的合成天气及原土壤也与前述真实气象/120cm完整
演示不同，不能直接拿两组产量归因于同一个变量。

## 实际密度怎样影响原生作物

`reference_density_plants_m2=23`是初始生物量缩放的固定参考，不是实际播种密度，
也没有把最优密度固定为23。实际密度由播种种子数/垄面积获得，再用初始成苗率修正：
`TDWI = profile_TDWI × actual_density / reference_density × initial_stand`。
比较同一品种不同株距时，应保留参考密度，改变实际株距/播种量。

虽然只有TDWI这一处直接入口，原生模型随后会改变初始器官重量、叶面积、光截获、
呼吸、衰老、耗水和需氮，因此最终产量并不按密度线性增长。农场模式还存在
LAI→冠层覆盖→抑草→同化折减的间接反馈。旧模型的最适密度惩罚曲线不在此分支运行。
分枝补偿、行距几何、逐日存活株数和高密度引起的倒伏尚未显式建立；目前也没有
本地密度试验标定。不能从一次模型比较推断田间最优密度。

`scripts/check_wofost_density_response.py`从同一适配器建立10/16/20/21/22/23/25/30/40株/m²，
固定2017年天气、播期、品种、土壤、初始成苗率与50kgN/ha施氮，雨养、关闭外部
病虫草和收获损失，并分别运行原雨量与雨量乘0.25的合成压力试验。
断言所有case除TDWI外的作物、土壤和站点参数完全一致。结果保存于
`validation_runs/wofost_density_response_20261021/`。23→40株/m²时，原雨量下籽粒
产量变化−2.25%，缩雨时−8.65%；这是当前程序的敏感性，不是实地密度响应验证。
此处产量为原生籽粒干物质换算到13%水分、未扣病虫草与收获损失，不能等同仓库产量。
