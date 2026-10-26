"""双场大豆全季：A全田除草、B全田虫害管理，共享设备和物料调度。

这是新增独立场景：完整初始化、两档任务、build_events_flow均在本文件中，
不导入/继承其他场景，也不实现validate。

初始化：北京时间2026-05-15 07:00。两场各64垄、268m长、1.1m垄距、一垄两行，
各1.88672ha，从裸地开始种HEINONG84，参考播深4cm、株距8cm，各需428800粒。
同地区seed101合成天气、同样保水黑土、营养指数0.82；不是实测天气或田间标定。
A全田初始草压0.22，B草压0.015，病虫初始均0.01。
B的私有物理profile预置6/9单日外源虫害输入：全64垄虫压0.45，随后自然演化。
这项合成输入表示入侵压力，不是虫株数，也不是由天气模型预测；不会持续重置喷后虫压。
workflow不直接改写物理状态、作物生物量或产量。

共享资源：唯一Warehouse、Tractor、Mavic3M、Robot0；固定传感器/灌溉各场独立。
仓库100万粒种子、500kg肥料产品、600L模拟药液、800L燃油、30t粮仓。
喷施采用apply_pesticide标准剂量（当前8L/垄，全B需512L），避免以微量药获得完整效果。
现有药效不按剂量标定，库存没有产品/有效成分标签；升数是本模型操作单位，不是现实用药建议。

完整参考workflow：
1. 两场分别查土壤、作物规则和额度，检查公共天气/库存；共用拖拉机逐场整地、底肥、起垄、播种。
2. 六月初分别查出苗和墒情。6/12遇雨时读预报和土壤，等待到6/15 V3、无雨可通行后复核。
3. 航测各场全64垄，Robot各查0–3、20–23、40–43、60–63四个样带共16垄；
   对比A的杂草证据与B的虫害证据。低NDVI不直接诊断，样带也不等于全田逐垄检查。
   A地面检查覆盖无人机充电；Robot查完A后充电，利用这段时间航测B，再补足等待后查B。
4. 两场证据齐全后，在同一管理窗口优先完成天气约束更严格的B喷施：
   共享仓库装标准全田用量，挂sprayer，B0–63分7趟。记录用药、油量和残效，再退余料。
   随后卸sprayer、挂cultivator，A0–63分7趟。共14趟，128垄各完成与其问题匹配的操作。
5. 数日后各场复查0–3和60–63共8垄：A看杂草、B看虫害；继续在初花/结荚/灌浆期复核两场。
6. 九月分别核对R8、含水、天气和通行后共享收获机，128垄形成32个来源批次，必要干燥后安全入库。

工具阻塞串行，两场共享北京时间；充电异步，未模拟跨场交通时间或并行忙锁。
这是经过实际工具运行和回放核对的固定参考，不是最高产搜索或真实农药方案。

观察原则参考ISU苗期巡田资料：分别核对阶段、出苗、杂草和虫害迹象。
https://crops.extension.iastate.edu/encyclopedia/early-season-crop-scouting
资料不为本场虫压输入、检测阈值或标准喷液量提供田间标定。

运行：
    PYTHONHASHSEED=0 python -m fairy.cli \
        -s scenario_two_farm_soybean_weeding_pest_control \
        --build-oracle --run-oracle-tools --replay \
        --output-dir /tmp/two-farm-soybean-weeding-pests
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world.equipment import DEFAULT_TRACTOR_IMPLEMENTS, TractorEquipment
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp, PESTICIDE_L_PER_RIDGE
from fairy.apps.farm_world.irrigation_app import IrrigationApp
from fairy.apps.farm_world.sensor_app import SensorApp
from fairy.apps.farm_world.shared_drone_app import SharedDroneApp
from fairy.apps.farm_world.shared_robot_app import SharedRobotApp
from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.system import SystemApp
from fairy.physics.soil_engine import SoilHydraulicModifier
from fairy.physics.profiles import BioticOutbreak
from fairy.physics.biotic_pressure_engine import TreatmentType
from fairy.scenarios.registry import register_scenario
from fairy.scenarios.scenario import Scenario
from fairy.types import EventRegisterer


SCENARIO_ID = "scenario_two_farm_soybean_weeding_pest_control"
WEATHER_PROFILE = "harbin_baseline_2026_seed_101"
NUM_RIDGES = 64
FIELD_LENGTH_M = 268.0
RIDGE_WIDTH_M = 1.1
SEED_TYPE = "HEINONG84"
SEED_SPACING_CM = 8.0
PLANTING_DEPTH_CM = 4.0
BASE_FERTILIZER_KG = 200.0

BASIC_BRIEFING = f"""
管理哈尔滨同地区farm_a、farm_b两个完整大豆季，从裸地到安全收获入库。
两场均64垄0–63、垄长268m、垄距1.1m、每垄两行，各1.88672ha，品种HEINONG84。
A有全田杂草历史，B有苗期虫害入侵风险，两场需要不同的管理。分别观察全田长势，
用跨区地面样本核实杂草/虫害成因、置信度和生育期，再安排适合各场的全田作业和复查。
不能因两场都长势偏弱就使用相同处理，不能以低NDVI直接诊断或把抽样说成逐垄检查。

