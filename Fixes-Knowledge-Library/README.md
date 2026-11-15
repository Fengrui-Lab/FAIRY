# FAIRY System Prompts & Knowledge Library

本文记录先验知识注入的现有组件、控制参数与实现边界；后续结构方案在文末维护。

审计日期：2026-11-15（Asia/Shanghai）。当前核对基于本地 `test_Knowledge` 分支、HEAD `31be9f8` 及工作区代码。范围为 `fairy-run --agent` / `iclr_validation_runner.py` 创建的新主 Agent；服务端 chat template 不在本文范围。

## 场景范围与清单关系

| 清单 | 有效且唯一的 ID | 集合关系 |
|---|---:|---|
| [formal_90_scenario_ids.txt](../scripts/fullseason/formal_90_scenario_ids.txt) | 90 个 L3 | 完整 L3 范围 |
| [l3_mini_20_scenario_ids.txt](../scripts/fullseason/l3_mini_20_scenario_ids.txt) | 20 个 L3 | 全部属于 formal 90，不是额外 20 个场景 |
| [selected_l2_l1_20_30_scenario_ids.txt](../scripts/fullseason/selected_l2_l1_20_30_scenario_ids.txt) | 30 个 L1、20 个 L2 | 50 个 ID 与上述 L3 ID 不重叠 |

清单内部均无重复，联合为 **140 个唯一场景**。实际注册表可以解析全部 ID；selected 清单中的 50 个 `source_path` 均与实际类文件一致。这些场景默认构造的 `detailed_briefing` 均为布尔 `True`。

还必须区分 `knowledge_library_pilot` 注册的 **20 个来源 L3**：

| 集合关系 | 结果 |
|---|---|
| L3-mini 20 ∩ formal 90 | 20 |
| 知识库 pilot 20 ∩ formal 90 | 20 |
| L3-mini 20 ∩ 知识库 pilot 20 | **0** |
| selected 50 的来源 L3 | 16 个，全部属于 formal 90，均不属于 L3-mini 20 |
| 这 16 个来源 L3 ∩ 知识库 pilot 20 | 15 |

唯一不在 pilot 中的 selected 来源是 `scenario_full_season_hb_replant_after_crusting_short_season`，对应选中清单中的 3 个 L1 和 1 个 L2。**自身 ID 不重叠，不等于来源任务相互独立。**

不能把“mini 的 20 个 L3”“pilot 的 20 个 L3”“selected 的 20 个 L2”混为一组；mini 集并没有现成的同源 pilot 知识库。

证据：[注册表](../fairy/scenarios/registry.py) 的 `get_scenario_class()`；[知识映射](../fairy/scenarios/farm_world_fullseason_v2/harbin_l3_context_briefings.py) 的 `_SCENARIO_LIBRARY_SLUGS`；split 类的 `source_l3_scenario_id`。

## System prompt（第一次 LLM call 前）

本节梳理**首轮请求的全部提示组件**，并标明实际位置。当前任务、知识和 controller 策略多数位于 `user`，工具说明位于独立 `tools` 参数；不能统称为 API 的 `system` 消息。

### 总览：组件、类别与装配关系

| 类别 | 本文含义 |
|---|---|
| 固定公用部分 | 标准主 Agent 路径必有、跨 Scenario 复用的固定文本 |
| 可选部分（必须存在） | 必须采用一种内容/配置，可在候选中选择；不是“可以省略”，例如 fairy/are 行为规则 |
| 可注入部分（可以不存在） | 按条件追加，可以为空，例如外部知识和 Relation |
| Scenario 私有定义 | 由场景提供的任务、数据或附加文字；“私有”表示来源，其存在条件另行说明 |

分类是对现有实现的整理，不是新增校验规则。**存在条件与内容来源是两个维度**：例如详细任务属于 Scenario 私有定义，但与基础任务二选一；跨源知识虽按 Scenario 检索，内容不一定由目标 Scenario 定义。

