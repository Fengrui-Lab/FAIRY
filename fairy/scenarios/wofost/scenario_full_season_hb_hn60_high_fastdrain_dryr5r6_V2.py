"""高密背景下浅土层低蓄水且较少捕雨土斑的灌溉。

保留原场景ID、文件和核心考点；先读FARMING_PLAN，再读完整静态工具流程。
WORLD、分区土壤、事件与每次工具调用均在本文件声明；不加载外部workflow。
构建只捕获计划，不执行农事、不读取回执选择动作、不推进物理。
日期采用本地模拟日历；区间事件为[start,end)，一次到达不每日覆盖治疗。
普通步骤日期为开始日，等待日期为目标日；time记录真实完成时刻。
官方作物YAML保留；既有密度适配仅缩放TDWI，不声称商业品种或田间最优。
病虫草通过既有外接PGASS胁迫影响原生生长，不冒充原生病理或杂草耗水。
粮食按13%商品水分计量；dry_grain仍为即时工具抽象。
"""
from datetime import date

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world import FarmWorldApp, TractorApp, WeatherApp, SensorApp, RobotApp, DroneApp
from fairy.apps.farm_world.field_ops_app import FieldOpsApp
from fairy.apps.system import SystemApp
from fairy.scenarios.registry import register_scenario
from fairy.scenarios.wofost_farm import FarmDefinition, WofostFarmScenario
from fairy.physics.soil_engine import SoilHydraulicModifier
from fairy.scenarios.wofost_events import DroughtEvent, PressureEvent, WeatherWindowEvent, install_scenario_events
from fairy.types import EventRegisterer

SCENARIO_ID = 'scenario_full_season_hb_hn60_high_fastdrain_dryr5r6_V2'
ORIGINAL_CORE = '高密度田24–39垄更早缺水，分区补水'
FARMING_PLAN = (
    '2019-04-28：播前核对、整地起垄、按任务高密60株/m²播种官方901；本轮60为明确任务背景而非官方最优或商业HN60参数；库存120万粒，实际播1132032粒，初始VWC.24合法，准备只level/form_ridges，不例行施氮。',
    '2019-05-13：出苗样本0至3垄；例行4垄出苗确认并非异常定位，不硬加航测；实际出苗后没有缺苗证据不补播。',
    '2019-05-28：苗期冠层和杂草样本；当日原天气4.23mm雨且无主要异常，只作例行4垄样本，不硬加不可飞航测；无可信主要草害证据不例行施药或加肥。',
    '2019-06-28：花期公开长势及根区复核；不把高密标签或幼苗营养代理当作立即灌水/追肥的依据，先看实际阶段和水况。',
    '2019-07-20：结荚期全田一次30mm正常轮灌；核对所有zone根水和近期雨量支持正常轮灌，普通区也有水分需求。',
    '2019-08-01：传感器线索→真实全田无人机粗查→目标/参考各4垄样本→24至39一次30mm；浅土层、低蓄水及较少捕雨使目标区易缺水。先核对可飞天气/电量并真实全田航测560秒，再做目标24–27及参考0–3各4垄样本，最后一次正常30mm局部补水。R3含9目标+2普通、R4含7目标+4普通，不当作全16垄精确读数。UAV只粗查，低置信阳性保留不确定，不为每个零星flag复查；普通区额外水也有效，不夸大分配优势。',
    '2019-08-08：鼓粒期全田一次30mm正常轮灌；以当期公开根水/少雨预报核对继续供水；全季67.5mm低于68，余.5mm不用，不灌碎尾水。',
    '2019-09-20：确认成熟含水和作业条件，16机趟收割并按容量合批干燥入库；逐批满足2吨粮箱及湿粮保守上界；必要批次按当前即时干燥工具降至13%，不捏造设备耗时。',
)
MIGRATION_NOTES = (
    'Original high-density background with16ridge native drypatch task retained; official901 is not a researched commercialHEINONG60 parameterisation.',
    'No N fertilizer: Nfix fraction.8 remains uncalibrated official crop input; no claim of a simulated nodulation system.',
    'Fullfield30+local30(16of64)+fullfield30;total67.5 under68,reference local40 gives70. No daily tiny pulses or tail0.5;wrong ordinary water can also benefit ordinary soil. D60 is a fixed task,not a claimed best density.',
    'All real calls retained; production source must contain literal static plan.',
)
IRRIGATION_REFERENCE_MM = 70.0
IRRIGATION_SELECTION_NOTES = '两次全田30共60mm，目标16/64垄额外40的正常参考总70mm；额度68，所选目标一次30后67.5mm，余.5不灌尾水。目标补水显著有效，但同量灌普通16垄的边际总DM也接近，不声称全局最优分配。'
DENSITY_SELECTION_NOTES = '任务固定60株/m²，沿官方901/Lille2019原参数，适配器TDWI120按60/40初始化180，其余参数不变；45株/m²对照使用135。并非商业HEINONG60参数或官方推荐最优；受限供水下D60产量低于D45，密度只通过初始生物量进入当前模型。'

