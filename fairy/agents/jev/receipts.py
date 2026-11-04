"""Enhanced receipt accounting. Original workflows and repeat detection are untouched."""
from __future__ import annotations
from fairy.agents.jev.management import get, number, successes, timestamp
from fairy.agents.jev.snapshot import _result_data, _range_of, ridge_ranges

COVERAGE_KEYS = ('surveyed_ridges','covered_ridges','planted_ridges','replanted_ridges','harvested_ridges',
                 'fertilized_ridges','fertigated_ridges','treated_ridges','weeded_ridges',
                 'sprayed_ridges','incorporated_ridges','tilled_ridges')


def receipt_summary(step):
    raw = get(step,'content'); data = _result_data(raw)
    args = get(step,'tool_args',{}) or {}
    failed = (get(step,'op_type') == 'TOOL_ERROR' or isinstance(raw,dict) and
              (raw.get('ok') is False or 'error' in raw))
    d = data if isinstance(data,dict) else {}
    status = 'no_op' if d.get('transfer_status') == 'no_op' else d.get('status','unknown')
    failed = failed or status in ('failed','error','rejected')
    coverage = next((d[k] for k in COVERAGE_KEYS if isinstance(d.get(k),list)), None)
    transfer = {k:d[k] for k in ('transfer_version','requested','transferred','onboard','remaining_capacity','inventory_remaining','unit','transfer_status') if k in d}
    return dict(transfer=transfer or None, status='failed' if failed else status,
                requested_ridges=_range_of(args), covered_ridges=coverage,
                uncovered_ridges=d.get('uncovered_ridges'), skipped_ridges=d.get('skipped_ridges'),
                warning=d.get('warning'), effect_ready_at=d.get('effect_ready_at'),
                coverage_known=coverage is not None)


def enhance_snapshot(snapshot, facts):
    work = {}; history_runs = []; summaries = []
    for i,s in enumerate(facts.get('steps',[]),1):
        r = receipt_summary(s); name = get(s,'tool_name','')
        scope = {k:v for k,v in (get(s,'tool_args',{}) or {}).items() if k in ('farm_id','asset_id','plot_id')}
        key = name + (' '+str(scope) if scope else '')
        row = work.setdefault(key, dict(successful_receipts=0,actual_ridges=[],unknown_coverage_calls=0,partial_calls=0,failed_calls=0,no_op_calls=0))
        if r['status'] == 'failed': row['failed_calls'] += 1
        elif r['status'] == 'no_op': row['no_op_calls'] += 1
        else:
            row['successful_receipts'] += 1
            if r['covered_ridges'] is not None: row['actual_ridges'] = sorted(set(row['actual_ridges']) | set(r['covered_ridges']))
            elif r['requested_ridges'] is not None: row['unknown_coverage_calls'] += 1
            if str(r['status']).startswith('partial'): row['partial_calls'] += 1
        text = f"{name}({get(s,'tool_args',{})}): {r['status']}"
        if r['covered_ridges'] is not None: text += ' actual ridges '+ridge_ranges(r['covered_ridges'])
        elif r['requested_ridges'] is not None: text += ' actual coverage unknown'
        if r['uncovered_ridges']: text += ' uncovered '+ridge_ranges(r['uncovered_ridges'])
        if r['warning']: text += ' warning '+str(r['warning'])
        if r['transfer']: text += ' transfer '+str(r['transfer'])
        when=get(s,'time_after',get(s,'time'))
        if history_runs and history_runs[-1]['text']==text:
            history_runs[-1].update(last=i,last_time=when)
        else:
            history_runs.append(dict(first=i,last=i,text=text,first_time=when,last_time=when))
        summaries.append(dict(action_index=i,action=name,**r))
    snapshot['farm_now']['actions_this_run'] = work
    snapshot['steps_so_far'] = [
        (f"{r['first']}. {r['text']}" if r['first']==r['last'] else
         f"{r['first']}-{r['last']}. {r['text']} (x{r['last']-r['first']+1}; recorded time {r['first_time']} to {r['last_time']})")
        for r in history_runs]

    # Keep the same recent-action slots and raw receipts; do not silently
    # introduce a second history-attention intervention during this revision.
    snapshot['recent_receipt_status'] = summaries[-5:]
    return snapshot


def grain_state(facts):
    """Track the current local pending batch via receipts and public inventory.

    A global grain_dried flag cannot attest a new batch. An empty dry receipt
    cannot repair grain previously admitted with a spoilage warning.
    """
    inv = facts.get('inventory',{})
    pending = inv.get('harvest_grain_kg')
    result = dict(pending_kg=pending, safe_current_batch=None, unsafe_stored_batches=[],
                  evidence='Unknown moisture requires batch observation or drying; a previous batch flag is not evidence.')
    safe = None
    for s,d in successes(facts):
        name = get(s,'tool_name','').split('__')[-1]
        if name == 'unload_grain' and (number(d.get('grain_kg_unloaded')) or 0) > 0:
            safe = None
        if name == 'dry_grain' and (number(d.get('trailer_grain_kg')) or 0) > 0:
            target = number(d.get('target_moisture_pct',d.get('storage_grain_moisture_pct')))
            limit = number(d.get('max_storage_moisture_pct'))
            if limit is None: limit = number(inv.get('storage',{}).get('max_storage_moisture_pct'))
            if target is not None and limit is not None: safe = target <= limit
        if name == 'store_grain' and (number(d.get('moved_kg')) or 0) > 0:
            moisture = number(d.get('storage_grain_moisture_pct'))
            limit = number(d.get('max_storage_moisture_pct'))
            if d.get('warning') or moisture is not None and limit is not None and moisture > limit:
                result['unsafe_stored_batches'].append(dict(action_index=facts.get('steps',[]).index(s)+1,
                    ridges=d.get('batch_ridge_ids'),kg=d['moved_kg'],warning=d.get('warning'),moisture_pct=moisture))
            safe = None
    result['safe_current_batch'] = safe if (number(pending) or 0) > 0 else None
    return result


def paddy_batches(facts):
    """Public batch identities plus acquired moisture/dryer receipts, not hidden grain fields."""
    batches = {b['batch_id']:dict(b,moisture_pct=None) for b in facts.get('inventory',{}).get('grain_batches',[])}
    for s,d in successes(facts):
        name=get(s,'tool_name','').split('__')[-1]
        args=get(s,'tool_args',{}) or {}
        bid=d.get('batch_id') or args.get('batch_id')
        if bid not in batches: continue
        if name in ('measure_grain_moisture','dry_grain') and number(d.get('moisture_pct')) is not None:
            batches[bid]['moisture_pct']=d['moisture_pct']
    return list(batches.values())
