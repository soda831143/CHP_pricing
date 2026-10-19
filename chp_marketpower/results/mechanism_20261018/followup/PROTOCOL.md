# Prespecified E2-E4 protocol, original branch, 2026-10-18

The user's updated instruction supersedes the old branch-creation rule. Work
continues on `research/market-power-parametric-regimes`, in this separate results
folder. E0-E1 data and all previous maps/benchmarks remain unchanged.

## E2 before looking at derivative results

Six G1 all-day neighborhoods: zero bid (right only); the first physical UC
switch's immediately following joint-region midpoint; critical bid minus/plus
0.001 USD/MWh; rho=40% and 45%. The finite-difference step is at most 0.001 and
at most one tenth of the distance to each relevant price/UC boundary. At zero,
use 0,h,2h. No new sample neighborhoods are selected by profit.

At most six full-system UC, six CHP and eighteen G1 SS solves, 600 seconds.
Require raw selected full-dual validity, independent UC global bound and full
accounting at every sample. A common SS plan that meets each endpoint's global
maximization upper bound certifies an affine surplus over the small interval;
otherwise retain the point as unresolved and do not assert an ordinary derivative.
Use a fixed channel classifier: dominance at ratio >=2; opposing nontrivial
channels when each magnitude exceeds 25% of the other. These labels are descriptive.

## E3, only after E2's gate

G1/G5/G2, hours 1,5,19. G2 follows the existing baseline least-online positive-
incremental-output rule, not new profit outcomes. Nine physical MRG objectives,
nine convexified MRG objectives, three whole-unit removals. One initial CHP cost
solve supplies the exact existing feasible LP and its matrices, followed by nine
objective-only reoptimizations: **ten actual CHP LP optimizations**, not nine.
To connect these structural quantities with actual profits using one declared
finite strategy set, also evaluate G2/G5 at rho=0, the original G1 critical rho,
and rho=0.5; inherit G1's existing verified values at the same bids. These six
additional full UC/CHP/SS settlements are registered before looking at G2/G5
profit results, and are not a continuous-domain optimum claim. Total upper
budget: **eighteen UC, sixteen CHP and six SS solves**, 600 seconds. Inherit the
already verified truthful baseline cost after checking model identity.

All minima retain global lower bounds and primal/dual residuals. Removal
infeasibility is an outcome, not an arbitrary penalty. MRG=0 is not equated with
zero removal premium or no profitable bids.

## E4 intervention rule, before evaluating treatment profits

Use one network line if its selected CHP dual in hours 1-5 is nonzero. Rank lines
by sum of absolute capacity duals in these hours times the absolute PTDF contrast
between G1 and G5; ties by line index. Relax only the winning line's two-sided
capacity, throughout the horizon, to a documented nonbinding triangle bound.
If no such line exists, consider the visibly active first-hour G1 startup ramp
as the single intervention instead. Do not apply both treatments.

For original and treated models, evaluate the same bids: zero and the original
critical point minus/plus 0.001 USD/MWh. Rebuild the UC, complete CHP and LOC at
every point; never use the original Oracle for the treated model. Use the same
declared cold-start dual-simplex selector, parameter tolerances and seed.
Compare this rule's original prices against the archived original selector.
Keep solver-selected physical execution; use boundary neighborhoods rather than
hiding a choice of optimistic boundary dispatch.

At zero and the higher neighborhood bid, audit coherent extreme optimal-dual
vectors for a frozen all-day G1 exposure direction, by minimizing/maximizing the
same linear price functional over the COMPLETE optimal dual face. Settle at the
resulting complete vectors. These are directional price-face sensitivity checks,
not independent componentwise extrema or a proof of global maximum/minimum profit.
Budget at most 6 UC,6 CHP,14 SS,8 auxiliary LP optimizations; 600 seconds.

Failure and absence of a profitable/causal effect are retained. No additional
lines, units, offer dimensions, bid search, coalition or learning tasks are triggered.
