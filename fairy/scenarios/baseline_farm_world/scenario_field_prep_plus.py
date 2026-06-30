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

_BASE_FERTILIZER_LOAD_KG = 200.0
_REFUEL_L = 50.0

# Soil VWC spike offset — rain puddle drains after ~2 hours
_PUDDLE_DRAIN_OFFSET = 2 * 3600

SCENARIO_INPUT_DETAIL = """
农场进入种植前准备阶段，今天需要完成全部整地工作。
请按以下步骤操作：
1. 查看今天天气，确认无雨可以下地。
2. 查看 3 天天气预报。
3. 读取土壤传感器，确认土壤 VWC < 0.35（拖拉机可通行）。如果土壤过湿，请等待土壤传感器关于。
4. 检查拖拉机油量和挂接状态。注意油量是否足够完成全部整地工作（平整8L+施肥8L+起垄8L=24L）。
5. 查看仓库库存，确认化肥和柴油充足。
6. 平整地面：先挂接平地机，然后旋耕平整全田，完成后卸下平地机。
7. 施基肥：从仓库装载 200 kg 化肥到施肥机，然后全田撒施。
8. 如果油量不足以完成起垄，先加油。
9. 起垄：挂接开沟机，起垄（垄宽 1.1 m），做完后卸下开沟机。
10. 全部完成后立即结束任务向我汇报。
"""

SCENARIO_INPUT = """要种地了，请开始种植前的准备处理。完成后告诉我。"""


class PuddleDrainEvent(Event):
    """
    Silent event: overnight rain left puddles, soil VWC is initially above
    the 0.35 trafficability threshold. After ~2 hours of morning sun the
    surface drains enough for tractor access.
    """

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
        self.weather_app.set_avg_soil_vwc(0.28)
        for i in range(64):
            r = self.farm_world_app.get_ridge(i)
            r.soil_vwc = 0.27 + ((i % 4) - 1.5) * 0.002
        return ""


