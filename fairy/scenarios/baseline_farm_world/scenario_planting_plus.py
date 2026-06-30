from __future__ import annotations

from fairy.apps.farm_world.drone_app import DroneApp
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.field_ops_app import FieldOpsApp
from fairy.apps.farm_world.robot_app import RobotApp
from fairy.apps.farm_world.sensor_app import SensorApp
from fairy.apps.farm_world.tractor_app import TractorApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.system import SystemApp
from fairy.controllers.event import Event
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.workflow import WorkflowStep
from fairy.scenarios.baseline_farm_world.Contants import DETAILED_BRIEFING, local_timestamp

_SEEDS_PER_LOAD = 300000
_SEED_TYPE = "STANDARD"
_DEPTH_CM = 4.0
_SPACING_CM = 5.0

_VWC_AFTER_RAIN = 0.38
_VWC_AFTER_DRY = 0.26

# Time offsets from scenario start (seconds)
_RAIN_STOP_OFFSET = 5 * 60 * 60 + 50 * 60  # rain stops at 12:50 local time

SCENARIO_INPUT_DETAIL = """
整地已完成（平整、施基肥、起垄），今天开始播种大豆。
请按以下步骤操作：
1. 查看今天天气，确认是否适合播种；
2. 如果当前天气不适合（比如下雨 影响拖拉机作业），查看未来3天天气预报，评估天气趋势；
3. 等待天气好转后继续。
4. 读取土壤传感器，确认VWC在0.20-0.30之间、土壤温度>10°C（适合播种）。
5. 条件合适后，检查拖拉机油量和料斗状态。
6. 查看仓库种子库存。
7. 装载第一批种子（料斗最大30万株）。
8. 逐批播种，每次4条垄（如0-3, 4-7, ...）。播深4cm，株距5cm。
9. 种子不够了，再装下一批。
10. 全部64垄播完后立即结束任务向我汇报。
"""

SCENARIO_INPUT = """整地已完成，今天开始播种。务必在条件合适时种完全部64垄。完成后告诉我。"""


class RainStopEvent(Event):

    def __init__(
        self,
        time_start: float,
        time_duration: float,
        weather_app: WeatherApp,
        farm_world_app: FarmWorldApp,
    ):
        super().__init__(time_start=time_start, time_duration=time_duration)
        self.weather_app = weather_app
        self.farm_world_app = farm_world_app

    def step(self):
        self.weather_app.set_weather(
            date="2026-04-28",
            temp_c=17.0,
            humidity_pct=68.0,
            wind_speed_ms=2.8,
            rainfall_mm=0.0,
            solar_radiation=360.0,
            forecast=[
                {"date": "2026-04-29", "temp_c": 15.0, "humidity_pct": 80.0,
                 "wind_speed_ms": 3.5, "rainfall_mm": 0.0, "solar_radiation": 380.0},
                {"date": "2026-04-30", "temp_c": 18.0, "humidity_pct": 60.0,
                 "wind_speed_ms": 2.5, "rainfall_mm": 12.0, "solar_radiation": 480.0},
                {"date": "2026-05-01", "temp_c": 20.0, "humidity_pct": 50.0,
                 "wind_speed_ms": 2.0, "rainfall_mm": 0.0, "solar_radiation": 520.0},
            ],
            avg_soil_vwc=_VWC_AFTER_DRY,
        )
        for i in range(64):
            r = self.farm_world_app.get_ridge(i)
            r.soil_vwc = 0.24 + (i % 5) * 0.01
        return "Rain has stopped; weather is suitable to re-check planting conditions."


