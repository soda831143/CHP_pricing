"""Licensed 6-bus check: raw nodal dual = local CHP demand derivative."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import PTDFNetwork, PrimalCHPLP, load_case  # noqa: E402
from gurobi_compat import GRB  # noqa: E402


def solve(generators, network, adder):
    bids = np.zeros((len(generators), network.T))
    bids[1] = adder
    solver = PrimalCHPLP(
        generators, network, bid_adders=bids, method=1, crossover=1,
        feasibility_tol=1e-9, optimality_tol=1e-9,
    )
    _, value, success = solver.solve()
    if not success or solver._model.Status != GRB.OPTIMAL:
        raise RuntimeError("CHP demand-perturbation solve was not OPTIMAL")
    return value, solver.raw_nodal_price


def main() -> None:
    generators, network = load_case("6", "ptdf", 24, 3, "tight")
    _, price = solve(generators, network, 0.06)  # interior of value regime 4
    step = 1e-3  # MW; small enough to stay within the local demand regime
    for bus, hour in ((0, 18), (5, 18)):
        values = []
        for sign in (-1, 1):
            demand = network.demand.copy()
            demand[bus, hour] += sign * step
            perturbed = PTDFNetwork(
                demand, network.PTDF, network.F_max,
                gen_bus_map=[network.gen_bus_idx(i) for i in range(len(generators))],
                PTDF_Gen=network.PTDF_Gen,
            )
            values.append(solve(generators, perturbed, 0.06)[0])
        derivative = (values[1] - values[0]) / (2 * step)
        error = abs(derivative - price[bus, hour])
        print(f"bus={bus + 1}, hour={hour + 1}: FD={derivative:.9f}, raw={price[bus, hour]:.9f}, error={error:.3e}")
        assert error < 1e-4, "raw price disagrees with the demand envelope derivative"


if __name__ == "__main__":
    main()
