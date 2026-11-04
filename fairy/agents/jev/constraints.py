"""Enhanced-only public contracts. Never infer a hard bound from a typical dose.

These helpers filter candidates before choice, without clamping a model answer or
executing additional simulator operations. Unknown resources remain unknown.
"""
from __future__ import annotations
import math
from fairy.agents.jev.management import number

FAMILIES = frozenset({'TractorApp', 'PaddyOpsApp', 'PaddyMachineryApp', 'FarmWorldApp',
                     'WeatherApp', 'RobotApp', 'DroneApp', 'SensorApp', 'PaddyDroneApp', 'PaddyInfrastructureApp'})


def family(tool):
    # The Python MRO identifies inherited contracts; public tool prefixes alone
    # are insufficient (and arbitrary class-name suffix matching is unsafe).
    for cls in type(tool.class_instance).__mro__:
        if cls.__name__ in FAMILIES:
            return cls.__name__
    return tool.class_name


def load_limit(tool, argument, arguments, facts):
    """(max transfer, unit) from public current stock and remaining capacity."""
    cls, name = family(tool), tool.name
    inv, machines = facts.get('inventory', {}), facts.get('machines', {})
    parts = None
    if cls == 'PaddyOpsApp' and name == 'load_seedlings' and argument == 'quantity':
        m = machines.get('transplanter', {})
        s = inv.get('seedlings', {})
        parts = (s.get('quantity'), m.get('seedling_capacity'), s.get('loaded'), 'seedlings')
    elif cls == 'PaddyMachineryApp' and name == 'refuel' and argument == 'liters':
        m = machines.get(arguments.get('machine_id'), {})
        parts = (inv.get('fuel_liters'), m.get('tank_capacity_liters'), m.get('fuel_liters'), 'L')
    elif cls == 'TractorApp':
        from fairy.apps.farm_world import tractor_app as t
        m = machines.get(tool.class_instance.name, {})
        if name == 'refuel' and argument == 'liters':
            parts = (inv.get('fuel_liters'), t._FUEL_TANK_MAX_L, m.get('fuel_tank_l'), 'L')
        elif name == 'load_fertilizer' and argument == 'kg':
            parts = (inv.get('fertilizer_kg'), t._FERTILIZER_SPREADER_MAX_KG, m.get('fertilizer_spreader_kg'), 'kg')
        elif name in ('load_pesticide','refill_pesticide_tank','load_fungicide') and argument == 'liters':
            fungicide = name == 'load_fungicide'
            parts = (inv.get('pesticide_liters'), t._PESTICIDE_TANK_MAX_L,
                     m.get('fungicide_tank_l' if fungicide else 'pesticide_tank_l'), 'L')
        elif name == 'load_seeds' and argument == 'count':
            parts = (inv.get('seed_stock',{}).get(arguments.get('seed_type')), t._SEED_HOPPER_MAX_PLANTS,
                     m.get('seed_hopper'), 'seeds')
    if parts and all(number(v) is not None for v in parts[:3]):
        stock, capacity, carried, unit = parts
        return max(0., min(stock, capacity-carried)), unit
    return None


