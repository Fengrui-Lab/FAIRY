# agent.py 错误与校验审阅

源文件：[fairy/agents/agent/agent.py](../fairy/agents/agent/agent.py)

共享 Agent 调用层，无直接 @app_tool；用于说明工具异常最终如何到达 Agent。现有顶层 error 分类和保留原始错误值是 README 既定协议，不要求增加 status/code/type 字段。

类型①：已有错误提示不清晰或不准确。类型②：缺少应在执行前完成的校验。P1：可能破坏状态；P2：影响行为或纠错；P3：提示可读性。

## 1. 【类型① / P2】所有异常使用相同的“改参数重试”建议

- 位置：[189-202, 257-284](../fairy/agents/agent/agent.py)。
- 现状/触发：_tool_exception_feedback 对 TypeError、KeyError、内部执行故障均要求 retry with valid arguments。若工具已扣电/扣药/改时间才失败，文本不会提示已发生的副作用，容易诱导重复操作。
- 建议：预期业务错误在工具内精确说明；内部执行异常提示失败阶段和状态可能已变，建议查询资源/时间后再决定。未知工具 KeyError 应说明工具不存在并给有效入口，不只回显 KeyError。

## 2. 【类型② / P2】解析后没有校验参数对象结构及字段类型

- 位置：[212-214, 257-258](../fairy/agents/agent/agent.py)。
- 现状/触发：json.loads 可以得到 null、数组或标量；随后 **args 才抛 Python 异常，未验证 schema 的字段类型/有限数。json.loads 默认也接受 NaN/Infinity。
- 建议：调用前要求 JSON object，检查参数名/必填和执行类型契约；拒绝非标准数值或在数值验证器中统一挡住。保持一次调用只计一次错误。

## 验收重点

对上述触发输入确认返回非空字符串 `error`；拒绝发生在扣减资源、修改作物或推进时间之前。提示改动应与实际阈值一致，并覆盖修正后的合法调用。没有写明“实测”的项目为静态路径审阅结论。
