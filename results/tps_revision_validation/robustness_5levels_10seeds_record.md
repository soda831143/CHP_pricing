# 30-Bus Bounded Input-Misspecification Experiment Record

## Purpose and scope

- This is a local, bounded input-misspecification study motivated by forecast, calibration, and availability errors. It is not an estimated probability model, Monte Carlo uncertainty quantification, or robust-optimization model.
- Case: modified IEEE 30-bus PTDF BASE case, $T=24$, three-segment PWL costs.
- Each modified instance regenerates the 48-hour rolling UC history before the pricing-day UC and pricing calculations.
- End-to-end pricing time includes construction, pricing optimization, and common exact unit self-scheduling/settlement evaluation; the warm-up UC is excluded.
- D-CHP and DWP are paired on every modified instance: they receive the same perturbed input, rolling initial condition, physical pricing-day schedule, and settlement protocol.

## Joint perturbations

- Bounds: $\delta\in\{0.1\%,0.5\%,1\%,3\%,5\%\}$.
- Ten fixed seeds per bound; 50 modified instances and 100 method-level records.
- All records reached `optimal` status.
- Maximum D-CHP/DWP absolute difference: 0.0006143025239 in pricing objective and 2.87023840428e-05 in total uplift.

## One-family-at-a-time perturbations

- Families: ramping limits, cost coefficients, hourly demand profile, and line limits.
- Same five bounds and ten fixed seeds per family and bound; 200 modified instances and 400 method-level records.
- All records reached `optimal` status.
- Maximum D-CHP/DWP absolute difference: 0.0024085319601 in pricing objective and 0.000663945322685 in total uplift.
- Largest observed pricing-day schedule-change ratio: 13.89\%.

## Interpretation rule

- A commitment switch is reported as an economic/physical UC response to altered data, not as a numerical error.
- Exactness is assessed by solver status and paired D-CHP/DWP agreement to displayed precision.
- No probability, confidence-level, or universal-invariance claim is made from the ten deterministic realizations.