def transplant_deadline(plot_id, facts):
    """A partial native job must finish in its recorded successful UTC day."""
    from datetime import datetime,timezone
    from fairy.agents.jev.management import successes,get,timestamp
    result=None
    for step,data in successes(facts):
        if get(step,'tool_name','').endswith('__transplant') and (get(step,'tool_args',{}) or {}).get('plot_id')==plot_id and data.get('completed') is False and data.get('transplanted_area_m2',0)>0:
            t=timestamp(get(step,'time_after'))
            if t is None:t=timestamp(get(step,'time'))
            if t is not None:result=(int(t//86400)+1)*86400
    return result


def transplant_capacity(arguments, facts):
    """Public capacity shared by action, plot selector and area candidate filters."""
    plot=next((p for p in facts.get('plots',[]) if p['plot_id']==arguments.get('plot_id')),None)
    m=facts.get('machines',{}).get('transplanter',{})
    seed=number(facts.get('inventory',{}).get('seedlings',{}).get('loaded'))
    fuel=number(m.get('fuel_liters'));now=number(facts.get('now'))
    if plot is None or seed is None or fuel is None:return None
    deadline=transplant_deadline(plot['plot_id'],facts)
    if deadline is not None and now is not None and now>=deadline and not plot.get('planted'):return 0.
    remaining=max(0.,plot['area_m2']-plot.get('transplanted_area_m2',0.))
    # Native contract: ceil(area*75) seedlings and strict end before midnight.
    midnight=max(0.,(math.ceil(86400-now%86400)-1)*2000/3600) if now is not None else remaining
    return math.floor(max(0.,min(remaining,seed/75.,fuel/.002,midnight))*1e6)/1e6


def numeric_bounds(tool, argument, facts):
    from fairy.agents.jev.menu import CODE_RANGES, CAPACITY_MAX
    key = (family(tool), tool.name, argument)
    lo, hi = None, None
    # This entry describes a typical range, not a rejected range.
    if key in CODE_RANGES and key != ('FarmWorldApp', 'apply_fertigation', 'nutrient_amount'):
        lo, hi = CODE_RANGES[key]
    if key in CAPACITY_MAX:
        lo, hi = 0., CAPACITY_MAX[key]
    fixed = {('PaddyOpsApp','transplant','row_spacing_cm'):20.,
             ('PaddyOpsApp','transplant','hill_spacing_cm'):20.,
             ('PaddyOpsApp','transplant','seedlings_per_hill'):3}
    if key[0]=='PaddyOpsApp' and key[1] in ('apply_pesticide','apply_fungicide') and argument=='liters_per_ha':
        lo,hi=0.,2.
    if key in fixed:
        lo = hi = fixed[key]
    if key[0] == 'TractorApp' and key[1] in ('plant_seeds','replant_seeds') and argument == 'depth_cm':
        # Crop-specific native rules supersede the original soybean fallback.
        from fairy.agents.jev.menu import scene_world
        world = scene_world(tool)
        rules = getattr(getattr(world,'crop_definition',None),'planting_rules',None)
        if rules is not None:
            lo, hi = rules.depth_cm.minimum, rules.depth_cm.maximum
    if key == ('FarmWorldApp','dry_grain','target_moisture_pct'):
        maximum = facts.get('inventory', {}).get('storage', {}).get('max_storage_moisture_pct')
        if number(maximum) is not None:
            hi = min(hi, maximum)
    return lo, hi


def legal_options(tool, arg, options, arguments, facts):
    """Intersect native JSON schema, true code bounds and known resource limits."""
    schema = getattr(tool, 'parameters_schema', {}).get('properties', {}).get(arg.name, {})
    # Nullable unions still have a numeric branch with constraints.
    branches = schema.get('anyOf', [schema])
    numeric = next((s for s in branches if s.get('type') in ('number','integer')), schema)
    lo, hi = numeric_bounds(tool, arg.name, facts)
    for key, is_lo in [('minimum',True),('maximum',False)]:
        value = numeric.get(key)
        if number(value) is not None:
            if is_lo: lo = max(lo, value) if lo is not None else value
            else: hi = min(hi, value) if hi is not None else value
    limit = load_limit(tool, arg.name, arguments, facts)
    from fairy.agents.jev import ridge_irrigation
    irrigation_hours = ridge_irrigation.supported(tool) and arg.name==ridge_irrigation.METHODS[tool.name][2]
    if irrigation_hours:
        cap=ridge_irrigation.hour_limit(tool,arguments,facts)
        if cap is not None:limit=(cap,'hours under field-equivalent water quota')
    cls, name = family(tool), tool.name
    if cls in ('TractorApp','PaddyOpsApp','FarmWorldApp'):
        from fairy.agents.jev.management import fertilizer_resources
        resources = fertilizer_resources(tool,facts)
        if resources:
            available = resources['available_kg']
            if resources['remaining_quota_kg'] is not None:
                available = min(available,resources['remaining_quota_kg'])
            cap = None
            if name == 'base_fertilize' and arg.name == 'total_kg': cap = available
            if name in ('apply_fertilizer','apply_fertigation'):
                start,end = arguments.get('start_ridge'),arguments.get('end_ridge')
                count = end-start+1 if type(start)==type(end)==int and end>=start else None
                if cls == 'TractorApp' and arg.name=='kg_per_ridge' and count: cap = available/count
                if cls == 'FarmWorldApp' and arg.name=='nutrient_amount' and count: cap = available/(30*count)
                plot = next((p for p in facts.get('plots',[]) if p['plot_id']==arguments.get('plot_id')),None)
                if cls=='PaddyOpsApp' and arg.name=='kg_per_ha' and plot and plot['area_m2']>0: cap=available*10000/plot['area_m2']
            if cap is not None: limit=(cap,'native product units')
    if family(tool) == 'PaddyOpsApp' and tool.name == 'transplant' and arg.name == 'area_m2':
        cap=transplant_capacity(arguments,facts)
        if cap is not None:
            limit=(cap,'m2')
            options={k:v for k,v in options.items() if v is not None}
    if limit:
        hi = min(hi,limit[0]) if hi is not None else limit[0]
    is_int = numeric.get('type') == 'integer' or arg.arg_type.split('|')[0].strip() == 'int'
    is_numeric = numeric.get('type') in ('number','integer') or arg.arg_type.split('|')[0].strip() in ('int','float')
    if cls == 'PaddyOpsApp' and name in ('drain','replant_seedlings'):
        from fairy.agents.jev.observations import latest
        method = 'read_water_sensors' if name == 'drain' else 'inspect_establishment'
        pid = arguments.get('plot_id')
        if arg.name == 'plot_id':
            options = {k:v for k,v in options.items() if latest(facts,method,v,facts.get('now'))['fresh']}
        elif pid and arg.name in ('water_mm','quantity'):
            obs = latest(facts,method,pid,facts.get('now'))
            if not obs['fresh']: return {}
            if name=='drain':
                depth = number(obs['data'].get('surface_water_mm'))
                if depth is not None: hi = min(hi,depth) if hi is not None else depth
    if cls == 'PaddyOpsApp' and name=='harvest' and arg.name=='area_m2':
        plot=next((p for p in facts.get('plots',[]) if p['plot_id']==arguments.get('plot_id')),None)
        m=facts.get('machines',{}).get('combine',{})
        if plot:
            cap=max(0.,plot['area_m2']-plot.get('harvested_area_m2',0.))
            if number(m.get('fuel_liters')) is not None: cap=min(cap,m['fuel_liters']/.003)
            limit=(cap,'m2');hi=min(hi,cap) if hi is not None else cap
            options={k:v for k,v in options.items() if v is not None}
    if cls == 'PaddyOpsApp' and name=='store_grain' and arg.name=='batch_id':
        from fairy.agents.jev.receipts import paddy_batches
        batches=paddy_batches(facts)
        stored=sum(b['wet_kg'] for b in batches if b['location']=='stored')
        capacity=number(facts.get('inventory',{}).get('storage_capacity_kg'))
        eligible={b['batch_id'] for b in batches if b['location']=='reception'
                  and number(b['moisture_pct']) is not None and b['moisture_pct']<=14.
                  and (capacity is None or stored+b['wet_kg']<=capacity)}
        options={k:v for k,v in options.items() if v in eligible}
    if cls=='PaddyDroneApp' and arg.name=='plot_ids':
        battery=number(facts.get('machines',{}).get('drone',{}).get('battery_pct'))
        areas={p['plot_id']:p['area_m2'] for p in facts.get('plots',[])}
        if battery is not None:
            options={k:v for k,v in options.items() if isinstance(v,list) and v and len(v)==len(set(v)) and all(pid in areas for pid in v)
                     and sum(areas[pid] for pid in v)*.008<=battery}
    if cls=='PaddyInfrastructureApp' and name=='clear_channel' and arg.name=='channel_id':
        eligible={c['channel_id'] for c in facts.get('inventory',{}).get('channels',[]) if (number(c.get('blockage_fraction')) or 0)>0}
        options={k:v for k,v in options.items() if v in eligible}
    if cls == 'PaddyMachineryApp' and arg.name == 'machine_id':
        if name in ('attach_implement','detach_implement'):
            options = {k:v for k,v in options.items() if facts.get('machines',{}).get(v,{}).get('kind')=='tractor'
                       and ((facts['machines'][v].get('implement') is None) if name=='attach_implement' else (facts['machines'][v].get('implement') is not None))}
        elif name=='refuel':
            options = {k:v for k,v in options.items() if (load_limit(tool,'liters',{'machine_id':v},facts) or (float('inf'),))[0] > 0}
    if cls == 'TractorApp' and arg.name=='seed_type':
        from fairy.agents.jev.menu import scene_world
        crop = getattr(scene_world(tool,arguments),'crop_definition',None)
        if crop is not None:
            options={k:v for k,v in options.items() if v in crop.seed_types}
    if cls == 'TractorApp' and name=='attach_implement' and arg.name=='implement':
        owned=facts.get('machines',{}).get(tool.class_instance.name,{}).get('available_implements')
        if owned is not None:
            options={str(v):v for v in owned}
    if cls == 'PaddyOpsApp' and arg.name=='plot_id':
        def eligible(pid):
            p=next((p for p in facts.get('plots',[]) if p['plot_id']==pid),None)
            if p is None: return False
            if name in ('soak','puddle_and_level'):
                if p.get('planted') or p.get('puddled'): return False
                from fairy.agents.jev.observations import latest
                obs=latest(facts,'read_water_sensors',pid,facts.get('now'))
                if name=='soak' and obs['fresh'] and number(obs['data'].get('preparation_wet_hours')) is not None:
                    return obs['data']['preparation_wet_hours']<24
                return True
            if name=='transplant':
                cap=transplant_capacity({**arguments,'plot_id':pid},facts)
                return not p.get('planted') and p.get('puddled') and p.get('levelled') and (cap is None or cap>0)
            if name=='harvest': return bool(p.get('planted') and not p.get('harvested'))
            return True
        options={k:v for k,v in options.items() if v is None or eligible(v)}
    enum = schema.get('enum', numeric.get('enum'))
    const = schema.get('const', numeric.get('const'))
    def valid(v):
        if enum is not None and v not in enum: return False
        if const is not None and v != const: return False
        if v is None:
            if cls=='TractorApp' and name=='base_fertilize' and arg.name=='total_kg' and limit:
                from fairy.agents.jev.menu import scene_world
                from fairy.apps.farm_world.tractor_operations import _base_fertilize_kg
                if _base_fertilize_kg(scene_world(tool,arguments))>limit[0]: return False
            return any(s.get('type')=='null' for s in branches) or 'None' in arg.arg_type
        if not is_numeric: return True
        n = number(v)
        return (n is not None and (not is_int or n.is_integer())
                and (lo is None or n >= lo) and (hi is None or n <= hi)
                and ('exclusiveMinimum' not in numeric or n > numeric['exclusiveMinimum'])
                and ('exclusiveMaximum' not in numeric or n < numeric['exclusiveMaximum'])
                and (not limit or n > 0)
                and (not irrigation_hours or n>0)
                and (not (cls=='PaddyOpsApp' and arg.name in ('kg_per_ha','liters_per_ha')) or n>0)
                and (not (cls=='FarmWorldApp' and name=='apply_fertigation' and arg.name=='nutrient_amount') or n>0))
    result = {k:v for k,v in options.items() if valid(v)}
    # Exact public constants/bounds and remaining capacity may be absent from
    # the original spaced menu; add them only when the native contract accepts.
    additions = [const] if const is not None else []
    if lo is not None and lo == hi: additions.append(lo)
    if limit: additions.append(math.floor(min(limit[0],hi)) if is_int and hi is not None else math.floor(limit[0]) if is_int else min(limit[0],hi) if hi is not None else limit[0])
    for v in additions:
        if valid(v):
            value = int(v) if is_int else v
            result[str(value)] = value
    return result


def action_blocker(tool, facts, now):
    """Hard publicly observable prerequisites only. No unobserved maturity guesses."""
    cls, name = family(tool), tool.name
    m = facts.get('machines',{}).get(getattr(tool.class_instance,'name',''),{})
    inv = facts.get('inventory',{})
    if cls in ('TractorApp','PaddyOpsApp','FarmWorldApp') and name in ('base_fertilize','apply_fertilizer','apply_fertigation'):
        from fairy.agents.jev.management import fertilizer_resources
        resource=fertilizer_resources(tool,facts)
        if resource and resource['remaining_quota_kg']==0:
            return 'The remaining fertilizer quota is insufficient (zero); loading cannot restore quota. Inspect resources or defer.'
        if resource and resource['available_kg']<=0:
            return ('The applicator carries zero fertilizer. Load fertilizer first; an empty applicator does not mean the prescribed work is complete.' if cls!='FarmWorldApp' else
                    'Fertilizer inventory is empty; no positive dose is currently executable. Inspect supply rather than repeating the application.')
    if cls == 'TractorApp':
        parameter = {'load_fertilizer':'kg','load_seeds':'count','refuel':'liters','load_pesticide':'liters','load_fungicide':'liters','refill_pesticide_tank':'liters'}.get(name)
        if parameter and name != 'load_seeds':
            cap = load_limit(tool,parameter,{},facts)
            if cap and cap[0] <= 0: return 'No observed stock or free onboard capacity.'
    if cls in ('RobotApp','DroneApp'):
        if name == 'charge' and number(m.get('battery_pct')) is not None and m['battery_pct'] >= 100:
            return 'Battery is already full.'
        if cls=='RobotApp' and name in ('inspect_emergence','inspect_pests','inspect_crop_health','inspect_ridge'):
            required = 20. if name=='inspect_ridge' else 15.
            if number(m.get('battery_pct')) is not None and m['battery_pct'] < required:
                return 'Observed battery is below the native inspection minimum; charge first.'
        if m.get('charging') and name not in ('check_status',):
            return 'Device is charging; wait until the announced ready time or choose another device.'
    if cls == 'TractorApp':
        if name in ('plant_seeds','harvest'):
            from fairy.agents.jev.menu import scene_world
            crop=getattr(scene_world(tool),'crop_definition',None)
            rules=getattr(crop,'planting_rules' if name=='plant_seeds' else 'harvest_rules',None)
            required=getattr(rules,'required_implement',None)
            if required and 'attached_implement' in m and m['attached_implement']!=required:
                return f'Current crop tool contract requires {required}; change implements first.'
            if name=='plant_seeds' and rules and 'completed_field_preparation_ops' in facts:
                missing=set(rules.required_preparation)-set(facts['completed_field_preparation_ops'])
                if missing: return 'Complete the public field-preparation prerequisites first: '+', '.join(sorted(missing))
        if name == 'attach_implement' and m.get('attached_implement') is not None:
            return 'Detach the currently mounted implement before changing it.'
        if name == 'detach_implement' and 'attached_implement' in m and m['attached_implement'] is None:
            return 'No implement is currently attached.'
        if name == 'level' and 'attached_implement' in m and m['attached_implement'] != 'grader':
            return 'Levelling requires the grader; detach the current implement and attach the grader.'
        if name == 'unload_grain' and number(m.get('grain_bin_kg')) == 0:
            return 'Grain bin is empty; there is no batch to unload.'
    if cls=='PaddyDroneApp':
        battery=number(facts.get('machines',{}).get('drone',{}).get('battery_pct'))
        if name=='charge' and battery is not None:
            if battery>=100: return 'Drone battery is already full.'
            electricity=number(inv.get('electricity_kwh'))
            if electricity is not None and electricity<(100-battery)/100*.4: return 'Insufficient observed electricity for a full charge.'
        if name=='fly_survey' and battery is not None and facts.get('plots') and min(p['area_m2']*.008 for p in facts['plots'])>battery:
            return 'No full plot survey fits the observed battery; charge first.'
    if cls=='PaddyInfrastructureApp' and name=='clear_channel' and inv.get('channels') and not any((number(c.get('blockage_fraction')) or 0)>0 for c in inv['channels']):
        return 'No public channel blockage to clear.'
    if cls == 'PaddyMachineryApp' and name in ('attach_implement','detach_implement','refuel'):
        candidates={str(v):v for v in facts.get('machines',{}) if v != 'drone'}
        arg=type('Selector',(),{'name':'machine_id','arg_type':'str'})()
        if not legal_options(tool,arg,candidates,{},facts):
            return 'No eligible machine for this operation under current public implement/fuel capacity.'
    if cls == 'PaddyOpsApp':
        if name=='transplant':
            loaded=number(inv.get('seedlings',{}).get('loaded'))
            fuel=number(facts.get('machines',{}).get('transplanter',{}).get('fuel_liters'))
            if loaded is not None and loaded<1:return 'No onboard seedlings; load_seedlings before further transplanting. Remaining plot area is not complete.'
            if fuel is not None and fuel<=0:return 'Transplanter fuel is empty; refuel the transplanter before transplanting.'
            caps=[transplant_capacity({'plot_id':p['plot_id']},facts) for p in facts.get('plots',[]) if not p.get('planted') and p.get('puddled') and p.get('levelled')]
            eligible=[p for p in facts.get('plots',[]) if not p.get('planted') and p.get('puddled') and p.get('levelled')]
            if eligible and number(now) is not None and all(transplant_deadline(p['plot_id'],facts) is not None and now>=transplant_deadline(p['plot_id'],facts) for p in eligible):return 'Recorded partial transplant windows have expired. Waiting or reloading cannot restore the same-UTC-day requirement; report the unresolved native task.'
            if caps and all(c is not None and c<=0 for c in caps):return 'No positive transplant batch fits seedlings, fuel and the strict midnight boundary; replenish resources or wait past midnight, then recheck.'
        if name=='store_grain':
            candidates={b['batch_id']:b['batch_id'] for b in inv.get('grain_batches',[])}
            arg=type('Selector',(),{'name':'batch_id','arg_type':'str'})()
            if not legal_options(tool,arg,candidates,{},facts):
                return 'No reception batch with observed safe moisture and free storage space; dry/measure the actual batch first.'
        if name=='harvest':
            combine=facts.get('machines',{}).get('combine',{})
            if number(combine.get('grain_bin_kg')) is not None and number(combine.get('grain_capacity_wet_kg')) is not None and combine['grain_bin_kg']>=combine['grain_capacity_wet_kg']:
                return 'Combine is full; unload before harvesting another batch.'
        if name == 'load_seedlings':
            limit=load_limit(tool,'quantity',{},facts)
            if limit and limit[0] <= 0: return 'No stock or free transplanter seedling capacity.'
        if name in ('soak','puddle_and_level','transplant','harvest'):
            candidates={p['plot_id']:p['plot_id'] for p in facts.get('plots',[])}
            arg=type('Selector',(),{'name':'plot_id','arg_type':'str'})()
            if candidates and not legal_options(tool,arg,candidates,{},facts):
                return 'No eligible plot at this preparation/planting/harvest stage.'
        if name in ('drain','replant_seedlings'):
            from fairy.agents.jev.observations import latest
            method = 'read_water_sensors' if name=='drain' else 'inspect_establishment'
            if facts.get('plots') and not any(latest(facts,method,p['plot_id'],now)['fresh'] for p in facts['plots']):
                return 'No fresh target observation; query '+method+' before choosing a quantity.'
        required = {'puddle_and_level':'puddler','apply_fertilizer':'spreader','apply_pesticide':'sprayer','apply_fungicide':'sprayer'}.get(name)
        tractor = facts.get('machines',{}).get('tractor',{})
        if required and 'implement' in tractor and tractor['implement'] != required:
            return f'Tractor requires {required}; detach its current implement before attaching the required one.'
    if cls == 'FarmWorldApp' and name in ('dry_grain','store_grain'):
        from fairy.agents.jev.receipts import grain_state
        grain = grain_state(facts)
        if number(grain['pending_kg']) == 0:
            return 'No pending grain batch. Empty drying/storage is not completion evidence.'
        if name == 'store_grain' and number(grain['pending_kg']) is not None and grain['pending_kg'] > 0 and grain['safe_current_batch'] is not True:
            return 'Current batch lacks known safe moisture; dry this batch first (or obtain a batch-specific safe receipt).'
        if name == 'dry_grain':
            cap = number(inv.get('storage',{}).get('drying_capacity_kg_per_day'))
            if cap is not None and number(grain['pending_kg']) is not None and grain['pending_kg'] > cap:
                return 'Pending batch exceeds public dryer capacity; this tool cannot split it. Inspect/report this blocker instead of repeating drying.'
    return None


def derive_transfer(tool, arg_name, arguments, facts):
    """Mechanical supply arithmetic, not an agronomic treatment decision."""
    cls,name = family(tool),tool.name
    limit = load_limit(tool,arg_name,arguments,facts)
    if not limit or limit[0] <= 0:
        return None
    value = None
    if name == 'refuel':
        value = limit[0]
    elif cls == 'PaddyOpsApp' and name == 'load_seedlings' and arg_name == 'quantity':
        inv=facts.get('inventory',{});loaded=inv.get('seedlings',{}).get('loaded')
        plots=facts.get('plots',[])
        if number(loaded) is not None and plots and all(number(p.get('area_m2')) is not None and number(p.get('transplanted_area_m2')) is not None for p in plots):
            need=sum(max(0.,p['area_m2']-p['transplanted_area_m2'])*75 for p in plots if not p.get('planted') and not p.get('harvested'))
            value=min(limit[0],max(0.,math.ceil(need)-loaded))
            value=int(value)
    if value is None or value <= 0: return None
    return value,'Public remaining tank/stock capacity, or native 75 seedlings/m2 times unplanted area minus onboard seedlings; bounded by free capacity and stock.'
