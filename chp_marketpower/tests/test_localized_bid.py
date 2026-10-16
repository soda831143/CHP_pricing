import numpy as np
import pytest

from price_vulnerability.affine_oracle import bid_adder_matrix, solve_endpoint
from price_vulnerability.persistent_chp import PersistentCHP


def test_single_hour_bid_and_all_day_bid_are_different_directions():
    localized = bid_adder_matrix(3, 24, 0, 2., hour=0)
    assert np.count_nonzero(localized) == 1
    assert localized[0, 0] == 2.
    full = bid_adder_matrix(3, 24, 0, 2.)
    assert np.count_nonzero(full) == 24
    assert np.all(full[0] == 2.)


@pytest.mark.parametrize('hour', [-1, 24, 1.5])
def test_bid_hours_cannot_be_silently_wrapped_or_truncated(hour):
    with pytest.raises(ValueError):
        bid_adder_matrix(3, 24, 0, 1., hour)


def test_hourly_persistent_objective_and_exposure_match_explicit_single_hour_lp():
    from engine import PrimalCHPLP, load_case
    gens, net = load_case('30', 'ptdf', 24, 3, 'tight')
    persistent = PersistentCHP(gens, net, 0, hour=0)
    for delta in (.2, .6):
        point = persistent.solve(delta)
        explicit_adders = np.zeros((len(gens), net.T))
        explicit_adders[0, 0] = delta
        direct = PrimalCHPLP(gens, net, bid_adders=explicit_adders, method=1, crossover=1,
                            feasibility_tol=1e-9, optimality_tol=1e-9)
        _, value, success = direct.solve()
        assert success and point.value == pytest.approx(value, abs=1e-6)
        assert point.exposure == pytest.approx(direct.incremental_energy_exposure(0, 0), abs=1e-6)
        assert np.count_nonzero(persistent.solver.bid_adders) == 1
        fresh = solve_endpoint(gens, net, 0, delta, hour=0)
        assert point.value == pytest.approx(fresh.value, abs=1e-6)
        assert np.allclose(point.objective, fresh.objective)
    expected_difference = .4*persistent.direction
    assert np.allclose(point.objective-persistent.c0, .6*persistent.direction)
    assert np.count_nonzero(expected_difference) > 0


@pytest.mark.parametrize('entry', ['range', 'interval', 'settlement'])
def test_all_day_profit_programs_refuse_hour_specific_price_maps(entry, tmp_path):
    from make_research_figures import ROOT
    directory = ROOT/'results/presentation_revision_20261016/30_G1_hour1_0to50'
    with pytest.raises(ValueError, match='all-day'):
        if entry == 'range':
            from run_profit_range import assess
            assess(directory, tmp_path/'unused')
        elif entry == 'interval':
            from run_profit_interval import assess
            assess(directory)
        else:
            from run_selector_settlement import compare
            compare(directory, 1.)


def test_historical_application_cli_cannot_mislabel_localized_map(monkeypatch, tmp_path):
    from make_research_figures import ROOT
    from run_oracle_paper_study import main
    directory = ROOT/'results/presentation_revision_20261016/30_G1_hour1_0to50'
    monkeypatch.setattr('sys.argv', ['study', '--stage', 'application', '--oracle-dir', str(directory),
                                   '--output', str(tmp_path/'unused')])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert not (tmp_path/'unused').exists()
