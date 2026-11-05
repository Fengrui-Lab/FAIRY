"""Public receipt-based observation coverage and long-horizon decision cues.

No forced actions, oracle calendar, hidden growth reads or synthetic success.
"""
from datetime import datetime,timezone
import re
from fairy.agents.jev import management as M
from fairy.agents.jev.receipts import COVERAGE_KEYS
VERSION='temporal-progress-v4'
MUTATIONS={'plant_seeds','replant_seeds','transplant','base_fertilize','apply_fertilizer','apply_fertigation',
           'irrigate','irrigate_range','irrigate_ridge','irrigate_ridges','drain','soak','puddle_and_level',
           'apply_pesticide','spray_pesticide','apply_fungicide','apply_herbicide','mechanical_weed_control','harvest'}

def when(step):
    t=M.timestamp(M.get(step,'time_after'))
    return t if t is not None else M.timestamp(M.get(step,'time'))

def build(task,facts,now):
    from fairy.agents.jev.model_view import classify
    if M.number(now) is None:
        return dict(version=VERSION,observation_coverage=[],season_unfinished=False,seasonal_task=False,recent_observations=0,recent_sim_hours=None,observation_loop_pressure=False,next_step='Simulation time unknown; do not infer current observation coverage.')
    steps=facts.get('steps',[]);successful=list(M.successes(facts));changes={};unknown_changes={}
    positions={id(s):i for i,s in enumerate(steps)}
    scope_of=lambda s,d:tuple((M.get(s,'tool_args',{}) or {}).get(k,d.get(k)) for k in ('farm_id','plot_id'))
    for s,d in successful:
        if M.get(s,'tool_name','').split('__')[-1] in MUTATIONS and 'pending' not in str(d.get('status','')):
            scope=scope_of(s,d);ids=set()
            for key in (*COVERAGE_KEYS,'irrigated_ridges'):
                if isinstance(d.get(key),list):ids.update(x for x in d[key] if type(x)==int)
            if ids:
                for rid in ids:changes[scope,rid]=positions[id(s)]
            else:unknown_changes[scope]=positions[id(s)]
    date=datetime.fromtimestamp(now,M.CST).date()
    coverage={}
    for s,d in successful:
        i=positions[id(s)];t=when(s)
        scope_key=scope_of(s,d)
        if i<=unknown_changes.get(scope_key,-1) or t is None or t>now or datetime.fromtimestamp(t,M.CST).date()!=date or classify(s)!='observation':continue
        name=M.get(s,'tool_name','');args=M.get(s,'tool_args',{}) or {}
        scope={k:args[k] for k in ('farm_id','plot_id','asset_id') if k in args}
        if 'farm_id' in d:scope['farm_id']=d['farm_id']
        key=(name,tuple(sorted(scope.items())))
        row=coverage.setdefault(key,dict(tool=name,scope=scope,cycle_covered_ridges=set(),observations=0,last_at=None))
        row['observations']+=1;row['last_at']=datetime.fromtimestamp(t,M.CST).strftime('%Y-%m-%d %H:%M:%S')
        ids=[]
        for k in (*COVERAGE_KEYS,'inspected_ridges'):
            if isinstance(d.get(k),list):ids.extend(x for x in d[k] if type(x)==int)
        if isinstance(d.get('ridges'),list):ids.extend(x['ridge_id'] for x in d['ridges'] if isinstance(x,dict) and type(x.get('ridge_id'))==int)
        if type(d.get('ridge_id'))==int:ids.append(d['ridge_id'])
        row['cycle_covered_ridges'].update(rid for rid in ids if changes.get((scope_key,rid),-1)<i)
    rows=[]
    for row in coverage.values():
        ridges=facts.get('ridges',[])
        farm=row['scope'].get('farm_id')
        if farm in facts.get('farms',{}):ridges=facts['farms'][farm].get('ridges',[])
        expected={r['ridge_id'] for r in ridges}
        known=bool(row['cycle_covered_ridges'])
        row.update(cycle_covered_ridges=sorted(row['cycle_covered_ridges']),coverage_known=known,field_coverage_complete=bool(expected) and expected.issubset(row['cycle_covered_ridges']))
        # Unknown/unobserved targets are not work orders. Keep acquired coverage
        # as evidence without emitting an invented whole-field inspection queue.
        rows.append(row)
    tail=steps[-16:];read_count=sum(classify(s)=='observation' for s in tail)
    from fairy.agents.jev.establishment import material_indices
    material=material_indices(task,facts)
    recent_changes=any(i>=len(steps)-16 for i in material)
    known_times=[when(s) for s in tail if when(s) is not None]
    elapsed=max(0.,now-min(known_times)) if known_times else None
    units=facts.get('ridges',[]) or facts.get('plots',[])
    unfinished=bool(units) and any(u.get('planted') and not u.get('harvested') for u in units)
    from fairy.agents.jev.state_semantics import lifecycle
    seasonal=lifecycle(task)['seasonal_task']
    stagnant=sum((len(steps)-len(tail)+i) not in material for i,s in enumerate(tail))
    pressure=seasonal and unfinished and (read_count>=8 or len(tail)==16 and stagnant>=12) and not recent_changes and elapsed is not None and elapsed<86400
    from fairy.agents.jev.constraints import transplant_deadline
    partials=[]
    for p in facts.get('plots',[]):
        deadline=transplant_deadline(p['plot_id'],facts)
        if not p.get('planted') and p.get('transplanted_area_m2',0)>0 and deadline is not None:
            partials.append(dict(plot_id=p['plot_id'],remaining_area_m2=p['area_m2']-p['transplanted_area_m2'],finish_before_utc=datetime.fromtimestamp(deadline,timezone.utc).isoformat(),seconds_left=max(0,deadline-now),expired=now>=deadline))
    return dict(version=VERSION,partial_transplant_windows=partials,coverage_interpretation='Unobserved ridges are not automatically to-do. Follow task scope; do not turn zonal/sample checks into mandatory every-ridge scans. Batch adjacent requested observations within native limits rather than repeating single-ridge trips.',coverage_cycle='current UTC+08 date; actual crop work invalidates affected targets, not unrelated ridges; unknown-scope work invalidates that scope',
                observation_coverage=rows,season_unfinished=unfinished,seasonal_task=seasonal,
                material_progress_recent=recent_changes,
                recent_observations=read_count,recent_sim_hours=round(elapsed/3600,2) if elapsed is not None else None,
                observation_loop_pressure=pressure,
                next_step=('If current evidence is sufficient, continue feasible due care or choose a bounded wait to a meaningful recheck. Only inspect targets needed by the task or a specific unresolved condition. Repeated inspections or device charging are not seasonal progress.' if pressure else
                           'Use current-round work and actual readiness. Past inspection is not proof that later cycles are complete.'))


