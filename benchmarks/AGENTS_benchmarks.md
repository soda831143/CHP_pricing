# benchmarks/ Notes

The benchmark package compares pricing methods under the same physical UC
schedule from `ScheduleRunMILP`.  All LOC/uplift calculations use the same
single-unit self-scheduling MILP in `unit_self_schedule.py`.

## Active Benchmark Methods

| File | CLI method | Paper label | Notes |
|---|---|---|---|
| `lmp_pricing.py` | `lmp` | LMP | fixed-commitment economic-dispatch pricing |
| `mirp_pricing.py` | `mirp` | IRP | UC binary relaxation pricing |
| `level_method_pricing.py` | `level` | LVM | level-method Lagrangian benchmark |
| `dantzig_wolfe_pricing_rebuild.py` | `dwp` | DWP | default rebuilt-RMP Dantzig-Wolfe with parallel unit pricing |
| `dantzig_wolfe_pricing.py` | `dwp_incremental` | DWP-inc | incremental-RMP timing diagnostic |
| `xiao_explicit_pricing.py` | `xiao` | S-CHP | Xiao et al. state-transition CHP |
| `comparison_runner.py` | - | - | unified runner and settlement metrics |
| `unit_self_schedule.py` | - | - | common best-response/LOC oracle |

`lagrangian_relaxation.py` remains in the repository because LVM reuses its
unit Lagrangian oracle utilities.  The old plain subgradient `lr` method is not
part of the public benchmark list.

## DWP Convention

The default `dwp` method is the rebuilt-RMP implementation with parallel unit
pricing.  It is slower than the incremental implementation but closer to the
transparent column-generation reference used for paper comparison.

The `dwp_incremental` method uses a persistent RMP and Gurobi `Column` objects.
It is useful for implementation diagnostics, but should be clearly labeled as
an implementation variant rather than the main paper DWP benchmark.

Reduced cost is computed as

```text
c_i(y) - lambda^T p_i(y) - sigma_i.
```

Since `UnitSelfScheduleMILP` returns `max_y(lambda^T p_i - c_i(y))`, the
minimum reduced cost is `-max_profit_i - sigma_i`.  DWP is certified when every
unit has reduced cost above `-epsilon`.

## Settlement Metrics

For all pricing methods:

- `gen_uplift` is the sum of unit LOC values.
- `ftr_cost` is the PTDF congestion/FTR settlement term.
- `total_uplift = gen_uplift + ftr_cost`.
- For exact CHP methods, `total_uplift` should match `milp_obj - pricing_obj`
  within numerical tolerance.

## Manual Run

From `chp_project/`:

```powershell
python run_experiments.py --cases 30 --networks ptdf --segments 3 --T 24 --congestion tight --methods lmp mirp level dwp xiao --level-max-iter 500 --out results/manual_30_ptdf_tight.csv
```
