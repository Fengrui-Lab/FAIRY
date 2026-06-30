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
_SURVEY_START = 18
_SURVEY_END = 32
_FERTILIZER_KG_PER_RIDGE = 10.0
_FERTILIZER_LOAD_KG = 100.0
_DRY_START = 40
_DRY_END = 50
_IRRIGATION_HOURS = 1.5
_ROBOT_INSPECT_RIDGE = 25

SCENARIO_INPUT_DETAIL = """
作物已进入V3生长阶段（播种后约35天），今天需要完成例行巡查，并处理发现的问题。
请按以下步骤操作：

【固定传感器监测阶段】
1. 查看今天天气，确认无雨且风速<12m/s（无人机飞行条件）。
2. 读取冠层传感器（6个固定传感器持续监测），发现C3和C5区域NDVI偏低。
3. 读取土壤传感器（6个固定传感器），发现S5区域VWC偏低（<0.20）。

【无人机航空巡查阶段】
4. 检查Mavic3M无人机电量（当前约65%，不满）。
5. 飞行巡查全部64垄，定位异常区域范围。飞到电量不足时会自动返航，返回部分结果。
6. 返航后，检查无人机状态，给无人机充电（约30分钟）。
7. 充电完成后继续飞剩余未覆盖的区域。
8. 分析巡查结果，确认两个问题：
   - ridges 22-27区域NDVI偏低（0.40-0.48），怀疑营养缺乏
   - ridges 40-50区域NDVI也偏低但不严重，可能是缺水

【地面确认阶段】
9. 检查Robot0状态，派机器狗到ridge 25做地面巡检，确认是营养问题不是虫害。

【追肥阶段】
10. 检查拖拉机状态（油量、施肥机）和仓库肥料库存。
11. 装载肥料100kg，对ridges 22-27追施肥料（每垄约10kg）。

【灌溉阶段】
12. 查看未来3天预报，如果近期无雨就需要灌溉。
13. 对ridges 40-50灌溉1.5小时。灌溉会使土壤VWC增加约0.08。
14. 灌溉后等待系统在约2小时后发送通知，再次读取传感器，确认土壤湿度已恢复到正常范围。
15. 全部完成后立即结束任务向我汇报。
"""

SCENARIO_INPUT = """作物进入V3阶段了，先看看传感器数据，再飞无人机巡查，发现问题就处理。完成后告诉我。"""


