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
_BOOM_START = 15
_MANUAL_RIDGE = 25
_PESTICIDE_LOAD_L = 100.0
_REFUEL_L = 80.0

SCENARIO_INPUT_DETAIL = """
昨天 Mavic3M 巡查发现 ridges 15-25 区域 NDVI 偏低，怀疑蚜虫爆发。
今天请按如下流程处理：
1. 查看当前天气，确认风速<5 m/s、无雨（喷药条件）。
2. 看 3 天预报，确认今天和明天的喷药窗口。
3. 读冠层传感器，再看一下 NDVI 分布。
4. 先使用Mavic3M核查异常区，使用前先检查机器状态。
5. 读土壤传感器，确认 VWC<0.35（机器狗可下地）。
6. 再使用Robot0地面复核Mavic3M报告的异常区域，使用前先检查机器状态。
7. 人工对异常点施药。
8. 全部完成立即结束任务后汇报。
"""

SCENARIO_INPUT = """昨天无人机发现 ridges 15-25 有蚜虫迹象。请核实后用合适的方式喷药处理，完成后汇报。"""


class ScenarioFarmWorldPesticide(Scenario):
    """
    Mid-season pesticide response after drone+robot confirmation.

    Yesterday's Mavic survey flagged ridges 15-25 for low NDVI / elevated canopy
    temperature. The agent must verify conditions, refuel/refill the tractor,
    apply pesticide via boom sprayer on ridges 15-24, and manually spray ridge 25.
    """

    scenario_id: str = "scenario_farm_world_pesticide"
    scenario_input: str = SCENARIO_INPUT_DETAIL if DETAILED_BRIEFING else SCENARIO_INPUT
    start_time: float | None = (
        local_timestamp(2026, 6, 6, 9, 0, 0)
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
            date="2026-06-06",
            temp_c=23.0,
            humidity_pct=50.0,
            wind_speed_ms=2.0,
            rainfall_mm=0.0,
            solar_radiation=500.0,
            forecast=[
                {"date": "2026-06-07", "temp_c": 24.0, "humidity_pct": 48.0,
                 "wind_speed_ms": 1.5, "rainfall_mm": 0.0, "solar_radiation": 520.0},
                {"date": "2026-06-08", "temp_c": 21.0, "humidity_pct": 72.0,
                 "wind_speed_ms": 5.5, "rainfall_mm": 9.0, "solar_radiation": 220.0},
                {"date": "2026-06-09", "temp_c": 20.0, "humidity_pct": 80.0,
                 "wind_speed_ms": 4.0, "rainfall_mm": 4.0, "solar_radiation": 260.0},
            ],
            avg_soil_vwc=0.23,
        )
        farm_world.set_season_phase("growing")

        for i in range(64):
            r = farm_world.get_ridge(i)
            r.planted = True
            r.seed_type = "STANDARD"
            r.seed_spacing_cm = 12.0
            r.seeds_planted = 4467
            r.days_since_planted = 43
            r.growth_stage = "V4"
            r.soil_vwc = 0.22 + (i % 4) * 0.01
            r.soil_temp_c = 20.0 + (i % 3) * 0.3
            r.yield_potential = 0.95

            if i == _MANUAL_RIDGE:
                r.pest_pressure_base = 0.65
            else:
                r.pest_pressure_base = 0.02
            r.pest_pressure = r.pest_pressure_base
            r.disease_pressure_base = 0.02
            r.disease_pressure = 0.02

        tractor._completed_prep_ops = ["level", "base_fertilize", "form_ridges"]
        tractor._fuel_tank_l = 10.0
        tractor._pesticide_tank_l = 0.0
        mavic._battery_pct = 80.0

    def oracle_solution(self, run_oracle=False):
        weather = self.get_typed_app(WeatherApp)
        sensor = self.get_typed_app(SensorApp)
        mavic = self.get_typed_app(DroneApp, app_name="Mavic3M")
        robot_0 = self.get_typed_app(RobotApp, app_name="Robot0")
        field_ops = self.get_typed_app(FieldOpsApp)

        if run_oracle:
            print(weather.get_current_weather())
        self.workflow.add_node(WorkflowStep(
            name="check_weather", op_type="READ",
            tool_name="WeatherApp__get_current_weather", tool_args={}, depends_on=[],
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
            depends_on=["check_weather"],
        ))

        if run_oracle:
            print(mavic.check_status())
        self.workflow.add_node(WorkflowStep(
            name="check_drone", op_type="READ",
            tool_name="Mavic3M__check_status", tool_args={},
            depends_on=["read_canopy"],
        ))

        if run_oracle:
            print(mavic.fly_survey(_BOOM_START, _MANUAL_RIDGE))
        self.workflow.add_node(WorkflowStep(
            name="survey_suspect", op_type="READ",
            tool_name="Mavic3M__fly_survey",
            tool_args={"start_ridge": _BOOM_START, "end_ridge": _MANUAL_RIDGE},
            depends_on=["check_drone"],
        ))

        if run_oracle:
            print(sensor.read_soil_sensors())
        self.workflow.add_node(WorkflowStep(
            name="read_soil", op_type="READ",
            tool_name="SensorApp__read_soil_sensors", tool_args={},
            depends_on=["survey_suspect"],
        ))

        if run_oracle:
            print(robot_0.check_status())
        self.workflow.add_node(WorkflowStep(
            name="check_robot", op_type="READ",
            tool_name="Robot0__check_status", tool_args={},
            depends_on=["read_soil"],
        ))

        if run_oracle:
            print(robot_0.inspect_ridge(25))
        self.workflow.add_node(WorkflowStep(
            name="robot_inspect", op_type="READ",
            tool_name="Robot0__inspect_ridge", tool_args={"ridge_id": 25},
            depends_on=["check_robot"],
        ))

        if run_oracle:
            print(field_ops.apply_pesticide_manual(_MANUAL_RIDGE))
        self.workflow.add_node(WorkflowStep(
            name="spray_manual", op_type="WRITE",
            tool_name="FieldOpsApp__apply_pesticide_manual",
            tool_args={"ridge_id": _MANUAL_RIDGE},
            depends_on=["spray_boom"],
        ))
