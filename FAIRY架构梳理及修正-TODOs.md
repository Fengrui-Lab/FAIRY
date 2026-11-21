

# FAIRY minimal fixes, Status Report: (✅表示已经push到了“https://github.com/Fengrui-Lab/FAIRY/tree/test_Knowledge”中)
1. ✅ 工具的tag：解决工具tag与工具能力边界不统一的问题；所有会改变当前系统状态的都是WRITE，所有不改变当前系统状态的只读操作都是READ
2. ✅ 工具的doc和schema：解决工具doc板式不清晰、schema中description字段缺失和堆积的问题；[详见Fixes-Tools-Doc-Schema/README.md](Fixes-Tools-Doc-Schema/README.md)
3. ✅ （第一类）反馈给 Agent 的工具调用错误的板式和逻辑，（第二类）LLM 响应不可用时用于后续生成修正的错误反馈的板式和逻辑：解决当前Agent调用工具的error格式和LLM相应的error格式的不统一、标签混乱、统计混乱的问题，统一了标签、补充了统计记录（运行场景oracle时，由于没有采集 Agent 的逐次 runtime_metrics，所以新工具指标可能显示为 0 或未知，不能据此判断 oracle 实际执行了多少次工具或发生多少次错误。）；[详见Fixes-Error-Contract/README.md](Fixes-Error-Contract/README.md)
4. ✅ 上下文结构中上述两类error的载入逻辑和位置：解决当前代码中error载入上下文的格式不统一，提示内容缺失的问题；上述第一类错误统一了格式和载入方式，第二类错误以临时的system反馈实现（可通过日志中的feedback_for_llm_call_id追踪第二类错误的位置）；[详见Fixes-Error-Contract/README.md](Fixes-Error-Contract/README.md)
5. ✅ System prompt 的结构和内容的校验，进一步区分“固定公用部分、可选（可注入）部分、Scenario 私有部分”；[详见Fixes-Knowledge-Library/README.md](Fixes-Knowledge-Library/README.md)
6. ✅ Library：false模式的语言表达顺序的校准；FAIRY Library中知识抽取时可能利用了工具的tag，已经校对，前置改动无影响；[详见Fixes-Knowledge-Library/README.md](Fixes-Knowledge-Library/README.md)
7. ✅ Library：知识载入的多模式划分，以及其内容、格式、位置、时间的校对；同时拓展了detailed_briefing==structured_true的结构化场景任务与知识的载入模式；调整部分全季任务的表达语序，统一表达方式；[详见Fixes-Knowledge-Library/README.md](Fixes-Knowledge-Library/README.md)
8. ✅ 校准支持的LLM的参数配置，补充常用参数的支持，处理了：（1）temperature已打通 runner CLI/JSON、默认为0.1，部分openai模型不支持该参数便不传；（2）Agent 重试次数已打通 runner CLI/JSON，默认为通过环境变量FAIRY_AGENT_LLM_CALL_RETRIES读取默认赋值 5；（3）vllm模式下的enable_thinking参数打通 runner CLI/JSON，其余模式未改动（4）各类 LLM 的 endpoint 配置已打通 runner CLI/JSON。
9. ✅ 时间推进工具的删减与整合（推进时间的工具advance_time、wait_for_notification、commit_daily_physics功能重叠，仅保留advance_time；有一个需要记录的连带反应，即“时间戳重建”，因为commit_daily_physics不会被Engine计入时间增量，已经完成了140个场景的oracle完整运行，未发现异常）
10. (由于是内容层面的修正，将会与之前的FAIRY产生差异；已经有方案和相应内容准备，未实施) 重新校准所有工具doc的内容（新版本位于[Fixes-Tools-Doc-Schema](Fixes-Tools-Doc-Schema)中的一系列以脚本文件为单位的md中）并测试，同时与老版本对比
11. (由于是内容层面的修正，将会与之前的FAIRY产生差异；已经有方案和相应内容准备，未实施) 重新校准所有工具error的内容（修改建议位于[Fixes-Error-Contract](Fixes-Error-Contract)中的一系列以脚本文件为单位的md中）并测试，同时与老版本对比
12. ✅ LLM的"thinking大类"的参数配置，补充代码实现，默认均为不开启思考（流式调用与非流式调用未纳入考虑范畴，仅遵循当前的FAIRY的解析操作的非流式版本），处理了：（1）补充了deepseek API的[thinking支持](https://api-docs.deepseek.com/guides/thinking_mode#tool-calls)**（测试通过）**；（2）补充了qwen API的[enable_thinking, preserve_thinking支持](https://www.alibabacloud.com/help/en/model-studio/deep-thinking)**（测试通过）**；（3）补充了本地vLLM（截止261118）已有系列Qwen模型的的enable_thinking支持**（测试通过）**
13. ✅ Library：Original-library-mode (static-knowledge-construction--static-retrival method) fixes if needed.
14. Library：（1）什么样的知识库结构适合FAIRY？（2）什么样的存储和检索模式适合FAIRY？（3）如何补充当前的静态的知识载入？
15. <span style="background-color:#FF5722; color:white;">(Less-prioritized)TODO</span>: Library：（4）❗需要注意改变上下文的动态知识注入对于“cashed_tokens和LLM成本”的影响❗️如何实现动态的知识载入？谁是触发知识检索的主体？
16. (Currently assuming the metrics' calculation and FAIRY engine is valid and robust) <span style="background-color:#FF5722; color:white;">(Less-prioritized)TODO</span>: Engine & Yield (recovered) 演进和计算模式的校准（当前的回放、评分逻辑的校准与修正；目前观察到有多个回放与评估的脚本/模式；一些被抛弃的统计指标也还仍然在被计算和记录；一些如yield（biological，reserved）和ktc（ktc_score(%)、ktc_adjusted、ktc(%)）等存在多个别名指标），并基于此反向校准每个Scenario的Oracle
17. (Currently assuming the language does not affect an LLM's understanding of tasks or the quality of its output.) <span style="background-color:#FF5722; color:white;">(Less-prioritized)TODO</span>: 统一代码库中所有描述所用的语言，或者实现双语适配。
