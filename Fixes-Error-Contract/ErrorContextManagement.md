# 错误反馈的上下文管理

状态：设计文档，待用户校准后再实施。更新：2026-11-15。
反馈格式与新增统计遵守 [README.md](/Users/hanlinyuan/Documents/Codex_Projects/FAIRY/Fixes-Error-Contract/README.md)。

## 1. 工具错误

以对应工具回复进入上下文；content 是 error 对象的 JSON 字符串：

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
- 外发反馈独立生成；现有 workflow 继续保存原始结果及原异常表示，不用新 JSON 反馈覆盖它。
- 将来若裁剪工具历史，只改变发送视图；原始 workflow 与运行记录保留，工具调用/回复必须保持合法关联。

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

沿用现有完整 `*.runtime_log.jsonl`，只附加必要字段，不重写旧事件。

兼容要求不冻结请求描述：response_policy.retry_changes_request 允许更新为符合新行为的值，messages 快照必须记录实际发送内容；旧事件类型/status/计数与评估输入仍保持。

| 位置 | 保留或附加的信息 |
|---|---|
| 既有工具主结果事件 | 原有字段不变；附加 is_error、实际生成的 agent_feedback；使用运行归属、事件序号及 tool_call_id 定位 |
| LLM 开始与结束事件 | 附加本次运行内唯一的 llm_call_id；保留原时间、响应和判定信息 |
| 拒绝的 llm_call_end | 保留 accepted=false、rejection_reason；附加完整 agent_feedback |
| 实际携带反馈的 llm_call_start | 保留本次发送的 messages 快照；附加 feedback_for_llm_call_id，指向反馈来源 |

- agent_feedback 保存 `{"error":"..."}`；它是日志附加信息，不替代旧 error_message、content_preview 或 workflow.content。
- 若请求没有携带临时反馈，不填写其来源；历史日志快照不得因后续移除反馈而被修改。
- 拒绝后停止仍有拒绝记录，但不存在对应的反馈使用请求。
- 日志只能证明“反馈纳入了哪个 client 请求”；网络失败时不能宣称服务端已收到。
- 当前进度日志省略完整 messages，最终诊断应查看 runtime_log.jsonl。agent_workflow.json 不记录 LLM 响应错误，也不加入 LLM 纠错步骤。
- 同一个 tool_call_id 不应作为跨运行唯一身份；请求/事件编号需限定在所属 Agent 运行内。
- 日志保留原始评估结果与真实 Agent 展示反馈；统一展示后，这两份文本不必相同，不能再假定 workflow.content 就是实际发送的全部文字。

## 4. 不影响旧回放和评分的约束

- 回放与评分继续使用原 workflow；不从裁剪后的消息或临时反馈列表重建评估轨迹。
- 不改 workflow 的 content、op_type、error_stage、工具名、参数、顺序、时间及其既有构造逻辑。
- 不给 workflow 增加 LLM 错误、重试或反馈节点，不把被拒绝响应中的工具变成实际工具调用。
- 不为新统计改变旧 runtime 事件的数量、类型和含义；附加元数据不应被旧读取器重新解释。
- 不改评分公式、错误关键词判断、回放是否执行的规则或 controller 的原有行为。
- 在固定调用/轨迹、环境和实现版本下检验旧结果一致。模型得到新反馈后的新轨迹可能不同，这属于交互改变，不能承诺重跑仍同分。

## 5. 必须通过的验证

- 工具错误：反馈为合法 JSON；实际下次请求有正确 tool_call_id；原始结果和旧 workflow 与改造前一致。
- 同批多个工具包含异常及执行期间通知：先补齐对应 tool 回复，再插入暂存通知，调用与回复不遗漏、不重复。
- LLM 拒绝→有效响应→后续请求：反馈只出现一次；日志始终可定位原错误及使用位置。
- LLM 拒绝→网络失败→重试：旧反馈不进入第二个后续请求。
- 连续两次拒绝：两次错误各计一次，各自反馈只关联一次请求。
- 拒绝后停止：不增加请求，不伪造反馈已经使用。
- 同一合成事件序列：旧统计不变，新四项满足 README 的减法关系。
- 固定 trace：旧回放动作、评分与结果保持一致；LLM 反馈不成为评估步骤。
