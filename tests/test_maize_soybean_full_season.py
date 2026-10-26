"""Mixed-crop public tools, complete harvest provenance and fresh replay."""
from copy import deepcopy
from collections import Counter

import pytest

from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.two_farm.scenario_two_farm_maize_soybean_full_season import (
    SCENARIO_ID, ScenarioTwoFarmMaizeSoybeanFullSeason,
)
from fairy.scenarios.workflow import Workflow


def create_scene():
    scene = ScenarioTwoFarmMaizeSoybeanFullSeason()
    scene.setup()
    return scene, Engine(None, scene)


def season_state(scene):
    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()
                    if key not in {'action_id', 'op_id', 'mission_id', 'inspection_id'}}
        if isinstance(value, (tuple, list)):
            return [clean(item) for item in value]
        return value
    return deepcopy(clean({
        'time': scene.farm_environment.time_manager.time(),
        'maize': scene.maize.get_state(), 'soybean': scene.soybean.get_state(),
        'warehouse': scene.warehouse.get_state(), 'tractor': scene.tractor.get_state(),
        'maize_sensor': scene.maize_sensor.get_state(),
        'soybean_sensor': scene.soybean_sensor.get_state(),
    }))


def test_mixed_scene_exposes_two_real_crops_and_one_shared_fleet():
    scene, engine = create_scene()
    assert get_scenario_class(SCENARIO_ID) is ScenarioTwoFarmMaizeSoybeanFullSeason
    assert set(scene.farm_environment.farms) == {'maize_field', 'soybean_field'}
    assert all(app.time_manager is engine.time_manager for app in scene.apps)
    assert len({app.name for app in scene.apps}) == len(scene.apps)
    assert scene.maize.physics is not scene.soybean.physics
    assert scene.maize.physics.profile is not scene.soybean.physics.profile
    assert scene.maize.shared_warehouse is scene.soybean.shared_warehouse is scene.warehouse
    assert scene.maize.field_geometry.planted_area_m2 == pytest.approx(11148.8)
    assert scene.soybean.field_geometry.planted_area_m2 == pytest.approx(18867.2)
    assert scene.maize_irrigation.bound_farm_id == 'maize_field'
    assert scene.soybean_irrigation.bound_farm_id == 'soybean_field'
    assert len(scene.shared_equipment) == 3


def test_export_is_pure_and_contains_the_entire_independent_workflow():
    scene, engine = create_scene()
    before = season_state(scene)
    workflow = engine.run_scenario_oracle(False)
    assert season_state(scene) == before
    assert len(workflow) == len(scene.events) - 1
    assert all(step.content['oracle_reason'] for step in workflow.dag.values())
    for event, step in zip(scene.events[1:], workflow.dag.values()):
        assert event.event_id == step.name
        assert f'{event.app.name}__{event.function.__name__}' == step.tool_name
        assert event.kwargs == step.tool_args
    assert sum(step.tool_name == 'Tractor__harvest' for step in workflow.dag.values()) == 32
    assert sum(step.tool_name == 'Warehouse__store_grain' for step in workflow.dag.values()) == 32


@pytest.fixture(scope='module')
def completed():
    scene, engine = create_scene()
    engine.run_scenario_oracle(True)
    return scene, engine


