

# FAIRY minimal fixes, Status Report: (✅表示已经push到了“https://github.com/Fengrui-Lab/FAIRY/tree/test_Knowledge”中)
1. ✅ 工具的tag：解决工具tag与工具能力边界不统一的问题；所有会改变当前系统状态的都是WRITE，所有不改变当前系统状态的只读操作都是READ
2. ✅ 工具的doc和schema：解决工具doc板式不清晰、schema中description字段缺失和堆积的问题；[详见Fixes-Tools-Doc-Schema/README.md](Fixes-Tools-Doc-Schema/README.md)
3. ✅ （第一类）反馈给 Agent 的工具调用错误的板式和逻辑，（第二类）LLM 响应不可用时用于后续生成修正的错误反馈的板式和逻辑：解决当前Agent调用工具的error格式和LLM相应的error格式的不统一、标签混乱、统计混乱的问题，统一了标签、补充了统计记录（运行场景oracle时，由于没有采集 Agent 的逐次 runtime_metrics，所以新工具指标可能显示为 0 或未知，不能据此判断 oracle 实际执行了多少次工具或发生多少次错误。）；[详见Fixes-Error-Contract/README.md](Fixes-Error-Contract/README.md)
4. ✅ 上下文结构中上述两类error的载入逻辑和位置：解决当前代码中error载入上下文的格式不统一，提示内容缺失的问题；上述第一类错误统一了格式和载入方式，第二类错误以临时的system反馈实现（可通过日志中的feedback_for_llm_call_id追踪第二类错误的位置）；[详见Fixes-Error-Contract/README.md](Fixes-Error-Contract/README.md)
5. (Ongoing) Library：FAIRY Library中知识抽取时可能利用了工具的tag，这一模式需要校对；[详见Fixes-Knowledge-Library/README.md](Fixes-Knowledge-Library/README.md)
6. (Ongoing) Library：知识载入的多模式划分，以及其内容、格式、位置、时间的校对；[详见Fixes-Knowledge-Library/README.md](Fixes-Knowledge-Library/README.md)
7. <span style="background-color:#FF5722; color:white;">TODO</span> 工具的删减（推进时间的工具advance_time、wait_for_notification、commit_daily_physics功能重叠）
8. <span style="background-color:#FF5722; color:white;">TODO</span> LLM的“思考”模式等其他参数的配置只打通了vllm，通过enable_thinking参数配置。
9. <span style="background-color:#FF5722; color:white;">TODO</span>: 重新校准所有工具doc的内容（已经准备好了一个校准好的版本，位于Fixes-Tools-Doc-Schema中的一系列以脚本文件为单位的md中）并测试，同时与老版本对比
10. <span style="background-color:#FF5722; color:white;">TODO</span>: 重新校准所有工具error的内容（尚未校准）并测试，同时与老版本对比
11. <span style="background-color:#FF5722; color:white;">TODO</span>: 当前的回放、评分逻辑的校准与修正（尚未校准）；目前观察到有多个回放与评估脚本/模式；一些被抛弃的统计指标（如FOS）也还仍然在被计算和记录
12. <span style="background-color:#FF5722; color:white;">TODO</span>: Library：如何补充当前的静态的知识载入？如何实现动态的知识载入？




