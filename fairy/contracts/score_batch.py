"""Offline batch transport around the existing native scoring worker."""
from pathlib import Path
import contextlib
import fcntl
import hashlib
import json
import os
import resource
import sys
import signal
import tempfile
import time
import traceback


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
        temporary = stream.name
    os.replace(temporary, path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_job(job):
    """One process, one output directory; durable receipt enables safe reuse."""
    from .scoring import worker
    output = Path(job['output']).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    signature = digest(job)
    started = output.parent/'started.json'
    receipt = output.parent/'receipt.json'
    lock = (output.parent/'.job.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return dict(status='busy', output=str(output), job_hash=signature)
    if receipt.exists():
        value = json.loads(receipt.read_text())
        if value['job_hash'] != signature:
            raise ValueError('Job identity differs from existing receipt')
        if value['status'] == 'completed' and (not output.exists() or sha(output) != value['result_sha256']):
            raise ValueError('Cached score checksum mismatch')
        return {**value, 'cached': True}
    if started.exists() or output.exists():
        return dict(status='interrupted', error='Previous job has no complete receipt; no automatic retry',
                    output=str(output), job_hash=signature)
    write(started, dict(job_hash=signature, job=job, pid=os.getpid(), time=time.time()))
    old_handler = signal.getsignal(signal.SIGALRM)
    def timeout(*_):
        raise TimeoutError('Offline scoring job exceeded 600 seconds')
    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(600)
    started_at = time.monotonic()
    try:
        with (output.parent/'stdout.log').open('w') as stdout, (output.parent/'stderr.log').open('w') as stderr:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                worker(job)
        result = json.loads(output.read_text())
        # Transport completion is distinct from the native score status.
        value = dict(status='completed', result_sha256=sha(output),
                     native_status=result.get('fos_result', result).get('status', 'ok'))
    except Exception as exc:
        value = dict(status='failed', error_type=type(exc).__name__, error=str(exc))
        with (output.parent/'stderr.log').open('a') as stderr:
            traceback.print_exc(file=stderr)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
    value.update(output=str(output), job_hash=signature, pid=os.getpid(),
                 elapsed_seconds=time.monotonic()-started_at,
                 cpu_seconds=resource.getrusage(resource.RUSAGE_SELF).ru_utime+resource.getrusage(resource.RUSAGE_SELF).ru_stime,
                 peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024))
    write(receipt, value)
    return value


def run_batch(manifest):
    from fairy.parallel import run_process_jobs
    jobs = manifest['jobs']
    workers = manifest.get('workers', 2)
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 16:
        raise ValueError('score-batch supports between one and sixteen workers')
    output = Path(manifest['output']).resolve()
    directories = [Path(job['output']).resolve().parent for job in jobs]
    if len(set(directories)) != len(directories):
        raise ValueError('Each job must have an independent output directory')
    if any(a in b.parents or b in a.parents for i, a in enumerate(directories) for b in directories[i+1:]):
        raise ValueError('Job output directories must not overlap')
    if any(output.is_relative_to(directory) for directory in directories):
        raise ValueError('Batch summary cannot be inside a job output directory')
    allowed = {'oracle','replay','rice_oracle','rice_replay','multi_farm_oracle','multi_farm_replay'}
    for job in jobs:
        if job['kind'] not in allowed:
            raise ValueError('Unsupported offline scoring kind')
        if job['kind'].endswith('replay') and not {'oracle_result','oracle_sha256'} <= job.keys():
            raise ValueError('Batch replay requires an explicit oracle')
    # Credentials are unavailable to all spawned scoring children.
    for key in list(os.environ):
        if any(word in key.upper() for word in ('API_KEY','TOKEN','SECRET','PASSWORD')):
            os.environ.pop(key, None)
    state = dict(status='running', workers=workers, pid=os.getpid(),
                 jobs=[dict(status='pending', output=j['output']) for j in jobs])
    write(output, state)
    try:
        for outcome in run_process_jobs(run_job, jobs, workers):
            index = outcome['index']
            state['jobs'][index] = outcome.get('value') or {
                **outcome, 'output':jobs[index]['output']}
            write(output, state)
    except Exception as exc:
        state.update(status='scheduler_error', error=f'{type(exc).__name__}: {exc}')
        write(output, state)
        return state
    state['status'] = ('scheduler_error' if any(x['status'] in {'pending','interrupted','worker_error','busy'}
                                              for x in state['jobs']) else 'complete')
    write(output, state)
    return state
