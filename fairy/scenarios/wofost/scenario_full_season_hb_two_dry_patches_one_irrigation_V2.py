"""两个缺水斑块与一次额外灌溉的分配。

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

SCENARIO_ID = 'scenario_full_season_hb_two_dry_patches_one_irrigation_V2'
ORIGINAL_CORE = '两块干斑中按真实灌溉收益分配仅够一块的水'
FARMING_PLAN = (
    '2019-04-28：播前核对、整地起垄、全田播种SOYBEAN_901；公开A/B土壤与参考区，初始VWC.24合法；45株/m²按真实种箱与16机趟完成，无例行氮肥。',
    '2019-05-13：出苗抽查0至3垄；例行4垄出苗确认不是异常粗定位，无需硬加航测；实际出苗后无缺苗依据不补播，不宣称地面覆盖全田。',
    '2019-05-28：冠层检查与苗期杂草样本；当日原天气4.23mm雨且无主要异常，不硬加不可飞航测；例行4垄草情样本无可信主要草害时不例行施药或中耕。',
    '2019-06-28：花期公开长势和根水复核；当时尚不需要耗水或例行追氮，不把幼苗营养代理当花期缺肥诊断。',
    '2019-07-20：全田一次正常30mm轮灌；两片和普通区域都有关键阶段供水需求，保留共同正常供水，不把所有水藏成一次额外补水。',
    '2019-08-01：传感器→可飞条件下真实全田无人机粗查→A/B各4垄地面样本→B一次30mm；总额度66，常规60后只够一块12垄正常轮灌。两区均有灌溉收益，但等面积边际籽粒干物质对照B263.29kg高于A239.60kg；A更干不自动等于回收收益最高。根探头R2含9A+2普通、R5含10B、R3为普通参考，均非整块精确读数；根水与冠层之后先核对可飞天气/无人机电量，真实全田飞行560秒并直接返回粗查产品，再进行A/B重点地面样本，不额外等待。实际公开生长代理A.353、B.383，B保存的当前生长较多；NDVI组间仅有较小差异，不能直接判病或定优先序；地面结论必须依据本次飞行后的新回执，低置信阳性保留不确定，不叫已证实误报，也不为每个零星flag增加复查。精确边际值来自离线对照，不冒充传感器预测。',
    '2019-08-08：鼓粒期全田一次正常30mm轮灌；保留全田关键供水；全季实用65.625mm，留0.375mm不灌碎尾水，两片都额外30需71.25mm超额度。',
    '2019-09-20：适收检查、16趟收割、按容量6批卸粮/必要干燥/安全入库；沿固定天气核对成熟、含水、无雨和土壤可通行；粮箱容量按湿粮保守上界，必要批次按当前即时干燥工具降至13%。',
)
MIGRATION_NOTES = (
    'Original two dry patches but onlyone extra irrigation round retained; only this one old scenario is studied.',
    'No N fertilizer: Nfix fraction.8 remains uncalibrated official crop input; no claim of a simulated nodulation system.',
    'Fullfield30+onepatch30(12of64)+fullfield30;total65.625 under66;bothpatch reference71.25 cannot fit. No daily tiny pulses/quota tail;fixed native marginal returns selectBnot severity or priority label.',
    'All real calls retained; production source must contain literal static plan.',
)
IRRIGATION_REFERENCE_MM = 71.25
IRRIGATION_SELECTION_NOTES = '常规两次全田30mm共60mm；两块各12垄都额外30mm需要71.25mm参考水量。公开额度66mm，仅支持一块正常30mm后实际65.625mm，留0.375不用。只A同样有效，B等面积边际干物质回收高约9.9%，整场差距约0.38%，不夸大成无水或全球最优。'
DENSITY_SELECTION_NOTES = '45株/m²沿用固定官方901/Lille2019已有候选的操作目标；适配器TDWI120按45/40初始化135，其余官方值保留，不声称官方田间最优密度。'

@register_scenario(SCENARIO_ID)
class ScenarioFullSeasonHBTwoDryPatchesOneIrrigation_V2(WofostFarmScenario):
    DESCRIPTION = '两个缺水斑块与一次额外灌溉的分配'
    DETAILED_BRIEFING = (
        "你负责法国里尔2019年64垄SOYBEAN_901大豆田，播种目标45株/平方米。同日同作物的地块有两种不同蓄水背景：浅土约0.8米，另一类约1.0米，普通土层约1.2米；它们的持水量与捕雨能力也不同，不预先认定最干的一片最值得补水。\n\n"
        "全季灌溉硬额度为全田等效66毫米。需要同时照顾常规阶段用水和局部异常，局部供水按面积折算，管理前后核对累计与剩余量。比较生育阶段、根区亏缺和仍能保持的植株长势，不只凭最低水分或一次冠层读数决定水往哪里分；不提前承诺两片都能额外供水。\n\n"
        "先读根水与冠层线索，天气和电量允许时用SurveyDrone实际航测粗查，再以Robot在疑区和参考位置取样。探头为覆盖区平均，航测只提供带噪声的长势与近似温度，不能直接确诊病因或预测精确增产；机器人每次最多4垄，弱阳性保留不确定，依据新证据再决定管理。例行出苗样本不必硬飞，雨天禁飞。\n\n"
        "播前整地起垄；种箱30万粒、粮箱2吨，播种和收割每次最多4垄。飞行、充电、作业和等待均耗时，跨日重查条件。成熟且水分、天气与通行性达标后收获，按容量卸粮、必要干燥并全田安全入库。"
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
        seed_stock=1000000,
        warehouse_fertilizer_kg=2600.0,
        warehouse_pesticide_l=1200.0,
        warehouse_fuel_l=1000.0,
        tractor_fuel_l=100.0,
        irrigation_quota_mm=66.0,
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
        modifiers = {}
        modifier = SoilHydraulicModifier(
            field_capacity_vwc=0.24,
            root_depth_m=0.8,
            rainfall_capture_efficiency=0.78,
            max_infiltration_mm_day=32.0,
        )
        modifiers.update({rid: modifier for rid in range(8, 20)})
        modifier = SoilHydraulicModifier(
            field_capacity_vwc=0.28,
            root_depth_m=1.0,
            rainfall_capture_efficiency=0.9,
            max_infiltration_mm_day=40.0,
        )
        modifiers.update({rid: modifier for rid in range(42, 54)})
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
            aui.send_message_to_agent('已知64垄同一SOYBEAN_901、同日播种。西A8–19土深0.8m、FC0.24、捕雨0.78、入渗32mm/day；东B42–53土深1.0m、FC0.28、捕雨0.90、入渗40mm/day；普通参考24–35及其他区土深1.2m、FC0.30、捕雨1.0、入渗50mm/day。这些为公开模型土壤假设，非实测田间校准。8月1–18为显式少雨窗口；全季水额66mm，请比较生育阶段、根区水与可回收生长状况，安排正常供水并在两片间选择额外灌溉。不要仅凭最干或单次NDVI决定，土壤探头为覆盖区均值。 异常诊断采用传感器线索→可飞天气下SurveyDrone全田/疑区粗查→Robot重点地面样本→针对管理；无人机只提供带噪声NDVI和近似冠层温度，不能直接确诊病因或预测精确反事实收益。例行出苗/雨天苗情样本无需为流程硬飞。')
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
            previous = (tractor.plant_seeds(start_ridge=0, end_ridge=3, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00012_2019-04-28_全场一次播种中的0至3垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=4, end_ridge=7, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00013_2019-04-28_全场一次播种中的4至7垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=8, end_ridge=11, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00014_2019-04-28_全场一次播种中的8至11垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=12, end_ridge=15, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00015_2019-04-28_全场一次播种中的12至15垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=16, end_ridge=19, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00016_2019-04-28_全场一次播种中的16至19垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=265320).oracle()
                .with_id('00017_2019-04-28_种箱不足下一趟时批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=20, end_ridge=23, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00018_2019-04-28_全场一次播种中的20至23垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=24, end_ridge=27, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00019_2019-04-28_全场一次播种中的24至27垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=28, end_ridge=31, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00020_2019-04-28_全场一次播种中的28至31垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=32, end_ridge=35, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00021_2019-04-28_全场一次播种中的32至35垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=36, end_ridge=39, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00022_2019-04-28_全场一次播种中的36至39垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=265320).oracle()
                .with_id('00023_2019-04-28_种箱不足下一趟时批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=40, end_ridge=43, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00024_2019-04-28_全场一次播种中的40至43垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=44, end_ridge=47, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00025_2019-04-28_全场一次播种中的44至47垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=48, end_ridge=51, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00026_2019-04-28_全场一次播种中的48至51垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=52, end_ridge=55, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00027_2019-04-28_全场一次播种中的52至55垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=56, end_ridge=59, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
                .with_id('00028_2019-04-28_全场一次播种中的56至59垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_901', count=18384).oracle()
                .with_id('00029_2019-04-28_种箱不足下一趟时批量装种').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=60, end_ridge=63, depth_cm=4.0, seed_spacing_cm=4.04040404040404).oracle()
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
                .with_id('00050_2019-08-01_两片异常粗查飞行前确认无雨及低于十二米每秒风速').depends_on(previous))
            previous = (drone.check_status().oracle()
                .with_id('00051_2019-08-01_两片粗查前确认无人机电量与覆盖能力').depends_on(previous))
            previous = (drone.fly_survey(start_ridge=0, end_ridge=63).oracle()
                .with_id('00052_2019-08-01_两片根水冠层线索后真实无人机全田粗查再机器人样本').depends_on(previous, delay_seconds=560))
            previous = (robot.check_status().oracle()
                .with_id('00053_2019-08-01_两块缺水斑块抽样前确认机器人足够电量').depends_on(previous))
            previous = (robot.inspect_crop_health(start_ridge=8, end_ridge=11).oracle()
                .with_id('00054_2019-08-01_西A区仅8至11垄样本核对主要病虫草证据').depends_on(previous, delay_seconds=2800))
            previous = (robot.inspect_crop_health(start_ridge=42, end_ridge=45).oracle()
                .with_id('00055_2019-08-01_东B区仅42至45垄样本核对主要病虫草证据').depends_on(previous, delay_seconds=2800))
            previous = (field_ops.irrigate(start=42, end=53, hours=6.0).oracle()
                .with_id('00056_2019-08-01_比较两区同面积边际产量后仅42至53垄一次30毫米').depends_on(previous, delay_seconds=21900))

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
