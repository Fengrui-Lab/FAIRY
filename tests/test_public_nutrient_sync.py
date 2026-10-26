"""A committed application cannot leave agent-visible nutrition at setup values."""
from datetime import datetime, timezone

import pytest

from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.time_manager import SimulationTimeManager


def test_same_timestamp_fertilizer_commit_updates_public_nutrition_once():
    farm = FarmWorldApp(num_ridges=1)
    clock = SimulationTimeManager()
    clock.reset(datetime(2026, 5, 12, tzinfo=timezone.utc).timestamp())
    farm.register_time_manager(clock)
    farm._ridges[0].nutrient_index = .76
    farm.physics.engines_active = True
    farm.advance_physics_time()
    before = farm.get_ridge_state(0)["nutrient_index"]
    assert before == .76
    result = farm.apply_fertigation(0, 0, .24, 0)
    assert result["status"] == "ok"
    actual = farm.physics.management.states[0].nutrient_index
    assert actual > before
    assert farm.get_ridge_state(0)["nutrient_index"] == pytest.approx(actual, abs=.001)
    farm.advance_physics_time()
    assert farm.physics.management.states[0].nutrient_index == actual
