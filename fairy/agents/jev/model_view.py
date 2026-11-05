"""Bounded enhanced-Jev presentation, separate from exact internal ledgers.

Historical receipts may be evicted by age/count/bytes with explicit omission
metadata. Current task, choices and management facts are not historical cache.
Byte budgets are engineering guards, not claims about the hosted tokenizer.
"""
from __future__ import annotations
import copy
import json
from datetime import datetime
from hashlib import sha256
from fairy.agents.jev import management as M
from fairy.agents.jev.snapshot import _result_data, _range_of
from fairy.agents.jev.receipts import COVERAGE_KEYS
from fairy.agents.jev import state_semantics as S

VERSION = 'bounded-model-view-v7'
RECENT_LIMIT = 5
OBSERVATION_LIMIT = 5
FAILURE_LIMIT = 5
HISTORY_MAX_AGE_SECONDS = 86400
OBSERVATION_BYTES = None
FAILURE_BYTES = None
RESULT_PREVIEW_BYTES = None
REQUEST_TARGET_BYTES = 40000
HISTORY_POLICY = 'whole-receipt-window-v1'
REQUEST_ENVELOPE_BYTES = 48000
ANSWER_ALLOWANCE_BYTES = 8000
MAP_KEYS = {'ridge_product_kg','planting_timestamps','planting_cohorts','root_water_by_ridge',
            'assigned_mm_by_ridge','remaining_mm_by_ridge','remaining_by_ridge_kg','observed_upper_vwc_by_ridge'}
ID_KEYS = {'ridges','ridge_ids','actual_ridges','covered_ridges','requested_ridges','uncovered_ridges',
           'skipped_ridges','remaining_ridges','cycle_covered_ridges','not_observed_ridges','pending_ridges','harvested_ridges','planted_ridges',
           'fertilized_ridges','fertigated_ridges','irrigated_ridges','treated_ridges','surveyed_ridges',
           'verified_ridges','unknown_ridges','pending_fertilizer_ridges',
           'pending_planting_ridges','prescription_or_stand_repair_ridges','unknown_establishment_ridges'}
CONVENTIONS = ("Event 'at' uses simulation UTC+08; explicitly labelled UTC fields retain UTC. Ranges are inclusive; grouped values are exact, not averages. "
               'Completed work is historical evidence, not completion of later rounds. '
               'Observations retain tool source and timestamp; differing sources/times are not interchangeable. '
               'Historical failures with unknown recovery are not proven current blockers. '
               'exact_keyed_columns_v1 stores row_keys in order; each field is constant or an aligned values array. '
               'Retained observations/failures are complete; reports keep delivery facts. Old receipts may be omitted as whole records by age/count/request budget. '
               'Omitted does not mean resolved or complete. '
               'Full receipts and exact ledgers remain in the workflow/internal adapter.')
SHA256 = sha256((VERSION+CONVENTIONS+str((RECENT_LIMIT,OBSERVATION_LIMIT,FAILURE_LIMIT,
    HISTORY_MAX_AGE_SECONDS,OBSERVATION_BYTES,FAILURE_BYTES,REQUEST_TARGET_BYTES,
    RESULT_PREVIEW_BYTES,REQUEST_ENVELOPE_BYTES,ANSWER_ALLOWANCE_BYTES))).encode()).hexdigest()


class ContextBudgetError(ValueError):
    """Protected task/state/questions cannot fit; do not call or retry service."""


def encode(v):
    return json.dumps(v,ensure_ascii=False,separators=(',',':'),default=str).encode()


def ranges(ids):
    runs=[]
    for i in ids:
        if runs and runs[-1][1]+1==i:runs[-1][1]=i
        else:runs.append([i,i])
    return ','.join(str(a) if a==b else f'{a}-{b}' for a,b in runs)


