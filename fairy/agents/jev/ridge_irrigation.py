"""Opt-in maize reference-depth arithmetic for the native fixed irrigation apps.

Only logged receipts, public task/geometry/allowance and acquired probes are
used. Selecting irrigation is still a model decision; references are not
unconditional irrigation orders. No simulator calls or hidden water reads.
"""
from __future__ import annotations
import math
from datetime import datetime, timezone, timedelta
from fairy.agents.jev.management import get, number, successes, timestamp, EPS

VERSION = 'ridge-irrigation-reference-v2'
MM_PER_HOUR = 5.0  # Native IrrigationApp._start_irrigation conversion.
METHODS = {'irrigate':('start','end','hours'),
           'irrigate_range':('start','end','duration_hours'),
           'irrigate_ridge':('ridge_id',None,'duration_hours')}


def supported(tool):
    from fairy.apps.farm_world.irrigation_app import IrrigationApp
    app=tool.class_instance
    return (tool.name in METHODS and isinstance(app,IrrigationApp)
            and type(app)._start_irrigation is IrrigationApp._start_irrigation)


def remaining_quota(facts):
    limits=facts.get('inventory',{}).get('limits_and_usage',{})
    quota,used=number(limits.get('irrigation_quota_mm_total')),number(limits.get('irrigation_used_mm_total',0.))
    return max(0.,quota-used) if quota is not None and used is not None else None


def hour_limit(tool,args,facts):
    if not supported(tool):return None
    quota=remaining_quota(facts);size=len(facts.get('ridges',[]))
    start,end,hours=METHODS[tool.name]
    lo=args.get(start);hi=args.get(end) if end else lo
    if quota is None or not size or type(lo)!=int or type(hi)!=int or not 0<=lo<=hi<size:return None
    return quota*size/(MM_PER_HOUR*(hi-lo+1))


def build(task,facts,management,now):
    size=len(facts.get('ridges',[]));plan=management['plan'];planted=management['ledger']['planting_timestamps']
    result=dict(version=VERSION,mm_per_hour=MM_PER_HOUR,scope=None,active=None,
                remaining_quota_field_mm=remaining_quota(facts),pending_ridges=[],rounds=[])
    # A zoned prescription must keep its own scope. Do not silently turn it
    # into a whole-field water order.
    import re
    windows=plan.get('irrigation_windows',[])
    if len(re.findall('参考灌溉安排为',task)) != 1:return result
    if (not size or not planted or not windows or not plan.get('long_horizon')
            or re.search(r'分区|定向|仅对|部分田|zone',task,re.I)):
        return result
    if len({day for day,mm in windows})!=len(windows) or any(day<0 or mm<=0 for day,mm in windows):return result
    anchor=max(planted.values())
    if not all(r.get('planted') or r.get('harvested') for r in facts['ridges']):return result
    windows=sorted(windows);result['scope']='whole-field reference; operation chosen by model after observation'
    rounds=[dict(index=i+1,reference_day=day,at=anchor+day*86400,target_mm_per_ridge=mm,
                 assigned_mm_by_ridge={str(r):0. for r in range(size)}) for i,(day,mm) in enumerate(windows)]
    pending=set();last_irrigation={};last_irrigation_index={}
    for step_index,(step,data) in enumerate(successes(facts)):
        name=get(step,'tool_name','') or '';method=name.split('__')[-1]
        if method in METHODS:
            # "irrigation_pending" reports an existing job, not another dose.
            if data.get('status')!='irrigation_started':continue
            ids=data.get('irrigated_ridges');depth=number(data.get('estimated_water_mm_per_ridge'))
        elif method=='apply_fertigation':
            ids=data.get('fertigated_ridges');depth=number(data.get('carrier_water_mm'))
        else:continue
        if not isinstance(ids,list) or depth is None or depth<=0:continue
        when=timestamp(get(step,'time_before'))
        if when is None:when=timestamp(get(step,'time_after'))
        if when is None:when=timestamp(get(step,'time'))
        if when is None:continue  # Unknown timing cannot attest a management round.
        due=[r for r in rounds if r['at']<=when+EPS]
        current=due[-1] if due else None
        ready=number(data.get('effect_ready_at'))
        for rid in set(ids):
            if type(rid)!=int or not 0<=rid<size:continue
            last_irrigation[rid]=when
            last_irrigation_index[rid]=step_index
            if ready is not None and ready>now:pending.add(rid)
            if current:current['assigned_mm_by_ridge'][str(rid)]+=depth
    for r in rounds:
        r['remaining_mm_by_ridge']={rid:max(0.,r['target_mm_per_ridge']-v) for rid,v in r['assigned_mm_by_ridge'].items()}
        r['remaining_mm_by_ridge']={rid:v for rid,v in r['remaining_mm_by_ridge'].items() if v>EPS}
        r['status']=('REFERENCE_AMOUNT_ACCOUNTED' if not r['remaining_mm_by_ridge'] else 'DUE') if r['at']<=now else 'UPCOMING'
    due=[r for r in rounds if r['at']<=now+EPS]
    if due and pending and not due[-1]['remaining_mm_by_ridge']:
        due[-1]['status']='AMOUNT_ACCOUNTED_PENDING_EFFECT'
    result.update(rounds=rounds,active=due[-1] if due else None,pending_ridges=sorted(pending),
        accounting_note='Actual started/queued water is reserved against its latest due reference window; pending is not confirmed soil response. Older missed windows remain explicit, not automatically stacked.')
    # Fresh public rooting-zone estimates; shallow probes cannot substitute.
    observation=None
    for step_index,(step,data) in enumerate(successes(facts)):
        if (get(step,'tool_name','') or '').endswith('__read_root_zone_sensors'):
            when=timestamp(get(step,'time_after'))
            if when is None:when=timestamp(get(step,'time'))
            observation=dict(at=when,step_index=step_index,zones=data.get('root_zone_sensors',[]),noise=number(data.get('measurement_noise_vwc')) or 0.)
    values={};fresh=False
    if observation and observation['at'] is not None:
        # Native maize settles by its existing Asia/Shanghai simulation date.
        cst=timezone(timedelta(hours=8))
        fresh=(observation['at']<=now and datetime.fromtimestamp(observation['at'],cst).date()==datetime.fromtimestamp(now,cst).date())
        if fresh:
            for z in observation['zones']:
                lo,hi=z.get('ridge_start'),z.get('ridge_end');v=number(z.get('root_vwc'))
                if type(lo)==type(hi)==int and 0<=lo<=hi<size and v is not None:
                    for rid in range(lo,hi+1):
                        if last_irrigation_index.get(rid,-1)<observation['step_index']:
                            values[str(rid)]=v+observation['noise']
    result['observations']=dict(fresh=fresh,observed_upper_vwc_by_ridge=values,at=observation['at'] if observation else None,
                                note='Zone-average observation proxy plus reported noise; not hidden per-ridge truth. Native tool remains authoritative.')
    return result


