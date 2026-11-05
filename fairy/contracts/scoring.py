"""Offline-only scoring contract; never creates a model client."""
from pathlib import Path
import json
import hashlib


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_oracle(job):
    path = Path(job['oracle_result']).resolve()
    if sha(path) != job['oracle_sha256']:
        raise ValueError('Oracle checksum mismatch')
    result = json.loads(path.read_text())
    if result['identity'] != job['identity']:
        raise ValueError('Oracle identity mismatch')
    for name, checksum in result['checksums'].items():
        if sha(path.parent/name) != checksum:
            raise ValueError('Oracle artifact checksum mismatch')
    return path, result


def tool_failed(step):
    if step.op_type == 'TOOL_ERROR': return True
    value=step.content
    if not isinstance(value,dict): return False
    if isinstance(value.get('ok'),bool): return not value['ok']
    return bool(value.get('error'))

def worker(job):
    if job['kind'] in {'multi_farm_oracle', 'multi_farm_replay', 'rice_oracle', 'rice_replay'}:
        return multi_farm_worker(job)
    import csv
    csv.field_size_limit(128 * 1024 * 1024)
    from fairy.controllers.engine import Engine
    from fairy.scenarios.registry import get_scenario_class
    from .cli import fingerprint
    output = Path(job['output']).resolve()
    if job['kind'] == 'oracle':
        ident = job['identity']
        from .scenario_adapter import instantiate
        from fairy.scenarios.workflow_validation import _normalize_workflow_times
        from fairy.apps.farm_world.multi_farm import farm_world_apps
        from fairy.scenarios.fos.evaluation import _extrapolate_physics_to_maturity
        from fairy.scenarios.fos.provenance import crop_backend_provenance
        scenario = instantiate(get_scenario_class(ident['scenario_id']), {**ident['kwargs'], 'seed': ident['seed']})
        engine = Engine(agent=None, scenario=scenario)
        workflow = engine.run_scenario_oracle(run_oracle=True, **ident['init_kwargs'])
        errors = [s for s in workflow.dag.values() if tool_failed(s)]
        if errors:
            raise ValueError('Oracle contains tool failures; cannot use as reference')
        outcome = engine.outcome_summary()
        evaluation = engine.evaluation_report(workflow)
        wf = workflow.to_dict()
        _normalize_workflow_times(wf)
        write(output.parent/'oracle_workflow.json', wf)
        farms = farm_world_apps(scenario.apps or [])
        if len(farms) != 1:
            raise ValueError('Single-farm FOS baseline unsupported for multi-farm scenario')
        farm = farms[0]
        extrap = _extrapolate_physics_to_maturity(farm, max_days=180)
        physics = farm._physics
        area = farm.field_length_m * farm.ridge_width_m
        states = [physics.yield_recovery.states[k] for k in sorted(physics.yield_recovery.states)]
        bio = [float(s.biological_yield_g_m2) for s in states]
        rec = [float(s.recovered_yield_g_m2_at_market_moisture) for s in states]
        baseline = dict(schema_version=3, scenario_id=ident['scenario_id'], crop_backend_provenance=crop_backend_provenance(physics),
            ridge_area_m2=area, ridges_total=len(states), biological_yield_g_m2_per_ridge=bio,
            biological_yield_kg_total=sum(bio)*area/1000, recovered_yield_g_m2_per_ridge=rec,
            recovered_yield_kg_total=sum(rec)*area/1000, extrapolation=extrap)
        name = 'baselines/'+ident['scenario_id']+'.json'
        write(output.parent/name, baseline)
        result = dict(identity=ident, outcome=outcome, evaluation=evaluation, baseline=baseline,
            scoring_identity=fingerprint(), checksums={n:sha(output.parent/n) for n in ['oracle_workflow.json',name]})
    elif job['kind'] == 'replay':
        from . import fos_replay as module
        if 'oracle_result' in job:
            path, oracle = load_oracle(job)
            if oracle['scoring_identity']['source_hash'] != fingerprint()['source_hash']:
                raise ValueError('Oracle scoring environment mismatch')
            baseline = path.parent/'baselines'
            oracle_workflow = json.loads((path.parent/'oracle_workflow.json').read_text())
        else:
            baseline = output.parent/'no_legacy_baselines'
            baseline.mkdir(exist_ok=True)
            oracle_workflow = None
        row = module.replay_one_cell(Path(job['cell_dir']), output.parent/'fos',
            extrapolate=job['extrapolate'], extrapolation_max_days=180, oracle_baseline_dir=baseline,
            output_rel=Path('run'), oracle_workflow=oracle_workflow)
        result = {'fos_result':row, 'extrapolate_to_maturity':job['extrapolate'], 'scoring_identity':fingerprint()}
    else:
        raise ValueError('Unsupported scoring kind')
    write(output, result)


