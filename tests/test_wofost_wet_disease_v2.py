"""Scene 02: locate disease before spending a finite chemical budget."""
import ast
from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from fairy.apps.farm_world import FarmWorldApp
from fairy.controllers.engine import Engine
from fairy.scenarios.wofost_events import scenario_events_snapshot
from fairy.scenarios.wofost_farm import WofostFarmScenario
from fairy.scenarios.wofost import scenario_full_season_heinong84_low_chemical_wet_disease_V2 as case

ROOT = Path(__file__).resolve().parents[1]
LEGACY_HASH = '7c9e7073c84fba606bd002ecf0ce89d309d07b42dfdb82c6f3428341ae6899b8'


@pytest.fixture(scope='module')
def built():
    scene = case.ScenarioFullSeasonHeinong84LowChemicalWetDisease_V2()
    scene.setup()
    engine = Engine(None, scene)
    farm = scene.get_typed_app(FarmWorldApp)
    before = deepcopy((farm.get_state(), farm.physics.crop_backend.export_state(), engine.time_manager.time()))
    workflow = engine.build_oracle_workflow(run_oracle=False)
    assert before == (farm.get_state(), farm.physics.crop_backend.export_state(), engine.time_manager.time())
    return scene, farm, workflow


def test_new_world_owns_plan_and_preserves_legacy(built):
    from fairy.scenarios.registry import get_scenario_class
    scene, _, _ = built
    old = ROOT / 'fairy/scenarios/farm_world_fullseason_v2' / Path(case.__file__).name.replace('_V2.py', '.py')
    assert hashlib.sha256(old.read_bytes()).hexdigest() == LEGACY_HASH
    assert get_scenario_class(case.SCENARIO_ID) is type(scene)
    assert not issubclass(get_scenario_class(case.LEGACY_SCENARIO_ID), WofostFarmScenario)
    tree = ast.parse(inspect.getsource(case))
    assert not any(isinstance(n, ast.ImportFrom) and (n.module or '').split('.')[-1].startswith('scenario_') for n in ast.walk(tree))
    plan = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'build_events_flow')
    assert not any(isinstance(n, (ast.If, ast.While, ast.ListComp, ast.DictComp)) for n in ast.walk(plan))
    assert all(isinstance(n.iter, ast.Name) and n.iter.id == 'captured' for n in ast.walk(plan) if isinstance(n, ast.For))
    assert '22–43' not in scene.DETAILED_BRIEFING  # The agent must locate the disease, not receive its answer.


def test_official_inputs_and_shared_once_only_world_events(built):
    scene, farm, _ = built
    assert (scene.WORLD.reference_id, scene.WORLD.seed_type) == ('lille', 'SOYBEAN_901')
    assert farm.field_area_m2 == 18867.2
    assert scene.reference['parameter_overrides'] == {} and scene.reference['native_parameter_count'] == 78
    assert scene.reference['weather_sha256'] == 'b0322825ef8140d714a9724b3933f18954d51541877459d3f9dd48cf7c80a675'
    events = scenario_events_snapshot(farm)['events']
    pressure, = [r for r in events if r['type'] == 'pressure']
    assert (pressure['kind'], pressure['ridge_start'], pressure['ridge_end'], pressure['repeat'], pressure['mode']) == ('disease', 22, 43, 'once', 'set')
    assert pressure['start'] == '2019-06-20' and pressure['value'] == .65
    windows = {r['event_id']: r for r in events if r['type'] == 'weather_window'}
    assert windows['wet_june_spell']['rain_mm'] == 8
    assert windows['wet_june_spell']['start'] == '2019-06-18' and windows['wet_june_spell']['end'] == '2019-07-03'
    assert not farm.physics.crop_backend._runs


def test_diagnosis_covers_disease_and_boundaries_before_targeted_spray(built):
    scene, _, workflow = built
    work = list(workflow.dag.values())
    day = [r for r in work if '2019-07-04' in r.name]
    methods = [r.tool_name for r in day]
    assert methods.index('SensorApp__read_canopy_sensors') < methods.index('SurveyDrone__fly_survey') < methods.index('Robot0__inspect_crop_health') < methods.index('TractorApp__apply_fungicide')
    visits = [r for r in day if r.tool_name.endswith('__inspect_crop_health')]
    assert Counter(rid for r in visits for rid in range(r.tool_args['start_ridge'], r.tool_args['end_ridge']+1)) == Counter(range(18, 46))
    assert all(r.tool_args['end_ridge']-r.tool_args['start_ridge']+1 <= 8 for r in visits)
    # A one-hour recharge separates the second and third 8-ridge missions.
    left, right = day.index(visits[1]), day.index(visits[2])
    assert any(r.tool_name == 'SystemApp__advance_time' and r.tool_args['hours'] == 1 for r in day[left+1:right])
    sprays = [r for r in day if r.tool_name.endswith('__apply_fungicide')]
    assert [(r.tool_args['start_ridge'], r.tool_args['end_ridge'], r.tool_args['liters_per_ridge']) for r in sprays] == [(22,31,3.8),(32,41,3.8),(42,43,3.8)]
    assert sum((r.tool_args['end_ridge']-r.tool_args['start_ridge']+1)*r.tool_args['liters_per_ridge'] for r in sprays) == pytest.approx(83.6)
    assert scene.WORLD.active_ingredient_cap_kg == .084 and scene.WORLD.warehouse_pesticide_l == 84
    assert scene.WORLD.max_fungicide_applications == 3
    irrigation = [r for r in work if r.tool_name.endswith('__irrigate')]
    assert len(irrigation) == 1 and '2019-08-08' in irrigation[0].name
    assert not any(r.tool_name.endswith(('__apply_fungicide', '__fly_survey')) for r in work if '2019-06-28' in r.name)


