# 正式90例 Oracle 管理校准

本轮沿用恢复后的 WOFOST + 多农场工作目录，不修改原 `multi-farm` 工作目录源码。正式集合仍是 `scripts/fullseason/formal_90_scenario_ids.txt` 的90个ID。交付范围包括逐场源码审查、品种参数分配、实际管理时机修正、剂量/删除对照、候选组合检查及从新场景开始的回放。

实际代码目录为 `/Users/quao/.codex/worktrees/wofost-management-audit/FAIRY`，分支 `codex/wofost-management-cultivars-oracle-audit`。

本轮的“校准”是指定模拟模型下的管理方案校准。它不是田间产量标定，不证明所有管理动作都符合某种真实药剂标签，也不证明找到了全局最高产。

## 最终数据入口

- [90例总表和逐场证据](/Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_formal90_recalibration_20261024/final_v1/REPORT.md)
- [独立核验结果](/Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_formal90_recalibration_20261024/final_v1/independent_verification.json)
- [完整工作流目录](/Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_formal90_recalibration_20261024/final_v1/calibrated_workflows)
- [品种来源、弱约束拟合与90例分配](oracle-cultivar-mapping.md)
- [90例播种参数复核](oracle-sowing-parameter-review.md)
- [7例补种的模型边界](formal90-native-replant-boundary.md)

每例的 `cases/<ID>/report.md` 和 `action_review.json` 分别说明原来的管理时刻/剂量、实际生育期与剂量、修改原因、对照效果及没有实现的场景机制。最终通过数量以总表及独立核验为准，预跑结果不能计入正式通过。

本次正式结果为：90例全部审查，覆盖238次原管理调用；83例完成全季与新场景严格回放，7例因原生补种能力不足保留阻断。主批实际执行237个对照，其中210个完整可比较、27个真实不可行；67例有消融对照，另23例明确没有该项已执行证据。补充水量搜索检查全部90例，其中27例有真实灌溉计划可比较，共运行29个候选，12例采用增产超过0.1kg且回放一致的高水计划；最终83份方案为71份主批方案和12份高水方案。

完整执行与机制覆盖分别计数：90例中26例仍有原任务机制缺口或补查的设备边界，其中19例虽可完整运行，也不能据此声称原任务机制已经全部校准。逐动作记录200次修改、11次删除、7次不支持、20次未执行至；“修改”包括实际阶段和时刻改变，不等于发现200个独立农艺错误。83份发布工作流均逐字节匹配实际选定文件，7份原未支持流程原样保留；508份模拟源码/数据的运行前、运行后、冻结副本与当前文件一致。

全部原生批量运行结束后，最终低负载全库回归为 **931 passed，113.68秒，0失败/跳过**。原日志、JUnit、命令和来源保存在最终目录的 `regression/` 及 `code_changes/test_evidence/`；此前并行负载下的1次超时失败和单项重跑记录仍按阶段保留，没有改写为当时已全绿。

## 品种和生理模型的边界

六个原有种子身份采用显式档案：黑农84、黑农58、黑农60、黑河50、黑河43、黑科71。新增五份完整78参数档案，以原黑农84生理背景为工程转移基础，只用公开成熟期资料约束 `TSUM1/TSUM2` 的共同缩放；固定二者比例的假设单独登记。筛选使用2017年独立真实天气，不使用这90场景的产量、风险窗口或收获结果。2018、2019天气只作独立原生运行诊断。

相同证据可以得到相同参数。黑农58和黑农60的本次热量参数相同；黑农58和黑农84保留同一 `DEPNR=5`，不能声称据此建立了黑农58更耐旱的原生定量响应。公开品种身份与完整生理参数的田间验证是两个层次。

品种档案中引用的土壤背景不覆盖实际场景输入。每例以原生specification里的 `RDMSOL/SMW/SMFCF/SM0/NAVAILI/NSOILBASE` 为准，例如黑农60基准实际 `RDMSOL=40cm`，不能把背景资料里的120cm写成所有场景的土层。本轮保留原场景土壤假设，没有用Oracle产量反向标定土壤。

