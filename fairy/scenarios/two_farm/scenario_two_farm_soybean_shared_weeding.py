"""双场大豆全季：两场全田杂草，同窗观察后共用拖拉机分批中耕。

独立场景文件：初始化、两档任务描述、完整build_events_flow都在此处。
不导入或继承其他场景；复用农场物理和公共App，不实现validate。

初始化：北京时间2026-05-15 07:00，哈尔滨，两场各64垄、垄长268m、垄距1.1m，
每垄两行，面积各1.88672ha。两场均从裸地开始，种HEINONG84，参考4cm深/8cm株距。
两场同seed101合成天气、相同保水黑土和营养指数0.82；不是2026年实测天气或田间校准。
杂草背景仅在初始化设置：A全64垄压力0.22，B全64垄压力0.19，A略重；
它们是模型竞争压力，不是株数/m²、杂草高度或现实经济防治阈值。
不安排季中强制暴发，也不直接改写生长/产量。病虫背景均0.01。
每场独立固定传感器和灌溉；一台Tractor、一架Mavic3M、一台Robot0和一个Warehouse共享。

参考workflow：
1. 分别查天气、土壤、库存与作物规则；共用拖拉机逐场平地、200kg底肥、起垄、全田播种。
2. 六月初观察出苗和墒情；地面抽查0–3垄不代表检查过全场杂草。
3. 6/12苗期窗口先读天气/墒情；固定参考遇雨11.19mm，等待三天排水，6/15为V3。
   复核无雨、土壤可通行后读两场阶段、土壤/冠层，再分别航测全64垄。
   每场地面抽查0–3、20–23、40–43、60–63，共16垄，确认跨区杂草证据；不是全田地面检查。
   A地面检查覆盖无人机充电；Robot查完A剩20%，充电期间航测B，再等充满才检查B。
   无人机低NDVI不能直接确诊杂草，地面工具返回带置信度的杂草检出和压力分档。
4. 两场跨区样带均支持全田杂草管理后，检查通行条件、挂cultivator，共享拖拉机先A后B。
   每场0–63按0–9、10–19、20–29、30–39、40–49、50–59、60–63分7趟，共14趟，无漏垄重叠。
   当前工具不模拟杂草高度、行内/行间区别或作物机械损伤，
   因而本参考仅用于既有模型的苗期调度，不把它当作真实机械作业参数建议。
5. 数日后各场抽查0–3和60–63共8垄复查，后续持续观察两场；该参考不另行追肥、施药或灌水。
6. 成熟后检查R8、水分、天气及通行，共用收获机逐场收完128垄，按来源形成32个批次，
   必要干燥后安全入库；核对各场管理投入和公共库存。

调度边界：两场共用北京时间。田间工具阻塞顺序执行，设备需求重叠时排队；充电异步。
没有跨场路程、并行派工或忙锁模拟。固定参考用真实工具执行/回放核对，不是最高产搜索。
基本任务说明全田管理范围，详细任务提供参考窗口和抽样安排；两档物理初态、工具和Oracle相同。

农艺流程参考：NCSU大豆杂草管理指南关于适时浅中耕与避免伤根的说明。
https://content.ces.ncsu.edu/north-carolina-soybean-production-guide/soybean-weed-management
资料支持苗期观察/管理原则，不是当前模型杂草压力或85%削减率的标定依据。

运行：
    PYTHONHASHSEED=0 python -m fairy.cli \
        -s scenario_two_farm_soybean_shared_weeding \
        --build-oracle --run-oracle-tools --replay \
        --output-dir /tmp/two-farm-soybean-shared-weeding
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

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
from fairy.types import EventRegisterer


SCENARIO_ID = "scenario_two_farm_soybean_shared_weeding"
WEATHER_PROFILE = "harbin_baseline_2026_seed_101"
NUM_RIDGES = 64
FIELD_LENGTH_M = 268.0
RIDGE_WIDTH_M = 1.1
SEED_TYPE = "HEINONG84"
SEED_SPACING_CM = 8.0
PLANTING_DEPTH_CM = 4.0
BASE_FERTILIZER_KG = 200.0

BASIC_BRIEFING = """
管理哈尔滨同地区farm_a、farm_b两个大豆地块的完整季节，从裸地到安全收获入库。
两场各64垄0–63、垄长268m、垄距1.1m、一垄两行，各1.88672ha；品种HEINONG84。
两场都有分布较广的杂草历史，A稍重；苗期分别检查全田长势，以分布在不同区域的地面抽样核实杂草，
安排两场各0–63垄的全田机械除草。无人机低NDVI不是杂草诊断，地面抽查只代表实际覆盖的垄。

