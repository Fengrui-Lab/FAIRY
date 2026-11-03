"""Public-observation maize reference controller. No model API. Explicit preflight gate."""
from pathlib import Path
import sys,json,hashlib,dataclasses,time,datetime,math
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fairy.scenarios.maize.basic_management import DATA
from fairy.scenarios.registry import get_scenario_class
from fairy.controllers.engine import Engine
from fairy.agents.agent.toolset_builder import build_toolset
from fairy.scenarios.workflow import WorkflowStep
TZ=ZoneInfo('Asia/Shanghai')
def jsonable(x):
 if isinstance(x,(set,tuple)):return list(x)
 if isinstance(x,(datetime.date,datetime.datetime)):return x.isoformat()
 if dataclasses.is_dataclass(x):return dataclasses.asdict(x)
 return str(x)
def data(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,default=jsonable,allow_nan=False).encode()
def digest(x):return hashlib.sha256(data(x)).hexdigest()
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data(x)+b'\n')
class PilotStop(RuntimeError):pass

def classify(r):
 if not isinstance(r,dict):return 'unknown'
 if r.get('error'):return 'rejected'
 if r.get('warning'):return 'warning'
 if r.get('status')=='irrigation_pending':return 'pending'
 if r.get('status')=='irrigation_started':
  return 'accepted' if isinstance(r.get('effect_ready_at'),(int,float)) and isinstance(r.get('irrigated_ridges'),list) else 'unknown'
 if r.get('status') in ('ok','noop') or any(k in r for k in ['sim_date','root_zone_sensors','ridges_overview','ridges','fuel_tank_l','available_implements','seed_stock','tool_calls','crop_type']):return 'ok'
 # Many legacy successful reads/writes use a specific payload, not a uniform status.
 return 'payload' if r else 'unknown'

def merge(ids):
 result=[]
 for n in sorted(set(ids)):
  if result and n==result[-1][1]+1:result[-1][1]=n
  else:result.append([n,n])
 return result

class Executor:
 def __init__(self,s,e,out):
  self.s=s;self.e=e;self.out=out;out.mkdir(parents=True,exist_ok=True);self.tools,self.schemas,self.map=build_toolset(list(s.apps));self.calls=0;self.wall=time.monotonic();self.locks=[];self.events=[];self.obs_serial=0;self.water_used=0.;self.decision_attempted={};self.aborted_reason=None
 def now(self):return self.e.time_manager.time()
 def log(self,x):
  with (self.out/'executor_events.jsonl').open('ab') as f:f.write(data(x)+b'\n')
 def call(self,name,**args):
  if self.calls>=500:raise PilotStop('agricultural_tool_budget_500')
  if time.monotonic()-self.wall>=1800:raise PilotStop('wall_timeout_1800')
  if self.now()>self.s.start_time+180*86400:raise PilotStop('simulation_duration_180_days')
  if name not in self.map:raise PilotStop('Tool not exposed: '+name)
  self.calls+=1;before=self.now();exc=None
  try:r=self.map[name](**args)
  except Exception as er:
   exc=type(er).__name__+': '+str(er);r={'executor_exception':exc}
  after=self.now();row={'index':self.calls,'tool':name,'args':args,'time_before':before,'time_after':after,'receipt':r,'classification':classify(r),'exception':exc};self.events.append(row)
  with (self.out/'tool_log.jsonl').open('ab') as f:f.write(data(row)+b'\n')
  self.s.workflow.add_node(WorkflowStep(name=f'pilot_{self.calls:04d}',op_type='TOOL_ERROR' if exc or (isinstance(r,dict) and r.get('error')) else 'tool',tool_name=name,tool_args=args,content=r,time_before=before,time_after=after,error_type=exc))
  if exc:raise PilotStop(exc)
  return r
 def required(self,name,**args):
  r=self.call(name,**args)
  if not isinstance(r,dict) or r.get('error') or r.get('warning'):raise PilotStop('Required operation refused/uncertain: '+name+': '+str(r))
  return r
 def wait(self,t):
  if t>self.now()+1e-6:self.required('SystemApp__advance_time',seconds=float(t-self.now()))
 def observe(self,kind,grid_id=None):
  soil=self.required('SensorApp__read_root_zone_sensors');crop=self.required('FarmWorldApp__get_farm_overview');weather=self.required('WeatherApp__get_current_weather');self.obs_serial+=1
  o={'id':f'obs-{self.obs_serial:04d}','time':self.now(),'local_date':datetime.datetime.fromtimestamp(self.now(),TZ).date().isoformat(),'kind':kind,'grid_id':grid_id,'soil':soil,'crop':crop,'weather':weather}
  self.log({'event':'observation','observation':o});return o
 def dispatch_water(self,start,end,dose,obs,grid_id):
  ids=set(range(start,end+1));now=self.now()
  if obs['kind']!='grid' or obs['grid_id']!=grid_id:raise PilotStop('Only grid observation can trigger irrigation')
  if now-obs['time']>21600 or datetime.datetime.fromtimestamp(now,TZ).date().isoformat()!=obs['local_date']:raise PilotStop('stale_observation')
  if any(ids.intersection(lock['ridges']) and lock['state']!='reconciled' for lock in self.locks):self.log({'event':'suppressed_overlap','ridges':sorted(ids),'observation':obs['id']});return {'executor_status':'suppressed_overlap'}
  if ids.intersection(self.decision_attempted.setdefault(grid_id,set())):raise PilotStop('same_grid_repeat')
  self.decision_attempted[grid_id].update(ids)
  lock={'dispatch':len(self.locks)+1,'operation':'irrigation','ridges':sorted(ids),'observation_id':obs['id'],'state':'dispatched','eta':None};self.locks.append(lock)
  r=self.call('FieldOpsApp__irrigate',start=start,end=end,hours=float(dose/5));cl=classify(r);lock['receipt']=r;lock['state']=cl
  if cl=='accepted':
   if sorted(r['irrigated_ridges'])!=sorted(ids):lock['state']='partial';raise PilotStop('partial_irrigation_coverage')
   lock['eta']=r['effect_ready_at'];self.water_used+=dose*len(ids)/64;lock['gross_mm_per_ridge']=dose
  elif cl=='rejected':lock['state']='reconciled';lock['actual_input']=0
  elif cl=='pending':
   lock['eta']=r.get('effect_ready_at');raise PilotStop('unexpected_native_pending_requires_input_reconciliation')
  else:raise PilotStop('unknown_irrigation_input_locked')
  self.log({'event':'water_dispatch','lock':lock,'water_used_field_mm':self.water_used});return r
 def settle(self):
  unresolved=[l for l in self.locks if l['state'] not in ('reconciled','accepted')]
  if unresolved:raise PilotStop('Unknown/partial pending input cannot be resent')
  pending=[l for l in self.locks if l['state']=='accepted']
  if not pending:return
  self.wait(max(l['eta'] for l in pending));o=self.observe('settlement');receipt=self.required('FieldOpsApp__get_irrigation_log')
  # Public success receipt+ETA+new read+public irrigation log; native quantity is checked separately offline.
  for lock in pending:lock['state']='reconciled';lock['confirmation_observation']=o['id'];lock['confirmation_time']=self.now()
  self.log({'event':'settlement_confirmation_only','observation':o['id'],'log':receipt,'new_irrigation_allowed':False})

