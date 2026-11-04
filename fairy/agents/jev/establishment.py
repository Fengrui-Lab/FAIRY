"""Enhanced-only explicit planting prescriptions and receipt-based progress.

No scenario IDs, oracle, hidden growth reads, model calls or tool execution.
Ambiguous/multi-farm prescriptions are left to the existing controller.
"""
from __future__ import annotations
import hashlib
import json
import re
from fairy.agents.jev import management as M

VERSION = 'receipt-establishment-v3.1'
CHECKPOINT = 'Jev report checkpoint: '


def emergence_evidence(row):
    """Only acquired phase fields, not elapsed days or a receipt's seed base.

    The public crop projection reports zero current stand before emergence.
    Unknown/contradictory phases cannot establish stand failure. Recognize the
    public soybean/maize stages; arbitrary stage strings are not evidence.
    """
    signs=[]
    if type(row.get('emerged')) is bool:signs.append(row['emerged'])
    for key in ('growth_stage','stage'):
        value=row.get(key)
        if not isinstance(value,str):continue
        value=value.strip().upper().replace('-','_').replace(' ','_')
        if value in ('BARE','NOT_PLANTED','PLANTED_PRE_EMERGENCE','PRE_EMERGENCE'):
            signs.append(False)
        elif re.fullmatch(r'(?:VE|VC|VT|V[1-9]\d*|R[1-9]\d*)(?:_[A-Z0-9_]+)?',value):
            signs.append(True)
    if False in signs:return False
    return True if True in signs else None


def record_stand(row, observed, *, index, at, source):
    """Keep stand evidence separate from planting/replanting receipt amounts.

    Emergence must be evidenced in the same crop cycle at/before the stand
    observation. A later stage-only lookup cannot reinterpret an old zero.
    Positive observed stand itself establishes emergence unless contradicted
    by an explicit pre-emergence phase. Zero alone never establishes it.
    """
    emerged=emergence_evidence(observed)
    if emerged is not None:row['emergence_confirmed']=emerged
    if emerged is False:row['stand_repair_confirmed']=False
    if 'stand_fraction' not in observed:return
    stand=M.number(observed['stand_fraction'])
    valid=stand is not None and 0<=stand<=1
    plateau=row.get('stand_repair_plateau')
    if valid and stand>0 and emerged is not False:
        row['emergence_confirmed']=True
    confirmed=valid and emerged is not False and row.get('emergence_confirmed') is True
    # A numerical change with a pre-emergence/conflicting phase is not new
    # stand-loss evidence and must not erase the non-improvement checkpoint.
    if confirmed and plateau is not None and abs(stand-plateau['value'])>M.EPS:
        row.pop('stand_repair_plateau');plateau=None
    row['stand_fraction']=observed['stand_fraction']
    row['stand_repair_confirmed']=bool(confirmed and stand<1.-M.EPS and plateau is None)
    row['stand_observation']=dict(value=observed['stand_fraction'],action_index=index,
        at=at,source=source,status=('invalid' if not valid else
        'unchanged_after_nonimproving_repair' if confirmed and plateau is not None else
        'post_emergence' if confirmed else 'pre_emergence' if emerged is False else 'emergence_unknown'))


def prescription(task, facts):
    from fairy.agents.jev.seed_candidates import _PLAN
    if facts.get('farms') or facts.get('plots'):
        return {}
    ids={r['ridge_id'] for r in facts.get('ridges', [])}
    result={}
    for match in _PLAN.finditer(task):
        lo,hi=int(match[1]),int(match[2]);spacing=float(match[4])
        zone=set(range(lo,hi+1)) if 0<=lo<=hi and hi-lo<len(ids) else set()
        if not zone or not zone<=ids or zone&result.keys() or spacing<=0:
            return {}
        result.update({rid:(match[3],spacing) for rid in zone})
    # Partial/overlapping plans must not silently restrict other field work.
    return result if result.keys()==ids else {}


def data_steps(facts):
    for i,step in enumerate(facts.get('steps', [])):
        pairs=list(M.successes({'steps':[step]}))
        if not pairs:continue
        _,data=pairs[0]
        if data.get('status') in ('rejected','no_op') or data.get('transfer_status')=='no_op':continue
        yield i,step,data