本范围的任务正文必须存在一种表示：基础版或详细版；知识模式采用基础版再追加知识，不是省略任务。

```text
messages[0], system:
  ① 基础角色 + ② fairy/are 行为规则 + ③ 环境说明
  + [④ 单工具补充] + [⑤ Scenario 额外 system] + ⑥ 初始仿真日期

messages[1], user:
  Scenario briefing，按 detailed_briefing 选择：
    false      → ⑦ 基础任务
    true       → ⑧ 详细任务（替换基础任务）
    L3知识模式 → ⑦ 基础任务 + ⑨ 场景知识/参考工作流
  + [⑪ controller 策略上下文，可能含 ⑫ controller skill 检索结果]

tools，与 messages 平级:
  ⑬ 当前工具的名称、功能和参数 schema + [⑭ Relation]

⑩ controller system addendum：配置中存在，当前标准 CLI 路径未送入 system。
⑮ A2A：可改变上述 tools，并为专家另建请求，不自动继承主 Agent 全部提示。
```

| 组件 | 类别 / 存在条件 | 主要控制入口 |
|---|---|---|
| ① 基础角色 | 固定公用部分 | 无独立 CLI 开关 |
| ② 行为规则 | 可选部分（必须存在） | `--system-prompt-mode fairy\|are` |
| ③ 环境说明 | 固定公用部分 | 无独立 CLI 开关 |
| ④ 单工具补充 | 可注入部分 | `--parallel-tool-calls false`；句子已存在则不重复 |
| ⑤ 额外 system | Scenario 私有定义；可不存在 | `--scenario-kwargs` 的 `additional_system_prompt` |
| ⑥ 初始仿真日期 | Scenario 私有数据；正常主路径存在，公共模板渲染 | `--scenario`、场景起始时间/checkpoint |
| ⑦ 基础任务 | Scenario 私有定义；briefing 的一种版本 | `--scenario`、`detailed_briefing=false` 或 L3 知识模式 |
| ⑧ 详细任务 | Scenario 私有定义；briefing 的另一版本 | `detailed_briefing=true`，本范围默认值 |
| ⑨ 场景知识 | 可注入部分；按场景选取，来源可同源/跨源 | `detailed_briefing` 的知识模式 + 文件/检索参数 |
| ⑩ controller system addendum | 可注入部分；当前 CLI 被覆盖 | `--controller`；Python `system_message` 优先级 |
| ⑪ controller 策略上下文 | 可注入部分；默认 baseline 为空 | `--controller`，runner 的 `--families` |
| ⑫ controller skill 知识 | 可注入部分；内置 family 均未开启 | 仅 Python `ResearchSkillConfig` |
| ⑬ 工具契约 | 可选部分（必须存在）；按场景与运行配置装配 | `--scenario`、`--a2a` 等；没有整体关闭工具说明的 CLI |
| ⑭ 工具关系说明 | 可注入部分 | `--tool-relations on\|off`，默认 on |
| ⑮ A2A 专家提示 | 可注入部分；仅委派时产生专家请求 | `--a2a`、`--a2a-policy`、`--a2a-app-agent` |

实际装配顺序是：场景构造/setup 生成 briefing 和 apps → 可选 A2A 包装 → 创建主 Agent 的基础 system 与 tools → Engine 追加场景额外 system、提取 briefing → controller 追加日期、构造策略上下文 → 写入 user → 首次调用 LLM。**文本生成顺序不同于最终 messages 的排列顺序。**

证据：[CLI](../fairy/cli.py)、[Engine](../fairy/controllers/engine.py)、[AgentBuilder](../fairy/controllers/agent_builder.py)、[BaseAgent](../fairy/agents/agent/base_agent.py)。以下组件标题编号与总览一致。

### 1. 基础角色

