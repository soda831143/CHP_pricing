"""Numerical-stability validation for the 30-bus TPS revision.

This is a coefficient-sensitivity experiment, not a robust-optimization
model.  Each perturbed instance regenerates its 48-hour rolling initial state
before the day-2 schedule and price calculations.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from benchmarks.comparison_runner import run_comparison
from chp_solver.chp_master_lp import PrimalCHPLP
from chp_solver.schedule_run import ScheduleRunMILP
from models.network import PTDFNetwork
from run_experiments import (
    _build_two_day_warmup_network,
    _extract_initial_conditions,
    apply_initial_conditions,
    load_case,
)


def _positive_scale(rng: np.random.Generator, delta: float, size=None):
    return 1.0 + rng.uniform(-delta, delta, size=size)


def perturb_instance(delta: float, seed: int, family: str = "joint"):
    """Return a physically valid 30-bus instance with a controlled perturbation.

    ``family='joint'`` perturbs all input families simultaneously and is used
    to test the complete workflow against small, distributed data errors.
    The four single-family modes are deliberately separate: they permit an
    economically interpretable sensitivity comparison without changing either
    the production pricing solver or the underlying test system.
    """
    if family not in {"joint", "ramping", "cost", "demand", "line_limit"}:
        raise ValueError(f"Unsupported perturbation family: {family}")
    gens, network = load_case("30", "ptdf", 24, 3, congestion="tight", fmax_scale=1.0)
    rng = np.random.default_rng(seed)
    perturbed_gens = []
    for g in gens:
        # Keep the pre-existing joint-perturbation draw sequence unchanged so
        # its archived CSV remains reproducible.  Single-family experiments
        # use the analogous, independently sampled scales only for that family.
        if family == "joint":
            marginal_scale = float(_positive_scale(rng, delta))
            fixed_scale = float(_positive_scale(rng, delta))
            ru_scale = float(_positive_scale(rng, delta))
            rd_scale = float(_positive_scale(rng, delta))
            su_scale = float(_positive_scale(rng, delta))
            sd_scale = float(_positive_scale(rng, delta))
        elif family == "ramping":
            marginal_scale = fixed_scale = 1.0
            ru_scale = float(_positive_scale(rng, delta))
            rd_scale = float(_positive_scale(rng, delta))
            su_scale = float(_positive_scale(rng, delta))
            sd_scale = float(_positive_scale(rng, delta))
        elif family == "cost":
            marginal_scale = float(_positive_scale(rng, delta))
            fixed_scale = float(_positive_scale(rng, delta))
            ru_scale = rd_scale = su_scale = sd_scale = 1.0
        else:
            marginal_scale = fixed_scale = 1.0
            ru_scale = rd_scale = su_scale = sd_scale = 1.0
        perturbed_gens.append(
            replace(
                g,
                R_up=max(1e-6, g.R_up * ru_scale),
                R_down=max(1e-6, g.R_down * rd_scale),
                SU_ramp=max(g.P_min, g.SU_ramp * su_scale),
                SD_ramp=max(g.P_min, g.SD_ramp * sd_scale),
                cost_var=g.cost_var * marginal_scale,
                pwl_slopes=[s * marginal_scale for s in g.pwl_slopes],
                cost_nl=g.cost_nl * fixed_scale,
                cost_su=g.cost_su * fixed_scale,
                cost_sd=g.cost_sd * fixed_scale,
            )
        )

    # One multiplier per time period preserves the spatial demand pattern and
    # changes only the daily load profile at the intended small magnitude.
    demand_scale = (
        _positive_scale(rng, delta, size=network.T)
        if family in {"joint", "demand"}
        else np.ones(network.T)
    )
    demand = np.asarray(network.demand, dtype=float) * demand_scale.reshape(1, -1)
    line_scale = (
        _positive_scale(rng, delta, size=network.N_line)
        if family in {"joint", "line_limit"}
        else np.ones(network.N_line)
    )
    fmax = np.maximum(1e-6, np.asarray(network.F_max, dtype=float) * line_scale)
    perturbed_network = PTDFNetwork(
        demand_matrix=demand,
        PTDF=network.PTDF,
        F_max=fmax,
        gen_bus_map=[network.gen_bus_idx(i) for i in range(len(perturbed_gens))],
        PTDF_Gen=network.PTDF_Gen,
    )
    return perturbed_gens, perturbed_network


def rolling_initial_conditions(gens, network):
    warm_gens = [replace(g, T=48) for g in gens]
    warm_network = _build_two_day_warmup_network(network, warmup_load_factor=0.98)
    p_warm, u_warm, _ = ScheduleRunMILP(warm_gens, warm_network).solve()
    u0, p0, on_time, off_time = _extract_initial_conditions(p_warm, u_warm, end_t=23)
    return apply_initial_conditions(gens, u0, p0, on_time, off_time)


def _round_row(kind: str, delta: float, seed: int, method: str, result: dict, chp: PrimalCHPLP | None = None, **extra):
    row = {
        "experiment": kind,
        "delta": delta,
        "seed": seed,
        "method": method,
        "status": "optimal",
        "pricing_obj": result.get("pricing_obj", ""),
        "total_uplift": result.get("total_uplift", ""),
        "gen_uplift": result.get("gen_uplift", ""),
        "ftr_component": result.get("ftr_cost", ""),
        "build_time": result.get("build_time", ""),
        "pricing_time": result.get("pricing_time", ""),
        "response_time": result.get("response_time", ""),
        "end_to_end_time": result.get("total_time", ""),
        "n_variables": chp.n_variables if chp is not None else "",
        "n_constraints": chp.n_constraints if chp is not None else "",
        "n_nonzeros": chp.n_nonzeros if chp is not None else "",
        "primal_violation": chp.primal_violation if chp is not None else "",
    }
    row.update(extra)
    return row


def run_perturbations(rows: list[dict], deltas, seeds, benchmarks) -> None:
    for delta in deltas:
        for seed in seeds:
            try:
                print(f"coefficient perturbation: delta={delta:g}, seed={seed}", flush=True)
                gens, network = perturb_instance(delta, seed, family="joint")
                gens = rolling_initial_conditions(gens, network)
                p_schedule, u_schedule, milp_obj = ScheduleRunMILP(gens, network).solve()
                chp = PrimalCHPLP(gens, network, use_output_vars=True)
                lmp, obj, ok = chp.solve()
                if not ok:
                    raise RuntimeError("D-CHP pricing LP did not reach an optimal status")
                results = run_comparison(
                    generators=gens,
                    network=network,
                    p_dispatch=p_schedule,
                    u_dispatch=u_schedule,
                    milp_obj=milp_obj,
                    chp_lp_obj=obj,
                    chp_lmp_matrix=lmp,
                    chp_uplifts=[],
                    chp_ptdf_alpha=chp._ptdf_alpha,
                    chp_ptdf_beta_=chp._ptdf_beta_,
                    methods=benchmarks,
                    lr_max_iter=500,
                    chp_solve_time=chp.total_time,
                    chp_build_time=chp.build_time,
                    chp_solver_time=chp.solver_time,
                )
                for method, result in results.items():
                    rows.append(_round_row(
                        "coefficient_perturbation", delta, seed, method,
                        result, chp if method == "chp" else None,
                        milp_obj=milp_obj, parameter_family="joint",
                    ))
                print(f"  completed: delta={delta:g}, seed={seed}", flush=True)
            except Exception as exc:  # data infeasibility is recorded, never hidden
                rows.append({
                    "experiment": "coefficient_perturbation",
                    "delta": delta,
                    "seed": seed,
                    "method": "all",
                    "status": f"failed: {type(exc).__name__}",
                    "message": str(exc),
                })


def _nominal_schedule():
    """Build the rolling-horizon nominal commitment used only for comparison."""
    gens, network = load_case("30", "ptdf", 24, 3, congestion="tight", fmax_scale=1.0)
    gens = rolling_initial_conditions(gens, network)
    _, u_schedule, _ = ScheduleRunMILP(gens, network).solve()
    return u_schedule


def run_family_sensitivity(rows: list[dict], deltas, seeds, benchmarks) -> None:
    """Run one-input-family-at-a-time 30-bus sensitivity experiments.

    The schedule-change ratio is a descriptive economic response, not a
    numerical-error metric.  A commitment switch under a data perturbation is
    expected near a nonconvex UC decision boundary and is therefore kept
    separate from exact-method agreement and solver status.
    """
    nominal_u = _nominal_schedule()
    for family in ("ramping", "cost", "demand", "line_limit"):
        for delta in deltas:
            for seed in seeds:
                try:
                    print(
                        f"family sensitivity: family={family}, delta={delta:g}, seed={seed}",
                        flush=True,
                    )
                    gens, network = perturb_instance(delta, seed, family=family)
                    gens = rolling_initial_conditions(gens, network)
                    p_schedule, u_schedule, milp_obj = ScheduleRunMILP(gens, network).solve()
                    schedule_change_ratio = float(
                        np.mean(np.abs(np.rint(u_schedule) - np.rint(nominal_u)))
                    )
                    chp = PrimalCHPLP(gens, network, use_output_vars=True)
                    lmp, obj, ok = chp.solve()
                    if not ok:
                        raise RuntimeError("D-CHP pricing LP did not reach an optimal status")
                    results = run_comparison(
                        generators=gens,
                        network=network,
                        p_dispatch=p_schedule,
                        u_dispatch=u_schedule,
                        milp_obj=milp_obj,
                        chp_lp_obj=obj,
                        chp_lmp_matrix=lmp,
                        chp_uplifts=[],
                        chp_ptdf_alpha=chp._ptdf_alpha,
                        chp_ptdf_beta_=chp._ptdf_beta_,
                        methods=benchmarks,
                        lr_max_iter=500,
                        chp_solve_time=chp.total_time,
                        chp_build_time=chp.build_time,
                        chp_solver_time=chp.solver_time,
                    )
                    for method, result in results.items():
                        rows.append(_round_row(
                            "family_sensitivity", delta, seed, method,
                            result, chp if method == "chp" else None,
                            milp_obj=milp_obj,
                            parameter_family=family,
                            schedule_change_ratio=schedule_change_ratio,
                        ))
                except Exception as exc:
                    rows.append({
                        "experiment": "family_sensitivity",
                        "parameter_family": family,
                        "delta": delta,
                        "seed": seed,
                        "method": "all",
                        "status": f"failed: {type(exc).__name__}",
                        "message": str(exc),
                    })


def run_solver_configs(rows: list[dict]) -> None:
    gens, network = load_case("30", "ptdf", 24, 3, congestion="tight", fmax_scale=1.0)
    gens = rolling_initial_conditions(gens, network)
    for config_name, method, crossover in (
        ("dual_simplex", 1, 0),
        ("barrier_no_crossover", 2, 0),
        ("barrier_with_crossover", 2, 1),
    ):
        for tolerance in (1e-6, 1e-8):
            for repetition in range(1, 6):
                chp = PrimalCHPLP(
                    gens,
                    network,
                    method=method,
                    crossover=crossover,
                    feasibility_tol=tolerance,
                    optimality_tol=tolerance,
                    use_output_vars=True,
                )
                _, obj, ok = chp.solve()
                result = {
                    "pricing_obj": obj,
                    "total_uplift": "",
                    "gen_uplift": "",
                    "ftr_cost": "",
                    "build_time": chp.build_time,
                    "pricing_time": chp.total_time,
                    "response_time": 0.0,
                    "total_time": chp.total_time,
                }
                rows.append(_round_row(
                    "solver_configuration",
                    tolerance,
                    repetition,
                    "chp",
                    result,
                    chp,
                    status="optimal" if ok else "not_optimal",
                    solver_config=config_name,
                    gurobi_method=method,
                    crossover=crossover,
                ))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default="results/tps_revision_validation/numerical_stability_30bus.csv",
    )
    parser.add_argument("--skip-perturbations", action="store_true")
    parser.add_argument("--skip-solver-configs", action="store_true")
    parser.add_argument(
        "--run-family-sensitivity",
        action="store_true",
        help="Run one-parameter-family-at-a-time coefficient sensitivity tests.",
    )
    parser.add_argument(
        "--family-deltas", nargs="+", type=float, default=[1e-3, 1e-2],
        help="Relative perturbation magnitudes for the family-sensitivity tests.",
    )
    parser.add_argument("--deltas", nargs="+", type=float, default=[1e-4, 1e-3, 1e-2])
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    parser.add_argument(
        "--benchmarks",
        nargs="+",
        default=["dwp_incremental"],
        choices=["dwp_incremental", "xiao"],
        help=(
            "Exact benchmark(s) to compare on each perturbation.  The default "
            "keeps DWP; exact S-CHP may require prohibitive output-state "
            "enumeration after coefficient perturbations."
        ),
    )
    args = parser.parse_args()

    rows: list[dict] = []
    if not args.skip_perturbations:
        run_perturbations(rows, args.deltas, args.seeds, args.benchmarks)
    if args.run_family_sensitivity:
        run_family_sensitivity(rows, args.family_deltas, args.seeds, args.benchmarks)
    if not args.skip_solver_configs:
        run_solver_configs(rows)
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
