# CHP market power: literature and direct-power model audit

> 本文件保留初版12条文献核查；第二版新增的竞价激励、自调度策略和参数LP教材条目及核实来源见REVISION_02.md，当前文献库共15条。

Date: 2026-10-20. This file records source checks and recommended model statements for the new manuscript. It does not change any historical experiment or claim a new CHP convexification algorithm.

## 1. Evidence and citation corrections

The local `paper/primal/Network-Flow-Based_Formulations_for_Convex_Hull_Pricing_With_Maximum_Start-Ups.txt` is a saved conversation, not a faithful article transcript. Its instructions and model claims were not used as evidence. The nine-page PDF was read directly, including equations (3)--(6), its initial-state discussion, and Theorem 1. The local `Polynomial time algorithms...txt` is an explicitly selected extract of the 2016 preprint; its author order differs from the 2018 published article. The formal publication controls the bibliography.

The old `chp_5th.tex` and its bibliography supply writing conventions and project context. They are not cited as a published source, and their numerical examples are not merged with the current market-power archive.

| BibTeX key | Verified publication metadata | Primary evidence and correction |
|---|---|---|
| `gribik2007` | P. R. Gribik, W. W. Hogan, S. L. Pope, *Market-Clearing Electricity Prices and Energy Uplift*, working paper, Dec. 2007 | [Harvard record](https://www.hks.harvard.edu/publications/market-clearing-electricity-prices-and-energy-uplift). No DOI asserted. |
| `hua2017` | B. Hua and R. Baldick, TPWRS 32(5), 3814--3823, 2017; DOI 10.1109/TPWRS.2016.2637718 | [Author's published PDF](https://users.ece.utexas.edu/~baldick/papers/convex_hull_2017.pdf), [author preprint record](https://arxiv.org/abs/1605.05002). DOI contains online year, not issue year. |
| `pan2018` | Y. Guan, K. Pan, K. Zhou, IISE Transactions 50(8), 735--751, 2018; DOI 10.1080/24725854.2017.1397303 | [Publisher issue listing](https://www.tandfonline.com/toc/uiie21/50/8), [author preprint](https://arxiv.org/abs/1608.00042). The 2016 PDF begins Pan, Zhou, Guan; use published author order Guan, Pan, Zhou. |
| `yu2019` | Y. Yu, Y. Guan, Y. Chen, *An Extended Integral Unit Commitment Formulation and an Iterative Algorithm for Convex Hull Pricing*, TPWRS 35(6), 4335--4346, **2020**; DOI 10.1109/TPWRS.2020.2993027 | [Author preprint](https://arxiv.org/abs/1910.12994), local bibliography, author reference in the network-flow PDF. The key is historical; printed year must be 2020. |
| `networkflow` | Y. Yu, T. Zhang, Y. Guan, TPWRS 37(2), 1198--1206, **2022**; DOI 10.1109/TPWRS.2021.3100560 | [IEEE article](https://ieeexplore.ieee.org/document/9520137/), local published PDF. Online publication 2021-08-20; issue year 2022. |
| `andrianesis2022dw` | P. Andrianesis, D. Bertsimas, M. C. Caramanis, W. W. Hogan, TPWRS 37(4), 2578--2589, 2022; DOI 10.1109/TPWRS.2021.3122000 | [Harvard record](https://www.hks.harvard.edu/publications/computation-convex-hull-prices-electricity-markets-non-convexities-using-dantzig-wolfe), [MIT accepted manuscript](https://dspace.mit.edu/entities/publication/269fd8c1-1cdb-470a-a9aa-d78d6acd5f60). Early preprint records may omit Bertsimas; the published four-author record governs. |
| `sun2020market` | J. Sun, N. Gu, C. Wu, *Poster: Market Power in Convex Hull Pricing*, ACM e-Energy, 2020; DOI 10.1145/3396851.3403510 | Local ACM published PDF front matter, [DOI](https://doi.org/10.1145/3396851.3403510). Include Nan Gu even though the Chinese paper's reference omits that author. No page range guessed. |
| `sun2021strategic` | J. Sun, N. Gu, C. Wu, *Strategic Bidding in Extended Locational Marginal Price Scheme*, IEEE Control Systems Letters 5(1), 19--24, **2021**; DOI 10.1109/LCSYS.2020.2999105 | [Author publication list](https://www.wuchenye.cn/publications.html), [IEEE CSS January 2021 issue digest](https://ieeecss.org/sites/ieeecss/files/documents/pcd/CSS_Publications_Content_Digest_012021.pdf). Some author listings use 2020 online year; use the 2021 issue year. |
| `wu2021potential` | C. Wu and J. Sun, *Analysis Method for Potential Market Power of Electricity Market in Convex Hull Pricing Mode*, Automation of Electric Power Systems 45(6), 101--108, 2021; DOI 10.7500/AEPS20200408007 | Local published PDF, pp. 101 and 108, including its own English title and DOI. Romanized authors and official English title avoid inventing a translation; note “In Chinese.” |
| `sun2021temporal` | J. Sun and C. Wu, *Temporal Vulnerability Assessment for Convex Hull Pricing*, ACM e-Energy 2021, 124--136; DOI 10.1145/3447555.3464862 | Local ACM PDF front matter; [author list with page range](https://www.wuchenye.cn/publications.html), [DOI](https://doi.org/10.1145/3447555.3464862). |
| `jiang2026minkowski` | W. Jiang and C. Wu, EPSR **262**, article **113675**, **January 2027**; DOI 10.1016/j.epsr.2026.113675 | [Publisher article](https://www.sciencedirect.com/science/article/pii/S0378779626009685). Online DOI year 2026 and assigned issue year 2027 differ. Preserve the project key; print the assigned 2027 volume year. |
| `zhao2023dependence` | F. Zhao, D. A. Schiro, J. Zhao, T. Zheng, E. Litvinov, TEMPR 1(4), 227--236, 2023; DOI 10.1109/TEMPR.2023.3319159 | [Author manuscript](https://optimization-online.org/wp-content/uploads/2021/06/8455.pdf) supports the substantive claim; the DOI identifies the formal journal record. Optional supporting citation for price preservation. |

DOI links identify articles; article meaning was checked against original paper text or primary author/publisher material. Browser failures opening the ACM full records and Taylor & Francis full text were not treated as verification. ACM metadata came from the local published PDFs and author list instead. No retracted/erratum status claim is made.

## 2. What the model can inherit

The old paper's sequence is useful: physical UC and costs → joint power--cost epigraph → convexified pricing → executable schedule versus pricing point versus unit response → settlement. Retain it in a short market-model section. The new work should devote its method space to objective-parametric CHP, certified physical regions, finite candidate profits, and economic attribution.

The new paper can use the same capacity, asymmetric normal-ramp, startup/shutdown-ramp, inherited-state, residual minimum-time, and convex PWL cost conventions. Define (p^{UC}) as the executable system schedule, (p^{CHP}) as the convexified pricing point, and (p^{SS}) as the individual best response. The last object need not satisfy system balance or transmission constraints. (U_g) is the current model's **uplift payment**, namely full reported LOC. It is not a claim about every ISO's make-whole implementation.

Use actual power variables in the formulation. There is no need to carry the old differential-power variables or generalized-polymatroid theorem into this paper. The current engine already has direct interval-power variables: `chp_energy/chp_solver/chp_master_lp.py` has capacity bounds on interval absolute output, adjacent-period ramp inequalities, inherited-output bounds, startup/shutdown bounds, and perspective PWL epigraph rows. `price_vulnerability/persistent_chp.py` changes only the strategic objective direction and re-extracts the complete dual. Thus replacing the manuscript's differential coordinates is a presentation aligned with the existing model; it does not itself warrant rebuilding historical experiments.

This was checked both in the working file and in Git `HEAD`, which match for that engine file. For any older differential-coordinate archive, the equivalent direct-power map is (p_{e,t}=z_ep_e^{ref}+\sum_{k=a_e}^t v_{e,k}\), with inverse (v_{e,a_e}=p_{e,a_e}-z_ep_e^{ref}\) and (v_{e,t}=p_{e,t}-p_{e,t-1}\) thereafter. Capacity bounds imply (p_e=0\) when (z_e=0\), and the inverse then gives (v_e=0\). Applying this invertible map to the complete unit block, costs, and system coupling preserves its physical power--cost projection. It does not assert that bases, solver paths, matrix sparsity, or measured computation times are identical between coordinate systems. Historical timing remains tied to its archived engine identity.

## 3. Recommended direct-power block

For generator (g), let a source--sink DAG path select legal maximal ON/OFF intervals after enforcing inherited minimum-time conditions. Let (z_{ge}) be the nonnegative unit-flow weight on arc (e), and for an ON interval (e=[a_e,b_e]), let (p_{ge,t}) be its **scaled absolute power**. For each retained ON interval,

\[
P_g^{\min}z_{ge}\le p_{ge,t}\le P_g^{\max}z_{ge},\qquad t\in e,
\]
\[
-R_g^{\downarrow}z_{ge}\le p_{ge,t}-p_{ge,t-1}
\le R_g^{\uparrow}z_{ge},\qquad t=a_e+1,\ldots,b_e.
\]

If the interval begins with an actual startup, impose (p_{ge,a_e}\le S_g^{\uparrow}z_{ge}). If it continues an initially online run with inherited output (p_g^{init}), impose

\[
(p_g^{init}-R_g^{\downarrow})z_{ge}\le p_{ge,1}
\le(p_g^{init}+R_g^{\uparrow})z_{ge}.
\]

The inherited interval's first period is written 1 here; use 0 if the main manuscript is zero-indexed. If the ON interval actually shuts down within the horizon, impose (p_{ge,b_e}\le S_g^{\downarrow}z_{ge}). Do not impose terminal shutdown on an interval that reaches the last period and remains online.

Write the true incremental PWL cost as (\phi_g(q)=\max_k\{a_{gk}q+b_{gk}\}), with (q=p-P_g^{\min}u\). Its scaled epigraph can be written

\[
\eta_{ge,t}\ge
a_{gk}(p_{ge,t}-P_g^{\min}z_{ge})+b_{gk}z_{ge},\qquad k\in\mathcal K_g.
\]

The strategic adder can remain in the objective as

\[
\delta\sum_{e\in\mathcal E_g^{on}}\sum_{t\in e}
\bigl(p_{ge,t}-P_g^{\min}z_{ge}\bigr),
\]

rather than changing these rows. This explicitly produces a fixed feasible matrix and an affine objective. Add true no-load costs for each online period and startup/shutdown costs once per actual transition. An initially online interval does not incur a new startup charge merely because the horizon begins; an interval continuing through the end does not incur an artificial shutdown charge.

Aggregate absolute power by

\[
p_{g,t}=\sum_{e\in\mathcal E_g^{on}:t\in e}p_{ge,t},\quad
u_{g,t}=\sum_{e\in\mathcal E_g^{on}:t\in e}z_{ge}.
\]

The standard flow equation is (B_gz_g=b_g, z_g\ge0), with one unit entering the source and leaving the sink. It represents a convex mixture of legal commitment paths. Joint cost convexification comes from the interval perspectives and path decomposition, not from a claim that the entire network-constrained system LP has integer commitment.

### Exactness conditions

The direct interval construction is exact for the stated physical unit set when (i) each graph path is a legal commitment trajectory; (ii) all retained interval power sets include the correct startup, shutdown and inherited-state constraints; (iii) interval feasible sets and costs are local once the interval and inherited state are fixed; and (iv) all quantities sharing an interval are scaled by the same arc weight. Distinct ON intervals are separated by OFF operation, which resets power to zero. A fractional feasible flow decomposes into paths; normalizing each nonzero interval power/cost block and assigning it to every path using that arc gives the required convex combination. Zero-weight interval output is zero by capacity bounds; upward cost slack is handled as epigraph slack.

This argument permits the current heterogeneous/asymmetric ramp coefficients because they remain linear local interval constraints. It does not establish arbitrary nonlocal daily-energy constraints, fuel budgets, reserve coupling, variable initial states, or cycle-dependent degradation without additional state/model work. The current results use fixed inherited states and fixed startup/no-load accounting.

The maximum-startup paper's counted-state construction is an extension: its Section II first gives the uncounted interval-flow block, then duplicates graph nodes by startup order. Merely citing that paper does not mean the current model imposes (\sum_t v_{gt}\le Q_g^{max}\). Do not add this assertion or recycle (Q_g) (the new paper's exposure) as a startup bound.

## 4. Economic and novelty boundaries

| Prior result | Appropriate inherited claim | New paper's supported capability |
|---|---|---|
| Gribik et al.; Hua--Baldick | CHP uses the convexified cost problem / Lagrangian dual; joint feasible set and convex cost envelope matter. | Keep the unit model fixed while constructing a reusable continuous-offer price map. |
| Guan--Pan--Zhou; Yu et al. | Direct-power interval dispatch and integral extended formulations are established tools. | Combine the pricing map with executable UC and self-scheduling settlement, rather than claim a new exact CHP engine. |
| Sun--Gu--Wu poster and strategic-bidding paper; Wu--Sun Chinese paper | CHP strategic profit, offer manipulation, profit decomposition, and removal-cost-related bounds already exist in their stated models. | Resolve actual profits along a declared one-dimensional offer domain with full multi-period physical execution and reported LOC, and quantify execution-selection effects. |
| Sun--Wu temporal vulnerability | Offer-to-CHP Jacobians and temporal influence are established; not a first discovery of price sensitivity. | Show when measured price influence translates into true profit after exposure and physical execution change. |
| Jiang--Wu | Offline demand-to-price maps and structural CHP interpretation already exist. | Use an offer-to-price map and finite candidates for settlement-aware strategic evaluation; the parameter and economic target differ. |
| Zhao et al. | Preserving one physical UC optimum is insufficient to establish price preservation under a changed primal model. | Match model identity and full-dual certificates, retain network-specific baselines, and reconstruct changed-network pricing rather than reuse an invalid map. |

For the new core identities, write (C_g^{bid}(s;\delta)=C_g^{true}(s)+\delta Q_g(s)\), with (Q_g=\sum_t(p_{gt}-P_g^{min}u_{gt})\) for the all-hours incremental-energy offer. Under full reported LOC,

\[
\Pi_g=M_g^{bid}(\lambda_g^{CHP},\delta)+\delta Q_g^{UC}.
\]

For a shared price and offer, the difference across tied executable schedules is (\delta(Q_g^{UC,A}-Q_g^{UC,B})\). On a differentiable shared-price/shared-UC region, the envelope derivative is

\[
\Pi'_g=(p_g^{SS})^\top(\lambda_g^{CHP})'
+Q_g^{UC}-Q_g^{SS}.
\]

Attribute these as settlement-based characterizations applied to the full model, not a first-ever CHP profit decomposition. If the chosen price is affine and one executable schedule is jointly optimal on the interval, (M_g^{bid}\) is a supremum of affine functions and (\Pi_g\) is convex there. Endpoints suffice for the maximum on that closed branch. At UC, price-rule, or settlement changes, evaluate the declared boundary selection and relevant one-sided branch limits separately. A finite result on this one-dimensional strategy set is not maximum market power over arbitrary startup/no-load/multidimensional bids.

Energy/congestion components depend on the PTDF reference. With nonnegative upper/lower line multipliers,

\[
\lambda_{n,t}^{CHP}=\lambda_t^E
-\sum_l H_{ln}(\mu^+_{lt}-\mu^-_{lt}).
\]

The nodal total is invariant to a consistent reference change. A zero explicit congestion term at the reference bus does not establish zero network influence. Always distinguish CHP-LP multiplier evidence from physical-UC flow evidence and use each network's own truthful-profit baseline.

## 5. Writing recommendations

Present the two contributions as (1) parametric CHP and finite strategic-offer evaluation, and (2) economic mechanisms linking prices, physical substitution, and uplift. Organize the established exact interval formulation as the computational foundation in a compact model section; the new parametric/settlement sections should contain the method detail. Do not reproduce the old generalized-polymatroid proof, call the graph construction novel, or restate development codes as scientific results.

Use constructive, specific sentences. State the scientific scope once in the market model, put numerical assertions beside the figure/table that supports them, and explain the reference-dependent price allocation in the price-mechanism subsection. A claim about the observed line-30 intervention stays a paired, same-offer causal comparison unless a separate relaxed-network full-domain optimization has been completed.

The bibliography intentionally retains historical project keys `yu2019`, `pan2018`, and `jiang2026minkowski`; printed bibliographic fields are authoritative. New draft text should avoid spelling a year from the key. Citation keys available: `gribik2007`, `hua2017`, `pan2018`, `yu2019`, `networkflow`, `andrianesis2022dw`, `sun2020market`, `sun2021strategic`, `wu2021potential`, `sun2021temporal`, `jiang2026minkowski`, `zhao2023dependence`.
