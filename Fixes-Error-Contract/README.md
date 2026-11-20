# Agent 错误反馈协议

本文描述当前实现，统一说明定义、改动与保留边界。反馈协议适用于 **Agent 工具调用错误**和 **LLM 响应不可用时的纠错反馈**；另统计 LLM 调用异常，不增加新的反馈类型。

## 格式与分类

两类反馈采用同一正文格式，`error` 为非空字符串，不增加对外 `type/status/code`：

```json
{"error": "清楚的错误原因"}
```

工具调用按以下规则分类：

| 调用结果 | 主结果事件 | workflow.op_type | error_stage | is_error |
|---|---|---|---|---|
| 参数 JSON 解析失败 | `tool_args_parse_error` | `TOOL_ERROR` | `tool_args_parse` | true |
| 工具查找、参数绑定或执行时抛出被捕获的异常 | `tool_call_error` | `TOOL_ERROR` | `tool_call` | true |
| 正常返回顶层包含 `error` 键的 Python 字典 | `tool_call_error` | `TOOL_ERROR` | `tool_call` | true |
| 其他正常返回 | `tool_call_end` | `TOOL` | 无 | false |

- 失败主事件和对应 `runtime_metrics.status` 均为 `error`；正常主事件为 `ok`，正常工具指标行只写 `is_error=false`，沿用不写 `status` 的方式。
- 合规业务错误提取原 `error` 字符串，构造只含该字段的反馈；额外返回字段不进入标准反馈。解析/调用异常将原有完整错误文本包装为 error 对象，不改原因或建议。原工具返回值仍交给原控制器回调。
- `error` 为空或不是字符串时仍判失败，记录 `error_contract_issue=invalid_error_value` 和原值；workflow 保留原返回，消息沿用 `str(原返回)`，不编造原因，也不保证生成标准 JSON 反馈。
- 不按文字中的 error、单独的 `status`、嵌套错误、`None` 或 `False` 推断失败。`TOOL` 仅表示未命中上述失败规则，不保证业务目标完成。失败也不保证无副作用。
- 每次已处理调用只记一个主结果事件、一条工具指标和一个原工具步骤；不为包装错误重跑工具。`tool_call` 阶段不证明方法体已经执行，业务 error 不伪造 Python 异常。

LLM 沿用两项拒绝条件：`finish_reason="length"` 对应 `output_truncated`；既无非空文本、又无工具调用对应 `empty_response`。程序按原因生成标准反馈。空文本但含工具调用仍可接受；本轮未增加其他响应校验。

拒绝记录为 `llm_call_end/status=rejected/accepted=false`，保留 `rejection_reason` 和完整 `agent_feedback`。请求侧网络、鉴权、SDK 异常仍走 `llm_call_error`，不混作响应拒绝。工具内部异常若向调用层传播，则按工具错误处理。

## 新统计与旧统计

| 新指标 | 当前口径 |
|---|---|
| `new_tools` | 已处理并得到结果的工具调用数，包含上述三类失败 |
| `new_tool_errors` | 其中 `is_error=true` 的次数 |
| `new_llm` | 已完成响应接收及接受/拒绝判定的次数 |
| `new_llm_errors` | 其中 `accepted=false` 的次数 |
| `new_llm_call_errors` | FAIRY 记录的 `llm_call_error` 次数，包括网络、超时、鉴权、服务端及客户端/SDK 调用异常 |

两组总数减错误数，分别得到未报错工具调用数、未被拒绝响应数；不代表任务成功或回答正确。没有响应判定的请求侧异常不计入 `new_llm`；被拒绝响应中的工具不执行、不另计工具调用。

`new_llm_call_errors` 是独立补充项，原四项口径不变。每个 `llm_call_error` 计一次，`llm_call_retry` 不重复计数，SDK 内部未向 FAIRY 暴露的重试失败不单独统计。新增统计不改变反馈、上下文、重试、停止或评分逻辑。

五项指标追加到 `run_report.metrics`、终端进度、runner CSV 和通用汇总 CSV/TSV。报告的原四项按 `runtime_metrics` 计数，`new_llm_call_errors` 按已有 `runtime_events` 计数；进度按事件流计数，CSV/TSV 读取报告字段。辅助日志和反馈消息不重复计数，父子 Agent 分别统计。

