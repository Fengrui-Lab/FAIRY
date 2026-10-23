"""Run the real public tool chain, replay it, and reject omitted obligations."""
from copy import deepcopy
import json

import pytest

from fairy.agents.agent.agent import Agent
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.workflow import Workflow

SCENE = "scenario_two_farm_shared_equipment"


def scene():
    scenario = get_scenario_class(SCENE)()
    scenario.setup()
    return scenario, Engine(None, scenario)


@pytest.mark.parametrize("scenario_id,seeds,pesticide,fertilizer,fuel", [
    ("scenario_two_farm_shared_equipment", 2_000_000, 4000, 4000, 2000),
    ("scenario_two_farm_full_season_hn84_normal", 2_000_000, 2400, 5000, 2400),
    ("scenario_two_farm_full_season_hn84_disease_water", 2_000_000, 320, 5000, 2400),
    ("scenario_three_farm_full_season_hn84_normal", 3_000_000, 3600, 7500, 3600),
])
def test_shared_warehouse_keeps_preexisting_scene_aggregate_budget(
    scenario_id, seeds, pesticide, fertilizer, fuel,
):
    scenario = get_scenario_class(scenario_id)()
    scenario.setup()
    stock = scenario.warehouse.stock
    assert len(stock.seed_stock) == 10
    assert set(stock.seed_stock.values()) == {seeds}
    assert stock.pesticide_liters == pesticide
    assert stock.fertilizer_kg == fertilizer
    assert stock.fuel_liters == fuel
    assert scenario.warehouse.get_inventory()["inventory_scope"] == "scene"
    assert scenario.farm_environment.warehouse is scenario.warehouse
    assert sum(app is scenario.warehouse for app in scenario.apps) == 1


def test_two_farm_oracle_completes_with_exact_fixed_and_mobile_ownership():
    scenario, engine = scene()
    engine.run_scenario_oracle(True)
    assert engine.evaluate().success
    assert scenario.sensor_a is not scenario.sensor_b
    assert scenario.irrigation_a is not scenario.irrigation_b
    assert scenario.farm_environment.warehouse is scenario.warehouse
    assert sum(app is scenario.warehouse for app in scenario.apps) == 1
    assert scenario.shared_equipment == [scenario.tractor, scenario.drone, scenario.robot]
    assert all(sum(r.planted for r in farm._ridges) == 64 for farm in (scenario.farm_a, scenario.farm_b))
    assert scenario.drone._battery_pct == 86
    assert scenario.robot._battery_pct == 20
    outcome = engine.outcome_summary()
    assert set(outcome["farms"]) == {"farm_a", "farm_b"}
    assert len(outcome["shared_equipment"]) == 3
    assert next(iter(scenario.workflow.dag.values())).op_type == "read"


def test_saved_reference_replays_from_a_blank_scene(tmp_path):
    original, engine = scene()
    workflow = engine.run_scenario_oracle(False)
    assert not any(r.planted for r in original.farm_a._ridges)
    path = tmp_path / "two_farm_oracle.json"
    workflow.save_workflow(str(path))
    fresh, replay = scene()
    replay.replay_workflow(Workflow.load_workflow(str(path)))
    assert replay.evaluate().success
    assert "source_farm_id" not in fresh.tractor.get_state()
    assert fresh.farm_environment.time_manager is replay.time_manager


def test_captured_reference_uses_same_public_actions():
    scenario, engine = scene()
    assert len(scenario.events) == len(scenario._reference_actions()) + 1
    assert not any(r.planted for r in scenario.farm_b._ridges)
    engine._run_captured_oracle_events(True)
    assert engine.evaluate().success


@pytest.mark.parametrize("omission", ["farm_b", "sensors_b", "short_irrigation", "short_survey", "short_robot", "wrong_depth"])
def test_reference_obligations_cannot_be_replaced_by_partial_or_wrong_actions(omission):
    scenario, engine = scene()
    actions = scenario._reference_actions()
    modified = []
    for app, method, arguments, reason in actions:
        arguments = dict(arguments)
        if omission == "farm_b" and (arguments.get("farm_id") == "farm_b" or app in (scenario.sensor_b, scenario.irrigation_b)):
            continue
        if omission == "sensors_b" and app is scenario.sensor_b:
            continue
        if omission == "short_irrigation" and method == "irrigate":
            arguments.update(end=0, hours=0.1)
        if omission == "short_survey" and method == "fly_survey":
            arguments["end_ridge"] = 0
        if omission == "short_robot" and method == "inspect_crop_health":
            arguments["end_ridge"] = arguments["start_ridge"]
        if omission == "wrong_depth" and method == "plant_seeds":
            arguments["depth_cm"] = 3.0
        modified.append((app, method, arguments, reason))
    scenario._reference_actions = lambda: modified
    engine.run_scenario_oracle(True)
    assert not engine.evaluate().success


class SchemaFollowingLLM:
    provider = "openai"
    model = "offline-two-farm-tool-test"

    def __init__(self):
        self.requests = []

    def chat_completion(self, messages, tools):
        from openai.types.chat import ChatCompletion
        self.requests.append(deepcopy(tools))
        turn = len(self.requests)
        schema = next(t["function"] for t in tools if t["function"]["name"] == "Mavic3M__fly_survey")
        assert schema["parameters"]["properties"]["farm_id"]["enum"] == ["farm_a", "farm_b"]
        calls = None
        if turn <= 2:
            calls = [{"id": f"survey_{turn}", "type": "function", "function": {
                "name": schema["name"], "arguments": json.dumps({
                    "farm_id": ["farm_a", "farm_b"][turn-1], "start_ridge": 0, "end_ridge": 0})}}]
        return ChatCompletion.model_validate({
            "id": f"turn_{turn}", "object": "chat.completion", "created": 0, "model": self.model,
            "choices": [{"index": 0, "finish_reason": "tool_calls" if calls else "stop",
                         "message": {"role": "assistant", "content": None if calls else "done", "tool_calls": calls}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}})


def test_actual_agent_gets_two_fixed_tool_sets_and_shared_explicit_drone():
    scenario, engine = scene()
    llm = SchemaFollowingLLM()
    agent = Agent("two-farm", llm, toolsets=scenario.apps)
    agent.set_time_manager(engine.time_manager)
    assert agent.run("Survey both farms with the shared drone", max_tool_calls=3) == "done"
    names = {t["function"]["name"] for t in llm.requests[0]}
    assert {"FarmA_Sensor__read_soil_sensors", "FarmB_Sensor__read_soil_sensors",
            "FarmA_Irrigation__irrigate", "FarmB_Irrigation__irrigate",
            "Warehouse__get_inventory", "Warehouse__get_grain_batches"} <= names
    assert {"FarmA__get_inventory", "FarmB__get_inventory"}.isdisjoint(names)
    assert scenario.drone._battery_pct == 98
    assert [log["farm_id"] for log in scenario.drone.get_state()["mission_log"]] == ["farm_a", "farm_b"]
