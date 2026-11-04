"""The scouting case preserves block input identity and the observation boundary."""

import json

from fairy.agents.agent.toolset_builder import build_toolset
from fairy.scenarios.registry import get_scenario_class


SCENARIO_ID = "scenario_l3_winter_wheat_block_scouting"


def test_block_scouting_observation_tools_and_heterogeneous_checkpoint():
    scenario = get_scenario_class(SCENARIO_ID)
    source = scenario()
    source.setup()
    _, _, tools = build_toolset(source.apps)
    assert {
        "Sensor__read_root_zone_sensors",
        "Sensor__read_canopy_sensors",
        "Drone__survey_blocks",
        "Robot__inspect_blocks",
    } <= tools.keys()
    rows = tools["WheatField__inspect_blocks"](start_block=5, end_block=7)["blocks"]
    assert [row["block_id"] for row in rows] == [5, 6, 7]
    assert all({"NAVAIL", "SM", "LAI", "TWSO"}.isdisjoint(row) for row in rows)

    source.system.advance_time(days=1)
    saved = json.loads(json.dumps(source.farm.get_state()))
    assert (
        saved["native"][5]["input_fingerprint"]
        != saved["native"][6]["input_fingerprint"]
    )
    assert (
        source.farm.backends[6].values["NAVAIL"]
        < source.farm.backends[5].values["NAVAIL"]
    )
    restored = scenario()
    restored.setup()
    restored.farm_environment.time_manager.reset(
        source.farm_environment.time_manager.time()
    )
    restored.farm.load_state(saved)
    assert restored.farm.get_state() == saved