凉八月案例另有显式播前适应：原黑农84在原180天期限内未成熟，改为有区域和成熟期资料的黑农58后重新运行。原天气、期限和其他资源保留，原黑农84失败对照保留。这个运行是品种选择适应方案，不能改写成“黑农84已成熟”。

## 管理时机怎样修正

`scripts/formal90_calibration_policy.py` 负责计划，物理结果仍由真实App和原生后端计算：

1. 固定日历等待使用原计划的北京时间绝对日期，已到该日时不再重复累加天数。
2. 出苗、R1、R5和收获观察窗口读取公开生育期；混播/错期场允许先到阶段的区先开启巡查，各次管理再确认自己的目标垄范围。
3. R1水肥和R5水肥/灌溉分别确认目标区实际阶段；晚过原窗口会登记，不能把阶段标签当作已经达到阶段的证据。
4. 收割依据公开机器含水率上限、目标区R8和当前天气。粗粒度探头不直接替代每条目标垄的可通行性判断；机具前置检查拒绝后，只有确认公开时钟、机器、库存和目标状态未改变，才重新等窗口。失败尝试单独留存，成功收割只执行一次。
5. 地面检查拆成每次真实4垄并核实覆盖。无人机按公开电量的实际消耗分批、充电、继续覆盖；30%是规划安全余量，不冒充读取到了设备内部返航阈值。
6. 原人工喷药计划把 `advance_time=False` 改为真实作业耗时，原始输入和修正原因同时保留。种子不足时只能从原有仓库补充装载，不能增加库存。

决策使用注册工具的公开响应。原生DVS、TWSO、水分和N等私有状态只进入审计及事后对照，不进入阶段门控。

## 参数和冗余如何判定

原管理调用先按一个实际管理决定分组：同一次喷杆、人工背负喷药或中耕决定的多次机具通过属于一个episode。对每组测试：保留原剂量、整组省略、半量；化学药剂再测试设备模拟参考量。机械除草没有虚构的“半药量”参数。

省略使用真实 `SystemApp.get_current_time` 占位，保留原始开始/结束时间；其余操作参数和绝对时刻固定，省去的作业时段成为等待。半量水肥保持原载水量，只减肥料产品；整次水肥省略同时省肥和载水，不能单独归因于N。半时长灌溉改变水量及其固有交付时机，不能解释成独立于交付时间的纯水量试验。

多个单项可省略或可降量的结论不能直接相加。脚本另外运行联合省略和各episode较好选择的组合，仍受原资源、时间及工具限制；不可行的候选保留错误证据而不参与选择。

目标是安全入库标准水分质量。候选在最高已测试产量的0.1kg范围内视为模拟口径等效，再依次比较管理调用数、化学工作液、肥料产品及灌溉量。此排序不是财务成本模型。最终选择会在新场景重放，并比较所有响应、参数、绝对时间和完整公开物理/原生快照。

`scripts/calibrate_formal90_oracles.py` 负责这些运行；`scripts/verify_formal90_oracle_calibration.py` 独立从粮食回执、每垄原生TWSO和实际面积复算，不能只信driver写出的总量。

补充灌溉搜索使用独立的 `scripts/extend_formal90_water_search.py`：以主批次选定方案为基线，测试原参考计划灌溉小时数的两倍，包括恢复主批次已省略的水操作。增加泵时产生的真实超时会顺延后续计划，原季末期限、已有额度及已建模的资源约束保留；因此这是水量与作业日程的组合比较，不是同一时刻的纯水量效应。多次灌溉的较好组合也须实际运行。只有完整合法、初态匹配、新场景回放一致且入库质量增加超过0.1kg时，才替代主选定方案。

该扩展不修改冻结的508文件，另存脚本自身指纹和每例 `supplemental_water_search/` 的完整证据。原 `selected/` 始终保留，最终发布清单明确采用哪一层方案。没有真实灌溉episode的场景不虚构水量试验；仍为零耗时抽象输入的水肥接口不参与放大载水量搜索。

## 本轮没有以“完成运行”代替的机制

默认肥料N比例为0.46。全64垄 `.24` 水肥实际是460.8kg产品、211.968kg N，另带指定载水。灌溉 `.65h` 为目标垄3.25mm。工作液参考量和药效系数仍是FAIRY经验模型参数，没有通过这次Oracle搜索变成现实药剂参数。

