"""Audit saved controls and ordinary CLI execution/replay for one multi-farm scene."""
from collections import Counter
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from fairy.controllers.engine import Engine
from wofost_multi4_experiments import recipe

UUID_KEYS = {'action_id','op_id','mission_id','inspection_id'}
def clean(value):
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if k not in UUID_KEYS}
    if isinstance(value,list):return [clean(v) for v in value]
    return value

def audit(number, output):
    c=recipe(number);directory=Path(output)/f'{number:02d}'
    arms={a:json.loads((directory/(a+'.json')).read_text()) for a in ('correct','none','wrong')}
    good=arms['correct']; summaries={}
    for arm,d in arms.items():
        for key in ('fields','initial_stock','regional_events','regional_changes'):
            assert d[key]==good[key],(arm,key)
        assert d['validation']['success']
        for fid,event in d['events'].items():
            assert event.get('events')==good['events'][fid].get('events')
        planted={f['farm_id']:[] for f in d['fields']};harvested=deepcopy(planted)
        water={f['farm_id']:0. for f in d['fields']};fert=deepcopy(water);chem=deepcopy(water)
        nr={f['farm_id']:f['num_ridges'] for f in d['fields']}
        last=0.;errors=[]
        for name,s in d['workflow'].items():
            assert last<=s['time_before']<=s['time_after'];last=s['time_after']
            a=s['tool_args'];receipt=s['content'];method=s['tool_name'].split('__')[1]
            if s.get('error_stage') or (isinstance(receipt,dict) and (receipt.get('error') or receipt.get('status') in ('partial','failed','error'))):
                assert name in d['expected_failures'],(arm,name,receipt)
                errors.append(name);continue
            if method in ('inspect_emergence','inspect_crop_health'):
                assert set(receipt['covered_ridges'])==set(range(a['start_ridge'],a['end_ridge']+1))
            if method=='fly_survey':
                assert receipt['surveyed_ridges']==list(range(a['start_ridge'],a['end_ridge']+1)) and receipt['battery_remaining_pct']>=20
            if method=='plant_seeds':planted[a['farm_id']]+=list(range(a['start_ridge'],a['end_ridge']+1))
            if method=='harvest':harvested[a['farm_id']]+=receipt['harvested_ridges']
            if method=='irrigate':
                fid=s['tool_name'].split('_Irrigation__')[0];water[fid]+=a['hours']*5*(a['end']-a['start']+1)/nr[fid]
            if method=='apply_fertilizer':fert[a['farm_id']]+=(a['end_ridge']-a['start_ridge']+1)*a['kg_per_ridge']
            if method=='base_fertilize':fert[a['farm_id']]+=a['total_kg']
            if method in ('spray_pesticide','apply_fungicide'):chem[a['farm_id']]+=(a['end_ridge']-a['start_ridge']+1)*a['liters_per_ridge']*.001
        for fid in planted:
            assert Counter(planted[fid])==Counter(harvested[fid])==Counter(range(nr[fid]))
            assert all(run['pcse']['DVS']>=2 for run in d['native'][fid].values())
            assert all(run['specification']==good['native'][fid][rid]['specification'] for rid,run in d['native'][fid].items())
            r=d['resources'][fid]
            assert abs(water[fid]-r['irrigation_used_mm_total'])<1e-6
            assert abs(fert[fid]-r['fertilizer_used_kg'])<1e-6
            assert abs(chem[fid]-r['active_ingredient_used_kg'])<1e-6
        assert d['tractor']['grain_bin_kg']==d['tractor']['seed_hopper']==0
        # The stock difference includes only material consumed by actual public tools.
        fuel=d['initial_stock']['fuel_liters']+100-d['warehouse']['stock']['fuel_liters']-d['tractor']['fuel_tank_l']
        farm_stats=deepcopy(d['validation']['metadata'])
        for fid,stats in farm_stats.items():
            rows=list(d['native'][fid].values())
            stats['native_dm_kg_ha']=stats['native_dm_kg']/stats['area_ha']
            stats['stored_grain_kg_ha']=stats['stored_grain_kg']/stats['area_ha']
            stats['native_irrigation_mm_mean']=sum(float(r['pcse'].get('TOTIRR') or 0)*10 for r in rows)/len(rows)
            stats['native_evapotranspiration_mm_mean']=sum((float(r['pcse'].get('WTRAT') or 0)+float(r['pcse'].get('EVST') or 0))*10 for r in rows)/len(rows)
        summaries[arm]={'farms':farm_stats,'total_stored_kg':sum(f['stored_grain_kg'] for f in d['validation']['metadata'].values()),
            'fuel_used_l':fuel,'tool_calls':d['tool_calls'],'field_operation_rounds':d['field_operation_rounds'],
            'operation_round_groups':d['operation_round_groups'],'expected_refusals':errors}
    a,b,z=[summaries[k]['total_stored_kg'] for k in ('correct','none','wrong')]
    assert a>b+.01 and a>z+.01,(number,a,b,z)
    if number==1:
        for key in ('correct','wrong'):
            assert sum(arms[key]['resources'][fid]['irrigation_used_mm_total'] for fid in planted)==150
        checks=good['checkpoints']
        shallow=next(iter(checks['土壤差异诊断与额外一轮水_shallow_soil']['farms']['shallow']['pcse'].values()))
        deep=next(iter(checks['土壤差异诊断与额外一轮水_deep_soil']['farms']['deep']['pcse'].values()))
        assert shallow['RFTRA']<.8 and deep['RFTRA']>.99
    if number==2:
        for arm in ('correct','wrong'):
            assert abs(sum(x['active_ingredient_used_kg'] for x in arms[arm]['resources'].values())-.1888)<1e-8
            assert abs(arms[arm]['warehouse']['stock']['pesticide_liters']-1.2)<1e-6
        for fid,kind in [('west','pest'),('east','disease')]:
            observations=good['checkpoints'][fid+'_diagnosis']['response']['observations'].values()
            assert sum(r[kind+'_present'] and r[kind+'_confidence']>.75 for r in observations)>=3
    if number==3:
        for arm in ('correct','wrong'):
            assert abs(sum(r['fertilizer_used_kg'] for r in arms[arm]['resources'].values())-200)<1e-6
            assert arms[arm]['warehouse']['stock']['fertilizer_kg']==0
        assert good['resources']['soybean']['fertilizer_used_kg']==0
        assert good['validation']['metadata']['maize']['stored_grain_kg']>arms['wrong']['validation']['metadata']['maize']['stored_grain_kg']+100
    if number==4:
        checks=good['checkpoints']
        early=checks['唯一雨前晴日共享割台优先级_early_rows']['response']['ridges']
        late=checks['唯一雨前晴日共享割台优先级_late_rows']['response']['ridges']
        assert all(r['growth_stage']=='R8' and r['grain_moisture_pct']<=18 for r in early)
        assert all(r['growth_stage']=='R8' and r['grain_moisture_pct']>18 for r in late)
        steps=list(good['workflow'].values())
        pre=[s for s in steps if s['tool_name']=='Tractor__harvest' and '2019-09-22' in s['time']]
        unloaded=[s for s in steps if s['tool_name']=='Tractor__unload_grain' and '2019-09-22' in s['time']]
        midnight=datetime(2019,9,23,tzinfo=ZoneInfo('Europe/Paris')).timestamp()
        assert [s['tool_args']['start_ridge'] for s in pre]==list(range(26))
        assert all(s['tool_args']['farm_id']=='early' and s['time_after']-s['time_before']==1830 for s in pre)
        assert len(unloaded)==26 and all(s['time_after']-s['time_before']==480 for s in unloaded)
        assert unloaded[-1]['time_after']<midnight<unloaded[-1]['time_after']+1830
        assert pre[0]['content']['grain_kg_added']>1000  # Two long ridges exceed the 2t bin.
        assert len(arms['wrong']['expected_failures'])==1
        assert all(r['max_machine_passes'] is None for r in good['resources'].values())
        for arm in ('none','wrong'):
            for fid in good['native']:
                assert abs(arms[arm]['validation']['metadata'][fid]['native_dm_kg']-good['validation']['metadata'][fid]['native_dm_kg'])<1e-6
    module=importlib.import_module(c['module']);scene=getattr(module,c['class_name'])();engine=Engine(None,scene)
    plan=engine.build_oracle_workflow(run_oracle=False).to_dict();sid=module.SCENARIO_ID
    built=json.loads((directory/'cli'/(sid+'.oracle.json')).read_text())
    replay=json.loads((directory/'cli'/(sid+'.replay.json')).read_text())
    report=json.loads((directory/'cli'/(sid+'.run_report.json')).read_text())
    assert list(plan)==list(built)==list(replay)==list(good['workflow'])
    for name,p in plan.items():
        assert p['content'] is None
        for key in ('name','tool_name','tool_args','depends_on','op_type','time'):
            assert p[key]==built[name][key]==replay[name][key],(name,key)
        for key in ('time_before','time_after'):
            assert built[name][key]==replay[name][key]==good['workflow'][name][key],(name,key)
        assert clean(built[name]['content'])==clean(replay[name]['content']),name
        assert not replay[name].get('error_stage')
    assert report['status']=='completed' and report['evaluation']['validation']['success']
    for fid,values in good['validation']['metadata'].items():
        assert report['evaluation']['validation']['metadata'][fid]==values
    source=Path(module.__file__)
    result={'number':number,'title':c['title'],'scenario_id':sid,'source_path':str(source.relative_to(ROOT)),
        'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'status':'calibrated',
        'proof':'source plan == real Oracle == fresh replay; identical control world; full harvest/storage/resources audited',
        'source_plan_and_real_times_match':True,'all_farms_completed':True,'arms':summaries,
        'gain_over_no_focal_management_pct':100*(a/b-1),'gain_over_wrong_management_pct':100*(a/z-1)}
    (directory/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='arms'},ensure_ascii=False))
    return result

if __name__=='__main__':audit(int(sys.argv[1]),sys.argv[2])
