"""Full-season counterfactuals for calibrated selected scenes 03–20.

PYTHONHASHSEED=0 .venv/bin/python tests/wofost_selected20_experiments.py 16 correct /tmp/wofost-controls
Repeat with none and wrong, then replace the arm with verify.
Inputs and fixed calendars live in tests/data. Native truth is read only for
result auditing. Production scenes own their complete literal workflows.
"""
from collections import Counter
import ast,copy,hashlib,importlib,inspect,json,sys
from dataclasses import asdict
from datetime import date,datetime,time
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from fairy.scenarios.wofost_farm import FarmDefinition,WofostFarmScenario
from fairy.scenarios.wofost_events import PressureEvent,WeatherWindowEvent,DroughtEvent,install_scenario_events,scenario_events_snapshot
from fairy.apps.farm_world import FarmWorldApp,TractorApp,WeatherApp,DroneApp
from fairy.physics.soil_engine import SoilHydraulicModifier
from wofost_model_experiments import ModelExperimentEngine
BASE=Path('/tmp/fairy-selected20-controls')
CLASSES={'pressure':PressureEvent,'weather':WeatherWindowEvent,'drought':DroughtEvent}
def config(n): return json.loads((ROOT/'tests/data/wofost_selected20'/f'{n:02d}.json').read_text())
def definition(c):
    kw=dict(c['world']);kw['sowing_date']=date.fromisoformat(kw.get('sowing_date','2019-04-28'));kw['end_date']=date.fromisoformat(kw.get('end_date','2019-11-15'))
    kw.setdefault('reference_id','lille');kw.setdefault('seed_type','SOYBEAN_901');kw.setdefault('timezone_name','Europe/Paris');kw.setdefault('num_ridges',64)
    kw.setdefault('base_fertilizer_kg',0.);kw.setdefault('warehouse_fertilizer_kg',0.);kw.setdefault('warehouse_pesticide_l',0.)
    kw.setdefault('required_field_preparation_ops',('level','form_ridges'));kw.setdefault('planting_density_plants_m2',45.)
    return FarmDefinition(**kw)
def declarations(c):
    ans=[]
    for item in c['events']:
        d=dict(item);kind=d.pop('type')
        for k in ('start','end'): d[k]=date.fromisoformat(d[k])
        ans.append(CLASSES[kind](**d))
    return ans

def make_scene(c,arm):
    world=definition(c)
    class Trial(WofostFarmScenario):
        WORLD=world;DESCRIPTION=c['title']
        def init_and_populate_apps(self):
            super().init_and_populate_apps()
            f=self.get_typed_app(FarmWorldApp)
            for patch in c.get('soil_patches',[]):
                mod=SoilHydraulicModifier(**patch['values']);f.physics.soil.set_hydraulic_modifiers({rid:mod for rid in range(patch['start'],patch['end']+1)})
            if c.get('planting_windows'): f.configure_planting_windows(c['planting_windows'])
            self.apps.append(DroneApp(f,self.get_typed_app(WeatherApp),name='SurveyDrone',speed_ms=5.,effective_ridges_per_pass=7,takeoff_overhead_s=30,min_battery_pct=20.,battery_pct_per_ridge=1.))
        def build_events_flow(self):
            install_scenario_events(self,declarations(c));return []
        def run_experiment(self,s):
            for item in c['actions']:
                if item.get('arms') and arm not in item['arms']: continue
                if 'at' in item:
                    day=date.fromisoformat(item['at']);s.advance_to(item['label'],datetime.combine(day,time(item.get('hour',7)),s.timezone).timestamp())
                    print(c['number'],arm,item['at'],flush=True)
                else:
                    try:
                        receipt=s.call(item['label'],item['tool'],item.get('args',{}))
                    except RuntimeError:
                        receipt=s.workflow.dag[s.previous].content
                        if not item.get('expected_error') or item['expected_error'] not in str(receipt): raise
                        assert s.workflow.dag[s.previous].time_before==s.workflow.dag[s.previous].time_after

                if item.get('checkpoint'):
                    f=self.get_typed_app(FarmWorldApp)
                    self.checkpoints=getattr(self,'checkpoints',{})
                    self.checkpoints[item['checkpoint']]={'day':str(s.today),'native':{str(rid):copy.deepcopy(run.pcse) for rid,run in f.physics.crop_backend._runs.items()},'biotic':{str(rid):asdict(state) for rid,state in f.physics.biotic.states.items()},'public_receipt':receipt if 'at' not in item else None}
            f=self.get_typed_app(FarmWorldApp)
            self.audit={'arm':arm,'world':asdict(self.WORLD),'events':scenario_events_snapshot(f),'native':{str(rid):{'pcse':copy.deepcopy(run.pcse),'specification':copy.deepcopy(run.specification),'water_mm':run.cumulative_irrigation_mm,'fertilizer_kg':run.cumulative_fertilizer_kg} for rid,run in f.physics.crop_backend._runs.items()},'resources':f._management_regime.to_dict(),'warehouse_grain_kg':f._inventory.warehouse_grain_kg,'tractor':self.get_typed_app(TractorApp).get_state(),'checkpoints':getattr(self,'checkpoints',{})}
    return Trial()

