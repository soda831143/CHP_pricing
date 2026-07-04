"""
Xiao et al. explicit M-CHP benchmark.

This module implements the method proposed in:

    Y. Xiao et al., "Convex Hull Pricing via An Explicit Formulation
    for the Lagrangian Dual of the Network-constrained Unit Commitment,"
    IEEE Transactions on Power Systems, 2025.

The implementation follows the paper's two-LP construction:

1. Build P2 by replacing each single-unit UC set with a state-transition
   convex-hull LP.  The state-transition variables play the role of the
   paper's omega_g(s_t, s_{t+1}); unit-level quantities c, p, x, u, d are
   recovered as linear expressions of these transition flows.
2. Solve the explicit dual LP of P2.  In addition to balance and line
   multipliers, the LP contains the free state-flow potentials induced by
   Xiao's Bellman/state-transition formulation.  The nodal CHP is then
   lambda_t + sum_l PTDF[l,b] * (alpha_l,t - delta_l,t), which is equivalent
   to Xiao's Eq. (33) with beta=-delta and gamma=-alpha.

This benchmark is independent from the proposed GP-DAG implementation:
it does not call PrimalCHPLP, VertexOracle, or RampingPolymatroid.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

_this_dir = os.path.dirname(os.path.abspath(__file__))
_proj_dir = os.path.normpath(os.path.join(_this_dir, ".."))
if _proj_dir not in sys.path:
    sys.path.insert(0, _proj_dir)

from models.generator import GeneratorParams
from models.network import NetworkModel, SingleNodeNetwork


@dataclass(frozen=True)
class XiaoState:
    """State before a period: online status, previous output, and run length."""

    online: int
    p_prev: float
    run_len: int


@dataclass(frozen=True)
class XiaoTransition:
    """One period transition arc in Xiao's state-space network."""

    src: XiaoState
    dst: XiaoState
    t: int
    p: float
    online: int
    startup: int
    shutdown: int
    cost: float


