"""Agent trace epochs survive replay without inheriting the host's CPU time."""
from datetime import datetime
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from fairy.agents.agent.base_agent import BaseAgent
from fairy.agents.agent.agent import Agent
from fairy.apps.app import App
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.workflow import Workflow, WorkflowStep
from fairy.tool_utils import app_tool
from fairy.time_manager import SimulationTimeManager, TimeManager
from fairy.types import EventRegisterer, event_registered


START = datetime(2026, 5, 5, 7, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()


class ClockProbe(App):
    def __init__(self, wall):
        super().__init__("ClockProbe")
        self.wall = wall
        self.calls = 0

    @app_tool()
    @event_registered()
    def observe(self) -> dict:
        self.calls += 1
        return {"timestamp": self.time_manager.time()}

    @app_tool()
    @event_registered()
    def work(self, seconds: int) -> dict:
        self.calls += 1
        self.wall[0] += 12.0  # A slower host must not add twelve replay seconds.
        self.time_manager.add_offset(seconds)
        return {"timestamp": self.time_manager.time()}


class RebuildingScene(Scenario):
    start_time = START

    def __init__(self, wall, *, legacy_wall_clock=False):
        super().__init__()
        self.wall = wall
        self.legacy_wall_clock = legacy_wall_clock

    def setup(self, **kwargs):
        self.setup_kwargs = kwargs
        self.weather = WeatherApp()
        self.weather.set_weather("2026-05-05", 16, 55, 1, 0, 250)
        self.worlds = [FarmWorldApp(farm_id=key, name=key)
                       for key in ("farm_a", "farm_b")]
        for world in self.worlds:
            world.configure_physics_profile("clock_probe_static")
        clock_arguments = {"start_time": START}
        if self.legacy_wall_clock:
            clock = TimeManager()
            clock.reset(START)
            clock_arguments = {"time_manager": clock}
        self.farm_environment = FarmEnvironment([
            FarmContext(world.farm_id, world, self.weather) for world in self.worlds
        ], self.weather, timezone_name="Asia/Shanghai",
           warehouse=WarehouseApp(stock=WarehouseStock(
               seed_stock={"STANDARD": 2_000_000}, pesticide_liters=4000.0,
               fertilizer_kg=4000.0, fuel_liters=2000.0,
           )), **clock_arguments)
        self.system = SystemApp()
        self.probe = ClockProbe(self.wall)
        self.apps = [self.weather, *self.worlds, self.farm_environment.warehouse,
                     self.system, self.probe]
        with EventRegisterer.capture_mode() as events:
            self.probe.work(seconds=60).oracle().with_id("work")
        self.events = events
        self.workflow = Workflow()


class OfflineAgent(BaseAgent):
    def __init__(self):
        super().__init__("clock-test", SimpleNamespace(provider="openai"))

    def run(self, **kwargs):
        self.observed_clock = self.time_manager
        self.observed_time = self.env_time_str()


@pytest.fixture
def wall(monkeypatch):
    value = [0.0]
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: value[0])
    return value


@pytest.mark.parametrize("mode", ["build", "agent", "dynamic"])
def test_setup_replacement_makes_engine_and_agent_adopt_the_new_environment_clock(wall, mode):
    scene = RebuildingScene(wall)
    scene.setup()
    old_clock = scene.farm_environment.time_manager
    agent = OfflineAgent()
    engine = Engine(agent, scene)
    scene.farm_environment.advance_time(3600)
    if mode == "build":
        engine.build_oracle_workflow(run_oracle=False)
    elif mode == "agent":
        engine.run_scenario_agent()
    else:
        engine.run_scenario_dynamic()
    assert engine.time_manager is scene.farm_environment.time_manager
    assert engine.time_manager is not old_clock
    assert agent.time_manager is engine.time_manager
    assert engine.time_manager.time() == START
    assert all(app.time_manager is engine.time_manager for app in scene.apps)


