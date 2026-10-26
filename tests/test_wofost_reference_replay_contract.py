"""Strict saved-workflow comparisons for the formal reference world's replay.

Only the robot's documented uuid4 inspection token is canonicalized. Device,
farm and ridge identities, observations, amounts and all timestamps remain
comparison inputs. The helper also supports independent CLI-artifact audits.
"""
from collections import Counter
from copy import deepcopy
from datetime import date
import json
import re

import pytest

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.app import App
from fairy.apps.farm_world import FarmWorldApp, RobotApp, SensorApp, WeatherApp
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.workflow import Workflow, WorkflowStep
from fairy.scenarios.wofost_events import install_scenario_events
from fairy.scenarios.wofost_farm import FarmDefinition, WofostReferenceScenario
from fairy.tool_execution import ToolExecutionError, ToolResult
from fairy.tool_utils import OperationType, app_tool
from fairy.types import EventRegisterer, event_registered


def _differences(left, right, path=()):
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(left.keys() | right.keys()):
            if key not in left or key not in right:
                yield {"path": list(path+(key,)), "oracle": left.get(key, "<missing>"),
                    "replay": right.get(key, "<missing>")}
            else:
                yield from _differences(left[key], right[key], path+(key,))
    elif isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            yield {"path": list(path+("length",)), "oracle": len(left), "replay": len(right)}
        for index, (a, b) in enumerate(zip(left, right)):
            yield from _differences(a, b, path+(index,))
    elif type(left) is bool or type(right) is bool:
        if type(left) is not type(right) or left != right:
            yield {"path": list(path), "oracle": left, "replay": right}
    elif left != right:
        yield {"path": list(path), "oracle": left, "replay": right}


def compare_saved_workflows(oracle, replay):
    """Return exact differences; never round observations or adjust clocks."""
    left, right = deepcopy(oracle), deepcopy(replay)
    random_id_differences = []
    for name in left.keys() & right.keys():
        a, b = left[name], right[name]
        if a.get("tool_name") != "Robot0__inspect_crop_health" or b.get("tool_name") != a["tool_name"]:
            continue
        ac, bc = a.get("content"), b.get("content")
        if not isinstance(ac, dict) or not isinstance(bc, dict):
            continue
        x, y = ac.get("inspection_id"), bc.get("inspection_id")
        if isinstance(x, str) and isinstance(y, str) and re.fullmatch(r"[0-9a-f]{8}", x) and re.fullmatch(r"[0-9a-f]{8}", y):
            if x != y:
                random_id_differences.append({"path": [name, "content", "inspection_id"],
                    "oracle": x, "replay": y})
            ac["inspection_id"] = bc["inspection_id"] = "<uuid4 inspection token>"
    differences = list(_differences(left, right))
    counts = Counter(row["path"][1] if len(row["path"]) > 1 else "workflow" for row in differences)
    return {"step_count_oracle": len(oracle), "step_count_replay": len(replay),
        "step_order_exact": list(oracle) == list(replay),
        "exact_after_documented_random_ids": not differences and list(oracle) == list(replay),
        "field_difference_counts": dict(counts), "differences": differences,
        "random_id_differences": random_id_differences}


def logged_preview_matches_saved_response(tool_name, content, preview):
    """Check the 500-character Python repr without dropping observation data.

    RobotApp constructs observations with integer ridge keys; JSON object keys
    are necessarily strings. Reconstruct only that documented key type when
    comparing the in-memory log's repr. Workflow-vs-workflow comparison above
    keeps the serialized identity keys untouched.
    """
    if str(content)[:500] == preview:
        return "exact_python_repr"
    if tool_name != "Robot0__inspect_crop_health" or not isinstance(content, dict):
        return "mismatch"
    observations = content.get("observations")
    if not isinstance(observations, dict) or not observations:
        return "mismatch"
    if not all(isinstance(key, str) and re.fullmatch(r"0|[1-9][0-9]*", key) for key in observations):
        return "mismatch"
    original = deepcopy(content)
    original["observations"] = {int(key): value for key, value in observations.items()}
    return "integer_ridge_keys_reconstructed_from_json" if str(original)[:500] == preview else "mismatch"


