"""Opt-in, visible task requirements; never the hidden scenario validator."""
from __future__ import annotations
import re
from fairy.agents.jev.done_check import done_problems


def positive_task(task):
    # Remove only direct negative action phrases. Unparsed/conditional language
    # is not claimed as a complete natural-language task contract.
    text=re.sub(r'(?:无需|不需要|不要|不必|禁止)\s*(?:进行|执行)?\s*(?:播种|种植|移栽|收获|收割|入库|储存|提交报告)', '',task)
    return re.sub(r'\b(?:do not|don\'t|no need to)\s+(?:plant|harvest|store|report)\b','',text,flags=re.I)


def problems(task,facts,tools):
    text=positive_task(task)
    result=done_problems(text,facts,tools)
    if re.search(r'收获|收割|\bharvest',text,re.I) and re.search(r'全部|所有|全田|全季|全周期|\ball\b|full[ -]season',text,re.I):
        for pid,rows in [('field',facts.get('ridges',[])),*[(fid,f.get('ridges',[])) for fid,f in facts.get('farms',{}).items()]]:
            missing=[r['ridge_id'] for r in rows if not r.get('planted') and not r.get('harvested')]
            if missing:
                result.append(f'{pid}: requested whole-field harvest includes {len(missing)} unplanted, unharvested ridges; no harvest evidence yet.')
        for p in facts.get('plots',[]):
            if not p.get('planted') and not p.get('harvested'):
                result.append(f"plot {p['plot_id']}: requested whole-season harvest has no planting/harvest evidence yet.")
    for pending in facts.get('pending',[]):
        if '__replant' in pending.get('from_action','') and not pending.get('ridges'):
            result.append('Announced replanting recovery is still pending; wait and observe before completion.')
    return result
