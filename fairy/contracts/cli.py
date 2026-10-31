"""Public process boundary. No experiment scheduler dependencies."""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys

CONTRACT_VERSION = 1


def fingerprint():
    package = Path(__file__).resolve().parents[1]
    root = package.parent
    files = sorted(package.rglob('*.py')) + [root/'pyproject.toml', root/'uv.lock']
    files += sorted(p for p in package.rglob('*') if p.is_file() and p.suffix.lower() in {'.json','.txt','.md','.yaml','.yml','.csv','.npz','.npy','.pkl','.pickle','.gz','.conf'})
    hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True)
    from importlib.metadata import version, PackageNotFoundError
    dependencies={}
    for name in ('openai','openai-agents','httpx','numpy','typesafe-sdk','pcse','jsonschema'):
        try: dependencies[name]=version(name)
        except PackageNotFoundError: dependencies[name]=None
    signature={'files':hashes,'dependencies':dependencies,'python_version':platform.python_version()}
    return {'source_hash': hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest(), 'dependencies':dependencies,
            'files': hashes, 'lock_hash': hashes.get('uv.lock'),
            'git_commit': head.stdout.strip() if head.returncode == 0 else None,
            'python_version': platform.python_version(), 'python_executable': sys.executable}


def capabilities():
    from fairy.scenarios.registry import list_scenarios
    from fairy.controllers.agent_builder import AgentBuilder
    return dict(contract_version=CONTRACT_VERSION, identity=fingerprint(),
                scenarios=list(list_scenarios()), controllers=list(AgentBuilder().list_agents()),
                providers=['typesafe','system-one-compatible','vllm','openai-compatible'],
                features=['run-manifest-v1','service-check-v1','oracle-v1','fos-replay-v1','llm-roles-v1','describe-scenario-v1','scenario-data-fingerprint-v1','probe-request-v1'])


def scrub(text, secrets):
    for value in sorted(filter(None, secrets), key=len, reverse=True):
        text = text.replace(value, '[REDACTED]')
    return re.sub(r'(?i)Bearer\s+[A-Za-z0-9._~+/=-]+', 'Bearer [REDACTED]', text)


def probe(service):
    from .service_probe import check_chat, check_decision
    p = service['provider']
    if p == 'typesafe':
        from fairy.agents.llm.typesafe_client import TypeSafeJevClient
        key = service.get('api_key_env') or 'TYPESAFE_API_KEY'
        if not os.environ.get(key):
            raise ValueError('Missing service credential')
        previous = os.environ.get('TYPESAFE_API_KEY')
        os.environ['TYPESAFE_API_KEY'] = os.environ[key]
        try:
            client = TypeSafeJevClient(service['model_id'], 0.0, timeout=service.get('timeout',60),
                                      max_retries=0, base_url=service.get('endpoint'))
        finally:
            if previous is None: os.environ.pop('TYPESAFE_API_KEY',None)
            else: os.environ['TYPESAFE_API_KEY'] = previous
        import time
        started = time.perf_counter()
        try:
            result = client.system_one({'label':'a'}, {'probe':{'type':'choice','instructions':'Choose a', 'criteria':{'a':'a','b':'b'}}})
        finally:
            client.close()
        match = result.choices['probe'].choice == 'a'
        return {'status':'passed' if match else 'semantic_probe_failed', 'contract_ok':True,
                'semantic_match':match, 'provider':p, 'requested_model':service['model_id'],
                'returned_model':result.model, 'usage':result.usage.tokens(),
                'probabilities':result.choices['probe'].probabilities,
                'provider_confidence':result.choices['probe'].confidence,
                'timeout_seconds':client.request_timeout, 'max_retries':client.sdk_max_retries,
                'endpoint':client.base_url, 'http_request_count':1,
                'wall_time_seconds':time.perf_counter()-started}
    args = argparse.Namespace(model=service['model_id'], endpoint=service['endpoint'],
        api_key_env=service.get('api_key_env'), timeout=service.get('timeout',60),
        max_questions_per_request=service.get('max_questions'), question_count=2, option_count=2,
        chat_provider=p, max_output_tokens=service.get('max_output_tokens',128),
        enable_thinking=service.get('enable_thinking'), output_token_parameter=service.get('output_token_parameter','max_tokens'),
        temperature=service.get('temperature',0.0), send_temperature=service.get('send_temperature',True), reasoning_effort=service.get('reasoning_effort'))
    if p not in {'vllm','openai-compatible','system-one-compatible'}:
        raise ValueError('Unsupported provider')
    result = check_decision(args) if p == 'system-one-compatible' else check_chat(args)
    result['status'] = 'passed' if result['semantic_match'] else 'semantic_probe_failed'
    return result


