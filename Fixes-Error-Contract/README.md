# Agent 错误反馈协议

状态：错误反馈与统计已实现；记录转换及回放适配已按最新要求撤回。验证与保留边界见 [IMPLEMENTATION-NOTES.md](IMPLEMENTATION-NOTES.md)。更新：2026-11-15。

本协议只约束两类面向 Agent 的错误：**工具调用错误**、**LLM 响应不可用的纠错反馈**，以及它们的分类、记录、上下文和统计。系统 debug、基础设施故障处理、停止机制、评分规则不在改造范围内。

**采用统一旧失败标签及错误内容表示的方案，不再冻结旧 workflow 的错误表示或要求旧统计值、评分值不变。具体工具的错误文案、业务条件和行为仍不修改。**

FILE-INVENTORY.md 与 FILE-PROMPTS.md 尚未同步这一决定；其中“冻结旧事件、workflow 和统计值”的约束已失效，本版以这两份主协议为准。

## 1. 统一格式与生成逻辑

两类反馈都只有一个字段：

```json
{"error": "错误内容"}
```

| 类别 | 生成者 | 判断依据 |
|---|---|---|
| 工具调用错误 | 工具提供业务原因，调用层统一生成反馈 | 调用前解析/查找/参数绑定失败、业务拒绝、原有处理路径捕获的执行异常 |
| LLM 响应错误 | 响应校验层 | 本次响应被判不可用；当前明确处理 `empty_response`、`output_truncated` |

- `error` 必须为非空字符串，不增加对外 type/status/code。成功结果不使用顶层 error。
- 工具错误保留原有错误内容，不翻译、扩写、润色或新增建议。已有合规 error 对象直接复用；解析/执行异常将现有反馈文本包装进 error。统一对象同时用于工具错误记录和 Agent 反馈，不为两者编写不同原因。
- 普通字符串、None 或内部 False 不自动变成错误。只处理已有明确失败字段、调用前错误和原有捕获异常，不按文本中是否出现 error 一词判错。
- 工具参数 JSON 错误归工具错误；整条 LLM 响应被拒绝时，其中工具不执行，也不另计工具错误。
- `raise` 只是内部实现方式。返回 error 字典同样算失败；内部异常被处理且操作最终完成，不仅因曾抛异常就判失败。
- 正常空结果、None、已满电、等待生效不是通用错误。不在本轮补充新的业务失败判定或部分完成协议。
- 工具 error 值为空或类型不合法时，不因空值判成功；若无法无损提取符合协议的原有错误文字，列为待确认项，不自行编写新的工具错误原因。
- LLM 请求侧网络/鉴权/SDK 故障不计为 LLM 响应错误。工具内部依赖故障若使这次工具调用失败，仍属于工具错误。
- 本轮不新增响应拒绝条件、工具业务限制或恢复/停止规则；发现缺失校验另列待确认，不以格式统一为由改变运行行为。

示例：

```json
{"error": "<原有工具错误内容，保持不变>"}
```

```json
{"error": "Previous response was truncated at the output token limit. No tool calls from that response were executed. Generate a shorter, complete response."}
```

工具示例仅表示包装方式；LLM 示例是根据已有拒绝原因生成的新反馈，不用于修改任何工具文案。

## 2. 统一失败标签与记录

| 记录位置 | 参数 JSON 解析失败 | 捕获的调用异常 | 正常返回 error 对象 |
|---|---|---|---|
| 主结果事件类型 | tool_args_parse_error | tool_call_error | tool_call_error |
| 主结果事件 status | error | error | error |
| runtime_metrics.status | error | error | error |
| workflow.op_type | TOOL_ERROR | TOOL_ERROR | TOOL_ERROR |
| workflow.error_stage | tool_args_parse | tool_call | tool_call |
| workflow.content | error 对象 | error 对象 | error 对象 |
| 内部 is_error | true | true | true |

成功调用仍使用 tool_call_end/status=ok，is_error=false，成功结果的内容表示沿用原方式。is_error 是内部记录字段，不加入对外 error 对象。

- tool_call 阶段包含现有工具查找、参数绑定、执行异常及业务拒绝；它不证明工具已进入方法体，也不证明曾抛 Python 异常。诊断需要时可另保留真实来源，业务拒绝不得伪造异常类型。
- LLM 响应拒绝沿用 llm_call_end/status=rejected、accepted=false、rejection_reason，并记录标准 error 反馈。llm_call_error 仍表示请求侧异常，不把它混作响应拒绝；两类错误统一正文格式，不混用工具和 LLM 事件标签。
- **工具 workflow.content 保存 error 字典对象；Agent 的 tool.content 保存该对象的 JSON 字符串。** 同一次调用只生成一份错误原因，序列化前后应相等；LLM 拒绝及纠错反馈不写入 workflow。
- 因此 workflow.content 会改变：已有合规业务 error 对象保持内容，旧解析/执行异常文本变为 error 对象。不能再承诺旧 workflow 完全不变；也不把 JSON 字符串双重编码后存入 workflow。
- 统一在通用调用/消息层完成；每次调用只有一个主结果事件、一条工具指标和一个原有工具步骤，不重跑工具、不增设“错误反馈步骤”。工具名、参数、顺序和实际时间保持。
- 失败不等于未执行、无副作用或需要自动重试。记录统一不要求把业务 error 改成 Python 抛异常；本轮保持既有控制器回调、反思、重试、预算及停止分流，不顺带改策略。

## 3. 统计与旧字段的关系