12例低肥/局部营养声明主要使用通用营养指数，尚未建立对应的分区原生初始N库存；K、微量元素和根瘤失效也没有专属原生机制。不能把某次N肥的模拟增益说成这些缺乏或故障的验证。叶面积移除、残茬碳氮分解、杂草反射掩盖及部分设备故障同样逐场登记代理或缺失边界。

这里的根瘤边界不是说PCSE没有固氮：当前档案的原生 `NFIX_FR=0.8` 按每日N需求的固定比例供氮；原“根瘤失效”场景只降低通用营养指数，没有把失效事件接到该比例或独立根瘤状态。因此正常固氮参数存在，故障机制仍未进入本场运行。12例低肥任务中“删肥不减产”的结果也只能说明当前原生输入下的表现，不能证明未被表达的真实缺肥不需要追肥。

补充复核还确认“分次灌水/电力限制”场景只有8mm水额度和规定的分次操作，没有独立kW/kWh、同时供水能力或电力不足事件。该例可验证已有水额度、串行作业时间和季末期限下的方案，不能据此声称电力调度任务已经校准；拖拉机燃油也不自动代表水泵柴油或电耗。这项发现以报告附录保留，冻结输入不作事后修改。

7例、14次补种调用仍有原生生命周期阻断：1例明确整垄重播，6例需要幸存苗与新苗同时存在。单个活跃冠层不能用重启整垄或提高stand替代两代苗及共享水氮。它们保留完整原Oracle、已执行部分和阻断证据，不导出伪造的成功候选。

一个排水差场景的原 `rainfall_capture_efficiency=1.02` 改为显式外部来水边界：当地雨不变，超出的2%日雨量单独记为场外run-on进入原生水账，和Agent实灌水分账。必须显式启用并给来源说明；默认仍拒绝大于1。该移植保留原经验假设，贡献区和空间水文未经标定。

播种密度另有90例审查及12例、13个分区的文献约束候选。候选保留种子身份、分区、播期和预算，单独运行。当前原生密度只缩放初始TDWI，不能据其单调增益识别真实密度最优；因此它们不会自动取代原场景的规定密度或故意密度对照。

## 复现

在本工作目录运行全部正式场景：

```bash
cd /Users/quao/.codex/worktrees/wofost-management-audit/FAIRY
env -u USER PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 \
  OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  .venv/bin/python scripts/calibrate_formal90_oracles.py \
  --all --workers 6 --experiments bounded \
  --output-dir /tmp/fairy-formal90-recalibration
```

回放某一份已交付的完整候选，包含该例的品种适应及模型配置：

```bash
cd /Users/quao/.codex/worktrees/wofost-management-audit/FAIRY
env -u USER PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 \
  OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  .venv/bin/python scripts/calibrate_formal90_oracles.py \
  --replay-case /Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_formal90_recalibration_20261024/final_v1/cases/scenario_full_season_hb_base_hn84_std_normal \
  --output-dir /tmp/fairy-normal-calibrated-replay
```

该入口校验交付时的代码和模型数据指纹。正式输出保留508份冻结源码/模型输入及每例的实际config、原计划、公开观察轨迹、对照、选定工作流和新场景回放，避免将后续源码变化混入同一轮结果。

`PYTHONHASHSEED=0` 必须在Python进程启动前指定：现有无人机以Python hash派生随机状态，省略它可能得到相同粮食质量但不同的观测、初态和回放哈希。一次省略环境的CLI检查已保留失败证据；正式worker及上述复现命令均固定环境。其余运行库版本和环境核验见最终证据目录。

回放包含补充水量选择的最终方案（该入口同时支持保留主方案的场景）：

```bash
cd /Users/quao/.codex/worktrees/wofost-management-audit/FAIRY
env -u USER PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 \
  OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  .venv/bin/python scripts/extend_formal90_water_search.py \
  --replay-case /Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_formal90_recalibration_20261024/final_v1/cases/scenario_full_season_hb_dryr5r6_hn84_water_limit \
  --output-dir /tmp/fairy-water-reviewed-replay
```
