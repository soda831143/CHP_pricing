"""Study-local budgets and durable checkpoints; no changes to archived maps."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from contextlib import contextmanager
from importlib.metadata import version

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT/'results/mechanism_20261018/followup'
CAUSAL_STAGE = 'E4_causal_recovery_02'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+'.pending')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    for attempt in range(6):
        try:
            temp.replace(path)
            break
        except PermissionError:
            if attempt == 5:
                raise
            # Sync clients can briefly lock the destination; keep atomic replacement.
            time.sleep(.05*2**attempt)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint():
    paths = list((ROOT/'mechanism_study').glob('*.py'))
    paths += list((ROOT.parent/'chp_energy').rglob('*.py'))
    paths += list((ROOT/'price_vulnerability').glob('*.py'))
    return {str(p.relative_to(ROOT.parent)):digest(p) for p in paths}


class Stage:
    def __init__(self, name, *, budgets, seconds=600., seed=20261018, resume=False, plan=None):
        self.out = OUTPUT/name
        self.out.mkdir(parents=True, exist_ok=True)
        self.path = self.out/'manifest.json'
        self.started = time.perf_counter()
        self.seconds, self.seed = seconds, seed
        identity = dict(code=fingerprint(), budgets=budgets, seconds=seconds, seed=seed, plan=plan)
        if self.path.exists():
            if not resume:
                raise ValueError('Existing stage: use --resume or preserve it before a revised protocol')
            self.state = read(self.path)
            if self.state['identity'] != identity:
                raise ValueError('Resume refuses changed code, protocol or budgets')
        else:
            self.state = dict(stage=name, status='running', identity=identity, calls=[], jobs={},
                base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,encoding='utf-8').strip(),
                branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,encoding='utf-8').strip(),
                solver=dict(name='COPT',version=version('coptpy'),threads=1,relative_mip_gap=0.,
                            absolute_mip_gap=1e-8,feasibility_tolerance=1e-9))
        write(self.path, self.state)

    def cached(self, name):
        entry = self.state['jobs'].get(name)
        if entry is None:
            return None
        if digest(self.out/(name+'.json')) != entry['json_sha256']:
            raise ValueError('Changed JSON checkpoint')
        if entry.get('npz_sha256') and digest(self.out/(name+'.npz')) != entry['npz_sha256']:
            raise ValueError('Changed numeric checkpoint')
        return read(self.out/(name+'.json'))

    def save(self, name, data, arrays=None):
        write(self.out/(name+'.json'), data)
        entry = dict(json_sha256=digest(self.out/(name+'.json')))
        if arrays is not None:
            np.savez_compressed(self.out/(name+'.npz'), **arrays)
            entry['npz_sha256'] = digest(self.out/(name+'.npz'))
        self.state['jobs'][name] = entry
        write(self.path, self.state)

    def call(self, kind, name, function):
        if sum(r['kind']==kind for r in self.state['calls']) >= self.state['identity']['budgets'][kind]:
            raise RuntimeError(f'{kind} budget exhausted; unsuccessful attempts are counted')
        if time.perf_counter()-self.started >= self.seconds:
            raise RuntimeError('Stage time budget exhausted')
        row = dict(kind=kind,job=name,status='started')
        self.state['calls'].append(row);write(self.path,self.state)
        tick = time.perf_counter()
        try:
            result = function()
            row['status'] = 'completed'
            return result
        except Exception as error:
            row.update(status='failed',error=f'{type(error).__name__}: {error}')
            raise
        finally:
            row['seconds'] = time.perf_counter()-tick
            write(self.path,self.state)

    def finish(self, status='passed'):
        self.state.update(status=status,seconds_this_invocation=time.perf_counter()-self.started)
        write(self.path,self.state)

    @contextmanager
    def solvers(self):
        import gurobi_compat as gp
        original = gp.Model
        def model(*args, **kwargs):
            m = original(*args, **kwargs)
            for key,value in dict(Logging=0,Threads=1,RandSeed=self.seed,AbsGap=1e-8,FeasTol=1e-9,
                    IntTol=1e-9,DualTol=1e-9,TimeLimit=max(.01,self.seconds-(time.perf_counter()-self.started))).items():
                m.setParam(key,value)
            return m
        gp.Model = model
        try:
            yield
        except Exception as error:
            self.state.update(status='failed',error=f'{type(error).__name__}: {error}')
            write(self.path,self.state)
            raise
        finally:
            gp.Model = original
