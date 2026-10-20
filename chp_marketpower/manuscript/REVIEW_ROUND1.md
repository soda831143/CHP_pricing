# Independent draft review — round 1

Date: 2026-10-20 (Asia/Shanghai). Scope: the English `main.tex` draft, its bibliography and model/literature audit, the existing settlement/threshold tables and verification records, and the 2026-10-20 experiment revision. This is an independent in-pair evaluator review under the acceptance criteria committed before the draft was read. No manuscript text, experiment source, or original data was changed by this reviewer.

## Dimension scores

Scores use the precommitted six dimensions, each out of 5. The discussion-draft threshold is 24/30 with every dimension at least 3; an unresolved critical correctness problem overrides the aggregate score.

| Dimension | Score | Evidence and assessment |
|---|---:|---|
| D1 Scientific question and originality | 4.5 | Introduction separates offer-to-price influence from exercisable profit. The two contributions are specific, and interval-flow formulations, prior market-power work, temporal vulnerability, and demand-to-price maps are credited. The strategy domain and selectors are declared rather than generalized to all possible bids. |
| D2 Mathematical correctness and certification | 4.0 | Complete-dual interpolation, common-UC optimality, convex profit on a joint interval, the profit identity, the envelope derivative, and the two-schedule threshold are algebraically sound under the stated assumptions. Algorithm 1 needs an explicit full-coverage condition; the network-settlement identity needs its omitted dual-accounting bridge. |
| D3 Numerical evidence and interpretation | 4.5 | Reported settlement changes agree with source tables. Independent 500/200-query IEEE118 streams are distinguished, the short unamortized workload is retained, and pricing time is not represented as full-profit time. Same-offer transmission comparisons retain separate truthful baselines. |
| D4 Model identity and inherited computational foundation | 4.0 | Direct interval power and ordinary output differences replace differential-power coordinates in exposition; inherited and terminal conditions are addressed. Pricing output, executable output, and unit self-scheduling are distinct. Exactness of the inherited formulation is supported by the separate model audit, while the new contribution is its parametric use. |
| D5 Structure and writing | 4.0 | A complete IEEE-style research draft connects methods, mechanisms, and four results subsections. It avoids development-stage codes and a run-log narrative. A few certificate/selector sentences can be tightened, and the abstract can represent the fourth timing workload more explicitly. |
| D6 Citation, integrity, and delivery | 4.0 | Twelve internally consistent bibliography entries support the inherited concepts and formulation boundary. Data/code records are identified. Compilation and final cross-references were still being checked by the main agent at review time; author metadata is inherited from the supplied template and still merits author confirmation before submission. |
| **Total** | **25.0/30** | **Meets the discussion-draft score threshold; revise the full-coverage condition before treating Algorithm 1 as a certified whole-domain procedure.** |

## Failure condition checks

- No invented numerical experiment, repeated timing sample, or unsupported new optimization is detected in the reviewed manuscript/source records.
- No algebraic error is found in the core profit identity, finite-endpoint argument, selected-price interpolation proposition, or threshold formula.
- No conflation of physical UC, convexified pricing output, and unit self-scheduling is detected.
- No reference-independent causal interpretation is assigned to the energy/congestion split. The G1 reference-bus zero and bus-23 re-expression are handled correctly.
- No universal conclusion about congestion and market power is drawn from the single-line intervention. The relaxed-network results are fixed-offer comparisons, not a newly optimized relaxed-network profit maximum.
- No first-ever claim is made for CHP market power, price derivatives, LOC algebra, or the inherited network-flow formulation.
- **One algorithmic completeness gap remains in the written pseudocode** (R1 below). The archived completed results themselves have full-coverage verification; the concern is what the stated algorithm permits when its budget expires.
- Compilation, final figure fit, and resolution of all references were outside this review's completed checks and remain with the main agent.

## Review body

### R1 — Require complete interval coverage before returning a whole-domain maximum [P1]

**Location in reviewed draft:** `main.tex`, Algorithm 1, approximately lines 203–212; whole-domain interpretation near lines 301 and 345.

The pricing loop runs while an uncertified bracket remains **within budget**, but after budget exhaustion the pseudocode proceeds directly to physical partitions, endpoints, and maximization. A finite-candidate theorem only covers the union of certified joint intervals. Without an explicit coverage check, the pseudocode permits an incomplete map to be presented as evaluation of the entire declared offer domain.

**Minimal correction:** after the pricing loop, require that accepted pricing intervals cover `[0, delta_bar]` without gaps; after physical-region construction, require the analogous full physical coverage. If either fails, return a checkpoint and unresolved intervals rather than a whole-domain maximum. The interval and endpoint tolerances should be numerical acceptance criteria, not substitutes for coverage. A short `Require certified complete partitions` statement would also be correct if the implementation intentionally delegates their construction elsewhere.

**Acceptance:** Algorithm 1 cannot exit on a budget limit and nevertheless claim certified full-domain optimization. No new experiment is needed to fix the exposition.

### R2 — Show the network-settlement accounting step [P2]

**Location in reviewed draft:** `main.tex`, approximately lines 260–270.

The formula is correct, but the text jumps from pricing complementarity/strong duality to the system identity without showing how reported unit self-scheduling enters. This is an economic relation used later to interpret the observed uplift reduction, so a compact derivation improves both verifiability and interpretation.

Using `M_i = hat{Pi}_i^{SS}` and the declared nodal-price sign, exact unit convexification gives

