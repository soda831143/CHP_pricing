# Verification review of revision 05

Date: 2026-11-03. Mode: `academic-paper-reviewer` re-review, using field analysis, an editorial verification pass, and synthesis. The governing feedback is the user's first pasted assessment, “从解释优化结果转向揭示市场力形成机制”. The second pasted prompt is contextual guidance. The author's response is [REVISION_05.md](REVISION_05.md).

This is an internal verification review by a separate agent that did not write or edit the manuscript. It is not external journal peer review. The review applies the source-grounding and claim-boundary discipline of the Nature skills within the requested re-review structure. It does not represent a mutually blind Nature reviewer panel or predict a publication decision.

## Decision

**Accept for the scope of this revision.** The manuscript addresses the first assessment's central request. It explains how G1 accumulates additional profit, then uses costly competing generation to explain a boundary of that opportunity. No unresolved blocking mathematical or economic interpretation defect was identified in the reviewed source.

This decision concerns scientific argument and source consistency. Compilation, final PDF layout, repository cleanup, and GitHub synchronization are separate delivery checks owned by the coordinating agent. Their status must be read from the final delivery records.

## Review packet and field analysis

The primary field is electricity-market optimization, with multiperiod unit commitment, convex hull pricing, and strategic producer settlement. The work combines a parametric computational method with a deterministic mechanism case study. Its demonstrated economic scope is G1 in the modified IEEE 30-bus system, along declared all-day and hour-1 offer directions. IEEE 30-G2 and IEEE 118-G11 supply pricing-computation evidence.

The complete [main.tex](main.tex) was read. The reviewed version has SHA-256 `3df12a0c7d6a751342f8026aa7dfc50a94bffebfaed38c6a3894a594e25ffce4`. Line pointers below refer to that version; labels and section titles are the stable anchors. The packet also included the Chinese abstract, argument plan, terminology ledger, existing bibliography and literature audit, and the following numerical records.

- [Base analysis and path account](../paper_results/analysis_summary.json), [settlement source table](../paper_results/source_data/table_II_settlement_changes.csv), and [hourly price effects](../paper_results/source_data/price_effect_by_hour.csv).
- [Physical switching costs](../paper_results/revision_20261021/source_data/physical_switching_costs.csv), [fixed-offer factorial settlements](../paper_results/revision_20261102/source_data/factorial_settlements.csv), and [frozen-schedule cost comparisons](../paper_results/revision_20261102/source_data/frozen_competition_predictions.csv).
- [Offer-timing comparison](../paper_results/revision_20261020/source_data/temporal_offer_comparison.csv), [four measured pricing workloads](../paper_results/revision_20261020/source_data/table_I_four_workloads.csv), and the existing numerical verification summaries.

