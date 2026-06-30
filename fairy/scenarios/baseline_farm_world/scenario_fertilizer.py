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

_DEFICIENT_START = 22
_DEFICIENT_END = 27
_SURVEY_START = 22
_SURVEY_END = 32
_FERTILIZER_KG_PER_RIDGE = 10.0
_FERTILIZER_LOAD_KG = 100.0

SCENARIO_INPUT_DETAIL = """
作物已进入V3-V4生长阶段（播种后约35天），冠层传感器显示部分区域NDVI偏低，怀疑营养缺乏。
由于大豆固氮作用，氮肥需求较低，但磷钾平衡仍影响产量。
请按以下步骤操作：
1. 查看当前天气，确认适合下地作业（无雨）。
2. 查看未来3天预报，确认作业窗口。
3. 读取冠层传感器，找出NDVI偏低的区域。
4. 检查Mavic3M状态，飞行巡查异常区域确认缺肥情况。
5. 检查拖拉机状态（油量、施肥机）和仓库肥料库存。
6. 装载肥料100kg，对缺肥区（NDVI小于0.45）域追施肥料（每垄约10kg）。
7. 全部完成后立即结束任务向我汇报。
"""

SCENARIO_INPUT = """作物进入V3阶段，部分区域长势偏弱。检查后追肥，完成后汇报。"""


class ScenarioFarmWorldFertilizer(Scenario):
    """
    Mid-season nutrient management triggered by observed canopy deficiency.

    Crops are at V3-V4 stage. Ridges 22-27 show low NDVI and reduced yield
    potential, indicating nutrient deficiency. The agent must diagnose the
    problem via canopy sensors and drone survey of the C3 zone (22-32),
    then apply targeted fertilizer using the tractor spreader.
    """

    scenario_id: str = "scenario_farm_world_fertilizer"
    scenario_input: str = SCENARIO_INPUT_DETAIL if DETAILED_BRIEFING else SCENARIO_INPUT
    start_time: float | None = (
        local_timestamp(2026, 6, 2, 8, 0, 0)
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
            description="Zhiyuan D1 Max #1 — ground-level inspection robot",
        )
        robot_1 = RobotApp(
            farm_world_app=farm_world,
            weather_app=weather,
            name="Robot1",
            description="Zhiyuan D1 Max #2 — ground-level inspection robot",
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
            date="2026-06-02",
            temp_c=24.0,
            humidity_pct=45.0,
            wind_speed_ms=1.5,
            rainfall_mm=0.0,
            solar_radiation=520.0,
            forecast=[
                {"date": "2026-06-03", "temp_c": 25.0, "humidity_pct": 42.0,
                 "wind_speed_ms": 2.0, "rainfall_mm": 0.0, "solar_radiation": 530.0},
                {"date": "2026-06-04", "temp_c": 23.0, "humidity_pct": 55.0,
                 "wind_speed_ms": 2.5, "rainfall_mm": 0.0, "solar_radiation": 480.0},
                {"date": "2026-06-05", "temp_c": 22.0, "humidity_pct": 70.0,
                 "wind_speed_ms": 3.0, "rainfall_mm": 5.0, "solar_radiation": 300.0},
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
            r.days_since_planted = 35
            r.growth_stage = "V3"
            r.soil_vwc = 0.23 + (i % 4) * 0.01
            r.soil_temp_c = 20.0 + (i % 3) * 0.3
            r.pest_pressure_base = 0.02
            r.pest_pressure = 0.02
            r.disease_pressure_base = 0.02
            r.disease_pressure = 0.02

            if _DEFICIENT_START <= i <= _DEFICIENT_END:
                r.ndvi = 0.45 + (i % 3) * 0.05
                r.yield_potential = 0.75 + (i % 3) * 0.02
                r.canopy_temp_c = 28.0 + (i % 2) * 0.5
            else:
                r.ndvi = 0.65 + (i % 4) * 0.03
                r.yield_potential = 0.95
                r.canopy_temp_c = 25.0 + (i % 3) * 0.3

        tractor._completed_prep_ops = ["level", "base_fertilize", "form_ridges"]
        tractor._fuel_tank_l = 80.0
        tractor._fertilizer_spreader_kg = 0.0
        mavic._battery_pct = 85.0

    def oracle_solution(self, run_oracle=False):
        weather = self.get_typed_app(WeatherApp)
        sensor = self.get_typed_app(SensorApp)
        farm_world = self.get_typed_app(FarmWorldApp)
        mavic = self.get_typed_app(DroneApp, app_name="Mavic3M")
        tractor = self.get_typed_app(TractorApp)

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
            print(mavic.fly_survey(_SURVEY_START, _SURVEY_END))
        self.workflow.add_node(WorkflowStep(
            name="survey_deficient", op_type="READ",
            tool_name="Mavic3M__fly_survey",
            tool_args={"start_ridge": _SURVEY_START, "end_ridge": _SURVEY_END},
            depends_on=["check_drone"],
        ))

        if run_oracle:
            print(tractor.get_status())
        self.workflow.add_node(WorkflowStep(
            name="check_tractor", op_type="READ",
            tool_name="TractorApp__get_status", tool_args={},
            depends_on=["survey_deficient"],
        ))

        if run_oracle:
            print(farm_world.get_inventory())
        self.workflow.add_node(WorkflowStep(
            name="check_inventory", op_type="READ",
            tool_name="FarmWorldApp__get_inventory", tool_args={},
            depends_on=["check_tractor"],
        ))

        if run_oracle:
            print(tractor.load_fertilizer(kg=_FERTILIZER_LOAD_KG))
        self.workflow.add_node(WorkflowStep(
            name="load_fertilizer", op_type="WRITE",
            tool_name="TractorApp__load_fertilizer",
            tool_args={"kg": _FERTILIZER_LOAD_KG},
            depends_on=["check_inventory"],
        ))

        if run_oracle:
            print(tractor.apply_fertilizer(
                _DEFICIENT_START, _DEFICIENT_END, _FERTILIZER_KG_PER_RIDGE,
            ))
        self.workflow.add_node(WorkflowStep(
            name="apply_fertilizer", op_type="WRITE",
            tool_name="TractorApp__apply_fertilizer",
            tool_args={
                "start_ridge": _DEFICIENT_START,
                "end_ridge": _DEFICIENT_END,
                "kg_per_ridge": _FERTILIZER_KG_PER_RIDGE,
            },
            depends_on=["load_fertilizer"],
        ))
