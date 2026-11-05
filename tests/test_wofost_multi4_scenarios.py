"""Multi-farm source ownership, fixed worlds and public-tool plan contracts.

Full physical controls and CLI replay are independently reproducible with
wofost_multi4_experiments.py and wofost_multi4_audit.py; these tests build only.
"""
import ast
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import importlib
import json
from pathlib import Path

import pytest
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.wofost_multi_farm import WofostMultiFarmScenario
from fairy.scenarios.wofost_events import scenario_events_snapshot

ROOT=Path(__file__).resolve().parents[1]
RECIPES=sorted((ROOT/'tests/data/wofost_multi4').glob('*.json'))

def snapshot(scene,engine):
    return deepcopy({'time':engine.time_manager.time(),
        'farms':{fid:f.get_state() for fid,f in scene.farms.items()},
        'native':{fid:f.physics.crop_backend.export_state() for fid,f in scene.farms.items()},
        'warehouse':scene.warehouse.get_state(),
        'devices':{a.name:a.get_state() for a in scene.shared_equipment},
        'events':{fid:scenario_events_snapshot(f) for fid,f in scene.farms.items()}})

@pytest.fixture(scope='module',params=RECIPES,ids=lambda p:p.stem)
def built(request):
    recipe=json.loads(request.param.read_text())
    module=importlib.import_module(recipe['module']);cls=getattr(module,recipe['class_name'])
    scene=cls();scene.setup();engine=Engine(None,scene);before=snapshot(scene,engine)
    plan=engine.build_oracle_workflow(run_oracle=False)
    assert snapshot(scene,engine)==before
    return recipe,module,scene,plan

def test_each_source_owns_its_world_and_literal_workflow(built):
    recipe,module,scene,plan=built
    cls=type(scene)
    assert cls.__bases__==(WofostMultiFarmScenario,)
    assert {'FARMS','SUPPLIES','REGIONAL_EVENTS','FIELD_EVENTS','BRIEFING','build_events_flow'}<=cls.__dict__.keys()
    assert get_scenario_class(module.SCENARIO_ID) is cls
    assert Path(module.__file__).parent==ROOT/'fairy/scenarios/wofost'
    tree=ast.parse(Path(module.__file__).read_text())
    assert not any(isinstance(n,ast.ImportFrom) and (n.module or '').split('.')[-1].startswith('scenario_') for n in ast.walk(tree))
    flow=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='build_events_flow')
    assert not any(isinstance(n,(ast.If,ast.While,ast.Try)) for n in ast.walk(flow))
    for n in ast.walk(flow):
        if isinstance(n,ast.For):assert isinstance(n.iter,ast.Name) and n.iter.id=='captured'
    assert module.FARMING_PLAN and len(scene.scenario_input)>1200
    assert not hasattr(scene,'execute_oracle_workflow')

def test_fields_have_separate_native_models_and_fixed_installations(built):
    _,_,scene,_=built
    assert len(scene.farms)==2
    assert len({id(f.physics) for f in scene.farms.values()})==2
    assert len({id(f.physics.crop_backend) for f in scene.farms.values()})==2
    assert len({id(f.physics.soil) for f in scene.farms.values()})==2
    assert len({id(f.physics.weather_generator) for f in scene.farms.values()})==1
    assert len(scene.shared_equipment)==3
    assert scene.farm_environment.warehouse is scene.warehouse
    for definition in scene.FARMS:
        fid=definition.farm_id;farm=scene.farms[fid]
        assert farm.physics.crop_backend_name=='wofost'
        assert farm.physics.crop_backend.export_state()['runs']=={}
        assert farm.physics.crop_backend.config.variety_name==definition.variety_name
        assert farm.physics.crop_backend.config.crop_name==definition.crop_name
        assert farm.farm_environment is scene.farm_environment
        assert scene.sensors[fid].bound_farm_id==scene.irrigations[fid].bound_farm_id==fid
        assert farm.physics.scenario_metadata['parameter_overrides']=={}
        assert farm.physics.scenario_metadata['regional_weather_changes']==scene.regional_weather_changes
        assert farm.field_area_m2/10000==pytest.approx(definition.area_ha)
    assert scene.warehouse.stock is not scene.SUPPLIES
    assert asdict(scene.warehouse.stock)==asdict(scene.SUPPLIES)

def test_complete_plan_names_every_mobile_target_and_respects_capacity(built):
    recipe,_,scene,plan=built
    nr={f.farm_id:f.num_ridges for f in scene.FARMS}
    planted={fid:[] for fid in nr};harvested={fid:[] for fid in nr};previous=None
    mobile={'plant_seeds','harvest','level','form_ridges','base_fertilize','apply_fertilizer',
            'spray_pesticide','apply_fungicide','inspect_crop_health','inspect_emergence','fly_survey'}
    for name,step in plan.dag.items():
        assert step.content is None
        assert step.depends_on==([] if previous is None else [previous]);previous=name
        method=step.tool_name.split('__')[1];a=step.tool_args
        if method in mobile:assert a['farm_id'] in nr
        if method in ('plant_seeds','harvest','apply_fertilizer','spray_pesticide','apply_fungicide','inspect_crop_health','inspect_emergence'):
            maximum=4 if method in ('plant_seeds','harvest') else 8 if method.startswith('inspect_') else 10
            assert 0<=a['start_ridge']<=a['end_ridge']<nr[a['farm_id']]
            assert a['end_ridge']-a['start_ridge']+1<=maximum
        if method=='plant_seeds':
            f=next(f for f in scene.FARMS if f.farm_id==a['farm_id'])
            assert a['seed_spacing_cm']==pytest.approx(100*f.rows_per_ridge/(f.density_plants_m2*f.ridge_width_m))
            planted[a['farm_id']]+=list(range(a['start_ridge'],a['end_ridge']+1))
        if method=='harvest':harvested[a['farm_id']]+=list(range(a['start_ridge'],a['end_ridge']+1))
    for fid,n in nr.items():assert Counter(planted[fid])==Counter(harvested[fid])==Counter(range(n))
    actions=[a for a in recipe['actions'] if not a.get('arms') or 'correct' in a['arms']]
    assert len(actions)==len(plan.dag)
    for action,step in zip(actions,plan.dag.values()):
        if 'at' in action:
            assert step.tool_name in ('SystemApp__advance_time','SystemApp__get_current_time')
        else:
            assert step.tool_name==action['tool']
            assert all(step.tool_args[k]==v for k,v in action.get('args',{}).items())

def test_disturbances_belong_to_initial_world_and_regional_weather_is_common(built):
    _,_,scene,_=built
    first=next(iter(scene.farms.values()))
    generator=first.physics.weather_generator
    for event in scene.REGIONAL_EVENTS:
        assert event.farm_id=='region'
        day=event.start;forcing=generator._day_overrides[day]
        if hasattr(event,'rain_multiplier') and event.rain_multiplier==0:assert forcing.rain_mm==0
        if getattr(event,'rain_mm',None) is not None:assert forcing.rain_mm==event.rain_mm
        if getattr(event,'wind_ms',None) is not None:assert forcing.wind_ms==event.wind_ms
    for fid,farm in scene.farms.items():
        installed=scenario_events_snapshot(farm).get('events',[])
        assert len(installed)==sum(e.farm_id==fid for e in scene.FIELD_EVENTS)
        if farm.crop_type=='maize':assert not installed
        assert all(e['repeat']=='once' for e in installed)
