from pathlib import Path
import json

def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2))

def worker(job):
    from fairy.controllers.engine import Engine
    from fairy.scenarios.registry import get_scenario_class
    if job['kind']=='oracle':
        ident=job['identity']
        from .scenario_adapter import instantiate
        scenario=instantiate(get_scenario_class(ident['scenario_id']), {**ident['kwargs'],'seed':ident['seed']})
        engine=Engine(agent=None,scenario=scenario)
        workflow=engine.run_scenario_oracle(run_oracle=True,**ident['init_kwargs'])
        errors=[s for s in workflow.dag.values() if s.op_type=='TOOL_ERROR' or isinstance(s.content,dict) and 'error' in s.content]
        if errors:
            raise ValueError('Oracle contains tool failures; cannot use as reference')
        result=dict(identity=ident,outcome=engine.outcome_summary(),evaluation=engine.evaluation_report(workflow))
    else:
        from . import fos_replay as module
        out=Path(job['output']).parent/'fos'
        # An explicitly empty directory prevents unrelated legacy oracle caches from being selected.
        baseline=Path(job['output']).parent/'no_legacy_baselines';baseline.mkdir(exist_ok=True)
        result=module.replay_one_cell(Path(job['cell_dir']),out,
            extrapolate=job['extrapolate'],extrapolation_max_days=180,oracle_baseline_dir=baseline,
            output_rel=Path('run'))
        result={'fos_result':result,'note':'FOS replay is separate from terminal metrics; primary oracle losses use the identity-scoped oracle.',
                'extrapolate_to_maturity':job['extrapolate']}
    write(job['output'],result)

