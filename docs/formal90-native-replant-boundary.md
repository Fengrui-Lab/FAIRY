# 正式90场景中的原生补种能力边界

本轮只读核查本地PCSE 6.0.13、官方源文档、FAIRY工具和冻结的原始完整Oracle；没有实现补种、修改原生状态或修改物理代码。七例原计划中的补种路径仍是明确的能力阻断，不能为了得到90个通过结果而重启整垄或直接提高stand。

下面关于保留土壤后重启作物的可行性判断来自源代码审查，本轮没有运行跨生命周期原型仿真，不能当作该能力已经通过验证的记录。

## 七例实际操作及含义

以下范围与参数逐个取自原始`canonical_workflow.json`，不是从场景名称猜测。全部操作播深4cm、播距7.9cm；未传`full_replant`时，工具默认值为`False`。

| 场景ID | 实际补种垄段 | 操作次数 | full_replant | 应表达的作物群体含义 |
|---|---|---:|---|---|
| `scenario_full_season_heinong84_edge_low_fertility` | 0–3 | 1 | 显式`True` | 原作物整垄终止、重新播种一个较晚的新生命周期；原幸存苗必须被明确移除 |
| `scenario_full_season_hb_wetcold_high_residue_establishment` | 0–15，按4垄分趟 | 4 | 未传，默认`False` | 在湿冷/残茬影响后的缺苗处补播，保留已有幸存苗 |
| `scenario_full_season_hb_compacted_headland_stand_recovery` | 0–7，按4垄分趟 | 2 | 未传，默认`False` | 在地头受压群体内补苗，不能把0–7垄的老苗全部改成新播苗 |
| `scenario_full_season_hb_organic_residue_weed_establishment` | 0–7，按4垄分趟 | 2 | 未传，默认`False` | 在有机/残茬缺苗区补苗，保留老群体和原有草害/资源约束 |
| `scenario_full_season_hb_fertilizer_quota_edge_lowfertility` | 0–3 | 1 | 未传，默认`False` | 低肥力弱苗区少量补苗；不能用补种给原群体凭空补充干物质或氮 |
| `scenario_full_season_hb_planter_skip_rows_stand_gap` | 12–15及28–31 | 2 | 未传，默认`False` | 两个漏播条带中的新苗与已有苗并存，需分别保留播期/苗龄 |
| `scenario_full_season_hb_replant_after_crusting_short_season` | 0–7，按4垄分趟 | 2 | 未传，默认`False` | 板结影响区内补播，补入苗的成熟窗口应晚于原幸存苗 |

总计14次原始工具调用，一例整垄重播、六例默认补苗。板结场景的历史影响及收获分区标签是0–11垄，但原补种操作实际仅0–7垄，不能在迁移中不加说明地扩大为0–11。

这些场景的历史设定不等于全垄死亡。例如边缘低肥力0–3垄初始stand为0.64；漏播条带只是分别声明`stand_fraction_delta=-0.48/-0.42`，不是整条垄所有苗都死亡。这些值也不能直接当成已测出的空缺面积比例。

源Oracle写了补种，不等于已经证明补种是最优或必要。后续可以另做保留稀疏群体、整垄重播或预防建植失败的管理决策对照；但那不能被报告为“已经实现并验证原计划中的局部补苗”。这七条路径受阻，也不意味着相同天气下任何管理方案都无法收获。

## PCSE支持连续土壤与前后两茬，但一个Engine只有一个活跃作物

