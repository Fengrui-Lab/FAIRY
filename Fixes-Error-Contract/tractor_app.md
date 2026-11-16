# tractor_app.py 错误与校验审阅

源文件：[fairy/apps/farm_world/tractor_app.py](../fairy/apps/farm_world/tractor_app.py)

覆盖本文件全部 23 个工具及其校验、库存、物理动作辅助路径。已有的正数、范围宽度、仓储容量等明确提示不重复列为问题。

已审阅入口：`attach_implement`（L207）、`detach_implement`（L229）、`refuel`（L244）、`refill_pesticide_tank`（L268）、`load_fertilizer`（L292）、`load_seeds`（L321）、`get_status`（L362）、`level`（L382）、`base_fertilize`（L426）、`form_ridges`（L479）、`apply_fertilizer`（L546）、`plant_seeds`（L631）、`apply_pesticide`（L778）、`load_pesticide`（L856）、`spray_pesticide`（L880）、`load_fungicide`（L968）、`apply_fungicide`（L996）、`apply_herbicide`（L1078）、`mechanical_weed_control`（L1157）、`replant_seeds`（L1222）、`incorporate_residue`（L1426）、`harvest`（L1473）、`unload_grain`（L1575）。

类型①：已有错误提示不清晰或不准确。类型②：缺少应在执行前完成的校验。P1：可能破坏状态；P2：影响行为或纠错；P3：提示可读性。

## 1. 【类型① / P2】播种 VWC 提示与条件不一致

