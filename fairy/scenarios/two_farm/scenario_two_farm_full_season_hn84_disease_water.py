"""双农场差异化大豆全季：A局部叶部病害，B局部低持水土壤。

一场景一文件：本文件完整定义初态、设施、共享设备与build_events_flow，
不继承其他场景、不调用其他场景的安装或流程helper。
两场同地区、同黑农84、同5月5日起点、各64垄（每场有效种植面积1.88672ha）；天气完全共享。
六月事件雨18mm/日×4日=72mm，本固定seed六月实测140.33mm，不采用源配置的洪涝级雨量。

差异是初态及土壤参数，不是在指定日期直接改写病压或土壤水分：
- A的20–39垄有较重前茬病害背景，初始潜在病原压力0.20，其余0.02。
- B的20–39垄有效蓄水层较浅、田间持水量较低；其余为与A相同的深厚黑土。
- 两个profile独立复制，全部清除源profile的强制病害outbreak；日推自然演化。

固定种子下参考窗口：5/26出苗复查，6/18雨后长势，7/5初花营养，
7/20 R3确认A病害并局部杀菌，7/27复查；8/2 R5和8/9 R6分别对B20–39补水，
每次4小时=20mm/垄，次日复查入渗。日期是经验证的参考路径，Agent以实际观测决策。
杀菌剂3.8L/垄是已有工具的工作液参数，不是现实农药有效成分推荐量。

各场全季水预算15个全田等效毫米：全田追肥载水2mm；B两次局部补水各6.25mm，
合计14.5mm。固定灌溉选区并行供水，一次4小时另加5分钟设置耗时。
地面每次只抽查4垄，不能声称覆盖全田；热像受噪声影响，仅作辅助。
本场景保留空validate；用真实工具回放和同管理窗口反事实验证，收获依成熟条件允许延后。

运行：
    python -m fairy.cli -s scenario_two_farm_full_season_hn84_disease_water \
        --build-oracle --replay --output-dir /tmp/two-farm-disease-water
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp, plants_per_ridge_from_spacing
from fairy.apps.farm_world.irrigation_app import IrrigationApp
from fairy.apps.farm_world.manual_ops_app import ManualOpsApp
from fairy.apps.farm_world.sensor_app import SensorApp
from fairy.apps.farm_world.shared_drone_app import SharedDroneApp
from fairy.apps.farm_world.shared_robot_app import SharedRobotApp
from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.system import SystemApp
from fairy.physics.soil_engine import SoilHydraulicModifier
from fairy.scenarios.registry import register_scenario
from fairy.scenarios.scenario import Scenario
from fairy.types import EventRegisterer


SCENARIO_ID = "scenario_two_farm_full_season_hn84_disease_water"
BASE_WEATHER_PROFILE = "harbin_l3_disease_then_drought_recovery_seed_1628"
PROFILE_NAME = "two_farm_hn84_shared_weather_rain18_seed_1628"
# 只采用同地区湿六月、八月连续少雨的气候；源profile的强制病害事件在setup清除。
SEED_TYPE = "HEINONG84"
SEED_SPACING_CM = 7.9
DEPTH_CM = 4.0
RIDGE_WIDTH_M = 1.1
NUM_RIDGES = 64
BASE_FERTILIZER_KG = 200.0  # 当前 base_fertilize 工具实际消耗，不沿用旧脚本的 250 kg 装载量。

BRIEFING = """
管理哈尔滨同一地区farm_a和farm_b的完整黑农84大豆季，完成播前准备、播种、
分别诊断与管理、收获及安全入库。每场64垄（本地0–63），垄长268m、垄距1.1m，
每场有效种植面积约1.887ha；播深4cm、株距7.9cm。两场同品种、同天气，不能把A/B当成不同气候。

田块档案：
- farm_a：深厚黑土；20–39垄前茬重茬且有叶部病害记录，重点巡查叶部病害。
  这是一项风险背景，不代表现在已有可见病斑。先调查再决定是否使用杀菌剂。
- farm_b：20–39垄为较浅、低持水土壤，其余与A相同。结荚灌浆期该区更容易先缺水，
  重点比较S3/S4与本场正常区探头、连续墒情、天气预报及作物阶段；热像仅作辅助。

