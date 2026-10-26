"""Registered maize tasks exercise native growth through the public farm tools."""
from __future__ import annotations

import ast
import copy
import inspect
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("pcse")

from fairy.apps.farm_world import FarmWorldApp, TractorApp
from fairy.controllers.engine import Engine
from fairy.physics.wofost_backend import WofostBackend
from fairy.scenarios.maize.maize_scenario_catalog import SPECS, TASK_SPECS
from fairy.scenarios.registry import get_scenario_class, list_scenarios
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.workflow import Workflow, WorkflowStep
from fairy.types import CapturedEvent


IDS = tuple(spec.scenario_id for spec in SPECS.values())


def physical_farm_state(farm):
    state = farm.get_state()
    # Complete farm snapshots now include the physical action journal. A new
    # invocation has a different UUID; retain every action field except that ID.
    for action in (state.get("physics_state") or {}).get("action_log", []):
        action.pop("action_id", None)
    return state


def _engine(scenario_id):
    scenario = get_scenario_class(scenario_id)()
    scenario.setup()
    engine = Engine(None, scenario)
    # Runtime clocks include elapsed wall time; scientific comparisons freeze
    # that incidental component and retain every explicit operation duration.
    engine.time_manager.real_time_passed = lambda: 0.0
    return scenario, engine


@pytest.fixture(scope="module")
def completed():
    runs = {}
    for scenario_id in IDS:
        scenario, engine = _engine(scenario_id)
        workflow = engine.run_scenario_oracle()
        runs[scenario_id] = scenario, engine, workflow
    return runs


def test_three_independent_scenario_modules_use_the_common_event_runtime():
    assert {sid for sid in list_scenarios() if sid.startswith("scenario_maize_")} == set(IDS) | set(TASK_SPECS)
    for scenario_id in IDS:
        cls = get_scenario_class(scenario_id)
        path = Path(inspect.getfile(cls))
        assert path.name == f"scenario_full_season_maize_{cls.spec.variant}.py"
        classes = [node for node in ast.parse(path.read_text()).body if isinstance(node, ast.ClassDef)]
        assert [node.name for node in classes] == [cls.__name__]
        assert cls.oracle_solution is Scenario.oracle_solution
        assert {"init_and_populate_apps", "build_events_flow"} <= cls.__dict__.keys()
        assert not (path.parent / "oracle_plans").exists()
        assert all(p.name == "scenario_artifacts.json" or "checkpoints" in p.parts
                   for p in path.parent.rglob("*.json"))


@pytest.mark.parametrize("scenario_id", IDS)
def test_setup_records_events_without_running_native_growth(scenario_id, monkeypatch):
    def reject_execution(*args, **kwargs):
        pytest.fail("Scenario construction must not execute the Oracle or integrate the crop")

    monkeypatch.setattr(WofostBackend, "advance_day", reject_execution)
    monkeypatch.setattr(CapturedEvent, "execute", reject_execution)
    scenario, engine = _engine(scenario_id)
    farm = scenario.get_typed_app(FarmWorldApp)
    assert farm.crop_name == "maize" and farm.rows_per_ridge == 1
    assert farm.ridge_width_m == 0.75
    assert all(not ridge.planted for ridge in farm._ridges)
    assert farm.physics.crop_backend.snapshot()["ridges"] == {}
    assert not scenario.validate().success
    before = copy.deepcopy(farm.get_state())
    workflow = engine.build_oracle_workflow(run_oracle=False)
    assert farm.get_state() == before
    assert len(workflow) == len(scenario.events)
    seen = set()
    for event in scenario.events:
        assert isinstance(event, CapturedEvent)
        assert event.event_id and event.event_id not in seen
        assert all(dependency.event_id in seen for dependency in event.dependencies)
        seen.add(event.event_id)
    assert "o_form_single_row_ridges" in seen
    assert "o_maize_dry_grain" in seen


