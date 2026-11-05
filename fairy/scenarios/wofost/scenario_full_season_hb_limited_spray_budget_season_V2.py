"""早轻后重虫情与有限药剂预算。

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

SCENARIO_ID = 'scenario_full_season_hb_limited_spray_budget_season_V2'
ORIGINAL_PROFILE_NAME = 'harbin_l3_limited_spray_budget_seed_1524'
FARMING_PLAN = (
    '2019-04-28：检查播床、天气和库存后完成整地、起垄与全田播种；SOYBEAN_901，45株/m²，播深4cm；不例行施氮底肥。',
    '2019-05-13：抽查4垄出苗，样本不代表全田逐垄检查；没有补种操作。',
    '2019-05-28：苗期冠层与4垄草害样本巡查，暂不安排预防性药剂处理。',
    '2019-06-27：对20垄单点检查，公开虫量档位为low；先观察轻虫，保留有限药剂额度。',
    '2019-06-28：公开阶段R1，营养指数0.85至0.85，复核根水后不例行追氮。',
    '2019-07-20：公开阶段R3、根层VWC均值0.180，近期预报雨0mm，单次全田补水30mm。',
    '2019-07-21：针对已诊断虫害，处理18至45垄，工作液8L/垄，共224L。',
    '2019-08-08：公开阶段R5、根层VWC均值0.168，近期预报雨5.72mm，单次全田补水30mm。',
    '2019-09-20：确认成熟、无雨、可通行及籽粒水分后完成全田收割；按2t粮箱分6批卸粮、必要干燥并安全入库。',
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
class ScenarioFullSeasonHBLimitedSprayBudgetSeason_V2(WofostFarmScenario):
    DESCRIPTION = '早轻后重虫情与有限药剂预算'
    DETAILED_BRIEFING = (
        "你负责法国里尔2019年64垄SOYBEAN_901大豆田，按45株/平方米播种。任务是在虫情可能变化的一季中分配有限药剂，同时完成正常水分管理和全田安全收储；发现虫害线索不等于必须立即把药用完。\n\n"
        "全季药剂有效成分总额度为0.24千克，杀虫施用最多3个施药日。工作液的升数不是有效成分的千克数，每轮前后都查看实际库存、累计用量及剩余次数；额度不足时不能靠把正常剂量切成极小量来声称完成有效治理。\n\n"
        "先看冠层、根区水分和近期天气，再由机器人抽查疑区和必要参考位置。每次最多4垄，以实际回执为准，虫量档位与置信度分别解读；弱信号可继续观察，可信且有损失风险时再选择目标和处置。病害、杂草或缺水不能用同一种药替代诊断，处理后保留复核。\n\n"
        "播前整地起垄，种箱30万粒，播种和收割每次最多4垄；粮箱2吨，油料和药剂装载要留足后续作业余地。电量不足先充电，等待和作业都会推进时间；雨风不合适先暂缓并在条件改善后重查。成熟、含水率及通行性达标再收获，按容量卸粮、必要干燥并全部安全入库。"
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
        active_ingredient_cap_kg=0.24,
        max_machine_passes=None,
        management_regime='conventional',
        max_insecticide_applications=3,
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
            PressureEvent(event_id='early_light_insect', farm_id='farm', ridge_start=12, ridge_end=31, start=date(2019, 6, 26), end=date(2019, 6, 27), kind='insect', value=0.24, mode='set', repeat='once'),
            PressureEvent(event_id='later_heavy_insect', farm_id='farm', ridge_start=18, ridge_end=45, start=date(2019, 7, 20), end=date(2019, 7, 21), kind='insect', value=0.58, mode='set', repeat='once'),
            WeatherWindowEvent(event_id='limited_budget_spray_window', farm_id='farm', start=date(2019, 7, 21), end=date(2019, 7, 25), rain_mm=0.0, wind_ms=2.0),
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

            # 2019-04-28：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00001_2019-04-28_播前土壤温湿和通行性').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00002_2019-04-28_播前作业天气').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00003_2019-04-28_播前共有种肥药油库存').depends_on(previous))
            previous = (tractor.get_status().oracle()
                .with_id('00004_2019-04-28_播前机具容量与燃油').depends_on(previous))
            previous = (tractor.attach_implement(implement='grader').oracle()
                .with_id('00005_2019-04-28_安装本次作业机具_grader').depends_on(previous))
            previous = (tractor.level().oracle()
                .with_id('00006_2019-04-28_全场一次整地').depends_on(previous, delay_seconds=8321))
            previous = (tractor.detach_implement().oracle()
                .with_id('00007_2019-04-28_整地后卸机具').depends_on(previous))
            previous = (tractor.attach_implement(implement='furrower').oracle()
                .with_id('00008_2019-04-28_安装本次作业机具_furrower').depends_on(previous))
            previous = (tractor.form_ridges(ridge_width_m=1.1).oracle()
                .with_id('00009_2019-04-28_全场按一米一垄宽起垄').depends_on(previous, delay_seconds=4376))
            previous = (tractor.detach_implement().oracle()
                .with_id('00010_2019-04-28_起垄后卸机具').depends_on(previous))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=300000).oracle()
                .with_id('00011_2019-04-28_种箱不足下一趟才批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=0, end_ridge=3, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00012_2019-04-28_一次全场播种中的0至3垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=4, end_ridge=7, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00013_2019-04-28_一次全场播种中的4至7垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=8, end_ridge=11, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00014_2019-04-28_一次全场播种中的8至11垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=12, end_ridge=15, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00015_2019-04-28_一次全场播种中的12至15垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=16, end_ridge=19, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00016_2019-04-28_一次全场播种中的16至19垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=265320).oracle()
                .with_id('00017_2019-04-28_种箱不足下一趟才批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=20, end_ridge=23, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00018_2019-04-28_一次全场播种中的20至23垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=24, end_ridge=27, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00019_2019-04-28_一次全场播种中的24至27垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=28, end_ridge=31, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00020_2019-04-28_一次全场播种中的28至31垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=32, end_ridge=35, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00021_2019-04-28_一次全场播种中的32至35垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=36, end_ridge=39, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00022_2019-04-28_一次全场播种中的36至39垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=265320).oracle()
                .with_id('00023_2019-04-28_种箱不足下一趟才批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=40, end_ridge=43, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00024_2019-04-28_一次全场播种中的40至43垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=44, end_ridge=47, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00025_2019-04-28_一次全场播种中的44至47垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=48, end_ridge=51, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00026_2019-04-28_一次全场播种中的48至51垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=52, end_ridge=55, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00027_2019-04-28_一次全场播种中的52至55垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=56, end_ridge=59, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00028_2019-04-28_一次全场播种中的56至59垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=18384).oracle()
                .with_id('00029_2019-04-28_种箱不足下一趟才批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=60, end_ridge=63, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00030_2019-04-28_一次全场播种中的60至63垄').depends_on(previous, delay_seconds=222))

            # 2019-05-13：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=1279751).oracle()
                .with_id('00031_2019-05-13_等待出苗后检查').depends_on(previous))
            previous = (robot.check_status().oracle()
                .with_id('00032_2019-05-13_首次地面检查前确认电量').depends_on(previous))
            previous = (robot.inspect_emergence(start_ridge=0, end_ridge=3).oracle()
                .with_id('00033_2019-05-13_出苗代表样本只覆盖0至3垄').depends_on(previous, delay_seconds=2800))

            # 2019-05-28：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=1293200).oracle()
                .with_id('00034_2019-05-28_等待苗期杂草样本检查').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00035_2019-05-28_苗期冠层长势检查').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=0, end_ridge=3).oracle()
                .with_id('00036_2019-05-28_苗期杂草代表样本只覆盖0至3垄').depends_on(previous, delay_seconds=2800))

            # 2019-06-27：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=2589200).oracle()
                .with_id('00037_2019-06-27_等待早期轻虫观察').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00038_2019-06-27_早期轻虫样本观察_冠层信号').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00039_2019-06-27_早期轻虫样本观察_生育阶段与营养背景').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00040_2019-06-27_早期轻虫样本观察_同区根层水分背景').depends_on(previous))
            previous = (robot.inspect_ridge(ridge_id=20).oracle()
                .with_id('00041_2019-06-27_早期轻虫样本观察_单垄虫量档位样本').depends_on(previous, delay_seconds=700))

            # 2019-06-28：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=85700).oracle()
                .with_id('00042_2019-06-28_等待花期水肥复核').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00043_2019-06-28_花期公开生育阶段与营养复核').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00044_2019-06-28_花期根层水分是否足够').depends_on(previous))

            # 2019-07-20：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=1900800).oracle()
                .with_id('00045_2019-07-20_等待关键生育期根区水分复核').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00046_2019-07-20_结荚阶段水分复核_公开生育阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00047_2019-07-20_结荚阶段水分复核_根层水分').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00048_2019-07-20_结荚阶段水分复核_近期降雨量复核').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=6.0).oracle()
                .with_id('00049_2019-07-20_结荚阶段水分复核_一次全田补足三十毫米毛水').depends_on(previous, delay_seconds=21900))

            # 2019-07-21：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=64500).oracle()
                .with_id('00050_2019-07-21_等待后期重虫针对性管理').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00051_2019-07-21_后期较重虫害样本_冠层信号').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00052_2019-07-21_后期较重虫害样本_生育阶段与营养背景').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00053_2019-07-21_后期较重虫害样本_同区根层水分背景').depends_on(previous))
            previous = (robot.inspect_ridge(ridge_id=30).oracle()
                .with_id('00054_2019-07-21_后期较重虫害样本_单垄虫量档位样本').depends_on(previous, delay_seconds=700))
            previous = (weather.get_current_weather().oracle()
                .with_id('00055_2019-07-21_施药前_雨风作业窗口').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00056_2019-07-21_施药前_土壤可通行性').depends_on(previous))
            previous = (tractor.attach_implement(implement='sprayer').oracle()
                .with_id('00057_2019-07-21_安装本次作业机具_sprayer').depends_on(previous))
            previous = (tractor.refill_pesticide_tank(liters=224.0).oracle()
                .with_id('00058_2019-07-21_本轮工作液一次装齐').depends_on(previous))
            previous = (tractor.spray_pesticide(start_ridge=18, end_ridge=27, liters_per_ridge=8.0).oracle()
                .with_id('00059_2019-07-21_本轮insect管理覆盖18至27垄').depends_on(previous, delay_seconds=190))
            previous = (tractor.spray_pesticide(start_ridge=28, end_ridge=37, liters_per_ridge=8.0).oracle()
                .with_id('00060_2019-07-21_本轮insect管理覆盖28至37垄').depends_on(previous, delay_seconds=190))
            previous = (tractor.spray_pesticide(start_ridge=38, end_ridge=45, liters_per_ridge=8.0).oracle()
                .with_id('00061_2019-07-21_本轮insect管理覆盖38至45垄').depends_on(previous, delay_seconds=190))

            # 2019-08-08：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=1553930).oracle()
                .with_id('00062_2019-08-08_等待关键生育期根区水分复核').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00063_2019-08-08_灌浆阶段水分复核_公开生育阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00064_2019-08-08_灌浆阶段水分复核_根层水分').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00065_2019-08-08_灌浆阶段水分复核_近期降雨量复核').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=6.0).oracle()
                .with_id('00066_2019-08-08_灌浆阶段水分复核_一次全田补足三十毫米毛水').depends_on(previous, delay_seconds=21900))

            # 2019-09-20：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=3693300).oracle()
                .with_id('00067_2019-09-20_等待成熟且水分适收窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00068_2019-09-20_收前一次确认全田成熟与籽粒水分').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00069_2019-09-20_收割前_雨风作业窗口').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00070_2019-09-20_收割前_土壤可通行性').depends_on(previous))
            previous = (tractor.detach_implement().oracle()
                .with_id('00071_2019-09-20_卸下前道机具').depends_on(previous))
            previous = (tractor.attach_implement(implement='harvester').oracle()
                .with_id('00072_2019-09-20_安装本次作业机具_harvester').depends_on(previous))
            previous = (tractor.harvest(start_ridge=0, end_ridge=3).oracle()
                .with_id('00073_2019-09-20_全田收割中的0至3垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=4, end_ridge=7).oracle()
                .with_id('00074_2019-09-20_全田收割中的4至7垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=8, end_ridge=11).oracle()
                .with_id('00075_2019-09-20_全田收割中的8至11垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00076_2019-09-20_按实际粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00077_2019-09-20_仅干燥超储藏水分批次当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00078_2019-09-20_安全入库并保留每批来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=12, end_ridge=15).oracle()
                .with_id('00079_2019-09-20_全田收割中的12至15垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=16, end_ridge=19).oracle()
                .with_id('00080_2019-09-20_全田收割中的16至19垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=20, end_ridge=23).oracle()
                .with_id('00081_2019-09-20_全田收割中的20至23垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00082_2019-09-20_按实际粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00083_2019-09-20_仅干燥超储藏水分批次当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00084_2019-09-20_安全入库并保留每批来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=24, end_ridge=27).oracle()
                .with_id('00085_2019-09-20_全田收割中的24至27垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=28, end_ridge=31).oracle()
                .with_id('00086_2019-09-20_全田收割中的28至31垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=32, end_ridge=35).oracle()
                .with_id('00087_2019-09-20_全田收割中的32至35垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00088_2019-09-20_按实际粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00089_2019-09-20_仅干燥超储藏水分批次当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00090_2019-09-20_安全入库并保留每批来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=36, end_ridge=39).oracle()
                .with_id('00091_2019-09-20_全田收割中的36至39垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=40, end_ridge=43).oracle()
                .with_id('00092_2019-09-20_全田收割中的40至43垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=44, end_ridge=47).oracle()
                .with_id('00093_2019-09-20_全田收割中的44至47垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00094_2019-09-20_按实际粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00095_2019-09-20_仅干燥超储藏水分批次当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00096_2019-09-20_安全入库并保留每批来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=48, end_ridge=51).oracle()
                .with_id('00097_2019-09-20_全田收割中的48至51垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=52, end_ridge=55).oracle()
                .with_id('00098_2019-09-20_全田收割中的52至55垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=56, end_ridge=59).oracle()
                .with_id('00099_2019-09-20_全田收割中的56至59垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00100_2019-09-20_按实际粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00101_2019-09-20_仅干燥超储藏水分批次当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00102_2019-09-20_安全入库并保留每批来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=60, end_ridge=63).oracle()
                .with_id('00103_2019-09-20_全田收割中的60至63垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00104_2019-09-20_按实际粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00105_2019-09-20_仅干燥超储藏水分批次当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00106_2019-09-20_安全入库并保留每批来源垄').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00107_2019-09-20_季末核对安全入库与实际资源消耗').depends_on(previous))

        for event in captured:
            event.record_runtime_timing = True
        self.events = list(captured)
        return self.events