class ScenarioFarmWorldFieldPrepPlus(Scenario):
    """
    Field prep with two real-world complications:

    1. Overnight rain left the soil surface wet (avg VWC 0.37, above the 0.35
       trafficability limit). The agent must wait ~2 hours for drainage before
       the tractor can enter the field. A silent PuddleDrainEvent lowers VWC
       to 0.28 after 2 hours.

    2. Tractor fuel tank is low (18 L). Level costs 8 L, base_fertilize costs
       8 L — leaving only 2 L, not enough for form_ridges (8 L). The agent
       must refuel from the warehouse before the final operation.

    Timeline:
      T+0   — soil VWC 0.37 (too wet), tractor fuel 18 L
      T+2h  — PuddleDrainEvent: VWC drops to 0.28 (trafficable)
      Agent: check → wait → re-check → level → fertilize → refuel → ridges
    """

    scenario_id: str = "scenario_farm_world_field_prep_plus"
    scenario_input: str = SCENARIO_INPUT_DETAIL if DETAILED_BRIEFING else SCENARIO_INPUT
    start_time: float | None = (
        local_timestamp(2026, 4, 25, 6, 0, 0)
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

        # Morning after overnight rain — no rain now but soil still wet
        weather.set_weather(
            date="2026-04-25",
            temp_c=13.0,
            humidity_pct=72.0,
            wind_speed_ms=2.0,
            rainfall_mm=0.0,
            solar_radiation=380.0,
            forecast=[
                {"date": "2026-04-26", "temp_c": 16.5, "humidity_pct": 50.0,
                 "wind_speed_ms": 3.0, "rainfall_mm": 0.0, "solar_radiation": 450.0},
                {"date": "2026-04-27", "temp_c": 14.0, "humidity_pct": 70.0,
                 "wind_speed_ms": 5.0, "rainfall_mm": 8.0, "solar_radiation": 200.0},
            ],
            avg_soil_vwc=0.37,
        )
        farm_world.set_season_phase("prep")

        # Soil wet from overnight rain
        for i in range(64):
            r = farm_world.get_ridge(i)
            r.soil_vwc = 0.36 + ((i % 4) - 1.5) * 0.002
            r.soil_temp_c = 10.0 + (i % 3) * 0.3

        # Low fuel — not enough for all 3 prep ops
        tractor._fuel_tank_l = 18.0

        # Soil drains after 2 hours of morning sun
        drain_event = PuddleDrainEvent(
            time_start=self.start_time + _PUDDLE_DRAIN_OFFSET,
            time_duration=0,
            weather_app=weather,
            farm_world_app=farm_world,
        )
        self.dynamic_events = [drain_event]

    def oracle_solution(self, run_oracle=False):
        weather = self.get_typed_app(WeatherApp)
        sensor = self.get_typed_app(SensorApp)
        tractor = self.get_typed_app(TractorApp)
        farm_world = self.get_typed_app(FarmWorldApp)
        system = self.get_typed_app(SystemApp)

        # ---- Phase 1: discover soil too wet ----

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

        if run_oracle:
            print(sensor.read_soil_sensors())
        self.workflow.add_node(WorkflowStep(
            name="read_soil_wet", op_type="READ",
            tool_name="SensorApp__read_soil_sensors", tool_args={},
            depends_on=["check_forecast"],
        ))

        # Wait for drainage (~2 hours)
        if run_oracle:
            system.wait_for_notification(timeout=_PUDDLE_DRAIN_OFFSET)
        self.workflow.add_node(WorkflowStep(
            name="wait_for_drain", op_type="READ",
            tool_name="SystemApp__wait_for_notification",
            tool_args={"timeout": _PUDDLE_DRAIN_OFFSET},
            depends_on=["read_soil_wet"],
        ))

        # ---- Phase 2: re-check conditions ----

        if run_oracle:
            print(sensor.read_soil_sensors())
        self.workflow.add_node(WorkflowStep(
            name="read_soil_dry", op_type="READ",
            tool_name="SensorApp__read_soil_sensors", tool_args={},
            depends_on=["wait_for_drain"],
        ))

        if run_oracle:
            print(tractor.get_status())
        self.workflow.add_node(WorkflowStep(
            name="check_tractor", op_type="READ",
            tool_name="TractorApp__get_status", tool_args={},
            depends_on=["read_soil_dry"],
        ))

        if run_oracle:
            print(farm_world.get_inventory())
        self.workflow.add_node(WorkflowStep(
            name="check_inventory", op_type="READ",
            tool_name="FarmWorldApp__get_inventory", tool_args={},
            depends_on=["check_tractor"],
        ))

        # ---- Phase 3: level ----

        if run_oracle:
            print(tractor.attach_implement("grader"))
        self.workflow.add_node(WorkflowStep(
            name="attach_grader", op_type="WRITE",
            tool_name="TractorApp__attach_implement",
            tool_args={"implement": "grader"},
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

        # ---- Phase 4: base fertilize ----

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

        # ---- Phase 5: refuel before form_ridges ----

        if run_oracle:
            print(tractor.refuel(_REFUEL_L))
        self.workflow.add_node(WorkflowStep(
            name="refuel", op_type="WRITE",
            tool_name="TractorApp__refuel", tool_args={"liters": _REFUEL_L},
            depends_on=["base_fertilize"],
        ))

        # ---- Phase 6: form ridges ----

        if run_oracle:
            print(tractor.attach_implement("furrower"))
        self.workflow.add_node(WorkflowStep(
            name="attach_furrower", op_type="WRITE",
            tool_name="TractorApp__attach_implement",
            tool_args={"implement": "furrower"},
            depends_on=["refuel"],
        ))

        if run_oracle:
            print(tractor.form_ridges(1.1))
        self.workflow.add_node(WorkflowStep(
            name="form_ridges", op_type="WRITE",
            tool_name="TractorApp__form_ridges",
            tool_args={"ridge_width_m": 1.1},
            depends_on=["attach_furrower"],
        ))

        if run_oracle:
            print(tractor.detach_implement())
        self.workflow.add_node(WorkflowStep(
            name="detach_furrower", op_type="WRITE",
            tool_name="TractorApp__detach_implement", tool_args={},
            depends_on=["form_ridges"],
        ))