def setup_operations(x,product):
 x.call('AgentUserInterface__send_message_to_agent',content=x.s.scenario_input)
 x.required('FarmWorldApp__get_crop_capabilities');x.required('FarmWorldApp__get_inventory');x.required('TractorApp__get_status');x.required('SensorApp__read_soil_sensors');x.required('WeatherApp__get_current_weather')
 for name,args in [('TractorApp__attach_implement',{'implement':'grader'}),('TractorApp__level',{}),('TractorApp__detach_implement',{}),('TractorApp__load_fertilizer',{'kg':float(product)}),('TractorApp__base_fertilize',{'total_kg':float(product)}),('TractorApp__attach_implement',{'implement':'furrower'}),('TractorApp__form_ridges',{'ridge_width_m':.75}),('TractorApp__detach_implement',{})]:x.required(name,**args)
 for start in range(0,64,4):
  # Actual hopper capacity is read; load exact next pass as needed.
  status=x.required('TractorApp__get_status');needed=4*1340
  if status['seed_hopper']<needed:x.required('TractorApp__load_seeds',seed_type=x.s.public_seed_type,count=needed-int(status['seed_hopper']))
  x.required('TractorApp__plant_seeds',start_ridge=start,end_ridge=start+3,depth_cm=4.,seed_spacing_cm=20.)
 x.required('FarmWorldApp__get_farm_overview')

def manage(x,water):
 anchor=datetime.datetime.fromisoformat(json.loads((DATA/'schedule.json').read_text())['grid_anchor']).timestamp();assert anchor==x.s.start_time, 'explicit grid anchor mismatch';next_grid=anchor+max(1,math.ceil((x.now()-anchor)/259200))*259200;daily=False
 while True:
  x.wait(next_grid);gid=int((next_grid-anchor)/86400);late=x.now()-next_grid
  x.log({'event':'decision_grid','grid_id':gid,'scheduled_at':next_grid,'lateness_seconds':late})
  o=x.observe('grid',gid);ridges=o['crop']['ridges_overview']
  if any(r['growth_stage']=='MATURE' and not r['harvested'] for r in ridges):daily=True
  if all(r['growth_stage']=='MATURE' or r['harvested'] for r in ridges):return
  if water=='water_threshold_v1':
   eligible=set()
   active={r['ridge_id'] for r in ridges if r['planted'] and not r['harvested'] and r['growth_stage']!='MATURE'}
   for z in o['soil']['root_zone_sensors']:
    if z['root_vwc']<.18:eligible.update(set(range(z['ridge_start'],z['ridge_end']+1))&active)
   remaining=set(eligible)
   while remaining and x.water_used<150-1e-9:
    if datetime.datetime.fromtimestamp(x.now(),TZ).date().isoformat()!=o['local_date'] or x.now()-o['time']>21600:
     o=x.observe('grid',gid);eligible2=set()
     for z in o['soil']['root_zone_sensors']:
      if z['root_vwc']<.18:eligible2.update(range(z['ridge_start'],z['ridge_end']+1))
     remaining&=eligible2
     if not remaining:break
    start,end=merge(remaining)[0];ids=set(range(start,end+1));remaining-=ids;dose=min(20.,(150-x.water_used)*64/len(ids))
    x.dispatch_water(start,end,dose,o,gid)
   x.settle()
  now=x.now()
  if daily:
   d=datetime.datetime.fromtimestamp(now,TZ);next_grid=datetime.datetime.combine(d.date()+datetime.timedelta(days=1),datetime.time(8),TZ).timestamp()
  else:next_grid=anchor+(math.floor((now-anchor)/259200)+1)*259200