def run(n,arm):
    c=config(n);out=BASE/f'{n:02d}';out.mkdir(parents=True,exist_ok=True)
    scene=make_scene(c,arm);engine=ModelExperimentEngine(None,scene);w=engine.run_experiment()
    scene.audit['workflow']=w.to_dict();scene.audit['validation']=asdict(scene.validate(SimpleNamespace(workflow=w,time_manager=engine.time_manager)))
    (out/f'{arm}.json').write_text(json.dumps(scene.audit,ensure_ascii=False,default=str,indent=2))
    print('RESULT',n,arm,scene.audit['warehouse_grain_kg'],scene.audit['resources'],scene.audit['validation']['success'],flush=True)

def arm_stats(d, group_prefixes=()):
    w=d['world'];area=w['field_length_m']*w['ridge_width_m']/10000
    ops=[x for x in d['workflow'].values() if not x['content'].get('error') and x['content'].get('status') not in ('partial','failed','error') and x['tool_name'].endswith(('__plant_seeds','__mechanical_weed_control','__apply_fungicide','__spray_pesticide','__apply_herbicide','__apply_pesticide_manual','__irrigate','__harvest','__level','__form_ridges'))]
    dates={(x['tool_name'],datetime.fromisoformat(x['time']).date().isoformat()) for x in ops}
    rounds={(x['tool_name'],next((p for p in group_prefixes if p in x['name']),datetime.fromisoformat(x['time']).date().isoformat())) for x in ops}
    refueled=0.
    steps=list(d['workflow'].values())
    for i,x in enumerate(steps):
        if x['tool_name'].endswith('__refuel') and not x['content'].get('error'):
            assert steps[i-1]['tool_name'].endswith('__get_status')
            before=steps[i-1]['content']['fuel_tank_l']
            if 'fuel_tank_l' not in x['content']:assert before==100 and 'already full' in x['content'].get('msg','')
            refueled+=x['content'].get('fuel_tank_l',before)-before
    return {'warehouse_grain_kg_at_13pct':d['warehouse_grain_kg'],'native_mean_dm_kg_ha':sum(r['pcse']['TWSO'] for r in d['native'].values())/w['num_ridges'],'native_total_dm_kg':sum(r['pcse']['TWSO']*area for r in d['native'].values()),'native_irrigation_mm_mean':sum(float(r['pcse'].get('TOTIRR') or 0)*10 for r in d['native'].values())/w['num_ridges'],'native_ET_mm_mean':sum(10*(float(r['pcse'].get('WTRAT') or 0)+float(r['pcse'].get('EVST') or 0)) for r in d['native'].values())/w['num_ridges'],'resource_usage':d['resources'],'fuel_used_l':w['tractor_fuel_l']+refueled-d['tractor']['fuel_tank_l'],'tool_calls':len(d['workflow']),'field_operation_rounds':len(rounds),'field_operation_round_groups':sorted(rounds),'field_operation_round_dates':sorted(dates),'completion_success':d['validation']['success']}