def evidence(task, facts):
    """Latest acquired fields and actual sowing/reset receipts, never guesses."""
    from fairy.agents.jev.state_semantics import observation_rows
    required=prescription(task,facts);rows={};seed=None;first={};progress=set()
    for i,step,data in data_steps(facts):
        name=M.get(step,'tool_name','').split('__')[-1];args=M.get(step,'tool_args',{}) or {}
        at=M.timestamp(M.get(step,'time_after'))
        if at is None:at=M.timestamp(M.get(step,'time'))
        if name=='load_seeds':seed=data.get('seed_type',args.get('seed_type',seed))
        observed=observation_rows(data)
        if observed is None and type(data.get('ridge_id')) is int:
            observed={data['ridge_id']:data}  # Public single-ridge lookup.
        if observed is not None:
            for rid,row in observed.items():
                if not any(k in row for k in ('seed_type','seed_spacing_cm','stand_fraction','emerged','growth_stage','stage')):
                    continue
                current=rows.setdefault(rid,{})
                fields={k:row[k] for k in ('seed_type','seed_spacing_cm') if row.get(k) is not None}
                if fields:rows.setdefault(rid,{}).update(fields,observed_at=at)
                record_stand(current,row,index=i+1,at=at,source=M.get(step,'tool_name',''))
        if name not in ('plant_seeds','replant_seeds'):continue
        ids=data.get('planted_ridges' if name=='plant_seeds' else 'replanted_ridges',[])
        resets=set(data.get('phenology_reset_ridges',[])) if name=='replant_seeds' else set(ids)
        useful=False
        for rid in ids:
            before=rows.get(rid,{})
            if name=='plant_seeds':
                useful=useful or rid not in first
                if at is not None:first.setdefault(rid,at)
            new=(seed,args.get('seed_spacing_cm',args.get('spacing_cm')))
            old=(before.get('seed_type'),before.get('seed_spacing_cm'))
            if rid in resets:
                if rid in required and new==required[rid] and old!=required[rid]:useful=True
                rows[rid]={'seed_type':new[0],'seed_spacing_cm':new[1],
                           'cycle_started_at':at,'action_index':i+1}
            if name=='replant_seeds':
                # A successful repair requires a new acquired observation;
                # stand_after is an operation outcome, not emergence evidence
                # or an instruction to keep filling the same target.
                rows.setdefault(rid,{}).pop('stand_observation',None)
                rows[rid]['stand_repair_confirmed']=False
            stand_before=data.get('stand_fraction_before',{}).get(rid,data.get('stand_fraction_before',{}).get(str(rid)))
            stand_after=data.get('stand_fraction_after',{}).get(rid,data.get('stand_fraction_after',{}).get(str(rid)))
            if M.number(stand_before) is not None and M.number(stand_after) is not None:
                if stand_after>stand_before+M.EPS:useful=True
                rows.setdefault(rid,{}).update(stand_fraction=stand_after)
                if name=='replant_seeds' and rid not in resets and 0<=stand_before<=1 and 0<=stand_after<=1:
                    if stand_after<=stand_before+M.EPS:
                        rows[rid]['stand_repair_plateau']=dict(value=stand_after,action_index=i+1,at=at)
                    else:rows[rid].pop('stand_repair_plateau',None)
        if useful:progress.add(i)
    return required,rows,first,progress


def target_sets(task, facts):
    required,rows,first,progress=evidence(task,facts)
    missing={r['ridge_id'] for r in facts.get('ridges',[]) if not r.get('planted') and not r.get('harvested')}
    repairs=set()
    for r in facts.get('ridges',[]):
        rid=r['ridge_id'];row=rows.get(rid,{})
        if not r.get('planted') or r.get('harvested') or rid not in required:continue
        known=[(row.get('seed_type'),required[rid][0]),(row.get('seed_spacing_cm'),required[rid][1])]
        mismatch=any(a is not None and a!=b for a,b in known)
        if mismatch or row.get('stand_repair_confirmed') is True:repairs.add(rid)
    return required,rows,missing,repairs


