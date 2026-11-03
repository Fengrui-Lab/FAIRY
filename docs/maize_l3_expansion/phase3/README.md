# W01/N01 v1.1 场景封装

> 进展更新：封装修订已获审查通过；随后 v1.1 动态入口的 W01、N01 正产全季参考各完成一次，均验证通过。见 [本次入口验收报告](../../../../integration/maize-l3-v11-reference-20261103/REPORT.md)。下文“未执行”描述的是此前封装修订交付时点。静态 oracle 图未单独运行，完整 checkpoint 仍未生成。

阶段2工程排错结案。两个独立 L3 场景已注册，正式 CLI 可解析任务及工具；没有加入任何旧 campaign 或运行模型实验。本次未重新执行全季，已有开发响应证据继续作为证据，不冒充新版入口的全季验收。

| ID | 任务 | 公开水肥额度 |
|---|---|---|
| scenario_maize_l3_basic_w01_v1 | 基础补灌 | 150mm 全田等效毛水、360kg 产品 |
| scenario_maize_l3_basic_n01_v1 | 基础供氮 | 0mm 人工灌水、360kg 产品 |

两者为未播种单田64垄、1.2864ha、40cm受限根层、合成哈尔滨天气、未本地校准 Grain_maize_201。两者不同环境，不作跨场景因果配对。未扩展天气、根深、品种或其他候选。

## 三种职责

- `fairy/scenarios/maize/basic_management.py`：原生初始化、任务与候选终态评价。无需精确 N60/N120、三日观察或20mm剂量；这些不是验收规则。公开合同保留正剂量基肥、预算及原生合法操作条件。
- `scripts/run_maize_basic_reference.py`：继承已审阅公共工具执行器的观察驱动参考控制器；当前参考处理用N120、W01阈值补灌、N01不补灌。没有复制生理模型或绕过工具修改状态。
- `basic_management_v1/*.reference.json`：从已保存正产开发轨迹提取的公共动作/参数，构建普通原生 oracle 事件图。是可复现参考而非最优解；原生 Path Corr 等参考路径指标保持原生含义，不成为任务完成的精确顺序否决条件。不是宣称新版动态控制器又跑完了正产全季。

## 终态与评分出口

`scenario.validate()` 返回原生 ScenarioValidationResult，metadata 分别保存 execution_complete、production_success、status、postharvest_applicability、逐垄成熟TWSO、实际仓库量、逐垄TOTIRR/面积及有效水、工具错误和旧验证结果。

- 正产：全成熟、全收割、安全干燥/入库、资源与粮食账闭合。
- 零产：64个不同垄有有限且为零的原生成熟产量，全成熟全收割，粮箱/缓冲区/仓库和回收账为零，没有 pending；`zero_yield_completed`、execution_complete=true、production_success=false；卸粮干燥入库不适用。
- `success` 对应生产成功，所以零产仍为 false；不会将流程完整包装为高分。
- 可恢复工具拒绝留为诊断；未审查警告仍阻止成功。原校验器及旧场景未改写。
- 生物产量、实际仓库粮食、有效水分开，不以其中一个替代另一个。缺失原生量不填零。

## 入口与保护

在 FAIRY 目录，先执行：

```sh
.venv/bin/python scripts/run_maize_basic_reference.py preflight --candidate W01 --gate /tmp/w01.preflight.json
```

需要运行参考处理时显式调用（本次未执行）：

```sh
.venv/bin/python scripts/run_maize_basic_reference.py run --candidate W01 --gate /tmp/w01.preflight.json --output /tmp/w01-reference-new
```

N01替换candidate即可。输出目录必须不存在，不自动重跑。入口核对 candidate、预检状态、执行器/候选源码、全部配置与参考文件、时序哈希，以及原生源码/依赖环境指纹；不匹配时在工具动作前失败。预检只是 setup、事件图、显式时序检查，不声称全季通过。

显式常规网格07:00已由历史轨迹执行；08:00成熟后切换逻辑保留，历史五条轨迹没有覆盖该分支。原08:00协议偏差永久保留，未追认合规。旧零产脚本作为冻结证据未改，新正式入口补上门禁。

## 本次验收

- 62 tests passed（含原40项），81条既有依赖warning。覆盖零/正产判定、NaN/布尔/重复垄/未收割/未结算/资源失败、无精确参考剂量限制、注册初态、过期门禁拒绝。
- 正式 FAIRY CLI `describe-scenario --job` 两项通过：event_briefing，60个对Agent公开工具，validate hook可用。参考控制器额外一项仅为 AgentUserInterface__send_message_to_agent，用于任务投递；所有田间动作属于同一 Agent 公开菜单。
- 没有全季仿真、PCSE from_state 重建或模型请求；没有改写任何旧实验/证据。

## 证据边界及关联

开发来源 `integration/maize-l3-phase2-20261103` 和 `integration/maize-l3-phase2-zero-closure-20261103`；源证据ZIP SHA与脚本/场景文件见 packaging_manifest.json。

旧补验“1403个文件未变”是本地审计；此前外部实际核对的是包内147个旧证据，其余1256个文件仅有哈希，不能宣称全部已外部独立核验。初态source_fingerprint变化，其余田间初态与生长历史一致。

目前具备两个正式可调用的候选实现及入口测试；封装版本尚无新增全季执行证据，未宣称新oracle全季运行已验收。后续如生成发布版本参考产物，须用明确版本与匹配环境，经原生入口执行并独立归档。

## v1.1 混合零产／正产终态修正

仅修改新候选的收储检查，旧 validation.py 和原有场景不变。已收垄仅在原生 DOM 存在、有限成熟 TWSO=0、有限实际回收量=0 时豁免干燥与含水要求。其他垄继续检查收割、安全含水与干燥状态；全部64垄成熟/收割、正粮实际入库、空缓冲区、预算守恒及无 pending 要求保留。不通过删除旧错误消息放行湿粮。

新增9项混合终态参数化检查：63垄正产安全入库＋1垄零产保留23.81%水分/干燥标记可以完成；真正有粮未干燥、成熟量与回收量不能共同证明为零、未收割、缺成熟记录、缓冲区残留、pending 或预算错误均失败。总计62项通过。

候选ID与任务参数不变，评价版本更新为 basic-management-v1.1。两份预检、CLI描述及清单已刷新；旧v1文档与预检保存在 archive-v1，旧ZIP不覆盖。本次没有全季仿真、原生历史恢复或模型请求。

结果使用时同时展示 execution_complete、production_success、成熟 TWSO、实际14%入库量及原生路径指标。production_success 只表示正产闭环，不代表方案优秀；路径相似不等于产量表现。N120仅为参考，不是最优剂量或预算上限（公开预算约128.73 kg N/ha）。
