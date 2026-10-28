"""scenario_full_season_hb_low_nutrient_carryover_flowering_nutrition_V2: 前季低氮供给后的花期营养管理。

保留原ID、64垄几何与任务；密度和限水额度按显式候选试验调整。
WORLD和事件是完整世界定义；build_events_flow是预先写好的固定农事计划。
构建只捕获工具调用，不读回执、不运行策略、不推进物理。
日期为当地民用日历；System.advance_time是真实等待，依赖延迟仅标记工具预计耗时。
普通步骤名称中的日期是作业开始日，等待步骤为目标日；time字段记录实际完成时间。
事件区间采用[start,end)，结束注入不会自动清除田间已有病虫草压力。
实际执行仍由真实工具核验设备、库存、天气和成熟度；输入改变后须重验计划。
品种基准78参数取自官方；有效TDWI随实际密度/40缩放，尚非田间最优标定。
病虫草通过FAIRY外接PGASS总同化胁迫影响生长；不直接模拟WOFOST原生叶面积脱落。
干燥工具在当前模型中是即时零耗时处理；步骤名称保存目的与目标，不混入工具回执。
本场不声称复现原田间试验产量或证明全球最优管理。
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

CALIBRATION_STATUS = 'uncalibrated'
SCENARIO_ID = 'scenario_full_season_hb_low_nutrient_carryover_flowering_nutrition_V2'
ORIGINAL_PROFILE_NAME = 'harbin_l3_low_nutrient_flowering_seed_1516'
MIGRATION_NOTES = (
    'Offline calibration only; production exporter writes literal static graph.',
    'Target density derives from stated reference-water density sweep, not field cultivar optimality.',
    'Official YAML remains unchanged;effectiveTDWI=120*density/40*stand1; actual other77crop values retained.',
    'dry_grain is instantaneous in current App; no invented drying duration.',
    'Harvest receipts/bins are13pctmarket-mass kg; wet-mass bounds separately calculated from public moisture.',
    '密度来自15–60株/m²已测候选；原始TDWI120按实际密度/40初始化，其余77项原值不变。',
    '批量装种、同日同剂量灌水及收储已合并；所有真实作业、充电和等待仍占场景时间。',
    '当前dry_grain为即时、零耗时的干燥抽象；没有假造设备能耗或烘干时长。',
)

IRRIGATION_REFERENCE_MM = None
IRRIGATION_SELECTION_NOTES = '此场景未设置全季硬水量额度；用公开根层与降雨预报复核补水窗口。'
DENSITY_SELECTION_NOTES = '目标密度60.0株/m²；901/902/905取固定供水参考15–60候选域最高；限水903另在本场预算下比较邻域。这不是商业品种田间最优，60也不是完整合法密度域的全局最优。'

@register_scenario(SCENARIO_ID)
class ScenarioFullSeasonHBLowNutrientCarryoverFloweringNutrition_V2(WofostFarmScenario):
    DESCRIPTION = '前季低氮供给后的花期营养管理'
    DETAILED_BRIEFING = (
        "你负责法国克莱蒙费朗2019年64垄SOYBEAN_902大豆的全季营养管理，按本场60株/平方米的目标播种。前季留下的土壤供氮很低，初始有效氮和待释放氮储备均为零；仓库有2600千克肥料，库存充足不代表田间必须多施。\n\n"
        "播前核对并完成本场要求的整地、底肥和起垄；之后关注出苗、花期长势、根区水分与土壤氮读数，结合地面叶片样本判断。土壤缺氮、植株长势弱和需要追肥不是同一个结论，大豆自身供氮也需纳入考虑。本场尚未证明花期追加氮肥能提高收成，不得把低营养指数当成固定追肥指令，也不能把任务改成只做灌溉。\n\n"
        "全季未设灌水硬额度，但仍应结合根水与降雨按需供水，避免缺水干扰营养判断。需要处理时核对肥料产品、实际用量和作业范围，保留前后观察，不反复追施来追求某个读数。机器人每次最多4垄，只能报告实际样本，电量不足先完成充电。\n\n"
        "种箱30万粒、粮箱2吨，播种和收割每次最多4垄。作业与等待均耗时，跨日要重查天气。确认成熟、适收水分及通行条件后全田收获，按容量卸粮、必要干燥并安全入库，完成营养判断记录和全部粮食交付。"
    )
    WORLD = FarmDefinition(
        reference_id='clermont_ferrand',
        seed_type='SOYBEAN_902',
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
        initial_available_n_kg_ha=0.0,
        base_soil_n_kg_ha=0.0,
        base_fertilizer_kg=2.0,
        seed_stock=1200000,
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
        planting_density_plants_m2=60.0,
    )


    def build_events_flow(self):
        # Explicit disturbances belong to this world, independently of the Oracle.
        install_scenario_events(self, [
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

            # 2019-04-28 (Europe/Paris): fixed observation/work block.
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('001_2019-04-28_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('002_2019-04-28_核对播床或土壤可通行性').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('003_2019-04-28_核对当前雨风作业窗口').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('004_2019-04-28_核对仓库、季节额度与收储结果').depends_on(previous))
            previous = (tractor.get_status().oracle()
                .with_id('005_2019-04-28_核对油料、机具、种箱及粮箱余量').depends_on(previous))
            previous = (tractor.attach_implement(implement='grader').oracle()
                .with_id('006_2019-04-28_安装本作业所需机具').depends_on(previous))
            previous = (tractor.level().oracle()
                .with_id('007_2019-04-28_平整播床').depends_on(previous, delay_seconds=8321))
            previous = (tractor.detach_implement().oracle()
                .with_id('008_2019-04-28_卸下前道机具后切换作业').depends_on(previous))
            previous = (tractor.load_fertilizer(kg=2.0).oracle()
                .with_id('009_2019-04-28_批量装足本轮肥料_2公斤').depends_on(previous))
            previous = (tractor.base_fertilize(total_kg=2.0).oracle()
                .with_id('010_2019-04-28_按实际产品质量施底肥_2公斤').depends_on(previous, delay_seconds=2257))
            previous = (tractor.attach_implement(implement='furrower').oracle()
                .with_id('011_2019-04-28_安装本作业所需机具').depends_on(previous))
            previous = (tractor.form_ridges(ridge_width_m=1.1).oracle()
                .with_id('012_2019-04-28_按1.1米垄距完成起垄').depends_on(previous, delay_seconds=4376))
            previous = (tractor.detach_implement().oracle()
                .with_id('013_2019-04-28_卸下前道机具后切换作业').depends_on(previous))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_902', count=300000).oracle()
                .with_id('014_2019-04-28_按30万粒种箱容量批量装种_300000粒').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=0, end_ridge=3, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('015_2019-04-28_按本品种已测目标密度播种、每趟最多4垄_0至3垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=4, end_ridge=7, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('016_2019-04-28_按本品种已测目标密度播种、每趟最多4垄_4至7垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=8, end_ridge=11, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('017_2019-04-28_按本品种已测目标密度播种、每趟最多4垄_8至11垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=12, end_ridge=15, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('018_2019-04-28_按本品种已测目标密度播种、每趟最多4垄_12至15垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_902', count=283008).oracle()
                .with_id('019_2019-04-28_按30万粒种箱容量批量装种_283008粒').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=16, end_ridge=19, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('020_2019-04-28_按本品种已测目标密度播种、每趟最多4垄_16至19垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=20, end_ridge=23, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('021_2019-04-28_按本品种已测目标密度播种、每趟最多4垄_20至23垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=24, end_ridge=27, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('022_2019-04-28_按本品种已测目标密度播种、每趟最多4垄_24至27垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=28, end_ridge=31, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('023_2019-04-28_按本品种已测目标密度播种、每趟最多4垄_28至31垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_902', count=283008).oracle()
                .with_id('024_2019-04-28_按30万粒种箱容量批量装种_283008粒').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=32, end_ridge=35, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('025_2019-04-28_按本品种已测目标密度播种、每趟最多4垄_32至35垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=36, end_ridge=39, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('026_2019-04-28_按本品种已测目标密度播种、每趟最多4垄_36至39垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=40, end_ridge=43, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('027_2019-04-28_按本品种已测目标密度播种、每趟最多4垄_40至43垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=44, end_ridge=47, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('028_2019-04-28_按本品种已测目标密度播种、每趟最多4垄_44至47垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.load_seeds(seed_type='SOYBEAN_902', count=266016).oracle()
                .with_id('029_2019-04-28_按30万粒种箱容量批量装种_266016粒').depends_on(previous))
            previous = (tractor.plant_seeds(start_ridge=48, end_ridge=51, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('030_2019-04-28_按本品种已测目标密度播种、每趟最多4垄_48至51垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=52, end_ridge=55, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('031_2019-04-28_按本品种已测目标密度播种、每趟最多4垄_52至55垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=56, end_ridge=59, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('032_2019-04-28_按本品种已测目标密度播种、每趟最多4垄_56至59垄').depends_on(previous, delay_seconds=222))
            previous = (tractor.plant_seeds(start_ridge=60, end_ridge=63, depth_cm=4.0, seed_spacing_cm=3.0303030303030303).oracle()
                .with_id('033_2019-04-28_按本品种已测目标密度播种、每趟最多4垄_60至63垄').depends_on(previous, delay_seconds=222))

            # 2019-05-02 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-05-02T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=327094).oracle()
                .with_id("034_2019-05-02_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('035_2019-05-02_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('036_2019-05-02_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('037_2019-05-02_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=10, hours=1.6).oracle()
                .with_id('038_2019-05-02_在本轮窗口补水、保留后续生育期额度_0至10垄_8毫米每垄').depends_on(previous, delay_seconds=6060))
            previous = (field_ops.irrigate(start=33, end=43, hours=1.6).oracle()
                .with_id('039_2019-05-02_在本轮窗口补水、保留后续生育期额度_33至43垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-05-13 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-05-13T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=938280).oracle()
                .with_id("040_2019-05-13_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (robot.check_status().oracle()
                .with_id('041_2019-05-13_核对机器人电量与实际覆盖能力').depends_on(previous))
            previous = (robot.inspect_emergence(start_ridge=0, end_ridge=3).oracle()
                .with_id('042_2019-05-13_出苗地面抽查、仅代表所列垄_0至3垄').depends_on(previous, delay_seconds=2800))

            # 2019-05-16 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-05-16T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=256400).oracle()
                .with_id("043_2019-05-16_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('044_2019-05-16_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('045_2019-05-16_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('046_2019-05-16_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=11, end=32, hours=1.6).oracle()
                .with_id('047_2019-05-16_在本轮窗口补水、保留后续生育期额度_11至32垄_8毫米每垄').depends_on(previous, delay_seconds=6060))
            previous = (field_ops.irrigate(start=44, end=63, hours=1.6).oracle()
                .with_id('048_2019-05-16_在本轮窗口补水、保留后续生育期额度_44至63垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-05-17 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-05-17T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=74280).oracle()
                .with_id("049_2019-05-17_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('050_2019-05-17_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('051_2019-05-17_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('052_2019-05-17_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=10, hours=1.6).oracle()
                .with_id('053_2019-05-17_在本轮窗口补水、保留后续生育期额度_0至10垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-05-23 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-05-23T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=512340).oracle()
                .with_id("054_2019-05-23_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('055_2019-05-23_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('056_2019-05-23_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('057_2019-05-23_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=33, end=43, hours=1.6).oracle()
                .with_id('058_2019-05-23_在本轮窗口补水、保留后续生育期额度_33至43垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-05-28 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-05-28T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=425940).oracle()
                .with_id("059_2019-05-28_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('060_2019-05-28_全田传感器复核冠层长势').depends_on(previous))

            # 2019-06-27 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-06-27T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=2592000).oracle()
                .with_id("061_2019-06-27_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('062_2019-06-27_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))

            # 2019-07-02 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-07-02T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=432000).oracle()
                .with_id("063_2019-07-02_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('064_2019-07-02_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('065_2019-07-02_核对播床或土壤可通行性').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('066_2019-07-02_核对当前雨风作业窗口').depends_on(previous))
            previous = (tractor.refuel(liters=7.0).oracle()
                .with_id('067_2019-07-02_仅补足剩余作业与5升余油所需燃油_7升').depends_on(previous))
            previous = (tractor.load_fertilizer(kg=76.8).oracle()
                .with_id('068_2019-07-02_批量装足本轮肥料_76.8公斤').depends_on(previous))
            previous = (tractor.apply_fertilizer(start_ridge=0, end_ridge=9, kg_per_ridge=1.2).oracle()
                .with_id('069_2019-07-02_对已诊断营养不足区定量追肥_0至9垄_1.2公斤每垄').depends_on(previous, delay_seconds=190))
            previous = (tractor.apply_fertilizer(start_ridge=10, end_ridge=19, kg_per_ridge=1.2).oracle()
                .with_id('070_2019-07-02_对已诊断营养不足区定量追肥_10至19垄_1.2公斤每垄').depends_on(previous, delay_seconds=190))
            previous = (tractor.apply_fertilizer(start_ridge=20, end_ridge=29, kg_per_ridge=1.2).oracle()
                .with_id('071_2019-07-02_对已诊断营养不足区定量追肥_20至29垄_1.2公斤每垄').depends_on(previous, delay_seconds=190))
            previous = (tractor.apply_fertilizer(start_ridge=30, end_ridge=39, kg_per_ridge=1.2).oracle()
                .with_id('072_2019-07-02_对已诊断营养不足区定量追肥_30至39垄_1.2公斤每垄').depends_on(previous, delay_seconds=190))
            previous = (tractor.apply_fertilizer(start_ridge=40, end_ridge=49, kg_per_ridge=1.2).oracle()
                .with_id('073_2019-07-02_对已诊断营养不足区定量追肥_40至49垄_1.2公斤每垄').depends_on(previous, delay_seconds=190))
            previous = (tractor.apply_fertilizer(start_ridge=50, end_ridge=59, kg_per_ridge=1.2).oracle()
                .with_id('074_2019-07-02_对已诊断营养不足区定量追肥_50至59垄_1.2公斤每垄').depends_on(previous, delay_seconds=190))
            previous = (tractor.apply_fertilizer(start_ridge=60, end_ridge=63, kg_per_ridge=1.2).oracle()
                .with_id('075_2019-07-02_对已诊断营养不足区定量追肥_60至63垄_1.2公斤每垄').depends_on(previous, delay_seconds=190))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('076_2019-07-02_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('077_2019-07-02_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=10, hours=1.6).oracle()
                .with_id('078_2019-07-02_在本轮窗口补水、保留后续生育期额度_0至10垄_8毫米每垄').depends_on(previous, delay_seconds=6060))
            previous = (field_ops.irrigate(start=44, end=53, hours=1.6).oracle()
                .with_id('079_2019-07-02_在本轮窗口补水、保留后续生育期额度_44至53垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-07-03 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-07-03T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=72950).oracle()
                .with_id("080_2019-07-03_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('081_2019-07-03_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('082_2019-07-03_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('083_2019-07-03_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=11, end=43, hours=1.6).oracle()
                .with_id('084_2019-07-03_在本轮窗口补水、保留后续生育期额度_11至43垄_8毫米每垄').depends_on(previous, delay_seconds=6060))
            previous = (field_ops.irrigate(start=54, end=63, hours=1.6).oracle()
                .with_id('085_2019-07-03_在本轮窗口补水、保留后续生育期额度_54至63垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-07-06 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-07-06T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=247080).oracle()
                .with_id("086_2019-07-06_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('087_2019-07-06_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('088_2019-07-06_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('089_2019-07-06_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=1.6).oracle()
                .with_id('090_2019-07-06_在本轮窗口补水、保留后续生育期额度_0至63垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-07-09 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-07-09T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=253140).oracle()
                .with_id("091_2019-07-09_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('092_2019-07-09_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('093_2019-07-09_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('094_2019-07-09_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=1.6).oracle()
                .with_id('095_2019-07-09_在本轮窗口补水、保留后续生育期额度_0至63垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-07-12 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-07-12T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=253140).oracle()
                .with_id("096_2019-07-12_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('097_2019-07-12_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('098_2019-07-12_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('099_2019-07-12_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=1.6).oracle()
                .with_id('100_2019-07-12_在本轮窗口补水、保留后续生育期额度_0至63垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-07-15 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-07-15T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=253140).oracle()
                .with_id("101_2019-07-15_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('102_2019-07-15_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('103_2019-07-15_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('104_2019-07-15_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=1.6).oracle()
                .with_id('105_2019-07-15_在本轮窗口补水、保留后续生育期额度_0至63垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-07-18 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-07-18T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=253140).oracle()
                .with_id("106_2019-07-18_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('107_2019-07-18_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('108_2019-07-18_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('109_2019-07-18_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=1.6).oracle()
                .with_id('110_2019-07-18_在本轮窗口补水、保留后续生育期额度_0至63垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-07-21 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-07-21T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=253140).oracle()
                .with_id("111_2019-07-21_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('112_2019-07-21_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_canopy_sensors().oracle()
                .with_id('113_2019-07-21_全田传感器复核冠层长势').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('114_2019-07-21_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('115_2019-07-21_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=1.6).oracle()
                .with_id('116_2019-07-21_在本轮窗口补水、保留后续生育期额度_0至63垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-07-26 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-07-26T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=425940).oracle()
                .with_id("117_2019-07-26_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('118_2019-07-26_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('119_2019-07-26_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('120_2019-07-26_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=22, end=53, hours=1.6).oracle()
                .with_id('121_2019-07-26_在本轮窗口补水、保留后续生育期额度_22至53垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-07-27 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-07-27T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=80340).oracle()
                .with_id("122_2019-07-27_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('123_2019-07-27_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('124_2019-07-27_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('125_2019-07-27_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=21, hours=1.6).oracle()
                .with_id('126_2019-07-27_在本轮窗口补水、保留后续生育期额度_0至21垄_8毫米每垄').depends_on(previous, delay_seconds=6060))
            previous = (field_ops.irrigate(start=54, end=63, hours=1.6).oracle()
                .with_id('127_2019-07-27_在本轮窗口补水、保留后续生育期额度_54至63垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-07-29 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-07-29T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=160680).oracle()
                .with_id("128_2019-07-29_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('129_2019-07-29_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('130_2019-07-29_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('131_2019-07-29_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=22, end=53, hours=1.6).oracle()
                .with_id('132_2019-07-29_在本轮窗口补水、保留后续生育期额度_22至53垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-07-30 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-07-30T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=80340).oracle()
                .with_id("133_2019-07-30_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('134_2019-07-30_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('135_2019-07-30_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('136_2019-07-30_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=21, hours=1.6).oracle()
                .with_id('137_2019-07-30_在本轮窗口补水、保留后续生育期额度_0至21垄_8毫米每垄').depends_on(previous, delay_seconds=6060))
            previous = (field_ops.irrigate(start=54, end=63, hours=1.6).oracle()
                .with_id('138_2019-07-30_在本轮窗口补水、保留后续生育期额度_54至63垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-08-01 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-08-01T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=160680).oracle()
                .with_id("139_2019-08-01_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('140_2019-08-01_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('141_2019-08-01_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('142_2019-08-01_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=22, end=53, hours=1.6).oracle()
                .with_id('143_2019-08-01_在本轮窗口补水、保留后续生育期额度_22至53垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-08-02 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-08-02T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=80340).oracle()
                .with_id("144_2019-08-02_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('145_2019-08-02_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('146_2019-08-02_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('147_2019-08-02_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=21, hours=1.6).oracle()
                .with_id('148_2019-08-02_在本轮窗口补水、保留后续生育期额度_0至21垄_8毫米每垄').depends_on(previous, delay_seconds=6060))
            previous = (field_ops.irrigate(start=54, end=63, hours=1.6).oracle()
                .with_id('149_2019-08-02_在本轮窗口补水、保留后续生育期额度_54至63垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-08-04 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-08-04T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=160680).oracle()
                .with_id("150_2019-08-04_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('151_2019-08-04_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('152_2019-08-04_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('153_2019-08-04_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=22, end=53, hours=1.6).oracle()
                .with_id('154_2019-08-04_在本轮窗口补水、保留后续生育期额度_22至53垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-08-05 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-08-05T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=80340).oracle()
                .with_id("155_2019-08-05_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('156_2019-08-05_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('157_2019-08-05_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('158_2019-08-05_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=21, hours=1.6).oracle()
                .with_id('159_2019-08-05_在本轮窗口补水、保留后续生育期额度_0至21垄_8毫米每垄').depends_on(previous, delay_seconds=6060))
            previous = (field_ops.irrigate(start=54, end=63, hours=1.6).oracle()
                .with_id('160_2019-08-05_在本轮窗口补水、保留后续生育期额度_54至63垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-08-07 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-08-07T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=160680).oracle()
                .with_id("161_2019-08-07_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('162_2019-08-07_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('163_2019-08-07_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('164_2019-08-07_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=22, end=53, hours=1.6).oracle()
                .with_id('165_2019-08-07_在本轮窗口补水、保留后续生育期额度_22至53垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-08-08 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-08-08T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=80340).oracle()
                .with_id("166_2019-08-08_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('167_2019-08-08_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('168_2019-08-08_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('169_2019-08-08_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=21, hours=1.6).oracle()
                .with_id('170_2019-08-08_在本轮窗口补水、保留后续生育期额度_0至21垄_8毫米每垄').depends_on(previous, delay_seconds=6060))
            previous = (field_ops.irrigate(start=54, end=63, hours=1.6).oracle()
                .with_id('171_2019-08-08_在本轮窗口补水、保留后续生育期额度_54至63垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-08-11 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-08-11T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=247080).oracle()
                .with_id("172_2019-08-11_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('173_2019-08-11_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('174_2019-08-11_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('175_2019-08-11_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=1.6).oracle()
                .with_id('176_2019-08-11_在本轮窗口补水、保留后续生育期额度_0至63垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-08-14 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-08-14T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=253140).oracle()
                .with_id("177_2019-08-14_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('178_2019-08-14_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('179_2019-08-14_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('180_2019-08-14_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=1.6).oracle()
                .with_id('181_2019-08-14_在本轮窗口补水、保留后续生育期额度_0至63垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-08-17 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-08-17T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=253140).oracle()
                .with_id("182_2019-08-17_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('183_2019-08-17_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_root_zone_sensors().oracle()
                .with_id('184_2019-08-17_核对根区水分以安排有限补水').depends_on(previous))
            previous = (weather.get_forecast(days=3).oracle()
                .with_id('185_2019-08-17_复核近期降雨、避免浪费灌水').depends_on(previous))
            previous = (field_ops.irrigate(start=0, end=63, hours=1.6).oracle()
                .with_id('186_2019-08-17_在本轮窗口补水、保留后续生育期额度_0至63垄_8毫米每垄').depends_on(previous, delay_seconds=6060))

            # 2019-09-02 (Europe/Paris): fixed observation/work block.
            # Wait until 2019-09-02T07:00:00+02:00; machine work is already counted.
            previous = (system.advance_time(seconds=1376340).oracle()
                .with_id("187_2019-09-02_等待下一作业窗口、作物继续日推").depends_on(previous))
            previous = (farm.get_ridge_range_state(start=0, end=63).oracle()
                .with_id('188_2019-09-02_核对生育阶段、目标垄及收前水分_0至63垄').depends_on(previous))
            previous = (sensor.read_soil_sensors().oracle()
                .with_id('189_2019-09-02_核对播床或土壤可通行性').depends_on(previous))
            previous = (weather.get_current_weather().oracle()
                .with_id('190_2019-09-02_核对当前雨风作业窗口').depends_on(previous))
            previous = (tractor.attach_implement(implement='harvester').oracle()
                .with_id('191_2019-09-02_安装本作业所需机具').depends_on(previous))
            previous = (tractor.harvest(start_ridge=0, end_ridge=3).oracle()
                .with_id('192_2019-09-02_成熟及水分合格后收割、每趟最多4垄_0至3垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=4, end_ridge=7).oracle()
                .with_id('193_2019-09-02_成熟及水分合格后收割、每趟最多4垄_4至7垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('194_2019-09-02_合批卸粮、保留2吨粮箱安全余量').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('195_2019-09-02_批次干燥至安全水分、当前工具即时零耗时_13%').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('196_2019-09-02_安全入库并保留来源垄覆盖').depends_on(previous))
            previous = (tractor.harvest(start_ridge=8, end_ridge=11).oracle()
                .with_id('197_2019-09-02_成熟及水分合格后收割、每趟最多4垄_8至11垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=12, end_ridge=15).oracle()
                .with_id('198_2019-09-02_成熟及水分合格后收割、每趟最多4垄_12至15垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('199_2019-09-02_合批卸粮、保留2吨粮箱安全余量').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('200_2019-09-02_批次干燥至安全水分、当前工具即时零耗时_13%').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('201_2019-09-02_安全入库并保留来源垄覆盖').depends_on(previous))
            previous = (tractor.harvest(start_ridge=16, end_ridge=19).oracle()
                .with_id('202_2019-09-02_成熟及水分合格后收割、每趟最多4垄_16至19垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=20, end_ridge=23).oracle()
                .with_id('203_2019-09-02_成熟及水分合格后收割、每趟最多4垄_20至23垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('204_2019-09-02_合批卸粮、保留2吨粮箱安全余量').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('205_2019-09-02_批次干燥至安全水分、当前工具即时零耗时_13%').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('206_2019-09-02_安全入库并保留来源垄覆盖').depends_on(previous))
            previous = (tractor.harvest(start_ridge=24, end_ridge=27).oracle()
                .with_id('207_2019-09-02_成熟及水分合格后收割、每趟最多4垄_24至27垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=28, end_ridge=31).oracle()
                .with_id('208_2019-09-02_成熟及水分合格后收割、每趟最多4垄_28至31垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('209_2019-09-02_合批卸粮、保留2吨粮箱安全余量').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('210_2019-09-02_批次干燥至安全水分、当前工具即时零耗时_13%').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('211_2019-09-02_安全入库并保留来源垄覆盖').depends_on(previous))
            previous = (tractor.harvest(start_ridge=32, end_ridge=35).oracle()
                .with_id('212_2019-09-02_成熟及水分合格后收割、每趟最多4垄_32至35垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=36, end_ridge=39).oracle()
                .with_id('213_2019-09-02_成熟及水分合格后收割、每趟最多4垄_36至39垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('214_2019-09-02_合批卸粮、保留2吨粮箱安全余量').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('215_2019-09-02_批次干燥至安全水分、当前工具即时零耗时_13%').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('216_2019-09-02_安全入库并保留来源垄覆盖').depends_on(previous))
            previous = (tractor.harvest(start_ridge=40, end_ridge=43).oracle()
                .with_id('217_2019-09-02_成熟及水分合格后收割、每趟最多4垄_40至43垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=44, end_ridge=47).oracle()
                .with_id('218_2019-09-02_成熟及水分合格后收割、每趟最多4垄_44至47垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('219_2019-09-02_合批卸粮、保留2吨粮箱安全余量').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('220_2019-09-02_批次干燥至安全水分、当前工具即时零耗时_13%').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('221_2019-09-02_安全入库并保留来源垄覆盖').depends_on(previous))
            previous = (tractor.harvest(start_ridge=48, end_ridge=51).oracle()
                .with_id('222_2019-09-02_成熟及水分合格后收割、每趟最多4垄_48至51垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=52, end_ridge=55).oracle()
                .with_id('223_2019-09-02_成熟及水分合格后收割、每趟最多4垄_52至55垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('224_2019-09-02_合批卸粮、保留2吨粮箱安全余量').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('225_2019-09-02_批次干燥至安全水分、当前工具即时零耗时_13%').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('226_2019-09-02_安全入库并保留来源垄覆盖').depends_on(previous))
            previous = (tractor.harvest(start_ridge=56, end_ridge=59).oracle()
                .with_id('227_2019-09-02_成熟及水分合格后收割、每趟最多4垄_56至59垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.harvest(start_ridge=60, end_ridge=63).oracle()
                .with_id('228_2019-09-02_成熟及水分合格后收割、每趟最多4垄_60至63垄').depends_on(previous, delay_seconds=271))
            previous = (tractor.unload_grain().oracle()
                .with_id('229_2019-09-02_合批卸粮、保留2吨粮箱安全余量').depends_on(previous, delay_seconds=480))
            previous = (farm.dry_grain(target_moisture_pct=13.0).oracle()
                .with_id('230_2019-09-02_批次干燥至安全水分、当前工具即时零耗时_13%').depends_on(previous))
            previous = (farm.store_grain().oracle()
                .with_id('231_2019-09-02_安全入库并保留来源垄覆盖').depends_on(previous))
            previous = (farm.get_inventory().oracle()
                .with_id('232_2019-09-02_核对仓库、季节额度与收储结果').depends_on(previous))
            previous = (tractor.get_status().oracle()
                .with_id('233_2019-09-02_核对油料、机具、种箱及粮箱余量').depends_on(previous))

        for event in captured:
            event.record_runtime_timing = True
        self.events = list(captured)
        return self.events