**类别：固定公用部分；位置：system / general_instructions。** 定义农场管理员身份、地点、规模及管理周期；没有独立 CLI 开关。L1/L2/L3 均使用下列原文，不随场景自动改写：

```text
You are an experienced farm manager for a soybean farm in Harbin, Heilongjiang. You manage 64 ridges across a 268m x 71m field through the full growing season: field preparation, planting, crop monitoring, and harvest.

You think and act like a seasoned farmer: practical, methodical, and grounded in real agronomic knowledge.
```

来源：[agent_config.py](../fairy/controllers/agent_config.py) 的 `FARM_WORLD_GENERAL_SYSTEM_PROMPT`。哈尔滨、64 垄、全季管理目前也是固定文字，并非从 Scenario 字段渲染。

### 2. 基础行为规则

**类别：可选部分（必须存在）；位置：system / agent_instructions。** `--system-prompt-mode fairy|are` 二选一，默认 `fairy`；只切换指令，不切换响应解析器。

`fairy` 原文（`FUNCTION_CALL_AGENT_INSTRUCTIONS`）：

```text
You solve tasks by reasoning step by step and calling the provided function tools.

Function-calling rules:
- Use the provided tool schema for tool calls; do not hand-write JSON action blobs in the assistant message.
- Take one physical action at a time, observe the result, then decide the next step.
- Use real values, not placeholders.
- If a tool takes no input, call it with an empty argument object.
- Continue until the task is complete or impossible with available tools.
- Only message the user when the full task is done or cannot be completed.
```

`are` 原文（`ARE_FUNCTION_CALL_AGENT_INSTRUCTIONS`）：

```text
You are an expert assistant who solves tasks by reasoning step by step and calling the provided function tools.

You must always follow the cycle:
1. Thought: briefly explain what you are thinking and why a tool is needed.
2. Tool call: call exactly ONE tool through the provided function schema.
3. Observation: will be provided by the system; you NEVER generate or fabricate it.

=== THOUGHT RULES ===
- Always explain your reasoning in natural language before the tool call.
- Keep tool call details and arguments in the structured tool call, not in the Thought.

=== TOOL CALL RULES ===
- Use the provided tool schema for tool calls; do not hand-write JSON action blobs in the assistant message.
- Only ONE tool call is allowed per turn.
- Each tool call represents one physical action.
- Use real values, not placeholders.
- If a tool takes no input, call it with an empty argument object.
- For booleans, use true/false in lowercase.

=== OBSERVATION RULES ===
- Do NOT generate or fabricate the Observation; the system will provide the tool result after each call.

=== EXECUTION GUIDELINES ===
- Take one action at a time and complete the thought/tool-call/observation cycle before proceeding.
- If a tool call fails, analyze the error and try a different approach.
- Don't call tools unnecessarily - use your reasoning when you can solve something directly.
- Continue iterating until the task is complete or you determine it is impossible with available tools.
- Pay attention to tool outputs and use them to inform subsequent actions.
- Only message the user when the full task is done or cannot be completed.
```

来源：[agent_config.py](../fairy/controllers/agent_config.py)。两者均采用原生 function calling，没有正文 `Action` JSON 解析。当前所有 controller 共享执行循环，不能仅凭 ReWOO/tree 等名称推断已经实现独立阶段调度。

### 3. 环境说明

**类别：固定公用部分；位置：system / environment_instructions。** 说明 App、工具与物理操作的关系；无独立 CLI 开关。实际文本为：

```text
You are managing a soybean farm through a set of applications, each controlling a physical subsystem on the farm.

Available tools are provided through the function-calling tool schema.

Each tool call represents one physical action. Call one tool, observe the result, then decide the next step. Only message the user when the full task is done or cannot be completed.
```

来源：[agent_config.py](../fairy/controllers/agent_config.py) 的 `FARM_WORLD_ENVIRONMENT_INSTRUCTIONS`；其 `environment_hints` 当前填空串。上述角色、行为、环境三段分别由同文件 `SYSTEM_PROMPT_TEMPLATE` 包在同名 XML 风格标签中。CLI 即使选择 `--controller default`，也显式传入 FARM 版本。