FarmA/FarmB各自提供状态和作物规则。FarmA_Sensor/FarmA_Irrigation固定服务A，
FarmB_Sensor/FarmB_Irrigation固定服务B。Tractor、Mavic3M、Robot0各只有一台；Warehouse唯一共享。
移动田间工具必须指定farm_id；装料、退料、加油操作共享仓库与设备，不选农场。
两场同一北京时间，操作/等待同时推进两场；田间工具顺序调用，充电异步，没有跨场路程模型。
苗期两场的观察和机械除草需求可能重叠，要先比较两场证据，再排共享设备的顺序。

本任务要求两场全田机械除草，处理前核对作物阶段、地面证据、可通行土壤、机具、电量和燃油。
按设备单次能力分批作业，覆盖各场全部64垄；处理后复查，不能把抽样垄数当作全田作业范围。
其余水肥药管理看实际证据，不要求把可用工具全部用一遍。分别完成整地、播种、观察、管理和收获。
收获须核对各场成熟度、籽粒水分和天气；切场前卸清粮箱，批次保留来源，必要干燥后安全入库。
最后分别报告观察依据、实际操作范围、用料、产量和共享库存。本场景不实现validate。
""".strip()

DETAILED_BRIEFING = """
管理farm_a、farm_b两个完整黑农84大豆季。两场各64垄0–63，268m×1.1m×64=1.88672ha，
每垄两行，从裸地开始；参考播深4cm、株距8cm，每场428800粒HEINONG84。
两场同区域天气和保水黑土，初始营养一致；两场全田均有杂草历史，A略重。
这是巡查线索，不是现时诊断；分别观察冠层、土壤和作物阶段，并用地面检出/置信度核实杂草。

每场独立固定传感器与灌溉，Tractor、Mavic3M、Robot0和Warehouse各一套共用。
移动作业传farm_id；补料、加油、退料不传。共享时钟使用北京时间，田间作业顺序执行，充电异步。

参考workflow：
1. 查两场规则/土壤及公共天气/库存；逐场平地、200kg底肥、起垄，挂soybean_planter，每趟4垄播种。
2. 六月初查出苗；0–3垄抽查不等于检查全场。苗期管理窗口先分别读两场阶段和墒情、冠层。
3. 参考6/12有雨，先查天气和土壤，等三天再复核；6/15为V3且可通行时进入观察/中耕窗口。
   每场航测全64垄，Robot分别抽查0–3、20–23、40–43、60–63四个分布样带，共16垄。
   无人机一次全田耗64%电，充电可由A地面检查覆盖。机器人每场耗80%电，A后必须充满再查B。
   A后Robot充电时先航测B，再补足剩余充电等待。地面检查同时看杂草、病虫和出苗，低置信阴性不等于排除。
4. 两场跨区证据齐全且作物处苗期、土壤可通行时，挂cultivator，同一拖拉机先A再B中耕全田。
   每场7趟：0–9、10–19、20–29、30–39、40–49、50–59、60–63，合计14趟、128垄，机耕耗油28L。
5. 数日后各场复查0–3和60–63共8垄；后续在结荚/灌浆窗口看天气、墒情和健康。参考不追加追肥、药剂或灌溉，
   如实际观测不同则重新判断；不承诺一次中耕永久无草，也不宣称当天冠层立刻恢复。
6. 九月核对两场R8、含水率≤18%、无雨且可通行，挂harvester，每趟4垄，逐趟卸到唯一batch_id，
   必要干燥至13%后安全入库。切场清空粮箱，最后核对128垄、32批来源粮食及公共库存。

