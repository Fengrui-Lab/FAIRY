"""Fixed-cultivar public references; no model requests, no trajectory reuse."""
import argparse,dataclasses,datetime,hashlib,importlib.metadata,json,sys,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import run_maize_basic_reference as base
import run_maize_h01_reference as h01
from fairy.scenarios.maize import cultivar_instances
from fairy.scenarios.registry import get_scenario_class
from fairy.apps.farm_world import FarmWorldApp,TractorApp
from fairy.controllers.engine import Engine
from fairy.crops.maize_identity import native_variety

class DeadlineStop(base.PilotStop):pass
class Executor(h01.H01Executor):
    def wait(self,t):
        if t > self.s.start_time+self.s.duration:
            # Do not generate weather or integrate beyond the frozen deadline.
            raise DeadlineStop('frozen_scenario_deadline')
        super().wait(t)

def source_identity():
    paths=sorted([*ROOT.joinpath('fairy').rglob('*.py'),
                  *ROOT.joinpath('fairy/physics/data').rglob('*'),
                  *ROOT.joinpath('fairy/scenarios/maize/basic_management_v1').glob('*'),
                  *ROOT.joinpath('fairy/scenarios/maize/basic_h01_v0').glob('*'),
                  *ROOT.joinpath('scripts').glob('*maize*reference.py')])
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}
    return {'files':hashes,'python':sys.version,'pcse':importlib.metadata.version('pcse')}

def crop_identity(s):
    farm=s.get_typed_app(FarmWorldApp)
    identity={'scenario_id':s.scenario_id,'family':s.family,'variant':s.variant,
      'crop_name':'maize','public_seed_type':s.public_seed_type,'native_variety_name':native_variety(s.public_seed_type),
      'maize_yaml_sha256':hashlib.sha256((ROOT/'fairy/physics/data/wofost/maize.yaml').read_bytes()).hexdigest(),
      'wofost_config':dataclasses.asdict(farm.physics.crop_backend.config),
      'selection_sha256':hashlib.sha256((ROOT/'fairy/crops/maize_identity.py').read_bytes()).hexdigest(),
      'factory_sha256':hashlib.sha256((ROOT/'fairy/scenarios/maize/cultivar_instances.py').read_bytes()).hexdigest(),
      'pcse_version':importlib.metadata.version('pcse')}
    identity['crop_config_fingerprint']=base.digest(identity)
    return identity

def actual_identity(s,executor=None,require_runs=False):
    farm=s.get_typed_app(FarmWorldApp);tractor=s.get_typed_app(TractorApp);seed=s.public_seed_type;variety=native_variety(seed)
    assert s.variant==int(seed[-3:])
    assert farm.crop_definition.seed_types==(seed,)
    assert farm.public_crop_profile()['seed_type']==seed
    assert farm.variety_name==variety
    loads=[] if executor is None else [r for r in executor.events if r['tool']=='TractorApp__load_seeds']
    if require_runs:
        assert loads and all(r['args']['seed_type']==seed and not r.get('exception') and not (isinstance(r['receipt'],dict) and r['receipt'].get('error')) for r in loads)
        assert tractor.seed_type==seed
        assert len(farm.physics.crop_backend._runs)==64
    runs=[]
    for rid,r in farm.physics.crop_backend._runs.items():
        ridge=farm._ridges[rid]
        assert ridge.seed_type==seed or (ridge.harvested and ridge.seed_type is None)
        assert r.specification['seed_type']==seed and r.specification['variety']==variety
        runs.append({'ridge':rid,'ridge_seed':farm._ridges[rid].seed_type,'native_seed':r.specification['seed_type'],'native_variety':r.specification['variety']})
    return {'passed':True,'scenario_variant':s.variant,'allowed_seeds':farm.crop_definition.seed_types,
            'loaded_seed':tractor.seed_type,'load_calls':len(loads),'native_runs':runs}

def setup(sid):
    s=get_scenario_class(sid)(seed=0);s.setup();return s,Engine(None,s)

def preflight(sid,gate):
    s,e=setup(sid);ci=crop_identity(s);actual=actual_identity(s)
    assert s.public_seed_type in s.scenario_input and ci['native_variety_name'] in s.scenario_input
    base.save(gate,{'status':'passed','scenario_id':sid,'source':source_identity(),'crop':ci,'initial_identity':actual,
                   'task_sha256':base.digest(s.scenario_input),'tool_names':sorted(t.name for a in s.apps for t in a.get_tools())})