### 4. 单工具补充

**类别：可注入部分；位置：基础 system 末尾。** `--parallel-tool-calls` 默认 `true`；设为 `false`，且基础 prompt 尚无下句时追加：

```text
Only ONE tool call is allowed per turn.
```

`are` 已含此句，因此不重复。硬限制也由该参数控制：false 时请求 API 禁止多调用，若返回多个则只保留第一个；true 时可接收多个，再顺序执行。因此 `are` 的单工具文字与默认多调用许可并不完全一致。见 [get_farm_world_system_prompt](../fairy/controllers/agent_config.py)、[BaseAgent 工具策略](../fairy/agents/agent/base_agent.py)。

### 5. Scenario 额外 system

**类别：Scenario 私有定义，可不存在；位置：基础 system/单工具补充之后。** 入口：

```text
--scenario-kwargs '{"additional_system_prompt":"..."}'
```

`Scenario.additional_system_prompt` 默认 `None`，当前内置场景未主动填写它。Engine 仅在非空且首条 system 尚未包含原文时追加。它与 controller 的 `system addendum` 是两个独立来源，不受第 10 节的覆盖影响。见 [Scenario 字段](../fairy/scenarios/scenario.py)、[Engine._apply_scenario_system_prompt](../fairy/controllers/engine.py)。

### 6. 初始仿真日期

**类别：Scenario 私有数据，公共固定模板渲染；位置：首条 system 最后。** 正常 CLI 路径存在；没有单独的日期提示开关。值来自 Engine 的 TimeManager，其起点由 `scenario.start_time` / checkpoint 决定，并受场景 setup 行为影响。

```text
Today's date in 'YYYY-MM-DD HH' format is {仿真日期，CST，精确到小时}
```

这是仿真时间，不是宿主机时间；在 run 开头追加一次，若日期标记已存在则跳过。此段不逐轮更新。见 [Engine 初始化](../fairy/controllers/engine.py)、[ResearchARESimulationAgent._ensure_current_time_system_prompt](../fairy/controllers/agent_builder.py)。

### 7. 基础任务

**类别：Scenario 私有定义；位置：user / briefing。** 表达任务目标、已知事实、资源及完成条件等，定义在场景类或其 spec；“基础”不意味着没有先验约束。

- `--scenario` 选择任务；`--scenario-kwargs '{"detailed_briefing":false}'` 选择基础版。
- 在支持的 L3 知识模式中，基础版还作为知识追加前的任务正文。
- Engine 取 events 中**第一条非空** `AgentUserInterface.send_message_to_agent` 内容；无该内容才退回 `scenario_input`。因此 `--scenario-kwargs '{"scenario_input":"..."}'` 不是已有 briefing 的覆盖开关。
- `--init-kwargs` 传给 setup，按场景实现影响状态或文字，没有统一的 prompt 编辑语义。checkpoint 恢复也不会自动把所有状态送模。

briefing 是基础/详细/带知识版本的最终承载文本；当前没有统一的“目标字段 + 知识字段”送模结构，也不会自动把完整 oracle 事件图送给模型。见 [Engine._resolve_agent_task](../fairy/controllers/engine.py)、[L3 批量构建器](../fairy/scenarios/farm_world_fullseason_v2/harbin_l3_batch_scenario.py)。

### 8. 详细任务

**类别：Scenario 私有定义；位置：user / briefing，替换基础版。** 在任务描述中增加步骤、诊断链、参数或操作建议，内容可能已混有先验知识。入口为 `--scenario-kwargs '{"detailed_briefing":true}'`，本范围 140 个场景默认均为 true。runner 的 `--detail` 会覆盖合并到该字段，不是第二层独立注入。

