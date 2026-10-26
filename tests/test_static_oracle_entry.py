"""A prewritten event graph builds without running and uses the existing Engine entry."""
from datetime import datetime, timezone

from fairy.apps.app import App
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.workflow import Workflow
from fairy.tool_utils import OperationType, app_tool
from fairy.types import EventRegisterer, event_registered


START = datetime(2019, 5, 1, 7, tzinfo=timezone.utc).timestamp()


class StaticFieldWorker(App):
    def __init__(self):
        super().__init__(name="FieldWorker")
        self.units = 0
        self.calls = []

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def observe(self) -> dict:
        """Read the actual counter and simulation clock."""
        self.calls.append("observe")
        return {"units": self.units, "timestamp": self.time_manager.time()}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def work(self, units: int, seconds: int) -> dict:
        """Perform explicitly sized work and charge its real operation duration."""
        before = self.time_manager.time()
        self.units += units
        self.calls.append("work")
        self.time_manager.add_offset(seconds)
        return {"status": "ok", "units": self.units,
                "started_at": before, "finished_at": self.time_manager.time()}


class StaticFieldScene(Scenario):
    start_time = START
    duration = 120
    simulation_timezone = timezone.utc

    def init_and_populate_apps(self):
        self.worker = StaticFieldWorker()
        self.clock = SystemApp()
        self.apps = [self.worker, self.clock]

    def build_events_flow(self):
        # This is a complete fixed plan. Capture never calls a tool body.
        with EventRegisterer.capture_mode() as events:
            before = self.worker.observe().oracle().with_id("before")
            first = (self.worker.work(units=2, seconds=17).oracle().with_id("first_work")
                     .depends_on(before, delay_seconds=17))
            # A dependency's delay is an exported timing estimate. The explicit
            # System tool is what actually advances the world while waiting.
            wait = (self.clock.advance_time(seconds=43).oracle().with_id("wait_until_070100")
                    .depends_on(first))
            middle = self.worker.observe().oracle().with_id("middle").depends_on(wait)
            last = (self.worker.work(units=3, seconds=11).oracle().with_id("last_work")
                    .depends_on(middle, delay_seconds=11))
            self.worker.observe().oracle().with_id("after").depends_on(last)
        for event in events:
            event.record_runtime_timing = True
        self.events = list(events)
        return self.events


def test_static_build_exports_complete_tools_arguments_and_dates_without_execution():
    scene = StaticFieldScene()
    engine = Engine(None, scene)
    workflow = engine.build_oracle_workflow(run_oracle=False)

    assert scene.worker.units == 0 and scene.worker.calls == []
    assert engine.time_manager.time() == START
    assert engine.run_log == []
    assert len(workflow) == 6
    assert list(workflow.dag) == ["before", "first_work", "wait_until_070100",
                                 "middle", "last_work", "after"]
    assert workflow.dag["first_work"].tool_args == {"units": 2, "seconds": 17}
    assert workflow.dag["wait_until_070100"].tool_name == "SystemApp__advance_time"
    assert workflow.dag["wait_until_070100"].tool_args == {"seconds": 43}
    assert workflow.dag["wait_until_070100"].time == "2019-05-01 07:01:00+00:00"
    assert workflow.dag["after"].time == "2019-05-01 07:01:11+00:00"
    assert all(step.content is None for step in workflow.dag.values())
    assert all(step.time_before is None and step.time_after is None
               for step in workflow.dag.values())


def test_original_captured_oracle_execution_and_saved_plan_replay_agree(tmp_path):
    build_scene = StaticFieldScene()
    build_engine = Engine(None, build_scene)
    planned = build_engine.build_oracle_workflow(run_oracle=False)
    path = tmp_path / "fixed_plan.json"
    planned.save_workflow(str(path))

    executed_scene = StaticFieldScene()
    executed_engine = Engine(None, executed_scene)
    executed = executed_engine.run_scenario_oracle(run_oracle=True)

    replay_scene = StaticFieldScene()
    replay_engine = Engine(None, replay_scene)
    replayed = replay_engine.replay_workflow(Workflow.load_workflow(str(path)))

    assert build_scene.worker.calls == []
    assert build_engine.time_manager.time() == START
    assert executed_scene.worker.calls == replay_scene.worker.calls == [
        "observe", "work", "observe", "work", "observe"]
    assert executed_scene.worker.units == replay_scene.worker.units == 5
    assert executed_engine.time_manager.time() == replay_engine.time_manager.time() == START + 71
    assert executed.dag["middle"].content == {"units": 2, "timestamp": START + 60}
    assert executed.dag["after"].content == {"units": 5, "timestamp": START + 71}
    assert executed.dag["first_work"].time_after - executed.dag["first_work"].time_before == 17
    assert executed.dag["last_work"].time_after - executed.dag["last_work"].time_before == 11
    assert executed.dag["wait_until_070100"].time_after - executed.dag["wait_until_070100"].time_before == 43
    assert executed.to_dict() == replayed.to_dict()
