"""双地块大豆全季：轻度局部肥力差异，同窗巡查和追肥共用设备。

本文件独立定义全部初始化、两档任务和 build_events_flow；不导入其他场景。
复用现有作物物理、天气、App 和设备工具，不修改引擎，不实现 validate。

初始化（所有差异在开季设置，季中不改写长势或产量）：
- 北京时间 2026-05-15 07:00，哈尔滨同地区，两场均未整地、未播种。
- farm_a、farm_b 各 64 垄，268m × 1.1m × 64 = 18,867.2m² = 1.88672ha；
  每垄两行，HEINONG84，株距8cm、播深4cm，每场需428,800粒种子。
- 同一 seed101 合成天气、同样的保水黑土；不是2026年真实气象或田间标定。
- 正常区初始营养指数0.82；A20–39为0.66，B40–59为0.72，A相对更弱。
  这是模型肥力指数，不是土壤检测的纯氮含量。病虫压力均0.01，无强制暴发。
- 每场独立传感器和固定灌溉；只建一个共享仓库、一台拖拉机、一架无人机、
  一台机器人。每场备用水额度20mm、肥料产品额度300kg；仓库见初始化代码。

参考 workflow（日期是固定初态下的巡查窗口，实际作业必须看工具结果）：
1. 逐场核对、平地、200kg底肥、起垄、64垄播种；显式挂载大豆播种机。
2. 六月初两场出苗检查：全田多光谱 + 各4垄地面抽查，共享电池连续消耗。
3. 六月下旬两场固定传感器和逐垄状态复查，记录各自低肥区的发展。
4. 七月上旬两场同时进入营养复核窗口。7/8雨天先读天气和墒情，等两天再复核；
   不顶雨飞行、不让拖拉机强行进湿田。7/10先读两场状态，再A全田航测、充电，
   充电期间Robot抽查A28–31；该任务46分40秒，覆盖无人机30分钟充电。
   随后B全田航测、Robot抽查B48–51。两地都观察后才排共享拖拉机作业。
   固定参考先处理较弱A20–39，再B40–59，各2kg/垄、40kg产品，各分两趟。
   不调用全田水肥接口绕过共享拖拉机，不给正常区搭便车追肥。
5. 立即复核公开营养指数，次日查土壤与冠层；不能声称NDVI立刻恢复。
6. 七月底、八月下旬分别检查墒情、预报和健康。保水正常年参考不调用固定灌溉或施药；
   Agent若观测到新的证据，仍可使用本场固定灌溉或共享设备处理。
7. 9/11早晨分别确认R8、籽粒水分≤18%、无雨且可通行，再共用收获机逐场收割。
   每趟4垄，独立来源批次、必要干燥至13%、安全入库；最后核对两场和公共账。

调度边界：当前田间工具是阻塞顺序调用，两场一起经过作业时间；充电异步。
这里是重叠需求下的串行排队，不是并行派工/忙锁测试；未建模跨场路程。
两档任务均要求季内颗粒肥追施使用共享拖拉机。原有Farm.apply_fertigation仍在工具集中，
本场景不改App接口；不以该直达接口替代设备作业是任务约束，没有validate强制评分。
追肥沿用现有FERTIGATION映射，每目标垄附带0.06667mm模型载水；不是纯营养实验。
Oracle是经过实际工具运行核对的固定参考，不是运行时自动分支或最高产优化器。
导出流程本身不执行工具；Engine执行/回放相同事件，保留原有大豆收获损失口径。

运行（不调用模型、不执行任务评分）：
    PYTHONHASHSEED=0 python -m fairy.cli \
        -s scenario_two_farm_soybean_shared_management \
        --build-oracle --run-oracle-tools --replay \
        --output-dir /tmp/two-farm-soybean-shared-management
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


SCENARIO_ID = "scenario_two_farm_soybean_shared_management"
WEATHER_PROFILE = "harbin_baseline_2026_seed_101"
NUM_RIDGES = 64
FIELD_LENGTH_M = 268.0
RIDGE_WIDTH_M = 1.1
SEED_TYPE = "HEINONG84"
SEED_SPACING_CM = 8.0
PLANTING_DEPTH_CM = 4.0
BASE_FERTILIZER_KG = 200.0
TOPDRESS_KG_PER_RIDGE = 2.0  # 模拟肥料产品；不是现实纯氮施用建议。

BASIC_BRIEFING = """
管理哈尔滨同一地区farm_a、farm_b两个大豆地块的完整季节，从裸地到收获安全入库。
两场均64垄（各自0–63）、垄长268m、垄距1.1m、每垄两行，各1.88672ha，品种HEINONG84。
两场同天气、保水黑土，各有一片肥力偏低区域，A的历史肥力更弱；需要观测定位和复核，
不能只凭档案施肥，也不能把一场的观测当成另一场。没有预设必须灌水或施药。