\[
v^{CHP}=\sum_{n,t}\lambda_{n,t}^{CHP}D_{n,t}
-\sum_{\ell,t}(\mu_{\ell,t}^++\mu_{\ell,t}^-)F_\ell-\sum_i M_i.
\]

Physical balance and the PTDF definition give

\[
\sum_i\lambda_i^\top p_i^{UC}-\sum_{n,t}\lambda_{n,t}^{CHP}D_{n,t}
=-\sum_{\ell,t}(\mu_{\ell,t}^+-\mu_{\ell,t}^-)f_{\ell,t}^{UC}.
\]

Substitute these into `sum_i U_i = sum_i M_i - sum_i lambda_i^T p_i^{UC} + v^{UC}` to obtain the displayed transmission adjustment and identity. Both objective values use reported costs. Stating exact power–cost convexification as the supporting condition makes the connection to the inherited formulation explicit.

**Acceptance:** add these bridges in concise form, without turning the section into a second general CHP derivation. The two stored cases already check the final identity to about `1.46e-10` USD.

### R3 — Distinguish exact propositions from numerical acceptance in the paper [P2]

**Location in reviewed draft:** approximately lines 159, 168, 275, 316 and 368.

The exact mathematical statements are appropriately written, but the paper currently sends numerical thresholds to an unspecified separate record. The unusually small displayed residuals demonstrate arithmetic consistency; they are not themselves an account of MIP global-gap acceptance, common-witness feasibility, or completeness tolerances.

**Minimal correction:** add one short reproducibility sentence or compact supplement pointer that names the actual certificate record and distinguishes primal feasibility, complete-dual stationarity/strong duality, UC optimality gaps, and domain coverage. Do not invent new tolerances; quote the actual saved protocol. If numerical residuals and certificate tolerances differ, present them as different quantities.

**Acceptance:** a reader can locate the numeric criteria used to accept the partitions and understand why the exact propositions apply numerically. No denser scan is requested.

### R4 — Keep the hourly control's claim matched to its evidence [P3]

**Location in reviewed draft:** approximately line 349.

The stated zero maximum is supported by the saved affine price selector, two common physical regions, four endpoint/plan candidates, and recomputed settlement. The revision record correctly says unit self-scheduling uses saved solver bounds rather than newly recovered unit response trajectories. The manuscript does not currently claim a new solve, so there is no false assertion to remove.

**Optional improvement:** say `the maximum additional profit is zero` instead of `no positive maximum additional profit`, and point the supplementary evidence to the hour-1 certification record. Maintain the distinction between this numerical chosen-selector conclusion and all legal dual/physical tie selections.

### R5 — Make the abstract's timing summary fully representative [P3]

**Location in reviewed draft:** abstract, approximately line 27.

The abstract lists three favorable ratios, while the body correctly retains four independent workloads including the 200-query 118-bus ratio below one. The abstract claim is literally supported, but can summarize the useful workload dependence more directly.

**Optional improvement:** state that the two 30-bus workloads reach 6.74 and 20.54, while the longer 118-bus workload reaches 2.00 after amortization. A short statement that the shorter workload has not amortized its map construction makes the computational message complete without a defensive qualification.

### R6 — Final author and availability checks [P3]

**Location in reviewed draft:** author block and Data and Code Availability section.

The author block is inherited from the user-supplied template rather than created from inference. Retain it as author-confirmation metadata before submission. The availability statement currently names the repository and the result directory; once this revision is pushed, record a stable commit/tag in the accompanying manuscript record so the new 500-query reorganization, hour-1 control, and exact draft version remain identifiable. The earlier published commit alone would not identify the new revision.

## Source checks performed

The reviewer read the full draft and bibliography, the inherited-model/literature audit, `paper_results/verification.json`, the revised verification and experiment explanation, and the existing network-settlement, threshold-prediction and six-generator settlement source tables. Specific checks include:

- G1 settlement: `4385.60611753 - 578.35752547 - (-4004.30651014) = 7811.55510221` USD.
- Network identity: truthful `(2814.52471974 + 548.25689738)` equals offered UC–CHP gap; best-offer `(1401.57271428 + 334.54943685)` does likewise within the recorded residual.
- Predicted thresholds and the stated online-cost sensitivity match the four source rows; equal startup counts are treated as a controlled threshold explanation, not an additional strategic startup-cost direction.
- Independent 118-bus workloads use distinct saved streams. Their total parametric times are `311.60282560` and `311.59933730` seconds; rounding both to `311.60` in the paper is correct.
- The chosen hour-1 case has full-domain numerical coverage and four candidate records; its claimed maximum additional profit is zero under the declared selector/witness scope.

This reviewer did not independently browse and revalidate every DOI against publishers, rerun optimization, or inspect the compiled PDF. The separate literature audit and numerical verification records are evidence used here, not independent reruns claimed by this review.

## Evaluator decision

**Revise and accept as a complete discussion draft after R1 and R2 are addressed and the main agent confirms successful compilation.** R3 should be resolved with the existing protocol before the draft is treated as ready for external review. R4–R6 are targeted clarity and handoff checks. The current draft has a coherent scientific argument and a sound core mechanism; no additional broad offer search or new experimental direction is needed to address this review.

The independent review did not change the manuscript or rerun any solver. Submission readiness still requires author confirmation, final compilation/layout review, and a stable public version of the new draft and supporting records.
