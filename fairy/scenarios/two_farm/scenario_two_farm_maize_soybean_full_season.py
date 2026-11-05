"""玉米＋大豆全季：两套固定设施，一套共享机械和仓库。

本文件完整定义两场初态、设备、公共天气、全部工作流、Oracle 和验收。
不调用其他场景的安装或工作流。两个农场各64垄，垄数沿用现有探头布局；
玉米268m×0.65m、单行25cm，大豆268m×1.1m、双行8cm，面积分别1.11488/1.88672ha。
玉米为未田间标定的MAIZE_EARLY_2026，大豆使用现有HEINONG84模型。
天气是哈尔滨气候参数下seed101的合成天气，不是2026年的气象实测。

两场都从裸地正常管理：播前准备、播种、出苗巡查、按作物安排追肥和水分管理、
独立确认成熟及含水率，最后分作物分批安全入库。没有强制病害或季中产量赋值。
参考日期只代表固定种子下的巡查窗口；Agent必须读取实际状态后决定作业。
参考路径在晚灌浆复核后12天检查并收获大豆，随后等待30天进入玉米收获窗口；
较旧路径大豆提前5天，玉米后续作业日期不变，减少大豆成熟后过干的回收损失。

运行：python -m fairy.cli -s scenario_two_farm_maize_soybean_full_season \
    --build-oracle --run-oracle-tools --replay --evaluate --output-dir /tmp/maize-soybean
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world.equipment import DEFAULT_TRACTOR_IMPLEMENTS, TractorEquipment
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.irrigation_app import IrrigationApp
from fairy.apps.farm_world.sensor_app import SensorApp
from fairy.apps.farm_world.shared_drone_app import SharedDroneApp
from fairy.apps.farm_world.shared_robot_app import SharedRobotApp
from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.system import SystemApp
from fairy.physics.soil_engine import SoilHydraulicModifier
from fairy.scenarios.registry import register_scenario
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.scenarios.workflow import Workflow, WorkflowStep
from fairy.types import EventRegisterer


SCENARIO_ID = "scenario_two_farm_maize_soybean_full_season"
WEATHER_PROFILE = "harbin_baseline_2026_seed_101"
NUM_RIDGES = 64
FIELD_LENGTH_M = 268.0
MAIZE_CULTIVAR = "MAIZE_EARLY_2026"
SOYBEAN_CULTIVAR = "HEINONG84"
MAIZE_SPACING_CM = 25.0
SOYBEAN_SPACING_CM = 8.0
BASE_FERTILIZER_KG = 200.0
MAIZE_TOPDRESS_KG_PER_RIDGE = 6.0
SOYBEAN_TOPDRESS_KG_PER_RIDGE = 2.0

BASIC_BRIEFING = """
管理哈尔滨同一地区 maize_field 玉米场和 soybean_field 大豆场的完整季节，从裸地到分别安全入库。
每场64垄，本地编号0–63，垄长268m。玉米场垄距0.65m、单行、面积1.11488ha，
作物 maize，模拟品种 MAIZE_EARLY_2026；大豆场垄距1.1m、双行、面积1.88672ha，
作物 soybean，品种 HEINONG84。玉米品种未经过田间标定，产量不是现实预测。

MaizeFarm、SoybeanFarm 分别公开自己的作物规则与状态。Maize_Sensor、Maize_Irrigation
固定服务玉米场，Soybean_Sensor、Soybean_Irrigation 固定服务大豆场。
Warehouse 统一拥有物料和粮食批次；Tractor、Mavic3M、Robot0 各只有一台，供两场共用。
移动田间工具必须指定 farm_id；装料、退料、挂接机具操作共享机器，不指定 farm_id。
换作物前核对并清空种箱；粮食逐批保留来源场、作物、品种与垄号，不能混记两场产量。

