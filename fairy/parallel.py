"""Bounded native process execution, shared by replay and offline CLI jobs."""
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from concurrent.futures.process import BrokenProcessPool
import multiprocessing


def run_process_jobs(function, jobs, workers):
    """Yield indexed outcomes; never resubmit work after a worker crashes.

    At most ``workers`` jobs are submitted at once. Each process handles one job
    so module patches, simulator state and environment settings cannot leak.
    There is deliberately no thread fallback.
    """
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError('workers must be a positive integer')
    jobs = list(jobs)
    if not jobs:
        return
    pool = ProcessPoolExecutor(max_workers=workers,
                               mp_context=multiprocessing.get_context('spawn'),
                               max_tasks_per_child=1)
    active = {}
    next_index = 0
    broken = None
    try:
        while next_index < len(jobs) or active:
            while next_index < len(jobs) and len(active) < workers and broken is None:
                try:
                    future = pool.submit(function, jobs[next_index])
                except (BrokenProcessPool, OSError, RuntimeError) as exc:
                    broken = f'{type(exc).__name__}: {exc}'
                    break
                active[future] = next_index
                next_index += 1
            if not active:
                break
            done, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                index = active.pop(future)
                try:
                    value = future.result()
                except BrokenProcessPool as exc:
                    broken = f'{type(exc).__name__}: {exc}'
                    yield dict(index=index, status='interrupted', error=broken)
                except Exception as exc:
                    yield dict(index=index, status='worker_error',
                               error=f'{type(exc).__name__}: {exc}')
                else:
                    yield dict(index=index, status='completed', value=value)
            if broken and not active:
                break
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    for index in range(next_index, len(jobs)):
        yield dict(index=index, status='pending', error=broken or 'Not submitted')
