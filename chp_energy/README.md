# CHP Project Code Guide

This directory contains the executable code for the CHP experiments.  The
current paper workflow uses 24 hours, 3-segment PWL costs, and the modified
IEEE 30-bus UC case with PTDF constraints.

## Main Commands

Generate the current paper tables and figures:

```powershell
python generate_current_30base_outputs.py
```

Run the main 30-bus benchmark manually:

```powershell
python run_experiments.py --cases 30 --networks ptdf --segments 3 --T 24 --congestion tight --methods lmp mirp level dwp xiao --level-max-iter 500 --out results/manual_30_ptdf_tight.csv
```

Run the same benchmark with the incremental DWP diagnostic:

```powershell
python run_experiments.py --cases 30 --networks ptdf --segments 3 --T 24 --congestion tight --methods lmp mirp level dwp dwp_incremental xiao --level-max-iter 500 --out results/manual_30_ptdf_tight_with_incremental.csv
```

Run the no-congestion audit:

```powershell
python run_experiments.py --cases 30 --networks ptdf --segments 3 --T 24 --congestion relaxed --methods lmp mirp level dwp dwp_incremental xiao --level-max-iter 500 --out results/manual_30_ptdf_relaxed.csv
```

## Method Names

| CLI method | Paper label | Description |
|---|---|---|
| `lmp` | LMP | fixed-commitment LMP |
| `mirp` | IRP | integer-relaxation pricing |
| `level` | LVM | level-method Lagrangian pricing |
| `dwp` | DWP | rebuilt-RMP Dantzig-Wolfe with parallel unit pricing |
| `dwp_incremental` | DWP-inc | incremental-RMP diagnostic variant |
| `xiao` | S-CHP | Xiao et al. state-transition CHP |
| automatic | D-CHP | proposed DAG--g-polymatroid LP |

`run_experiments.py` includes D-CHP unless `--skip-proposed` is passed.

## Kept Results

The clean result directories are:

- `results/current_30base_seg3`
- `results/network_capacity_audit_30_seg3`

Older single-segment, stress-sweep, and partial 118-bus outputs were removed to
avoid accidental reuse.
