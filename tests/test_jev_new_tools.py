"""New tool support without models, hidden-state inputs, or oracle calls."""
import copy
import json
from types import SimpleNamespace
import pytest
from fairy.scenarios.registry import get_scenario_class
from fairy.controllers.engine import Engine
from fairy.controllers.agent_builder import build_controller_agent
from fairy.agents.jev.menu import build_tool_menus, dependent_menu
from fairy.agents.jev.snapshot import build_snapshot
from fairy.agents.jev.done_check import done_problems
from test_jev_agent import _ScriptedJev, _ScriptedLLM

SCENES = [
 'scenario_full_season_hb_base_hn84_std_normal_V2',
 'scenario_two_farm_full_season_hn84_normal',
 'scenario_three_farm_full_season_hn84_normal',
 'scenario_rice_l3_normal',
 'scenario_multi_crop_full_season_maize',
]

def setup(sid):
 s=get_scenario_class(sid)(seed=0,detailed_briefing=True);s.setup()
 a=build_controller_agent('farm_jev',llm=_ScriptedJev([]),toolsets=s.apps)
 return s,a

@pytest.mark.parametrize('sid',SCENES)
def test_initialized_menus_snapshot_do_not_change_scene(sid):
 s,a=setup(sid)
 task=Engine(agent=None,scenario=s)._resolve_agent_task()
 before=[copy.deepcopy(x.get_state()) for x in s.apps]
 snapshot,facts=build_snapshot(s.apps,SimpleNamespace(dag={}),s.start_time)
 menus=build_tool_menus(a.tools_map,task_text=task,num_ridges=a._num_ridges)
 after=[copy.deepcopy(x.get_state()) for x in s.apps]
 assert before==after
 assert menus
 assert not any('backend' in k for k in snapshot)
 if 'farm' in sid and ('two_' in sid or 'three_' in sid):
  assert len(facts['farms'])==(3 if 'three_' in sid else 2)
 if 'rice' in sid:
  assert facts['plots'] and not facts.get('ridges')


def test_shared_batch_lifecycle_menus():
 from fairy.apps.farm_world.warehouse_app import GrainBatch
 s,a=setup(SCENES[1]);w=s.warehouse
 def menus():return build_tool_menus(a.tools_map,task_text='harvest 64 ridges and store',num_ridges=64)
 def find(ms,method):return next(m for name,m in ms.items() if name.endswith('__'+method))
 initial=menus(); assert not any(n.endswith('__dry_grain') for n in initial)
 unload=find(initial,'unload_grain');label=next(iter(unload.args[0].options.values()))
 w.grain_batches[label]=GrainBatch(label,'farm_a','soybean',None,[0],100,20)
 active=menus();assert label in find(active,'dry_grain').args[0].options.values()
 assert label not in find(active,'unload_grain').args[0].options.values()
 w.grain_batches[label].status='stored'
 assert not any(n.endswith('__dry_grain') for n in menus())


def test_rice_mutually_exclusive_grain_sensor():
 s,a=setup(SCENES[3]);a.tool_menus=build_tool_menus(a.tools_map,task_text='inspect 2 plots',num_ridges=0)
 m=next(m for n,m in a.tool_menus.items() if n.endswith('__measure_grain_moisture'))
 calls=[]
 def ask(kind,state,qs):
  calls.append(qs)
  return {k:{'choice':next(iter(q['criteria'])),'confidence':1} for k,q in qs.items()}
 a._ask=ask
 values,_=a._dependent_values(m,{})
 assert (values['plot_id'] is None)!=(values['batch_id'] is None)


def test_multi_done_checks_each_farm():
 facts={'farms':{'a':{'ridges':[{'ridge_id':0,'planted':True,'harvested':True}]},
                 'b':{'ridges':[{'ridge_id':0,'planted':True,'harvested':False}]}},
        'inventory':{},'machines':{}}
 assert done_problems('harvest',facts,None)==['b: ridges 0 are planted but not harvested yet.']


def test_shared_farm_selection_precedes_ridges():
 s,a=setup(SCENES[1]);a.tool_menus=build_tool_menus(a.tools_map,task_text='plant 64 ridges 4 cm 7.9 cm',num_ridges=64)
 m=next(m for n,m in a.tool_menus.items() if n.endswith('__plant_seeds'))
 assert dependent_menu(a.tools_map[m.tool_name])
 calls=[]
 def ask(kind,state,qs):
  calls.append(qs)
  return {k:{'choice':('farm_b' if k=='arg__farm_id' else next(iter(q['criteria']))),'confidence':1} for k,q in qs.items()}
 a._ask=ask
 values,_=a._dependent_values(m,{})
 assert next(iter(calls[0]))=='arg__farm_id'
 assert values['farm_id']=='farm_b'
 assert 0<=values['start_ridge']<=values['end_ridge']<64


