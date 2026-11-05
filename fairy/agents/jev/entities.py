"""Enhanced-only finite IDs from public metadata and acquired catalog receipts.

Unknown entity IDs are not fabricated. Discovery tools remain available while
write tools needing an unseen catalog are withheld until it has been queried.
"""
from fairy.agents.jev.management import successes,get
VERSION='receipt-entity-v1'


def rows(value):
    if isinstance(value,dict):
        yield value
        for v in value.values():yield from rows(v)
    elif isinstance(value,list):
        for v in value:yield from rows(v)


def dependent(tool):
    return tool.class_name in ('SeedMarket','SeasonPlanning')


def choices(tool,arg,arguments,steps):
    name=arg.name;arguments=arguments or {}
    public=[]
    for s,d in successes({'steps':steps}):
        source=get(s,'tool_args',{}) or {}
        if any(k in arguments and source.get(k,d.get(k)) is not None and arguments[k]!=source.get(k,d.get(k)) for k in ('farm_id','plot_id','asset_id')):continue
        public.append((s,d))
    if name=='farm_id':
        from fairy.agents.jev.menu import scene_world
        fid=getattr(scene_world(tool),'farm_id',None)
        if isinstance(fid,str):return [fid],'public bound farm identity'
    catalogs=[]
    for s,d in public:
        if get(s,'tool_name','').endswith('__get_crop_options'):
            source=(get(s,'tool_args',{}) or {}).get('farm_id')
            if source is None or arguments.get('farm_id',source)==source:catalogs.append(d)
    if tool.class_name=='SeasonPlanning':
        if name=='crop_id':return sorted({k for d in catalogs for k,v in d.items() if isinstance(v,dict)}),'queried crop-option catalog keys'
        if name=='cultivar_id':
            # Native select_crop accepts the seed identity returned in crop options.
            selected=arguments.get('crop_id');values=[]
            for d in catalogs:
                for crop,v in d.items():
                    if isinstance(v,dict) and (selected is None or crop==selected) and isinstance(v.get('seed_type'),str):values.append(v['seed_type'])
            return sorted(set(values)),'selected queried crop option seed identity (native cultivar selector contract)'
    if tool.class_name=='SeedMarket':
        offers={r['offer_id']:r for s,d in public for r in rows(d) if 'offer_id' in r and 'quantity' in r}
        used={r['offer_id'] for s,d in public if get(s,'tool_name','').endswith(('__purchase_seed','__get_purchase_records')) for r in rows(d) if 'offer_id' in r}
        offers={k:r for k,r in offers.items() if r.get('available_lots',1)>0 and k not in used}
        if name=='offer_id':return list(offers),'queried, not-yet-purchased offer IDs'
        if name=='quantity' and tool.name=='purchase_seed':
            offer=arguments.get('offer_id');selected=[offers[offer]] if offer in offers else list(offers.values())
            return sorted({r['quantity'] for r in selected}),'exact queried indivisible lot quantity for selected offer'
        if name=='order_id' and tool.name=='purchase_seed':
            existing={r['order_id'] for s,d in public for r in rows(d) if isinstance(r.get('order_id'),str)};i=1
            while f'jev-order-{i:06d}' in existing:i+=1
            return [f'jev-order-{i:06d}'],'one unused caller-supplied idempotency label'
    if name.endswith('_id'):
        values=sorted({r[name] for s,d in public for r in rows(d) if isinstance(r.get(name),str)})
        return values,'exact entity IDs in successful public receipts; query discovery tools when absent'
    return None
