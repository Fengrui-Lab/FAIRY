from datetime import datetime, timezone

import pytest

from fairy.apps.farm_world.assets import AssetSpec
from fairy.apps.farm_world.multi_farm import FarmFleet, FarmSite
from fairy.agents.agent.toolset_builder import build_toolset
from fairy.controllers.engine import Engine
from fairy.scenarios.scenario import Scenario


def _site():
    return FarmSite.create("north", "North", create_devices=False,
                           num_ridges=2, field_length_m=80)


def test_engine_discovers_restored_clock_from_services_without_resetting_it():
    fleet = FarmFleet([_site()], shared_tools=True,
                      assets=[AssetSpec("drone", "drone", ("north",))])
    start = datetime(2026, 5, 12, tzinfo=timezone.utc).timestamp()
    engine = Engine(None, Scenario(apps=fleet.apps, start_time=start))
    engine.time_manager.add_offset(3600)
    restored = fleet.runtime.load_snapshot(fleet.runtime.snapshot())
    offset = restored.clock.offset
    checkpoint_start = restored.clock.start_time
    resumed = Engine(None, Scenario(apps=restored.apps, start_time=0))
    assert resumed.time_manager is restored.clock
    assert resumed.time_manager.start_time == checkpoint_start
    assert resumed.time_manager.offset == offset
    assert len(resumed.runtime_participants) == 1
    resumed.time_manager.add_offset(60)
    assert restored.clock.offset == offset + 60


def test_capability_directory_reports_all_compatible_seeds_and_effective_harvest_limit():
    fleet = FarmFleet([_site()], shared_tools=True,
                      assets=[AssetSpec("tractor", "tractor", ("north",),
                                        parameters={"harvest_moisture_limit_pct": 12})])
    world = next(app for app in fleet.apps if app.name == "World")
    result = world.get_capabilities(farm_id="north", asset_id="tractor")
    assert result["ok"]
    compatible = result["data"]["planting"]["compatible_seed_types"]
    assert {"STANDARD", "EARLY_COLD", "HEINONG60"} <= set(compatible)
    assert "MAIZE_STANDARD" not in compatible
    assert result["data"]["harvest"]["max_grain_moisture_pct"] == 12


def test_initial_payload_crop_must_match_declared_origin_farm():
    with pytest.raises(ValueError, match="Initial seed payload"):
        FarmFleet([_site()], shared_tools=True,
                  assets=[AssetSpec("tractor", "tractor", ("north",), initial_state={
                      "seed_type": "MAIZE_STANDARD", "seed_hopper": 10,
                      "payload_origin_farm_id": "north"})])


def test_shared_model_descriptions_match_canonical_parameters_and_variable_layout():
    fleet = FarmFleet([_site()], shared_tools=True,
                      assets=[AssetSpec("tractor", "tractor", ("north",))])
    _, schemas, _ = build_toolset(fleet.apps)
    descriptions = {item["function"]["name"]: item["function"]["description"] for item in schemas}
    manual = descriptions["FieldOps__apply_pesticide_manual"]
    assert "start_ridge" in manual and "end_ridge" in manual
    assert "advance_time" not in manual and "ridge_count" not in manual
    replant = descriptions["Tractor__replant_seeds"]
    assert "seed_spacing_cm:" in replant and "3-5 cm" not in replant
    seed_schema = next(item["function"]["parameters"] for item in schemas
                       if item["function"]["name"] == "Tractor__load_seeds")
    assert "MAIZE_STANDARD" in seed_schema["properties"]["seed_type"]["enum"]
    assert "World capabilities" in descriptions["Tractor__plant_seeds"]
    assert "crop-specific" in descriptions["Tractor__plant_seeds"]
    assert "global" in descriptions["Sensor__read_soil_sensor"].lower()
    assert "six fixed" not in descriptions["Sensor__read_soil_sensors"]
