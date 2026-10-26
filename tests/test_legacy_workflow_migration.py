from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from fairy.apps.farm_world.multi_farm import AssetSpec, FarmFleet, FarmSite
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
from fairy.scenarios.legacy_workflow_migration import LegacyAppBinding, migrate_legacy_workflow
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.workflow import Workflow, WorkflowStep
from fairy.tool_execution import ToolExecutionError, WorkflowBundle
from fairy.tool_utils import SchemaValidationError


def _target():
    sites = [FarmSite.create(fid, fid.title(), create_devices=False, num_ridges=3,
                            field_length_m=80, ridge_width_m=1.1)
             for fid in ("north", "south")]
    fleet = FarmFleet(sites, shared_tools=True, seed=10, assets=[
        AssetSpec("tractor_n", "tractor", ("north",)),
        AssetSpec("tractor_s", "tractor", ("south",)),
        AssetSpec("robot_n", "robot", ("north",)),
        AssetSpec("tractor_both", "tractor", ("north", "south")),
    ])
    for site in sites:
        site.weather.set_weather("2026-05-12", 25, 55, 2, 0, 400)
        for ridge in site.farm._ridges:
            ridge.soil_vwc = .26
    system = SystemApp()
    scenario = Scenario(apps=[*fleet.apps, system],
                        start_time=datetime(2026, 5, 12, 7, tzinfo=timezone.utc).timestamp())
    scenario.runtime_participants = [fleet.runtime]
    engine = Engine(None, scenario)
    return fleet.runtime, engine, system


def _workflow(*calls):
    result = Workflow()
    for index, (tool, arguments) in enumerate(calls):
        result.add_node(WorkflowStep(name=f"step{index}", tool_name=tool, tool_args=arguments,
                                     depends_on=[f"step{index-1}"] if index else [],
                                     content={"phase": "legacy", "nested": {"values": []}}))
    return result


def test_explicit_conversion_is_deep_copied_preflighted_and_replayable():
    runtime, engine, _ = _target()
    source = _workflow(
        ("OldNorthTractor__load_seeds", {"seed_type": "STANDARD", "count": 100}),
        ("OldSouthTractor__load_seeds", {"seed_type": "STANDARD", "count": 120}),
    )
    original = deepcopy(source.to_dict())
    inventories = {fid: site.farm._inventory.to_dict() for fid, site in runtime.farms.items()}
    assets = {aid: asset.snapshot() for aid, asset in runtime.assets.items()}
    offset = engine.time_manager.offset
    bundle = migrate_legacy_workflow(source, runtime, {
        "OldNorthTractor": LegacyAppBinding("Tractor", "north", "tractor_n"),
        "OldSouthTractor": {"service": "Tractor", "farm_id": "south", "asset_id": "tractor_s"},
    })
    assert source.to_dict() == original
    assert inventories == {fid: site.farm._inventory.to_dict() for fid, site in runtime.farms.items()}
    assert assets == {aid: asset.snapshot() for aid, asset in runtime.assets.items()}
    assert engine.time_manager.offset == offset and runtime.executor.history == []
    first, second = bundle.workflow.dag.values()
    assert first.tool_name == second.tool_name == "Tractor__load_seeds"
    assert first.tool_args == {"seed_type": "STANDARD", "count": 100,
                               "farm_id": "north", "asset_id": "tractor_n"}
    assert second.tool_args["asset_id"] == "tractor_s"
    assert bundle.manifest["catalog_version"] == runtime.registry.catalog_version
    assert bundle.manifest["migration"]["dynamic_success_verified"] is False
    first.content["nested"]["values"].append("new")
    assert source.to_dict() == original
    replayed = engine.replay_workflow(bundle)
    assert len(replayed) == 2
    assert runtime.assets["tractor_n"].data["_seed_hopper"] == 100
    assert runtime.assets["tractor_s"].data["_seed_hopper"] == 120


