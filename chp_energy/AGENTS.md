# CHP Project Notes

This directory contains the executable CHP experiment code.  The current code
path is intentionally compact:

```text
chp_project/
├── run_experiments.py                  # manual benchmark CLI
├── generate_current_30base_outputs.py  # current paper tables/figures
├── run_network_capacity_audit_30.py    # relaxed/no-congestion audit
├── README.md                           # command guide
├── models/                             # generator and network models
├── data/                               # 6/30/118-bus test data
├── chp_core/                           # DAG and ramping modules
├── chp_solver/                         # schedule-run MILP and D-CHP LP
├── benchmarks/                         # LMP/IRP/LVM/DWP/S-CHP comparison
└── results/                            # current generated outputs
```

Deleted legacy entry points include `main.py`, `benchmark_main.py`,
`paper_outputs.py`, `stress_sweep_fast.py`, and
`export_iterative_histories.py`.

## Current Manual Commands

Generate the current paper outputs:

```powershell
python generate_current_30base_outputs.py
```

Run the main benchmark manually:

```powershell
python run_experiments.py --cases 30 --networks ptdf --segments 3 --T 24 --congestion tight --methods lmp mirp level dwp xiao --level-max-iter 500 --out results/manual_30_ptdf_tight.csv
```

Add the incremental DWP implementation only when diagnosing implementation
speed:

```powershell
python run_experiments.py --cases 30 --networks ptdf --segments 3 --T 24 --congestion tight --methods lmp mirp level dwp dwp_incremental xiao --level-max-iter 500 --out results/manual_30_ptdf_tight_with_incremental.csv
```

Run the no-congestion audit:

```powershell
python run_experiments.py --cases 30 --networks ptdf --segments 3 --T 24 --congestion relaxed --methods lmp mirp level dwp dwp_incremental xiao --level-max-iter 500 --out results/manual_30_ptdf_relaxed.csv
```

## Method Names

| CLI name | Paper label | Role |
|---|---|---|
| `lmp` | LMP | fixed-commitment pricing |
| `mirp` | IRP | integer-relaxation pricing |
| `level` | LVM | level-method Lagrangian benchmark |
| `dwp` | DWP | rebuilt-RMP Dantzig-Wolfe with parallel unit pricing |
| `dwp_incremental` | DWP-inc | incremental-RMP implementation diagnostic |
| `xiao` | S-CHP | Xiao et al. state-transition CHP |
| automatic | D-CHP | proposed DAG--g-polymatroid LP |

Plain subgradient `lr` is kept internally as an oracle/helper dependency for
LVM development, but it is not exposed as a paper benchmark.

## Current Results

Keep and use:

- `results/current_30base_seg3`
- `results/network_capacity_audit_30_seg3`

Older single-segment, stress-sweep, and partial 118-bus outputs were removed.
