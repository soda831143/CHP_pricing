from __future__ import annotations

import argparse
import csv
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from benchmarks.lmp_pricing import FixedULP
from chp_solver.schedule_run import ScheduleRunMILP
from models.network import PTDFNetwork
from run_experiments import (
    apply_initial_conditions,
    load_case,
    _build_two_day_warmup_network,
    _extract_initial_conditions,
    _network_with_demand_like,
)


def _scaled_network(network: PTDFNetwork, load_scale: float, fmax_scale: float) -> PTDFNetwork:
    return PTDFNetwork(
        demand_matrix=np.asarray(network.demand, dtype=float) * load_scale,
        PTDF=network.PTDF,
        F_max=network.F_max * fmax_scale,
        gen_bus_map=[network.gen_bus_idx(i) for i in range(network.PTDF_Gen.shape[1])],
        PTDF_Gen=network.PTDF_Gen,
    )


def _warm_start(gens, network: PTDFNetwork, warmup_load_factor: float):
    warm_net = _build_two_day_warmup_network(network, warmup_load_factor)
    warm_gens = [replace(g, T=48) for g in gens]
    p48, u48, _ = ScheduleRunMILP(warm_gens, warm_net).solve()
    u0, p0, on_time, off_time = _extract_initial_conditions(p48, u48, 23)
    return apply_initial_conditions(gens, u0, p0, on_time, off_time)


def _schedule_flows(network: PTDFNetwork, p_dispatch: np.ndarray) -> np.ndarray:
    return network.PTDF_Gen @ p_dispatch - network.PTDF @ network.demand


def scan_one(load_scale: float, fmax_scale: float, warm_start: bool, warmup_load_factor: float):
    gens, network = load_case("118", "ptdf", 24, 3, congestion="tight", fmax_scale=1.0)
    network = _scaled_network(network, load_scale, fmax_scale)
    if warm_start:
        gens = _warm_start(gens, network, warmup_load_factor)

    row = {
        "load_scale": load_scale,
        "fmax_scale": fmax_scale,
        "warm_start": int(warm_start),
        "status": "ok",
    }
    t0 = time.time()
    try:
        p_dispatch, u_dispatch, milp_obj = ScheduleRunMILP(gens, network).solve()
    except Exception as exc:
        row.update({"status": f"uc_failed: {type(exc).__name__}", "error": str(exc)[:180]})
        return row
    row["uc_time_s"] = time.time() - t0
    row["milp_obj"] = milp_obj

    flows = _schedule_flows(network, p_dispatch)
    util = np.abs(flows) / np.maximum(network.F_max[:, None], 1e-9)
    row["load_peak_mw"] = float(network.sys_demand.max())
    row["load_min_mw"] = float(network.sys_demand.min())
    row["online_units_avg"] = float(u_dispatch.sum(axis=0).mean())
    row["online_units_max"] = int(u_dispatch.sum(axis=0).max())
    row["committed_units"] = int((u_dispatch.sum(axis=1) > 1e-6).sum())
    row["max_line_util"] = float(util.max())
    row["binding_line_hours_099"] = int((util >= 0.99).sum())
    row["binding_line_hours_095"] = int((util >= 0.95).sum())

    solver = FixedULP(gens, network, u_dispatch)
    t0 = time.time()
    try:
        lmp, lmp_obj, _ = solver.solve()
        row["lmp_time_s"] = time.time() - t0
        row["lmp_obj"] = lmp_obj
        alpha = np.asarray(solver._ptdf_alpha) if solver._ptdf_alpha is not None else np.zeros_like(flows)
        beta = np.asarray(solver._ptdf_beta_) if solver._ptdf_beta_ is not None else np.zeros_like(flows)
        dual_mag = np.abs(alpha) + np.abs(beta)
        row["congested_dual_line_hours"] = int((dual_mag > 1e-6).sum())
        row["dual_abs_sum"] = float(dual_mag.sum())
        row["lmp_min"] = float(np.nanmin(lmp))
        row["lmp_max"] = float(np.nanmax(lmp))
    except Exception as exc:
        row.update({"lmp_status": f"failed: {type(exc).__name__}", "lmp_error": str(exc)[:180]})
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--load-scales", nargs="+", type=float, default=[1.0, 1.05, 1.10, 1.15])
    parser.add_argument("--fmax-scales", nargs="+", type=float, default=[1.0, 0.95, 0.90, 0.85])
    parser.add_argument("--warm-start", action="store_true")
    parser.add_argument("--warmup-load-factor", type=float, default=0.98)
    parser.add_argument("--out", default="results/scan_118_load_fmax.csv")
    args = parser.parse_args()

    rows = []
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    for ls in args.load_scales:
        for fs in args.fmax_scales:
            print(f"scan load_scale={ls:g}, fmax_scale={fs:g}")
            row = scan_one(ls, fs, args.warm_start, args.warmup_load_factor)
            rows.append(row)
            print(row)
            fieldnames = sorted({k for r in rows for k in r})
            with out.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

    fieldnames = sorted({k for r in rows for k in r})
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
