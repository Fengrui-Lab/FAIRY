# app_agent.py

源文件：[fairy/controllers/app_agent.py](/Users/hanlinyuan/Documents/Codex_Projects/FAIRY/fairy/controllers/app_agent.py)。共 2 个工具；以下为审阅稿。

## FinalAnswerApp.final_answer

能力边界：返回委派任务的最终答复文本，本函数不执行农场操作，也不直接终止运行。

```python
"""
Description:
    Return the final answer for a delegated task.

Args:
    answer: Concise results, including any unfinished work.
"""
```

## AppAgent.expert_agent

能力边界：将当前应用范围内的任务交给专家 Agent；专家可实际调用该应用的工具，返回文字结果，达到调用限制时可能仅部分完成。

```python
"""
Description:
    Ask this app's expert agent to complete a task using the app's tools. The expert may
    take actions and returns a result summary, which may describe partial completion.

Args:
    task: Specific task, relevant context, and constraints for this app's expert.
"""
```
