"""两个农场的完整大豆季：播前准备 -> 播种 -> 生长期管理 -> 收获入库。

来源：scenario_full_season_hb_base_hn84_std_normal。这里完整定义双农场
配置和 workflow，不继承原场景，也不调用其 install/plant/harvest helpers。
复用的是农场物理引擎、天气 profile 和真实设备工具。

田块：farm_a/FarmA、farm_b/FarmB，各 64 垄，垄长 268 m、垄距 1.1 m，
每场 18,867.2 m²（1.88672 ha），一垄两行，HEINONG84，株距 7.9 cm。
固定设施：每场独立 Sensor 和 Irrigation；仓库、土壤、作物和收获物也独立。
共享设备：一台 Tractor、一台 Mavic3M、一台 Matrice4T、一台 Robot0。

build_events_flow() 按以下顺序完整展开参考工作流：
  1. 两场分别检查、平地、施底肥、起垄、播种全 64 垄，完成后才进入出苗期。
  2. 公共时间 +15 天：两场出苗检查、全田 NDVI、Robot0 抽查各场 0–7 垄。
  3. +23 天：两场早期长势检查、全田 NDVI、健康抽查各场 28–35 垄。
  4. +22 天：两场初花营养复核、健康抽查 28–35 垄、常规轻量追肥。
  5. +18 天：两场中期水分、全田 NDVI、病虫草抽查各场 56–63 垄。
  6. +8 天：两场灌浆水分和冠层检查，Matrice4T 分两半巡查各场全田。
  7. +39 天：分别复核成熟、含水率、天气和通行；分 4 垄收获，逐趟卸回来源场，
     分别完成必要干燥和入库。+1 天后核对两场库存并汇报。

上述等待是指定 profile 下的参考巡查窗口，不是对生育期或可作业性的断言；
Agent 要以实际观测调整时机。设备作业和充电也占用公共时间，A/B 始终一起生长。
播后、追肥后和灌浆复核后各有一次公共1天结算；参考路径还显式保留中期和
灌浆雨天的停飞等待，等待后重新读天气，不通过set_weather人为清除降雨。
Robot0 每次明确只请求 8 垄抽查，不把抽查写成全田覆盖。灌溉按实际干旱证据决定；
正常年参考路径没有额外灌溉/施药。validate 按当前要求留空，不提供任务成功判定。

导出完整参考 workflow 并在新初态回放（不调用模型）：
    uv run python -m fairy.cli -s scenario_two_farm_full_season_hn84_normal \
        --build-oracle --replay --workflow /tmp/two-farm-season/oracle.json \
        --output-dir /tmp/two-farm-season/replay
使用 Agent 时建议 max-tool-calls 至少600，另按所用模型设置 provider/model/endpoint。
"""
from __future__ import annotations

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
from fairy.scenarios.registry import register_scenario
from fairy.scenarios.scenario import Scenario
from fairy.types import EventRegisterer


SCENARIO_ID = "scenario_two_farm_full_season_hn84_normal"
SOURCE_SCENARIO_ID = "scenario_full_season_hb_base_hn84_std_normal"
PROFILE_NAME = "harbin_hb_base_hn84_std_normal_seed_1101"
# 复用物理层正常年气候：seed=1101；固定雨段8/2–4、8/18–19，另有生成的日降雨。
SEED_TYPE = "HEINONG84"
SEED_SPACING_CM = 7.9
DEPTH_CM = 4.0
RIDGE_WIDTH_M = 1.1
NUM_RIDGES = 64
BASE_FERTILIZER_KG = 200.0  # 当前 base_fertilize 工具实际消耗，不沿用旧脚本的 250 kg 装载量。

