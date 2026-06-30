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

_BASE_FERTILIZER_LOAD_KG = 200.0
_SEEDS_PER_LOAD = 300000
_SEED_TYPE = "STANDARD"
_DEPTH_CM = 4.0
_SPACING_CM = 5.0
_REFUEL_L = 50.0

SCENARIO_INPUT_DETAIL = """
天气窗口只有今明两天（后天下雨），今天必须把整地和播种全部完成。
请按以下步骤操作：

【整地阶段】
1. 查看今天天气，确认无雨可以下地。
2. 查看3天天气预报。
3. 读取土壤传感器，确认VWC<0.35（拖拉机可通行）且土壤温度>10°C（适合播种）。
4. 检查拖拉机油量（当前60L）和挂接状态。
5. 查看仓库库存，确认化肥、种子和柴油充足。
6. 平整地面：挂接平地机→旋耕平整全田→卸下平地机。
7. 施基肥：装载200kg化肥→全田撒施。
8. 起垄：挂接开沟机→起垄（垄宽1.1m）→卸下开沟机。

【播种阶段】
9. 检查拖拉机油量，建议加50.0油。
10. 装载第一批种子（料斗最大30万株）。
11. 逐批播种，每次4条垄（0-3, 4-7, ...），播深4cm，株距5cm。
12. 种子不够了再装下一批。
13. 全部64垄播完后立即结束任务向我汇报。
"""

SCENARIO_INPUT = """今天必须把整地和播种全部完成。做完告诉我。"""