@register_scenario(SCENARIO_ID)
class ScenarioFullSeasonHBHN60HighFastdrainDryR5R6_V2(WofostFarmScenario):
    DESCRIPTION = '高密背景下浅土层低蓄水且较少捕雨土斑的灌溉'
    DETAILED_BRIEFING = (
        "你负责法国里尔2019年64垄高密大豆田，任务规定使用SOYBEAN_901、60株/平方米、一垄两行，库存120万粒种子；种子批次是SOYBEAN_901，并非黑农60，不能自行换种或降低密度来回避高密管理任务。目标是在有限供水下完成高密群体的全季管理与安全收储。\n\n"
        "田内存在浅土层、低蓄水与较弱捕雨条件，普通土层约1.2米，浅土约0.8米。具体异常范围仍需观察确认，入渗能力较低不等于排水更快。全季灌溉硬额度为全田等效68毫米，局部水深按面积折算；根据阶段、根区和降雨安排供水，不能只因高密度就立即多灌水或追肥。\n\n"
        "先看根水与冠层，再检查可飞天气和SurveyDrone电量，实际航测粗查后用Robot在疑区和参考位置取样。航测不能直接确诊，探头覆盖区也不等于某块地的精确读数；机器人每次最多4垄，以新回执决定是否处置，不把弱阳性自动当病害。例行抽样不必硬飞，雨天不得起飞。\n\n"
        "播前整地起垄，种箱30万粒，需要分批装种；播种、收割每次最多4垄，粮箱2吨。飞行、充电和作业都耗时，等待后重查天气。自然成熟、适收水分、无雨可通行后收割，按容量卸粮，必要干燥后全部安全入库，核对64垄没有遗漏。"
    )
    WORLD = FarmDefinition(
        reference_id='lille',
        seed_type='SOYBEAN_901',
        timezone_name='Europe/Paris',
        sowing_date=date(2019, 4, 28),
        end_date=date(2019, 11, 15),
        farm_id='farm',
        num_ridges=64,
        field_length_m=268.0,
        ridge_width_m=1.1,
        initial_vwc=0.24,
        initial_soil_temperature_c=12.0,
        soil_depth_m=1.2,
        wilting_point_vwc=0.1,
        field_capacity_vwc=0.3,
        saturation_vwc=0.45,
        infiltration_mm_day=50.0,
        initial_available_n_kg_ha=50.0,
        base_soil_n_kg_ha=50.0,
        base_fertilizer_kg=0.0,
        seed_stock=1200000,
        warehouse_fertilizer_kg=2600.0,
        warehouse_pesticide_l=1200.0,
        warehouse_fuel_l=1000.0,
        tractor_fuel_l=100.0,
        irrigation_quota_mm=68.0,
        active_ingredient_cap_kg=None,
        max_machine_passes=None,
        management_regime='conventional',
        max_insecticide_applications=None,
        max_fungicide_applications=None,
        max_mechanical_weed_ridges=None,
        external_biotic_coupling=True,
        grain_moisture_mode='soybean_equilibrium',
        planting_density_plants_m2=60.0,
        required_field_preparation_ops=('level', 'form_ridges'),
    )

    def init_and_populate_apps(self):
        super().init_and_populate_apps()
        farm = self.get_typed_app(FarmWorldApp)
        modifiers = {}
        modifier = SoilHydraulicModifier(
            field_capacity_vwc=0.24,
            root_depth_m=0.8,
            rainfall_capture_efficiency=0.78,
            max_infiltration_mm_day=32.0,
        )
        modifiers.update({rid: modifier for rid in range(24, 40)})
        farm.physics.soil.set_hydraulic_modifiers(modifiers)
        weather = self.get_typed_app(WeatherApp)
        # 一台模拟巡查设备：粗查范围，地面样本随后确诊。
        self.apps.append(DroneApp(
            farm, weather,
            name='SurveyDrone',
            description='模拟农用巡查无人机，提供带噪声NDVI与近似冠层温度；用于粗查异常范围，不能直接确诊病因。',
            speed_ms=5.0,
            effective_ridges_per_pass=7,
            takeoff_overhead_s=30,
            min_battery_pct=20.0,
            battery_pct_per_ridge=1.0,
        ))

    def build_events_flow(self):
        # 世界事件独立于Oracle，Agent与Oracle面对相同条件。
        install_scenario_events(self, [
            DroughtEvent(event_id='reproductive_dry_spell', farm_id='farm', start=date(2019, 8, 1), end=date(2019, 8, 19), rain_multiplier=0.0),
        ])
        aui = self.get_typed_app(AgentUserInterface)
        farm = self.get_typed_app(FarmWorldApp)
        tractor = self.get_typed_app(TractorApp)
        weather = self.get_typed_app(WeatherApp)
        sensor = self.get_typed_app(SensorApp)
        robot = self.get_typed_app(RobotApp)
        field_ops = self.get_typed_app(FieldOpsApp)
        system = self.get_typed_app(SystemApp)
        drone = self.get_typed_app(DroneApp, 'SurveyDrone')
        with EventRegisterer.capture_mode() as captured:
            aui.send_message_to_agent(self.reference_briefing())
            aui.send_message_to_agent('全场64垄、268m长、1.1m垄宽、一垄两行，同日播官方SOYBEAN_901，本任务规定60株/m²高密度，非官方最佳密度或商业黑农60参数。已知24–39为浅土层、低蓄水、较少捕雨的易缺水区，土深0.8m、FC0.24、捕雨0.78、入渗32mm/day；普通区含0–15参考土深1.2m、FC0.30、捕雨1.0、入渗50mm/day。土壤为公开模型假设非实测校准。8月1–18显式旱期，其他原天气保留；全季水额度68mm，请根据阶段、根水、冠层和可信地面样本安排正常轮灌与局部补水，不能单凭高密或NDVI决定。 异常诊断按传感器线索→可飞天气下SurveyDrone全田或疑区粗查→Robot重点地面样本→针对管理。无人机只提供带噪声NDVI与近似冠层温度，不直接确诊病因；例行出苗/雨天苗情无需为流程硬飞。较低32mm/day是入渗上限，不等同快排水率。')
            previous = None

            # 2019-04-28：同一管理窗口内的真实设备、观察与等待。
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00001_2019-04-28_播前检查土壤温湿与通行性').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00002_2019-04-28_播前检查当天作业天气').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00003_2019-04-28_播前确认全季种肥药油库存').depends_on(previous))
            previous = (tractor.get_status().oracle()
                .with_id('00004_2019-04-28_播前确认机具容量与燃油').depends_on(previous))
            previous = (tractor.attach_implement(implement='grader').oracle()
                .with_id('00005_2019-04-28_挂载平地机').depends_on(previous))
            previous = (tractor.level().oracle()
                .with_id('00006_2019-04-28_一次完成全场整地').depends_on(previous, delay_seconds=8321))
            previous = (tractor.detach_implement().oracle()
                .with_id('00007_2019-04-28_卸下平地机').depends_on(previous))
            previous = (tractor.attach_implement(implement='furrower').oracle()
                .with_id('00008_2019-04-28_挂载起垄机').depends_on(previous))
            previous = (tractor.form_ridges(ridge_width_m=1.1).oracle()
                .with_id('00009_2019-04-28_全场按1点1米垄宽起垄').depends_on(previous, delay_seconds=4376))
            previous = (tractor.detach_implement().oracle()
                .with_id('00010_2019-04-28_卸下起垄机准备播种').depends_on(previous))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=300000).oracle()
                .with_id('00011_2019-04-28_种箱不足下一趟时批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=0, end_ridge=3, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('00012_2019-04-28_全场一次播种中的0至3垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=4, end_ridge=7, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('00013_2019-04-28_全场一次播种中的4至7垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=8, end_ridge=11, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('00014_2019-04-28_全场一次播种中的8至11垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=12, end_ridge=15, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('00015_2019-04-28_全场一次播种中的12至15垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=283008).oracle()
                .with_id('00016_2019-04-28_种箱不足下一趟时批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=16, end_ridge=19, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('00017_2019-04-28_全场一次播种中的16至19垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=20, end_ridge=23, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('00018_2019-04-28_全场一次播种中的20至23垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=24, end_ridge=27, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('00019_2019-04-28_全场一次播种中的24至27垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=28, end_ridge=31, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('00020_2019-04-28_全场一次播种中的28至31垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=283008).oracle()
                .with_id('00021_2019-04-28_种箱不足下一趟时批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=32, end_ridge=35, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('00022_2019-04-28_全场一次播种中的32至35垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=36, end_ridge=39, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('00023_2019-04-28_全场一次播种中的36至39垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=40, end_ridge=43, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('00024_2019-04-28_全场一次播种中的40至43垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=44, end_ridge=47, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('00025_2019-04-28_全场一次播种中的44至47垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=266016).oracle()
                .with_id('00026_2019-04-28_种箱不足下一趟时批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=48, end_ridge=51, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('00027_2019-04-28_全场一次播种中的48至51垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=52, end_ridge=55, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('00028_2019-04-28_全场一次播种中的52至55垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=56, end_ridge=59, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('00029_2019-04-28_全场一次播种中的56至59垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=60, end_ridge=63, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('00030_2019-04-28_全场一次播种中的60至63垄').depends_on(previous, delay_seconds=222))

            # 2019-05-13：同一管理窗口内的真实设备、观察与等待。
            previous = (system.advance_time(seconds=1279751).oracle()
                .with_id('00031_2019-05-13_等待出苗后检查').depends_on(previous))
            previous = (robot.check_status().oracle()
                .with_id('00032_2019-05-13_出苗检查前确认机器人电量').depends_on(previous))
            previous = (robot.inspect_emergence(start_ridge=0, end_ridge=3).oracle()
                .with_id('00033_2019-05-13_出苗样本检查仅代表0至3垄').depends_on(previous, delay_seconds=2800))

            # 2019-05-28：同一管理窗口内的真实设备、观察与等待。
            previous = (system.advance_time(seconds=1293200).oracle()
                .with_id('00034_2019-05-28_等待苗期杂草与长势检查').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00035_2019-05-28_苗期全田冠层传感器检查').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=0, end_ridge=3).oracle()
                .with_id('00036_2019-05-28_苗期杂草地面抽查仅代表0至3垄').depends_on(previous, delay_seconds=2800))

            # 2019-06-28：同一管理窗口内的真实设备、观察与等待。
            previous = (system.advance_time(seconds=2675600).oracle()
                .with_id('00037_2019-06-28_等待开花期水分与长势复核').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00038_2019-06-28_开花期确认全田公开生育阶段与营养').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00039_2019-06-28_开花期复核根层水分').depends_on(previous))

            # 2019-07-20：同一管理窗口内的真实设备、观察与等待。
            previous = (system.advance_time(seconds=1900800).oracle()
                .with_id('00040_2019-07-20_等待关键生育期补水窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00041_2019-07-20_补水前核对公开生育阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00042_2019-07-20_补水前确认根区可利用水不足').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00043_2019-07-20_补水前核对近期降雨量').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=6.0).oracle()
                .with_id('00044_2019-07-20_全田一次补足30毫米毛水').depends_on(previous, delay_seconds=21900))

            # 2019-08-01：同一管理窗口内的真实设备、观察与等待。
            previous = (system.advance_time(seconds=1014900).oracle()
                .with_id('00045_2019-08-01_等待关键生育期补水窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00046_2019-08-01_补水前核对公开生育阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00047_2019-08-01_补水前确认根区可利用水不足').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00048_2019-08-01_补水前核对近期降雨量').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00049_2019-08-01_空间差异冠层复核仅作为缺水诊断线索').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00050_2019-08-01_高密背景局部异常航测前核对无雨和风速').depends_on(previous))
            previous = (drone.check_status().oracle()
                .with_id('00051_2019-08-01_粗查前核对无人机满电未充电及覆盖配置').depends_on(previous))
            previous = (drone.fly_survey(start_ridge=0, end_ridge=63).oracle()
                .with_id('00052_2019-08-01_根水冠层线索后真实无人机全田粗查再重点地面样本').depends_on(previous, delay_seconds=560))
            previous = (robot.check_status().oracle()
                .with_id('00053_2019-08-01_目标及参考样本检查前确认机器人足够电量').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=24, end_ridge=27).oracle()
                .with_id('00054_2019-08-01_目标仅24至27垄样本检查可信主要病虫草证据').depends_on(previous, delay_seconds=2800))
            previous = (robot.inspect_crop_health(start_ridge=0, end_ridge=3).oracle()
                .with_id('00055_2019-08-01_普通参考仅0至3垄样本辅助判断').depends_on(previous, delay_seconds=2800))
            previous = (field_ops.irrigate(start=24, end=39, hours=6.0).oracle()
                .with_id('00056_2019-08-01_仅24至39垄一次正常30毫米补水').depends_on(previous, delay_seconds=21900))

            # 2019-08-08：同一管理窗口内的真实设备、观察与等待。
            previous = (system.advance_time(seconds=576740).oracle()
                .with_id('00057_2019-08-08_等待关键生育期补水窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00058_2019-08-08_补水前核对公开生育阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00059_2019-08-08_补水前确认根区可利用水不足').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00060_2019-08-08_补水前核对近期降雨量').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=6.0).oracle()
                .with_id('00061_2019-08-08_全田一次补足30毫米毛水').depends_on(previous, delay_seconds=21900))

            # 2019-09-20：同一管理窗口内的真实设备、观察与等待。
            previous = (system.advance_time(seconds=3693300).oracle()
                .with_id('00062_2019-09-20_等待成熟且籽粒水分适收的窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00063_2019-09-20_收前一次核对64垄成熟及籽粒水分').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00064_2019-09-20_收前确认土壤可通行').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00065_2019-09-20_收前确认无雨作业窗口').depends_on(previous))
            previous = (tractor.attach_implement(implement='harvester').oracle()
                .with_id('00066_2019-09-20_安装收割机具').depends_on(previous))
            previous = (tractor.harvest(start_ridge=0, end_ridge=3).oracle()
                .with_id('00067_2019-09-20_全田收割中的0至3垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=4, end_ridge=7).oracle()
                .with_id('00068_2019-09-20_全田收割中的4至7垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=8, end_ridge=11).oracle()
                .with_id('00069_2019-09-20_全田收割中的8至11垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00070_2019-09-20_按粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00071_2019-09-20_仅对超安全水分批次干燥当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00072_2019-09-20_合批粮食安全入库并核对来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=12, end_ridge=15).oracle()
                .with_id('00073_2019-09-20_全田收割中的12至15垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=16, end_ridge=19).oracle()
                .with_id('00074_2019-09-20_全田收割中的16至19垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=20, end_ridge=23).oracle()
                .with_id('00075_2019-09-20_全田收割中的20至23垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00076_2019-09-20_按粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00077_2019-09-20_仅对超安全水分批次干燥当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00078_2019-09-20_合批粮食安全入库并核对来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=24, end_ridge=27).oracle()
                .with_id('00079_2019-09-20_全田收割中的24至27垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=28, end_ridge=31).oracle()
                .with_id('00080_2019-09-20_全田收割中的28至31垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=32, end_ridge=35).oracle()
                .with_id('00081_2019-09-20_全田收割中的32至35垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00082_2019-09-20_按粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00083_2019-09-20_仅对超安全水分批次干燥当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00084_2019-09-20_合批粮食安全入库并核对来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=36, end_ridge=39).oracle()
                .with_id('00085_2019-09-20_全田收割中的36至39垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=40, end_ridge=43).oracle()
                .with_id('00086_2019-09-20_全田收割中的40至43垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=44, end_ridge=47).oracle()
                .with_id('00087_2019-09-20_全田收割中的44至47垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00088_2019-09-20_按粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00089_2019-09-20_仅对超安全水分批次干燥当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00090_2019-09-20_合批粮食安全入库并核对来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=48, end_ridge=51).oracle()
                .with_id('00091_2019-09-20_全田收割中的48至51垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=52, end_ridge=55).oracle()
                .with_id('00092_2019-09-20_全田收割中的52至55垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=56, end_ridge=59).oracle()
                .with_id('00093_2019-09-20_全田收割中的56至59垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00094_2019-09-20_按粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00095_2019-09-20_仅对超安全水分批次干燥当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00096_2019-09-20_合批粮食安全入库并核对来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=60, end_ridge=63).oracle()
                .with_id('00097_2019-09-20_全田收割中的60至63垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00098_2019-09-20_按粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00099_2019-09-20_仅对超安全水分批次干燥当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00100_2019-09-20_合批粮食安全入库并核对来源垄').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00101_2019-09-20_季末核对入库总量与剩余库存').depends_on(previous))

        for event in captured:
            event.record_runtime_timing = True
        self.events = list(captured)
        return self.events