BRIEFING = """
管理哈尔滨同一地区 farm_a 和 farm_b 的完整黑农84大豆季，从播前准备到安全入库。
每场64垄（各自0–63），每垄268米长、垄距1.1米，一垄两行，每场约1.887公顷。
品种HEINONG84，标准密度，播深4厘米、株距7.9厘米，两场均未整地、未播种。

归属：FarmA/FarmB分别提供本场状态和仓库；FarmA_Sensor/FarmA_Irrigation只服务farm_a，
FarmB_Sensor/FarmB_Irrigation只服务farm_b。Tractor、Mavic3M、Matrice4T、Robot0跨场共用，
所有田间移动作业必须指定farm_id。切场前把剩余种肥药退回来源场，粮箱必须卸回粮食来源场。
两场共同经过时间；SystemApp.advance_time只推进一次，不要为两个农场各等待一遍。
FarmA/FarmB的commit_daily_physics也会让两场一起经过一天，不能把它当无耗时刷新。

全季工作：
1. 读公共天气和预报，分别检查两场土壤、库存和共享设备。适播后逐场平地、施200kg底肥、
   按1.1米起垄，再以每趟最多4垄完成各场0–63垄播种。拖拉机油箱100L、种箱30万粒，
   按真实需求补装；不要把一个农场装载的剩余物料带到另一个农场使用。
2. 约播后15天进入出苗复核：分别读两场概览、土壤和冠层；Mavic3M巡查各场0–63垄；
   Robot0用inspect_emergence抽查各场0–7垄，异常时扩大调查，不把抽查当全田地面覆盖。
3. 早期长势窗口（出苗复核后约23天）：两场分别读土壤/冠层、全田NDVI，
   Robot0用inspect_crop_health抽查各场28–35垄，区别营养、水分、病虫草问题。
4. 初花营养窗口（再约22天）：分别复核各场28–35垄健康及全田营养。
   正常年参考方案每场全田轻量追肥一次：nutrient_amount=0.24，water_mm=2.0；
   实际管理根据本场诊断和资源决定。处理A不能替代处理B。
5. 中期巡查（再约18天）：分别读土壤和全田NDVI，Robot0用inspect_pests抽查各场56–63垄。
6. 灌浆水分窗口（再约8天）：分别检查土壤/冠层，Matrice4T分0–31和32–63垄巡查两场；
   只有观测确认干旱才调用对应农场的固定灌溉，有病虫草证据才选对应处理，处理后复查。
   正常年也有雨天，停飞时继续观察并等待；参考路径中期等1天、灌浆等3天再复核天气。
7. 参考收获窗口在再约39天后；这些间隔只是巡查计划，成熟和可作业条件必须重新观测。
   每场收获前分别确认0–63垄R8成熟、籽粒水分≤18%、无降雨、土壤允许通行。
   必要时继续观察和等待；不要强行收未成熟或不满足条件的田。安装harvester，每次最多4垄；
   每趟卸粮到本场，粮箱清空后才能切场。分别检查收获物，偏湿粮干燥到13%后入库，
   已满足≤13.5%安全水分的批次可直接入库；最后分别汇报两场管理、产量、库存及设备状态。

无人机和机器人电池跨场连续，充电异步；先查看回执中的覆盖范围、剩余电量和充电状态。
Robot0每次最多检查8垄，不能请求0–63后声称全田检查。Mavic3M一次64垄约耗64%电量，
巡查下一场前需充电；Matrice4T巡查32垄约耗48%，两半之间充电。无人机约30分钟、
机器人约60分钟充满，等待也让两场继续生长。参考流程在每场巡查后显式充电并等待。
这是正常年基线，不预设必须灌溉、必须施药或任何异常。本场景暂未实现validate评分。
""".strip()


