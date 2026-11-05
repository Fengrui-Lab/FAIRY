"""11｜先病后虫，共用施药预算。
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

SCENARIO_ID = 'scenario_full_season_hb_insect_after_fungicide_budget_conflict_V2'
LEGACY_SCENARIO_ID = 'scenario_full_season_hb_insect_after_fungicide_budget_conflict'
CALIBRATION_STATUS = 'calibrated'
FARMING_PLAN = (
    '前期16垄×3.8L=60.8L；后期16垄×背负3L=48L，总108.8/110L、0.1088/0.11kg，余1.2L不追用。',
    '后期5天人工雨共150mm及浅黏土参数共同通过真实原生水量平衡形成湿土；停雨后核对土水，正常人工背负8趟、每趟2垄且advance_time=True。',
    '原题共享预算和湿土人工路线都保留，不把机喷8L/垄与背负3L/垄不同参考当真实浓度或零耗时优势；8月根区充足不额外灌水。',
    '2019-05-23：等待出苗',
    '2019-07-06：中期病害诊断',
    '2019-07-07：只病区60点8升杀菌窗口',
    '2019-07-20：关键期根水检查',
    '2019-08-07：后期停雨但湿土虫情',
    '2019-08-08：雨后根区充足不再例行灌水',
    '2019-08-13：后期药后复核',
    '2019-09-20：成熟与收获窗口',
)

@register_scenario(SCENARIO_ID)
class ScenarioFullSeasonHBInsectAfterFungicideBudgetConflict_V2(WofostFarmScenario):
    DESCRIPTION = '先病后虫，共用施药预算'
    DETAILED_BRIEFING = '中期杀菌与后期杀虫共用库存及活性额度。后期遇真实湿土、无雨小风时需改用人工背负点喷，保留原题湿土人工路径；不可通过时间开关免除人工耗时。\n\n土壤为浅黏层情境：FC0.38、饱和0.50、有效土层0.4m、导水10mm/day。后期有明确人工强雨事件，停雨后需同时检查土壤与雨风；人工背负药效参考3L/垄，与机喷8L/垄是工具的不同工作液规范，不解释成真实药品浓度优势。\n\n农场farm，64垄，每垄268.0×1.1m，一垄两行，面积1.88672ha。官方地区种子SOYBEAN_901，目标45.0株/m²，对应工具株距4.040404040cm、播深4cm。初始VWC0.26、土温12.0°C、土层0.4m，萎蔫点0.1、田间持水量0.38、饱和0.5，入渗10.0mm/day。初始有效N/储备N各为50.0/50.0kgN/ha；库存种子1000000粒、肥料0.0kg、化学工作液110.0L、仓库油1000.0L，拖拉机油100.0L。全季毛灌水额度60.0mm（None表示无硬额度），设施5mm/h；活性成分额度0.11kg（None表示无硬额度）；管理规则conventional。机械除草累计垄次上限None、机械作业额度None；杀虫/杀菌施药日上限1/1。同日多趟仅一个施药日但逐趟扣药。工作液按1g/L记账，机喷杀虫8L/垄、杀菌3.8L/垄、背负杀虫3L/垄为各工具模拟参考，不是现实标签。官方原始作物参数无覆盖，既有适配仅按实际密度/40缩放TDWI，不称田间最优或黑农品种复现。土壤为模型假设；天气为固定NASA POWER公开网格，加本文件明示的人工天气事件。机器人单次最多实际覆盖8垄、内部4垄一批，步行700秒/垄，5%电/垄，充电1h；看实际covered_ridges。无人机速度5m/s、7垄一航带、全田560秒、每垄1%电，最低20%，充电30分钟。种箱30万粒、粮箱2t，播种和收获每次最多4垄、喷药最多10垄；作业、充电和等待推进时间。根区传感器→无人机粗查→机器人分点确认，不把NDVI当病因诊断；低置信度单点不足作业依据。营养及部分表层水分为代理，不能当独立5cm实测或真实缺N诊断；不例行追氮。不按日历每日小水或追满额度。收获须自然R8、水分≤18%、无雨、可通行；卸粮后必要干燥至≤13.5%并入库，核对全部垄。'
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
        soil_depth_m=0.4,
        wilting_point_vwc=0.1,
        field_capacity_vwc=0.38,
        saturation_vwc=0.5,
        infiltration_mm_day=10.0,
        initial_available_n_kg_ha=50.0,
        base_soil_n_kg_ha=50.0,
        base_fertilizer_kg=0.0,
        seed_stock=1000000,
        warehouse_fertilizer_kg=0.0,
        warehouse_pesticide_l=110.0,
        warehouse_fuel_l=1000.0,
        tractor_fuel_l=100.0,
        irrigation_quota_mm=60.0,
        active_ingredient_cap_kg=0.11,
        max_machine_passes=None,
        management_regime='conventional',
        max_insecticide_applications=1,
        max_fungicide_applications=1,
        max_mechanical_weed_ridges=None,
        external_biotic_coupling=True,
        grain_moisture_mode='soybean_equilibrium',
        planting_density_plants_m2=45.0,
        required_field_preparation_ops=('level', 'form_ridges'),
    )

    def init_and_populate_apps(self):
        super().init_and_populate_apps()
        farm = self.get_typed_app(FarmWorldApp)
        self.apps.append(DroneApp(farm, self.get_typed_app(WeatherApp), name='SurveyDrone',
            speed_ms=5.0, effective_ridges_per_pass=7, takeoff_overhead_s=30,
            min_battery_pct=20.0, battery_pct_per_ridge=1.0))

    def build_events_flow(self):
        # 世界自身事件，与Agent/oracle采取的步骤无关。一次注入不每日覆盖药后下降。
        install_scenario_events(self, [
            WeatherWindowEvent(event_id='flowering_wet_spell', farm_id='farm', start=date(2019, 7, 1), end=date(2019, 7, 5), rain_mm=6.0, wind_ms=None),
            PressureEvent(event_id='midseason_disease', farm_id='farm', ridge_start=20, ridge_end=35, start=date(2019, 7, 1), end=date(2019, 7, 2), kind='disease', value=0.6, mode='set', repeat='once'),
            WeatherWindowEvent(event_id='fungicide_window', farm_id='farm', start=date(2019, 7, 6), end=date(2019, 7, 9), rain_mm=0.0, wind_ms=2.0),
            WeatherWindowEvent(event_id='late_wet_soil_spell', farm_id='farm', start=date(2019, 8, 2), end=date(2019, 8, 7), rain_mm=30.0, wind_ms=None),
            PressureEvent(event_id='later_insect', farm_id='farm', ridge_start=40, ridge_end=55, start=date(2019, 8, 5), end=date(2019, 8, 6), kind='insect', value=0.65, mode='set', repeat='once'),
            WeatherWindowEvent(event_id='manual_spray_window', farm_id='farm', start=date(2019, 8, 7), end=date(2019, 8, 10), rain_mm=0.0, wind_ms=2.0),
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
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=300000).oracle()
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
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=265320).oracle()
                .with_id('00017_2019-04-28_批量装种_20').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=20, end_ridge=23, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00018_2019-04-28_同轮播种_20').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=24, end_ridge=27, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00019_2019-04-28_同轮播种_24').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=28, end_ridge=31, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00020_2019-04-28_同轮播种_28').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=32, end_ridge=35, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00021_2019-04-28_同轮播种_32').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=36, end_ridge=39, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00022_2019-04-28_同轮播种_36').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=265320).oracle()
                .with_id('00023_2019-04-28_批量装种_40').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=40, end_ridge=43, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00024_2019-04-28_同轮播种_40').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=44, end_ridge=47, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00025_2019-04-28_同轮播种_44').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=48, end_ridge=51, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00026_2019-04-28_同轮播种_48').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=52, end_ridge=55, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00027_2019-04-28_同轮播种_52').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=56, end_ridge=59, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00028_2019-04-28_同轮播种_56').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=18384).oracle()
                .with_id('00029_2019-04-28_批量装种_60').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=60, end_ridge=63, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00030_2019-04-28_同轮播种_60').depends_on(previous, delay_seconds=222))

            # 2019-05-23：等待出苗
            previous = (system.advance_time(seconds=2143751).oracle()
                .with_id('00031_2019-05-23_等待出苗').depends_on(previous))
            previous = (robot.check_status().oracle()
                .with_id('00032_2019-05-23_出苗前电量').depends_on(previous))
            previous = (robot.inspect_emergence(start_ridge=0, end_ridge=3).oracle()
                .with_id('00033_2019-05-23_仅0至3垄出苗样本').depends_on(previous, delay_seconds=2800))
            previous = (robot.charge().oracle()
                .with_id('00034_2019-05-23_下轮检查前充电').depends_on(previous))
            previous = (system.advance_time(hours=1).oracle()
                .with_id('00035_2019-05-23_等待下轮检查前充电').depends_on(previous))

            # 2019-07-06：中期病害诊断
            previous = (system.advance_time(seconds=3795200).oracle()
                .with_id('00036_2019-07-06_中期病害诊断').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00037_2019-07-06_中期病害根水').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00038_2019-07-06_中期病害冠层').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00039_2019-07-06_中期病害飞行天气').depends_on(previous))
            previous = (drone.check_status().oracle()
                .with_id('00040_2019-07-06_中期病害无人机电量').depends_on(previous))
            previous = (drone.fly_survey(start_ridge=0, end_ridge=63).oracle()
                .with_id('00041_2019-07-06_中期病害全田粗查非确诊').depends_on(previous, delay_seconds=560))
            previous = (robot.check_status().oracle()
                .with_id('00042_2019-07-06_中期病害机器人电量').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=18, end_ridge=25).oracle()
                .with_id('00043_2019-07-06_病区与边界检查_18_25').depends_on(previous, delay_seconds=5600))
            previous = (robot.inspect_crop_health(start_ridge=26, end_ridge=33).oracle()
                .with_id('00044_2019-07-06_病区与边界检查_26_33').depends_on(previous, delay_seconds=5600))
            previous = (robot.charge().oracle()
                .with_id('00045_2019-07-06_补齐检查前充电').depends_on(previous))
            previous = (system.advance_time(hours=1).oracle()
                .with_id('00046_2019-07-06_等待补齐检查前充电').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=34, end_ridge=41).oracle()
                .with_id('00047_2019-07-06_病区与边界检查_34_41').depends_on(previous, delay_seconds=5600))
            previous = (robot.charge().oracle()
                .with_id('00048_2019-07-06_本轮检查后充电').depends_on(previous))
            previous = (drone.charge().oracle()
                .with_id('00049_2019-07-06_无人机充电').depends_on(previous))
            previous = (system.advance_time(hours=1).oracle()
                .with_id('00050_2019-07-06_等待本轮检查后充电').depends_on(previous))

            # 2019-07-07：只病区60点8升杀菌窗口
            previous = (system.advance_time(seconds=61840).oracle()
                .with_id('00051_2019-07-07_只病区60点8升杀菌窗口').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00052_2019-07-07_只病区60点8升杀菌天气').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00053_2019-07-07_只病区60点8升杀菌土壤通行性').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00054_2019-07-07_只病区60点8升杀菌资源').depends_on(previous))
            previous = (tractor.attach_implement(implement='sprayer').oracle()
                .with_id('00055_2019-07-07_只病区60点8升杀菌机具').depends_on(previous))
            previous = (tractor.load_fungicide(liters=60.8).oracle()
                .with_id('00056_2019-07-07_只病区60点8升杀菌装药').depends_on(previous))
            previous = (tractor.apply_fungicide(start_ridge=20, end_ridge=29, liters_per_ridge=3.8).oracle()
                .with_id('00057_2019-07-07_只病区60点8升杀菌_20').depends_on(previous, delay_seconds=190))
            previous = (tractor.apply_fungicide(start_ridge=30, end_ridge=35, liters_per_ridge=3.8).oracle()
                .with_id('00058_2019-07-07_只病区60点8升杀菌_30').depends_on(previous, delay_seconds=190))
            previous = (tractor.detach_implement().oracle()
                .with_id('00059_2019-07-07_只病区60点8升杀菌卸机具').depends_on(previous))

            # 2019-07-20：关键期根水检查
            previous = (system.advance_time(seconds=1122820).oracle()
                .with_id('00060_2019-07-20_关键期根水检查').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00061_2019-07-20_公开阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00062_2019-07-20_根区亏缺').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00063_2019-07-20_近期降雨').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=6.0).oracle()
                .with_id('00064_2019-07-20_正常一轮补水').depends_on(previous, delay_seconds=21900))

            # 2019-08-07：后期停雨但湿土虫情
            previous = (system.advance_time(seconds=1533300).oracle()
                .with_id('00065_2019-08-07_后期停雨但湿土虫情').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00066_2019-08-07_后期虫情根水').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00067_2019-08-07_后期虫情冠层').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00068_2019-08-07_后期虫情飞行天气').depends_on(previous))
            previous = (drone.check_status().oracle()
                .with_id('00069_2019-08-07_后期虫情无人机电量').depends_on(previous))
            previous = (drone.fly_survey(start_ridge=0, end_ridge=63).oracle()
                .with_id('00070_2019-08-07_后期虫情全田粗查非确诊').depends_on(previous, delay_seconds=560))
            previous = (robot.check_status().oracle()
                .with_id('00071_2019-08-07_后期虫情机器人电量').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=38, end_ridge=45).oracle()
                .with_id('00072_2019-08-07_虫区及边界检查_38_45').depends_on(previous, delay_seconds=5600))
            previous = (robot.inspect_crop_health(start_ridge=46, end_ridge=53).oracle()
                .with_id('00073_2019-08-07_虫区及边界检查_46_53').depends_on(previous, delay_seconds=5600))
            previous = (robot.charge().oracle()
                .with_id('00074_2019-08-07_补齐检查前充电').depends_on(previous))
            previous = (system.advance_time(hours=1).oracle()
                .with_id('00075_2019-08-07_等待补齐检查前充电').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=54, end_ridge=61).oracle()
                .with_id('00076_2019-08-07_虫区及边界检查_54_61').depends_on(previous, delay_seconds=5600))
            previous = (robot.charge().oracle()
                .with_id('00077_2019-08-07_本轮检查后充电').depends_on(previous))
            previous = (drone.charge().oracle()
                .with_id('00078_2019-08-07_无人机充电').depends_on(previous))
            previous = (system.advance_time(hours=1).oracle()
                .with_id('00079_2019-08-07_等待本轮检查后充电').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00080_2019-08-07_人工前土壤湿度').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00081_2019-08-07_人工前雨风条件').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00082_2019-08-07_人工前共享余额').depends_on(previous))
            previous = (field_ops.apply_pesticide_manual(ridge_id=40, liters_per_ridge=3.0, advance_time=True, ridge_count=2).oracle()
                .with_id('00083_2019-08-07_湿土背负正常两垄一趟_40').depends_on(previous, delay_seconds=700))
            previous = (field_ops.apply_pesticide_manual(ridge_id=42, liters_per_ridge=3.0, advance_time=True, ridge_count=2).oracle()
                .with_id('00084_2019-08-07_湿土背负正常两垄一趟_42').depends_on(previous, delay_seconds=700))
            previous = (field_ops.apply_pesticide_manual(ridge_id=44, liters_per_ridge=3.0, advance_time=True, ridge_count=2).oracle()
                .with_id('00085_2019-08-07_湿土背负正常两垄一趟_44').depends_on(previous, delay_seconds=700))
            previous = (field_ops.apply_pesticide_manual(ridge_id=46, liters_per_ridge=3.0, advance_time=True, ridge_count=2).oracle()
                .with_id('00086_2019-08-07_湿土背负正常两垄一趟_46').depends_on(previous, delay_seconds=700))
            previous = (field_ops.apply_pesticide_manual(ridge_id=48, liters_per_ridge=3.0, advance_time=True, ridge_count=2).oracle()
                .with_id('00087_2019-08-07_湿土背负正常两垄一趟_48').depends_on(previous, delay_seconds=700))
            previous = (field_ops.apply_pesticide_manual(ridge_id=50, liters_per_ridge=3.0, advance_time=True, ridge_count=2).oracle()
                .with_id('00088_2019-08-07_湿土背负正常两垄一趟_50').depends_on(previous, delay_seconds=700))
            previous = (field_ops.apply_pesticide_manual(ridge_id=52, liters_per_ridge=3.0, advance_time=True, ridge_count=2).oracle()
                .with_id('00089_2019-08-07_湿土背负正常两垄一趟_52').depends_on(previous, delay_seconds=700))
            previous = (field_ops.apply_pesticide_manual(ridge_id=54, liters_per_ridge=3.0, advance_time=True, ridge_count=2).oracle()
                .with_id('00090_2019-08-07_湿土背负正常两垄一趟_54').depends_on(previous, delay_seconds=700))

            # 2019-08-08：雨后根区充足不再例行灌水
            previous = (system.advance_time(seconds=56240).oracle()
                .with_id('00091_2019-08-08_雨后根区充足不再例行灌水').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00092_2019-08-08_R5根水充足').depends_on(previous))

            # 2019-08-13：后期药后复核
            previous = (system.advance_time(seconds=432000).oracle()
                .with_id('00093_2019-08-13_后期药后复核').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=40, end_ridge=47).oracle()
                .with_id('00094_2019-08-13_虫区复查样本').depends_on(previous, delay_seconds=5600))

            # 2019-09-20：成熟与收获窗口
            previous = (system.advance_time(seconds=3277600).oracle()
                .with_id('00095_2019-09-20_成熟与收获窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00096_2019-09-20_成熟与粮水').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00097_2019-09-20_收前土壤').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00098_2019-09-20_收前天气').depends_on(previous))
            previous = (tractor.attach_implement(implement='harvester').oracle()
                .with_id('00099_2019-09-20_安装收割机').depends_on(previous))
            previous = (tractor.harvest(start_ridge=0, end_ridge=3).oracle()
                .with_id('00100_2019-09-20_同轮收割_0').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=4, end_ridge=7).oracle()
                .with_id('00101_2019-09-20_同轮收割_4').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00102_2019-09-20_合批卸粮_0').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00103_2019-09-20_必要干燥_0').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00104_2019-09-20_安全入库_0').depends_on(previous))
            previous = (tractor.harvest(start_ridge=8, end_ridge=11).oracle()
                .with_id('00105_2019-09-20_同轮收割_8').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=12, end_ridge=15).oracle()
                .with_id('00106_2019-09-20_同轮收割_12').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00107_2019-09-20_合批卸粮_8').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00108_2019-09-20_必要干燥_8').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00109_2019-09-20_安全入库_8').depends_on(previous))
            previous = (tractor.harvest(start_ridge=16, end_ridge=19).oracle()
                .with_id('00110_2019-09-20_同轮收割_16').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=20, end_ridge=23).oracle()
                .with_id('00111_2019-09-20_同轮收割_20').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00112_2019-09-20_合批卸粮_16').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00113_2019-09-20_必要干燥_16').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00114_2019-09-20_安全入库_16').depends_on(previous))
            previous = (tractor.harvest(start_ridge=24, end_ridge=27).oracle()
                .with_id('00115_2019-09-20_同轮收割_24').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=28, end_ridge=31).oracle()
                .with_id('00116_2019-09-20_同轮收割_28').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00117_2019-09-20_合批卸粮_24').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00118_2019-09-20_必要干燥_24').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00119_2019-09-20_安全入库_24').depends_on(previous))
            previous = (tractor.harvest(start_ridge=32, end_ridge=35).oracle()
                .with_id('00120_2019-09-20_同轮收割_32').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=36, end_ridge=39).oracle()
                .with_id('00121_2019-09-20_同轮收割_36').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00122_2019-09-20_合批卸粮_32').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00123_2019-09-20_必要干燥_32').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00124_2019-09-20_安全入库_32').depends_on(previous))
            previous = (tractor.harvest(start_ridge=40, end_ridge=43).oracle()
                .with_id('00125_2019-09-20_同轮收割_40').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=44, end_ridge=47).oracle()
                .with_id('00126_2019-09-20_同轮收割_44').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00127_2019-09-20_合批卸粮_40').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00128_2019-09-20_必要干燥_40').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00129_2019-09-20_安全入库_40').depends_on(previous))
            previous = (tractor.harvest(start_ridge=48, end_ridge=51).oracle()
                .with_id('00130_2019-09-20_同轮收割_48').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=52, end_ridge=55).oracle()
                .with_id('00131_2019-09-20_同轮收割_52').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00132_2019-09-20_合批卸粮_48').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00133_2019-09-20_必要干燥_48').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00134_2019-09-20_安全入库_48').depends_on(previous))
            previous = (tractor.harvest(start_ridge=56, end_ridge=59).oracle()
                .with_id('00135_2019-09-20_同轮收割_56').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=60, end_ridge=63).oracle()
                .with_id('00136_2019-09-20_同轮收割_60').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00137_2019-09-20_合批卸粮_56').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00138_2019-09-20_必要干燥_56').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00139_2019-09-20_安全入库_56').depends_on(previous))
            previous = (tractor.detach_implement().oracle()
                .with_id('00140_2019-09-20_收后卸机具').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00141_2019-09-20_全季预算与交付').depends_on(previous))

        for event in captured:
            event.record_runtime_timing = True
        self.events = list(captured)
        return self.events
