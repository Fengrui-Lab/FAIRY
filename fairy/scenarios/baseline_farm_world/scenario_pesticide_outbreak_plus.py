from __future__ import annotations

from fairy.apps.farm_world.drone_app import DroneApp
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.field_ops_app import FieldOpsApp
from fairy.apps.farm_world.robot_app import RobotApp
from fairy.apps.farm_world.sensor_app import SensorApp
from fairy.apps.farm_world.tractor_app import TractorApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.system import SystemApp
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.workflow import WorkflowStep
from fairy.scenarios.baseline_farm_world.Contants import DETAILED_BRIEFING, local_timestamp

_OUTBREAK_START = 15
_OUTBREAK_END = 39
_REFUEL_L = 80.0
_PESTICIDE_LOAD_L = 250.0

# Ridges to inspect across the full outbreak zone
_INSPECT_RIDGES = [15, 20, 25, 30, 35, 39]

SCENARIO_INPUT_DETAIL = """
作物已进入V4-V5生长阶段（播种后约45天），固定传感器显示多个区域NDVI异常偏低，怀疑大面积蚜虫爆发。
在今天完成巡查、复核和喷药处理。
请按以下步骤操作：
1. 查看当前天气，确认风速<5m/s、无雨（喷药条件）。
2. 查看未来3天预报，确认喷药窗口。
3. 读取冠层传感器，找出NDVI偏低的区域。
4. 检查Mavic3M状态，对冠层传感器提示的异常带进行航测，确认虫害范围；如果因电量不足中途返航，给无人机充电（约30分钟）。
   充电完成后继续飞剩余未覆盖的区域。
5. 读取土壤传感器，确认VWC<0.35（拖拉机可下地）。
6. 检查Robot0状态，用Robot0沿无人机确认的连续虫害带做6个地面复核点：从低垄号到高垄号按约5垄间距抽样，避开未见虫的缓冲垄，并在中心热点附近加密，确认是否为蚜虫；
    如果电量不足，给Robot0充电（约60分钟）。充电完成后继续复核剩余未区域。
7. 检查拖拉机状态和仓库库存。
8. 给拖拉机挂接喷药器，加80.0L油，再向喷药箱装250.0L药。
9. 用拖拉机喷杆按喷药（每趟最多10垄），覆盖全部虫害区域。
10. 全部完成后卸载喷药器、立即结束任务向我汇报。
"""

SCENARIO_INPUT = """传感器显示大面积虫害，全面巡查核实后大规模喷药处理，完成后汇报。"""