def compact(value, key=None):
    """Lossless grouping of ridge maps/lists and per-ridge observation rows."""
    if isinstance(value,dict):
        if key in MAP_KEYS and value and all(str(k).isdigit() and str(int(k))==str(k) for k in value):
            groups=[]
            for rid,v in sorted(((int(k),v) for k,v in value.items())):
                if groups and groups[-1]['end']+1==rid and encode(groups[-1]['value'])==encode(v):groups[-1]['end']=rid
                else:groups.append(dict(start=rid,end=rid,value=copy.deepcopy(v)))
            return dict(encoding='inclusive_ridge_ranges',groups=groups)
        return {k:compact(v,k) for k,v in value.items()}
    if isinstance(value,list):
        if key in ID_KEYS and value and all(type(v)==int for v in value):
            return dict(encoding='ordered_ridge_ranges',ranges=ranges(value),count=len(value))
        if value and all(isinstance(v,dict) and type(v.get('ridge_id'))==int for v in value):
            groups=[]
            for row in value:
                rid=row['ridge_id'];rest={k:v for k,v in row.items() if k!='ridge_id'}
                if groups and groups[-1]['end']+1==rid and encode(groups[-1]['values'])==encode(rest):groups[-1]['end']=rid
                else:groups.append(dict(start=rid,end=rid,values=copy.deepcopy(rest)))
            return dict(encoding='inclusive_ridge_rows',groups=[{**g,'values':compact(g['values'])} for g in groups])
        return [compact(v) for v in value]
    return copy.deepcopy(value)


def clock(step):
    t=M.timestamp(M.get(step,'time_after'))
    if t is None:t=M.timestamp(M.get(step,'time'))
    return datetime.fromtimestamp(t,M.CST).strftime('%Y-%m-%d %H:%M:%S') if t is not None else None


def classify(step):
    name=M.get(step,'tool_name','');method=name.split('__')[-1]
    raw=M.get(step,'content');data=_result_data(raw)
    failed=(M.get(step,'op_type')=='TOOL_ERROR' or isinstance(raw,dict) and (raw.get('error') or raw.get('ok') is False)
            or isinstance(data,dict) and data.get('status') in ('failed','error','rejected'))
    if failed:return 'failure'
    if isinstance(data,dict) and data.get('transfer_status')=='no_op':return 'no_op'
    if method=='send_message_to_user':return 'report'
    if method in ('advance_time','wait_for_notification'):return 'wait'
    if method.startswith(('get_','read_','inspect_','check_','measure_')) or method=='fly_survey':return 'observation'
    return 'operation'


def irrigation_view(water):
    water=copy.deepcopy(water);active=water.pop('active',None)
    # A pointer keeps the applicable round visible without duplicating its map.
    # Reading probes completes a check, not the reference delivery itself.
    water['active_reference_index']=active.get('index') if active else None
    pending=bool(water.get('pending_ridges'))
    for r in water.get('rounds',[]):
        if not r.get('remaining_mm_by_ridge'):
            r['status']='AMOUNT_ACCOUNTED_PENDING_EFFECT' if pending and active and r.get('index')==active.get('index') else 'REFERENCE_AMOUNT_ACCOUNTED'
    return water


def fertilizer_reference(context, now):
    """Separate a quantity remainder from the timing of its task reference.

    References are soft guidance. Unknown timing is never inferred to be due,
    and these labels do not change tool legality, dosage or execution.
    """
    current=context.get('next_ridge_fertilizer_round')
    if not current:
        return None
    result=copy.deepcopy(current)
    matches=[w for w in context.get('windows',[]) if w.get('kind')=='fertilizer'
             and w.get('target')=='field' and w.get('reference_day')==current.get('reference_day')]
    at=M.number(matches[0].get('at')) if matches else None
    known=at is not None and M.number(now) is not None
    result['timing_status']=('DUE_REFERENCE' if at<=now else 'UPCOMING_REFERENCE') if known else 'TIMING_UNKNOWN'
    result['seconds_until_reference']=max(0.,at-now) if known else None
    return result


