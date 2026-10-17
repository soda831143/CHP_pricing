# CHP Oracle Explorer — implementation scope

The dashboard is a research instrument, not a new pricing algorithm. Reuse the
existing compact selector, global UC model and unit self-schedule settlement.
The four published directions are the release scope; an unavailable direction
must never silently fall back to another generator or hour.

Visual direction: a quiet laboratory workbench, paper background `#F5F7F8`,
ink `#203442`, teal `#087E8B`, ochre `#BA7B25`, and muted slate `#68818E`.
Use system sans-serif with monospaced quotation/version labels. The distinguishing
element is a quotation ruler: price knots and physical UC boundaries share a
horizontal bid axis, with the current bid highlighted. Use the space for plots
and scope explanations rather than decorative metric walls.

Architecture: `data.py` is solver-free; `export.py` validates original witnesses
once; `service.py` performs explicitly requested UC/LOC and exact-key caching;
`app.py` is the local Streamlit workbench. `static.html` generates a self-contained
read-only demonstration, with neither a COPT dependency nor a public solve endpoint.

Reach of this change: new dashboard code, export data/manifest, dashboard tests,
usage documentation and a separate Q500 timing artifact. Existing algorithms,
paper figures, Q200 timing and user-modified IEEE118 workbook remain untouched.

Three independent capability levels are visible: P selected optimal CHP prices,
U feasible globally optimal physical execution, S direct reported-LOC settlement.
Prices are not asserted unique; profit samples are never interpolated. A UC tie
returns separate plans. A change in fixed model data invalidates live settlement.
SHA-256 records data integrity and provenance, not a digital signature.

The Q500 workload is fixed before measurement, run from a fresh persistent model,
and kept independent of the earlier Q200 stream. Do not extend Q to force a crossing.

## Interaction revision

Keep the laboratory palette and quotation ruler; avoid another decorative KPI wall.
The first screen answers one question: what changes when this generator changes
its offer? Show P/U/S as three distinct capability panels, then baseline/current/
additional profit for the strategic generator, with unavailable values explicitly
unknown. The requested and evaluated offer remain visible side by side.

Use a persistent page selector instead of eagerly rendering every tab. Shared unit,
bus and hour controls drive all views, and settlement-row selection updates those
same controls. A new case/generator/direction resets the observation context.
Bid-response heatmaps show space/time versus bid using the existing compact map;
they are rendering samples, not newly discovered mathematical regions.

Changes use red for positive differences and blue for negative differences, a
white zero centre, explicit bus/generator axes and separate USD versus USD/MWh
units. Retain Segoe UI for body/headings and Consolas for quotation/version data.
Long UC/LOC runs move into a bounded local child process with progress, cancel
and timeout, so a native solver call cannot freeze the UI. Results remain bound
to their original query; switching the screen never re-labels an old result.