class ScenarioFarmWorldPesticideOutbreakPlus(Scenario):
    """
    Large-scale pest outbreak with battery-constrained drone and robot.

    Compared to the base scenario:
    - Mavic3M starts at 35% battery → partial survey → charge → finish survey
    - Robot0 inspects 6 evenly spaced representative ridges
      → 5 inspections exhaust battery → charge → finish the last point
    - Then tractor boom sprays as before

    Drone charge: ~30 min.  Robot charge: ~60 min.
    """

    scenario_id: str = "scenario_farm_world_pesticide_outbreak_plus"
    scenario_input: str = SCENARIO_INPUT_DETAIL if DETAILED_BRIEFING else SCENARIO_INPUT
    start_time: float | None = (
        local_timestamp(2026, 6, 15, 8, 0, 0)
    )
    time_increment_in_seconds: int = 60

    def initiate_scenario(self):
        if self.apps:
            return
        farm_world = FarmWorldApp()
        weather = WeatherApp()
        sensor = SensorApp(farm_world_app=farm_world)
        mavic = DroneApp(
            farm_world_app=farm_world,
            weather_app=weather,
            name="Mavic3M",
            description="DJI Mavic 3 Multispectral — multispectral NDVI mapping drone",
            speed_ms=5.0,
            effective_ridges_per_pass=7,
            battery_pct_per_ridge=1.0,
        )
        matrice = DroneApp(
            farm_world_app=farm_world,
            weather_app=weather,
            name="Matrice4T",
            description="DJI Matrice 4T — thermal imaging drone",
            speed_ms=4.0,
            effective_ridges_per_pass=5,
            battery_pct_per_ridge=1.5,
        )
        robot_0 = RobotApp(
            farm_world_app=farm_world,
            weather_app=weather,
            name="Robot0",
            description="Zhiyuan D1 Max #1 — ground-level pest/disease inspection robot",
        )
        robot_1 = RobotApp(
            farm_world_app=farm_world,
            weather_app=weather,
            name="Robot1",
            description="Zhiyuan D1 Max #2 — ground-level pest/disease inspection robot",
        )
        tractor = TractorApp(farm_world_app=farm_world, weather_app=weather)
        field_ops = FieldOpsApp(farm_world_app=farm_world, weather_app=weather)
        system = SystemApp()

        self.apps = [
            farm_world, weather, sensor, mavic, matrice,
            robot_0, robot_1, tractor, field_ops, system,
        ]

        # --- Configure initial state ---
        weather.set_weather(
            date="2026-06-15",
            temp_c=22.0,
            humidity_pct=55.0,
            wind_speed_ms=2.0,
            rainfall_mm=0.0,
            solar_radiation=480.0,
            forecast=[
                {"date": "2026-06-16", "temp_c": 23.0, "humidity_pct": 52.0,
                 "wind_speed_ms": 2.5, "rainfall_mm": 0.0, "solar_radiation": 490.0},
                {"date": "2026-06-17", "temp_c": 20.0, "humidity_pct": 78.0,
                 "wind_speed_ms": 5.5, "rainfall_mm": 12.0, "solar_radiation": 200.0},
                {"date": "2026-06-18", "temp_c": 19.0, "humidity_pct": 82.0,
                 "wind_speed_ms": 4.0, "rainfall_mm": 6.0, "solar_radiation": 240.0},
            ],
            avg_soil_vwc=0.24,
        )
        farm_world.set_season_phase("growing")

        for i in range(64):
            r = farm_world.get_ridge(i)
            r.planted = True
            r.seed_type = "STANDARD"
            r.seed_spacing_cm = 12.0
            r.seeds_planted = 4467
            r.days_since_planted = 45
            r.growth_stage = "V4"
            r.soil_vwc = 0.23 + (i % 4) * 0.01
            r.soil_temp_c = 20.0 + (i % 3) * 0.3
            r.yield_potential = 0.95
            r.disease_pressure_base = 0.02
            r.disease_pressure = 0.02

            if _OUTBREAK_START <= i <= _OUTBREAK_END:
                center = (_OUTBREAK_START + _OUTBREAK_END) / 2.0
                dist = abs(i - center) / ((_OUTBREAK_END - _OUTBREAK_START) / 2.0)
                r.pest_pressure_base = round(0.50 - 0.20 * dist, 2)
                r.ndvi = round(0.65 - r.pest_pressure_base * 0.35, 3)
                r.canopy_temp_c = round(24.0 + r.pest_pressure_base * 4.0, 2)
            else:
                r.pest_pressure_base = 0.02
                r.ndvi = 0.65 + (i % 4) * 0.03
                r.canopy_temp_c = 24.0 + (i % 3) * 0.3
            r.pest_pressure = r.pest_pressure_base

        tractor._completed_prep_ops = ["level", "base_fertilize", "form_ridges"]
        tractor._fuel_tank_l = 15.0
        tractor._pesticide_tank_l = 0.0

        # Drone starts low — forces a mid-survey charge
        mavic._battery_pct = 35.0

    def oracle_solution(self, run_oracle=False):
        weather = self.get_typed_app(WeatherApp)
        sensor = self.get_typed_app(SensorApp)
        farm_world = self.get_typed_app(FarmWorldApp)
        mavic = self.get_typed_app(DroneApp, app_name="Mavic3M")
        robot_0 = self.get_typed_app(RobotApp, app_name="Robot0")
        tractor = self.get_typed_app(TractorApp)
        system = self.get_typed_app(SystemApp)

        # ---- Phase 1: Weather & sensor diagnosis ----

        if run_oracle:
            print(weather.get_current_weather())
        self.workflow.add_node(WorkflowStep(
            name="check_weather", op_type="READ",
            tool_name="WeatherApp__get_current_weather", tool_args={},
            depends_on=[],
        ))

        if run_oracle:
            print(weather.get_forecast(days=3))
        self.workflow.add_node(WorkflowStep(
            name="check_forecast", op_type="READ",
            tool_name="WeatherApp__get_forecast", tool_args={"days": 3},
            depends_on=["check_weather"],
        ))

        if run_oracle:
            print(sensor.read_canopy_sensors())
        self.workflow.add_node(WorkflowStep(
            name="read_canopy", op_type="READ",
            tool_name="SensorApp__read_canopy_sensors", tool_args={},
            depends_on=["check_forecast"],
        ))

        # ---- Phase 2: Drone survey (partial → charge → finish) ----

        if run_oracle:
            print(mavic.check_status())
        self.workflow.add_node(WorkflowStep(
            name="check_drone", op_type="READ",
            tool_name="Mavic3M__check_status", tool_args={},
            depends_on=["read_canopy"],
        ))

        # First survey attempt — will abort partway due to low battery
        if run_oracle:
            print(mavic.fly_survey(11, 43))
        self.workflow.add_node(WorkflowStep(
            name="survey_partial", op_type="READ",
            tool_name="Mavic3M__fly_survey",
            tool_args={"start_ridge": 11, "end_ridge": 43},
            depends_on=["check_drone"],
        ))

        # Charge drone
        if run_oracle:
            print(mavic.charge())
        self.workflow.add_node(WorkflowStep(
            name="drone_charge", op_type="WRITE",
            tool_name="Mavic3M__charge", tool_args={},
            depends_on=["survey_partial"],
        ))

        # Wait for drone charge (~30 min)
        if run_oracle:
            system.wait_for_notification(timeout=30 * 60)
        self.workflow.add_node(WorkflowStep(
            name="wait_drone_charge", op_type="READ",
            tool_name="SystemApp__wait_for_notification",
            tool_args={"timeout": 30 * 60},
            depends_on=["drone_charge"],
        ))

        # Finish survey — cover the ridges missed in first attempt
        if run_oracle:
            print(mavic.fly_survey(25, 43))
        self.workflow.add_node(WorkflowStep(
            name="survey_finish", op_type="READ",
            tool_name="Mavic3M__fly_survey",
            tool_args={"start_ridge": 25, "end_ridge": 43},
            depends_on=["wait_drone_charge"],
        ))

        # ---- Phase 3: Soil check ----

        if run_oracle:
            print(sensor.read_soil_sensors())
        self.workflow.add_node(WorkflowStep(
            name="read_soil", op_type="READ",
            tool_name="SensorApp__read_soil_sensors", tool_args={},
            depends_on=["survey_finish"],
        ))

        # ---- Phase 4: Robot ground inspection (5 ridges → charge → 1 ridge) ----

        if run_oracle:
            print(robot_0.check_status())
        self.workflow.add_node(WorkflowStep(
            name="check_robot", op_type="READ",
            tool_name="Robot0__check_status", tool_args={},
            depends_on=["read_soil"],
        ))

        # First 5 inspections (100% → 0%)
        prev = "check_robot"
        for idx, ridge_id in enumerate(_INSPECT_RIDGES[:5]):
            name = f"robot_inspect_{ridge_id}"
            if run_oracle:
                print(robot_0.inspect_ridge(ridge_id))
            self.workflow.add_node(WorkflowStep(
                name=name, op_type="READ",
                tool_name="Robot0__inspect_ridge",
                tool_args={"ridge_id": ridge_id},
                depends_on=[prev],
            ))
            prev = name

        # Robot charge
        if run_oracle:
            print(robot_0.charge())
        self.workflow.add_node(WorkflowStep(
            name="robot_charge", op_type="WRITE",
            tool_name="Robot0__charge", tool_args={},
            depends_on=[prev],
        ))

        # Wait for robot charge (~60 min)
        if run_oracle:
            system.wait_for_notification(timeout=60 * 60)
        self.workflow.add_node(WorkflowStep(
            name="wait_robot_charge", op_type="READ",
            tool_name="SystemApp__wait_for_notification",
            tool_args={"timeout": 60 * 60},
            depends_on=["robot_charge"],
        ))

        # Remaining inspection
        prev = "wait_robot_charge"
        for ridge_id in _INSPECT_RIDGES[5:]:
            name = f"robot_inspect_{ridge_id}"
            if run_oracle:
                print(robot_0.inspect_ridge(ridge_id))
            self.workflow.add_node(WorkflowStep(
                name=name, op_type="READ",
                tool_name="Robot0__inspect_ridge",
                tool_args={"ridge_id": ridge_id},
                depends_on=[prev],
            ))
            prev = name

        # ---- Phase 5: Prepare tractor & spray ----

        if run_oracle:
            print(tractor.get_status())
        self.workflow.add_node(WorkflowStep(
            name="check_tractor", op_type="READ",
            tool_name="TractorApp__get_status", tool_args={},
            depends_on=[prev],
        ))

        if run_oracle:
            print(farm_world.get_inventory())
        self.workflow.add_node(WorkflowStep(
            name="check_inventory", op_type="READ",
            tool_name="FarmWorldApp__get_inventory", tool_args={},
            depends_on=["check_tractor"],
        ))

        if run_oracle:
            print(tractor.attach_implement("sprayer"))
        self.workflow.add_node(WorkflowStep(
            name="attach_sprayer", op_type="WRITE",
            tool_name="TractorApp__attach_implement",
            tool_args={"implement": "sprayer"},
            depends_on=["check_inventory"],
        ))

        if run_oracle:
            print(tractor.refuel(_REFUEL_L))
        self.workflow.add_node(WorkflowStep(
            name="refuel", op_type="WRITE",
            tool_name="TractorApp__refuel", tool_args={"liters": _REFUEL_L},
            depends_on=["attach_sprayer"],
        ))

        if run_oracle:
            print(tractor.refill_pesticide_tank(_PESTICIDE_LOAD_L))
        self.workflow.add_node(WorkflowStep(
            name="load_pesticide", op_type="WRITE",
            tool_name="TractorApp__refill_pesticide_tank",
            tool_args={"liters": _PESTICIDE_LOAD_L},
            depends_on=["refuel"],
        ))

        # Spray 3 passes
        if run_oracle:
            print(tractor.apply_pesticide(15, 24))
        self.workflow.add_node(WorkflowStep(
            name="spray_pass_1", op_type="WRITE",
            tool_name="TractorApp__apply_pesticide",
            tool_args={"start_ridge": 15, "end_ridge": 24},
            depends_on=["load_pesticide"],
        ))

        if run_oracle:
            print(tractor.apply_pesticide(25, 34))
        self.workflow.add_node(WorkflowStep(
            name="spray_pass_2", op_type="WRITE",
            tool_name="TractorApp__apply_pesticide",
            tool_args={"start_ridge": 25, "end_ridge": 34},
            depends_on=["spray_pass_1"],
        ))

        if run_oracle:
            print(tractor.apply_pesticide(35, 39))
        self.workflow.add_node(WorkflowStep(
            name="spray_pass_3", op_type="WRITE",
            tool_name="TractorApp__apply_pesticide",
            tool_args={"start_ridge": 35, "end_ridge": 39},
            depends_on=["spray_pass_2"],
        ))

        if run_oracle:
            print(tractor.detach_implement())
        self.workflow.add_node(WorkflowStep(
            name="detach_sprayer", op_type="WRITE",
            tool_name="TractorApp__detach_implement", tool_args={},
            depends_on=["spray_pass_3"],
        ))