class XiaoStateSpaceBuilder:
    """
    Finite state-transition generator for the 1UC convex hull.

    Xiao's paper constructs a finite state space containing output levels,
    online/offline status, start/shutdown flags, and minimum on/off counters.
    The implementation below uses the equivalent information needed by this
    project's UC model: previous output, online/offline status, and the current
    run length.  Output levels are taken from a finite grid consisting of
    Pmin/Pmax, PWL breakpoints, and all ramp-reachable levels.  This makes the
    state-transition LP finite and implementable, as in Xiao's Appendix A-B.
    """

    def __init__(self, params: GeneratorParams, output_step: float = 0.0) -> None:
        self.params = params
        self.output_step = float(output_step)
        self.levels = self._build_output_grid(params, self.output_step)

    @staticmethod
    def _build_output_grid(params: GeneratorParams, output_step: float) -> Tuple[float, ...]:
        points = {0.0, float(params.P_min), float(params.P_max)}

        # PWL breakpoints in total-output coordinates.
        q = float(params.P_min)
        points.add(q)
        for _, width in params.get_pwl_segments():
            q += float(width)
            points.add(min(max(q, params.P_min), params.P_max))

        # Xiao Appendix A constructs a finite output set from lower/upper
        # limits, regular-ramp shifts, start/shutdown-ramp shifts, and segment
        # breakpoints.  We reproduce that idea for possibly asymmetric ramps.
        # For asymmetric ramps, vertices can also be induced by alternating
        # up/down movements, so we add a bounded ramp-closure of the same base
        # levels.  This keeps the benchmark on the exact state-space side
        # instead of relying only on one-directional shifts.
        bases = list(points)
        max_ramp = max(params.R_up, params.R_down, 1e-6)
        n_shift = int(np.ceil((params.P_max - params.P_min) / max_ramp)) + params.T + 2
        for n in range(n_shift + 1):
            points.add(min(params.P_min + n * params.R_up, params.P_max))
            points.add(max(params.P_max - n * params.R_down, params.P_min))
            points.add(min(params.SU_ramp + n * params.R_up, params.P_max))
            points.add(max(params.SD_ramp - n * params.R_down, params.P_min))
            for base in bases:
                points.add(min(base + n * params.R_up, params.P_max))
                points.add(max(base - n * params.R_down, params.P_min))

        closure_bases = list(points)
        closure_depth = params.T + 2
        for base in closure_bases:
            for n_up in range(closure_depth + 1):
                for n_dn in range(closure_depth + 1 - n_up):
                    p = float(base) + n_up * params.R_up - n_dn * params.R_down
                    if params.P_min - 1e-8 <= p <= params.P_max + 1e-8:
                        points.add(p)

        # Optional supplemental uniform grid for diagnostic replication.  Keep
        # the default at zero so the benchmark is state-space based rather than
        # brute-force output enumeration.
        if output_step and output_step > 0.0:
            step = max(output_step, 1e-6)
            n = int(round((params.P_max - params.P_min) / step))
            for k in range(n + 1):
                points.add(round(params.P_min + k * step, 10))

        clean = sorted(
            p for p in points
            if p == 0.0 or params.P_min - 1e-8 <= p <= params.P_max + 1e-8
        )
        return tuple(float(round(p, 10)) for p in clean)

    def build(self) -> Tuple[List[Dict[XiaoState, int]], List[XiaoTransition]]:
        T = self.params.T
        if self.params.initial_status == 1:
            initial_state = XiaoState(
                1,
                float(self.params.initial_power),
                min(int(self.params.initial_up_time), self.params.T_on_min),
            )
        else:
            initial_state = XiaoState(
                0,
                0.0,
                min(int(self.params.initial_down_time), self.params.T_off_min),
            )
        layers: List[Dict[XiaoState, int]] = [
            {initial_state: 0}
        ]
        transitions: List[XiaoTransition] = []

        for t in range(T):
            next_layer: Dict[XiaoState, int] = {}
            for state in layers[t]:
                for tr in self._successors(state, t):
                    if tr.dst not in next_layer:
                        next_layer[tr.dst] = len(next_layer)
                    transitions.append(tr)
            layers.append(next_layer)

        return layers, transitions

    def _successors(self, state: XiaoState, t: int) -> List[XiaoTransition]:
        g = self.params
        out: List[XiaoTransition] = []

        # Candidate offline transition.
        if state.online == 0:
            dst = XiaoState(0, 0.0, min(state.run_len + 1, g.T_off_min))
            out.append(
                XiaoTransition(
                    src=state, dst=dst, t=t, p=0.0, online=0,
                    startup=0, shutdown=0, cost=0.0,
                )
            )
        else:
            can_shutdown = state.run_len >= g.T_on_min
            can_fit_off_tail = (self.params.T - t) >= g.T_off_min
            if can_shutdown and can_fit_off_tail and state.p_prev <= g.SD_ramp + 1e-8:
                dst = XiaoState(0, 0.0, 1)
                out.append(
                    XiaoTransition(
                        src=state, dst=dst, t=t, p=0.0, online=0,
                        startup=0, shutdown=1, cost=float(g.cost_sd),
                    )
                )

        # Candidate online transitions.
        if state.online == 0:
            if state.run_len == 0 or state.run_len >= g.T_off_min:
                can_fit_on_tail = (self.params.T - t) >= g.T_on_min
                if can_fit_on_tail:
                    for p in self.levels:
                        if p == 0.0:
                            continue
                        if p <= g.SU_ramp + 1e-8:
                            dst = XiaoState(1, p, 1)
                            out.append(
                                XiaoTransition(
                                    src=state, dst=dst, t=t, p=p, online=1,
                                    startup=1, shutdown=0,
                                    cost=self._period_cost(p, 1, 1, 0),
                                )
                            )
        else:
            for p in self.levels:
                if p == 0.0:
                    continue
                if p - state.p_prev <= g.R_up + 1e-8 and state.p_prev - p <= g.R_down + 1e-8:
                    dst = XiaoState(1, p, min(state.run_len + 1, g.T_on_min))
                    out.append(
                        XiaoTransition(
                            src=state, dst=dst, t=t, p=p, online=1,
                            startup=0, shutdown=0,
                            cost=self._period_cost(p, 1, 0, 0),
                        )
                    )

        return out

    def _period_cost(self, p: float, online: int, startup: int, shutdown: int) -> float:
        g = self.params
        if online == 0:
            return g.cost_sd * shutdown
        excess = max(float(p) - g.P_min, 0.0)
        var_cost = 0.0
        remaining = excess
        for slope, width in g.get_pwl_segments():
            fill = min(max(remaining, 0.0), float(width))
            var_cost += float(slope) * fill
            remaining -= fill
            if remaining <= 1e-9:
                break
        return (
            var_cost
            + g.cost_nl
            + g.cost_su * startup
            + g.cost_sd * shutdown
        )


