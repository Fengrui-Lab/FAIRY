"""Incremental static and public-call contracts for each newly calibrated scene."""
import ast
from collections import Counter
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path

import pytest
from fairy.apps.farm_world import FarmWorldApp
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.wofost_farm import WofostFarmScenario

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=json.loads((ROOT/'configs/oracles/wofost_selected20_20261027.json').read_text())
READY=[r for r in MANIFEST['cases'] if r['number']>=3 and r['status']=='calibrated']

@pytest.fixture(scope='module',params=READY,ids=lambda r:r['planned_wofost_id'])
def built(request):
    row=request.param
    mod=importlib.import_module('.'.join(Path(row['planned_wofost_source_path']).with_suffix('').parts))
    cls=getattr(mod,row['planned_wofost_class_name']);scene=cls();scene.setup();engine=Engine(None,scene)
    farm=scene.get_typed_app(FarmWorldApp)
    before=deepcopy((farm.get_state(),farm.physics.crop_backend.export_state(),engine.time_manager.time()))
    work=engine.build_oracle_workflow(run_oracle=False)
    assert before==(farm.get_state(),farm.physics.crop_backend.export_state(),engine.time_manager.time())
    return row,mod,scene,work


def test_legacy_and_native_sources_are_independent(built):
    row,mod,scene,work=built
    assert hashlib.sha256((ROOT/row['legacy_source_path']).read_bytes()).hexdigest()==row['legacy_sha256']
    assert hashlib.sha256(Path(mod.__file__).read_bytes()).hexdigest()==row['source_sha256']
    assert get_scenario_class(row['planned_wofost_id']) is type(scene)
    assert not issubclass(get_scenario_class(row['legacy_id']),WofostFarmScenario)
    tree=ast.parse(Path(mod.__file__).read_text())
    assert not any(isinstance(n,ast.ImportFrom) and (n.module or '').split('.')[-1].startswith('scenario_') for n in ast.walk(tree))
    plan=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='build_events_flow')
    assert not any(isinstance(n,(ast.If,ast.While,ast.ListComp,ast.DictComp,ast.GeneratorExp)) for n in ast.walk(plan))
    assert all(isinstance(n.iter,ast.Name) and n.iter.id=='captured' for n in ast.walk(plan) if isinstance(n,ast.For))
    assert scene.reference['parameter_overrides']=={} and scene.crop_backend_options['reference_density_plants_m2']==40


def test_complete_static_plan_has_honest_scope_and_resources(built):
    row,mod,scene,workflow=built
    planted=[];harvested=[];previous=None;world=scene.WORLD
    for name,s in workflow.dag.items():
        assert s.content is None and s.depends_on==([] if previous is None else [previous]);previous=name
        method=s.tool_name.split('__')[1];a=s.tool_args
        if method in ('inspect_emergence','inspect_crop_health'):
            assert 1<=a['end_ridge']-a['start_ridge']+1<=8
        if method=='plant_seeds':
            planted+=list(range(a['start_ridge'],a['end_ridge']+1))
            assert a['seed_spacing_cm']==pytest.approx(200/(world.planting_density_plants_m2*world.ridge_width_m))
        if method=='harvest':harvested+=list(range(a['start_ridge'],a['end_ridge']+1))
    assert Counter(planted)==Counter(harvested)==Counter(range(world.num_ridges))
    assert world.base_fertilizer_kg==0
    assert len(workflow.dag)==row['tool_calls']

    # The reproducible control recipe and complete production calls must agree.
    from wofost_selected20_experiments import config, definition, declarations
    from fairy.scenarios.wofost_events import scenario_events_snapshot
    recipe=config(row['number'])
    assert definition(recipe)==world
    trial=[x for x in recipe['actions'] if not x.get('arms') or 'correct' in x['arms']]
    assert len(trial)==len(workflow.dag)
    for expected,actual in zip(trial,workflow.dag.values()):
        if 'at' in expected:
            assert actual.tool_name in ('SystemApp__advance_time','SystemApp__get_current_time')
        else:
            assert expected['tool']==actual.tool_name
            assert all(actual.tool_args[k]==v for k,v in expected.get('args',{}).items())
    assert len(declarations(recipe))==len(scenario_events_snapshot(scene.get_typed_app(FarmWorldApp))['events'])


def test_selected_queue_preserves_both_namespaces():
    rows=MANIFEST['cases']
    assert [r['number'] for r in rows]==list(range(1,21))
    historical=json.loads((ROOT/'configs/oracles/wofost_scenario_versions.json').read_text())['rows']
    assert not {r['legacy_id'] for r in rows}&{r['legacy_id'] for r in historical}
    assert MANIFEST['completed']==sum(r['status']=='calibrated' for r in rows)
    assert MANIFEST['pending']==sum(r['status']=='pending' for r in rows)
    assert MANIFEST['blocked']==sum(r['status']=='blocked_by_model' for r in rows)
    assert MANIFEST['completed']+MANIFEST['pending']+MANIFEST['blocked']==20
    for row in rows:
        assert row['planned_wofost_id']==row['legacy_id']+'_V2'
        old=ROOT/row['legacy_source_path']
        assert old.parent==ROOT/'fairy/scenarios/farm_world_fullseason_v2'
        assert ROOT/row['planned_wofost_source_path']==ROOT/'fairy/scenarios/wofost'/(old.stem+'_V2.py')
        if row['status']=='calibrated':
            assert row['oracle_cli_replay_evaluate']=='passed'
            assert row['tool_calls']>0 and row['field_operation_rounds']>0
