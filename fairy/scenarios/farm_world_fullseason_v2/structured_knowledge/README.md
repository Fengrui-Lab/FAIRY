# structured_true 本地知识

这些文件保存离线整理的知识，运行时按场景 ID 和组件选择读取，在第一次 LLM 调用前装入初始 user 消息的 Scenario briefing。支持 formal90 的全部90个场景，不随后续观测自动更新。

| 文件 | 内容 |
|---|---|
| `plans.json` | P：90份场景计划、387个步骤，含原文明确的时间、数量和约束 |
| `guides.json` | G：从其他场景详细文案归纳的12类可复用指南 |
| `scenario_guidelines.json` | 目标场景→指南映射；每条选中指南绑定两个不同的非目标场景来源 |
| `manifest.json` | 支持的场景ID、来源文件哈希、运行文件哈希 |

G不把来源场景的日期、垄号和剂量当作通用要求。P保留原文条件及数值，并补齐错期播种类内true的日期/窗口要求；原文疑点保存在`review_notes`，不自行改成另一组数值。审阅备注与原始引文不进入默认模型正文。

G正文不显示来源行/来源ID，跨源来源只保存在本地记录与运行报告元数据中；替换为library来源时也按此规则处理，旧library模式自身不变。标准Agent运行仅在初始化时组装一次，后续请求携带已有历史，不重新加载或追加指引。

## 配置

在场景配置中设置 `detailed_briefing="structured_true"`，通过 `structured_briefing.components` 选择内容。未提供structured_briefing或components时按空列表处理，单独选择模式不会自动启用G/P。L1/L2及formal90之外的场景不支持此模式。

| components | 最终briefing |
|---|---|
| `[]` | B，逐字等于原false基础任务 |
| `["reusable_operational_guidelines"]` | B + G |
| `["scenario_specific_plan"]` | B + P |
| `["reusable_operational_guidelines", "scenario_specific_plan"]` | B + G + P |

CLI示例（模型/provider等选项沿用原运行配置）：

```sh
python3 -m fairy.cli --agent \
  --scenario scenario_full_season_hb_organic_patch_weed_mechanical_capacity \
  --scenario-kwargs '{"detailed_briefing":"structured_true","structured_briefing":{"components":["reusable_operational_guidelines","scenario_specific_plan"],"guidelines":{"source":"cross_scenario_detailed"}}}'
```

`guidelines.source` 默认是 `cross_scenario_detailed`，即本目录的指南。若要用已有跨场景library知识替换G，将`guidelines`改为：

```json
{"source": "library", "mode": "l2_textsim_differ", "top_k": 6}
```

这只替换G，P独立加载；未在components中选择G时不加载任何指南。固定装配顺序始终为B→G→P。原有false、true与library模式保持独立。

`top_k`只适用于`l2_textsim_differ`，显式值优先于环境变量且必须为正整数；grouped模式沿用1/2/1配额。pathsim/L3 textsim等map来源可用`context_path`指定文件，须提供对应mode及非目标来源/分数。完整支持列表和map格式见[知识注入参数说明](../../../../Fixes-Knowledge-Library/README.md#3-用现有library知识替换g)。

runner用`--detail structured_true`选择模式，并通过`--scenario-kwargs`传入上述structured_briefing配置。新模式的`run_report.json`包含structured_briefing字段，记录所选组件、来源及实际正文/hash。

## 离线维护与追溯

源材料位于[场景计划审阅库](../../../../Fixes-Knowledge-Library/scenario_specific_plan/INDEX.md)和[指南审阅库](../../../../Fixes-Knowledge-Library/reusable_operational_guidelines/INDEX.md)。修改并核对来源后，在仓库根目录执行：

```sh
python3 scripts/fullseason/build_structured_knowledge.py
python3 scripts/fullseason/build_structured_knowledge.py --check
```

生成器只整理本地文件，不调用LLM。`--check`只验证，不写文件。运行时直接加载此目录，无需访问审阅库或执行生成器。

P的`source`/`additional_sources`记录文件、行号和内容哈希；G的`source_evidence`记录场景ID、行号和引文哈希，可回查审阅JSON中的原文。manifest记录整份源文件与运行文件的哈希。`review_notes`保留原文歧义，便于后续修订与复核。