| 范围 | 定义与选择实现 |
|---|---|
| selected 30 L1 + 20 L2 | 50 个类全部使用 `if self.detailed_briefing`，在类内基础/人工详细文案之间选择 |
| formal 90 L3 | 78 个走共享 `build_batch_events()`；12 个在类内分支并接入公共 loader。人工文案覆盖全部 90 个 |
| mini 20 L3 | 上述 formal 子集；16 个共享构建器、4 个类内分支 |

重要边界：

- L1/L2 不支持多模式协议：直接传非空字符串 `"kwoo"`、`"library"`、`"false"` 都会按真值选择详细版。关闭应传 JSON 布尔 `false`；runner 会归一化常见布尔字符串。
- L3 loader 的 true 返回 `detailed_briefing_text`，缺失才回退基础版；不会默认拼成“基础 + 详细 + 知识”。
- L3 的 JSON `null` 在 78 个共享入口归一为 true，在 12 个类内入口走基础版。错期播种场景 `scenario_full_season_heinong84_staggered_planting` 的布尔 true 另加最早播种日期，字符串 `"true"` 不执行该追加。

来源：[选中 L2 示例](../fairy/scenarios/farm_world_fullseason_v2/l2_l1_splits/hb_disease_then_drought_recovery_tradeoff/scenario_l2_hb_disease_drought_mid_fungicide_20_43.py)、[L3 人工文案](../fairy/scenarios/farm_world_fullseason_v2/harbin_l3_detailed_briefings.py)、[模式 loader](../fairy/scenarios/farm_world_fullseason_v2/harbin_l3_context_briefings.py)、[runner 参数合并](../scripts/iclr_validation_runner.py)。

### 9. 场景知识与参考工作流

**类别：可注入部分；位置：user / 基础任务之后。** 由目标 Scenario ID/spec 决定取哪份内容，但来源可以是目标同源知识、其他场景或外部文件。入口为 `--scenario-kwargs '{"detailed_briefing":"模式"}'`，或 runner 的 `--detail 模式`。模式互斥，当前 CLI 不能组合多种场景知识。“可以不存在”指可以不选知识模式；选中后，必需文件或映射缺失会报错。

以下 11 种知识模式与 false/true 合计 **13 个规范模式**；完整协议适用于接入 loader 的 formal90 L3，不适用于 selected50 的布尔分支。

| 模式 | 内容与实际加载方式 |
|---|---|
| `kwoo` | 基础任务 + 已保存扩写。按 JSON 的 scenario ID 取文本，或读取纯文本；运行时不调用 Kwoo API |
| `library` | 同源 `library_same_l3.md` 全文 |
| `l2_human_same` | 同源 `library_same_l3.json` 全部 skill 卡重新渲染 |
| `l2_human_differ` | 依据固定手工映射选择跨源 L2 卡 |
| `l2_textsim_differ` | 初始化时跨源词频重合检索，默认 top 6；非 embedding，无需预生成 context map |
| `l2_textsim_grouped_differ` | 同上，按建植/管理/收获取 1/2/1 张 |
| `l2_pathsim_differ` | 离线用 candidate 局部窗口与跨源 L2 oracle 做 Farm FOS 路径评分，再加载结果 map |
| `l2_pathsim_grouped_differ` | 同上，阶段配额 1/2/1 |
| `l3_pathsim_same` | 离线比较 candidate 与 L3 oracle 参考池；允许目标自身入池，非“只取自身” |
| `l3_pathsim_differ` | 同上，排除目标自身 |
| `l3_textsim_differ` | 离线按目标描述与跨 L3 参考文本的词频相似度排序，加载结果 map；不需要 candidate 预跑 |

知识来源与参数：

