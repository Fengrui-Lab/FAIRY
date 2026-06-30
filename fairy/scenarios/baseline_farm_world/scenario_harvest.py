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

SCENARIO_INPUT_DETAIL = """
大豆已成熟，进入收获阶段。请按真实农民流程操作：
1. 查看今天天气（rainfall=0，可收割）和 3 天预报
2. 读土壤传感器，确认 VWC<0.35、地面可通行。
3. 读冠层传感器，看 NDVI 是否全田枯黄（R8 应该偏低）。
4. 确认所有 64 条垄都到 R8 且籽粒含水 13-18%。
5. 用 Mavic3M 飞一圈（fly_survey 0-63）验证均匀成熟。
6. 检查拖拉机状态：先挂接收割机,油只有 20 L → 再refuel 到 100 L。
7. 一趟 4 垄，共 16 趟，从 0-3 开始到 60-63。
   每趟约 980 kg 粮食进入储罐（容量 2000 kg），
   所以每 2 趟就要 unload_grain 一次把粮食卸到仓库。
8. 全部收割完 + 卸完粮后，卸载收割机，看 inventory 汇报总产量。
9. 全部完成后立即结束任务向我汇报。
"""

SCENARIO_INPUT = """大豆熟了，收割全部64垄。完成后汇报总产量。"""


class ScenarioFarmWorldHarvest(Scenario):
    """
    Soybean harvest scenario.

    Late September, Harbin. All 64 ridges are at R8 maturity with grain
    moisture in the 13-18% harvest window. The agent must check weather,
    confirm field conditions, survey crop maturity, then systematically
    harvest all ridges before the weather window closes.
    """

    scenario_id: str = "scenario_farm_world_harvest"
    scenario_input: str = SCENARIO_INPUT_DETAIL if DETAILED_BRIEFING else SCENARIO_INPUT
    start_time: float | None = (
        local_timestamp(2026, 9, 25, 8, 0, 0)
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
            description="DJI Mavic 3M multispectral drone",
            speed_ms=5.0,
            effective_ridges_per_pass=7,
            takeoff_overhead_s=30,
            min_battery_pct=20.0,
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
            date="2026-09-25",
            temp_c=18.0,
            humidity_pct=45.0,
            wind_speed_ms=2.0,
            rainfall_mm=0.0,
            solar_radiation=380.0,
            forecast=[
                {"date": "2026-09-26", "temp_c": 19.0, "humidity_pct": 50.0,
                 "wind_speed_ms": 2.5, "rainfall_mm": 0.0, "solar_radiation": 400.0},
                {"date": "2026-09-27", "temp_c": 16.0, "humidity_pct": 75.0,
                 "wind_speed_ms": 6.0, "rainfall_mm": 12.0, "solar_radiation": 150.0},
            ],
            avg_soil_vwc=0.24,
        )
        farm_world.set_season_phase("harvest")

        for i in range(64):
            r = farm_world.get_ridge(i)
            r.planted = True
            r.seed_type = "STANDARD"
            r.seed_spacing_cm = 12.0
            r.seeds_planted = 4467
            r.days_since_planted = 125
            r.growth_stage = "R8"
            r.grain_moisture_pct = 15.0 + ((i % 5) - 2) * 0.3
            r.soil_vwc = 0.24 + ((i % 4) - 1.5) * 0.01
            r.soil_temp_c = 12.0 + (i % 3) * 0.2
            r.yield_potential = 0.93 + (i % 7) * 0.01
            r.ndvi = 0.35 + (i % 5) * 0.02
            r.canopy_temp_c = 20.0 + (i % 3) * 0.5

        tractor._fuel_tank_l = 20.0
        tractor._completed_prep_ops = ["level", "base_fertilize", "form_ridges"]

    def oracle_solution(self, run_oracle=False):
        weather = self.get_typed_app(WeatherApp)
        sensor = self.get_typed_app(SensorApp)
        farm_world = self.get_typed_app(FarmWorldApp)
        drone = self.get_typed_app(DroneApp, app_name="Mavic3M")
        tractor = self.get_typed_app(TractorApp)

        # Pre-harvest checks
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
            print(sensor.read_canopy_sensors())
        self.workflow.add_node(WorkflowStep(
            name="read_canopy", op_type="READ",
            tool_name="SensorApp__read_canopy_sensors", tool_args={},
            depends_on=["read_soil"],
        ))

        if run_oracle:
            print(farm_world.get_farm_overview())
        self.workflow.add_node(WorkflowStep(
            name="farm_overview", op_type="READ",
            tool_name="FarmWorldApp__get_farm_overview", tool_args={},
            depends_on=["read_canopy"],
        ))

        # Drone survey
        if run_oracle:
            print(drone.fly_survey(start_ridge=0, end_ridge=63))
        self.workflow.add_node(WorkflowStep(
            name="drone_survey", op_type="READ",
            tool_name="Mavic3M__fly_survey",
            tool_args={"start_ridge": 0, "end_ridge": 63},
            depends_on=["farm_overview"],
        ))

        # Tractor check + refuel
        if run_oracle:
            print(tractor.get_status())
        self.workflow.add_node(WorkflowStep(
            name="check_tractor", op_type="READ",
            tool_name="TractorApp__get_status", tool_args={},
            depends_on=["drone_survey"],
        ))

        if run_oracle:
            print(tractor.attach_implement("harvester"))
        self.workflow.add_node(WorkflowStep(
            name="attach_harvester", op_type="WRITE",
            tool_name="TractorApp__attach_implement", tool_args={"implement": "harvester"},
            depends_on=["check_tractor"],
        ))

        if run_oracle:
            print(tractor.refuel(80.0))
        self.workflow.add_node(WorkflowStep(
            name="refuel", op_type="WRITE",
            tool_name="TractorApp__refuel", tool_args={"liters": 80.0},
            depends_on=["check_tractor"],
        ))

        # 16 harvest passes, unload every 2 passes
        prev = "refuel"
        for pass_idx in range(16):
            start_ridge = pass_idx * 4
            end_ridge = start_ridge + 3
            harvest_name = f"harvest_pass_{pass_idx + 1}"
            if run_oracle:
                print(tractor.harvest(start_ridge=start_ridge, end_ridge=end_ridge))
            self.workflow.add_node(WorkflowStep(
                name=harvest_name, op_type="WRITE",
                tool_name="TractorApp__harvest",
                tool_args={"start_ridge": start_ridge, "end_ridge": end_ridge},
                depends_on=[prev],
            ))
            prev = harvest_name

            if pass_idx % 2 == 1:
                unload_name = f"unload_{(pass_idx + 1) // 2}"
                if run_oracle:
                    print(tractor.unload_grain())
                self.workflow.add_node(WorkflowStep(
                    name=unload_name, op_type="WRITE",
                    tool_name="TractorApp__unload_grain", tool_args={},
                    depends_on=[prev],
                ))
                prev = unload_name

        if run_oracle:
            print(tractor.detach_implement())
        self.workflow.add_node(WorkflowStep(
            name="detach_furrower", op_type="WRITE",
            tool_name="TractorApp__detach_implement", tool_args={},
            depends_on=[prev],
        ))
        # Check inventory
        if run_oracle:
            print(farm_world.get_inventory())
        self.workflow.add_node(WorkflowStep(
            name="check_inventory", op_type="READ",
            tool_name="FarmWorldApp__get_inventory", tool_args={},
            depends_on=[prev],
        ))
