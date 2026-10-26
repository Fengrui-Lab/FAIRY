# 场景作者直接改变土壤氮

`SoilNitrogenEvent` 是场景作者定义的外部干预，不是 Agent 工具，也不是 PCSE 自动算出的淋失。它只改变指定农场、指定垄的真实 CNB 土壤氮池；作物如何响应，继续由原生 WOFOST 方程计算。

## 在完整场景文件中声明

在该场景自己的 `build_events_flow()` 中，与其他世界事件一起声明，随后保留该文件自己的完整静态农事 workflow：

```python
from datetime import date
from fairy.scenarios.wofost_events import (
    SoilNitrogenEvent,
    install_scenario_events,
)

install_scenario_events(self, [
    SoilNitrogenEvent(
        event_id="flowering_soil_n_drop",
        farm_id="farm",
        ridge_start=0,
        ridge_end=63,
        day=date(2019, 6, 25),
        available_n_kg_ha=0.0,
        reserve_n_kg_ha=0.0,
    ),
])
```

日期采用该农场的本地模拟日历，垄范围两端都包含。农场进入该日期时，事件在当天原生日生长计算前执行一次，随后的读数即可看到新氮值；WOFOST 仍按日推进，不产生一个额外的生长日。

读数分别提供 `native_effective_day`（最近已完成生长积分的日期）与 `nitrogen_state_effective_day`（氮状态最近更新的日期）。例如 6月25日日初已清氮，但尚未完成 6月25日的生长，两个日期可以分别为 6月24日和 6月25日。这种差别是显式的，不能把尚未完成的生长说成已经完成。

两种氮值的单位都是 **kg N/ha**，不是肥料产品 kg，也不是 0—1 的营养指数：

| 字段 | 改变的原生状态 | 含义 |
|---|---|---|
| `available_n_kg_ha` | `NAVAIL` | 当前可被作物吸收的土壤有效氮 |
| `reserve_n_kg_ha` | `NSOIL` | 后续仍可释放的土壤氮储备 |

至少指定一种，两者都必须是有限非负数。省略某种值就保留对应池。设置有效氮为 0 不会清空储备池；储备随后仍可释放。设置储备只改变剩余储备，不重新定义初始释放基准 `NSOILI`，也不改变释放比例；原释放基准为 0 时，不支持通过此事件添加非零储备。事件只用于已经建立原生作物运行的垄，未播种或尚未初始化的目标会明确报错。

## 数据怎样进入生长计算

1. 场景文件声明日期、农场、垄范围和目标值。
2. 已有场景事件调度在对应农场日推时，将干预交给 WOFOST 适配层。
3. 适配层在当天生长计算前改 CNB 的实际状态，记录修改前后值和氮量差；日初事件生效后，同日观察、存档和恢复都能看到修改。
4. 当天施肥仍通过真实农事工具进入原生施氮事件，按肥料含氮率、回收率计算；它不会被一次性土壤事件每天重新清除。
5. WOFOST 计算氮吸收、固氮、器官氮量及后续生长。事件本身不修改作物氮、生物量、产量、品种参数或胁迫系数。
6. 根区读数公开真实模型土壤氮及对应日期。事件和干预日志随存档保存，恢复与深拷贝会重新得到相同状态。

同日多个土壤氮事件按场景文件中的声明顺序执行。相同事件不会因为重复构建、重复推进或恢复存档而再次扣氮。土壤干预有自己的记录，不伪装成施肥、不扣仓库肥料，也不套施肥回收率。

## Agent 能观察到什么

`SensorApp.read_root_zone_sensors()` 保留原来的根区水分读数，并在原有观测区域上提供原生土壤氮遥测。它不是声称原有 5cm 水温探头能够直接测出整层土壤氮。尚未建立原生运行或只覆盖部分已初始化垄的区域，不会用 0 冒充完整有效读数；应同时检查状态、覆盖和日期。

`nutrient_index` 仍是既有兼容代理，不能把它改小来制造 WOFOST 缺氮，也不能只凭其花期低值安排追肥。土壤氮低与植株已经缺氮是两个不同判断：植株已有氮和大豆固氮仍会参与后续计算。

## 不保证追肥一定增产

官方大豆配置保留 `NFIX_FR=0.8`。此前 03 在全季有效氮和储备氮均为 0 时，花期追肥最大增产约 0.072%。把非负土壤氮降到 0 可以正确设置外部扰动，但不能凭此承诺显著的花期追肥保产。03 的农艺验收必须依据同天气、同水量、同品种条件下的对照，不能把接口接通等同于考点校准完成。

