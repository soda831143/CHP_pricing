import numpy as np
import pytest

from revise_research_figures import (OLD, PROFIT, ROOT, read, load_rows, price_heatmap,
                                     settlement_table, first_amortized_query)


def test_heatmap_keeps_breakpoints_and_evaluates_the_affine_selector():
    compact = dict(value_boundaries=np.array([0., 1., 2.]), values=np.array([0., 1., 1.5]),
        price_boundaries=np.array([0., 1., 2.]), prices=np.array([[[2., 4.]], [[4., 2.]], [[3., 5.]]]))
    edges, centers, change = price_heatmap(compact, 4.)
    assert 25. in edges
    assert change.shape == (2, len(centers))
    assert np.allclose(change[0], np.interp(centers, [0., 1., 2.], [0., 2., 1.]))
    assert np.allclose(change[1], np.interp(centers, [0., 1., 2.], [0., -2., 1.]))


def test_settlement_decomposition_uses_same_boundary_plan_and_all_units():
    source = read(OLD/'economic_source_audit.json')
    report = read(PROFIT/'profit_range.json')
    table = settlement_table(load_rows(OLD/'generator_settlements.csv'), source['baseline'], report['maximizing_candidate'])
    assert len(table) == 6
    for r in table:
        assert r['energy_revenue_change']+r['reported_uplift_change']-r['true_cost_change'] == pytest.approx(r['true_profit_change'], abs=1e-5)
    assert table[0]['true_profit_change'] == pytest.approx(report['maximizing_candidate']['extra_profit_vs_truthful'], abs=1e-5)
    assert table[2]['energy_revenue_change'] < 0 < table[2]['true_profit_change']
    assert table[4]['energy_revenue_change'] > 10000 and abs(table[4]['true_profit_change']) < 1e-5


def test_118_prefix_is_one_measured_batch_without_extrapolation():
    trace = read(ROOT/'results/presentation_revision_20261016/trace_118_G11_q200.json')
    direct, online = trace['same_model_cumulative_seconds'], trace['oracle_cumulative_online_seconds']
    assert len(direct) == len(online) == trace['n_queries'] == 200
    assert direct[-1] == trace['same_model_reoptimization_batch_seconds']
    assert online[-1] == trace['oracle_online_batch_seconds']
    fixed = trace['oracle_offline_seconds_prior_run']+trace['postprocessing_seconds']+trace['oracle_file_load_seconds']
    assert first_amortized_query(direct, online, fixed) is None


def test_localized_study_keeps_scope_and_reports_a_null_selected_price_response():
    directory = ROOT/'results/presentation_revision_20261016/30_G1_hour1_0to50'
    audit, validation = read(directory/'audit.json'), read(directory/'validation.json')
    assert audit['scope']['bid_hour_1based'] == 1
    assert validation['scope'] == audit['scope'] and validation['status'] == 'passed'
    assert audit['price_coverage_fraction'] == 1.
    with np.load(directory/'oracle.npz') as data:
        assert np.allclose(data['exposures'], 40.)
        assert data['values'][-1]-data['values'][0] == pytest.approx(40.*20.991, abs=1e-6)
        assert np.max(abs(data['prices']-data['prices'][0])) < 1e-6
