"""Non-monotone reoptimization must refresh every primal/dual vector."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from engine import load_case
from price_vulnerability.affine_oracle import solve_endpoint, dual_audit_passed
from price_vulnerability.persistent_chp import PersistentCHP


def main():
    generators, network = load_case('6', 'ptdf', 24, 3, 'tight')
    model = PersistentCHP(generators, network, 1)
    points = [model.solve(delta) for delta in (0., .6, .05, .6, 0.)]
    assert model.calls == 5
    assert all(dual_audit_passed(p) for p in points)
    for k in (0, 1, 2):
        direct = solve_endpoint(generators, network, 1, points[k].delta)
        assert abs(direct.value-points[k].value) < 1e-6
    assert abs(points[0].value-points[4].value) < 1e-6
    assert abs(points[1].value-points[3].value) < 1e-6
    # Archived arrays must not alias the mutable model state or a later solution.
    assert not np.shares_memory(points[0].primal, points[4].primal)
    print('Persistent objective updates, complete-dual extraction, and non-monotone returns passed')


if __name__ == '__main__':
    main()
