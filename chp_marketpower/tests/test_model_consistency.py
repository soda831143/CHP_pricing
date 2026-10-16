import copy
import json
from dataclasses import replace

import numpy as np
import pytest

from engine import load_case, ScheduleRunMILP
from models.generator import GeneratorParams
from models.network import SingleNodeNetwork
from benchmarks.unit_self_schedule import dispatch_cost, UnitSelfScheduleMILP
from price_vulnerability.model_identity import model_identity, check_model_identity
from price_vulnerability.scalar_markup import apply_generator_adder
from strategic_market_simulation.profit_sweep import _settle_target
from run_initial_condition_audit import schedule_residuals
from make_research_figures import ROOT, read


@pytest.mark.parametrize('component', ['initial', 'cost', 'demand', 'PTDF', 'PTDF_Gen', 'F_max'])
def test_identity_detects_changes_to_fixed_market_inputs(component, tmp_path):
    gens, net = load_case('30', 'ptdf', 24, 3, 'tight')
    original = model_identity(gens, net)
    assert original == model_identity(copy.deepcopy(gens), copy.deepcopy(net))
    if component == 'initial':
        gens[0] = replace(gens[0], initial_down_time=0)
    elif component == 'cost':
        gens[0] = replace(gens[0], cost_su=gens[0].cost_su+1.)
    else:
        getattr(net, component).flat[0] += .001
    assert original['model_sha256'] != model_identity(gens, net)['model_sha256']
    with pytest.raises(ValueError, match='changed'):
        check_model_identity(tmp_path, gens, net, dict(model_identity=original))


def test_unbound_legacy_map_is_explicit_not_silently_fingerprinted(tmp_path):
    gens, net = load_case('30', 'single', 24, 3)
    with pytest.warns(RuntimeWarning, match='Legacy'):
        assert check_model_identity(tmp_path, gens, net, {}) is False


def test_unbound_legacy_witnesses_cannot_be_inherited_and_relabelled(monkeypatch, tmp_path):
    from run_affine_oracle import main
    parent = tmp_path/'legacy'
    parent.mkdir()
    (parent/'audit.json').write_text(json.dumps({'scope':{}}))
    monkeypatch.setattr('sys.argv', ['oracle', '--discover', '--case', '30', '--generator', '0',
        '--lower', '0', '--upper', '1', '--resume-from', str(parent), '--seed-delta', '.5',
        '--out-dir', str(tmp_path/'new')])
    with pytest.warns(RuntimeWarning, match='Legacy'), pytest.raises(ValueError, match='Cannot inherit unbound'):
        main()
    assert not (tmp_path/'new/oracle.npz').exists()


def toy_case():
    gen = GeneratorParams(P_max=100., P_min=10., R_up=100., R_down=100., T_on_min=1,
        T_off_min=1, cost_var=20., cost_su=9., cost_sd=4., cost_nl=5., T=3,
        initial_status=1, initial_power=20., initial_up_time=3,
        pwl_slopes=[10., 20., 30.], pwl_widths=[30., 30., 30.])
    return gen, SingleNodeNetwork(np.array([40., 55., 30.]))


def test_hourly_costs_reconcile_UC_self_schedule_LOC_and_true_profit():
    gen, net = toy_case()
    adders = np.array([2., 0., 0.])
    p, u, value = ScheduleRunMILP([gen], net, bid_adders=adders[None]).solve(require_optimal=True, mip_gap=0.)
    true_cost = dispatch_cost(gen, p[0], u[0])
    assert value == pytest.approx(true_cost+60.)
    assert value == pytest.approx(dispatch_cost(gen, p[0], u[0], bid_adders=adders))
    result = _settle_target(gen, gen, np.array([50., 50., 50.]), p[0], u[0], mip_gap=0., bid_adders=adders)
    assert result['true_profit'] == pytest.approx(result['best_reported_profit']+60.)
    assert result['reported_cost']-result['true_cost'] == pytest.approx(60.)
    assert max(schedule_residuals([gen], net, p, u).values()) < 1e-8


def test_new_all_day_objective_is_equivalent_to_existing_reported_generator_path():
    gen, net = toy_case()
    reported = apply_generator_adder([gen], 0, 2.)[0]
    p, u, value = ScheduleRunMILP([gen], net, bid_adders=np.full((1, 3), 2.)).solve(require_optimal=True, mip_gap=0.)
    _, _, old_value = ScheduleRunMILP([reported], net).solve(require_optimal=True, mip_gap=0.)
    assert value == pytest.approx(old_value)
    assert dispatch_cost(gen, p[0], u[0], bid_adders=np.full(3, 2.)) == pytest.approx(dispatch_cost(reported, p[0], u[0]))
    price = np.full(3, 50.)
    _, _, first = UnitSelfScheduleMILP.solve(gen, price, require_optimal=True, bid_adders=np.full(3, 2.))
    _, _, second = UnitSelfScheduleMILP.solve(reported, price, require_optimal=True)
    assert first == pytest.approx(second)


def test_hourly_objective_inputs_are_not_broadcast_silently():
    gen, net = toy_case()
    with pytest.raises(ValueError, match='generator-by-hour'):
        ScheduleRunMILP([gen], net, bid_adders=np.zeros(3))
    with pytest.raises(ValueError, match='hourly'):
        UnitSelfScheduleMILP.solve(gen, np.ones(3), bid_adders=[np.nan, 0., 0.])


def test_initial_audit_does_not_accept_optimal_status_without_dual_residual_gate(monkeypatch):
    from types import SimpleNamespace
    import run_initial_condition_audit as study
    gen, net = toy_case()
    monkeypatch.setattr(study, 'ScheduleRunMILP', lambda *a, **kw: SimpleNamespace(
        solve=lambda **kw: (np.zeros((1, 3)), np.zeros((1, 3)), 0.)))
    monkeypatch.setattr(study, 'solve_endpoint', lambda *a, **kw: object())
    monkeypatch.setattr(study, 'dual_audit_passed', lambda endpoint: False)
    with pytest.raises(RuntimeError, match='complete primal-dual audit'):
        study.audited_point([gen], net, 0, 0., {})


def test_published_initial_audit_and_localized_economics_do_not_conflate_price_and_dispatch():
    root = ROOT/'results/finalization_20261017'
    audit = read(root/'initial_audit/initial_condition_audit.json')
    for identity in audit['model_identities'].values():
        assert all(row['initial_status'] == row['initial_power'] == 0 for row in identity['initial_conditions'])
    for rows in audit['records'].values():
        for row in rows:
            from types import SimpleNamespace
            from price_vulnerability.affine_oracle import dual_audit_passed
            assert dual_audit_passed(SimpleNamespace(audit=row['chp_full_dual_residuals']))
            assert max(row['physical_residuals'].values()) < 1e-6
            assert row['chp_above_uc_lower_bound_usd'] < 1e-5
            assert row['reported_cost_reconstruction_usd'] < 1e-5
    local = audit['localized_economics']
    assert local['common_plan_found'] is False
    assert local['endpoint_uc_checks'][1]['units'][0]['true_profit'] < local['endpoint_uc_checks'][0]['units'][0]['true_profit']
    followup = read(root/'localized_economics/localized_economic_followup.json')
    assert followup['status'] == 'numerically_validated' and followup['new_uc_solves'] == 1
    assert len(followup['physical_regions']) == 2 and abs(followup['maximum_additional_profit']) < 1e-5
