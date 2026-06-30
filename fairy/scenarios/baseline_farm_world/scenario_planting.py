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

_SEEDS_PER_LOAD = 300000
_SEED_TYPE = "STANDARD"
_DEPTH_CM = 4.0
_SPACING_CM = 5.0

SCENARIO_INPUT_DETAIL = """
整地已完成（平整、施基肥、起垄），今天开始播种大豆。
请按以下步骤操作：
1. 查看今天天气，确认无雨；
2. 读取土壤传感器，确认VWC在0.20-0.30之间、土壤温度>10°C（适合播种）。
3. 检查拖拉机油量（当前80L，不满）和料斗状态。
4. 查看仓库种子库存。
5. 装载第一批种子（料斗最大30万株）。
6. 逐批播种，每次4条垄（如0-3, 4-7, ...）。播深4cm，株距5cm。。
7. 种子不够了，再装下一批。
8. 全部64垄播完后立即结束任务向我汇报。
"""

SCENARIO_INPUT = """整地已完成，今天开始播种。务必今天种完全部64垄。完成后告诉我。"""


class ScenarioFarmWorldPlanting(Scenario):
    """
    Planting 64 ridges of soybean after field prep is complete.

    A realistic planting shift: the agent must check conditions, load seeds,
    plant in 4-ridge batches, reload seeds when the hopper runs low, monitor
    fuel, and handle the full 64-ridge field.
    """

    scenario_id: str = "scenario_farm_world_planting"
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

        # --- Configure initial state ---
        tractor._completed_prep_ops = ["level", "base_fertilize", "form_ridges"]

        weather.set_weather(
            date="2026-04-28",
            temp_c=18.0,
            humidity_pct=50.0,
            wind_speed_ms=2.5,
            rainfall_mm=0.0,
            solar_radiation=480.0,
            forecast=[
                {"date": "2026-04-29", "temp_c": 19.0, "humidity_pct": 45.0,
                 "wind_speed_ms": 2.0, "rainfall_mm": 0.0, "solar_radiation": 500.0},
                {"date": "2026-04-30", "temp_c": 16.0, "humidity_pct": 65.0,
                 "wind_speed_ms": 4.0, "rainfall_mm": 5.0, "solar_radiation": 250.0},
                {"date": "2026-05-01", "temp_c": 14.0, "humidity_pct": 70.0,
                 "wind_speed_ms": 6.0, "rainfall_mm": 12.0, "solar_radiation": 180.0},
            ],
            avg_soil_vwc=0.24,
        )
        farm_world.set_season_phase("planting")

        for i in range(64):
            r = farm_world.get_ridge(i)
            r.soil_vwc = 0.22 + (i % 5) * 0.01
            r.soil_temp_c = 12.0 + (i % 4) * 0.5

        tractor._fuel_tank_l = 80.0

    def oracle_solution(self, run_oracle=False):
        weather = self.get_typed_app(WeatherApp)
        sensor = self.get_typed_app(SensorApp)
        tractor = self.get_typed_app(TractorApp)
        farm_world = self.get_typed_app(FarmWorldApp)

        # Pre-planting checks
        if run_oracle:
            print(weather.get_current_weather())
        self.workflow.add_node(WorkflowStep(
            name="check_weather", op_type="READ",
            tool_name="WeatherApp__get_current_weather", tool_args={}, depends_on=[],
        ))

        if run_oracle:
            print(sensor.read_soil_sensors())
        self.workflow.add_node(WorkflowStep(
            name="read_soil", op_type="READ",
            tool_name="SensorApp__read_soil_sensors", tool_args={},
            depends_on=["check_weather"],
        ))

        if run_oracle:
            print(tractor.get_status())
        self.workflow.add_node(WorkflowStep(
            name="check_tractor", op_type="READ",
            tool_name="TractorApp__get_status", tool_args={},
            depends_on=["read_soil"],
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

        # Batch 1: plant ridges 0-31 (8 passes of 4 ridges)
        prev = "load_seeds_1"
        for i in range(7):
            start = i * 4
            end = start + 3
            name = f"plant_b1_{start}_{end}"
            if run_oracle:
                print(tractor.plant_seeds(start, end, _DEPTH_CM, _SPACING_CM))
            self.workflow.add_node(WorkflowStep(
                name=name, op_type="WRITE",
                tool_name="TractorApp__plant_seeds",
                tool_args={"start_ridge": start, "end_ridge": end,
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

        # Batch 2: plant ridges 28-55 (7 passes)
        prev = "load_seeds_2"
        for i in range(7):
            start = 24 + i * 4
            end = start + 3
            name = f"plant_b2_{start}_{end}"
            if run_oracle:
                print(tractor.plant_seeds(start, end, _DEPTH_CM, _SPACING_CM))
            self.workflow.add_node(WorkflowStep(
                name=name, op_type="WRITE",
                tool_name="TractorApp__plant_seeds",
                tool_args={"start_ridge": start, "end_ridge": end,
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

        # Batch 3: plant ridges 56-63 (2 passes)
        prev = "load_seeds_3"
        for i in range(4):
            start = 48 + i * 4
            end = start + 3
            name = f"plant_b3_{start}_{end}"
            if run_oracle:
                print(tractor.plant_seeds(start, end, _DEPTH_CM, _SPACING_CM))
            self.workflow.add_node(WorkflowStep(
                name=name, op_type="WRITE",
                tool_name="TractorApp__plant_seeds",
                tool_args={"start_ridge": start, "end_ridge": end,
                            "depth_cm": _DEPTH_CM, "seed_spacing_cm": _SPACING_CM},
                depends_on=[prev],
            ))
            prev = name