def note_omission(view,section,reason):
    meta=view.setdefault('history_retention',dict(policy=HISTORY_POLICY,omitted={},
        meaning='Omitted is not resolved or complete; inspect again if needed. Current facts/blockers are separate.'))
    counts=meta['omitted'].setdefault(section,{})
    counts[reason]=counts.get(reason,0)+1


def prune_history(view):
    """Drop old historical rows, keeping retained result structures complete.

    Age is a cache-retention policy, not an agronomic validity assertion. A
    current blocked_actions/last_blocker predicate is managed independently.
    Input is an owned copy, already compacted; exact ledgers are not touched.
    """
    sections=(('latest_observations',OBSERVATION_LIMIT),
              ('unresolved_failures',FAILURE_LIMIT))
    present=[s for s,_ in sections if isinstance(view.get(s),list)]
    if not present:
        return
    for section,count in sections:
        if section not in present:
            continue
        rows=view[section]
        def note(reason):
            note_omission(view,section,reason)
        kept=[]
        for row in rows:
            age=M.number(row.get('age_seconds')) if isinstance(row,dict) else None
            if age is not None and age>HISTORY_MAX_AGE_SECONDS:
                note('age')
            else:kept.append(row)
        # Stable fallback to supplied order when an action index is unknown.
        kept=sorted(enumerate(kept),key=lambda x:(x[1].get('action_index',x[0]) if isinstance(x[1],dict) else x[0]))
        rows[:]=[r for _,r in kept]
        while len(rows)>count:
            rows.pop(0);note('count')


