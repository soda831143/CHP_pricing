# Release checks — 2026-10-17

## UI revision after 804cb9b

- Full suite after the revision: **118 passed**, including22 dashboard and3 native
  job tests. The first full run exposed a real Windows progress-file sharing race;
  bounded read/replace retries and a deterministic sharing-violation test fix it.
- AppTest verifies that only the current page renders (overview2 plots,
  settlement1, price5), shared unit/bus controls, left/right boundary metrics,
  missing-scene isolation and readable parameter tables. Response grids include
  all selected-price knots and match the existing affine selector, not new solves.
- Actual localhost browser verified the revised P/U/S/profit overview, switching
  IEEE118 without stale IEEE30 values, and the two space/time response modes.
- An actual browser-launched IEEE118-G11 zero-bid job completed54-unit settlement.
  A separate25.123456789% offer was stopped at a1-second budget; its saved task
  state was `timed_out` at1.0073s, not a successful settlement. Retrying that same
  offer at600s completed both required baseline/current exact caches in about12.6s.
  Current-result UC/LOC itself took6.125s; baseline took6.060s on this workstation.
  These are UI acceptance timings, not a new paper benchmark or speedup claim.
- At this acceptance offer, G11 baseline/current/extra profit were respectively
  57627.163321 /38107.946382 /−19519.216939USD. Both caches contain54 unit rows;
  maximum physical residual was9.095e-13, accounting residual0 at saved precision,
  maximum self-schedule gap6.822e-12USD. This offer is not claimed optimal or
  representative of the full market-power strategy range. Caches remain local.
- Cancel, timeout, invalid model failure and successful same-quote retry were
  exercised with native subprocess tests. Terminal elapsed time is frozen;
  completed tasks no longer keep increasing their reported duration.
- Offline HTML was re-exported from the same four validated maps. Structural
  checks cover unique element IDs, one visible initial view, inline assets and
  no unresolved export placeholders. This round's browser tool could not inspect
  the user's `file://` tab because its URL policy forbids that protocol. We did
  not bypass the restriction or claim a new complete offline-browser acceptance;
  earlier HTTP offline-page checks below belong to the preceding release.

## Preceding release checks (804cb9b)

- Export verified all four raw/compact/model bindings on the research workstation;
  IEEE118 raw witness remains local. Browser uses the exported scenario only.
- Export reconciled all 1290 all-day and12 hourly saved unit rows against displayed
  price/physical witnesses, costs and profit accounting. Maximum observed monetary
  reconciliation error was zero at stored precision; self-schedule gaps stay below
  the declared1e-5USD export check. This is numerical consistency, not symbolic proof.
- Automated suite: **111 passed**, including18 dashboard checks. Real COPT checks
  cover6-unit settlement at an arbitrary nonsampled bid and global UC plus6-unit
  settlement where no physical map exists. Stale live-model cache and mismatched
  saved monetary rows are rejected by regression tests.
- Streamlit AppTest: first load, precise boundary with two physical choices,
  numeric/slider synchronization, unavailable direction,30-G2,118-G11 switching.
- Actual in-app browser: local Streamlit rendered; self-contained static page
  rendered with no external script/data assets. Static boundary showed45100.87
  and43713.52USD for the two plans. Hour1 upper endpoint showed−106.42USD relative
  G1 profit. Missing hour2 map hid prior results instead of reusing them.
  Local Streamlit at12.3456789% changed from unavailable S to `solved_on_demand`
  after the explicit button completed all6 direct self-schedule settlements.
- Independent Q500 trace:500 real query prefixes, seeded shuffled workload,
  Q224 measured crossing,623.405880s/311.602826s atQ500; no splice withQ200.
- Queue preview marks existing G1/G2 all-day maps as skipped and G3–G6 pending.
  No additional direction was executed for this release. The process interruption
  and disk-limit branches are implemented but were not fault-injected against a
  long COPT build; native checkpoint validation rejects incomplete/corrupt data.

## Review-driven corrections

Current-data identity is checked when reading live caches, not only when starting
a new solve. Saved settlement provenance includes the price and physical archive,
not only the profit-report hash. All exported monetary rows are reconciled against
the actual displayed physical execution. CSS explicitly hides missing UC panels;
numeric bid changes refresh the static page immediately. Diverging heatmaps have
a minimum±1e-6 range to avoid presenting floating-point noise as a price mechanism.

## Environment notes