def legacy_scenes():
 from pathlib import Path
 root=Path(__file__).resolve().parents[1]/"scripts/fullseason"
 ids=[]
 for name in ("selected_l2_l1_20_30_scenario_ids.txt", "l3_mini_20_scenario_ids.txt"):
  for line in (root/name).read_text().splitlines():
   if line.strip() and not line.startswith("#"):
    ids.append(line.split(",")[2] if "," in line else line.strip())
 return ids

@pytest.mark.parametrize("sid",legacy_scenes())
def test_legacy_menu_and_snapshot_match_frozen_source(sid):
 import importlib.util
 import sys
 from dataclasses import asdict
 from pathlib import Path
 original=Path(__file__).parent/'fixtures/jev_before_new_tools'
 def load(name):
  spec=importlib.util.spec_from_file_location('upstream_'+name,original/(name+'.py'))
  mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod);return mod
 old_menu,old_snap=load('menu'),load('snapshot')
 s,a=setup(sid)
 task=Engine(agent=None,scenario=s)._resolve_agent_task()
 before=old_menu.build_tool_menus(a.tools_map,task_text=task,num_ridges=a._num_ridges)
 after=build_tool_menus(a.tools_map,task_text=task,num_ridges=a._num_ridges)
 assert {k:asdict(v) for k,v in before.items()}=={k:asdict(v) for k,v in after.items()}
 wf=SimpleNamespace(dag={})
 assert old_snap.build_snapshot(s.apps,wf,s.start_time)==build_snapshot(s.apps,wf,s.start_time)


def test_shared_snapshot_charging_is_read_only():
 s,a=setup(SCENES[1]);drone=next(x for x in s.apps if type(x).__name__=='SharedDroneApp')
 drone._charging=True;drone._charge_started_at=s.start_time-100
 drone._charge_complete_at=s.start_time+100;drone._charge_start_battery_pct=20
 before=copy.deepcopy(drone.get_state())
 build_snapshot(s.apps,SimpleNamespace(dag={}),s.start_time)
 assert drone.get_state()==before


def test_rice_list_options_are_typed():
 s,a=setup(SCENES[3]);menus=build_tool_menus(a.tools_map,task_text='survey 2 plots',num_ridges=0)
 m=next(m for n,m in menus.items() if n.endswith('__fly_survey'))
 assert all(isinstance(v,list) and v for v in m.args[0].options.values())
 assert len(m.args[0].options)==3


def test_runtime_entity_and_crop_scoping():
 s,a=setup(SCENES[4]);a.tool_menus=build_tool_menus(a.tools_map,task_text='plant 64 ridges at depth 4 cm and 20 cm spacing',num_ridges=a._num_ridges)
 m=next(m for n,m in a.tool_menus.items() if n.endswith('__load_seeds'))
 questions=[]
 def ask(kind,state,qs):
  questions.extend(qs.values())
  return {k:{'choice':next(iter(q['criteria'])),'confidence':1} for k,q in qs.items()}
 a._ask=ask
 values,_=a._dependent_values(m,{})
 runtime=a.tools_map[m.tool_name].class_instance.runtime
 assert values['farm_id'] in runtime.assets[values['asset_id']].spec.allowed_farm_ids
 from fairy.apps.farm_world.crop_profiles import seed_crop_type
 assert seed_crop_type(values['seed_type'])==runtime.farms[values['farm_id']].farm.crop_type


def test_native_warehouse_drying_storage_updates_candidates():
 from fairy.apps.farm_world.warehouse_app import GrainBatch
 s,a=setup(SCENES[1]);w=s.warehouse
 w.grain_batches['fixture']=GrainBatch('fixture','farm_a','soybean',None,[0],100,20)
 assert 'error' not in w.dry_grain('fixture',13.0)
 assert 'error' not in w.store_grain('fixture')
 menus=build_tool_menus(a.tools_map,task_text='harvest 64 ridges and store',num_ridges=64)
 assert not any(n.endswith(('__dry_grain','__store_grain')) for n in menus)


def test_target_ridge_bounds_use_selected_farm():
 s,a=setup(SCENES[1]);s.farm_b.num_ridges=10;s.farm_b._ridges=s.farm_b._ridges[:10]
 a.tool_menus=build_tool_menus(a.tools_map,task_text='plant 64 ridges at 4 cm',num_ridges=64)
 m=next(m for n,m in a.tool_menus.items() if n.endswith('__plant_seeds'))
 def ask(kind,state,qs):
  return {k:{'choice':('farm_b' if k=='arg__farm_id' else list(q['criteria'])[-1]),'confidence':1} for k,q in qs.items()}
 a._ask=ask
 values,_=a._dependent_values(m,{})
 assert values['start_ridge']==9 and values['end_ridge']==9
