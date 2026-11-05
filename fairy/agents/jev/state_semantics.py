"""Enhanced-only presentation contracts derived from public facts/receipts.

No tool calls, oracle access, agronomic prescriptions or recovery actions.
Unknown evidence remains unknown. These helpers do not replace native validation.
"""
from __future__ import annotations

import copy
import json
import re
import math
from datetime import datetime

from fairy.agents.jev import management as M
from fairy.agents.jev.snapshot import _result_data, _range_of

VERSION = 'public-state-semantics-v1.2'
COLUMN_ENCODING = 'exact_keyed_columns_v1'


def lifecycle(task):
    """Conservative shared recognition; an unrecognised task is not short-term."""
    forbidden = bool(re.search(r'(?:禁止|无需|不得|不要)收获|do not harvest', task, re.I))
    explicit = bool(re.search(r'全季|全周期|全生长期|full[ -]season|whole season', task, re.I))
    sequence = bool(re.search(r'收获|harvest', task, re.I) and
                    re.search(r'播种|插秧|生育|成熟|生长|plant|growth|matur', task, re.I))
    seasonal = (explicit or sequence) and not forbidden
    return dict(seasonal_task=seasonal,
                recognition='seasonal' if seasonal else 'harvest_forbidden' if forbidden else 'unknown',
                basis='explicit seasonal language or planting-to-harvest objective; not a care prescription')


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str).encode()


def pack_columns(value):
    """Reversible, size-reducing encoding of homogeneous numeric-key row maps.

    Constants use JSON equality (so bool/int are not conflated). No rounding,
    averaging, field deletion or cross-source merging occurs.
    """
    if isinstance(value, list):
        return [pack_columns(v) for v in value]
    if not isinstance(value, dict):
        return copy.deepcopy(value)
    rebuilt = {k: pack_columns(v) for k, v in value.items()}
    numeric_key = lambda k: type(k) is int and k >= 0 or isinstance(k, str) and k.isdigit()
    if not value or not all(numeric_key(k) and isinstance(v, dict)
                            for k, v in value.items()):
        return rebuilt
    # Do not conflate a live integer key with a separate string key of the same
    # spelling. Both native integer keys and archived string keys stay typed in
    # row_keys, and the decoder preserves them exactly.
    if len({str(k) for k in value}) != len(value):
        return rebuilt
    keys = list(value)
    fields = list(value[keys[0]])
    if not all(set(v) == set(fields) for v in value.values()):
        return rebuilt
    columns = {}
    for field in fields:
        vals = [rebuilt[k][field] for k in keys]
        columns[field] = ({'constant': vals[0]} if all(_bytes(v) == _bytes(vals[0]) for v in vals)
                          else {'values': vals})
    candidate = dict(encoding=COLUMN_ENCODING, row_keys=keys, columns=columns)
    return candidate if len(_bytes(candidate)) < len(_bytes(rebuilt)) else rebuilt


def unpack_columns(value):
    """Decoder for verification/export; runtime uses the explicit column view."""
    if isinstance(value, list):
        return [unpack_columns(v) for v in value]
    if not isinstance(value, dict):
        return copy.deepcopy(value)
    if value.get('encoding') == COLUMN_ENCODING and set(value) == {'encoding', 'row_keys', 'columns'}:
        return {k: {field: unpack_columns(col['constant'] if 'constant' in col else col['values'][i])
                    for field, col in value['columns'].items()} for i, k in enumerate(value['row_keys'])}
    return {k: unpack_columns(v) for k, v in value.items()}


def observation_rows(data):
    if not isinstance(data, dict):
        return None
    rows=data.get('ridges')
    if not isinstance(rows,list):
        observed=data.get('observations')
        if not isinstance(observed,dict) or not observed:return None
        rows=[]
        for key,value in observed.items():
            if not isinstance(value,dict) or not str(key).isdigit():return None
            rid=int(key)
            if value.get('ridge_id',rid)!=rid:return None
            rows.append({**value,'ridge_id':rid})
    if not rows or not all(isinstance(r, dict) and type(r.get('ridge_id')) is int for r in rows):
        return None
    if len({r['ridge_id'] for r in rows}) != len(rows):
        return None
    return {r['ridge_id']: r for r in rows}


