"""Two soybean farms, two fixed installations, one shared mobile fleet.

This first scenario prepares and plants both complete 64-ridge fields. It is
an ownership/integration task, not a full-season or multi-crop scenario.
Configuration, setup, reference actions, event graph and validation are here.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp, plants_per_ridge_from_spacing
from fairy.apps.farm_world.irrigation_app import IrrigationApp
from fairy.apps.farm_world.manual_ops_app import ManualOpsApp
from fairy.apps.farm_world.sensor_app import SensorApp
from fairy.apps.farm_world.shared_drone_app import SharedDroneApp
from fairy.apps.farm_world.shared_robot_app import SharedRobotApp
from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.system import SystemApp
from fairy.scenarios.registry import register_scenario
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.scenarios.workflow import Workflow, WorkflowStep
from fairy.types import EventRegisterer


@register_scenario("scenario_two_farm_shared_equipment")
class ScenarioTwoFarmSharedEquipment(Scenario):
    """Manage two separate fixed installations using one mobile fleet."""

    scenario_id = "scenario_two_farm_shared_equipment"
    start_time = datetime(2026, 5, 12, tzinfo=timezone.utc).timestamp()
    duration = 3 * 86400
    time_increment_in_seconds = 60
    expects_agent_harvest = False
    additional_system_prompt = (
        "This task manages exactly two farms: farm_a and farm_b, each with 64 local ridges. "
        "FarmA/FarmB are separate field state and warehouses. FarmA_Sensor and FarmA_Irrigation "
        "are permanently bound to farm_a; FarmB_Sensor and FarmB_Irrigation to farm_b. "
        "Tractor, Mavic3M and Robot0 are the same physical machines across both farms. "
        "Their field operations require farm_id. Material sources are independent: return "
        "unused supplies to their recorded farm before switching fields. All tools use one clock. "
        "Finish this preparation and planting task after both farms meet the task; harvest is not required."
    )
    scenario_input = (
        "管理 farm_a 和 farm_b 两个大豆农场，各有64垄，沿用现有268米垄长和1.1米垄宽。"
        "两个农场均未整地、未播种。FarmA_Sensor/FarmA_Irrigation只服务farm_a，"
        "FarmB_Sensor/FarmB_Irrigation只服务farm_b；Tractor、Mavic3M、Robot0跨场共用。"
        "先分别读取两场土壤。用各场固定灌溉系统对0–3垄各运行0.2小时，"
        "按当地条件完成两场平地、基肥、起垄及全部64垄播种。"
        "播种用STANDARD种子，播深4厘米、株距5厘米，机器每次最多4垄。"
        "使用同一Mavic3M巡查两场0–6垄、同一Robot0检查两场0–7垄。"
        "库存各场独立；共享设备的油量、电量和物料来源连续。"
        "任一场作业都会让两场一起经过时间。完成两场后汇报。"
    )

    def init_and_populate_apps(self) -> None:
        self.weather = WeatherApp()
        self.weather.set_weather("2026-05-12", 20, 55, 2, 0, 350, forecast=[
            {"date": f"2026-05-{day}", "temp_c": 21, "humidity_pct": 55,
             "wind_speed_ms": 2, "rainfall_mm": 0, "solar_radiation": 350}
            for day in range(13, 20)
        ])
        self.farm_a = FarmWorldApp(farm_id="farm_a", name="FarmA")
        self.farm_b = FarmWorldApp(farm_id="farm_b", name="FarmB")
        self.sensor_a = SensorApp(self.farm_a, name="FarmA_Sensor")
        self.sensor_b = SensorApp(self.farm_b, name="FarmB_Sensor")
        self.irrigation_a = IrrigationApp(self.farm_a, self.weather, name="FarmA_Irrigation")
        self.irrigation_b = IrrigationApp(self.farm_b, self.weather, name="FarmB_Irrigation")
        self.farm_environment = FarmEnvironment([
            FarmContext("farm_a", self.farm_a, self.weather, self.sensor_a, self.irrigation_a),
            FarmContext("farm_b", self.farm_b, self.weather, self.sensor_b, self.irrigation_b),
        ], self.weather, start_time=self.start_time, timezone_name="Asia/Shanghai")
        self.tractor = SharedTractorApp(self.farm_environment, name="Tractor")
        self.drone = SharedDroneApp(self.farm_environment, name="Mavic3M")
        self.robot = SharedRobotApp(self.farm_environment, name="Robot0")
        self.manual_ops = ManualOpsApp(self.farm_environment)
        self.system = SystemApp()
        self.aui = AgentUserInterface()
        self.shared_equipment = [self.tractor, self.drone, self.robot]
        self.apps = [self.aui, self.weather, self.farm_a, self.farm_b,
                     self.sensor_a, self.sensor_b, self.irrigation_a, self.irrigation_b,
                     *self.shared_equipment, self.manual_ops, self.system]
        for index, farm in enumerate((self.farm_a, self.farm_b)):
            farm.bound_farm_id = farm.farm_id
            farm._sim_date = "2026-05-12"
            for ridge in farm._ridges:
                ridge.soil_vwc = 0.24 + index * 0.02
                ridge.soil_temp_c = 16.0
            farm.configure_physics_profile("two_farm_shared_equipment", random_seed=self.seed)
        self.system.attach_farm_environment(self.farm_environment)
        for app in self.apps:
            app.register_time_manager(self.farm_environment.time_manager)
            app.set_seed(self.seed)
        self._initial_inventories = {
            farm.farm_id: deepcopy(farm._inventory.to_dict())
            for farm in (self.farm_a, self.farm_b)
        }

    def _reference_actions(self):
        """Complete, explicit reference strategy for this one scenario."""
        actions = []
        for sensor, irrigation in ((self.sensor_a, self.irrigation_a),
                                   (self.sensor_b, self.irrigation_b)):
            actions.extend([
                (sensor, "read_soil_sensors", {}, "Read this farm's own fixed probes."),
                (irrigation, "irrigate", {"start": 0, "end": 3, "hours": 0.2},
                 "Use this farm's fixed controller and water allowance."),
            ])
        for farm_id in ("farm_a", "farm_b"):
            actions.extend([
                (self.tractor, "attach_implement", {"implement": "grader"}, "Mount shared grader."),
                (self.tractor, "level", {"farm_id": farm_id}, "Level this field; prep belongs here."),
                (self.tractor, "detach_implement", {}, "Free the shared attachment."),
                (self.tractor, "load_fertilizer", {"farm_id": farm_id, "kg": 200.0},
                 "Load only this farm's required base fertilizer."),
                (self.tractor, "base_fertilize", {"farm_id": farm_id}, "Fertilize this field."),
                (self.tractor, "form_ridges", {"farm_id": farm_id, "ridge_width_m": 1.1},
                 "Form this field's declared ridges."),
                (self.tractor, "refuel", {"farm_id": farm_id, "liters": 100.0},
                 "Top up the same tractor from the selected farm's stock."),
            ])
            for start in range(0, 64, 4):
                actions.extend([
                    (self.tractor, "load_seeds", {
                        "farm_id": farm_id, "seed_type": "STANDARD",
                        "count": plants_per_ridge_from_spacing(5.0) * 4},
                     "Load the exact next pass so supplies need not cross farms."),
                    (self.tractor, "plant_seeds", {
                        "farm_id": farm_id, "start_ridge": start, "end_ridge": start + 3,
                        "depth_cm": 4.0, "seed_spacing_cm": 5.0},
                     "Sow these four local ridges with the shared tractor."),
                ])
            actions.extend([
                (self.drone, "fly_survey", {"farm_id": farm_id, "start_ridge": 0, "end_ridge": 6},
                 "Acquire this field's observations using the same drone battery."),
                (self.robot, "inspect_crop_health", {"farm_id": farm_id, "start_ridge": 0, "end_ridge": 7},
                 "Inspect this field using the same ground robot."),
            ])
        return actions

    def build_events_flow(self):
        """Capture the briefing and complete reference graph without running it."""
        with EventRegisterer.capture_mode() as events:
            previous = self.aui.send_message_to_agent(content=self.scenario_input).with_id("briefing")
            for index, (app, method, arguments, _) in enumerate(self._reference_actions()):
                previous = (getattr(app, method)(**arguments).oracle()
                            .with_id(f"two_farm_{index}").depends_on(previous))
        self.events = events
        return events

    def oracle_solution(self, run_oracle: bool = False) -> None:
        """Export or execute this file's reference plan via public tool methods."""
        if not self.apps:
            self.setup()
        self.workflow = Workflow()
        for index, (app, method, arguments, reason) in enumerate(self._reference_actions()):
            before = self.farm_environment.time_manager.time() if run_oracle else None
            result = getattr(app, method)(**arguments) if run_oracle else {}
            if isinstance(result, dict) and "error" in result:
                raise RuntimeError(f"{app.name}__{method}: {result['error']}")
            self.workflow.add_node(WorkflowStep(
                name=f"two_farm_{index}", tool_name=f"{app.name}__{method}",
                tool_args=arguments, content={**result, "oracle_reason": reason},
                op_type=getattr(getattr(app, method), "_event_operation_type").value,
                time_before=before,
                time_after=self.farm_environment.time_manager.time() if run_oracle else None,
                depends_on=[f"two_farm_{index-1}"] if index else [],
            ))

    def validate(self, env) -> ScenarioValidationResult:
        failures = []
        farms = {}
        steps = list(env.workflow.dag.values())
        for context in self.farm_environment.farms.values():
            farm = context.world
            planted = sum(ridge.planted for ridge in farm._ridges)
            prep = set(farm.completed_prep_ops)
            if planted != 64 or not {"level", "base_fertilize", "form_ridges"} <= prep:
                failures.append(f"{context.farm_id}: field preparation or planting incomplete")
            irrigation_log = context.irrigation.get_state()["irrigation_log"]
            irrigated = {entry["ridge_id"] for entry in irrigation_log
                         if abs(entry["duration_hours"] - 0.2) < 1e-9}
            if not set(range(4)) <= irrigated:
                failures.append(f"{context.farm_id}: own controller must irrigate ridges 0–3 for 0.2 hours each")
            if not any(step.tool_name == f"{context.sensors.name}__read_soil_sensors" for step in steps):
                failures.append(f"{context.farm_id}: own fixed sensors were not read")
            expected_seed = sum(ridge.seeds_planted for ridge in farm._ridges)
            used_seed = (self._initial_inventories[context.farm_id]["seed_stock"]["STANDARD"]
                         - farm._inventory.seed_stock["STANDARD"])
            if used_seed != expected_seed:
                failures.append(f"{context.farm_id}: seed inventory does not match this farm's planting")
            if any(ridge.seed_type != "STANDARD" or ridge.seed_spacing_cm != 5.0 for ridge in farm._ridges):
                failures.append(f"{context.farm_id}: planting must use STANDARD seed and 5 cm spacing")
            planting_log = [entry for entry in self.tractor.get_state()["operation_log"]
                            if entry.get("farm_id") == context.farm_id and entry["operation"] == "plant_seeds"]
            correct_depth = {ridge_id for entry in planting_log if entry["depth_cm"] == 4.0
                             for ridge_id in entry["ridge_ids"]}
            if correct_depth != set(range(64)):
                failures.append(f"{context.farm_id}: all ridges must be planted at 4 cm depth")
            surveyed = {ridge_id for item in self.drone.get_state()["mission_log"]
                        if item.get("farm_id") == context.farm_id
                        for ridge_id in item["surveyed_ridges"]}
            if not set(range(7)) <= surveyed:
                failures.append(f"{context.farm_id}: shared drone must actually survey ridges 0–6")
            inspected = {ridge_id for item in self.robot.get_state()["inspection_log"]
                         if item.get("farm_id") == context.farm_id and item.get("modality") == "crop_health"
                         for ridge_id in item["covered_ridges"]}
            if not set(range(8)) <= inspected:
                failures.append(f"{context.farm_id}: shared robot must actually inspect health on ridges 0–7")
            farms[context.farm_id] = {"planted_ridges": planted, "prep": sorted(prep),
                                      "used_seed": used_seed, "sim_date": farm._sim_date}
        if any(step.error_stage or (isinstance(step.content, dict) and "error" in step.content)
               for step in steps):
            failures.append("workflow contains failed tools")
        return ScenarioValidationResult(
            success=not failures, message="; ".join(failures) or "Both farms completed using two fixed installations and one shared fleet.",
            metadata={"farms": farms, "shared_equipment": [app.name for app in self.shared_equipment]},
        )
