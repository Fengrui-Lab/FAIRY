"""R5/R6干旱与有限灌溉。

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

SCENARIO_ID = 'scenario_full_season_hb_dryr5r6_hn84_water_limit_V2'
ORIGINAL_PROFILE_NAME = 'harbin_l3_hn84_dryr5r6_waterlimit_seed_1526'
FARMING_PLAN = (
    '2019-04-30：整地、起垄和一次全田播种；正常大豆不例行施氮肥。',
    '2019-05-10：0至63垄一次20mm灌溉。',
    '2019-05-15：出苗抽查，无需补播。',
    '2019-05-30：苗期查草，无需除草。',
    '2019-06-19：0至63垄一次40mm灌溉。',
    '2019-06-27：0至63垄一次40mm灌溉。',
    '2019-07-05：0至63垄一次40mm灌溉。',
    '2019-07-13：0至63垄一次40mm灌溉。',
    '2019-07-21：0至63垄一次40mm灌溉。',
    '2019-07-29：22至43垄一次40mm灌溉。',
    '2019-08-12：全田成熟收割16机趟、合为4批卸粮/必要干燥/安全入库。',
)
MIGRATION_NOTES = (
    'Original task and official weather/crop data retained; no routine nitrogen fertilizer.',
    'Normal-sized complete irrigation rounds, with unused budget permitted and no tail pulses.',
    'Disease pressure source is once in case08; treatment reduces rather than erases residual pressure.',
    'Human farming plan is separate from real machine passes and read/wait calls.',
    'All recorded real tools retained; no posthoc read pruning.',
)
IRRIGATION_REFERENCE_MM = 260.0
IRRIGATION_SELECTION_NOTES = '供水参考为一次20毫米保苗水加6轮40毫米整轮水，共260毫米；本题额度240毫米，末轮优先给22至43垄，不把余水拆成尾水。不是全局最优证明。'
DENSITY_SELECTION_NOTES = '沿用前轮公开条件下的模型候选密度，不称官方推荐或田间最优。'

@register_scenario(SCENARIO_ID)
class ScenarioFullSeasonHBDryR5R6HN84WaterLimit_V2(WofostFarmScenario):
    DESCRIPTION = 'R5/R6干旱与有限灌溉'
    DETAILED_BRIEFING = (
        "你负责西班牙巴利亚多利德2019年64垄SOYBEAN_903大豆的全季管理，播种目标40株/平方米。任务重点是在缺水风险下分配有限灌溉，同时完成正常播种、巡田和成熟收储，不能只照顾一处而遗漏其余田块。\n\n"
        "全季灌溉硬额度为全田等效240毫米。局部灌水应按覆盖面积折算计入全田用量，每轮后查看实际扣减和剩余额度；没有必要为了用尽额度再补零碎尾水。田内土壤条件存在差异，要从各覆盖区根水、生育阶段和近期降雨判断保苗及花荚、鼓粒阶段的供水需求。\n\n"
        "先读土壤和冠层传感器，再选择有代表性的地面样本；机器人每次最多4垄，不能把一次样本当全田结论。缺水、病虫和营养问题分别核对，避免看到弱长势就加肥或用药；没有依据不做预防性处理。\n\n"
        "播前完成整地与起垄，按库存装种；种箱30万粒，播种和收割每次最多4垄，粮箱2吨。留出油料、充电、机趟及卸粮时间，等待后复核天气与成熟度。确认自然成熟、籽粒含水率不高于18%、无雨且可通行后收获，必要干燥至安全水分再入库，最后核对64垄均已收储。"
    )
    WORLD = FarmDefinition(
        reference_id='valladolid',
        seed_type='SOYBEAN_903',
        timezone_name='Europe/Madrid',
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
        irrigation_quota_mm=240.0,
        active_ingredient_cap_kg=None,
        max_machine_passes=None,
        management_regime='conventional',
        max_insecticide_applications=None,
        max_fungicide_applications=None,
        max_mechanical_weed_ridges=None,
        external_biotic_coupling=True,
        grain_moisture_mode='soybean_equilibrium',
        planting_density_plants_m2=40.0,
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
        farm.physics.soil.set_hydraulic_modifiers({rid: modifier for rid in range(22, 44)})

    def build_events_flow(self):
        # 事件属于世界本身，Agent与Oracle面对相同条件。
        install_scenario_events(self, [
            DroughtEvent(event_id='r5_r6_drought', farm_id='farm', start=date(2019, 6, 25), end=date(2019, 7, 21), rain_multiplier=0.0),
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
                .with_id('00001_2019-04-30_播前土壤温湿与通行性').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00002_2019-04-30_播前作业天气').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00003_2019-04-30_播前全季仓库与资源额度').depends_on(previous))
            previous = (tractor.get_status().oracle()
                .with_id('00004_2019-04-30_播前机具容量及燃油').depends_on(previous))
            previous = (tractor.attach_implement(implement='grader').oracle()
                .with_id('00005_2019-04-30_挂载平地机').depends_on(previous))
            previous = (tractor.level().oracle()
                .with_id('00006_2019-04-30_一次整平全场').depends_on(previous, delay_seconds=8321))
            previous = (tractor.detach_implement().oracle()
                .with_id('00007_2019-04-30_卸平地机').depends_on(previous))
            previous = (tractor.attach_implement(implement='furrower').oracle()
                .with_id('00008_2019-04-30_挂载起垄机').depends_on(previous))
            previous = (tractor.form_ridges(ridge_width_m=1.1).oracle()
                .with_id('00009_2019-04-30_一次起垄全场').depends_on(previous, delay_seconds=4376))
            previous = (tractor.detach_implement().oracle()
                .with_id('00010_2019-04-30_卸起垄机').depends_on(previous))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_903', count=300000).oracle()
                .with_id('00011_2019-04-30_种箱不足下一趟时批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=0, end_ridge=3, depth_cm=4.0, seed_spacing_cm=4.545454545454546).oracle()
                .with_id('00012_2019-04-30_一次全田播种的0至3垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=4, end_ridge=7, depth_cm=4.0, seed_spacing_cm=4.545454545454546).oracle()
                .with_id('00013_2019-04-30_一次全田播种的4至7垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=8, end_ridge=11, depth_cm=4.0, seed_spacing_cm=4.545454545454546).oracle()
                .with_id('00014_2019-04-30_一次全田播种的8至11垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=12, end_ridge=15, depth_cm=4.0, seed_spacing_cm=4.545454545454546).oracle()
                .with_id('00015_2019-04-30_一次全田播种的12至15垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=16, end_ridge=19, depth_cm=4.0, seed_spacing_cm=4.545454545454546).oracle()
                .with_id('00016_2019-04-30_一次全田播种的16至19垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=20, end_ridge=23, depth_cm=4.0, seed_spacing_cm=4.545454545454546).oracle()
                .with_id('00017_2019-04-30_一次全田播种的20至23垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_903', count=283008).oracle()
                .with_id('00018_2019-04-30_种箱不足下一趟时批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=24, end_ridge=27, depth_cm=4.0, seed_spacing_cm=4.545454545454546).oracle()
                .with_id('00019_2019-04-30_一次全田播种的24至27垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=28, end_ridge=31, depth_cm=4.0, seed_spacing_cm=4.545454545454546).oracle()
                .with_id('00020_2019-04-30_一次全田播种的28至31垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=32, end_ridge=35, depth_cm=4.0, seed_spacing_cm=4.545454545454546).oracle()
                .with_id('00021_2019-04-30_一次全田播种的32至35垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=36, end_ridge=39, depth_cm=4.0, seed_spacing_cm=4.545454545454546).oracle()
                .with_id('00022_2019-04-30_一次全田播种的36至39垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=40, end_ridge=43, depth_cm=4.0, seed_spacing_cm=4.545454545454546).oracle()
                .with_id('00023_2019-04-30_一次全田播种的40至43垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=44, end_ridge=47, depth_cm=4.0, seed_spacing_cm=4.545454545454546).oracle()
                .with_id('00024_2019-04-30_一次全田播种的44至47垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_903', count=171680).oracle()
                .with_id('00025_2019-04-30_种箱不足下一趟时批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=48, end_ridge=51, depth_cm=4.0, seed_spacing_cm=4.545454545454546).oracle()
                .with_id('00026_2019-04-30_一次全田播种的48至51垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=52, end_ridge=55, depth_cm=4.0, seed_spacing_cm=4.545454545454546).oracle()
                .with_id('00027_2019-04-30_一次全田播种的52至55垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=56, end_ridge=59, depth_cm=4.0, seed_spacing_cm=4.545454545454546).oracle()
                .with_id('00028_2019-04-30_一次全田播种的56至59垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=60, end_ridge=63, depth_cm=4.0, seed_spacing_cm=4.545454545454546).oracle()
                .with_id('00029_2019-04-30_一次全田播种的60至63垄').depends_on(previous, delay_seconds=222))

            # 2019-05-10：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=847751).oracle()
                .with_id('00030_2019-05-10_等待计划灌水窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00031_2019-05-10_关键水分窗口确认公开阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00032_2019-05-10_灌水前复核根层亏缺').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00033_2019-05-10_灌水前复核近期降雨').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=4.0).oracle()
                .with_id('00034_2019-05-10_按正常轮灌量一次灌水不补尾数').depends_on(previous, delay_seconds=14700))

            # 2019-05-15：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=417300).oracle()
                .with_id('00035_2019-05-15_等待出苗检查').depends_on(previous))
            previous = (robot.check_status().oracle()
                .with_id('00036_2019-05-15_出苗检查前确认机器人电量').depends_on(previous))
            previous = (robot.inspect_emergence(start_ridge=0, end_ridge=3).oracle()
                .with_id('00037_2019-05-15_出苗样本仅代表0至3垄').depends_on(previous, delay_seconds=2800))

            # 2019-05-30：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=1293200).oracle()
                .with_id('00038_2019-05-30_等待苗期杂草检查').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00039_2019-05-30_苗期全田冠层传感器').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=0, end_ridge=3).oracle()
                .with_id('00040_2019-05-30_苗期草情仅抽样0至3垄').depends_on(previous, delay_seconds=2800))

            # 2019-06-19：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=1725200).oracle()
                .with_id('00041_2019-06-19_等待计划灌水窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00042_2019-06-19_关键水分窗口确认公开阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00043_2019-06-19_灌水前复核根层亏缺').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00044_2019-06-19_灌水前复核近期降雨').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=8.0).oracle()
                .with_id('00045_2019-06-19_按正常轮灌量一次灌水不补尾数').depends_on(previous, delay_seconds=29100))

            # 2019-06-27：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=662100).oracle()
                .with_id('00046_2019-06-27_等待计划灌水窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00047_2019-06-27_关键水分窗口确认公开阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00048_2019-06-27_灌水前复核根层亏缺').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00049_2019-06-27_灌水前复核近期降雨').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=8.0).oracle()
                .with_id('00050_2019-06-27_按正常轮灌量一次灌水不补尾数').depends_on(previous, delay_seconds=29100))

            # 2019-07-05：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=662100).oracle()
                .with_id('00051_2019-07-05_等待计划灌水窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00052_2019-07-05_关键水分窗口确认公开阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00053_2019-07-05_灌水前复核根层亏缺').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00054_2019-07-05_灌水前复核近期降雨').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=8.0).oracle()
                .with_id('00055_2019-07-05_按正常轮灌量一次灌水不补尾数').depends_on(previous, delay_seconds=29100))

            # 2019-07-13：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=662100).oracle()
                .with_id('00056_2019-07-13_等待计划灌水窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00057_2019-07-13_关键水分窗口确认公开阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00058_2019-07-13_灌水前复核根层亏缺').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00059_2019-07-13_灌水前复核近期降雨').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=8.0).oracle()
                .with_id('00060_2019-07-13_按正常轮灌量一次灌水不补尾数').depends_on(previous, delay_seconds=29100))

            # 2019-07-21：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=662100).oracle()
                .with_id('00061_2019-07-21_等待计划灌水窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00062_2019-07-21_关键水分窗口确认公开阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00063_2019-07-21_灌水前复核根层亏缺').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00064_2019-07-21_灌水前复核近期降雨').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=8.0).oracle()
                .with_id('00065_2019-07-21_按正常轮灌量一次灌水不补尾数').depends_on(previous, delay_seconds=29100))

            # 2019-07-29：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=662100).oracle()
                .with_id('00066_2019-07-29_等待计划灌水窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00067_2019-07-29_关键水分窗口确认公开阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00068_2019-07-29_灌水前复核根层亏缺').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00069_2019-07-29_灌水前复核近期降雨').depends_on(previous))
            previous = (field_ops.irrigate(start=22, end=43, hours=8.0).oracle()
                .with_id('00070_2019-07-29_按正常轮灌量一次灌水不补尾数').depends_on(previous, delay_seconds=29100))

            # 2019-08-12：本轮管理或检查；以下是实际设备所需的工具调用。
            previous = (system.advance_time(seconds=1180500).oracle()
                .with_id('00071_2019-08-12_等待成熟且水分适收窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00072_2019-08-12_收前一次核对64垄成熟与籽粒水分').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00073_2019-08-12_收前土壤可通行性').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00074_2019-08-12_收前无雨窗口').depends_on(previous))
            previous = (tractor.attach_implement(implement='harvester').oracle()
                .with_id('00075_2019-08-12_安装收割机具').depends_on(previous))
            previous = (tractor.harvest(start_ridge=0, end_ridge=3).oracle()
                .with_id('00076_2019-08-12_一次全田收割中的0至3垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=4, end_ridge=7).oracle()
                .with_id('00077_2019-08-12_一次全田收割中的4至7垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=8, end_ridge=11).oracle()
                .with_id('00078_2019-08-12_一次全田收割中的8至11垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=12, end_ridge=15).oracle()
                .with_id('00079_2019-08-12_一次全田收割中的12至15垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00080_2019-08-12_依据2吨粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00081_2019-08-12_必要批次干燥当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00082_2019-08-12_安全入库并保留批次来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=16, end_ridge=19).oracle()
                .with_id('00083_2019-08-12_一次全田收割中的16至19垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=20, end_ridge=23).oracle()
                .with_id('00084_2019-08-12_一次全田收割中的20至23垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=24, end_ridge=27).oracle()
                .with_id('00085_2019-08-12_一次全田收割中的24至27垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=28, end_ridge=31).oracle()
                .with_id('00086_2019-08-12_一次全田收割中的28至31垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00087_2019-08-12_依据2吨粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00088_2019-08-12_必要批次干燥当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00089_2019-08-12_安全入库并保留批次来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=32, end_ridge=35).oracle()
                .with_id('00090_2019-08-12_一次全田收割中的32至35垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=36, end_ridge=39).oracle()
                .with_id('00091_2019-08-12_一次全田收割中的36至39垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=40, end_ridge=43).oracle()
                .with_id('00092_2019-08-12_一次全田收割中的40至43垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=44, end_ridge=47).oracle()
                .with_id('00093_2019-08-12_一次全田收割中的44至47垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00094_2019-08-12_依据2吨粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00095_2019-08-12_必要批次干燥当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00096_2019-08-12_安全入库并保留批次来源垄').depends_on(previous))
            previous = (tractor.harvest(start_ridge=48, end_ridge=51).oracle()
                .with_id('00097_2019-08-12_一次全田收割中的48至51垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=52, end_ridge=55).oracle()
                .with_id('00098_2019-08-12_一次全田收割中的52至55垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=56, end_ridge=59).oracle()
                .with_id('00099_2019-08-12_一次全田收割中的56至59垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=60, end_ridge=63).oracle()
                .with_id('00100_2019-08-12_一次全田收割中的60至63垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00101_2019-08-12_依据2吨粮箱容量合批卸粮').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00102_2019-08-12_必要批次干燥当前工具即时零耗时').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00103_2019-08-12_安全入库并保留批次来源垄').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00104_2019-08-12_季末核对粮食与资源额度').depends_on(previous))

        for event in captured:
            event.record_runtime_timing = True
        self.events = list(captured)
        return self.events
