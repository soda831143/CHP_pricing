"""Targeted numerical-stability diagnostic for the CHP pricing algorithms.

This script deliberately separates algorithmic numerical stability from
economic sensitivity.  Every perturbed data vector defines a *new* UC/CHP
instance.  On that same instance, default D-CHP and DWP are compared with a
strict direct-LP/DWP agreement check.  No nominal-relative market outcome is
used as an algorithm-error metric.

The script is independent of the production solvers: it only instantiates
their public constructors and reads their recorded diagnostics.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from benchmarks.comparison_runner import (
    compute_ftr_from_lp_duals,
    compute_milp_line_flows,
    timed_uplift_under_prices,
)
from benchmarks.dantzig_wolfe_pricing import DantzigWolfePricing
from chp_solver.chp_master_lp import PrimalCHPLP
from chp_solver.schedule_run import ScheduleRunMILP
from scripts.run_tps_numerical_stability import perturb_instance, rolling_initial_conditions


REFERENCE_REL_TOL = 1e-7


def _finite_or_blank(value: Any) -> float | str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return ""
    return value if math.isfinite(value) else ""


def _quality(model: Any, attribute: str) -> float | str:
    """Return an available Gurobi quality attribute without assuming a method."""
    try:
        return _finite_or_blank(getattr(model, attribute))
    except Exception:  # Attribute may be unavailable, e.g., KappaExact after barrier.
        return ""


def _relative_error(value: float, reference: float) -> float:
    return abs(float(value) - float(reference)) / max(1.0, abs(float(reference)))


def _settlement(gens, network, p_schedule, u_schedule, lmp, alpha, beta) -> dict[str, float]:
    unit = timed_uplift_under_prices(gens, network, p_schedule, u_schedule, lmp)
    flows = compute_milp_line_flows(network, p_schedule)
    _, ftr = compute_ftr_from_lp_duals(alpha, beta, flows, network.F_max)
    return {
        "gen_uplift": float(unit["gen_uplift"]),
        "ftr_component": float(ftr),
        "total_uplift": float(unit["gen_uplift"] + ftr),
        "response_time": float(unit["oracle_time"]),
    }


def _direct_result(name: str, solver: PrimalCHPLP, gens, network, p_schedule, u_schedule) -> dict[str, Any]:
    lmp, objective, ok = solver.solve()
    settlement = _settlement(
        gens,
        network,
        p_schedule,
        u_schedule,
        lmp,
        solver._ptdf_alpha,
        solver._ptdf_beta_,
    )
    model = solver._model
    return {
        "method": name,
        "status": "optimal" if ok else f"status_{getattr(model, 'Status', 'unknown')}",
        "converged": bool(ok),
        "objective": float(objective),
        "total_uplift": settlement["total_uplift"],
        "gen_uplift": settlement["gen_uplift"],
        "ftr_component": settlement["ftr_component"],
        "build_time": _finite_or_blank(solver.build_time),
        "pricing_time": _finite_or_blank(solver.solver_time),
        "response_time": settlement["response_time"],
        "end_to_end_time": _finite_or_blank(solver.total_time + settlement["response_time"]),
        "primal_violation": _quality(model, "ConstrVio"),
        "dual_violation": _quality(model, "DualVio"),
        "bound_violation": _quality(model, "BoundVio"),
        "kappa_exact": _quality(model, "KappaExact"),
        "n_iterations": _finite_or_blank(getattr(model, "IterCount", "")),
        "n_columns": "",
        "dwp_min_reduced_cost": "",
        "dwp_rmp_gap_bound": "",
        "dwp_stop_reason": "",
    }


def _dwp_result(name: str, solver: DantzigWolfePricing, gens, network, p_schedule, u_schedule) -> dict[str, Any]:
    lmp, objective, ok = solver.solve()
    settlement = _settlement(
        gens,
        network,
        p_schedule,
        u_schedule,
        lmp,
        solver._ptdf_alpha,
        solver._ptdf_beta_,
    )
    last = solver.history[-1] if solver.history else {}
    return {
        "method": name,
        "status": "optimal" if ok and solver.converged else solver.stop_reason,
        "converged": bool(ok and solver.converged),
        "objective": float(objective),
        "total_uplift": settlement["total_uplift"],
        "gen_uplift": settlement["gen_uplift"],
        "ftr_component": settlement["ftr_component"],
        "build_time": _finite_or_blank(solver.build_time),
        "pricing_time": _finite_or_blank(solver.solver_time),
        "response_time": settlement["response_time"],
        "end_to_end_time": _finite_or_blank(solver.total_time + settlement["response_time"]),
        "primal_violation": "",
        "dual_violation": "",
        "bound_violation": "",
        "kappa_exact": "",
        "n_iterations": int(solver.n_iter),
        "n_columns": int(solver.n_columns),
        "dwp_min_reduced_cost": _finite_or_blank(last.get("min_reduced_cost", "")),
        "dwp_rmp_gap_bound": _finite_or_blank(last.get("rmp_gap_bound", "")),
        "dwp_stop_reason": solver.stop_reason,
    }


def _run_one(delta: float, seed: int) -> list[dict[str, Any]]:
    gens, network = perturb_instance(delta, seed, family="joint")
    gens = rolling_initial_conditions(gens, network)
    p_schedule, u_schedule, milp_objective = ScheduleRunMILP(gens, network).solve()

    direct_default = _direct_result(
        "D-CHP default",
        PrimalCHPLP(gens, network, use_output_vars=True),
        gens, network, p_schedule, u_schedule,
    )
    direct_strict = _direct_result(
        "D-CHP strict",
        PrimalCHPLP(
            gens,
            network,
            method=1,
            crossover=0,
            feasibility_tol=1e-9,
            optimality_tol=1e-9,
            use_output_vars=True,
        ),
        gens, network, p_schedule, u_schedule,
    )
    dwp_default = _dwp_result(
        "DWP default",
        DantzigWolfePricing(gens, network, p_schedule, u_schedule, tol=1e-6),
        gens, network, p_schedule, u_schedule,
    )
    dwp_strict = _dwp_result(
        "DWP strict",
        DantzigWolfePricing(gens, network, p_schedule, u_schedule, tol=1e-8),
        gens, network, p_schedule, u_schedule,
    )

    reference_accepted = (
        direct_strict["converged"]
        and dwp_strict["converged"]
        and _relative_error(dwp_strict["objective"], direct_strict["objective"]) <= REFERENCE_REL_TOL
        and _relative_error(dwp_strict["total_uplift"], direct_strict["total_uplift"]) <= REFERENCE_REL_TOL
    )

    rows: list[dict[str, Any]] = []
    for result in (direct_default, direct_strict, dwp_default, dwp_strict):
        result.update(
            {
                "delta": delta,
                "seed": seed,
                "milp_objective": float(milp_objective),
                "reference_method": "D-CHP strict",
                "reference_objective": direct_strict["objective"],
                "reference_total_uplift": direct_strict["total_uplift"],
                "reference_accepted": reference_accepted,
                "objective_relative_error": _relative_error(result["objective"], direct_strict["objective"]),
                "uplift_relative_error": _relative_error(result["total_uplift"], direct_strict["total_uplift"]),
            }
        )
        rows.append(result)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default="results/tps_revision_validation/algorithm_stability_diagnostic_30bus.csv",
    )
    parser.add_argument("--deltas", nargs="+", type=float, default=[1e-6, 1e-4, 1e-3])
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    for delta in args.deltas:
        for seed in args.seeds:
            print(f"algorithm-stability diagnostic: delta={delta:g}, seed={seed}", flush=True)
            try:
                rows.extend(_run_one(delta, seed))
            except Exception as exc:
                rows.append(
                    {
                        "delta": delta,
                        "seed": seed,
                        "method": "all",
                        "status": f"failed: {type(exc).__name__}",
                        "error": str(exc),
                    }
                )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with out.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    main()