当前机械模型不区分杂草种类/株高或行内/行间，也未模拟作物机械损伤；日期和范围是固定初态参考，
不替代实际观测。当前两场工具串行，未模拟跨场行驶。本场景不实现validate，不以默认评分证明成功。
""".strip()


@register_scenario(SCENARIO_ID)
class ScenarioTwoFarmSoybeanSharedWeeding(Scenario):
    """两场苗期全田杂草管理，观察与中耕共用唯一移动设备。"""

    start_time = datetime(2026, 5, 15, 7, tzinfo=timezone(timedelta(hours=8))).timestamp()
    duration = 160 * 86400
    queue_based_loop = True
    time_increment_in_seconds = 60
    expects_agent_harvest = True
    additional_system_prompt = (
        "Manage both soybean farms for a full season. Fixed sensors and irrigation are farm-bound; "
        "Tractor, Mavic3M, Robot0 and Warehouse are shared. Observe both fields before scheduling "
        "whole-field mechanical weed control over ridges 0–63 in each farm. Use distributed "
        "ground samples to distinguish weeds from other "
        "causes of low canopy indices. Check stage, trafficability, coverage, battery and fuel. "
        "Operations are sequential and advance both farms; charging is asynchronous. Reinspect "
        "after treatment, preserve grain provenance and report actual outcomes. "
        "There is no scenario-specific validator."
    )

    def __post_init__(self) -> None:
        super().__post_init__()
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean: false or true")
        if not self.scenario_input:
            self.scenario_input = DETAILED_BRIEFING if self.detailed_briefing else BASIC_BRIEFING

    def init_and_populate_apps(self) -> None:
        """一次性声明几何、土壤、物料、设备、作物和公共时钟。"""
        self.aui = AgentUserInterface()
        self.weather = WeatherApp()
        self.weather.set_weather(
            date="2026-05-15",
            temp_c=17.0,
            humidity_pct=55.0,
            wind_speed_ms=2.0,
            rainfall_mm=0.0,
            solar_radiation=20.0 / 0.0864,
            forecast=[
                {
                    "date": "2026-05-16",
                    "temp_c": 17.5,
                    "humidity_pct": 55.0,
                    "wind_speed_ms": 2.0,
                    "rainfall_mm": 0.0,
                    "solar_radiation": 20.5 / 0.0864,
                }
            ],
        )
        self.farm_a = FarmWorldApp(
            name="FarmA",
            farm_id="farm_a",
            crop_id="soybean",
            cultivar_id=SEED_TYPE,
            field_length_m=FIELD_LENGTH_M,
            ridge_width_m=RIDGE_WIDTH_M,
            rows_per_ridge=2,
        )
        self.farm_b = FarmWorldApp(
            name="FarmB",
            farm_id="farm_b",
            crop_id="soybean",
            cultivar_id=SEED_TYPE,
            field_length_m=FIELD_LENGTH_M,
            ridge_width_m=RIDGE_WIDTH_M,
            rows_per_ridge=2,
        )
        self.sensor_a = SensorApp(self.farm_a, name="FarmA_Sensor")
        self.sensor_b = SensorApp(self.farm_b, name="FarmB_Sensor")
        self.irrigation_a = IrrigationApp(self.farm_a, self.weather, name="FarmA_Irrigation")
        self.irrigation_b = IrrigationApp(self.farm_b, self.weather, name="FarmB_Irrigation")
        self.warehouse = WarehouseApp(
            name="Warehouse",
            stock=WarehouseStock(
                seed_stock={SEED_TYPE: 1_000_000},
                pesticide_liters=40.0,
                fertilizer_kg=500.0,
                fuel_liters=800.0,
            ),
            max_storage_moisture_pct=13.5,
            storage_capacity_kg=30_000.0,
        )
        self.farm_environment = FarmEnvironment(
            [
                FarmContext("farm_a", self.farm_a, self.weather, self.sensor_a, self.irrigation_a),
                FarmContext("farm_b", self.farm_b, self.weather, self.sensor_b, self.irrigation_b),
            ],
            self.weather,
            warehouse=self.warehouse,
            start_time=self.start_time,
            timezone_name="Asia/Shanghai",
        )
        self.tractor = SharedTractorApp(
            self.farm_environment,
            name="Tractor",
            equipment=TractorEquipment(
                implements=(*DEFAULT_TRACTOR_IMPLEMENTS, "soybean_planter"),
                ridging_implement="furrower",
            ),
        )
        self.mavic = SharedDroneApp(
            self.farm_environment,
            name="Mavic3M",
            description="两场共用的唯一多光谱无人机",
            speed_ms=5.0,
            effective_ridges_per_pass=7,
            battery_pct_per_ridge=1.0,
        )
        self.robot = SharedRobotApp(self.farm_environment, name="Robot0")
        self.system = SystemApp()
        self.system.attach_farm_environment(self.farm_environment)
        self.shared_equipment = [self.tractor, self.mavic, self.robot]
        self.apps = [
            self.aui,
            self.weather,
            self.warehouse,
            self.farm_a,
            self.farm_b,
            self.sensor_a,
            self.sensor_b,
            self.irrigation_a,
            self.irrigation_b,
            *self.shared_equipment,
            self.system,
        ]

        # 两场均为全田杂草背景，A略重；土壤、营养、品种和区域天气相同。
        black_soil = SoilHydraulicModifier(
            root_depth_m=1.45,
            field_capacity_vwc=0.37,
            top_drainage_rate=0.22,
            root_drainage_rate=0.03,
            rainfall_capture_efficiency=0.95,
            irrigation_efficiency=0.90,
            max_infiltration_mm_day=80.0,
        )
        for farm, weed_pressure in (
            (self.farm_a, 0.22),
            (self.farm_b, 0.19),
        ):
            # 只收紧本场景的机具约束；不改变旧大豆场景的作业规则。
            farm.crop_definition = replace(
                farm.crop_definition,
                planting_rules=replace(farm.crop_definition.planting_rules, required_implement="soybean_planter"),
                harvest_rules=replace(farm.crop_definition.harvest_rules, required_implement="harvester"),
            )
            farm._sim_date = "2026-05-15"
            farm.set_season_phase("full_season")
            farm.completed_prep_ops = []
            for ridge in farm._ridges:
                ridge.planted = ridge.harvested = False
                ridge.soil_vwc = 0.26 + ((ridge.ridge_id % 5) - 2) * 0.002
                ridge.soil_temp_c = 13.0 + (ridge.ridge_id % 4) * 0.2
                ridge.nutrient_index = 0.82
                ridge.stand_fraction = 1.0
                ridge.pest_pressure_base = ridge.pest_pressure = 0.01
                ridge.disease_pressure_base = ridge.disease_pressure = 0.01
            farm.configure_physics_profile(
                WEATHER_PROFILE,
                location="Harbin/Heilongjiang",
                seed_type=SEED_TYPE,
                cultivar="黑农84",
                start_date="2026-05-15",
            )
            farm.physics.profile = deepcopy(farm.physics.profile)
            # 在setup中一次性初始化，不在workflow中强制抬高杂草或改写产量。
            farm.physics.biotic.set_pressure(
                list(range(NUM_RIDGES)), weed_pressure=weed_pressure, insect_pressure=0.01, disease_pressure=0.01
            )
            farm.physics.soil.set_hydraulic_modifiers({rid: black_soil for rid in range(NUM_RIDGES)})
            farm.configure_management_regime(
                regime="conventional",
                irrigation_quota_mm_total=20.0,
                fertilizer_quota_kg=250.0,
            )
        for app in self.apps:
            app.register_time_manager(self.farm_environment.time_manager)
            app.set_seed(self.seed)

    def build_events_flow(self):
        """固定参考事件图：苗期同窗观察 -> 共用中耕 -> 复查 -> 收储。

        capture_mode只登记事件，不执行观测、不读取未来状态。参考路径没有隐藏分支；
        每个工具调用及其顺序在本方法中完整展开，Engine负责执行和导出Oracle。
        """
        farms = (("farm_a", self.farm_a, self.sensor_a), ("farm_b", self.farm_b, self.sensor_b))
        with EventRegisterer.capture_mode() as events:
            previous = self.aui.send_message_to_agent(content=self.scenario_input).with_id("briefing")

            # 1. 播前检查与准备。两场物料从同一个仓库扣减，拖拉机只有一套运行状态。
            previous = self.weather.get_current_weather().oracle().with_id("prep_weather").depends_on(previous)
            previous = self.weather.get_forecast(days=4).oracle().with_id("prep_forecast").depends_on(previous)
            previous = self.warehouse.get_inventory().oracle().with_id("prep_inventory").depends_on(previous)
            for farm_id, farm, sensor in farms:
                previous = farm.get_crop_capabilities().oracle().with_id(f"prep_{farm_id}_rules").depends_on(previous)
                previous = sensor.read_soil_sensors().oracle().with_id(f"prep_{farm_id}_soil").depends_on(previous)
                previous = farm.get_management_status().oracle().with_id(f"prep_{farm_id}_budget").depends_on(previous)
                previous = self.tractor.get_status().oracle().with_id(f"prep_{farm_id}_tractor").depends_on(previous)
                previous = self.tractor.refuel(100.0).oracle().with_id(f"prep_{farm_id}_refuel").depends_on(previous)
                previous = (
                    self.tractor.attach_implement("grader")
                    .oracle()
                    .with_id(f"prep_{farm_id}_grader")
                    .depends_on(previous)
                )
                previous = self.tractor.level(farm_id).oracle().with_id(f"prep_{farm_id}_level").depends_on(previous)
                previous = (
                    self.tractor.detach_implement()
                    .oracle()
                    .with_id(f"prep_{farm_id}_detach_grader")
                    .depends_on(previous)
                )
                previous = (
                    self.tractor.load_fertilizer(BASE_FERTILIZER_KG)
                    .oracle()
                    .with_id(f"prep_{farm_id}_load_base")
                    .depends_on(previous)
                )
                previous = (
                    self.tractor.base_fertilize(farm_id).oracle().with_id(f"prep_{farm_id}_base").depends_on(previous)
                )
                previous = (
                    self.tractor.attach_implement("furrower")
                    .oracle()
                    .with_id(f"prep_{farm_id}_furrower")
                    .depends_on(previous)
                )
                previous = (
                    self.tractor.form_ridges(farm_id, RIDGE_WIDTH_M)
                    .oracle()
                    .with_id(f"prep_{farm_id}_ridges")
                    .depends_on(previous)
                )
                previous = (
                    self.tractor.detach_implement()
                    .oracle()
                    .with_id(f"prep_{farm_id}_detach_furrower")
                    .depends_on(previous)
                )
                previous = (
                    self.tractor.attach_implement("soybean_planter")
                    .oracle()
                    .with_id(f"plant_{farm_id}_planter")
                    .depends_on(previous)
                )
                for start in range(0, NUM_RIDGES, 4):
                    end = start + 3
                    count = farm.plants_per_ridge_from_spacing(SEED_SPACING_CM) * 4
                    previous = (
                        self.tractor.load_seeds(SEED_TYPE, count)
                        .oracle()
                        .with_id(f"plant_{farm_id}_load_{start}_{end}")
                        .depends_on(previous)
                    )
                    previous = (
                        self.tractor.plant_seeds(farm_id, start, end, PLANTING_DEPTH_CM, SEED_SPACING_CM)
                        .oracle()
                        .with_id(f"plant_{farm_id}_{start}_{end}")
                        .depends_on(previous)
                    )
                previous = (
                    self.tractor.detach_implement()
                    .oracle()
                    .with_id(f"plant_{farm_id}_detach_planter")
                    .depends_on(previous)
                )
                previous = (
                    self.tractor.return_supplies()
                    .oracle()
                    .with_id(f"plant_{farm_id}_return_seed")
                    .depends_on(previous)
                )

            # 2. 出苗观察：先抽查0–3垄确认建植，尚未完成全田分布样带调查。
            previous = (
                self.system.advance_time(days=16, hours=14).oracle().with_id("wait_emergence").depends_on(previous)
            )
            previous = self.weather.get_current_weather().oracle().with_id("emergence_weather").depends_on(previous)
            for farm_id, farm, sensor in farms:
                previous = (
                    farm.get_ridge_range_state(0, 63)
                    .oracle()
                    .with_id(f"emergence_{farm_id}_state")
                    .depends_on(previous)
                )
                previous = (
                    sensor.read_soil_sensors().oracle().with_id(f"emergence_{farm_id}_soil").depends_on(previous)
                )
                previous = (
                    self.robot.inspect_emergence(farm_id, 0, 3)
                    .oracle()
                    .with_id(f"emergence_{farm_id}_ground")
                    .depends_on(previous)
                )
            previous = self.robot.charge().oracle().with_id("emergence_charge_robot").depends_on(previous)

            # 3. 同窗管理：取得两场证据，再给同一拖拉机排队；充电与地面观察重叠。
            previous = self.system.advance_time(days=11).oracle().with_id("wait_weeding_window").depends_on(previous)
            previous = (
                self.weather.get_current_weather().oracle().with_id("weeding_rainy_weather").depends_on(previous)
            )
            previous = (
                self.weather.get_forecast(days=4).oracle().with_id("weeding_rainy_forecast").depends_on(previous)
            )
            for farm_id, farm, sensor in farms:
                previous = (
                    sensor.read_soil_sensors().oracle().with_id(f"weeding_rainy_{farm_id}_soil").depends_on(previous)
                )
            previous = (
                self.system.advance_time(days=3).oracle().with_id("wait_rain_and_field_drainage").depends_on(previous)
            )
            previous = self.weather.get_current_weather().oracle().with_id("weeding_weather").depends_on(previous)
            previous = self.weather.get_forecast(days=4).oracle().with_id("weeding_forecast").depends_on(previous)
            for farm_id, farm, sensor in farms:
                previous = (
                    farm.get_ridge_range_state(0, 63)
                    .oracle()
                    .with_id(f"weeding_{farm_id}_before")
                    .depends_on(previous)
                )
                previous = sensor.read_soil_sensors().oracle().with_id(f"weeding_{farm_id}_soil").depends_on(previous)
                previous = (
                    sensor.read_canopy_sensors().oracle().with_id(f"weeding_{farm_id}_canopy").depends_on(previous)
                )
                previous = (
                    farm.get_management_status().oracle().with_id(f"weeding_{farm_id}_budget").depends_on(previous)
                )
            # 全田航测 + 四个分布样带。地面实际覆盖16/64垄，不冒充逐垄检查。
            for farm_id in ("farm_a", "farm_b"):
                previous = (
                    self.mavic.check_status().oracle().with_id(f"weeding_{farm_id}_drone_ready").depends_on(previous)
                )
                previous = (
                    self.mavic.fly_survey(farm_id, 0, 63)
                    .oracle()
                    .with_id(f"weeding_{farm_id}_flight")
                    .depends_on(previous)
                )
                previous = self.mavic.charge().oracle().with_id(f"weeding_{farm_id}_charge_drone").depends_on(previous)
                if farm_id == "farm_b":
                    # A抽查后机器人需60分钟充满，B航测已用9分20秒；再等51分钟留20秒余量。
                    previous = (
                        self.system.advance_time(minutes=51)
                        .oracle()
                        .with_id("wait_robot_charge_between_farms")
                        .depends_on(previous)
                    )
                previous = (
                    self.robot.check_status().oracle().with_id(f"weeding_{farm_id}_robot_ready").depends_on(previous)
                )
                for start in (0, 20, 40, 60):
                    previous = (
                        self.robot.inspect_crop_health(farm_id, start, start + 3)
                        .oracle()
                        .with_id(f"weeding_{farm_id}_ground_{start}_{start + 3}")
                        .depends_on(previous)
                    )
                previous = self.robot.charge().oracle().with_id(f"weeding_{farm_id}_charge_robot").depends_on(previous)
            previous = self.tractor.get_status().oracle().with_id("weeding_shared_tractor").depends_on(previous)
            previous = self.tractor.refuel(100.0).oracle().with_id("weeding_refuel").depends_on(previous)
            previous = (
                self.tractor.attach_implement("cultivator")
                .oracle()
                .with_id("weeding_attach_cultivator")
                .depends_on(previous)
            )
            for farm_id, farm, sensor in farms:
                previous = (
                    self.weather.get_current_weather()
                    .oracle()
                    .with_id(f"cultivate_{farm_id}_weather")
                    .depends_on(previous)
                )
                previous = (
                    sensor.read_soil_sensors().oracle().with_id(f"cultivate_{farm_id}_soil").depends_on(previous)
                )
                # 单趟最多10垄；末趟60–63只作业4垄，不重复前面的垄。
                for start in range(0, NUM_RIDGES, 10):
                    end = min(start + 9, NUM_RIDGES - 1)
                    previous = (
                        self.tractor.mechanical_weed_control(farm_id, start, end)
                        .oracle()
                        .with_id(f"cultivate_{farm_id}_{start}_{end}")
                        .depends_on(previous)
                    )
                previous = (
                    farm.get_management_status()
                    .oracle()
                    .with_id(f"cultivate_{farm_id}_budget_after")
                    .depends_on(previous)
                )
            previous = (
                self.tractor.detach_implement().oracle().with_id("weeding_detach_cultivator").depends_on(previous)
            )

            # 4. 处理后复查；只报告实际覆盖，不能宣称永久除净或瞬时恢复生物量。
            # 当日全田中耕约17:30完成；2天15小时后在第三天上午复查，避免排到晚间。
            previous = (
                self.system.advance_time(days=2, hours=15)
                .oracle()
                .with_id("wait_weeding_recheck")
                .depends_on(previous)
            )
            for farm_id, farm, sensor in farms:
                previous = (
                    farm.get_ridge_range_state(0, 63).oracle().with_id(f"recheck_{farm_id}_state").depends_on(previous)
                )
                previous = sensor.read_soil_sensors().oracle().with_id(f"recheck_{farm_id}_soil").depends_on(previous)
                previous = (
                    sensor.read_canopy_sensors().oracle().with_id(f"recheck_{farm_id}_canopy").depends_on(previous)
                )
                for start in (0, 60):
                    previous = (
                        self.robot.inspect_crop_health(farm_id, start, start + 3)
                        .oracle()
                        .with_id(f"recheck_{farm_id}_ground_{start}_{start + 3}")
                        .depends_on(previous)
                    )
            previous = self.robot.charge().oracle().with_id("recheck_charge_robot").depends_on(previous)

            # 5. 后续两场持续观察。等待留出地面巡查的作业时间，让三次复查均落在上午。
            # 固定参考为7/10、7/30、8/20；该保水正常年不额外制造水肥药任务。
            for phase, wait_days, wait_hours in (
                ("flowering", 21, 21),
                ("pod_fill", 19, 22),
                ("late_fill", 20, 22),
            ):
                previous = (
                    self.system.advance_time(days=wait_days, hours=wait_hours)
                    .oracle()
                    .with_id(f"wait_{phase}")
                    .depends_on(previous)
                )
                previous = self.weather.get_current_weather().oracle().with_id(f"{phase}_weather").depends_on(previous)
                previous = self.weather.get_forecast(days=4).oracle().with_id(f"{phase}_forecast").depends_on(previous)
                for farm_id, farm, sensor in farms:
                    previous = (
                        farm.get_ridge_range_state(0, 63)
                        .oracle()
                        .with_id(f"{phase}_{farm_id}_state")
                        .depends_on(previous)
                    )
                    previous = (
                        sensor.read_soil_sensors().oracle().with_id(f"{phase}_{farm_id}_soil").depends_on(previous)
                    )
                    previous = (
                        sensor.read_canopy_sensors().oracle().with_id(f"{phase}_{farm_id}_canopy").depends_on(previous)
                    )
                    start = 20 if farm_id == "farm_a" else 44
                    previous = (
                        self.robot.check_status()
                        .oracle()
                        .with_id(f"{phase}_{farm_id}_robot_ready")
                        .depends_on(previous)
                    )
                    previous = (
                        self.robot.inspect_crop_health(farm_id, start, start + 3)
                        .oracle()
                        .with_id(f"{phase}_{farm_id}_ground")
                        .depends_on(previous)
                    )
                previous = self.robot.charge().oracle().with_id(f"{phase}_charge_robot").depends_on(previous)

            # 6. 九月共用收获机，先核查两场，再逐场重新核对天气和通行。
            # 等待到参考成熟窗口；执行时仍核对每场实际阶段、含水和天气。
            previous = (
                self.system.advance_time(days=21, hours=22)
                .oracle()
                .with_id("wait_harvest_window")
                .depends_on(previous)
            )
            for farm_id, farm, sensor in farms:
                previous = (
                    farm.get_ridge_range_state(0, 63)
                    .oracle()
                    .with_id(f"harvest_{farm_id}_maturity")
                    .depends_on(previous)
                )
                previous = sensor.read_soil_sensors().oracle().with_id(f"harvest_{farm_id}_soil").depends_on(previous)
            previous = (
                self.tractor.attach_implement("harvester")
                .oracle()
                .with_id("harvest_attach_shared_header")
                .depends_on(previous)
            )
            for farm_id, farm, sensor in farms:
                previous = (
                    self.weather.get_current_weather()
                    .oracle()
                    .with_id(f"harvest_{farm_id}_weather")
                    .depends_on(previous)
                )
                previous = (
                    self.weather.get_forecast(days=3)
                    .oracle()
                    .with_id(f"harvest_{farm_id}_forecast")
                    .depends_on(previous)
                )
                previous = (
                    self.tractor.refuel(100.0).oracle().with_id(f"harvest_{farm_id}_refuel").depends_on(previous)
                )
                for start in range(0, NUM_RIDGES, 4):
                    end = start + 3
                    batch_id = f"{farm_id}_{start:02d}_{end:02d}"
                    previous = (
                        self.tractor.harvest(farm_id, start, end)
                        .oracle()
                        .with_id(f"harvest_{batch_id}")
                        .depends_on(previous)
                    )
                    previous = (
                        self.tractor.unload_grain(batch_id).oracle().with_id(f"unload_{batch_id}").depends_on(previous)
                    )
                    previous = (
                        self.warehouse.dry_grain(batch_id, target_moisture_pct=13.0)
                        .oracle()
                        .with_id(f"dry_{batch_id}")
                        .depends_on(previous)
                    )
                    previous = (
                        self.warehouse.store_grain(batch_id).oracle().with_id(f"store_{batch_id}").depends_on(previous)
                    )
            previous = self.tractor.detach_implement().oracle().with_id("harvest_detach_header").depends_on(previous)

            # 8. 结账只陈述真实结果；场景没有成功/失败评分实现。
            for farm_id, farm, sensor in farms:
                previous = farm.get_farm_overview().oracle().with_id(f"final_{farm_id}_overview").depends_on(previous)
                previous = (
                    farm.get_management_status().oracle().with_id(f"final_{farm_id}_budget").depends_on(previous)
                )
            previous = self.warehouse.get_grain_batches().oracle().with_id("final_batches").depends_on(previous)
            previous = self.warehouse.get_inventory().oracle().with_id("final_inventory").depends_on(previous)
            previous = self.tractor.get_status().oracle().with_id("final_tractor").depends_on(previous)
            self.aui.send_message_to_user(
                content="双场大豆共享设备参考流程结束。请按工具结果核对两场观察、14趟128垄全田中耕、128垄收获、32个来源批次和公共库存；本场景未实现validate，不能据默认评分声称任务成功。",
            ).oracle().with_id("report").depends_on(previous)
        self.events = events
        return events

    # 按要求不实现 validate；继承基类的 None，运行报告默认状态不是任务评分。
