"""Audit COPT basis degeneracy and price selection before exact continuation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from engine import PrimalCHPLP, load_case


METHODS = (("simplex", 1, 1), ("barrier_crossover", 2, 1))


def _basis_summary(solver: PrimalCHPLP, tolerance: float) -> dict:
    import coptpy as cp

    variables = solver._model.getVars()
    basis = np.asarray(solver._model.getVarBasis(), dtype=int).reshape(-1)
    reduced_cost = np.asarray([variable.rc for variable in variables], dtype=float)
    value = np.asarray([variable.x for variable in variables], dtype=float)
    lower = np.asarray([variable.lb for variable in variables], dtype=float)
    upper = np.asarray([variable.ub for variable in variables], dtype=float)

    labels = {
        cp.COPT.BASIS_LOWER: "lower",
        cp.COPT.BASIS_BASIC: "basic",
        cp.COPT.BASIS_UPPER: "upper",
        cp.COPT.BASIS_SUPERBASIC: "superbasic",
        cp.COPT.BASIS_FIXED: "fixed",
    }
    counts = {label: int(np.sum(basis == code)) for code, label in labels.items()}
    zero_nonbasic = (basis != cp.COPT.BASIS_BASIC) & (np.abs(reduced_cost) <= tolerance)

    # Bound-status signs for a minimization LP. Fixed variables are excluded:
    # their two bound multipliers need not identify a unique reduced-cost sign.
    lower_violation = np.maximum(-reduced_cost[basis == cp.COPT.BASIS_LOWER], 0.0)
    upper_violation = np.maximum(reduced_cost[basis == cp.COPT.BASIS_UPPER], 0.0)
    superbasic_violation = np.abs(reduced_cost[basis == cp.COPT.BASIS_SUPERBASIC])
    violations = np.concatenate((lower_violation, upper_violation, superbasic_violation))

    finite_lower = lower > -1e20
    finite_upper = upper < 1e20
    basic = basis == cp.COPT.BASIS_BASIC
    basic_at_bound = basic & (
        (finite_lower & (np.abs(value - lower) <= tolerance))
        | (finite_upper & (np.abs(value - upper) <= tolerance))
    )

    return {
        "basis_counts": counts,
        "zero_reduced_cost_nonbasic_count": int(np.sum(zero_nonbasic)),
        "zero_reduced_cost_nonbasic_by_status": {
            label: int(np.sum(zero_nonbasic & (basis == code)))
            for code, label in labels.items()
            if code != cp.COPT.BASIS_BASIC
        },
        "basic_at_bound_count": int(np.sum(basic_at_bound)),
        "reduced_cost_sign_violation_count": int(np.sum(violations > tolerance)),
        "max_reduced_cost_sign_violation": float(np.max(violations, initial=0.0)),
        "warning": (
            "Zero reduced-cost nonbasic variables or basic variables at bounds show "
            "degeneracy/alternative-basis risk; they do not alone prove dual nonuniqueness."
        ),
    }


def audit(generators, network, generator_index: int, deltas, tolerance: float) -> dict:
    if not 0 <= generator_index < len(generators):
        raise IndexError(f"generator_index out of range: {generator_index}")
    if tolerance <= 0 or not np.isfinite(tolerance):
        raise ValueError("tolerance must be finite and positive")

    deltas = np.asarray(deltas, dtype=float)
    if (
        deltas.ndim != 1
        or not len(deltas)
        or np.any(~np.isfinite(deltas))
        or len(np.unique(deltas)) != len(deltas)
    ):
        raise ValueError("deltas must be a nonempty sequence of distinct finite values")

    records = []
    for delta in deltas:
        adders = np.zeros((len(generators), network.T))
        adders[generator_index] = delta
        for method_name, method, crossover in METHODS:
            solver = PrimalCHPLP(
                generators,
                network,
                bid_adders=adders,
                method=method,
                crossover=crossover,
            )
            _, objective, success = solver.solve()
            from gurobi_compat import GRB
            if not success or solver._model.Status != GRB.OPTIMAL:
                raise RuntimeError(f"CHP did not reach OPTIMAL at delta={delta:g}, method={method_name}")
            records.append({
                "delta": float(delta),
                "method": method_name,
                "objective": float(objective),
                "lmp": solver.raw_nodal_price.tolist(),
                **_basis_summary(solver, tolerance),
            })

    comparisons = []
    for delta in deltas:
        pair = [record for record in records if record["delta"] == float(delta)]
        comparisons.append({
            "delta": float(delta),
            "max_abs_lmp_method_gap": float(np.max(np.abs(
                np.asarray(pair[0]["lmp"]) - np.asarray(pair[1]["lmp"])
            ))),
            "abs_objective_method_gap": abs(pair[0]["objective"] - pair[1]["objective"]),
        })
    return {
        "generator_index": generator_index,
        "tolerance": tolerance,
        "records": records,
        "method_comparisons": comparisons,
        "interpretation": (
            "Method agreement is a necessary numerical check, not a proof of dual uniqueness. "
            "If prices differ materially, exact price continuation requires an explicit selection rule."
        ),
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("6", "30"), default="6")
    parser.add_argument("--network", choices=("single", "ptdf"), default="ptdf")
    parser.add_argument("--congestion", choices=("tight", "moderate", "relaxed"), default="tight")
    parser.add_argument("--T", type=int, default=24)
    parser.add_argument("--segments", type=int, choices=(1, 3), default=3)
    parser.add_argument("--generator", type=int, required=True, help="0-based generator index")
    parser.add_argument("--deltas", type=float, nargs="+", default=[0.0, 0.04, 0.06, 0.10])
    parser.add_argument("--tolerance", type=float, default=1e-8)
    parser.add_argument("--out", type=Path, default=Path("results/basis_dual_audit.json"))
    return parser.parse_args()


def main() -> None:
    args = _arguments()
    generators, network = load_case(
        args.case, args.network, args.T, args.segments, args.congestion
    )
    result = audit(generators, network, args.generator, args.deltas, args.tolerance)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    for comparison in result["method_comparisons"]:
        print(
            f"delta={comparison['delta']:g}: "
            f"max price gap={comparison['max_abs_lmp_method_gap']:.3e}, "
            f"objective gap={comparison['abs_objective_method_gap']:.3e}"
        )
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