def criteria(criteria,guidance):
    result=dict(criteria);covered={r['tool'] for r in guidance['observation_coverage'] if r['field_coverage_complete']}
    for name in result:
        if name in covered:result[name]='[OBSERVATION MEMORY: this tool already covered the field this cycle; repeat only for a specific new need] '+result[name]
        if guidance['observation_loop_pressure'] and name.endswith(('__advance_time','__wait_for_notification')):
            result[name]='[SEASONAL RECHECK: prefer meaningful time advance once required observations are covered; honor pending effects and due care] '+result[name]
    return result


def wait_options(options,pressure):
    """Deduplicate equivalent durations, retaining deadline/readiness explanations."""
    result={};seen={};scale=dict(seconds=1,minutes=60,hours=3600,days=86400)
    priority=lambda label: int(any(x in label for x in ('ready','defer','next task check')))
    for label,v in options.items():
        secs=sum(M.number(x)*scale[k] for k,x in v.items()) if isinstance(v,dict) and all(k in scale and M.number(x) is not None for k,x in v.items()) else M.number(v)
        if secs is None or secs<=0:continue
        old=seen.get(secs)
        if old is not None:
            if priority(label)<=priority(old):continue
            result.pop(old)
        if pressure and secs==86400:label+=' [seasonal recheck; continue due care, not a maturity prediction]'
        seen[secs]=label;result[label]=v
    return result