class ReplayContractWorld(WofostReferenceScenario):
    WORLD = FarmDefinition(reference_id="lille", seed_type="SOYBEAN_901",
        timezone_name="Europe/Paris", sowing_date=date(2019, 4, 28),
        end_date=date(2019, 11, 15), num_ridges=2, external_biotic_coupling=False)
    DESCRIPTION = "A short real-tool sequence in the formal native world."

    def build_events_flow(self):
        install_scenario_events(self, [])
        sensor = self.get_typed_app(SensorApp)
        robot = self.get_typed_app(RobotApp)
        system = self.get_typed_app(SystemApp)
        weather = self.get_typed_app(WeatherApp)
        farm = self.get_typed_app(FarmWorldApp)
        with EventRegisterer.capture_mode() as events:
            self.get_typed_app(AgentUserInterface).send_message_to_agent(self.reference_briefing())
            surface = sensor.read_soil_sensors().oracle().with_id("surface")
            ground = (robot.inspect_crop_health(start_ridge=0, end_ridge=1).oracle()
                      .with_id("ground").depends_on(surface))
            wait = (system.advance_time(seconds=86400).oracle().with_id("real_day")
                    .depends_on(ground))
            station = weather.get_current_weather().oracle().with_id("station").depends_on(wait)
            next_ground = (robot.inspect_crop_health(start_ridge=0, end_ridge=1).oracle()
                           .with_id("next_ground").depends_on(station))
            farm.get_inventory().oracle().with_id("inventory").depends_on(next_ground)
        for event in events:
            event.record_runtime_timing = True
        self.events = list(events)
        return self.events


def test_formal_registered_tools_survive_json_save_load_and_fresh_replay_without_ignoring_time(tmp_path):
    first = Engine(None, ReplayContractWorld())
    oracle = first.run_scenario_oracle()
    source = tmp_path / "oracle.json"
    oracle.save_workflow(str(source))
    fresh = Engine(None, ReplayContractWorld())
    replay = fresh.replay_workflow(Workflow.load_workflow(str(source)))
    target = tmp_path / "replay.json"
    replay.save_workflow(str(target))
    result = compare_saved_workflows(json.loads(source.read_text()), json.loads(target.read_text()))
    assert result["step_order_exact"] and result["exact_after_documented_random_ids"], result["differences"]
    assert len(result["random_id_differences"]) == 2
    assert first.time_manager.time() == fresh.time_manager.time()
    assert all(row["status"] == "ok" for row in fresh.run_log)
    for step, log in zip(replay.dag.values(), fresh.run_log):
        assert step.time_before == log["sim_timestamp_before"]
        assert step.time_after == log["sim_timestamp_after"]


@pytest.mark.parametrize("field,new_value", [
    ("time_before", 101.), ("time_after", 101.), ("time", "2019-04-28 07:00:01"),
    ("tool_args", {"ridge_id": 1}), ("content", {"ridge_id": 1, "vwc": .260001}),
])
def test_artifact_comparison_detects_even_small_numeric_time_argument_and_identity_changes(field, new_value):
    oracle = {"step": {"tool_name": "SensorApp__read_soil_sensor", "tool_args": {"ridge_id": 0},
        "content": {"ridge_id": 0, "vwc": .26}, "time_before": 100., "time_after": 100.,
        "time": "2019-04-28 07:00:00"}}
    replay = deepcopy(oracle)
    replay["step"][field] = new_value
    result = compare_saved_workflows(oracle, replay)
    assert result["exact_after_documented_random_ids"] is False
    assert field in result["field_difference_counts"]


def test_random_id_whitelist_does_not_hide_stable_farm_or_ridge_ids_or_other_tool_tokens():
    oracle = {"ground": {"tool_name": "Robot0__inspect_crop_health", "content": {
        "inspection_id": "1234abcd", "farm_id": "farm", "covered_ridges": [0, 1], "confidence": .9}}}
    replay = deepcopy(oracle)
    replay["ground"]["content"].update(inspection_id="abcd1234", farm_id="other", confidence=.900001)
    result = compare_saved_workflows(oracle, replay)
    assert len(result["random_id_differences"]) == 1
    assert {tuple(row["path"][-1:]) for row in result["differences"]} == {("farm_id",), ("confidence",)}
    oracle["ground"]["tool_name"] = replay["ground"]["tool_name"] = "OtherApp__inspect_crop_health"
    assert not compare_saved_workflows(oracle, replay)["random_id_differences"]


def test_runtime_preview_checks_integer_key_serialization_without_hiding_changed_observations():
    native = {"observations": {0: {"ridge_id": 0, "confidence": .9}}, "covered_ridges": [0]}
    saved = json.loads(json.dumps(native))
    tool = "Robot0__inspect_crop_health"
    assert logged_preview_matches_saved_response(tool, saved, str(native)) == "integer_ridge_keys_reconstructed_from_json"
    saved["observations"]["0"]["confidence"] = .900001
    assert logged_preview_matches_saved_response(tool, saved, str(native)) == "mismatch"
    assert logged_preview_matches_saved_response("OtherApp__inspect_crop_health", saved, str(native)) == "mismatch"


