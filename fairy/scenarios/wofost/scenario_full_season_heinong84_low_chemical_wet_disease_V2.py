"""02｜湿季病害与低化学投入：独立完整的 WOFOST 全季场景。

考点是先确认局部病害，再把有限药量用于病区；不是预防性全田低剂量喷药。
历史 Heinong84 名称仅用于旧文件身份；本场使用官方地区参数组 Soybean_901。
官方原始78项参数无覆盖；既有密度适配按实际45/40缩放TDWI，不称田间最优。
NASA POWER Lille 2019 固定天气为底本；本文件明确声明15日人工雨期与雨后风雨窗。
病害是FAIRY外接同化胁迫，非WOFOST原生病原模型；压力只注入一次，不每日set。
每个工具调用、依赖、充电、等待和真实作业耗时直接写于本文件。
6轮田间农事与132次工具调用分开计数；3趟杀菌为同一施药日，16趟收割为同一轮。
dry_grain仍为即时工具抽象，未增加公共引擎或物理机制。
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

SCENARIO_ID = 'scenario_full_season_heinong84_low_chemical_wet_disease_V2'
LEGACY_SCENARIO_ID = 'scenario_full_season_heinong84_low_chemical_wet_disease'
CALIBRATION_STATUS = 'calibrated'
FARMING_PLAN = (
    '4月28日：土壤、天气、库存、机具检查后整地、起垄，全田一垄两行播种；不例行施氮。',
    '5月23日：实际出苗后抽查0–3垄；5月28日冠层及0–3垄苗情、杂草样本，均不称全田逐垄检查。',
    '6月28日：花期连雨下核对阶段、根区水分、冠层和预报；雨天不飞无人机、不施药。',
    '7月4日：根水及冠层传感器→无雨风速/电量核对→全田无人机粗查；NDVI异常仅作定位线索。',
    '7月4日：机器人18–25、26–33垄检查后充满电，再查34–41、42–45；实际覆盖18–45，含22–43病区及两侧参考。',
    '7月4日：多点地面病害证据且虫害证据不足；确认可通行及药量后只对22–43垄3.8L/垄杀菌，83.6L，分10+10+2垄三趟同日一轮。',
    '7月8日：复查22–25及40–43垄和库存；二元阳性可能残留，不把阳性直接解释成药效失败或无依据追加用药。',
    '7月20日：R3根区仍湿润，近期少雨也不按旧日历灌溉；保留水额。',
    '8月8日：R5根层VWC约0.19–0.21且近期降雨仅约5.7mm，一轮全田30mm，余30mm不追满。',
    '9月20日：全田R8、水分≤18%、无雨、土壤可通行；16趟全田收割，8批卸粮、必要干燥至13%并安全入库。',
)
# 64×268×1.1=18867.2m²=1.88672ha；一垄两行。
# 45株/m² => 株距200/(45×1.1)=4.040404...cm，13266粒/垄，849024粒/全田。
# 22×3.8=83.6L，1g/L的现有记账为0.0836kg；总额0.084kg，剩余0.4L不追用。
# 六轮田间农事：整地1、起垄1、播种1、杀菌1、灌溉1、收获1；检查、机趟及收储批次另计。

@register_scenario(SCENARIO_ID)
class ScenarioFullSeasonHeinong84LowChemicalWetDisease_V2(WofostFarmScenario):
    DESCRIPTION = '湿季病害与低化学投入：先确认病区，有限药量定向杀菌，完成全季安全收储。'
    DETAILED_BRIEFING = (
        '你负责法国Lille的一块64垄大豆田，农场ID为farm。官方种子SOYBEAN_901为地区参数组，历史文件名不代表黑农84试验复现。'
        '每垄268×1.1m，一垄两行，总面积1.88672ha；目标45株/m²，工具株距4.040404cm、播深4cm，合计849024粒。'
        '初始VWC0.26、土温12°C、土层1.2m，萎蔫点0.10/持水量0.30/饱和0.45，入渗上限50mm/日；初始有效氮及土壤储备氮模型设定各50kgN/ha。'
        '土壤为明确的模拟假设；官方作物参数无覆盖，现有适配仅按实际45/40缩放TDWI，不称官方推荐或田间最优密度。\n\n'
        '库存100万粒种子、肥料0kg、共有化学工作液84L、仓库燃油1000L，拖拉机初始100L。固定灌溉设施5mm/h，全季毛水额度60mm，按全田等效面积记账；无需为了用满额度灌水。'
        'low_chemical管理最多3个杀菌施药日，活性成分总额0.084kg；现有工具按工作液1g/L记账，杀菌模拟参考剂量3.8L/垄，不是现实药剂标签。'
        '按参考剂量全田需243.2L，库存仅够局部一轮。确认类别后load_fungicide并apply_fungicide，不能把有限药量平均摊全田，也不能用杀虫剂替代杀菌剂。'
        '同日分趟计一个施药日，各趟实际扣药；剩余少量药液不足一轮时不能稀释成无依据的追加处理。\n\n'
        '湿期可能出现病害风险，先用根区水分与冠层传感器检查，再在可飞天气用无人机粗查异常范围，最后机器人确认病害、虫害及边界。'
        'NDVI偏低不能直接确诊；范围检查的二元病害检测有假阳性/假阴性，要综合多个样本的disease_present与disease_confidence、周围参考及作物阶段，低置信度单点不能决定施药。'
        '雨天不飞不喷；停止下雨也要复核土壤可通行和风速<6m/s。施药后复查，残留阳性并不直接量化病压或证明药效失败。'
        '病害耦合属于FAIRY的外接胁迫，非原生WOFOST病原或田间标定药效。\n\n'
        '机器人单次范围任务最多实际覆盖8垄，内部4垄一批观测；本场可以分次补齐异常区并比较两侧参考，必须看covered_ridges，不能把一次大范围请求称全部检查。'
        '步行每垄700秒、每垄耗电5%，检查16垄后需要充电；充满需1小时。SurveyDrone速度5m/s、7垄一航带、全田560秒，100%电量降至36%，最低20%，充电30分钟。'
        '拖拉机种箱30万粒、粮箱2吨，播种和收割每次最多4垄，喷药每趟最多10垄；操作、等待和充电都推进时间，跨日需重查条件。'
        '成熟R8、籽粒含水率不高于18%、无雨且地面可通行时收割，分批卸粮，必要干燥至不超过13.5%后入库并核对全部64垄。'
        '原生TWSO为干物质，收储按13%商品水分另记；营养及部分表层读数为代理，不当作独立5cm实测或真实缺氮确诊。'
    )
    WORLD = FarmDefinition(
        reference_id='lille', seed_type='SOYBEAN_901', timezone_name='Europe/Paris',
        sowing_date=date(2019, 4, 28), end_date=date(2019, 11, 15), farm_id='farm',
        num_ridges=64, field_length_m=268.0, ridge_width_m=1.1,
        initial_vwc=0.26, initial_soil_temperature_c=12.0, soil_depth_m=1.2,
        wilting_point_vwc=0.10, field_capacity_vwc=0.30, saturation_vwc=0.45,
        infiltration_mm_day=50.0, initial_available_n_kg_ha=50.0, base_soil_n_kg_ha=50.0,
        base_fertilizer_kg=0.0, seed_stock=1000000, warehouse_fertilizer_kg=0.0,
        warehouse_pesticide_l=84.0, warehouse_fuel_l=1000.0, tractor_fuel_l=100.0,
        irrigation_quota_mm=60.0, active_ingredient_cap_kg=0.084,
        max_machine_passes=None, management_regime='low_chemical',
        max_insecticide_applications=None, max_fungicide_applications=3,
        max_mechanical_weed_ridges=None, external_biotic_coupling=True,
        grain_moisture_mode='soybean_equilibrium', planting_density_plants_m2=45.0,
        required_field_preparation_ops=('level', 'form_ridges'),
    )

    def init_and_populate_apps(self):
        super().init_and_populate_apps()
        self.apps.append(DroneApp(
            self.get_typed_app(FarmWorldApp), self.get_typed_app(WeatherApp),
            name='SurveyDrone', description='全田冠层粗查定位，地面分段确认病区与边界。',
            speed_ms=5.0, effective_ridges_per_pass=7, takeoff_overhead_s=30,
            min_battery_pct=20.0, battery_pct_per_ridge=1.0,
        ))

    def build_events_flow(self):
        # 世界自身的雨期与局部病害，所有策略共享；once/set不覆盖后续处理下降。
        # 雨风窗口是人工天气设定；其余温度、湿度、辐射保留公开固定数据。
        install_scenario_events(self, [
            WeatherWindowEvent('wet_june_spell', 'farm',
                date(2019, 6, 18), date(2019, 7, 3), rain_mm=8.0),
            PressureEvent('localized_wet_season_disease', 'farm', 22, 43,
                date(2019, 6, 20), date(2019, 6, 21), 'disease', 0.65, 'set', 'once'),
            WeatherWindowEvent('post_rain_scout_and_spray_window', 'farm',
                date(2019, 7, 4), date(2019, 7, 6), rain_mm=0.0, wind_ms=2.0),
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

            # 2019-04-28：播前核对→整地→起垄→全田一垄两行播种；分批装种不算多轮播种。
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00001_2019-04-28_播前土壤温湿通行性').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00002_2019-04-28_播前天气').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00003_2019-04-28_播前种肥药油库存').depends_on(previous))
            previous = (tractor.get_status().oracle()
                .with_id('00004_2019-04-28_播前机具容量与燃油').depends_on(previous))
            previous = (tractor.attach_implement(implement='grader').oracle()
                .with_id('00005_2019-04-28_挂平地机').depends_on(previous))
            previous = (tractor.level().oracle()
                .with_id('00006_2019-04-28_全田整地').depends_on(previous, delay_seconds=8321))
            previous = (tractor.detach_implement().oracle()
                .with_id('00007_2019-04-28_卸平地机').depends_on(previous))
            previous = (tractor.attach_implement(implement='furrower').oracle()
                .with_id('00008_2019-04-28_挂起垄机').depends_on(previous))
            previous = (tractor.form_ridges(ridge_width_m=1.1).oracle()
                .with_id('00009_2019-04-28_一米一宽全田起垄').depends_on(previous, delay_seconds=4376))
            previous = (tractor.detach_implement().oracle()
                .with_id('00010_2019-04-28_卸起垄机').depends_on(previous))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=300000).oracle()
                .with_id('00011_2019-04-28_批量装种_0').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=0, end_ridge=3, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00012_2019-04-28_同一轮播种_0').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=4, end_ridge=7, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00013_2019-04-28_同一轮播种_4').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=8, end_ridge=11, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00014_2019-04-28_同一轮播种_8').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=12, end_ridge=15, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00015_2019-04-28_同一轮播种_12').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=16, end_ridge=19, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00016_2019-04-28_同一轮播种_16').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=265320).oracle()
                .with_id('00017_2019-04-28_批量装种_20').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=20, end_ridge=23, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00018_2019-04-28_同一轮播种_20').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=24, end_ridge=27, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00019_2019-04-28_同一轮播种_24').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=28, end_ridge=31, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00020_2019-04-28_同一轮播种_28').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=32, end_ridge=35, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00021_2019-04-28_同一轮播种_32').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=36, end_ridge=39, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00022_2019-04-28_同一轮播种_36').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=265320).oracle()
                .with_id('00023_2019-04-28_批量装种_40').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=40, end_ridge=43, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00024_2019-04-28_同一轮播种_40').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=44, end_ridge=47, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00025_2019-04-28_同一轮播种_44').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=48, end_ridge=51, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00026_2019-04-28_同一轮播种_48').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=52, end_ridge=55, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00027_2019-04-28_同一轮播种_52').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=56, end_ridge=59, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00028_2019-04-28_同一轮播种_56').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=18384).oracle()
                .with_id('00029_2019-04-28_批量装种_60').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=60, end_ridge=63, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00030_2019-04-28_同一轮播种_60').depends_on(previous, delay_seconds=222))

            # 2019-05-23：已过实际出苗日，检查仅0–3垄代表样本。
            previous = (system.advance_time(seconds=2143751).oracle()
                .with_id('00031_2019-05-23_等实际出苗后检查').depends_on(previous))
            previous = (robot.check_status().oracle()
                .with_id('00032_2019-05-23_出苗样本前电量').depends_on(previous))
            previous = (robot.inspect_emergence(start_ridge=0, end_ridge=3).oracle()
                .with_id('00033_2019-05-23_出苗样本仅0至3垄').depends_on(previous, delay_seconds=2800))

            # 2019-05-28：冠层与苗情杂草样本复核，充电为下轮诊断准备。
            previous = (system.advance_time(seconds=429200).oracle()
                .with_id('00034_2019-05-28_等苗期冠层杂草复核').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00035_2019-05-28_苗期冠层').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=0, end_ridge=3).oracle()
                .with_id('00036_2019-05-28_杂草样本仅0至3垄').depends_on(previous, delay_seconds=2800))
            previous = (robot.charge().oracle()
                .with_id('00037_2019-05-28_下轮检查前充电').depends_on(previous))
            previous = (system.advance_time(hours=1).oracle()
                .with_id('00038_2019-05-28_等机器人充电一小时').depends_on(previous))

            # 2019-06-28：连续降雨期间检查阶段/根水/冠层/预报，雨天不飞不喷，不例行追氮。
            previous = (system.advance_time(seconds=2672000).oracle()
                .with_id('00039_2019-06-28_等湿期花期巡查').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00040_2019-06-28_湿期当前降雨').depends_on(previous))
            previous = (weather.get_forecast(days=7).oracle()
                .with_id('00041_2019-06-28_湿期短期预报').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00042_2019-06-28_花期生育状态').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00043_2019-06-28_花期根水非仅看表土').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00044_2019-06-28_湿期冠层初筛').depends_on(previous))

            # 2019-07-04：传感器→全田无人机粗查→分段地面确认病区与两侧参考；16垄后实际充电，再补齐覆盖；核对土壤/雨风后定向杀菌。
            previous = (system.advance_time(seconds=518400).oracle()
                .with_id('00045_2019-07-04_等雨后可飞可施药窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00046_2019-07-04_雨后阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00047_2019-07-04_雨后根区水分排除旱情').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00048_2019-07-04_雨后全田冠层初筛').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00049_2019-07-04_飞行前无雨风速').depends_on(previous))
            previous = (drone.check_status().oracle()
                .with_id('00050_2019-07-04_飞行前电量覆盖能力').depends_on(previous))
            previous = (drone.fly_survey(start_ridge=0, end_ridge=63).oracle()
                .with_id('00051_2019-07-04_无人机全田粗查非直接确诊').depends_on(previous, delay_seconds=560))
            previous = (robot.check_status().oracle()
                .with_id('00052_2019-07-04_地面覆盖前确认机器人电量').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=18, end_ridge=25).oracle()
                .with_id('00053_2019-07-04_检查18至25含病区左侧参考').depends_on(previous, delay_seconds=5600))
            previous = (robot.inspect_crop_health(start_ridge=26, end_ridge=33).oracle()
                .with_id('00054_2019-07-04_检查26至33补齐病区中段').depends_on(previous, delay_seconds=5600))
            previous = (robot.charge().oracle()
                .with_id('00055_2019-07-04_检查16垄后充电').depends_on(previous))
            previous = (system.advance_time(hours=1).oracle()
                .with_id('00056_2019-07-04_等补齐病区前充满一小时').depends_on(previous))
            previous = (robot.check_status().oracle()
                .with_id('00057_2019-07-04_继续检查前核对电量').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=34, end_ridge=41).oracle()
                .with_id('00058_2019-07-04_检查34至41病区后段').depends_on(previous, delay_seconds=5600))
            previous = (robot.inspect_crop_health(start_ridge=42, end_ridge=45).oracle()
                .with_id('00059_2019-07-04_检查42至45含病区右侧参考').depends_on(previous, delay_seconds=2800))
            previous = (weather.get_current_weather().oracle()
                .with_id('00060_2019-07-04_药前当天雨风窗口').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00061_2019-07-04_药前复查土壤可通行').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00062_2019-07-04_药前确认额度与药剂库存').depends_on(previous))
            previous = (tractor.attach_implement(implement='sprayer').oracle()
                .with_id('00063_2019-07-04_挂喷雾机').depends_on(previous))
            previous = (tractor.load_fungicide(liters=83.6).oracle()
                .with_id('00064_2019-07-04_装杀菌工作液83点6升').depends_on(previous))
            previous = (tractor.apply_fungicide(start_ridge=22, end_ridge=31, liters_per_ridge=3.8).oracle()
                .with_id('00065_2019-07-04_定向杀菌_22').depends_on(previous, delay_seconds=190))
            previous = (tractor.apply_fungicide(start_ridge=32, end_ridge=41, liters_per_ridge=3.8).oracle()
                .with_id('00066_2019-07-04_定向杀菌_32').depends_on(previous, delay_seconds=190))
            previous = (tractor.apply_fungicide(start_ridge=42, end_ridge=43, liters_per_ridge=3.8).oracle()
                .with_id('00067_2019-07-04_定向杀菌_42').depends_on(previous, delay_seconds=190))
            previous = (tractor.detach_implement().oracle()
                .with_id('00068_2019-07-04_施药后卸喷雾机').depends_on(previous))
            previous = (robot.charge().oracle()
                .with_id('00069_2019-07-04_复查前机器人充电').depends_on(previous))
            previous = (drone.charge().oracle()
                .with_id('00070_2019-07-04_无人机用后充电').depends_on(previous))
            previous = (system.advance_time(hours=1).oracle()
                .with_id('00071_2019-07-04_等复查设备充电完成').depends_on(previous))

            # 2019-07-08：药后复查与余额核对；二元病害阳性不自动构成再次施药依据。
            previous = (system.advance_time(seconds=317670).oracle()
                .with_id('00072_2019-07-08_等药后复查').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('00073_2019-07-08_药后冠层仅作恢复线索').depends_on(previous))
            previous = (robot.check_status().oracle()
                .with_id('00074_2019-07-08_药后检查前电量').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=22, end_ridge=25).oracle()
                .with_id('00075_2019-07-08_药后22至25样本').depends_on(previous, delay_seconds=2800))
            previous = (robot.inspect_crop_health(start_ridge=40, end_ridge=43).oracle()
                .with_id('00076_2019-07-08_药后40至43样本').depends_on(previous, delay_seconds=2800))
            previous = (farm.get_inventory().oracle()
                .with_id('00077_2019-07-08_药后库存与实际额度').depends_on(previous))

            # 2019-07-20：R3根区约0.24仍充足，不因少雨或旧日历而灌水。
            previous = (system.advance_time(seconds=1031200).oracle()
                .with_id('00078_2019-07-20_等R3根区与降雨检查').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00079_2019-07-20_R3公开生育阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00080_2019-07-20_R3根区水分').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00081_2019-07-20_R3近期降雨').depends_on(previous))

            # 2019-08-08：R5根区约0.19–0.21，预报少量雨；一轮全田30mm，余30mm不用。
            previous = (system.advance_time(seconds=1641600).oracle()
                .with_id('00082_2019-08-08_等R5补水复核').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00083_2019-08-08_R5公开生育阶段').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('00084_2019-08-08_R5根区水分').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('00085_2019-08-08_R5近期降雨').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=6.0).oracle()
                .with_id('00086_2019-08-08_R5全田一轮30毫米').depends_on(previous, delay_seconds=21900))

            # 2019-09-20：全田成熟/水分/无雨/通行性核对，一轮全田收获，按8垄批次卸粮干燥入库。
            previous = (system.advance_time(seconds=3693300).oracle()
                .with_id('00087_2019-09-20_等自然成熟和合法收获窗口').depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('00088_2019-09-20_全田成熟及粮食水分').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('00089_2019-09-20_收前土壤通行性').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('00090_2019-09-20_收前无雨窗口').depends_on(previous))
            previous = (tractor.attach_implement(implement='harvester').oracle()
                .with_id('00091_2019-09-20_挂收割机').depends_on(previous))
            previous = (tractor.harvest(start_ridge=0, end_ridge=3).oracle()
                .with_id('00092_2019-09-20_同一轮收获_0').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=4, end_ridge=7).oracle()
                .with_id('00093_2019-09-20_同一轮收获_4').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00094_2019-09-20_粮箱限额合批卸粮_0').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00095_2019-09-20_批次必要干燥至百分之13_0').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00096_2019-09-20_批次安全入库_0').depends_on(previous))
            previous = (tractor.harvest(start_ridge=8, end_ridge=11).oracle()
                .with_id('00097_2019-09-20_同一轮收获_8').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=12, end_ridge=15).oracle()
                .with_id('00098_2019-09-20_同一轮收获_12').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00099_2019-09-20_粮箱限额合批卸粮_8').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00100_2019-09-20_批次必要干燥至百分之13_8').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00101_2019-09-20_批次安全入库_8').depends_on(previous))
            previous = (tractor.harvest(start_ridge=16, end_ridge=19).oracle()
                .with_id('00102_2019-09-20_同一轮收获_16').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=20, end_ridge=23).oracle()
                .with_id('00103_2019-09-20_同一轮收获_20').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00104_2019-09-20_粮箱限额合批卸粮_16').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00105_2019-09-20_批次必要干燥至百分之13_16').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00106_2019-09-20_批次安全入库_16').depends_on(previous))
            previous = (tractor.harvest(start_ridge=24, end_ridge=27).oracle()
                .with_id('00107_2019-09-20_同一轮收获_24').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=28, end_ridge=31).oracle()
                .with_id('00108_2019-09-20_同一轮收获_28').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00109_2019-09-20_粮箱限额合批卸粮_24').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00110_2019-09-20_批次必要干燥至百分之13_24').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00111_2019-09-20_批次安全入库_24').depends_on(previous))
            previous = (tractor.harvest(start_ridge=32, end_ridge=35).oracle()
                .with_id('00112_2019-09-20_同一轮收获_32').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=36, end_ridge=39).oracle()
                .with_id('00113_2019-09-20_同一轮收获_36').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00114_2019-09-20_粮箱限额合批卸粮_32').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00115_2019-09-20_批次必要干燥至百分之13_32').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00116_2019-09-20_批次安全入库_32').depends_on(previous))
            previous = (tractor.harvest(start_ridge=40, end_ridge=43).oracle()
                .with_id('00117_2019-09-20_同一轮收获_40').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=44, end_ridge=47).oracle()
                .with_id('00118_2019-09-20_同一轮收获_44').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00119_2019-09-20_粮箱限额合批卸粮_40').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00120_2019-09-20_批次必要干燥至百分之13_40').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00121_2019-09-20_批次安全入库_40').depends_on(previous))
            previous = (tractor.harvest(start_ridge=48, end_ridge=51).oracle()
                .with_id('00122_2019-09-20_同一轮收获_48').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=52, end_ridge=55).oracle()
                .with_id('00123_2019-09-20_同一轮收获_52').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00124_2019-09-20_粮箱限额合批卸粮_48').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00125_2019-09-20_批次必要干燥至百分之13_48').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00126_2019-09-20_批次安全入库_48').depends_on(previous))
            previous = (tractor.harvest(start_ridge=56, end_ridge=59).oracle()
                .with_id('00127_2019-09-20_同一轮收获_56').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=60, end_ridge=63).oracle()
                .with_id('00128_2019-09-20_同一轮收获_60').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('00129_2019-09-20_粮箱限额合批卸粮_56').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('00130_2019-09-20_批次必要干燥至百分之13_56').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('00131_2019-09-20_批次安全入库_56').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('00132_2019-09-20_季末核对库存和全田交付').depends_on(previous))

        for event in captured:
            event.record_runtime_timing = True
        self.events = list(captured)
        return self.events