def run(sid,gate,output):
    g=json.loads(gate.read_text());assert g['status']=='passed' and g['scenario_id']==sid and g['source']==source_identity(),'stale gate'
    s,e=setup(sid);ci=crop_identity(s);assert ci==g['crop'];actual_identity(s)
    if output.exists():raise RuntimeError('No automatic retry or overwrite')
    x=Executor(s,e,output);errors=[];completed=False;identity_ok=False
    base.save(output/'started.json',{'scenario_id':sid,'source':g['source'],'crop':ci,'policy':'H01 A inspect/service' if s.family=='H01' else 'existing v1.1 reference','seed':0,'model_requests':0})
    base.save(output/'initial_state.json',{'scenario':dataclasses.asdict(s.spec),'crop_options':s.crop_backend_options,'farm':s.get_typed_app(FarmWorldApp).get_state()})
    try:
        base.setup_operations(x,120*1.2864/.46)
        base.manage(x,'water_threshold_v1' if s.family=='W01' else 'none')
        base.save(output/'preharvest_identity.json',actual_identity(s,x,require_runs=True))
        if s.family=='H01':base.save(output/'header_decision.json',h01.inspect_and_branch(x,'A'))
        base.harvest(x);completed=True
    except Exception as er:
        errors.append({'type':type(er).__name__,'message':str(er),'traceback':traceback.format_exc()})
    evaluation={}
    try:evaluation=s.validate().to_dict()
    except Exception as er:errors.append({'type':type(er).__name__,'message':'validation: '+str(er)})
    try:
        actual=actual_identity(s,x,require_runs=True);identity_ok=True
    except Exception as er:
        actual={'passed':False,'reason':repr(er)};errors.append({'type':'invalid_identity','message':repr(er)})
    base.save(output/'workflow.json',s.workflow.to_dict());base.save(output/'evaluation.json',evaluation)
    base.save(output/'identity.json',{'crop':ci,'actual':actual})
    # Exports are audits, never read for management decisions.
    farm=s.get_typed_app(FarmWorldApp);backend=farm.physics.crop_backend
    native=backend.export_state();base.save(output/'native_backend_state.json',native)
    per=[]
    for rid,r in backend._runs.items():
        m=r.maturity_snapshot or {};p=r.pcse
        per.append({'ridge':rid,'DOE':m.get('DOE',p.get('DOE')),'DOA':m.get('DOA',p.get('DOA')),'DOM':m.get('DOM'),
                    'final_DVS':p.get('DVS'),'TWSO':m.get('TWSO'),'harvested':farm._ridges[rid].harvested})
    meta=evaluation.get('metadata',{})
    tool_errors=[r for r in x.events if r['exception'] or isinstance(r['receipt'],dict) and r['receipt'].get('error')]
    warnings=[r for r in x.events if isinstance(r['receipt'],dict) and r['receipt'].get('warning')]
    valid=completed and meta.get('execution_complete') is True and identity_ok and not errors and not tool_errors and not warnings
    status=meta.get('status','incomplete')
    if not identity_ok:status='invalid_identity'
    elif any(er['type']=='DeadlineStop' for er in errors) and not all(p['DOM'] for p in per):status='seasonal_mismatch'
    elif errors:status='reference_failed'
    def dates(key):
        vals=sorted({str(p[key]) for p in per if p[key] is not None});return vals[0] if len(vals)==1 else vals or None
    # fertilizer preplant may be carried outside journal: use actual successful public application instead.
    fertilizer=sum(float(r['args'].get('total_kg',0)) for r in x.events if r['tool']=='TractorApp__base_fertilize' and r['classification']=='ok')
    summary={**{k:ci[k] for k in ('scenario_id','family','variant','public_seed_type','native_variety_name','crop_config_fingerprint')},
      'DOE':dates('DOE'),'DOA':dates('DOA'),'DOM':dates('DOM'),'native_per_ridge':per,
      'mature_TWSO_kg_DM_ha':meta.get('mature_TWSO_kg_DM_ha'),'warehouse_kg_at_14pct':meta.get('warehouse_kg_at_14pct'),
      'actual_external_n_kg_ha':fertilizer*.46/1.2864,'actual_gross_irrigation_mm':x.water_used,
      'native_effective_irrigation_mm':meta.get('effective_irrigation_field_mm'),
      'execution_complete':meta.get('execution_complete',False),'production_success':meta.get('production_success',False),
      'status':status,'tier':'B' if valid else 'registered_candidate','acceptance':'accepted' if valid else status,
      'run_valid':identity_ok,'tool_call_count':x.calls,'tool_errors':tool_errors,'tool_warnings':warnings,'failures':errors,
      'final_sim_time':datetime.datetime.fromtimestamp(x.now(),base.TZ).isoformat(),'model_requests':0}
    assert native_variety(summary['public_seed_type'])==summary['native_variety_name']
    base.save(output/'summary.json',summary)
    return 0 if valid else 1

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['preflight','run']);p.add_argument('--scenario',required=True);p.add_argument('--gate',type=Path,required=True);p.add_argument('--output',type=Path);a=p.parse_args()
    if a.action=='preflight':preflight(a.scenario,a.gate)
    else:sys.exit(run(a.scenario,a.gate,a.output))
