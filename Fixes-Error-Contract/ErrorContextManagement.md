# 错误反馈的上下文管理

状态：设计文档，待用户校准后再实施。更新：2026-11-15。
反馈格式与新增统计遵守 [README.md](/Users/hanlinyuan/Documents/Codex_Projects/FAIRY/Fixes-Error-Contract/README.md)。

本版采用统一旧失败标签和 workflow 错误内容的方案；旧清单/执行 prompt 尚未同步，其中冻结旧表示及旧数值的条款已失效。

## 1. 工具错误

同一次工具错误先生成一个 error 对象，再分别保存记录和构造消息：

```python
error_obj = {"error": original_error_text}
workflow_step.content = error_obj
tool_message["content"] = json.dumps(error_obj, ensure_ascii=False)
```

workflow.content 是字典对象，消息 content 是字符串；JSON 解码消息正文后，应与 workflow.content 相等。以上为设计示意，统一包装不修改工具错误原因。异常文本不再作为新 workflow 的裸字符串；已有合规业务 error 对象复用。

对应工具回复进入上下文的形式：

```json
{
  "role": "tool",
  "tool_call_id": "call_123",
  "content": "{\"error\":\"<原有工具错误内容，保持不变>\"}"
}
```

- 使用真实 tool_call_id，每次已处理调用只有一个匹配回复；不另加 user/system 错误消息。
- 发起调用的 assistant 消息之后，先补齐同批所有工具回复，再放执行过程中暂存的其他通知。
- 本轮不改变工具历史的保留规则；不自动删除失败、不永久钉住失败、不自动推断已经修复。
- 运行继续时，工具错误随正常历史进入后续请求，不采用 LLM 纠错的一次性移除规则；若运行已停止，不为发送错误额外发起 LLM 请求。
- 三类工具失败均按 README 记为 TOOL_ERROR；成功结果的消息和 workflow 内容沿用原处理方式。一次调用只保留一个工具步骤，不再加一条错误反馈步骤。
- 将来若裁剪工具历史，只改变发送视图；完整 workflow 与运行记录保留，工具调用/回复必须保持合法关联。

## 2. LLM 错误：只反馈给紧接着的一次请求

```json
{
  "role": "system",
  "content": "{\"error\":\"Previous response was truncated at the output token limit. No tool calls from that response were executed. Generate a shorter, complete response.\"}"
}
```

system 表示框架提供的生成纠正反馈，不是第三类系统/引擎报错。文案由程序根据已识别原因生成，不直接拼入模型原始无效输出；不伪造 tool_call_id。

一次性生命周期：

每个 Agent 运行独立管理待发送反馈；新的运行或场景不得继承上一运行剩余的反馈。

1. 第 N 次请求产生不可用响应：保留拒绝记录，生成对应反馈；该响应不进入有效 assistant 历史，其中工具不执行。
2. 若现有规则允许继续，反馈只放进第 N+1 次**实际 LLM client 调用**的临时消息列表。
3. 到 client 调用边界时消费该反馈。无论 N+1 成功、再次被拒绝，还是发生网络异常，旧反馈都不得进入 N+2。
4. 如果 N+1 又产生新的不可用响应，生成属于 N+1 的新反馈，供 N+2 使用。文案即使相同，也是新的错误；按来源请求编号区分。
5. 如果下一次请求尚未发生就停止，只保留错误记录，不增加一次 LLM 调用，也不标记反馈已经使用。

有效历史不追加这条临时消息；它仅出现在那一次请求的发送副本中，不进入用于校验 Agent 的 workflow。

这里的“下一次”按 FAIRY 调用 LLM client 的边界界定，包含外层重试请求；SDK 内部 HTTP 重试仍按现有机制处理，不另定义一次 Agent 请求。未调用 client 的本地准备失败不消费反馈。

例：

```text
请求 10：截断 → 记录错误 E10
请求 11：携带 E10 → 网络失败
请求 12：不携带 E10
```

```text
请求 20：截断 → 记录错误 E20
请求 21：携带 E20 → 空响应，记录新错误 E21
请求 22：只携带 E21，不携带 E20
```

不改变现有重试次数、等待策略、停止条件或基础设施故障处理。实际请求增加了反馈时，记录的 response_policy 必须如实反映请求可能变化，不能继续笼统声称 retry_changes_request=False。

## 3. 如何在场景运行后定位

沿用现有完整 `*.runtime_log.jsonl`。新运行按 README 重新分类工具主结果事件，并附加必要关联字段；已经生成的历史文件不追溯改写。

response_policy.retry_changes_request 须如实反映新行为，messages 快照记录实际发送内容。不能为保留旧字段值而记录失真的请求。工具事件类型/status 按新协议变化；全部旧统计字段、显示与计算方法保持不变，只追加新四项，旧数值可因输入变化而变化。