| 控制入口 | 默认 / 作用 |
|---|---|
| `FARM_FAIRY_KWOO_CONTEXT_PATH` | 默认 `scripts/kwoo_expansion_result.json`，90 条覆盖 formal90；可改成其他 JSON/text |
| `FARM_FAIRY_TEXTSIM_TOP_K` | 普通 L2 textsim 默认 6；不改变 grouped 配额 |
| `FARM_FAIRY_RETRIEVED_CONTEXT_PATH` | pathsim 与 L3 textsim 必需的 JSON，运行时只读 `contexts[scenario_id]` |
| 离线脚本 `--candidate-output-root` | 可复用 candidate 轨迹；pathsim 未提供时先独立运行 detail=false |
| 离线脚本 `--reference-scenarios`、`--pathsim-top-k` | 参考池和 top-k，默认 k=4；L3 textsim 也复用该 k |

三个环境变量兼容对应 `FARM_ARE_*` 旧名，FAIRY 名优先。`l3_textdiff_differ` 是 `l3_textsim_differ` 的旧别名；loader 另接受布尔及 `detail_*` 等别名。

资源边界：pilot20 共 72 张卡，包含 belief、evidence_chain、constraints、success_checks、oracle_events 等，也包含具体步骤和参数。`library` / `l2_human_same` / `l2_human_differ` 的现有映射不覆盖 mini20；跨源 textsim 可利用已有卡池，map 模式需准备目标 ID 的内容。L1/L2 的 `scripts/kwoo_l1l2_expansion_result.json` 虽覆盖 selected50，但类中尚无加载接入。

以上知识均在**每次 run 初始化时构建一次**。pathsim 是“预跑/旧轨迹 → 离线检索 → 带知识的新 run”，不是当前 Agent 执行中的动态检索；map loader 也不校验文件 mode 与请求模式一致。`detail=false` 只选基础任务，不关闭 system、工具说明或 controller 提示。

来源：[模式/知识 loader](../fairy/scenarios/farm_world_fullseason_v2/harbin_l3_context_briefings.py)、[离线检索脚本](../scripts/fullseason/run_l3_skill_retrieval_experiments.py)。

### 10. Controller 的 system addendum

**类别：可注入部分；配置目标位置：system；当前标准 CLI 未生效。** addendum 就是 `PLANNING_ADDENDUM` 等控制器专属指令，包在 `<research_family_instructions>` 中。例如 planning 原文：

```text
<research_family_instructions>
Before calling tools, create a compact plan with explicit milestones.
After each tool call, check whether the plan still holds; if not, replan before continuing.
End by reporting completion status and unresolved risks.
</research_family_instructions>
```

`--controller` 选择 family，配置层本应组合“基础 prompt + 该 family 指令”；但当前链路是：

```text
CLI 显式传 system_message = 基础 prompt
→ 配置层生成 基础 prompt + family addendum
→ AgentBuilder 优先使用非空的显式 system_message
→ 最终只选中基础 prompt，family addendum 未进入请求
```

这是代码组装优先级问题，不是模型忽略了已经收到的指令。直接 Python 调用且不显式传 `system_message` 时可保留 addendum；Scenario 的 `additional_system_prompt` 和下一节的 user 策略上下文不在这个覆盖范围内。

来源：[addendum 常量与 family 配置](../fairy/controllers/agent_config.py)、[CLI 调用](../fairy/cli.py)、[AgentBuilder.build](../fairy/controllers/agent_builder.py)。历史上 `e678fa7e` 引入 CLI 的基础 prompt 参数；未找到这是为适配 parser 而有意丢弃 family 指令的说明。

### 11. Controller 的一次性策略上下文

**类别：可注入部分；位置：user / briefing 之后。** `--controller` 默认 `farm_baseline_react`；runner `--families` 最终传入该参数。公共 profile/strategy 生成文字，不是 Scenario 自行定义 controller prompt。