def test_both_crops_finish_with_separate_provenance_and_correct_accounts(completed):
    scene, engine = completed
    result = engine.evaluate()
    assert result.success, result.message
    farms = result.metadata['farms']
    assert farms['maize_field']['harvested_ridges'] == farms['soybean_field']['harvested_ridges'] == 64
    assert farms['maize_field']['seed_used'] == 68608
    assert farms['soybean_field']['seed_used'] == 428800
    assert farms['maize_field']['water_used_mm'] == 20
    assert farms['soybean_field']['water_used_mm'] == 0
    assert farms['maize_field']['market_moisture_pct'] == 14
    assert farms['soybean_field']['market_moisture_pct'] == 13
    assert result.metadata['fertilizer_used_kg'] == 2 * 200 + 64 * (6 + 2)
    assert scene.warehouse.stock.pesticide_liters == 20
    for farm_id, farm in (('maize_field', scene.maize), ('soybean_field', scene.soybean)):
        batches = [b for b in scene.warehouse.grain_batches.values() if b.origin_farm_id == farm_id]
        assert len(batches) == 16
        assert Counter(rid for b in batches for rid in b.ridge_ids) == Counter(range(64))
        assert all(b.crop_id == farm.crop_id and b.status == 'stored' and b.quantity_kg > 0 for b in batches)
        harvest_kg = sum(op['grain_kg_added'] for op in scene.tractor.get_state()['operation_log']
                         if op['operation'] == 'harvest' and op['farm_id'] == farm_id)
        assert sum(b.quantity_kg for b in batches) == pytest.approx(harvest_kg)
        assert all(state.harvested for state in farm.physics.yield_recovery.states.values())
        assert farm.physics.last_physics_sim_time == engine.time_manager.time()
    assert all(not step.error_stage and 'error' not in step.content
               and step.content.get('status') != 'partial' for step in scene.workflow.dag.values())
    assert not any(step.tool_name == 'Maize_Irrigation__irrigate' for name, step in scene.workflow.dag.items()
                   if name.startswith('grain_fill'))


def test_complete_reference_replays_to_same_world_warehouse_and_clock(tmp_path, completed):
    original, _ = completed
    empty, exporter = create_scene()
    path = tmp_path / 'maize_soybean.json'
    exporter.run_scenario_oracle(False).save_workflow(str(path))
    fresh, replay = create_scene()
    replay.replay_workflow(Workflow.load_workflow(str(path)))
    assert replay.evaluate().success
    assert season_state(fresh) == season_state(original)
    assert not empty.warehouse.grain_batches


def test_captured_events_execute_the_same_complete_mixed_season(completed):
    original, _ = completed
    fresh, engine = create_scene()
    engine._run_captured_oracle_events(True)
    assert engine.evaluate().success
    assert season_state(fresh) == season_state(original)


@pytest.mark.parametrize('farm_id', ['maize_field', 'soybean_field'])
def test_one_successful_crop_cannot_hide_the_other_missing_harvest(completed, farm_id):
    scene, _ = completed
    # Alter only one batch's admission status. Shared total kg remains positive,
    # so acceptance must depend on each crop's stored batch coverage.
    batch = next(b for b in scene.warehouse.grain_batches.values() if b.origin_farm_id == farm_id)
    previous_status = batch.status
    try:
        batch.status = 'pending'
        result = scene.validate()
        assert not result.success
        assert farm_id in result.message
    finally:
        batch.status = previous_status


@pytest.mark.parametrize('omission', ['maize_topdress', 'soybean_topdress', 'maize_water'])
def test_missing_management_reduces_its_crop_without_changing_the_other_clock(completed, omission):
    normal, _ = completed
    scene, engine = create_scene()
    original_actions = scene._reference_actions()
    actions = []
    for name, app, method, arguments, reason in original_actions:
        omitted = (
            (omission == 'maize_topdress' and method == 'apply_fertilizer' and arguments['farm_id'] == 'maize_field')
            or (omission == 'soybean_topdress' and method == 'apply_fertilizer' and arguments['farm_id'] == 'soybean_field')
            or (omission == 'maize_water' and app is scene.maize_irrigation and method == 'irrigate')
        )
        if omitted:
            actual = normal.workflow.dag[name]
            duration = int(actual.time_after - actual.time_before)
            assert duration > 0
            actions.append((name, scene.system, 'advance_time', {'seconds': duration},
                            'Equal-duration control; omit the material or water input only.'))
        else:
            actions.append((name, app, method, arguments, reason))
    scene._reference_actions = lambda: actions
    engine.run_scenario_oracle(True)
    result = engine.evaluate()
    assert not result.success
    affected = 'soybean_field' if omission == 'soybean_topdress' else 'maize_field'
    other = 'maize_field' if affected == 'soybean_field' else 'soybean_field'
    assert affected in result.message
    normal_totals = normal.validate().metadata['farms']
    assert result.metadata['farms'][affected]['stored_grain_kg'] < normal_totals[affected]['stored_grain_kg']
    assert result.metadata['farms'][other]['stored_grain_kg'] == normal_totals[other]['stored_grain_kg']
    assert engine.time_manager.time() == normal.farm_environment.time_manager.time()