固定设施FarmA_Sensor/FarmA_Irrigation只服务A，FarmB_Sensor/FarmB_Irrigation只服务B。
Tractor、Mavic3M、Robot0各只有一台，Warehouse只有一个；移动作业必须指定farm_id，
装料/退料/加油操作共享设备与仓库，不指定农场。所有操作和等待同时推进两场北京时间。
田间工具顺序执行，充电异步，未模拟跨场交通时间。不同任务也会争用相同的设备和观察电量。

检查天气、土壤通行、共享机具、电量、燃油、物料和各场额度后排优先级，安排充电、装料和换机具。
喷施受无雨/风速等条件约束，中耕需可通行土壤。apply_pesticide固定消耗{PESTICIDE_L_PER_RIDGE:g}L/垄模拟药液；
这是设备消耗规则，库存没有现实产品标签，不能据此推导有效成分剂量或农田用药建议。
完成两场全田种植、按证据管理和复查；成熟后分场收割、切场卸清粮箱，粮食按来源干燥并安全入库。
最后分别报告观察证据、实际操作范围、投入、产量与共享库存。本场景不实现validate。
""".strip()

DETAILED_BRIEFING = f"""
管理farm_a、farm_b两个黑农84大豆完整季。每场64垄0–63，268m×1.1m×64=1.88672ha，一垄两行。
从裸地开始，参考4cm播深、8cm株距，每场428800粒HEINONG84；两场同区域天气和保水黑土。
田块档案：A全田杂草风险较高；B苗期有虫害入侵风险。档案是巡查线索，实际处理以观测为依据。

公共Warehouse、Tractor、Mavic3M、Robot0各一套；固定传感器和固定灌溉各场独立。
移动作业传farm_id，补料/退料/加油不传。共用北京时间，田间作业串行，充电异步。

参考workflow：
1. 查公共天气/库存、各场土壤/能力/额度，共用拖拉机逐场平地、200kg底肥、起垄，
   挂soybean_planter每趟4垄，完成两场各64垄播种；六月初分别检查出苗。
2. 参考6/12有雨，先看预报和两场土壤，等三天排水；6/15 V3复核后，分别航测全64垄，
   Robot各查0–3、20–23、40–43、60–63共16垄，比较A杂草与B虫害检出、置信度和压力分档。
3. 无人机每场耗64%电，A地面检查覆盖其充电。Robot每场16垄耗80%电；A后启动60分钟充电，
   先航测B，再等51分钟，确认Robot满电才查B；B后再充电，利用拖拉机作业时间完成充电。
4. 两场证据齐全后，优先处理无雨/低风窗口下的B虫害：装{NUM_RIDGES * PESTICIDE_L_PER_RIDGE:g}L模拟药液，
   挂sprayer，用apply_pesticide标准{PESTICIDE_L_PER_RIDGE:g}L/垄，0–63按最多10垄分7趟。
   药液量来自当前标准工具常量，不是有效成分剂量；不用极小自定义剂量绕过物料消耗。
5. B喷施后退余料，卸sprayer再挂cultivator；A0–63同样分7趟机械除草。两场共14趟，
   各覆盖全64垄且不重叠；共享拖拉机这14趟共耗28L燃油。不能把B喷药复制到A或把A中耕复制到B。
6. 数日后两场各复查0–3和60–63共8垄，A看杂草压力档位、B看虫害及残效，并在后续生育期继续复核。
   初始模型参考一次B喷施可维持后续风险受控，不表示现实中一次处理必然够用。
7. 九月分别核对R8、水分≤18%、无雨且可通行，挂harvester每趟4垄、逐趟卸入唯一来源batch_id，
   必要干燥至13%再安全入库；切场清空粮箱。最后核对128垄收获、32批粮食和各项物资。

