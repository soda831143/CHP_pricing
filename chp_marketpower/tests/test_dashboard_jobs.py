"""Native child-process lifecycle: cancellation/timeout cannot publish partial settlement."""
import time
import json

from dashboard.data import load_catalog, get_scenario, evaluate
from dashboard.jobs import SolveJob, read_state, write_state
from dashboard.service import cached


def finished(job):
    deadline = time.monotonic()+30
    while time.monotonic()<deadline:
        state = job.state()
        if state['status']!='running': return state
        time.sleep(.05)
    job.stop()
    raise AssertionError(f'Worker did not finish; inspect {job.path.parent}')


def test_cancel_and_timeout_stop_native_process_without_success_cache(tmp_path):
    scenario = get_scenario(load_catalog()[0],'118',10)
    for action in ('cancelled','timed_out'):
        job = SolveJob(scenario,.123456789,None,seconds=.1 if action=='timed_out' else 10,
            directory=tmp_path/'jobs',cache_directory=tmp_path/'cache')
        if action=='cancelled': job.stop()
        state = finished(job)
        assert state['status']==action and job.process.poll() is not None
        assert json.loads(job.path.read_text(encoding='utf-8'))['status']==action
        elapsed = state['elapsed_seconds']
        time.sleep(.02)
        assert job.state()['elapsed_seconds']==elapsed
    assert not list((tmp_path/'cache').glob('*.json'))


def test_worker_failure_is_visible_and_retry_completes_same_quote(tmp_path):
    scenario = get_scenario(load_catalog()[0],'30',1)
    query = evaluate(scenario,.123456789)
    region = query['physical'][0]['region_index'] if query['physical'] else None
    bad = dict(scenario,model_sha256='wrong-model')
    job = SolveJob(bad,.123456789,region,seconds=15,directory=tmp_path/'jobs',cache_directory=tmp_path/'cache')
    assert finished(job)['status']=='failed'
    assert not list((tmp_path/'cache').glob('*.json'))
    retry = SolveJob(scenario,.123456789,region,seconds=20,directory=tmp_path/'jobs',cache_directory=tmp_path/'cache')
    state = finished(retry)
    assert state['status']=='complete', (state,(retry.path.parent/'worker.log').read_text(encoding='utf-8'))
    q = evaluate(scenario,.123456789)
    result = cached(scenario,q['delta'],region,tmp_path/'cache')
    assert len(result['rows'])==6
    base = evaluate(scenario,0.)
    baseline_region = base['physical'][0]['region_index'] if base['physical'] else None
    assert cached(scenario,0.,baseline_region,tmp_path/'cache') is not None


def test_independent_chp_job_does_not_publish_settlement(tmp_path):
    scenario = get_scenario(load_catalog()[0],'30',0)
    job = SolveJob(scenario,.123456789,0,seconds=25,directory=tmp_path/'jobs',
        cache_directory=tmp_path/'cache',mode='validation')
    state = finished(job)
    assert state['status']=='complete', (state,(job.path.parent/'worker.log').read_text(encoding='utf-8'))
    assert state['validation']['status']=='passed'
    assert state['validation']['checks']['value_error_usd']<1e-6
    assert not list((tmp_path/'cache').glob('*.json'))


def test_progress_io_retries_transient_windows_sharing_violation(tmp_path,monkeypatch):
    from pathlib import Path
    path = tmp_path/'progress.json'
    original_replace,original_read = Path.replace,Path.read_text
    calls = dict(read=0,replace=0)
    def locked_replace(self,target):
        calls['replace']+=1
        if calls['replace']==1: raise PermissionError('sharing violation')
        return original_replace(self,target)
    def locked_read(self,**kwargs):
        calls['read']+=1
        if calls['read']==1: raise PermissionError('sharing violation')
        return original_read(self,**kwargs)
    monkeypatch.setattr(Path,'replace',locked_replace)
    monkeypatch.setattr(Path,'read_text',locked_read)
    write_state(path,dict(status='running',message='test'))
    assert read_state(path)['status']=='running'
    assert calls==dict(read=2,replace=2)
