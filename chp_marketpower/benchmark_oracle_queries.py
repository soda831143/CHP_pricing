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


def _solve_fresh(generators, network, g: int, delta: float) -> tuple[float, np.ndarray]:
    from gurobi_compat import GRB

    adders = np.zeros((len(generators), network.T))
    adders[g] = delta
    solver = PrimalCHPLP(generators, network, bid_adders=adders,
                         method=1, crossover=1,
                         feasibility_tol=1e-9, optimality_tol=1e-9)
    _, value, success = solver.solve()
    if not success or solver._model.Status != GRB.OPTIMAL:
        raise RuntimeError(f"fresh CHP failed at delta={delta:g}")
    return float(value), solver.raw_nodal_price.copy()


def _reoptimize_workload(generators, network, g: int,
                         deltas: np.ndarray) -> tuple[float, list[float]]:
    import coptpy as cp
    from gurobi_compat import GRB

    first = float(deltas[0])
    adders = np.zeros((len(generators), network.T))
    adders[g] = first
    start = time.perf_counter()
    solver = PrimalCHPLP(generators, network, bid_adders=adders,
                         method=1, crossover=1,
                         feasibility_tol=1e-9, optimality_tol=1e-9)
    _, first_value, success = solver.solve()
    if not success or solver._model.Status != GRB.OPTIMAL:
        raise RuntimeError("initial reusable CHP model failed")
    model = solver._model
    direction = solver.bid_adder_direction(g)
    all_variables = model.getVars()
    changed = np.flatnonzero(direction)
    variables = [all_variables[int(k)] for k in changed]
    base = np.asarray([all_variables[int(k)].obj for k in changed]) - first * direction[changed]
    values = [float(first_value)]
    n_eq = len(solver._all_eq_duals)
    for delta in deltas[1:]:
        model.setInfo(cp.COPT.Info.Obj, variables,
                      (base + float(delta) * direction[changed]).tolist())
        model.optimize()
        if model.Status != GRB.OPTIMAL:
            raise RuntimeError(f"same-model CHP reoptimization failed at delta={delta:g}")
        values.append(float(model.objval))
        rows = model.getConstrs()
        balance = np.asarray([rows[k].pi for k in range(n_eq - network.T, n_eq)])
        if network.is_single_node:
            price = balance[np.newaxis, :]
        else:
            n_line_rows = 2 * network.N_line * network.T
            line_duals = np.asarray([rows[k].pi for k in range(len(rows) - n_line_rows,
                                                               len(rows))])
            alpha = line_duals[0::2].reshape(network.N_line, network.T)
            beta = line_duals[1::2].reshape(network.N_line, network.T)
            price = balance[np.newaxis, :] + network.PTDF.T @ (alpha - beta)
        if not np.all(np.isfinite(price)):
            raise RuntimeError("same-model reoptimization produced a nonfinite price")
    elapsed = time.perf_counter() - start
    return elapsed, values


def benchmark(oracle_dir: Path, n_queries: int, skip_fresh: bool = False) -> dict:
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
    generators, network = load_case(
        scope["case"], scope["network"], scope["T"],
        scope["segments"], scope["congestion"],
    )
    started = time.perf_counter()
    with np.load(oracle_dir / "compact.npz") as compact:
        value_boundaries, values = compact["value_boundaries"], compact["values"]
        price_boundaries, prices = compact["price_boundaries"], compact["prices"]
    load_seconds = time.perf_counter() - started
    lower, upper = float(value_boundaries[0]), float(value_boundaries[-1])
    # Fixed before any direct solve; includes all value regions without using their breakpoints.
    deltas = np.linspace(lower + 0.025 * (upper - lower),
                         upper - 0.025 * (upper - lower), n_queries)
    started = time.perf_counter()
    online_values = [query_compact(float(delta), value_boundaries, values,
                                   price_boundaries, prices)[0] for delta in deltas]
    online_seconds = time.perf_counter() - started
    direct_values = None
    fresh_seconds = None
    if not skip_fresh:
        started = time.perf_counter()
        direct_values = [_solve_fresh(generators, network, scope["generator_index"], float(delta))[0]
                         for delta in deltas]
        fresh_seconds = time.perf_counter() - started
    reopt_seconds, reopt_values = _reoptimize_workload(
        generators, network, scope["generator_index"], deltas,
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
        "scope": scope, "workload": "fixed equally spaced interior queries",
        "query_deltas": deltas.tolist(), "n_queries": n_queries,
        "max_value_discrepancy_usd": max_value_error,
        "oracle_offline_seconds_prior_run": build["offline_seconds"],
        "oracle_file_load_seconds": load_seconds,
        "oracle_online_batch_seconds": online_seconds,
        "oracle_total_with_offline_seconds": build["offline_seconds"] + load_seconds + online_seconds,
        "fresh_chp_batch_seconds": fresh_seconds,
        "fresh_chp_skipped": skip_fresh,
        "same_model_reoptimization_batch_seconds": reopt_seconds,
        "query_hit_rate": 1.0,
        "compact_file_bytes": (oracle_dir / "compact.npz").stat().st_size,
        "raw_audit_file_bytes": (oracle_dir / "oracle.npz").stat().st_size,
        "timing_scope": "Fresh and same-model timings include objective update/build and optimize; case-data load is common and excluded. Oracle load is separate; offline time came from its prior construction run.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle-dir", type=Path, required=True)
    parser.add_argument("--queries", type=int, default=12)
    parser.add_argument("--skip-fresh", action="store_true",
                        help="Measure high-Q same-model reoptimization without repeating fresh model builds")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = benchmark(args.oracle_dir, args.queries, args.skip_fresh)
    output = args.output or args.oracle_dir / f"batch_benchmark_q{args.queries}.json"
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    fresh = (f"{result['fresh_chp_batch_seconds']:.2f}s"
             if result["fresh_chp_batch_seconds"] is not None else "not run")
    print(f"Q={args.queries}: direct {fresh}; "
          f"same-model {result['same_model_reoptimization_batch_seconds']:.2f}s; "
          f"oracle construction+load+queries {result['oracle_total_with_offline_seconds']:.2f}s; "
          f"max value discrepancy {result['max_value_discrepancy_usd']:.3e} USD")


if __name__ == "__main__":
    main()