def compare_outcomes(expected, actual, path='outcome'):
    """Compare all recorded fields, with tolerance only for floating arithmetic."""
    import math
    expected = json.loads(json.dumps(expected))
    actual = json.loads(json.dumps(actual))
    differences=[]
    if isinstance(expected, dict):
        if not isinstance(actual, dict):return [path+': type mismatch']
        for key,value in expected.items():
            # Native UUID labels are random on replay; retain all physical and farm identity fields.
            if key in {'op_id','inspection_id','mission_id'}:continue
            if key not in actual:differences.append(path+'.'+key+': missing')
            else:differences.extend(compare_outcomes(value,actual[key],path+'.'+key))
    elif isinstance(expected,list):
        if not isinstance(actual,list) or len(expected)!=len(actual):return [path+': length mismatch']
        for i,(a,b) in enumerate(zip(expected,actual)):differences.extend(compare_outcomes(a,b,f'{path}[{i}]'))
    elif isinstance(expected,(int,float)) and not isinstance(expected,bool):
        if not isinstance(actual,(int,float)) or not math.isclose(expected,actual,rel_tol=1e-6,abs_tol=1e-4):differences.append(path+': value mismatch')
    elif expected!=actual:differences.append(path+': value mismatch')
    return differences


def workflow_scores(oracle, agent):
    from fairy.scenarios.fos.spatiotemporal import baseline_bfcl
    from fairy.scenarios.fos.path_correctness_v2 import evaluate_path_correctness_v2
    from fairy.scenarios.workflow_validation import evaluate_workflows
    return dict(bfcl_success=baseline_bfcl(oracle,agent),v2=evaluate_path_correctness_v2(oracle,agent,tol_ratio=2.0),v1=evaluate_workflows(oracle,agent))


