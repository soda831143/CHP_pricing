# data/ Notes

`data/cases/` contains the UC-CHP test systems used by the executable
experiments.

| File | System | Notes |
|---|---|---|
| `case_6ww.py` | 6-bus | small smoke/mechanism case |
| `case_30ww.py` | 30-bus | current main paper case |
| `case_118ww.py` | 118-bus | scalability extension data |
| `case_common.py` | shared utilities | load profile, PTDF, PWL helpers |

## Current Data Convention

- Horizon: 24 hours for the paper runs.
- PWL cost: 3 segments.
- Online power is represented as `p = P_min u + sum_k x_k`.
- `cost_nl = C(P_min)` and PWL segment costs cover the incremental output
  above `P_min`.
- The 30-bus PTDF paper scenario uses `--fmax-scale 1.0` with the current
  30-bus data.
- The original `rateA` line limits are not used as a paper scenario because
  schedule-run UC is infeasible under the current 24-hour UC data.
- The 118-bus extension uses MATPOWER case118 buses/branches and 54 fossil
  thermal units from `IEEE-118 system unit data.pdf` (Units 1001--1054).
  Other PDF resources such as hydro, pumped-storage, fuel-switching, and
  multi-configuration combined-cycle units are not used because the current
  UC-CHP framework models single-mode thermal units.
- MATPOWER case118 branch `rateA` values are zero.  The 118-bus PTDF case
  therefore uses the complete `RATEA` column from `IEEE118/SCUC_118.xls`.
  In `models/network.py`, `congestion="tight"` uses these limits directly
  and `moderate` applies a 1.25 multiplier.
- Paper runs should pass `--warm-start-from-uc` for both 30-bus and 118-bus
  cases when using derived initial conditions.  The 118-bus PDF initial-time
  column is not hard-coded into the case file, so both systems use the same
  initialization protocol.

## Common Calls

```python
from models.generator import load_all_case30ww_generators, load_all_case118ww_generators
from models.network import build_ptdf_network_from_case30ww, build_ptdf_network_from_case118ww

generators = load_all_case30ww_generators(T=24, n_segments=3)
network = build_ptdf_network_from_case30ww(T=24, congestion="tight")

gens118 = load_all_case118ww_generators(T=24, n_segments=3)
network118 = build_ptdf_network_from_case118ww(T=24, congestion="tight")
```

## Minimum Check After Data Changes

```powershell
python run_experiments.py --cases 30 --networks ptdf --segments 3 --T 24 --congestion tight --methods lmp mirp xiao --out results/manual_data_smoke.csv
```

Then run the exact-method check:

```powershell
python run_experiments.py --cases 30 --networks ptdf --segments 3 --T 24 --congestion tight --methods dwp xiao --out results/manual_exact_check.csv
```

Expected: DWP, S-CHP, and D-CHP objectives agree within tolerance once DWP
converges.
