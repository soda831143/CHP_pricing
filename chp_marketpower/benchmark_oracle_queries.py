"""Timed, fixed-workload comparison with fresh CHP and same-model reoptimization."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from engine import PrimalCHPLP, load_case
from price_vulnerability.oracle_compression import query_compact
from price_vulnerability.affine_oracle import bid_adder_matrix
from price_vulnerability.model_identity import check_model_identity


def _solve_fresh(generators, network, g: int, delta: float, *, aggregate_output=False, hour=None) -> tuple[float, np.ndarray]:
    from gurobi_compat import GRB

    adders = bid_adder_matrix(len(generators), network.T, g, delta, hour)
    solver = PrimalCHPLP(generators, network, bid_adders=adders,
                         method=1, crossover=1,
                         feasibility_tol=1e-9, optimality_tol=1e-9, use_output_vars=aggregate_output)
    _, value, success = solver.solve()
    if not success or solver._model.Status != GRB.OPTIMAL:
        raise RuntimeError(f"fresh CHP failed at delta={delta:g}")
    return float(value), solver.raw_nodal_price.copy()


def _reoptimize_workload(generators, network, g: int,
                         deltas: np.ndarray, *, aggregate_output=False,
                         cumulative_trace=None, hour=None) -> tuple[float, list[float], list[np.ndarray]]:
    import coptpy as cp
    from gurobi_compat import GRB

    first = float(deltas[0])
    adders = bid_adder_matrix(len(generators), network.T, g, first, hour)
    start = time.perf_counter()
    solver = PrimalCHPLP(generators, network, bid_adders=adders,
                         method=1, crossover=1,
                         feasibility_tol=1e-9, optimality_tol=1e-9, use_output_vars=aggregate_output)
    _, first_value, success = solver.solve()
    if not success or solver._model.Status != GRB.OPTIMAL:
        raise RuntimeError("initial reusable CHP model failed")
    model = solver._model
    direction = solver.bid_adder_direction(g, hour)
    all_variables = model.getVars()
    changed = np.flatnonzero(direction)
    variables = [all_variables[int(k)] for k in changed]
    base = np.asarray([all_variables[int(k)].obj for k in changed]) - first * direction[changed]
    values = [float(first_value)]
    prices = [solver.raw_nodal_price.copy()]
    n_eq = len(solver._all_eq_duals)
    rows = model.getConstrs()
    # Aggregate output-link equalities follow, rather than precede, the balance block.
    balance_end = n_eq-(len(generators)*network.T if aggregate_output else 0)
    balance_rows = [rows[k] for k in range(balance_end-network.T, balance_end)]
    n_line_rows = 2*network.N_line*network.T if not network.is_single_node else 0
    line_rows = [rows[k] for k in range(len(rows)-n_line_rows, len(rows))]
    if cumulative_trace is not None:
        cumulative_trace.append(time.perf_counter()-start)
    for delta in deltas[1:]:
        model.setInfo(cp.COPT.Info.Obj, variables,
                      (base + float(delta) * direction[changed]).tolist())
        model.optimize()
        if model.Status != GRB.OPTIMAL:
            raise RuntimeError(f"same-model CHP reoptimization failed at delta={delta:g}")
        values.append(float(model.objval))
        balance = np.asarray(model.getInfo(cp.COPT.Info.Dual, balance_rows))
        if network.is_single_node:
            price = balance[np.newaxis, :]
        else:
            line_duals = np.asarray(model.getInfo(cp.COPT.Info.Dual, line_rows))
            alpha = line_duals[0::2].reshape(network.N_line, network.T)
            beta = line_duals[1::2].reshape(network.N_line, network.T)
            price = balance[np.newaxis, :] + network.PTDF.T @ (alpha - beta)
        if not np.all(np.isfinite(price)):
            raise RuntimeError("same-model reoptimization produced a nonfinite price")
        prices.append(price)
        if cumulative_trace is not None:
            cumulative_trace.append(time.perf_counter()-start)
    elapsed = time.perf_counter() - start
    if cumulative_trace is not None:
        cumulative_trace[-1] = elapsed
    return elapsed, values, prices


def benchmark(oracle_dir: Path, n_queries: int, skip_fresh: bool = False,
              order: str = 'sorted', seed: int = 20261015, *, record_trace=False) -> dict:
    if n_queries < 2:
        raise ValueError("at least two predeclared queries are required")
    build = json.loads((oracle_dir / "audit.json").read_text(encoding="utf-8"))
    compact_audit = json.loads((oracle_dir / "compression.json").read_text(encoding="utf-8"))
    if build["status"] != "numerically_validated" or compact_audit["status"] != "numerically_validated_compression":
        raise ValueError("benchmark requires a fully audited compact oracle")
    if compact_audit.get("source_sha256") != hashlib.sha256(
            (oracle_dir / "oracle.npz").read_bytes()).hexdigest():
        raise ValueError("compact oracle was built from a different raw witness version")
    scope = build["scope"]
    hour = scope['bid_hour_1based']-1 if 'bid_hour_1based' in scope else None
    generators, network = load_case(
        scope["case"], scope["network"], scope["T"],
        scope["segments"], scope["congestion"],
    )
    check_model_identity(oracle_dir, generators, network, build)
    started = time.perf_counter()
    with np.load(oracle_dir / "compact.npz") as compact:
        value_boundaries, values = compact["value_boundaries"], compact["values"]
        price_boundaries, prices = compact["price_boundaries"], compact["prices"]
    load_seconds = time.perf_counter() - started
    lower, upper = float(value_boundaries[0]), float(value_boundaries[-1])
    # Fixed independently of observed breakpoints; need not sample every value region.
    deltas = np.linspace(lower + 0.025 * (upper - lower),
                         upper - 0.025 * (upper - lower), n_queries)
    if order == 'shuffled':
        deltas = np.random.default_rng(seed).permutation(deltas)
    elif order != 'sorted':
        raise ValueError('order must be sorted or shuffled')
    started = time.perf_counter()
    online_trace = []
    online_answers = []
    for delta in deltas:
        online_answers.append(query_compact(float(delta), value_boundaries, values, price_boundaries, prices))
        if record_trace:
            online_trace.append(time.perf_counter()-started)
    online_seconds = time.perf_counter() - started
    if record_trace:
        online_trace[-1] = online_seconds
    online_values = [answer[0] for answer in online_answers]
    direct_values = None
    fresh_seconds = None
    if not skip_fresh:
        started = time.perf_counter()
        direct_values = [_solve_fresh(generators, network, scope["generator_index"], float(delta),
                                      aggregate_output=scope.get('aggregate_output', False), hour=hour)[0]
                         for delta in deltas]
        fresh_seconds = time.perf_counter() - started
    reopt_trace = [] if record_trace else None
    reopt_seconds, reopt_values, reopt_prices = _reoptimize_workload(
        generators, network, scope["generator_index"], deltas,
        aggregate_output=scope.get('aggregate_output', False),
        cumulative_trace=reopt_trace,
        hour=hour,
    )
    max_value_error = float(np.max(np.abs(np.asarray(online_values) - reopt_values)))
    if direct_values is not None:
        max_value_error = max(
            max_value_error,
            float(np.max(np.abs(np.asarray(direct_values) - reopt_values))),
        )
    if max_value_error > 1e-6:
        raise RuntimeError(f"batch benchmark value discrepancy: {max_value_error:g} USD")
    return {
        "scope": scope, "workload": "fixed equally spaced interior queries", 'order': order, 'seed': seed,
        "query_deltas": deltas.tolist(), "n_queries": n_queries,
        'same_model_cumulative_seconds': reopt_trace,
        'oracle_cumulative_online_seconds': online_trace if record_trace else None,
        'trace_scope': 'Elapsed prefixes of one fixed query stream, including first-model setup and every raw price extraction; not independently restarted batches at each Q.' if record_trace else None,
        "max_value_discrepancy_usd": max_value_error,
        "oracle_offline_seconds_prior_run": build["offline_seconds"],
        'postprocessing_seconds': compact_audit.get('postprocessing_seconds', 0.),
        "oracle_file_load_seconds": load_seconds,
        "oracle_online_batch_seconds": online_seconds,
        "oracle_total_with_offline_seconds": build["offline_seconds"] + compact_audit.get('postprocessing_seconds', 0.) + load_seconds + online_seconds,
        "fresh_chp_batch_seconds": fresh_seconds,
        "fresh_chp_skipped": skip_fresh,
        "same_model_reoptimization_batch_seconds": reopt_seconds,
        "query_hit_rate": 1.0,
        "compact_file_bytes": (oracle_dir / "compact.npz").stat().st_size,
        "raw_audit_file_bytes": (oracle_dir / "oracle.npz").stat().st_size,
        'selector_vs_direct_max_price_difference': float(np.max(np.abs(
            np.stack([answer[1] for answer in online_answers])-np.stack(reopt_prices)))),
        'price_validation': 'Prices extracted at every query; different legal dual selectors need not agree. Complete-dual interpolation is independently checked per interval and at boundary neighborhoods by validate_affine_oracle.py.',
        "timing_scope": "Fresh and same-model timings include objective update/build and optimize; case-data load is common and excluded. Oracle load is separate; offline time came from its prior construction run.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle-dir", type=Path, required=True)
    parser.add_argument("--queries", type=int, default=12)
    parser.add_argument("--skip-fresh", action="store_true",
                        help="Measure high-Q same-model reoptimization without repeating fresh model builds")
    parser.add_argument("--output", type=Path)
    parser.add_argument('--order', choices=('sorted', 'shuffled'), default='shuffled')
    parser.add_argument('--seed', type=int, default=20261015)
    parser.add_argument('--record-trace', action='store_true', help='Record actual elapsed prefixes after every query for a cumulative-time curve')
    args = parser.parse_args()
    output = args.output or args.oracle_dir / f"batch_benchmark_q{args.queries}.json"
    if output.exists():
        parser.error('Use a fresh output file to preserve earlier timed results')
    result = benchmark(args.oracle_dir, args.queries, args.skip_fresh, args.order, args.seed,
                       record_trace=args.record_trace)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    fresh = (f"{result['fresh_chp_batch_seconds']:.2f}s"
             if result["fresh_chp_batch_seconds"] is not None else "not run")
    print(f"Q={args.queries}: direct {fresh}; "
          f"same-model {result['same_model_reoptimization_batch_seconds']:.2f}s; "
          f"oracle construction+load+queries {result['oracle_total_with_offline_seconds']:.2f}s; "
          f"max value discrepancy {result['max_value_discrepancy_usd']:.3e} USD")


if __name__ == "__main__":
    main()
