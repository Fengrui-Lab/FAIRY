"""Briefing detail changes agent guidance, never the underlying farm experiment.

The seven independently defined scenarios share this public mode contract. The
integration check executes each real Oracle twice, rather than treating an
identical exported plan as proof that physics and inventory also stay identical.
"""
from copy import deepcopy
from types import SimpleNamespace
import re

import pytest

from fairy.agents.agent.agent import Agent
from fairy.agents.agent.toolset_builder import build_toolset
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class


SCENARIOS = (
    "scenario_two_farm_shared_equipment",
    "scenario_two_farm_full_season_hn84_normal",
    "scenario_three_farm_full_season_hn84_normal",
    "scenario_two_farm_full_season_hn84_disease_water",
    "scenario_single_farm_maize_full_season",
    "scenario_single_farm_maize_normal_management",
    "scenario_two_farm_maize_soybean_full_season",
)

# These are reference-strategy hints, not the task's completion requirements.
# False must leave the agent to obtain conditions and choose actions from tools.
DETAILED_ONLY_HINTS = {
    SCENARIOS[0]: ("机器每次最多4垄",),
    SCENARIOS[1]: ("nutrient_amount=0.24", "water_mm=2.0", "约播后15天"),
    SCENARIOS[2]: ("nutrient_amount=0.24", "water_mm=2.0", "约播后15天"),
    SCENARIOS[3]: ("3.8L/垄", "精确装76L", "参考8/2、8/9"),
    SCENARIOS[4]: ("6kg/垄", "参考各补水20mm", "5月中旬"),
    SCENARIOS[5]: ("6kg/垄", "R1窗口可补20mm", "未来两天有约18mm雨"),
    SCENARIOS[6]: ("6kg/垄", "2kg/垄", "吐丝期参考补水20mm"),
}


def new_scene(scenario_id, **kwargs):
    scene = get_scenario_class(scenario_id)(seed=37, **kwargs)
    scene.setup()
    return scene


def briefing_event(scene):
    candidates = [event for event in scene.events
                  if event.app.name == "AgentUserInterface"
                  and event.function.__name__ == "send_message_to_agent"]
    assert len(candidates) == 1
    return candidates[0]


class FirstTurnProbe(Agent):
    """Use real Engine/Agent input handling, replacing only the model response."""

    def __init__(self, apps):
        super().__init__("briefing-probe", SimpleNamespace(provider="openai"),
                         system_message="Test controller.", toolsets=apps)

    def _chat_completion_with_retries(self, messages, tools=None):
        self.first_request = deepcopy(messages)
        return SimpleNamespace(content="Offline input captured.", tool_calls=[])


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_selected_briefing_reaches_captured_event_and_real_agent_first_turn(scenario_id):
    basic = new_scene(scenario_id, detailed_briefing=False)
    detailed = new_scene(scenario_id, detailed_briefing=True)
    default = get_scenario_class(scenario_id)()
    assert basic.scenario_input != detailed.scenario_input
    assert len(detailed.scenario_input) > len(basic.scenario_input)
    assert default.detailed_briefing is True
    assert default.scenario_input == detailed.scenario_input

    first_requests = []
    for scene in (basic, detailed):
        assert briefing_event(scene).kwargs == {"content": scene.scenario_input}
        agent = FirstTurnProbe(scene.apps)
        engine = Engine(agent, scene)
        engine.run_scenario_agent()
        first_requests.append(agent.first_request)
        user_messages = [message for message in agent.first_request
                         if message["role"] == "user"]
        assert [message["content"] for message in user_messages] == [scene.scenario_input]
        assert next(iter(agent.workflow.dag.values())).content == scene.scenario_input
        source = [event for event in agent.runtime_events
                  if event["event_type"] == "agent_task_source"]
        assert len(source) == 1 and source[0]["source"] == "event_briefing"

    # Inspect the complete first prompt as well as the scenario string: a basic
    # briefing must not quietly receive the detailed recipe via system context.
    basic_prompt = "\n".join(message["content"]
                             for message in first_requests[0])
    for hint in DETAILED_ONLY_HINTS[scenario_id]:
        assert hint in detailed.scenario_input
        assert hint not in basic_prompt


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_basic_mode_keeps_ownership_geometry_and_completion_contract(scenario_id):
    text = get_scenario_class(scenario_id)(detailed_briefing=False).scenario_input
    assert all(token in text for token in ("64", "268", "farm_id"))
    if "shared_equipment" in scenario_id:
        required = ("farm_a", "farm_b", "1.1", "STANDARD", "Warehouse",
                    "0–3", "0.2", "4cm", "5cm", "0–6", "0–7", "无需收获")
    elif "maize" in scenario_id:
        required = ("maize_field", "0.65", "1.11488", "MAIZE_EARLY_2026",
                    "入库", "北京时间")
        if "two_farm" in scenario_id:
            required += ("soybean_field", "1.88672", "HEINONG84", "Warehouse")
        else:
            required += ("SensorApp", "FieldOpsApp")
    else:
        required = ("farm_a", "farm_b", "1.1", "1.88672", "HEINONG84",
                    "Warehouse", "入库", "北京时间", "validate暂空")
        if "three_farm" in scenario_id:
            required += ("farm_c", "FarmC_Sensor", "FarmC_Irrigation")
        if "disease_water" in scenario_id:
            required += ("病害记录", "土层较浅", "实际观测")
    for token in required:
        assert token in text


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_mode_rejects_coercion_and_preserves_explicit_custom_task(scenario_id):
    scenario_class = get_scenario_class(scenario_id)
    for invalid in (None, 0, 1, "false", "true", "fasle", [], {}):
        with pytest.raises(ValueError, match="detailed_briefing must be a JSON boolean"):
            scenario_class(detailed_briefing=invalid)
    custom = "自定义任务：只检查当前田块状态，等待用户后续安排。"
    for mode in (False, True):
        scene = new_scene(scenario_id, detailed_briefing=mode, scenario_input=custom)
        assert scene.scenario_input == custom
        assert briefing_event(scene).kwargs["content"] == custom
        assert Engine(None, scene)._resolve_agent_task() == custom


