# 冬小麦接入与验证

本扩展增加四个**单地块、日尺度、秋播次年收获**的 L3 场景。它们是一季冬小麦，不能与两次种植收获的 L4 混称。所有新增实现、数据、专用测试和离线工具均在本目录；继续使用项目现有的 Engine、CLI、Agent 工具 schema 和 JSON 工作流回放。

## 场景与代码位置

| 场景 ID | 文件与目标 |
| --- | --- |
| `scenario_l3_winter_wheat_full_season` | `L3/scenario_winter_wheat_full_season.py`，全季净经营收益 |
| `scenario_l3_winter_wheat_water_limit` | `L3/scenario_winter_wheat_water_limit.py`，有限水量下的分配与经营 |
| `scenario_l3_winter_wheat_nitrogen_limit` | `L3/scenario_winter_wheat_nitrogen_limit.py`，有限尿素产品库存下的分期施氮 |
| `scenario_l3_winter_wheat_high_water_price` | `L3/scenario_winter_wheat_high_water_price.py`，较高供水报价下的投入产出权衡 |

每个文件直接继承现有 `Scenario`，包含初始化、两种任务描述、`ORACLE_REFERENCE` 和完整字面 `build_events_flow()`。没有新增场景基类，也不在场景初始化时搜索策略。

- `apps/winter_wheat_app.py`：`WinterWheat` 工具、资源事务、USD 账本与粮食物流。
- `engines/winter_wheat_wofost.py`：真实 PCSE 原生模型、当日输入合并与确定性状态重放。
- `engines/winter_wheat_inputs.py`：日期、天气、参数和单位契约。
- `evaluation/winter_wheat.py`：完成条件、物资守恒与带符号 Agent/Oracle 对比。
- `evaluation/winter_wheat_observations.py`：真实观测档案导入与明确匹配后的精度评价。
- `winter_wheat_data.py`、`winter_wheat_oracles.py`：离线下载、检查、搜索和回放验证入口。
- `tests/test_winter_wheat_*.py`：原生模型、工具、单位、回放与数据语义测试。

## 原生模型和输入

模型为 PCSE 6.0.x 的 `Wofost81_NWLP_CWB_CNB`，本机验证版本为 6.0.13。复用仓库现有延迟日速率工厂，不修改其代码，不使用测试替身作为生产后端。