def target(tool,facts,management):
    """Deterministic contiguous batch for a single-farm maize reference window."""
    if not supported(tool):return None
    from fairy.agents.jev.menu import scene_world
    if getattr(scene_world(tool),'crop_type',None)!='maize':return None
    ctx=(management or {}).get('ridge_irrigation') or {};active=ctx.get('active')
    if not active or not active.get('remaining_mm_by_ridge'):return None
    obs=ctx.get('observations',{});values=obs.get('observed_upper_vwc_by_ridge',{})
    if not obs.get('fresh'):return None
    remaining=active['remaining_mm_by_ridge'];pending=set(ctx.get('pending_ridges',[]))
    eligible=sorted(int(r) for r in remaining if r in values and values[r]<tool.class_instance.irrigation_stop_vwc and int(r) not in pending)
    if not eligible:return None
    start=eligible[0];end=start;depth=remaining[str(start)]
    if METHODS[tool.name][1] is not None:
        allowed=set(eligible)
        while end+1 in allowed and abs(remaining[str(end+1)]-depth)<=EPS:end+=1
    quota=remaining_quota(facts);size=len(facts['ridges'])
    if quota is not None:depth=min(depth,quota*size/(end-start+1))
    hours=math.floor(depth/MM_PER_HOUR*1e9)/1e9
    if hours<=0:return None
    a,b,h=METHODS[tool.name];args={a:start,h:hours}
    if b:args[b]=end
    return dict(arguments=args,reference_index=active['index'],reference_day=active['reference_day'],
                target_mm_per_ridge=depth,reason='Explicit whole-field reference depth / native 5 mm per hour; actual per-ridge prior coverage, fresh acquired root probes and public remaining quota. Single native action; no hidden irrigation or auto time advance.')


def blocker(tool,facts,management):
    if not supported(tool):return None
    quota=remaining_quota(facts)
    if quota is not None and quota<=EPS:return 'No remaining public irrigation allowance.'
    from fairy.agents.jev.menu import scene_world
    if getattr(scene_world(tool),'crop_type',None)!='maize':return None
    ctx=(management or {}).get('ridge_irrigation') or {};active=ctx.get('active')
    pending=set(ctx.get('pending_ridges',[]))
    if pending and (len(pending)==len(facts.get('ridges',[])) or active and not active.get('remaining_mm_by_ridge')):
        return 'The reference delivery is already queued; wait until its reported ready time, then recheck root-zone probes. Do not repeat the pending dose.'
    if not active or not active.get('remaining_mm_by_ridge'):return None
    if target(tool,facts,management) is None:
        return 'Current reference irrigation has no observed eligible target: read fresh root-zone probes, wait for pending delivery, or defer wet areas. Do not infer readiness from the calendar alone.'
    return None
