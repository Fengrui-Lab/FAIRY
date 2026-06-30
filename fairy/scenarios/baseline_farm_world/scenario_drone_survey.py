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

_ANOMALY_START = 18
_ANOMALY_END = 18

SCENARIO_INPUT_DETAIL = """
作物已进入V4生长阶段（播种后约42天），需要进行例行无人机巡查监测作物健康。
请按以下步骤操作：
1. 查看天气，确认无雨且风速<12m/s（无人机飞行条件）。
2. Mavic3M 检查无人机电量（当前约65%，不满）。
3. 飞行巡查全部64垄。飞到电量不足时会自动返航，返回部分结果。
4. 返航后，检查无人机状态，给无人机充电（约30分钟）。
5. 充电完成后用 继续飞剩余未覆盖的区域。
6. 全部飞完后，如果发现NDVI偏低的区域，然后派机器狗到异常垄做地面巡检确认病虫害，执行前先检查机器狗Robot0电量，。
7. 全部完成后立即结束任务向我汇报巡查结果。
"""

SCENARIO_INPUT = """作物进入V4阶段了，飞一圈无人机看看长势。发现问题的话派机器狗去确认一下。完成后告诉我。"""


class ScenarioFarmWorldDroneSurvey(Scenario):
    """
    Routine drone survey for crop health monitoring.

    Crops are at V4-V5 stage. The agent must check weather conditions,
    verify drone battery levels, fly systematic surveys across all 64 ridges,
    charge the drone mid-way if needed, identify anomalies (low NDVI zones),
    and dispatch a robot for ground-truth inspection of suspicious areas.
    """

    scenario_id: str = "scenario_farm_world_drone_survey"
    scenario_input: str = SCENARIO_INPUT_DETAIL if DETAILED_BRIEFING else SCENARIO_INPUT
    start_time: float | None = (
        local_timestamp(2026, 6, 5, 8, 0, 0)
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
            description="DJI Mavic 3 Multispectral — multispectral imaging drone for NDVI vegetation index mapping",
            speed_ms=5.0,
            effective_ridges_per_pass=7,
            battery_pct_per_ridge=1.0,
        )
        matrice = DroneApp(
            farm_world_app=farm_world,
            weather_app=weather,
            name="Matrice4T",
            description="DJI Matrice 4T — thermal imaging drone for canopy temperature and stress detection",
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
            date="2026-06-05",
            temp_c=24.0,
            humidity_pct=55.0,
            wind_speed_ms=3.0,
            rainfall_mm=0.0,
            solar_radiation=520.0,
            forecast=[
                {"date": "2026-06-06", "temp_c": 25.0, "humidity_pct": 50.0,
                 "wind_speed_ms": 2.5, "rainfall_mm": 0.0, "solar_radiation": 530.0},
                {"date": "2026-06-07", "temp_c": 22.0, "humidity_pct": 65.0,
                 "wind_speed_ms": 4.0, "rainfall_mm": 3.0, "solar_radiation": 350.0},
            ],
            avg_soil_vwc=0.23,
        )
        farm_world.set_season_phase("growing")

        for i in range(64):
            r = farm_world.get_ridge(i)
            r.planted = True
            r.seed_type = "STANDARD"
            r.days_since_planted = 42
            r.growth_stage = "V4"
            r.soil_vwc = 0.22 + (i % 4) * 0.01
            r.soil_temp_c = 20.0 + (i % 3) * 0.3
            if _ANOMALY_START <= i <= _ANOMALY_END:
                r.pest_pressure_base = 0.3 + (i % 3) * 0.1
                r.pest_pressure = r.pest_pressure_base
            else:
                r.pest_pressure_base = 0.02
                r.pest_pressure = 0.02

        mavic._battery_pct = 65.0

    def oracle_solution(self, run_oracle=False):
        weather = self.get_typed_app(WeatherApp)
        mavic = self.get_typed_app(DroneApp, app_name="Mavic3M")
        robot_0 = self.get_typed_app(RobotApp, app_name="Robot0")
        system = self.get_typed_app(SystemApp)

        # Pre-flight checks
        if run_oracle:
            print(weather.get_current_weather())
        self.workflow.add_node(WorkflowStep(
            name="check_weather", op_type="READ",
            tool_name="WeatherApp__get_current_weather", tool_args={}, depends_on=[],
        ))

        if run_oracle:
            print(mavic.check_status())
        self.workflow.add_node(WorkflowStep(
            name="check_drone", op_type="READ",
            tool_name="Mavic3M__check_status", tool_args={},
            depends_on=["check_weather"],
        ))

        # First survey attempt (will return partial due to low battery)
        if run_oracle:
            print(mavic.fly_survey(0, 63))
        self.workflow.add_node(WorkflowStep(
            name="survey_first", op_type="READ",
            tool_name="Mavic3M__fly_survey",
            tool_args={"start_ridge": 0, "end_ridge": 63},
            depends_on=["check_drone"],
        ))

        # Check battery after partial return
        if run_oracle:
            print(mavic.check_status())
        self.workflow.add_node(WorkflowStep(
            name="check_battery_after", op_type="READ",
            tool_name="Mavic3M__check_status", tool_args={},
            depends_on=["survey_first"],
        ))

        # Charge drone
        if run_oracle:
            print(mavic.charge())
        self.workflow.add_node(WorkflowStep(
            name="charge_drone", op_type="WRITE",
            tool_name="Mavic3M__charge", tool_args={},
            depends_on=["check_battery_after"],
        ))

        if run_oracle:
            system.wait_for_notification(timeout=30 * 60)
        self.workflow.add_node(WorkflowStep(
            name="wait_for_charge_complete", op_type="READ",
            tool_name="SystemApp__wait_for_notification",
            tool_args={"timeout": 30 * 60},
            depends_on=["charge_drone"],
        ))

        # Continue survey: remaining ridges 42-63
        if run_oracle:
            print(mavic.fly_survey(42, 63))
        self.workflow.add_node(WorkflowStep(
            name="survey_remaining", op_type="READ",
            tool_name="Mavic3M__fly_survey",
            tool_args={"start_ridge": 42, "end_ridge": 63},
            depends_on=["wait_for_charge_complete"],
        ))

        # Ground-truth with robot
        if run_oracle:
            print(robot_0.check_status())
        self.workflow.add_node(WorkflowStep(
            name="check_robot", op_type="READ",
            tool_name="Robot0__check_status", tool_args={},
            depends_on=["survey_remaining"],
        ))

        if run_oracle:
            print(robot_0.inspect_ridge(18))
        self.workflow.add_node(WorkflowStep(
            name="robot_inspect", op_type="READ",
            tool_name="Robot0__inspect_ridge", tool_args={"ridge_id": 18},
            depends_on=["check_robot"],
        ))