def planting_phase(task,facts):
    """Recognize only an explicit sowing sequence, never infer agronomy."""
    required=prescription(task,facts)
    section=re.search(r'播种时序约束[:：]([^\n]+)',task)
    if not required or not section:return None
    text=section[1];matches=list(re.finditer(r'(?:先播|后播)\s*(\d+)\s*[-–—]\s*(\d+)\s*垄',text))
    if not matches:return None
    phases=[];seen=set();end=0
    for i,m in enumerate(matches):
        lo,hi=int(m[1]),int(m[2])
        if not 0<=lo<=hi or hi-lo>=len(required):return None
        ids=set(range(lo,hi+1))
        if not ids or not ids<=required.keys() or ids&seen or len({required[r] for r in ids})!=1:return None
        days=re.findall(r'等待约?\s*(\d+(?:\.\d+)?)\s*天',text[end:m.start()])
        if i and len(days)!=1 or not i and days:return None
        phases.append((ids,float(days[0]) if i else 0.));seen.update(ids);end=m.end()
    if seen!=required.keys():return None
    _,_,first,_=evidence(task,facts)
    missing={r['ridge_id'] for r in facts.get('ridges',[]) if not r.get('planted') and not r.get('harvested')}
    for i,(ids,days) in enumerate(phases):
        if not ids&missing:continue
        at=None
        if i:
            previous=phases[i-1][0]
            if not previous<=first.keys():return dict(target_ridges=sorted(ids&missing),status='TIMING_UNKNOWN',at=None)
            at=max(first[r] for r in previous)+days*86400
        now=M.number(facts.get('now'))
        return dict(target_ridges=sorted(ids&missing),at=at,
                    status='UPCOMING' if at is not None and (now is None or now<at) else 'READY',
                    seconds_until=max(0.,at-now) if at is not None and now is not None else None,
                    source='explicit sowing sequence after previous zone completion; no maturity prediction')
    return None


def machine(tool, facts):
    return facts.get('machines',{}).get(tool.class_instance.name,{})


def supported(tool, task, facts):
    from fairy.agents.jev.constraints import family
    return family(tool)=='TractorApp' and tool.name in ('plant_seeds','replant_seeds','load_seeds') and bool(prescription(task,facts))


def options(tool, argument, values, arguments, task, facts):
    if not supported(tool,task,facts):return values
    required,rows,missing,repairs=target_sets(task,facts)
    m=machine(tool,facts);seed=m.get('seed_type');name=tool.name
    targets=missing if name=='plant_seeds' else repairs if name=='replant_seeds' else missing|repairs
    phase=planting_phase(task,facts)
    if phase and name=='plant_seeds':targets=set(phase['target_ridges']) if phase['status'] in ('READY','TIMING_UNKNOWN') else set()
    elif phase and name=='load_seeds' and missing:targets=set(phase['target_ridges'])
    if argument=='seed_type':
        seeds={required[r][0] for r in targets}
        return {k:v for k,v in values.items() if v in seeds}
    if argument=='start_ridge':
        return {k:v for k,v in values.items() if v in targets and required[v][0]==seed}
    start=arguments.get('start_ridge')
    if start in required and argument in ('seed_spacing_cm','spacing_cm'):
        dose=required[start][1]
        return {k:v for k,v in values.items() if v==dose}
    if start in required and argument=='full_replant':
        # A known cultivar/spacing correction needs an actual restart. Missing
        # stand alone is gap fill; unknown recovery purpose requires observation.
        row=rows.get(start,{})
        mismatch=any(a is not None and a!=b for a,b in
                     ((row.get('seed_type'),required[start][0]),(row.get('seed_spacing_cm'),required[start][1])))
        value=bool(mismatch)
        return {k:v for k,v in values.items() if v is value}
    return values