| family | 当前初始上下文与能力边界 |
|---|---|
| `default` / `farm_world` / `farm_baseline_react` | 无额外 research context |
| `farm_planner_executor` | 固定里程碑、逐项执行、失败重规划提示；无独立 planner/executor 调度 |
| `farm_reflective_memory` | run 开始清空记忆，初始无 reflection 段；后续写入不回注 |
| `farm_multi_specialist` | 同一模型采用天气/土壤/设备/运营视角；真正子 Agent 由 A2A 另控 |
| `farm_adaptive_verifier` | 固定不确定性检查提示及关键词；无动态预算控制 |
| `farm_rewoo_modular` | 正则拆分输入 task 为步骤，再生成 plan-work-solve 提示；不解析模型产出的计划 |
| `farm_tree_search` | 从 task 生成候选、手工评分；非环境分支搜索，后续错误标记不再回注 |
| `farm_critic_refiner` | 从 task 生成提案/检查提示；blocked 只是文本，无工具层拦截 |
| `farm_graph_memory` | 从 task 建初始 objective 图并注入；后续 action/outcome 节点不回注 |

planner/specialist/verifier 主要取决于固定 profile；ReWOO/tree/critic/graph 会读取完整 briefing，因此详细任务或知识模式也会间接改变策略文字。Python 还可通过 `ResearchAgentProfileConfig` 的 planning、reflection、delegation、verification、rewoo、tree_search、critic、graph_memory 字段调整各项配置；CLI 没有逐项开关。

“一次性”的代码原因：`run()` 只在进入循环前调用 `_controller_context(task)`；每轮的 `before_llm_turn()` 返回空串。文本仍随对话历史保留，普通 assistant 消息、工具调用及结果也持续增加；停止更新的是额外策略/记忆注入。该改动始于 `d6a46529`，后续 README 已记载为已知限制，不能归因于统一 parser 的必然要求。

所有 family 共用原生 content/tool_calls/finish_reason 处理。有效响应无 tool_calls 即结束；空/截断响应重试。共享解析器本身不阻止实现多阶段 controller，当前缺少的调度不能靠换 fairy/are 文案补齐。

来源：[AgentBuilder](../fairy/controllers/agent_builder.py)、[策略实现](../fairy/controllers/research_strategies.py)、[配置字段](../fairy/controllers/agent_config.py)、[已知边界](../docs/ai/known-pitfalls.md)。

### 12. Controller skill 知识

**类别：可注入部分；位置：user / controller context 内。** 与第 9 节的场景库独立，当前没有内置 CLI family 启用，也没有已注册的 `farm_skill_rag`。

Python 入口为 `ResearchSkillConfig(enabled, library_path, top_k, min_score)`，默认 false、None、3、0.1。库在 `fairy/controllers/research_skills`，有天气窗口、土壤通行性、设备补给、无人机/机器人确认、收获卸粮、完成汇报 6 个 JSON。

开启后在 run 开始按 title/description/keywords 与任务的词集合重合检索，只注入 ID、score、title、description，不注入 workflow。懒加载后缓存，也不逐轮检索；因此当前没有独立默认生效的“共用 Knowledge Library 层”。见 [skill_library.py](../fairy/controllers/skill_library.py)、[ResearchSkillConfig](../fairy/controllers/agent_config.py)。

### 13. 工具名称、功能和参数 schema

**类别：可选部分（必须存在）；位置：独立 tools 参数。** 这里“可选”指按环境组成和运行参数装配工具集；工具实现、功能/参数说明通常维护在公共 App 层，而非每个 Scenario 重写。

| 内容 | 定义来源 / 控制 |
|---|---|
| 可见工具集合 | `--scenario` 决定 `scenario.apps`；公共过滤和 A2A 进一步修改 |
| `function.name` | `<app.name>__<method>`，实例名由场景组装提供，例如 Mavic3M、Matrice4T、Robot0 |
| 功能说明 | App 方法 docstring 的 Description |
| 参数 schema | 方法签名/类型注解生成类型和 required，Args 提供参数说明 |