def project(state, facts, context, now, labels=None):
    """Use workflow evidence, not previously truncated recent-result strings."""
    labels=labels or {};steps=facts.get('steps',[]);events=[];observations={};failures={};work={};waits=0;resolved=0
    for i,step in enumerate(steps,1):
        name=M.get(step,'tool_name','');args=M.get(step,'tool_args',{}) or {};data=_result_data(M.get(step,'content'))
        kind=classify(step);signature=(name,encode(args));row=dict(action_index=i,at=clock(step),action=name,arguments=compact(args),kind=kind)
        if i in labels:row['round_boundary']={k:v for k,v in labels[i].items() if k!='meaning'}
        # Equality includes untruncated raw result, not just a 1500-char prefix.
        when=M.timestamp(M.get(step,'time_after'))
        if when is None:when=M.timestamp(M.get(step,'time'))
        identity=(name,encode(args),encode(data),when)
        if kind=='failure':
            row['result']=compact(data if data is not None else M.get(step,'content'));old=failures.get(signature)
            row['count']=(old.get('count',1)+1) if old else 1
            row['recovery_status']='unknown; historical failure, not proof of a current blocker'
            if S.resolved_failure(step,steps[i:]):
                resolved+=1
            else:failures[signature]=row
        else:
            if (_range_of(args) is None and (kind=='observation' or isinstance(data,dict) and
                    data.get('status') in ('ok','success','completed') and data.get('transfer_status') != 'partial')):
                failures.pop(signature,None)  # Spatial recovery requires actual full coverage above.
            if kind=='observation':
                row['status']='observation_received';row['result']=compact(data)
                old=observations.get(signature)
                if old and old['_identity']==identity:row['repeat_count']=old.get('repeat_count',1)+1
                observations[signature]={**row,'_identity':identity,'_raw_result':data,'_when':when,'_args':args}
            elif kind=='wait':waits+=1
            elif kind=='report':
                # Generated report text repeats facts already in the current
                # view. Keep its delivery fact, not another full farm snapshot.
                row['arguments']={'content_in_original_workflow':True}
                row['result']={'report_sent':True,'original_receipt_in_workflow':True}
            else:
                row['result']=compact(data)
                scope={k:v for k,v in args.items() if k in ('farm_id','plot_id','asset_id')}
                k=name+(' '+json.dumps(scope,ensure_ascii=False,sort_keys=True) if scope else '')
                w=work.setdefault(k,dict(receipts=0,actual_ridges=set(),last_at=None))
                w['receipts']+=int(kind!='no_op');w['last_at']=row['at']
                if kind=='no_op':w['no_op_receipts']=w.get('no_op_receipts',0)+1
                if isinstance(data,dict):
                    for field,v in data.items():
                        if field in (*COVERAGE_KEYS,'irrigated_ridges') and isinstance(v,list) and all(type(x)==int for x in v):w['actual_ridges'].update(v)
        # Merge interleaved identical observations at identical simulated time.
        match=next((x for x in events if x['_identity']==identity),None)
        if match:
            match['repeat_count']=match.get('repeat_count',1)+1;match['last_action_index']=i
            events.remove(match);events.append(match)
        else:events.append({**row,'_identity':identity})
        events=events[-RECENT_LIMIT:]
    clean=lambda rows:[{k:v for k,v in r.items() if not k.startswith('_')} for r in rows]
    latest=sorted(observations.values(),key=lambda x:x['action_index'])
    latest,superseded=S.superseded_observations(latest)
    for row in latest:
        row['age_seconds']=max(0.,now-row['_when']) if row['_when'] is not None and row['_when']<=now else None
        row['validity']='dated evidence; freshness/comparability not assumed'
    for row in failures.values():
        at=M.timestamp(row['at'])
        row['age_seconds']=max(0.,now-at) if at is not None and at<=now else None
    recent=clean(events)
    # Recent observations/failures already have a single dedicated section.
    recent=[{k:v for k,v in r.items() if k!='result'} if r['kind'] in ('observation','failure') else r for r in recent]
    management={k:copy.deepcopy(v) for k,v in context.items() if k not in ('ledger','rules','ridge_irrigation','next_ridge_fertilizer_round','plot_progress','clocks','establishment')}
    if context.get('ridge_irrigation'):management['ridge_irrigation']=irrigation_view(context['ridge_irrigation'])
    # Exact product balance remains available, without per-ridge timestamps.
    ledger=context.get('ledger',{})
    balance={k:ledger[k] for k in ('basal_used_kg','ridge_product_kg','plot_doses_kg_ha') if k in ledger}
    management['product_accounting']=balance
    # Presentation names must not turn unknown schedules into "nothing to do".
    progress=management.get('field_progress')
    if progress:
        progress['pending_fertilizer_ridges']=progress.pop('remaining_ridges',[]) if context['plan'].get('kind') else None
        progress.pop('remaining_ridges',None)
        progress['pending_fertilizer_product_kg']=progress.pop('remaining_product_kg',None)
        progress['fertilizer_schedule_status']='parsed' if context['plan'].get('kind') else 'not_parsed'
        # This is the existing scheduling anchor, not the age of every plant.
        # Keep cohort ages too for staggered sowing rather than deleting the
        # direct elapsed-time cue used by the earlier successful normal run.
        progress['planting_age_basis']='days since latest confirmed crop-cycle start, including phenology reset; individual cohorts can be older; not maturity'
    planting=ledger.get('planting_timestamps',{})
    if planting and all(str(k).isdigit() for k in planting):
        management['planting_cohorts']=S.planting_cohorts(planting,now)
    # Keep pending/unsafe batch evidence; do not display a drying warning for zero grain.
    post=management.get('postharvest',{})
    if post.get('pending_kg')==0 and not post.get('unsafe_stored_batches'):
        management['postharvest']={'pending_kg':0,'status':'no_pending_batch'}
    if not facts.get('plots'):
        for key in ('grain_batches','shared_clock_note'):
            management.pop(key,None)
        management['schedule_basis']='Parsed ridge reference windows use last sowing after establishment; cohort ages are separate, not maturity estimates.'
        for key in ('rice_fertilizer_days','water_interval_days','periodic_checks','daily_maturity_from_day'):
            management['plan'].pop(key,None)
    farm=copy.deepcopy(state.get('farm_now',{}))
    for k in ('actions_this_run','action_history_scope'):farm.pop(k,None)
    if facts.get('ridges'):
        farm['crop']=S.crop_groups(facts['ridges'])
    due=[w for w in context.get('windows',[]) if w['at']<=now]
    focus=dict(version=VERSION,due_checkpoints=due,next_fertilizer_round=fertilizer_reference(context,now),
               plot_progress=context.get('plot_progress',[]),waiting='Defer due work only for an actual blocker.' if due else 'Wait only when no required work is ready.')
    if context.get('establishment'):focus['establishment']=copy.deepcopy(context['establishment'])
    focus['schedule_interpretation']=('Known parsed reference checks only; no due checkpoint is not proof that care is complete.'
        if context['plan'].get('kind') else 'Fertilizer prescription not parsed; empty checkpoints mean unknown care needs, not completed care.')
    focus['schedule_interpretation']+=' A remaining dose or loaded batch is not an instruction to apply it now. UPCOMING_REFERENCE is future planning; check actual need before deviating. An observed check is not a delivered dose.'
    result=dict(task=state['task'],view_version=VERSION,time_basis=CONVENTIONS,
                current_decision=focus,farm_now=farm,management_progress=management,
                task_compliance=S.task_compliance(state['task'],facts),
                latest_observations=clean(latest),
                unresolved_failures=list(failures.values()),recent_events=recent,
                completed_work={k:{**v,'actual_ridges':sorted(v['actual_ridges'])} for k,v in work.items()},
                history_summary=dict(total_actions=len(steps),wait_calls=waits,resolved_failed_targets=resolved,
                                     equivalent_observations_superseded=superseded,
                                     note='Full receipts remain in workflow; completion of new rounds is determined only by current_decision.'))
    # Preserve future extension fields; remove only known redundant presentations.
    for k,v in state.items():
        if k not in result and k not in ('recent_actions','recent_receipt_status','actions_so_far','steps_so_far','current_decision'):
            result[k]=copy.deepcopy(v)
    result=S.pack_columns(compact(result))
    prune_history(result)
    return result