def test_maize_scenarios_reject_soybean_backend_or_identity():
    cls = get_scenario_class(IDS[0])
    with pytest.raises(ValueError, match="WOFOST"):
        cls(crop_backend="legacy")
    with pytest.raises(ValueError, match="Grain_maize_201"):
        cls(crop_backend_options={"crop_name": "soybean"})
    with pytest.raises(ValueError, match="biotic"):
        cls(crop_backend_options={"external_biotic_coupling": True})


@pytest.mark.parametrize("scenario_id", IDS)
def test_full_season_oracles_mature_harvest_and_safely_store_all_64_ridges(scenario_id, completed):
    scenario, engine, workflow = completed[scenario_id]
    result = engine.evaluate(workflow)
    assert result.success, result.to_dict()
    farm = scenario.get_typed_app(FarmWorldApp)
    tractor = scenario.get_typed_app(TractorApp)
    assert len(farm.physics.crop_backend._runs) == 64
    assert all(run.pcse["DOM"] and run.pcse["DVS"] == 2.0 for run in farm.physics.crop_backend._runs.values())
    assert all(ridge.harvested for ridge in farm._ridges)
    assert all(run.specification["density_plants_m2"] * 268.0 * 0.75 == pytest.approx(1340)
               for run in farm.physics.crop_backend._runs.values())
    assert farm._inventory.seed_stock["MAIZE_201"] == 100000 - 64 * 1340
    assert tractor._seed_hopper == tractor._grain_bin_kg == 0
    assert farm._inventory.harvest_grain_kg == 0
    assert farm._inventory.warehouse_grain_kg > 0
    for state in farm.physics.yield_recovery.states.values():
        assert state.harvest_date >= state.maturity_date
        assert state.grain_moisture_frac <= 0.14 + 1e-9
        assert not state.drying_required
    assert not farm.physics.pending_management_actions_by_ridge
    assert not farm.physics.crop_backend._pending
    assert result.metadata["crop_config_fingerprint"]


@pytest.mark.parametrize("scenario_id", IDS)
def test_public_tool_workflow_replay_reproduces_crop_inventory_and_resource_state(scenario_id, completed):
    original, _, workflow = completed[scenario_id]
    replay, engine = _engine(scenario_id)
    engine.replay_workflow(workflow)
    expected = original.get_typed_app(FarmWorldApp)
    actual = replay.get_typed_app(FarmWorldApp)
    assert physical_farm_state(actual) == physical_farm_state(expected)
    assert actual.physics.crop_backend.export_state() == expected.physics.crop_backend.export_state()
    assert actual.physics.yield_recovery.get_state() == expected.physics.yield_recovery.get_state()
    assert replay.get_typed_app(TractorApp).get_status() == original.get_typed_app(TractorApp).get_status()
    assert engine.evaluate().success