def audit_arm(d,allow_errors=False):
    expected=Counter(range(d['world']['num_ridges']));stored=[];harvest=[];water=chem=0.;errors=[];last=0
    for name,step in d['workflow'].items():
        c=step['content'];a=step['tool_args'];t=step['tool_name'].split('__')[1]
        assert last<=step['time_before']<=step['time_after'];last=step['time_after']
        if c.get('error') or c.get('status') in ('partial','failed','error'):
            errors.append({'name':name,'content':c});continue
        if t in ('inspect_crop_health','inspect_emergence'):
            scope=set(range(a['start_ridge'],a['end_ridge']+1));assert set(c['covered_ridges'])==set(map(int,c['observations']))==scope
        if t=='fly_survey':assert c['surveyed_ridges']==list(range(a['start_ridge'],a['end_ridge']+1)) and c['battery_remaining_pct']>=20
        if t=='irrigate':water+=5*a['hours']*(a['end']-a['start']+1)/d['world']['num_ridges']
        if t in ('apply_fungicide','spray_pesticide','apply_herbicide'):chem+=(a['end_ridge']-a['start_ridge']+1)*a['liters_per_ridge']*.001
        if t=='apply_pesticide_manual':
            assert a.get('advance_time',True) is True and step['time_after']>step['time_before']
            chem+=a['liters_per_ridge']*a.get('ridge_count',1)*.001
        if t=='harvest':harvest+=c['harvested_ridges']
        if t=='store_grain':stored+=c['batch_ridge_ids'];assert c['storage_grain_moisture_pct']<=13.5 and not c.get('warning')
    assert not errors or allow_errors,errors
    assert Counter(stored)==Counter(harvest)==expected
    assert abs(water-d['resources']['irrigation_used_mm_total'])<1e-6
    assert abs(chem-d['resources']['active_ingredient_used_kg'])<1e-6
    assert d['tractor']['grain_bin_kg']==0
    if not errors:assert d['validation']['success']
    return errors

