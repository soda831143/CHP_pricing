"""Matched 0-50% domains, three construction repeats, and a downward-bid extension."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from benchmark_oracle_queries import benchmark
from engine import load_case
from postprocess_oracle import postprocess
from price_vulnerability.range_vulnerability import range_price_impact
from price_vulnerability.oracle_compression import query_compact

ROOT = Path(__file__).resolve().parent
CASES = {'6': (1, 5.9999375), '30': (0, 20.991), '118': (10, 18.165)}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, result):
    if path.exists():
        raise ValueError(f'Preserve the previous experiment: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')


def run(command, output):
    print('Starting '+output.name, flush=True)
    done = subprocess.run([sys.executable, *command], cwd=ROOT, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix('.log').write_text(done.stdout, encoding='utf-8')
    if done.returncode:
        raise RuntimeError(f'Experiment exited {done.returncode}: {done.stdout[-3000:]}')
    print(done.stdout.splitlines()[-1], flush=True)


def algorithms(root, resume=False):
    for case, (g, upper) in CASES.items():
        generators, _ = load_case(case, 'ptdf', 24, 3, 'tight')
        slopes = generators[g].pwl_slopes
        reference = slopes[len(slopes)//2] if slopes else generators[g].cost_var
        if abs(upper-.5*reference) > 1e-10:
            raise ValueError('Declared 50% range does not match the loaded reference slope')
    plan = dict(rho=[0., .5], repeats=3, checkpoint_every=0,
        cases=CASES, source_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
            'run_affine_oracle.py', 'run_region_oracle.py', 'price_vulnerability/optimality_region.py',
            'price_vulnerability/budgeted_oracle.py', 'price_vulnerability/persistent_chp.py')},
        purpose='Isolate construction costs on identical domains and archive policies. The 118 run is separate, not a profit experiment.')
    if resume:
        if read(root/'construction_plan.json')['source_sha256'] != plan['source_sha256']:
            raise ValueError('Construction sources changed; use a new study directory')
    else:
        save(root/'construction_plan.json', plan)
    rows = []
    for repeat in range(1, 4):
        # Alternate method order between repeats to avoid always giving one method a cold machine.
        methods = ['bracket', 'active_cone', 'persistent_cone']
        if repeat % 2 == 0:
            methods.reverse()
        for case in ('6', '30'):
            g, upper = CASES[case]
            for method in methods:
                folder = root/f'{case}_{method}_repeat{repeat}'
                if method == 'bracket':
                    command = ['run_affine_oracle.py', '--discover', '--complete', '--max-points', '600']
                else:
                    command = ['run_region_oracle.py', '--formulation', method, '--max-chp-solves', '300']
                if not (resume and (folder/'audit.json').exists()):
                    run(command+['--case', case, '--generator', str(g), '--upper', str(upper),
                                 '--checkpoint-every', '0', '--out-dir', str(folder)], folder)
                compression = (read(folder/'compression.json') if (folder/'compression.json').exists()
                               else postprocess(folder))
                audit = read(folder/'audit.json')
                rows.append(dict(case=case, method=method, repeat=repeat,
                    offline_seconds=audit['offline_seconds'], postprocess_seconds=compression['postprocessing_seconds'],
                    chp_solves=audit['chp_solves'], auxiliary_lps=audit.get('auxiliary_lps', 0),
                    value_intervals=compression['merged_value_intervals'],
                    price_segments=compression['selected_price_intervals'],
                    auxiliary_phase_seconds=audit.get('auxiliary_phase_seconds')))
                record = root/f'construction_{len(rows):02d}.json'
                if not (resume and record.exists()):
                    save(record, rows[-1])
    stats = []
    for case in ('6', '30'):
        for method in ('bracket', 'active_cone', 'persistent_cone'):
            selected = [r for r in rows if r['case'] == case and r['method'] == method]
            with np.load(root/f'{case}_bracket_repeat1/compact.npz') as base:
                for repeat in range(1, 4):
                    with np.load(root/f'{case}_{method}_repeat{repeat}/compact.npz') as other:
                        points = np.unique(np.r_[base['value_boundaries'], other['value_boundaries']])
                        gap = np.max(np.abs(np.interp(points, base['value_boundaries'], base['values'])
                                           -np.interp(points, other['value_boundaries'], other['values'])))
                        if gap > 1e-6:
                            raise RuntimeError('Complete value maps disagree')
            stats.append(dict(case=case, method=method,
                offline_mean_seconds=float(np.mean([r['offline_seconds'] for r in selected])),
                offline_std_seconds=float(np.std([r['offline_seconds'] for r in selected], ddof=1)),
                chp_solves=[r['chp_solves'] for r in selected], auxiliary_lps=[r['auxiliary_lps'] for r in selected],
                value_intervals=[r['value_intervals'] for r in selected], price_segments=[r['price_segments'] for r in selected]))
    save(root/'construction_summary.json', dict(rows=rows, summary=stats,
        note='Three serial cold construction repeats per case and strategy, final-only full witness archival. Compression separately timed. No presumption that expansion wins.'))


def queries(root):
    save(root/'query_plan.json', dict(seed=20261016, order='shuffled',
        workloads={'6': {'Q':[24,100], 'repeats':3, 'single_batch_Q':[1000]},
                   '30': {'Q':[24,100], 'repeats':3, 'single_batch_Q':[1000]},
                   '118': {'Q':[24], 'repeats':1}},
        benchmark_source_sha256=hashlib.sha256((ROOT/'benchmark_oracle_queries.py').read_bytes()).hexdigest()))
    rows = []
    for case in CASES:
        folder = root/(f'{case}_bracket_repeat1' if case != '118' else '118_sparse_bracket_0to50')
        workloads = ([(r, q) for r in range(1, 4) for q in (24, 100)]+[(1, 1000)]
                     if case != '118' else [(1, 24)])
        for repeat, q in workloads:
            result = benchmark(folder, q, skip_fresh=True, order='shuffled', seed=20261016)
            save(root/f'query_{case}_q{q}_repeat{repeat}.json', result)
            rows.append(dict(case=case, repeat=repeat, queries=q,
                reopt_seconds=result['same_model_reoptimization_batch_seconds'],
                oracle_seconds=result['oracle_total_with_offline_seconds']))
            print(f'{case}, Q={q}, repeat={repeat}: reopt {rows[-1]["reopt_seconds"]:.3f}s', flush=True)
    save(root/'query_summary.json', dict(rows=rows, note='6/30: three repeats at Q=24,100 and one Q=1000 batch; 118: one Q=24 scalability batch. Single batches are not variance estimates. Actual shuffled workloads; no extrapolated speedup.'))


def bidirectional(root):
    # Preserve the entire positive path including delta=0, so directional comparisons share a baseline.
    for case in ('6', '30'):
        g, upper = CASES[case]
        parent = root/f'{case}_bracket_repeat1'
        folder = root/f'{case}_bidirectional'
        run(['run_affine_oracle.py', '--discover', '--complete', '--case', case, '--generator', str(g),
             '--lower', str(-upper), '--upper', str(upper), '--max-points', '1000', '--checkpoint-every', '0',
             '--initial-map', str(parent), '--out-dir', str(folder)], folder)
        postprocess(folder)
        with np.load(folder/'compact.npz') as data:
            report = range_price_impact(data['price_boundaries'], data['prices'])
            baseline = query_compact(0., data['value_boundaries'], data['values'],
                                      data['price_boundaries'], data['prices'])[1]
            report['directional_maxima_usd_per_mwh'] = {
                name:float(np.max(np.abs(data['prices'][mask]-baseline)))
                for name, mask in (('downward', data['price_boundaries'] <= 0.),
                                   ('upward', data['price_boundaries'] >= 0.))}
        save(folder/'range_price_impact.json', report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('algorithms', 'queries', 'bidirectional'), required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--resume', action='store_true', help='Continue frozen construction runs without rerunning completed models')
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    if args.resume and args.stage != 'algorithms':
        parser.error('resume applies only to frozen construction experiments')
    if args.stage == 'algorithms':
        algorithms(args.root, args.resume)
    else:
        {'queries': queries, 'bidirectional': bidirectional}[args.stage](args.root)


if __name__ == '__main__':
    main()
