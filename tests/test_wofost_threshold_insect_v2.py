"""Scenario 01's public decisions, budget, independence, and result-only audit."""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import ast
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from fairy.apps.farm_world import FarmWorldApp, TractorApp
from fairy.controllers.engine import Engine
from fairy.scenarios.wofost_farm import WofostFarmScenario
from fairy.scenarios.wofost import scenario_full_season_heinong84_threshold_insect_limited_spray_V2 as case

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / 'fairy/scenarios/farm_world_fullseason_v2/scenario_full_season_heinong84_threshold_insect_limited_spray.py'
LEGACY_HASH = '49468f8b265cd84b58572036fc67bce2699f2ae714a3bb0c5d7afc01dc9b248a'


@pytest.fixture(scope='module')
def built():
    scene = case.ScenarioFullSeasonHeinong84ThresholdInsectLimitedSpray_V2()
    scene.setup()
    engine = Engine(None, scene)
    farm = scene.get_typed_app(FarmWorldApp)
    before = deepcopy((farm.get_state(), farm.physics.crop_backend.export_state(), engine.time_manager.time()))
    workflow = engine.build_oracle_workflow(run_oracle=False)
    assert before == (farm.get_state(), farm.physics.crop_backend.export_state(), engine.time_manager.time())
    return scene, farm, workflow


def test_legacy_preserved_and_new_scene_owns_entire_plan(built):
    from fairy.scenarios.registry import get_scenario_class
    scene, _, _ = built
    assert hashlib.sha256(OLD.read_bytes()).hexdigest() == LEGACY_HASH
    assert get_scenario_class(case.SCENARIO_ID) is type(scene)
    assert not issubclass(get_scenario_class(case.LEGACY_SCENARIO_ID), WofostFarmScenario)
    tree = ast.parse(inspect.getsource(case))
    assert not any(isinstance(n, ast.ImportFrom) and (n.module or '').split('.')[-1].startswith('scenario_') for n in ast.walk(tree))
    plan = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'build_events_flow')
    assert not any(isinstance(n, (ast.If, ast.While, ast.ListComp, ast.DictComp)) for n in ast.walk(plan))
    assert all(isinstance(n.iter, ast.Name) and n.iter.id == 'captured' for n in ast.walk(plan) if isinstance(n, ast.For))


def test_fixed_world_density_and_once_only_shared_events(built):
    scene, farm, _ = built
    world = scene.WORLD
    assert (world.num_ridges, farm.field_area_m2) == (64, 18867.2)
    assert (world.reference_id, world.seed_type) == ('lille', 'SOYBEAN_901')
    assert scene.reference['parameter_overrides'] == {} and scene.reference['native_parameter_count'] == 78
    assert scene.crop_backend_options['reference_density_plants_m2'] == 40
    assert world.planting_density_plants_m2 == 45
    from fairy.scenarios.wofost_events import scenario_events_snapshot
    events = scenario_events_snapshot(farm)['events']
    pressures = [e for e in events if e['type'] == 'pressure']
    assert [(e['start'], e['value']) for e in pressures] == [('2019-06-14', .08), ('2019-07-24', .65)]
    assert all((e['farm_id'], e['ridge_start'], e['ridge_end'], e['repeat']) == ('farm', 18, 37, 'once') for e in pressures)
    assert not farm.physics.crop_backend._runs  # Building must never sow or grow.


def test_finite_budget_single_round_and_actual_diagnostic_scope(built):
    scene, _, workflow = built
    work = list(workflow.dag.values())
    sprays = [r for r in work if r.tool_name.endswith('__spray_pesticide')]
    assert len(sprays) == 2
    assert [r.tool_args for r in sprays] == [
        {'start_ridge': 18, 'end_ridge': 27, 'liters_per_ridge': 8.},
        {'start_ridge': 28, 'end_ridge': 37, 'liters_per_ridge': 8.}]
    assert all('2019-07-25' in r.name for r in sprays)
    assert scene.WORLD.warehouse_pesticide_l == 160
    assert scene.WORLD.max_insecticide_applications == 1
    assert scene.WORLD.active_ingredient_cap_kg == .16
    for r in work:
        if r.tool_name.endswith(('__inspect_crop_health', '__inspect_emergence')):
            assert r.tool_args['end_ridge']-r.tool_args['start_ridge']+1 <= 8
    for day in ('2019-06-15', '2019-07-25'):
        segment = [r.tool_name for r in work if day in r.name]
        assert segment.index('SensorApp__read_canopy_sensors') < segment.index('SurveyDrone__fly_survey') < segment.index('Robot0__inspect_crop_health') < segment.index('Robot0__inspect_ridge')
    sow = [r for r in work if r.tool_name.endswith('__plant_seeds')]
    assert Counter(rid for r in sow for rid in range(r.tool_args['start_ridge'], r.tool_args['end_ridge']+1)) == Counter(range(64))
    assert all(r.tool_args['seed_spacing_cm'] == pytest.approx(200/(45*1.1)) for r in sow)


