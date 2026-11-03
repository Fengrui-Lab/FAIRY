"""Actual planting/native initialization, not config-only identity tests."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from fairy.crops.maize_identity import MAIZE_WOFOST_VARIANTS
from fairy.physics.wofost_backend import WofostConfig, WofostBackend
from fairy.scenarios.maize import cultivar_instances
from fairy.scenarios.registry import get_scenario_class
from fairy.apps.farm_world import FarmWorldApp,TractorApp
from fairy.controllers.engine import Engine
import run_maize_basic_reference as ref

@pytest.mark.parametrize('seed,variety',MAIZE_WOFOST_VARIANTS.items())
def test_actual_public_planting_native_identity(seed,variety,tmp_path):
 sid=f'scenario_maize_l3_basic_n01_maize{seed[-3:]}_v1'
 s=get_scenario_class(sid)(seed=0);s.setup();e=Engine(None,s);x=ref.Executor(s,e,tmp_path/'run')
 farm=s.get_typed_app(FarmWorldApp)
 assert farm.crop_definition.seed_types==(seed,)
 assert seed in s.scenario_input and variety in s.scenario_input
 ref.setup_operations(x,120*1.2864/.46);x.wait(x.now()+86400)
 assert s.get_typed_app(TractorApp).seed_type==seed
 assert len(farm.physics.crop_backend._runs)==64
 for rid,run in farm.physics.crop_backend._runs.items():
  assert farm._ridges[rid].seed_type==seed
  assert run.specification['seed_type']==seed
  assert run.specification['variety']==variety

@pytest.mark.parametrize('seed,variety',[('MAIZE_203','Grain_maize_201'),('MAIZE_205','Grain_maize_204'),('MAIZE_206','Grain_maize_201')])
def test_reject_mismatch(seed,variety):
 with pytest.raises(ValueError):WofostConfig(crop_name='maize',variety_name=variety,cultivar_map={seed:variety})

@pytest.mark.parametrize('variant',['Grain_maize_206','unknown'])
def test_reject_unknown_variety(variant):
 with pytest.raises(ValueError):WofostConfig(crop_name='maize',variety_name=variant)

def test_no_fallback():
 with pytest.raises(ValueError):WofostConfig(crop_name='maize',variety_name='Grain_maize_203')
 b=WofostBackend(WofostConfig(crop_name='maize'))
 for seed in ['MAIZE_203','MAIZE_206','MAIZE_20x','MAIZE_STANDARD']:
  with pytest.raises(ValueError):b._variety_for_seed(seed)

@pytest.mark.parametrize('family',['w01','n01'])
def test_historical_alias_identity(family):
 sid=f'scenario_maize_l3_basic_{family}_v1';s=get_scenario_class(sid)(seed=0);s.setup()
 assert s.public_seed_type=='MAIZE_201'
 assert s.get_typed_app(FarmWorldApp).variety_name=='Grain_maize_201'

@pytest.mark.parametrize('harvested,ridge_seed,valid',[(False,'MAIZE_202',True),(True,None,True),(True,'MAIZE_203',False),(False,None,False)])
def test_postharvest_identity_keeps_mismatch_guard(harvested,ridge_seed,valid):
 from types import SimpleNamespace as S
 from run_maize_cultivar_reference import actual_identity
 farm=S(crop_definition=S(seed_types=('MAIZE_202',)),public_crop_profile=lambda:{'seed_type':'MAIZE_202'},variety_name='Grain_maize_202',
        _ridges=[S(seed_type=ridge_seed,harvested=harvested)],physics=S(crop_backend=S(_runs={0:S(specification={'seed_type':'MAIZE_202','variety':'Grain_maize_202'})})))
 tractor=S(seed_type='MAIZE_202');scenario=S(public_seed_type='MAIZE_202',variant=202,get_typed_app=lambda cls:farm if cls is FarmWorldApp else tractor)
 if valid:assert actual_identity(scenario)['passed']
 else:
  with pytest.raises(AssertionError):actual_identity(scenario)