固定设施：FarmA_Sensor/FarmA_Irrigation只服务A，FarmB_Sensor/FarmB_Irrigation只服务B。
Tractor、Mavic3M、Matrice4T、Robot0全场共用；田间移动工具必须给farm_id。
物料剩余退回来源场，粮箱卸回来源场，之后才能切场。System一次等待同时推进两场。

全季安排：
1. 检查天气、土壤、库存，逐场平地、施200kg底肥、按1.1m起垄；每趟最多4垄播种，
   完成各场0–63。共享拖拉机油箱100L，种箱30万粒，按真实需求补装。
2. 约5月下旬复核出苗，6月湿雨后复核长势；两场都要观察。地面每次明确只请求4垄，
   如28–31、32–35；抽查发现异常再扩大调查，不把低置信阴性当作排除病害。
3. 约7月初初花，分别复核营养与墒情；参考每场全田nutrient_amount=0.24、water_mm=2。
4. 约7月中下旬R3，重点调查A20–39：多光谱定位，Robot分两次抽查28–31、32–35，
   与B健康抽查对照。有多垄高置信病害证据、且天气和通行允许时，才局部施杀菌剂。
   参考7/20对A20–29、30–39各一趟，3.8L/垄，精确从A装76L；约7天后复查。
   低置信虫害提示不能替代虫害确诊；B无相应证据时不照搬A的施药。
5. 约8月上旬R5–R6，重点复核B20–39持续缺水：看表土探头趋势、与正常区差异、
   生育期和无有效降雨预报，同时地面检查排除明显病虫害。Agent看不到精确根层VWC，
   不要凭空声称读到了根层数值，也不要依据一次有噪声热像下结论。
   参考8/2、8/9分别用FarmB_Irrigation.irrigate(20,39,4.0)，每次20mm/垄。
   水先进入表层，次日再查入渗及长势，不宣称立即解除全部根层缺水。
6. 两场季水预算各15个全田等效毫米，含追肥载水。局部20垄补20mm只扣6.25mm，
   B两次加全田载水共14.5mm；不可把20mm误当全场20mm，也不可无证据全田灌溉。
   杀菌剂全季最多1个施药日；A同一天两趟计同一施药日，不能天天重复施药。
7. 分别观察两场成熟度和含水率，满足所有目标垄R8、籽粒水分≤18%、无雨及土壤可通行
   才收获。先成熟的田可以先收，不能只因到了日历日期就强行收割。
   安装harvester，每趟最多4垄、逐趟卸回本场；检查批次水分，必要时干燥至13%再入库，
   ≤13.5%的安全批次可直接入库。最后分别汇报管理证据、处理区域、水药用量、产量。

