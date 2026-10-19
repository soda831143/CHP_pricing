# Complete reported LOC: profit mechanisms and their limits

Status, 2026-10-18: P1–P2 are proved below and numerically checked by the E0–E1
IEEE30 audit. The recovered IEEE30 E2 raw witnesses now numerically verify P3
in six declared neighborhoods (maximum difference residual 2.19e-7); P4 retains
its common-plan/affine-selector hypotheses and existing endpoint analysis.
See `results/mechanism_20261018/followup/MECHANISM_REPORT.md` for the recovery
audit and the completed E4 directional optimal-price-face checks. These are accounting and
envelope/convex-analysis consequences, not claims of first discovery of CHP
market power, bid-price derivatives, or a general profit decomposition.

## Common assumptions and settlement convention

The complete physical single-unit set S_g is fixed and nonempty. It includes
initial conditions, actual startups/shutdowns, minimum durations, normal and
transition ramps, and capacity bounds. Output p(s), true cost C_g(s), and bid
exposure D_g(s) are finite. For existence/envelope statements, assume S_g is
compact and the objective is continuous (a finite union of bounded polyhedra
with linear/PWL costs suffices). Each time step is one hour.

Only g bids strategically: C_g^rep(s;δ)=C_g(s)+δD_g(s), with
D_g(s)=Σ_t[p_gt(s)−Pmin_g u_gt(s)]. Other units' true and reported costs agree.
All statements use one explicitly declared full-horizon nodal price λ_g(δ).
The IEEE30 experiment uses the original full-dual interpolated CHP selector;
CHP prices are not assumed unique. Let

\[
 M(\lambda,\delta)=\max_{s\in S_g}\{\lambda^\top p(s)-C_g(s)-\delta D_g(s)\}.
\]

For the feasible physical execution s_U, complete reported LOC is

\[
 U=M-[\lambda^\top p(s_U)-C_g(s_U)-\delta D_g(s_U)].
\]

U is nonnegative by single-unit feasibility. In floating-point code, a negative
value beyond tolerance is rejected; it is not silently converted to a different
settlement rule. These are counterfactual complete-LOC payments, not a statement
about any actual ISO's make-whole rules.

## P1. Accounting identity and truthful-dispatch invariance

**Statement.** For any feasible execution s_U (system optimality is unnecessary),

\[
 \Pi^{true}=\lambda^\top p(s_U)+U-C_g(s_U)=M(\lambda,\delta)+\delta D_g(s_U).
\]

At δ=0 and fixed λ, all feasible executions yield the same profit M(λ,0).

**Proof.** Substitute U and cancel λ^T p and C_g(s_U). At δ=0 the remaining
execution-dependent term vanishes. This argument is pointwise: it needs neither
convexity, differentiability, nor uniqueness of the CHP price or UC optimum. □

**Limits/counterexample.** With capped LOC or make-whole-only compensation the
cancellation need not hold. Test `test_missing_full_loc_does_not_satisfy_the_identity`
gives a concrete shortfall. Misreporting capacity changes S_g and lies outside
this fixed-cost-direction model. Unknown true costs prevent empirical evaluation
of true profits even though the formal identity still has meaning.

**Validation.** `mechanism_study.profit_identity.ledger` reconstructs hourly cost
independently of the existing settlement engine. The audit compares them at four
actual IEEE30 bids; δ=0 also settles A/B as *feasible counterfactual executions*,
without pretending those two plans minimize truthful system cost. See
`results/mechanism_20261018/identity_validation.json`.

## P2. Common-price physical-execution profit difference

**Statement.** Fix the same δ, λ, S_g, true cost and complete-LOC rule. For two
feasible executions A and B,

\[
 \Pi^A-\Pi^B=\delta(D^A-D^B).
\]

In particular this holds for two tied globally optimal system UC plans.

**Proof.** Apply P1 twice. M is identical because its arguments and feasible set
are identical, so it cancels. □

**A useful conditional corollary.** If only g is strategic and A/B also have the
same *total reported system cost*, let C_sys^A and C_sys^B denote total true costs.
Then

