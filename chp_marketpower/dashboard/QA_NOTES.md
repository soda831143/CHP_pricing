# Release checks — 2026-10-17

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