**旧字段、显示内容、数据来源和计算条件保持不变；旧数值不保证不变。** 例如进度中的 `tools` 仍只数 `tool_call_end`，`tool_errors` 仍数两类工具错误事件，`llm` 仍数 `llm_call_end`。业务 error 被重新分类后，这些旧数值可能变化；新指标不覆盖旧字段，也不接入评分公式。

缺少失败分类时，已知总数保留、错误数标为未知（JSON 为 `null`，终端为 `unknown`，CSV/TSV 留空）。若报告的工具总数与逐次指标数不一致，两项新工具指标均为未知。未提供运行事件时，`new_llm_call_errors` 为未知；明确提供空事件集时为零。旧报告缺少该字段时导出留空。缺少数据不能冒充零次调用；确认没有结果的空集合计为零。历史文件不追溯改写，不从预览文字猜测错误。

# 错误反馈的上下文管理

## 工具错误：进入正常历史

合规工具错误在三个位置保存同一原因：

| 位置 | 表示 |
|---|---|
| 原始 Agent `workflow.content` | error 字典对象 |
| 主结果事件 `agent_feedback` | 同一 error 对象 |
| 消息 `role="tool"` 的 `content` | error 对象经 `json.dumps(..., ensure_ascii=False)` 得到的字符串 |

工具消息使用原 `tool_call_id`，不另加 user/system 错误消息。成功返回仍沿用 `str(tool_response)`；不合规 error 值按前述例外保留原返回。

同批**已处理调用**的工具回复排在执行期间产生的通知之前，包括异常回复。工具错误随正常历史进入后续请求，不自动删除、不推断已修复，也不采用 LLM 反馈的一次性规则。运行停止后，不为发送错误额外调用 LLM。

## LLM 响应拒绝：只进入紧接着的一次实际请求

纠错提示作为临时 `system` 消息追加在发送列表末尾，`content` 是 error 对象的 JSON 字符串。该角色表示框架纠错反馈，不是新增一类系统报错。

1. 第 N 次响应被拒绝：记录错误，该响应不进入有效 assistant 历史，其中工具不执行。
2. 现有重试规则允许继续时，将反馈加入 N+1 次实际 LLM client 调用的消息副本。
3. 在 client 调用边界消费反馈；无论成功、再次拒绝或网络失败，旧反馈都不进入 N+2。调用前的本地准备失败不消费反馈。
4. N+1 若再次被拒绝，则另记一次错误、生成新反馈供 N+2 使用。若没有后续请求，只保留拒绝记录，不伪造使用记录。

临时反馈不写入持久消息历史或 workflow。新 `Agent.run()` 清空待发送反馈；重试次数、等待和停止条件保持原样。这里的“请求”以 FAIRY 的 client 调用为单位，不另计算 SDK 内部 HTTP 重试。由于请求可能增加反馈，`response_policy.retry_changes_request=true`。

`llm_call_error` 沿用原异常处理与重试规则，不因新增计数而生成临时 `system` 纠错提示。

## 运行后定位

查看完整 `*.runtime_log.jsonl`；进度日志省略完整请求消息，不能代替它。

| 要定位的内容 | 关联字段 |
|---|---|
| 工具失败及完整原因 | 运行归属、`record_index`（内存事件为 `event_index`）、`tool_call_id`、`is_error`、`agent_feedback`；不合规值另查 `error_contract_issue/error_value` |
| LLM 不可用响应 | `llm_call_end.llm_call_id`、`accepted`、`rejection_reason`、`agent_feedback` |
| LLM 调用异常 | `llm_call_error.llm_call_id`、`error_type`、`error_message` |
| 哪次请求使用了纠错反馈 | `llm_call_start.feedback_for_llm_call_id` 指向来源请求，`messages` 保存实际发送列表的快照 |

`llm_call_id` 按 Agent 实例递增；新运行清空反馈，不重置该计数。所有 ID 均结合所属 Agent/运行解读。日志可证明反馈进入了哪个 client 调用，不能在网络失败时证明服务端已收到。