def target_context(args):
    return {k: v for k, v in args.items()
            if k not in ('start', 'end', 'start_ridge', 'end_ridge', 'ridge_id')}


def superseded_observations(observations):
    """Only same tool, time, scope, metadata and equal overlap can supersede.

    Acquired rows, not requested ranges, prove coverage. Differing observations
    or clocks are retained, even when one requests the whole field.
    """
    removed = set()
    for i, old in enumerate(observations):
        a = observation_rows(old['_raw_result'])
        if a is None or old['_when'] is None:
            continue
        for j, new in enumerate(observations):
            if i == j or old['action_index'] >= new['action_index']:
                continue
            b = observation_rows(new['_raw_result'])
            if (b is None or old['action'] != new['action'] or old['_when'] != new['_when'] or
                    _bytes(target_context(old['_args'])) != _bytes(target_context(new['_args']))):
                continue
            metadata = lambda r: {k: v for k, v in r.items() if k != 'ridges'}
            if (_bytes(metadata(old['_raw_result'])) == _bytes(metadata(new['_raw_result'])) and
                    a.keys() <= b.keys() and all(_bytes(r) == _bytes(b[k]) for k, r in a.items())):
                removed.add(i)
                break
    return [v for i, v in enumerate(observations) if i not in removed], len(removed)


def resolved_failure(failure_step, subsequent):
    """Later actual coverage can resolve a historical failed target.

    Never infer recovery from elapsed time, replenishment, requested coverage or
    a different operation/variety. Partial successes must cover every target.
    """
    args = M.get(failure_step, 'tool_args', {}) or {}
    wanted = _range_of(args)
    if not wanted:
        return False
    remaining = set(wanted)
    name = M.get(failure_step, 'tool_name', '')
    from fairy.agents.jev.receipts import COVERAGE_KEYS
    for s, data in M.successes({'steps': subsequent}):
        if (M.get(s, 'tool_name', '') != name or
                _bytes(target_context(M.get(s, 'tool_args', {}) or {})) != _bytes(target_context(args)) or
                data.get('status') in ('rejected', 'no_op') or 'pending' in str(data.get('status', ''))):
            continue
        for key in COVERAGE_KEYS:
            ids = data.get(key)
            if isinstance(ids, list):
                remaining.difference_update(x for x in ids if type(x) is int)
    return not remaining


