import numpy as np
import pytest

from make_research_figures import first_amortized_query


def test_first_amortized_query_uses_measured_integer_prefixes():
    assert first_amortized_query([2., 4., 6., 8.], [.1, .2, .3, .4], 5.) == 3
    assert first_amortized_query([2., 4.], [.1, .2], 5.) is None
    assert first_amortized_query([5.1], [.1], 5.) == 1


@pytest.mark.parametrize('direct,online,fixed', [([2., 1.], [.1, .2], 1.),
    ([1.], [.2, .3], 1.), ([np.nan], [.1], 1.), ([1.], [-.1], 1.),
    ([1.], [.1], -1.), ([], [], 1.)])
def test_amortization_rejects_fabricated_or_misaligned_prefixes(direct, online, fixed):
    with pytest.raises(ValueError):
        first_amortized_query(direct, online, fixed)


@pytest.mark.parametrize('unit', ['G1', 'G2'])
def test_archived_cumulative_trace_contains_observations_not_extrapolations(unit):
    import json
    from make_research_figures import ROOT
    path = ROOT/f'results/figure_study_20261016/trace_30_{unit}_q1000.json'
    trace = json.loads(path.read_text(encoding='utf-8'))
    direct, online = trace['same_model_cumulative_seconds'], trace['oracle_cumulative_online_seconds']
    assert len(direct) == len(online) == trace['n_queries'] == 1000
    assert direct[-1] == trace['same_model_reoptimization_batch_seconds']
    assert online[-1] == trace['oracle_online_batch_seconds']
    fixed = trace['oracle_offline_seconds_prior_run']+trace['postprocessing_seconds']+trace['oracle_file_load_seconds']
    assert fixed+online[-1] == pytest.approx(trace['oracle_total_with_offline_seconds'])
    assert first_amortized_query(direct, online, fixed) is not None


def test_all_generator_plot_sources_reconcile_LOC_and_hourly_redispatch():
    from make_research_figures import ROOT, load_rows, values
    root = ROOT/'results/figure_study_20261016'
    rows = load_rows(root/'generator_settlements.csv')
    assert {r['unit'] for r in rows} == {f'G{i}' for i in range(1, 7)}
    residual = values(rows, 'true_profit')-values(rows, 'best_reported_surplus')-values(rows, 'bid_wedge')
    assert np.max(np.abs(residual)) < 1e-5
    nonstrategic = [r for r in rows if r['unit'] != 'G1']
    assert np.max(np.abs(values(nonstrategic, 'bid_wedge'))) == 0.
    hourly = load_rows(root/'boundary_hourly_redispatch.csv')
    assert len(hourly) == 6*24
    assert np.max(np.abs(values(hourly, 'output_change').reshape(6, 24).sum(axis=0))) < 1e-6
