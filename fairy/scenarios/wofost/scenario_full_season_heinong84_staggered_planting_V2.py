"""16｜同品种错期播种与分区收获。
保留旧文件；本文件独立完整声明初始条件、事件与全部公共工具步骤。
官方地区参数不冒充黑农商业品种。病虫草为FAIRY外接同化胁迫。
人工雨风与土壤设定明确记录；无隐藏执行函数、无跨场景workflow导入。
农事轮次与实际机趟分别统计。等待来自真实工具耗时；干燥仍为即时抽象。
"""
from datetime import date
from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world import FarmWorldApp, TractorApp, WeatherApp, SensorApp, RobotApp, DroneApp
from fairy.apps.farm_world.field_ops_app import FieldOpsApp
from fairy.apps.system import SystemApp
from fairy.scenarios.registry import register_scenario
from fairy.scenarios.wofost_farm import FarmDefinition, WofostFarmScenario
from fairy.scenarios.wofost_events import PressureEvent, WeatherWindowEvent, DroughtEvent, install_scenario_events
from fairy.physics.soil_engine import SoilHydraulicModifier
from fairy.types import EventRegisterer

SCENARIO_ID = 'scenario_full_season_heinong84_staggered_planting_V2'
LEGACY_SCENARIO_ID = 'scenario_full_season_heinong84_staggered_planting'
CALIBRATION_STATUS = 'calibrated'
FARMING_PLAN = (
    '三区同一官方Soybean_901，按4/28、5/11、5/28实际播种；已有播期窗口约束。5/8土温不足的试验已否决，不能靠覆写土温强播。',
    '出苗仅各4垄样本；6/28传感器—全田无人机—三区各4垄地面确认，解释冠层差异先考虑播期。',
    '7/20、8/8各30mm常规关键期补水；无例行化学投入。9/17开始分别查阶段/粮水。',
    '9/20收早区、9/22收中区、10/7收迟区；这是公开逐日校准后固定的合法窗口，收前仍实际查各区。',
    '9/20–10/9人工无雨、风2m/s，温湿度辐射保留NASA原值；迟区即使9/26已R8，仍须等粮水≤18%。',
    '对照统一等迟区再收，量化早中区在田损失；错误收未熟迟区应被工具拒绝，随后完成合法补救收储。',
    '2019-05-11：中播区独立播床检查',
    '2019-05-23：早播区出苗样本',
    '2019-05-28：迟播区独立播床检查',
    '2019-06-15：两后播区分别出苗样本',
    '2019-06-28：三区阶段差异',
    '2019-07-20：关键期根水检查',
    '2019-08-08：关键期根水检查',
    '2019-09-17：临近成熟各区分别检查',
    '2019-09-20：成熟与收获窗口',
    '2019-09-22：成熟与收获窗口',
    '2019-10-07：成熟与收获窗口',
)

