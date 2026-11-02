# 连续土壤跨年 L4 基础实验

`TwoYearMaizeScenario` 的第一阶段范围是同一块田、同一参考玉米品种、2026 和 2027 两季；不是多地块或跨物种轮作。场景已通过扩展家族的显式模块列表注册，模块导入本身无注册副作用。静态 Oracle 与参考来自已完成有限搜索，独立回放证据由下述验证命令生成。

## 农场和目标

64 垄 × 268 m × 0.75 m = 12,864 m²。两季共同使用 200,000 粒 MAIZE_201 种子、1,200 kg 肥料产品及 400 mm 全田等效灌水额度；单季上限为 800 kg 产品和 300 mm。肥料含氮 46%，800 kg 产品约为 286 kg N/ha；这是既有工具额度，不代表经过地区试验推荐的施氮量。无年度补货、土壤初态重置或虚构轮作增益。

目标为最大化两季实际安全入库粮总量。每季须于当年 10 月 31 日前完成实际成熟收获、卸粮、干燥至安全水分（≤14%）并入库。`SeasonCycle.close_season(year)` 按本季新增仓库存量记账；旧粮不能再算作第二季产量。完成约束与距参考差距分开报告：

```
YieldLoss = 100 * (1 - actual_two_season_stored_kg / reference_two_season_stored_kg)
```

负数保留。未校准或输入配置指纹不匹配时参考和 YieldLoss 为 `null`，不虚设 0% 或 99% 门槛。

## 连续性和能力边界

`ContinuousSeasonBackend` 继承既有 WOFOST 后端，仅此家族 opt in。作物结束后，同一个 PCSE model、CWB 和 CNB 对象在整个休耕期继续逐日结算。翌年显式发 `crop_start`，仅更换作物状态；信号前后 W/WLOW/SS/NAVAIL/NSOIL 必须完全一致。每个原生 journal 保存第二季开始记录，恢复时从最初播种重放全部真实日驱动。没有 monkeypatch，也没有改共享后端的默认复种禁令。

`ContinuousFarm` 显式处理本地后端 checkpoint，保留共享 FarmWorld 其他状态的正常解码。`SeasonCycle` 检查上一季真收获，清理下一作物的兼容生育状态和田间作业标记；库存、拖拉机、油箱、土壤、历史粮账、累计投入均不重建。没有新增现金补助；本场尚未定义经营现金账户。

天气是 seed 101 的连续合成哈尔滨气候，含所有月份；2026/2027 使用不同日历日期的可复现生成值，不把某一实测年复制成另一个实测年。仅声明两年各自 5 月 5 日开始的 5 天播种干燥窗口。天气当前读数、七日预报和物理输入经 550 日一致性检查。使用现成 `completed_calendar_day` 结算方式，每个已经过去的日历日恰结算一次。

**农学限制：** 冬季低温和降水真实进入现有 CWB/CNB，但该基础实验没有增加积雪、冻结/融化土壤过程；欧洲参考玉米品种及其在合成寒地气候中的越冬土壤过程未作地区校准。因此可用于检验跨年状态守恒和管理约束，不应宣称是寒地玉米生产推荐。未模拟残茬返还、土壤有机碳增益或豆科固氮轮作信用。

## 有限搜索与工具工作流

粗网格第一年肥料产品分配为 400/600/800 kg，第二年为 1,200 kg 剩余额；第一年灌水上限为 100/200/300 mm，第二年为 `min(300,400-第一年实际耗水)`。固定 5 月 5 日播种、200 kg 基肥，剩余肥料在播后 15/30 日各半；灌水窗口为第 20/60/70/80 日。每个窗口读现成土壤传感器，仅当所有覆盖区读数 <0.28 时灌其分配量，为 ±0.01 观测噪声留余量；湿地跳过不强灌。成熟与可收获水分由公开观测判断，仍受原工具作业条件约束。候选探索使用真实公开工具；不直接调作物产量。

粗网格完成后，在最佳分配附近以 100 kg 产品、50 mm 水检查完整二维相邻 8 点（扣除边界和已测点），保持原边界，到无改善为止。参考是固定完整合成天气序列下的离线事后参考，仅是该有限策略族中已测最佳，尚未穷举播期、密度、肥料分次、灌溉时点或品种。原始失败和成功轨迹保存在 `validation_runs/management_v2_development_20261102/l4/`，不是源码资产。

`publish.py` 将已测最佳轨迹转换为 `oracle.py` 中逐条显式的公开工具调用，带步骤说明。Oracle 不在运行时优化，不读取隐藏产量，捕获 workflow 不运行工具。`verify.py` 在新环境直接执行，再从保存的 workflow 在另一个新环境完整重放，并比较农场、原生 journal、设备、季别账、天气、传感器随机状态与时钟；只忽略随机操作ID，浮点按9位小数规范化。

## 命令

在项目根目录：

```bash
export PYTHONPATH=.
.venv/bin/python -m pytest -q fairy/scenarios/management_extensions/v2/l4/tests
.venv/bin/python -m fairy.scenarios.management_extensions.v2.l4.calibrate --smoke --workers 1 --output validation_runs/l4_reproduction/smoke
.venv/bin/python -m fairy.scenarios.management_extensions.v2.l4.calibrate --workers 3 --output validation_runs/l4_reproduction/search
.venv/bin/python -m fairy.scenarios.management_extensions.v2.l4.refine --workers 3 --directory validation_runs/l4_reproduction/search
# 仅更新参考时执行下一行；单纯复验现有Oracle可直接运行verify。
.venv/bin/python -m fairy.scenarios.management_extensions.v2.l4.publish --input validation_runs/l4_reproduction/search
.venv/bin/python -m fairy.scenarios.management_extensions.v2.l4.verify --output validation_runs/l4_reproduction/verified
```

开发测试里的恒温冬季仅用来隔离机制，绝不是正式场景的气候。正式场景采用上述连续季节气候。

开发机为隔离 PCSE 日志/配置写入使用了 `PYTHONPATH=/tmp/fairy-pcse-settings:.`；该临时目录不是场景依赖，正常安装环境使用项目根目录即可。

本场应用观测随机数在 `randomness.py` 冻结为首次校准实际使用的种子表；其值保持原 `PYTHONHASHSEED=0` 实验不变，普通 CLI 无须设置 Python hash seed。物理天气仍使用独立 seed 101。

## 指标读取

正式 Engine/CLI 报告读取 `validation.metadata.total_stored_grain_kg`、`reference_stored_grain_kg` 和 `yield_loss_pct`，并单独读取 `validation.success`。通用单季 FOS/baseline 脚本只看到当前末季作物状态，不适合作为本场两季累计安全入库指标；这里不修改共享评分器。

## 已完成搜索结果

19 个真实候选均可行。9 点粗网格最佳为29,575.36 kg；完整二维邻域后选定第一季肥料500 kg、灌水上限150 mm，两季累计安全入库 **29,615.04 kg**。第一季14,727.04 kg，第二季14,888.00 kg；实际灌水分别150/125 mm，肥料分别500/700 kg。最后相邻8点均已测试，100 kg产品/50 mm水的指定邻域无改善。静态 workflow 共 **263 步**（含任务说明）。原始候选SHA256、输入指纹、灌水日期和剂量以及局部停止证据见 `reference.json`；最终独立重放证据另见验证目录。
