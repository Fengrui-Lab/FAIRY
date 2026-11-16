# agent_user_interface.py 错误与校验审阅

源文件：[fairy/apps/agent_user_interface.py](../fairy/apps/agent_user_interface.py)

覆盖 send_message_to_agent、send_message_to_user 两个装饰工具；前者按运行配置对普通 Agent 隐藏，仍因本次要求全量审阅而列出。未发现类型①既有业务错误。

已审阅入口：`send_message_to_agent`（L15）、`send_message_to_user`（L35）。

类型①：已有错误提示不清晰或不准确。类型②：缺少应在执行前完成的校验。P1：可能破坏状态；P2：影响行为或纠错；P3：提示可读性。

## 1. 【类型② / P2】消息内容未校验字符串类型

- 位置：[15-31, 35-49](../fairy/apps/agent_user_interface.py#L15)。
- 现状/触发：两个入口直接 append 并原样返回。实测 send_message_to_user(None) 返回 None，消息列表也收到 None；调用层不把这种结果判成错误。
- 建议：append 前拒绝非字符串并给 content 的类型要求；是否拒绝空白内容可另定产品约束，不把它当成已存在的硬性规则。

## 验收重点

对上述触发输入确认返回非空字符串 `error`；拒绝发生在扣减资源、修改作物或推进时间之前。提示改动应与实际阈值一致，并覆盖修正后的合法调用。没有写明“实测”的项目为静态路径审阅结论。
