"""Farm identity, heterogeneous area, and compatible FOS yield attribution."""
from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from fairy.apps.farm_world import FarmWorldApp
from fairy.scenarios.fos import evaluation
from fairy.scenarios.fos.multi_farm import extrapolate_fleet, fleet_provenance, fleet_yields
from fairy.scenarios.fos.provenance import validate_baseline_provenance


def fleet(width=3):
    farms = []
    for name, area_width, bio in [("a", 1, 1000), ("b", width, 2000)]:
        farm = FarmWorldApp(farm_id=name, num_ridges=1, field_length_m=100, ridge_width_m=area_width)
        farm.configure_physics_profile("harbin_baseline_2026_seed_101")
        state = farm.physics.yield_recovery.states[0]
        state.biological_yield_g_m2 = bio
        state.recovered_yield_g_m2_at_market_moisture = bio * .9
        state.harvested = state.r8_reached = True
        farm.physics.phenology.states[0].planted = True
        farms.append(farm)
    return SimpleNamespace(apps=farms, scenario_id="test_fleet", start_time=0)


def test_same_local_ridge_ids_keep_distinct_farms_and_correct_areas():
    scene = fleet()
    data = fleet_yields(scene)
    assert set(data["farms"]) == {"a", "b"}
    assert data["farms"]["a"]["ridges"]["0"]["biological_yield_kg"] == 100
    assert data["farms"]["b"]["ridges"]["0"]["biological_yield_kg"] == 600
    assert data["biological_yield_kg_total"] == 700
    assert data["recovered_yield_kg_total"] == 630


def test_multi_farm_outcome_totals_match_baseline_and_do_not_mutate_world():
    scene = fleet()
    before = deepcopy([f.get_state() for f in scene.apps])
    env = SimpleNamespace(event_log=SimpleNamespace(list_view=lambda: []))
    _, outcome = evaluation._compute_outcome(scene, env, .5, oracle_biological_kg=1000)
    assert outcome.agent_biological_kg == 700
    assert outcome.yield_preserved_ratio == .7
    assert outcome.agent_recovered_yield_kg == 630
    assert set(outcome.to_dict()["farms"]) == {"a", "b"}
    assert [f.get_state() for f in scene.apps] == before
    # Above-oracle yield stays visible through the untruncated ratio/CSV.
    _, higher = evaluation._compute_outcome(scene, env, .5, oracle_biological_kg=350)
    assert higher.yield_preserved_ratio == 2


def test_fleet_fingerprint_checks_farm_geometry_and_does_not_follow_crop_state():
    scene = fleet()
    provenance = fleet_provenance(scene)
    scene.apps[0].physics.yield_recovery.states[0].biological_yield_g_m2 = 500
    assert fleet_provenance(scene) == provenance
    validate_baseline_provenance({"crop_backend_provenance": provenance}, provenance, "cache")
    with pytest.raises(ValueError, match="provenance mismatch"):
        validate_baseline_provenance({"crop_backend_provenance": provenance}, fleet_provenance(fleet(2)), "cache")
    with pytest.raises(ValueError, match="provenance mismatch"):
        validate_baseline_provenance({"crop_backend_provenance": {"backend": "legacy"}}, provenance, "cache")


def test_baseline_load_round_trip_and_ambiguous_focus_rejected(tmp_path):
    from scripts.build_oracle_baselines import BaselineResult, _baseline_to_dict

    scene = fleet()
    yields = fleet_yields(scene)
    data = _baseline_to_dict(BaselineResult(
        scenario_id=scene.scenario_id, biological_yield_g_m2_per_ridge=[],
        biological_yield_kg_total=yields["biological_yield_kg_total"],
        recovered_yield_g_m2_per_ridge=[], recovered_yield_kg_total=yields["recovered_yield_kg_total"],
        ridges_planted=2, ridges_r8=2, ridges_harvested=2, extrapolation={}, duration_s=0,
        crop_backend_provenance=fleet_provenance(scene), farms=yields["farms"],
    ))
    assert data["schema_version"] == 4
    assert data["ridges_total"] == data["ridges_mature"] == 2
    assert "ridge_area_m2" not in data
    assert "biological_yield_g_m2_per_ridge" not in data
    (tmp_path / "test_fleet.json").write_text(json.dumps(data))
    assert evaluation._load_oracle_baseline_biological_kg("test_fleet", tmp_path, provenance=fleet_provenance(scene)) == 700
    env = SimpleNamespace(event_log=SimpleNamespace(list_view=lambda: []))
    with pytest.raises(ValueError, match="farm-qualified"):
        evaluation._compute_outcome(scene, env, .5, focus_ridge_ids=[0])


def test_shared_clock_waits_for_both_soybean_and_native_maize():
    scene = fleet()
    soybean = scene.apps[0].physics.yield_recovery.states[0]
    soybean.r8_reached = False
    maize = SimpleNamespace(**{k: v for k, v in vars(scene.apps[1].physics.yield_recovery.states[0]).items()
                               if k != "r8_reached"}, r6_reached=False)
    scene.apps[1].physics.yield_recovery.states[0] = maize
    calls = []

    def advance_time(days):
        calls.append(days)
        soybean.r8_reached = True
        maize.r6_reached = len(calls) >= 3
        return {"status": "ok"}

    scene.get_typed_app = lambda _: SimpleNamespace(advance_time=advance_time)
    capped = extrapolate_fleet(scene, 2)
    assert capped["days_ticked"] == 2
    assert capped["reached_maturity"] is False
    done = extrapolate_fleet(scene, 2)
    assert done["days_ticked"] == 1
    assert done["reached_maturity"] is True
    assert all(done["farms"].values())
    assert fleet_yields(scene)["farms"]["b"]["ridges"]["0"]["mature"] is True


def test_shared_clock_reports_failed_time_advance():
    scene = fleet()
    scene.apps[0].physics.yield_recovery.states[0].r8_reached = False
    scene.get_typed_app = lambda _: SimpleNamespace(advance_time=lambda **_: {"error": "calendar unavailable"})
    status = extrapolate_fleet(scene, 180)
    assert status["status"] == "error"
    assert status["reached_maturity"] is False
    assert status["days_ticked"] == 0
