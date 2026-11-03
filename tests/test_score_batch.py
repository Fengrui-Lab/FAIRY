from pathlib import Path
import json
import os
import time

import pytest

from fairy.parallel import run_process_jobs
from fairy.contracts.score_batch import run_batch, run_job


def _job(value):
    time.sleep(.15)
    if value == 'error':raise ValueError('isolated failure')
    if value == 'crash':os._exit(7)
    return {'pid':os.getpid(),'value':value}


def test_native_pool_isolates_processes_and_continues_after_failure():
    results=list(run_process_jobs(_job,[1,'error',2],2))
    assert sorted(x['index'] for x in results)==[0,1,2]
    assert sum(x['status']=='completed' for x in results)==2
    assert next(x for x in results if x['index']==1)['status']=='worker_error'
    assert len({x['value']['pid'] for x in results if 'value' in x})==2


def test_native_pool_crash_preserves_unsubmitted_work():
    results=list(run_process_jobs(_job,['crash',1,2,3,4],2))
    assert {x['index'] for x in results}==set(range(5))
    assert any(x['status']=='interrupted' for x in results)
    assert next(x for x in results if x['index']==4)['status']=='pending'


def test_batch_rejects_same_or_overlapping_output_directories(tmp_path):
    base={'workers':2,'output':str(tmp_path/'batch.json')}
    for second in [tmp_path/'a/result2.json',tmp_path/'a/b/result.json']:
        with pytest.raises(ValueError,match='directory|directories'):
            run_batch({**base,'jobs':[{'output':str(tmp_path/'a/result.json')},{'output':str(second)}]})


def test_batch_requires_explicit_oracle(tmp_path):
    with pytest.raises(ValueError,match='explicit oracle'):
        run_batch({'workers':2,'output':str(tmp_path/'batch.json'),
                   'jobs':[{'kind':'replay','output':str(tmp_path/'a/result.json')}]})


def test_failed_receipt_is_reused_and_started_job_is_not_retried(tmp_path):
    job={'kind':'oracle','identity':{'scenario_id':'not_a_real_scenario'},'output':str(tmp_path/'failed/result.json')}
    first=run_job(job)
    assert first['status']=='failed'
    receipt=tmp_path/'failed/receipt.json';mtime=receipt.stat().st_mtime_ns
    assert run_job(job)['cached'] is True
    assert receipt.stat().st_mtime_ns==mtime
    interrupted={**job,'output':str(tmp_path/'interrupted/result.json')}
    marker=tmp_path/'interrupted/started.json';marker.parent.mkdir();marker.write_text('{}')
    assert run_job(interrupted)['status']=='interrupted'
    assert not (marker.parent/'result.json').exists()
