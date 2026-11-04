"""Public operation-time previews. No calls and no simulator writes."""
import math
from fairy.agents.jev.constraints import family
from fairy.agents.jev.management import number


def estimate(tool,args,facts):
    if family(tool) not in ('PaddyOpsApp','PaddyMachineryApp'): return None
    name=tool.name
    if name=='soak' and number(args.get('hours')) is not None: return args['hours']*3600
    fixed={'load_seedlings':600,'refuel':300,'attach_implement':300,'detach_implement':300}
    if name in fixed: return fixed[name]
    plot=next((p for p in facts.get('plots',[]) if p['plot_id']==args.get('plot_id')),None)
    if plot:
        if name=='puddle_and_level': return math.ceil(plot['area_m2']/1000*3600)
        if name in ('transplant','harvest'):
            area=args.get('area_m2')
            if area is None: area=plot['area_m2']-plot.get('transplanted_area_m2' if name=='transplant' else 'harvested_area_m2',0)
            if number(area) is not None: return math.ceil(area/2000*3600)
    return None


def annotation(tool,args,facts,context):
    duration=estimate(tool,args,facts)
    if duration is None: return None
    now=facts.get('now')
    crossed=[dict(kind=w['kind'],target=w['target'],utc=w['utc']) for w in (context or {}).get('windows',[])
             if number(now) is not None and now < w['at'] <= now+duration]
    return dict(estimated_seconds=duration,shared_clock=True,crossed_checks=crossed,
                instruction='This operation advances the same clock for every plot. Complete due care before a long job; recheck all plots afterwards. Duration does not prove wet-soak or crop readiness.')
