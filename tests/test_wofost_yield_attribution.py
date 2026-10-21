from __future__ import annotations

from types import SimpleNamespace

import pytest

from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
from fairy.apps.farm_world.farm_world_app import DEFAULT_RIDGE_WIDTH_M, FIELD_LENGTH_M
from fairy.scenarios.fos.evaluation import (
    _compute_outcome,
    _compute_recovered_yield_floor_kg,
)


RIDGE_AREA_M2 = FIELD_LENGTH_M * DEFAULT_RIDGE_WIDTH_M


def _harvested_scenario(*, dry_matter: bool, recovery_fraction: float = 0.95):
    physics = FarmPhysicsState(num_ridges=1)
    physics.engines_active = True
    physics.yield_recovery.params.biological_yield_is_dry_matter = dry_matter
    physics.phenology.states[0].planted = True
    state = physics.yield_recovery.states[0]
    state.r8_reached = True
    state.harvested = True
    state.biological_yield_g_m2 = 87.0
    # 87 g dry matter corresponds to 100 g grain at 13% market moisture.
    state.recovered_yield_g_m2_at_market_moisture = (
        100.0 if dry_matter else 87.0
    ) * recovery_fraction
    farm_world = SimpleNamespace(_physics=physics)
    scenario = SimpleNamespace(get_typed_app=lambda _: farm_world)
    return scenario, physics


@pytest.mark.parametrize("dry_matter", [False, True])
def test_recovery_ratio_uses_one_mass_basis_and_preserves_biological_attribution(dry_matter):
    scenario, _ = _harvested_scenario(dry_matter=dry_matter)
    biological_kg = 87.0 * RIDGE_AREA_M2 / 1000.0

    _, breakdown = _compute_outcome(
        scenario,
        env=None,
        crop_loss_threshold=0.5,
        oracle_biological_kg=2.0 * biological_kg,
        donothing_biological_kg=0.5 * biological_kg,
    )

    assert breakdown.yield_ratio == pytest.approx(0.95)
    assert breakdown.harvest_loss_count == 0
    assert breakdown.agent_biological_kg == pytest.approx(biological_kg)
    assert breakdown.scenario_potential_kg == pytest.approx(biological_kg)
    assert breakdown.yield_preserved_ratio == pytest.approx(0.5)
    assert breakdown.crop_loss_pct == pytest.approx(0.5)
    assert breakdown.normalized_yield_score == pytest.approx(1.0 / 3.0)


@pytest.mark.parametrize("dry_matter", [False, True])
@pytest.mark.parametrize("recovery_fraction, expected_losses", [(0.49, 1), (0.51, 0)])
def test_harvest_loss_threshold_compares_recovered_and_potential_on_same_basis(
    dry_matter, recovery_fraction, expected_losses
):
    scenario, _ = _harvested_scenario(
        dry_matter=dry_matter, recovery_fraction=recovery_fraction
    )

    _, breakdown = _compute_outcome(scenario, env=None, crop_loss_threshold=0.5)

    assert breakdown.harvest_loss_count == expected_losses
    assert breakdown.yield_ratio == pytest.approx(recovery_fraction)


@pytest.mark.parametrize("dry_matter, expected_floor_g_m2", [(False, 152.25), (True, 175.0)])
def test_recovered_floor_converts_only_unharvested_biological_pool(
    dry_matter, expected_floor_g_m2
):
    _, physics = _harvested_scenario(dry_matter=dry_matter)
    unharvested = FarmPhysicsState(num_ridges=2)
    physics.phenology.states[1] = unharvested.phenology.states[1]
    physics.yield_recovery.states[1] = unharvested.yield_recovery.states[1]
    physics.phenology.states[1].planted = True
    state = physics.yield_recovery.states[1]
    state.r8_reached = True
    state.biological_yield_g_m2 = 87.0
    state.field_loss_fraction = 0.2

    # No farm object is supplied: this isolates the mass accounting from the
    # separate October-30 replay policy.
    actual = _compute_recovered_yield_floor_kg(None, physics, RIDGE_AREA_M2)

    assert actual == pytest.approx(expected_floor_g_m2 * RIDGE_AREA_M2 / 1000.0)


def test_unharvested_mature_ridge_stays_in_recovery_ratio_denominator():
    scenario, physics = _harvested_scenario(dry_matter=True)
    second = FarmPhysicsState(num_ridges=2)
    physics.phenology.states[1] = second.phenology.states[1]
    physics.yield_recovery.states[1] = second.yield_recovery.states[1]
    physics.phenology.states[1].planted = True
    physics.yield_recovery.states[1].biological_yield_g_m2 = 87.0
    physics.yield_recovery.states[1].r8_reached = True

    _, breakdown = _compute_outcome(scenario, env=None, crop_loss_threshold=0.5)

    assert breakdown.yield_ratio == pytest.approx(0.95 / 2.0)
    assert breakdown.unharvested_mature_count == 1
    assert breakdown.agent_biological_kg == pytest.approx(174.0 * RIDGE_AREA_M2 / 1000.0)
