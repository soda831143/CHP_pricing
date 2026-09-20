# CHP Research Code

This repository root contains the executable convex-hull-pricing research code.

```text
chp_project/
├── chp_energy/       # COPT-based UC and exact CHP engine
└── chp_marketpower/  # price vulnerability, mechanism, and profit experiments
```

`energy-reserve/` is a local legacy checkout of an earlier solver branch. It is
kept on disk for comparison but ignored by this repository because the active
market-power code does not import it and tracking it would duplicate the full
CHP engine and data.

## Branches

- `master`: stable COPT CHP engine plus the finite-difference/profit
  market-power baseline.
- `research/market-power-parametric-regimes`: objective-parametric CHP,
  price-impact regime analysis, and the proposed solver-assisted 1D oracle.

The research branch must preserve the direct COPT solve as ground truth. A
grid-level slope change is only a candidate breakpoint until a basis/reduced-
cost calculation certifies the interval and direct solves reproduce its value
and selected price within tolerance.

## Minimal checks

```powershell
cd chp_energy
python -m pytest -q tests/test_primal_lp_static.py tests/test_interval_coordinate_equivalence.py

cd ..\chp_marketpower
python -m pytest -q tests
python tests/check_chp_integration.py
```

Generated `results/`, solver dumps, caches, and the legacy `energy-reserve/`
checkout are intentionally not versioned.
