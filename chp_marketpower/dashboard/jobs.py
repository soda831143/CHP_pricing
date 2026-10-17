"""One bounded local UC/LOC child process per UI session; no public job service."""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from dashboard.data import evaluate, load_catalog, get_scenario, sampled_settlement
from dashboard.service import CACHE, ROOT, engine_sha, solve
from dashboard.catalog import write_json


def write_state(path, state):
    write_json(path,state)


def read_state(path):
    for attempt in range(5):
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except PermissionError:
            if attempt==4: raise
            time.sleep(.02)


class SolveJob:
    def __init__(self, scenario, rho, region, seconds=600., directory=None, cache_directory=CACHE, mode='settlement'):
        if not 0<seconds<=3600:
            raise ValueError('Set a wall-time budget in (0, 3600] seconds')
        if mode not in ('settlement','validation'):
            raise ValueError('Unknown computation mode')
        query = evaluate(scenario,rho)
        self.scope = dict(scenario=scenario['id'],rho=query['rho'],region=region,mode=mode)
        self.started = time.monotonic()
        self.seconds = seconds
        self._lock = threading.Lock()
        self._terminal = None
        folder = (directory or ROOT/'results/dashboard_jobs')/uuid.uuid4().hex
        folder.mkdir(parents=True)
        self.path = folder/'progress.json'
        request = dict(**self.scope, model_sha256=scenario['model_sha256'],
            selector_sha256=scenario['price_selector_sha256'],engine_sha256=engine_sha(),
            physical_sha256=scenario['physical_sha256'],
            cache_directory=str(cache_directory.resolve()),started_at=time.time(),timeout_at=time.time()+seconds)
        (folder/'request.json').write_text(json.dumps(request),encoding='utf-8')
        write_state(self.path,dict(status='running',message='启动独立求解进程…'))
        with (folder/'worker.log').open('w',encoding='utf-8') as log:
            self.process = subprocess.Popen([sys.executable,'-m','dashboard.jobs','--request',str(folder/'request.json')],
                cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                env=dict(os.environ,PYTHONIOENCODING='utf-8'),
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self._timer = threading.Timer(seconds,self.stop,args=('timed_out',))
        self._timer.daemon = True
        self._timer.start()

    def stop(self, status='cancelled'):
        with self._lock:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=10)
                self._terminal = dict(status=status,message='已超时并终止求解进程' if status=='timed_out' else '已取消并终止求解进程')
                self._terminal['elapsed_seconds'] = time.monotonic()-self.started
                write_state(self.path,self._terminal)
            self._timer.cancel()

    def state(self):
        with self._lock:
            if self._terminal:
                result = self._terminal
            else:
                result = read_state(self.path)
                code = self.process.poll()
                if code is not None:
                    self._timer.cancel()
                    if result['status']=='running':
                        result = dict(status='failed',message=f'求解进程退出（{code}），未生成成功标记；日志：{self.path.parent.name}')
                    result.setdefault('elapsed_seconds',time.monotonic()-self.started)
                    self._terminal = result
                    write_state(self.path,result)
            return dict(result,**self.scope,elapsed_seconds=result.get('elapsed_seconds',time.monotonic()-self.started))


def worker(request_path):
    request = json.loads(request_path.read_text(encoding='utf-8'))
    progress_path = request_path.parent/'progress.json'
    started_at = request.get('started_at',time.time())
    def progress(message):
        write_state(progress_path,dict(status='running',message=message))
    def expired():
        write_state(progress_path,dict(status='timed_out',message='已超时并终止求解进程',elapsed_seconds=time.time()-started_at))
        os._exit(124)
    watchdog = threading.Timer(max(.001,request.get('timeout_at',time.time()+600)-time.time()),expired)
    watchdog.daemon = True
    watchdog.start()
    try:
        data,_ = load_catalog()
        entry = next(s for s in data['scenarios'] if s['id']==request['scenario'])
        s = get_scenario(data,entry['case'],entry['generator_index'],entry['bid_hour_1based'])
        if (request['model_sha256']!=s['model_sha256'] or request['selector_sha256']!=s['price_selector_sha256']
                or request.get('physical_sha256')!=s['physical_sha256'] or request['engine_sha256']!=engine_sha()):
            raise ValueError('求解请求的模型、选价或计算代码已改变，请重新提交')
        if request.get('mode')=='validation':
            progress('独立求解当前报价的CHP并核对完整对偶，不计算UC或LOC…')
            from dashboard.validation import validate_current
            result = validate_current(s,request['rho'])
            write_state(progress_path,dict(status='complete',message='当前报价的CHP独立数值验证已通过',
                validation=result,elapsed_seconds=time.time()-started_at))
            return
        q = evaluate(s,0.)
        baseline_region = q['physical'][0]['region_index'] if q['physical'] else None
        directory = Path(request['cache_directory'])
        if sampled_settlement(s,q['delta'],baseline_region) is None:
            progress('按成本申报基准：准备机组组合（UC） 与全部机组结算…')
            solve(s,0.,baseline_region,progress=lambda message:progress('基准 · '+message),directory=directory)
        solve(s,request['rho'],request['region'],progress=lambda message:progress('当前报价 · '+message),directory=directory)
        write_state(progress_path,dict(status='complete',message='当前报价及所需基准已完成，完整结果已写入精确缓存',elapsed_seconds=time.time()-started_at))
    except Exception as error:
        write_state(progress_path,dict(status='failed',message=str(error),elapsed_seconds=time.time()-started_at))
        raise
    finally:
        watchdog.cancel()


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',type=Path,required=True)
    worker(parser.parse_args().request)