@register_scenario(SCENARIO_ID)
class ScenarioTwoFarmFullSeasonHN84Normal(Scenario):
    """独立完整场景；只复用领域工具和物理 profile，不复用单场场景流程。"""

    # 与来源场景一致：北京时间 2026-05-05 07:00。
    start_time = datetime(2026, 5, 5, 7, tzinfo=timezone(timedelta(hours=8))).timestamp()
    duration = 170 * 86400
    queue_based_loop = True
    time_increment_in_seconds = 60
    expects_agent_harvest = True
    scenario_input = BRIEFING
    additional_system_prompt = (
        "Manage both farm_a and farm_b through the entire soybean season, including harvest "
        "and storage. Each farm has 64 local ridges and independent state, inventory, fixed "
        "sensors and fixed irrigation. Tractor, Mavic3M, Matrice4T and Robot0 each have one "
        "shared equipment state. Mobile field tools require farm_id. Return unused payload "
        "to its source and unload grain to its origin before changing farms. All farms share "
        "one clock; advancing time or committing one farm's daily physics advances both. "
        "Observe each farm separately, check actual coverage, manage shared fuel and batteries, "
        "and finish only after both farms' harvest and storage work is complete. "
        "Calendar windows in the briefing guide observations; actual field conditions govern actions. "
        "Scenario validation is not implemented yet."
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
            farm._inventory.pesticide_liters = 1200.0
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
                PROFILE_NAME, location="Harbin/Heilongjiang", seed_type=SEED_TYPE,
                cultivar="黑农84标准密度/哈尔滨正常年份baseline",
                density_target_plants_m2=23.0, start_date="2026-05-05",
            )
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

            # 来源场景播后有一次日结算。这里统一推进一天，不分别commit造成双倍时间。
            previous = self.system.advance_time(days=1).oracle().with_id(
                "settle_both_farms_after_planting_1_day").depends_on(previous)

            # 2. 出苗：同一个等待同时作用于两场；全田航测，地面明确抽查0–7。
            previous = self.system.advance_time(days=15).oracle().with_id(
                "wait_both_farms_emergence_15_days").depends_on(previous)
            for farm_id, farm, sensor in farms:
                previous = farm.get_farm_overview().oracle().with_id(
                    f"emergence_{farm_id}_overview").depends_on(previous)
                previous = sensor.read_soil_sensors().oracle().with_id(
                    f"emergence_{farm_id}_soil").depends_on(previous)
                previous = sensor.read_canopy_sensors().oracle().with_id(
                    f"emergence_{farm_id}_canopy").depends_on(previous)
                previous = self.mavic.check_status().oracle().with_id(
                    f"emergence_{farm_id}_mavic_status").depends_on(previous)
                previous = self.mavic.fly_survey(farm_id, 0, 63).oracle().with_id(
                    f"emergence_{farm_id}_ndvi_0_63").depends_on(previous)
                previous = self.robot.check_status().oracle().with_id(
                    f"emergence_{farm_id}_robot_status").depends_on(previous)
                previous = self.robot.inspect_emergence(farm_id, 0, 7).oracle().with_id(
                    f"emergence_{farm_id}_ground_sample_0_7").depends_on(previous)
                previous = self.mavic.charge().oracle().with_id(
                    f"emergence_{farm_id}_charge_mavic").depends_on(previous)
                previous = self.robot.charge().oracle().with_id(
                    f"emergence_{farm_id}_charge_robot").depends_on(previous)
                previous = self.system.advance_time(hours=1).oracle().with_id(
                    f"emergence_{farm_id}_wait_shared_chargers").depends_on(previous)

            # 3. 早期长势：复核两场，Robot抽查28–35，不暗称全田地面覆盖。
            previous = self.system.advance_time(days=23).oracle().with_id(
                "wait_both_farms_early_growth_23_days").depends_on(previous)
            for farm_id, farm, sensor in farms:
                previous = sensor.read_soil_sensors().oracle().with_id(
                    f"early_{farm_id}_soil").depends_on(previous)
                previous = sensor.read_canopy_sensors().oracle().with_id(
                    f"early_{farm_id}_canopy").depends_on(previous)
                previous = self.mavic.fly_survey(farm_id, 0, 63).oracle().with_id(
                    f"early_{farm_id}_ndvi_0_63").depends_on(previous)
                previous = self.robot.inspect_crop_health(farm_id, 28, 35).oracle().with_id(
                    f"early_{farm_id}_health_sample_28_35").depends_on(previous)
                previous = self.mavic.charge().oracle().with_id(
                    f"early_{farm_id}_charge_mavic").depends_on(previous)
                previous = self.robot.charge().oracle().with_id(
                    f"early_{farm_id}_charge_robot").depends_on(previous)
                previous = self.system.advance_time(hours=1).oracle().with_id(
                    f"early_{farm_id}_wait_shared_chargers").depends_on(previous)

            # 4. 初花营养：沿用来源baseline的0.24营养量/2mm载水轻量追肥。
            previous = self.system.advance_time(days=22).oracle().with_id(
                "wait_both_farms_flowering_22_days").depends_on(previous)
            for farm_id, farm, sensor in farms:
                previous = sensor.read_soil_sensors().oracle().with_id(
                    f"flowering_{farm_id}_soil").depends_on(previous)
                previous = sensor.read_canopy_sensors().oracle().with_id(
                    f"flowering_{farm_id}_canopy").depends_on(previous)
                previous = farm.get_ridge_range_state(0, 63).oracle().with_id(
                    f"flowering_{farm_id}_state_0_63").depends_on(previous)
                previous = self.robot.inspect_crop_health(farm_id, 28, 35).oracle().with_id(
                    f"flowering_{farm_id}_health_sample_28_35").depends_on(previous)
                previous = farm.apply_fertigation(
                    0, 63, nutrient_amount=0.24, water_mm=2.0,
                ).oracle().with_id(f"flowering_{farm_id}_light_fertigation_0_63").depends_on(previous)
                previous = self.robot.charge().oracle().with_id(
                    f"flowering_{farm_id}_charge_robot").depends_on(previous)
                previous = self.system.advance_time(hours=1).oracle().with_id(
                    f"flowering_{farm_id}_wait_robot_charge").depends_on(previous)

            previous = self.system.advance_time(days=1).oracle().with_id(
                "settle_both_farms_after_fertigation_1_day").depends_on(previous)

            # 5. 中期：两场分别查水分/NDVI/病虫草；正常年不预设施药。
            previous = self.system.advance_time(days=18).oracle().with_id(
                "wait_both_farms_midseason_18_days").depends_on(previous)
            previous = self.weather.get_current_weather().oracle().with_id(
                "midseason_weather").depends_on(previous)
            previous = self.weather.get_forecast(days=3).oracle().with_id(
                "midseason_forecast").depends_on(previous)
            # 本profile的中期参考日7/25有雨；7/26无雨。明确保留停飞等待与复核。
            # 这是可回放的已选参考路径；Agent遇到其他观测时按实际天气决定等待。
            previous = self.system.advance_time(days=1).oracle().with_id(
                "midseason_wait_rain_1_day").depends_on(previous)
            previous = self.weather.get_current_weather().oracle().with_id(
                "midseason_recheck_flight_weather").depends_on(previous)
            for farm_id, farm, sensor in farms:
                previous = sensor.read_soil_sensors().oracle().with_id(
                    f"midseason_{farm_id}_soil").depends_on(previous)
                previous = self.mavic.fly_survey(farm_id, 0, 63).oracle().with_id(
                    f"midseason_{farm_id}_ndvi_0_63").depends_on(previous)
                previous = self.robot.inspect_pests(farm_id, 56, 63).oracle().with_id(
                    f"midseason_{farm_id}_pest_sample_56_63").depends_on(previous)
                previous = self.mavic.charge().oracle().with_id(
                    f"midseason_{farm_id}_charge_mavic").depends_on(previous)
                previous = self.robot.charge().oracle().with_id(
                    f"midseason_{farm_id}_charge_robot").depends_on(previous)
                previous = self.system.advance_time(hours=1).oracle().with_id(
                    f"midseason_{farm_id}_wait_shared_chargers").depends_on(previous)

            # 6. 灌浆水分：同一热红外无人机分0–31/32–63检查A，再检查B。
            previous = self.system.advance_time(days=8).oracle().with_id(
                "wait_both_farms_podfill_8_days").depends_on(previous)
            previous = self.weather.get_current_weather().oracle().with_id(
                "podfill_weather").depends_on(previous)
            previous = self.weather.get_forecast(days=4).oracle().with_id(
                "podfill_forecast").depends_on(previous)
            # 8/3处于固定雨段，8/5仍有生成雨；参考路径等到8/6再航测，不覆盖天气。
            previous = self.system.advance_time(days=3).oracle().with_id(
                "podfill_wait_rain_3_days").depends_on(previous)
            previous = self.weather.get_current_weather().oracle().with_id(
                "podfill_recheck_flight_weather").depends_on(previous)
            for farm_id, farm, sensor in farms:
                previous = sensor.read_soil_sensors().oracle().with_id(
                    f"podfill_{farm_id}_soil").depends_on(previous)
                previous = sensor.read_canopy_sensors().oracle().with_id(
                    f"podfill_{farm_id}_canopy").depends_on(previous)
                previous = self.matrice.check_status().oracle().with_id(
                    f"podfill_{farm_id}_matrice_status").depends_on(previous)
                for start, end in ((0, 31), (32, 63)):
                    previous = self.matrice.fly_survey(farm_id, start, end).oracle().with_id(
                        f"podfill_{farm_id}_thermal_{start}_{end}").depends_on(previous)
                    previous = self.matrice.charge().oracle().with_id(
                        f"podfill_{farm_id}_charge_matrice_after_{end}").depends_on(previous)
                    previous = self.system.advance_time(minutes=30).oracle().with_id(
                        f"podfill_{farm_id}_wait_matrice_after_{end}").depends_on(previous)

            previous = self.system.advance_time(days=1).oracle().with_id(
                "settle_both_farms_after_podfill_1_day").depends_on(previous)

            # 7. 成熟/收获/入库：每一场独立核对、收获、卸粮、干燥和入库。
            previous = self.system.advance_time(days=39).oracle().with_id(
                "wait_both_farms_harvest_39_days").depends_on(previous)
            previous = self.weather.get_current_weather().oracle().with_id(
                "harvest_weather").depends_on(previous)
            previous = self.weather.get_forecast(days=3).oracle().with_id(
                "harvest_forecast").depends_on(previous)
            previous = self.tractor.attach_implement("harvester").oracle().with_id(
                "harvest_attach_shared_harvester").depends_on(previous)
            for farm_id, farm, sensor in farms:
                previous = sensor.read_soil_sensors().oracle().with_id(
                    f"harvest_{farm_id}_trafficability").depends_on(previous)
                previous = farm.get_farm_overview().oracle().with_id(
                    f"harvest_{farm_id}_overview").depends_on(previous)
                previous = farm.get_ridge_range_state(0, 63).oracle().with_id(
                    f"harvest_{farm_id}_maturity_moisture_0_63").depends_on(previous)
                previous = self.tractor.get_status().oracle().with_id(
                    f"harvest_{farm_id}_tractor_status").depends_on(previous)
                previous = self.tractor.refuel(farm_id, 100.0).oracle().with_id(
                    f"harvest_{farm_id}_refuel").depends_on(previous)
                for start in range(0, NUM_RIDGES, 4):
                    end = start + 3
                    previous = self.tractor.harvest(farm_id, start, end).oracle().with_id(
                        f"harvest_{farm_id}_{start}_{end}").depends_on(previous)
                    previous = self.tractor.unload_grain(farm_id).oracle().with_id(
                        f"harvest_{farm_id}_unload_{start}_{end}").depends_on(previous)
                # dry_grain 在已安全时返回 drying_skipped，不虚构一次烘干消耗。
                previous = farm.dry_grain(target_moisture_pct=13.0).oracle().with_id(
                    f"storage_{farm_id}_dry_if_needed").depends_on(previous)
                previous = farm.store_grain().oracle().with_id(
                    f"storage_{farm_id}_store").depends_on(previous)
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
                content="双农场全季参考流程结束；请分别核对两场收获入库、库存及共享设备记录。validate暂未实现。",
            ).oracle().with_id("report_both_farms_full_season").depends_on(previous)
        self.events = events
        return events

    def validate(self, env=None) -> None:
        """TODO：按当前要求暂留空；None表示没有实现评分，不代表任务成功。"""
        return None
