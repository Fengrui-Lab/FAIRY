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

_PEST_START = 20
_PEST_END = 35
_ROBOT_INSPECT_RIDGE = 27
_REFUEL_L = 80.0
_PESTICIDE_LOAD_L = 200.0
_DRY_START = 50
_DRY_END = 58
_IRRIGATION_HOURS = 1.5

SCENARIO_INPUT_DETAIL = """
作物已进入V4生长阶段（播种后约42天），传感器报警NDVI异常，同时最近持续干旱。
今天需要完成诊断、喷药和灌溉。后天有雨，喷药必须今天完成（雨会冲掉药效）。
请按以下步骤操作：

【固定传感器监测阶段】
1. 查看当前天气，确认风速<5m/s、无雨（喷药条件）。
2. 查看3天预报（后天有雨→今天必须喷药）。
3. 读取冠层传感器（6个固定传感器），发现C3/C4区域NDVIen e偏低，怀疑虫害。
4. 读取土壤传感器（6个固定传感器），确认VWC<0.35（拖拉机可下地），同时发现S5/S6区域ridges 50-58干旱。

【无人机航空巡查阶段】
5. 检查Mavic3M状态（电量约90%），飞行巡查异常区域ridges 15-40，定位虫害范围。

【地面确认阶段】
6. 检查Robot0状态，派机器狗到ridge 27做地面复核确认蚜虫。

【喷药阶段】
7. 检查拖拉机状态（油量15L不够）和仓库库存。
8. 挂接喷药器，加油80L，装药200L。
9. 用拖拉机喷杆分2趟喷药（20-29, 30-35），覆盖全部虫害区域。
10. 卸载喷药器。

【灌溉阶段】
11. 对ridges 50-58灌溉1.5小时。
12. 灌溉后等待系统在约2小时后发送通知，再次读取传感器确认土壤湿度恢复。
13. 全部完成后立即结束任务向我汇报。
"""

SCENARIO_INPUT = """传感器报警了，先看看传感器数据，再派无人机和机器狗确认。虫害要喷药，缺水要灌溉，今天都处理完。完成后告诉我。"""


