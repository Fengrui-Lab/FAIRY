# Agent 错误反馈协议

状态：设计文档，待用户校准后再实施。更新：2026-11-15。

本协议只约束两类面向 Agent 的错误：**工具调用错误**、**LLM 响应不可用的纠错反馈**，以及它们的新增统计。系统 debug、基础设施故障处理、停止机制、评分规则不在改造范围内。

**本轮不修改任何具体工具的错误文案、业务内容、失败条件或行为，只统一已有报错反馈的表示与传递。**

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
- 工具错误保留原有错误内容，不翻译、扩写、润色或补充操作建议。已有合规 error 字典直接复用；已有异常文本只额外包装成 error 对象。
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

## 2. 反馈与旧评估记录分开

同一次调用保留两个用途：

- **原始结果**：继续用于现有 workflow、回放、评分和旧统计。既有业务字典、异常文本、op_type、error_stage、参数、顺序和时间保持原义。
- **Agent 反馈**：按上述格式生成，只用于实际发送的消息和附加的反馈记录。

当前评分会读取原始 error 文案和内容类型，因此不能直接用新反馈覆盖旧 workflow 的 content。只改变外发消息的包装，不把旧异常文本整体改成评估中的 error 字典，也不把业务 TOOL 步骤改成 TOOL_ERROR。

两份表示对应同一次工具调用，不是连续写两个 return、执行两次工具或新增一个 workflow 步骤。不需要为各工具增加业务格式器、状态快照或内容修正逻辑；包装在通用调用/消息层完成。

本轮保证的是**固定输入/状态/原轨迹下的旧统计与评分语义兼容**。模型看到新反馈后可能改变后续操作，因此新运行不保证获得相同轨迹、token 数和最终分数。

## 3. 新增统计：只追加，不覆盖旧值

保留所有现有进度、报告、CSV、controller telemetry 和评估指标的原口径，新增：

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

- 工具在统一调用边界生成一次 `is_error`。复用既有主结果事件：正常 return 的 `tool_call_end`、异常的 `tool_call_error`、解析失败的 `tool_args_parse_error`；每次调用只选其实际所属的一条。
- 为保护旧计数，不给异常路径再补一条 tool_call_end，不改旧事件类型/status，不增加旧 runtime_metrics 的重复行。
- 同一 is_error 同时附加到既有主结果事件和对应 runtime_metrics 行；正常返回行由 Messages 写入，解析失败/执行异常等手工指标行由调用层补齐。报告读取 runtime_metrics，进度读取事件，两者不得各自猜测失败。
- LLM 沿用 `llm_call_end.accepted/rejection_reason`；拒绝一次只计一次。retry、异常传播、反馈消息都不重复计数。
- 工具辅助观察事件不再次计数；反馈在上下文中出现或移除不影响失败发生次数。
- 新字段追加到现有 run_report.metrics、CSV 新列及终端进度行；不覆盖 tools、tool_errors、llm、error_count 或现有报告字段，不接入旧评分公式。
- 父子 Agent 按各自运行计数；不把子 Agent 的内部调用重复累计到父调用。
- 旧日志缺少完整分类时标记未知，不默认填零或通过 content_preview 猜测。旧报告仍按旧逻辑读取。
- 两条链路共用已经判定的事实，但不为新统计改变旧控制器回调、反思或策略分支。

终端示意（旧字段原样保留，新字段追加）：

```text
elapsed=... llm=... tools=... tool_errors=... tokens_in=... tokens_out=... last=... idle=... new_tools=... new_tool_errors=... new_llm=... new_llm_errors=...
```

当前旧 progress.tools 不含异常/解析失败，tool_errors 漏业务错误，所以新旧数值允许不同。不能用新口径覆盖旧字段后再宣称历史统计未变。

上下文位置、一次性反馈与运行后定位见 [ErrorContextManagement.md](/Users/hanlinyuan/Documents/Codex_Projects/FAIRY/Fixes-Error-Contract/ErrorContextManagement.md)。文件范围和执行 prompt 见 [FILE-INVENTORY.md](/Users/hanlinyuan/Documents/Codex_Projects/FAIRY/Fixes-Error-Contract/FILE-INVENTORY.md)、[FILE-PROMPTS.md](/Users/hanlinyuan/Documents/Codex_Projects/FAIRY/Fixes-Error-Contract/FILE-PROMPTS.md)。
