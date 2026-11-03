# 公开接口与最终任务文本合同 v1

## 已实查的基线与尚未实施的目标

`current_binding_snapshot.json`来自本次对现有water_limit/nitrogen_limit场景设置 `detailed_briefing=False` 后的setup。没有执行Oracle工具或运行季节。保存实际get_tools名称、参数/返回schema、描述、旧基础说明、附加system、backend/土层和灌溉stop阈值。

基线为旧签名单田固定Apps，`farm_environment=None`；不能换成shared绑定却默认为root-zone工具仍在。未来十个候选使用相同绑定是设计约定，尚未运行时验证。W05 forecast-off尤其必须真的从工具目录移除get_forecast，不能用文字禁令假装信息消融。

## 控制器允许读取

|公开工具/数据|用途|不可越界|
|---|---|---|
|SensorApp.read_root_zone_sensors|探头覆盖区root_vwc，±0.005不确定性，coverage与日期|不能以分区均值推断每垄真实水分都低于门槛|
|公开soil_nitrogen（如存在）|带原生日/覆盖状态的模型估计|非测土N；not_started/partial/mixed_day不当0；N02播前可辨识性仍未过门禁|
|read_soil_sensors、read_canopy_sensors、get_ridge_range_state|公开墒情、温度、作物/水分观测|nutrient_index不当化学土壤N检测；不隐藏访问内部变量|
|get_farm_overview、get_crop_capabilities|公开阶段、成熟、水分、准备/播种/收获规则|不用DVS、RFTRA或硬编码“某天必成熟”替代门槛|
|WeatherApp.get_current_weather、get_forecast（许可时）|当前作业与允许时窗内的预测|不读WeatherGenerator未来真值；不引用内部后期干燥事件作行动日历|
|get_inventory、TractorApp.get_status、get_irrigation_log、动作回执|库存、容量、资源与投入核对|装料不是施入；effect_ready_at不是作物恢复；未知投入不是0|
|SystemApp.advance_time、commit_daily_physics|公开时间推进/生效复查|不得直接改时钟、PCSE日、作物/天气状态|

精确签名以逐候选tool_catalog.json为准。控制器禁用读取backend.native_*、物理引擎私有状态、oracle事件/未来天气；离线诊断可以读但必须分离存放。

## 完整文本渲染门禁

每项 `agent/task.zh.txt` 是阶段1完整目标文本，独立可读；`additional_system_prompt.txt`单列。四个首轮处理的N60/N120和水政策是实验员参考控制器配置，不混进自主Agent的任务答案。面积、产品46%N、配额、必要准备和安全规则等事实仍公开。W01水试点中的固定N120也只在配对策略里声明，不在Agent任务中推荐。

阶段2必须同时替换：初始化的scenario_input、AUI briefing事件载荷、详细参考生成、建植/季内参考脚本。只关detailed_briefing不合格。首轮建植必须显式传入剂量，不可调用旧无参数200kg helper；不得保留旧topdress_schedule造成额外输入。

运行前导出实际Agent起始消息和每次接收的AUI任务消息、实际附加system与通用system模板/版本、工具schema。校验完整任务与目标文本相等、没有参考日期/推荐剂量/未来窗口；目标20000kg容量不得被“200”子串误判为基肥泄漏。内部变量名出现在工具的边界说明不等于泄漏其值，检查的是实际载荷和策略读取。

合并/暂缓候选文本明确标设计稿，不可当正式任务发布；S02延迟、N02测土数据、W05消融均不伪称已实现。生产实现与目标不一致时停止该试点，记录差异，不静默放行。