**保留全部现有统计字段、显示方式、读取数据源、计数条件和汇总公式，只追加四项新指标。不得为统一报错重写旧指标的计算方法，或用新指标覆盖旧字段。**

例如旧 progress.tools 仍只数 tool_call_end，旧 tool_errors 仍只数 tool_call_error 与 tool_args_parse_error，旧 llm 仍只数 llm_call_end；不把旧 tools 改成“全部已处理调用数”。完整新口径使用下面四项：

| 新字段 | 含义 |
|---|---|
| `new_tools` | 已处理并得到明确结果的工具调用数，包含成功、调用前失败、业务失败和执行异常 |
| `new_tool_errors` | 上述调用中确定失败的次数 |
| `new_llm` | 已完成响应接收或拒绝判定的次数，包含有效和不可用响应 |
| `new_llm_errors` | 上述响应中因不可用而被拒绝的次数 |

因此：

- `new_tools - new_tool_errors` = 未报错的工具调用次数。
- `new_llm - new_llm_errors` = 未被拒绝的 LLM 响应次数。

“未报错”不代表任务目标达成或回答内容正确。尚无明确结果、仍在运行的尝试不计入；没有响应判定的 LLM 基础设施故障不计入 new_llm。

记录和汇总规则：

- 工具按第 2 节分类：成功才记 tool_call_end；业务 error 与调用异常记 tool_call_error；解析失败记 tool_args_parse_error。一次调用只记其中一种主结果事件，失败不能再补一个 tool_call_end。
- 同一 is_error 写入主结果事件和对应 runtime_metrics 行，包括手工追加的异常行；报告读取指标行、进度读取事件，应得到相同的新统计，不依赖正文关键词猜测。
- LLM 沿用 `llm_call_end.accepted/rejection_reason`；拒绝一次只计一次。retry、异常传播、反馈消息都不重复计数。
- 工具辅助观察事件不再次计数；反馈在上下文中出现或移除不影响失败发生次数。
- 新字段追加到 run_report.metrics、CSV 新列及终端进度行，不覆盖旧字段，不接入评分公式。new_tools 是三种工具主结果事件之和，new_tool_errors 是其中两种错误事件之和；指标行按相同事实各计一次。
- 父子 Agent 按各自运行计数；不把子 Agent 的内部调用重复累计到父调用。
- 旧日志缺少完整分类时标记未知，不默认填零或通过 content_preview 猜测。旧报告仍按旧逻辑读取。
- 旧统计计算方法保持不变；输入事件按新协议重新分类，所以旧数值可能改变。旧 error_count/controller telemetry 仍按原回调统计，不能当作统一后的全部工具失败数。同一份日志/指标输入交给修改前后的统计实现，全部旧字段应得到相同结果。

终端示意（旧字段及显示保留，不保证旧数值；新字段追加）：

```text
elapsed=... llm=... tools=... tool_errors=... tokens_in=... tokens_out=... last=... idle=... new_tools=... new_tool_errors=... new_llm=... new_llm_errors=...
```

例：5 次成功、2 次业务 error、1 次解析失败、1 次执行异常。原事件下旧 progress 是 tools=7/tool_errors=2；按新标签、沿用旧读取公式后为 tools=5/tool_errors=4；完整新口径为 new_tools=9/new_tool_errors=4。只有新四项适用上面的减法关系，不能承诺新旧数值可直接比较。已有历史文件不追溯改写；历史分类信息不足时不得伪造新口径统计。

## 4. 评估与回放边界

- 本轮不主动改 gate 成功条件、路径评分公式或安全关键词规则；不修这些旧规则，并不妨碍统一错误记录或继续评估。字段传递适配与评分定义修改分别处理。
- **规则不变不代表结果不变。** TOOL_ERROR 会被回放读取；workflow 中异常文本改为 error 对象，也会改变现有消费者的识别范围。即使固定调用轨迹，统计与评分也可能改变。
- 已知条件性风险：异常对象开始进入安全关键词检测后，解析错误中的 dry_grain 可能因含 rain 被计安全违规；部分 gate 则仍可能接受失败尝试。这些是消费者的判别问题，单列说明，不自动扩大为本轮评分改造，也不能宣称变化都代表评估更正确。
- 不根据 TOOL_ERROR 自动删除失败步骤、跳过所有回放执行或将它当作真实异常。回放缺工具恢复、实际结果与原记录的差异，以及记录转换中的失败信息传递，都需按实际路径核查并报告；不以格式统一为由自行改变这些策略。
- 按最新回退要求，本轮保留原版 CompletedEvent、workflow 转换与回放实现，包括原时间口径、工具名称/读写类型生成方式及连续 advance_time 合并规则。原始 Agent workflow 仍按本协议记录错误；后续转换可能丢失失败标签/阶段的旧问题暂不修复。
- 模型看到统一反馈后也可能改变后续决策，不保证重新运行得到相同轨迹或分数。本轮不修具体工具文案、参数条件或失败前的状态修改。

上下文位置、一次性反馈与运行后定位见 [ErrorContextManagement.md](/Users/hanlinyuan/Documents/Codex_Projects/FAIRY/Fixes-Error-Contract/ErrorContextManagement.md)。文件范围和执行 prompt 见 [FILE-INVENTORY.md](/Users/hanlinyuan/Documents/Codex_Projects/FAIRY/Fixes-Error-Contract/FILE-INVENTORY.md)、[FILE-PROMPTS.md](/Users/hanlinyuan/Documents/Codex_Projects/FAIRY/Fixes-Error-Contract/FILE-PROMPTS.md)。