@pytest.mark.parametrize("variant,tool", [
    ("water_limit", "FieldOpsApp__irrigate"),
    ("nitrogen_limit", "FarmWorldApp__apply_fertigation"),
])
def test_irrigation_and_topdressing_improve_yield_in_matched_controls(variant, tool, completed):
    scenario_id = f"scenario_maize_l3_{variant}"
    _, _, workflow = completed[scenario_id]
    managed_prefix, control_prefix = Workflow(), Workflow()
    first_harvest = None
    ablated_calls = 0
    for step in workflow.dag.values():
        if step.tool_name == "TractorApp__harvest":
            first_harvest = step
            break
        managed_prefix.add_node(replace(step, depends_on=list(step.depends_on)))
        if step.tool_name == tool:
            ablated_calls += 1
            assert step.time_before is not None and step.time_after is not None
            seconds = step.time_after - step.time_before
            assert seconds >= 0
            if variant == "nitrogen_limit":
                # This contrast removes N only, not carrier-water irrigation.
                assert step.tool_args["water_mm"] == 0
            if seconds > 0:
                # Preserve the exact recorded operation duration. Rounded
                # public minutes would move subsequent inputs across dates.
                step = replace(step, tool_name="SystemApp__advance_time",
                               tool_args={"seconds": seconds}, content=None)
            else:
                step = replace(step, tool_name="FarmWorldApp__get_inventory",
                               tool_args={}, content=None)
        control_prefix.add_node(replace(step, depends_on=list(step.depends_on)))
    assert first_harvest is not None and first_harvest.time_before is not None
    assert ablated_calls > 0

    # Both comparisons are fresh real-tool replays at the same pre-harvest
    # boundary. A drought control may have no recoverable grain; biological
    # sensitivity must not depend on replaying the managed unloading schedule.
    managed, managed_engine = _engine(scenario_id)
    ablated, control_engine = _engine(scenario_id)
    managed_engine.replay_workflow(managed_prefix)
    control_engine.replay_workflow(control_prefix)
    assert managed_engine.time_manager.time() == control_engine.time_manager.time() == first_harvest.time_before
    for scene in (managed, ablated):
        farm = scene.get_typed_app(FarmWorldApp)
        assert not any(ridge.harvested for ridge in farm._ridges)
        assert not any(state.harvested for state in farm.physics.yield_recovery.states.values())
    native_managed = managed.get_typed_app(FarmWorldApp).physics.crop_backend
    native_control = ablated.get_typed_app(FarmWorldApp).physics.crop_backend
    assert set(native_managed._runs) == set(native_control._runs) == set(range(64))
    # TWSO is kg dry matter/ha. These equally sized ridges give an area-weighted
    # field mean without mixing biological yield with warehouse moisture/losses.
    managed_yield = sum(run.pcse["TWSO"] for run in native_managed._runs.values()) / 64
    control_yield = sum(run.pcse["TWSO"] for run in native_control._runs.values()) / 64
    assert managed_yield > control_yield * 1.05
    # Check actual forcing and unchanged non-ablated inputs, not merely seed equality.
    for ridge_id, run in native_managed._runs.items():
        other = native_control._runs[ridge_id]
        assert run.specification == other.specification
        assert [(row["day"], row["weather"], row["humidity_pct"], row["external_growth_factor"], row["harvested"])
                for row in run.journal] == [
            (row["day"], row["weather"], row["humidity_pct"], row["external_growth_factor"], row["harvested"])
            for row in other.journal
        ]
        unchanged = ("fertilizer_kg", "n_kg_ha") if variant == "water_limit" else ("irrigation_mm",)
        for input_name in unchanged:
            assert [row["inputs"][input_name] for row in run.journal] == [
                row["inputs"][input_name] for row in other.journal
            ]
        removed = "irrigation_mm" if variant == "water_limit" else "n_kg_ha"
        assert sum(row["inputs"][removed] for row in run.journal) > sum(
            row["inputs"][removed] for row in other.journal
        )


@pytest.mark.parametrize("content,op_type", [
    ({"error": "failed tool"}, "WRITE"),
    ({"warning": "stored without drying"}, "WRITE"),
    ("RuntimeError: failed tool", "TOOL_ERROR"),
])
def test_evaluation_checks_external_agent_workflow(completed, content, op_type):
    scenario, engine, original_workflow = completed[IDS[0]]
    external_workflow = Workflow()
    external_workflow.add_node(WorkflowStep(name="agent_failure", op_type=op_type, content=content))
    scenario.workflow = Workflow()
    try:
        result = engine.evaluate(external_workflow)
        assert not result.success
        assert result.metadata["tool_errors"] == ["agent_failure"]
    finally:
        scenario.workflow = original_workflow


def test_validation_detects_duplicate_resource_accounting(completed):
    scenario, engine, workflow = completed[IDS[0]]
    farm = scenario.get_typed_app(FarmWorldApp)
    original = farm._inventory.fertilizer_kg
    farm._inventory.fertilizer_kg += 1.0
    try:
        result = engine.evaluate(workflow)
        assert not result.success
        assert "fertilizer inventory and native input accounting disagree" in result.metadata["failures"]
    finally:
        farm._inventory.fertilizer_kg = original
