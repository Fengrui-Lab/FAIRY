"""Public information, takeover conservation and independent performance checks."""

import ast
import inspect
import json
from datetime import date

import pytest

from fairy.scenarios.management_extensions.evaluation.sugarbeet import performance_indices
from fairy.scenarios.management_extensions.sugarbeet.yield_oracles import YieldController, yield_policy_grid


def metrics(root=100, wheat=40, margin=-100):
    return dict(root_yield=root, wheat_yield=wheat, net_operating_margin=margin)


def test_performance_is_separate_from_completion_and_can_exceed_reference():
    baseline = metrics()
    lower = performance_indices(metrics(root=80), baseline, "root_yield", True)
    assert lower["objective_score"] == 0.8
    assert lower["root_shortfall_pct"] == pytest.approx(20)
    higher = performance_indices(metrics(root=110), baseline, "root_yield", True)
    assert higher["objective_score"] == 1.1
    assert performance_indices(metrics(), baseline, "root_yield", False)["objective_score"] is None
    assert performance_indices(metrics(), None, "root_yield", True)["status"] == "reference_unavailable"


@pytest.mark.parametrize("reference, actual, expected", [(-100, -50, 1.5), (0, 5, 6), (100, 50, 0.5)])
def test_margin_improvement_has_consistent_direction(reference, actual, expected):
    result = performance_indices(metrics(margin=actual), metrics(margin=reference), "net_operating_margin", True)
    assert result["objective_score"] == expected


def test_rotation_reports_ordered_scores_without_adding_crop_masses():
    result = performance_indices(metrics(root=90, wheat=80, margin=-50), metrics(), "rotation_yield", True)
    assert result["objective_score"] == [0.9, 2.0, 1.5]


def test_yield_grids_are_distinct_complete_declared_choices():
    for variant, size in (("seedling_rescue", 12), ("soil_water_priority", 40), ("shared_resources", 16)):
        grid = yield_policy_grid(variant)
        assert len(grid) == len({p.candidate_id for p in grid}) == size
    assert all(p.beet_n_kg_ha + p.wheat_n_kg_ha == 300 for p in yield_policy_grid("shared_resources"))


def test_yield_controller_only_uses_public_information():
    tree = ast.parse(inspect.getsource(YieldController))
    forbidden = {"backends", "model", "native", "_ridges", "set_variable", "_send_signal", "harvest_now", "queue"}
    assert not {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} & forbidden


@pytest.fixture(scope="module")
def rescue():
    from fairy.scenarios.management_extensions.L3.scenario_sugarbeet_seedling_rescue import ScenarioSugarBeetSeedlingRescue
    scene = ScenarioSugarBeetSeedlingRescue(calibrating=True)
    scene.setup()
    return scene


def test_takeover_is_public_history_with_consumed_stock_and_elapsed_clock(rescue):
    field = rescue.farm.get_field_info()
    blocks = rescue.farm.inspect_blocks(0, 15)["blocks"]
    assert all(b["planted"] and b["sowing_date"] for b in blocks)
    assert all(b["applied_n_kg_ha"] == pytest.approx(72) for b in blocks)
    assert all(b["irrigation_mm_this_cycle"] == 0 for b in blocks)
    assert min(b["relative_available_water"] for b in blocks) < 0.45
    assert date.fromisoformat(field["date"]) > date.fromisoformat(blocks[0]["sowing_date"])
    account = rescue.accounts.get_accounts()
    assert account["fertilizer_product_kg"] == pytest.approx(72 / 0.46)
    assert account["production_cost"] > 0
    assert account["shared_water_remaining_m3"] == rescue.resources.water_stock_m3
    assert field["mission_context"]["public_tool_history"]
    before = rescue.input_fingerprint()
    rescue.setup()
    assert rescue.input_fingerprint() == before


def test_takeover_setup_is_deterministic_and_native_checkpoint_continues(rescue):
    other = type(rescue)(calibrating=True)
    other.setup()
    assert other.input_fingerprint() == rescue.input_fingerprint()
    assert other.farm.get_state() == rescue.farm.get_state()
    backend = other.farm.backends[0]
    restored = type(backend).restore(backend.bundle, json.loads(json.dumps(backend.export_state())))
    backend.advance_day()
    restored.advance_day()
    assert restored.export_state() == backend.export_state()


def test_zonal_soil_is_public_and_survives_checkpoint():
    from fairy.scenarios.management_extensions.L3.scenario_sugarbeet_soil_water_priority import ScenarioSugarBeetSoilWaterPriority
    scene = ScenarioSugarBeetSoilWaterPriority(calibrating=True)
    scene.setup()
    info = scene.farm.get_field_info()
    assert info["blocks"][0]["soil_water_reference"]["rootable_depth_cm"] == 60
    assert info["blocks"][8]["soil_water_reference"]["rootable_depth_cm"] == 120
    ids = [b.bundle.identity for b in scene.farm.backends]
    assert len(set(ids)) == 2
    saved = json.loads(json.dumps(scene.farm.get_state()))
    scene.farm.load_state(saved)
    assert [b.bundle.identity for b in scene.farm.backends] == ids
    assert scene.farm.get_state() == saved
    assert scene.resources.water_stock_m3 == 1000
    from fairy.scenarios.management_extensions.sugarbeet.oracle import PublicController, Policy
    controller = PublicController(scene)
    sowed = controller.sow_cycle(info, Policy())
    from datetime import timedelta
    controller.until(sowed + timedelta(days=40))
    scene.farm.get_field_info()
    assert scene.farm.backends[0].values["SM"] != scene.farm.backends[8].values["SM"]
    for i in (0, 8):
        backend = scene.farm.backends[i]
        restored = type(backend).restore(backend.bundle, json.loads(json.dumps(backend.export_state())))
        backend.advance_day()
        restored.advance_day()
        assert restored.export_state() == backend.export_state()


def test_l4_combined_stocks_bind_before_both_season_caps():
    from fairy.scenarios.management_extensions.L4.scenario_wheat_sugarbeet_shared_resources import ScenarioWheatSugarBeetSharedResources
    scene = ScenarioWheatSugarBeetSharedResources(calibrating=True)
    scene.setup()
    info = scene.farm.get_field_info()
    assert scene.resources.fertilizer_stock_kg * scene.resources.fertilizer_n_fraction == pytest.approx(300)
    assert sum(c["maximum_n_kg_ha"] for c in info["cycles"]) > 300
    assert scene.resources.water_stock_m3 == 4200
    assert info["management_objective"]["minimum_wheat_dry_kg_ha"] == 6500
    assert info["cycle"]["minimum_dry_yield_kg_ha"] == 6500
    assert info["cycles"][0]["minimum_dry_yield_kg_ha"] == 6500
