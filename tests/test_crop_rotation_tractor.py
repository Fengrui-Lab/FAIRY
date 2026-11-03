"""Static rotation catalogues do not bypass the live crop's loading rules."""

from fairy.scenarios.management_extensions.L4.scenario_soybean_predecessor_maize_nutrition import (
    ScenarioSoybeanPredecessorMaizeNutrition,
)
from fairy.types import EventRegisterer


def test_rotation_capture_accepts_future_crop_without_mutating_live_crop():
    scene = ScenarioSoybeanPredecessorMaizeNutrition(calibrating=True)
    scene.setup()
    farm = scene.cycle.farm
    tractor = scene.cycle.tractor
    before = farm.get_state(), tractor.get_state()
    with EventRegisterer.capture_mode() as events:
        tractor.load_seeds(seed_type="MAIZE_201", count=100)
    assert len(events) == 1
    assert (farm.get_state(), tractor.get_state()) == before
    rejected = tractor.load_seeds(seed_type="MAIZE_201", count=100)
    assert rejected.get("error")
    assert (farm.get_state(), tractor.get_state()) == before