class ScenarioFarmWorldSurveyPesticideIrrigation(Scenario):
    """
    Combined drone survey + pesticide + irrigation scenario.

    A realistic emergency day: fixed sensors detect anomalies, drone confirms
    extent, robot ground-truths the cause, then targeted interventions.

    Sensing hierarchy (PDF-compliant):
      1. Fixed sensors (continuous monitoring) detect anomalies
      2. Drone aerial survey (spatial mapping) confirms extent
      3. Robot ground inspection (high-res verification) determines root cause

    Problems identified:
      - Ridges 20-35 have pest outbreak (aphids confirmed by robot)
      - Ridges 50-58 are drought-stressed (low VWC)

    Rain forecast on day 3 creates urgency: pesticide must be applied today
    (rain washes it off).

    Timeline:
      Phase 1: fixed sensor monitoring (canopy + soil)
      Phase 2: drone aerial survey
      Phase 3: robot ground-truth
      Phase 4: tractor pesticide spraying (refuel + load + 2 passes)
      Phase 5: irrigation + wait + verify
    """

    scenario_id: str = "scenario_farm_world_survey_pesticide_irrigation"
    scenario_input: str = SCENARIO_INPUT_DETAIL if DETAILED_BRIEFING else SCENARIO_INPUT
    start_time: float | None = (
        local_timestamp(2026, 6, 10, 8, 0, 0)
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
            date="2026-06-10",
            temp_c=24.0,
            humidity_pct=50.0,
            wind_speed_ms=2.0,
            rainfall_mm=0.0,
            solar_radiation=500.0,
            forecast=[
                {"date": "2026-06-11", "temp_c": 25.0, "humidity_pct": 48.0,
                 "wind_speed_ms": 2.0, "rainfall_mm": 0.0, "solar_radiation": 510.0},
                {"date": "2026-06-12", "temp_c": 20.0, "humidity_pct": 75.0,
                 "wind_speed_ms": 5.5, "rainfall_mm": 10.0, "solar_radiation": 200.0},
                {"date": "2026-06-13", "temp_c": 19.0, "humidity_pct": 80.0,
                 "wind_speed_ms": 4.0, "rainfall_mm": 5.0, "solar_radiation": 250.0},
            ],
            avg_soil_vwc=0.22,
        )
        farm_world.set_season_phase("growing")

        for i in range(64):
            r = farm_world.get_ridge(i)
            r.planted = True
            r.seed_type = "STANDARD"
            r.seed_spacing_cm = 12.0
            r.seeds_planted = 4467
            r.days_since_planted = 42
            r.growth_stage = "V4"
            r.soil_temp_c = 20.0 + (i % 3) * 0.3
            r.disease_pressure_base = 0.02
            r.disease_pressure = 0.02
            r.yield_potential = 0.95

            # Pest zone (ridges 20-35)
            if _PEST_START <= i <= _PEST_END:
                center = (_PEST_START + _PEST_END) / 2.0
                dist = abs(i - center) / ((_PEST_END - _PEST_START) / 2.0)
                r.pest_pressure_base = round(0.45 - 0.20 * dist, 2)
                r.pest_pressure = r.pest_pressure_base
                r.ndvi = round(0.65 - r.pest_pressure_base * 0.35, 3)
                r.canopy_temp_c = round(24.0 + r.pest_pressure_base * 4.0, 2)
                r.soil_vwc = 0.22 + (i % 4) * 0.01
            # Drought zone (ridges 50-58)
            elif _DRY_START <= i <= _DRY_END:
                r.pest_pressure_base = 0.02
                r.pest_pressure = 0.02
                r.ndvi = 0.58 + (i % 3) * 0.02
                r.canopy_temp_c = 26.0 + (i % 2) * 0.5
                r.soil_vwc = 0.14 + (i % 3) * 0.01
            # Normal zones
            else:
                r.pest_pressure_base = 0.02
                r.pest_pressure = 0.02
                r.ndvi = 0.65 + (i % 4) * 0.03
                r.canopy_temp_c = 24.0 + (i % 3) * 0.3
                r.soil_vwc = 0.22 + (i % 4) * 0.01

        tractor._completed_prep_ops = ["level", "base_fertilize", "form_ridges"]
        tractor._fuel_tank_l = 15.0
        tractor._pesticide_tank_l = 0.0
        mavic._battery_pct = 90.0

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

        if run_oracle:
            print(weather.get_forecast(days=3))
        self.workflow.add_node(WorkflowStep(
            name="check_forecast", op_type="READ",
            tool_name="WeatherApp__get_forecast", tool_args={"days": 3},
            depends_on=["check_weather"],
        ))

        # Read fixed canopy sensors first (continuous monitoring)
        if run_oracle:
            print(sensor.read_canopy_sensors())
        self.workflow.add_node(WorkflowStep(
            name="read_canopy", op_type="READ",
            tool_name="SensorApp__read_canopy_sensors", tool_args={},
            depends_on=["check_forecast"],
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

        if run_oracle:
            print(mavic.fly_survey(15, 40))
        self.workflow.add_node(WorkflowStep(
            name="survey_pest_zone", op_type="READ",
            tool_name="Mavic3M__fly_survey",
            tool_args={"start_ridge": 15, "end_ridge": 40},
            depends_on=["check_drone"],
        ))

        # ===== PHASE 3: GROUND-TRUTH WITH ROBOT =====

        if run_oracle:
            print(robot_0.check_status())
        self.workflow.add_node(WorkflowStep(
            name="check_robot", op_type="READ",
            tool_name="Robot0__check_status", tool_args={},
            depends_on=["survey_pest_zone"],
        ))

        if run_oracle:
            print(robot_0.inspect_ridge(_ROBOT_INSPECT_RIDGE))
        self.workflow.add_node(WorkflowStep(
            name="robot_inspect", op_type="READ",
            tool_name="Robot0__inspect_ridge",
            tool_args={"ridge_id": _ROBOT_INSPECT_RIDGE},
            depends_on=["check_robot"],
        ))

        # ===== PHASE 4: PESTICIDE SPRAYING =====

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
            tool_name="TractorApp__attach_implement",
            tool_args={"implement": "sprayer"},
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

        # Spray pass 1: ridges 20-29 (10 ridges)
        if run_oracle:
            print(tractor.apply_pesticide(20, 29))
        self.workflow.add_node(WorkflowStep(
            name="spray_pass_1", op_type="WRITE",
            tool_name="TractorApp__apply_pesticide",
            tool_args={"start_ridge": 20, "end_ridge": 29},
            depends_on=["load_pesticide"],
        ))

        # Spray pass 2: ridges 30-35 (6 ridges)
        if run_oracle:
            print(tractor.apply_pesticide(30, 35))
        self.workflow.add_node(WorkflowStep(
            name="spray_pass_2", op_type="WRITE",
            tool_name="TractorApp__apply_pesticide",
            tool_args={"start_ridge": 30, "end_ridge": 35},
            depends_on=["spray_pass_1"],
        ))

        if run_oracle:
            print(tractor.detach_implement())
        self.workflow.add_node(WorkflowStep(
            name="detach_sprayer", op_type="WRITE",
            tool_name="TractorApp__detach_implement", tool_args={},
            depends_on=["spray_pass_2"],
        ))

        # ===== PHASE 5: IRRIGATION =====

        if run_oracle:
            print(field_ops.irrigate_range(_DRY_START, _DRY_END, _IRRIGATION_HOURS))
        self.workflow.add_node(WorkflowStep(
            name="irrigate", op_type="WRITE",
            tool_name="FieldOpsApp__irrigate_range",
            tool_args={"start": _DRY_START, "end": _DRY_END,
                        "duration_hours": _IRRIGATION_HOURS},
            depends_on=["detach_sprayer"],
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