The optional Python Playwright package and skill server helper were absent;
used Streamlit AppTest and the available browser controls instead, without adding
a dependency. Sandboxed Python emitted Windows temporary-directory cleanup and
pyreadline destructor warnings after successful pytest runs (exit0); no optimizer
or assertion failed. Local browser servers required normal-host loopback access;
both bind only127.0.0.1. No public deployment or license/configuration changes.

The runtime settlement cache is intentionally local/ignored. The export manifest
is a SHA-256 provenance record, not a digital signature. The old retrospective
model binding is disclosed; no new claim of historical snapshot identity is made.

## Price-coverage / mathematical-explanation revision, 2026-10-17

- Added a hash-checked lazy catalog, per-scenario immutable payloads and automatic
  registration after source/model/full-interval independent validation. The local
  app and its UC/LOC worker use the same exact generator/hour lookup. The standalone
  remains the original four curated directions; no 150-map embedded HTML.
- All six IEEE30 all-day price maps are independently checked. Their saved UC maps
  contain respectively 17, 6, 21, 1, 7, 1 common-plan regions for G1–G6. New UC
  archives check full-system feasibility and endpoint global MIP bounds, not only
  the target generator. Shared boundaries retain both adjacent plans.
- Original four curated selectors were independently revalidated to bind reports
  to raw witness and verified model hashes. Their original model and compact price
  selector hashes remain unchanged. Direct validation prices can differ under dual
  nonuniqueness; the release gate uses complete-dual KKT and objective residuals.
- Actual browser: method page rendered equations and an actual archived IEEE30-G1
  interval. Numerical-validation page displayed endpoint/interior residuals,
  zero-offer comparison, source versions and a separate explicit validation action.
- Actual browser: IEEE30-G1 at 16.7% passed a new bounded independent CHP check in
  about 5.7s, with value error 2.04e-10 USD and selected complete-dual gap 1.16e-10 USD.
  This action did not create settlement results or run physical UC.
- Actual browser: new IEEE30-G3 all-day at 16.812345% queried prices and reused UC
  region 8, then completed all six unit self-schedules. S changed to solved_on_demand,
  G3 baseline profit was 0 USD and current profit about 1585.50 USD; percentage was
  correctly undefined for the zero baseline. This is a UI acceptance point, not an
  optimal bid or cross-generator market-power ranking.
- Browser testing found a real completion-rerun widget-cleanup exception not caught
  by the earlier suite. Observation values now have a non-widget backup and recover
  without losing generator/bus/hour. Repeated the browser completion successfully;
  added a regression with persistent context but absent widget state.
- Batch testing found a complete map with coverage-length sum 0.9999999999999999.
  Publication now checks all individual interval-ready flags and full validated
  coverage, rather than exact floating-point equality of the summed fraction.
  An unready interval still fails. The interrupted queue resumes validated archives.
- Read-only code review caught and corrected wrong-direction checkpoint reuse,
  stale compact handling, validation/model source binding, stale UC publication
  and validation display after selector changes. The reviewer found no remaining
  Critical/Important issue in those fixes, and did not independently rerun solvers.
- Full regression after these corrections and final coverage check: 130 tests passed. Startup laziness,
  scope/hash rejection, unchanged curated prices, UC ties, baseline disclosure,
  method pages, exact settlement cache and bounded native jobs are covered.

Terminology: use CHP nodal price; network-constrained UC and generation schedule;
energy market revenue; reported-cost lost-opportunity-cost (LOC) compensation;
actual operating cost; generator profit and profit increment. Base-case PTDF limits
are not an N−1 security-constrained UC model. The historical price_tolerance_usd
parameter bounds common-primal OBJECTIVE gaps in USD, not price error in USD/MWh;
the interface now separates this from price-path compression/projection tolerances.

Current published direction counts, per-map timing/residual summaries and baseline
comparisons are in exports/coverage.csv and coverage.json. Raw newly computed LP
witnesses and runtime settlements stay local under ignored results directories;
the published lightweight payloads retain their provenance hashes. Offline HTML
structure was regression-tested; this revision's visual/interactive browser QA
was performed on the localhost Streamlit app, not a new file-protocol browser run.

Final published inventory: all 150 IEEE30 scalar directions (6 all-day + 144 hourly),
all source-bound and independently validated; six all-day UC maps. Their 981
independent interior checks have maximum objective error 3.49246e-10 USD and
maximum selected complete-dual objective gap 5.58794e-9 USD. All 150 zero-adder
price arrays exactly match the original G1 all-day reference in this experiment;
no endpoint was rewritten to force agreement. IEEE118 G11 all-day remains included,
so the lazy catalog contains 151 scenarios. The curated offline HTML is about
10.50 MiB and remains limited to four selected scenarios.