先分别查询两场作物能力、天气、土壤、冠层、机器与共享库存，按实际状态完成播前准备、播种、
出苗巡查、季内水肥和健康管理、成熟检查、收获与必要干燥，不把一场管理方案照搬到另一场。
从工具获取各作物播收、安全水分、作业条件与资源限制；处理前确认依据，处理后复查效果。
完成边界：每场64垄均已收获，各作物粮食安全入库，无待入库批次，种箱和粮箱清空，
各场额度与共享库存账一致，分别报告管理覆盖和实际收获结果；抽查不能代替全田覆盖。
达到本场收割条件后及时分批收获；必要时收后干燥，不必等籽粒在田间降到入库水分，以免过干损失。
所有动作共用北京时间的一只模拟时钟；等待一次同时推进两场，不为每场重复等待。
""".strip()

DETAILED_BRIEFING = """
管理哈尔滨同一地区的maize_field玉米场和soybean_field大豆场，从裸地到全季安全入库。
每场本地编号0–63、垄长268m。玉米垄距0.65m、单行、株距25cm、播深5cm，
面积1.11488ha，需68608粒MAIZE_EARLY_2026种子。大豆垄距1.1m、双行、株距8cm、
播深4cm，面积1.88672ha，需428800粒HEINONG84种子。玉米品种未田间标定。

MaizeFarm/SoybeanFarm分别公开自己的作物规则和田块状态。Maize_Sensor、
Maize_Irrigation固定服务玉米，Soybean_Sensor、Soybean_Irrigation固定服务大豆。
Warehouse统一拥有物料和粮食批次；Tractor、Mavic3M、Robot0各只有一台。
移动田间工具必须指定farm_id；装料、退料、挂接机具操作共享机器，不指定farm_id。
种箱有余种时先return_supplies再换品种；按趟精确装种也可避免混种。
玉米挂maize_planter、maize_header；本场显式配置soybean_planter和harvester供大豆。

工作安排：
1. 读两场get_crop_capabilities、公共天气/预报、共享库存及各场土壤。逐场平地、
   施200kg模拟肥料产品、按本场垄距起垄，再完成各场64垄播种，每趟最多4垄。
2. 约6月初分别检查出苗、土壤与冠层。Mavic巡查每场全田；跨场前充电并等待完成。
   Robot只抽查各场0–3垄，发现异常再扩大检查，不能把抽查当作全田地面覆盖。
3. 约6月下旬检查玉米V期、营养和墒情，参考全田追施6kg/垄肥料产品。大豆同期只巡查。
   约7月中旬分别复查两场营养，参考大豆轻量追肥2kg/垄。上述kg为产品量，不是纯氮。
4. 玉米吐丝和灌浆窗口分别复核连续墒情、天气预报、冠层与地面健康。吐丝期参考补水20mm，
   固定设施运行4小时另计5分钟设置；次日复核入渗。灌浆期预报有效降雨则暂不补水，
   次日检查自然降雨与土壤。水预算30个全田等效mm，不能按日期固定灌两次。
   大豆为保水较好的土壤，独立检查水分；本参考年不因玉米灌水就给大豆同样灌水。
   大豆备用水额度20mm；玉米/大豆全季肥料产品额度分别650/400kg，含底肥。
   无确诊病虫害不预防性施药；异常先复查并记录证据。
5. 分别检查两场成熟度和天气，满足本场实际条件才收：玉米R6且水分≤30%，
   大豆R8且水分≤18%；都需无雨和可通行。先成熟的作物可先收，不按一个日期强收两场。
   达到本场收割条件后及时分批收获，必要时收后干燥；不必等田间自然降到入库水分，以免过干损失。
6. 每次最多收4垄，立即unload_grain(batch_id)，清空粮箱再切场。共享仓库按批次
   保留来源场、作物、品种和垄号；玉米必要时干燥至14%、大豆至13%后逐批store_grain。
   本仓库设备上限14%，大豆仍按自身13.5%安全上限检查，不会套用玉米的14%。
7. 最后核对每场64垄均收获、无待入库批次、种箱粮箱清空、各场水额度及共享物料账，
   分开汇报玉米和大豆数量。粮重分别为14%与13%标准水分口径，不把混合总kg当统一单产。

