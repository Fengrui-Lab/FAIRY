"""Failed operation/restore requests must not install partial farm state."""
from copy import deepcopy

import pytest

from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.tractor_app import TractorApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.scenarios.maize.scenario_single_farm_maize_full_season import ScenarioSingleFarmMaizeFullSeason
from fairy.time_manager import SimulationTimeManager


def growing_maize():
    scenario = ScenarioSingleFarmMaizeFullSeason()
    scenario.init_and_populate_apps()
    for name, arguments in (
        ("attach_implement", {"implement": "grader"}),
        ("level", {}), ("load_fertilizer", {"kg": 200}), ("base_fertilize", {}),
        ("detach_implement", {}), ("attach_implement", {"implement": "furrower"}),
        ("form_ridges", {"ridge_width_m": .65}),
        ("detach_implement", {}), ("attach_implement", {"implement": "maize_planter"}),
        ("load_seeds", {"seed_type": "MAIZE_EARLY_2026", "count": 4288}),
        ("plant_seeds", {"start_ridge": 0, "end_ridge": 3, "depth_cm": 5, "seed_spacing_cm": 25}),
    ):
        result = getattr(scenario.tractor, name)(**arguments)
        assert "error" not in result, (name, result)
    return scenario


def test_insufficient_seed_preflight_does_not_lazily_install_a_physics_bundle():
    world, weather = FarmWorldApp(), WeatherApp()
    tractor = TractorApp(world, weather)
    clock = SimulationTimeManager()
    clock.reset(1778800000)
    for app in (world, weather, tractor):
        app.register_time_manager(clock)
    for name, arguments in (
        ("attach_implement", {"implement": "grader"}), ("level", {}),
        ("load_fertilizer", {"kg": 200}), ("base_fertilize", {}),
        ("form_ridges", {"ridge_width_m": 1.1}),
        ("load_seeds", {"seed_type": "EARLY_COLD", "count": 1}),
    ):
        result = getattr(tractor, name)(**arguments)
        assert "error" not in result, (name, result)
    before = deepcopy(world.get_state())
    device_before = deepcopy(tractor.get_state())
    now = clock.time()
    assert before["physics_state"] is None
    result = tractor.plant_seeds(0, 0, 4, 5)
    assert "Insufficient" in result["error"]
    assert world.get_state() == before
    assert tractor.get_state() == device_before
    assert clock.time() == now


def test_invalid_prep_snapshot_cannot_change_unbound_farm_identity():
    world = FarmWorldApp()
    before = deepcopy(world.get_state())
    corrupted = deepcopy(before)
    corrupted["farm_id"] = "different_id"
    corrupted["completed_prep_ops"] = None
    with pytest.raises((TypeError, ValueError)):
        world.load_state(corrupted)
    assert world.get_state() == before


def test_established_modern_crop_requires_physics_before_snapshot_install():
    scenario = growing_maize()
    world = scenario.farm_world
    before = deepcopy(world.get_state())
    corrupted = deepcopy(before)
    corrupted["physics_state"] = None
    with pytest.raises(ValueError, match="physics|physical|established|growing"):
        world.load_state(corrupted)
    assert world.get_state() == before
    assert world.get_ridge_state(0)["planted"] is True


def test_legacy_initial_establishment_is_preserved_by_native_planting_event():
    world, weather = FarmWorldApp(), WeatherApp()
    world._ridges[0].stand_fraction = 0.84  # A scenario's initial establishment condition.
    tractor = TractorApp(world, weather)
    clock = SimulationTimeManager()
    clock.reset(1778800000)
    for app in (world, weather, tractor):
        app.register_time_manager(clock)
    for name, arguments in (
        ('attach_implement', {'implement': 'grader'}), ('level', {}),
        ('load_fertilizer', {'kg': 200}), ('base_fertilize', {}),
        ('form_ridges', {'ridge_width_m': 1.1}),
        ('load_seeds', {'seed_type': 'EARLY_COLD', 'count': 100000}),
        ('plant_seeds', {'start_ridge': 0, 'end_ridge': 0, 'depth_cm': 4, 'seed_spacing_cm': 5}),
    ):
        result = getattr(tractor, name)(**arguments)
        assert 'error' not in result, (name, result)
    assert world.physics.management.states[0].stand_fraction == 0.84