共享无人机充满约30分钟、机器人约60分钟，充电异步；读覆盖和剩余电量后安排作业。
Mavic全64垄约耗64%，下一场前需充电；地面4垄约耗20%，留足下一次检查的电量。
所有推进都使用同一北京时间；作业跨日正常日推，不把一个农场等待重复算两次。
当前validate暂空；参考流程完成不等于已经实现任务评分。
""".strip()


@register_scenario(SCENARIO_ID)
class ScenarioTwoFarmFullSeasonHN84DiseaseWater(Scenario):
    """同气候、局部病史与土壤差异，管理必须指向实际有需求的农场。"""

    # 场景起点：北京时间 2026-05-05 07:00。
    start_time = datetime(2026, 5, 5, 7, tzinfo=timezone(timedelta(hours=8))).timestamp()
    duration = 170 * 86400
    queue_based_loop = True
    time_increment_in_seconds = 60
    expects_agent_harvest = True
    scenario_input = BRIEFING
    additional_system_prompt = (
        "Manage both farms for the whole soybean season with one shared clock and equipment fleet. "
        "Farm A has a local previous-disease history; farm B has a local lower-water-holding soil. "
        "Both receive identical regional weather. Scout each independently: use disease evidence "
        "for targeted fungicide on A and persistent soil-water evidence at reproductive stages "
        "for targeted irrigation on B. Ground inspections sample four ridges at a time. "
        "Surface sensors do not expose exact root-zone water. Recheck treatment and infiltration, "
        "respect each farm's seasonal water and chemical budget, and harvest/store both safely. "
        "Calendar windows guide observation; actual conditions determine actions."
    )

    def init_and_populate_apps(self) -> None:
        """两场的固定设施独立创建，四台移动设备各创建一次。"""
        self.aui = AgentUserInterface()
        self.weather = WeatherApp()
        self.weather.set_weather(
            date="2026-05-05", temp_c=16.0, humidity_pct=58.0,
            # 天气profile的20 MJ/m²/day换算为WeatherApp声明的平均W/m²。
            wind_speed_ms=2.4, rainfall_mm=0.0, solar_radiation=20.0 / 0.0864,
            forecast=[
                {"date": "2026-05-06", "temp_c": 16.5, "humidity_pct": 56.0,
                 "wind_speed_ms": 2.0, "rainfall_mm": 0.0, "solar_radiation": 20.5 / 0.0864},
                {"date": "2026-05-07", "temp_c": 17.0, "humidity_pct": 55.0,
                 "wind_speed_ms": 2.4, "rainfall_mm": 0.0, "solar_radiation": 21.0 / 0.0864},
                {"date": "2026-05-08", "temp_c": 18.0, "humidity_pct": 54.0,
                 "wind_speed_ms": 2.2, "rainfall_mm": 0.0, "solar_radiation": 21.0 / 0.0864},
            ],
        )
        self.farm_a = FarmWorldApp(farm_id="farm_a", name="FarmA")
        self.farm_b = FarmWorldApp(farm_id="farm_b", name="FarmB")
        self.sensor_a = SensorApp(self.farm_a, name="FarmA_Sensor")
        self.sensor_b = SensorApp(self.farm_b, name="FarmB_Sensor")
        self.irrigation_a = IrrigationApp(self.farm_a, self.weather, name="FarmA_Irrigation")
        self.irrigation_b = IrrigationApp(self.farm_b, self.weather, name="FarmB_Irrigation")
        self.farm_environment = FarmEnvironment([
            FarmContext("farm_a", self.farm_a, self.weather, self.sensor_a, self.irrigation_a),
            FarmContext("farm_b", self.farm_b, self.weather, self.sensor_b, self.irrigation_b),
        ], self.weather, start_time=self.start_time, timezone_name="Asia/Shanghai")
        self.tractor = SharedTractorApp(self.farm_environment, name="Tractor")
        self.mavic = SharedDroneApp(
            self.farm_environment, name="Mavic3M", description="共享多光谱巡查无人机",
            speed_ms=5.0, effective_ridges_per_pass=7, battery_pct_per_ridge=1.0,
        )
        self.matrice = SharedDroneApp(
            self.farm_environment, name="Matrice4T", description="共享热红外巡查无人机",
            speed_ms=4.0, effective_ridges_per_pass=5, battery_pct_per_ridge=1.5,
        )
        self.robot = SharedRobotApp(self.farm_environment, name="Robot0")
        self.manual_ops = ManualOpsApp(self.farm_environment)
        self.system = SystemApp()
        self.shared_equipment = [self.tractor, self.mavic, self.matrice, self.robot]
        self.apps = [
            self.aui, self.weather, self.farm_a, self.farm_b,
            self.sensor_a, self.sensor_b, self.irrigation_a, self.irrigation_b,
            *self.shared_equipment, self.manual_ops, self.system,
        ]
        # 显式保留各场初态与资源；使用真实 Inventory 字段，不创建无效的库存别名。
        for farm in (self.farm_a, self.farm_b):
            farm.bound_farm_id = farm.farm_id
            farm._sim_date = "2026-05-05"
            farm.set_season_phase("full_season")
            farm.completed_prep_ops = []
            farm._inventory.seed_stock[SEED_TYPE] = 1_000_000
            farm._inventory.fertilizer_kg = 2500.0
            farm._inventory.pesticide_liters = 160.0
            farm._inventory.fuel_liters = 1200.0
            for ridge in farm._ridges:
                ridge.planted = False
                ridge.soil_vwc = 0.30 + ((ridge.ridge_id % 5) - 2) * 0.003
                ridge.soil_temp_c = 13.1 + (ridge.ridge_id % 4) * 0.25
                ridge.nutrient_index = 0.76
                ridge.stand_fraction = 1.0
                ridge.pest_pressure_base = ridge.pest_pressure = 0.02
                ridge.disease_pressure_base = ridge.disease_pressure = 0.02
            farm.configure_physics_profile(
                BASE_WEATHER_PROFILE, location="Harbin/Heilongjiang", seed_type=SEED_TYPE,
                cultivar="黑农84/同气候病害与水分差异化全季",
                density_target_plants_m2=23.0, start_date="2026-05-05",
            )
        # 两个profile必须独立；修改原registry对象会污染其他场景与另一农场。
        # 清除源profile的固定日期强制病害；本场病压只从初态随天气自然演化。
        for farm in (self.farm_a, self.farm_b):
            local_profile = deepcopy(farm.physics.profile)
            local_profile.name = PROFILE_NAME
            local_profile.biotic_outbreaks = []
            for weather_event in local_profile.weather_events:
                if weather_event.event_type == "rain_event":
                    # 当前引擎逐日应用事件雨：18mm/日×4日，而不是源配置72mm/日×4日。
                    weather_event.total_rain_mm = 18.0
            farm.physics.profile = local_profile
            farm.physics.profile_name = PROFILE_NAME
            farm.configure_management_regime(
                regime="conventional", max_fungicide_applications=1,
                irrigation_quota_mm_total=15.0,
            )

        # 使用已有深厚黑土参数，root_depth是模型等效蓄水层厚度，不代表幼苗实际根长。
        black_soil = SoilHydraulicModifier(
            root_depth_m=1.45, field_capacity_vwc=0.37,
            top_drainage_rate=0.22, root_drainage_rate=0.03,
            rainfall_capture_efficiency=0.97, irrigation_efficiency=0.92,
            max_infiltration_mm_day=85.0,
        )
        low_holding_soil = SoilHydraulicModifier(
            root_depth_m=0.80, field_capacity_vwc=0.29,
            top_drainage_rate=0.22, root_drainage_rate=0.30,
            rainfall_capture_efficiency=0.66, irrigation_efficiency=0.80,
            max_infiltration_mm_day=72.0,
        )
        self.farm_a.physics.soil.set_hydraulic_modifiers({rid: black_soil for rid in range(64)})
        self.farm_b.physics.soil.set_hydraulic_modifiers({
            rid: low_holding_soil if 20 <= rid <= 39 else black_soil for rid in range(64)
        })
        for ridge in self.farm_a._ridges[20:40]:
            # 0–1潜在病原压力指数，不是20%叶片已经发病；不在季中重新赋值。
            ridge.disease_pressure_base = ridge.disease_pressure = 0.20

        # 不沿用原单场脚本190L初始油量；这台共享拖拉机真实油箱上限为100L。
        self.tractor._fuel_tank_l = 100.0
        self.system.attach_farm_environment(self.farm_environment)
        for app in self.apps:
            app.register_time_manager(self.farm_environment.time_manager)
            app.set_seed(self.seed)

    def build_events_flow(self):
        """完整参考 workflow；每个节点包含阶段、农场、动作和垄范围。"""
        farms = (
            ("farm_a", self.farm_a, self.sensor_a),
            ("farm_b", self.farm_b, self.sensor_b),
        )
        with EventRegisterer.capture_mode() as events:
            previous = self.aui.send_message_to_agent(content=BRIEFING).with_id("briefing")

            # 1. 播前准备与播种：先完成A和B，再共同进入出苗等待。
            previous = self.weather.get_current_weather().oracle().with_id(
                "prep_weather").depends_on(previous)
            previous = self.weather.get_forecast(days=5).oracle().with_id(
                "prep_forecast").depends_on(previous)
            for farm_id, farm, sensor in farms:
                previous = sensor.read_soil_sensors().oracle().with_id(
                    f"prep_{farm_id}_soil").depends_on(previous)
                previous = farm.get_inventory().oracle().with_id(
                    f"prep_{farm_id}_inventory").depends_on(previous)
                previous = self.tractor.get_status().oracle().with_id(
                    f"prep_{farm_id}_tractor_status").depends_on(previous)
                previous = self.tractor.refuel(farm_id, 100.0).oracle().with_id(
                    f"prep_{farm_id}_refuel").depends_on(previous)
                previous = self.tractor.attach_implement("grader").oracle().with_id(
                    f"prep_{farm_id}_attach_grader").depends_on(previous)
                previous = self.tractor.level(farm_id).oracle().with_id(
                    f"prep_{farm_id}_level").depends_on(previous)
                previous = self.tractor.detach_implement().oracle().with_id(
                    f"prep_{farm_id}_detach_grader").depends_on(previous)
                previous = self.tractor.load_fertilizer(farm_id, BASE_FERTILIZER_KG).oracle().with_id(
                    f"prep_{farm_id}_load_base_fertilizer").depends_on(previous)
                previous = self.tractor.base_fertilize(farm_id).oracle().with_id(
                    f"prep_{farm_id}_base_fertilize").depends_on(previous)
                previous = self.tractor.attach_implement("furrower").oracle().with_id(
                    f"prep_{farm_id}_attach_furrower").depends_on(previous)
                previous = self.tractor.form_ridges(farm_id, RIDGE_WIDTH_M).oracle().with_id(
                    f"prep_{farm_id}_form_ridges").depends_on(previous)
                previous = self.tractor.detach_implement().oracle().with_id(
                    f"prep_{farm_id}_detach_furrower").depends_on(previous)
                # 每趟恰好装本场4垄所需种子，16趟共64垄，不把余种带入另一场。
                for start in range(0, NUM_RIDGES, 4):
                    end = start + 3
                    count = plants_per_ridge_from_spacing(SEED_SPACING_CM) * 4
                    previous = self.tractor.load_seeds(farm_id, SEED_TYPE, count).oracle().with_id(
                        f"plant_{farm_id}_load_seed_{start}_{end}").depends_on(previous)
                    previous = self.tractor.plant_seeds(
                        farm_id, start, end, DEPTH_CM, SEED_SPACING_CM,
                    ).oracle().with_id(f"plant_{farm_id}_{start}_{end}").depends_on(previous)
                previous = self.tractor.return_supplies(farm_id).oracle().with_id(
                    f"plant_{farm_id}_return_supplies").depends_on(previous)

            # 播后统一推进一天，让两场共同结算，不分别commit造成双倍时间。
            previous = self.system.advance_time(days=1).oracle().with_id(
                "settle_both_farms_after_planting_1_day").depends_on(previous)

            # 2. 5/26上午：播后约21天复核；扣除此前作业耗时，把多光谱巡查安排在白天。
            previous = self.system.advance_time(days=19, hours=15).oracle().with_id(
                "wait_both_farms_daylight_emergence").depends_on(previous)
            previous = self.weather.get_current_weather().oracle().with_id(
                "emergence_weather").depends_on(previous)
            for farm_id, farm, sensor in farms:
                previous = farm.get_farm_overview().oracle().with_id(
                    f"emergence_{farm_id}_overview").depends_on(previous)
                previous = sensor.read_soil_sensors().oracle().with_id(
                    f"emergence_{farm_id}_soil").depends_on(previous)
                previous = self.mavic.fly_survey(farm_id, 0, 63).oracle().with_id(
                    f"emergence_{farm_id}_ndvi_0_63").depends_on(previous)
                previous = self.robot.inspect_emergence(farm_id, 0, 3).oracle().with_id(
                    f"emergence_{farm_id}_ground_0_3").depends_on(previous)
                previous = self.mavic.charge().oracle().with_id(
                    f"emergence_{farm_id}_charge_mavic").depends_on(previous)
                previous = self.robot.charge().oracle().with_id(
                    f"emergence_{farm_id}_charge_robot").depends_on(previous)
                previous = self.system.advance_time(hours=1).oracle().with_id(
                    f"emergence_{farm_id}_wait_shared_chargers").depends_on(previous)

            # 3. 约6/18：共同经历6/14–17湿雨后，分别观察；风险背景不等于已有病害。
            previous = self.system.advance_time(days=23).oracle().with_id(
                "wait_both_farms_rainy_june_growth_23_days").depends_on(previous)
            previous = self.weather.get_current_weather().oracle().with_id(
                "early_growth_weather").depends_on(previous)
            for farm_id, farm, sensor in farms:
                previous = sensor.read_soil_sensors().oracle().with_id(
                    f"early_{farm_id}_soil").depends_on(previous)
                previous = sensor.read_canopy_sensors().oracle().with_id(
                    f"early_{farm_id}_canopy").depends_on(previous)
                previous = self.mavic.fly_survey(farm_id, 0, 63).oracle().with_id(
                    f"early_{farm_id}_ndvi_0_63").depends_on(previous)
                previous = self.robot.inspect_crop_health(farm_id, 28, 31).oracle().with_id(
                    f"early_{farm_id}_ground_28_31").depends_on(previous)
                previous = self.mavic.charge().oracle().with_id(
                    f"early_{farm_id}_charge_mavic").depends_on(previous)
                previous = self.robot.charge().oracle().with_id(
                    f"early_{farm_id}_charge_robot").depends_on(previous)
                previous = self.system.advance_time(hours=1).oracle().with_id(
                    f"early_{farm_id}_wait_shared_chargers").depends_on(previous)

            # 4. 约7/5初花：相同轻量营养管理，避免把营养差异误当病害/缺水。
            previous = self.system.advance_time(days=16, hours=16).oracle().with_id(
                "wait_both_farms_r1_nutrition").depends_on(previous)
            for farm_id, farm, sensor in farms:
                previous = sensor.read_soil_sensors().oracle().with_id(
                    f"flowering_{farm_id}_soil").depends_on(previous)
                previous = sensor.read_canopy_sensors().oracle().with_id(
                    f"flowering_{farm_id}_canopy").depends_on(previous)
                previous = farm.get_ridge_range_state(0, 63).oracle().with_id(
                    f"flowering_{farm_id}_state_0_63").depends_on(previous)
                previous = farm.apply_fertigation(0, 63, nutrient_amount=0.24, water_mm=2.0).oracle().with_id(
                    f"flowering_{farm_id}_light_fertigation").depends_on(previous)

            # 5. 约7/20 R3：证据->天气/通行->A局部处理；B无病害证据不跟着用药。
            previous = self.system.advance_time(days=15).oracle().with_id(
                "wait_both_farms_r3_disease_decision").depends_on(previous)
            previous = self.weather.get_current_weather().oracle().with_id(
                "disease_weather").depends_on(previous)
            previous = self.weather.get_forecast(days=3).oracle().with_id(
                "disease_forecast").depends_on(previous)
            for farm_id, farm, sensor in farms:
                previous = sensor.read_soil_sensors().oracle().with_id(
                    f"disease_{farm_id}_soil").depends_on(previous)
                previous = farm.get_ridge_range_state(20, 39).oracle().with_id(
                    f"disease_{farm_id}_stage_20_39").depends_on(previous)
            previous = self.mavic.fly_survey("farm_a", 20, 39).oracle().with_id(
                "disease_farm_a_ndvi_20_39").depends_on(previous)
            for start, end in ((28, 31), (32, 35)):
                previous = self.robot.inspect_crop_health("farm_a", start, end).oracle().with_id(
                    f"disease_farm_a_confirm_{start}_{end}").depends_on(previous)
            previous = self.robot.inspect_crop_health("farm_b", 28, 31).oracle().with_id(
                "disease_farm_b_healthy_comparison_28_31").depends_on(previous)
            previous = self.tractor.refuel("farm_a", 100.0).oracle().with_id(
                "disease_farm_a_refuel").depends_on(previous)
            previous = self.tractor.attach_implement("sprayer").oracle().with_id(
                "disease_attach_shared_sprayer").depends_on(previous)
            previous = self.tractor.load_fungicide("farm_a", 76.0).oracle().with_id(
                "disease_farm_a_load_exact_76_l").depends_on(previous)
            for start, end in ((20, 29), (30, 39)):
                previous = self.tractor.apply_fungicide("farm_a", start, end, 3.8).oracle().with_id(
                    f"disease_farm_a_treat_{start}_{end}").depends_on(previous)
            previous = self.tractor.return_supplies("farm_a").oracle().with_id(
                "disease_farm_a_return_supplies").depends_on(previous)
            previous = self.tractor.detach_implement().oracle().with_id(
                "disease_detach_shared_sprayer").depends_on(previous)
            previous = self.mavic.charge().oracle().with_id(
                "disease_charge_mavic").depends_on(previous)
            previous = self.robot.charge().oracle().with_id(
                "disease_charge_robot").depends_on(previous)
            previous = self.system.advance_time(hours=1).oracle().with_id(
                "disease_wait_shared_chargers").depends_on(previous)

            # 6. 约7/27：同一病区复查；没有证据不重复施药，不用新病压覆盖药效。
            previous = self.system.advance_time(days=7).oracle().with_id(
                "wait_fungicide_followup_7_days").depends_on(previous)
            previous = self.farm_a.get_ridge_range_state(20, 39).oracle().with_id(
                "disease_followup_farm_a_stage_20_39").depends_on(previous)
            for start, end in ((28, 31), (32, 35)):
                previous = self.robot.inspect_crop_health("farm_a", start, end).oracle().with_id(
                    f"disease_followup_farm_a_{start}_{end}").depends_on(previous)
            previous = self.sensor_b.read_soil_sensors().oracle().with_id(
                "disease_followup_farm_b_water_trend").depends_on(previous)
            previous = self.robot.charge().oracle().with_id(
                "disease_followup_charge_robot").depends_on(previous)
            previous = self.system.advance_time(hours=1).oracle().with_id(
                "disease_followup_wait_robot").depends_on(previous)

            # 7. 约8/2 R5：B低持水区缺水，A及B正常区作为同天气参照。
            previous = self.system.advance_time(days=5, hours=16).oracle().with_id(
                "wait_both_farms_r5_water_decision").depends_on(previous)
            previous = self.weather.get_current_weather().oracle().with_id(
                "r5_weather").depends_on(previous)
            previous = self.weather.get_forecast(days=4).oracle().with_id(
                "r5_forecast").depends_on(previous)
            previous = self.sensor_a.read_soil_sensors().oracle().with_id(
                "r5_farm_a_water_comparison").depends_on(previous)
            previous = self.sensor_b.read_soil_sensors().oracle().with_id(
                "r5_farm_b_soil_before_irrigation").depends_on(previous)
            previous = self.sensor_b.read_canopy_sensors().oracle().with_id(
                "r5_farm_b_canopy").depends_on(previous)
            previous = self.farm_b.get_ridge_range_state(20, 39).oracle().with_id(
                "r5_farm_b_stage_20_39").depends_on(previous)
            previous = self.robot.inspect_crop_health("farm_b", 28, 31).oracle().with_id(
                "r5_farm_b_disease_differential_28_31").depends_on(previous)
            previous = self.matrice.fly_survey("farm_b", 20, 39).oracle().with_id(
                "r5_farm_b_thermal_support_20_39").depends_on(previous)
            previous = self.irrigation_b.irrigate(20, 39, 4.0).oracle().with_id(
                "r5_farm_b_irrigate_20_39_20_mm").depends_on(previous)
            previous = self.sensor_b.read_soil_sensors().oracle().with_id(
                "r5_farm_b_surface_after_irrigation").depends_on(previous)
            previous = self.system.advance_time(days=1).oracle().with_id(
                "r5_wait_infiltration_1_day").depends_on(previous)
            previous = self.sensor_b.read_soil_sensors().oracle().with_id(
                "r5_farm_b_next_day_soil").depends_on(previous)
            previous = self.farm_b.get_ridge_range_state(20, 39).oracle().with_id(
                "r5_farm_b_next_day_crop").depends_on(previous)

            # 8. 约8/9 R6：持续少雨，再评估再补第二水；不是首次灌后立即重复浇水。
            previous = self.system.advance_time(days=5, hours=20).oracle().with_id(
                "wait_both_farms_r6_water_recheck").depends_on(previous)
            previous = self.weather.get_current_weather().oracle().with_id(
                "r6_weather").depends_on(previous)
            previous = self.weather.get_forecast(days=4).oracle().with_id(
                "r6_forecast").depends_on(previous)
            previous = self.sensor_b.read_soil_sensors().oracle().with_id(
                "r6_farm_b_soil_before_second_irrigation").depends_on(previous)
            previous = self.farm_b.get_ridge_range_state(20, 39).oracle().with_id(
                "r6_farm_b_stage_20_39").depends_on(previous)
            previous = self.matrice.fly_survey("farm_b", 20, 39).oracle().with_id(
                "r6_farm_b_thermal_support_20_39").depends_on(previous)
            previous = self.irrigation_b.irrigate(20, 39, 4.0).oracle().with_id(
                "r6_farm_b_irrigate_20_39_20_mm").depends_on(previous)
            previous = self.sensor_b.read_soil_sensors().oracle().with_id(
                "r6_farm_b_surface_after_irrigation").depends_on(previous)
            previous = self.system.advance_time(days=1).oracle().with_id(
                "r6_wait_infiltration_1_day").depends_on(previous)
            previous = self.sensor_b.read_soil_sensors().oracle().with_id(
                "r6_farm_b_next_day_soil").depends_on(previous)

            # 9. 约9/11：A全场与B正常区已R8、约14%水分，先收，避免为B局部晚熟而过干。
            # 约9/21：B20–39垄晚熟且需田间降水分，另行复核后收；没有满足门槛不能强收。
            previous = self.system.advance_time(days=32).oracle().with_id(
                "wait_first_harvest_maturity_and_moisture").depends_on(previous)
            previous = self.tractor.attach_implement("harvester").oracle().with_id(
                "harvest_attach_shared_harvester").depends_on(previous)
            harvest_phases = (
                ("farm_a", self.farm_a, self.sensor_a, "farm_a_all", ((0, 63),), 0),
                ("farm_b", self.farm_b, self.sensor_b, "farm_b_normal", ((0, 19), (40, 63)), 0),
                ("farm_b", self.farm_b, self.sensor_b, "farm_b_low_holding", ((20, 39),), 10),
            )
            for farm_id, farm, sensor, phase, windows, wait_days in harvest_phases:
                if wait_days:
                    previous = self.system.advance_time(days=wait_days).oracle().with_id(
                        "wait_farm_b_low_holding_maturity_and_moisture").depends_on(previous)
                previous = self.weather.get_current_weather().oracle().with_id(
                    f"harvest_{phase}_weather").depends_on(previous)
                previous = self.weather.get_forecast(days=3).oracle().with_id(
                    f"harvest_{phase}_forecast").depends_on(previous)
                previous = sensor.read_soil_sensors().oracle().with_id(
                    f"harvest_{phase}_trafficability").depends_on(previous)
                previous = farm.get_farm_overview().oracle().with_id(
                    f"harvest_{phase}_overview").depends_on(previous)
                previous = self.tractor.refuel(farm_id, 100.0).oracle().with_id(
                    f"harvest_{phase}_refuel").depends_on(previous)
                for first, last in windows:
                    previous = farm.get_ridge_range_state(first, last).oracle().with_id(
                        f"harvest_{phase}_maturity_moisture_{first}_{last}").depends_on(previous)
                    for start in range(first, last + 1, 4):
                        end = min(start + 3, last)
                        previous = self.tractor.harvest(farm_id, start, end).oracle().with_id(
                            f"harvest_{phase}_{start}_{end}").depends_on(previous)
                        previous = self.tractor.unload_grain(farm_id).oracle().with_id(
                            f"harvest_{phase}_unload_{start}_{end}").depends_on(previous)
                # B正常区与晚熟区分批干燥/入库；不把已入库安全粮反复当新批次处理。
                previous = farm.dry_grain(target_moisture_pct=13.0).oracle().with_id(
                    f"storage_{phase}_dry_if_needed").depends_on(previous)
                previous = farm.store_grain().oracle().with_id(
                    f"storage_{phase}_store").depends_on(previous)
            previous = self.tractor.detach_implement().oracle().with_id(
                "harvest_detach_shared_harvester").depends_on(previous)
            previous = self.system.advance_time(days=1).oracle().with_id(
                "wait_both_farms_post_storage_1_day").depends_on(previous)
            for farm_id, farm, sensor in farms:
                previous = farm.get_farm_overview().oracle().with_id(
                    f"final_{farm_id}_overview").depends_on(previous)
                previous = farm.get_inventory().oracle().with_id(
                    f"final_{farm_id}_inventory").depends_on(previous)
            self.aui.send_message_to_user(
                content="双场差异化全季参考结束：分别核对A局部病害处理、B关键期两次补水、两场入库和共享设备归属。validate暂空。",
            ).oracle().with_id("report_differentiated_full_season").depends_on(previous)
        self.events = events
        return events

    def validate(self, env=None) -> None:
        """按当前要求暂留空；None不代表已实现任务评分。"""
        return None