class ReplayDevice(App):
    """A real registered device whose failures can occur after partial work."""

    def __init__(self):
        super().__init__(name="ReplayDevice")
        self.stock, self.calls, self.receipt = 10, [], None

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def prepare(self) -> dict:
        self.calls.append("prepare")
        self.stock -= 1
        self.time_manager.add_offset(2)
        return {"status": "ok", "remaining": self.stock}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def attempt(self, kind: str) -> dict:
        self.calls.append("attempt")
        self.stock -= 2
        before = self.time_manager.time()
        self.time_manager.add_offset(5)
        if kind == "structured":
            self.receipt = ToolResult(ok=False, tool="ReplayDevice__attempt", data={"remaining": self.stock},
                error=ToolExecutionError("DEVICE_FAILURE", "Pressure failed during delivery",
                    stage="execution", partial_effects=True),
                time_before=before, time_after=self.time_manager.time())
        elif kind == "legacy_error":
            self.receipt = {"error": "Pressure failed during delivery", "remaining": self.stock}
        elif kind in {"error", "failed", "partial"}:
            self.receipt = {"status": kind, "reason": "Pressure failed during delivery", "remaining": self.stock}
        elif kind == "warning":
            self.receipt = {"status": "warning", "warning": "Inspect pressure after delivery", "remaining": self.stock}
        elif kind == "empty_error":
            self.receipt = {"status": "ok", "error": "", "remaining": self.stock}
        else:
            self.receipt = {"status": "ok", "error": None, "warnings": ["Inspect pressure"], "remaining": self.stock}
        return self.receipt

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def following_work(self) -> dict:
        self.calls.append("following_work")
        self.stock -= 1
        self.time_manager.add_offset(1)
        return {"status": "ok", "remaining": self.stock}


class DeviceReplayScene(Scenario):
    start_time = 1000.
    duration = 120.

    def init_and_populate_apps(self):
        self.device = ReplayDevice()
        self.apps = [self.device]


def device_workflow(kind):
    workflow = Workflow()
    for name, method, args, before, after, dependencies in [
        ("prepare", "prepare", {}, 1000., 1002., []),
        ("attempt", "attempt", {"kind": kind}, 1002., 1007., ["prepare"]),
        ("following", "following_work", {}, 1007., 1008., ["attempt"]),
    ]:
        workflow.add_node(WorkflowStep(name=name, tool_name="ReplayDevice__"+method,
            tool_args=args, op_type="WRITE", time_before=before, time_after=after, depends_on=dependencies))
    return workflow


@pytest.mark.parametrize("kind", ["legacy_error", "error", "failed", "partial", "structured"])
def test_replay_stops_on_returned_tool_error_and_preserves_actual_partial_effects(kind):
    scene = DeviceReplayScene()
    engine = Engine(None, scene)
    with pytest.raises(ToolExecutionError, match="Pressure failed during delivery") as raised:
        engine.replay_workflow(device_workflow(kind))
    assert scene.device.calls == ["prepare", "attempt"]
    assert scene.device.stock == 7
    assert engine.time_manager.time() == 1007.
    assert list(scene.workflow.dag) == ["prepare", "attempt"]
    failed = scene.workflow.dag["attempt"]
    assert failed.content == scene.device.receipt
    assert failed.tool_args == {"kind": kind} and failed.op_type == "WRITE"
    assert (failed.time_before, failed.time_after) == (1002., 1007.)
    assert len(engine.run_log) == 2 and engine.run_log[-1]["status"] == "error"
    assert engine.run_log[-1]["sim_timestamp_after"] == 1007.
    assert "Pressure failed during delivery" in engine.run_log[-1]["error"]
    assert raised.value.stage == "execution"
    if kind == "structured":
        assert raised.value.code == "DEVICE_FAILURE" and raised.value.partial_effects is True
    else:
        assert raised.value.code == "LEGACY_TOOL_ERROR" and raised.value.partial_effects == "unknown"


@pytest.mark.parametrize("kind", ["warning", "empty_error", "warnings"])
def test_replay_does_not_mistake_warnings_or_false_error_values_for_failure(kind):
    scene = DeviceReplayScene()
    engine = Engine(None, scene)
    replay = engine.replay_workflow(device_workflow(kind))
    assert list(replay.dag) == ["prepare", "attempt", "following"]
    assert scene.device.calls == ["prepare", "attempt", "following_work"]
    assert scene.device.stock == 6 and engine.time_manager.time() == 1008.
    assert [row["status"] for row in engine.run_log] == ["ok", "ok", "ok"]
