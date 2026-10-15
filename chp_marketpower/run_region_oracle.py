"""Build a CHP response map by fixed-primal optimality-region expansion."""
import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from engine import load_case
from price_vulnerability.affine_oracle import save_endpoints
from price_vulnerability.optimality_region import build_region_oracle
from price_vulnerability.persistent_chp import PersistentCHP


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=('6', '30'), required=True)
    parser.add_argument('--generator', type=int, required=True)
    parser.add_argument('--lower', type=float, default=0.)
    parser.add_argument('--upper', type=float, required=True)
    parser.add_argument('--max-chp-solves', type=int, default=40)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--formulation', choices=('full_dual', 'active_cone'), default='full_dual')
    args = parser.parse_args()
    if args.out_dir.exists():
        parser.error('Use a new directory; existing price-selector versions are immutable')
    if not np.isfinite([args.lower, args.upper]).all() or args.lower >= args.upper:
        parser.error('Domain must be finite and increasing')
    generators, network = load_case(args.case, 'ptdf', 24, 3, 'tight')
    chp = PersistentCHP(generators, network, args.generator)
    args.out_dir.mkdir(parents=True)
    scope = dict(case=args.case, network='ptdf', T=24, segments=3, congestion='tight',
                 generator_index=args.generator, parameter='all-day absolute adder')
    started = time.perf_counter()

    def save(points, intervals, expander, failures):
        ready = np.asarray([item.price_ready for item in intervals])
        report = dict(
            status='numerically_validated' if np.all(ready) else 'numerically_validated_partial',
            scope=scope, method='fixed-primal full-dual optimality-region expansion with gap-refinement fallback',
            endpoint_solver='persistent', solved_points=len(points), stored_points=len(points),
            region_formulation=args.formulation,
            chp_solves=chp.calls, auxiliary_lps=expander.calls, max_chp_solves=args.max_chp_solves,
            auxiliary_wall_seconds=expander.seconds, region_expansions=expander.records,
            expansion_failures=failures, value_tolerance_usd=1e-6, price_tolerance_usd=1e-6,
            intervals=[asdict(item) for item in intervals],
            price_coverage_fraction=sum(i.right-i.left for i in intervals if i.price_ready)/(args.upper-args.lower),
            offline_seconds=time.perf_counter()-started,
            persistent_timing=dict(setup_seconds=chp.setup_seconds,
                                   reoptimization_seconds=chp.reoptimization_seconds,
                                   extraction_audit_seconds=chp.audit_seconds),
            max_unresolved_value_gap_usd=max((i.max_value_gap for i in intervals if not i.price_ready), default=0.),
            max_full_lp_residuals={key:max(p.audit[key] for p in points) for key in points[0].audit},
            interpretation='Numerical KKT-validated selected prices; auxiliary equality LPs locate fixed-primal optimality regions, not symbolic exact boundaries.',
        )
        save_endpoints(args.out_dir/'oracle.pending.npz', points, ready)
        (args.out_dir/'oracle.pending.npz').replace(args.out_dir/'oracle.npz')
        (args.out_dir/'audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(f"{chp.calls} CHP + {expander.calls} auxiliary LPs; "
              f"{report['price_coverage_fraction']:.1%} coverage; {report['offline_seconds']:.2f}s", flush=True)

    points, intervals, expander, failures = build_region_oracle(
        chp, args.lower, args.upper, max_chp_solves=args.max_chp_solves, on_update=save,
        formulation=args.formulation)
    if not all(item.price_ready for item in intervals):
        raise SystemExit('price coverage incomplete at the CHP-solve budget; partial archive preserved')


if __name__ == '__main__':
    main()
