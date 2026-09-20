"""Thin adapter to the existing exact CHP engine in ``../chp_energy``."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np


CHP_ENERGY_ROOT = Path(__file__).resolve().parents[1] / "chp_energy"
if not CHP_ENERGY_ROOT.is_dir():
    raise RuntimeError(f"Missing shared CHP engine: {CHP_ENERGY_ROOT}")
if str(CHP_ENERGY_ROOT) not in sys.path:
    sys.path.insert(0, str(CHP_ENERGY_ROOT))

from chp_solver.chp_master_lp import PrimalCHPLP  # noqa: E402
from chp_solver.schedule_run import ScheduleRunMILP  # noqa: E402
from models.generator import (  # noqa: E402
    load_all_case6ww_generators,
    load_all_case30ww_generators,
)
from models.network import (  # noqa: E402
    PTDFNetwork,
    SingleNodeNetwork,
    build_ptdf_network_from_case6ww,
    build_ptdf_network_from_case30ww,
    build_single_node_from_case6ww,
    build_single_node_from_case30ww,
)


@dataclass(frozen=True)
class PricingRun:
    lmp: np.ndarray
    energy_price: np.ndarray
    objective: float
    solver_status: str
    runtime: float


def warmup_initial_conditions(generators, network):
    """Use one physical-UC day to construct the next day's feasible initial state."""
    p_dispatch, u_dispatch, _ = ScheduleRunMILP(generators, network).solve()
    warmed = []
    for i, generator in enumerate(generators):
        status = int(u_dispatch[i, -1])
        duration = 0
        for value in u_dispatch[i, ::-1]:
            if int(value) != status:
                break
            duration += 1
        if duration == network.T and status == generator.initial_status:
            duration += generator.initial_up_time if status else generator.initial_down_time
        warmed.append(replace(
            generator,
            initial_status=status,
            initial_power=float(p_dispatch[i, -1]) if status else 0.0,
            initial_up_time=duration if status else 0,
            initial_down_time=0 if status else duration,
        ))
    return warmed


def load_case(
    case: str,
    network: str,
    T: int,
    segments: int,
    congestion: str = "tight",
    load_scale: float = 1.0,
    load_shift: tuple[float, float, float] | None = None,
    warmup: bool = False,
):
    """Load an existing 6- or 30-bus CHP case without copying case data."""
    if network not in {"single", "ptdf"}:
        raise ValueError(f"Unsupported network: {network}")
    if not np.isfinite(load_scale) or load_scale <= 0:
        raise ValueError("load_scale must be finite and positive")
    if case == "6":
        generators = load_all_case6ww_generators(T=T, n_segments=segments)
        grid = (
            build_ptdf_network_from_case6ww(T=T, congestion=congestion)
            if network == "ptdf"
            else build_single_node_from_case6ww(T=T)
        )
    elif case == "30":
        generators = load_all_case30ww_generators(T=T, n_segments=segments)
        grid = (
            build_ptdf_network_from_case30ww(T=T, congestion=congestion)
            if network == "ptdf"
            else build_single_node_from_case30ww(T=T)
        )
    else:
        raise ValueError(f"Unsupported case: {case}")
    if load_scale != 1.0:
        grid = (
            SingleNodeNetwork(grid.sys_demand * load_scale)
            if network == "single"
            else PTDFNetwork(
                grid.demand * load_scale, grid.PTDF, grid.F_max,
                gen_bus_map=[grid.gen_bus_idx(i) for i in range(len(generators))],
                PTDF_Gen=grid.PTDF_Gen,
            )
        )
    if load_shift is not None:
        if network != "ptdf":
            raise ValueError("load_shift requires a PTDF network")
        from_bus, to_bus, fraction = load_shift
        if not float(from_bus).is_integer() or not float(to_bus).is_integer():
            raise ValueError("load_shift buses must be integer 1-based indices")
        from_idx, to_idx = int(from_bus) - 1, int(to_bus) - 1
        if not 0 <= from_idx < grid.N_bus or not 0 <= to_idx < grid.N_bus or from_idx == to_idx:
            raise ValueError("load_shift buses must be distinct and inside the network")
        if not np.isfinite(fraction) or not 0 < fraction < 1:
            raise ValueError("load_shift fraction must lie in (0, 1)")
        demand = grid.demand.copy()
        moved = fraction * demand[from_idx]
        demand[from_idx] -= moved
        demand[to_idx] += moved
        grid = PTDFNetwork(
            demand, grid.PTDF, grid.F_max,
            gen_bus_map=[grid.gen_bus_idx(i) for i in range(len(generators))],
            PTDF_Gen=grid.PTDF_Gen,
        )
    return (warmup_initial_conditions(generators, grid) if warmup else generators), grid


def controlled_case(
    case: str, scenario: str, T: int, segments: int, congestion: str = "tight",
    load_scale: float = 1.0, load_shift: tuple[float, float, float] | None = None,
    warmup: bool = False,
):
    """C0-C2 isolate time coupling; C2N/C3 share a PTDF grid and differ only in line limits."""
    if scenario not in {"C0", "C1", "C2", "C2N", "C3"}:
        raise ValueError(f"Unsupported scenario: {scenario}")
    generators, network = load_case(
        case, "ptdf" if scenario in {"C2N", "C3"} else "single", T, segments,
        "relaxed" if scenario == "C2N" else congestion, load_scale, load_shift, warmup,
    )
    if scenario == "C0":
        generators = [
            replace(
                g, T_on_min=1, T_off_min=1, cost_su=0.0, cost_sd=0.0,
                R_up=g.P_max, R_down=g.P_max, SU_ramp=g.P_max, SD_ramp=g.P_max,
            )
            for g in generators
        ]
    elif scenario == "C1":
        generators = [replace(g, R_up=g.P_max, R_down=g.P_max) for g in generators]
    return generators, network


def solve_chp(generators, network, bid_multipliers=None, bid_adders=None) -> PricingRun:
    """Run Phase-1 exact CHP and expose the baseline interface used here."""
    from gurobi_compat import GRB

    started = time.perf_counter()
    solver = PrimalCHPLP(
        generators, network, bid_multipliers=bid_multipliers, bid_adders=bid_adders
    )
    lmp, objective, success = solver.solve()
    status_code = solver._model.Status
    status = "optimal" if status_code == GRB.OPTIMAL else "suboptimal" if success else f"failed:{status_code}"
    return PricingRun(
        lmp=np.asarray(lmp, dtype=float),
        energy_price=np.asarray(solver.energy_price if success else np.full(network.T, np.nan), dtype=float),
        objective=float(objective),
        solver_status=status,
        runtime=time.perf_counter() - started,
    )