\[
 \Pi_g^A-\Pi_g^B=\delta(D_g^A-D_g^B)=C_{sys}^B-C_{sys}^A.
\]

Indeed, subtract C_sys^A+δD_g^A=C_sys^B+δD_g^B. This is a pairwise statement at
one fixed bid and price. It does **not** say strategic profit maximization
minimizes social cost as bids change, or that uplift/CHP price selection is irrelevant.

**Limits/counterexample.** A comparison at different legal CHP prices adds the
difference of M values. Total generation is not D when online hours differ:
with Pmin=10, schedules (30,0), u=(1,0) and (15,15), u=(1,1) have equal generation
but exposures 20 and 10. At δ=3 their P2 profit difference is 30, not zero.

**Validation.** The original full-system A/B arrays are rechecked against fresh
global UC lower bounds at δ*=13.204080443599175. Shared 30×24 selected prices and
their complete dual witness are saved in `boundary.npz`. `paired_identity`
operates on independently reconstructed ledgers. No rounded total is an input.

## P3. Local and one-sided profit response

**Statement.** On an open interval assume λ(δ) is differentiable and a fixed
physical plan s_U is used. If the optimal self-schedule is unique, or all optimal
self-schedules have the same directional objective slope, then

\[
 \Pi'(\delta)=p(s_{SS})^\top\lambda'(\delta)+D(s_U)-D(s_{SS}).
\]

**Proof.** Differentiate the maximized self-schedule objective by the envelope
theorem/Danskin, giving M'=p_SS^T λ'−D_SS. Add the derivative D_U of δD_U in P1. □

For a fixed physical plan, energy revenue and LOC derivatives satisfy

\[
 R'=p_U^\top\lambda',\qquad
 U'=(p_{SS}-p_U)^\top\lambda'+D_U-D_{SS},\qquad C_U'=0.
\]

Their sum gives P3. The price channel is weighted by *self-scheduling* output
because energy income and LOC are both price-dependent.

**Degeneracy.** If λ is differentiable but self-scheduling is tied, put
a(s)=p(s)^Tλ'−D(s). Danskin gives M'_+=max_{s in argmax}a(s), and
M'_−=min_{s in argmax}a(s). An arbitrary tied optimizer does not supply both
derivatives. For a piecewise smooth selector, use its corresponding one-sided
price slope and the appropriate extremum. At a physical UC switch, compute the
two plan limits and the P2 jump; a jump has no finite ordinary derivative.
If a chosen physical exposure varies smoothly, the additional δD_U' term is
required; the displayed fixed-plan formula cannot be applied unchanged.

**Limits/counterexample.** The analytic test in `test_profit_identity.py` has
λ=3+δ/2, C(p)=p/2, p∈[0,2], and D_U=1. Profit equals max(5−δ,0)+δ.
At δ=5 the left derivative is 0, the right derivative is 1. Neither an ordinary
derivative nor a centered difference can replace these one-sided statements.

**Validation scope.** The recovered E2 intersects selected-price and common-UC
regions in six prespecified neighborhoods. A common SS witness meets the saved
global upper bounds at both sample endpoints; direct one-sided differences
agree with P3 within 2.19e-7. Zero bid has only a right domain derivative. The
critical UC switch itself has a P2 jump, not an ordinary derivative. Raw saved
prices, physical and SS schedules, selected full-dual interpolation and hashes
were rechecked by `mechanism_study.verify_recovery`; this is a local result,
not a new full-domain derivative or an integral decomposition of the total gain.

## P4. Convexity on a common-plan/affine-price interval

**Statement.** On a closed bounded interval I=[a,b], use one fixed feasible
physical plan, λ(δ)=λ0+δv, and the fixed compact S_g. Then Π is convex and
max_{δ∈I}Π(δ)=max{Π(a),Π(b)}.

**Proof.** For each feasible self-schedule s, λ0^T p(s)−C(s)+δ[v^T p(s)−D(s)]
is affine in δ. Its pointwise maximum is convex. Adding δD_U preserves convexity.
For δ=(1−θ)a+θb, convexity bounds Π(δ) by (1−θ)Π(a)+θΠ(b), hence by the larger
endpoint. Compactness/continuity ensure attainment. □

