"""Captured references preserve farm identity, execution clocks and rationale."""
from datetime import datetime

import pytest

from fairy.apps.app import App
from fairy.apps.farm_world.multi_farm import FarmFleet, FarmSite
from fairy.apps.system import SystemApp
from fairy.controllers.engine import CST, Engine
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.workflow_validation import workflow_from_oracle_events
from fairy.tool_utils import OperationType, app_tool
from fairy.types import EventRegisterer, event_registered


class ElapsedToolApp(App):
    """A tool whose simulated operation takes time independently of DAG delay."""

    def __init__(self):
        super().__init__(name="NorthWorker")
        self.calls = 0
        self.result = None

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def work(self, seconds: int = 73, result_kind: str = "dict"):
        self.calls += 1
        self.time_manager.add_offset(seconds)
        self.result = {"worked_seconds": seconds} if result_kind == "dict" else (
            "finished" if result_kind == "scalar" else None
        )
        return self.result


@pytest.fixture(autouse=True)
def isolate_event_registerer(monkeypatch):
    monkeypatch.setattr(EventRegisterer, "last_events", [])


def _captured_work(*, runtime_timing=True, metadata=True, result_kind="dict"):
    app = ElapsedToolApp()
    with EventRegisterer.capture_mode() as captured:
        event = app.work(result_kind=result_kind).oracle().with_id("work")
        event.depends_on(None, delay_seconds=5000)
        event.record_runtime_timing = runtime_timing
        if metadata:
            event.workflow_metadata = {"phase": "care", "oracle_reason": "Treat the observed local deficit."}
    scenario = Scenario(apps=[app], events=list(captured), start_time=1000)
    return app, Engine(None, scenario)


def test_event_execution_records_actual_tool_time_without_mutating_its_result(monkeypatch):
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: 10000)
    app, engine = _captured_work()
    workflow = engine.run_scenario_oracle(run_oracle=True)
    step = workflow.dag["work"]

    assert app.calls == 1
    assert step.time_before == 1000
    assert step.time_after == 1073
    assert datetime.fromisoformat(step.time).replace(tzinfo=CST).timestamp() == 1073
    assert step.content == {
        "worked_seconds": 73, "phase": "care",
        "oracle_reason": "Treat the observed local deficit.",
    }
    assert app.result == {"worked_seconds": 73}


def test_building_event_workflow_retains_reason_without_executing_tools(monkeypatch):
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: 10000)
    app, engine = _captured_work()
    step = engine.run_scenario_oracle(run_oracle=False).dag["work"]

    assert app.calls == 0
    assert engine.time_manager.time() == 1000
    assert step.content == {"phase": "care", "oracle_reason": "Treat the observed local deficit."}
    assert step.time_before is None and step.time_after is None
    assert datetime.fromisoformat(step.time).replace(tzinfo=CST).timestamp() == 6000


@pytest.mark.parametrize("result_kind,expected", [
    ("scalar", {"result": "finished", "phase": "care", "oracle_reason": "Treat the observed local deficit."}),
    ("none", {"phase": "care", "oracle_reason": "Treat the observed local deficit."}),
])
def test_metadata_wraps_non_dict_results(result_kind, expected):
    _, engine = _captured_work(result_kind=result_kind)
    assert engine.run_scenario_oracle().dag["work"].content == expected


def test_legacy_events_keep_estimated_timing_and_unwrapped_results(monkeypatch):
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: 10000)
    app, engine = _captured_work(runtime_timing=False, metadata=False, result_kind="scalar")
    step = engine.run_scenario_oracle().dag["work"]

    assert app.calls == 1
    assert engine.time_manager.time() == 1073
    assert step.content == "finished"
    assert datetime.fromisoformat(step.time).replace(tzinfo=CST).timestamp() == 6000
    assert "time_before" not in step.to_dict() and "time_after" not in step.to_dict()


def test_event_metadata_defaults_are_independent():
    app = ElapsedToolApp()
    with EventRegisterer.capture_mode():
        first, second = app.work(), app.work()
    first.workflow_metadata["phase"] = "care"
    assert second.workflow_metadata == {}
    assert not first.record_runtime_timing


def test_oracle_event_conversion_preserves_every_farm_app_namespace():
    fleet = FarmFleet([
        FarmSite.create("north", "North", num_ridges=3),
        FarmSite.create("south", "South", num_ridges=5),
    ])
    expected_tools = set()
    with EventRegisterer.capture_mode() as captured:
        for site in fleet.sites:
            for app, method in (
                (site.farm, "get_inventory"),
                (site.tractor, "get_status"),
                (site.weather, "get_current_weather"),
                (site.sensor, "read_soil_sensors"),
                (site.field_ops, "get_irrigation_log"),
            ):
                event = getattr(app, method)().oracle().with_id(f"event{len(captured)}")
                event.workflow_metadata = {"phase": "monitor", "oracle_reason": f"Read {app.name}."}
                expected_tools.add(f"{app.name}__{method}")
    workflow = workflow_from_oracle_events(Scenario(apps=fleet.apps, events=list(captured)))

    assert {step["tool_name"] for step in workflow.values()} == expected_tools
    assert len(workflow) == 10
    for step in workflow.values():
        assert step["content"] == {
            "phase": "monitor",
            "oracle_reason": f"Read {step['tool_name'].split('__')[0]}.",
        }


def test_event_conversion_keeps_distinct_reasons_for_consecutive_waits():
    system = SystemApp()
    with EventRegisterer.capture_mode() as captured:
        previous = None
        for hours, reason in ((1, "Wait for field access."), (2, "Wait for the next inspection.")):
            event = system.advance_time(hours=hours).oracle().with_id(f"wait{hours}")
            event.depends_on(previous)
            event.workflow_metadata = {"phase": "wait", "oracle_reason": reason}
            previous = event
    workflow = workflow_from_oracle_events(Scenario(apps=[system], events=list(captured)))

    assert len(workflow) == 2
    assert workflow["step0"]["content"]["oracle_reason"] == "Wait for field access."
    assert workflow["step1"]["content"]["oracle_reason"] == "Wait for the next inspection."
    assert workflow["step1"]["depends_on"] == ["step0"]