@pytest.mark.parametrize("binding,match", [
    (LegacyAppBinding("Tractor", "missing", "tractor_n"), "unknown farm"),
    (LegacyAppBinding("Tractor", "north", "missing"), "unknown asset"),
    (LegacyAppBinding("Tractor", "north", "robot_n"), "does not match"),
    (LegacyAppBinding("Tractor", "south", "tractor_n"), "cannot serve"),
    (LegacyAppBinding("Farm", "north", "tractor_n"), "must not contain"),
])
def test_unknown_or_mismatched_explicit_bindings_are_rejected(binding, match):
    runtime, _, _ = _target()
    source = _workflow(("OldApp__get_status", {}))
    with pytest.raises(ValueError, match=match):
        migrate_legacy_workflow(source, runtime, {"OldApp": binding})
    assert runtime.executor.history == []


def test_collapsing_legacy_device_instances_onto_one_asset_requires_new_oracle():
    runtime, _, _ = _target()
    source = _workflow(("OldNorthTractor__get_status", {}), ("OldSouthTractor__get_status", {}))
    with pytest.raises(ValueError, match="same asset.*rebuild"):
        migrate_legacy_workflow(source, runtime, {
            "OldNorthTractor": LegacyAppBinding("Tractor", "north", "tractor_both"),
            "OldSouthTractor": LegacyAppBinding("Tractor", "south", "tractor_both"),
        })


@pytest.mark.parametrize("prefix", ["World", "Farm", "Weather", "Sensor", "FieldOps", "Tractor", "Drone", "Robot"])
def test_converter_refuses_already_shared_names_even_with_legacy_steps(prefix):
    runtime, _, _ = _target()
    source = _workflow(("OldNorthFarm__get_inventory", {}), (f"{prefix}__get_status", {}))
    with pytest.raises(ValueError, match="already uses shared"):
        migrate_legacy_workflow(source, runtime, {"OldNorthFarm": LegacyAppBinding("Farm", "north")})
    assert runtime.executor.history == []


def test_unknown_prefix_method_and_injected_routing_arguments_are_rejected():
    runtime, _, _ = _target()
    binding = {"OldFarm": LegacyAppBinding("Farm", "north")}
    with pytest.raises(ValueError, match="unmapped"):
        migrate_legacy_workflow(_workflow(("UnknownFarm__get_inventory", {})), runtime, binding)
    with pytest.raises(ValueError, match="Unknown legacy public"):
        migrate_legacy_workflow(_workflow(("OldFarm__configure_management_regime", {})), runtime, binding)
    with pytest.raises(SchemaValidationError, match="unknown parameter"):
        migrate_legacy_workflow(_workflow(("OldFarm__get_inventory", {"farm_id": "south"})), runtime, binding)


def test_aliases_probe_ids_and_manual_spray_are_explicitly_translated():
    runtime, _, _ = _target()
    source = _workflow(
        ("OldFields__irrigate_ridge", {"ridge_id": 1, "duration_hours": 1.5}),
        ("OldSensor__read_soil_sensor", {"sensor_id": "S1"}),
        ("OldFields__apply_pesticide_manual", {"ridge_id": 0, "ridge_count": 2, "advance_time": True}),
    )
    bundle = migrate_legacy_workflow(source, runtime, {
        "OldFields": LegacyAppBinding("FieldOps", "north"),
        "OldSensor": LegacyAppBinding("Sensor", "north"),
    })
    first, probe, spray = bundle.workflow.dag.values()
    assert first.tool_name == "FieldOps__irrigate"
    assert first.tool_args == {"farm_id": "north", "start": 1, "end": 1, "hours": 1.5}
    assert probe.tool_args == {"sensor_id": "north:S1"}
    assert spray.tool_args["start_ridge"] == 0 and spray.tool_args["end_ridge"] == 1
    assert "advance_time" not in spray.tool_args and runtime.executor.history == []
    with pytest.raises(ValueError, match="advance_time=False"):
        migrate_legacy_workflow(
            _workflow(("OldFields__apply_pesticide_manual", {"ridge_id": 0, "advance_time": False})),
            runtime, {"OldFields": LegacyAppBinding("FieldOps", "north")},
        )