@register_scenario(SCENARIO_ID)
class ScenarioFullSeasonHeinong84StaggeredPlanting_V2(WofostFarmScenario):
    DESCRIPTION = '同品种错期播种与分区收获'
    DETAILED_BRIEFING = '同一官方地区大豆分三播期建植，按各区真实出苗、生育、成熟、粮水和天气分别收获，不把早区成熟当全田成熟。\n\n公开计划：0–20垄4/28，21–42垄5/11，43–63垄5/28；三块均同一SOYBEAN_901。工具已有播期窗口限制，不能提前播迟播区；晚播是否成熟及何时能收以各区实际观测为准。\n\n农场farm，64垄，每垄268.0×1.1m，一垄两行，面积1.88672ha。官方地区种子SOYBEAN_901，目标45.0株/m²，对应工具株距4.040404040cm、播深4cm。初始VWC0.26、土温12.0°C、土层1.2m，萎蔫点0.1、田间持水量0.3、饱和0.45，入渗50.0mm/day。初始有效N/储备N各为50.0/50.0kgN/ha；库存种子1000000粒、肥料0.0kg、化学工作液0.0L、仓库油1000.0L，拖拉机油100.0L。全季毛灌水额度60.0mm（None表示无硬额度），设施5mm/h；活性成分额度Nonekg（None表示无硬额度）；管理规则conventional。机械除草累计垄次上限None、机械作业额度None；杀虫/杀菌施药日上限None/None。同日多趟仅一个施药日但逐趟扣药。工作液按1g/L记账，机喷杀虫8L/垄、杀菌3.8L/垄、背负杀虫3L/垄为各工具模拟参考，不是现实标签。官方原始作物参数无覆盖，既有适配仅按实际密度/40缩放TDWI，不称田间最优或黑农品种复现。土壤为模型假设；天气为固定NASA POWER公开网格，加本文件明示的人工天气事件。机器人单次最多实际覆盖8垄、内部4垄一批，步行700秒/垄，5%电/垄，充电1h；看实际covered_ridges。无人机速度5m/s、7垄一航带、全田560秒、每垄1%电，最低20%，充电30分钟。种箱30万粒、粮箱2t，播种和收获每次最多4垄、喷药最多10垄；作业、充电和等待推进时间。根区传感器→无人机粗查→机器人分点确认，不把NDVI当病因诊断；低置信度单点不足作业依据。营养及部分表层水分为代理，不能当独立5cm实测或真实缺N诊断；不例行追氮。不按日历每日小水或追满额度。收获须自然R8、水分≤18%、无雨、可通行；卸粮后必要干燥至≤13.5%并入库，核对全部垄。'
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
        warehouse_fertilizer_kg=0.0,
        warehouse_pesticide_l=0.0,
        warehouse_fuel_l=1000.0,
        tractor_fuel_l=100.0,
        irrigation_quota_mm=60.0,
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
        farm.configure_planting_windows([{'label': 'A_early', 'start': 0, 'end': 20, 'seed_type': 'SOYBEAN_901', 'earliest_date': '2019-04-28'}, {'label': 'B_middle', 'start': 21, 'end': 42, 'seed_type': 'SOYBEAN_901', 'earliest_date': '2019-05-11'}, {'label': 'C_late', 'start': 43, 'end': 63, 'seed_type': 'SOYBEAN_901', 'earliest_date': '2019-05-28'}])
        self.apps.append(DroneApp(farm, self.get_typed_app(WeatherApp), name='SurveyDrone',
            speed_ms=5.0, effective_ridges_per_pass=7, takeoff_overhead_s=30,
            min_battery_pct=20.0, battery_pct_per_ridge=1.0))

    def build_events_flow(self):
        # 世界自身事件，与Agent/oracle采取的步骤无关。一次注入不每日覆盖药后下降。
        install_scenario_events(self, [
            WeatherWindowEvent(event_id='middle_sowing_window', farm_id='farm', start=date(2019, 5, 11), end=date(2019, 5, 12), rain_mm=0.0, wind_ms=2.0),
            WeatherWindowEvent(event_id='late_sowing_window', farm_id='farm', start=date(2019, 5, 28), end=date(2019, 5, 29), rain_mm=0.0, wind_ms=2.0),
            WeatherWindowEvent(event_id='harvest_clear_spells', farm_id='farm', start=date(2019, 9, 20), end=date(2019, 10, 9), rain_mm=0.0, wind_ms=2.0),
            WeatherWindowEvent(event_id='cohort_comparison_flight', farm_id='farm', start=date(2019, 6, 28), end=date(2019, 6, 29), rain_mm=0.0, wind_ms=2.0),
        ])
        sensor = self.get_typed_app(SensorApp)
        weather = self.get_typed_app(WeatherApp)
        farm = self.get_typed_app(FarmWorldApp)
        tractor = self.get_typed_app(TractorApp)
        robot = self.get_typed_app(RobotApp)
        drone = self.get_typed_app(DroneApp)
        field_ops = self.get_typed_app(FieldOpsApp)
        system = self.get_typed_app(SystemApp)
        aui = self.get_typed_app(AgentUserInterface)
        with EventRegisterer.capture_mode() as captured:
            aui.send_message_to_agent(self.reference_briefing())
            previous = None

            # 2019-04-28：同一轮正常作业及必要复查
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00001_2019-04-28_播前土壤').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00002_2019-04-28_播前天气').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00003_2019-04-28_播前库存').depends_on(previous))
            previous = (tractor.get_status().oracle()
                .with_id('00004_2019-04-28_播前机具').depends_on(previous))
            previous = (tractor.attach_implement(implement='grader').oracle()
                .with_id('00005_2019-04-28_挂载grader').depends_on(previous))
            previous = (tractor.level().oracle()
                .with_id('00006_2019-04-28_全田level').depends_on(previous, delay_seconds=8321))
            previous = (tractor.detach_implement().oracle()
                .with_id('00007_2019-04-28_卸下grader').depends_on(previous))
            previous = (tractor.attach_implement(implement='furrower').oracle()
                .with_id('00008_2019-04-28_挂载furrower').depends_on(previous))
            previous = (tractor.form_ridges(ridge_width_m=1.1).oracle()
                .with_id('00009_2019-04-28_全田form_ridges').depends_on(previous, delay_seconds=4376))
            previous = (tractor.detach_implement().oracle()
                .with_id('00010_2019-04-28_卸下furrower').depends_on(previous))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=278586).oracle()
                .with_id('00011_2019-04-28_批量装种_0').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=0, end_ridge=3, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00012_2019-04-28_同轮播种_0').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=4, end_ridge=7, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00013_2019-04-28_同轮播种_4').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=8, end_ridge=11, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00014_2019-04-28_同轮播种_8').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=12, end_ridge=15, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00015_2019-04-28_同轮播种_12').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=16, end_ridge=19, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00016_2019-04-28_同轮播种_16').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=20, end_ridge=20, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00017_2019-04-28_同轮播种_20').depends_on(previous, delay_seconds=222))

            # 2019-05-11：中播区独立播床检查
            previous = (system.advance_time(seconds=1109171).oracle()
                .with_id('00018_2019-05-11_中播区独立播床检查').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00019_2019-05-11_中播土壤').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00020_2019-05-11_中播天气').depends_on(previous))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=291852).oracle()
                .with_id('00021_2019-05-11_批量装种_21').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=21, end_ridge=24, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00022_2019-05-11_同轮播种_21').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=25, end_ridge=28, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00023_2019-05-11_同轮播种_25').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=29, end_ridge=32, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00024_2019-05-11_同轮播种_29').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=33, end_ridge=36, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00025_2019-05-11_同轮播种_33').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=37, end_ridge=40, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00026_2019-05-11_同轮播种_37').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=41, end_ridge=42, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00027_2019-05-11_同轮播种_41').depends_on(previous, delay_seconds=222))

            # 2019-05-23：早播区出苗样本
            previous = (system.advance_time(seconds=1035468).oracle()
                .with_id('00028_2019-05-23_早播区出苗样本').depends_on(previous))
            previous = (robot.inspect_emergence(start_ridge=0, end_ridge=3).oracle()
                .with_id('00029_2019-05-23_A出苗样本').depends_on(previous, delay_seconds=2800))
            previous = (robot.charge().oracle()
                .with_id('00030_2019-05-23_出苗后充电').depends_on(previous))
            previous = (system.advance_time(hours=1).oracle()
                .with_id('00031_2019-05-23_等待出苗后充电').depends_on(previous))

            # 2019-05-28：迟播区独立播床检查
            previous = (system.advance_time(seconds=425600).oracle()
                .with_id('00032_2019-05-28_迟播区独立播床检查').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00033_2019-05-28_迟播土壤').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00034_2019-05-28_迟播天气').depends_on(previous))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=278586).oracle()
                .with_id('00035_2019-05-28_批量装种_43').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=43, end_ridge=46, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00036_2019-05-28_同轮播种_43').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=47, end_ridge=50, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00037_2019-05-28_同轮播种_47').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=51, end_ridge=54, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00038_2019-05-28_同轮播种_51').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=55, end_ridge=58, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00039_2019-05-28_同轮播种_55').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=59, end_ridge=62, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00040_2019-05-28_同轮播种_59').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=63, end_ridge=63, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00041_2019-05-28_同轮播种_63').depends_on(previous, delay_seconds=222))

            # 2019-06-15：两后播区分别出苗样本
            previous = (system.advance_time(seconds=1553868).oracle()
                .with_id('00042_2019-06-15_两后播区分别出苗样本').depends_on(previous))
            previous = (robot.inspect_emergence(start_ridge=24, end_ridge=27).oracle()
                .with_id('00043_2019-06-15_分区出苗24').depends_on(previous, delay_seconds=2800))
            previous = (robot.inspect_emergence(start_ridge=48, end_ridge=51).oracle()
                .with_id('00044_2019-06-15_分区出苗48').depends_on(previous, delay_seconds=2800))

            # 2019-06-28：三区阶段差异
            previous = (system.advance_time(seconds=1117600).oracle()
                .with_id('00045_2019-06-28_三区阶段差异').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00046_2019-06-28_三区公开阶段').depends_on(previous))
            previous = (robot.charge().oracle()
                .with_id('00047_2019-06-28_分区检查前补满电').depends_on(previous))
            previous = (system.advance_time(hours=1).oracle()
                .with_id('00048_2019-06-28_等待分区检查前补满电').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00049_2019-06-28_分播期冠层比较根水').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00050_2019-06-28_分播期冠层比较冠层').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00051_2019-06-28_分播期冠层比较飞行天气').depends_on(previous))
            previous = (drone.check_status().oracle()
                .with_id('00052_2019-06-28_分播期冠层比较无人机电量').depends_on(previous))
            previous = (drone.fly_survey(start_ridge=0, end_ridge=63).oracle()
                .with_id('00053_2019-06-28_分播期冠层比较全田粗查非确诊').depends_on(previous, delay_seconds=560))
            previous = (robot.check_status().oracle()
                .with_id('00054_2019-06-28_分播期冠层比较机器人电量').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=0, end_ridge=3).oracle()
                .with_id('00055_2019-06-28_各播区地面样本_0_3').depends_on(previous, delay_seconds=2800))
            previous = (robot.inspect_crop_health(start_ridge=24, end_ridge=27).oracle()
                .with_id('00056_2019-06-28_各播区地面样本_24_27').depends_on(previous, delay_seconds=2800))
            previous = (robot.inspect_crop_health(start_ridge=48, end_ridge=51).oracle()
                .with_id('00057_2019-06-28_各播区地面样本_48_51').depends_on(previous, delay_seconds=2800))
            previous = (robot.charge().oracle()
                .with_id('00058_2019-06-28_本轮检查后充电').depends_on(previous))
            previous = (drone.charge().oracle()
                .with_id('00059_2019-06-28_无人机充电').depends_on(previous))
            previous = (system.advance_time(hours=1).oracle()
                .with_id('00060_2019-06-28_等待本轮检查后充电').depends_on(previous))

            # 2019-07-20：关键期根水检查
            previous = (system.advance_time(seconds=1884640).oracle()
                .with_id('00061_2019-07-20_关键期根水检查').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00062_2019-07-20_公开阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00063_2019-07-20_根区亏缺').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00064_2019-07-20_近期降雨').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=6.0).oracle()
                .with_id('00065_2019-07-20_正常一轮补水').depends_on(previous, delay_seconds=21900))

            # 2019-08-08：关键期根水检查
            previous = (system.advance_time(seconds=1619700).oracle()
                .with_id('00066_2019-08-08_关键期根水检查').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00067_2019-08-08_公开阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00068_2019-08-08_根区亏缺').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00069_2019-08-08_近期降雨').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=6.0).oracle()
                .with_id('00070_2019-08-08_正常一轮补水').depends_on(previous, delay_seconds=21900))

            # 2019-09-17：临近成熟各区分别检查
            previous = (system.advance_time(seconds=3434100).oracle()
                .with_id('00071_2019-09-17_临近成熟各区分别检查').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00072_2019-09-17_各区成熟与粮水').depends_on(previous))
            previous = (weather.get_forecast(days=5).oracle()
                .with_id('00073_2019-09-17_收获天气预报').depends_on(previous))

            # 2019-09-20：成熟与收获窗口
            previous = (system.advance_time(seconds=259200).oracle()
                .with_id('00074_2019-09-20_成熟与收获窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=20).oracle()
                .with_id('00075_2019-09-20_成熟与粮水').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00076_2019-09-20_收前土壤').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00077_2019-09-20_收前天气').depends_on(previous))
            previous = (tractor.attach_implement(implement='harvester').oracle()
                .with_id('00078_2019-09-20_安装收割机').depends_on(previous))
            previous = (tractor.harvest(start_ridge=0, end_ridge=3).oracle()
                .with_id('00079_2019-09-20_同轮收割_0').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=4, end_ridge=7).oracle()
                .with_id('00080_2019-09-20_同轮收割_4').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00081_2019-09-20_合批卸粮_0').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00082_2019-09-20_必要干燥_0').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00083_2019-09-20_安全入库_0').depends_on(previous))
            previous = (tractor.harvest(start_ridge=8, end_ridge=11).oracle()
                .with_id('00084_2019-09-20_同轮收割_8').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=12, end_ridge=15).oracle()
                .with_id('00085_2019-09-20_同轮收割_12').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00086_2019-09-20_合批卸粮_8').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00087_2019-09-20_必要干燥_8').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00088_2019-09-20_安全入库_8').depends_on(previous))
            previous = (tractor.harvest(start_ridge=16, end_ridge=19).oracle()
                .with_id('00089_2019-09-20_同轮收割_16').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=20, end_ridge=20).oracle()
                .with_id('00090_2019-09-20_同轮收割_20').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00091_2019-09-20_合批卸粮_16').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00092_2019-09-20_必要干燥_16').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00093_2019-09-20_安全入库_16').depends_on(previous))
            previous = (tractor.detach_implement().oracle()
                .with_id('00094_2019-09-20_收后卸机具').depends_on(previous))

            # 2019-09-22：成熟与收获窗口
            previous = (system.advance_time(seconds=169734).oracle()
                .with_id('00095_2019-09-22_成熟与收获窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=21, end=42).oracle()
                .with_id('00096_2019-09-22_成熟与粮水').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00097_2019-09-22_收前土壤').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00098_2019-09-22_收前天气').depends_on(previous))
            previous = (tractor.attach_implement(implement='harvester').oracle()
                .with_id('00099_2019-09-22_安装收割机').depends_on(previous))
            previous = (tractor.harvest(start_ridge=21, end_ridge=24).oracle()
                .with_id('00100_2019-09-22_同轮收割_21').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=25, end_ridge=28).oracle()
                .with_id('00101_2019-09-22_同轮收割_25').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00102_2019-09-22_合批卸粮_21').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00103_2019-09-22_必要干燥_21').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00104_2019-09-22_安全入库_21').depends_on(previous))
            previous = (tractor.harvest(start_ridge=29, end_ridge=32).oracle()
                .with_id('00105_2019-09-22_同轮收割_29').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=33, end_ridge=36).oracle()
                .with_id('00106_2019-09-22_同轮收割_33').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00107_2019-09-22_合批卸粮_29').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00108_2019-09-22_必要干燥_29').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00109_2019-09-22_安全入库_29').depends_on(previous))
            previous = (tractor.harvest(start_ridge=37, end_ridge=40).oracle()
                .with_id('00110_2019-09-22_同轮收割_37').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=41, end_ridge=42).oracle()
                .with_id('00111_2019-09-22_同轮收割_41').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00112_2019-09-22_合批卸粮_37').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00113_2019-09-22_必要干燥_37').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00114_2019-09-22_安全入库_37').depends_on(previous))
            previous = (tractor.detach_implement().oracle()
                .with_id('00115_2019-09-22_收后卸机具').depends_on(previous))

            # 2019-10-07：成熟与收获窗口
            previous = (system.advance_time(seconds=1292934).oracle()
                .with_id('00116_2019-10-07_成熟与收获窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=43, end=63).oracle()
                .with_id('00117_2019-10-07_成熟与粮水').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00118_2019-10-07_收前土壤').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00119_2019-10-07_收前天气').depends_on(previous))
            previous = (tractor.attach_implement(implement='harvester').oracle()
                .with_id('00120_2019-10-07_安装收割机').depends_on(previous))
            previous = (tractor.harvest(start_ridge=43, end_ridge=46).oracle()
                .with_id('00121_2019-10-07_同轮收割_43').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=47, end_ridge=50).oracle()
                .with_id('00122_2019-10-07_同轮收割_47').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00123_2019-10-07_合批卸粮_43').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00124_2019-10-07_必要干燥_43').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00125_2019-10-07_安全入库_43').depends_on(previous))
            previous = (tractor.harvest(start_ridge=51, end_ridge=54).oracle()
                .with_id('00126_2019-10-07_同轮收割_51').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=55, end_ridge=58).oracle()
                .with_id('00127_2019-10-07_同轮收割_55').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00128_2019-10-07_合批卸粮_51').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00129_2019-10-07_必要干燥_51').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00130_2019-10-07_安全入库_51').depends_on(previous))
            previous = (tractor.harvest(start_ridge=59, end_ridge=62).oracle()
                .with_id('00131_2019-10-07_同轮收割_59').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=63, end_ridge=63).oracle()
                .with_id('00132_2019-10-07_同轮收割_63').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00133_2019-10-07_合批卸粮_59').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00134_2019-10-07_必要干燥_59').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00135_2019-10-07_安全入库_59').depends_on(previous))
            previous = (tractor.detach_implement().oracle()
                .with_id('00136_2019-10-07_收后卸机具').depends_on(previous))

        for event in captured:
            event.record_runtime_timing = True
        self.events = list(captured)
        return self.events
