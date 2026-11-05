"""病害恢复后再遇干旱的辨因管理。

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

SCENARIO_ID = 'scenario_full_season_hb_disease_then_drought_recovery_tradeoff_V2'
ORIGINAL_PROFILE_NAME = 'harbin_l3_disease_then_drought_recovery_seed_1628'
FARMING_PLAN = (
    '2019-04-28：整地、起垄和一次全田播种；正常大豆不例行施氮肥。',
    '2019-05-13：出苗抽查，无需补播。',
    '2019-05-28：苗期查草，无需除草。',
    '2019-06-22：20至43垄一次杀菌管理，3.8L/垄、3个机趟。',
    '2019-06-28：花期长势和根水复核，无例行施肥。',
    '2019-08-01：20至43垄一次30mm灌溉。',
    '2019-09-20：全田成熟收割16机趟、合为6批卸粮/必要干燥/安全入库。',
)
MIGRATION_NOTES = (
    'Original task and official weather/crop data retained; no routine nitrogen fertilizer.',
    'Normal-sized complete irrigation rounds, with unused budget permitted and no tail pulses.',
    'Disease pressure source is once in case08; treatment reduces rather than erases residual pressure.',
    'Human farming plan is separate from real machine passes and read/wait calls.',
    'All recorded real tools retained; no posthoc read pruning.',
)
IRRIGATION_REFERENCE_MM = 13.125
IRRIGATION_SELECTION_NOTES = '供水参考为目标24垄一次35毫米整轮水，折算全田13.125毫米；本题额度仅够一次30毫米局部水（全田11.25毫米），考病后缺水辨因。不是99%平台或全局最优证明。'
DENSITY_SELECTION_NOTES = '沿用前轮公开条件下的模型候选密度，不称官方推荐或田间最优。'

@register_scenario(SCENARIO_ID)
class ScenarioFullSeasonHBDiseaseThenDroughtRecoveryTradeoff_V2(WofostFarmScenario):
    DESCRIPTION = '病害恢复后再遇干旱的辨因管理'
    DETAILED_BRIEFING = (
        "你负责法国里尔2019年64垄SOYBEAN_901大豆田，按45株/平方米播种。任务是在病害管理后仍持续判断长势异常的原因；看到熟悉症状也要重新检查，不能自动重复上一轮用药。目标是保护整季收成并完成全田收储。\n\n"
        "全季灌溉硬额度只有全田等效11.25毫米，局部灌水按面积折算扣减。每次用水前查看累计用量与剩余量，将根区亏缺、生育阶段、近期降雨和当前植株状况一起考虑，不能在尚无需要时先耗尽额度。\n\n"
        "冠层异常只是线索，要结合根水和地面样本区分病害残留、缺水及其他原因。机器人每次最多检查4垄，可选疑区和参考位置，不能把样本说成全田确诊；施药后的残病提示也不代表应继续施同一种药。按本次证据选择用水、用药或继续观察，处置后再复核，营养指标低也不直接触发追肥。\n\n"
        "播前完成整地起垄，种箱30万粒、粮箱2吨，播种和收割每次最多4垄。先查油料、电量和挂载，充电、作业及等待都会耗时；跨日重查天气。确认自然成熟、籽粒含水率不高于18%、无雨且可通行后收获，按容量卸粮并必要干燥，安全入库后核对64垄没有遗漏。"
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
        irrigation_quota_mm=11.25,
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

    def init_and_populate_apps(self):
        super().init_and_populate_apps()
        farm = self.get_typed_app(FarmWorldApp)
        modifier = SoilHydraulicModifier(
            field_capacity_vwc=0.31,
            root_drainage_rate=0.26,
            rainfall_capture_efficiency=0.82,
            irrigation_efficiency=0.86,
            max_infiltration_mm_day=85.0,
        )
        farm.physics.soil.set_hydraulic_modifiers({rid: modifier for rid in range(20, 44)})

    def build_events_flow(self):
        # 事件属于世界本身，Agent与Oracle面对相同条件。
        install_scenario_events(self, [
            WeatherWindowEvent(event_id='wet_june', farm_id='farm', start=date(2019, 6, 14), end=date(2019, 6, 18), rain_mm=18.0, wind_ms=None),
            PressureEvent(event_id='wet_june_disease', farm_id='farm', ridge_start=20, ridge_end=43, start=date(2019, 6, 19), end=date(2019, 6, 21), kind='disease', value=0.52, mode='set', repeat='once'),
            DroughtEvent(event_id='late_drought', farm_id='farm', start=date(2019, 8, 1), end=date(2019, 8, 17), rain_multiplier=0.0),
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
                .with_id('00001_2019-04-28_播前土壤温湿与通行性').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00002_2019-04-28_播前作业天气').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00003_2019-04-28_播前全季仓库与资源额度').depends_on(previous))
            previous = (tractor.get_status().oracle()
                .with_id('00004_2019-04-28_播前机具容量及燃油').depends_on(previous))
            previous = (tractor.attach_implement(implement='grader').oracle()
                .with_id('00005_2019-04-28_挂载平地机').depends_on(previous))
            previous = (tractor.level().oracle()
                .with_id('00006_2019-04-28_一次整平全场').depends_on(previous, delay_seconds=8321))
            previous = (tractor.detach_implement().oracle()
                .with_id('00007_2019-04-28_卸平地机').depends_on(previous))
            previous = (tractor.attach_implement(implement='furrower').oracle()
                .with_id('00008_2019-04-28_挂载起垄机').depends_on(previous))
            previous = (tractor.form_ridges(ridge_width_m=1.1).oracle()
                .with_id('00009_2019-04-28_一次起垄全场').depends_on(previous, delay_seconds=4376))
            previous = (tractor.detach_implement().oracle()
                .with_id('00010_2019-04-28_卸起垄机').depends_on(previous))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=300000).oracle()
                .with_id('00011_2019-04-28_种箱不足下一趟时批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=0, end_ridge=3, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00012_2019-04-28_一次全田播种的0至3垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=4, end_ridge=7, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00013_2019-04-28_一次全田播种的4至7垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=8, end_ridge=11, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00014_2019-04-28_一次全田播种的8至11垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=12, end_ridge=15, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00015_2019-04-28_一次全田播种的12至15垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=16, end_ridge=19, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00016_2019-04-28_一次全田播种的16至19垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=265320).oracle()
                .with_id('00017_2019-04-28_种箱不足下一趟时批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=20, end_ridge=23, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00018_2019-04-28_一次全田播种的20至23垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=24, end_ridge=27, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00019_2019-04-28_一次全田播种的24至27垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=28, end_ridge=31, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00020_2019-04-28_一次全田播种的28至31垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=32, end_ridge=35, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00021_2019-04-28_一次全田播种的32至35垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=36, end_ridge=39, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00022_2019-04-28_一次全田播种的36至39垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=265320).oracle()
                .with_id('00023_2019-04-28_种箱不足下一趟时批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=40, end_ridge=43, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00024_2019-04-28_一次全田播种的40至43垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=44, end_ridge=47, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00025_2019-04-28_一次全田播种的44至47垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=48, end_ridge=51, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00026_2019-04-28_一次全田播种的48至51垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=52, end_ridge=55, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00027_2019-04-28_一次全田播种的52至55垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=56, end_ridge=59, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00028_2019-04-28_一次全田播种的56至59垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=18384).oracle()
                .with_id('00029_2019-04-28_种箱不足下一趟时批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=60, end_ridge=63, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00030_2019-04-28_一次全田播种的60至63垄').depends_on(previous, delay_seconds=222))

            # 2019-05-13：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=1279751).oracle()
                .with_id('00031_2019-05-13_等待出苗检查').depends_on(previous))
            previous = (robot.check_status().oracle()
                .with_id('00032_2019-05-13_出苗检查前确认机器人电量').depends_on(previous))
            previous = (robot.inspect_emergence(start_ridge=0, end_ridge=3).oracle()
                .with_id('00033_2019-05-13_出苗样本仅代表0至3垄').depends_on(previous, delay_seconds=2800))

            # 2019-05-28：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=1293200).oracle()
                .with_id('00034_2019-05-28_等待苗期杂草检查').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00035_2019-05-28_苗期全田冠层传感器').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=0, end_ridge=3).oracle()
                .with_id('00036_2019-05-28_苗期草情仅抽样0至3垄').depends_on(previous, delay_seconds=2800))

            # 2019-06-22：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=2157200).oracle()
                .with_id('00037_2019-06-22_等待病害管理窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00038_2019-06-22_病害管理前公开生育阶段').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=20, end_ridge=21).oracle()
                .with_id('00039_2019-06-22_病害代表样本仅抽样20至21垄').depends_on(previous, delay_seconds=1400))
            previous = (robot.inspect_crop_health(start_ridge=42, end_ridge=43).oracle()
                .with_id('00040_2019-06-22_病害代表样本仅抽样42至43垄').depends_on(previous, delay_seconds=1400))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00041_2019-06-22_施药前土壤可通行性').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00042_2019-06-22_施药前雨风窗口').depends_on(previous))
            previous = (tractor.attach_implement(implement='sprayer').oracle()
                .with_id('00043_2019-06-22_挂载喷药机具').depends_on(previous))
            previous = (tractor.load_fungicide(liters=91.19999999999999).oracle()
                .with_id('00044_2019-06-22_一次装齐病区杀菌工作液').depends_on(previous))
            previous = (tractor.apply_fungicide(start_ridge=20, end_ridge=29, liters_per_ridge=3.8).oracle()
                .with_id('00045_2019-06-22_一次病害管理的分区机趟').depends_on(previous, delay_seconds=190))
            previous = (tractor.apply_fungicide(start_ridge=30, end_ridge=39, liters_per_ridge=3.8).oracle()
                .with_id('00046_2019-06-22_一次病害管理的分区机趟').depends_on(previous, delay_seconds=190))
            previous = (tractor.apply_fungicide(start_ridge=40, end_ridge=43, liters_per_ridge=3.8).oracle()
                .with_id('00047_2019-06-22_一次病害管理的分区机趟').depends_on(previous, delay_seconds=190))

            # 2019-06-28：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=515030).oracle()
                .with_id('00048_2019-06-28_等待花期长势检查').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00049_2019-06-28_开花期长势与营养').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00050_2019-06-28_开花期根区水分复核').depends_on(previous))

            # 2019-08-01：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=2937600).oracle()
                .with_id('00051_2019-08-01_等待病后遇旱的原因复核窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00052_2019-08-01_关键水分窗口确认公开阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00053_2019-08-01_灌水前复核根层亏缺').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00054_2019-08-01_灌水前复核近期降雨').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00055_2019-08-01_病后冠层异常复核').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=20, end_ridge=21).oracle()
                .with_id('00056_2019-08-01_区分病害与缺水的代表样本仅抽样20至21垄').depends_on(previous, delay_seconds=1400))
            previous = (robot.inspect_crop_health(start_ridge=42, end_ridge=43).oracle()
                .with_id('00057_2019-08-01_区分病害与缺水的代表样本仅抽样42至43垄').depends_on(previous, delay_seconds=1400))
            previous = (field_ops.irrigate(start=20, end=43, hours=6.0).oracle()
                .with_id('00058_2019-08-01_按正常轮灌量一次灌水不补尾数').depends_on(previous, delay_seconds=21900))

            # 2019-09-20：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=4295300).oracle()
                .with_id('00059_2019-09-20_等待成熟且水分适收窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00060_2019-09-20_收前一次核对64垄成熟与籽粒水分').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00061_2019-09-20_收前土壤可通行性').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00062_2019-09-20_收前无雨窗口').depends_on(previous))
            previous = (tractor.detach_implement().oracle()
                .with_id('00063_2019-09-20_卸下喷药机具').depends_on(previous))
            previous = (tractor.attach_implement(implement='harvester').oracle()
                .with_id('00064_2019-09-20_安装收割机具').depends_on(previous))
            previous = (tractor.harvest(start_ridge=0, end_ridge=3).oracle()
                .with_id('00065_2019-09-20_一次全田收割中的0至3垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=4, end_ridge=7).oracle()
                .with_id('00066_2019-09-20_一次全田收割中的4至7垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=8, end_ridge=11).oracle()
                .with_id('00067_2019-09-20_一次全田收割中的8至11垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00068_2019-09-20_依据2吨粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00069_2019-09-20_必要批次干燥当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00070_2019-09-20_安全入库并保留批次来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=12, end_ridge=15).oracle()
                .with_id('00071_2019-09-20_一次全田收割中的12至15垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=16, end_ridge=19).oracle()
                .with_id('00072_2019-09-20_一次全田收割中的16至19垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=20, end_ridge=23).oracle()
                .with_id('00073_2019-09-20_一次全田收割中的20至23垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00074_2019-09-20_依据2吨粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00075_2019-09-20_必要批次干燥当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00076_2019-09-20_安全入库并保留批次来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=24, end_ridge=27).oracle()
                .with_id('00077_2019-09-20_一次全田收割中的24至27垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=28, end_ridge=31).oracle()
                .with_id('00078_2019-09-20_一次全田收割中的28至31垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=32, end_ridge=35).oracle()
                .with_id('00079_2019-09-20_一次全田收割中的32至35垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00080_2019-09-20_依据2吨粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00081_2019-09-20_必要批次干燥当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00082_2019-09-20_安全入库并保留批次来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=36, end_ridge=39).oracle()
                .with_id('00083_2019-09-20_一次全田收割中的36至39垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=40, end_ridge=43).oracle()
                .with_id('00084_2019-09-20_一次全田收割中的40至43垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=44, end_ridge=47).oracle()
                .with_id('00085_2019-09-20_一次全田收割中的44至47垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00086_2019-09-20_依据2吨粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00087_2019-09-20_必要批次干燥当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00088_2019-09-20_安全入库并保留批次来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=48, end_ridge=51).oracle()
                .with_id('00089_2019-09-20_一次全田收割中的48至51垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=52, end_ridge=55).oracle()
                .with_id('00090_2019-09-20_一次全田收割中的52至55垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=56, end_ridge=59).oracle()
                .with_id('00091_2019-09-20_一次全田收割中的56至59垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00092_2019-09-20_依据2吨粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00093_2019-09-20_必要批次干燥当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00094_2019-09-20_安全入库并保留批次来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=60, end_ridge=63).oracle()
                .with_id('00095_2019-09-20_一次全田收割中的60至63垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00096_2019-09-20_依据2吨粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00097_2019-09-20_必要批次干燥当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00098_2019-09-20_安全入库并保留批次来源垄').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00099_2019-09-20_季末核对粮食与资源额度').depends_on(previous))

        for event in captured:
            event.record_runtime_timing = True
        self.events = list(captured)
        return self.events
