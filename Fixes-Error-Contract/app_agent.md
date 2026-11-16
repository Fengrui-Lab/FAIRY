# app_agent.py 错误与校验审阅

源文件：[fairy/controllers/app_agent.py](../fairy/controllers/app_agent.py)

覆盖 FinalAnswerApp.final_answer、AppAgent.expert_agent 两个工具。达到调用上限时返回 partial 说明是现有显式策略，不能只因没有 error 键判为协议缺陷。

已审阅入口：`final_answer`（L31）、`expert_agent`（L77）。

类型①：已有错误提示不清晰或不准确。类型②：缺少应在执行前完成的校验。P1：可能破坏状态；P2：影响行为或纠错；P3：提示可读性。

## 1. 【类型② / P2】委派任务/最终回答缺少字符串输入校验

- 位置：[31-38, 77-101](../fairy/controllers/app_agent.py#L31)。
- 现状/触发：final_answer 使用 str(answer)，expert_agent 用 str(task)，会把 null、数组/对象转换为文字并当作合法任务或最终回答；委派前还重置专家会话。
- 建议：在重置会话或运行专家前检查 task 的字符串类型；final_answer 检查 answer 类型。错误给字段名及允许类型，避免用隐式字符串化掩盖坏输入。

## 验收重点

对上述触发输入确认返回非空字符串 `error`；拒绝发生在扣减资源、修改作物或推进时间之前。提示改动应与实际阈值一致，并覆盖修正后的合法调用。没有写明“实测”的项目为静态路径审阅结论。
