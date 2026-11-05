"""降雨打断除草后的恢复管理。

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

SCENARIO_ID = 'scenario_full_season_hb_herbicide_window_missed_rain_delay_V2'
ORIGINAL_PROFILE_NAME = 'harbin_l3_herbicide_window_missed_rain_delay_seed_1717'
FARMING_PLAN = (
    '2019-04-28：检查播床、天气和库存后完成整地、起垄与全田播种；SOYBEAN_901，45株/m²，播深4cm；不例行施氮底肥。',
    '2019-05-13：抽查4垄出苗，样本不代表全田逐垄检查；没有补种操作。',
    '2019-05-27：连续降雨打断原除草作业窗口，只检查雨情与冠层，暂缓施药，不消耗药剂。',
    '2019-06-01：雨后恢复已延误的除草，处理12至45垄，工作液8L/垄，共272L。',
    '2019-06-28：公开阶段R1，营养指数0.85至0.85，复核根水后不例行追氮。',
    '2019-07-20：公开阶段R3，根层VWC均值0.206，水分或预报雨量条件不支持本轮补水，暂缓灌溉。',
    '2019-08-08：公开阶段R5、根层VWC均值0.169，近期预报雨5.72mm，单次全田补水30mm。',
    '2019-08-21：公开阶段R6、根层VWC均值0.187，近期预报雨0.02mm，单次全田补水30mm。',
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
class ScenarioFullSeasonHBHerbicideWindowMissedRainDelay_V2(WofostFarmScenario):
    DESCRIPTION = '降雨打断除草后的恢复管理'
    DETAILED_BRIEFING = (
        "你负责法国里尔2019年64垄SOYBEAN_901大豆田，按45株/平方米播种。任务核心是在除草计划被降雨打断时合理暂缓，并在条件改善后恢复管理；既不能冒雨强行作业，也不能把暂缓等同于整个季节放弃控草。\n\n"
        "播前完成整地起垄，之后结合冠层和机器人样本确认是否确有杂草。机器人每次最多检查4垄，样本只代表实际覆盖；草害、病害和缺水要区分，不能凭一个冠层值决定药剂。没有可信草情依据时不做预防性处理。\n\n"
        "计划用药前检查当前雨量、风速、土壤可通行性和短期预报；条件不合法就保留待处理事项，经过明确等待后重新读取天气和草情，再核对药剂类别、剂量、库存及覆盖范围。按实际回执确认已完成部分，避免漏作或重复消耗。全季也要照顾根区供水和作物阶段，不因除草延误就乱加水肥。\n\n"
        "种箱30万粒、粮箱2吨，播种和收割每次最多4垄。先查机器人电量及拖拉机油料，充电、作业和等待都会耗时，跨日不沿用旧天气判断。成熟且籽粒含水率不高于18%、无雨和可通行后再收割；按容量卸粮、必要干燥后安全入库，核对全田粮食均已交付。"
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
            PressureEvent(event_id='rain_delayed_weeds', farm_id='farm', ridge_start=12, ridge_end=45, start=date(2019, 5, 24), end=date(2019, 5, 27), kind='weed', value=0.18, mode='add', repeat='daily'),
            WeatherWindowEvent(event_id='missed_herbicide_window', farm_id='farm', start=date(2019, 5, 24), end=date(2019, 5, 30), rain_mm=10.666666666666666, wind_ms=None),
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

            # 2019-05-27：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=1206800).oracle()
                .with_id('00034_2019-05-27_等待原计划除草窗口受雨阻断').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00035_2019-05-27_雨期草害风险冠层信号').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00036_2019-05-27_连续降雨打断原除草窗口').depends_on(previous))

            # 2019-06-01：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=432000).oracle()
                .with_id('00037_2019-06-01_等待雨后首个无雨除草恢复窗口').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00038_2019-06-01_施药前区分病虫草原因_冠层异常信号').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=12, end_ridge=15).oracle()
                .with_id('00039_2019-06-01_施药前区分病虫草原因_地面代表样本仅四垄').depends_on(previous, delay_seconds=2800))
            previous = (weather.get_current_weather().oracle()
                .with_id('00040_2019-06-01_施药前_雨风作业窗口').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00041_2019-06-01_施药前_土壤可通行性').depends_on(previous))
            previous = (tractor.attach_implement(implement='sprayer').oracle()
                .with_id('00042_2019-06-01_安装本次作业机具_sprayer').depends_on(previous))
            previous = (tractor.refill_pesticide_tank(liters=272.0).oracle()
                .with_id('00043_2019-06-01_本轮工作液一次装齐').depends_on(previous))
            previous = (tractor.apply_herbicide(start_ridge=12, end_ridge=21, liters_per_ridge=8.0).oracle()
                .with_id('00044_2019-06-01_本轮weed管理覆盖12至21垄').depends_on(previous, delay_seconds=190))
            previous = (tractor.apply_herbicide(start_ridge=22, end_ridge=31, liters_per_ridge=8.0).oracle()
                .with_id('00045_2019-06-01_本轮weed管理覆盖22至31垄').depends_on(previous, delay_seconds=190))
            previous = (tractor.apply_herbicide(start_ridge=32, end_ridge=41, liters_per_ridge=8.0).oracle()
                .with_id('00046_2019-06-01_本轮weed管理覆盖32至41垄').depends_on(previous, delay_seconds=190))
            previous = (tractor.apply_herbicide(start_ridge=42, end_ridge=45, liters_per_ridge=8.0).oracle()
                .with_id('00047_2019-06-01_本轮weed管理覆盖42至45垄').depends_on(previous, delay_seconds=190))

            # 2019-06-28：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=2329240).oracle()
                .with_id('00048_2019-06-28_等待花期水肥复核').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00049_2019-06-28_花期公开生育阶段与营养复核').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00050_2019-06-28_花期根层水分是否足够').depends_on(previous))

            # 2019-07-20：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=1900800).oracle()
                .with_id('00051_2019-07-20_等待关键生育期根区水分复核').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00052_2019-07-20_结荚阶段水分复核_公开生育阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00053_2019-07-20_结荚阶段水分复核_根层水分').depends_on(previous))

            # 2019-08-08：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=1641600).oracle()
                .with_id('00054_2019-08-08_等待关键生育期根区水分复核').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00055_2019-08-08_灌浆阶段水分复核_公开生育阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00056_2019-08-08_灌浆阶段水分复核_根层水分').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00057_2019-08-08_灌浆阶段水分复核_近期降雨量复核').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=6.0).oracle()
                .with_id('00058_2019-08-08_灌浆阶段水分复核_一次全田补足三十毫米毛水').depends_on(previous, delay_seconds=21900))

            # 2019-08-21：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=1101300).oracle()
                .with_id('00059_2019-08-21_等待关键生育期根区水分复核').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00060_2019-08-21_灌浆后段水分复核_公开生育阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00061_2019-08-21_灌浆后段水分复核_根层水分').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00062_2019-08-21_灌浆后段水分复核_近期降雨量复核').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=6.0).oracle()
                .with_id('00063_2019-08-21_灌浆后段水分复核_一次全田补足三十毫米毛水').depends_on(previous, delay_seconds=21900))

            # 2019-09-20：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=2570100).oracle()
                .with_id('00064_2019-09-20_等待成熟且水分适收窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00065_2019-09-20_收前一次确认全田成熟与籽粒水分').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00066_2019-09-20_收割前_雨风作业窗口').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00067_2019-09-20_收割前_土壤可通行性').depends_on(previous))
            previous = (tractor.detach_implement().oracle()
                .with_id('00068_2019-09-20_卸下前道机具').depends_on(previous))
            previous = (tractor.attach_implement(implement='harvester').oracle()
                .with_id('00069_2019-09-20_安装本次作业机具_harvester').depends_on(previous))
            previous = (tractor.harvest(start_ridge=0, end_ridge=3).oracle()
                .with_id('00070_2019-09-20_全田收割中的0至3垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=4, end_ridge=7).oracle()
                .with_id('00071_2019-09-20_全田收割中的4至7垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=8, end_ridge=11).oracle()
                .with_id('00072_2019-09-20_全田收割中的8至11垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00073_2019-09-20_按实际粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00074_2019-09-20_仅干燥超储藏水分批次当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00075_2019-09-20_安全入库并保留每批来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=12, end_ridge=15).oracle()
                .with_id('00076_2019-09-20_全田收割中的12至15垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=16, end_ridge=19).oracle()
                .with_id('00077_2019-09-20_全田收割中的16至19垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=20, end_ridge=23).oracle()
                .with_id('00078_2019-09-20_全田收割中的20至23垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00079_2019-09-20_按实际粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00080_2019-09-20_仅干燥超储藏水分批次当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00081_2019-09-20_安全入库并保留每批来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=24, end_ridge=27).oracle()
                .with_id('00082_2019-09-20_全田收割中的24至27垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=28, end_ridge=31).oracle()
                .with_id('00083_2019-09-20_全田收割中的28至31垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=32, end_ridge=35).oracle()
                .with_id('00084_2019-09-20_全田收割中的32至35垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00085_2019-09-20_按实际粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00086_2019-09-20_仅干燥超储藏水分批次当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00087_2019-09-20_安全入库并保留每批来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=36, end_ridge=39).oracle()
                .with_id('00088_2019-09-20_全田收割中的36至39垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=40, end_ridge=43).oracle()
                .with_id('00089_2019-09-20_全田收割中的40至43垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=44, end_ridge=47).oracle()
                .with_id('00090_2019-09-20_全田收割中的44至47垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00091_2019-09-20_按实际粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00092_2019-09-20_仅干燥超储藏水分批次当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00093_2019-09-20_安全入库并保留每批来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=48, end_ridge=51).oracle()
                .with_id('00094_2019-09-20_全田收割中的48至51垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=52, end_ridge=55).oracle()
                .with_id('00095_2019-09-20_全田收割中的52至55垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=56, end_ridge=59).oracle()
                .with_id('00096_2019-09-20_全田收割中的56至59垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00097_2019-09-20_按实际粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00098_2019-09-20_仅干燥超储藏水分批次当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00099_2019-09-20_安全入库并保留每批来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=60, end_ridge=63).oracle()
                .with_id('00100_2019-09-20_全田收割中的60至63垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00101_2019-09-20_按实际粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00102_2019-09-20_仅干燥超储藏水分批次当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00103_2019-09-20_安全入库并保留每批来源垄').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00104_2019-09-20_季末核对安全入库与实际资源消耗').depends_on(previous))

        for event in captured:
            event.record_runtime_timing = True
        self.events = list(captured)
        return self.events