def multi_farm_worker(job):
    from fairy.controllers.engine import Engine
    from fairy.scenarios.registry import get_scenario_class
    from fairy.scenarios.workflow import Workflow
    from .scenario_adapter import instantiate
    from .cli import fingerprint
    output=Path(job['output']).resolve();ident=job['identity']
    rice = job['kind'].startswith('rice_')
    replay = job['kind'].endswith('_replay')
    result=dict(identity=ident,scoring_identity=fingerprint(),status='failed',phase='input')
    try:
        if ident['source_hash']!=result['scoring_identity']['source_hash']:raise ValueError('Scoring source identity mismatch')
        if replay:
            cell=Path(job['cell_dir']);sid=ident['scenario_id']
            wfpath=cell/(sid+'.agent_workflow.json');reportpath=cell/(sid+'.run_report.json')
            if not wfpath.exists():raise ValueError('Missing complete agent workflow')
            report=json.loads(reportpath.read_text()) if reportpath.exists() else {}
            if report and (report.get('scenario_id')!=sid or report.get('seed')!=ident['seed']):raise ValueError('Original report identity mismatch')
            if not report:result.setdefault('diagnostics',[]).append('Original report absent; terminal comparison unavailable')
            op,oracle=load_oracle(job)
            if oracle.get('status')!='ok':raise ValueError('Oracle is not usable')
            if oracle['scoring_identity']['source_hash']!=result['scoring_identity']['source_hash']:raise ValueError('Oracle scoring environment mismatch')
        result['phase']='initialization'
        scenario=instantiate(get_scenario_class(ident['scenario_id']),{**ident['kwargs'],'seed':ident['seed']})
        engine=Engine(agent=None,scenario=scenario)
        if not replay:
            result['phase']='oracle'
            workflow=engine.run_scenario_oracle(run_oracle=True,**ident['init_kwargs'])
            if any(tool_failed(s) for s in workflow.dag.values()):raise ValueError('Oracle contains tool failures')
            wf=workflow.to_dict()
            if not any(s.get('tool_name') for s in wf.values()):raise ValueError('Empty oracle workflow')
            write(output.parent/'oracle_workflow.json',wf)
            names=['oracle_workflow.json']
            if getattr(workflow,'manifest',None) is not None:
                write(output.parent/'oracle_workflow.manifest.json',workflow.manifest);names.append('oracle_workflow.manifest.json')
            result.update(outcome=engine.outcome_summary(),evaluation=engine.evaluation_report(workflow),checksums={n:sha(output.parent/n) for n in names})
            if not rice and not result['outcome'].get('farms'):raise ValueError('Expected multi-farm outcome')
            if rice:
                baseline = rice_baseline(scenario, result['evaluation'])
                write(output.parent/'rice_baseline.json', baseline)
                result['checksums']['rice_baseline.json'] = sha(output.parent/'rice_baseline.json')
        else:
            result['phase']='replay'
            workflow=Workflow.load_workflow(str(wfpath))
            sidecar=wfpath.with_suffix('.manifest.json')
            manifest=json.loads(sidecar.read_text()) if sidecar.exists() else None
            with replay_comparison():
                replayed=engine.replay_workflow(workflow,manifest=manifest,**ident['init_kwargs'])
            outcome=engine.outcome_summary()
            differences=compare_outcomes(report['outcome'],outcome) if report.get('outcome') else None
            result.update(outcome=outcome,original_outcome=report.get('outcome'),terminal_match=not differences if differences is not None else None,terminal_differences=differences)
            write(output.parent/'replayed_workflow.json',replayed.to_dict())
            result['phase']='terminal_comparison'
            if differences:result.setdefault('diagnostics',[]).append('Replay terminal differs; native scores retained')
            result['phase']='evaluation'
            try:result['evaluation']=engine.evaluation_report(replayed)
            except Exception as exc:result.setdefault('diagnostics',[]).append('Evaluation: '+str(exc))
            ow=json.loads((op.parent/'oracle_workflow.json').read_text());aw=workflow.to_dict()
            write(output.parent/'metric_oracle_workflow.json',ow);write(output.parent/'metric_agent_workflow.json',aw)
            result['workflow_metrics']=workflow_scores(ow,aw)
            if rice:
                from fairy.scenarios.rice.evaluation import compare_outcome
                try:
                    result['rice_comparison']=compare_outcome(scenario,json.loads((op.parent/'rice_baseline.json').read_text()))
                except Exception as exc:
                    result['yield_missing_reason']=f'{type(exc).__name__}: {exc}'
        if not rice:
            try:result['yield_projection'] = project_farms(engine)
            except Exception as exc:result['yield_missing_reason']=str(exc)
        if replay:
            result['yield_metrics'] = yield_metrics(result, oracle)
        result.update(status='ok',phase='complete')
    except Exception as exc:
        result.update(error_type=type(exc).__name__,error=str(exc))
    write(output,result)


from contextlib import contextmanager


def canonical_response(value):
    """JSON key equivalence and native random labels only; retain error/state data."""
    value = json.loads(json.dumps(value))
    def visit(v):
        if isinstance(v, dict):
            return {k: visit(x) for k, x in v.items() if k not in {'op_id','inspection_id','mission_id'}}
        if isinstance(v, list):
            return [visit(x) for x in v]
        return v
    return visit(value)


