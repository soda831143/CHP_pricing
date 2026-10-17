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

The current research algorithm uses persistent CHP solves and adaptive
bracket-and-validate discovery, with complete-dual affine selection and
common-primal interval witnesses. It does not require degenerate-basis
enumeration. Direct COPT solves check value and primal-dual optimality;
different legal optimal price selections need not agree componentwise.

The [CHP Oracle Explorer](chp_marketpower/dashboard/README.md) adds a local
interactive workbench and a solver-free offline demonstration for the four
existing 30/118-bus bid directions. Price lookup, physical UC and reported-LOC
settlement are separate capabilities. The independent 118-G11 Q500 experiment
and its measured amortization are documented [here](chp_marketpower/results/dashboard_study_20261017/README.md).
Current theory and scope are linked from [the research README](chp_marketpower/README.md).

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