class ScenarioFarmWorldSurveyFertilizerIrrigation(Scenario):
    """
    Combined drone survey + fertilizer + irrigation scenario.

    A realistic multi-problem day: fixed sensors detect anomalies, drone survey
    confirms extent, robot ground-truths the cause, then targeted interventions.

    Sensing hierarchy (PDF-compliant):
      1. Fixed sensors (continuous monitoring) detect anomalies
      2. Drone aerial survey (spatial mapping) confirms extent
      3. Robot ground inspection (high-res verification) determines root cause

    Problems identified:
      - Ridges 22-27 show low NDVI (nutrient deficiency)
      - Ridges 40-50 show low soil VWC (drought stress)

    Timeline:
      Phase 1: fixed sensor monitoring (canopy + soil)
      Phase 2: drone aerial survey (partial → charge → continue)
      Phase 3: robot ground-truth
      Phase 4: targeted fertilization
      Phase 5: irrigation + wait + verify
    """

    scenario_id: str = "scenario_farm_world_survey_fertilizer_irrigation"
    scenario_input: str = SCENARIO_INPUT_DETAIL if DETAILED_BRIEFING else SCENARIO_INPUT
    start_time: float | None = (
        local_timestamp(2026, 6, 3, 8, 0, 0)
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
            date="2026-06-03",
            temp_c=25.0,
            humidity_pct=40.0,
            wind_speed_ms=2.0,
            rainfall_mm=0.0,
            solar_radiation=520.0,
            forecast=[
                {"date": "2026-06-04", "temp_c": 26.0, "humidity_pct": 38.0,
                 "wind_speed_ms": 2.5, "rainfall_mm": 0.0, "solar_radiation": 530.0},
                {"date": "2026-06-05", "temp_c": 27.0, "humidity_pct": 35.0,
                 "wind_speed_ms": 1.5, "rainfall_mm": 0.0, "solar_radiation": 540.0},
                {"date": "2026-06-06", "temp_c": 24.0, "humidity_pct": 50.0,
                 "wind_speed_ms": 3.0, "rainfall_mm": 0.0, "solar_radiation": 500.0},
            ],
            avg_soil_vwc=0.21,
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
            r.soil_temp_c = 20.0 + (i % 3) * 0.3
            r.pest_pressure_base = 0.02
            r.pest_pressure = 0.02
            r.disease_pressure_base = 0.02
            r.disease_pressure = 0.02

            # Nutrient deficiency zone (ridges 22-27)
            if _DEFICIENT_START <= i <= _DEFICIENT_END:
                r.ndvi = 0.40 + (i % 3) * 0.03
                r.yield_potential = 0.75 + (i % 3) * 0.02
                r.canopy_temp_c = 28.0 + (i % 2) * 0.5
                r.soil_vwc = 0.22 + (i % 3) * 0.01
            # Drought zone (ridges 40-50)
            elif _DRY_START <= i <= _DRY_END:
                r.ndvi = 0.55 + (i % 3) * 0.02
                r.yield_potential = 0.90
                r.canopy_temp_c = 26.0 + (i % 2) * 0.5
                r.soil_vwc = 0.14 + (i % 3) * 0.01  # Dry
            # Normal zones
            else:
                r.ndvi = 0.65 + (i % 4) * 0.03
                r.yield_potential = 0.95
                r.canopy_temp_c = 25.0 + (i % 3) * 0.3
                r.soil_vwc = 0.22 + (i % 4) * 0.01

        tractor._completed_prep_ops = ["level", "base_fertilize", "form_ridges"]
        tractor._fuel_tank_l = 80.0
        tractor._fertilizer_spreader_kg = 0.0
        mavic._battery_pct = 65.0

    def oracle_solution(self, run_oracle=False):
        weather = self.get_typed_app(WeatherApp)
        sensor = self.get_typed_app(SensorApp)
        farm_world = self.get_typed_app(FarmWorldApp)
        mavic = self.get_typed_app(DroneApp, app_name="Mavic3M")
        robot_0 = self.get_typed_app(RobotApp, app_name="Robot0")
        tractor = self.get_typed_app(TractorApp)
        field_ops = self.get_typed_app(FieldOpsApp)
        system = self.get_typed_app(SystemApp)

        # ===== PHASE 1: FIXED SENSOR MONITORING =====

        if run_oracle:
            print(weather.get_current_weather())
        self.workflow.add_node(WorkflowStep(
            name="check_weather", op_type="READ",
            tool_name="WeatherApp__get_current_weather", tool_args={}, depends_on=[],
        ))

        # Read fixed canopy sensors first (continuous monitoring)
        if run_oracle:
            print(sensor.read_canopy_sensors())
        self.workflow.add_node(WorkflowStep(
            name="read_canopy", op_type="READ",
            tool_name="SensorApp__read_canopy_sensors", tool_args={},
            depends_on=["check_weather"],
        ))

        # Read fixed soil sensors (continuous monitoring)
        if run_oracle:
            print(sensor.read_soil_sensors())
        self.workflow.add_node(WorkflowStep(
            name="read_soil", op_type="READ",
            tool_name="SensorApp__read_soil_sensors", tool_args={},
            depends_on=["read_canopy"],
        ))

        # ===== PHASE 2: DRONE AERIAL SURVEY =====

        if run_oracle:
            print(mavic.check_status())
        self.workflow.add_node(WorkflowStep(
            name="check_drone", op_type="READ",
            tool_name="Mavic3M__check_status", tool_args={},
            depends_on=["read_soil"],
        ))

        # First survey attempt (will return partial due to low battery ~65%)
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

        # Continue survey: remaining ridges (approximately 42-63)
        if run_oracle:
            print(mavic.fly_survey(42, 63))
        self.workflow.add_node(WorkflowStep(
            name="survey_remaining", op_type="READ",
            tool_name="Mavic3M__fly_survey",
            tool_args={"start_ridge": 42, "end_ridge": 63},
            depends_on=["wait_for_charge_complete"],
        ))

        # ===== PHASE 3: GROUND-TRUTH WITH ROBOT =====

        if run_oracle:
            print(robot_0.check_status())
        self.workflow.add_node(WorkflowStep(
            name="check_robot", op_type="READ",
            tool_name="Robot0__check_status", tool_args={},
            depends_on=["survey_remaining"],
        ))

        if run_oracle:
            print(robot_0.inspect_ridge(_ROBOT_INSPECT_RIDGE))
        self.workflow.add_node(WorkflowStep(
            name="robot_inspect", op_type="READ",
            tool_name="Robot0__inspect_ridge",
            tool_args={"ridge_id": _ROBOT_INSPECT_RIDGE},
            depends_on=["check_robot"],
        ))

        # ===== PHASE 4: TARGETED FERTILIZATION =====

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

        # ===== PHASE 5: IRRIGATION =====

        if run_oracle:
            print(weather.get_forecast(days=3))
        self.workflow.add_node(WorkflowStep(
            name="check_forecast", op_type="READ",
            tool_name="WeatherApp__get_forecast", tool_args={"days": 3},
            depends_on=["apply_fertilizer"],
        ))

        if run_oracle:
            print(field_ops.irrigate_range(_DRY_START, _DRY_END, _IRRIGATION_HOURS))
        self.workflow.add_node(WorkflowStep(
            name="irrigate", op_type="WRITE",
            tool_name="FieldOpsApp__irrigate_range",
            tool_args={"start": _DRY_START, "end": _DRY_END,
                        "duration_hours": _IRRIGATION_HOURS},
            depends_on=["check_forecast"],
        ))

        if run_oracle:
            system.wait_for_notification(timeout=2 * 60 * 60)
        self.workflow.add_node(WorkflowStep(
            name="wait_for_irrigation_effect", op_type="READ",
            tool_name="SystemApp__wait_for_notification",
            tool_args={"timeout": 2 * 60 * 60},
            depends_on=["irrigate"],
        ))

        if run_oracle:
            print(sensor.read_soil_sensors())
        self.workflow.add_node(WorkflowStep(
            name="verify_soil", op_type="READ",
            tool_name="SensorApp__read_soil_sensors", tool_args={},
            depends_on=["wait_for_irrigation_effect"],
        ))