FarmA/FarmB分别提供farm_a/farm_b状态、作物规则和额度。FarmA_Sensor、FarmA_Irrigation
只服务A；FarmB_Sensor、FarmB_Irrigation只服务B。Tractor、Mavic3M、Robot0各一台，两场共用。
Warehouse是唯一共享物料和粮食仓库。移动田间作业指定farm_id；装料、退料、加油不选农场。
两场同一北京时间，作业或等待会同时推进两场；田间工具顺序执行，充电可以异步进行。
管理窗口可能重叠，要根据各场需求安排设备、电量和用料，避免处理完一场却漏掉另一场。
本任务的季内颗粒肥追施使用共享Tractor，不用FarmA/FarmB.apply_fertigation代替设备作业。

分别观察出苗、营养、墒情、健康和成熟度；处理前记录依据，处理后复查实际效果。
收获两场全部垄，粮食按来源场/品种/垄号分批，必要干燥后安全入库，清空种箱和粮箱。
最后分别报告观察、管理范围、实际投入与产量，并核对公共库存；地面抽查不代表全田排查。
本场景不实现validate，不把默认评分状态当成完成证据。
""".strip()

DETAILED_BRIEFING = """
管理哈尔滨同一地区farm_a、farm_b的完整黑农84大豆季。两场均从裸地开始，各64垄0–63，
垄长268m、垄距1.1m、一垄两行，各1.88672ha。参考播深4cm、株距8cm，每场428800粒HEINONG84。
正常区肥力较好；A20–39历史肥力较弱，B40–59轻度偏低。先观测再确认，不能把历史当当前诊断。
同一seed101合成天气、同样保水黑土，无预设强制病虫暴发；模拟结果不是现实田间预测。

FarmA/FarmB分别服务farm_a/farm_b。FarmA_Sensor/FarmA_Irrigation绑定A，
FarmB_Sensor/FarmB_Irrigation绑定B。Tractor、Mavic3M、Robot0各一台；Warehouse只有一个。
移动田间作业传farm_id，装料、退料、加油不传。每场备用水20mm、肥料产品额度300kg。
所有工具共用北京时间。田间作业顺序执行，跨场没有额外路程模型；充电异步。

参考工作安排：
1. 查询两场作物能力、土壤、天气/预报、共享库存和设备；逐场平地、施200kg底肥、按1.1m起垄。
   显式换挂soybean_planter，每趟4垄播种；每趟按需装26800粒，完成两场后才等待生长。
2. 六月初逐场检查出苗、全田多光谱和0–3垄地面抽查。一次64垄航测耗64%电，
   无人机一块电池不能连续完成两场；航测后charge，用Robot的4垄检查覆盖30分钟充电。
   Robot每4垄耗20%电、约46分40秒；观察covered/uncovered，不把抽查当全田健康结论。
3. 六月下旬两场营养和墒情复核。七月上旬先查天气和墒情，参考7/8下雨且土壤湿，
   暂不飞行和追肥，等两天再查。7/10重新读两场逐垄状态、传感器、公共天气/预报，
   比较各自低肥区与正常区。A全田航测后充电并检查A28–31，再B航测并检查B48–51。
   营养偏低、冠层和地面结果支持营养处理且土壤可通行，才安排同一台拖拉机追肥。
