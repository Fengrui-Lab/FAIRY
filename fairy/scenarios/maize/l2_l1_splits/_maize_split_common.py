"""Python-authored task flows and checkpoint initialization for maize splits."""
from __future__ import annotations

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world import FarmWorldApp, FieldOpsApp, SensorApp, TractorApp, WeatherApp
from fairy.apps.system import SystemApp
from fairy.scenarios.farm_world_fullseason_v2.harbin_l3_scenario_helpers import (
    advance_days, collect_event_graph, harvest_range,
)
from fairy.scenarios.maize.farm_checkpoint_state import load_checkpoint, restore_maize_checkpoint
from fairy.scenarios.maize.maize_scenario_catalog import SPECS, MaizeTaskSpec
from fairy.scenarios.maize.maize_scenario_helpers import (
    MaizeScenario, init_maize_apps, build_maize_establishment,
)
from fairy.types import EventRegisterer


class MaizeSplitScenario(MaizeScenario):
    task_spec: MaizeTaskSpec

    def __init__(self, **kwargs):
        self.spec = SPECS[self.task_spec.variant]
        self.level, self.task = self.task_spec.level, self.task_spec.task
        self.source_l3_scenario_id = self.task_spec.source_l3_scenario_id
        self.source_checkpoint_label = self.task_spec.checkpoint_label
        self._checkpoint = load_checkpoint(self.spec.variant, self.source_checkpoint_label)
        if kwargs.get("crop_backend_options", {}) not in ({}, self.spec.backend_options()):
            raise ValueError("A maize split must use its source checkpoint crop configuration")
        start = self._checkpoint["farm"]["sim_time"]
        if "start_time" in kwargs and kwargs["start_time"] != start:
            raise ValueError("A maize split must start at its checkpoint time")
        kwargs.setdefault("scenario_id", self.task_spec.scenario_id)
        kwargs.setdefault("start_time", start)
        kwargs.setdefault("duration", (self.task_spec.window_days + 3) * 86400)
        kwargs.setdefault("additional_system_prompt", (
            "Complete only the standalone maize subtask specified in the briefing. "
            "Stop at its stated endpoint after checking the result. Preserve the "
            "requested grain location: a harvest-only task ends with grain in the "
            "machine, an unload or drying task ends with grain in the receiving "
            "area, and storage is required only when the task asks for it."
        ))
        super().__init__(**kwargs)

    def validate(self, env=None):
        from fairy.scenarios.maize.validation import validate_maize_task
        return validate_maize_task(self, workflow=env.workflow if env is not None else self.workflow)


def init_maize_split(scenario):
    from fairy.scenarios.maize.validation import task_state
    init_maize_apps(scenario, scenario.spec)
    restore_maize_checkpoint(scenario, scenario._checkpoint)
    scenario._task_initial = task_state(scenario)
    scenario.scenario_input = (
        scenario.task_spec.briefing + "\n农田共64垄（0–63），每垄268米、宽0.75米、单行；"
        "品种为未本地标定的Grain_maize_201。本任务只完成指定目标，无需继续整个种植季。"
        "使用现有天气、土壤、田间观测和设备工具复核条件与结果。玉米成熟采用原生成熟状态，"
        "收获水分上限25%，入库水分上限14%；本版本不模拟病虫草害。"
    )


def build_maize_split_events(scenario):
    farm = scenario.get_typed_app(FarmWorldApp)
    tractor = scenario.get_typed_app(TractorApp)
    weather = scenario.get_typed_app(WeatherApp)
    sensor = scenario.get_typed_app(SensorApp)
    field_ops = scenario.get_typed_app(FieldOpsApp)
    system = scenario.get_typed_app(SystemApp)
    aui = scenario.get_typed_app(AgentUserInterface)
    task, level = scenario.task, scenario.level
    with EventRegisterer.capture_mode():
        briefing = aui.send_message_to_agent(content=scenario.scenario_input).with_id("briefing")
        prev = briefing

        def emit(event, name):
            nonlocal prev
            prev = event.oracle().with_id(name).depends_on(prev)

        def observe(prefix):
            emit(weather.get_current_weather(), f"{prefix}_weather")
            emit(sensor.read_soil_sensors(), f"{prefix}_soil")
            emit(farm.get_farm_overview(), f"{prefix}_crop")
            emit(farm.get_ridge_range_state(*scenario.task_spec.target_ridges), f"{prefix}_ridges")
            emit(farm.get_inventory(), f"{prefix}_inventory")
            emit(tractor.get_status(), f"{prefix}_equipment")

        observe("o_start")
        if task == "level":
            emit(tractor.attach_implement("grader"), "o_attach_grader")
            emit(tractor.level(), "o_level_field")
            emit(tractor.detach_implement(), "o_detach_grader")
        elif task == "base_fertilize":
            emit(tractor.load_fertilizer(200.0), "o_load_base_fertilizer")
            emit(tractor.base_fertilize(total_kg=200.0), "o_apply_base_fertilizer")
        elif task == "form_ridges":
            emit(tractor.attach_implement("furrower"), "o_attach_furrower")
            emit(tractor.form_ridges(0.75), "o_form_single_row_ridges")
            emit(tractor.detach_implement(), "o_detach_furrower")
        elif task == "plant":
            # The real checkpoint already contains the full-season seed load.
            emit(tractor.plant_seeds(0, 3, 4.0, 20.0), "o_plant_0_3")
        elif task == "refuel":
            emit(tractor.refuel(100.0), "o_refuel")
        elif task == "harvest":
            emit(tractor.harvest(0, 3), "o_harvest_0_3")
        elif task == "unload":
            emit(tractor.unload_grain(), "o_unload_first_batch")
        elif task == "dry":
            emit(farm.dry_grain(target_moisture_pct=14.0), "o_dry_grain")
        elif task == "store":
            emit(farm.store_grain(), "o_store_grain")
        elif task in {"irrigate", "irrigation_management"}:
            emit(field_ops.irrigate(0, 63, 6.0), "o_irrigate")
            # Native water is integrated on daily boundaries; allow it to take
            # effect before the action-ready task's final observation.
            days = 1 if level == "L1" else scenario.task_spec.window_days
            prev = advance_days(scenario, prev, days, "o_follow_water")
        elif task in {"fertilize", "nutrition_management"}:
            emit(farm.apply_fertigation(0, 63, 80.0 / (30.0 * 64), water_mm=0.0), "o_topdress")
            if level == "L2":
                prev = advance_days(scenario, prev, scenario.task_spec.window_days, "o_follow_nutrition")
        elif task == "establishment":
            prev = build_maize_establishment(scenario, prev)
            prev = advance_days(scenario, prev, 15, "o_follow_emergence")
        elif task == "harvest_storage":
            emit(weather.get_forecast(days=3), "o_harvest_forecast")
            emit(system.advance_time(days=1), "o_wait_for_field_drydown")
            observe("o_ready")
            emit(tractor.refuel(100.0), "o_refuel_before_harvest")
            prev = harvest_range(tractor, farm, prev, start_ridge=0, end_ridge=63,
                                 id_prefix="o_maize", drying_target_moisture_pct=14.0)
        else:
            raise ValueError(f"Unsupported maize task {task}")
        observe("o_recheck")
        emit(aui.send_message_to_user(content="指定玉米任务已执行，请依据作业记录、田间状态及资源台账核对结果。"), "o_report")
        scenario.events = collect_event_graph(briefing)
