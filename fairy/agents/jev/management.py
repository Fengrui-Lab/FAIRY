"""Opt-in task arithmetic and management ledger, using public inputs only.

No scenario IDs/specs, oracle, backend reads, queries, or simulator writes.
A missing/ambiguous prescription remains a model choice, never an invented dose.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from hashlib import sha256
import math
import re

PROFILE = 'enforced-v2'
VERSION = 'task-management-v3'
CST = timezone(timedelta(hours=8))
EPS = 1e-8
RULES = (
    'The adapter calculates explicitly prescribed fertilizer quantities. Choose the operation and target; do not reinterpret kg product as kg nitrogen or kg/ha as kg.',
    'Read management_progress before each decision. DUE means inspect the actual crop, weather and resources, then perform or defer that task. A reference date alone does not prove readiness.',
    'Continue required seasonal care after planting. Check each plot and each fertilizer round; partial or failed work is not completion. Observe any pending effect before repeating its treatment.',
    'When no required work is ready, choose a wait ending no later than the next listed check, then recheck. Do not end a growing season because planting or one management round succeeded.',
    'UTC canal windows and UTC+08 display time are different clocks. Both explicit clocks are provided. Correct the actual blocker; repeating an unchanged rejected call cannot clear it.',
)
SHA256 = sha256('\n'.join(RULES).encode()).hexdigest()


def number(v):
    return float(v) if type(v) in (float, int) and math.isfinite(v) else None


def get(s, k, default=None):
    return s.get(k, default) if isinstance(s, dict) else getattr(s, k, default)


def successes(facts):
    for s in facts.get('steps', []):
        if get(s, 'op_type') != 'TOOL':
            continue
        d = get(s, 'content')
        if not isinstance(d, dict) or d.get('error') or d.get('ok') is False:
            continue
        if d.get('ok') is True:
            d = d.get('data')
        if not isinstance(d, dict) or d.get('status') in ('error', 'failed'):
            continue
        yield s, d


def timestamp(value):
    if number(value) is not None:
        return float(value)
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    # Workflow times use the existing logger's UTC+08 display convention.
    return (dt if dt.tzinfo else dt.replace(tzinfo=CST)).timestamp()


def task_plan(task, facts, num_ridges):
    plan = {'source': 'explicit task text', 'kind': None, 'unresolved': []}
    plots = facts.get('plots', [])
    negated = bool(re.search(r'不(?:要|得|需)?(?:施肥|追肥|施基肥)|无需(?:施肥|追肥)|禁止(?:施肥|追肥)', task))
    if negated:
        plan['unresolved'].append('Negative fertilizer instruction present; do not infer a positive prescription from nearby numbers.')
    if not negated and plots and re.search(r'尿素|urea', task, re.I):
        doses = {}
        for p in plots:
            pid = p['plot_id']
            matches = list(re.finditer(re.escape(pid) + r'\s*三轮依次为\s*(\d+(?:\.\d+)?)\s*[、,，]\s*(\d+(?:\.\d+)?)\s*[、,，]\s*(\d+(?:\.\d+)?)\s*(?:千克|公斤|kg)\s*/\s*(?:公顷|ha)', task, re.I))
            m = matches[0] if len(matches) == 1 else None
            if m and all(0 < float(v) <= 300 for v in m.groups()):
                doses[pid] = [float(v) for v in m.groups()]
        if len(doses) == len(plots):
            plan.update(kind='paddy', doses_kg_ha=doses)
        else:
            plan['unresolved'].append('Per-plot fertilizer prescription not uniquely parsed; do not invent a dose.')
    elif not negated and facts.get('ridges'):
        basal = [float(x) for x in re.findall(r'基肥\s*(\d+(?:\.\d+)?)\s*(?:公斤|千克|kg)', task)]
        basal += [float(x) for x in re.findall(r'(\d+(?:\.\d+)?)\s*(?:公斤|千克|kg)\s*基肥', task)]
        basal = set(basal)
        top = []
        m = re.search(r'参考追肥安排为([^\n。]+)', task)
        if m:
            top = [(int(d), float(kg)) for d, kg in re.findall(r'第\s*(\d+)\s*日\s*(\d+(?:\.\d+)?)\s*(?:公斤|千克|kg)', m[1])]
        if len(basal) == 1 and next(iter(basal)) > 0:
            plan.update(kind='ridge', basal_kg=next(iter(basal)), topdress=top, num_ridges=num_ridges)
    plan['fertigation_carrier_zero'] = '单独追肥不额外添加灌溉水' in task
    if plan['kind'] is None and not plan['unresolved']:
        plan['unresolved'].append('No supported unambiguous fertilizer prescription; retain model quantity choices within public resource limits.')
    elif plan['kind'] == 'ridge' and not plan['topdress']:
        plan['unresolved'].append('No explicit topdressing schedule parsed; this does not mean no topdressing is needed.')
    from fairy.agents.jev.state_semantics import lifecycle
    plan['lifecycle'] = lifecycle(task)
    plan['long_horizon'] = plan['lifecycle']['seasonal_task']
    plan['water_interval_days'] = None
    m = re.search(r'每隔\s*(\d+)\s*个?\s*UTC日[^。]*?(?:水分|水层|water)', task, re.I)
    if m and int(m[1]) > 0:
        plan['water_interval_days'] = int(m[1])
    plan['periodic_checks'] = []
    for kind, tool, pattern in [
        ('crop_check','PaddyObservationApp__inspect_crop',r'每\s*(\d+)\s*天检查两田长势和生育阶段'),
        ('pest_check','PaddyObservationApp__inspect_pests',r'每\s*(\d+)\s*天逐田检查虫'),
    ]:
        m = re.search(pattern, task)
        if m and int(m[1]) > 0:
            plan['periodic_checks'].append(dict(kind=kind,tool=tool,interval_days=int(m[1])))
    m = re.search(r'移栽后约第\s*(\d+)\s*日起每天检查成熟', task)
    plan['daily_maturity_from_day'] = int(m[1]) if m else None
    plan['rice_fertilizer_days'] = [int(x) for x in re.findall(r'移栽后第\s*(\d+)\s*日[^。]*?第[二三]轮肥', task)]
    plan['irrigation_windows'] = []
    m = re.search(r'参考灌溉安排为([^\n。]+)', task)
    if m:
        plan['irrigation_windows'] = [(int(d), float(mm)) for d, mm in re.findall(r'第\s*(\d+)\s*日\s*(\d+(?:\.\d+)?)\s*毫米', m[1])]
    return plan


def ledger(plan, facts):
    """Account only successful, actually returned coverage and product quantities."""
    result = {'basal_used_kg': 0.0, 'ridge_product_kg': {}, 'plot_doses_kg_ha': {}, 'planting_timestamps': {}, 'first_planting_timestamps': {}, 'last_observations': {}, 'root_water_by_ridge': {}}
    areas = {p['plot_id']: p.get('area_m2') for p in facts.get('plots', [])}
    for s, d in successes(facts):
        name = get(s, 'tool_name', '')
        args = get(s, 'tool_args', {}) or {}
        when = timestamp(get(s, 'time_after'))
        if when is None:
            when = timestamp(get(s, 'time'))
        if name == 'TractorApp__base_fertilize':
            v = number(d.get('fertilizer_used_kg'))
            if v is not None:
                result['basal_used_kg'] += v
        elif name in ('TractorApp__apply_fertilizer', 'FarmWorldApp__apply_fertigation'):
            ids = d.get('fertilized_ridges', d.get('fertigated_ridges'))
            used = number(d.get('fertilizer_used_kg', d.get('fertilizer_kg_used')))
            if isinstance(ids, list) and ids and used is not None and used > 0:
                for rid in set(ids):
                    result['ridge_product_kg'][rid] = result['ridge_product_kg'].get(rid, 0.) + used / len(set(ids))
        elif name == 'PaddyOpsApp__apply_fertilizer':
            pid = args.get('plot_id'); area = number(areas.get(pid)); used = number(d.get('product_kg'))
            if area and used is not None and used > 0:
                result['plot_doses_kg_ha'].setdefault(pid, []).append(used * 10000 / area)
        if name == 'TractorApp__plant_seeds' and d.get('planted_ridges') and when is not None:
            for rid in d['planted_ridges']:
                result['first_planting_timestamps'].setdefault(str(rid), when)
                result['planting_timestamps'][str(rid)] = when
        elif name == 'TractorApp__replant_seeds' and when is not None:
            # Requested/full_replant flags are not evidence of actual reset.
            for rid in d.get('phenology_reset_ridges',[]):
                if type(rid)==int:
                    result['planting_timestamps'][str(rid)] = when
        elif name == 'PaddyOpsApp__transplant' and d.get('completed') is True and when is not None:
            result['planting_timestamps'].setdefault(args.get('plot_id'), when)
            result['first_planting_timestamps'].setdefault(args.get('plot_id'), when)
        if when is not None and observation_role(name) is not None:
            key = name + ':' + str(args.get('plot_id', 'field'))
            result['last_observations'][key] = when
            if name.endswith('__read_root_zone_sensors'):
                for zone in d.get('root_zone_sensors',[]):
                    lo,hi=zone.get('ridge_start'),zone.get('ridge_end')
                    if type(lo)==type(hi)==int and 0<=lo<=hi and number(zone.get('root_vwc')) is not None:
                        for rid in range(lo,hi+1):
                            if rid < len(facts.get('ridges',[])):
                                result['root_water_by_ridge'][str(rid)]=when
    return result


def ridge_round(plan, account):
    previous = 0.
    size = plan.get('num_ridges') or 0
    if size <= 0:
        return None
    for index, (day, kg) in enumerate(plan.get('topdress', [])):
        per = kg / size
        needs = {i: max(0., previous + per - account['ridge_product_kg'].get(i, 0.)) for i in range(size)}
        needs = {i: x for i, x in needs.items() if x > EPS}
        if needs:
            return {'index': index + 1, 'reference_day': day, 'total_kg': kg, 'per_ridge_kg': per, 'remaining_by_ridge_kg': needs}
        previous += per
    return None


def paddy_round(plan, account, pid):
    used = account['plot_doses_kg_ha'].get(pid, [])
    prescribed = plan.get('doses_kg_ha', {}).get(pid, [])
    # A successful under-dose does not count as a complete round.
    applied = sum(used); target = 0.
    for i, dose in enumerate(prescribed):
        target += dose
        if applied < target - EPS:
            return {'index': i + 1, 'remaining_kg_ha': target - applied}
    return None


def fertilizer_resources(native, facts):
    from fairy.agents.jev.constraints import family
    cls, name = family(native), native.name
    if cls not in ('TractorApp', 'PaddyOpsApp', 'FarmWorldApp'):
        return None
    inv = facts.get('inventory', {})
    if cls == 'FarmWorldApp':
        stock = inv.get('fertilizer_kg')
        carried, capacity = 0., stock
    elif cls == 'PaddyOpsApp':
        m = facts.get('machines', {}).get('tractor', {})
        stock = inv.get('fertilizer', {}).get('stock_kg')
        carried, capacity = m.get('fertilizer_kg'), m.get('fertilizer_capacity_kg')
    else:
        m = facts.get('machines', {}).get(native.class_instance.name, {})
        stock, carried = inv.get('fertilizer_kg'), m.get('fertilizer_spreader_kg')
        # Public native tool capacity, not a hidden crop state.
        from fairy.apps.farm_world.tractor_app import _FERTILIZER_SPREADER_MAX_KG
        capacity = _FERTILIZER_SPREADER_MAX_KG
    if any(number(v) is None for v in (stock, carried, capacity)):
        return None
    limits = inv.get('limits_and_usage', {})
    quota = limits.get('fertilizer_quota_kg')
    used = limits.get('fertilizer_used_kg', 0.)
    remaining_quota = max(0., quota - used) if number(quota) is not None and number(used) is not None else None
    return dict(stock_kg=max(0., stock), carried_kg=max(0., carried), capacity_kg=capacity,
                load_limit_kg=max(0., min(stock, capacity-carried)), remaining_quota_kg=remaining_quota,
                available_kg=max(0.,stock if cls == 'FarmWorldApp' else carried))


def derive_fertilizer(native, arg_name, arguments, plan, account, facts):
    """Return explicit task arithmetic; operation readiness is constrained separately."""
    resources = fertilizer_resources(native, facts)
    if not resources:
        return None
    from fairy.agents.jev.constraints import family
    cls, tool = family(native), native.name
    value = None
    if cls == 'PaddyOpsApp' and plan['kind'] == 'paddy':
        if tool == 'apply_fertilizer' and arg_name == 'kg_per_ha':
            current = paddy_round(plan, account, arguments.get('plot_id'))
            if current:
                value = current['remaining_kg_ha']
        elif tool == 'load_fertilizer' and arg_name == 'kg':
            # Supply the earliest incomplete round across plots, not all future rounds.
            remaining = [(p, paddy_round(plan, account, p['plot_id'])) for p in facts.get('plots', []) if not p.get('harvested')]
            active = [r['index'] for p, r in remaining if r]
            if active:
                batch_kg = sum(r['remaining_kg_ha'] * p['area_m2'] / 10000 for p, r in remaining if r and r['index'] == min(active))
                value = min(resources['load_limit_kg'], max(0., batch_kg-resources['carried_kg']))
    elif cls == 'FarmWorldApp' and tool == 'apply_fertigation' and plan['kind'] == 'ridge' and plan['fertigation_carrier_zero']:
        current = ridge_round(plan, account)
        if current and arg_name == 'nutrient_amount':
            dose = current['remaining_by_ridge_kg'].get(arguments.get('start_ridge'))
            if dose is not None:
                # The public tool schema defines 1.0 as 30 kg product per ridge.
                value = dose / 30.
        elif current and arg_name == 'water_mm':
            return 0., 'Explicit task asks for fertilizer without added carrier irrigation water.'
    elif cls == 'TractorApp' and plan['kind'] == 'ridge':
        basal_left = max(0., plan['basal_kg']-account['basal_used_kg'])
        current = ridge_round(plan, account)
        if tool == 'base_fertilize' and arg_name == 'total_kg' and basal_left > EPS:
            value = basal_left
        elif tool == 'apply_fertilizer' and arg_name == 'kg_per_ridge' and current:
            rid = arguments.get('start_ridge')
            value = current['remaining_by_ridge_kg'].get(rid)
        elif tool == 'load_fertilizer' and arg_name == 'kg':
            needed = basal_left if basal_left > EPS else sum(current['remaining_by_ridge_kg'].values()) if current else 0.
            if resources['remaining_quota_kg'] is not None:
                needed = min(needed, resources['remaining_quota_kg'])
            value = min(resources['load_limit_kg'], max(0., needed-resources['carried_kg']))
    if value is None or not math.isfinite(value) or value <= EPS:
        return None
    return value, 'Explicit task product dose minus successful coverage and observed carried stock; native units and available resources.'


def management_context(task, facts, now, num_ridges):
    plan = task_plan(task, facts, num_ridges)
    account = ledger(plan, facts)
    windows = []
    current = ridge_round(plan, account) if plan['kind'] == 'ridge' else None
    planted = account['planting_timestamps']
    if facts.get('ridges') and planted and all(r.get('planted') or r.get('harvested') for r in facts.get('ridges', [])):
        # Whole-field task reference dates keep the establishment anchor;
        # partial replanting updates cohort age, not the whole field calendar.
        anchor = max((account['first_planting_timestamps'] or planted).values())
        if current:
            windows.append({'kind': 'fertilizer', 'target': 'field', 'at': anchor+current['reference_day']*86400, 'reference_day': current['reference_day']})
        for day, mm in plan['irrigation_windows']:
            # A reference window prompts observation; it does not order irrigation.
            at = anchor+day*86400
            # A single probe or shallow 5cm reading does not establish a full
            # rooting-zone check. Unknown coverage stays due.
            inspected = min((account['root_water_by_ridge'].get(str(r['ridge_id']),0.) for r in facts.get('ridges',[])),default=0.)
            if inspected < at:
                windows.append({'kind': 'water_check', 'target': 'field', 'at': at, 'target_mm_reference': mm})
    if facts.get('plots'):
        for p in facts.get('plots', []):
            pid = p['plot_id']; anchor = planted.get(pid)
            if anchor is None or p.get('harvested'):
                continue
            # Task dates are UTC calendar days, not durations from the CST display.
            day0 = datetime.fromtimestamp(anchor, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            interval = plan['water_interval_days']
            if interval:
                last = account['last_observations'].get('PaddyObservationApp__read_water_sensors:'+pid, day0)
                last_day = datetime.fromtimestamp(last, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                windows.append({'kind': 'water_check', 'target': pid, 'at': max(day0, last_day)+interval*86400})
            for check in plan['periodic_checks']:
                last = account['last_observations'].get(check['tool']+':'+pid, day0)
                last_day = datetime.fromtimestamp(last,timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
                windows.append({'kind':check['kind'],'target':pid,'at':max(day0,last_day)+check['interval_days']*86400,'tool':check['tool']})
            maturity_day = plan['daily_maturity_from_day']
            if maturity_day is not None:
                first = day0+maturity_day*86400
                last = account['last_observations'].get('PaddyObservationApp__inspect_crop:'+pid,0.)
                last_day = datetime.fromtimestamp(last,timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
                windows.append({'kind':'maturity_check','target':pid,'at':max(first,last_day+86400),'tool':'PaddyObservationApp__inspect_crop'})
            r = paddy_round(plan, account, pid)
            if r and 1 < r['index'] <= len(plan['rice_fertilizer_days'])+1:
                windows.append({'kind': 'fertilizer', 'target': pid, 'at': day0+plan['rice_fertilizer_days'][r['index']-2]*86400})
    for w in windows:
        w.update(status='DUE: observe readiness and act/defer' if w['at'] <= now else 'UPCOMING',
                 utc=datetime.fromtimestamp(w['at'],timezone.utc).isoformat(), seconds_until=max(0., w['at']-now))
    future = [w['at']-now for w in windows if w['at'] > now]
    wait_limit = min(future) if future else None
    if any(w['at'] <= now for w in windows):
        wait_limit = min(wait_limit,86400.) if wait_limit is not None else 86400.
    canals = canal_limits(facts, now)
    opens = [c['seconds_until_open'] for c in canals if c['seconds_until_open'] > 0 and c['usable_flow_m3_hour'] > 0 and c['remaining_withdrawal_m3'] > 0]
    if opens:
        wait_limit = min([wait_limit, *opens]) if wait_limit is not None else min(opens)
    plot_progress = []
    for p in facts.get('plots', []):
        pid = p['plot_id']; anchor = planted.get(pid)
        r = paddy_round(plan, account, pid) if plan['kind'] == 'paddy' else None
        plot_progress.append(dict(plot_id=pid, planted=p.get('planted'), harvested=p.get('harvested'),
            days_since_transplant_utc=(datetime.fromtimestamp(now,timezone.utc).date()-datetime.fromtimestamp(anchor,timezone.utc).date()).days if anchor is not None else None,
            next_fertilizer_round=r, remaining_product_kg=r['remaining_kg_ha']*p['area_m2']/10000 if r else None))
    field_progress = None
    if facts.get('ridges'):
        field_progress = dict(total=len(facts['ridges']),planted=sum(r.get('planted',False) or r.get('harvested',False) for r in facts['ridges']),
            harvested=sum(r.get('harvested',False) for r in facts['ridges']),
            days_since_last_planting=(now-max(planted.values()))/86400 if planted else None,
            remaining_ridges=list(current['remaining_by_ridge_kg']) if current else [],
            remaining_product_kg=sum(current['remaining_by_ridge_kg'].values()) if current else None)
    last_blocker = None
    steps = facts.get('steps', [])
    if steps:
        last = steps[-1]; raw = get(last, 'content')
        if get(last,'op_type') == 'TOOL_ERROR' or isinstance(raw,dict) and (raw.get('error') or raw.get('ok') is False):
            last_blocker = dict(tool=get(last,'tool_name'),arguments=get(last,'tool_args'),receipt=str(raw)[:600],
                                instruction='Correct this constraint or choose inspection/wait; do not repeat unchanged arguments.')
    return dict(version=VERSION, plan=plan, ledger=account, last_blocker=last_blocker, plot_progress=plot_progress,
                field_progress=field_progress, canal_limits=canals, next_ridge_fertilizer_round=current,
                schedule_basis='Rice: UTC calendar day of successful transplant. Ridge field: elapsed days after last successful sowing once all ridges are established.',
                windows=sorted(windows,key=lambda w:w['at']), wait_limit_seconds=wait_limit,
                clocks={'utc':datetime.fromtimestamp(now,timezone.utc).isoformat(), 'utc_plus_08':datetime.fromtimestamp(now,CST).isoformat()},
                rules=list(RULES))


def canal_limits(facts, now):
    """Public canal opening/flow/quota arithmetic; do not inspect backend water."""
    result = []
    day = now - now % 86400
    for c in facts.get('inventory', {}).get('channels', []):
        if c.get('channel_id') != 'supply':
            continue
        required = ('open_hour','close_hour','flow_m3_hour','efficiency','quota_m3','withdrawn_m3','blockage_fraction')
        if any(number(c.get(k)) is None for k in required):
            continue
        opening, closing = c['open_hour']*3600, c['close_hour']*3600
        if not 0 <= opening < closing <= 86400:
            continue
        current = now % 86400
        is_open = opening <= current < closing
        next_open = day+opening if current < opening else day+86400+opening
        seconds_left = math.floor(closing-current) if is_open else 0.
        flow = max(0., c['flow_m3_hour']*(1-c['blockage_fraction']))
        quota = max(0.,c['quota_m3']-c['withdrawn_m3'])
        available = min(flow*seconds_left/3600,quota)*max(0.,min(1.,c['efficiency']))
        depths = {p['plot_id']:available*1000/p['area_m2'] for p in facts.get('plots', [])
                  if p.get('area_m2',0)>0 and p['plot_id'] in c.get('connected_plots', [])}
        result.append(dict(channel_id=c['channel_id'],is_open=is_open,seconds_until_open=0. if is_open else next_open-now,
                           next_open_utc=datetime.fromtimestamp(now if is_open else next_open,timezone.utc).isoformat(),
                           max_delivery_mm_by_plot=depths,remaining_withdrawal_m3=quota,usable_flow_m3_hour=flow))
    return result


def observation_role(name):
    method = name.split('__')[-1]
    if method in ('read_water_sensors','read_root_zone_sensors','get_root_zone_water'):
        return 'water'
    if method in ('read_soil_sensor','read_soil_sensors'):
        return 'shallow_water'
    if name.startswith('PaddyObservationApp__'):
        return {'inspect_crop':'crop','inspect_pests':'pests','measure_grain_moisture':'grain'}.get(method)
    return None