- 位置：[706-710](../fairy/apps/farm_world/tractor_app.py#L706)。
- 现状/触发：判断允许 0.20–0.35，错误文本却要求 0.20–0.30；实测 VWC=0.36 返回后者。Agent 会据此采用错误边界。
- 建议：让判断和提示引用同一阈值，并说明是目标垄平均 VWC。业务若选择 0.30，则同时调整判断，不能只改文案。

## 2. 【类型① / P2】库存错误遗漏数量，肥料配额错误还被误称缺货

- 位置：[256-260, 280-284, 304-308, 867-871, 982-986](../fairy/apps/farm_world/tractor_app.py#L256)。
- 现状/触发：装载失败只说 Insufficient … in warehouse。consume_fertilizer 同时检查配额；实测仓库有货、配额为 0 时 load_fertilizer(1) 返回 Insufficient fertilizer in warehouse。
- 建议：区分仓库不足与季节配额不足，给出实际申请转移量、可用量、单位；杀菌剂说明使用共享 pesticide_liters 池。

## 3. 【类型① / P3】部分拒绝缺少可执行信息

- 位置：[215-221, 331-332, 386-391, 694-695, 1268-1278, 1499-1514, 1611-1618](../fairy/apps/farm_world/tractor_app.py#L215)。
- 现状/触发：未知 implement/seed_type 未列允许值；不适配农具未明确需要 grader；已播种/未播种错误未列具体垄；成熟度缺当前阶段及 R8 要求；部分燃油/种子错误仅给 need。范围错误未给实际上界。
- 建议：按分支提供允许集合、目标农具及 detach/attach 路径、冲突垄 ID、当前阶段/阈值、need/have 和有效垄范围。

## 4. 【类型① / P2】喷药天气错误未给风速阈值和实测值

- 位置：[805-808, 908-911, 1021-1024, 1102-1105](../fairy/apps/farm_world/tractor_app.py#L805)。
- 现状/触发：统一写 rain or wind above spray limit，无法判断实际阻塞原因和放行边界。
- 建议：输出当前 rainfall_mm、wind_speed_ms，准确说明无雨且风速严格小于 WeatherApp 的喷药阈值（当前 6.5 m/s）；避免把等于阈值写成 above。

## 5. 【类型② / P1】缺少参数类型及有限数校验

- 位置：[244-353, 479-499, 546-568, 631-669, 880-906, 968-1019, 1078-1100, 1222-1263](../fairy/apps/farm_world/tractor_app.py#L244)。
- 现状/触发：@type_check 是空包装。实测 load_fertilizer("NaN") 返回 ok，仓库和机载肥料均变成 nan。多个 float(x)<=0 条件挡不住 NaN；int(count) 截断小数；布尔值可冒充数量，字符串 "false" 会使 full_replant 进入真分支。范围浮点数可在扣资源后到 range() 才失败。
- 建议：在所有副作用前校验严格整数（排除 bool）、真实布尔、有限实数及域；共享验证覆盖全部范围工具和装载别名。拒绝时给参数名、收到值与预期类型/单位。

## 6. 【类型② / P1】装种失败改变品种，非空料斗允许混种

- 位置：[333-350](../fairy/apps/farm_world/tractor_app.py#L333)。
- 现状/触发：self.seed_type 在 count 和库存校验前赋值。实测先装 STANDARD 10 粒，再 EARLY_COLD 0 粒，虽报错，品种已变；再装另一品种 10 粒会把全部 20 粒标为新种。
- 建议：先完成全部校验，非空料斗禁止更换品种（或实现分品种料斗），成功转移后才提交 seed_type。错误给当前品种、余量、请求品种和处理方法。

## 7. 【类型② / P2】种子超容量缺少文档承诺的拒绝

- 位置：[321-353](../fairy/apps/farm_world/tractor_app.py#L321)。
- 现状/触发：docstring 写 excess is rejected，实际 min(count, space) 静默部分装载。
- 建议：按现有契约在 count>space 时返回容量 error；若决定保留部分装载，需另行修订契约并返回实际/未装数量。

## 8. 【类型② / P2】整地顺序只在播种时检查集合

- 位置：[426-444, 479-529, 671-688](../fairy/apps/farm_world/tractor_app.py#L426)。
- 现状/触发：plant_seeds 注释声称各整地工具会守卫顺序，但 base_fertilize/form_ridges 没有对应前置判断。实测新拖拉机直接 form_ridges(1.2) 成功。
- 建议：在 base_fertilize 前校验 level，在 form_ridges 前校验 base_fertilize；拒绝说明缺失步骤。允许重复执行与是否守卫顺序分开处理。

## 9. 【类型② / P1】起垄缺少已有作物保护

- 位置：[479-529](../fairy/apps/farm_world/tractor_app.py#L479)。
- 现状/触发：form_ridges 无 planted 检查，会直接清空全田 planted、seed_type、生育期等；误调用返回 ok。
- 建议：破坏作物前检查已有种植垄并返回 error，列出冲突垄。若业务允许毁种重整，应有明确的独立操作语义。

## 10. 【类型② / P2】农具适配校验不完整

- 位置：[479-499, 778-816, 996-1032, 1078-1113, 1157-1182, 1473-1494](../fairy/apps/farm_world/tractor_app.py#L479)。
- 现状/触发：attach_implement 明确 furrower/harvester/sprayer/cultivator 的用途，但只有 level 校验附件；未挂任何农具也可起垄，其他相关操作同样没有附件守卫。
- 建议：对起垄、喷药、机械除草、收获建立必要农具映射，操作前返回需要/当前农具和更换步骤；不要给没有定义附件的工具臆造要求。

## 11. 【类型② / P2】重新播种绕过播种日期窗口

- 位置：[1253-1283, 1306-1319](../fairy/apps/farm_world/tractor_app.py#L1253)。
- 现状/触发：replant_seeds 可对 NOT_PLANTED 或 full_replant=True 的垄启动新作物，但未调用 plant_seeds 使用的 check_planting_window。
- 建议：对会重新启动生育期的垄预先执行日期/品种窗口校验；补苗与新播种分开判断，失败列出最早允许日期。

## 12. 【类型② / P2】秸秆还田没有收获前置校验

- 位置：[1426-1452](../fairy/apps/farm_world/tractor_app.py#L1426)。
- 现状/触发：工具定义为 post-harvest；实测全新未种植农田 incorporate_residue(0,0) 返回 ok 并扣油、推进时间。
- 建议：检查目标垄 harvested 或明确的残茬可用状态，拒绝列出未收获垄；不应将无法执行的还田记为成功动作。

## 13. 【类型② / P2】依赖物理引擎的防治未校验能力是否启用

- 位置：[1038-1073, 1119-1152, 1187-1217, 1968-1978, 2021-2030](../fairy/apps/farm_world/tractor_app.py#L1038)。
- 现状/触发：apply_fungicide 的效果仅在 physics_active 时执行；除草辅助函数在 inactive 时直接返回。外层仍扣药/油并返回 ok，legacy 模式无相应防治效果。
- 建议：在扣资源前拒绝不支持的模式，提示当前能力不可用；或补充等价 legacy 效果。此项不适用于已有 legacy 效果的 apply_pesticide。

## 验收重点

对上述触发输入确认返回非空字符串 `error`；拒绝发生在扣减资源、修改作物或推进时间之前。提示改动应与实际阈值一致，并覆盖修正后的合法调用。没有写明“实测”的项目为静态路径审阅结论。
