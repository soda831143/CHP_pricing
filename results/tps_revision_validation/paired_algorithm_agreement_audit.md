# Paired D-CHP/DWP Algorithm-Agreement Audit

## Purpose

This audit assesses numerical agreement on the same perturbed UC/CHP instance. It does not interpret the difference between a perturbed instance and the nominal market instance as an algorithmic error.

## Result

- Paired instances: 250 (50 joint and 200 one-family instances).
- Every D-CHP and DWP run has status `optimal`.
- Maximum relative pricing-objective disagreement: 1.339e-08.
- Maximum relative total-uplift disagreement: 2.430e-07.
- Conclusion: the archived perturbation data show no method-specific numerical disagreement at the solver precision represented by these runs.

## Joint-perturbation audit

| Input set | $\delta$ | Instances | Max relative objective disagreement | Max relative total-uplift disagreement |
|---|---:|---:|---:|---:|
| joint | 0.1% | 10 | 3.417e-09 | 8.309e-09 |
| joint | 0.5% | 10 | 1.310e-09 | 3.371e-09 |
| joint | 1% | 10 | 1.090e-09 | 5.316e-09 |
| joint | 3% | 10 | 7.557e-10 | 5.124e-09 |
| joint | 5% | 10 | 9.831e-10 | 7.139e-09 |

## One-family-at-a-time audit

| Input set | $\delta$ | Instances | Max relative objective disagreement | Max relative total-uplift disagreement |
|---|---:|---:|---:|---:|
| cost | 0.1% | 10 | 1.701e-09 | 5.120e-09 |
| cost | 0.5% | 10 | 2.950e-10 | 3.364e-10 |
| cost | 1% | 10 | 2.151e-10 | 1.155e-08 |
| cost | 3% | 10 | 7.995e-10 | 6.348e-08 |
| cost | 5% | 10 | 2.127e-09 | 5.750e-09 |
| demand | 0.1% | 10 | 4.696e-10 | 1.508e-09 |
| demand | 0.5% | 10 | 4.673e-09 | 2.430e-07 |
| demand | 1% | 10 | 1.582e-09 | 4.391e-08 |
| demand | 3% | 10 | 2.084e-09 | 6.261e-09 |
| demand | 5% | 10 | 1.235e-10 | 2.349e-08 |
| line_limit | 0.1% | 10 | 1.135e-09 | 1.722e-09 |
| line_limit | 0.5% | 10 | 1.658e-09 | 1.436e-09 |
| line_limit | 1% | 10 | 1.339e-08 | 1.837e-08 |
| line_limit | 3% | 10 | 1.221e-09 | 3.010e-09 |
| line_limit | 5% | 10 | 1.041e-09 | 9.585e-09 |
| ramping | 0.1% | 10 | 3.207e-09 | 9.106e-09 |
| ramping | 0.5% | 10 | 2.266e-09 | 4.668e-09 |
| ramping | 1% | 10 | 1.763e-10 | 4.442e-10 |
| ramping | 3% | 10 | 1.981e-09 | 1.070e-09 |
| ramping | 5% | 10 | 1.623e-09 | 4.530e-09 |

## Scope boundary

This is a first-round agreement audit. The archived runs do not retain a DWP reduced-cost certificate or high-accuracy solver-quality attributes. The separate `run_algorithm_stability_diagnostic.py` script is available for a strict direct-LP/DWP tolerance check in a normal local Gurobi environment if that additional evidence is needed.
