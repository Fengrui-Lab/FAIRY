"""Versioned, opt-in decision presentation; no tool execution or hidden state.

History is evidence of past receipts, not proof that a new round is complete.
Tool selection is separated from argument selection for every enhanced scene.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256

from fairy.agents.jev import management as M

VERSION = 'scoped-decision-context-v5'
INSTRUCTIONS = (
    'Choose the next single operation using current_decision and management_progress. '
    'Historical coverage is cumulative across the run, not completion of the current round. '
    'A new required round or changed target/time is a reason to repeat an operation; '
    'do not repeat an unchanged failed request or duplicate a pending effect. '
    'For due work, select its feasible prerequisite first (for example load before apply). '
    'DUE is a reference checkpoint, not proof of crop readiness. Observe missing readiness '
    'or resource evidence; defer only for an actual blocker. A wait does not complete due work. '
    'Remaining quantities and loaded supplies are not proof that a reference window is due. '
    'Distinguish upcoming references from due work; observations can justify adjustments, not the mere existence of an unfinished dose. '
    'Observation coverage records past evidence, not a requirement to inspect every ridge. '
    'A completed check is not a completed application. Inspections and charging do not replace seasonal care or time advance. '
    'Match explicit planting prescriptions before sowing or replanting; finish pending establishment. '
    'Crop-cycle ages follow confirmed reset receipts. A charge-ready time is an optional wake-up, not a farm deadline. '
    'Choose only the operation now; its arguments are resolved after selection. '
    'Follow jev_execution_guidance for task scope and recovery.'
)

SHA256 = sha256(INSTRUCTIONS.encode()).hexdigest()


def evidence_time(s, now):
    """Actual recorded clock only; unknown timestamps remain unknown."""
    before = M.timestamp(M.get(s, 'time_before'))
    after = M.timestamp(M.get(s, 'time_after'))
    recorded = M.timestamp(M.get(s, 'time'))
    end = after if after is not None else recorded
    return dict(time_before=before, time_after=after, recorded_time=recorded,
                age_seconds=max(0., now-end) if end is not None and end <= now else None,
                age_days=(now-end)/86400 if end is not None and end <= now else None,
                recorded_at_utc=datetime.fromtimestamp(end, timezone.utc).isoformat() if end is not None else None,
                recorded_at_utc_plus_08=datetime.fromtimestamp(end, M.CST).isoformat() if end is not None else None,
                time_basis='simulation epoch seconds; unknown stays null')


def round_labels(facts, context):
    """Label successful fertilizer receipts by the existing quantity ledger.

    No date-to-round guess: a receipt spanning rounds is labelled with both
    limits, rather than falsely assigning all its coverage to the newest one.
    """
    plan = context['plan']; labels = {}
    account = M.ledger(plan, {'steps': []})
    for index, s in enumerate(facts.get('steps', []), 1):
        name = M.get(s, 'tool_name', '').split('__')[-1]
        if name in ('apply_fertilizer', 'apply_fertigation') and list(M.successes({'steps': [s]})):
            before = {**account, 'ridge_product_kg': dict(account['ridge_product_kg']),
                      'plot_doses_kg_ha': {p: list(v) for p, v in account['plot_doses_kg_ha'].items()}}
            delta = M.ledger(plan, {**facts, 'steps': [s]})
            for rid, dose in delta['ridge_product_kg'].items():
                account['ridge_product_kg'][rid] = account['ridge_product_kg'].get(rid, 0.)+dose
            for pid, doses in delta['plot_doses_kg_ha'].items():
                account['plot_doses_kg_ha'].setdefault(pid, []).extend(doses)
            after = account
            if plan['kind'] == 'ridge':
                a, b = M.ridge_round(plan, before), M.ridge_round(plan, after)
                if before['ridge_product_kg'] != after['ridge_product_kg'] and a:
                    labels[index] = dict(earliest_incomplete_round_before=a['index'],
                                         earliest_incomplete_round_after=b['index'] if b else None,
                                         meaning='quantity-ledger boundary before/after this receipt; not completion of subsequent rounds')
            elif plan['kind'] == 'paddy':
                pid = (M.get(s, 'tool_args', {}) or {}).get('plot_id')
                a, b = M.paddy_round(plan, before, pid), M.paddy_round(plan, after, pid)
                if before['plot_doses_kg_ha'] != after['plot_doses_kg_ha'] and a:
                    labels[index] = dict(plot_id=pid, earliest_incomplete_round_before=a['index'],
                                         earliest_incomplete_round_after=b['index'] if b else None,
                                         meaning='quantity-ledger boundary before/after this receipt; not completion of subsequent rounds')
    return labels


def present(state, facts, context, now):
    """Build a bounded model projection; exact facts/context are unchanged."""
    from fairy.agents.jev.model_view import project
    return project(state, facts, context, now, labels=round_labels(facts, context))