def test_geometry_changes_are_not_silently_reinterpreted_as_success():
    runtime, _, _ = _target()
    source = _workflow(("OldTractor__form_ridges", {"ridge_width_m": 1.5}))
    with pytest.raises(ToolExecutionError, match="declared"):
        migrate_legacy_workflow(source, runtime, {"OldTractor": LegacyAppBinding("Tractor", "north", "tractor_n")})
    assert runtime.executor.history == []


def test_platform_steps_require_explicit_instances_and_cannot_be_resigned_alone():
    runtime, _, system = _target()
    source = _workflow(("OldFarm__get_inventory", {}), ("SystemApp__advance_time", {"days": 1}))
    bindings = {"OldFarm": LegacyAppBinding("Farm", "north"), "SystemApp": LegacyAppBinding("SystemApp")}
    with pytest.raises(ValueError, match="instances must be supplied"):
        migrate_legacy_workflow(source, runtime, bindings)
    bundle = migrate_legacy_workflow(source, runtime, bindings, platform_apps=[system])
    assert bundle.workflow.dag["step1"].tool_name == "SystemApp__advance_time"
    assert source.dag["step1"].tool_args == {"days": 1}
    with pytest.raises(ValueError, match="platform-only"):
        migrate_legacy_workflow(_workflow(("SystemApp__advance_time", {"days": 1})), runtime,
                                {"SystemApp": LegacyAppBinding("SystemApp")}, platform_apps=[system])


def test_conversion_does_not_claim_dynamic_preconditions_or_configuration_equivalence():
    runtime, engine, _ = _target()
    # A correctly routed harvest is statically meaningful, but the fresh field
    # is unplanted. A manifest is not proof that this legacy plan can succeed.
    bundle = migrate_legacy_workflow(
        _workflow(("OldTractor__harvest", {"start_ridge": 0, "end_ridge": 0})), runtime,
        {"OldTractor": LegacyAppBinding("Tractor", "north", "tractor_n")},
    )
    assert bundle.manifest["migration"]["dynamic_success_verified"] is False
    with pytest.raises(ToolExecutionError):
        engine.replay_workflow(bundle)


def test_legacy_record_content_uses_portable_json_without_changing_source(tmp_path):
    runtime, _, _ = _target()
    source = _workflow(("OldFarm__get_inventory", {}))
    source.dag["step0"].content = {"phase": "legacy", "by_ridge": {0: .5}, "range": (0, 1)}
    bundle = migrate_legacy_workflow(source, runtime, {"OldFarm": LegacyAppBinding("Farm", "north")})
    assert source.dag["step0"].content["by_ridge"] == {0: .5}
    assert source.dag["step0"].content["range"] == (0, 1)
    assert bundle.workflow.dag["step0"].content["by_ridge"] == {"0": .5}
    path = tmp_path / "migrated.json"
    bundle.save(path)
    WorkflowBundle.load(path).validate(runtime.registry)


def test_metadata_only_content_is_portable_and_preserved_when_saved(tmp_path):
    runtime, _, _ = _target()
    source = Workflow()
    source.add_node(WorkflowStep(name="note", content={"by_ridge": {0: .5}, "range": (0, 1)}))
    source.add_node(WorkflowStep(name="inventory", tool_name="OldFarm__get_inventory",
                                 tool_args={}, depends_on=["note"]))
    original = deepcopy(source.to_dict())
    bundle = migrate_legacy_workflow(source, runtime, {"OldFarm": LegacyAppBinding("Farm", "north")})
    assert source.to_dict() == original
    assert bundle.workflow.dag["note"].content == {"by_ridge": {"0": .5}, "range": [0, 1]}
    path = tmp_path / "migrated-with-note.json"
    bundle.save(path)
    loaded = WorkflowBundle.load(path)
    loaded.validate(runtime.registry)
    assert loaded.workflow.dag["note"].content == bundle.workflow.dag["note"].content
    assert loaded.workflow.dag["inventory"].depends_on == ["note"]
