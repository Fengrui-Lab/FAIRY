"""R5附近食叶虫压力管理。

保留原场景ID和原考点；先读FARMING_PLAN，再读完整静态工具流程。
场景自行完整声明世界、事件和Oracle；构建不执行农事，不读取回执选择动作。
农事轮次与工具调用分别统计；容量导致的分趟不另算一种农事。
日期使用当地日历；事件为[start,end)，结束注入不会自动清除已有压力。
普通步骤名称为开始日，等待名称为目标日；time记录完成时刻。
官方78项基准未改；现有密度适配仅按实际密度/40缩放TDWI，非田间最优标定。
病虫草由FAIRY外接PGASS胁迫耦合；食叶虫尚不直接移除原生叶面积。
dry_grain仍是即时零耗时处理；只在水分需要时调用，不伪造烘干耗时。
"""
from datetime import date

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world import FarmWorldApp, TractorApp, WeatherApp, SensorApp, RobotApp
from fairy.apps.farm_world.field_ops_app import FieldOpsApp
from fairy.apps.system import SystemApp
from fairy.scenarios.registry import register_scenario
from fairy.scenarios.wofost_farm import FarmDefinition, WofostFarmScenario
from fairy.physics.soil_engine import SoilHydraulicModifier
from fairy.scenarios.wofost_events import DroughtEvent, PressureEvent, WeatherWindowEvent, install_scenario_events
from fairy.types import EventRegisterer

SCENARIO_ID = 'scenario_full_season_hb_r5_leaf_feeder_defoliation_V2'
ORIGINAL_PROFILE_NAME = 'harbin_l3_r5_leaf_feeder_seed_1523'
FARMING_PLAN = (
    '2019-04-30：检查播床、天气和库存后完成整地、起垄与全田播种；SOYBEAN_905，45株/m²，播深4cm；不例行施氮底肥。',
    '2019-05-15：抽查4垄出苗，样本不代表全田逐垄检查；没有补种操作。',
    '2019-05-30：苗期冠层与4垄草害样本巡查，暂不安排预防性药剂处理。',
    '2019-06-23：公开阶段R1，营养指数0.85至0.85，复核根水后不例行追氮。',
    '2019-07-05：公开阶段R3、根层VWC均值0.176，近期预报雨1.5mm，单次全田补水30mm。',
    '2019-07-18：针对已诊断虫害，处理16至39垄，工作液8L/垄，共192L。',
    '2019-07-20：公开阶段R5、根层VWC均值0.178，近期预报雨0mm，单次全田补水30mm。',
    '2019-07-30：公开阶段R6、根层VWC均值0.182，近期预报雨0.26mm，单次全田补水30mm。',
    '2019-09-04：确认成熟、无雨、可通行及籽粒水分后完成全田收割；按2t粮箱分4批卸粮、必要干燥并安全入库。',
)
MIGRATION_NOTES = (
    'Original core task retained; event timing/intensity/window changes are explicit in this file.',
    'Normal legume no automatic N fertilizer;03 retains actual low soil N and one observed flowering-stage topdress.',
    'No daily root/forecast polling or repeated low-confidence ground inspection. Representative4ridge samples do not claim full-field ground coverage.',
    'Water decisions occur at prespecified R3/R5 windows, with R6 follow-up where earlier water was skipped or in warmer reference climates; every actual call remains in trace.',
    'Drying remains an instantaneous tool abstraction; standard13%mass and public-moisture wet bounds checked separately.',
    'Official raw crop values unchanged;effectiveTDWI scales with actual sown density; no field-optimum claim.',
)
IRRIGATION_REFERENCE_MM = None
IRRIGATION_SELECTION_NOTES = '以关键生育期、根区亏水和降雨预报安排整轮灌溉；允许剩水，不追满模型平台。'
DENSITY_SELECTION_NOTES = '沿用前轮公开条件下的模型候选密度，不称官方推荐或田间最优。'

