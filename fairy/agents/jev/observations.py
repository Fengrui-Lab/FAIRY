"""Receipt-local observation freshness and explicit target arithmetic (opt-in)."""
from __future__ import annotations
import re
from fairy.agents.jev.management import successes, get, timestamp, number, observation_role

# These mutate the relevant measurement even inside one UTC day. Read-only
# reports, failed actions and unrelated-plot work do not erase an observation.
WATER_MUTATIONS = frozenset({'irrigate','drain','soak','puddle_and_level','transplant','apply_fertigation','irrigate_ridges'})
STAND_MUTATIONS = frozenset({'transplant','replant_seedlings'})


def latest(facts, method, target, now):
    found = None; reason = 'No successful observation for this target.'
    for s,d in successes(facts):
        args = get(s,'tool_args',{}) or {}; name = get(s,'tool_name','').split('__')[-1]
        scope = args.get('plot_id','field')
        when = timestamp(d.get('timestamp'))
        if when is None: when = timestamp(get(s,'time_after'))
        if when is None: when = timestamp(get(s,'time'))
        if name == method and scope == target:
            found = dict(data=d,at=when,action=get(s,'tool_name'),fresh=False,reason=None)
            reason = None
        elif found and scope == target:
            mutations = WATER_MUTATIONS if method == 'read_water_sensors' else STAND_MUTATIONS if method == 'inspect_establishment' else frozenset()
            if name in mutations:
                reason = 'A subsequent '+name+' may change this measurement; observe again.'
    if found:
        if reason is None and found['at'] is None:
            reason = 'Observation timestamp unknown; do not treat it as current.'
        if reason is None and number(now) is not None and (found['at'] > now or int(found['at']//86400) != int(now//86400)):
            reason = 'Observation belongs to another UTC day; water/growth/weather may have changed.'
        found.update(fresh=reason is None,reason=reason)
    return found or dict(fresh=False,reason=reason,data=None,at=None)


def water_targets(task, facts, now):
    """Only unambiguous explicitly named plot targets, never an optimal dose."""
    result = []
    for p in facts.get('plots',[]):
        pid = p['plot_id']; obs = latest(facts,'read_water_sensors',pid,now)
        row = dict(plot_id=pid,observation_at=obs['at'],fresh=obs['fresh'],reason=obs['reason'])
        if obs['fresh']:
            depth = number(obs['data'].get('surface_water_mm'))
            row['observed_depth_mm'] = depth
            # A bounded, directly plot-qualified clause is deliberately narrow.
            for action,phrase in [('irrigate',r'(?:灌溉|灌水|补水)(?:至|到)'),('drain',r'(?:排水)(?:至|到)')]:
                matches = re.findall(re.escape(pid)+r'\s*'+phrase+r'\s*(\d+(?:\.\d+)?)\s*(?:毫米|mm)',task,re.I)
                if depth is not None and len(set(matches)) == 1:
                    target = float(matches[0]); amount = max(0.,target-depth if action=='irrigate' else depth-target)
                    row[action+'_explicit_increment_mm'] = amount
        result.append(row)
    return result


def chinese_durations(task):
    aliases = {'秒':'seconds','秒钟':'seconds','分钟':'minutes','小时':'hours','天':'days','日':'days'}
    return [(aliases[u],float(v)) for v,u in re.findall(r'(\d+(?:\.\d+)?)\s*(秒钟|分钟|小时|秒|天|日)',task)]


def derive_water(tool, argument, arguments, task, facts, now):
    if tool.name not in ('irrigate','drain') or argument != 'water_mm':
        return None
    pid = arguments.get('plot_id')
    row = next((r for r in water_targets(task,facts,now) if r['plot_id']==pid),None)
    value = row.get(tool.name+'_explicit_increment_mm') if row else None
    if value is None or value <= 0:
        return None
    if tool.name == 'irrigate':
        from fairy.agents.jev.management import canal_limits
        limits = [c['max_delivery_mm_by_plot'][pid] for c in canal_limits(facts,now) if pid in c['max_delivery_mm_by_plot']]
        if limits: value = min(value,max(limits))
    if value <= 0: return None
    import math
    value = math.floor(value*1e6)/1e6
    return value,'Explicit plot water target minus fresh observed depth (bounded by current public canal capacity). Recheck after delivery.'


def weather_evidence(facts, now):
    from datetime import datetime, timezone
    today=datetime.fromtimestamp(now,timezone.utc).date().isoformat()
    result={}
    for s,d in successes(facts):
        name=get(s,'tool_name','');method=name.split('__')[-1]
        if method not in ('get_forecast','get_current_weather'): continue
        scope=str((get(s,'tool_args',{}) or {}).get('farm_id',name.split('__')[0]))
        row=result.setdefault(scope,{})
        if method=='get_current_weather':
            row['current_weather']={'data':d,'valid_for_today_utc':d.get('date')==today}
        else:
            rows=d.get('forecast',[])
            row['forecast']={'dated_entries':[x for x in rows if isinstance(x,dict) and str(x.get('date',''))>=today],
                'undated_entries':sum(isinstance(x,dict) and not x.get('date') for x in rows),
                'note':'Use only explicit forecast dates. Unknown dates do not establish a current weather window.'}
    return result
