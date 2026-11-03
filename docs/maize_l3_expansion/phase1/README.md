# 阶段1：玉米L3候选规格与首轮配对设计

日期：2026-11-03。阶段0已通过，本次落实用户粘贴评审的阶段1范围。阶段0报告保留原文；本目录补充其实现细节，不追改历史审计身份。

**交付状态：规格设计完成；生产场景未实现，4条配对轨迹尚未启动，无模型请求。** 当前不是十场景准入或全季验收通过。

## 审阅入口

- `candidate_review.md`：十项独立性、合并/暂缓理由、实施优先级。
- `candidates/<ID>/scenario_spec.yaml`：十份完整规格卡。
- `candidates/<ID>/agent/task.zh.txt`：逐项完整中文任务说明，不依赖拼接模板阅读。
- `candidates/<ID>/agent/additional_system_prompt.txt`：新增场景指令约定。
- `candidates/<ID>/agent/tool_catalog.json`：从当前对应场景setup后实查的公开菜单、schema、描述。
- `interface/public_interface_contract.md`：允许的公开字段和最终运行时接口核验。
- `evaluation_contract.md`：流程终态、粮食结果、操作与恢复三套独立记录。
- `pilot_pair_plan.yaml`：W01/N01四条最小运行计划、全部剂量和环境引用。
- `shared_executor_contract.md`：共同回执、等待、去重和不确定投入处理规则。
- `result_decision_rules.md`：E1/E2、弱响应、无效配对与停止规则。
- `freeze/environment.json`：Python/PCSE、依赖、参数与评分/重放源码哈希；现有评分版本仅记录不切换。
- `freeze/development_configs.json`：两个拟实施开发环境的有效配置、源配置与显式差异。
- `freeze/development_and_holdout.json`：分组登记；当前没有冒充未见留出的环境。
- `design_validation.json`：规格结构、剂量、接口文件及生产源码未改的文档验收结果。

## 三项评审修订

1. **200kg不是基肥工具下限。** N60/N120指包含基肥追肥的全季实际外源元素N、回收前口径。首轮全部显式正剂量基施，禁止沿用旧build_maize_establishment的200kg或旧topdress。库存/配额同为360kg产品，不能通过不同库存制造对照。
2. **不直接继承所有工具error/warning整季失败。** 旧校验器结果原样保留，新的终态与操作恢复合同单列，不在管线抹去原生失败或篡改Succ.。只有以后在新场景内实现并验收本合同后才可部署；旧场景和旧评分不变。
3. **最终完整说明整体替换。** detailed_briefing=False仍保留旧基础文本中的200kg，本目录保存的是目标最终文本。当前新类尚不存在，因此不能假称已从Agent运行截获；阶段2必须把Engine/Agent实际收到的任务、附加system指令和工具schema导出，逐字/逐字段与目标合同核对后才运行。

## 工作量边界

优先只实施W01/N01两配对，每项一个开发环境、合计4条轨迹。没有共享参考轨迹，因为缺水/低氮环境不同。S01/W02随后筛选；S02合并、W04作为环境变体、W03暂缓、W05/N02先过信息门禁、N03仅做机制诊断。正式场景数量依证据确定，不预先承诺十个通过。

不将完整生理校准、双PCSE版本认证或外部田间定量拟合作为本轮前置。历史结果继续保留其原始身份，新基线只用本轮PCSE6.0.13；不降级依赖、不重置工作树、不改动运行实验。
