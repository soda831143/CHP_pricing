"""Independent direct-CHP and complete interpolated-dual validation of a saved oracle."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from engine import PrimalCHPLP, load_case
from price_vulnerability.affine_oracle import audited_solution, dual_audit_passed, query, bid_adder_matrix
from price_vulnerability.model_identity import check_model_identity


def validate_point(generators, network, generator_index, delta, k, data, persistent=None, *, aggregate_output=False, hour=None):
    from gurobi_compat import GRB

    boundaries = data["boundaries"]
    theta = (delta - boundaries[k]) / (boundaries[k + 1] - boundaries[k])
    blend = lambda key: (1 - theta) * data[key][k] + theta * data[key][k + 1]
    predicted_value, selected_price = query(
        delta, boundaries, data["values"], data["prices"]
    )
    if persistent is None:
        adders = bid_adder_matrix(len(generators), network.T, generator_index, delta, hour)
        solver = PrimalCHPLP(
            generators, network, bid_adders=adders, method=1, crossover=1,
            feasibility_tol=1e-9, optimality_tol=1e-9, use_output_vars=aggregate_output,
        )
        _, direct_value, success = solver.solve()
        if not success or solver._model.Status != GRB.OPTIMAL:
            raise RuntimeError(f"direct CHP did not reach OPTIMAL at {delta:g}")
        direct = audited_solution(solver, generator_index, delta, direct_value, hour=hour)
    else:
        direct = persistent.solve(delta)
        direct_value, solver = direct.value, persistent.solver
    if not dual_audit_passed(direct):
        raise RuntimeError(f"direct CHP complete-dual audit failed at {delta:g}: {direct.audit}")
    eq, rhs_eq, n_flow, n_src, _ = solver._build_eq_constraints(solver._idx)
    ineq, rhs_ineq = solver._build_ineq_constraints(solver._idx)
    pi, mu = blend("eq_duals"), blend("ineq_duals")
    z_lower, z_upper = blend("lower_duals"), blend("upper_duals")
    variables = solver._model.getVars()
    from coptpy import COPT
    c, lb, ub = (np.asarray(solver._model.getInfo(info, variables))
                 for info in (COPT.Info.Obj, COPT.Info.LB, COPT.Info.UB))
    x = solver._solution_x
    finite_lb = np.isfinite(lb) & (lb > -1e20)
    finite_ub = np.isfinite(ub) & (ub < 1e20)
    dual_value = (
        rhs_eq @ pi + rhs_ineq @ mu
        + lb[finite_lb] @ z_lower[finite_lb]
        + ub[finite_ub] @ z_upper[finite_ub]
    )
    balance = pi[n_flow + n_src:n_flow + n_src + network.T]
    if network.is_single_node:
        projected_price = balance[np.newaxis, :]
    else:
        lines = mu[-2 * network.N_line * network.T:]
        alpha = lines[0::2].reshape(network.N_line, network.T)
        beta = lines[1::2].reshape(network.N_line, network.T)
        projected_price = balance[np.newaxis, :] + network.PTDF.T @ (alpha - beta)
    return {
        "interval": k + 1, "delta": delta,
        "value_error_usd": float(abs(predicted_value - direct_value)),
        "selector_dual_gap_usd": float(abs(dual_value - direct_value)),
        "selector_stationarity": float(np.max(np.abs(
            c - eq.T @ pi - ineq.T @ mu - z_lower - z_upper
        ))),
        "selector_dual_sign": float(max(
            np.max(mu, initial=0.0), -np.min(z_lower, initial=0.0),
            np.max(z_upper, initial=0.0), 0.0,
        )),
        "selector_complementarity": float(max(
            np.max(np.abs(mu * (rhs_ineq - ineq @ x)), initial=0.0),
            np.max(np.abs(z_lower[finite_lb] * (x[finite_lb] - lb[finite_lb])), initial=0.0),
            np.max(np.abs(z_upper[finite_ub] * (ub[finite_ub] - x[finite_ub])), initial=0.0),
        )),
        "selector_price_projection": float(np.max(np.abs(projected_price - selected_price))),
        "selector_vs_direct_price_gap_usd_per_mwh": float(np.max(np.abs(
            selected_price - solver.raw_nodal_price
        ))),
        "direct_complete_dual_gap_usd": direct.audit["duality_gap"],
        "direct_complete_dual_stationarity": direct.audit["stationarity"],
        "direct_chp_seconds": solver.total_time,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle-dir", type=Path, required=True)
    parser.add_argument("--fractions", type=float, nargs="*", default=[0.5],
                        help='Interior fractions per interval; empty allows explicit extra-deltas only')
    parser.add_argument("--extra-deltas", type=float, nargs="*", default=[])
    parser.add_argument('--persistent-direct', action='store_true',
                        help='Use a separately built persistent LP for independent validation queries')
    args = parser.parse_args()
    if not args.fractions and not args.extra_deltas:
        raise ValueError('Supply at least one interior fraction or independent delta')
    if any(not 0 < fraction < 1 for fraction in args.fractions):
        raise ValueError("validation fractions must lie strictly inside an interval")
    report = json.loads((args.oracle_dir / "audit.json").read_text(encoding="utf-8"))
    if not report["status"].startswith("numerically_validated"):
        raise ValueError("oracle was not numerically validated at build time")
    scope = report["scope"]
    generators, network = load_case(
        scope["case"], scope["network"], scope["T"],
        scope["segments"], scope["congestion"],
    )
    check_model_identity(args.oracle_dir, generators, network, report)
    from price_vulnerability.persistent_chp import PersistentCHP
    aggregate_output = scope.get('aggregate_output', False)
    hour = scope['bid_hour_1based']-1 if 'bid_hour_1based' in scope else None
    persistent = PersistentCHP(generators, network, scope['generator_index'],
                               aggregate_output=aggregate_output, hour=hour) if args.persistent_direct else None
    with np.load(args.oracle_dir / "oracle.npz") as archive:
        # NPZ access decompresses a whole array; load each witness block once, not per query.
        data = {key:archive[key] for key in ('boundaries', 'values', 'prices', 'eq_duals',
                                            'ineq_duals', 'lower_duals', 'upper_duals')}
        if 'price_ready' in archive:
            data['price_ready'] = archive['price_ready']
        boundaries = data["boundaries"]
        ready = data["price_ready"] if "price_ready" in data else np.ones(len(boundaries) - 1, bool)
        checks = [
            validate_point(
                generators, network, scope["generator_index"],
                float(boundaries[k] + fraction * (boundaries[k + 1] - boundaries[k])),
                k, data, persistent, aggregate_output=aggregate_output, hour=hour,
            )
            for k in range(len(ready)) if ready[k]
            for fraction in args.fractions
        ]
        for delta in args.extra_deltas:
            if not np.isfinite(delta) or not boundaries[0] < delta < boundaries[-1]:
                raise ValueError("extra validation delta is outside the oracle interior")
            k = int(np.searchsorted(boundaries, delta, side="right")) - 1
            if not ready[k]:
                raise ValueError("extra validation delta lies in an uncovered interval")
            checks.append(validate_point(
                generators, network, scope["generator_index"], delta, k, data, persistent,
                aggregate_output=aggregate_output, hour=hour,
            ))
        samples = [float(0.5 * (boundaries[k] + boundaries[k + 1]))
                   for k in range(len(ready)) if ready[k]]
        if not samples:
            raise RuntimeError("no price-ready intervals to validate")
        values, prices = data["values"], data["prices"]
        started = time.perf_counter()
        for _ in range(1000):
            for delta in samples:
                query(delta, boundaries, values, prices)
        online_mean = (time.perf_counter() - started) / (1000 * len(samples))
    limits = {"value_error_usd": 1e-6, "selector_dual_gap_usd": 1e-6,
              "selector_stationarity": 1e-7, "selector_dual_sign": 1e-7,
              "selector_complementarity": 1e-6,
              "selector_price_projection": 1e-9,
              "direct_complete_dual_gap_usd": 1e-6,
              "direct_complete_dual_stationarity": 1e-7}
    passed = all(item[key] <= limit for item in checks for key, limit in limits.items())
    direct_mean = float(np.mean([item["direct_chp_seconds"] for item in checks]))
    full_coverage = bool(np.all(ready))
    result = {
        "status": "passed" if passed else "failed", "scope": scope,
        'validation_sampling': dict(fractions=args.fractions, extra_deltas=args.extra_deltas),
        'validation_solver': 'independently rebuilt persistent CHP' if persistent else 'independent fresh CHP per point',
        "direct_checks": checks,
        "maximums": {key: max(item[key] for item in checks) for key in checks[0]
                     if key not in {"interval", "delta"}},
        "online_mean_seconds_loaded": online_mean,
        "direct_mean_seconds_independent": direct_mean,
        "full_price_coverage": full_coverage,
        "saved_oracle_bytes": (args.oracle_dir / "oracle.npz").stat().st_size,
        'performance_evidence': 'Use measured fixed-workload batches; validation-point timings do not estimate a break-even threshold.',
        "price_gap_interpretation": "Direct simplex and the valid affine dual selector may differ under dual nonuniqueness.",
    }
    (args.oracle_dir / "validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"{len(checks)} direct checks; status {result['status']}; "
          f"max selector dual gap {result['maximums']['selector_dual_gap_usd']:.3e} USD; "
          f"max price-selection gap {result['maximums']['selector_vs_direct_price_gap_usd_per_mwh']:.3g} USD/MWh")
    if not passed:
        raise SystemExit("interpolated complete-dual validation failed")


if __name__ == "__main__":
    main()