def task_compliance(task, facts):
    """Compare explicit ridge cultivar/spacing clauses with acquired rows.

    Keep each source/scope separate; do not decide which sensor is true. A
    mismatch is a dated observation, not a command to replant or a done guard.
    """
    from fairy.agents.jev.seed_candidates import _PLAN
    expected = {}
    allowed = {r['ridge_id'] for r in facts.get('ridges', [])}
    for m in _PLAN.finditer(task):
        lo, hi = int(m[1]), int(m[2])
        if not allowed or lo > hi or hi-lo+1 > len(allowed):
            return dict(status='unknown', reason='Explicit zone outside known field scope')
        ids = set(range(lo, hi+1))
        if not ids <= allowed or expected.keys() & ids:
            return dict(status='unknown', reason='Overlapping or out-of-scope explicit zones')
        expected.update({rid: dict(seed_type=m[3], seed_spacing_cm=float(m[4])) for rid in ids})
    if not expected:
        return dict(status='not_parsed', reason='No supported explicit ridge cultivar/spacing clauses; no compliance inferred')
    sources = {}
    changed={}
    for index,step in enumerate(facts.get('steps',[]),1):
        for _,data in M.successes({'steps':[step]}):
            method=M.get(step,'tool_name','').split('__')[-1]
            ids=(data.get('planted_ridges',[]) if method=='plant_seeds' else
                 data.get('phenology_reset_ridges',[]) if method=='replant_seeds' else [])
            for rid in ids:changed[rid]=index
    for index, step in enumerate(facts.get('steps', []), 1):
        if not list(M.successes({'steps': [step]})):
            continue
        data = _result_data(M.get(step, 'content'))
        rows = observation_rows(data)
        if rows is None:
            continue
        # Stand/pest-only observations cannot answer a cultivar/spacing
        # question. Keep them in observations and establishment evidence,
        # rather than adding another full-field "unknown prescription" list.
        rows={rid:row for rid,row in rows.items() if
              row.get('seed_type') is not None or row.get('seed_spacing_cm') is not None}
        if not rows:continue
        args = M.get(step, 'tool_args', {}) or {}
        scope = {k: args[k] for k in ('farm_id', 'plot_id', 'asset_id') if k in args}
        key = (M.get(step, 'tool_name'), _bytes(scope))
        bucket = sources.setdefault(key, dict(source=key[0], scope=scope, rows={}))
        for rid, row in rows.items():
            if rid in expected:
                bucket['rows'][rid] = (row, index, M.get(step, 'time_after', M.get(step, 'time')))
    result = []
    for bucket in sources.values():
        mismatches = []; verified = []; unknown = []
        for rid, requirement in expected.items():
            observed = bucket['rows'].get(rid)
            if observed is None or changed.get(rid,-1)>observed[1]:
                unknown.append(rid); continue
            row, index, at = observed
            fields = {k: row[k] for k in requirement if row.get(k) is not None}
            wrong = {k: v for k, v in fields.items() if _bytes(v) != _bytes(requirement[k])
                     and not (M.number(v) is not None and M.number(requirement[k]) is not None and v == requirement[k])}
            if wrong:
                mismatches.append(dict(ridge_id=rid, expected=requirement, observed=fields, action_index=index, at=at))
            elif len(fields) == len(requirement):
                verified.append(rid)
            else:
                unknown.append(rid)
        result.append(dict(source=bucket['source'], scope=bucket['scope'],
                           mismatches=mismatches, verified_ridges=verified, unknown_ridges=unknown))
    return dict(status='evidence_compared' if result else 'not_observed', expected_ridges=len(expected),
                sources=result, interpretation='Dated per-source comparisons only; no automatic recovery or native task validation')


def crop_groups(ridges):
    groups = []
    for r in ridges:
        values = {k: r.get(k) for k in ('planted', 'harvested', 'growth_stage')}
        rid = r['ridge_id']
        if groups and groups[-1]['end']+1 == rid and groups[-1]['values'] == values:
            groups[-1]['end'] = rid
        else:
            groups.append(dict(start=rid, end=rid, values=values))
    return dict(source='existing public snapshot; stored stage is not a planting flag', groups=groups)


def planting_cohorts(timestamps, now):
    """Adjacent same-date cohorts with enclosing age bounds; exact ledger stays internal."""
    groups = []
    for key, at in sorted(timestamps.items(), key=lambda p: int(p[0])):
        rid = int(key)
        date = datetime.fromtimestamp(at, M.CST).date().isoformat()
        age = (now-at)/86400 if at <= now else None
        if groups and groups[-1]['end']+1 == rid and groups[-1]['planted_on'] == date:
            groups[-1]['end'] = rid
            groups[-1]['ages'].append(age)
        else:
            groups.append(dict(start=rid,end=rid,planted_on=date,ages=[age]))
    for g in groups:
        ages = g.pop('ages')
        g['elapsed_days_bounds'] = ([math.floor(min(ages)*100)/100, math.ceil(max(ages)*100)/100]
                                   if all(v is not None for v in ages) else None)
    return dict(time_basis='UTC+08 current crop-cycle start from successful sowing or confirmed phenology reset; elapsed-day bounds to 0.01 day; not maturity',groups=groups)
