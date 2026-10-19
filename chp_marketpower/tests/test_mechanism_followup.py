"""Regression checks for the recovered E2-E4 study and structural UC options."""
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from engine import ScheduleRunMILP, load_case
from models.network import SingleNodeNetwork
from price_vulnerability.model_identity import model_identity
from mechanism_study import constraint_attribution as causal
from mechanism_study.local_response import price_segment, classify
from mechanism_study.runtime import Stage
from test_model_consistency import toy_case


def test_expected_old_oracle_rejection_allows_rebuilt_e4(monkeypatch, tmp_path):
    # Reproduce the original failure before the first solver context is entered.
    class ReachedRebuild(Exception):
        pass

    @contextmanager
    def solvers():
        raise ReachedRebuild
        yield

    monkeypatch.setattr(causal, 'Stage', lambda *a, **kw: SimpleNamespace(out=tmp_path, solvers=solvers))
    with pytest.raises(ReachedRebuild):
        causal.run()


def test_treatment_changes_only_the_selected_line_and_rejects_old_map(tmp_path):
    gens, net = load_case('30', 'ptdf', 24, 3, 'tight')
    original = model_identity(gens, net)
    intervention = dict(kind='line_capacity', line_index_0based=29, new_capacity_mw=81.0599681)
    changed_g, changed_n = causal.treatment(gens, net, intervention)
    changed = model_identity(changed_g, changed_n)
    assert changed_g is gens
    assert net.F_max[29] == 20.8
    assert changed_n.F_max[29] == intervention['new_capacity_mw']
    assert {k for k in original['components'] if original['components'][k] != changed['components'][k]} == {'F_max'}
    from price_vulnerability.model_identity import check_model_identity
    with pytest.raises(ValueError, match='changed'):
        check_model_identity(tmp_path, changed_g, changed_n, dict(model_identity=original))


def test_original_binding_corruption_is_not_mistaken_for_expected_rejection(monkeypatch, tmp_path):
    monkeypatch.setattr(causal, 'Stage', lambda *a, **kw: SimpleNamespace(out=tmp_path))
    def corrupted(*a, **kw):
        raise ValueError('Model identity belongs to different archived witnesses')
    monkeypatch.setattr(causal, 'check_model_identity', corrupted)
    with pytest.raises(ValueError, match='different archived witnesses'):
        causal.run()


def test_failed_worker_is_not_left_running_in_manifest(monkeypatch, tmp_path):
    from mechanism_study import run_followup
    from mechanism_study.runtime import read
    monkeypatch.setattr(run_followup, 'OUTPUT', tmp_path)
    monkeypatch.setattr('sys.argv', ['study', '--stage', 'causal'])
    monkeypatch.setattr(run_followup.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=17))
    with pytest.raises(SystemExit, match='Stage failed'):
        run_followup.main()
    state=read(tmp_path/run_followup.CAUSAL_STAGE/'manifest.json')
    assert state['status']=='failed' and state['worker_returncode']==17


def test_local_price_slope_uses_declared_side_at_kink():
    compact = dict(price_boundaries=np.array([0., 1., 2.]), prices=np.array([[[0.]], [[2.]], [[1.]]]))
    assert price_segment(compact, 1., 'left')[1].item() == 2.
    assert price_segment(compact, 1., 'right')[1].item() == -1.
    assert classify(4., -3.) == 'opposing_channels'


def test_structural_objective_preserves_dispatch_and_records_output_bound():
    gen, net = toy_case()
    uc = ScheduleRunMILP([gen], net)
    p, u, minimum = uc.solve(require_optimal=True, mip_gap=0., minimize_output=(0, 1))
    assert minimum == pytest.approx(55.)
    assert uc.solve_info['lower_bound'] == pytest.approx(minimum)
    np.testing.assert_allclose(p[0], net.demand[0])


def test_forced_outage_removes_output_and_records_true_infeasibility():
    from coptpy import COPT
    gen, _ = toy_case()
    gen = replace(gen, initial_status=0, initial_power=0., initial_up_time=0, initial_down_time=100)
    net = SingleNodeNetwork(np.array([40., 55., 30.]))
    spare = replace(gen, unit_id='spare', cost_var=gen.cost_var+10.)
    p, u, _ = ScheduleRunMILP([gen, spare], net).solve(require_optimal=True, force_off=(0,))
    np.testing.assert_allclose(p[0], 0.)
    np.testing.assert_allclose(u[0], 0.)
    np.testing.assert_allclose(p[1], net.demand[0])
    removed = ScheduleRunMILP([gen], net)
    with pytest.raises(RuntimeError):
        removed.solve(require_optimal=True, force_off=(0,))
    assert removed._model.getAttr(COPT.Attr.MipStatus) == COPT.INFEASIBLE


def test_checkpoint_rejects_changed_numeric_results_and_budget_counts_failures(monkeypatch, tmp_path):
    from mechanism_study import runtime
    monkeypatch.setattr(runtime, 'OUTPUT', tmp_path)
    stage = Stage('test', budgets={'uc': 1}, seconds=10.)
    stage.save('sample', {'status': 'passed'}, {'p': np.array([1.])})
    (stage.out/'sample.npz').write_bytes(b'changed')
    with pytest.raises(ValueError, match='numeric checkpoint'):
        stage.cached('sample')
    with pytest.raises(ZeroDivisionError):
        stage.call('uc', 'failed', lambda: 1/0)
    with pytest.raises(RuntimeError, match='budget exhausted'):
        stage.call('uc', 'retry', lambda: 0)


def test_complete_price_face_at_the_reproduced_high_bid(monkeypatch, tmp_path):
    from mechanism_study import runtime
    from mechanism_study.linear_audit import price_face_extremes
    from price_vulnerability.persistent_chp import PersistentCHP
    monkeypatch.setattr(runtime, 'OUTPUT', tmp_path)
    stage=Stage('face',budgets=dict(chp=1,auxiliary=2),seconds=120.)
    gens,net=load_case('30','ptdf',24,3,'tight')
    with np.load(runtime.ROOT/'results/mechanism_20261018/baseline.npz') as z:weight=z['self_p']
    with stage.solvers():
        cp=PersistentCHP(gens,net,0)
        point=stage.call('chp','matrix',lambda:cp.solve(causal.CRITICAL+.001))
        faces=price_face_extremes(cp,point,weight,stage,'regression')
    assert [face['status'] for face in faces]==['optimal','optimal']
    assert faces[0]['functional_value']<=faces[1]['functional_value']+1e-6
    assert max(f['full_dual_residual'] for f in faces)<1e-6
