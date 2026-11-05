"""01｜虫害阈值与有限施药机会：独立、完整的 WOFOST 全季场景。

旧 ID/文件仍由经典引擎运行；历史 Heinong84 名称不代表本场实际品种。
官方 Soybean_901 的 78 项作物原值不覆盖；土壤、密度、额度及外接虫压是
场景假设。天气来自仓库内带 SHA256 的 NASA POWER Lille 2019 固定数据；
两个明确声明的雨风窗口为人工设定，其余气象字段保留原值。
世界事件不依赖任何 oracle 农事步骤。once/set 只注入一次，随后可正常治虫。
农事轮次与设备调用分开；分两趟施药仍是一轮，同一天只占一个施药日额度。
等待及 delay_seconds 来自真实工具耗时；dry_grain 仍为即时处理抽象。
"""
from datetime import date

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world import FarmWorldApp, TractorApp, WeatherApp, SensorApp, RobotApp, DroneApp
from fairy.apps.farm_world.field_ops_app import FieldOpsApp
from fairy.apps.system import SystemApp
from fairy.scenarios.registry import register_scenario
from fairy.scenarios.wofost_farm import FarmDefinition, WofostFarmScenario
from fairy.scenarios.wofost_events import PressureEvent, WeatherWindowEvent, install_scenario_events
from fairy.types import EventRegisterer

SCENARIO_ID = 'scenario_full_season_heinong84_threshold_insect_limited_spray_V2'
LEGACY_SCENARIO_ID = 'scenario_full_season_heinong84_threshold_insect_limited_spray'
CALIBRATION_STATUS = 'calibrated'
FARMING_PLAN = (
    '4月28日：核对土壤、天气、库存和设备，整地、起垄、全田播种；不例行追施氮肥。',
    '5月13日抽样0–3垄播后状态；尚未出苗不等于播种失败；5月28日用冠层及地面样本复核苗情和杂草，均不代表逐垄全查。',
    '6月15日：传感器→全田无人机粗查→18–21及34–37垄地面样本→18和34垄虫量分档确认；轻虫情不施药，保留额度。',
    '6月28日花期核对阶段与根水；7月20日确认根水亏缺、近期少雨，全田一次30mm。',
    '7月25日：再次核对生育期、根水、冠层→全田无人机粗查→同两组地面样本及虫量分档确认；病害证据不足，不改用杀菌剂。',
    '7月25日：确认虫害需要干预且无雨可通行，18–37垄8L/垄，共160L，18–27与28–37分两趟，同日一轮施药。',
    '7月28日：复查两组样本与库存；处理后虫情下降，不重复施药。',
    '8月8日：复核阶段、根水及降雨预报，全田一次30mm；不每日小水追满额度。',
    '9月20日：确认全田R8、粮水≤18%、无雨及可通行；一次全田收获，16趟收割、8批卸粮/必要干燥至13%/入库。',
)
# 64×268×1.1=18867.2m²=1.88672ha；一垄两行。
# 45株/m² => 株距100×2/(45×1.1)=4.040404...cm；每垄13266粒，合计849024粒。
# 七轮田间农事：整地1、起垄1、播种1、灌溉2、杀虫1、收获1；检查另计。
# 内部压力分档/检测是工程教学阈值，不是田间验证的虫种经济阈值。

