"""
Batch experiment runner for the CHP paper.

Examples
--------
python run_experiments.py --cases 6 30 --networks single ptdf --methods lmp mirp level dwp
python run_experiments.py --cases 118 --networks ptdf --methods lmp mirp dwp --segments 3
python run_experiments.py --cases 30 --networks ptdf --segments 3 --level-max-iter 500
python run_experiments.py --cases 6 30 --networks single ptdf --methods xiao dwp --xiao-max-states 200000
python run_experiments.py --cases 6 --networks single --methods xiao --T 24 48 72 96
python run_experiments.py --cases 6 30 --networks single --methods xiao --segments 3
python run_experiments.py --cases 6 30 --networks single --methods xiao --ramp-scenarios base tight heterogeneous
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from pathlib import Path
import time
from typing import List, Optional, Tuple

import numpy as np

from models.generator import (
    load_all_case6ww_generators,
    load_all_case30ww_generators,
    load_all_case118ww_generators,
)
from models.network import (
    PTDFNetwork,
    SingleNodeNetwork,
    build_single_node_from_case6ww,
    build_single_node_from_case30ww,
    build_single_node_from_case118ww,
    build_ptdf_network_from_case6ww,
    build_ptdf_network_from_case30ww,
    build_ptdf_network_from_case118ww,
)
from chp_solver.schedule_run import ScheduleRunMILP
from chp_solver.chp_master_lp import PrimalCHPLP
from benchmarks.unit_self_schedule import UnitSelfScheduleMILP
from chp_core.graph_builder import DAGBuilder
from benchmarks.comparison_runner import run_comparison


def load_case(case: str, network_mode: str, T: int, n_segments: int, congestion: str = "tight", fmax_scale: Optional[float] = None):
    if case == "6":
        gens = load_all_case6ww_generators(T=T, n_segments=n_segments)
        network = (
            build_ptdf_network_from_case6ww(T=T, congestion=congestion, fmax_scale=fmax_scale)
            if network_mode == "ptdf"
            else build_single_node_from_case6ww(T=T)
        )
    elif case == "30":
        gens = load_all_case30ww_generators(T=T, n_segments=n_segments)
        network = (
            build_ptdf_network_from_case30ww(T=T, congestion=congestion, fmax_scale=fmax_scale)
            if network_mode == "ptdf"
            else build_single_node_from_case30ww(T=T)
        )
    elif case == "118":
        gens = load_all_case118ww_generators(T=T, n_segments=n_segments)
        network = (
            build_ptdf_network_from_case118ww(T=T, congestion=congestion, fmax_scale=fmax_scale)
            if network_mode == "ptdf"
            else build_single_node_from_case118ww(T=T)
        )
    else:
        raise ValueError(f"Unsupported case: {case}")
    return gens, network


def apply_ramp_scenario(gens, scenario: str):
    """
    Return generator parameters for a ramping stress scenario.

    The benchmark algorithms are not changed; every method receives the same
    modified UC data.  These scenarios are sensitivity tests for ramping
    tightness/heterogeneity, not new pricing methods.
    """
    if scenario == "base":
        return gens

    out = []
    for i, g in enumerate(gens):
        if scenario == "tight":
            ru_scale, rd_scale = 0.85, 0.85
            su_scale, sd_scale = 0.95, 0.95
        elif scenario == "heterogeneous":
            if i % 2 == 0:
                ru_scale, rd_scale = 0.90, 1.10
                su_scale, sd_scale = 1.00, 1.00
            else:
                ru_scale, rd_scale = 1.10, 0.90
                su_scale, sd_scale = 1.00, 1.00
        elif scenario == "tight_heterogeneous":
            if i % 2 == 0:
                ru_scale, rd_scale = 0.85, 0.95
                su_scale, sd_scale = 0.95, 0.95
            else:
                ru_scale, rd_scale = 0.95, 0.85
                su_scale, sd_scale = 0.95, 0.95
        else:
            raise ValueError(f"Unsupported ramp scenario: {scenario}")

        out.append(
            replace(
                g,
                R_up=max(1e-6, g.R_up * ru_scale),
                R_down=max(1e-6, g.R_down * rd_scale),
                SU_ramp=max(g.P_min, g.SU_ramp * su_scale),
                SD_ramp=max(g.P_min, g.SD_ramp * sd_scale),
            )
        )
    return out


def apply_fixed_cost_multiplier(gens, multiplier: float):
    """
    Return generator parameters with uniformly scaled non-convex costs.

    The base case is left unchanged when ``multiplier=1``.  Values above one
    define a transparent stress scenario that preserves marginal energy costs,
    capacity limits, ramp limits, and network data while strengthening
    commitment-dependent costs.
    """
    if abs(multiplier - 1.0) < 1e-12:
        return gens
    if multiplier <= 0:
        raise ValueError("fixed-cost multiplier must be positive")
    return [
        replace(
            g,
            cost_nl=g.cost_nl * multiplier,
            cost_su=g.cost_su * multiplier,
            cost_sd=g.cost_sd * multiplier,
        )
        for g in gens
    ]


def apply_load_scenario(network, scenario: str):
    """
    Return a network with a modified net-load trajectory.

    This is a demand/net-load stress test only.  It does not add renewable
    generators to the market model, so renewable resources do not receive
    convex-hull prices or uplift in these experiments.  The interpretation is:
    thermal UC sees a net load after exogenous renewable forecast subtraction.
    """
    if scenario == "base":
        return network

    demand = np.asarray(network.demand, dtype=float).copy()
    T = network.T
    hours = np.arange(T, dtype=float) % 24.0

    if scenario == "duck":
        # Midday net-load depression and evening rebound.  Keep the multiplier
        # mild enough that feasibility is governed by ramping, not adequacy.
        midday_dip = 0.18 * np.exp(-0.5 * ((hours - 13.0) / 3.0) ** 2)
        evening_peak = 0.12 * np.exp(-0.5 * ((hours - 19.0) / 2.0) ** 2)
        multiplier = 1.0 - midday_dip + evening_peak
    elif scenario == "high_ramp":
        # A sharper but still smooth net-load ramp around sunset.
        midday_dip = 0.22 * np.exp(-0.5 * ((hours - 13.0) / 2.5) ** 2)
        evening_peak = 0.16 * np.exp(-0.5 * ((hours - 18.5) / 1.5) ** 2)
        multiplier = 1.0 - midday_dip + evening_peak
    else:
        raise ValueError(f"Unsupported load scenario: {scenario}")

    # Avoid changing the adequacy level too much; this stress should mainly
    # alter net-load ramping shape.  Preserve each case's original peak load.
    stressed = demand * multiplier.reshape(1, -1)
    base_peak = float(demand.sum(axis=0).max())
    stressed_peak = float(stressed.sum(axis=0).max())
    if stressed_peak > 1e-9:
        stressed *= base_peak / stressed_peak

    if isinstance(network, SingleNodeNetwork):
        return SingleNodeNetwork(stressed.reshape(-1))
    if isinstance(network, PTDFNetwork):
        return PTDFNetwork(
            demand_matrix=stressed,
            PTDF=network.PTDF,
            F_max=network.F_max,
            gen_bus_map=[network.gen_bus_idx(i) for i in range(network.PTDF_Gen.shape[1])],
            PTDF_Gen=network.PTDF_Gen,
        )
    raise TypeError(f"Unsupported network type for load scenario: {type(network)!r}")


def apply_load_scale(network, scale: float):
    if abs(scale - 1.0) < 1e-12:
        return network
    if scale <= 0:
        raise ValueError("load scale must be positive")
    return _network_with_demand_like(network, np.asarray(network.demand, dtype=float) * scale)


def _network_with_demand_like(network, demand: np.ndarray):
    if isinstance(network, SingleNodeNetwork):
        return SingleNodeNetwork(np.asarray(demand, dtype=float).reshape(-1))
    if isinstance(network, PTDFNetwork):
        return PTDFNetwork(
            demand_matrix=np.asarray(demand, dtype=float),
            PTDF=network.PTDF,
            F_max=network.F_max,
            gen_bus_map=[network.gen_bus_idx(i) for i in range(network.PTDF_Gen.shape[1])],
            PTDF_Gen=network.PTDF_Gen,
        )
    raise TypeError(f"Unsupported network type: {type(network)!r}")


def _build_two_day_warmup_network(eval_network, warmup_load_factor: float = 0.98):
    """Use a lightly scaled copy of the evaluation day as warm-up day 1."""
    demand = np.asarray(eval_network.demand, dtype=float)
    if isinstance(eval_network, SingleNodeNetwork):
        first = demand.reshape(1, -1) * warmup_load_factor
        second = demand.reshape(1, -1)
        return SingleNodeNetwork(np.concatenate([first, second], axis=1).reshape(-1))
    first = demand * warmup_load_factor
    second = demand.copy()
    return _network_with_demand_like(eval_network, np.concatenate([first, second], axis=1))


def _extract_initial_conditions(p_dispatch: np.ndarray, u_dispatch: np.ndarray, end_t: int):
    """Return (u0, p0, consecutive_on, consecutive_off) at period ``end_t``."""
    N = u_dispatch.shape[0]
    u0 = np.asarray(u_dispatch[:, end_t], dtype=float)
    p0 = np.asarray(p_dispatch[:, end_t], dtype=float)
    on_time = np.zeros(N, dtype=int)
    off_time = np.zeros(N, dtype=int)
    for i in range(N):
        if u0[i] > 0.5:
            k = end_t
            while k >= 0 and u_dispatch[i, k] > 0.5:
                on_time[i] += 1
                k -= 1
        else:
            k = end_t
            while k >= 0 and u_dispatch[i, k] <= 0.5:
                off_time[i] += 1
                k -= 1
    return u0, p0, on_time, off_time


def apply_initial_conditions(gens, u0, p0, on_time, off_time):
    out = []
    for i, g in enumerate(gens):
        online = int(round(float(u0[i])))
        out.append(
            replace(
                g,
                initial_status=online,
                initial_power=float(p0[i]) if online else 0.0,
                initial_up_time=int(on_time[i]) if online else 0,
                initial_down_time=0 if online else int(off_time[i]),
            )
        )
    return out


def derive_warm_start_initial_conditions(
    case: str,
    network_mode: str,
    n_segments: int,
    congestion: str,
    fmax_scale: Optional[float],
    ramp_scenario: str = "base",
    load_scenario: str = "base",
    load_scale: float = 1.0,
    fixed_cost_multiplier: float = 1.0,
    warmup_load_factor: float = 0.98,
):
    """Run a two-day UC and return initial conditions for the second day."""
    eval_gens, eval_network = load_case(
        case, network_mode, 24, n_segments, congestion=congestion, fmax_scale=fmax_scale
    )
    eval_gens = apply_ramp_scenario(eval_gens, ramp_scenario)
    eval_gens = apply_fixed_cost_multiplier(eval_gens, fixed_cost_multiplier)
    eval_network = apply_load_scenario(eval_network, load_scenario)
    eval_network = apply_load_scale(eval_network, load_scale)

    warm_gens = [replace(g, T=48) for g in eval_gens]
    warm_network = _build_two_day_warmup_network(eval_network, warmup_load_factor)
    p_warm, u_warm, _ = ScheduleRunMILP(warm_gens, warm_network).solve()
    return _extract_initial_conditions(p_warm, u_warm, end_t=23)


def summarize_size(gens) -> dict:
    dags = [DAGBuilder.build(g) for g in gens]
    return {
        "on_arcs": sum(d.n_on for d in dags),
        "off_arcs": sum(d.n_off for d in dags),
        "dag_edges": sum(d.n_edges for d in dags),
        "v_vars": sum(d.n_v_vars for d in dags),
    }


def run_one(
    case: str,
    network_mode: str,
    T: int,
    n_segments: int,
    methods: List[str],
    lr_max_iter: int,
    xiao_max_states: int,
    xiao_state_step: float,
    skip_proposed: bool,
    congestion: str = "tight",
    fmax_scale: Optional[float] = None,
    ramp_scenario: str = "base",
    load_scenario: str = "base",
    load_scale: float = 1.0,
    fixed_cost_multiplier: float = 1.0,
    warm_start_from_uc: bool = False,
    warmup_load_factor: float = 0.98,
    chp_method: int = 2,
    chp_crossover: int = 0,
    chp_bar_conv_tol: Optional[float] = None,
    chp_feasibility_tol: Optional[float] = None,
    chp_optimality_tol: Optional[float] = None,
    chp_numeric_focus: Optional[int] = None,
):
    gens, network = load_case(case, network_mode, T, n_segments, congestion=congestion, fmax_scale=fmax_scale)
    gens = apply_ramp_scenario(gens, ramp_scenario)
    gens = apply_fixed_cost_multiplier(gens, fixed_cost_multiplier)
    network = apply_load_scenario(network, load_scenario)
    network = apply_load_scale(network, load_scale)
    if warm_start_from_uc:
        if T != 24:
            raise ValueError("warm_start_from_uc currently expects the evaluation horizon T=24")
        u0, p0, on_time, off_time = derive_warm_start_initial_conditions(
            case,
            network_mode,
            n_segments,
            congestion,
            fmax_scale,
            ramp_scenario=ramp_scenario,
            load_scenario=load_scenario,
            load_scale=load_scale,
            fixed_cost_multiplier=fixed_cost_multiplier,
            warmup_load_factor=warmup_load_factor,
        )
        gens = apply_initial_conditions(gens, u0, p0, on_time, off_time)
    size = summarize_size(gens)

    print(
        f"\n=== case={case} network={network_mode} T={T} "
        f"segments={n_segments} ramp={ramp_scenario} load={load_scenario} "
        f"load_scale={load_scale:g} fixed_mult={fixed_cost_multiplier:g} ==="
    )
    t0 = time.time()
    milp = ScheduleRunMILP(gens, network)
    p_dispatch, u_dispatch, milp_obj = milp.solve()
    milp_time = time.time() - t0

    if skip_proposed:
        chp = None
        chp_lmp = np.zeros((network.N_bus, network.T))
        chp_obj = float("nan")
        chp_time = ""
        chp_uplifts = []
        oracle_time = ""
    else:
        t0 = time.time()
        chp = PrimalCHPLP(
            gens,
            network,
            method=chp_method,
            crossover=chp_crossover,
            bar_conv_tol=chp_bar_conv_tol,
            feasibility_tol=chp_feasibility_tol,
            optimality_tol=chp_optimality_tol,
            numeric_focus=chp_numeric_focus,
        )
        chp_lmp, chp_obj, ok = chp.solve()
        chp_time = time.time() - t0
        if not ok:
            raise RuntimeError("CHP LP failed")
        chp_uplifts = []
        oracle_time = ""

    results = run_comparison(
        generators=gens,
        network=network,
        p_dispatch=p_dispatch,
        u_dispatch=u_dispatch,
        milp_obj=milp_obj,
        chp_lp_obj=chp_obj,
        chp_lmp_matrix=chp_lmp,
        chp_uplifts=chp_uplifts,
        chp_ptdf_alpha=None if chp is None else chp._ptdf_alpha,
        chp_ptdf_beta_=None if chp is None else chp._ptdf_beta_,
        methods=methods,
        lr_max_iter=lr_max_iter,
        lr_verbose=False,
        xiao_max_states=xiao_max_states,
        xiao_state_step=xiao_state_step,
        chp_solve_time=0.0 if skip_proposed else float(chp_time),
    )
    if skip_proposed:
        results.pop("chp", None)

    rows = []
    for key, r in results.items():
        rows.append(
            {
                "case": case,
                "network": network_mode,
                "congestion": congestion if network_mode == "ptdf" else "none",
                "T": T,
                "segments": n_segments,
                "ramp_scenario": ramp_scenario,
                "load_scenario": load_scenario,
                "load_scale": load_scale,
                "fixed_cost_multiplier": fixed_cost_multiplier,
                "method": key,
                "method_name": r["name"],
                "milp_obj": milp_obj,
                "pricing_obj": r["pricing_obj"],
                "duality_gap": r["duality_gap"],
                "gen_uplift": r["gen_uplift"],
                "ftr_cost": r["ftr_cost"],
                "total_uplift": r["total_uplift"],
                "lmp_min": r["lmp_min"],
                "lmp_max": r["lmp_max"],
                "method_time": r.get("total_time", r["solve_time"]),
                "build_time": (
                    chp.build_time if key == "chp" and chp is not None
                    else r.get("build_time", "")
                ),
                "solver_time": (
                    chp.solver_time if key == "chp" and chp is not None
                    else r.get("solver_time", "")
                ),
                "total_time": (
                    chp.total_time if key == "chp" and chp is not None
                    else r.get("total_time", r["solve_time"])
                ),
                "schedule_time": milp_time,
                "chp_time": chp_time if key == "chp" else "",
                "oracle_time": r.get("oracle_time", ""),
                "on_arcs": size["on_arcs"],
                "off_arcs": size["off_arcs"],
                "dag_edges": size["dag_edges"],
                "v_vars": size["v_vars"],
                "n_iter": r.get("n_iter", ""),
                "n_columns": r.get("n_columns", ""),
                "converged": r.get("converged", ""),
                "stop_reason": r.get("stop_reason", ""),
                "upper_bound": r.get("upper_bound", ""),
                "bound_gap": (
                    "" if r.get("upper_bound", "") == ""
                    else float(r["upper_bound"]) - float(r["pricing_obj"])
                ),
                "n_states": r.get("n_states", ""),
                "n_arcs": r.get("n_arcs", ""),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", nargs="+", default=["6"], choices=["6", "30", "118"])
    parser.add_argument("--networks", nargs="+", default=["single"], choices=["single", "ptdf"])
    parser.add_argument("--segments", nargs="+", default=[3], type=int)
    parser.add_argument("--T", nargs="+", default=[24], type=int)
    parser.add_argument("--methods", nargs="+", default=["lmp", "mirp", "level", "dwp", "xiao"])
    parser.add_argument(
        "--level-max-iter",
        "--lr-max-iter",
        dest="lr_max_iter",
        default=300,
        type=int,
        help="Maximum iterations for the LVM/level-method benchmark.",
    )
    parser.add_argument("--xiao-max-states", default=200000, type=int)
    parser.add_argument("--xiao-state-step", default=0.0, type=float)
    parser.add_argument("--skip-proposed", action="store_true")
    parser.add_argument("--congestion", default="tight", choices=["tight", "moderate", "relaxed"])
    parser.add_argument("--fmax-scale", default=None, type=float,
                        help="Override line capacity multiplier (e.g. 1.5).")
    parser.add_argument("--warm-start-from-uc", action="store_true",
                        help="Run a two-day UC warm-up and use day-1 end states as initial conditions.")
    parser.add_argument("--warmup-load-factor", default=0.98, type=float,
                        help="Multiplier applied to the warm-up day load; the evaluation day is unchanged.")
    parser.add_argument("--chp-method", default=2, type=int,
                        help="Gurobi Method parameter for D-CHP; default 2 is barrier.")
    parser.add_argument("--chp-crossover", default=0, type=int,
                        help="Gurobi Crossover parameter for D-CHP; use 1 for dual-price diagnostics.")
    parser.add_argument("--chp-bar-conv-tol", default=None, type=float)
    parser.add_argument("--chp-feasibility-tol", default=None, type=float)
    parser.add_argument("--chp-optimality-tol", default=None, type=float)
    parser.add_argument("--chp-numeric-focus", default=None, type=int)
    parser.add_argument(
        "--ramp-scenarios",
        nargs="+",
        default=["base"],
        choices=["base", "tight", "heterogeneous", "tight_heterogeneous"],
    )
    parser.add_argument(
        "--load-scenarios",
        nargs="+",
        default=["base"],
        choices=["base", "duck", "high_ramp"],
    )
    parser.add_argument(
        "--load-scales",
        nargs="+",
        default=[1.0],
        type=float,
        help="Uniform multiplier applied to all bus loads after load-scenario shaping.",
    )
    parser.add_argument(
        "--fixed-cost-multipliers",
        nargs="+",
        default=[1.0],
        type=float,
        help="Uniform multipliers for no-load, startup, and shutdown costs.",
    )
    parser.add_argument("--out", default="results/chp_experiment_results.csv")
    args = parser.parse_args()

    all_rows = []
    for case in args.cases:
        for network in args.networks:
            for T in args.T:
                for segments in args.segments:
                    for ramp_scenario in args.ramp_scenarios:
                        for load_scenario in args.load_scenarios:
                            for load_scale in args.load_scales:
                                for fixed_cost_multiplier in args.fixed_cost_multipliers:
                                    rows = run_one(
                                        case,
                                        network,
                                        T,
                                        segments,
                                        args.methods,
                                        args.lr_max_iter,
                                        args.xiao_max_states,
                                        args.xiao_state_step,
                                        args.skip_proposed,
                                        args.congestion,
                                        args.fmax_scale,
                                        ramp_scenario,
                                        load_scenario,
                                        load_scale,
                                        fixed_cost_multiplier,
                                        args.warm_start_from_uc,
                                        args.warmup_load_factor,
                                        args.chp_method,
                                        args.chp_crossover,
                                        args.chp_bar_conv_tol,
                                        args.chp_feasibility_tol,
                                        args.chp_optimality_tol,
                                        args.chp_numeric_focus,
                                    )
                                    all_rows.extend(rows)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if all_rows:
        with out.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
            writer.writeheader()
            writer.writerows(all_rows)
    print(f"\nSaved {len(all_rows)} rows to {out}")


if __name__ == "__main__":
    main()