4. 本固定初态参考先A20–39、再B40–59，各2kg/垄肥料产品，共80kg一次装入共享料箱，
   各分两趟10垄。正常区不跟着追肥；不调用Farm.apply_fertigation绕开共享设备排队。
   立即复核营养指数，次日再查土壤/冠层；株体不会在一次施肥后立刻恢复全部长势。
5. 七月底、八月下旬继续分别看墒情、预报、阶段和健康。本正常年保水参考不额外灌溉施药，
   没有明确证据就不增加操作；不同实测支持处理时，使用正确农场的设施或共享设备并复查。
6. 九月先读两场完整成熟度/含水率、天气及通行；R8、籽粒水分≤18%、无雨且可通行才收。
   挂harvester逐场收，每趟最多4垄并卸粮到唯一batch_id，再必要干燥至13%并入库。
   切场前清空粮箱，批次保留来源和垄号。最后分别报告覆盖、观察依据、投入、产量及公共余料。

日期和剂量是固定种子的参考，不替代实测决策；本Oracle不宣称最高产。本场景不实现validate。
""".strip()


@register_scenario(SCENARIO_ID)
class ScenarioTwoFarmSoybeanSharedManagement(Scenario):
    """两场同季、局部轻量管理，观测和作业争用唯一的移动设备。"""

    start_time = datetime(2026, 5, 15, 7, tzinfo=timezone(timedelta(hours=8))).timestamp()
    duration = 160 * 86400
    queue_based_loop = True
    time_increment_in_seconds = 60
    expects_agent_harvest = True
    additional_system_prompt = (
        "Manage farm_a and farm_b through one soybean season with one shared clock, "
        "Tractor, Mavic3M, Robot0 and Warehouse. Fixed sensors and irrigation belong "
        "to their named farm. Observe both fields before assigning shared equipment, "
        "read tool conditions and battery coverage, recheck after treatment, and keep "
        "grain provenance separate. A field operation advances time for both farms; "
        "charging is asynchronous. Ground samples are not whole-field inspections. "
        "Use the shared Tractor for seasonal granular topdressing; do not substitute "
        "FarmA/FarmB.apply_fertigation for the assigned equipment operations. "
        "Calendar windows are guidance; actual observations determine actions. "
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
                fertilizer_kg=700.0,
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

        # 两场仅局部肥力不同；水力参数、品种和区域天气相同。
        black_soil = SoilHydraulicModifier(
            root_depth_m=1.45,
            field_capacity_vwc=0.37,
            top_drainage_rate=0.22,
            root_drainage_rate=0.03,
            rainfall_capture_efficiency=0.95,
            irrigation_efficiency=0.90,
            max_infiltration_mm_day=80.0,
        )
        for farm, weak_start, weak_end, weak_nutrient in (
            (self.farm_a, 20, 39, 0.66),
            (self.farm_b, 40, 59, 0.72),
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
                ridge.nutrient_index = weak_nutrient if weak_start <= ridge.ridge_id <= weak_end else 0.82
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
            farm.physics.soil.set_hydraulic_modifiers({rid: black_soil for rid in range(NUM_RIDGES)})
            farm.configure_management_regime(
                regime="conventional",
                irrigation_quota_mm_total=20.0,
                fertilizer_quota_kg=300.0,
            )
        for app in self.apps:
            app.register_time_manager(self.farm_environment.time_manager)
            app.set_seed(self.seed)

    def build_events_flow(self):
        """固定参考事件图：同窗观测 -> 单设备排队 -> 局部处理 -> 复查 -> 收储。

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

            # 2. 六月初出苗，两场都要无人机；地面任务覆盖无人机充电，避免空等。
            # 减去准备作业占用的夜间部分，让两场多光谱任务落在白天。
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
                    self.mavic.check_status().oracle().with_id(f"emergence_{farm_id}_drone_ready").depends_on(previous)
                )
                previous = (
                    self.mavic.fly_survey(farm_id, 0, 63)
                    .oracle()
                    .with_id(f"emergence_{farm_id}_flight")
                    .depends_on(previous)
                )
                previous = (
                    self.mavic.charge().oracle().with_id(f"emergence_{farm_id}_charge_drone").depends_on(previous)
                )
                previous = (
                    self.robot.check_status().oracle().with_id(f"emergence_{farm_id}_robot_ready").depends_on(previous)
                )
                previous = (
                    self.robot.inspect_emergence(farm_id, 0, 3)
                    .oracle()
                    .with_id(f"emergence_{farm_id}_ground_0_3")
                    .depends_on(previous)
                )
            previous = self.robot.charge().oracle().with_id("emergence_charge_robot").depends_on(previous)

            # 3. 六月下旬建立两场趋势；此时不抢先治疗，不假定弱冠层一定是缺肥。
            previous = self.system.advance_time(days=24).oracle().with_id("wait_vegetative").depends_on(previous)
            previous = self.weather.get_current_weather().oracle().with_id("vegetative_weather").depends_on(previous)
            for farm_id, farm, sensor in farms:
                previous = (
                    farm.get_ridge_range_state(0, 63)
                    .oracle()
                    .with_id(f"vegetative_{farm_id}_state")
                    .depends_on(previous)
                )
                previous = (
                    sensor.read_soil_sensors().oracle().with_id(f"vegetative_{farm_id}_soil").depends_on(previous)
                )
                previous = (
                    sensor.read_canopy_sensors().oracle().with_id(f"vegetative_{farm_id}_canopy").depends_on(previous)
                )

            # 4. 七月上旬同窗需求：先取得两地证据，再安排A/B共用拖拉机。
            previous = (
                self.system.advance_time(days=13)
                .oracle()
                .with_id("wait_shared_management_window")
                .depends_on(previous)
            )
            previous = (
                self.weather.get_current_weather().oracle().with_id("management_rainy_weather").depends_on(previous)
            )
            previous = (
                self.weather.get_forecast(days=4).oracle().with_id("management_rainy_forecast").depends_on(previous)
            )
            for farm_id, farm, sensor in farms:
                previous = (
                    sensor.read_soil_sensors()
                    .oracle()
                    .with_id(f"management_rainy_{farm_id}_soil")
                    .depends_on(previous)
                )
            previous = (
                self.system.advance_time(days=2).oracle().with_id("wait_rain_and_field_drainage").depends_on(previous)
            )
            previous = self.weather.get_current_weather().oracle().with_id("management_weather").depends_on(previous)
            previous = self.weather.get_forecast(days=4).oracle().with_id("management_forecast").depends_on(previous)
            for farm_id, farm, sensor in farms:
                previous = (
                    farm.get_ridge_range_state(0, 63)
                    .oracle()
                    .with_id(f"management_{farm_id}_before")
                    .depends_on(previous)
                )
                previous = (
                    sensor.read_soil_sensors().oracle().with_id(f"management_{farm_id}_soil").depends_on(previous)
                )
                previous = (
                    sensor.read_canopy_sensors().oracle().with_id(f"management_{farm_id}_canopy").depends_on(previous)
                )
                previous = (
                    farm.get_management_status().oracle().with_id(f"management_{farm_id}_budget").depends_on(previous)
                )
            for farm_id, sample_start in (("farm_a", 28), ("farm_b", 48)):
                previous = (
                    self.mavic.check_status()
                    .oracle()
                    .with_id(f"management_{farm_id}_drone_ready")
                    .depends_on(previous)
                )
                previous = (
                    self.mavic.fly_survey(farm_id, 0, 63)
                    .oracle()
                    .with_id(f"management_{farm_id}_flight")
                    .depends_on(previous)
                )
                previous = (
                    self.mavic.charge().oracle().with_id(f"management_{farm_id}_charge_drone").depends_on(previous)
                )
                previous = (
                    self.robot.check_status()
                    .oracle()
                    .with_id(f"management_{farm_id}_robot_ready")
                    .depends_on(previous)
                )
                previous = (
                    self.robot.inspect_crop_health(farm_id, sample_start, sample_start + 3)
                    .oracle()
                    .with_id(f"management_{farm_id}_health")
                    .depends_on(previous)
                )
            previous = self.robot.charge().oracle().with_id("management_charge_robot").depends_on(previous)
            previous = self.warehouse.get_inventory().oracle().with_id("management_shared_stock").depends_on(previous)
            previous = self.tractor.get_status().oracle().with_id("management_shared_tractor").depends_on(previous)
            previous = self.tractor.refuel(100.0).oracle().with_id("management_refuel").depends_on(previous)
            # 20垄×2kg×2场=80kg，低于500kg料箱；同一物料无需跨场退回再装。
            previous = (
                self.tractor.load_fertilizer(80.0)
                .oracle()
                .with_id("management_load_both_farms_80kg")
                .depends_on(previous)
            )
            for farm_id, farm, first in (("farm_a", self.farm_a, 20), ("farm_b", self.farm_b, 40)):
                for start in (first, first + 10):
                    previous = (
                        self.tractor.apply_fertilizer(farm_id, start, start + 9, TOPDRESS_KG_PER_RIDGE)
                        .oracle()
                        .with_id(f"topdress_{farm_id}_{start}_{start + 9}")
                        .depends_on(previous)
                    )
                previous = (
                    farm.get_ridge_range_state(0, 63)
                    .oracle()
                    .with_id(f"management_{farm_id}_after")
                    .depends_on(previous)
                )
                previous = (
                    self.tractor.get_status()
                    .oracle()
                    .with_id(f"management_{farm_id}_remaining_payload")
                    .depends_on(previous)
                )
            previous = (
                self.tractor.return_supplies().oracle().with_id("management_return_supplies").depends_on(previous)
            )

            # 5. 处理后次日检查；不重复消耗另一场的一天，也不宣称冠层立即恢复。
            previous = (
                self.system.advance_time(days=1).oracle().with_id("wait_management_recheck").depends_on(previous)
            )
            for farm_id, farm, sensor in farms:
                previous = (
                    farm.get_ridge_range_state(0, 63).oracle().with_id(f"recheck_{farm_id}_state").depends_on(previous)
                )
                previous = sensor.read_soil_sensors().oracle().with_id(f"recheck_{farm_id}_soil").depends_on(previous)
                previous = (
                    sensor.read_canopy_sensors().oracle().with_id(f"recheck_{farm_id}_canopy").depends_on(previous)
                )

            # 6. 结荚/灌浆与晚期复查：两场保水，不因为有设备就制造灌溉和药物任务。
            for phase, wait_days in (("pod_fill", 19), ("late_fill", 21)):
                previous = (
                    self.system.advance_time(days=wait_days).oracle().with_id(f"wait_{phase}").depends_on(previous)
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
                    previous = (
                        self.robot.check_status()
                        .oracle()
                        .with_id(f"{phase}_{farm_id}_robot_ready")
                        .depends_on(previous)
                    )
                    sample_start = 28 if farm_id == "farm_a" else 48
                    previous = (
                        self.robot.inspect_crop_health(farm_id, sample_start, sample_start + 3)
                        .oracle()
                        .with_id(f"{phase}_{farm_id}_health")
                        .depends_on(previous)
                    )
                previous = self.robot.charge().oracle().with_id(f"{phase}_charge_robot").depends_on(previous)

            # 7. 九月收获同样要共用一台机。先检查两场，再逐场重新核对天气和通行。
            # 固定参考8/20约14:15 -> 9/11约07:15，给两场收割留足同一白天。
            previous = (
                self.system.advance_time(days=21, hours=17)
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
                content="双场大豆共享设备参考流程结束。请按工具结果核对两场观察、局部追肥、128垄收获、32个来源批次和公共库存；本场景未实现validate，不能据默认评分声称任务成功。",
            ).oracle().with_id("report").depends_on(previous)
        self.events = events
        return events

    # 按要求不实现 validate；继承基类的 None，运行报告默认状态不是任务评分。