def assert_counterfactuals(arms):
    """Audit full-season receipts, native dry matter, spatial effects and budgets."""
    good, none, uniform = (arms[k] for k in ('correct', 'none', 'uniform'))
    for arm in arms.values():
        assert arm['world'] == good['world']
        assert arm['events']['events'] == good['events']['events']
        assert arm['events']['weather_changes'] == good['events']['weather_changes']
        assert arm['validation']['success'] is True
        assert arm['resources']['irrigation_used_mm_total'] == 30
        assert arm['resources']['fertilizer_used_kg'] == 0
        for rid, native in arm['native'].items():
            assert native['specification'] == good['native'][rid]['specification']
            assert native['water_mm'] == 30 and native['fertilizer_kg'] == 0
            assert native['pcse']['DVS'] == 2
            if not 22 <= int(rid) <= 43:
                assert native['pcse']['TWSO'] == good['native'][rid]['pcse']['TWSO']
        stored, harvested = [], []
        for row in arm['workflow'].values():
            content = row['content']
            assert not content.get('error') and content.get('status') not in ('partial', 'failed', 'error')
            if row['tool_name'].endswith(('__inspect_crop_health','__inspect_emergence')):
                requested = set(range(row['tool_args']['start_ridge'],row['tool_args']['end_ridge']+1))
                assert set(content['covered_ridges']) == requested
                assert set(map(int,content['observations'])) == requested
                assert content['battery_remaining_pct'] >= 10
            if row['tool_name'].endswith('__store_grain'):
                stored.extend(content['batch_ridge_ids'])
                assert content['storage_grain_moisture_pct'] <= 13.5
            if row['tool_name'].endswith('__harvest'):
                harvested.extend(content['harvested_ridges'])
        assert Counter(stored) == Counter(harvested) == Counter(range(64))
    def target(arm):
        return sum(arm['native'][str(rid)]['pcse']['TWSO'] for rid in range(22,44))/22
    assert target(good) > target(uniform) > target(none)
    assert good['warehouse_grain_kg'] > uniform['warehouse_grain_kg'] > none['warehouse_grain_kg']
    assert good['resources']['active_ingredient_used_kg'] == uniform['resources']['active_ingredient_used_kg'] == pytest.approx(.0836)
    assert none['resources']['active_ingredient_used_kg'] == 0
    for arm in (good, uniform):
        assert arm['resources']['fungicide_applications_used'] == 1
        assert arm['resources']['last_fungicide_application_day'] == '2019-07-04'
    # Same active quantity and date: uniform spraying trades away useful target dose and costs extra passes.
    for arm, expected_scope in [(good, range(22,44)), (uniform, range(64))]:
        scope = [rid for r in arm['workflow'].values() if r['tool_name'].endswith('__apply_fungicide')
                 for rid in range(r['tool_args']['start_ridge'], r['tool_args']['end_ridge']+1)]
        assert Counter(scope) == Counter(expected_scope)
    assert uniform['tractor']['fuel_tank_l'] < good['tractor']['fuel_tank_l']
    diagnosis = [r for r in good['workflow'].values() if r['tool_name'].endswith('__inspect_crop_health') and '检查' in r['name'] and '含病区' in r['name']]
    assert diagnosis
    initial_visits = [r for r in good['workflow'].values()
        if r['tool_name'].endswith('__inspect_crop_health') and r['name'].split('_',1)[1].startswith(('检查18','检查26','检查34','检查42'))]
    observations = {int(rid):obs for row in initial_visits for rid,obs in row['content']['observations'].items()}
    assert set(observations) == set(range(18,46))
    target_hits = [rid for rid,o in observations.items() if 22 <= rid <= 43 and o['disease_present'] and o['disease_confidence'] >= .6]
    reference_hits = [rid for rid,o in observations.items() if not 22 <= rid <= 43 and o['disease_present'] and o['disease_confidence'] >= .6]
    assert len(target_hits) >= 16 and not reference_hits
    return {'passed': True,
        'commodity_gain_over_no_fungicide_pct': 100*(good['warehouse_grain_kg']/none['warehouse_grain_kg']-1),
        'commodity_gain_over_uniform_pct': 100*(good['warehouse_grain_kg']/uniform['warehouse_grain_kg']-1),
        'target_native_gain_over_no_fungicide_pct': 100*(target(good)/target(none)-1)}