LLM 拒绝、重试和临时纠错不成为 workflow 步骤；原始 Agent workflow 保留实际工具尝试及其结果。后续回放和评估继续使用原有输入链路，不从临时消息列表构造轨迹。

# 错误协议实现记录

## 改了什么

| 文件 | 本轮保留的改动 |
|---|---|
| [agent.py](../fairy/agents/agent/agent.py) | 统一三类工具失败的事件、标签、指标和反馈；业务 error 沿用正常返回回调，捕获异常沿用异常回调；同批工具回复统一排在通知前 |
| [base_agent.py](../fairy/agents/agent/base_agent.py) | 为原有 LLM 响应拒绝增加一次性反馈、请求编号和来源关联；原发送快照记录实际含反馈的请求 |
| [messages.py](../fairy/agents/agent/messages.py) | 合规工具错误使用 JSON 字符串；指标记录 `is_error`、响应接受/拒绝信息 |
| [run_artifacts.py](../fairy/controllers/run_artifacts.py) | 汇总五个新指标，区分零值与缺失信息 |
| [cli.py](../fairy/cli.py) | 将已有运行事件传给统计，主 Agent 与专家 Agent 分别计算调用异常数 |
| [iclr_validation_runner.py](../scripts/iclr_validation_runner.py)、[summarize_runs.py](../scripts/summarize_runs.py) | 在进度和 CSV/TSV 中追加新指标，保留旧统计方法 |

## 保留了什么

具体工具的文案、业务条件、执行行为，以及控制器回调分流、反思、预算、重试和停止策略均未修改。系统 debug 和基础设施故障恢复也未改造。工具未校验非法输入、内部吞异常或未实现预期效果等存量问题，不会仅因统一错误格式而自动解决；部分完成、警告和降级不自动改判失败。

此前对 `fairy/types.py`、`fairy/scenarios/workflow_validation.py`、`fairy/controllers/engine.py`、`scripts/rebatch_fos_from_traces.py` 的转换/回放适配已撤回，这四个文件保持本轮修改前的实现：

| 路径 | 当前保留的行为 |
|---|---|
| 后续 workflow 转换 | 保留原数值事件时间、工具名称/读写类型和连续 `advance_time` 合并规则；可能丢失原始 `TOOL_ERROR/error_stage`，未实现全链路统一 |
| rebatch 回放 | 有效错误记录若属参数解析失败或缺 App/方法，可不执行并恢复错误事件；方法存在的其他失败仍尝试执行。缺工具检查适用于所有非 `TOOL_ERROR` 记录，不只 `TOOL`。使用历史 content 建事件，不逐条比较重执行返回值；`failed()` 为真本身不拒绝评分 |
| Engine 直接回放 | 不按 `TOOL_ERROR/error_stage` 豁免执行；未知工具和执行异常向外抛出，正常返回 error 字典仍可能记为 `status=ok` |
| 评分 | 公式、权重和判定规则未修改。部分 gate 不统一排除失败；FARM-FOS v2 根据内容识别错误；有事件日志时，FOS 安全子串匹配可能把异常文本中的 `dry_grain` 误匹配为 `rain` |
| Oracle 指标 | 新指标依赖逐次 Agent 记录；Oracle 可能显示零或未知，不能据此推断其实际工具调用与错误次数 |

**实现未改，不等于输入和结果不变。** 新错误格式/标签可能触发原有回放及评分分支，反馈也可能改变 Agent 后续决策；不承诺旧统计值、轨迹或分数相同，也不将所有分数变化解释为纠正了旧误判。

## 验证

相关测试集中在 [tests/test_error_contract.py](../tests/test_error_contract.py)，共 44 项：工具反馈 12、LLM 上下文 8、统计 12、汇总导出 4、运行产物集成 1、原版转换/回放 7。

在仓库根目录运行：

```bash
.venv/bin/python -B tests/test_error_contract.py -v
```

测试使用假 client 和内存文件，覆盖反馈一致性、消息顺序、既有回调/预算、一次性纠错、统计与导出，以及转换后进入 FARM-FOS/FARM-FOS v2 的兼容性。没有真实 LLM 请求；这些测试不代表已穷举全部工具状态、全部场景或模型服务行为。