def run_cli(argv):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--task-id')
    parser.add_argument('--credential-envs', default='[]')
    meta, legacy = parser.parse_known_args(argv)
    def value(flag, default=None):
        return legacy[legacy.index(flag)+1] if flag in legacy else default
    output = Path(value('--output-dir','runs')).resolve()
    scenario = value('--scenario', value('-s'))
    secrets = [os.environ.get(k) for k in json.loads(meta.credential_envs)]
    for flag in ('--api-key-env','--fallback-api-key-env','--decision-api-key-env'):
        if value(flag): secrets.append(os.environ.get(value(flag)))
    secrets.extend(os.environ.get(k) for k in ('TYPESAFE_API_KEY','OPENAI_API_KEY','VLLM_API_KEY','LLAMA_API_KEY'))
    secrets = [x for x in secrets if x and x != 'EMPTY']
    os.environ["FAIRY_REDACT_ENV_NAMES"] = json.dumps(json.loads(meta.credential_envs) + [value(f) for f in ("--api-key-env","--fallback-api-key-env","--decision-api-key-env") if value(f)])
    buffer = io.StringIO(); code = 0
    oldargv = sys.argv
    def terminate(*_): raise SystemExit(143)
    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            from fairy.cli import main as legacy_main
            sys.argv = ['fairy-cli', *legacy]
            legacy_main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:
        code = 1
        buffer.write(f'FAIRY failed: {type(exc).__name__}\n')
    finally:
        sys.argv = oldargv
        signal.signal(signal.SIGTERM, previous)
        # Runtime also redacts live events at their source; final artifacts are sanitized here.
        if output.exists():
            for p in output.glob('*'):
                if p.suffix in {'.json','.jsonl'} and p.is_file():
                    p.write_text(scrub(p.read_text(),secrets))
        report = output/f'{scenario}.run_report.json'
        if report.exists():
            data = json.loads(report.read_text())
            if data.get('error'): code = code or 1
            artifacts = {p.name:p.name for p in output.iterdir() if p.is_file() and p.name.startswith(str(scenario)+'.')}
            manifest = dict(contract_version=CONTRACT_VERSION, task_id=meta.task_id, scenario_id=scenario,
                seed=data.get('seed'), identity=fingerprint(), argv=legacy, artifacts=artifacts,
                exit_code=code, requested_provider=value('--provider'), requested_model=value('--model'))
            (output/'run_manifest.json').write_text(scrub(json.dumps(manifest,ensure_ascii=False,indent=2),secrets))
        print(scrub(buffer.getvalue(),secrets),end='')
    return code


def describe_scenario(job):
    from fairy.scenarios.registry import get_scenario_class
    from fairy.controllers.engine import Engine
    cls=get_scenario_class(job['scenario_id'])
    kwargs={**job.get('kwargs',{}),'seed':job.get('seed',0)}
    if kwargs.get('agent_task_override') or kwargs.get('scenario_input'):
        raise ValueError('Native description cannot override task text')
    scenario=cls(**kwargs)
    scenario.setup(**job.get('init_kwargs',{}))
    engine=Engine(agent=None,scenario=scenario)
    task=engine._resolve_agent_task()
    if not task: raise ValueError('Scenario has no native task')
    source='event_briefing' if engine._agent_briefing_from_events() else 'scenario_input'
    result=dict(contract_version=1,scenario_id=job['scenario_id'],seed=scenario.seed,
        task=task,task_hash=hashlib.sha256(json.dumps(task,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
        task_source=source,kwargs=kwargs,init_kwargs=job.get('init_kwargs',{}),
        start_time=scenario.start_time,expects_agent_harvest=scenario.expects_agent_harvest,
        validation_hook_available=callable(getattr(scenario,'validate',None)),
        checkpoint_label=getattr(scenario,'source_checkpoint_label',None),identity=fingerprint())
    if job.get('include_tool_schemas'):
        from fairy.agents.agent.toolset_builder import build_toolset
        from fairy.controllers.agent_builder import FARM_AGENT_HIDDEN_TOOL_NAMES
        result['tools'] = build_toolset(scenario.apps, excluded_tool_names=FARM_AGENT_HIDDEN_TOOL_NAMES)[1]
    if job.get('output'):
        Path(job['output']).parent.mkdir(parents=True,exist_ok=True)
        Path(job['output']).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in {'capabilities','check-service','score','describe-scenario','probe-request'}:
        return run_cli(argv)
    operation = argv.pop(0)
    parser = argparse.ArgumentParser()
    if operation == 'capabilities': parser.add_argument('--json', action='store_true')
    else: parser.add_argument('--job', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if operation == 'capabilities': result = capabilities()
        else:
            job = json.loads(args.job.read_text())
            with contextlib.redirect_stdout(io.StringIO()):
                if operation == 'probe-request':
                    from .request_probe import probe_request
                    result = probe_request(job)
                elif operation == 'check-service': result = probe(job)
                elif operation == 'describe-scenario': result = describe_scenario(job)
                else:
                    from .scoring import worker
                    worker(job)
                    result = {'status':'passed','output':job['output']}
        secrets = [os.environ.get(job.get('service',{}).get('api_key_env') or '')] if operation != 'capabilities' else []
        print(scrub(json.dumps(result, ensure_ascii=False), secrets))
        return 0 if result.get('status','passed') == 'passed' else 1
    except Exception as exc:
        print(json.dumps({'status':'failed','error_type':type(exc).__name__}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