所有动作共用北京时间；等待一次同时推进两场，不为每个农场重复等待。
参考Oracle是固定合成天气下经过工具执行的管理基线，不代表最高产或现实农艺推荐。
""".strip()


@register_scenario(SCENARIO_ID)
class ScenarioTwoFarmMaizeSoybeanFullSeason(Scenario):
    """正常管理的异种双场任务，全部场景内容就地定义。"""

    start_time = datetime(2026, 5, 15, 7, tzinfo=timezone(timedelta(hours=8))).timestamp()
    duration = 190 * 86400
    queue_based_loop = True
    time_increment_in_seconds = 60
    expects_agent_harvest = True
    additional_system_prompt = (
        "Manage maize_field and soybean_field for one complete season using a shared clock, "
        "tractor, drone, robot and Warehouse. Fixed sensors and irrigation belong to their named farm. "
        "Read each farm's crop capabilities, observations and actual maturity; do not copy maize "
        "stages, fertilizer rates or moisture limits to soybean. Field tools require farm_id; "
        "loading, returning supplies and switching implements do not. Empty the seed hopper before "
        "changing seed varieties and unload each harvest pass into a unique, traceable batch. "
        "Store maize at <=14% and soybean at <=13.5% moisture. Keep grain totals separate by crop. "
        "Observe before treatment and recheck after irrigation. The simulated maize is not field-calibrated."
    )

    def __post_init__(self) -> None:
        super().__post_init__()
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean: false or true")
        if not self.scenario_input:
            self.scenario_input = DETAILED_BRIEFING if self.detailed_briefing else BASIC_BRIEFING

    def init_and_populate_apps(self) -> None:
        self.aui = AgentUserInterface()
        self.weather = WeatherApp()
        self.weather.set_weather(
            date="2026-05-15", temp_c=17.0, humidity_pct=55.0,
            wind_speed_ms=2.0, rainfall_mm=0.0, solar_radiation=20.0 / 0.0864,
            forecast=[{"date": "2026-05-16", "temp_c": 17.5, "humidity_pct": 55.0,
                       "wind_speed_ms": 2.0, "rainfall_mm": 0.0, "solar_radiation": 20.5 / 0.0864}],
        )
        self.maize = FarmWorldApp(
            name="MaizeFarm", farm_id="maize_field", crop_id="maize", cultivar_id=MAIZE_CULTIVAR,
            field_length_m=FIELD_LENGTH_M, ridge_width_m=0.65, rows_per_ridge=1,
        )
        self.soybean = FarmWorldApp(
            name="SoybeanFarm", farm_id="soybean_field", crop_id="soybean", cultivar_id=SOYBEAN_CULTIVAR,
            field_length_m=FIELD_LENGTH_M, ridge_width_m=1.1, rows_per_ridge=2,
        )
        # 本场显式要求大豆播种机/收获机；不改变历史大豆场景的宽松机具规则。
        # 快照续跑须先创建同一场景，作业规则属于场景配置而非设备运行状态。
        self.soybean.crop_definition = replace(
            self.soybean.crop_definition,
            planting_rules=replace(self.soybean.crop_definition.planting_rules,
                                   required_implement="soybean_planter"),
            harvest_rules=replace(self.soybean.crop_definition.harvest_rules,
                                  required_implement="harvester"),
        )
        self.maize_sensor = SensorApp(self.maize, name="Maize_Sensor")
        self.soybean_sensor = SensorApp(self.soybean, name="Soybean_Sensor")
        self.maize_irrigation = IrrigationApp(self.maize, self.weather, name="Maize_Irrigation")
        self.soybean_irrigation = IrrigationApp(self.soybean, self.weather, name="Soybean_Irrigation")
        self.warehouse = WarehouseApp(
            stock=WarehouseStock({MAIZE_CULTIVAR: 100000, SOYBEAN_CULTIVAR: 500000},
                                 pesticide_liters=20.0, fertilizer_kg=1400.0, fuel_liters=800.0),
            max_storage_moisture_pct=14.0, storage_capacity_kg=30000.0,
        )
        self.farm_environment = FarmEnvironment([
            FarmContext("maize_field", self.maize, self.weather, self.maize_sensor, self.maize_irrigation),
            FarmContext("soybean_field", self.soybean, self.weather, self.soybean_sensor, self.soybean_irrigation),
        ], self.weather, warehouse=self.warehouse, start_time=self.start_time, timezone_name="Asia/Shanghai")
        self.tractor = SharedTractorApp(self.farm_environment, equipment=TractorEquipment(
            implements=(*DEFAULT_TRACTOR_IMPLEMENTS, "maize_planter", "maize_header", "soybean_planter"),
            ridging_implement="furrower",
        ))
        self.mavic = SharedDroneApp(self.farm_environment, name="Mavic3M", speed_ms=5.0,
                                    effective_ridges_per_pass=7, battery_pct_per_ridge=1.0)
        self.robot = SharedRobotApp(self.farm_environment, name="Robot0")
        self.system = SystemApp()
        self.system.attach_farm_environment(self.farm_environment)
        self.shared_equipment = [self.tractor, self.mavic, self.robot]
        self.apps = [self.aui, self.weather, self.warehouse, self.maize, self.soybean,
                     self.maize_sensor, self.soybean_sensor, self.maize_irrigation,
                     self.soybean_irrigation, *self.shared_equipment, self.system]
        for app in self.apps:
            app.register_time_manager(self.farm_environment.time_manager)
            app.set_seed(self.seed)

        maize_soil = SoilHydraulicModifier(
            root_depth_m=1.00, field_capacity_vwc=0.34,
            top_drainage_rate=0.22, root_drainage_rate=0.04,
            rainfall_capture_efficiency=0.90, irrigation_efficiency=0.90,
            max_infiltration_mm_day=80.0,
        )
        soybean_soil = SoilHydraulicModifier(
            root_depth_m=1.45, field_capacity_vwc=0.37,
            top_drainage_rate=0.22, root_drainage_rate=0.03,
            rainfall_capture_efficiency=0.95, irrigation_efficiency=0.90,
            max_infiltration_mm_day=80.0,
        )
        for farm, cultivar, nutrient, initial_vwc, soil, water_quota, fertilizer_quota in (
            (self.maize, MAIZE_CULTIVAR, 0.66, 0.25, maize_soil, 30.0, 650.0),
            (self.soybean, SOYBEAN_CULTIVAR, 0.78, 0.26, soybean_soil, 20.0, 400.0),
        ):
            farm._sim_date = "2026-05-15"
            farm.set_season_phase("full_season")
            for ridge in farm._ridges:
                ridge.planted = ridge.harvested = False
                ridge.soil_vwc = initial_vwc + ((ridge.ridge_id % 5) - 2) * 0.002
                ridge.soil_temp_c = 13.0 + (ridge.ridge_id % 4) * 0.2
                ridge.nutrient_index = nutrient
                ridge.stand_fraction = 1.0
                ridge.pest_pressure_base = ridge.pest_pressure = 0.01
                ridge.disease_pressure_base = ridge.disease_pressure = 0.01
            farm.configure_physics_profile(
                WEATHER_PROFILE, location="Harbin/Heilongjiang", seed_type=cultivar,
                cultivar=cultivar, start_date="2026-05-15",
            )
            farm.physics.profile = deepcopy(farm.physics.profile)
            farm.physics.soil.set_hydraulic_modifiers({
                rid: soil for rid in range(NUM_RIDGES)
            })
            farm.configure_management_regime(
                regime="conventional", irrigation_quota_mm_total=water_quota,
                fertilizer_quota_kg=fertilizer_quota,
            )
        self._initial_stock = deepcopy(self.warehouse.stock)

    def _reference_actions(self) -> list[tuple[str, Any, str, dict[str, Any], str]]:
        """完整固定种子参考；每个工具调用均有本场目标和管理理由。"""
        actions = []

        def add(step, app, method, reason, **arguments):
            actions.append((step, app, method, arguments, reason))

        def observe(phase):
            add(f"{phase}_weather", self.weather, "get_current_weather", "先核对共同天气。")
            add(f"{phase}_forecast", self.weather, "get_forecast", "读取未来有效降雨和可作业窗口。", days=4)
            for farm_id, farm, sensor in (("maize_field", self.maize, self.maize_sensor),
                                           ("soybean_field", self.soybean, self.soybean_sensor)):
                add(f"{phase}_{farm_id}_state", farm, "get_ridge_range_state", "读取本场实际生育阶段、营养与水分。", start=0, end=63)
                add(f"{phase}_{farm_id}_soil", sensor, "read_soil_sensors", "读取本场六区墒情并与前次比较。")
                add(f"{phase}_{farm_id}_canopy", sensor, "read_canopy_sensors", "冠层与土壤、阶段交叉判断。")

        add("maize_capabilities", self.maize, "get_crop_capabilities", "读取玉米需求，不自动生成设备。")
        add("soybean_capabilities", self.soybean, "get_crop_capabilities", "读取大豆的不同播收规则。")
        add("initial_stock", self.warehouse, "get_inventory", "物料只从这一个共享仓库支取。")
        observe("preplant")
        for farm_id, farm, cultivar, spacing, depth, planter in (
            ("maize_field", self.maize, MAIZE_CULTIVAR, MAIZE_SPACING_CM, 5.0, "maize_planter"),
            ("soybean_field", self.soybean, SOYBEAN_CULTIVAR, SOYBEAN_SPACING_CM, 4.0, "soybean_planter"),
        ):
            add(f"{farm_id}_refuel", self.tractor, "refuel", "补充共享油箱剩余空间，库存只扣实际转入量。", liters=100.0)
            add(f"{farm_id}_grader", self.tractor, "attach_implement", "安装平地机。", implement="grader")
            add(f"{farm_id}_level", self.tractor, "level", "仅整平目标农场。", farm_id=farm_id)
            add(f"{farm_id}_detach_grader", self.tractor, "detach_implement", "卸下平地机。")
            add(f"{farm_id}_load_base", self.tractor, "load_fertilizer", "从共享库存装200kg底肥产品。", kg=BASE_FERTILIZER_KG)
            add(f"{farm_id}_base", self.tractor, "base_fertilize", "只给本场施用题设的200kg底肥，另一场同时经过作业时间。", farm_id=farm_id, total_kg=BASE_FERTILIZER_KG)
            add(f"{farm_id}_furrower", self.tractor, "attach_implement", "安装起垄机。", implement="furrower")
            add(f"{farm_id}_ridges", self.tractor, "form_ridges", "按本场实际垄距起垄。", farm_id=farm_id, ridge_width_m=farm.ridge_width_m)
            add(f"{farm_id}_detach_furrower", self.tractor, "detach_implement", "起垄后换播种机。")
            add(f"{farm_id}_planter", self.tractor, "attach_implement", "挂载本场作物的已配置播种机。", implement=planter)
            for start in range(0, NUM_RIDGES, 4):
                end = start + 3
                add(f"{farm_id}_load_seed_{start}", self.tractor, "load_seeds", "按真实行数/长度精确装这一趟种子。",
                    seed_type=cultivar, count=farm.plants_per_ridge_from_spacing(spacing) * 4)
                add(f"{farm_id}_plant_{start}", self.tractor, "plant_seeds", "目标垄编号属于此farm_id。",
                    farm_id=farm_id, start_ridge=start, end_ridge=end, depth_cm=depth, seed_spacing_cm=spacing)
            add(f"{farm_id}_detach_planter", self.tractor, "detach_implement", "播种结束卸下机具。")
            add(f"{farm_id}_return_seed", self.tractor, "return_supplies", "确认种箱清空再换作物，余料回唯一仓库。")

        add("wait_emergence", self.system, "advance_time", "一次共同等待，进入两场出苗复查窗口。", days=17)
        observe("emergence")
        for farm_id in ("maize_field", "soybean_field"):
            add(f"{farm_id}_emergence_ground", self.robot, "inspect_emergence", "仅抽查本场0–3垄。", farm_id=farm_id, start_ridge=0, end_ridge=3)
            add(f"{farm_id}_emergence_flight", self.mavic, "fly_survey", "获取本场64垄多光谱，非另一个农场。", farm_id=farm_id, start_ridge=0, end_ridge=63)
            add(f"{farm_id}_charge_drone", self.mavic, "charge", "跨场共用同一块无人机电池。")
            add(f"{farm_id}_charge_robot", self.robot, "charge", "机器人电量同样跨场连续。")
            add(f"{farm_id}_charge_wait", self.system, "advance_time", "异步充电一小时，同时推进两场。", hours=1)

        add("wait_vegetative", self.system, "advance_time", "约6月下旬玉米营养期巡查，两场共同生长。", days=24)
        observe("vegetative")
        add("maize_topdress_load", self.tractor, "load_fertilizer", "玉米参考追肥产品384kg。", kg=NUM_RIDGES * MAIZE_TOPDRESS_KG_PER_RIDGE)
        for start in range(0, NUM_RIDGES, 10):
            add(f"maize_topdress_{start}", self.tractor, "apply_fertilizer", "只给玉米分区追肥，记录实际消耗与耗时。",
                farm_id="maize_field", start_ridge=start, end_ridge=min(start + 9, 63), kg_per_ridge=MAIZE_TOPDRESS_KG_PER_RIDGE)
        add("maize_after_topdress", self.maize, "get_ridge_range_state", "复查公开营养指数已反映处理。", start=0, end=63)

        add("wait_silking", self.system, "advance_time", "约7月中下旬分别检查玉米吐丝与大豆生殖期。", days=23)
        observe("silking")
        add("soybean_topdress_load", self.tractor, "load_fertilizer", "大豆采用独立的轻量产品用量128kg。", kg=NUM_RIDGES * SOYBEAN_TOPDRESS_KG_PER_RIDGE)
        for start in range(0, NUM_RIDGES, 10):
            add(f"soybean_topdress_{start}", self.tractor, "apply_fertilizer", "本场实际营养复查后轻量追肥，不使用玉米剂量。",
                farm_id="soybean_field", start_ridge=start, end_ridge=min(start + 9, 63), kg_per_ridge=SOYBEAN_TOPDRESS_KG_PER_RIDGE)
        for phase, wait_days in (("silking", 0), ("grain_fill", 20)):
            if wait_days:
                add(f"wait_{phase}", self.system, "advance_time", "进入灌浆复查窗口。", days=wait_days)
                observe(phase)
            for farm_id in ("maize_field", "soybean_field"):
                add(f"{phase}_{farm_id}_health", self.robot, "inspect_crop_health", "分别抽查28–31垄，先排查明显病虫。",
                    farm_id=farm_id, start_ridge=28, end_ridge=31)
            if phase == "silking":
                add("silking_maize_water", self.maize_irrigation, "irrigate", "玉米吐丝期墒情与少雨预报支持补20mm，固定设施无需farm_id。", start=0, end=63, hours=4.0)
                add("silking_infiltration", self.system, "advance_time", "补水后等一天复核入渗，两场共同经过时间。", days=1)
            else:
                add("grain_fill_rain_wait", self.system, "advance_time", "当前墒情及有效降雨预报支持暂不灌水，次日复核自然降雨。", days=1)
            add(f"{phase}_maize_recheck", self.maize_sensor, "read_soil_sensors", "复查本场入渗，不宣称立刻全部解除根区缺水。")
            add(f"{phase}_soybean_recheck", self.soybean_sensor, "read_soil_sensors", "确认另一场独立水分，不把玉米处理写到大豆。")
            add(f"{phase}_robot_charge", self.robot, "charge", "为下次健康巡查充电。")
        add("wait_dent", self.system, "advance_time", "约8月下旬分别检查灌浆/成熟进度。", days=19)
        observe("late_fill")
        # 固定天气下大豆提前5天收获；后续等待补足这5天，保留玉米管理和收获日期。
        add("wait_soybean_harvest", self.system, "advance_time", "及时复核较早熟大豆的成熟与水分，避免成熟后过干。", days=12)
        observe("soybean_harvest")
        self._append_harvest_actions(actions, "soybean_field", "harvester", 13.0)
        add("wait_maize_harvest", self.system, "advance_time", "等待玉米独立达到收获条件；补足大豆提前收获的5天，保持玉米原参考窗口。", days=30)
        observe("maize_harvest")
        self._append_harvest_actions(actions, "maize_field", "maize_header", 14.0)
        add("final_batches", self.warehouse, "get_grain_batches", "按作物/来源逐批核对，不能用总粮重替代大豆完成。")
        add("final_stock", self.warehouse, "get_inventory", "核对共同物料余额和无待入库粮食。")
        for farm_id, farm in (("maize_field", self.maize), ("soybean_field", self.soybean)):
            add(f"final_{farm_id}", farm, "get_farm_overview", "独立核对本场64垄收获。")
            add(f"final_{farm_id}_budget", farm, "get_management_status", "独立核对水与物料应用额度。")
        add("report", self.aui, "send_message_to_user", "分别报告两种作物和共同资源账。",
            content="玉米与大豆全季参考完成：逐场核对128垄、分作物追肥/补水、不同成熟和含水率门槛、32个来源批次及共享仓库物料账；产量为未标定模拟结果。")
        return actions

    def _append_harvest_actions(self, actions, farm_id: str, implement: str, storage_moisture: float) -> None:
        """本文件内的公开收获步骤；每一趟入库都有独立来源批次。"""
        def add(step, app, method, reason, **arguments):
            actions.append((step, app, method, arguments, reason))

        add(f"{farm_id}_harvest_refuel", self.tractor, "refuel", "补足共享油箱用于本场收获。", liters=100.0)
        add(f"{farm_id}_header", self.tractor, "attach_implement", "挂载本场已配置收获机具。", implement=implement)
        for start in range(0, NUM_RIDGES, 4):
            batch_id = f"{farm_id}_{start:02d}_{start + 3:02d}"
            add(f"harvest_{batch_id}", self.tractor, "harvest", "工具再次检查本场阶段、含水率和天气。",
                farm_id=farm_id, start_ridge=start, end_ridge=start + 3)
            add(f"unload_{batch_id}", self.tractor, "unload_grain", "保留来源场/作物/垄号，清空粮箱。", batch_id=batch_id)
            add(f"dry_{batch_id}", self.warehouse, "dry_grain", "按该作物安全水分处理本批，已安全时工具跳过。",
                batch_id=batch_id, target_moisture_pct=storage_moisture)
            add(f"store_{batch_id}", self.warehouse, "store_grain", "只把此安全批次入库。", batch_id=batch_id)
        add(f"{farm_id}_detach_header", self.tractor, "detach_implement", "结束本场收获后才能换另一种割台。")

    def build_events_flow(self):
        with EventRegisterer.capture_mode() as events:
            previous = self.aui.send_message_to_agent(content=self.scenario_input).with_id("briefing")
            for step, app, method, arguments, _ in self._reference_actions():
                previous = getattr(app, method)(**arguments).oracle().with_id(step).depends_on(previous)
        self.events = events
        return events

    def oracle_solution(self, run_oracle: bool = False) -> None:
        if not self.apps:
            self.setup()
        self.workflow = Workflow()
        previous = None
        for step, app, method, arguments, reason in self._reference_actions():
            before = self.farm_environment.time_manager.time() if run_oracle else None
            result = getattr(app, method)(**arguments) if run_oracle else {}
            if isinstance(result, dict) and ("error" in result or result.get("status") == "partial"):
                raise RuntimeError(f"{step}: {app.name}__{method}: {result}")
            content = dict(result) if isinstance(result, dict) else {"result": result}
            content["oracle_reason"] = reason
            operation = getattr(getattr(app, method), "_event_operation_type", None)
            self.workflow.add_node(WorkflowStep(
                name=step, tool_name=f"{app.name}__{method}", tool_args=arguments,
                content=content, depends_on=[previous] if previous else [],
                op_type=operation.value if operation is not None else None,
                time_before=before,
                time_after=self.farm_environment.time_manager.time() if run_oracle else None,
            ))
            previous = step

    def validate(self, env=None) -> ScenarioValidationResult:
        """按每个农场、每个批次和共享资源验收，不以混合总粮重代替完成。"""
        self.farm_environment.sync()
        failures = []
        totals = {}
        operations = self.tractor.get_state()["operation_log"]
        batches = list(self.warehouse.grain_batches.values())
        steps = list((env.workflow if env is not None else self.workflow).dag.values())
        for farm_id, farm, cultivar, spacing in (
            ("maize_field", self.maize, MAIZE_CULTIVAR, MAIZE_SPACING_CM),
            ("soybean_field", self.soybean, SOYBEAN_CULTIVAR, SOYBEAN_SPACING_CM),
        ):
            planted = [op for op in operations if op["operation"] == "plant_seeds" and op.get("farm_id") == farm_id]
            expected = set(range(NUM_RIDGES))
            if {rid for op in planted for rid in op["ridge_ids"]} != expected:
                failures.append(f"{farm_id}: planting coverage incomplete")
            if not {"level", "base_fertilize", "form_ridges"} <= set(farm.completed_prep_ops):
                failures.append(f"{farm_id}: field preparation incomplete")
            topdressing = [op for op in operations if op["operation"] == "apply_fertilizer"
                           and op.get("farm_id") == farm_id and op["fertilizer_used_kg"] > 0]
            if {rid for op in topdressing for rid in op["ridge_ids"]} != expected:
                failures.append(f"{farm_id}: seasonal topdressing coverage incomplete")
            if not all(r.harvested for r in farm._ridges):
                failures.append(f"{farm_id}: harvest coverage incomplete")
            own_batches = [batch for batch in batches if batch.origin_farm_id == farm_id]
            coverage = Counter(rid for batch in own_batches for rid in batch.ridge_ids)
            if coverage != Counter(range(NUM_RIDGES)):
                failures.append(f"{farm_id}: batch ridge coverage missing or duplicated")
            limit = min(self.warehouse.max_storage_moisture_pct, farm._postharvest_market.max_storage_moisture_pct)
            if any(batch.status != "stored" or batch.quantity_kg <= 0 or batch.crop_id != farm.crop_id
                   or batch.cultivar_ids != [cultivar] or batch.moisture_pct is None
                   or batch.moisture_pct > limit + 1e-9 for batch in own_batches):
                failures.append(f"{farm_id}: incorrect crop, provenance, storage or moisture")
            seed_used = self._initial_stock.seed_stock[cultivar] - self.warehouse.stock.seed_stock[cultivar]
            expected_seeds = farm.plants_per_ridge_from_spacing(spacing) * NUM_RIDGES
            if seed_used != expected_seeds or sum(op["seeds_used"] for op in planted) != expected_seeds:
                failures.append(f"{farm_id}: seed account mismatch")
            regime = farm._management_regime
            if regime.irrigation_used_mm_total > regime.irrigation_quota_mm_total + 1e-9:
                failures.append(f"{farm_id}: irrigation quota exceeded")
            if regime.fertilizer_used_kg > regime.fertilizer_quota_kg + 1e-9:
                failures.append(f"{farm_id}: fertilizer quota exceeded")
            observed = {
                ridge["growth_stage"] for step in steps
                if step.tool_name == f"{farm.name}__get_ridge_range_state" and isinstance(step.content, dict)
                for ridge in step.content.get("ridges", []) if "growth_stage" in ridge
            }
            if not observed & {"VE", "V3", "V4"} or not observed & {"R1", "R1_SILKING", "R3_MILK"}:
                failures.append(f"{farm_id}: emergence or reproductive observation missing")
            if not observed & set(farm.crop_definition.harvest_rules.stage_codes):
                failures.append(f"{farm_id}: maturity observation missing")
            totals[farm_id] = {
                "crop_id": farm.crop_id, "cultivar_id": cultivar,
                "area_m2": farm.field_geometry.planted_area_m2,
                "harvested_ridges": sum(r.harvested for r in farm._ridges),
                "seed_used": seed_used, "water_used_mm": regime.irrigation_used_mm_total,
                "stored_grain_kg": round(sum(batch.quantity_kg for batch in own_batches), 2),
                "market_moisture_pct": farm.crop_definition.market_moisture_pct,
                "observed_stages": sorted(observed),
            }
        if self.maize._management_regime.irrigation_used_mm_total <= 0:
            failures.append("maize_field: key-stage water management missing")
        if any(step.error_stage or (isinstance(step.content, dict)
                                   and ("error" in step.content or step.content.get("status") == "partial"))
               for step in steps):
            failures.append("workflow contains failed or partial tools")
        device = self.tractor.get_state()
        if device["grain_bin_kg"] != 0 or device["seed_hopper"] != 0:
            failures.append("shared machine retains unaccounted seed or grain")
        if self.warehouse.stock.fertilizer_kg < 0 or self.warehouse.stock.fuel_liters < 0:
            failures.append("negative shared supplies")
        if any(batch.origin_farm_id not in totals for batch in batches):
            failures.append("unknown grain origin")
        return ScenarioValidationResult(
            success=not failures, message="; ".join(failures) or "Both crop seasons harvested and stored by origin.",
            metadata={"farms": totals, "grain_batches": len(batches),
                      "fertilizer_used_kg": self._initial_stock.fertilizer_kg - self.warehouse.stock.fertilizer_kg,
                      "model_scope": "simulation baseline; maize not field-calibrated"},
        )