Local original-paper extracts and the existing literature audit support the reading of Sun–Gu–Wu, Sun–Wu, and Wu–Sun. Publisher and author records were consulted for bibliographic spot checks. No new paper or citation was proposed. DOI-access failures were not treated as successful full-text verification. In particular, the assigned January 2027 volume metadata for Jiang–Wu is supported by the [publisher article record](https://www.sciencedirect.com/science/article/pii/S0378779626009685), despite the 2026 DOI year.

## Revision response checklist

### Priority 1 — Required revisions

All author claims in this table refer to the numbered response rows in `REVISION_05.md` and were checked against the manuscript itself.

| ID | Original concern | Author's claim | Response status | Verified revision location | Verified? | Quality assessment |
|---|---|---|---|---|---|---|
| R1 | The research question should explain profitable opportunity, not center the validity of a threshold. | Rows 1–4 replace the title and opening and organize the account around accumulation and substitution. | FULLY_ADDRESSED | Title and abstract, lines 21–27; Introduction, lines 33–38; IV opening, lines 367–368. | Yes | The economic question precedes the interval machinery and remains the organizing question in the conclusion. |
| R2 | Explain why G1 first earns about USD 7,812. | Rows 3–4 make the local derivative and complete path account central. | FULLY_ADDRESSED | IV-A, `eq:identity`, `eq:derivative`, `eq:path-ledger`, lines 370–399; V-A, lines 492–502. | Yes | The USD 8,741.60 price-response accumulation is connected to exposure and physical-switch contributions. The threshold no longer substitutes for an explanation of profit formation. |
| R3 | Distinguish final settlement accounting from the offer-path explanation. | Row 5 assigns separate roles and output weights to the two accounts. | FULLY_ADDRESSED | IV-A, line 399; V-A, Table I and lines 494–500. | Yes | Actual energy revenue uses physical output. The path price term uses the best self-schedule. Neither is presented as an independently identified causal share. |
| R4 | Preserve complete physical execution and the correct reported-cost settlement definition. | The mathematical-retention response preserves all three dispatch objects, full reported LOC, and branch evaluation. | FULLY_ADDRESSED | II, `eq:ss`–`eq:profit`, lines 168–189; III-D, lines 289–324. | Yes | Physical UC, convexified pricing, and individual self-scheduling use consistent unit conventions and retain their different roles. Actual profit uses actual cost. |
| R5 | Give a rigorous substitution-cost perspective without claiming the complete frontier was computed. | Row 7 defines the truthful global baseline, feasible reduction range, and nonnegative-adder value identity. | FULLY_ADDRESSED | IV-B, `eq:substitution-frontier` and `eq:frontier-value`, lines 404–418. | Yes | The proof establishes the identity without assuming frontier convexity. It distinguishes offer exposure from minimum required total generation and states the numerical study's two-schedule scope. |
| R6 | Tell the physical story of early G5 operation before the algebraic crossing. | Row 6 introduces the extra five hours and their energy and expense. | FULLY_ADDRESSED | V-B, lines 511–520; Fig. 2, `fig:substitution`. | Yes | The additional system cost per removed MWh is interpretable before the threshold equation is evaluated. A/B optimality support remains a necessary condition. |
| R7 | Separate an existing substitute becoming expensive from a new alternative becoming feasible. | Rows 8–9 distinguish the online-cost perturbation from line relaxation and move detailed exclusion mathematics to the appendix. | FULLY_ADDRESSED | IV-C, lines 449–464; V-C, lines 522–541; Appendix B, `eq:competitor-exclusion`. | Yes | The supported 13.204 to 13.442 shift and the admission of C have different economic meanings. Rectangle-wide exclusion of A/B is distinguished from pointwise optimality support for C. |
| R8 | Use profit, substitution, changed conditions, then computation as the result sequence. | Row 11 adopts the four requested subsections and four figures/two tables. | FULLY_ADDRESSED | V-A/B/C/D, lines 471, 504, 522, and 543; `fig:profits`, `fig:substitution`, `fig:competition`, `fig:timing`. | Yes | The reader sees the opportunity and its economic explanation before the measured reuse evidence. |
| R9 | State two contributions without repackaging established CHP profit decomposition or sensitivity as new. | Rows 2 and 12 combine the computational chain and make the second contribution an economic capability. | FULLY_ADDRESSED | I-A, lines 40–47; I-B, lines 49–53; V-D, lines 563–567. | Yes | Sun–Gu–Wu profit decomposition/maximal markup and Sun–Wu temporal sensitivity are expressly credited. The inherited network-flow formulation is a foundation, not a claimed new engine. |
| R10 | Move reference-node component accounting and extensive certificates out of the economic foreground. | Rows 9–10 and 13 move auxiliary algebra and detailed accounts to appendices/source data. | FULLY_ADDRESSED | Appendix A, lines 575–584; Appendix B, lines 586–600; Appendix C, lines 602–630. | Yes | The network mechanism in the main results is the feasible competing schedule and its settlement. The reference-dependent zero congestion component at G1 is not interpreted as zero network effect. |
| R11 | Retain necessary theory, including finite evaluation and boundary behavior. | The mathematical-retention response preserves convexity, endpoint candidates, and one-sided supremum statements. | FULLY_ADDRESSED | III-D, `prop:finite`, `eq:candidate-value`, `eq:supremum`, lines 289–324; IV-A, lines 378–397. | Yes | The finite result is conditional on a covering partition, affine selected prices, common physical schedules, and complete reported LOC. Boundary execution is specified rather than hidden. |
| R12 | Avoid turning more threshold validation into the research objective. | Rows 13–15 focus the primary displays and reuse existing optimization evidence. | FULLY_ADDRESSED | V-A–D and Conclusion; `REVISION_05.md` figure/evidence allocation. | Yes | The presentation has a single accumulation/substitution case and two controlled changes in competition. The review found no need for another comparable validation campaign to establish these claims. |

### Priority 2 — Suggested revisions and scope choices

| ID | Suggestion | Response status | Verified response |
|---|---|---|---|
| S1 | Add a complete comparator generator if making general claims about which generators have more profitable market power. | DELIBERATE_LIMITATION | Response row 16 retains a reusable method and G1 mechanism case. Table I records other producers' settlement when G1 changes its offer; it is not a ranking of their own optimal strategies. No unsupported cross-generator ranking is claimed. |
| S2 | Match another pricing/compensation rule if claiming a cause unique to CHP. | DELIBERATE_LIMITATION | Response row 17 and the title use “under CHP”. The model states complete reported LOC. The economic conclusion does not claim that the substitution mechanism is unique to CHP. |
| S3 | Do not impose a ten-page compression target at this stage. | FULLY_ADDRESSED | Response row 18 and `DRAFT_PLAN.md` remove the compression target while retaining the model, method, and proofs. This review makes no page-count acceptance requirement. |

These two deliberate economic scope choices are consistent with the conditional wording of the original recommendations. They do not leave a required claim unsupported.

## Technical verification

The full-LOC identity follows by substituting uplift into actual profit. On an interval with a common physical schedule and differentiable self-scheduling value, the envelope derivative is the selected price response weighted by an optimal self-schedule plus the physical/self-scheduled exposure difference. The selected price is continuous because adjacent accepted intervals share their endpoint dual. Consequently, the stated physical jump is the change in the exposure term. The path account includes a terminal switch only when its outgoing execution is used. An alternative price rule with a jump requires the additional change in the self-scheduling value, which the text states.

The frontier identity uses a truthful globally optimal baseline and nonnegative offer adders. A schedule with exposure above the baseline is weakly dominated by that baseline. For a remaining schedule with exposure reduction r, joint minimization permits q between zero and r; the term minus delta times q is minimized at r. This recovers the physical objective and includes delta equal to zero. The constraints defining the physical schedule set make the bounded set closed, so the declared piecewise-linear cost minima are attained. No convexity of K is needed. Its maximum feasible reduction is defined, not reported as a computed numerical result.

For finite profit evaluation, each fixed self-schedule contributes an affine function on a joint interval. The maximum of those functions plus the affine physical-exposure term is convex, so the two endpoint extensions suffice. Compact unit output and finite operating costs make these branch values continuous. The supremum argument correctly limits alternative execution rules to the same open-region schedules and adjacent boundary choices. It does not silently optimize over every tied system schedule. At the truthful baseline, complete reported LOC makes actual profit independent of the physical tie. Numerical UC cost tolerances are explicitly not described as bounds on dispatch or profit error.

The A/B threshold is an average cost ratio for complete schedules, subject to global and adjacent optimality support. The line-relaxation argument requires only a feasible C cheaper than A/B at the rectangle corners, since each frozen cost difference is affine. This proves exclusion of A/B throughout the stated rectangle. It does not prove C optimal everywhere, and the revised Appendix B keeps those conclusions separate.

## Numerical consistency and corrections verified during review

Fresh read-only arithmetic on the saved source values gave the following results.

| Check | Verified result |
|---|---|
| Offer-path reconciliation | 8741.602192558714 − 29.225307549150628 − 900.821782809915 = 7811.555102199649 USD. Difference from the saved total is about 5.50e-9 USD. |
| Six-unit settlement identity | Maximum absolute source-table residual in delta R + delta U − delta C − delta Pi is about 2.55e-11 USD. |
| Switches before the maximizing incoming branch | The first two switching losses are 769.3506871577993 and 131.47109565211576 USD, totaling 900.821782809915 USD. The terminal 1387.3469913044 USD replacement is excluded for the incoming boundary candidate. |
| Fixed second offer in the relaxed network | Absolute G1 profit is 40511.81463387649 USD at both cost levels. Truthful baseline profit falls by 93.62923239459633 USD, exactly explaining the increase in additional profit. |
| C exclusion rectangle | The minimum saved A/B-minus-C corner difference is 1635.464037952188 USD over the declared offer/cost rectangle. |
| Timing and offer-direction evidence | The four workload rows reproduce the stated 6.74, 20.54, 2.00, and 0.90 ratios. The Q500 and Q200 rows are independent streams. The hour-1 direction has four candidates and zero maximum additional profit. |

Three local issues identified during the review were corrected by the writing/coordinating agents, then verified in the locked source.

| ID | Issue and evidence | Verified correction |
|---|---|---|
| NEW-1 | V-C originally attributed the relaxed-network second-offer gain too loosely to changed prices/self-scheduling. Source settlements show unchanged absolute profit and a lower baseline. | Line 539 now gives the exact baseline explanation. This removes a misleading quote-level mechanism attribution. |
| NEW-2 | Rounded Table I entries can differ from the exact ledger by a cent. G5's displayed components sum to −0.01 USD while its exact profit change is zero. | Line 490 now states that each identity holds before rounding. The path-total paragraph likewise uses unrounded aggregation. |
| NEW-3 | The displayed rounded numerator and denominator of the A/B ratio do not reproduce every printed threshold digit. | Line 516 uses an approximation sign. No underlying result was changed. |

## Residual issues and assessment boundary

No required scientific revision remains open in the reviewed `main.tex`. The strongest supported economic conclusion is that, in this case and offer direction, self-schedule-weighted CHP price responses accumulate profit before costly competing operation changes execution. The cost and network comparisons establish specified changes in competition and settlement. General generator rankings, a computed full substitution frontier, and a mechanism unique to CHP are outside the stated claims.

This pass rechecked formulas, argument order, author-response traceability, and selected numerical arithmetic. It read existing verification records rather than rerunning every underlying UC, CHP, or self-scheduling optimization. It did not independently reproduce all archived experiments on another machine, inspect the final compiled page images, or verify the final GitHub commit. File cleanup and retained witness completeness require the coordinator's dependency and delivery checks.

The coordinator subsequently refreshed the manuscript README to version 05 and recorded the separate PDF build and asset checks in validation.json. The independent review verdict above concerns the locked scientific source; final GitHub and retained-witness completeness are coordinated delivery checks.