def test_replay_restores_recorded_waiting_and_epoch_boundaries(wall):
    scene = RebuildingScene(wall)
    engine = Engine(None, scene)
    workflow = Workflow()
    workflow.add_node(WorkflowStep(
        name="read", tool_name="ClockProbe__observe", tool_args={},
        time="2099-01-01 00:00:00", time_before=START + 1800, time_after=START + 1802,
    ))
    workflow.add_node(WorkflowStep(
        name="work", tool_name="ClockProbe__work", tool_args={"seconds": 60},
        time="2099-01-01 00:00:00", time_before=START + 18 * 3600,
        time_after=START + 18 * 3600 + 65,
    ))
    replayed = engine.replay_workflow(workflow, configured="yes")
    assert scene.setup_kwargs == {"configured": "yes"}
    for source, result, log in zip(workflow.dag.values(), replayed.dag.values(), engine.run_log):
        assert result.time_before == source.time_before == log["sim_timestamp_before"]
        assert result.time_after == source.time_after == log["sim_timestamp_after"]
        assert result.time == log["sim_time_after"] == engine._format_timestamp(source.time_after)
    assert replayed.dag["read"].content["timestamp"] == START + 1800
    assert replayed.dag["work"].content["timestamp"] == START + 18 * 3600 + 60
    assert engine.time_manager.time() == START + 18 * 3600 + 65
    assert all(world._sim_date == "2026-05-06" for world in scene.worlds)
    assert all(world.physics.last_physics_sim_time == engine.time_manager.time()
               for world in scene.worlds)


def test_legacy_oracle_display_strings_do_not_schedule_replay(wall):
    engine = Engine(None, RebuildingScene(wall))
    workflow = Workflow()
    workflow.add_node(WorkflowStep(
        tool_name="ClockProbe__work", tool_args={"seconds": 60}, time="2099-01-01 00:00:00"
    ))
    replayed = engine.replay_workflow(workflow)
    step = next(iter(replayed.dag.values()))
    assert step.time_before == START
    assert step.time_after == START + 60
    assert engine.time_manager.time() == START + 60
    assert wall[0] == 12


@pytest.mark.parametrize("end", [START - 1, float("nan"), float("inf")])
def test_invalid_recorded_end_is_rejected_before_tool_execution(wall, end):
    engine = Engine(None, RebuildingScene(wall))
    workflow = Workflow()
    workflow.add_node(WorkflowStep(tool_name="ClockProbe__observe", time_after=end))
    with pytest.raises(ValueError, match="invalid end timestamp"):
        engine.replay_workflow(workflow)
    assert engine.scenario.probe.calls == 0


def test_tool_cannot_overrun_recorded_end_and_rewind_physics(wall):
    engine = Engine(None, RebuildingScene(wall))
    workflow = Workflow()
    workflow.add_node(WorkflowStep(
        tool_name="ClockProbe__work", tool_args={"seconds": 60},
        time_before=START, time_after=START + 59,
    ))
    with pytest.raises(ValueError, match="precedes current state"):
        engine.replay_workflow(workflow)
    assert engine.time_manager.time() == START + 60
    assert engine.scenario.probe.calls == 1


def test_executed_oracle_records_actual_time_instead_of_build_estimate(wall):
    engine = Engine(None, RebuildingScene(wall, legacy_wall_clock=True))
    workflow = engine.run_scenario_oracle(run_oracle=True)
    step = workflow.dag["work"]
    assert step.time_before == START
    assert step.time_after == START + 72
    assert step.time == "2026-05-05 07:01:12+08:00"


def test_unexecuted_oracle_does_not_claim_exact_epoch_boundaries(wall):
    engine = Engine(None, RebuildingScene(wall))
    step = engine.build_oracle_workflow().dag["work"]
    assert step.time_before is step.time_after is None
    assert engine.scenario.probe.calls == 0