| 位置 | 保留或附加的信息 |
|---|---|
| 工具主结果事件 | 按 README 设置事件类型/status；附加 is_error、完整 agent_feedback；使用运行归属、事件序号及 tool_call_id 定位 |
| 对应工具 runtime_metrics 行 | 失败 status=error、is_error=true；每次已处理调用一行，不因附加反馈重复计数 |
| LLM 开始与结束事件 | 附加本次运行内唯一的 llm_call_id；保留原时间、响应和判定信息 |
| 拒绝的 llm_call_end | 保留 accepted=false、rejection_reason；附加完整 agent_feedback |
| 实际携带反馈的 llm_call_start | 保留本次发送的 messages 快照；附加 feedback_for_llm_call_id，指向反馈来源 |

- agent_feedback 保存完整 `{"error":"..."}` 对象；工具失败时，它与 workflow.content 及实际 tool.content 解码结果一致。原有 error_type/error_message/raw_arguments 等诊断信息继续如实记录；业务错误不伪造异常类型，短 preview 不能代替完整反馈。
- 若请求没有携带临时反馈，不填写其来源；历史日志快照不得因后续移除反馈而被修改。
- 拒绝后停止仍有拒绝记录，但不存在对应的反馈使用请求。
- 日志只能证明“反馈纳入了哪个 client 请求”；网络失败时不能宣称服务端已收到。
- 当前进度日志省略完整 messages，最终诊断应查看 runtime_log.jsonl。agent_workflow.json 不记录 LLM 响应错误，也不加入 LLM 纠错步骤。
- 同一个 tool_call_id 不应作为跨运行唯一身份；请求/事件编号需限定在所属 Agent 运行内。
- 工具错误原因在日志、workflow 和实际消息中一致，只有对象/字符串的存储类型不同。LLM 错误原因保留在运行日志及其一次性请求中，不出现在 workflow。

## 4. workflow、回放与评估的范围

- 回放与评分使用完整 workflow，不从裁剪后的消息或临时 LLM 反馈列表重建评估轨迹。工具失败的 content/op_type/error_stage 按新协议保存，工具名、参数、顺序、实际时间不变。
- 不给 workflow 增加 LLM 错误、重试或反馈节点，不把被拒绝响应中的工具变成实际工具调用。
- 本协议覆盖的记录转换须保留失败事实及原阶段；若转换为 CompletedEvent 再导出 workflow，也不能仅凭工具读/写类型覆盖掉 TOOL_ERROR。必要字段传递属于协议适配，不等于给 gate 增加成功条件。
- TOOL_ERROR 表示调用失败，不代表工具未执行、无状态变化或应自动重试。解析失败的未执行事实不能在转换中丢失；tool_call 阶段不能被一律当作未执行。
- 本轮不主动改变 gate、路径指标、安全关键词、回放是否执行/缺工具恢复/结果比较策略或 controller 分流。只读检查这些消费者，区分旧缺陷与由新记录触发的行为变化；超出字段传递的修复单独提出。
- 当前消费者并非全按同一失败字段判定：有的读 TOOL_ERROR，有的读 content.error，有的只匹配工具名/参数。规则不变仍可能因为输入表示改变而变分；既有误判不得被描述为协议已解决或必然合理。
- 历史数据保留原貌，新运行按新协议；不以固定旧分数、旧统计值或旧 workflow 字节完全一致作为验收条件。LLM 纠错不进入评估输入，但它引导的新操作仍正常参与评估。

## 5. 必须通过的验证

- 三类工具错误：事件/指标/workflow 标签符合 README；workflow.content 是对象，实际下次请求的 tool.content 是合法 JSON 字符串，解码后二者及 agent_feedback 相等，原有错误文字不变。
- 工具名、参数、实际时间与业务执行不因包装改变；成功输出沿用原方式。每个已处理请求只处理一次，工具方法至多执行一次，解析/查找等执行前失败不执行工具；记一个主结果事件、一条指标及一个原工具步骤。
- 同批多个工具包含异常及执行期间通知：先补齐对应 tool 回复，再插入暂存通知，调用与回复不遗漏、不重复。
- LLM 拒绝→有效响应→后续请求：反馈只出现一次；日志始终可定位原错误及使用位置。
- LLM 拒绝→网络失败→重试：旧反馈不进入第二个后续请求。
- 连续两次拒绝：两次错误各计一次，各自反馈只关联一次请求。
- 拒绝后停止：不增加请求，不伪造反馈已经使用。
- 统计验收分两步：同一日志/指标输入下，新增四项前后全部旧字段结果相同；换成新协议事件后，旧数值变化应由事件重分类解释。新四项满足 README 的口径与减法关系，不重复计数。
- 记录转换：失败对象、TOOL_ERROR 和原 error_stage 不丢失；Agent JSON 字符串不能直接替代 workflow 对象。
- 回放/评估兼容核查：记录实际是否执行、失败事件是否保留、缺失工具如何处理、原结果与回放结果是否不同；区分预期识别变化、既有判别缺陷和迁移引入的问题，不以“允许分数变化”代替解释，也不自动扩大评分修改范围。