@contextmanager
def replay_comparison():
    # Offline process only. Native execution, failure classification and timestamps unchanged.
    from dataclasses import replace
    import fairy.controllers.engine as module
    original = module._verify_replay_response
    def verify(step, content, tool):
        if module._returned_failure(step.content, tool):
            return original(replace(step, content=canonical_response(step.content)),
                            canonical_response(content), tool)
        return original(step, content, tool)
    module._verify_replay_response = verify
    try:
        yield
    finally:
        module._verify_replay_response = original


def rice_baseline(scenario, evaluation):
    # Mirrors native build_baseline, but uses the already instantiated frozen kwargs/seed.
    from fairy.scenarios.rice.evaluation import SCHEMA, focus_units, project_outcome
    from fairy.apps.paddy.world import PaddyWorldApp
    if not evaluation['validation']['success']:
        raise ValueError('Rice oracle validation failed')
    world = scenario.get_typed_app(PaddyWorldApp)
    return dict(schema_version=4, outcome_schema=SCHEMA, scenario_id=scenario.scenario_id,
                crop_backend_provenance=world.crop_backend_provenance(),
                initial_checkpoint_sha256=scenario._initial_state['sha256'],
                source_l3_scenario_id=scenario.source_l3_scenario_id,
                source_checkpoint_label=scenario.source_checkpoint_label,
                focus_unit_ids=focus_units(scenario), projection_max_days=220,
                oracle=project_outcome(world,max_days=220), validation=evaluation['validation'])


def project_farms(engine):
    from fairy.scenarios.fos.evaluation import _extrapolate_physics_to_maturity
    from fairy.apps.farm_world.multi_farm import farm_world_apps
    contexts = getattr(engine.farm_environment, 'farms', {})
    farms = {key: ctx.world for key, ctx in contexts.items()}
    if not farms:
        raise ValueError('No explicit farm identities for yield projection')
    output = {}
    def biological(farm):
        physics = getattr(farm, '_physics', None)
        states = getattr(getattr(physics, 'yield_recovery', None), 'states', {})
        if not states:
            return None
        return sum(float(x.biological_yield_g_m2) for x in states.values()) * farm.field_length_m * farm.ridge_width_m / 1000
    for key, farm in farms.items():
        terminal = biological(farm)
        try:
            status = _extrapolate_physics_to_maturity(farm, max_days=180)
        except Exception as exc:
            status = dict(status='error', error=str(exc), reached_maturity=False)
        mature = biological(farm)
        output[key] = dict(terminal_kg=terminal, projected_kg=mature,
                           extrapolation=status, valid=status.get('reached_maturity',False))
    return output


def yield_metrics(result, oracle):
    """Map native biological masses to the existing unclipped FOS loss definition.

    No surrogate harvest/storage yield; multi-farm denominator is total biological
    mass, not an unweighted mean of farm percentages. Unknown stays unknown.
    """
    import math
    def loss(a, o):
        if isinstance(a,bool) or isinstance(o,bool) or a is None or o is None or not math.isfinite(a) or not math.isfinite(o) or o <= 0:
            return None
        return 100 * (1 - a / o)
    if 'rice_comparison' in result:
        comparison = result['rice_comparison']
        return dict(biological_loss_pct_extrapolated=loss(comparison['agent']['biological_dry_kg'],
                                                         comparison['oracle']['biological_dry_kg']),
                    definition='100*(1-agent_biological_dry_kg/oracle_biological_dry_kg); rice native projection')
    agent = result.get('yield_projection', {})
    reference = oracle.get('yield_projection', {})
    values = dict(biological_loss_pct_extrapolated=None, biological_loss_pct_terminal=None,
                  definition='100*(1-sum(agent_biological_kg)/sum(oracle_biological_kg)); native per-farm FOS projection')
    if not agent or set(agent) != set(reference):
        return values
    for field, metric in [('projected_kg','biological_loss_pct_extrapolated'),('terminal_kg','biological_loss_pct_terminal')]:
        av=[x[field] for x in agent.values()];ov=[x[field] for x in reference.values()]
        if all(x is not None for x in av+ov):
            values[metric]=loss(sum(av),sum(ov))
            if field=='projected_kg':values.update(agent_biological_kg=sum(av),oracle_biological_kg=sum(ov))
    return values