class ScenarioFarmWorldPlantingPlus(Scenario):
    """
    Planting scenario with a dynamic rain-stop event.

    Timeline:
      T+0      — raining, current weather is unsuitable for planting
      T+5h50m  — RainStopEvent: rain stops at 12:50, near the forecasted 13:00

    Oracle flow: check weather → discover rain → check forecast (rain stops
    around 13:00) → wait for rain-stop event → re-check weather & soil →
    proceed with planting.
    """

    scenario_id: str = "scenario_farm_world_planting_plus"
    scenario_input: str = SCENARIO_INPUT_DETAIL if DETAILED_BRIEFING else SCENARIO_INPUT
    start_time: float | None = (
        local_timestamp(2026, 4, 28, 7, 0, 0)
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

        tractor._completed_prep_ops = ["level", "base_fertilize", "form_ridges"]

        weather.set_weather(
            date="2026-04-28",
            temp_c=14.0,
            humidity_pct=88.0,
            wind_speed_ms=4.0,
            rainfall_mm=12.0,
            solar_radiation=120.0,
            forecast=[
                {"date": "2026-04-28", "temp_c": 17.0, "humidity_pct": 68.0,
                 "wind_speed_ms": 2.8, "rainfall_mm": 12.0, "solar_radiation": 360.0,
                 "msg": "the rain will stop at about 13:00"},
                {"date": "2026-04-29", "temp_c": 19.0, "humidity_pct": 45.0,
                 "wind_speed_ms": 2.0, "rainfall_mm": 12.0, "solar_radiation": 500.0},
                {"date": "2026-04-30", "temp_c": 16.0, "humidity_pct": 65.0,
                 "wind_speed_ms": 4.0, "rainfall_mm": 5.0, "solar_radiation": 250.0},
            ],
            avg_soil_vwc=_VWC_AFTER_RAIN,
        )
        farm_world.set_season_phase("planting")

        for i in range(64):
            r = farm_world.get_ridge(i)
            r.soil_vwc = 0.36 + (i % 5) * 0.01
            r.soil_temp_c = 12.0 + (i % 4) * 0.5

        tractor._fuel_tank_l = 80.0

        # --- Dynamic events ---
        rain_stop_event = RainStopEvent(
            time_start=self.start_time + _RAIN_STOP_OFFSET,
            time_duration=0,
            weather_app=weather,
            farm_world_app=farm_world,
        )
        self.dynamic_events = [rain_stop_event]

    def oracle_solution(self, run_oracle=False):
        weather = self.get_typed_app(WeatherApp)
        sensor = self.get_typed_app(SensorApp)
        tractor = self.get_typed_app(TractorApp)
        farm_world = self.get_typed_app(FarmWorldApp)
        system = self.get_typed_app(SystemApp)

        # ---- Phase 1: discover rain ----

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


        # Wait for the forecasted rain stop around 13:00.
        if run_oracle:
            system.wait_for_notification(timeout=6 * 60 * 60)
        self.workflow.add_node(WorkflowStep(
            name="wait_for_rain_stop", op_type="READ",
            tool_name="SystemApp__wait_for_notification",
            tool_args={"timeout": 6 * 60 * 60},
            depends_on=["check_forecast"],
        ))

        # ---- Phase 2: verify conditions after rain stops ----

        if run_oracle:
            print(weather.get_current_weather())
        self.workflow.add_node(WorkflowStep(
            name="check_weather_after", op_type="READ",
            tool_name="WeatherApp__get_current_weather", tool_args={},
            depends_on=["wait_for_rain_stop"],
        ))

        if run_oracle:
            print(sensor.read_soil_sensors())
        self.workflow.add_node(WorkflowStep(
            name="read_soil_after", op_type="READ",
            tool_name="SensorApp__read_soil_sensors", tool_args={},
            depends_on=["check_weather_after"],
        ))

        # ---- Phase 3: normal planting workflow ----

        if run_oracle:
            print(tractor.get_status())
        self.workflow.add_node(WorkflowStep(
            name="check_tractor", op_type="READ",
            tool_name="TractorApp__get_status", tool_args={},
            depends_on=["read_soil_after"],
        ))

        if run_oracle:
            print(farm_world.get_inventory())
        self.workflow.add_node(WorkflowStep(
            name="check_inventory", op_type="READ",
            tool_name="FarmWorldApp__get_inventory", tool_args={},
            depends_on=["check_tractor"],
        ))

        # Load seeds batch 1
        if run_oracle:
            print(tractor.load_seeds(_SEED_TYPE, _SEEDS_PER_LOAD))
        self.workflow.add_node(WorkflowStep(
            name="load_seeds_1", op_type="WRITE",
            tool_name="TractorApp__load_seeds",
            tool_args={"seed_type": _SEED_TYPE, "count": _SEEDS_PER_LOAD},
            depends_on=["check_inventory"],
        ))

        # Batch 1: ridges 0-27 (7 passes × 4 ridges, last pass may fail on seeds)
        prev = "load_seeds_1"
        for i in range(7):
            s, e = i * 4, i * 4 + 3
            name = f"plant_b1_{s}_{e}"
            if run_oracle:
                print(tractor.plant_seeds(s, e, _DEPTH_CM, _SPACING_CM))
            self.workflow.add_node(WorkflowStep(
                name=name, op_type="WRITE",
                tool_name="TractorApp__plant_seeds",
                tool_args={"start_ridge": s, "end_ridge": e,
                           "depth_cm": _DEPTH_CM, "seed_spacing_cm": _SPACING_CM},
                depends_on=[prev],
            ))
            prev = name

        # Load seeds batch 2
        if run_oracle:
            print(tractor.load_seeds(_SEED_TYPE, _SEEDS_PER_LOAD))
        self.workflow.add_node(WorkflowStep(
            name="load_seeds_2", op_type="WRITE",
            tool_name="TractorApp__load_seeds",
            tool_args={"seed_type": _SEED_TYPE, "count": _SEEDS_PER_LOAD},
            depends_on=[prev],
        ))

        # Batch 2: ridges 24-51 (7 passes, overlaps to cover failed ridge 24-27)
        prev = "load_seeds_2"
        for i in range(7):
            s, e = 24 + i * 4, 24 + i * 4 + 3
            name = f"plant_b2_{s}_{e}"
            if run_oracle:
                print(tractor.plant_seeds(s, e, _DEPTH_CM, _SPACING_CM))
            self.workflow.add_node(WorkflowStep(
                name=name, op_type="WRITE",
                tool_name="TractorApp__plant_seeds",
                tool_args={"start_ridge": s, "end_ridge": e,
                           "depth_cm": _DEPTH_CM, "seed_spacing_cm": _SPACING_CM},
                depends_on=[prev],
            ))
            prev = name

        # Load seeds batch 3
        if run_oracle:
            print(tractor.load_seeds(_SEED_TYPE, _SEEDS_PER_LOAD))
        self.workflow.add_node(WorkflowStep(
            name="load_seeds_3", op_type="WRITE",
            tool_name="TractorApp__load_seeds",
            tool_args={"seed_type": _SEED_TYPE, "count": _SEEDS_PER_LOAD},
            depends_on=[prev],
        ))

        # Batch 3: ridges 48-63 (4 passes)
        prev = "load_seeds_3"
        for i in range(4):
            s, e = 48 + i * 4, 48 + i * 4 + 3
            name = f"plant_b3_{s}_{e}"
            if run_oracle:
                print(tractor.plant_seeds(s, e, _DEPTH_CM, _SPACING_CM))
            self.workflow.add_node(WorkflowStep(
                name=name, op_type="WRITE",
                tool_name="TractorApp__plant_seeds",
                tool_args={"start_ridge": s, "end_ridge": e,
                           "depth_cm": _DEPTH_CM, "seed_spacing_cm": _SPACING_CM},
                depends_on=[prev],
            ))
            prev = name