本地`pcse.engine.Engine`的结构是单个`crop`对象和单个`soil`对象。`CROP_START`在旧`crop`仍存在时会直接报错；`CROP_FINISH(crop_delete=True)`安排结束并删除旧作物。土壤对象在Engine初始化时创建，普通作物结束不会重新创建土壤，因而框架具备在同一土壤上前后运行两个生命周期的条件。[官方Engine源码](https://pcse.readthedocs.io/en/stable/_modules/pcse/engine.html)

这支持的是先结束旧群体、再开始新群体的轮作/整垄重播。它不支持在同一Engine的同一个VariableKiosk中并排启动两套老苗、新苗对象。两套对象都会注册`DVS`、`LAI`、`RNuptake`等相同变量名，而当前Engine也只有一个`self.crop`。

结束不是立即删除：`_on_CROP_FINISH`先设标志，真正的finalize/delete在日推的正确阶段执行。不能连续发送finish和start，就认定同一时刻已经安全换茬。AgroManager还管理当前CropCalendar的持续时间、后续campaign与终止条件；新生命周期必须与它一致。当前适配为保留成熟后裸地土壤，已经安排了一个遥远的空campaign，但这本身并不构成可动态补种的第二个作物日历。[官方AgroManager源码](https://pcse.readthedocs.io/en/stable/_modules/pcse/agromanager.html)

## 为什么土壤可以保留，又不能仅复制SM/NAVAIL重建模型

**CWB水分。** `WaterbalanceFD`接收作物开始/结束信号，在根系深度改变时重新分配根层和下层水量。土壤可持续保存`W`、`WLOW`、`SS`以及累计雨、灌溉、蒸发、蒸腾、径流、深排等。根层`SM`可能因根深重定义而改变，因此守恒对象应是整个土柱水量与通量，而不是要求换茬前后`SM`数值完全相同。[官方CWB源码](https://pcse.readthedocs.io/en/stable/_modules/pcse/soil/classic_waterbalance.html)

**CNB氮素。** `N_Soil_Dynamics`在土壤初始化时设`NSOIL`和`NAVAIL`，随后按矿化、外加肥、背景供给和作物`RNuptake`逐日记账；它没有在每次作物结束时重置这两个库。因此在同一Engine内保留同一土壤对象，可以避免把初始可利用氮再发一遍。[官方CNB源码](https://pcse.readthedocs.io/en/stable/_modules/pcse/soil/n_soil_dynamics.html)

如果删除整套PCSE模型，只用最新`SM`和`NAVAIL`重新创建一个Engine，会丢掉水分分层、`RDold`、蒸发历史、累计通量、原土壤潜在氮库、待施肥/灌水和日推阶段等；土壤初始参数也可能重新注入水氮。这样的“新季”不能作为守恒的补种实现。

作物初始干物质及器官氮在新作物初始化时产生，必须对应实际新种子的投入；旧作物被终止时的地上/地下干物质和氮去向也必须登记。当前CNB没有残茬分解过程，不能把终止作物的氮自动当作立即可利用肥料。

## FAIRY当前为何明确拒绝

当前`_operate_replant_seeds`在扣种、扣油和推进时间之前调用`backend.check_replant`，发现已有原生生命周期就拒绝。后端的PLANTING队列和每日推进也分别拒绝重复种植或突然改变播种日期。这个保护避免了工具表面成功、原生模型仍沿用老苗的情况。

旧简化路径的补苗只是代理：按整垄播距扣种，然后用`min(0.92, old_stand + (1-old_stand)*0.6)`提高stand；已出苗时保留原物候，尚未出苗或`full_replant=True`时才重置物候。它没有创建新苗的播期、生育阶段、根系或器官氮，不能直接照搬到原生模型。

原生适配当前是每垄一个`_RidgeRun`、一个原生模型、一份初始specification、一个日记和一个成熟快照。换茬还会涉及：重新安装FAIRY的同化耦合模块、每个生命周期的成熟/失败快照、产量恢复状态、粮食来源及checkpoint/journal回放。仅绕过`check_replant`或清空`_runs[ridge_id]`并不足够。

相关本地入口：`fairy/apps/farm_world/tractor_operations.py::_operate_replant_seeds`、`fairy/physics/wofost_backend.py::check_replant/queue_actions/advance_day/_advance_native/export_state`。原简化工具的群体恢复规则属于FAIRY经验逻辑，不是PCSE提供的补苗生理模型。

## 最小正确方案的范围

**整垄重播可作为一个独立能力实现。** 仅允许显式`full_replant=True`：在明确日界结束旧作物，保留同一Engine与土壤，登记旧作物终止原因及生物量/氮去向，按新种子投入创建新生命周期和新作物日历。需要保存每周期的品种参数与原生历史，重新绑定同化耦合，避免旧成熟快照或旧实收状态冻结新作物。当前并未实现或验证这一能力，不能将上述可行性判断记为一例已通过。

**局部补苗需要额外群体表示。** 老苗与补苗至少各有独立播期、DVS、LAI、器官干物质、器官氮、根系及成熟/水分状态。若实际是同一地表内交错的新老苗，还需共享土壤水氮、分配光及根系资源并只扣除一次总吸收；不能让两个独立整垄模型各享有一整份土壤库存和灌水。将两个DVS平均、把LAI乘一个恢复比例或只加TDWI，都无法保留两代苗的物候与成熟差异。

如果现场证据能把幸存区和漏播区明确划成互不重叠的面积，另一种可评估的近似是空间子块：每块拥有自身持续土壤与作物历史，按面积加权所有雨、水、氮和产量，面积分数之和为1。它必须从初始缺苗事件就保存裸地区水氮历史，不能在补种当日才凭空创建一块初始湿润/肥沃的新土壤。当前仅有stand_fraction，不能自动认定这等于可分割的空间面积；该近似也尚未实现。

## 后续实现至少需要保存的字段与验证

- **身份和事件：** farm/ridge、cycle/cohort ID、补种模式、原/新品种及参数指纹、作业完成时间、播种/出苗日期、实际新增种子数、幸存苗数、缺苗数量及空间证据。
- **群体：** 各群体DVS、LAI、叶龄结构、叶/茎/根/籽粒干物质及氮、根深、活死状态、成熟日期、籽粒含水率、损伤和实收批次来源。
- **持续土壤：** 水分层`W/WLOW/SS`、`RDold`和蒸发/入渗辅助状态、`NSOIL/NAVAIL`、全部累计输入输出、待提交水肥和日推阶段；不得重发初始水、初始氮或先前已用肥料。
- **终止与新增物质：** 被移除的旧群体干物质/氮去向、新种子的物质投入、未分解残茬记录；土壤CNB没有实现的过程保持明确边界。
- **回放：** 原生日记中能重放终止/新增群体事件，检查点跨越补种时刻能精确恢复；每个群体各自成熟后才能收获，混批水分与总质量守恒。
- **因果与守恒：** 幸存苗状态在局部补苗时不重置，新苗不继承老苗DVS；换茬前后水氮差异只能由已登记通量解释；无补种对照、整垄重播对照、缺苗数量和新增种子量的对应，以及分批收获后的总产量都必须可复算。

这些是模型能力与数据契约的新增工作，不能通过修改Oracle日期、剂量或品种参数来代替。本轮应保留七例补种模型阻断，其余场景的Oracle校准成果另列；不能将未完成的原任务记为成功。