参考日期与操作均需实际观测支持。药效和杂草削减是既有简化模型，没有商品药标签、行间杂草高度和机械伤根模拟。
本场景不实现validate，不以默认评分状态代替实际运行证据。
""".strip()


@register_scenario(SCENARIO_ID)
class ScenarioTwoFarmSoybeanWeedingPestControl(Scenario):
    """A除草、B虫害管理，同窗争用公共移动设备和物料。"""

    start_time = datetime(2026, 5, 15, 7, tzinfo=timezone(timedelta(hours=8))).timestamp()
    duration = 160 * 86400
    queue_based_loop = True
    time_increment_in_seconds = 60
    expects_agent_harvest = True
    additional_system_prompt = (
        "Manage both soybean farms for the full season with different observed needs: "
        "farm_a weed management and farm_b insect management. Fixed sensors and irrigation "
        "are farm-bound; Tractor, Mavic3M, Robot0 and Warehouse are shared. Observe both "
        "fields before scheduling treatments. Ground samples cover only visited ridges. "
        "Account for charging, shared payloads, implement changes and weather constraints. "
        "Use the standard pesticide tool dose in this reduced simulation, not a tiny dose "
        "to exploit its uncalibrated dose response. Operations are sequential and advance "
        "both farms. Reinspect after treatment, preserve grain provenance and report actual outcomes. "
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
                pesticide_liters=600.0,
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

        # A是全田杂草风险，B是苗期外源虫害；土壤、营养、品种和区域天气相同。
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
            (self.farm_b, 0.015),
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
            # 两场共用相同天气起点；事件仅写入本场私有profile，注册表不修改。
            farm.physics.profile.start_date = date(2026, 5, 15)
            farm.physics.profile.biotic_outbreaks = []
            if farm.farm_id == "farm_b":
                farm.physics.profile.biotic_outbreaks = [
                    BioticOutbreak(
                        pressure_type=TreatmentType.INSECTICIDE,
                        start_day_offset=(date(2026, 6, 9) - farm.physics.profile.start_date).days,
                        duration_days=1,
                        ridge_start=0,
                        ridge_end=63,
                        severity=0.45,
                        label="synthetic_seedling_insect_arrival",
                    )
                ]
            # 初态与B单日外源输入均在setup声明；workflow只调用公开工具。
            farm.physics.biotic.set_pressure(
                list(range(NUM_RIDGES)), weed_pressure=weed_pressure, insect_pressure=0.01, disease_pressure=0.01
            )
            farm.physics.soil.set_hydraulic_modifiers({rid: black_soil for rid in range(NUM_RIDGES)})
            farm.configure_management_regime(
                regime="conventional",
                irrigation_quota_mm_total=20.0,
                fertilizer_quota_kg=250.0,
                max_insecticide_applications=1,
            )
        for app in self.apps:
            app.register_time_manager(self.farm_environment.time_manager)
            app.set_seed(self.seed)

    def build_events_flow(self):
        """固定参考事件图：两场观察 -> B喷施 -> 换机具 -> A中耕 -> 分别复查与收储。

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
            previous = (
                self.system.advance_time(days=11).oracle().with_id("wait_management_window").depends_on(previous)
            )
            previous = self.weather.get_current_weather().oracle().with_id("scout_rainy_weather").depends_on(previous)
            previous = self.weather.get_forecast(days=4).oracle().with_id("scout_rainy_forecast").depends_on(previous)
            for farm_id, farm, sensor in farms:
                previous = (
                    sensor.read_soil_sensors().oracle().with_id(f"scout_rainy_{farm_id}_soil").depends_on(previous)
                )
            previous = (
                self.system.advance_time(days=3).oracle().with_id("wait_rain_and_field_drainage").depends_on(previous)
            )
            previous = self.weather.get_current_weather().oracle().with_id("scout_weather").depends_on(previous)
            previous = self.weather.get_forecast(days=4).oracle().with_id("scout_forecast").depends_on(previous)
            for farm_id, farm, sensor in farms:
                previous = (
                    farm.get_ridge_range_state(0, 63).oracle().with_id(f"scout_{farm_id}_before").depends_on(previous)
                )
                previous = sensor.read_soil_sensors().oracle().with_id(f"scout_{farm_id}_soil").depends_on(previous)
                previous = (
                    sensor.read_canopy_sensors().oracle().with_id(f"scout_{farm_id}_canopy").depends_on(previous)
                )
                previous = (
                    farm.get_management_status().oracle().with_id(f"scout_{farm_id}_budget").depends_on(previous)
                )
            # 全田航测 + 四个分布样带。地面实际覆盖16/64垄，不冒充逐垄检查。
            for farm_id in ("farm_a", "farm_b"):
                previous = (
                    self.mavic.check_status().oracle().with_id(f"scout_{farm_id}_drone_ready").depends_on(previous)
                )
                previous = (
                    self.mavic.fly_survey(farm_id, 0, 63)
                    .oracle()
                    .with_id(f"scout_{farm_id}_flight")
                    .depends_on(previous)
                )
                previous = self.mavic.charge().oracle().with_id(f"scout_{farm_id}_charge_drone").depends_on(previous)
                if farm_id == "farm_b":
                    # A抽查后机器人需60分钟充满，B航测已用9分20秒；再等51分钟留20秒余量。
                    previous = (
                        self.system.advance_time(minutes=51)
                        .oracle()
                        .with_id("wait_robot_charge_between_farms")
                        .depends_on(previous)
                    )
                previous = (
                    self.robot.check_status().oracle().with_id(f"scout_{farm_id}_robot_ready").depends_on(previous)
                )
                for start in (0, 20, 40, 60):
                    previous = (
                        self.robot.inspect_crop_health(farm_id, start, start + 3)
                        .oracle()
                        .with_id(f"scout_{farm_id}_ground_{start}_{start + 3}")
                        .depends_on(previous)
                    )
                previous = self.robot.charge().oracle().with_id(f"scout_{farm_id}_charge_robot").depends_on(previous)
            # 4. 不同管理争用同一台Tractor：B喷施有更严格天气约束，先B后A。
            previous = self.warehouse.get_inventory().oracle().with_id("management_shared_stock").depends_on(previous)
            previous = self.tractor.get_status().oracle().with_id("management_shared_tractor").depends_on(previous)
            previous = self.tractor.refuel(100.0).oracle().with_id("management_refuel").depends_on(previous)
            previous = self.weather.get_current_weather().oracle().with_id("spray_farm_b_weather").depends_on(previous)
            previous = self.sensor_b.read_soil_sensors().oracle().with_id("spray_farm_b_soil").depends_on(previous)
            previous = (
                self.tractor.attach_implement("sprayer")
                .oracle()
                .with_id("management_attach_sprayer")
                .depends_on(previous)
            )
            previous = (
                self.tractor.load_pesticide(NUM_RIDGES * PESTICIDE_L_PER_RIDGE)
                .oracle()
                .with_id("management_load_standard_spray_volume")
                .depends_on(previous)
            )
            for start in range(0, NUM_RIDGES, 10):
                end = min(start + 9, NUM_RIDGES - 1)
                previous = (
                    self.tractor.apply_pesticide("farm_b", start, end)
                    .oracle()
                    .with_id(f"spray_farm_b_{start}_{end}")
                    .depends_on(previous)
                )
            previous = (
                self.farm_b.get_management_status().oracle().with_id("spray_farm_b_budget_after").depends_on(previous)
            )
            previous = (
                self.tractor.return_supplies()
                .oracle()
                .with_id("management_return_spray_supplies")
                .depends_on(previous)
            )
            previous = (
                self.tractor.detach_implement().oracle().with_id("management_detach_sprayer").depends_on(previous)
            )
            previous = (
                self.tractor.attach_implement("cultivator")
                .oracle()
                .with_id("management_attach_cultivator")
                .depends_on(previous)
            )
            previous = (
                self.weather.get_current_weather().oracle().with_id("cultivate_farm_a_weather").depends_on(previous)
            )
            previous = self.sensor_a.read_soil_sensors().oracle().with_id("cultivate_farm_a_soil").depends_on(previous)
            for start in range(0, NUM_RIDGES, 10):
                end = min(start + 9, NUM_RIDGES - 1)
                previous = (
                    self.tractor.mechanical_weed_control("farm_a", start, end)
                    .oracle()
                    .with_id(f"cultivate_farm_a_{start}_{end}")
                    .depends_on(previous)
                )
            previous = (
                self.farm_a.get_management_status()
                .oracle()
                .with_id("cultivate_farm_a_budget_after")
                .depends_on(previous)
            )
            previous = (
                self.tractor.detach_implement().oracle().with_id("management_detach_cultivator").depends_on(previous)
            )

            # 5. 分别复查A杂草、B虫害；不能把一次处理解释为永久清除。
            # 固定参考在第三天上午复查；等待计入两场的共同时间。
            previous = (
                self.system.advance_time(days=2, hours=15)
                .oracle()
                .with_id("wait_management_recheck")
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

            # 6. 后续两场持续观察。等待留出地面巡查的作业时间，让三次复查均落在上午。
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

            # 7. 九月共用收获机，先核查两场，再逐场重新核对天气和通行。
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
                content="双场不同管理参考流程结束。请核对两场观察、B全田喷施7趟、A全田中耕7趟、共享物料/换机具/电量、128垄收获及32个来源批次；本场景未实现validate。",
            ).oracle().with_id("report").depends_on(previous)
        self.events = events
        return events

    # 按要求不实现 validate；继承基类的 None，运行报告默认状态不是任务评分。