VOLATILE_ID_FIELDS = {"op_id", "action_id", "mission_id", "inspection_id"}
UUID_PATTERN = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                          r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


def comparable(value):
    """Ignore nondeterministic identifiers only; keep every business value."""
    if isinstance(value, dict):
        return {key: comparable(item) for key, item in value.items()
                if key not in VOLATILE_ID_FIELDS}
    if isinstance(value, (list, tuple)):
        return [comparable(item) for item in value]
    if isinstance(value, str):
        return UUID_PATTERN.sub("<uuid>", value)
    return value


def complete_state(scene, engine):
    # World get_state includes native crop/soil/management/biotic states,
    # pending actions, observation RNG and weather RNG/cache. Device states
    # include all logs, batteries and stock. App RNGs are checked separately.
    return comparable(deepcopy({
        "clock": engine.time_manager.time(),
        "timezone": str(scene.farm_environment.simulation_timezone),
        "farm_ids": list(scene.farm_environment.farms),
        "apps": {app.name: {"class": type(app).__name__, "state": app.get_state(),
                            "random_state": app.rng.getstate()}
                 for app in scene.apps},
    }))


def comparable_workflow(workflow):
    result = deepcopy(workflow.to_dict())
    for step in result.values():
        if step["tool_name"] == "AgentUserInterface__send_message_to_agent":
            # Event-based Oracles include the selected briefing; handwritten
            # Oracles omit it. Preserve this step's identity/time/dependencies.
            assert step["name"] == "briefing"
            step["tool_args"] = {"content": "<selected briefing>"}
            step["content"] = "<selected briefing>"
    return comparable(result)


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_detail_modes_have_identical_tools_initial_world_and_real_oracle_outcome(scenario_id):
    basic = new_scene(scenario_id, detailed_briefing=False)
    detailed = new_scene(scenario_id, detailed_briefing=True)
    engines = [Engine(None, scene) for scene in (basic, detailed)]
    schemas = [build_toolset(scene.apps)[1] for scene in (basic, detailed)]
    assert schemas[0] == schemas[1]
    initial = [complete_state(scene, engine)
               for scene, engine in zip((basic, detailed), engines)]
    assert initial[0] == initial[1]

    exported = [comparable_workflow(engine.run_scenario_oracle(False))
                for engine in engines]
    assert exported[0] == exported[1]
    for scene, engine, original in zip((basic, detailed), engines, initial):
        assert complete_state(scene, engine) == original

    executed = [comparable_workflow(engine.run_scenario_oracle(True))
                for engine in engines]
    assert executed[0] == executed[1]
    assert complete_state(basic, engines[0]) == complete_state(detailed, engines[1])
    evaluations = [engine.evaluate().to_dict() for engine in engines]
    assert comparable(evaluations[0]) == comparable(evaluations[1])
    assert evaluations[0]["success"], evaluations[0]["message"]