class XiaoExplicitPricing:
    """
    Xiao explicit two-LP M-CHP benchmark.

    Parameters
    ----------
        state_output_step
        Optional supplemental output grid.  The default ``0.0`` uses Xiao's
        finite ramp/segment-point construction only.
    """

    def __init__(
        self,
        generators: List[GeneratorParams],
        network: "NetworkModel | np.ndarray",
        state_output_step: float = 0.0,
        max_states_per_unit: int = 200000,
        **_: object,
    ) -> None:
        self.generators = generators
        if isinstance(network, np.ndarray):
            network = SingleNodeNetwork(network)
        self.network = network
        self.T = network.T
        self.N = len(generators)
        self.state_output_step = float(state_output_step)
        self.max_states_per_unit = int(max_states_per_unit)

        self.layers: List[List[Dict[XiaoState, int]]] = []
        self.transitions: List[List[XiaoTransition]] = []
        t_state = time.perf_counter()
        self._build_state_spaces()
        self.state_build_time = max(0.0, time.perf_counter() - t_state)

        self._ptdf_alpha: Optional[np.ndarray] = None
        self._ptdf_beta_: Optional[np.ndarray] = None
        self.n_states = sum(sum(len(layer) for layer in layers) for layers in self.layers)
        self.n_arcs = sum(len(trs) for trs in self.transitions)
        self.n_patterns = self.n_arcs  # backward-compatible CSV field
        self.build_time = float("nan")
        self.solver_time = float("nan")
        self.total_time = float("nan")
        self.p2_build_time = float("nan")
        self.p2_solver_time = float("nan")
        self.dual_build_time = float("nan")
        self.dual_solver_time = float("nan")

    def _build_state_spaces(self) -> None:
        for i, g in enumerate(self.generators):
            builder = XiaoStateSpaceBuilder(g, output_step=self.state_output_step)
            layers, transitions = builder.build()
            n_states = sum(len(layer) for layer in layers)
            if n_states > self.max_states_per_unit:
                raise RuntimeError(
                    f"Xiao state-space model skipped for G{i + 1}: "
                    f"{n_states} states exceeds max_states_per_unit={self.max_states_per_unit}"
                )
            self.layers.append(layers)
            self.transitions.append(transitions)

    def solve(self) -> Tuple[np.ndarray, float, bool]:
        import gurobipy as gp
        from gurobipy import GRB

        t_start = time.perf_counter()
        p2 = self._solve_p2()
        lmp_matrix, alpha, beta_code = self._solve_step2_dual(p2)
        self._ptdf_alpha = alpha
        self._ptdf_beta_ = beta_code
        self.solver_time = float(self.p2_solver_time + self.dual_solver_time)
        self.build_time = float(
            self.state_build_time + self.p2_build_time + self.dual_build_time
        )
        self.total_time = max(0.0, time.perf_counter() - t_start + self.state_build_time)
        return lmp_matrix, p2["obj"], True

    def _solve_p2(self) -> dict:
        import gurobipy as gp
        from gurobipy import GRB

        t_start = time.perf_counter()
        model = gp.Model("XiaoP2StateSpace")
        model.Params.OutputFlag = 0
        model.Params.Method = 2
        model.Params.Crossover = 0

        omega: List[List[gp.Var]] = []
        obj = gp.LinExpr()
        for i, transitions in enumerate(self.transitions):
            omega_i = []
            for a, tr in enumerate(transitions):
                var = model.addVar(lb=0.0, name=f"omega_{i}_{a}")
                omega_i.append(var)
                obj += tr.cost * var
            omega.append(omega_i)
        model.setObjective(obj, GRB.MINIMIZE)

        # State-transition flow conservation: source mass 1 and internal
        # conservation.  A separate sink equality is unnecessary because the
        # layered network has no arcs after period T.
        for i, layers in enumerate(self.layers):
            outgoing: Dict[Tuple[int, XiaoState], List[int]] = {}
            incoming: Dict[Tuple[int, XiaoState], List[int]] = {}
            for a, tr in enumerate(self.transitions[i]):
                outgoing.setdefault((tr.t, tr.src), []).append(a)
                incoming.setdefault((tr.t + 1, tr.dst), []).append(a)

            source = next(iter(layers[0]))
            model.addConstr(
                gp.quicksum(omega[i][a] for a in outgoing.get((0, source), [])) == 1.0,
                name=f"source_{i}",
            )
            for t in range(1, self.T):
                for state in layers[t]:
                    model.addConstr(
                        gp.quicksum(omega[i][a] for a in incoming.get((t, state), []))
                        == gp.quicksum(omega[i][a] for a in outgoing.get((t, state), [])),
                        name=f"flow_{i}_{t}_{layers[t][state]}",
                    )
        balance = {}
        for t in range(self.T):
            balance[t] = model.addConstr(
                gp.quicksum(
                    tr.p * omega[i][a]
                    for i in range(self.N)
                    for a, tr in enumerate(self.transitions[i])
                    if tr.t == t
                )
                == float(self.network.sys_demand[t]),
                name=f"balance_{t}",
            )

        ptdf_ub = {}
        ptdf_lb = {}
        if not self.network.is_single_node:
            PTDF_Gen = self.network.PTDF_Gen
            rhs_pos, rhs_neg = self.network.line_rhs()
            for l in range(self.network.N_line):
                for t in range(self.T):
                    lhs = gp.quicksum(
                        float(PTDF_Gen[l, i]) * tr.p * omega[i][a]
                        for i in range(self.N)
                        for a, tr in enumerate(self.transitions[i])
                        if tr.t == t
                    )
                    ptdf_ub[l, t] = model.addConstr(
                        lhs <= float(rhs_pos[l, t]), name=f"ptdf_ub_{l}_{t}"
                    )
                    ptdf_lb[l, t] = model.addConstr(
                        -lhs <= -float(rhs_neg[l, t]), name=f"ptdf_lb_{l}_{t}"
                    )

        build_done = time.perf_counter()
        model.optimize()
        total_done = time.perf_counter()
        self.p2_build_time = max(0.0, build_done - t_start)
        self.p2_solver_time = float(getattr(model, "Runtime", total_done - build_done))
        if model.Status not in (GRB.OPTIMAL, GRB.SUBOPTIMAL):
            raise RuntimeError(f"Xiao P2 求解失败，Gurobi Status={model.Status}")

        omega_val: List[np.ndarray] = []
        p_star = np.zeros((self.N, self.T))
        c_star = np.zeros((self.N, self.T))
        for i in range(self.N):
            vals = np.array([var.X for var in omega[i]], dtype=float)
            omega_val.append(vals)
            for a, tr in enumerate(self.transitions[i]):
                p_star[i, tr.t] += tr.p * vals[a]
                c_star[i, tr.t] += tr.cost * vals[a]

        flows = None
        if not self.network.is_single_node:
            flows = self.network.PTDF_Gen @ p_star - self.network.PTDF @ self.network.demand

        return {
            "obj": float(model.ObjVal),
            "omega": omega_val,
            "p": p_star,
            "c": c_star,
            "flows": flows,
        }

    def _solve_step2_dual(self, p2: dict) -> Tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
        """Solve Xiao Step 2 as the explicit dual LP of P2."""
        import gurobipy as gp
        from gurobipy import GRB

        t_start = time.perf_counter()
        model = gp.Model("XiaoStep2Dual")
        model.Params.OutputFlag = 0
        model.Params.Method = 2
        model.Params.Crossover = 0

        lam = model.addVars(self.T, lb=-GRB.INFINITY, name="lambda")
        rho = model.addVars(self.N, lb=-GRB.INFINITY, name="rho_source")
        phi = {}
        for i, layers in enumerate(self.layers):
            for t in range(1, self.T):
                for state, idx in layers[t].items():
                    phi[i, t, state] = model.addVar(
                        lb=-GRB.INFINITY, name=f"phi_{i}_{t}_{idx}"
                    )

        if self.network.is_single_node:
            alpha = {}
            beta_code = {}
        else:
            alpha = model.addVars(
                self.network.N_line, self.T, lb=-GRB.INFINITY, ub=0.0, name="alpha_ub"
            )
            beta_code = model.addVars(
                self.network.N_line, self.T, lb=-GRB.INFINITY, ub=0.0, name="beta_lb"
            )

        # Explicit dual feasibility for every state-transition arc.  The phi
        # terms are the state-flow potentials corresponding to Xiao's Bellman
        # dual; omitting them would incorrectly force every single-period arc
        # to recover its fixed/start-up cost directly from the energy price.
        for i, transitions in enumerate(self.transitions):
            for a, tr in enumerate(transitions):
                expr = gp.LinExpr()
                if tr.t == 0:
                    expr += rho[i]
                else:
                    expr += -phi[i, tr.t, tr.src]
                if tr.t + 1 < self.T:
                    expr += phi[i, tr.t + 1, tr.dst]

                expr += tr.p * lam[tr.t]
                if not self.network.is_single_node:
                    for l in range(self.network.N_line):
                        coeff = float(self.network.PTDF_Gen[l, i]) * tr.p
                        expr += coeff * alpha[l, tr.t]
                        expr += -coeff * beta_code[l, tr.t]
                model.addConstr(expr <= tr.cost + 1e-8, name=f"dual_feas_{i}_{a}")

        obj = gp.LinExpr()
        for i in range(self.N):
            obj += rho[i]
        for t in range(self.T):
            obj += float(self.network.sys_demand[t]) * lam[t]

        if not self.network.is_single_node:
            rhs_pos, rhs_neg = self.network.line_rhs()
            for l in range(self.network.N_line):
                for t in range(self.T):
                    obj += float(rhs_pos[l, t]) * alpha[l, t]
                    obj += -float(rhs_neg[l, t]) * beta_code[l, t]

        model.setObjective(obj, GRB.MAXIMIZE)

        build_done = time.perf_counter()
        model.optimize()
        total_done = time.perf_counter()
        self.dual_build_time = max(0.0, build_done - t_start)
        self.dual_solver_time = float(getattr(model, "Runtime", total_done - build_done))
        if model.Status not in (GRB.OPTIMAL, GRB.SUBOPTIMAL):
            raise RuntimeError(f"Xiao Step-2 dual LP 求解失败，Gurobi Status={model.Status}")

        lambda_t = np.array([lam[t].X for t in range(self.T)], dtype=float)
        lambda_t = np.where(np.abs(lambda_t) < 1e-8, 0.0, lambda_t)

        if self.network.is_single_node:
            return np.tile(lambda_t, (1, 1)), None, None

        alpha_arr = np.array(
            [[alpha[l, t].X for t in range(self.T)] for l in range(self.network.N_line)],
            dtype=float,
        )
        beta_arr = np.array(
            [[beta_code[l, t].X for t in range(self.T)] for l in range(self.network.N_line)],
            dtype=float,
        )
        lmp_matrix = lambda_t[np.newaxis, :] + self.network.PTDF.T @ (alpha_arr - beta_arr)
        return lmp_matrix, alpha_arr, beta_arr
