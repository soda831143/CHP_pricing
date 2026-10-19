import numpy as np
import pytest

from mechanism_study.predictive_mechanism import crossing
from run_profit_range import physical_regions
from mechanism_study import runtime


def test_online_cost_moves_crossing_but_equal_startup_counts_cancel():
    cost_a,cost_b,da,db=100.,160.,12.,7.
    base=crossing(cost_a,cost_b,da,db)
    epsilon=2.
    assert crossing(cost_a+19*epsilon,cost_b+24*epsilon,da,db)==pytest.approx(base+5*epsilon/(da-db))
    assert crossing(cost_a+epsilon,cost_b+epsilon,da,db)==pytest.approx(base)
    with pytest.raises(ValueError):crossing(cost_a,cost_b,da,da)
    with pytest.raises(ValueError):crossing(np.nan,cost_b,da,db)


def test_negative_surplus_envelope_finds_self_schedule_switch_and_channels():
    # M=max(0,2δ-1), with price slope 3 and D_SS=1 for the active plan.
    def solve(delta):
        intercept,exposure=(0.,0.) if delta<=.5 else (1.,-2.)
        return dict(intercept=intercept,exposure=exposure,lower_bound=-max(0.,2*delta-1))
    points,regions=physical_regions(solve,0.,1.,max_solves=10,tolerance=1e-8)
    assert all(r['ready'] for r in regions)
    assert len(regions)==2
    price=exposure=0.
    for r in regions:
        witness=points[r['witness_delta']]
        active=witness['exposure']<0
        width=r['right']-r['left']
        price+=width*(3. if active else 0.)
        exposure+=width*(4.-(1. if active else 0.))
    assert price==pytest.approx(1.5)
    assert exposure==pytest.approx(3.5)
    assert price+exposure==pytest.approx(1.+4.)


def test_candidate_crossing_does_not_certify_global_optimality():
    delta=crossing(0.,10.,2.,0.)
    globally_better_third_plan=8.
    assert delta==5.
    assert min(2*delta,10.)-globally_better_third_plan>1e-5


def test_checkpoint_retries_a_temporary_file_lock(monkeypatch,tmp_path):
    from pathlib import Path
    original=Path.replace
    attempts=[]
    def locked_once(path,target):
        attempts.append(path)
        if len(attempts)<3:raise PermissionError('sync file lock')
        return original(path,target)
    monkeypatch.setattr(Path,'replace',locked_once)
    monkeypatch.setattr(runtime.time,'sleep',lambda seconds:None)
    runtime.write(tmp_path/'state.json',dict(saved=True))
    assert runtime.read(tmp_path/'state.json')==dict(saved=True)
    assert len(attempts)==3


def test_checkpoint_permanent_lock_keeps_old_file_and_pending(monkeypatch,tmp_path):
    from pathlib import Path
    path=tmp_path/'state.json';path.write_text('{"old":true}')
    def locked(path,target):raise PermissionError('permanent lock')
    monkeypatch.setattr(Path,'replace',locked)
    monkeypatch.setattr(runtime.time,'sleep',lambda seconds:None)
    with pytest.raises(PermissionError):runtime.write(path,dict(new=True))
    assert runtime.read(path)==dict(old=True)
    assert runtime.read(path.with_suffix('.json.pending'))==dict(new=True)
