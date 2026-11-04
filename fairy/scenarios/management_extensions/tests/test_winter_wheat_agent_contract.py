"""Both briefings and the real model-visible block tool schemas."""

import inspect
import re
import pytest
from fairy.agents.agent.toolset_builder import build_toolset
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.tool_utils import _argument_descriptions
from fairy.scenarios.management_extensions.winter_wheat_oracles import SCENARIO_IDS


@pytest.mark.parametrize(
    "sid", (*SCENARIO_IDS, "scenario_l3_winter_wheat_block_scouting")
)
def test_task_modes_query_prices_and_observation_without_oracle_doses(sid):
    scenes = []
    for detailed in (False, True):
        s = get_scenario_class(sid)(detailed_briefing=detailed)
        s.setup()
        engine = Engine(None, s)
        task = engine._resolve_agent_task()
        assert task == s.scenario_input == s.additional_system_prompt
        assert {float(n) for n in re.findall(r"\d+(?:\.\d+)?", task)} == {10000.0}
        if detailed:
            assert all(
                phase in task for phase in ("秋播", "越冬", "开花", "灌浆", "成熟")
            )
            assert "根区" in task and "价格" in task
        else:
            assert (
                "OperatingAccounts.get_accounts" in task
                and "WheatField.get_field_info" in task
            )
        before = s.farm.get_state()
        workflow = engine.build_oracle_workflow(run_oracle=False)
        assert s.farm.get_state() == before
        assert len(workflow) == s.ORACLE_REFERENCE["workflow_steps"]
        tools, schemas, _ = build_toolset(s.apps)
        if detailed:
            assert all(tool.name not in task for tool in tools)
        names = {f"{t.app_name}__{t.name}" for t in tools}
        assert {
            "Tractor__load_seeds",
            "Tractor__load_fertilizer",
            "Tractor__sow",
            "Tractor__fertilize",
            "Tractor__harvest_blocks",
            "Warehouse__dry_grain",
            "Warehouse__store_grain",
            "SystemApp__advance_time",
        } <= names
        assert "Tractor__form_ridges" not in names and not any(
            n.startswith("WinterWheat__") for n in names
        )
        schemas = {s["function"]["name"]: s["function"] for s in schemas}
        for tool in tools:
            if tool.name not in {
                "sow",
                "fertilize",
                "harvest_blocks",
                "prepare_field",
                "get_field_info",
                "inspect_blocks",
                "irrigate",
            }:
                continue
            schema = schemas[f"{tool.app_name}__{tool.name}"]
            assert "Returns:" in schema["description"]
            args = set(inspect.signature(tool.function).parameters) - {"self"}
            assert set(_argument_descriptions(tool.function)) == args
            assert set(schema["parameters"]["properties"]) == args
        scenes.append(s.farm.get_state())
    assert scenes[0] == scenes[1]


@pytest.mark.parametrize("value", ["false", 0, None])
def test_invalid_briefing_boolean(value):
    with pytest.raises(ValueError, match="JSON boolean"):
        get_scenario_class(SCENARIO_IDS[0])(detailed_briefing=value)
