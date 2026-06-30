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

SCENARIO_INPUT_DETAIL = """
农场进入种植前准备阶段，今天需要完成全部整地工作。
请按以下步骤操作：
1. 查看今天天气，确认无雨可以下地。
2. 查看 3 天天气预报（后天有雨 → 今天必须做完）。
3. 读取土壤传感器，确认土壤 VWC < 0.35（拖拉机可通行）。
4. 检查拖拉机油量和挂接状态。
5. 查看仓库库存，确认化肥和柴油充足。
6. 平整地面：先挂接平地机，然后旋耕平整全田（平地机宽 3m，速度 3 km/h），完成后卸下平地机。
7. 施基肥：从仓库装载 200 kg 化肥到施肥机，然后全田撒施（撒播机宽 6 m，速度 6 km/h）。
8. 起垄：挂接开沟机，起垄（垄宽 1.1 m，4 垄/趟，速度 4 km/h），做完后卸下开沟机。
9. 全部完成后立即结束任务向我汇报。
"""

SCENARIO_INPUT="""要种地了，请开始种植前的准备处理。
                  完成后告诉我。"""

class ScenarioFarmWorldFieldPrep(Scenario):
    """
    Pre-planting field preparation.

    A realistic field-prep shift: the agent must first check weather and soil
    conditions to confirm the field is workable, then complete three preparation
    steps in the correct agronomic order:
      1. level          — attach grader, rotary till and level the soil surface
      2. base_fertilize — load fertilizer from warehouse, apply across field
      3. form_ridges    — form the 64 ridge rows (1.1 m width)

    The oracle sequence includes the ground-condition checks a real farmer
    would perform before driving onto the field.
    """

    scenario_id: str = "scenario_farm_world_field_prep"
    scenario_input: str = SCENARIO_INPUT_DETAIL if DETAILED_BRIEFING else SCENARIO_INPUT
    start_time: float | None = (
            local_timestamp(2026, 4, 25, 8, 0, 0)
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
            farm_world,
            weather,
            sensor,
            mavic,
            matrice,
            robot_0,
            robot_1,
            tractor,
            field_ops,
            system,
        ]

        # --- Configure initial state ---
        weather.set_weather(
            date="2026-04-25",
            temp_c=15.0,
            humidity_pct=55.0,
            wind_speed_ms=2.0,
            rainfall_mm=0.0,
            solar_radiation=420.0,
            forecast=[
                {
                    "date": "2026-04-26",
                    "temp_c": 16.5,
                    "humidity_pct": 50.0,
                    "wind_speed_ms": 3.0,
                    "rainfall_mm": 0.0,
                    "solar_radiation": 450.0,
                },
                {
                    "date": "2026-04-27",
                    "temp_c": 14.0,
                    "humidity_pct": 70.0,
                    "wind_speed_ms": 5.0,
                    "rainfall_mm": 8.0,
                    "solar_radiation": 200.0,
                },
            ],
            avg_soil_vwc=0.22,
        )
        farm_world.set_season_phase("prep")
        for i in range(64):
            r = farm_world.get_ridge(i)
            r.soil_vwc = 0.22 + ((i % 4) - 1.5) * 0.002
            r.soil_temp_c = 10.0 + (i % 3) * 0.3

    def oracle_solution(self, run_oracle=False):
        weather = self.get_typed_app(WeatherApp)
        sensor = self.get_typed_app(SensorApp)
        tractor = self.get_typed_app(TractorApp)
        farm_world = self.get_typed_app(FarmWorldApp)

        # step 1: check weather
        if run_oracle:
            print(weather.get_current_weather())
        self.workflow.add_node(WorkflowStep(
            name="check_weather", op_type="READ",
            tool_name="WeatherApp__get_current_weather", tool_args={}, depends_on=[],
        ))

        # step 2: check forecast
        if run_oracle:
            print(weather.get_forecast(days=3))
        self.workflow.add_node(WorkflowStep(
            name="check_forecast", op_type="READ",
            tool_name="WeatherApp__get_forecast", tool_args={"days": 3},
            depends_on=["check_weather"],
        ))

        # step 3: read soil sensors
        if run_oracle:
            print(sensor.read_soil_sensors())
        self.workflow.add_node(WorkflowStep(
            name="read_soil", op_type="READ",
            tool_name="SensorApp__read_soil_sensors", tool_args={},
            depends_on=["check_forecast"],
        ))

        # step 4: check tractor status
        if run_oracle:
            print(tractor.get_status())
        self.workflow.add_node(WorkflowStep(
            name="check_tractor", op_type="READ",
            tool_name="TractorApp__get_status", tool_args={},
            depends_on=["read_soil"],
        ))

        # step 5: check inventory
        if run_oracle:
            print(farm_world.get_inventory())
        self.workflow.add_node(WorkflowStep(
            name="check_inventory", op_type="READ",
            tool_name="FarmWorldApp__get_inventory", tool_args={},
            depends_on=["check_tractor"],
        ))

        # step 6: attach grader
        if run_oracle:
            print(tractor.attach_implement("grader"))
        self.workflow.add_node(WorkflowStep(
            name="attach_grader", op_type="WRITE",
            tool_name="TractorApp__attach_implement", tool_args={"implement": "grader"},
            depends_on=["check_inventory"],
        ))

        # step 7: level field
        if run_oracle:
            print(tractor.level())
        self.workflow.add_node(WorkflowStep(
            name="level", op_type="WRITE",
            tool_name="TractorApp__level", tool_args={},
            depends_on=["attach_grader"],
        ))

        # step 8: detach grader
        if run_oracle:
            print(tractor.detach_implement())
        self.workflow.add_node(WorkflowStep(
            name="detach_grader", op_type="WRITE",
            tool_name="TractorApp__detach_implement", tool_args={},
            depends_on=["level"],
        ))

        # step 9: load fertilizer
        if run_oracle:
            print(tractor.load_fertilizer(_BASE_FERTILIZER_LOAD_KG))
        self.workflow.add_node(WorkflowStep(
            name="load_fertilizer", op_type="WRITE",
            tool_name="TractorApp__load_fertilizer",
            tool_args={"kg": _BASE_FERTILIZER_LOAD_KG},
            depends_on=["detach_grader"],
        ))

        # step 10: base fertilize
        if run_oracle:
            print(tractor.base_fertilize())
        self.workflow.add_node(WorkflowStep(
            name="base_fertilize", op_type="WRITE",
            tool_name="TractorApp__base_fertilize", tool_args={},
            depends_on=["load_fertilizer"],
        ))

        # step 11: attach furrower
        if run_oracle:
            print(tractor.attach_implement("furrower"))
        self.workflow.add_node(WorkflowStep(
            name="attach_furrower", op_type="WRITE",
            tool_name="TractorApp__attach_implement", tool_args={"implement": "furrower"},
            depends_on=["base_fertilize"],
        ))

        # step 12: form ridges
        if run_oracle:
            print(tractor.form_ridges(1.1))
        self.workflow.add_node(WorkflowStep(
            name="form_ridges", op_type="WRITE",
            tool_name="TractorApp__form_ridges", tool_args={"ridge_width_m": 1.1},
            depends_on=["attach_furrower"],
        ))

        # step 13: detach furrower
        if run_oracle:
            print(tractor.detach_implement())
        self.workflow.add_node(WorkflowStep(
            name="detach_furrower", op_type="WRITE",
            tool_name="TractorApp__detach_implement", tool_args={},
            depends_on=["form_ridges"],
        ))
