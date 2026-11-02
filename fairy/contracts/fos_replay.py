"""CLI-only adapter around FAIRY's native replay script.

No replay loop, clock binding, tool dispatch, error reproduction or metric
implementation is copied here. Optional oracle injection and unrounded yield
exports are confined to this offline, single-job process.
"""
from pathlib import Path
import importlib.util
import hashlib
import math
import sys
from unittest.mock import patch


def _native():
    source = Path(__file__).resolve().parents[2] / 'scripts/rebatch_fos_from_traces.py'
    name = '_fairy_native_rebatch_fos'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, source)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name], source


def replay_one_cell(*args, oracle_workflow=None, **kwargs):
    native, source = _native()
    from fairy.scenarios.fos import evaluation
    original_replay = native._replay_fairy_run_bundle
    original_evaluate = evaluation.evaluate_fos
    captured = {}

    def replay(bundle):
        scenario, env, info = original_replay(bundle)
        if oracle_workflow is not None:
            scenario._cached_oracle_workflow = oracle_workflow
        captured['scenario'] = scenario
        # Capture the native terminal summary before optional maturity projection.
        from fairy.controllers.engine import Engine
        from fairy.apps.farm_world.multi_farm import farm_world_apps
        from types import SimpleNamespace
        farms = farm_world_apps(scenario.apps or [])
        if len(farms) == 1:
            captured['terminal'] = Engine._farm_outcome_summary(SimpleNamespace(scenario=scenario), farms[0])
        captured['original'] = (bundle.get('run_report') or {}).get('outcome')
        captured['info'] = info
        return scenario, env, info

    def evaluate(*a, **kw):
        result = original_evaluate(*a, **kw)
        captured['report'] = result
        return result

    with patch.object(native, '_replay_fairy_run_bundle', replay), patch.object(evaluation, 'evaluate_fos', evaluate):
        row = native.replay_one_cell(*args, **kwargs)
    if 'terminal' in captured:
        from .scoring import compare_outcomes
        expected = captured.get('original') or {}
        if len(expected.get('farms', {})) == 1:
            expected = next(iter(expected['farms'].values()))
        differences = compare_outcomes(expected, captured['terminal']) if expected else None
        row.update(replayed_terminal_outcome=captured['terminal'], terminal_match=not differences if differences is not None else None, terminal_comparison=differences)
    row['native_replay_source'] = str(source)
    row['native_replay_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    report = captured.get('report')
    if report is not None:
        ob = report.outcome_breakdown
        agent, oracle = ob.agent_biological_kg, ob.oracle_biological_kg
        row['agent_biological_kg'] = agent
        row['oracle_biological_kg'] = oracle
        row['crop_loss_unclipped_pct'] = (
            100 * (1 - agent / oracle)
            if all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (agent, oracle)) and oracle > 0 else None
        )
        row['yield_source'] = 'FAIRY evaluate_fos outcome biological mass, unrounded; no maturity veto'
    return row
