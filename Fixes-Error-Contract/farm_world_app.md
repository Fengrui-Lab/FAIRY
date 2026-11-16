# farm_world_app.py 错误与校验审阅

源文件：[fairy/apps/farm_world/farm_world_app.py](../fairy/apps/farm_world/farm_world_app.py)

覆盖 8 个工具及其库存、配额、物理时间、粮食批次辅助路径。store_grain 对未干燥粮食仅警告是文档明确允许行为，不列为缺失拒绝。

已审阅入口：`get_farm_overview`（L275）、`get_ridge_state`（L313）、`get_ridge_range_state`（L335）、`get_inventory`（L361）、`commit_daily_physics`（L837）、`apply_fertigation`（L858）、`dry_grain`（L976）、`store_grain`（L1057）。

类型①：已有错误提示不清晰或不准确。类型②：缺少应在执行前完成的校验。P1：可能破坏状态；P2：影响行为或纠错；P3：提示可读性。

## 1. 【类型① / P2】范围错误未完整说明约束

- 位置：[347-350, 879-884](../fairy/apps/farm_world/farm_world_app.py#L347)。
- 现状/触发：get_ridge_range_state 给出上界但没解释 start<=end；apply_fertigation 只说 Invalid ridge range。
- 建议：明确整数、零基、闭区间、0<=start<=end<num_ridges，并回显输入。

## 2. 【类型① / P2】水肥错误将库存不足与配额超限混在一起

- 位置：[901-906, 1487-1498](../fairy/apps/farm_world/farm_world_app.py#L901)。
- 现状/触发：consume_fertilizer 以同一个 False 表示两种失败，apply_fertigation 仅返回 insufficient fertilizer or fertilizer quota exceeded 和需求量。
- 建议：在扣库存前分别判断，返回实际阻塞原因、所需 kg、仓库余额或季节剩余额度。TractorApp.load_fertilizer 同受影响。

## 3. 【类型② / P1】缺少索引类型和水肥有限数校验

- 位置：[324-328, 347-353, 879-914](../fairy/apps/farm_world/farm_world_app.py#L324)。
- 现状/触发：get_ridge_state(0.5) 通过范围比较后触发列表索引异常；nutrient_amount="NaN" 绕过正数校验，NaN 需求也绕过 >0 扣料条件；water_mm="NaN" 绕过负值与配额校验。
- 建议：先严格校验整数垄号及有限数；对 nutrient_amount>0、water_mm>=0 分别校验，禁止 bool/字符串冒充数值。

## 4. 【类型② / P2】水肥操作缺少物理引擎可用性校验

- 位置：[895-912, 957-971](../fairy/apps/farm_world/farm_world_app.py#L895)。
- 现状/触发：实测新 FarmWorldApp 的 physics_active=False 时 apply_fertigation(0,0,1,5) 扣除 30 kg 肥料并记灌水额度，返回 ok；没有 legacy 水肥效果路径。
- 建议：在扣料前返回能力不可用 error，或实现 legacy 等价效果；错误说明尚未执行和模式限制。

## 5. 【类型② / P2】空粮食批次未拒绝，仍制造完成状态

- 位置：[990-1047, 1068-1070, 1104-1125](../fairy/apps/farm_world/farm_world_app.py#L990)。
- 现状/触发：实测空库 dry_grain() 返回 ok 并设置 grain_dried=True、虚构批次湿度；store_grain() 也返回 ok，物理模式还可记录零重量入库动作。
- 建议：dry_grain 在 harvest_grain_kg<=0 时返回无可干燥批次 error，提示先收获并卸粮。store_grain 拒绝空批次，或明确无操作结果并禁止生成完成动作。

## 6. 【类型② / P2】药剂次数校验与记账日期可能跨日不一致

- 位置：[1354-1362, 1394-1405](../fairy/apps/farm_world/farm_world_app.py#L1354)。
- 现状/触发：check_chemical_application 按作业开始时的日期判定是否已经计次；调用者随后推进作业时长，record_chemical_application 却按结束日期计次。当天配额已用且临近午夜时可能越过次数上限。
- 建议：两处使用同一计划施药日期并在资源扣减前完成检查；复核午夜前开始、午夜后结束的喷药。静态路径确认，尚未做跨日动态复现。

## 验收重点

对上述触发输入确认返回非空字符串 `error`；拒绝发生在扣减资源、修改作物或推进时间之前。提示改动应与实际阈值一致，并覆盖修正后的合法调用。没有写明“实测”的项目为静态路径审阅结论。