def request_guard(state, questions, model=None, *, limit=REQUEST_ENVELOPE_BYTES-ANSWER_ALLOWANCE_BYTES):
    """Prefer a bounded working view, evicting old history before hard stop."""
    view=S.pack_columns(state)
    measured=lambda:len(encode(dict(state=view,questions=questions,model=model)))
    before=measured();removed=[]
    prune_history(view)
    target=min(limit,REQUEST_TARGET_BYTES)
    if measured()>target:
        for key in ('recent_events','completed_work'):
            if key in view:
                view.pop(key);removed.append(key)
                if measured()<=target:break
    # After optional summaries, oldest historical evidence yields. Never delete
    # task/choices/current snapshot/management/blocked_actions to meet a target.
    while measured()>target:
        rows=[(name,row) for name in ('latest_observations','unresolved_failures')
              for row in view.get(name,[]) if isinstance(row,dict)]
        if not rows:break
        name,row=min(rows,key=lambda item:(item[1].get('action_index',-1),
                                           -float(item[1].get('age_seconds') or 0)))
        view[name].remove(row)
        note_omission(view,name,'request_budget')
    after=measured()
    info=dict(version=VERSION,request_bytes=after,original_request_bytes=before,input_limit_bytes=limit,
              response_allowance_bytes=ANSWER_ALLOWANCE_BYTES,working_target_bytes=target,working_target_met=after<=target,
              history_retention=copy.deepcopy(view.get('history_retention')),
              removed_optional_sections=removed,
              measurement='UTF-8 JSON byte guard; not service token count',status='passed' if after<=limit else 'blocked_before_network')
    if after>limit:
        error=ContextBudgetError(f'Protected Jev request needs {after} bytes, exceeding local input guard {limit}; no service request sent.')
        error.budget=info;raise error
    return view,info
