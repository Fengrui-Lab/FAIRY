# agent_user_interface.py

源文件：[fairy/apps/agent_user_interface.py](/Users/hanlinyuan/Documents/Codex_Projects/FAIRY/fairy/apps/agent_user_interface.py)。共 2 个工具；以下为审阅稿。

## AgentUserInterface.send_message_to_agent

能力边界：向 Agent 传递消息并返回原文，通常用于下发任务说明；常规 Agent 工具集中隐藏此入口。

```python
"""
Description:
    Send a message to the agent and return the message text.

Args:
    content: Message or task instructions to send to the agent.
"""
```

## AgentUserInterface.send_message_to_user

能力边界：向用户发送任务结果或受阻说明并返回原文，不执行农场操作。

```python
"""
Description:
    Send the user a completion report or an explanation of why the task cannot be
    completed. Return the message text.

Args:
    content: The result or explanation to send to the user.
"""
```
