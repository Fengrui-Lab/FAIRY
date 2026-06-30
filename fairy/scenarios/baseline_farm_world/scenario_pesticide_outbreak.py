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
_INSPECT_RIDGE = 27
_REFUEL_L = 80.0
_PESTICIDE_LOAD_L = 250.0

SCENARIO_INPUT_DETAIL = """
作物已进入V4-V5生长阶段（播种后约45天），固定传感器显示多个区域NDVI异常偏低，怀疑大面积蚜虫爆发。
请按以下步骤操作：
1. 查看当前天气，确认风速<5m/s、无雨（喷药条件）。
2. 查看未来3天预报，确认喷药窗口（后天有雨，今天必须喷）。
3. 读取冠层传感器，找出NDVI偏低的区域。
4. 检查Mavic3M状态，飞行巡查异常区域确认虫害范围。
5. 读取土壤传感器，确认VWC<0.35（拖拉机可下地）。
6. 检查Robot0状态，派机器狗到虫害中心区域地面复核确认蚜虫。
7. 检查拖拉机状态和仓库库存。
8. 给拖拉机装载喷药器、 加80.0L油、装250.0L药。
9. 用拖拉机喷杆分多趟喷药（每趟最多10垄），覆盖全部虫害区域。
10. 全部完成后卸载喷药器、立即结束任务向我汇报。
"""

SCENARIO_INPUT = """传感器显示大面积虫害，核实后大规模喷药处理，完成后汇报。"""


class ScenarioFarmWorldPesticideOutbreak(Scenario):
    """
    Large-scale pest outbreak response with tractor boom spraying.

    Crops are at V4-V5 stage. A major aphid outbreak spans ridges 15-39
    (25 ridges). The agent must follow a layered monitoring workflow:
    canopy sensors detect anomaly → drone confirms hotspot extent →
    robot ground-verifies → tractor boom sprays at scale (multi-pass).
    Rain forecast on day 3 creates urgency to spray today.
    """

    scenario_id: str = "scenario_farm_world_pesticide_outbreak"
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
        mavic._battery_pct = 80.0

    def oracle_solution(self, run_oracle=False):
        weather = self.get_typed_app(WeatherApp)
        sensor = self.get_typed_app(SensorApp)
        farm_world = self.get_typed_app(FarmWorldApp)
        mavic = self.get_typed_app(DroneApp, app_name="Mavic3M")
        robot_0 = self.get_typed_app(RobotApp, app_name="Robot0")
        tractor = self.get_typed_app(TractorApp)

        # --- Phase 1: Diagnosis ---

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
            depends_on=["check_forecast"],
        ))

        if run_oracle:
            print(mavic.check_status())
        self.workflow.add_node(WorkflowStep(
            name="check_drone", op_type="READ",
            tool_name="Mavic3M__check_status", tool_args={},
            depends_on=["read_canopy"],
        ))

        if run_oracle:
            print(mavic.fly_survey(11, 43))
        self.workflow.add_node(WorkflowStep(
            name="survey_outbreak", op_type="READ",
            tool_name="Mavic3M__fly_survey",
            tool_args={"start_ridge": 11, "end_ridge": 43},
            depends_on=["check_drone"],
        ))

        if run_oracle:
            print(sensor.read_soil_sensors())
        self.workflow.add_node(WorkflowStep(
            name="read_soil", op_type="READ",
            tool_name="SensorApp__read_soil_sensors", tool_args={},
            depends_on=["survey_outbreak"],
        ))

        if run_oracle:
            print(robot_0.check_status())
        self.workflow.add_node(WorkflowStep(
            name="check_robot", op_type="READ",
            tool_name="Robot0__check_status", tool_args={},
            depends_on=["read_soil"],
        ))

        if run_oracle:
            print(robot_0.inspect_ridge(_INSPECT_RIDGE))
        self.workflow.add_node(WorkflowStep(
            name="robot_inspect", op_type="READ",
            tool_name="Robot0__inspect_ridge",
            tool_args={"ridge_id": _INSPECT_RIDGE},
            depends_on=["check_robot"],
        ))

        # --- Phase 2: Prepare tractor ---

        if run_oracle:
            print(tractor.get_status())
        self.workflow.add_node(WorkflowStep(
            name="check_tractor", op_type="READ",
            tool_name="TractorApp__get_status", tool_args={},
            depends_on=["robot_inspect"],
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
            tool_name="TractorApp__attach_implement", tool_args={"implement": "sprayer"},
            depends_on=["check_inventory"],
        ))

        if run_oracle:
            print(tractor.refuel(_REFUEL_L))
        self.workflow.add_node(WorkflowStep(
            name="refuel", op_type="WRITE",
            tool_name="TractorApp__refuel", tool_args={"liters": _REFUEL_L},
            depends_on=["check_inventory"],
        ))

        if run_oracle:
            print(tractor.refill_pesticide_tank(_PESTICIDE_LOAD_L))
        self.workflow.add_node(WorkflowStep(
            name="load_pesticide", op_type="WRITE",
            tool_name="TractorApp__refill_pesticide_tank",
            tool_args={"liters": _PESTICIDE_LOAD_L},
            depends_on=["refuel"],
        ))

        # --- Phase 3: Spray (3 passes) ---

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
            name="detach_furrower", op_type="WRITE",
            tool_name="TractorApp__detach_implement", tool_args={},
            depends_on=["spray_pass_3"],
        ))