相同方法的文案通常不随油量、库存等状态改写；实际调用参数值由模型生成。主 Agent 隐藏 `AgentUserInterface__send_message_to_agent`。工具定义在 Agent 初始化时导出，后续请求复用，没有整体关闭 Description/Args 的 CLI 开关。

已确认特例：[balanced_v2 场景文件](../fairy/scenarios/farm_world_fullseason/scenario_full_season_baseline_balanced_season_v2.py) 内定义了 `DailyStateTraceApp`，导出 `DailyStateTrace__capture_daily_state`。它虽被注释为 oracle probe，`@app_tool` 仍使其对 Agent 可见；该场景不属于本次 140 个 ID。当前框架没有强制禁止场景文件定义工具。

来源：[App.get_tools](../fairy/apps/app.py)、[tool_utils.py](../fairy/tool_utils.py)、[toolset_builder.py](../fairy/agents/agent/toolset_builder.py)。

### 14. 工具 Relation

**类别：可注入部分；位置：tools / function.description 末尾。** `--tool-relations on|off` 默认 on，同时控制主 Agent 与 A2A 专家。关闭仅移除独立 Relation 段，不移除 Description、Args 或其中已有的操作约束。

Relation 当前是原文追加，**不会按实例名改写引用，也不校验目标工具是否可见**。例如 [doc 审阅稿](../Fixes-Tools-Doc-Schema/field_ops_app.md) 的 `RobotApp.inspect_pests` 对应实际实例可能是 `Robot0__inspect_pests`；裸 `check_status` 也需区分无人机/机器人实例。A2A 包装后，主 Agent 可能只剩 `Robot0__expert_agent`，不能直接调用原始方法。

这些 Markdown 审阅稿尚未替换源码 doc，也不被运行时加载；不能将草稿歧义等同于已发生的模型误调用。当前源码的 Relation 多为自然语言配合建议。见 [doc/schema 约定](../Fixes-Tools-Doc-Schema/README.md)、[AppTool.to_open_ai](../fairy/tool_utils.py)。

### 15. A2A 专家提示

**类别：可注入部分；位置：独立专家请求。** 默认 `--a2a false`；开启后 `--a2a-app-prop`（默认 0.5）与场景 apps/seed 决定包装对象，主 Agent 工具变为 `AppName__expert_agent`。

- `--a2a-policy generic|typed_experts` 默认 generic；`--a2a-app-agent` 默认 `default_app_agent`，提供通用或类型匹配失败时的 profile。
- 专家 system 由公共 `AppAgentConfigBuilder` 生成，使用通用助手角色、function-calling 规则、环境说明及委派提示；typed profile 再加类型专属指令。主 Agent 的 `--system-prompt-mode are` 不自动应用到专家。
- 每次委派重建专家历史；user 是主模型给出的 task，附 Received at/Sender/Message 等字段。不会自动继承主 Agent briefing、知识、additional system 或历史；时间在委派 user 中。
- 专家 tools 为被包装 App 的原始工具 + FinalAnswerTool；跨 App Relation 不因此获得直接调用权限。

来源：[AppAgentConfigBuilder](../fairy/controllers/agent_config.py)、[AppAgent](../fairy/controllers/app_agent.py)、[AppAgentBuilder](../fairy/controllers/agent_builder.py)。`--provider/model/endpoint/temperature/max-output-tokens/enable-thinking` 及 A2A 对应参数控制模型请求，不直接选择本文的提示文字。

## 核验依据

已完成 140 个注册 ID、清单关系与 briefing 分支的核对；16 组构造对照复现 CLI addendum 覆盖，首轮内存 mock 确认 system/user/tools 的结构，两轮 mock 确认研究记忆不回注但普通工具结果保留。上述均未调用真实 LLM。本次仅重整文档，并校验固定 prompt 原文、链接与 Markdown 格式，不修改运行时代码。

## 结构优化方案
