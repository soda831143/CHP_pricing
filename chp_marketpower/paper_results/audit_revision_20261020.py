"""Independent source-to-table checks for the targeted revision; no optimizer."""
import numpy as np
from mechanism_study.runtime import ROOT, read, write, digest
from paper_results.build_results import PAPER, rows


def main():
    folder = PAPER/'revision_20261020'
    manifest = read(folder/'input_manifest.json')
    assert all(digest(ROOT/p) == expected for p, expected in manifest.items())
    timing = rows(folder/'source_data/table_I_four_workloads.csv')
    prefixes = rows(folder/'source_data/fig1_independent_query_streams.csv')
    maximum = 0.
    for record in timing:
        source = read(ROOT/record['source'])
        data = [r for r in prefixes if r['stream_id'] == record['stream_id']]
        assert len(data) == int(record['queries']) == source['n_queries']
        fixed = sum(source[k] for k in ('oracle_offline_seconds_prior_run', 'postprocessing_seconds', 'oracle_file_load_seconds'))
        hits = []
        for i, r in enumerate(data):
            assert int(r['queries']) == i+1 and float(r['delta']) == source['query_deltas'][i]
            error = max(abs(float(r['direct_seconds'])-source['same_model_cumulative_seconds'][i]),
                abs(float(r['parametric_seconds'])-fixed-source['oracle_cumulative_online_seconds'][i]))
            assert error < 1e-10
            maximum = max(maximum, error)
            if float(r['direct_seconds']) >= float(r['parametric_seconds']):
                hits.append(i+1)
        assert record['first_amortized_query'] == (str(hits[0]) if hits else 'not reached')
        assert abs(float(data[-1]['direct_seconds'])/float(data[-1]['parametric_seconds'])-float(record['direct_over_parametric'])) < 1e-12
    local = read(ROOT/'results/finalization_20261017/localized_economics/localized_economic_followup.json')
    verified = rows(folder/'source_data/hour1_profit_candidates_verified.csv')
    assert len(verified) == len(local['target_candidates']) == 4
    for new, original in zip(verified, local['target_candidates']):
        assert float(new['delta']) == original['delta'] and int(new['physical_region']) == original['physical_region']
        assert abs(float(new['Pi'])-original['true_profit']) < 1e-6
        assert abs(float(new['R'])+float(new['U'])-float(new['C'])-float(new['Pi'])) < 1e-6
        assert abs(float(new['Pi'])-local['baseline_true_profit']-float(new['delta_Pi'])) < 1e-6
    assert abs(max(float(r['delta_Pi']) for r in verified)) < 1e-6
    certificate = rows(folder/'source_data/hour1_common_UC_certificates.csv')
    assert float(certificate[0]['left']) == 0 and float(certificate[-1]['right']) == 20.991
    assert np.isclose(float(certificate[0]['right']), float(certificate[1]['left']), rtol=0, atol=1e-10)
    assert all(float(r['maximum_endpoint_bound_gap']) < 1e-6 for r in certificate)
    old = read(PAPER/'delivery_manifest.json')
    assert all(digest(ROOT/p) == expected for p, expected in old['files'].items())
    result = dict(status='passed', input_hashes=len(manifest), timing_streams=len(timing),
        measured_prefixes=len(prefixes), max_prefix_reconstruction_error=maximum,
        localized_candidates=len(verified), original_delivery_files_unchanged=len(old['files']), new_optimization_solves=0)
    write(folder/'independent_verification.json', result)
    print(result)


if __name__ == '__main__':
    main()