@register_scenario(SCENARIO_ID)
class ScenarioFullSeasonHBR5LeafFeederDefoliation_V2(WofostFarmScenario):
    DESCRIPTION = 'R5附近食叶虫压力管理'
    DETAILED_BRIEFING = (
        "你负责意大利博洛尼亚2019年64垄SOYBEAN_905大豆田的全季管理，播种目标45株/平方米。任务尤其关注生殖生长阶段的食叶虫危害：及时发现可信虫情并保护仍能形成收成的冠层，同时不能把所有长势异常都归为虫害。\n\n"
        "先完成播前检查、整地与起垄，之后按出苗和生育阶段巡田。发现冠层变差时，结合根区水分、天气和机器人地面样本辨别缺水、虫情或病害；单个阳性或高置信度不等于虫口严重，应看本次观察中的虫量和实际覆盖。机器人每次最多检查4垄，电量与充电状态先核对。\n\n"
        "确认需要施药后，核对药剂类别、工具允许剂量、目标范围及当前雨风条件，装载相应药剂并分合法机趟完成；处理后继续观察，不能假定一次用药使风险永久消失。水分与营养分别判断，根区确有亏缺且预报不足以补偿时再灌水，不按固定日历加水加肥。\n\n"
        "种箱30万粒、粮箱2吨，播种和收割每次最多4垄。作业、充电和等待都占用时间，跨日后重新查天气。收割须等自然成熟、籽粒含水率不高于18%、无雨且地面可通行；及时卸粮，必要干燥后安全入库，并核对64垄已全部交付。"
    )
    WORLD = FarmDefinition(
        reference_id='bologna',
        seed_type='SOYBEAN_905',
        timezone_name='Europe/Rome',
        sowing_date=date(2019, 4, 30),
        end_date=date(2019, 11, 15),
        farm_id='farm',
        num_ridges=64,
        field_length_m=268.0,
        ridge_width_m=1.1,
        initial_vwc=0.26,
        initial_soil_temperature_c=12.0,
        soil_depth_m=1.2,
        wilting_point_vwc=0.1,
        field_capacity_vwc=0.3,
        saturation_vwc=0.45,
        infiltration_mm_day=50.0,
        initial_available_n_kg_ha=50.0,
        base_soil_n_kg_ha=50.0,
        base_fertilizer_kg=0.0,
        seed_stock=1000000,
        warehouse_fertilizer_kg=2600.0,
        warehouse_pesticide_l=1200.0,
        warehouse_fuel_l=1000.0,
        tractor_fuel_l=100.0,
        irrigation_quota_mm=None,
        active_ingredient_cap_kg=None,
        max_machine_passes=None,
        management_regime='conventional',
        max_insecticide_applications=None,
        max_fungicide_applications=None,
        max_mechanical_weed_ridges=None,
        external_biotic_coupling=True,
        grain_moisture_mode='soybean_equilibrium',
        planting_density_plants_m2=45.0,
        required_field_preparation_ops=('level', 'form_ridges'),
    )

    def build_events_flow(self):
        # 事件属于世界本身，Agent与Oracle面对相同条件。
        install_scenario_events(self, [
            PressureEvent(event_id='leaf_feeder', farm_id='farm', ridge_start=16, ridge_end=39, start=date(2019, 7, 17), end=date(2019, 7, 18), kind='insect', value=0.58, mode='set', repeat='once'),
            WeatherWindowEvent(event_id='leaf_feeder_spray_window', farm_id='farm', start=date(2019, 7, 18), end=date(2019, 7, 23), rain_mm=0.0, wind_ms=2.0),
        ])
        aui = self.get_typed_app(AgentUserInterface)
        farm = self.get_typed_app(FarmWorldApp)
        tractor = self.get_typed_app(TractorApp)
        weather = self.get_typed_app(WeatherApp)
        sensor = self.get_typed_app(SensorApp)
        robot = self.get_typed_app(RobotApp)
        field_ops = self.get_typed_app(FieldOpsApp)
        system = self.get_typed_app(SystemApp)
        with EventRegisterer.capture_mode() as captured:
            aui.send_message_to_agent(self.reference_briefing())
            previous = None

            # 2019-04-30：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00001_2019-04-30_播前土壤温湿和通行性').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00002_2019-04-30_播前作业天气').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00003_2019-04-30_播前共有种肥药油库存').depends_on(previous))
            previous = (tractor.get_status().oracle()
                .with_id('00004_2019-04-30_播前机具容量与燃油').depends_on(previous))
            previous = (tractor.attach_implement(implement='grader').oracle()
                .with_id('00005_2019-04-30_安装本次作业机具_grader').depends_on(previous))
            previous = (tractor.level().oracle()
                .with_id('00006_2019-04-30_全场一次整地').depends_on(previous, delay_seconds=8321))
            previous = (tractor.detach_implement().oracle()
                .with_id('00007_2019-04-30_整地后卸机具').depends_on(previous))
            previous = (tractor.attach_implement(implement='furrower').oracle()
                .with_id('00008_2019-04-30_安装本次作业机具_furrower').depends_on(previous))
            previous = (tractor.form_ridges(ridge_width_m=1.1).oracle()
                .with_id('00009_2019-04-30_全场按一米一垄宽起垄').depends_on(previous, delay_seconds=4376))
            previous = (tractor.detach_implement().oracle()
                .with_id('00010_2019-04-30_起垄后卸机具').depends_on(previous))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_905', count=300000).oracle()
                .with_id('00011_2019-04-30_种箱不足下一趟才批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=0, end_ridge=3, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00012_2019-04-30_一次全场播种中的0至3垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=4, end_ridge=7, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00013_2019-04-30_一次全场播种中的4至7垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=8, end_ridge=11, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00014_2019-04-30_一次全场播种中的8至11垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=12, end_ridge=15, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00015_2019-04-30_一次全场播种中的12至15垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=16, end_ridge=19, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00016_2019-04-30_一次全场播种中的16至19垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_905', count=265320).oracle()
                .with_id('00017_2019-04-30_种箱不足下一趟才批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=20, end_ridge=23, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00018_2019-04-30_一次全场播种中的20至23垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=24, end_ridge=27, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00019_2019-04-30_一次全场播种中的24至27垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=28, end_ridge=31, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00020_2019-04-30_一次全场播种中的28至31垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=32, end_ridge=35, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00021_2019-04-30_一次全场播种中的32至35垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=36, end_ridge=39, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00022_2019-04-30_一次全场播种中的36至39垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_905', count=265320).oracle()
                .with_id('00023_2019-04-30_种箱不足下一趟才批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=40, end_ridge=43, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00024_2019-04-30_一次全场播种中的40至43垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=44, end_ridge=47, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00025_2019-04-30_一次全场播种中的44至47垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=48, end_ridge=51, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00026_2019-04-30_一次全场播种中的48至51垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=52, end_ridge=55, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00027_2019-04-30_一次全场播种中的52至55垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=56, end_ridge=59, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00028_2019-04-30_一次全场播种中的56至59垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_905', count=18384).oracle()
                .with_id('00029_2019-04-30_种箱不足下一趟才批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=60, end_ridge=63, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00030_2019-04-30_一次全场播种中的60至63垄').depends_on(previous, delay_seconds=222))

            # 2019-05-15：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=1279751).oracle()
                .with_id('00031_2019-05-15_等待出苗后检查').depends_on(previous))
            previous = (robot.check_status().oracle()
                .with_id('00032_2019-05-15_首次地面检查前确认电量').depends_on(previous))
            previous = (robot.inspect_emergence(start_ridge=0, end_ridge=3).oracle()
                .with_id('00033_2019-05-15_出苗代表样本只覆盖0至3垄').depends_on(previous, delay_seconds=2800))

            # 2019-05-30：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=1293200).oracle()
                .with_id('00034_2019-05-30_等待苗期杂草样本检查').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00035_2019-05-30_苗期冠层长势检查').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=0, end_ridge=3).oracle()
                .with_id('00036_2019-05-30_苗期杂草代表样本只覆盖0至3垄').depends_on(previous, delay_seconds=2800))

            # 2019-06-23：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=2070800).oracle()
                .with_id('00037_2019-06-23_等待花期水肥复核').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00038_2019-06-23_花期公开生育阶段与营养复核').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00039_2019-06-23_花期根层水分是否足够').depends_on(previous))

            # 2019-07-05：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=1036800).oracle()
                .with_id('00040_2019-07-05_等待关键生育期根区水分复核').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00041_2019-07-05_结荚阶段水分复核_公开生育阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00042_2019-07-05_结荚阶段水分复核_根层水分').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00043_2019-07-05_结荚阶段水分复核_近期降雨量复核').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=6.0).oracle()
                .with_id('00044_2019-07-05_结荚阶段水分复核_一次全田补足三十毫米毛水').depends_on(previous, delay_seconds=21900))

            # 2019-07-18：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=1101300).oracle()
                .with_id('00045_2019-07-18_等待R5虫害管理窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00046_2019-07-18_确认食叶虫管理处于公开R5期').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00047_2019-07-18_施药前区分病虫草原因_冠层异常信号').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=16, end_ridge=19).oracle()
                .with_id('00048_2019-07-18_施药前区分病虫草原因_地面代表样本仅四垄').depends_on(previous, delay_seconds=2800))
            previous = (weather.get_current_weather().oracle()
                .with_id('00049_2019-07-18_施药前_雨风作业窗口').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00050_2019-07-18_施药前_土壤可通行性').depends_on(previous))
            previous = (tractor.attach_implement(implement='sprayer').oracle()
                .with_id('00051_2019-07-18_安装本次作业机具_sprayer').depends_on(previous))
            previous = (tractor.refill_pesticide_tank(liters=192.0).oracle()
                .with_id('00052_2019-07-18_本轮工作液一次装齐').depends_on(previous))
            previous = (tractor.spray_pesticide(start_ridge=16, end_ridge=25, liters_per_ridge=8.0).oracle()
                .with_id('00053_2019-07-18_本轮insect管理覆盖16至25垄').depends_on(previous, delay_seconds=190))
            previous = (tractor.spray_pesticide(start_ridge=26, end_ridge=35, liters_per_ridge=8.0).oracle()
                .with_id('00054_2019-07-18_本轮insect管理覆盖26至35垄').depends_on(previous, delay_seconds=190))
            previous = (tractor.spray_pesticide(start_ridge=36, end_ridge=39, liters_per_ridge=8.0).oracle()
                .with_id('00055_2019-07-18_本轮insect管理覆盖36至39垄').depends_on(previous, delay_seconds=190))

            # 2019-07-20：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=169430).oracle()
                .with_id('00056_2019-07-20_等待关键生育期根区水分复核').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00057_2019-07-20_灌浆阶段水分复核_公开生育阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00058_2019-07-20_灌浆阶段水分复核_根层水分').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00059_2019-07-20_灌浆阶段水分复核_近期降雨量复核').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=6.0).oracle()
                .with_id('00060_2019-07-20_灌浆阶段水分复核_一次全田补足三十毫米毛水').depends_on(previous, delay_seconds=21900))

            # 2019-07-30：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=842100).oracle()
                .with_id('00061_2019-07-30_等待关键生育期根区水分复核').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00062_2019-07-30_灌浆后段水分复核_公开生育阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00063_2019-07-30_灌浆后段水分复核_根层水分').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00064_2019-07-30_灌浆后段水分复核_近期降雨量复核').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=6.0).oracle()
                .with_id('00065_2019-07-30_灌浆后段水分复核_一次全田补足三十毫米毛水').depends_on(previous, delay_seconds=21900))

            # 2019-09-04：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=3088500).oracle()
                .with_id('00066_2019-09-04_等待成熟且水分适收窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00067_2019-09-04_收前一次确认全田成熟与籽粒水分').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00068_2019-09-04_收割前_雨风作业窗口').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00069_2019-09-04_收割前_土壤可通行性').depends_on(previous))
            previous = (tractor.detach_implement().oracle()
                .with_id('00070_2019-09-04_卸下前道机具').depends_on(previous))
            previous = (tractor.attach_implement(implement='harvester').oracle()
                .with_id('00071_2019-09-04_安装本次作业机具_harvester').depends_on(previous))
            previous = (tractor.harvest(start_ridge=0, end_ridge=3).oracle()
                .with_id('00072_2019-09-04_全田收割中的0至3垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=4, end_ridge=7).oracle()
                .with_id('00073_2019-09-04_全田收割中的4至7垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=8, end_ridge=11).oracle()
                .with_id('00074_2019-09-04_全田收割中的8至11垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=12, end_ridge=15).oracle()
                .with_id('00075_2019-09-04_全田收割中的12至15垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00076_2019-09-04_按实际粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.store_grain().oracle()
                .with_id('00077_2019-09-04_安全入库并保留每批来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=16, end_ridge=19).oracle()
                .with_id('00078_2019-09-04_全田收割中的16至19垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=20, end_ridge=23).oracle()
                .with_id('00079_2019-09-04_全田收割中的20至23垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=24, end_ridge=27).oracle()
                .with_id('00080_2019-09-04_全田收割中的24至27垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=28, end_ridge=31).oracle()
                .with_id('00081_2019-09-04_全田收割中的28至31垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00082_2019-09-04_按实际粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.store_grain().oracle()
                .with_id('00083_2019-09-04_安全入库并保留每批来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=32, end_ridge=35).oracle()
                .with_id('00084_2019-09-04_全田收割中的32至35垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=36, end_ridge=39).oracle()
                .with_id('00085_2019-09-04_全田收割中的36至39垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=40, end_ridge=43).oracle()
                .with_id('00086_2019-09-04_全田收割中的40至43垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=44, end_ridge=47).oracle()
                .with_id('00087_2019-09-04_全田收割中的44至47垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00088_2019-09-04_按实际粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.store_grain().oracle()
                .with_id('00089_2019-09-04_安全入库并保留每批来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=48, end_ridge=51).oracle()
                .with_id('00090_2019-09-04_全田收割中的48至51垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=52, end_ridge=55).oracle()
                .with_id('00091_2019-09-04_全田收割中的52至55垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=56, end_ridge=59).oracle()
                .with_id('00092_2019-09-04_全田收割中的56至59垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=60, end_ridge=63).oracle()
                .with_id('00093_2019-09-04_全田收割中的60至63垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00094_2019-09-04_按实际粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.store_grain().oracle()
                .with_id('00095_2019-09-04_安全入库并保留每批来源垄').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00096_2019-09-04_季末核对安全入库与实际资源消耗').depends_on(previous))

        for event in captured:
            event.record_runtime_timing = True
        self.events = list(captured)
        return self.events