def range_width(tool, arguments, task, facts, width):
    if not supported(tool,task,facts) or tool.name not in ('plant_seeds','replant_seeds'):return width
    required,rows,missing,repairs=target_sets(task,facts)
    start=arguments.get('start_ridge');targets=missing if tool.name=='plant_seeds' else repairs
    phase=planting_phase(task,facts)
    if phase and tool.name=='plant_seeds':targets=set(phase['target_ridges']) if phase['status'] in ('READY','TIMING_UNKNOWN') else set()
    seed=machine(tool,facts).get('seed_type')
    if start not in targets or required[start][0]!=seed:return 0
    correction=lambda r:any(a is not None and a!=b for a,b in ((rows.get(r,{}).get('seed_type'),required[r][0]),(rows.get(r,{}).get('seed_spacing_cm'),required[r][1])))
    count=0
    while count<width:
        rid=start+count
        if rid not in targets or required.get(rid)!=required[start]:break
        if tool.name=='replant_seeds' and correction(rid)!=correction(start):break
        count+=1
    # Seed use is the native geometry calculation, not an agronomic guess.
    from fairy.agents.jev.menu import scene_world
    hopper=M.number(machine(tool,facts).get('seed_hopper'))
    per=scene_world(tool).plants_per_ridge_from_spacing(required[start][1])
    return min(count,int(hopper//per)) if hopper is not None and per>0 else count


def load_amount(tool, seed, task, facts):
    if not supported(tool,task,facts):return None
    required,rows,missing,repairs=target_sets(task,facts)
    from fairy.agents.jev.menu import scene_world
    from fairy.agents.jev.constraints import load_limit
    world=scene_world(tool);m=machine(tool,facts)
    targets=missing|repairs
    phase=planting_phase(task,facts)
    if phase and missing:targets=set(phase['target_ridges'])
    need=sum(world.plants_per_ridge_from_spacing(required[r][1]) for r in targets if required[r][0]==seed)
    carried=m.get('seed_hopper') if m.get('seed_type')==seed else 0
    cap=load_limit(tool,'count',{'seed_type':seed},facts)
    if M.number(carried) is None or cap is None:return None
    amount=int(min(max(0,need-carried),cap[0]))
    return (amount,'Explicit pending planting/correction targets, native row geometry and observed seed stock/capacity.') if amount>0 else None


def blocker(tool, task, facts):
    if not supported(tool,task,facts):return None
    required,rows,missing,repairs=target_sets(task,facts)
    if tool.name=='load_seeds':
        if not any(load_amount(tool,seed,task,facts) for seed,_ in set(required.values())):
            return 'No additional prescribed seed batch is needed or can fit. Loading is not field planting.'
        return None
    targets=missing if tool.name=='plant_seeds' else repairs
    phase=planting_phase(task,facts)
    if phase and tool.name=='plant_seeds':
        if phase['status']=='UPCOMING':return 'Explicit next sowing phase is not ready. Wait to its recorded reference time; charging is not that crop-stage deadline.'
        targets=set(phase['target_ridges'])
    if not targets:
        if tool.name=='replant_seeds':
            if any(row.get('stand_repair_plateau') for row in rows.values()):
                return ('No new repair target: the last non-reset gap fill did not improve the observed stand base. '
                        'Repeating it on an unchanged target is not seasonal care; reassess only new loss or a prescription mismatch.')
            return ('No confirmed stand loss or prescription mismatch. Zero stand before emergence or with unknown phase is not replant evidence. '
                    'If no required work is ready, advance time and recheck; full_replant=false can still reset pre-emergence crops.')
        return 'No evidenced pending target for this operation; inspect unknown needs rather than restarting correct crops.'
    m=machine(tool,facts);seed=m.get('seed_type')
    if not any(required[r][0]==seed for r in targets):
        return 'Pending targets require another prescribed cultivar. Load its seed before selecting this operation; do not use the current hopper on a different zone.'
    hopper=M.number(m.get('seed_hopper'))
    if hopper is not None:
        from fairy.agents.jev.menu import scene_world
        minimum=min(scene_world(tool).plants_per_ridge_from_spacing(required[r][1]) for r in targets if required[r][0]==seed)
        if hopper<minimum:return 'The correct cultivar is selected, but onboard seed cannot cover one pending ridge. Load the prescribed batch first.'
    return None


def summary(task, facts):
    required,rows,missing,repairs=target_sets(task,facts)
    if not required:return None
    live={r['ridge_id'] for r in facts.get('ridges',[]) if r.get('planted') and not r.get('harvested')}
    unknown=[r['ridge_id'] for r in facts.get('ridges',[]) if r.get('planted') and
             any(rows.get(r['ridge_id'],{}).get(k) is None for k in ('seed_type','seed_spacing_cm'))]
    deferred=[rid for rid,row in rows.items() if rid in live and rid not in missing|repairs and
              row.get('stand_observation',{}).get('status') in ('pre_emergence','emergence_unknown') and
              M.number(row.get('stand_fraction')) is not None and row['stand_fraction']<1.-M.EPS]
    stalled=[rid for rid,row in rows.items() if rid in live and rid not in missing|repairs and row.get('stand_repair_plateau')]
    return dict(version=VERSION,pending_planting_ridges=sorted(missing),prescription_or_stand_repair_ridges=sorted(repairs),
                **({'stand_diagnosis_deferred':dict(ridges=sorted(deferred),
                    reason='Pre-emergence/unknown-phase stand is not confirmed failure or a mandatory inspection queue. '
                           'If no required work is ready, advance time then recheck; no maturity date is inferred.')} if deferred else {}),
                **({'nonimproving_stand_repairs':dict(ridges=sorted(stalled),
                    reason='Actual non-reset gap fill did not improve stand. An unchanged fresh observation does not request another attempt; '
                           'continue other required care or meaningful time advance. New stand loss or prescription errors can reopen repair.')} if stalled else {}),
                next_planting_phase=planting_phase(task,facts),
                unknown_establishment_ridges=unknown,
                instruction='Finish unplanted targets when feasible. Match hopper cultivar, target zone and prescribed spacing. '
                            'Zero stand before emergence is not establishment failure; confirm emergence before diagnosing stand loss. '
                            'Correction is not crop care; acquire a new observation before repeating. Unknown stand is not a restart order.')


def material_indices(task, facts):
    """Successful crop changes are not automatically beneficial progress."""
    from fairy.agents.jev.temporal import MUTATIONS
    _,_,_,plant_progress=evidence(task,facts)
    result=set(plant_progress)
    for i,s,d in data_steps(facts):
        name=M.get(s,'tool_name','').split('__')[-1]
        if name=='plant_seeds' and (facts.get('farms') or facts.get('plots')) and d.get('planted_ridges'):result.add(i)
        elif name in MUTATIONS and name not in ('plant_seeds','replant_seeds') and 'pending' not in str(d.get('status','')):result.add(i)
        elif name in ('load_seeds','load_fertilizer','unload_grain','store_grain','dry_grain'):
            amounts=[M.number(d.get(k)) for k in ('transferred','moved_kg','grain_kg_unloaded','trailer_grain_kg')]
            if any(v is not None and v>0 for v in amounts):result.add(i)
    return result


def report_signature(task,facts):
    crop_fields=('ridge_id','plot_id','planted','harvested','growth_stage','stage','transplanted_area_m2','harvested_area_m2')
    project=lambda units:[{k:r.get(k) for k in crop_fields} for r in units]
    crop=project(facts.get('ridges',[]) or facts.get('plots',[]))
    farms={fid:project(f.get('ridges',[]) or f.get('plots',[])) for fid,f in facts.get('farms',{}).items()}
    _,rows,_,_=evidence(task,facts)
    assignments=[(rid,row.get('seed_type'),row.get('seed_spacing_cm')) for rid,row in sorted(rows.items())]
    # No simulation clock, charging, query counts, report text or wasted seed/fuel.
    failures=[]
    for s in facts.get('steps',[]):
        raw=M.get(s,'content')
        if isinstance(raw,dict) and raw.get('error'):
            failures.append((M.get(s,'tool_name'),M.get(s,'tool_args'),raw['error']))
    value={'material_action':max(material_indices(task,facts),default=-1),'crop':crop,'farms':farms,'assignments':assignments,'latest_error':failures[-1] if failures else None,
           'grain':{k:facts.get('inventory',{}).get(k) for k in ('harvest_grain_kg','warehouse_grain_kg')}}
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()[:24]


def report_allowed(task,facts,current_report=None):
    from fairy.agents.jev.state_semantics import lifecycle
    if not lifecycle(task)['seasonal_task']:return True
    last=None
    for i,s in enumerate(facts.get('steps',[])):
        if not (M.get(s,'tool_name') or '').endswith('__send_message_to_user') or M.get(s,'op_type')!='TOOL':continue
        raw=M.get(s,'content')
        # Native UI echoes a string; it is not a farm-operation dict receipt.
        if isinstance(raw,dict) and (raw.get('error') or raw.get('ok') is False or raw.get('status') in ('error','failed','rejected')):continue
        last=(i,s)
    if last is None:return True
    i,s=last;text=str((M.get(s,'tool_args',{}) or {}).get('content',M.get(s,'content','')))
    match=re.search(re.escape(CHECKPOINT)+r'([a-f0-9]{24})',text)
    if match:return match[1]!=report_signature(task,facts)
    # Derive the earlier checkpoint from the immutable prefix. Do not append
    # internal hashes to messages shown to people or rewrite old reports.
    earlier={**facts,'steps':facts.get('steps',[])[:i]}
    if report_signature(task,earlier)!=report_signature(task,facts):return True
    def crop_view(content):
        def clean(v):
            if isinstance(v,list):return [clean(x) for x in v]
            if isinstance(v,dict):return {k:clean(x) for k,x in v.items() if k not in
                ('inventory','management','machines','pending_effects','time','name','current_time')}
            return v
        if isinstance(content,(list,dict)):return clean(content)
        line=next((s[len('Crop now: '):] for s in str(content).splitlines() if s.startswith('Crop now: ')),None)
        if line is None:return None
        try:return clean(json.loads(line))
        except (ValueError,TypeError):return None
    old,current=crop_view(text),crop_view(current_report)
    return old is not None and current is not None and old!=current