class ScenarioFarmWorldFieldPrepPlanting(Scenario):
    """
    Combined field prep + planting scenario.

    A realistic full-day operation: weather window closes tomorrow (rain on day 3),
    so the farmer must complete both field preparation and planting today.

    Timeline:
      Phase 1 (field prep): level → base_fertilize → form_ridges
      Phase 2 (planting): refuel → load seeds → plant all 64 ridges in batches

    Key challenge: tractor starts with 60L fuel. Field prep consumes 24L (8L×3),
    leaving 36L. Planting needs 32L (16 passes × 2L), leaving only 4L margin.
    Agent should refuel before planting to be safe.
    """

    scenario_id: str = "scenario_farm_world_field_prep_planting"
    scenario_input: str = SCENARIO_INPUT_DETAIL if DETAILED_BRIEFING else SCENARIO_INPUT
    start_time: float | None = (
        local_timestamp(2026, 4, 26, 8, 0, 0)
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
            date="2026-04-26",
            temp_c=18.0,
            humidity_pct=50.0,
            wind_speed_ms=2.0,
            rainfall_mm=0.0,
            solar_radiation=480.0,
            forecast=[
                {"date": "2026-04-27", "temp_c": 19.0, "humidity_pct": 45.0,
                 "wind_speed_ms": 2.5, "rainfall_mm": 0.0, "solar_radiation": 500.0},
                {"date": "2026-04-28", "temp_c": 16.0, "humidity_pct": 70.0,
                 "wind_speed_ms": 5.0, "rainfall_mm": 8.0, "solar_radiation": 200.0},
            ],
            avg_soil_vwc=0.24,
        )
        farm_world.set_season_phase("prep")

        for i in range(64):
            r = farm_world.get_ridge(i)
            r.soil_vwc = 0.22 + ((i % 5) - 2) * 0.01
            r.soil_temp_c = 12.0 + (i % 4) * 0.5

        # Tractor starts with 60L fuel (tight but enough for prep+planting if careful)
        tractor._fuel_tank_l = 60.0

    def oracle_solution(self, run_oracle=False):
        weather = self.get_typed_app(WeatherApp)
        sensor = self.get_typed_app(SensorApp)
        tractor = self.get_typed_app(TractorApp)
        farm_world = self.get_typed_app(FarmWorldApp)

        # ===== PHASE 1: FIELD PREP =====

        # Pre-work checks
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
            print(sensor.read_soil_sensors())
        self.workflow.add_node(WorkflowStep(
            name="read_soil", op_type="READ",
            tool_name="SensorApp__read_soil_sensors", tool_args={},
            depends_on=["check_forecast"],
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

        # Level
        if run_oracle:
            print(tractor.attach_implement("grader"))
        self.workflow.add_node(WorkflowStep(
            name="attach_grader", op_type="WRITE",
            tool_name="TractorApp__attach_implement", tool_args={"implement": "grader"},
            depends_on=["check_inventory"],
        ))

        if run_oracle:
            print(tractor.level())
        self.workflow.add_node(WorkflowStep(
            name="level", op_type="WRITE",
            tool_name="TractorApp__level", tool_args={},
            depends_on=["attach_grader"],
        ))

        if run_oracle:
            print(tractor.detach_implement())
        self.workflow.add_node(WorkflowStep(
            name="detach_grader", op_type="WRITE",
            tool_name="TractorApp__detach_implement", tool_args={},
            depends_on=["level"],
        ))

        # Base fertilize
        if run_oracle:
            print(tractor.load_fertilizer(_BASE_FERTILIZER_LOAD_KG))
        self.workflow.add_node(WorkflowStep(
            name="load_fertilizer", op_type="WRITE",
            tool_name="TractorApp__load_fertilizer",
            tool_args={"kg": _BASE_FERTILIZER_LOAD_KG},
            depends_on=["detach_grader"],
        ))

        if run_oracle:
            print(tractor.base_fertilize())
        self.workflow.add_node(WorkflowStep(
            name="base_fertilize", op_type="WRITE",
            tool_name="TractorApp__base_fertilize", tool_args={},
            depends_on=["load_fertilizer"],
        ))

        # Form ridges
        if run_oracle:
            print(tractor.attach_implement("furrower"))
        self.workflow.add_node(WorkflowStep(
            name="attach_furrower", op_type="WRITE",
            tool_name="TractorApp__attach_implement", tool_args={"implement": "furrower"},
            depends_on=["base_fertilize"],
        ))

        if run_oracle:
            print(tractor.form_ridges(1.1))
        self.workflow.add_node(WorkflowStep(
            name="form_ridges", op_type="WRITE",
            tool_name="TractorApp__form_ridges", tool_args={"ridge_width_m": 1.1},
            depends_on=["attach_furrower"],
        ))

        if run_oracle:
            print(tractor.detach_implement())
        self.workflow.add_node(WorkflowStep(
            name="detach_furrower", op_type="WRITE",
            tool_name="TractorApp__detach_implement", tool_args={},
            depends_on=["form_ridges"],
        ))

        # ===== PHASE 2: PLANTING =====

        # Refuel before planting (fuel is tight: 60-24=36L, planting needs 32L)
        if run_oracle:
            print(tractor.refuel(_REFUEL_L))
        self.workflow.add_node(WorkflowStep(
            name="refuel", op_type="WRITE",
            tool_name="TractorApp__refuel", tool_args={"liters": _REFUEL_L},
            depends_on=["detach_furrower"],
        ))

        # Load seeds batch 1
        if run_oracle:
            print(tractor.load_seeds(_SEED_TYPE, _SEEDS_PER_LOAD))
        self.workflow.add_node(WorkflowStep(
            name="load_seeds_1", op_type="WRITE",
            tool_name="TractorApp__load_seeds",
            tool_args={"seed_type": _SEED_TYPE, "count": _SEEDS_PER_LOAD},
            depends_on=["refuel"],
        ))

        # Batch 1: plant ridges 0-23 (6 passes of 4 ridges, 257280 seeds from 300000)
        prev = "load_seeds_1"
        for i in range(6):
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

        # Batch 2: plant ridges 24-47 (6 passes)
        prev = "load_seeds_2"
        for i in range(6):
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

        # Batch 3: plant ridges 48-63 (4 passes)
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
