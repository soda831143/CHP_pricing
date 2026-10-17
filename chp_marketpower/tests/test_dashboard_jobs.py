"""Native child-process lifecycle: cancellation/timeout cannot publish partial settlement."""
import time
import json

from dashboard.data import load_export, evaluate
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
    scenario = load_export()[0]['scenarios'][2]
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
    scenario = load_export()[0]['scenarios'][1]
    bad = dict(scenario,model_sha256='wrong-model')
    job = SolveJob(bad,.123456789,None,seconds=15,directory=tmp_path/'jobs',cache_directory=tmp_path/'cache')
    assert finished(job)['status']=='failed'
    assert not list((tmp_path/'cache').glob('*.json'))
    retry = SolveJob(scenario,.123456789,None,seconds=20,directory=tmp_path/'jobs',cache_directory=tmp_path/'cache')
    state = finished(retry)
    assert state['status']=='complete', (state,(retry.path.parent/'worker.log').read_text(encoding='utf-8'))
    q = evaluate(scenario,.123456789)
    result = cached(scenario,q['delta'],None,tmp_path/'cache')
    assert len(result['rows'])==6 and result['uc_status']=='solved_on_demand'
    assert cached(scenario,0.,None,tmp_path/'cache') is not None


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
