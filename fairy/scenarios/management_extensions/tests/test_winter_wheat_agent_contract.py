"""Scene-local briefings and actual model-visible wheat tool schemas."""

import inspect
import re

import pytest

from fairy.agents.agent.toolset_builder import build_toolset
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.tool_utils import _argument_descriptions
from fairy.scenarios.management_extensions.winter_wheat_oracles import SCENARIO_IDS


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_both_briefing_modes_reach_agent_and_preserve_native_state(sid):
    states = []
    fingerprints = []
    for mode in (False, True):
        scene = get_scenario_class(sid)(detailed_briefing=mode)
        scene.setup()
        engine = Engine(None, scene)
        task = engine._resolve_agent_task()
        assert task == scene.scenario_input == scene.additional_system_prompt
        assert {float(n) for n in re.findall(r"\d+(?:\.\d+)?", task)} == {10000.0}
        assert ("WinterWheat.observe" in task) is mode
        assert (
            "WinterWheat.get_accounts" in task and "WinterWheat.get_field_info" in task
        )
        before = scene.world.get_state()
        plan = engine.build_oracle_workflow(run_oracle=False)
        assert scene.world.get_state() == before
        assert len(plan) == scene.ORACLE_REFERENCE["workflow_steps"]
        states.append(before)
        fingerprints.append(scene.input_fingerprint())
        tools, schemas, _ = build_toolset(scene.apps)
        schemas = {s["function"]["name"]: s["function"] for s in schemas}
        for tool in tools:
            if tool.app_name != "WinterWheat":
                continue
            schema = schemas[f"{tool.app_name}__{tool.name}"]
            assert "Returns:" in schema["description"]
            args = set(inspect.signature(tool.function).parameters) - {"self"}
            assert set(_argument_descriptions(tool.function)) == args
            assert set(schema["parameters"]["properties"]) == args
        assert scene.world.get_accounts()["prices"]["currency"] == "USD"
    assert states[0] == states[1] and fingerprints[0] == fingerprints[1]


@pytest.mark.parametrize("value", ["false", 0, None])
def test_invalid_briefing_flag_rejected(value):
    with pytest.raises(ValueError, match="JSON boolean"):
        get_scenario_class(SCENARIO_IDS[0])(detailed_briefing=value)