def check_controls(n):
    c=config(n);arms={key:json.loads((BASE/f'{n:02d}'/(key+'.json')).read_text()) for key in ('correct','none','wrong')}
    good=arms['correct'];errors={}
    for key,d in arms.items():
        errors[key]=audit_arm(d,key=='wrong' and c.get('allow_wrong_errors',False))
        assert d['world']==good['world'] and d['events']['events']==good['events']['events'] and d['events']['weather_changes']==good['events']['weather_changes']
        for rid,r in d['native'].items():
            assert r['pcse']['DVS']>=2 and r['specification']==good['native'][rid]['specification']
    if n==20:
        from datetime import date, time
        from zoneinfo import ZoneInfo
        assert good['world']['field_length_m']==2000 and good['world']['num_ridges']==64
        assert good['resources']['max_machine_passes'] is None
        steps=list(good['workflow'].values())
        pre=[x for x in steps if x['tool_name'].endswith('__harvest') and '2019-09-22' in x['time']]
        assert [r for x in pre for r in x['content']['harvested_ridges']]==list(range(26))
        assert all(x['time_after']-x['time_before']==1830 for x in pre)
        unload=[x for x in steps if x['tool_name'].endswith('__unload_grain') and '2019-09-22' in x['time']]
        assert len(unload)==26 and all(x['time_after']-x['time_before']==480 for x in unload)
        midnight=datetime(2019,9,23,tzinfo=ZoneInfo('Europe/Paris')).timestamp()
        assert pre[-1]['time_after']<midnight and unload[-1]['time_after']+1830>midnight
        rows=next(x['content']['ridges'] for x in steps if x['name'].endswith('雨前两区真实阶段粮水'))
        assert rows[0]['growth_stage']==rows[32]['growth_stage']=='R8'
        assert rows[0]['grain_moisture_pct']<=18<rows[32]['grain_moisture_pct']
        forecast=next(x['content'] for x in steps if x['name'].endswith('明日降雨预报'))
        assert '15.0' in str(forecast)
        for d in arms.values():
            final_inventory=next(x['content'] for x in d['workflow'].values() if x['name'].endswith('全季库存交付核验'))
            assert final_inventory['seed_stock']['SOYBEAN_901']==664000
            stat=arm_stats(d,c.get('operation_round_group_prefixes',()))
            assert abs(stat['fuel_used_l']-(5100-final_inventory['fuel_liters']-d['tractor']['fuel_tank_l']))<1e-5
        assert good['warehouse_grain_kg']>arms['wrong']['warehouse_grain_kg']+.01
    if n==17:
        allocation=next(x['content']['ridges'] for x in good['workflow'].values() if x['name'].endswith('旱期真实阶段'))
        assert allocation[0]['growth_stage']!=allocation[32]['growth_stage']
        assert abs(good['resources']['irrigation_used_mm_total']-arms['wrong']['resources']['irrigation_used_mm_total'])<1e-6
    if n==11:
        soil=next(r['content']['soil_sensors'] for r in good['workflow'].values() if r['name'].endswith('人工前土壤湿度'))
        assert sum(x['vwc'] for x in soil)/len(soil)>.405
    kind=c.get('compare','yield')
    a,b,z=[arms[k]['warehouse_grain_kg'] for k in ('correct','none','wrong')]
    if kind=='yield':assert a>b+.01 and a>z+.01,(n,a,b,z)
    elif kind=='resource':
        assert abs(a-b)<max(1.,a*.001) and abs(a-z)<max(1.,a*.001)
        assert arms['wrong']['resources']['active_ingredient_used_kg']>good['resources']['active_ingredient_used_kg']
    elif kind=='target_resource':
        assert a>b+.01 and abs(a-z)<max(1.,a*.001)
        assert arms['wrong']['resources']['active_ingredient_used_kg']>good['resources']['active_ingredient_used_kg']
    elif kind=='recovery':
        before=next(r['content']['root_zone_sensors'] for r in good['workflow'].values() if r['name'].endswith('扩展期缺水根水'))
        after=next(r['content']['root_zone_sensors'] for r in good['workflow'].values() if r['name'].endswith('补水后根区水分'))
        canopy=next(r['content']['canopy_sensors'] for r in good['workflow'].values() if r['name'].endswith('补水后冠层差距'))
        assert after[2]['root_vwc']>before[2]['root_vwc']+.03
        target=sum(x['ndvi_proxy'] for x in canopy if x['ridge_id'] in (25,38))/2
        reference=sum(x['ndvi_proxy'] for x in canopy if x['ridge_id'] not in (25,38))/4
        assert target<reference-.03,(target,reference)
        assert a>b+.01 and abs(a-z)<max(1.,a*.001)
        assert arms['wrong']['resources']['active_ingredient_used_kg']>good['resources']['active_ingredient_used_kg']
    elif kind=='window':assert errors['wrong'] and a>b+.01
    elif kind=='harvest':assert a>b+.01 and a>z+.01
    else:raise ValueError(kind)
    return arms,{'passed':True,'criterion':kind,'gain_over_none_pct':100*(a/b-1),'gain_over_wrong_pct':100*(a/z-1),'expected_errors':errors,'arms':{k:arm_stats(d,c.get('operation_round_group_prefixes',())) for k,d in arms.items()}}

if __name__=='__main__':
    BASE=Path(sys.argv[3]) if len(sys.argv)>3 else BASE
    number=int(sys.argv[1]);arm=sys.argv[2]
    if arm=='verify':
        _,audit=check_controls(number)
        path=BASE/f'{number:02d}'/'comparison_audit.json'
        path.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
        print('VERIFIED',number,path)
    else:
        if arm not in ('correct','none','wrong'):raise ValueError('Use correct, none, wrong or verify')
        run(number,arm)