@register_scenario(SCENARIO_ID)
class ScenarioFullSeasonHeinong84ThresholdInsectLimitedSpray_V2(WofostFarmScenario):
    DESCRIPTION = '虫害阈值与有限施药机会：轻虫情先观察，确认加重再定向处理，完成全季安全收储。'
    DETAILED_BRIEFING = (
        '你负责法国Lille一块64垄大豆田，种子为官方地区参数组SOYBEAN_901，历史文件名不表示黑农84研究复现。'
        '农场ID为farm，每垄268m长、1.1m宽，一垄两行，面积1.88672ha。目标45株/m²，工具株距4.040404cm、播深4cm；'
        '初始根区设定VWC0.26、土温12°C、土层1.2m，萎蔫点0.10/田间持水量0.30/饱和0.45、入渗上限50mm/日；'
        '当前密度适配仅按45/40缩放官方TDWI初始生物量，不称官方推荐或田间最优密度。初始有效氮与土壤储备氮模型设定均50kgN/ha，不因营养代理读数偏低而例行施氮。\n\n'
        '库存100万粒种子、肥料0kg、杀虫工作液160L、仓库燃油1000L，拖拉机初始100L；'
        '固定灌溉设施5mm/h，全季毛水60mm（按全田等效面积核算）。杀虫最多1个施药日，活性成分总额0.16kg；'
        '当前工具按1g/L工作液记账，8L/垄为既有模拟药效参考剂量，并非现实农药标签。'
        '同一天多趟只计一个施药日，但每趟均扣工作液和活性成分。药量只够20垄按参考剂量处理一轮，轻微信号就用完会失去后续机会。\n\n'
        '农场交接记录将18–37垄列为重点巡查区，这是公开的风险线索，不是必须施药的结论。无人机差异可能弱且带噪，不能据此精确划定虫区。按生育阶段巡查，轻虫情先观察；冠层异常先看根区水分与天气，再用无人机粗查范围，机器人分点确认虫情、病害及虫量分档。'
        '结合多个样本的pest_present、置信度、inspect_ridge的pest_count_estimate和前后变化判断，不能把一个阳性或无人机NDVI直接当作施药依据。'
        '从low发展为medium/high、多个样本确认有虫且作物仍有保产价值时，核对无雨、风速低于6m/s、土壤可通行再安排针对性处理；处理后复查。'
        '这些分档是本模拟的管理判据，不是田间虫种的经济阈值；病虫草由FAIRY外接胁迫耦合。\n\n'
        '机器人单次范围任务最多实际覆盖8垄，观测内部每4垄一批；看实际covered_ridges，不能把4垄样本称全田检查。'
        'SurveyDrone满电100%，5m/s、7垄一航带、每垄耗电1%，最低20%；全田一次560秒，飞行后须充电30分钟。'
        '机器人充电1小时，步行检查每垄700秒，范围检查每垄耗电5%，单垄详细检查耗电20%。'
        '拖拉机种箱30万粒、粮箱2吨；播种和收割每次最多4垄，喷药每趟最多10垄。作业按真实耗时推进。'
        '确认自然成熟R8、籽粒含水率不高于18%、无雨且可通行后收割，及时卸粮，必要干燥后≤13.5%安全入库，核对全部64垄。'
        '表层水分与营养部分读数为模型代理，不能解释成独立5cm实测或真实缺氮确诊。'
    )
    WORLD = FarmDefinition(
        reference_id='lille', seed_type='SOYBEAN_901', timezone_name='Europe/Paris',
        sowing_date=date(2019, 4, 28), end_date=date(2019, 11, 15), farm_id='farm',
        num_ridges=64, field_length_m=268.0, ridge_width_m=1.1,
        initial_vwc=0.26, initial_soil_temperature_c=12.0, soil_depth_m=1.2,
        wilting_point_vwc=0.10, field_capacity_vwc=0.30, saturation_vwc=0.45,
        infiltration_mm_day=50.0, initial_available_n_kg_ha=50.0, base_soil_n_kg_ha=50.0,
        base_fertilizer_kg=0.0, seed_stock=1000000, warehouse_fertilizer_kg=0.0,
        warehouse_pesticide_l=160.0, warehouse_fuel_l=1000.0, tractor_fuel_l=100.0,
        irrigation_quota_mm=60.0, active_ingredient_cap_kg=0.16,
        max_machine_passes=None, management_regime='limited_insecticide',
        max_insecticide_applications=1, max_fungicide_applications=None,
        max_mechanical_weed_ridges=None, external_biotic_coupling=True,
        grain_moisture_mode='soybean_equilibrium', planting_density_plants_m2=45.0,
        required_field_preparation_ops=('level', 'form_ridges'),
    )

    def init_and_populate_apps(self):
        super().init_and_populate_apps()
        self.apps.append(DroneApp(
            self.get_typed_app(FarmWorldApp), self.get_typed_app(WeatherApp),
            name='SurveyDrone', description='全田冠层粗查，用地面样本确认病因。',
            speed_ms=5.0, effective_ridges_per_pass=7, takeoff_overhead_s=30,
            min_battery_pct=20.0, battery_pct_per_ridge=1.0,
        ))

    def build_events_flow(self):
        # 只注入一次：不能每日set覆盖施药后的虫压下降。雨风窗口公开标为人工设定。
        install_scenario_events(self, [
            PressureEvent('early_light_insects', 'farm', 18, 37,
                date(2019, 6, 14), date(2019, 6, 15), 'insect', 0.08, 'set', 'once'),
            PressureEvent('reproductive_insect_outbreak', 'farm', 18, 37,
                date(2019, 7, 24), date(2019, 7, 25), 'insect', 0.65, 'set', 'once'),
            WeatherWindowEvent('early_scout_window', 'farm',
                date(2019, 6, 15), date(2019, 6, 16), rain_mm=0.0, wind_ms=2.0),
            WeatherWindowEvent('outbreak_scout_and_spray_window', 'farm',
                date(2019, 7, 25), date(2019, 7, 28), rain_mm=0.0, wind_ms=2.0),
        ])
        aui = self.get_typed_app(AgentUserInterface)
        farm = self.get_typed_app(FarmWorldApp)
        tractor = self.get_typed_app(TractorApp)
        weather = self.get_typed_app(WeatherApp)
        sensor = self.get_typed_app(SensorApp)
        robot = self.get_typed_app(RobotApp)
        drone = self.get_typed_app(DroneApp, 'SurveyDrone')
        field_ops = self.get_typed_app(FieldOpsApp)
        system = self.get_typed_app(SystemApp)
        with EventRegisterer.capture_mode() as captured:
            aui.send_message_to_agent(self.reference_briefing())
            previous = None

            # 2019-04-28：播前核对→整地→起垄→一垄两行全田播种，按30万粒种箱分批装种。
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00001_2019-04-28_soil_before_sowing').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00002_2019-04-28_weather_before_sowing').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00003_2019-04-28_seed_fuel_chemical_inventory').depends_on(previous))
            previous = (tractor.get_status().oracle()
                .with_id('00004_2019-04-28_tractor_capacity').depends_on(previous))
            previous = (tractor.attach_implement(implement='grader').oracle()
                .with_id('00005_2019-04-28_grader').depends_on(previous))
            previous = (tractor.level().oracle()
                .with_id('00006_2019-04-28_level64').depends_on(previous, delay_seconds=8321))
            previous = (tractor.detach_implement().oracle()
                .with_id('00007_2019-04-28_detach_grader').depends_on(previous))
            previous = (tractor.attach_implement(implement='furrower').oracle()
                .with_id('00008_2019-04-28_furrower').depends_on(previous))
            previous = (tractor.form_ridges(ridge_width_m=1.1).oracle()
                .with_id('00009_2019-04-28_form64').depends_on(previous, delay_seconds=4376))
            previous = (tractor.detach_implement().oracle()
                .with_id('00010_2019-04-28_detach_furrower').depends_on(previous))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=300000).oracle()
                .with_id('00011_2019-04-28_seed_payload_0').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=0, end_ridge=3, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00012_2019-04-28_sow_0').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=4, end_ridge=7, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00013_2019-04-28_sow_4').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=8, end_ridge=11, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00014_2019-04-28_sow_8').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=12, end_ridge=15, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00015_2019-04-28_sow_12').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=16, end_ridge=19, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00016_2019-04-28_sow_16').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=265320).oracle()
                .with_id('00017_2019-04-28_seed_payload_20').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=20, end_ridge=23, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00018_2019-04-28_sow_20').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=24, end_ridge=27, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00019_2019-04-28_sow_24').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=28, end_ridge=31, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00020_2019-04-28_sow_28').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=32, end_ridge=35, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00021_2019-04-28_sow_32').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=36, end_ridge=39, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00022_2019-04-28_sow_36').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=265320).oracle()
                .with_id('00023_2019-04-28_seed_payload_40').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=40, end_ridge=43, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00024_2019-04-28_sow_40').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=44, end_ridge=47, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00025_2019-04-28_sow_44').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=48, end_ridge=51, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00026_2019-04-28_sow_48').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=52, end_ridge=55, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00027_2019-04-28_sow_52').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=56, end_ridge=59, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00028_2019-04-28_sow_56').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=18384).oracle()
                .with_id('00029_2019-04-28_seed_payload_60').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=60, end_ridge=63, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00030_2019-04-28_sow_60').depends_on(previous, delay_seconds=222))

            # 2019-05-13：播后状态样本：此时官方模型尚未出苗，不能仅据此盲目补播。
            previous = (system.advance_time(seconds=1279751).oracle()
                .with_id('00031_2019-05-13_wait_emergence').depends_on(previous))
            previous = (robot.check_status().oracle()
                .with_id('00032_2019-05-13_emergence_battery').depends_on(previous))
            previous = (robot.inspect_emergence(start_ridge=0, end_ridge=3).oracle()
                .with_id('00033_2019-05-13_emergence_sample0to3').depends_on(previous, delay_seconds=2800))

            # 2019-05-28：播后苗情和杂草复核，有限地面样本不称作全田检查。
            previous = (system.advance_time(seconds=1293200).oracle()
                .with_id('00034_2019-05-28_wait_vegetative').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00035_2019-05-28_early_canopy').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=0, end_ridge=3).oracle()
                .with_id('00036_2019-05-28_weed_sample0to3').depends_on(previous, delay_seconds=2800))
            previous = (robot.charge().oracle()
                .with_id('00037_2019-05-28_recharge_before_scouting').depends_on(previous))
            previous = (system.advance_time(hours=1).oracle()
                .with_id('00038_2019-05-28_wait_recharge').depends_on(previous))

            # 2019-06-15：早期轻虫情：传感器→无人机粗查→两组地面样本→两垄详细虫量分档；保留药量。
            previous = (system.advance_time(seconds=1548800).oracle()
                .with_id('00039_2019-06-15_wait_early_light_insect_scout').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00040_2019-06-15_light_canopy').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00041_2019-06-15_light_roots').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00042_2019-06-15_light_weather').depends_on(previous))
            previous = (drone.check_status().oracle()
                .with_id('00043_2019-06-15_light_drone_status').depends_on(previous))
            previous = (drone.fly_survey(start_ridge=0, end_ridge=63).oracle()
                .with_id('00044_2019-06-15_light_aerial64').depends_on(previous, delay_seconds=560))
            previous = (robot.check_status().oracle()
                .with_id('00045_2019-06-15_light_robot_status').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=18, end_ridge=21).oracle()
                .with_id('00046_2019-06-15_light_ground18to21').depends_on(previous, delay_seconds=2800))
            previous = (robot.inspect_crop_health(start_ridge=34, end_ridge=37).oracle()
                .with_id('00047_2019-06-15_light_ground34to37').depends_on(previous, delay_seconds=2800))
            previous = (robot.inspect_ridge(ridge_id=18).oracle()
                .with_id('00048_2019-06-15_light_density18').depends_on(previous, delay_seconds=700))
            previous = (robot.inspect_ridge(ridge_id=34).oracle()
                .with_id('00049_2019-06-15_light_density34').depends_on(previous, delay_seconds=700))
            previous = (robot.charge().oracle()
                .with_id('00050_2019-06-15_light_charge_robot').depends_on(previous))
            previous = (drone.charge().oracle()
                .with_id('00051_2019-06-15_light_charge_drone').depends_on(previous))
            previous = (system.advance_time(hours=1).oracle()
                .with_id('00052_2019-06-15_light_wait_charging').depends_on(previous))

            # 2019-06-28：花期公开阶段与根水复核，无依据不例行追氮。
            previous = (system.advance_time(seconds=1112040).oracle()
                .with_id('00053_2019-06-28_wait_flowering').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00054_2019-06-28_flowering_stage').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00055_2019-06-28_flowering_roots').depends_on(previous))

            # 2019-07-20：R3根水与近期降雨核对后，一轮全田30mm。
            previous = (system.advance_time(seconds=1900800).oracle()
                .with_id('00056_2019-07-20_wait_R3_water').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00057_2019-07-20_R3_stage').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00058_2019-07-20_R3_roots').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00059_2019-07-20_R3_rain_forecast').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=6.0).oracle()
                .with_id('00060_2019-07-20_R3_30mm').depends_on(previous, delay_seconds=21900))

            # 2019-07-25：生殖期虫情加重：同样层次的复查确认后处理18–37；8L/垄两趟，同日一轮。
            previous = (system.advance_time(seconds=410100).oracle()
                .with_id('00061_2019-07-25_wait_outbreak_scout').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00062_2019-07-25_outbreak_stage').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00063_2019-07-25_outbreak_canopy').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00064_2019-07-25_outbreak_roots').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00065_2019-07-25_outbreak_weather').depends_on(previous))
            previous = (drone.check_status().oracle()
                .with_id('00066_2019-07-25_outbreak_drone_status').depends_on(previous))
            previous = (drone.fly_survey(start_ridge=0, end_ridge=63).oracle()
                .with_id('00067_2019-07-25_outbreak_aerial64').depends_on(previous, delay_seconds=560))
            previous = (robot.check_status().oracle()
                .with_id('00068_2019-07-25_outbreak_robot_status').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=18, end_ridge=21).oracle()
                .with_id('00069_2019-07-25_outbreak_ground18to21').depends_on(previous, delay_seconds=2800))
            previous = (robot.inspect_crop_health(start_ridge=34, end_ridge=37).oracle()
                .with_id('00070_2019-07-25_outbreak_ground34to37').depends_on(previous, delay_seconds=2800))
            previous = (robot.inspect_ridge(ridge_id=18).oracle()
                .with_id('00071_2019-07-25_outbreak_density18').depends_on(previous, delay_seconds=700))
            previous = (robot.inspect_ridge(ridge_id=34).oracle()
                .with_id('00072_2019-07-25_outbreak_density34').depends_on(previous, delay_seconds=700))
            previous = (robot.charge().oracle()
                .with_id('00073_2019-07-25_outbreak_charge_robot').depends_on(previous))
            previous = (drone.charge().oracle()
                .with_id('00074_2019-07-25_outbreak_charge_drone').depends_on(previous))
            previous = (system.advance_time(hours=1).oracle()
                .with_id('00075_2019-07-25_outbreak_wait_charging').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00076_2019-07-25_threshold_spray_weather').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00077_2019-07-25_threshold_spray_soil').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00078_2019-07-25_threshold_spray_inventory').depends_on(previous))
            previous = (tractor.attach_implement(implement='sprayer').oracle()
                .with_id('00079_2019-07-25_threshold_spray_sprayer').depends_on(previous))
            previous = (tractor.load_pesticide(liters=160.0).oracle()
                .with_id('00080_2019-07-25_threshold_spray_load160L').depends_on(previous))
            previous = (tractor.spray_pesticide(start_ridge=18, end_ridge=27, liters_per_ridge=8.0).oracle()
                .with_id('00081_2019-07-25_threshold_spray_first10').depends_on(previous, delay_seconds=190))
            previous = (tractor.spray_pesticide(start_ridge=28, end_ridge=37, liters_per_ridge=8.0).oracle()
                .with_id('00082_2019-07-25_threshold_spray_second10').depends_on(previous, delay_seconds=190))
            previous = (tractor.detach_implement().oracle()
                .with_id('00083_2019-07-25_threshold_spray_detach').depends_on(previous))

            # 2019-07-28：药后复查确认下降；不能把低置信度单点假阳性当成病害确诊。
            previous = (system.advance_time(seconds=247660).oracle()
                .with_id('00084_2019-07-28_wait_post_spray_recheck').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00085_2019-07-28_recheck_canopy').depends_on(previous))
            previous = (robot.check_status().oracle()
                .with_id('00086_2019-07-28_recheck_robot_status').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=18, end_ridge=21).oracle()
                .with_id('00087_2019-07-28_recheck18to21').depends_on(previous, delay_seconds=2800))
            previous = (robot.inspect_crop_health(start_ridge=34, end_ridge=37).oracle()
                .with_id('00088_2019-07-28_recheck34to37').depends_on(previous, delay_seconds=2800))
            previous = (farm.get_inventory().oracle()
                .with_id('00089_2019-07-28_recheck_inventory').depends_on(previous))

            # 2019-08-08：R5再次确认根水亏缺及预报不足，一轮全田30mm。
            previous = (system.advance_time(seconds=944800).oracle()
                .with_id('00090_2019-08-08_wait_R5_water').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00091_2019-08-08_R5_stage').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00092_2019-08-08_R5_roots').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00093_2019-08-08_R5_rain_forecast').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=6.0).oracle()
                .with_id('00094_2019-08-08_R5_30mm').depends_on(previous, delay_seconds=21900))

            # 2019-09-20：全田成熟/粮水/通行性/无雨核对后收割；每8垄卸粮一次，均实际记账。
            previous = (system.advance_time(seconds=3693300).oracle()
                .with_id('00095_2019-09-20_wait_harvest').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00096_2019-09-20_maturity_all64').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00097_2019-09-20_trafficability_before_harvest').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00098_2019-09-20_harvest_weather').depends_on(previous))
            previous = (tractor.attach_implement(implement='harvester').oracle()
                .with_id('00099_2019-09-20_harvester').depends_on(previous))
            previous = (tractor.harvest(start_ridge=0, end_ridge=3).oracle()
                .with_id('00100_2019-09-20_harvest_0').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=4, end_ridge=7).oracle()
                .with_id('00101_2019-09-20_harvest_4').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00102_2019-09-20_unload_0').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00103_2019-09-20_dry_0').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00104_2019-09-20_store_0').depends_on(previous))
            previous = (tractor.harvest(start_ridge=8, end_ridge=11).oracle()
                .with_id('00105_2019-09-20_harvest_8').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=12, end_ridge=15).oracle()
                .with_id('00106_2019-09-20_harvest_12').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00107_2019-09-20_unload_8').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00108_2019-09-20_dry_8').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00109_2019-09-20_store_8').depends_on(previous))
            previous = (tractor.harvest(start_ridge=16, end_ridge=19).oracle()
                .with_id('00110_2019-09-20_harvest_16').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=20, end_ridge=23).oracle()
                .with_id('00111_2019-09-20_harvest_20').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00112_2019-09-20_unload_16').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00113_2019-09-20_dry_16').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00114_2019-09-20_store_16').depends_on(previous))
            previous = (tractor.harvest(start_ridge=24, end_ridge=27).oracle()
                .with_id('00115_2019-09-20_harvest_24').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=28, end_ridge=31).oracle()
                .with_id('00116_2019-09-20_harvest_28').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00117_2019-09-20_unload_24').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00118_2019-09-20_dry_24').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00119_2019-09-20_store_24').depends_on(previous))
            previous = (tractor.harvest(start_ridge=32, end_ridge=35).oracle()
                .with_id('00120_2019-09-20_harvest_32').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=36, end_ridge=39).oracle()
                .with_id('00121_2019-09-20_harvest_36').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00122_2019-09-20_unload_32').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00123_2019-09-20_dry_32').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00124_2019-09-20_store_32').depends_on(previous))
            previous = (tractor.harvest(start_ridge=40, end_ridge=43).oracle()
                .with_id('00125_2019-09-20_harvest_40').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=44, end_ridge=47).oracle()
                .with_id('00126_2019-09-20_harvest_44').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00127_2019-09-20_unload_40').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00128_2019-09-20_dry_40').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00129_2019-09-20_store_40').depends_on(previous))
            previous = (tractor.harvest(start_ridge=48, end_ridge=51).oracle()
                .with_id('00130_2019-09-20_harvest_48').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=52, end_ridge=55).oracle()
                .with_id('00131_2019-09-20_harvest_52').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00132_2019-09-20_unload_48').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00133_2019-09-20_dry_48').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00134_2019-09-20_store_48').depends_on(previous))
            previous = (tractor.harvest(start_ridge=56, end_ridge=59).oracle()
                .with_id('00135_2019-09-20_harvest_56').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=60, end_ridge=63).oracle()
                .with_id('00136_2019-09-20_harvest_60').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00137_2019-09-20_unload_56').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00138_2019-09-20_dry_56').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00139_2019-09-20_store_56').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00140_2019-09-20_final_inventory').depends_on(previous))

        for event in captured:
            event.record_runtime_timing = True
        self.events = list(captured)
        return self.events