本次固定 Soybean_902、Clermont-Ferrand 2019 天气、60株/m²和三轮35mm供水，初始有效氮30、储备20 kg N/ha，得到以下原生干物质对照：

| 处理 | 籽粒干物质 kg/ha |
|---|---:|
| 不清氮、不追肥 | 3788.71 |
| 6月25日清空两池，不追肥 | 3782.69 |
| 6月25日清空，6月27日追3kg肥料产品/垄 | 3786.03 |
| 提前到5月1日清空，不追肥 | 3782.68 |
| 5月1日清空，6月27日追3kg肥料产品/垄 | 3784.41 |

这些是同条件机制对照，不是田间产量校准。3kg产品/垄在此几何和46%含氮率下，约为46.81kg N/ha施用量、32.77kg N/ha回收量。5月1日清零已经与全季N0/0的结果相同；提前清零仍未形成有明显产量选择意义的花期追肥题。正式事件与原型的五组对照，各201日、9种作物/土壤状态及储备氮逐日相等，事件生效前后的恢复也相等。

初始30/20和清零事件均为公开的工程题设，不冒充该地点实测土壤或自然淋失。`NFIX_FR=0.8`按原生公式作用于每日需求，需求包含未满足部分；它不是让作物永久缺少20%的氮。清土壤池也不会清除作物已有氮。

## 其他养分的边界

当前模型是 `Wofost81_NWLP_CWB_CNB`，原生营养限制为氮。磷、钾、硫、铁等在现实中会影响作物，但在场景里添加这些字段并不会自动进入当前生长计算。SNOMIN也是土壤碳氮模块，不能自动补齐磷钾机制。PCSE官方说明其6.0版本弃用了8.0 beta并移除磷钾限制生长的支持，见[版本说明](https://pcse.readthedocs.io/en/6.0.4/whatsnew.html)。

CNB两池和释放公式见[PCSE官方源码](https://pcse.readthedocs.io/en/6.0.8/_modules/pcse/soil/n_soil_dynamics.html)。原生通用`set_variable`必须有对应的专用setter，而当前CNB没有这两个setter，见[状态修改约定](https://pcse.readthedocs.io/en/develop/code.html#pcse.engine.Engine.set_variable)。本实现因此在适配层明确修改CNB注册状态，并由事件日志负责恢复，不修改安装的PCSE源码。

## 验证范围

`tests/test_wofost_nitrogen_events.py`核验真实状态、事件顺序、外部氮记账、施肥不会被重复清零、跨场隔离、日初可见，以及日结前后存档/深拷贝。`tests/test_wofost_nitrogen_observation.py`核验观测覆盖、未启动/部分覆盖不造0、局部事件读数与施肥生效日期。它们与原生一致性、既有九个已校准场景、03原文件身份和相关App回归一起，共529项通过；这不是全仓库测试声明。

完整对照方法、逐日曲线、真实工具候选和测试日志保存在[本次验证目录](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_nitrogen_event_20261026>)。03正式场景的“花期追肥保产”考点仍未校准，旧生产文件暂未被不成立的候选替换；引入固氮受限环境或其他养分机制是另一项模型设计选择。

另已写好一个独立完整的[03候选场景文件](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_nitrogen_event_20261026/scenario_full_season_hb_low_nutrient_carryover_flowering_nutrition.candidate.py>)，包含全部世界、事件及字面workflow，没有外部轨迹加载器。七个日期窗口展开为101次真实工具调用，9月2日收储7964.16kg；纯构建、实际回放、日历与执行时刻、64垄收储和氮观测均通过[独立核验](</Users/quao/Desktop/Second-year/CWSN/FAIRY/validation_runs/wofost_nitrogen_event_20261026/candidate_static_audit.json>)。其中花期施肥明确标为诊断对照；它不是已经验收的推荐管理，不能把这个操作能执行当成它有必要。

## 为什么修改这些文件

- `fairy/scenarios/wofost_events.py`：定义带单位、日期、农场和垄范围的事件，复用已有场景日调度；不增加Agent引擎或农事工具入口。
- `fairy/physics/wofost_backend.py`：修改真正的CNB状态，区分外部氮增减和施肥，保存即时已生效但尚未日结的事件，并在恢复时准确重放；提供只读真实氮查询，避免Sensor访问私有运行字典。
- `fairy/apps/farm_world/sensor_app.py`：在既有根区覆盖内公开真实氮值、覆盖状态和两个日期；保留原水分噪声与旧引擎读数行为。
- 两个新增氮事件/观测测试文件：核验上述因果路径、边界与恢复语义。官方作物文件、固氮比例、Agent Engine、TimeManager均未因本功能修改。