def assert_counterfactuals(arms):
    """Inspect saved full-season receipts; no physics or policy is executed here."""
    good, none, early = (arms[k] for k in ('correct', 'none', 'early'))
    area_ha = good['world']['field_length_m'] * good['world']['ridge_width_m'] / 10000
    for arm in arms.values():
        assert arm['world'] == good['world']
        assert arm['events']['events'] == good['events']['events']
        assert arm['events']['weather_changes'] == good['events']['weather_changes']
        assert arm['validation']['success'] is True
        assert arm['resources']['irrigation_used_mm_total'] == 60
        assert arm['resources']['fertilizer_used_kg'] == 0
        for rid, native in arm['native'].items():
            assert native['specification'] == good['native'][rid]['specification']
            assert native['water_mm'] == 60
            assert native['pcse']['DVS'] == 2
            if not 18 <= int(rid) <= 37:
                assert native['pcse']['TWSO'] == good['native'][rid]['pcse']['TWSO']
        stored, harvested = [], []
        for row in arm['workflow'].values():
            content = row['content']
            assert not content.get('error') and content.get('status') not in ('partial', 'failed', 'error')
            if row['tool_name'].endswith('__store_grain'):
                stored.extend(content['batch_ridge_ids'])
                assert content['storage_grain_moisture_pct'] <= 13.5
            if row['tool_name'].endswith('__harvest'):
                harvested.extend(content['harvested_ridges'])
        assert Counter(stored) == Counter(harvested) == Counter(range(64))
    def target(arm):
        return sum(arm['native'][str(rid)]['pcse']['TWSO']*area_ha for rid in range(18, 38))
    assert target(good) > target(none)*1.15
    assert good['warehouse_grain_kg'] > none['warehouse_grain_kg']*1.03
    assert good['warehouse_grain_kg'] > early['warehouse_grain_kg']*1.03
    assert abs(target(early)-target(none)) < target(none)*.01
    assert [arm['resources']['active_ingredient_used_kg'] for arm in (good, none, early)] == [.16, 0., .16]
    assert early['resources']['last_insecticide_application_day'] == '2019-06-15'
    assert good['resources']['last_insecticide_application_day'] == '2019-07-25'
    return {'passed': True, 'field_area_ha': area_ha*64,
        'commodity_gain_over_no_insecticide_pct': 100*(good['warehouse_grain_kg']/none['warehouse_grain_kg']-1),
        'target_native_gain_pct': 100*(target(good)/target(none)-1)}


def test_current_selected_queue_preserves_legacy_files_and_completed_prefix():
    manifest = json.loads((ROOT / 'configs/oracles/wofost_selected20_20261027.json').read_text())
    old = json.loads((ROOT / 'configs/oracles/wofost_scenario_versions.json').read_text())
    rows = manifest['cases']
    assert len(rows) == len({row['legacy_id'] for row in rows}) == 20
    assert not {row['legacy_id'] for row in rows} & {row['legacy_id'] for row in old['rows']}
    completed = [row for row in rows if row['status'] == 'calibrated']
    assert completed and completed == rows[:len(completed)]
    assert all(row['status'] == 'pending' for row in rows[len(completed):])
    assert (manifest['completed'], manifest['pending']) == (len(completed), 20-len(completed))
    for row in completed:
        assert hashlib.sha256((ROOT / row['planned_wofost_source_path']).read_bytes()).hexdigest() == row['source_sha256']
    assert manifest['existing_13_pairs']['uncalibrated'] == 1
    for row in rows:
        assert hashlib.sha256((ROOT / row['legacy_source_path']).read_bytes()).hexdigest() == row['legacy_sha256']
    assert rows[0]['planned_wofost_id'] == case.SCENARIO_ID
    assert hashlib.sha256(Path(case.__file__).read_bytes()).hexdigest() == rows[0]['source_sha256']