def test_real_agent_tool_trace_roundtrips_exact_times_and_results_offline(wall, tmp_path):
    scene = RebuildingScene(wall)
    scene.setup()
    agent = Agent("offline-clock", SimpleNamespace(provider="openai"), toolsets=scene.apps)
    Engine(agent, scene)

    def call(name, arguments):
        agent.call_function(SimpleNamespace(
            id=f"call-{agent.tool_call_count}", type="function",
            function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
        ))

    wall[0] += 2 * 3600  # Current multi-farm simulation ignores model waiting.
    call("SystemApp__advance_time", {"days": 1})
    wall[0] += 18 * 3600
    call("farm_a__apply_fertigation", {"start_ridge": 0, "end_ridge": 0,
                              "nutrient_amount": 0.24, "water_mm": 2.0})
    call("farm_a__get_farm_overview", {})
    path = tmp_path / "agent_workflow.json"
    agent.workflow.save_workflow(str(path))
    recorded = Workflow.load_workflow(str(path))
    replay = Engine(None, RebuildingScene(wall))
    result = replay.replay_workflow(recorded)
    for source, step, log in zip(recorded.dag.values(), result.dag.values(), replay.run_log):
        assert step.tool_name == source.tool_name
        assert step.tool_args == source.tool_args
        assert step.content == source.content
        assert step.time_before == source.time_before == log["sim_timestamp_before"]
        assert step.time_after == source.time_after == log["sim_timestamp_after"]
        assert step.time == source.time == log["sim_time_after"]
    assert all(world._sim_date == "2026-05-06" for world in replay.scenario.worlds)
    assert replay.time_manager.time() == agent.time_manager.time()
    for original, restored in zip(scene.worlds, replay.scenario.worlds):
        assert original.physics.soil.states == restored.physics.soil.states
        assert original.physics.management.states == restored.physics.management.states
        assert original.physics.biotic.states == restored.physics.biotic.states


def test_rebuilt_scene_rebinds_real_agent_tools_without_reopening_hidden_or_custom_tools(wall):
    scene = RebuildingScene(wall)
    scene.setup()
    original_world = scene.worlds[0]
    original_warehouse = scene.farm_environment.warehouse
    original_stock = original_warehouse.stock.fertilizer_kg
    external = ClockProbe(wall)
    external.name = "ExternalProbe"
    hidden = "farm_a__get_management_status"
    agent = Agent("offline-rebind", SimpleNamespace(provider="openai"),
                  toolsets=[*scene.apps, external], hidden_tool_names={hidden})
    engine = Engine(agent, scene)
    external_tool = agent.tools_map["ExternalProbe__observe"]

    def run(**kwargs):
        agent.call_function(SimpleNamespace(
            id="fertigate-new-scene", type="function", function=SimpleNamespace(
                name="farm_a__apply_fertigation", arguments=json.dumps({
                    "start_ridge": 0, "end_ridge": 0,
                    "nutrient_amount": 0.24, "water_mm": 2.0,
                }),
            ),
        ))

    agent.run = run
    engine.run_scenario_agent()
    assert scene.worlds[0] is not original_world
    assert scene.farm_environment.warehouse.stock.fertilizer_kg == pytest.approx(original_stock - 7.2)
    assert original_warehouse.stock.fertilizer_kg == original_stock
    assert agent.tools_map["farm_a__apply_fertigation"].class_instance is scene.worlds[0]
    assert agent.tools_map["ExternalProbe__observe"] is external_tool
    assert external_tool in agent.tools
    assert hidden not in agent.tools_map
    assert hidden not in {schema["function"]["name"] for schema in agent.tool_schemas}


def test_dynamic_mode_keeps_real_time_and_rebinds_every_clock_without_sleeping(wall, monkeypatch):
    scene = RebuildingScene(wall)
    scene.setup()
    scene.setup = lambda: None
    agent = OfflineAgent()
    engine = Engine(agent, scene)
    scene.farm_environment.advance_time(3600)
    engine.time_increment_in_seconds = 60

    class OneIterationThread:
        def __init__(self, target, **kwargs):
            self.target = target
            self.checks = 0

        def start(self):
            self.target()

        def is_alive(self):
            self.checks += 1
            return self.checks == 1

    def sleep(seconds):
        wall[0] += seconds

    monkeypatch.setattr("fairy.controllers.engine.Thread", OneIterationThread)
    monkeypatch.setattr("fairy.controllers.engine.time.sleep", sleep)
    engine.run_scenario_dynamic()
    assert not isinstance(engine.time_manager, SimulationTimeManager)
    assert engine.time_manager.time() == START + 3600 + 60
    assert engine.time_manager is scene.farm_environment.time_manager is agent.time_manager
    assert all(app.time_manager is engine.time_manager for app in scene.apps)
    assert all(world.physics.last_physics_sim_time == START + 3600 + 60
               for world in scene.worlds)
