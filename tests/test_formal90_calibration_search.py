"""Counterfactuals must isolate an intervention and preserve the real clock."""
from copy import deepcopy

import pytest

from fairy.scenarios.workflow import Workflow, WorkflowStep
from scripts.calibrate_formal90_oracles import (
    choose_best, dose_totals, episodes, variant_workflow,
)


def plan():
    workflow = Workflow()
    for index, (name, tool, args) in enumerate([
        ("v001_o_mid_fungicide_0_16_23_spray_16_23", "TractorApp__apply_fungicide",
         {"start_ridge": 16, "end_ridge": 23, "liters_per_ridge": 3.8}),
        ("v002_o_r1_nutrition", "FarmWorldApp__apply_fertigation",
         {"start_ridge": 0, "end_ridge": 63, "nutrient_amount": 0.24, "water_mm": 2}),
        ("v003_read", "FarmWorldApp__get_farm_overview", {}),
    ]):
        workflow.add_node(WorkflowStep(name=name, tool_name=tool, tool_args=args,
                         time_before=1000 + index * 100, time_after=1020 + index * 100))
    return workflow


def test_omission_is_real_noop_and_preserves_absolute_execution_slots():
    original = plan()
    before = deepcopy(original.to_dict())
    name = next(iter(original.dag))
    revised = variant_workflow(original, {name: {"kind": "omit"}}, Workflow)
    assert original.to_dict() == before
    assert revised.dag[name].tool_name == "SystemApp__get_current_time"
    assert revised.dag[name].tool_args == {}
    for key in original.dag:
        assert revised.dag[key].time_before == original.dag[key].time_before
        assert revised.dag[key].time_after == original.dag[key].time_after
        if key != name:
            assert revised.dag[key].to_dict() == original.dag[key].to_dict()


def test_half_nutrition_holds_carrier_water_constant():
    original = plan()
    name = list(original.dag)[1]
    revised = variant_workflow(original, {name: {"kind": "half"}}, Workflow)
    assert revised.dag[name].tool_args["nutrient_amount"] == 0.12
    assert revised.dag[name].tool_args["water_mm"] == 2
    quantities = dose_totals(revised)
    assert quantities["fertilizer_product_kg"] == pytest.approx(230.4)
    assert quantities["carrier_water_ridge_mm"] == 128


def test_working_fluid_and_fertilizer_are_different_quantities():
    quantities = dose_totals(plan())
    assert quantities["chemical_working_fluid_l"] == pytest.approx(30.4)
    assert quantities["fertilizer_product_kg"] == pytest.approx(460.8)
    assert quantities["intervention_calls"] == 2


def test_manual_backpack_dose_counts_both_requested_ridges():
    workflow = Workflow()
    workflow.add_node(WorkflowStep(name="manual", tool_name="FieldOpsApp__apply_pesticide_manual",
                      tool_args={"ridge_id": 12, "ridge_count": 2, "liters_per_ridge": 3.0}))
    revised = variant_workflow(workflow, {"manual": {"kind": "half"}}, Workflow)
    assert revised.dag["manual"].tool_args["liters_per_ridge"] == 1.5
    assert dose_totals(revised)["chemical_working_fluid_l"] == 3.0


def test_multiple_passes_of_one_decision_are_one_episode():
    workflow = Workflow()
    for index, (start, end) in enumerate([(16, 25), (26, 35), (36, 39)]):
        workflow.add_node(WorkflowStep(name=f"v{index:05d}_o_r5_insecticide_0_16_39_insecticide_spray_{start}_{end}",
                         tool_name="TractorApp__spray_pesticide",
                         tool_args={"start_ridge": start, "end_ridge": end, "liters_per_ridge": 3.8}))
    groups = episodes(workflow)
    assert len(groups) == 1
    assert len(groups[0]["step_ids"]) == 3


def test_backpack_passes_of_one_treatment_decision_are_one_episode():
    workflow = Workflow()
    for index, start in enumerate((24, 26, 28)):
        workflow.add_node(WorkflowStep(name=f"v{index:05d}_o_r5_insecticide_0_24_47_manual_spray_{start}_{start+1}",
                         tool_name="FieldOpsApp__apply_pesticide_manual",
                         tool_args={"ridge_id": start, "ridge_count": 2,
                                    "liters_per_ridge": 3.2, "advance_time": True}))
    assert len(episodes(workflow)) == 1


def candidate(identity, mass, calls, *, complete=True, fluid=1, fertilizer=0):
    return {"id": identity, "metrics": {"operational_complete": complete,
            "safe_stored_kg": mass, "intervention_inputs": {
                "intervention_calls": calls, "chemical_working_fluid_l": fluid,
                "fertilizer_product_kg": fertilizer, "irrigation_ridge_mm": 0}}}


def test_incomplete_high_yield_cannot_win():
    bad = candidate("wet_grain", 10000, 0, complete=False)
    good = candidate("stored", 1000, 2)
    assert choose_best([bad, good]) is good


def test_resource_tie_break_does_not_override_material_yield_gain():
    low_input = candidate("low", 1000, 1)
    better = candidate("more_yield", 1001, 2)
    assert choose_best([low_input, better]) is better
    equivalent = candidate("equivalent", 1001.05, 3)
    assert choose_best([better, equivalent]) is better


def test_empty_feasible_set_is_explicit():
    assert choose_best([candidate("invalid", 1000, 1, complete=False)]) is None
