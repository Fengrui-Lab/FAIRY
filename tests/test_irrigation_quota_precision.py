"""Split legal water applications must conserve the same seasonal allowance."""
from copy import deepcopy
import math

import pytest

from fairy.apps.farm_world import FarmWorldApp


def test_splitting_a_seasonal_allowance_does_not_accumulate_rounding_debt():
    world = FarmWorldApp()
    world._management_regime.irrigation_quota_mm_total = 320.
    # One field-equivalent pulse across 22 of 64 ridges; a non-terminating
    # decimal representative of partial-field irrigation in a 64-ridge world.
    pulse = 20. * 22 / 64 / 3
    applications = [pulse] * 100
    applications.append(320. - math.fsum(applications))
    for amount in applications:
        assert world.check_irrigation_quota(amount) is None
        world.record_irrigation_use(amount)
    assert world._management_regime.irrigation_used_mm_total == pytest.approx(320., abs=1e-10)
    assert world.check_irrigation_quota(.000001) is not None


@pytest.mark.parametrize("amount", [1e-7, 1e-10, 1e-12])
def test_sub_micro_field_mm_is_recorded_instead_of_becoming_free(amount):
    world = FarmWorldApp()
    for _ in range(10):
        world.record_irrigation_use(amount)
    assert world._management_regime.irrigation_used_mm_total == pytest.approx(10 * amount, rel=1e-12, abs=0.)


def test_accounting_precision_survives_public_state_snapshot_round_trip():
    world = FarmWorldApp()
    world._management_regime.irrigation_quota_mm_total = 320.
    world.record_irrigation_use(318.51190476190476)
    snapshot = deepcopy(world.get_state())
    restored = FarmWorldApp()
    restored.load_state(snapshot)
    remainder = 320. - 318.51190476190476
    assert restored.check_irrigation_quota(remainder) is None
    restored.record_irrigation_use(remainder)
    assert restored._management_regime.irrigation_used_mm_total == 320.
