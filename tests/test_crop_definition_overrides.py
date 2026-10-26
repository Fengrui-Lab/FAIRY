"""Scenario-authored operation rules retain identity and survive full snapshots."""
from copy import deepcopy
from dataclasses import replace
import json
from zoneinfo import ZoneInfo

import pytest

from fairy.apps.farm_world.farm_world_app import FarmWorldApp


def test_scenario_crop_rule_override_survives_json_snapshot_without_creating_equipment():
    original = FarmWorldApp(crop_id="soybean", cultivar_id="HEINONG84")
    original.simulation_timezone = ZoneInfo("Asia/Shanghai")
    original.crop_definition = replace(
        original.crop_definition,
        planting_rules=replace(original.crop_definition.planting_rules,
                               required_implement="soybean_planter"),
        harvest_rules=replace(original.crop_definition.harvest_rules,
                              required_implement="harvester"),
    )
    saved = json.loads(json.dumps(original.get_state(), allow_nan=False))
    restored = FarmWorldApp(crop_id="soybean", cultivar_id="HEINONG84")
    restored.simulation_timezone = ZoneInfo("Asia/Shanghai")
    restored.load_state(saved)
    assert restored.crop_definition == original.crop_definition
    assert restored.get_crop_capabilities()["planting"]["required_implement"] == "soybean_planter"
    assert restored.get_crop_capabilities()["harvest"]["required_implement"] == "harvester"
    assert restored.get_state() == saved
    assert restored._physics is None  # Rules do not initialize growth or create a device.


def test_crop_rule_override_rejects_identity_changes_atomically():
    world = FarmWorldApp(crop_id="maize")
    before = deepcopy(world.get_state())
    with pytest.raises(ValueError, match="species|cultivar"):
        world.crop_definition = replace(world.crop_definition, crop_id="soybean")
    assert world.get_state() == before