def harvest(x):
 remaining=set(range(64));last_fail=None
 while remaining:
  x.required('WeatherApp__get_current_weather');o=x.required('FarmWorldApp__get_farm_overview');state={r['ridge_id']:r for r in o['ridges_overview']}
  ready=[r for r in remaining if state[r]['growth_stage']=='MATURE' and state[r]['grain_moisture_pct']<=25.]
  if not ready:x.wait(x.now()+86400);continue
  start,end=merge(ready)[0];end=min(end,start+3)
  status=x.required('TractorApp__get_status')
  if status['fuel_tank_l']<30:x.required('TractorApp__refuel',liters=float(100-status['fuel_tank_l']))
  r=x.call('TractorApp__harvest',start_ridge=start,end_ridge=end)
  if r.get('error'):
   last_fail=r['error'];x.log({'event':'recoverable_harvest_refusal','reason':last_fail,'retry_after_seconds':86400});x.wait(x.now()+86400);continue
  if r.get('warning'):raise PilotStop('Harvest warning requires safety review')
  remaining-=set(range(start,end+1))
  status=x.required('TractorApp__get_status')
  if status['grain_bin_kg']>0:x.required('TractorApp__unload_grain')
  elif status['grain_bin_kg']==0:x.log({'event':'unload_not_applicable_no_grain','harvested_range':[start,end]})
  else:raise PilotStop('invalid grain bin quantity')
 inventory=x.required('FarmWorldApp__get_inventory')
 if inventory['harvest_grain_kg']>0:
  x.required('FarmWorldApp__dry_grain',target_moisture_pct=14.);x.required('FarmWorldApp__store_grain')
 elif inventory['harvest_grain_kg']==0:x.log({'event':'dry_store_not_applicable_no_grain'})
 else:raise PilotStop('invalid harvest buffer quantity')
 x.required('FarmWorldApp__get_inventory');x.required('FarmWorldApp__get_farm_overview')


def identity():
 paths=[Path(__file__),ROOT/'fairy/scenarios/maize/basic_management.py',
        ROOT/'fairy/scenarios/maize/scenario_basic_w01_v1.py',ROOT/'fairy/scenarios/maize/scenario_basic_n01_v1.py']
 paths+=sorted(p for p in DATA.iterdir() if p.is_file())
 from fairy.contracts.cli import fingerprint
 result={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
 result['native_runtime']=fingerprint()['source_hash']
 return result

def main():
 import argparse
 parser=argparse.ArgumentParser()
 parser.add_argument('action',choices=['preflight','run']);parser.add_argument('--candidate',choices=['W01','N01'],required=True)
 parser.add_argument('--gate',type=Path,required=True);parser.add_argument('--output',type=Path)
 args=parser.parse_args()
 sid='scenario_maize_l3_basic_'+args.candidate.lower()+'_v1'
 scenario=get_scenario_class(sid)(seed=0);scenario.setup();engine=Engine(None,scenario)
 anchor=datetime.datetime.fromisoformat(json.loads((DATA/'schedule.json').read_text())['grid_anchor']).timestamp()
 assert anchor==scenario.start_time
 if args.action=='preflight':
  save(args.gate,{'status':'passed','candidate':args.candidate,'identity':identity(),'checks':['registered setup','native event graph build','explicit anchor']});return
 gate=json.loads(args.gate.read_text())
 if gate.get('status')!='passed' or gate.get('candidate')!=args.candidate or gate.get('identity')!=identity():
  raise RuntimeError('Stale or mismatched preflight; no actions executed')
 if args.output is None or args.output.exists():raise RuntimeError('A new independent output directory is required')
 x=Executor(scenario,engine,args.output)
 save(args.output/'started.json',{'identity':identity(),'candidate':args.candidate,'reference_only':True})
 try:
  setup_operations(x,120*1.2864/.46)
  manage(x,'water_threshold_v1' if args.candidate=='W01' else 'none')
  harvest(x)
 finally:
  save(args.output/'workflow.json',scenario.workflow.to_dict())
  save(args.output/'evaluation.json',scenario.validate().to_dict())

if __name__=='__main__':main()