**Endpoint interpretation.** If the plan or selector is defined only on an open
interval, endpoint *extensions/limits* bound the supremum; they need not be
attained by the actual boundary execution. At a shared UC boundary evaluate each
adjacent optimal plan under the same selected price. Positive δ favors larger D
among these plans. The original optimistic boundary rule is an explicit rule,
not a claim about a real ISO. Existing `TARGETED_STUDY_20261016.md` distinguishes
the maximum from a common supremum under continuous price selection and a complete
exact physical partition. We retain its hypotheses and do not turn a finite MIP
cost tolerance into an exact profit guarantee.

**Limits/counterexample.** Without affine λ, convexity need not hold: take one
feasible schedule, D=0, p=1, C=0 and λ(δ)=1−δ² on [−1,1]. Profit is maximal in
the interior. A plan switch also invalidates applying P4 across the whole domain.

**Validation scope.** Max-affine toy tests and the existing common-plan region
tests are reused. This delivery does not create new global profit curves or
re-run the archived 0–50% optimum calculation.

## Numerical certificate for the complete optimal dual face

For an LP `min c^T x` with `E x=b`, `A x<=h`, and finite variable bounds,
fix a certified optimal primal `x*`. Every dual optimum satisfies stationarity,
dual signs and complementary slackness against `x*`. Conversely, any dual-feasible
vector satisfying those complementarity conditions is optimal: the primal-dual
gap is the sum of nonnegative slack-times-multiplier terms, all zero. Therefore
forcing multipliers of strictly inactive rows/bounds to zero, while retaining
stationarity and signs, describes the same complete optimal dual face. A single
optimal primal suffices even when primal and dual optima are not unique.

In `mechanism_study.linear_audit`, rows/bounds with saved primal slack above
1e-7 are fixed inactive. Smaller numerical slacks are left unrestricted, so
uncertain activity is not silently fixed. Each candidate full dual is then
checked against the ORIGINAL, unscaled stationarity and strong-duality equations
and bounds, with maximum residual below 1e-6. These are numerical certificates
at declared tolerances; the exact-face equivalence above assumes an exact primal
optimum. This formulation avoids using the large cost equality as a solver row,
while retaining it as an independent acceptance check. It does not relax the
economic optimum into an epsilon-cost band or concatenate separate nodal extrema.

## Literature boundary

Sun–Gu–Wu (2020), *Market Power in Convex Hull Pricing*, e-Energy poster,
DOI 10.1145/3396851.3403510: Eq. (10) already separates optimal reported surplus
and reported-minus-true dispatched cost. Its Theorem 1 relates the maximal extra
profit to removal cost under homogeneous capacity, a stylized pool and its
strategy set. Its displayed two-unit inequality is not an unrestricted full-UC
set-function theorem.

吴辰晔、孙健 (2021),《凸包定价模式下的电力市场潜在市场力分析方法》,
45(6):101–108: Eq. (16) already gives the corresponding profit decomposition;
Eqs. (18), (21), (22) distinguish the removal-cost bound, fixed-cost strategies
and variable-cost-only strategies. Its network numerical example precludes a
claim of first considering networks. Those formulas are not imported as exact
equalities for our finite incremental-only strategy and full UC model.

Sun–Wu (2021), *Temporal Vulnerability Assessment for Convex Hull Pricing*:
desired-generation sets, multi-period bid-price Jacobians and VI are prior work.
The main model's whole-horizon ON/OFF restriction is distinct from the complete
switching trajectories here. Jiang–Wu's demand-to-price/Minkowski construction
changes demand rather than the objective's bid direction. Yu/Pan interval/network
flow formulations are computational foundations, not novelty asserted here.

Our present contribution claim is limited to **verified economic consequences of
the existing complete-trajectory CHP/UC/LOC model and its declared selector**.
Controlled physical attribution and any broader empirical regularity remain open.