使用 WUR 固定提交 [`1ca91d7.../wheat.yaml`](https://raw.githubusercontent.com/ajwdewit/WOFOST_crop_parameters/1ca91d7dbb5aaf6b41462162de03a8254812d3a5/wheat.yaml) 中未改动的 `Winter_wheat_104`。保留原生春化与光周期，`IDSL=2`；1月不重建作物，闰日不跳过。它是欧洲参考参数，**没有完成中国品种或田间标定**。

`data/winter_wheat_ncp_2019_2020/` 已包含实际下载、校验过的参数、NASA POWER 原始 JSON、统一单位的连续290天气日及来源哈希。位置是石家庄附近网格，2019年秋至2020年夏，不能冒充下述某一观测站点。NASA 辐射单位从返回元数据读取后转换；运行场景不联网，缺日或哈希不符直接报错，不复制上一年天气填缺。

土壤初态、管理效率和库存是明确的场景假设。此版本没有雪被、冻死、倒伏、病虫草害或密度响应；原生春化不等于冬季冻害模型。作业按全田服务计价，**没有接入逐垄拖拉机轨迹、共享农机调度或作业时长**。

## 工具和单位

`get_field_info` 查询面积、播期、固定用种、原生条件与作业限额；`get_accounts` 查询价格、库存、预算及实际账本；`observe` 读取生育状态、模型土壤估计和上一完整日天气，不提供未来实况。

管理工具为 `prepare_field`、`sow`、`apply_nitrogen`、`irrigate`、`wait`、`harvest`、`dry_grain`、`store_grain`。写操作使用稳定的 `operation_id`，相同请求重试不重复扣费或投入。

- 施氮接收 **kg纯N/ha**；库存与费用扣 **kg尿素商品**，含氮率独立换算。
- 灌溉接收 **mm毛水深**；购买量为 `mm × ha × 10 m³`，效率只作用于原生入水。
- 当日同类输入先合并，再发送一次原生信号，防止后一笔覆盖前一笔。
- `wait` 可合并较长等待，但逐日结算中间所有日历日；仅受季节截止时间和天气覆盖约束。
- 原生 `DOM` 成熟且 `TWSO` 为正才允许收获。`TWSO` 是 kg干物质/ha，乘面积一次；干燥只减水，不增加干物质。
- 物流含水率为明确的固定假设，不是 WOFOST 动态水分预测；成熟后延迟收获的田间损失暂未建模。

土壤 `SM` 为体积含水率，`NAVAIL` 为 kg N/ha 的模型估计，不是独立土样化验，也不能仅凭其为零就断言植株缺氮。

## 价格、Oracle 与任务描述

使用同一固定汇率 `1 USD = 7.1757 CNY`，冬小麦价格表单列在 `data/winter_wheat_prices_2025.json`，不修改此前16场的价格表。小麦粮值采用[2025—2026年三等小麦最低收购价](https://zfxxgk.ndrc.gov.cn/web/iteminfo.jsp?id=20439)作为固定计值基准，不代表自动具备收购资格或2019/2020年的实际价格。种子、机械及仓储服务部分为明确的实验合同估价；服务包含机械、燃油及操作人员，不再重复记燃油费。

四场以实际入库粮值减经营成本为目标；库存与现金为可行性约束，不强迫用满。账本不含地租、资本折旧及报价外普通人工。报告中的成本、净经营收益比例为 `(Agent-Oracle)/Oracle`，YieldLoss 符号相反，允许负值。

Oracle 来源于实际执行的有限候选搜索，比较播期、水氮总量、分配与春季时机，并交叉检验其他配置的方案和少水少氮对照。首次真实Agent找到更好的四期投入方案后，保留原始成绩，再将该候选族独立复现并纳入搜索；最终共执行1443条候选。失败候选保留；这些参考不是全局最优或中国田间最优承诺。运行时执行各场景文件中的冻结工作流。当前普通供水与高水价在此天气和报价下选中同一投入计划，差异体现为成本与收益；最优动作是否变化取决于边际增产，不由场景名称预设。

`detail=false` 给目标、情境和查询入口；`detail=true` 增加观测、判断、处理和复查指导。任务仅保留面积数字，不给出 Oracle 日期、剂量和未来收益。

## Zenodo 实际数据核查

已下载并核对 DOI [10.5281/zenodo.14785961](https://zenodo.org/records/14785961) 的两个档案与五个 XLSX。导入187条观测汇总，保留作者 calibration / validation / overall 分组，仅读取观测列，不把作者的 WOFOST 预测作为观测。

县级表没有 `Year` 列，物候为含小数的日统计值；`overall` 有1984—2020年区域汇总，但没有这里所需的田块身份、逐年县样本、空间权重或粮食含水率。故保留小数和未知年份，不将抽穗当开花，不造日历日期，也不输出这套示例田的拟合精度。`observations/published_summaries.json` 是实际导入结果。要做中国本地标定，仍需匹配的逐年气象、土壤、品种、管理和观测身份。

## 运行命令

在仓库根目录使用已安装 PCSE 的 Python；观测 XLSX 导入另需 `openpyxl`。

```bash
# 已随代码提供输入，正常运行不需要重新下载。
PYTHONPATH=. .venv/bin/python -m fairy.cli \
  --scenario scenario_l3_winter_wheat_full_season \
  --build-oracle --replay --evaluate \
  --scenario-kwargs '{"seed":0,"detailed_briefing":true}' \
  --output-dir validation_runs/winter_wheat_full_season

# 四场原生执行、JSON新实例回放与冬季检查点继续验证。
PYTHONPATH=. .venv/bin/python -m fairy.scenarios.management_extensions.winter_wheat_oracles \
  verify --output validation_runs/winter_wheat_verify

# 重做有限搜索，输出目录必须是新目录。
PYTHONPATH=. .venv/bin/python -m fairy.scenarios.management_extensions.winter_wheat_oracles \
  search --workers 3 --output validation_runs/winter_wheat_search

PYTHONPATH=. .venv/bin/python -m pytest -q fairy/scenarios/management_extensions/tests
```

原始包的37项测试含接口替身，不能替代上述真实原生验证。此次接入的实际运行与管理对照证据保存在 `validation_runs/winter_wheat_integration_20261104/`。

真实Agent首次测试的原始报告保留其当时的Oracle比较；最终参考更新后的轨迹重放单独存档，不改写原实验指标。

收尾检查修正了零投入对照固定生成三期数组的问题，现按实际方案期数生成。原6条参数不匹配错误保留，另行16条正确构造的原生对照全部完成，所选Oracle不变；参数错误不当作农业减产。
