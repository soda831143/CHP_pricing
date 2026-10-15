"""Independent direct-CHP and complete interpolated-dual validation of a saved oracle."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from engine import PrimalCHPLP, load_case
from price_vulnerability.affine_oracle import audited_solution, dual_audit_passed, query


def validate_point(generators, network, generator_index, delta, k, data):
    from gurobi_compat import GRB

    boundaries = data["boundaries"]
    theta = (delta - boundaries[k]) / (boundaries[k + 1] - boundaries[k])
    blend = lambda key: (1 - theta) * data[key][k] + theta * data[key][k + 1]
    predicted_value, selected_price = query(
        delta, boundaries, data["values"], data["prices"]
    )
    adders = np.zeros((len(generators), network.T))
    adders[generator_index] = delta
    solver = PrimalCHPLP(
        generators, network, bid_adders=adders, method=1, crossover=1,
        feasibility_tol=1e-9, optimality_tol=1e-9,
    )
    _, direct_value, success = solver.solve()
    if not success or solver._model.Status != GRB.OPTIMAL:
        raise RuntimeError(f"direct CHP did not reach OPTIMAL at {delta:g}")
    direct = audited_solution(solver, generator_index, delta, direct_value)
    if not dual_audit_passed(direct):
        raise RuntimeError(f"direct CHP complete-dual audit failed at {delta:g}: {direct.audit}")
    eq, rhs_eq, n_flow, n_src, _ = solver._build_eq_constraints(solver._idx)
    ineq, rhs_ineq = solver._build_ineq_constraints(solver._idx)
    pi, mu = blend("eq_duals"), blend("ineq_duals")
    z_lower, z_upper = blend("lower_duals"), blend("upper_duals")
    variables = solver._model.getVars()
    c = np.asarray([variable.obj for variable in variables])
    lb = np.asarray([variable.lb for variable in variables])
    ub = np.asarray([variable.ub for variable in variables])
    x = solver._solution_x
    finite_lb = np.isfinite(lb) & (lb > -1e20)
    finite_ub = np.isfinite(ub) & (ub < 1e20)
    dual_value = (
        rhs_eq @ pi + rhs_ineq @ mu
        + lb[finite_lb] @ z_lower[finite_lb]
        + ub[finite_ub] @ z_upper[finite_ub]
    )
    balance = pi[n_flow + n_src:]
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
    parser.add_argument("--fractions", type=float, nargs="+", default=[0.5])
    parser.add_argument("--extra-deltas", type=float, nargs="*", default=[])
    args = parser.parse_args()
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
    with np.load(args.oracle_dir / "oracle.npz") as data:
        boundaries = data["boundaries"]
        ready = data["price_ready"] if "price_ready" in data else np.ones(len(boundaries) - 1, bool)
        checks = [
            validate_point(
                generators, network, scope["generator_index"],
                float(boundaries[k] + fraction * (boundaries[k + 1] - boundaries[k])),
                k, data,
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
                generators, network, scope["generator_index"], delta, k, data,
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
        "direct_checks": checks,
        "maximums": {key: max(item[key] for item in checks) for key in checks[0]
                     if key not in {"interval", "delta"}},
        "online_mean_seconds_loaded": online_mean,
        "direct_mean_seconds_independent": direct_mean,
        "full_price_coverage": full_coverage,
        "saved_oracle_bytes": (args.oracle_dir / "oracle.npz").stat().st_size,
        "break_even_queries_estimate": (
            report["offline_seconds"] / (direct_mean - online_mean)
            if full_coverage and direct_mean > online_mean else None
        ),
        "batch_total_seconds_estimate": {
            str(q): {"direct": q * direct_mean,
                     "oracle": report["offline_seconds"] + q * online_mean}
            for q in (10, 100, 1000)
        } if full_coverage else None,
        "price_gap_interpretation": "Direct simplex and the valid affine dual selector may differ under dual nonuniqueness.",
    }
    (args.oracle_dir / "validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"{len(checks)} direct checks; status {result['status']}; "
          f"max selector dual gap {result['maximums']['selector_dual_gap_usd']:.3e} USD; "
          f"max price-selection gap {result['maximums']['selector_vs_direct_price_gap_usd_per_mwh']:.3g} USD/MWh; "
          f"estimated break-even {result['break_even_queries_estimate']}")
    if not passed:
        raise SystemExit("interpolated complete-dual validation failed")


if __name__ == "__main__":
    main()
